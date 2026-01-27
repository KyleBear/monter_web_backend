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
from models import RewardLink, RewardLinkKeyword, UsersAdmin
from utils.auth_helpers import get_current_user
from datetime import datetime
import random
import string
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


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
    query_keyword: str
    acq_keyword: str


class RewardLinkCreate(BaseModel):
    product_name: Optional[str] = None
    keywords: List[KeywordCombination] = []


class RewardLinkUpdate(BaseModel):
    product_name: Optional[str] = None
    keywords: Optional[List[KeywordCombination]] = None


class KeywordAdd(BaseModel):
    query_keyword: str
    acq_keyword: str


# ==================== 유틸리티 함수 ====================

def generate_short_code(length: int = 10) -> str:
    """랜덤 짧은 코드 생성 (영문숫자)"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_random_ackey(length: int = 8) -> str:
    """랜덤 ackey 생성 (영문숫자 8글자)"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


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
            # 키워드 조합 조회
            keywords = db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.link_id == link.link_id
            ).all()
            
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
        
        # 키워드 조합 조회
        keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link.link_id
        ).all()
        
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
    """
    try:
        link = db.query(RewardLink).filter(RewardLink.short_code == short_code).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {short_code}"
            )
        
        # 키워드 조합 조회
        keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link.link_id
        ).all()
        
        if not keywords:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="등록된 키워드가 없습니다."
            )
        
        # 랜덤으로 키워드 조합 선택
        random_keyword = random.choice(keywords)
        query = random_keyword.query_keyword
        acq = random_keyword.acq_keyword
        
        # 네이버 검색 URL 생성
        from urllib.parse import quote
        ackey = generate_random_ackey(8)
        acr = random.randint(0, 10)
        
        naver_url = (
            f"https://m.search.naver.com/search.naver?"
            f"sm=mtp_sug.top&"
            f"where=m&"
            f"query={quote(query)}&"
            f"ackey={ackey}&"
            f"acq={quote(acq)}&"
            f"acr={acr}&"
            f"qdt=0"
        )
        
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
    """
    check_admin_permission(current_user, db)
    
    try:
        # 짧은 코드 생성 (중복 체크)
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
        
        # 링크 생성
        new_link = RewardLink(
            short_code=short_code,
            product_name=link_data.product_name
        )
        db.add(new_link)
        db.flush()
        
        # 키워드 조합 저장
        for kw in link_data.keywords:
            keyword = RewardLinkKeyword(
                link_id=new_link.link_id,
                query_keyword=kw.query_keyword,
                acq_keyword=kw.acq_keyword
            )
            db.add(keyword)
        
        db.commit()
        db.refresh(new_link)
        
        return {
            "success": True,
            "message": "링크가 생성되었습니다.",
            "data": {
                "link_id": new_link.link_id,
                "short_code": new_link.short_code,
                "product_name": new_link.product_name,
                "keyword_count": len(link_data.keywords),
                "short_url": f"/redirect/{new_link.short_code}"
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
                keyword = RewardLinkKeyword(
                    link_id=link_id,
                    query_keyword=kw.query_keyword,
                    acq_keyword=kw.acq_keyword
                )
                db.add(keyword)
        
        db.commit()
        db.refresh(link)
        
        return {
            "success": True,
            "message": "링크가 수정되었습니다.",
            "data": {
                "link_id": link.link_id,
                "short_code": link.short_code,
                "product_name": link.product_name
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
    """
    check_admin_permission(current_user, db)
    
    try:
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        # 키워드 조합 추가
        keyword = RewardLinkKeyword(
            link_id=link_id,
            query_keyword=keyword_data.query_keyword,
            acq_keyword=keyword_data.acq_keyword
        )
        db.add(keyword)
        db.commit()
        db.refresh(keyword)
        
        return {
            "success": True,
            "message": "키워드가 추가되었습니다.",
            "data": {
                "keyword_id": keyword.keyword_id,
                "query_keyword": keyword.query_keyword,
                "acq_keyword": keyword.acq_keyword
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
    """
    check_admin_permission(current_user, db)
    
    try:
        keyword = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.keyword_id == keyword_id,
            RewardLinkKeyword.link_id == link_id
        ).first()
        
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"키워드를 찾을 수 없습니다: {keyword_id}"
            )
        
        db.delete(keyword)
        db.commit()
        
        return {
            "success": True,
            "message": "키워드가 삭제되었습니다."
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


@router.delete("/links/{link_id}")
async def delete_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    링크 삭제 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        # 관련 키워드 삭제
        db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link_id
        ).delete()
        
        # 링크 삭제
        db.delete(link)
        db.commit()
        
        return {
            "success": True,
            "message": "링크가 삭제되었습니다."
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"링크 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 삭제 중 오류가 발생했습니다: {str(e)}"
        )
