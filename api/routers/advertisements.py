"""
광고 관리 API 라우터
광고 조회, 생성, 수정, 삭제, 연장
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import AdvertisementsAdmin, UsersAdmin, SettlementAdmin
from utils.time_check import check_edit_time_allowed
from utils.auth_helpers import get_current_user
from datetime import date, datetime, timedelta

router = APIRouter()


# 요청/응답 모델
class AdvertisementCreate(BaseModel):
    user_id: int
    main_keyword: str
    price_comparison: bool = False
    plus: bool = False
    product_name: Optional[str] = None
    product_mid: Optional[str] = None
    price_comparison_mid: Optional[str] = None
    work_days: int
    start_date: date
    end_date: date


class AdvertisementUpdate(BaseModel):
    status: Optional[str] = None
    main_keyword: Optional[str] = None
    price_comparison: Optional[bool] = None
    plus: Optional[bool] = None
    product_name: Optional[str] = None
    product_mid: Optional[str] = None
    price_comparison_mid: Optional[str] = None
    work_days: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class AdvertisementDelete(BaseModel):
    ad_ids: List[int]


class AdvertisementExtend(BaseModel):
    ad_ids: List[int]
    extend_days: int


def _apply_advertisement_permission_filter(
    query,
    current_user: dict,
    db: Session
):
    """
    광고 조회 권한에 따른 필터링 적용
    계정 조회 로직과 동일하게 적용
    """
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    current_user_id = current_user.get("user_id")
    
    # 슈퍼유저는 모든 광고 조회 가능
    if current_username in ["admin", "monter"]:
        return query  # 필터링 없음
    
    if current_role == "total":  # 총판사
        # 자신 + 직접 하위 대행사 + 그 대행사들의 광고주가 등록한 광고
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == current_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        
        filter_conditions = [
            AdvertisementsAdmin.user_id == current_user_id,  # 자신
            UsersAdmin.parent_user_id == current_user_id,  # 직접 하위 (대행사)
        ]
        
        # 간접 하위 (대행사의 광고주) - agency_ids가 있을 때만 추가
        if agency_ids:
            filter_conditions.append(UsersAdmin.parent_user_id.in_(agency_ids))
        
        return query.filter(or_(*filter_conditions))
    
    elif current_role == "agency":  # 대행사
        # 자신 + 직접 하위 광고주가 등록한 광고만
        return query.filter(
            or_(
                AdvertisementsAdmin.user_id == current_user_id,  # 자신
                and_(
                    UsersAdmin.parent_user_id == current_user_id,
                    UsersAdmin.role == "advertiser"
                )  # 직접 하위 (광고주)
            )
        )
    
    elif current_role == "advertiser":  # 광고주
        # 자신이 등록한 광고만 조회
        return query.filter(AdvertisementsAdmin.user_id == current_user_id)
    
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한이 없습니다."
        )


def _check_advertisement_ownership(
    ad: AdvertisementsAdmin,
    current_user: dict,
    db: Session
) -> bool:
    """
    광고 소유권 체크 (등록/수정/삭제 시 사용)
    - 총판사: 자신 + 직접 하위 대행사 + 그 대행사들의 광고주가 등록한 광고 수정 가능
    - 대행사: 자신 + 직접 하위 광고주가 등록한 광고 수정 가능
    - 광고주: 자신이 등록한 광고만 수정 가능
    """
    current_user_id = current_user.get("user_id")
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 슈퍼유저는 모든 광고 수정/삭제 가능
    if current_username in ["admin", "monter"]:
        return True
    
    # 광고주 정보 조회
    advertiser = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
    if not advertiser:
        return False
    
    # 자신이 등록한 광고는 항상 수정 가능
    if ad.user_id == current_user_id:
        return True
    
    if current_role == "total":  # 총판사
        # 직접 하위 대행사가 등록한 광고
        if advertiser.parent_user_id == current_user_id and advertiser.role == "agency":
            return True
        
        # 간접 하위 (대행사의 광고주)가 등록한 광고
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == current_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        if advertiser.parent_user_id in agency_ids and advertiser.role == "advertiser":
            return True
        
        return False
    
    elif current_role == "agency":  # 대행사
        # 직접 하위 광고주가 등록한 광고만 수정 가능
        if advertiser.parent_user_id == current_user_id and advertiser.role == "advertiser":
            return True
        
        return False
    
    elif current_role == "advertiser":  # 광고주
        # 자신이 등록한 광고만 수정 가능
        return ad.user_id == current_user_id
    
    return False


@router.get("")
async def get_advertisements(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    search_type: str = Query("all"),
    search_keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    광고 목록 조회 API
    - 페이지네이션 처리
    - 검색 기능 (No, 상품명, 아이디, 키워드, 프로덕트ID, 벤더ID)
    - 상태별 필터링 (정상/오류/대기/종료예정/종료)
    - 권한 기반 필터링 (화면 시작 시부터 적용)
    - 통계 정보 포함
    """
    # 페이지네이션 계산
    offset = (page - 1) * limit
    
    # 기본 쿼리 (JOIN users_admin)
    query = db.query(AdvertisementsAdmin, UsersAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    
    # 권한에 따른 조회 범위 필터링 (가장 먼저 적용 - 화면 시작 시부터)
    query = _apply_advertisement_permission_filter(query, current_user, db)
    
    # 상태 필터링
    if status:
        query = query.filter(AdvertisementsAdmin.status == status)
    
    # 검색 필터링
    if search_keyword:
        if search_type == "no":
            try:
                ad_id = int(search_keyword)
                query = query.filter(AdvertisementsAdmin.ad_id == ad_id)
            except ValueError:
                query = query.filter(False)  # 숫자가 아니면 결과 없음
        elif search_type == "product_name":
            query = query.filter(AdvertisementsAdmin.product_name.contains(search_keyword))
        elif search_type == "userid":
            query = query.filter(UsersAdmin.username.contains(search_keyword))
        elif search_type == "keyword":
            query = query.filter(AdvertisementsAdmin.main_keyword.contains(search_keyword))
        elif search_type == "product_id":
            query = query.filter(AdvertisementsAdmin.product_mid.contains(search_keyword))
        elif search_type == "vendor_id":
            query = query.filter(AdvertisementsAdmin.price_comparison_mid.contains(search_keyword))
        elif search_type == "all":
            query = query.filter(
                or_(
                    AdvertisementsAdmin.product_name.contains(search_keyword),
                    UsersAdmin.username.contains(search_keyword),
                    AdvertisementsAdmin.main_keyword.contains(search_keyword),
                    AdvertisementsAdmin.product_mid.contains(search_keyword),
                    AdvertisementsAdmin.price_comparison_mid.contains(search_keyword)
                )
            )
    
    # 전체 개수 조회
    total = query.count()
    
    # 페이지네이션 적용
    results = query.offset(offset).limit(limit).all()
    
    # 광고 목록 구성
    advertisement_list = []
    for ad, user in results:
        advertisement_list.append({
            "ad_id": ad.ad_id,
            "user_id": ad.user_id,
            "username": user.username,
            "status": ad.status,
            "main_keyword": ad.main_keyword,
            "price_comparison": ad.price_comparison,
            "plus": ad.plus,
            "product_name": ad.product_name or "",
            "product_mid": ad.product_mid or "",
            "price_comparison_mid": ad.price_comparison_mid or "",
            "work_days": ad.work_days,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "created_at": ad.created_at.isoformat() if ad.created_at else None
        })
    
    # 상태별 통계 계산 (권한 범위 내에서만)
    stats_query = db.query(AdvertisementsAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    stats_query = _apply_advertisement_permission_filter(stats_query, current_user, db)
    
    total_count = stats_query.count()
    normal_count = stats_query.filter(AdvertisementsAdmin.status == "normal").count()
    error_count = stats_query.filter(AdvertisementsAdmin.status == "error").count()
    pending_count = stats_query.filter(AdvertisementsAdmin.status == "pending").count()
    ending_count = stats_query.filter(AdvertisementsAdmin.status == "ending").count()
    ended_count = stats_query.filter(AdvertisementsAdmin.status == "ended").count()
    
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    
    return {
        "success": True,
        "data": {
            "advertisements": advertisement_list,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        },
        "stats": {
            "total": total_count,
            "normal": normal_count,
            "error": error_count,
            "pending": pending_count,
            "ending": ending_count,
            "ended": ended_count
        }
    }


@router.get("/{ad_id}")
async def get_advertisement(
    ad_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    광고 상세 조회 API
    - 권한 체크 포함
    """
    ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고를 찾을 수 없습니다."
        )
    
    # 권한 체크 (조회 가능한 광고인지 확인)
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고 소유자를 찾을 수 없습니다."
        )
    
    # 권한 필터링 적용하여 조회 가능한지 확인
    query = db.query(AdvertisementsAdmin, UsersAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    ).filter(AdvertisementsAdmin.ad_id == ad_id)
    
    query = _apply_advertisement_permission_filter(query, current_user, db)
    result = query.first()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 광고를 조회할 권한이 없습니다."
        )
    
    ad, user = result
    
    return {
        "success": True,
        "data": {
            "ad_id": ad.ad_id,
            "user_id": ad.user_id,
            "username": user.username,
            "status": ad.status,
            "main_keyword": ad.main_keyword,
            "price_comparison": ad.price_comparison,
            "plus": ad.plus,
            "product_name": ad.product_name,
            "product_mid": ad.product_mid,
            "price_comparison_mid": ad.price_comparison_mid,
            "work_days": ad.work_days,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "created_at": ad.created_at.isoformat() if ad.created_at else None,
            "updated_at": ad.updated_at.isoformat() if ad.updated_at else None
        }
    }


@router.post("")
async def create_advertisement(
    advertisement: AdvertisementCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 생성 API
    - 자신의 user_id만 사용 가능 (자신의 광고만 등록 가능)
    - 광고 등록과 동시에 정산 로그 생성 (order 타입)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    current_user_id = current_user.get("user_id")
    current_username = current_user.get("username")
    
    # 슈퍼유저가 아니면 자신의 user_id만 사용 가능
    if current_username not in ["admin", "monter"]:
        if advertisement.user_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="자신의 광고만 등록할 수 있습니다."
            )
    
    # 사용자 존재 확인
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == advertisement.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다."
        )
    
    # 날짜 유효성 검증
    if advertisement.start_date >= advertisement.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="시작일은 종료일보다 이전이어야 합니다."
        )
    
    # work_days 계산 (날짜 차이)
    delta = advertisement.end_date - advertisement.start_date
    work_days = delta.days + 1  # 시작일과 종료일 포함
    
    # 트랜잭션 시작 (광고 생성 + 정산 로그 생성)
    try:
        # 광고 생성 (status 기본값: 'pending')
        new_advertisement = AdvertisementsAdmin(
            user_id=advertisement.user_id,
            status="pending",
            main_keyword=advertisement.main_keyword,
            price_comparison=advertisement.price_comparison,
            plus=advertisement.plus,
            product_name=advertisement.product_name,
            product_mid=advertisement.product_mid,
            price_comparison_mid=advertisement.price_comparison_mid,
            work_days=work_days,
            start_date=advertisement.start_date,
            end_date=advertisement.end_date
        )
        
        db.add(new_advertisement)
        db.flush()  # ad_id를 얻기 위해 flush
        
        # 정산 로그 생성 (order 타입)
        # 대행사 ID 찾기 (광고주의 parent_user_id)
        agency_user_id = user.parent_user_id if user.role == "advertiser" else None
        
        new_settlement = SettlementAdmin(
            settlement_type="order",
            agency_user_id=agency_user_id,
            advertiser_user_id=advertisement.user_id,
            ad_id=new_advertisement.ad_id,
            quantity=1,
            period_start=advertisement.start_date,
            period_end=advertisement.end_date,
            total_days=work_days,
            start_date=advertisement.start_date
        )
        
        db.add(new_settlement)
        db.commit()
        db.refresh(new_advertisement)
        db.refresh(new_settlement)
        
        return {
            "success": True,
            "message": "광고가 생성되었습니다.",
            "data": {
                "ad_id": new_advertisement.ad_id,
                "settlement_id": new_settlement.settlement_id
            }
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"광고 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/{ad_id}")
async def update_advertisement(
    ad_id: int,
    advertisement: AdvertisementUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 수정 API
    - 자신의 광고만 수정 가능
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    # 광고 조회
    ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고를 찾을 수 없습니다."
        )
    
    # 권한 체크 (총판사/대행사는 하위 계정의 광고도 수정 가능)
    if not _check_advertisement_ownership(ad, current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 광고를 수정할 권한이 없습니다."
        )
    
    # 종료된 광고는 수정 불가
    if ad.status == "ended":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="종료된 광고는 수정할 수 없습니다."
        )
    
    # 상태 변경
    if advertisement.status:
        valid_statuses = ["normal", "error", "pending", "ending", "ended"]
        if advertisement.status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 상태입니다. 가능한 상태: {', '.join(valid_statuses)}"
            )
        ad.status = advertisement.status
    
    # 메인 키워드 변경
    if advertisement.main_keyword:
        ad.main_keyword = advertisement.main_keyword
    
    # 가격비교 변경
    if advertisement.price_comparison is not None:
        ad.price_comparison = advertisement.price_comparison
    
    # 플러스 변경
    if advertisement.plus is not None:
        ad.plus = advertisement.plus
    
    # 상품명 변경
    if advertisement.product_name is not None:
        ad.product_name = advertisement.product_name
    
    # 상품 MID 변경
    if advertisement.product_mid is not None:
        ad.product_mid = advertisement.product_mid
    
    # 가격비교 MID 변경
    if advertisement.price_comparison_mid is not None:
        ad.price_comparison_mid = advertisement.price_comparison_mid
    
    # 날짜 변경
    start_date = advertisement.start_date if advertisement.start_date else ad.start_date
    end_date = advertisement.end_date if advertisement.end_date else ad.end_date
    
    if advertisement.start_date or advertisement.end_date:
        if start_date >= end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="시작일은 종료일보다 이전이어야 합니다."
            )
        ad.start_date = start_date
        ad.end_date = end_date
        
        # work_days 재계산
        delta = end_date - start_date
        ad.work_days = delta.days + 1
    elif advertisement.work_days is not None:
        ad.work_days = advertisement.work_days
    
    ad.updated_at = datetime.now()
    
    db.commit()
    db.refresh(ad)
    
    return {
        "success": True,
        "message": "광고가 수정되었습니다.",
        "data": {
            "ad_id": ad.ad_id
        }
    }


@router.delete("")
async def delete_advertisements(
    delete_request: AdvertisementDelete,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 삭제 API
    - 여러 광고 일괄 삭제
    - 자신의 광고만 삭제 가능
    - 하드 삭제 (실제 데이터베이스에서 삭제)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    deleted_count = 0
    not_found_ids = []
    unauthorized_ids = []
    
    for ad_id in delete_request.ad_ids:
        ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
        
        if not ad:
            not_found_ids.append(ad_id)
            continue
        
        # 권한 체크 (총판사/대행사는 하위 계정의 광고도 삭제 가능)
        if not _check_advertisement_ownership(ad, current_user, db):
            unauthorized_ids.append(ad_id)
            continue
        
        # 광고 삭제 (하드 삭제)
        db.delete(ad)
        deleted_count += 1
    
    db.commit()
    
    message_parts = []
    if deleted_count > 0:
        message_parts.append(f"{deleted_count}개의 광고가 삭제되었습니다.")
    if not_found_ids:
        message_parts.append(f"{len(not_found_ids)}개 광고를 찾을 수 없습니다.")
    if unauthorized_ids:
        message_parts.append(f"{len(unauthorized_ids)}개 광고는 삭제 권한이 없습니다.")
    
    return {
        "success": True,
        "message": " ".join(message_parts) if message_parts else "광고 삭제가 완료되었습니다.",
        "data": {
            "deleted_count": deleted_count,
            "not_found_ids": not_found_ids,
            "unauthorized_ids": unauthorized_ids
        }
    }


@router.post("/extend")
async def extend_advertisements(
    extend_request: AdvertisementExtend,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 연장 API
    - 여러 광고 일괄 연장
    - 자신의 광고만 연장 가능
    - end_date에 extend_days 추가
    - 광고 연장과 동시에 정산 로그 생성 (extend 타입)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    extended_ads = []
    not_found_ids = []
    ended_ads = []
    unauthorized_ids = []
    failed_ads = []  # 정산 로그 생성 실패한 광고
    
    for ad_id in extend_request.ad_ids:
        # 트랜잭션 시작
        try:
            ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
            
            if not ad:
                not_found_ids.append(ad_id)
                continue
            
        # 권한 체크 (총판사/대행사는 하위 계정의 광고도 연장 가능)
        if not _check_advertisement_ownership(ad, current_user, db):
            unauthorized_ids.append(ad_id)
            continue
            
            # 이미 종료된 광고는 연장 불가
            if ad.status == "ended":
                ended_ads.append(ad_id)
                continue
            
            # 광고주 정보 조회 (대행사 ID 찾기 위해)
            user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
            if not user:
                failed_ads.append({"ad_id": ad_id, "reason": "광고주 정보를 찾을 수 없습니다."})
                continue
            
            # end_date에 extend_days 추가
            if ad.end_date:
                old_end_date = ad.end_date
                new_end_date = ad.end_date + timedelta(days=extend_request.extend_days)
                ad.end_date = new_end_date
                
                # work_days 재계산
                if ad.start_date:
                    delta = new_end_date - ad.start_date
                    ad.work_days = delta.days + 1
                
                ad.updated_at = datetime.now()
                
                # 정산 로그 생성 (extend 타입)
                # 대행사 ID 찾기 (광고주의 parent_user_id)
                agency_user_id = user.parent_user_id if user.role == "advertiser" else None
                
                # 연장 기간 계산 (기존 종료일 다음날부터 새 종료일까지)
                extend_period_start = old_end_date + timedelta(days=1)
                extend_period_end = new_end_date
                extend_total_days = extend_request.extend_days
                
                new_settlement = SettlementAdmin(
                    settlement_type="extend",
                    agency_user_id=agency_user_id,
                    advertiser_user_id=ad.user_id,
                    ad_id=ad.ad_id,
                    quantity=1,
                    period_start=extend_period_start,
                    period_end=extend_period_end,
                    total_days=extend_total_days,
                    start_date=extend_period_start
                )
                
                db.add(new_settlement)
                db.flush()  # settlement_id를 얻기 위해 flush
                
                extended_ads.append({
                    "ad_id": ad.ad_id,
                    "new_end_date": new_end_date.isoformat(),
                    "settlement_id": new_settlement.settlement_id
                })
            else:
                failed_ads.append({"ad_id": ad_id, "reason": "종료일 정보가 없습니다."})
                continue
        
        except Exception as e:
            db.rollback()
            failed_ads.append({"ad_id": ad_id, "reason": f"연장 처리 중 오류: {str(e)}"})
            continue
    
    # 모든 작업이 성공한 경우에만 commit
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"광고 연장 중 오류가 발생했습니다: {str(e)}"
        )
    
    message_parts = []
    if extended_ads:
        message_parts.append(f"{len(extended_ads)}개의 광고가 연장되었습니다.")
    if not_found_ids:
        message_parts.append(f"{len(not_found_ids)}개 광고를 찾을 수 없습니다.")
    if ended_ads:
        message_parts.append(f"{len(ended_ads)}개 광고는 이미 종료되어 연장할 수 없습니다.")
    if unauthorized_ids:
        message_parts.append(f"{len(unauthorized_ids)}개 광고는 연장 권한이 없습니다.")
    if failed_ads:
        message_parts.append(f"{len(failed_ads)}개 광고는 정산 로그 생성 실패로 연장되지 않았습니다.")
    
    return {
        "success": True,
        "message": " ".join(message_parts) if message_parts else "광고 연장이 완료되었습니다.",
        "data": {
            "extended_count": len(extended_ads),
            "extended_ads": extended_ads,
            "not_found_ids": not_found_ids,
            "ended_ads": ended_ads,
            "unauthorized_ids": unauthorized_ids,
            "failed_ads": failed_ads
        }
    }

