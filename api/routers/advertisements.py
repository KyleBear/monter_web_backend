"""
광고 관리 API 라우터
광고 조회, 생성, 수정, 삭제, 연장
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import AdvertisementsAdmin, UsersAdmin
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


@router.get("")
async def get_advertisements(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    search_type: str = Query("all"),
    search_keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    광고 목록 조회 API
    - 페이지네이션 처리
    - 검색 기능 (No, 상품명, 아이디, 키워드, 프로덕트ID, 벤더ID)
    - 상태별 필터링 (정상/오류/대기/종료예정/종료)
    - 통계 정보 포함
    """
    # 페이지네이션 계산
    offset = (page - 1) * limit
    
    # 기본 쿼리 (JOIN users_admin)
    query = db.query(AdvertisementsAdmin, UsersAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    
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
    
    # 상태별 통계 계산
    total_count = db.query(func.count(AdvertisementsAdmin.ad_id)).scalar() or 0
    normal_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.status == "normal"
    ).scalar() or 0
    error_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.status == "error"
    ).scalar() or 0
    pending_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.status == "pending"
    ).scalar() or 0
    ending_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.status == "ending"
    ).scalar() or 0
    ended_count = db.query(func.count(AdvertisementsAdmin.ad_id)).filter(
        AdvertisementsAdmin.status == "ended"
    ).scalar() or 0
    
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
async def get_advertisement(ad_id: int, db: Session = Depends(get_db)):
    """
    광고 상세 조회 API
    """
    ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고를 찾을 수 없습니다."
        )
    
    return {
        "success": True,
        "data": {
            "ad_id": ad.ad_id,
            "user_id": ad.user_id,
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
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
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
    db.commit()
    db.refresh(new_advertisement)
    
    return {
        "success": True,
        "message": "광고가 생성되었습니다.",
        "data": {
            "ad_id": new_advertisement.ad_id
        }
    }


@router.put("/{ad_id}")
async def update_advertisement(
    ad_id: int,
    advertisement: AdvertisementUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 수정 API
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
    - 하드 삭제 (실제 데이터베이스에서 삭제)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    deleted_count = 0
    not_found_ids = []
    
    for ad_id in delete_request.ad_ids:
        ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
        
        if not ad:
            not_found_ids.append(ad_id)
            continue
        
        # 광고 삭제 (하드 삭제)
        db.delete(ad)
        deleted_count += 1
    
    db.commit()
    
    if not_found_ids:
        return {
            "success": True,
            "message": f"{deleted_count}개의 광고가 삭제되었습니다. ({len(not_found_ids)}개 광고를 찾을 수 없음)",
            "data": {
                "deleted_count": deleted_count,
                "not_found_ids": not_found_ids
            }
        }
    
    return {
        "success": True,
        "message": f"선택한 {deleted_count}개의 광고가 삭제되었습니다.",
        "data": {
            "deleted_count": deleted_count
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
    - end_date에 extend_days 추가
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
    extended_ads = []
    not_found_ids = []
    ended_ads = []
    
    for ad_id in extend_request.ad_ids:
        ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
        
        if not ad:
            not_found_ids.append(ad_id)
            continue
        
        # 이미 종료된 광고는 연장 불가
        if ad.status == "ended":
            ended_ads.append(ad_id)
            continue
        
        # end_date에 extend_days 추가
        if ad.end_date:
            new_end_date = ad.end_date + timedelta(days=extend_request.extend_days)
            ad.end_date = new_end_date
            
            # work_days 재계산
            if ad.start_date:
                delta = new_end_date - ad.start_date
                ad.work_days = delta.days + 1
            
            ad.updated_at = datetime.now()
            extended_ads.append({
                "ad_id": ad.ad_id,
                "new_end_date": new_end_date.isoformat()
            })
    
    db.commit()
    
    message_parts = []
    if extended_ads:
        message_parts.append(f"{len(extended_ads)}개의 광고가 연장되었습니다.")
    if not_found_ids:
        message_parts.append(f"{len(not_found_ids)}개 광고를 찾을 수 없습니다.")
    if ended_ads:
        message_parts.append(f"{len(ended_ads)}개 광고는 이미 종료되어 연장할 수 없습니다.")
    
    return {
        "success": True,
        "message": " ".join(message_parts) if message_parts else "광고 연장이 완료되었습니다.",
        "data": {
            "extended_count": len(extended_ads),
            "extended_ads": extended_ads,
            "not_found_ids": not_found_ids,
            "ended_ads": ended_ads
        }
    }

