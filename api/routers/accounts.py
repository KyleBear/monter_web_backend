"""
계정 관리 API 라우터
계정 조회, 생성, 수정, 삭제
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
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
    username: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    affiliation: Optional[str] = Query(None),
    memo: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    계정 목록 조회 API
    - 페이지네이션 지원
    - 검색 기능 (username, affiliation, memo)
    - 권한 기반 필터링 (화면 시작 시부터 적용)
    
    권한별 조회 범위:
    - Admin/Monter: 모든 계정 조회
    - Total (총판사): 자신 + 자신이 직접 생성한 대행사 + 그 대행사들의 광고주
    - Agency (대행사): 자신 + 자신이 직접 생성한 광고주만
    - Advertiser (광고주): 자신만
    """
    # 기본 쿼리
    query = db.query(UsersAdmin)
    
    # 권한에 따른 조회 범위 필터링 (가장 먼저 적용 - 화면 시작 시부터)
    query = _apply_account_permission_filter(query, current_user, db)
    
    # 역할 필터링
    if role:
        query = query.filter(UsersAdmin.role == role)
    
    # 검색 조건 추가
    if username:
        query = query.filter(UsersAdmin.username.contains(username))
    if keyword:
        query = query.filter(
            or_(
                UsersAdmin.username.contains(keyword),
                UsersAdmin.affiliation.contains(keyword),
                UsersAdmin.memo.contains(keyword)
            )
        )
    if affiliation:
        query = query.filter(UsersAdmin.affiliation.contains(affiliation))
    if memo:
        query = query.filter(UsersAdmin.memo.contains(memo))
    
    # 전체 개수 조회 (페이지네이션 전)
    total = query.count()
    
    # 페이지네이션 적용
    offset = (page - 1) * limit
    accounts = query.offset(offset).limit(limit).all()
    
    # 통계 계산 (조회된 계정 기준)
    stats = {
        "total": total,
        "distributor": sum(1 for a in accounts if a.role == "total"),
        "agency": sum(1 for a in accounts if a.role == "agency"),
        "advertiser": sum(1 for a in accounts if a.role == "advertiser")
    }
    
    # 간단한 정보만 반환 (상세 정보는 /detail 사용)
    account_list = []
    for account in accounts:
        account_list.append({
            "user_id": account.user_id,
            "username": account.username,
            "role": account.role,
            "affiliation": account.affiliation or "",
            "memo": account.memo or "",
            "is_active": account.is_active,
            "created_at": account.created_at.isoformat() if account.created_at else None
        })
    
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
        "stats": stats
    }

def _apply_account_permission_filter(
    query,
    current_user: dict,
    db: Session
):
    """
    계정 조회 권한에 따른 필터링 적용
    username 기반으로 실제 user_id 조회 후 필터링
    """
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 슈퍼유저는 모든 계정 조회 가능
    if current_username in ["admin", "monter"]:
        return query  # 필터링 없음
    
    # username으로 실제 user_id 조회 (세션의 user_id 대신)
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 정보를 찾을 수 없습니다."
        )
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    # 세션의 role과 실제 role이 다르면 에러
    if actual_role != current_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한 정보가 일치하지 않습니다. 다시 로그인해주세요."
        )
    
    if actual_role == "total":  # 총판사
        # 자신 + 직접 하위 대행사 + 그 대행사들의 광고주
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        
        filter_conditions = [
            UsersAdmin.user_id == actual_user_id,  # 자신
            UsersAdmin.parent_user_id == actual_user_id,  # 직접 하위 (대행사)
        ]
        
        # 간접 하위 (대행사의 광고주) - agency_ids가 있을 때만 추가
        if agency_ids:
            filter_conditions.append(UsersAdmin.parent_user_id.in_(agency_ids))
        
        return query.filter(or_(*filter_conditions))
    
    elif actual_role == "agency":  # 대행사
        # 자신 + 직접 하위 광고주만
        return query.filter(
            or_(
                UsersAdmin.user_id == actual_user_id,  # 자신
                and_(
                    UsersAdmin.parent_user_id == actual_user_id,
                    UsersAdmin.role == "advertiser"
                )  # 직접 하위 (광고주)
            )
        )
    
    elif actual_role == "advertiser":  # 광고주
        # 자신만 조회
        return query.filter(UsersAdmin.user_id == actual_user_id)
    
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한이 없습니다."
        )


def _check_account_access_permission(
    account: UsersAdmin,
    current_user: dict,
    db: Session
) -> bool:
    """
    계정 조회 권한 체크 (단일 계정용)
    username 기반으로 실제 user_id 조회 후 체크
    Returns: True if access allowed, False otherwise
    """
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 슈퍼유저는 모든 계정 조회 가능
    if current_username in ["admin", "monter"]:
        return True
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        return False
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    if actual_role != current_role:
        return False
    
    if actual_role == "total":  # 총판사
        # 자신 + 직접 하위 대행사 + 그 대행사들의 광고주
        if account.user_id == actual_user_id:
            return True
        
        # 직접 하위 (대행사)
        if account.parent_user_id == actual_user_id:
            return True
        
        # 간접 하위 (대행사의 광고주)
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        if account.parent_user_id in agency_ids:
            return True
        
        return False
    
    elif actual_role == "agency":  # 대행사
        # 자신 + 직접 하위 광고주만
        if account.user_id == actual_user_id:
            return True
        
        if account.parent_user_id == actual_user_id and account.role == "advertiser":
            return True
        
        return False
    
    elif actual_role == "advertiser":  # 광고주
        # 자신만 조회 가능
        return account.user_id == actual_user_id
    
    return False


def _get_account_stats(account: UsersAdmin, db: Session) -> dict:
    """
    계정 통계 정보 계산
    """
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
        "ad_count": ad_count,
        "active_ad_count": active_ad_count
    }


@router.get("/detail")
async def get_account_detail(
    username: Optional[str] = Query(None, description="사용자명으로 검색 (기본값)"),
    affiliation: Optional[str] = Query(None, description="소속으로 검색"),
    memo: Optional[str] = Query(None, description="메모로 검색"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    계정 상세 조회 API
    - 기본적으로 username 기반으로 검색
    - username, affiliation, memo로 검색 가능
    - 권한에 따라 조회 가능한 계정만 반환 (화면 시작 시부터 적용)
    
    검색 우선순위: username > affiliation > memo
    """
    # 검색 조건 구성
    query = db.query(UsersAdmin)
    
    # 권한에 따른 조회 범위 필터링 (가장 먼저 적용 - 화면 시작 시부터)
    query = _apply_account_permission_filter(query, current_user, db)
    
    # 검색 조건 추가 (우선순위: username > affiliation > memo)
    if username:
        query = query.filter(UsersAdmin.username == username)
    elif affiliation:
        query = query.filter(UsersAdmin.affiliation.contains(affiliation))
    elif memo:
        query = query.filter(UsersAdmin.memo.contains(memo))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="검색 조건을 하나 이상 제공해야 합니다. (username, affiliation, memo 중 하나)"
        )
    
    # 계정 조회 (첫 번째 결과만)
    account = query.first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="계정을 찾을 수 없거나 조회 권한이 없습니다."
        )
    
    # 권한 재확인 (추가 안전장치)
    if not _check_account_access_permission(account, current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 계정을 조회할 권한이 없습니다."
        )
    
    # 통계 정보 계산
    stats = _get_account_stats(account, db)
    
    return {
        "success": True,
        "data": {
            "user_id": account.user_id,
            "username": account.username,
            "role": account.role,
            "parent_user_id": account.parent_user_id,
            "affiliation": account.affiliation,
            "memo": account.memo,
            "ad_count": stats["ad_count"],
            "active_ad_count": stats["active_ad_count"],
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
    
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 정보를 찾을 수 없습니다."
        )
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    # 세션의 role과 실제 role이 다르면 에러
    if actual_role != current_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한 정보가 일치하지 않습니다. 다시 로그인해주세요."
        )
    
    # parent_user_id 자동 설정 (총판사는 parent_user_id가 None이어야 함)
    final_parent_user_id = account.parent_user_id
    
    # 슈퍼유저가 아닌 경우, parent_user_id 자동 설정
    if current_username not in ["admin", "monter"]:
        if account.role == "total":
            # 총판사는 parent_user_id가 None이어야 함
            final_parent_user_id = None
        elif account.role == "agency":
            # 대행사는 총판사의 하위여야 함
            if actual_role == "total":
                final_parent_user_id = actual_user_id
            elif not final_parent_user_id:
                # parent_user_id가 명시되지 않았으면 현재 사용자를 parent로 설정
                final_parent_user_id = actual_user_id
        elif account.role == "advertiser":
            # 광고주는 대행사의 하위여야 함
            if actual_role == "agency":
                final_parent_user_id = actual_user_id
            elif not final_parent_user_id:
                # parent_user_id가 명시되지 않았으면 현재 사용자를 parent로 설정
                final_parent_user_id = actual_user_id
    
    # parent_user_id 검증
    if account.role == "agency" and final_parent_user_id:
        parent = db.query(UsersAdmin).filter(UsersAdmin.user_id == final_parent_user_id).first()
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
    elif account.role == "advertiser" and final_parent_user_id:
        parent = db.query(UsersAdmin).filter(UsersAdmin.user_id == final_parent_user_id).first()
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
    elif account.role == "total" and final_parent_user_id:
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
        parent_user_id=final_parent_user_id,  # 자동 설정된 parent_user_id 사용
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