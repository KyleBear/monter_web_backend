"""
리워드 링크 관리 API 라우터
- 짧은 링크 생성 및 관리
- 키워드 조합 관리
- 랜덤 리다이렉트
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import Optional, List
from database import get_db, SessionLocal
from models import RewardLink, RewardLinkKeyword, UsersAdmin, RandomAcq, RandomAckeyAcq
from utils.auth_helpers import get_current_user
from datetime import datetime
from typing import Tuple
import random
import string
import logging
import sys
import os
import threading
import time

# reward_keysearch 모듈 import
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from reward_keysearch import create_missing_keywords_and_search_url
from sellution_rank3 import BrowserPool

router = APIRouter()
logger = logging.getLogger(__name__)

# ✅ RandomAcq 데이터 캐시 (5분 TTL)
_random_acq_cache = {
    'acq_words': [],
    'adj_words': [],
    'last_update': 0,
    'cache_ttl': 300,  # 5분
    'lock': threading.Lock()
}

# ✅ 키워드 조회 캐시 (short_code별, 5분 TTL)
_keywords_cache = {
    'data': {},  # {short_code: [keywords_list]}
    'last_update': {},  # {short_code: timestamp}
    'cache_ttl': 300,  # 5분
    'lock': threading.Lock()
}

def get_cached_keywords(short_code: str, db: Session) -> List[RewardLinkKeyword]:
    """
    캐시된 키워드 조회 (short_code별, 5분 TTL) - 락 최적화
    Double-checked locking 패턴으로 락 경합 최소화
    """
    current_time = time.time()
    
    # ✅ 1단계: 락 없이 캐시 유효성 확인
    if (short_code in _keywords_cache['data'] and 
        short_code in _keywords_cache['last_update'] and
        current_time - _keywords_cache['last_update'][short_code] <= _keywords_cache['cache_ttl']):
        # 캐시가 유효하면 바로 반환 (락 없이!)
        return _keywords_cache['data'][short_code]
    
    # ✅ 2단계: 캐시 만료 시에만 락 잡고 갱신
    with _keywords_cache['lock']:
        # Double-check: 다른 스레드가 이미 갱신했을 수 있음
        if (short_code in _keywords_cache['data'] and 
            short_code in _keywords_cache['last_update'] and
            current_time - _keywords_cache['last_update'][short_code] <= _keywords_cache['cache_ttl']):
            return _keywords_cache['data'][short_code]
        
        # 캐시 갱신 필요 - DB 조회
        try:
            keywords = db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.short_code == short_code,
                RewardLinkKeyword.query_keyword.isnot(None),
                RewardLinkKeyword.query_keyword != ''
            ).order_by(RewardLinkKeyword.keyword_id).all()
            
            # 캐시에 저장
            _keywords_cache['data'][short_code] = keywords
            _keywords_cache['last_update'][short_code] = current_time
            
            logger.debug(f"[키워드 캐시] 갱신 완료: short_code={short_code}, 키워드 수={len(keywords)}")
        
        except Exception as e:
            logger.error(f"[키워드 캐시] 갱신 오류: {e}", exc_info=True)
            # 오류 시 빈 리스트 반환
            _keywords_cache['data'][short_code] = []
            _keywords_cache['last_update'][short_code] = current_time
    
    return _keywords_cache['data'].get(short_code, [])


def _get_cached_random_acq_data(db: Session) -> Tuple[list, list]:
    """
    캐시된 RandomAcq 데이터 반환 (5분 TTL) - 락 최적화
    Double-checked locking 패턴으로 락 경합 최소화
    """
    current_time = time.time()
    
    # ✅ 1단계: 락 없이 캐시 유효성 확인 (대부분의 경우 여기서 반환)
    if (_random_acq_cache['last_update'] > 0 and 
        current_time - _random_acq_cache['last_update'] <= _random_acq_cache['cache_ttl'] and
        _random_acq_cache['acq_words'] and 
        _random_acq_cache['adj_words']):
        # 캐시가 유효하면 바로 반환 (락 없이!)
        return _random_acq_cache['acq_words'], _random_acq_cache['adj_words']
    
    # ✅ 2단계: 캐시 만료 시에만 락 잡고 갱신
    with _random_acq_cache['lock']:
        # Double-check: 다른 스레드가 이미 갱신했을 수 있음
        if (current_time - _random_acq_cache['last_update'] <= _random_acq_cache['cache_ttl'] and
            _random_acq_cache['acq_words'] and 
            _random_acq_cache['adj_words']):
            return _random_acq_cache['acq_words'], _random_acq_cache['adj_words']
        
        # 캐시 갱신 필요
        try:
            # ✅ DISTINCT로 중복 제거하여 조회 (한 번만)
            acq_words = db.query(RandomAcq.acq_word).filter(
                RandomAcq.acq_word.isnot(None),
                RandomAcq.acq_word != ''
            ).distinct().all()
            
            adj_words = db.query(RandomAcq.adj_word).filter(
                RandomAcq.adj_word.isnot(None),
                RandomAcq.adj_word != ''
            ).distinct().all()
            
            _random_acq_cache['acq_words'] = [w[0] for w in acq_words if w[0]]
            _random_acq_cache['adj_words'] = [w[0] for w in adj_words if w[0]]
            _random_acq_cache['last_update'] = current_time
            
            logger.debug(f"[acq 캐시] 갱신 완료: acq_words={len(_random_acq_cache['acq_words'])}, adj_words={len(_random_acq_cache['adj_words'])}")
        
        except Exception as e:
            logger.error(f"[acq 캐시] 갱신 오류: {e}", exc_info=True)
            # 기본값 설정
            if not _random_acq_cache['acq_words']:
                _random_acq_cache['acq_words'] = ['상품']
            if not _random_acq_cache['adj_words']:
                _random_acq_cache['adj_words'] = ['']
    
    return _random_acq_cache['acq_words'], _random_acq_cache['adj_words']


# Admin 권한 체크 함수
def check_admin_permission(current_user: dict, db: Session):
    """admin 권한 체크"""
    username = current_user.get("username")
    user = db.query(UsersAdmin).filter(UsersAdmin.username == username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다."
        )
    
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다."
        )
    
    return user


# ==================== Pydantic 모델 ====================

class KeywordCombination(BaseModel):
    # 프론트엔드 호환성을 위해 두 가지 형식 모두 지원
    query_keyword: Optional[str] = None
    acq_keyword: Optional[str] = None
    query: Optional[str] = None  # 프론트엔드 형식
    acq: Optional[str] = None    # 프론트엔드 형식
    
    def get_query(self) -> str:
        """query_keyword 또는 query 반환"""
        return self.query_keyword or self.query or ""
    
    def get_acq(self) -> str:
        """acq_keyword 또는 acq 반환"""
        return self.acq_keyword or self.acq or ""


class RewardLinkCreate(BaseModel):
    product_name: Optional[str] = None
    nvmid: Optional[str] = None  # 네이버 상품 ID
    short_link: Optional[str] = None  # 프론트엔드에서 생성한 링크 (선택사항)
    keywords: List[KeywordCombination] = []
    query_list: Optional[List[str]] = None  # query 키워드 리스트


class ProductItem(BaseModel):
    """상품 정보 아이템"""
    product_name: str
    nvmid: str  # 네이버 상품 ID


class RewardLinkBatchCreate(BaseModel):
    """다량 링크 생성 요청 모델"""
    products: Optional[List[ProductItem]] = None  # 다량의 상품 정보
    links: Optional[List[ProductItem]] = None  # 프론트엔드 호환성 (links 필드)
    
    def get_products(self) -> List[ProductItem]:
        """products 또는 links 중 하나를 반환"""
        if self.products:
            return self.products
        elif self.links:
            return self.links
        else:
            return []


class RewardLinkUpdate(BaseModel):
    product_name: Optional[str] = None
    keywords: Optional[List[KeywordCombination]] = None


class KeywordAdd(BaseModel):
    query_keyword: Optional[str] = None
    acq_keyword: Optional[str] = None
    query: Optional[str] = None  # 프론트엔드 형식
    acq: Optional[str] = None    # 프론트엔드 형식
    
    def get_query(self) -> str:
        """query_keyword 또는 query 반환"""
        return self.query_keyword or self.query or ""
    
    def get_acq(self) -> str:
        """acq_keyword 또는 acq 반환"""
        return self.acq_keyword or self.acq or ""


class KeywordBatchDelete(BaseModel):
    """배치 삭제 요청 모델"""
    keyword_ids: List[int]  # 삭제할 keyword_id 리스트


class KeywordBatchItem(BaseModel):
    """배치 수정용 키워드 아이템"""
    keyword_id: int  # 필수: 수정할 keyword_id
    query_keyword: Optional[str] = None  # 선택: query 키워드 (없으면 수정 안 함)
    acq_keyword: Optional[str] = None  # 선택: acq 키워드 (없으면 수정 안 함)


class KeywordBatchUpdate(BaseModel):
    """배치 수정 요청 모델"""
    keywords: List[KeywordBatchItem]  # 수정할 키워드 리스트


# ==================== 유틸리티 함수 ====================

def generate_short_code(length: int = 10) -> str:
    """랜덤 짧은 코드 생성 (영문숫자)"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_acq_from_random_table(db: Session) -> str:
    """
    random_acq 테이블에서 acq_word와 adj_word를 랜덤으로 선택하여 acq 생성
    성능 최적화: 캐싱 사용 (5분 TTL)
    
    Args:
        db: DB 세션
    
    Returns:
        str: 생성된 acq (acq_word + adj_word 형식)
    """
    try:
        # ✅ 캐시에서 데이터 가져오기
        acq_words, adj_words = _get_cached_random_acq_data(db)
        
        if not acq_words or not adj_words:
            logger.warning("[acq 생성] random_acq 테이블에 데이터가 없습니다. 기본값 사용.")
            return "상품"
        
        # ✅ 메모리에서 랜덤 선택 (매우 빠름)
        selected_acq_word = random.choice(acq_words)
        selected_adj_word = random.choice(adj_words)
        
        # acq_word + adj_word 형식으로 조합
        acq = f"{selected_acq_word}{selected_adj_word}"
        
        # ✅ 로깅 레벨을 DEBUG로 변경 (성능 향상)
        logger.debug(f"[acq 생성] '{selected_acq_word}' + '{selected_adj_word}' = '{acq}'")
        return acq
        
    except Exception as e:
        logger.error(f"[acq 생성] 오류: {e}", exc_info=True)
        return "상품"


def generate_random_ackey(length: int = 8) -> str:
    """랜덤 ackey 생성 (소문자 영문숫자 8글자)"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def get_random_ackey_from_table(db: Session) -> Optional[str]:
    """
    random_ackey_acq 테이블에서 random_key_queue_id <= 255인 레코드 중 랜덤으로 ackey 가져오기
    
    Args:
        db: DB 세션
    
    Returns:
        str or None: ackey 값 (없으면 None)
    """
    try:
        # random_key_queue_id <= 255인 레코드 중 랜덤으로 선택
        records = db.query(RandomAckeyAcq).filter(
            RandomAckeyAcq.random_key_queue_id <= 255,
            RandomAckeyAcq.ackey.isnot(None),
            RandomAckeyAcq.ackey != ''
        ).all()
        
        if not records:
            logger.warning("random_ackey_acq 테이블에 random_key_queue_id <= 255인 레코드가 없습니다.")
            return None
        
        # 랜덤으로 하나 선택
        selected = random.choice(records)
        ackey = selected.ackey
        
        logger.debug(f"[ackey 조회] random_key_queue_id={selected.random_key_queue_id}, ackey={ackey}")
        
        return ackey
        
    except Exception as e:
        logger.error(f"[ackey 조회] 오류: {e}", exc_info=True)
        return None


# ==================== API 엔드포인트 ====================

@router.get("/links")
async def get_all_links(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    모든 링크 목록 조회 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        links = db.query(RewardLink).order_by(desc(RewardLink.created_at)).all()
        
        result = []
        for link in links:
            # 키워드 조합 조회 (keyword_id 순서로 정렬)
            keywords = db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.link_id == link.link_id
            ).order_by(RewardLinkKeyword.keyword_id).all()
            
            keyword_list = [
                {
                    "keyword_id": kw.keyword_id,
                    "query_keyword": kw.query_keyword,
                    "acq_keyword": kw.acq_keyword
                }
                for kw in keywords
            ]
            
            result.append({
                "link_id": link.link_id,
                "short_code": link.short_code,
                "product_name": link.product_name or "",
                "reward_link": link.reward_link or "",  # reward_link 포함
                "keyword_count": len(keyword_list),
                "keywords": keyword_list,
                "created_at": link.created_at.isoformat() if link.created_at else None,
                "updated_at": link.updated_at.isoformat() if link.updated_at else None,
            })
        
        return {
            "success": True,
            "data": {
                "links": result
            }
        }
    
    except Exception as e:
        logger.error(f"링크 목록 조회 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/links/{short_code}")
async def get_link_by_code(
    short_code: str,
    db: Session = Depends(get_db)
):
    """
    짧은 코드로 링크 정보 조회 (공개, 리다이렉트용)
    """
    try:
        link = db.query(RewardLink).filter(RewardLink.short_code == short_code).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {short_code}"
            )
        
        # 키워드 조합 조회 (keyword_id 순서로 정렬)
        keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link.link_id
        ).order_by(RewardLinkKeyword.keyword_id).all()
        
        if not keywords:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="등록된 키워드가 없습니다."
            )
        
        keyword_list = [
            {
                "query_keyword": kw.query_keyword,
                "acq_keyword": kw.acq_keyword
            }
            for kw in keywords
        ]
        
        return {
            "success": True,
            "data": {
                "link": {
                    "link_id": link.link_id,
                    "short_code": link.short_code,
                    "product_name": link.product_name or "",
                    "reward_link": link.reward_link or "",  # reward_link 포함
                    "keywords": keyword_list
                }
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"링크 조회 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/redirect/{short_code}")
async def redirect_to_naver(
    short_code: str,
    db: Session = Depends(get_db)
):
    """
    짧은 링크로 접속 시 랜덤 네이버 URL로 리다이렉트
    short_code에 해당하는 RewardLinkKeyword에서 query_keyword를 랜덤으로 선택하여
    새로운 search_url을 생성하여 리다이렉트
    """
    t1 = time.time()
    
    try:
        # 1. 키워드 조회 (캐시 사용)
        keywords = get_cached_keywords(short_code, db)
        
        t2 = time.time()
        logger.info(f"[리다이렉트 성능] 키워드 조회: {(t2-t1)*1000:.2f}ms")
        
        if not keywords:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"키워드를 찾을 수 없습니다: {short_code}"
            )
        
        # 랜덤으로 하나의 키워드 선택
        random_keyword = random.choice(keywords)
        query_keyword = random_keyword.query_keyword
        
        # 2. ACQ 생성 (기존대로 random_acq 테이블에서)
        acq = generate_acq_from_random_table(db)
        t3 = time.time()
        logger.info(f"[리다이렉트 성능] ACQ 생성: {(t3-t2)*1000:.2f}ms")
        
        # 3. ACKEY 생성 (random_ackey_acq 테이블에서 가져오기)
        ackey = get_random_ackey_from_table(db)
        
        # ackey가 없으면 랜덤 생성 (fallback)
        if not ackey:
            ackey = generate_random_ackey(8)
            logger.warning("random_ackey_acq 테이블에서 ackey를 가져오지 못해 랜덤 생성")
        
        acr = random.randint(1, 10)
        
        naver_url = (
            f"https://m.search.naver.com/search.naver?"
            f"sm=mtp_sug.top&"
            f"where=m&"
            f"query={query_keyword}&"
            f"ackey={ackey}&"
            f"acq={acq}&"
            f"acr={acr}&"
            f"qdt=0"
        )
        
        t4 = time.time()
        logger.info(f"[리다이렉트 성능] URL 생성: {(t4-t3)*1000:.2f}ms")
        logger.info(f"[리다이렉트 성능] 전체: {(t4-t1)*1000:.2f}ms")
        logger.info(f"[리다이렉트] short_code={short_code}, 선택된 keyword_id={random_keyword.keyword_id}, query='{query_keyword}', 생성된 URL: {naver_url[:100]}...")
        
        # 리다이렉트
        return RedirectResponse(url=naver_url, status_code=302)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"리다이렉트 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"리다이렉트 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/links")
async def create_link(
    link_data: RewardLinkCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    새 링크 생성 (관리자용)
    query_list가 제공되면 모든 조합을 생성
    keywords가 제공되면 그대로 사용
    acq는 random_acq 테이블에서 랜덤으로 생성
    각 조합마다 별도의 link_id를 생성하되, 모두 같은 short_code를 사용
    """
    check_admin_permission(current_user, db)
    
    try:
        # query_list만 사용 (acq는 random_acq 테이블에서 생성)
        keyword_combinations = []
        
        if link_data.query_list:
            for query in link_data.query_list:
                if not query or not query.strip():
                    continue
                keyword_combinations.append({
                    "query": query.strip()
                })
            logger.info(f"query_list 개수: {len(keyword_combinations)}")
        elif link_data.keywords:
            # keywords가 제공되면 그대로 사용
            for kw in link_data.keywords:
                query = kw.get_query()
                if query:
                    keyword_combinations.append({
                        "query": query
                    })
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_list 또는 keywords를 제공해주세요."
            )
        
        if len(keyword_combinations) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효한 키워드 조합이 없습니다."
            )
        
        # 입력 데이터 로깅
        logger.info(f"링크 생성 요청: product_name={link_data.product_name}, 조합 개수={len(keyword_combinations)}")
        for idx, comb in enumerate(keyword_combinations):
            logger.info(f"  조합[{idx}]: query={comb['query']}")
        
        # 하나의 short_code 생성 (모든 레코드가 공유)
        max_attempts = 10
        short_code = None
        
        for _ in range(max_attempts):
            candidate = generate_short_code(10)
            existing = db.query(RewardLink).filter(RewardLink.short_code == candidate).first()
            if not existing:
                short_code = candidate
                break
        
        if not short_code:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="짧은 코드 생성에 실패했습니다. 다시 시도해주세요."
            )
        
        logger.info(f"생성된 short_code (공통): {short_code}")
        
        # 각 키워드 조합마다 별도의 reward_link 레코드 생성 (모두 같은 short_code 사용)
        created_links = []
        saved_keywords = []
        failed_combinations = []
        
        for idx, comb in enumerate(keyword_combinations):
            query = comb['query']
            
            # random_acq 테이블에서 acq 생성
            acq = generate_acq_from_random_table(db)
            
            logger.info(f"조합[{idx}] 처리 시작: query='{query}', acq='{acq}'")
            
            try:
                # 각 조합마다 네이버 검색 URL 생성 (reward_link에 저장)
                ackey = generate_random_ackey(8)
                acr = random.randint(1, 10)
                
                naver_url = (
                    f"https://m.search.naver.com/search.naver?"
                    f"sm=mtp_sug.top&"
                    f"where=m&"
                    f"query={query}&"
                    f"ackey={ackey}&"
                    f"acq={acq}&"
                    f"acr={acr}&"
                    f"qdt=0"
                )
                
                logger.info(f"조합[{idx}] - 생성된 네이버 URL: {naver_url}")
                
                # 각 키워드 조합마다 별도의 reward_link 레코드 생성 (같은 short_code 사용)
                new_link = RewardLink(
                    short_code=short_code,  # 모두 같은 short_code 사용
                    product_name=link_data.product_name,
                    nvmid=link_data.nvmid,  # nvmid 추가
                    reward_link=naver_url  # 네이버 검색 URL 저장
                )
                db.add(new_link)
                db.flush()  # link_id를 얻기 위해 flush
                
                logger.info(f"조합[{idx}] - 생성된 link_id: {new_link.link_id}, short_code: {short_code}, reward_link: {naver_url}")
                
                # 각 reward_link에 하나의 키워드 조합만 저장
                keyword = RewardLinkKeyword(
                    link_id=new_link.link_id,
                    short_code=short_code,  # 각각 다른 link_id
                    query_keyword=query,
                    acq_keyword=acq
                )
                db.add(keyword)
                db.flush()  # keyword_id를 얻기 위해 flush
                
                logger.info(f"조합[{idx}] 저장 완료: link_id={new_link.link_id}, keyword_id={keyword.keyword_id}, query='{query}', acq='{acq}'")
                
                created_links.append({
                    "link_id": new_link.link_id,
                    "short_code": new_link.short_code,  # 모두 같은 short_code
                    "reward_link": new_link.reward_link,  # 각각 다른 네이버 URL
                    "keyword_id": keyword.keyword_id,
                    "query": query,
                    "acq": acq
                })
                
                saved_keywords.append({
                    "link_id": new_link.link_id,
                    "query": query,
                    "acq": acq
                })
            except Exception as e:
                logger.error(f"조합[{idx}] 저장 중 오류 발생: query='{query}', acq='{acq}', 오류: {e}", exc_info=True)
                failed_combinations.append({
                    "index": idx,
                    "query": query,
                    "error": str(e)
                })
                # 개별 레코드 저장 실패 시에도 계속 진행
                continue
        
        if len(created_links) == 0:
            db.rollback()
            logger.error("저장된 링크가 없습니다. 롤백합니다.")
            error_detail = "링크 생성에 실패했습니다."
            if failed_combinations:
                error_detail += f" 실패한 조합: {failed_combinations}"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail
            )
        
        # 일부 조합이 실패했어도 성공한 레코드는 커밋
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"커밋 중 오류 발생: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"링크 저장 중 오류가 발생했습니다: {str(e)}"
            )
        
        logger.info(f"링크 생성 완료: 총 {len(created_links)}개의 링크 생성됨 (모두 같은 short_code: {short_code})")
        if failed_combinations:
            logger.warning(f"일부 조합 저장 실패: {len(failed_combinations)}개 실패")
            for failed in failed_combinations:
                logger.warning(f"  실패한 조합: query='{failed['query']}', 오류: {failed['error']}")
        
        for link_info in created_links:
            logger.info(f"  - link_id={link_info['link_id']}, short_code={link_info['short_code']}, reward_link={link_info['reward_link']}, query='{link_info['query']}', acq='{link_info['acq']}'")
        
        response_message = f"{len(created_links)}개의 링크가 생성되었습니다."
        if failed_combinations:
            response_message += f" ({len(failed_combinations)}개 조합 저장 실패)"
        
        return {
            "success": True,
            "message": response_message,
            "data": {
                "short_code": short_code,  # 공통 short_code 반환
                "created_count": len(created_links),
                "failed_count": len(failed_combinations),
                "links": created_links,  # 생성된 모든 링크 정보 (같은 short_code, 각각 다른 네이버 URL)
                "keywords": saved_keywords,  # 저장된 키워드 목록
                "failed_combinations": failed_combinations if failed_combinations else []  # 실패한 조합 목록
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"링크 생성 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 생성 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/links/batch")
async def create_links_batch(
    link_data: RewardLinkBatchCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    다량 링크 생성 (관리자용)
    products 또는 links 리스트의 각 상품마다 링크와 키워드를 생성
    reward_keysearch의 create_missing_keywords_and_search_url 함수를 사용하여
    product_name으로 키워드 조합을 생성하고 통검 노출된 키워드만 저장
    """
    check_admin_permission(current_user, db)
    
    try:
        # products 또는 links 가져오기
        products = link_data.get_products()
        
        # products 검증
        if not products or len(products) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="상품 정보를 제공해주세요. (products 또는 links 필드)"
            )
        
        # 입력 데이터 로깅
        logger.info(f"[배치 링크 생성] 상품 개수={len(products)}")
        
        # BrowserPool 생성 (reward_keysearch에서 사용)
        browser_pool = BrowserPool(pool_size=10)
        browser_pool.initialize()
        
        # 전체 결과 저장
        all_created_links = []
        all_failed_products = []
        
        # 각 상품마다 처리
        for product_idx, product in enumerate(products):
            try:
                logger.info(f"[배치 링크 생성] 상품[{product_idx}] 처리 시작: product_name='{product.product_name}', nvmid='{product.nvmid}'")
                
                # product_name과 nvmid 검증
                if not product.product_name or not product.product_name.strip():
                    logger.warning(f"[배치 링크 생성] 상품[{product_idx}] product_name이 없습니다.")
                    all_failed_products.append({
                        "product_index": product_idx,
                        "product_name": product.product_name,
                        "nvmid": product.nvmid,
                        "error": "product_name이 없습니다."
                    })
                    continue
                
                if not product.nvmid or not product.nvmid.strip():
                    logger.warning(f"[배치 링크 생성] 상품[{product_idx}] nvmid가 없습니다.")
                    all_failed_products.append({
                        "product_index": product_idx,
                        "product_name": product.product_name,
                        "nvmid": product.nvmid,
                        "error": "nvmid가 없습니다."
                    })
                    continue
                
                # 각 상품마다 별도의 short_code 생성
                max_attempts = 10
                short_code = None
                
                for _ in range(max_attempts):
                    candidate = generate_short_code(10)
                    existing = db.query(RewardLink).filter(RewardLink.short_code == candidate).first()
                    if not existing:
                        short_code = candidate
                        break
                
                if not short_code:
                    logger.error(f"[배치 링크 생성] 상품[{product_idx}] short_code 생성 실패")
                    all_failed_products.append({
                        "product_index": product_idx,
                        "product_name": product.product_name,
                        "nvmid": product.nvmid,
                        "error": "short_code 생성 실패"
                    })
                    continue
                
                logger.info(f"[배치 링크 생성] 상품[{product_idx}] 생성된 short_code: {short_code}")
                
                # RewardLink 생성 (product_name과 nvmid로)
                new_link = RewardLink(
                    short_code=short_code,
                    product_name=product.product_name.strip(),
                    nvmid=product.nvmid.strip(),
                    reward_link=None  # reward_keysearch에서 생성
                )
                db.add(new_link)
                db.flush()  # link_id를 얻기 위해 flush
                db.commit()  # commit하여 link_id 확보
                
                logger.info(f"[배치 링크 생성] 상품[{product_idx}] RewardLink 생성 완료: link_id={new_link.link_id}, short_code={short_code}")
                
                # reward_keysearch의 create_missing_keywords_and_search_url 함수 호출
                # 새로운 DB 세션 생성 (reward_keysearch에서 사용)
                new_db = SessionLocal()
                try:
                    create_result = create_missing_keywords_and_search_url(
                        link_id=new_link.link_id,
                        db=new_db,
                        browser_pool=browser_pool
                    )
                    
                    if not create_result['success']:
                        logger.warning(f"[배치 링크 생성] 상품[{product_idx}] 키워드 생성 실패: {create_result['message']}")
                        all_failed_products.append({
                            "product_index": product_idx,
                            "product_name": product.product_name,
                            "nvmid": product.nvmid,
                            "error": create_result['message']
                        })
                        continue
                    
                    logger.info(f"[배치 링크 생성] 상품[{product_idx}] 키워드 생성 완료: {create_result['message']}")
                    
                    # 생성된 키워드 조회
                    keywords = new_db.query(RewardLinkKeyword).filter(
                        RewardLinkKeyword.link_id == new_link.link_id
                    ).order_by(RewardLinkKeyword.keyword_id).all()
                    
                    # 업데이트된 reward_link 조회
                    updated_link = new_db.query(RewardLink).filter(
                        RewardLink.link_id == new_link.link_id
                    ).first()
                    
                    created_links = []
                    for keyword in keywords:
                        created_links.append({
                            "link_id": new_link.link_id,
                            "short_code": short_code,
                            "reward_link": updated_link.reward_link if updated_link else None,
                            "keyword_id": keyword.keyword_id,
                            "query": keyword.query_keyword,
                            "acq": keyword.acq_keyword
                        })
                    
                    # 상품별 결과 저장
                    all_created_links.append({
                        "product_index": product_idx,
                        "product_name": product.product_name,
                        "nvmid": product.nvmid,
                        "short_code": short_code,
                        "link_id": new_link.link_id,
                        "created_keywords": create_result['created_keywords'],
                        "created_search_url": create_result['created_search_url'],
                        "message": create_result['message'],
                        "links": created_links
                    })
                    
                finally:
                    new_db.close()
                
            except Exception as e:
                logger.error(f"[배치 링크 생성] 상품[{product_idx}] 처리 중 오류: product_name='{product.product_name}', nvmid='{product.nvmid}', 오류: {e}", exc_info=True)
                all_failed_products.append({
                    "product_index": product_idx,
                    "product_name": product.product_name,
                    "nvmid": product.nvmid,
                    "error": str(e)
                })
                continue
        
        # BrowserPool 종료
        try:
            browser_pool.cleanup()
        except Exception as e:
            logger.warning(f"[배치 링크 생성] BrowserPool cleanup 중 오류: {e}")
        
        # 전체 통계 계산
        total_created_keywords = sum(item["created_keywords"] for item in all_created_links)
        total_created_links_count = len(all_created_links)
        
        logger.info(f"[배치 링크 생성] 총 {len(products)}개 상품, {total_created_links_count}개 링크 생성 완료, {total_created_keywords}개 키워드 생성")
        
        return {
            "success": True,
            "message": f"{len(products)}개 상품에 대해 {total_created_links_count}개 링크, {total_created_keywords}개 키워드가 생성되었습니다.",
            "data": {
                "total_products": len(products),
                "total_created_links": total_created_links_count,
                "total_created_keywords": total_created_keywords,
                "total_failed": len(all_failed_products),
                "products": all_created_links,
                "failed_products": all_failed_products if all_failed_products else []
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[배치 링크 생성] 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"배치 링크 생성 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/links/{link_id}/keywords/{keyword_id}")
async def update_keyword(
    link_id: int,
    keyword_id: int,
    keyword_data: KeywordAdd,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 조합 수정 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        # 링크 확인
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        # 키워드 조회
        keyword = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.keyword_id == keyword_id,
            RewardLinkKeyword.link_id == link_id
        ).first()
        
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"키워드를 찾을 수 없습니다: {keyword_id}"
            )
        
        query = keyword_data.get_query()
        
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query 키워드를 입력해주세요."
            )
        
        # random_acq 테이블에서 acq 생성
        acq = generate_acq_from_random_table(db)
        
        # 키워드 수정
        keyword.query_keyword = query
        keyword.acq_keyword = acq
        keyword.short_code = link.short_code  # short_code도 업데이트
        keyword.updated_at = datetime.now()
        
        db.commit()
        db.refresh(keyword)
        
        return {
            "success": True,
            "message": "키워드가 수정되었습니다.",
            "data": {
                "keyword_id": keyword.keyword_id,
                "query_keyword": keyword.query_keyword,
                "acq_keyword": keyword.acq_keyword,
                "short_code": keyword.short_code
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"키워드 수정 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"키워드 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/links/{link_id}")
async def update_link(
    link_id: int,
    link_data: RewardLinkUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    링크 정보 수정 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        # 상품명 업데이트
        if link_data.product_name is not None:
            link.product_name = link_data.product_name
            link.updated_at = datetime.now()
        
        # 키워드 조합 업데이트
        if link_data.keywords is not None:
            # 기존 키워드 삭제
            db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.link_id == link_id
            ).delete()
            
            # 새 키워드 추가
            for kw in link_data.keywords:
                query = kw.get_query()
                
                if not query:
                    continue  # 빈 키워드는 건너뛰기
                
                # random_acq 테이블에서 acq 생성
                acq = generate_acq_from_random_table(db)
                
                keyword = RewardLinkKeyword(
                    link_id=link_id,
                    short_code=link.short_code,  # short_code 추가
                    query_keyword=query,
                    acq_keyword=acq
                )
                db.add(keyword)
        
        db.commit()
        db.refresh(link)
        
        # 업데이트된 키워드 조합 조회 (keyword_id 순서로 정렬)
        keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link_id
        ).order_by(RewardLinkKeyword.keyword_id).all()
        
        keyword_list = [
            {
                "keyword_id": kw.keyword_id,
                "query_keyword": kw.query_keyword,
                "acq_keyword": kw.acq_keyword
            }
            for kw in keywords
        ]
        
        return {
            "success": True,
            "message": "링크가 수정되었습니다.",
            "data": {
                "link_id": link.link_id,
                "short_code": link.short_code,
                "product_name": link.product_name,
                "reward_link": link.reward_link or "",  # reward_link 포함
                "keywords": keyword_list
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"링크 수정 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/links/{link_id}/keywords")
async def add_keyword(
    link_id: int,
    keyword_data: KeywordAdd,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 조합 추가 (관리자용)
    키워드 추가 시 RewardLink 테이블에도 해당 search_url을 추가
    """
    check_admin_permission(current_user, db)
    
    try:
        # 기존 link 조회하여 product_name, short_code, nvmid 가져오기
        existing_link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not existing_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        query = keyword_data.get_query()
        
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query 키워드를 입력해주세요."
            )
        
        # generate_search_url 함수 import
        from api.routers.keyword_search_api2 import generate_search_url
        
        # 키워드로 search_url 생성
        search_url = generate_search_url(query, db)
        
        # random_acq 테이블에서 acq 생성
        acq = generate_acq_from_random_table(db)
        
        # 새로운 RewardLink 레코드 생성 (같은 short_code, product_name, nvmid, 새로운 search_url)
        new_link = RewardLink(
            short_code=existing_link.short_code,
            product_name=existing_link.product_name,
            nvmid=existing_link.nvmid,  # 기존 link의 nvmid 사용
            reward_link=search_url  # 새로 생성한 search_url
        )
        db.add(new_link)
        db.flush()  # 새로운 link_id를 얻기 위해 flush
        
        logger.info(f"새로운 RewardLink 생성: link_id={new_link.link_id}, short_code={existing_link.short_code}, nvmid={existing_link.nvmid}, search_url={search_url[:100]}...")
        
        # 키워드 조합 추가 (새로 생성한 link_id 사용)
        keyword = RewardLinkKeyword(
            link_id=new_link.link_id,  # 새로 생성한 link_id 사용
            short_code=existing_link.short_code,
            query_keyword=query,
            acq_keyword=acq
        )
        db.add(keyword)
        db.commit()
        db.refresh(keyword)
        db.refresh(new_link)
        
        return {
            "success": True,
            "message": "키워드가 추가되었습니다.",
            "data": {
                "link_id": new_link.link_id,
                "keyword_id": keyword.keyword_id,
                "query_keyword": keyword.query_keyword,
                "acq_keyword": keyword.acq_keyword,
                "nvmid": new_link.nvmid,
                "search_url": new_link.reward_link
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"키워드 추가 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"키워드 추가 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/links/{link_id}/keywords/{keyword_id}")
async def delete_keyword(
    link_id: int,
    keyword_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 조합 삭제 (관리자용)
    키워드 삭제 시 해당 reward_link 레코드도 함께 삭제
    """
    check_admin_permission(current_user, db)
    
    try:
        # 키워드 조회
        keyword = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.keyword_id == keyword_id,
            RewardLinkKeyword.link_id == link_id
        ).first()
        
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"키워드를 찾을 수 없습니다: {keyword_id}"
            )
        
        # 해당 link_id의 reward_link 레코드 조회
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        # 키워드 삭제
        db.delete(keyword)
        db.flush()  # 키워드 삭제를 즉시 반영
        logger.info(f"키워드 삭제 완료: keyword_id={keyword_id}, link_id={link_id}")
        
        # 키워드 삭제 시 해당 reward_link 레코드도 함께 삭제
        if link:
            db.delete(link)
            db.flush()  # 링크 삭제를 즉시 반영
            logger.info(f"reward_link 레코드 삭제 완료: link_id={link_id}")
        else:
            logger.warning(f"link_id {link_id}에 해당하는 reward_link 레코드를 찾을 수 없습니다.")
        
        db.commit()  # 최종 커밋
        
        return {
            "success": True,
            "message": "키워드와 링크가 삭제되었습니다."
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"키워드 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"키워드 삭제 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/links/{short_code}")
async def delete_link(
    short_code: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    SHORT_CODE 기준으로 모든 링크 및 키워드 삭제 (관리자용)
    RANDOM_LINK 버튼의 작업삭제 기능
    """
    check_admin_permission(current_user, db)
    
    try:
        # short_code로 모든 RewardLink 레코드 조회
        links = db.query(RewardLink).filter(
            RewardLink.short_code == short_code
        ).all()
        
        if not links:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"short_code '{short_code}'에 해당하는 링크를 찾을 수 없습니다."
            )
        
        # short_code 기준으로 모든 키워드 삭제
        deleted_keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.short_code == short_code
        ).all()
        deleted_keyword_count = len(deleted_keywords)
        
        for keyword in deleted_keywords:
            db.delete(keyword)
        
        # 모든 링크 삭제
        deleted_link_count = len(links)
        for link in links:
            db.delete(link)
        
        db.commit()
        
        logger.info(f"[작업삭제] short_code '{short_code}': {deleted_link_count}개 링크, {deleted_keyword_count}개 키워드 삭제 완료")
        
        return {
            "success": True,
            "message": f"short_code '{short_code}'에 해당하는 모든 항목이 삭제되었습니다.",
            "deleted_links": deleted_link_count,
            "deleted_keywords": deleted_keyword_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[작업삭제] short_code '{short_code}' 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"삭제 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/keywords/batch")
async def delete_keywords_batch(
    request: KeywordBatchDelete,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 일괄 삭제 (관리자용)
    keyword_ids 리스트에 포함된 모든 키워드를 삭제하고, 
    해당 키워드와 연결된 reward_link 레코드도 함께 삭제
    """
    check_admin_permission(current_user, db)
    
    if not request.keyword_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="삭제할 keyword_ids를 제공해주세요."
        )
    
    try:
        deleted_count = 0
        deleted_link_ids = set()
        failed_keyword_ids = []
        
        for keyword_id in request.keyword_ids:
            try:
                # 키워드 조회
                keyword = db.query(RewardLinkKeyword).filter(
                    RewardLinkKeyword.keyword_id == keyword_id
                ).first()
                
                if not keyword:
                    failed_keyword_ids.append({
                        "keyword_id": keyword_id,
                        "error": "키워드를 찾을 수 없습니다."
                    })
                    continue
                
                link_id = keyword.link_id
                
                # 키워드 삭제
                db.delete(keyword)
                db.flush()
                
                # 해당 link_id의 reward_link 레코드 조회 및 삭제
                link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
                if link:
                    # 같은 link_id를 가진 다른 키워드가 있는지 확인
                    other_keywords = db.query(RewardLinkKeyword).filter(
                        RewardLinkKeyword.link_id == link_id,
                        RewardLinkKeyword.keyword_id != keyword_id
                    ).count()
                    
                    # 다른 키워드가 없으면 링크도 삭제
                    if other_keywords == 0:
                        db.delete(link)
                        deleted_link_ids.add(link_id)
                
                deleted_count += 1
                logger.info(f"키워드 삭제 완료: keyword_id={keyword_id}, link_id={link_id}")
                
            except Exception as e:
                logger.error(f"keyword_id {keyword_id} 삭제 중 오류: {e}", exc_info=True)
                failed_keyword_ids.append({
                    "keyword_id": keyword_id,
                    "error": str(e)
                })
                continue
        
        db.commit()
        
        logger.info(f"[배치 삭제] 총 {len(request.keyword_ids)}개 중 {deleted_count}개 삭제 완료, {len(deleted_link_ids)}개 링크 삭제")
        
        return {
            "success": True,
            "message": f"{deleted_count}개의 키워드가 삭제되었습니다.",
            "data": {
                "deleted_count": deleted_count,
                "deleted_link_count": len(deleted_link_ids),
                "failed_count": len(failed_keyword_ids),
                "failed_keywords": failed_keyword_ids if failed_keyword_ids else []
            }
        }
    
    except Exception as e:
        db.rollback()
        logger.error(f"배치 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"배치 삭제 중 오류가 발생했습니다: {str(e)}"
        )


@router.patch("/keywords/batch")
async def update_keywords_batch(
    request: KeywordBatchUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 일괄 수정 (관리자용)
    keyword_id로 해당 키워드만 조회하여 수정
    """
    check_admin_permission(current_user, db)
    
    if not request.keywords:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 키워드를 제공해주세요."
        )
    
    try:
        updated_count = 0
        failed_keywords = []
        results = []
        
        for kw_item in request.keywords:
            try:
                # keyword_id로 해당 키워드만 조회
                keyword = db.query(RewardLinkKeyword).filter(
                    RewardLinkKeyword.keyword_id == kw_item.keyword_id
                ).first()
                
                if not keyword:
                    failed_keywords.append({
                        "keyword_id": kw_item.keyword_id,
                        "error": f"키워드를 찾을 수 없습니다: {kw_item.keyword_id}"
                    })
                    continue
                
                # link_id로 링크 정보 조회 (short_code 업데이트용)
                link = db.query(RewardLink).filter(RewardLink.link_id == keyword.link_id).first()
                
                # query_keyword가 제공되면 수정
                if kw_item.query_keyword is not None:
                    query = kw_item.query_keyword.strip()
                    if not query:
                        failed_keywords.append({
                            "keyword_id": kw_item.keyword_id,
                            "error": "query_keyword가 비어있습니다."
                        })
                        continue
                    keyword.query_keyword = query
                
                # acq_keyword가 제공되면 수정, 없으면 랜덤 생성
                if kw_item.acq_keyword is not None:
                    keyword.acq_keyword = kw_item.acq_keyword
                else:
                    # acq_keyword가 제공되지 않았을 때만 랜덤 생성
                    if kw_item.query_keyword is not None:
                        keyword.acq_keyword = generate_acq_from_random_table(db)
                
                # short_code 업데이트 (link가 있으면)
                if link:
                    keyword.short_code = link.short_code
                
                keyword.updated_at = datetime.now()
                db.flush()
                updated_count += 1
                
                results.append({
                    "keyword_id": keyword.keyword_id,
                    "link_id": keyword.link_id,
                    "query_keyword": keyword.query_keyword,
                    "acq_keyword": keyword.acq_keyword,
                    "action": "updated"
                })
                
                logger.info(f"키워드 수정 완료: keyword_id={keyword.keyword_id}, query='{keyword.query_keyword}', acq='{keyword.acq_keyword}'")
            
            except Exception as e:
                logger.error(f"키워드 처리 중 오류: keyword_id={kw_item.keyword_id}, 오류: {e}", exc_info=True)
                failed_keywords.append({
                    "keyword_id": kw_item.keyword_id,
                    "error": str(e)
                })
                continue
        
        db.commit()
        
        logger.info(f"[배치 수정] 총 {len(request.keywords)}개 중 {updated_count}개 수정 완료, 실패: {len(failed_keywords)}개")
        
        return {
            "success": True,
            "message": f"{updated_count}개 수정되었습니다.",
            "data": {
                "updated_count": updated_count,
                "failed_count": len(failed_keywords),
                "results": results,
                "failed_keywords": failed_keywords if failed_keywords else []
            }
        }
    
    except Exception as e:
        db.rollback()
        logger.error(f"배치 수정 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"배치 수정 중 오류가 발생했습니다: {str(e)}"
        )
