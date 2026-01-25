"""
키워드 검색 API 라우터
- 메인키워드 추출 API (10개, 20개, 30개)
- GUI 제거, FastAPI 라우터로 변환
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import RewardRank, UsersAdmin
from utils.auth_helpers import get_current_user
from datetime import datetime
from urllib.parse import quote
import random
import string
import re
from bs4 import BeautifulSoup

# keyword_search.py의 함수들 import
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# keyword_search.py의 함수들 import
from api.routers.keyword_search import (
    split_keywords_by_space,
    generate_keyword_combinations,
    get_api_rank_by_keyword,
    get_shopping_rank_with_ad_flag
)

router = APIRouter()


# ==================== 유틸리티 함수 ====================

def remove_html_tags(text: str) -> str:
    """
    HTML 태그를 제거하고 텍스트만 반환
    
    Args:
        text: HTML 태그가 포함될 수 있는 텍스트
    
    Returns:
        HTML 태그가 제거된 텍스트
    """
    if not text:
        return ""
    
    # 문자열로 변환 (혹시 다른 타입일 경우 대비)
    text = str(text)
    
    # 먼저 정규표현식으로 HTML 태그 제거 (더 확실함)
    cleaned_text = re.sub(r'<[^>]+>', '', text)
    
    # BeautifulSoup으로도 한 번 더 정제 (HTML 엔티티 처리)
    try:
        soup = BeautifulSoup(cleaned_text, "html.parser")
        cleaned_text = soup.get_text(separator=" ", strip=True)
    except Exception:
        pass  # BeautifulSoup 실패해도 이미 정규표현식으로 처리했으므로 계속 진행
    
    # HTML 엔티티 디코딩 (예: &lt; -> <, &gt; -> >, &amp; -> &)
    try:
        import html
        cleaned_text = html.unescape(cleaned_text)
    except Exception:
        pass
    
    # 여러 공백을 하나로 통합
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    return cleaned_text


def generate_ackey(length: int = 8) -> str:
    """영문숫자 랜덤 문자열 생성 (ackey용)"""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def generate_search_url(keyword: str, all_keywords: List[str] = None) -> str:
    """
    네이버 모바일 검색 URL 생성
    
    Args:
        keyword: 검색할 키워드 (query 파라미터용)
        all_keywords: 저장된 모든 키워드 리스트 (acq 파라미터용, 랜덤 선택)
    
    Returns:
        네이버 모바일 검색 URL
    """
    # query 파라미터: 현재 키워드 사용
    encoded_keyword = quote(keyword)
    
    # ackey: 영문숫자 8글자 랜덤
    ackey = generate_ackey(8)
    
    # acq: 저장된 키워드 중 랜덤 (없으면 현재 키워드 사용)
    if all_keywords and len(all_keywords) > 0:
        acq_keyword = random.choice(all_keywords)
    else:
        acq_keyword = keyword
    encoded_acq = quote(acq_keyword)
    
    # acr: 0~10 랜덤
    acr = random.randint(0, 10)
    
    # search_url 생성
    search_url = (
        f"https://m.search.naver.com/search.naver?"
        f"sm=mtp_sug.top&"
        f"where=m&"
        f"query={encoded_keyword}&"
        f"ackey={ackey}&"
        f"acq={encoded_acq}&"
        f"acr={acr}&"
        f"qdt=0"
    )
    
    return search_url


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


# ==================== 요청/응답 모델 ====================

class KeywordExtractRequest(BaseModel):
    keyword: str  # 검색할 키워드 (띄어쓰기로 구분)
    nvmid: str  # 찾을 상품의 nvmid
    count: int  # 추출할 메인키워드 개수 (10, 20, 30)
    product_url: Optional[str] = None  # 상품 URL (선택)


class KeywordExtractResponse(BaseModel):
    success: bool
    message: str
    data: dict


# ==================== API 엔드포인트 ====================

@router.post("/extract")
async def extract_main_keywords(
    request: KeywordExtractRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    메인키워드 추출 API
    키워드 조합을 생성하고 순위를 조회한 후, 상위 N개를 랜덤으로 선택하여 reward_rank 테이블에 저장
    
    Args:
        request: 키워드 추출 요청 (keyword, nvmid, count)
    
    Returns:
        추출된 메인키워드 리스트
    """
    # 관리자 권한 체크
    check_admin_permission(current_user, db)
    
    # count 검증 (10, 20, 30만 허용)
    if request.count not in [10, 20, 30]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="count는 10, 20, 30 중 하나여야 합니다."
        )
    
    try:
        # 1. 키워드 분리 및 조합 생성
        words = split_keywords_by_space(request.keyword)
        if len(words) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="키워드는 최소 2개 단어 이상이어야 합니다."
            )
        
        keyword_combinations = generate_keyword_combinations(words, min_length=2, max_length=len(words))
        
        if not keyword_combinations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="키워드 조합을 생성할 수 없습니다."
            )
        
        # 2. 각 조합 키워드로 순위 조회
        keyword_rank_results = []
        
        for idx, combo_keyword in enumerate(keyword_combinations, 1):
            try:
                # API로 순위 조회 (최대 1000등까지)
                rank = get_api_rank_by_keyword(combo_keyword, request.nvmid, max_rank=1000)
                
                if rank:  # 순위가 있는 키워드만 저장
                    keyword_rank_results.append({
                        "keyword": combo_keyword,
                        "rank": rank
                    })
                
                # API 호출 간격
                import time
                time.sleep(0.5)
                
            except Exception as e:
                # 개별 키워드 조회 실패는 무시하고 계속 진행
                continue
        
        if not keyword_rank_results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="순위가 있는 키워드를 찾을 수 없습니다."
            )
        
        # 3. 순위가 있는 키워드 중에서 랜덤으로 N개 선택
        # 순위가 낮을수록(숫자가 작을수록) 우선순위가 높으므로 정렬
        keyword_rank_results.sort(key=lambda x: x["rank"])
        
        # 요청한 개수만큼 랜덤 선택 (순위가 있는 키워드가 부족하면 모두 선택)
        selected_count = min(request.count, len(keyword_rank_results))
        selected_keywords = random.sample(keyword_rank_results, selected_count)
        
        # 4. 선택된 키워드들의 상세 정보 조회 및 reward_rank 테이블에 저장
        saved_rewards = []
        
        # 같은 nvmid의 기존 키워드들 조회 (acq 파라미터용)
        existing_keywords = db.query(RewardRank.keyword).filter(
            RewardRank.nvmid == request.nvmid,
            RewardRank.keyword.isnot(None),
            RewardRank.keyword != ''
        ).all()
        existing_keyword_list = [kw[0] for kw in existing_keywords if kw[0]]
        
        # 현재 저장할 키워드들도 리스트에 추가
        all_available_keywords = existing_keyword_list + [s["keyword"] for s in selected_keywords]
        
        for selected in selected_keywords:
            keyword = selected["keyword"]
            rank = selected["rank"]
            
            try:
                # 네이버 쇼핑 API로 상품 정보 조회
                api_results = get_shopping_rank_with_ad_flag(keyword, display=1, start=1)
                
                if api_results and len(api_results) > 0:
                    item = api_results[0]
                    
                    # search_url 생성 (네이버 모바일 검색 URL 형식)
                    # acq는 저장된 키워드 중 랜덤 선택 (현재 키워드 포함)
                    search_url = generate_search_url(keyword, all_available_keywords)
                    
                    # HTML 태그 제거된 상품명 및 스토어명 가져오기
                    raw_product_name = item.get("product_name", "")
                    cleaned_product_name = remove_html_tags(raw_product_name)
                    
                    raw_store_name = item.get("mall_name", "")
                    cleaned_store_name = remove_html_tags(raw_store_name)
                    
                    # 디버깅 로그 (HTML 태그가 제거되었는지 확인)
                    import logging
                    logger = logging.getLogger(__name__)
                    if raw_product_name != cleaned_product_name:
                        logger.info(f"HTML 태그 제거됨 - 원본: '{raw_product_name[:100]}...' -> 정제: '{cleaned_product_name[:100]}...'")
                    elif '<' in raw_product_name or '>' in raw_product_name:
                        logger.warning(f"HTML 태그가 여전히 포함됨: '{raw_product_name[:100]}...'")
                    
                    # reward_rank 테이블에 저장
                    reward_rank = RewardRank(
                        keyword=keyword,
                        store_name=cleaned_store_name,
                        product_name=cleaned_product_name,
                        productid=item.get("productId", ""),
                        search_url=search_url,
                        product_url=request.product_url or "",
                        image_url=item.get("image", ""),
                        image_tag="",  # 나중에 업데이트 가능
                        nvmid=request.nvmid
                    )
                    
                    db.add(reward_rank)
                    db.flush()
                    
                    # 저장된 키워드 리스트에 추가 (다음 키워드의 acq 선택에 사용)
                    all_available_keywords.append(keyword)
                    
                    saved_rewards.append({
                        "reward_id": reward_rank.reward_id,
                        "keyword": keyword,
                        "rank": rank,
                        "search_url": search_url,
                        "store_name": cleaned_store_name,
                        "product_name": cleaned_product_name,
                        "image_url": item.get("image", "")
                    })
                
            except Exception as e:
                # 개별 키워드 저장 실패는 무시하고 계속 진행
                continue
        
        # 5. DB 커밋
        db.commit()
        
        return {
            "success": True,
            "message": f"{len(saved_rewards)}개의 메인키워드가 추출되어 저장되었습니다.",
            "data": {
                "count": len(saved_rewards),
                "rewards": saved_rewards
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"메인키워드 추출 중 오류가 발생했습니다: {str(e)}"
        )
