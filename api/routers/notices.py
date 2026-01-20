"""
공지사항 및 FAQ 관리 API 라우터
등록, 수정, 삭제 (admin만 가능)
조회는 모든 사용자 가능
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import Notice, FAQ, UsersAdmin
from utils.auth_helpers import get_current_user
from datetime import datetime

router = APIRouter()


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


# ==================== 공지사항 API ====================

# 공지사항 요청/응답 모델
class NoticeCreate(BaseModel):
    title: str
    content: str
    is_pinned: Optional[bool] = False


class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_pinned: Optional[bool] = None


class NoticeResponse(BaseModel):
    notice_id: int
    title: str
    content: str
    is_pinned: bool
    created_by: int
    updated_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


@router.get("/notices", response_model=List[NoticeResponse])
async def get_notices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_pinned: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    공지사항 목록 조회
    - 모든 사용자 조회 가능
    - 고정 공지(is_pinned=True) 우선 정렬
    """
    query = db.query(Notice)
    
    if is_pinned is not None:
        query = query.filter(Notice.is_pinned == is_pinned)
    
    # 고정 공지 우선, 그 다음 최신순
    notices = query.order_by(desc(Notice.is_pinned), desc(Notice.created_at)).offset(skip).limit(limit).all()
    
    return notices


@router.get("/notices/{notice_id}", response_model=NoticeResponse)
async def get_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    공지사항 상세 조회
    - 모든 사용자 조회 가능
    """
    notice = db.query(Notice).filter(Notice.notice_id == notice_id).first()
    
    if not notice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="공지사항을 찾을 수 없습니다."
        )
    
    return notice


@router.post("/notices", response_model=NoticeResponse, status_code=status.HTTP_201_CREATED)
async def create_notice(
    notice: NoticeCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    공지사항 등록
    - admin만 가능
    """
    # Admin 권한 체크
    user = check_admin_permission(current_user, db)
    
    try:
        new_notice = Notice(
            title=notice.title,
            content=notice.content,
            is_pinned=notice.is_pinned,
            created_by=user.user_id
        )
        
        db.add(new_notice)
        db.commit()
        db.refresh(new_notice)
        
        return new_notice
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"공지사항 등록 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"공지사항 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/notices/{notice_id}", response_model=NoticeResponse)
async def update_notice(
    notice_id: int,
    notice: NoticeUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    공지사항 수정
    - admin만 가능
    """
    # Admin 권한 체크
    user = check_admin_permission(current_user, db)
    
    try:
        existing_notice = db.query(Notice).filter(Notice.notice_id == notice_id).first()
        
        if not existing_notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="공지사항을 찾을 수 없습니다."
            )
        
        # 업데이트할 필드만 수정
        if notice.title is not None:
            existing_notice.title = notice.title
        if notice.content is not None:
            existing_notice.content = notice.content
        if notice.is_pinned is not None:
            existing_notice.is_pinned = notice.is_pinned
        
        existing_notice.updated_by = user.user_id
        existing_notice.updated_at = datetime.now()
        
        db.commit()
        db.refresh(existing_notice)
        
        return existing_notice
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"공지사항 수정 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"공지사항 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    공지사항 삭제
    - admin만 가능
    """
    # Admin 권한 체크
    check_admin_permission(current_user, db)
    
    try:
        notice = db.query(Notice).filter(Notice.notice_id == notice_id).first()
        
        if not notice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="공지사항을 찾을 수 없습니다."
            )
        
        db.delete(notice)
        db.commit()
        
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"공지사항 삭제 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"공지사항 삭제 중 오류가 발생했습니다: {str(e)}"
        )


# ==================== FAQ API ====================

# FAQ 요청/응답 모델
class FAQCreate(BaseModel):
    question: str
    answer: str
    category: Optional[str] = None
    sort_order: Optional[int] = 0


class FAQUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    sort_order: Optional[int] = None


class FAQResponse(BaseModel):
    faq_id: int
    question: str
    answer: str
    category: Optional[str]
    sort_order: int
    created_by: int
    updated_by: Optional[int]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


@router.get("/faqs", response_model=List[FAQResponse])
async def get_faqs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    FAQ 목록 조회
    - 모든 사용자 조회 가능
    - sort_order, faq_id 순으로 정렬
    """
    query = db.query(FAQ)
    
    if category:
        query = query.filter(FAQ.category == category)
    
    faqs = query.order_by(FAQ.sort_order, FAQ.faq_id).offset(skip).limit(limit).all()
    
    return faqs


@router.get("/faqs/{faq_id}", response_model=FAQResponse)
async def get_faq(
    faq_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    FAQ 상세 조회
    - 모든 사용자 조회 가능
    """
    faq = db.query(FAQ).filter(FAQ.faq_id == faq_id).first()
    
    if not faq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FAQ를 찾을 수 없습니다."
        )
    
    return faq


@router.post("/faqs", response_model=FAQResponse, status_code=status.HTTP_201_CREATED)
async def create_faq(
    faq: FAQCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    FAQ 등록
    - admin만 가능
    """
    # Admin 권한 체크
    user = check_admin_permission(current_user, db)
    
    try:
        new_faq = FAQ(
            question=faq.question,
            answer=faq.answer,
            category=faq.category,
            sort_order=faq.sort_order,
            created_by=user.user_id
        )
        
        db.add(new_faq)
        db.commit()
        db.refresh(new_faq)
        
        return new_faq
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"FAQ 등록 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"FAQ 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/faqs/{faq_id}", response_model=FAQResponse)
async def update_faq(
    faq_id: int,
    faq: FAQUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    FAQ 수정
    - admin만 가능
    """
    # Admin 권한 체크
    user = check_admin_permission(current_user, db)
    
    try:
        existing_faq = db.query(FAQ).filter(FAQ.faq_id == faq_id).first()
        
        if not existing_faq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="FAQ를 찾을 수 없습니다."
            )
        
        # 업데이트할 필드만 수정
        if faq.question is not None:
            existing_faq.question = faq.question
        if faq.answer is not None:
            existing_faq.answer = faq.answer
        if faq.category is not None:
            existing_faq.category = faq.category
        if faq.sort_order is not None:
            existing_faq.sort_order = faq.sort_order
        
        existing_faq.updated_by = user.user_id
        existing_faq.updated_at = datetime.now()
        
        db.commit()
        db.refresh(existing_faq)
        
        return existing_faq
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"FAQ 수정 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"FAQ 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/faqs/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    FAQ 삭제
    - admin만 가능
    """
    # Admin 권한 체크
    check_admin_permission(current_user, db)
    
    try:
        faq = db.query(FAQ).filter(FAQ.faq_id == faq_id).first()
        
        if not faq:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="FAQ를 찾을 수 없습니다."
            )
        
        db.delete(faq)
        db.commit()
        
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"FAQ 삭제 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"FAQ 삭제 중 오류가 발생했습니다: {str(e)}"
        )
