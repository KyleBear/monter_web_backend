"""
reward_rank 테이블 업데이트 스크립트
- reward_rank 테이블의 reward_id를 순회하면서
- keyword와 nvmid로 네이버 Open API를 사용하여
- product_url, 스토어명, product_name, product_id를 업데이트
"""
import logging
import sys
import os
import time
import re
from typing import Optional, Dict

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
from datetime import datetime

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
            
            try:
                # 네이버 오픈 API로 검색
                api_results = get_shopping_rank_with_ad_flag(
                    keyword,
                    display=display,
                    start=start,
                    filter=None
                )
                
                if not api_results:
                    logger.debug(f"페이지 {page}: 결과 없음, 검색 중단")
                    break
                
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
                
                # API 호출 간격 (너무 빠르게 호출하지 않도록)
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"페이지 {page} 검색 중 오류: {e}", exc_info=True)
                continue
        
        logger.warning(f"검색 결과에서 nvmid '{target_nvmid}'를 찾지 못했습니다. (최대 {max_pages}페이지 검색)")
        return None
        
    except Exception as e:
        logger.error(f"상품 정보 조회 중 오류: {e}", exc_info=True)
        return None


def update_reward_rank_by_api(start_id: Optional[int] = None, end_id: Optional[int] = None, delay: float = 0.5):
    """
    reward_rank 테이블을 순회하면서 네이버 Open API로 정보 업데이트
    
    Args:
        start_id: 시작 reward_id (None이면 전체)
        end_id: 종료 reward_id (None이면 전체)
        delay: API 호출 간 대기 시간 (초)
    
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
        
        logger.info(f"=" * 60)
        logger.info(f"reward_rank 테이블 업데이트 시작")
        logger.info(f"총 {stats['total']}개 레코드 처리 예정")
        if start_id or end_id:
            logger.info(f"reward_id 범위: {start_id or '시작'} ~ {end_id or '끝'}")
        logger.info(f"=" * 60)
        
        for idx, record in enumerate(records, 1):
            try:
                reward_id = record.reward_id
                keyword = record.keyword
                nvmid = record.nvmid
                
                logger.info(f"\n[{idx}/{stats['total']}] reward_id={reward_id} 처리 시작")
                logger.info(f"  - keyword: {keyword}")
                logger.info(f"  - nvmid: {nvmid}")
                
                # 네이버 Open API로 상품 정보 조회
                product_info = get_product_info_by_keyword_and_nvmid(keyword, nvmid)
                
                if product_info:
                    # 업데이트할 필드 확인
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
                    
                    # productid 업데이트 (추가)
                    if product_info.get('product_id'):
                        if record.productid != product_info['product_id']:
                            record.productid = product_info['product_id']
                            updated_fields.append('productid')
                    
                    if updated_fields:
                        record.updated_at = datetime.now()
                        db.commit()
                        stats['updated'] += 1
                        logger.info(f"  ✅ 업데이트 완료: {', '.join(updated_fields)}")
                    else:
                        stats['skipped'] += 1
                        logger.info(f"  ⏭️  변경사항 없음 (이미 최신 정보)")
                else:
                    stats['failed'] += 1
                    logger.warning(f"  ❌ 상품 정보 조회 실패")
                
                # API 호출 간 대기
                if idx < stats['total']:
                    time.sleep(delay)
                    
            except Exception as e:
                db.rollback()
                stats['failed'] += 1
                logger.error(f"  ❌ reward_id={record.reward_id} 처리 중 오류: {e}", exc_info=True)
                continue
        
        logger.info(f"\n" + "=" * 60)
        logger.info(f"업데이트 완료")
        logger.info(f"=" * 60)
        logger.info(f"전체: {stats['total']}개")
        logger.info(f"업데이트: {stats['updated']}개")
        logger.info(f"실패: {stats['failed']}개")
        logger.info(f"건너뜀: {stats['skipped']}개")
        logger.info(f"=" * 60)
        
        return stats
        
    except Exception as e:
        db.rollback()
        logger.error(f"업데이트 중 오류: {e}", exc_info=True)
        raise
    finally:
        db.close()


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description='reward_rank 테이블 업데이트 (네이버 Open API 사용)')
    parser.add_argument('--start-id', type=int, help='시작 reward_id')
    parser.add_argument('--end-id', type=int, help='종료 reward_id')
    parser.add_argument('--delay', type=float, default=0.5, help='API 호출 간 대기 시간 (초, 기본값: 0.5)')
    
    args = parser.parse_args()
    
    try:
        stats = update_reward_rank_by_api(
            start_id=args.start_id,
            end_id=args.end_id,
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
