"""
계정 관리 API 라우터
계정 조회, 생성, 수정, 삭제
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import UsersAdmin, AdvertisementsAdmin
from utils.password import hash_password
from utils.time_check import check_edit_time_allowed
from utils.auth_helpers import get_current_user
from datetime import datetime

router = APIRouter()


# 요청/응답 모델
class AccountCreate(BaseModel):
    username: str
    password: str
    role: str  # 총판사/대행사/광고주
    parent_user_id: Optional[int] = None
    affiliation: Optional[str] = None
    memo: Optional[str] = None


class AccountUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    affiliation: Optional[str] = None
    memo: Optional[str] = None
    is_active: Optional[bool] = None


class AccountDelete(BaseModel):
    user_ids: List[int]


@router.get("")
async def get_accounts(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    search_type: str = Query("all"),
    search_keyword: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    계정 목록 조회 API
    - 페이지네이션 처리
    - 검색 기능 (아이디, 소속, 메모)
    - 역할별 필터링
    - 통계 정보 포함
    """
    # 페이지네이션 계산
    offset = (page - 1) * limit
    
    # 기본 쿼리
    query = db.query(UsersAdmin)
    
    # 역할 필터링
    if role:
        query = query.filter(UsersAdmin.role == role)
    
    # 검색 필터링
    if search_keyword:
        if search_type == "userid":
            query = query.filter(UsersAdmin.username.contains(search_keyword))
        elif search_type == "group":
            query = query.filter(UsersAdmin.affiliation.contains(search_keyword))
        elif search_type == "memo":
            query = query.filter(UsersAdmin.memo.contains(search_keyword))
        elif search_type == "all":
            query = query.filter(
                or_(
                    UsersAdmin.username.contains(search_keyword),
                    UsersAdmin.affiliation.contains(search_keyword),
                    UsersAdmin.memo.contains(search_keyword)
                )
            )
    
    # 전체 개수 조회
    total = query.count()
    
    # 페이지네이션 적용
    accounts = query.offset(offset).limit(limit).all()
    
    # 각 계정의 통계 정보 계산
    account_list = []
    for account in accounts:
        # 광고 수량 계산
        ad_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
            AdvertisementsAdmin.user_id == account.user_id
        ).scalar() or 0
        
        # 진행중인 광고 수 계산 (정상 상태)
        active_ad_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
            AdvertisementsAdmin.user_id == account.user_id,
            AdvertisementsAdmin.status == "normal"
        ).scalar() or 0
        
        account_list.append({
            "user_id": account.user_id,
            "username": account.username,
            "role": account.role,
            "affiliation": account.affiliation or "",
            "ad_count": ad_count,
            "active_ad_count": active_ad_count,
            "memo": account.memo or "",
            "is_active": account.is_active,
            "created_at": account.created_at.isoformat() if account.created_at else None
        })
    
    # 전체 통계 계산
    total_count = db.query(func.count(UsersAdmin.user_id)).scalar() or 0
    total_seller_count = db.query(func.count(UsersAdmin.user_id)).filter(
        UsersAdmin.role == "total"
    ).scalar() or 0
    agency_count = db.query(func.count(UsersAdmin.user_id)).filter(
        UsersAdmin.role == "agency"
    ).scalar() or 0
    advertiser_count = db.query(func.count(UsersAdmin.user_id)).filter(
        UsersAdmin.role == "advertiser"
    ).scalar() or 0
    
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    
    return {
        "success": True,
        "data": {
            "accounts": account_list,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        },
        "stats": {
            "total": total_count,
            "total_seller": total_seller_count,
            "agency": agency_count,
            "advertiser": advertiser_count
        }
    }


@router.get("/{user_id}")
async def get_account(user_id: int, db: Session = Depends(get_db)):
    """
    계정 상세 조회 API
    """
    account = db.query(UsersAdmin).filter(UsersAdmin.user_id == user_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="계정을 찾을 수 없습니다."
        )
    
    # 광고 수량 계산
    ad_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.user_id == account.user_id
    ).scalar() or 0
    
    # 진행중인 광고 수 계산
    active_ad_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.user_id == account.user_id,
        AdvertisementsAdmin.status == "normal"
    ).scalar() or 0
    
    return {
        "success": True,
        "data": {
            "user_id": account.user_id,
            "username": account.username,
            "role": account.role,
            "parent_user_id": account.parent_user_id,
            "affiliation": account.affiliation,
            "memo": account.memo,
            "ad_count": ad_count,
            "active_ad_count": active_ad_count,
            "is_active": account.is_active,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None
        }
    }


@router.post("")
async def create_account(
    account: AccountCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    계정 생성 API
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    # username 중복 체크
    existing_user = db.query(UsersAdmin).filter(UsersAdmin.username == account.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 존재하는 아이디입니다."
        )
    
    # role 검증
    valid_roles = ["total", "agency", "advertiser"]
    if account.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 역할입니다. 가능한 역할: {', '.join(valid_roles)}"
        )
    
    # parent_user_id 검증
    if account.role == "agency" and account.parent_user_id:
        parent = db.query(UsersAdmin).filter(UsersAdmin.user_id == account.parent_user_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="상위 계정을 찾을 수 없습니다."
            )
        if parent.role != "total":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="대행사의 상위 계정은 총판사여야 합니다."
            )
    elif account.role == "advertiser" and account.parent_user_id:
        parent = db.query(UsersAdmin).filter(UsersAdmin.user_id == account.parent_user_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="상위 계정을 찾을 수 없습니다."
            )
        if parent.role != "agency":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="광고주의 상위 계정은 대행사여야 합니다."
            )
    elif account.role == "total" and account.parent_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="총판사는 상위 계정을 가질 수 없습니다."
        )
    
    # 비밀번호 해시화
    password_hash = hash_password(account.password)
    
    # 계정 생성
    new_account = UsersAdmin(
        username=account.username,
        password_hash=password_hash,
        role=account.role,
        parent_user_id=account.parent_user_id,
        affiliation=account.affiliation,
        memo=account.memo,
        is_active=True
    )
    
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    
    return {
        "success": True,
        "message": "계정이 생성되었습니다.",
        "data": {
            "user_id": new_account.user_id,
            "username": new_account.username
        }
    }


@router.put("/{user_id}")
async def update_account(
    user_id: int,
    account: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    계정 수정 API
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    # 계정 조회
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="계정을 찾을 수 없습니다."
        )
    
    # 비밀번호 변경
    if account.password:
        user.password_hash = hash_password(account.password)
    
    # 역할 변경
    if account.role:
        valid_roles = ["total", "agency", "advertiser"]
        if account.role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 역할입니다. 가능한 역할: {', '.join(valid_roles)}"
            )
        user.role = account.role
    
    # 소속 변경
    if account.affiliation is not None:
        user.affiliation = account.affiliation
    
    # 메모 변경
    if account.memo is not None:
        user.memo = account.memo
    
    # 활성화 상태 변경
    if account.is_active is not None:
        user.is_active = account.is_active
    
    user.updated_at = datetime.now()
    
    db.commit()
    db.refresh(user)
    
    return {
        "success": True,
        "message": "계정이 수정되었습니다.",
        "data": {
            "user_id": user.user_id
        }
    }


@router.delete("")
async def delete_accounts(
    delete_request: AccountDelete,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    계정 삭제 API
    - 여러 계정 일괄 삭제
    - 소프트 삭제 (is_active=False)로 처리
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    deleted_count = 0
    not_found_ids = []
    
    for user_id in delete_request.user_ids:
        user = db.query(UsersAdmin).filter(UsersAdmin.user_id == user_id).first()
        
        if not user:
            not_found_ids.append(user_id)
            continue
        
        # 관련 광고 확인
        ad_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
            AdvertisementsAdmin.user_id == user_id
        ).scalar() or 0
        
        # 소프트 삭제 (is_active=False)
        user.is_active = False
        user.updated_at = datetime.now()
        deleted_count += 1
    
    db.commit()
    
    if not_found_ids:
        return {
            "success": True,
            "message": f"{deleted_count}개의 계정이 삭제되었습니다. ({len(not_found_ids)}개 계정을 찾을 수 없음)",
            "data": {
                "deleted_count": deleted_count,
                "not_found_ids": not_found_ids
            }
        }
    
    return {
        "success": True,
        "message": f"선택한 {deleted_count}개의 계정이 삭제되었습니다.",
        "data": {
            "deleted_count": deleted_count
        }
    }

# 현재 비활덩인것만 삭제 