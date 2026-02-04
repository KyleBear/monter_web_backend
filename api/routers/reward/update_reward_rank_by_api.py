"""
reward_rank 테이블 업데이트 스크립트
- reward_rank 테이블의 reward_id를 순회하면서
- keyword와 nvmid로 네이버 Open API를 사용하여
- product_url, 스토어명, product_name, product_id를 업데이트
- 비동기로 3개씩 배치 처리 (429 에러 방지)
- API 호출 간격: 1초, 배치 간 대기: 3초
- 429 에러 발생 시 자동 재시도 (exponential backoff)
"""
import logging
import sys
import os
import time
import re
import asyncio
import requests
from typing import Optional, Dict, List
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.insert(0, project_root)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 데이터베이스 및 모델 import
from database import SessionLocal
from models import RewardRank

# 네이버 Open API 함수 import
from api.routers.crol import get_shopping_rank_with_ad_flag


def get_product_info_by_keyword_and_nvmid(keyword: str, nvmid: str) -> Optional[Dict]:
    """
    키워드와 nvmid로 네이버 Open API를 사용하여 상품 정보 조회
    
    Args:
        keyword: 검색 키워드
        nvmid: 찾을 nvmid
    
    Returns:
        dict: {
            'product_url': str,
            'store_name': str,
            'product_name': str,
            'product_id': str  # 추가
        } 또는 None
    """
    if not keyword or not nvmid:
        return None
    
    try:
        target_nvmid = str(nvmid).strip()
        logger.info(f"키워드 '{keyword}'로 nvmid '{target_nvmid}' 검색 시작")
        
        # 여러 페이지 검색 (최대 1000개 결과)
        display = 100
        max_pages = 10
        
        for page in range(1, max_pages + 1):
            start = (page - 1) * 100 + 1  # 1, 101, 201, 301, ...
            
            # 재시도 로직 (429 에러 대응)
            max_retries = 3
            retry_count = 0
            api_results = None
            
            while retry_count < max_retries:
                try:
                    # 네이버 오픈 API로 검색
                    api_results = get_shopping_rank_with_ad_flag(
                        keyword,
                        display=display,
                        start=start,
                        filter=None
                    )
                    break  # 성공 시 루프 탈출
                    
                except requests.exceptions.HTTPError as e:
                    if e.response and e.response.status_code == 429:
                        retry_count += 1
                        wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8초
                        logger.warning(
                            f"페이지 {page} 429 Too Many Requests 에러 발생 "
                            f"(재시도 {retry_count}/{max_retries}). {wait_time}초 대기 후 재시도..."
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        raise
                except Exception as e:
                    if retry_count < max_retries - 1:
                        retry_count += 1
                        wait_time = 2 ** retry_count
                        logger.warning(
                            f"페이지 {page} 검색 중 오류 발생 (재시도 {retry_count}/{max_retries}): {e}"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        raise
            
            if not api_results:
                logger.debug(f"페이지 {page}: 결과 없음, 검색 중단")
                break
            
            try:
                logger.debug(f"페이지 {page} 검색 완료: {len(api_results)}개 결과 (start={start})")
                
                # 각 결과에서 nvmid 매칭 시도
                for item in api_results:
                    # 방법 1: productId가 nvmid일 수 있음
                    product_id = str(item.get("productId", "")).strip()
                    
                    # 방법 2: link URL에서 nvmid 및 product_id 추출
                    link = item.get("link", "")
                    nvmid_from_link = None
                    product_id_from_link = None
                    
                    if link:
                        # nvmid 추출 패턴
                        nvmid_patterns = [
                            r'nv_mid[=_](\d+)',  # nv_mid= 또는 nv_mid_
                            r'nvmid[=_](\d+)',   # nvmid= 또는 nvmid_
                            r'nv-mid[=_](\d+)',  # nv-mid= 또는 nv-mid_
                        ]
                        
                        # product_id 추출 패턴
                        # 스마트스토어: https://smartstore.naver.com/{쇼핑몰이름}/products/{product_id}
                        # 쇼핑몰: https://search.shopping.naver.com/catalog/{product_id}
                        product_id_patterns = [
                            r'(?:smartstore|brand)\.naver\.com/[^/]+/products/(\d+)',  # 스마트스토어/브랜드 스토어
                            r'search\.shopping\.naver\.com/catalog/(\d+)',  # 쇼핑몰
                            r'/products/(\d+)',  # /products/숫자 (일반 패턴)
                        ]
                        
                        for pattern in nvmid_patterns:
                            match = re.search(pattern, link, re.IGNORECASE)
                            if match:
                                nvmid_from_link = match.group(1)
                                break
                        
                        for pattern in product_id_patterns:
                            match = re.search(pattern, link, re.IGNORECASE)
                            if match:
                                product_id_from_link = match.group(1)
                                break
                        
                        # catalog 패턴도 nvmid로 사용 (쇼핑몰의 경우)
                        if not nvmid_from_link:
                            catalog_patterns = [
                                r'/catalog/(\d+)',   # /catalog/숫자
                                r'catalog/(\d+)',     # catalog/숫자
                            ]
                            for pattern in catalog_patterns:
                                match = re.search(pattern, link, re.IGNORECASE)
                                if match:
                                    nvmid_from_link = match.group(1)
                                    break
                    
                    # nvmid 매칭 (productId 또는 link에서 추출한 값과 비교)
                    if (product_id and product_id == target_nvmid) or \
                       (nvmid_from_link and nvmid_from_link == target_nvmid):
                        # 매칭 성공 - 상품 정보 반환
                        product_url = link if link else None
                        store_name = item.get("mall_name", "") or item.get("mallName", "")
                        product_name = item.get("product_name", "") or item.get("title", "")
                        
                        # HTML 태그 제거
                        if product_name:
                            product_name = re.sub(r'<[^>]+>', '', product_name).strip()
                        
                        logger.info(
                            f"nvmid 매칭 성공: productId={product_id}, "
                            f"link_nvmid={nvmid_from_link}, target={target_nvmid}, "
                            f"product_id={product_id_from_link}, "
                            f"product_name={product_name[:50]}... (페이지 {page})"
                        )
                        
                        return {
                            'product_url': product_url,
                            'store_name': store_name,
                            'product_name': product_name,
                            'product_id': product_id_from_link  # link에서 추출한 product_id
                        }
                
                # 마지막 페이지면 중단
                if len(api_results) < display:
                    logger.debug(f"페이지 {page}: 마지막 페이지 (결과 {len(api_results)}개 < {display}개)")
                    break
                
                # API 호출 간격 (너무 빠르게 호출하지 않도록) - 429 에러 방지를 위해 1초로 증가
                time.sleep(1.0)
                
            except Exception as e:
                logger.error(f"페이지 {page} 검색 중 오류: {e}", exc_info=True)
                continue
        
        logger.warning(f"검색 결과에서 nvmid '{target_nvmid}'를 찾지 못했습니다. (최대 {max_pages}페이지 검색)")
        return None
        
    except Exception as e:
        logger.error(f"상품 정보 조회 중 오류: {e}", exc_info=True)
        return None


async def process_single_record(record: RewardRank) -> Dict:
    """
    단일 레코드 처리 (비동기)
    
    Args:
        record: RewardRank 레코드
    
    Returns:
        dict: 처리 결과 {'success': bool, 'reward_id': int, 'updated': bool, 'error': str}
    """
    reward_id = record.reward_id
    keyword = record.keyword
    nvmid = record.nvmid
    
    result = {
        'success': False,
        'reward_id': reward_id,
        'updated': False,
        'error': None
    }
    
    try:
        # 별도 스레드에서 동기 함수 실행
        loop = asyncio.get_event_loop()
        product_info = await loop.run_in_executor(
            None,
            get_product_info_by_keyword_and_nvmid,
            keyword,
            nvmid
        )
        
        if product_info:
            # 데이터베이스 세션 생성 (스레드 안전)
            db = SessionLocal()
            try:
                # 레코드 다시 조회 (최신 상태)
                record = db.query(RewardRank).filter(RewardRank.reward_id == reward_id).first()
                if not record:
                    result['error'] = '레코드를 찾을 수 없습니다'
                    return result
                
                updated_fields = []
                
                # product_url 업데이트
                if product_info.get('product_url'):
                    if record.product_url != product_info['product_url']:
                        record.product_url = product_info['product_url']
                        updated_fields.append('product_url')
                
                # store_name 업데이트
                if product_info.get('store_name'):
                    if record.store_name != product_info['store_name']:
                        record.store_name = product_info['store_name']
                        updated_fields.append('store_name')
                
                # product_name 업데이트
                if product_info.get('product_name'):
                    if record.product_name != product_info['product_name']:
                        record.product_name = product_info['product_name']
                        updated_fields.append('product_name')
                
                # productid 업데이트
                if product_info.get('product_id'):
                    if record.productid != product_info['product_id']:
                        record.productid = product_info['product_id']
                        updated_fields.append('productid')
                
                if updated_fields:
                    record.updated_at = datetime.now()
                    db.commit()
                    result['updated'] = True
                    logger.info(f"  ✅ reward_id={reward_id} 업데이트 완료: {', '.join(updated_fields)}")
                else:
                    logger.info(f"  ⏭️  reward_id={reward_id} 변경사항 없음")
                
                result['success'] = True
                
            except Exception as e:
                db.rollback()
                result['error'] = str(e)
                logger.error(f"  ❌ reward_id={reward_id} DB 업데이트 중 오류: {e}", exc_info=True)
            finally:
                db.close()
        else:
            result['error'] = '상품 정보 조회 실패'
            logger.warning(f"  ❌ reward_id={reward_id} 상품 정보 조회 실패")
            
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"  ❌ reward_id={reward_id} 처리 중 오류: {e}", exc_info=True)
    
    return result


async def process_batch(records: List[RewardRank], batch_num: int, total_batches: int) -> Dict:
    """
    배치 단위로 레코드 처리 (10개씩)
    
    Args:
        records: 처리할 레코드 리스트
        batch_num: 현재 배치 번호
        total_batches: 전체 배치 개수
    
    Returns:
        dict: 통계 정보
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"배치 {batch_num}/{total_batches} 처리 시작 ({len(records)}개 레코드)")
    logger.info(f"{'='*60}")
    
    # 10개씩 병렬 처리
    tasks = [process_single_record(record) for record in records]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 결과 집계
    batch_stats = {
        'total': len(records),
        'success': 0,
        'updated': 0,
        'failed': 0
    }
    
    for idx, result in enumerate(results, 1):
        record = records[idx - 1]
        reward_id = record.reward_id
        
        if isinstance(result, Exception):
            logger.error(f"  ❌ reward_id={reward_id} 예외 발생: {result}", exc_info=True)
            batch_stats['failed'] += 1
        elif result.get('success'):
            batch_stats['success'] += 1
            if result.get('updated'):
                batch_stats['updated'] += 1
        else:
            batch_stats['failed'] += 1
            logger.warning(f"  ❌ reward_id={reward_id} 실패: {result.get('error', 'Unknown error')}")
    
    logger.info(f"\n배치 {batch_num}/{total_batches} 완료: 성공={batch_stats['success']}, 업데이트={batch_stats['updated']}, 실패={batch_stats['failed']}")
    
    return batch_stats


async def update_reward_rank_by_api_async(
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    batch_size: int = 3,  # 10 -> 3으로 감소 (429 에러 방지)
    delay: float = 3.0  # 0.5 -> 3.0으로 증가 (429 에러 방지)
) -> Dict:
    """
    reward_rank 테이블을 비동기로 배치 처리하여 업데이트
    
    Args:
        start_id: 시작 reward_id (None이면 전체)
        end_id: 종료 reward_id (None이면 전체)
        batch_size: 배치 크기 (기본값: 10)
        delay: 배치 간 대기 시간 (초)
    
    Returns:
        dict: 통계 정보
    """
    db = SessionLocal()
    stats = {
        'total': 0,
        'updated': 0,
        'failed': 0,
        'skipped': 0
    }
    
    try:
        # reward_rank 테이블에서 keyword와 nvmid가 있는 레코드 조회
        query = db.query(RewardRank).filter(
            RewardRank.keyword.isnot(None),
            RewardRank.keyword != '',
            RewardRank.nvmid.isnot(None),
            RewardRank.nvmid != ''
        )
        
        # reward_id 범위 필터링
        if start_id:
            query = query.filter(RewardRank.reward_id >= start_id)
        if end_id:
            query = query.filter(RewardRank.reward_id <= end_id)
        
        records = query.order_by(RewardRank.reward_id).all()
        stats['total'] = len(records)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"reward_rank 테이블 비동기 업데이트 시작")
        logger.info(f"총 {stats['total']}개 레코드 처리 예정")
        logger.info(f"배치 크기: {batch_size}개")
        if start_id or end_id:
            logger.info(f"reward_id 범위: {start_id or '시작'} ~ {end_id or '끝'}")
        logger.info(f"{'='*60}\n")
        
        # 배치로 나누기
        total_batches = (stats['total'] + batch_size - 1) // batch_size
        
        for batch_num in range(1, total_batches + 1):
            start_idx = (batch_num - 1) * batch_size
            end_idx = min(start_idx + batch_size, stats['total'])
            batch_records = records[start_idx:end_idx]
            
            # 배치 처리
            batch_stats = await process_batch(batch_records, batch_num, total_batches)
            
            # 통계 업데이트
            stats['updated'] += batch_stats['updated']
            stats['failed'] += batch_stats['failed']
            stats['skipped'] += (batch_stats['total'] - batch_stats['updated'] - batch_stats['failed'])
            
            # 배치 간 대기 (마지막 배치 제외)
            if batch_num < total_batches:
                await asyncio.sleep(delay)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"전체 업데이트 완료")
        logger.info(f"{'='*60}")
        logger.info(f"전체: {stats['total']}개")
        logger.info(f"업데이트: {stats['updated']}개")
        logger.info(f"실패: {stats['failed']}개")
        logger.info(f"건너뜀: {stats['skipped']}개")
        logger.info(f"{'='*60}")
        
        return stats
        
    except Exception as e:
        logger.error(f"업데이트 중 오류: {e}", exc_info=True)
        raise
    finally:
        db.close()


def update_reward_rank_by_api(
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    batch_size: int = 3,  # 10 -> 3으로 감소 (429 에러 방지)
    delay: float = 3.0  # 0.5 -> 3.0으로 증가 (429 에러 방지)
) -> Dict:
    """
    동기 래퍼 함수 (비동기 함수 호출)
    
    Args:
        start_id: 시작 reward_id
        end_id: 종료 reward_id
        batch_size: 배치 크기 (기본값: 10)
        delay: 배치 간 대기 시간 (초)
    
    Returns:
        dict: 통계 정보
    """
    return asyncio.run(update_reward_rank_by_api_async(
        start_id=start_id,
        end_id=end_id,
        batch_size=batch_size,
        delay=delay
    ))


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description='reward_rank 테이블 업데이트 (네이버 Open API 사용, 비동기 배치 처리)')
    parser.add_argument('--start-id', type=int, help='시작 reward_id')
    parser.add_argument('--end-id', type=int, help='종료 reward_id')
    parser.add_argument('--batch-size', type=int, default=3, help='배치 크기 (기본값: 3, 429 에러 방지)')
    parser.add_argument('--delay', type=float, default=3.0, help='배치 간 대기 시간 (초, 기본값: 3.0, 429 에러 방지)')
    
    args = parser.parse_args()
    
    try:
        stats = update_reward_rank_by_api(
            start_id=args.start_id,
            end_id=args.end_id,
            batch_size=args.batch_size,
            delay=args.delay
        )
        
        sys.exit(0)
        
    except KeyboardInterrupt:
        logger.info("\n[중단] 사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
