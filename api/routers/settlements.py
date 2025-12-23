"""
정산 로그 API 라우터
정산 로그 조회 (시간별 조회)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from typing import Optional
from database import get_db
from models import SettlementAdmin, UsersAdmin, AdvertisementsAdmin
from utils.auth_helpers import get_current_user
from datetime import date, datetime, timedelta

router = APIRouter()


def _apply_settlement_permission_filter(
    query,
    current_user: dict,
    db: Session
):
    """
    정산 로그 조회 권한에 따른 필터링 적용
    계급구조와 소속 기반 필터링
    - 총판사: 자신 + 직접 하위 대행사 + 그 대행사들의 광고주가 등록한 광고의 정산 로그
    - 대행사: 자신 + 직접 하위 광고주가 등록한 광고의 정산 로그
    - 광고주: 자신이 등록한 광고의 정산 로그만
    username 기반으로 실제 user_id 조회 후 필터링
    """
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 슈퍼유저는 모든 정산 로그 조회 가능
    if current_username in ["admin", "monter"]:
        return query  # 필터링 없음
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 정보를 찾을 수 없습니다."
        )
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    if actual_role != current_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한 정보가 일치하지 않습니다. 다시 로그인해주세요."
        )
    
    if actual_role == "total":  # 총판사
        # 자신 + 직접 하위 대행사 + 그 대행사들의 광고주가 등록한 광고의 정산 로그
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        
        # 조회 가능한 광고주 ID 목록 구성
        allowed_advertiser_ids = [actual_user_id]  # 자신
        
        # 직접 하위 대행사 (대행사가 광고를 등록한 경우)
        if agency_ids:
            allowed_advertiser_ids.extend(agency_ids)
        
        # 간접 하위 (대행사의 광고주)
        if agency_ids:
            advertiser_ids = db.query(UsersAdmin.user_id).filter(
                UsersAdmin.parent_user_id.in_(agency_ids),
                UsersAdmin.role == "advertiser"
            ).all()
            advertiser_id_list = [adv[0] for adv in advertiser_ids]
            if advertiser_id_list:
                allowed_advertiser_ids.extend(advertiser_id_list)
        
        return query.filter(SettlementAdmin.advertiser_user_id.in_(allowed_advertiser_ids))
    
    elif actual_role == "agency":  # 대행사
        # 자신 + 직접 하위 광고주가 등록한 광고의 정산 로그만
        advertiser_ids = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "advertiser"
        ).all()
        advertiser_id_list = [adv[0] for adv in advertiser_ids]
        
        # 조회 가능한 광고주 ID 목록 구성
        allowed_advertiser_ids = [actual_user_id]  # 자신
        
        if advertiser_id_list:
            allowed_advertiser_ids.extend(advertiser_id_list)
        
        return query.filter(SettlementAdmin.advertiser_user_id.in_(allowed_advertiser_ids))
    
    elif actual_role == "advertiser":  # 광고주
        # 자신이 등록한 광고의 정산 로그만 조회
        return query.filter(SettlementAdmin.advertiser_user_id == actual_user_id)
    
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한이 없습니다."
        )


@router.get("")
async def get_settlements(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
    start_datetime: Optional[datetime] = Query(None, description="시작 시간 (YYYY-MM-DDTHH:mm:ss)"),
    end_datetime: Optional[datetime] = Query(None, description="종료 시간 (YYYY-MM-DDTHH:mm:ss)"),
    settlement_type: Optional[str] = Query(None),
    agency_user_id: Optional[int] = Query(None),
    advertiser_user_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    정산 로그 시간별 조회 API
    - 페이지네이션 처리 (50/100/1000개씩 보기)
    - 시간 범위 필터링 (created_at 기준)
    - 정산 유형별 필터링
    - 계급구조와 소속 기반 필터링 (화면 시작 시부터 적용)
    - 통계 정보 포함
    """
    # 페이지네이션 계산
    offset = (page - 1) * limit
    
    # 기본 쿼리
    query = db.query(SettlementAdmin)
    
    # 권한에 따른 조회 범위 필터링 (가장 먼저 적용 - 화면 시작 시부터)
    query = _apply_settlement_permission_filter(query, current_user, db)
    
    # 시간 범위 필터링 (created_at 기준)
    if start_datetime:
        query = query.filter(SettlementAdmin.created_at >= start_datetime)
    if end_datetime:
        query = query.filter(SettlementAdmin.created_at <= end_datetime)
    
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
    
    # 통계 계산 (권한 범위 내에서만)
    stats_query = db.query(SettlementAdmin)
    
    # 권한에 따른 조회 범위 필터링 적용
    stats_query = _apply_settlement_permission_filter(stats_query, current_user, db)
    
    # 시간 범위 필터링 적용
    if start_datetime:
        stats_query = stats_query.filter(SettlementAdmin.created_at >= start_datetime)
    if end_datetime:
        stats_query = stats_query.filter(SettlementAdmin.created_at <= end_datetime)
    
    # 조회 기간 일수 계산 (start_date 기준)
    if start_datetime and end_datetime:
        # created_at의 날짜 범위로 계산
        period_days = (end_datetime.date() - start_datetime.date()).days + 1
    elif start_datetime:
        period_days = (date.today() - start_datetime.date()).days + 1
    elif end_datetime:
        period_days = (end_datetime.date() - date.today()).days + 1
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