"""
정산 로그 API 라우터
정산 로그 조회, 생성, 수정
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from db_code.database import get_db
from models import SettlementAdmin
from datetime import date, datetime

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


# TODO: 정산 로그 목록 조회 API 구현
# - 페이지네이션 처리 (50/100/1000개씩 보기)
# - 날짜 범위 필터링 (start_date, end_date)
# - 정산 유형별 필터링 (발주/연장/환불)
# - 대행사/광고주 필터링
# - 통계 정보 포함 (조회 기간, 발주일수, 연장일수, 환불일수, 일수합계)
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
    
    TODO:
    1. 페이지네이션 계산 (offset, limit)
    2. 날짜 범위 필터링 (start_date, end_date)
    3. 검색 조건에 따른 쿼리 필터링
       - settlement_type: order/extend/refund
       - agency_user_id: 대행사 ID
       - advertiser_user_id: 광고주 ID
    4. 데이터베이스에서 정산 로그 목록 조회 (JOIN users_admin)
    5. 각 정산 로그의 대행사/광고주 정보 포함
    6. 통계 계산:
       - period_days: 조회 기간 일수
       - order_days: 발주 일수 합계
       - extend_days: 연장 일수 합계
       - refund_days: 환불 일수 합계
       - total_days: 일수 합계
    7. 응답 데이터 구성 및 반환
    """
    return {
        "success": False,
        "message": "정산 로그 목록 조회 API 구현 필요",
        "data": None
    }


# TODO: 정산 로그 상세 조회 API 구현
@router.get("/{settlement_id}")
async def get_settlement(settlement_id: int, db: Session = Depends(get_db)):
    """
    정산 로그 상세 조회 API
    
    TODO:
    1. settlement_id로 정산 로그 조회
    2. 정산 로그가 존재하지 않으면 404 에러
    3. 정산 로그 정보 반환
    """
    return {
        "success": False,
        "message": "정산 로그 상세 조회 API 구현 필요",
        "data": None
    }


# TODO: 정산 로그 생성 API 구현
# - 정산 유형 검증 (order/extend/refund)
# - 사용자 존재 확인 (agency_user_id, advertiser_user_id)
# - 광고 존재 확인 (ad_id)
# - 날짜 유효성 검증 (period_start < period_end)
# - total_days 계산
# - 정산 로그 생성 및 반환
@router.post("")
async def create_settlement(
    settlement: SettlementCreate,
    db: Session = Depends(get_db)
):
    """
    정산 로그 생성 API
    
    TODO:
    1. settlement_type 검증 (order/extend/refund)
    2. agency_user_id, advertiser_user_id 존재 확인 (필요시)
    3. ad_id 존재 확인 (필요시)
    4. 날짜 유효성 검증 (period_start < period_end)
    5. total_days 계산 (period_end - period_start + 1)
    6. 정산 로그 생성
    7. 데이터베이스 커밋
    8. 생성된 정산 로그 정보 반환
    9. 에러 처리: 존재하지 않는 사용자/광고, 잘못된 날짜
    """
    return {
        "success": False,
        "message": "정산 로그 생성 API 구현 필요",
        "data": None
    }


# TODO: 정산 로그 수정 API 구현
# - 정산 로그 존재 확인
# - 권한 검증
# - 날짜 변경 시 유효성 검증 및 total_days 재계산
# - 정산 로그 정보 업데이트
@router.put("/{settlement_id}")
async def update_settlement(
    settlement_id: int,
    settlement: SettlementUpdate,
    db: Session = Depends(get_db)
):
    """
    정산 로그 수정 API
    
    TODO:
    1. settlement_id로 정산 로그 조회
    2. 정산 로그가 존재하지 않으면 404 에러
    3. 권한 검증 (관리자만 수정 가능)
    4. 날짜 변경 시 유효성 검증
    5. total_days 재계산 (period_end - period_start + 1)
    6. 정산 로그 정보 업데이트
    7. 데이터베이스 커밋
    8. 업데이트된 정산 로그 정보 반환
    """
    return {
        "success": False,
        "message": "정산 로그 수정 API 구현 필요",
        "data": None
    }

