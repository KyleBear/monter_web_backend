"""
정산 로그 API 라우터
정산 로그 조회, 생성, 수정
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from database import get_db
from models import SettlementAdmin, UsersAdmin, AdvertisementsAdmin
from utils.time_check import check_edit_time_allowed
from datetime import date, datetime, timedelta

router = APIRouter()


# 요청/응답 모델
class SettlementCreate(BaseModel):
    settlement_type: str  # order/extend/refund
    agency_user_id: Optional[int] = None
    advertiser_user_id: Optional[int] = None
    ad_id: Optional[int] = None
    quantity: int
    period_start: date
    period_end: date
    start_date: date


class SettlementUpdate(BaseModel):
    settlement_type: Optional[str] = None
    quantity: Optional[int] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    start_date: Optional[date] = None


@router.get("")
async def get_settlements(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    settlement_type: Optional[str] = Query(None),
    agency_user_id: Optional[int] = Query(None),
    advertiser_user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """
    정산 로그 목록 조회 API
    - 페이지네이션 처리 (50/100/1000개씩 보기)
    - 날짜 범위 필터링
    - 정산 유형별 필터링
    - 통계 정보 포함
    """
    # 페이지네이션 계산
    offset = (page - 1) * limit
    
    # 기본 쿼리
    query = db.query(SettlementAdmin)
    
    # 날짜 범위 필터링 (start_date 기준)
    if start_date:
        query = query.filter(SettlementAdmin.start_date >= start_date)
    if end_date:
        query = query.filter(SettlementAdmin.start_date <= end_date)
    
    # 정산 유형 필터링
    if settlement_type:
        query = query.filter(SettlementAdmin.settlement_type == settlement_type)
    
    # 대행사 필터링
    if agency_user_id:
        query = query.filter(SettlementAdmin.agency_user_id == agency_user_id)
    
    # 광고주 필터링
    if advertiser_user_id:
        query = query.filter(SettlementAdmin.advertiser_user_id == advertiser_user_id)
    
    # 전체 개수 조회
    total = query.count()
    
    # 페이지네이션 적용
    settlements = query.order_by(SettlementAdmin.created_at.desc()).offset(offset).limit(limit).all()
    
    # 정산 로그 목록 구성
    settlement_list = []
    for settlement in settlements:
        # 대행사 정보 조회
        agency_username = None
        if settlement.agency_user_id:
            agency = db.query(UsersAdmin).filter(UsersAdmin.user_id == settlement.agency_user_id).first()
            agency_username = agency.username if agency else None
        
        # 광고주 정보 조회
        advertiser_username = None
        if settlement.advertiser_user_id:
            advertiser = db.query(UsersAdmin).filter(UsersAdmin.user_id == settlement.advertiser_user_id).first()
            advertiser_username = advertiser.username if advertiser else None
        
        settlement_list.append({
            "settlement_id": settlement.settlement_id,
            "settlement_type": settlement.settlement_type,
            "agency_user_id": settlement.agency_user_id,
            "agency_username": agency_username,
            "advertiser_user_id": settlement.advertiser_user_id,
            "advertiser_username": advertiser_username,
            "ad_id": settlement.ad_id,
            "quantity": settlement.quantity,
            "period_start": settlement.period_start.isoformat() if settlement.period_start else None,
            "period_end": settlement.period_end.isoformat() if settlement.period_end else None,
            "total_days": settlement.total_days,
            "created_at": settlement.created_at.isoformat() if settlement.created_at else None,
            "start_date": settlement.start_date.isoformat() if settlement.start_date else None
        })
    
    # 통계 계산
    stats_query = db.query(SettlementAdmin)
    
    # 날짜 범위 필터링 적용
    if start_date:
        stats_query = stats_query.filter(SettlementAdmin.start_date >= start_date)
    if end_date:
        stats_query = stats_query.filter(SettlementAdmin.start_date <= end_date)
    
    # 조회 기간 일수 계산
    if start_date and end_date:
        period_days = (end_date - start_date).days + 1
    elif start_date:
        period_days = (date.today() - start_date).days + 1
    elif end_date:
        period_days = (end_date - date.today()).days + 1
    else:
        period_days = 0
    
    # 발주 일수 합계
    order_days = stats_query.filter(
        SettlementAdmin.settlement_type == "order"
    ).with_entities(func.sum(SettlementAdmin.total_days)).scalar() or 0
    
    # 연장 일수 합계
    extend_days = stats_query.filter(
        SettlementAdmin.settlement_type == "extend"
    ).with_entities(func.sum(SettlementAdmin.total_days)).scalar() or 0
    
    # 환불 일수 합계
    refund_days = stats_query.filter(
        SettlementAdmin.settlement_type == "refund"
    ).with_entities(func.sum(SettlementAdmin.total_days)).scalar() or 0
    
    # 일수 합계
    total_days = (order_days or 0) + (extend_days or 0) + (refund_days or 0)
    
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    
    return {
        "success": True,
        "data": {
            "settlements": settlement_list,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        },
        "stats": {
            "period_days": period_days,
            "order_days": order_days or 0,
            "extend_days": extend_days or 0,
            "refund_days": refund_days or 0,
            "total_days": total_days
        }
    }


@router.get("/{settlement_id}")
async def get_settlement(settlement_id: int, db: Session = Depends(get_db)):
    """
    정산 로그 상세 조회 API
    """
    settlement = db.query(SettlementAdmin).filter(
        SettlementAdmin.settlement_id == settlement_id
    ).first()
    
    if not settlement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="정산 로그를 찾을 수 없습니다."
        )
    
    return {
        "success": True,
        "data": {
            "settlement_id": settlement.settlement_id,
            "settlement_type": settlement.settlement_type,
            "agency_user_id": settlement.agency_user_id,
            "advertiser_user_id": settlement.advertiser_user_id,
            "ad_id": settlement.ad_id,
            "quantity": settlement.quantity,
            "period_start": settlement.period_start.isoformat() if settlement.period_start else None,
            "period_end": settlement.period_end.isoformat() if settlement.period_end else None,
            "total_days": settlement.total_days,
            "created_at": settlement.created_at.isoformat() if settlement.created_at else None,
            "start_date": settlement.start_date.isoformat() if settlement.start_date else None
        }
    }


@router.post("")
async def create_settlement(
    settlement: SettlementCreate,
    db: Session = Depends(get_db)
):
    """
    정산 로그 생성 API
    """
    # 오후 4시 30분 이후 수정 차단
    check_edit_time_allowed()
    
    # 정산 유형 검증
    valid_types = ["order", "extend", "refund"]
    if settlement.settlement_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"유효하지 않은 정산 유형입니다. 가능한 유형: {', '.join(valid_types)}"
        )
    
    # 대행사 존재 확인
    if settlement.agency_user_id:
        agency = db.query(UsersAdmin).filter(UsersAdmin.user_id == settlement.agency_user_id).first()
        if not agency:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="대행사 계정을 찾을 수 없습니다."
            )
    
    # 광고주 존재 확인
    if settlement.advertiser_user_id:
        advertiser = db.query(UsersAdmin).filter(UsersAdmin.user_id == settlement.advertiser_user_id).first()
        if not advertiser:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="광고주 계정을 찾을 수 없습니다."
            )
    
    # 광고 존재 확인
    if settlement.ad_id:
        ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == settlement.ad_id).first()
        if not ad:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="광고를 찾을 수 없습니다."
            )
    
    # 날짜 유효성 검증
    if settlement.period_start >= settlement.period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="기간 시작일은 기간 종료일보다 이전이어야 합니다."
        )
    
    # total_days 계산
    delta = settlement.period_end - settlement.period_start
    total_days = delta.days + 1  # 시작일과 종료일 포함
    
    # 정산 로그 생성
    new_settlement = SettlementAdmin(
        settlement_type=settlement.settlement_type,
        agency_user_id=settlement.agency_user_id,
        advertiser_user_id=settlement.advertiser_user_id,
        ad_id=settlement.ad_id,
        quantity=settlement.quantity,
        period_start=settlement.period_start,
        period_end=settlement.period_end,
        total_days=total_days,
        start_date=settlement.start_date
    )
    
    db.add(new_settlement)
    db.commit()
    db.refresh(new_settlement)
    
    return {
        "success": True,
        "message": "정산 로그가 생성되었습니다.",
        "data": {
            "settlement_id": new_settlement.settlement_id,
            "total_days": new_settlement.total_days
        }
    }


@router.put("/{settlement_id}")
async def update_settlement(
    settlement_id: int,
    settlement: SettlementUpdate,
    db: Session = Depends(get_db)
):
    """
    정산 로그 수정 API
    """
    # 오후 4시 30분 이후 수정 차단
    check_edit_time_allowed()
    
    # 정산 로그 조회
    stmt = db.query(SettlementAdmin).filter(SettlementAdmin.settlement_id == settlement_id).first()
    
    if not stmt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="정산 로그를 찾을 수 없습니다."
        )
    
    # 정산 유형 변경
    if settlement.settlement_type:
        valid_types = ["order", "extend", "refund"]
        if settlement.settlement_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 정산 유형입니다. 가능한 유형: {', '.join(valid_types)}"
            )
        stmt.settlement_type = settlement.settlement_type
    
    # 수량 변경
    if settlement.quantity is not None:
        stmt.quantity = settlement.quantity
    
    # 날짜 변경
    period_start = settlement.period_start if settlement.period_start else stmt.period_start
    period_end = settlement.period_end if settlement.period_end else stmt.period_end
    
    if settlement.period_start or settlement.period_end:
        if period_start >= period_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="기간 시작일은 기간 종료일보다 이전이어야 합니다."
            )
        stmt.period_start = period_start
        stmt.period_end = period_end
        
        # total_days 재계산
        delta = period_end - period_start
        stmt.total_days = delta.days + 1
    
    # 시작일 변경
    if settlement.start_date:
        stmt.start_date = settlement.start_date
    
    db.commit()
    db.refresh(stmt)
    
    return {
        "success": True,
        "message": "정산 로그가 수정되었습니다.",
        "data": {
            "settlement_id": stmt.settlement_id
        }
    }

