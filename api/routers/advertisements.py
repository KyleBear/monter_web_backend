"""
광고 관리 API 라우터
광고 조회, 생성, 수정, 삭제, 연장
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from db_code.database import get_db
from models import AdvertisementsAdmin
from datetime import date, datetime

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


# TODO: 광고 목록 조회 API 구현
# - 페이지네이션 처리
# - 검색 기능 (No, 상품명, 아이디, 키워드, 프로덕트ID, 벤더ID)
# - 상태별 필터링 (정상/오류/대기/종료예정/종료)
# - 통계 정보 포함 (전체, 상태별 수)
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
    
    TODO:
    1. 페이지네이션 계산 (offset, limit)
    2. 검색 조건에 따른 쿼리 필터링
       - search_type: all/no/product_name/userid/keyword/product_id/vendor_id
       - search_keyword: 검색어
       - status: normal/error/pending/ending/ended
    3. 데이터베이스에서 광고 목록 조회 (JOIN users_admin)
    4. 각 광고의 사용자 정보 포함
    5. 상태별 통계 계산
    6. 응답 데이터 구성 및 반환
    """
    return {
        "success": False,
        "message": "광고 목록 조회 API 구현 필요",
        "data": None
    }


# TODO: 광고 상세 조회 API 구현
@router.get("/{ad_id}")
async def get_advertisement(ad_id: int, db: Session = Depends(get_db)):
    """
    광고 상세 조회 API
    
    TODO:
    1. ad_id로 광고 조회
    2. 광고가 존재하지 않으면 404 에러
    3. 광고 정보 반환
    """
    return {
        "success": False,
        "message": "광고 상세 조회 API 구현 필요",
        "data": None
    }


# TODO: 광고 생성 API 구현
# - 사용자 존재 확인
# - 날짜 유효성 검증 (start_date < end_date)
# - 광고 생성 및 반환
@router.post("")
async def create_advertisement(
    advertisement: AdvertisementCreate,
    db: Session = Depends(get_db)
):
    """
    광고 생성 API
    
    TODO:
    1. user_id로 사용자 존재 확인
    2. 날짜 유효성 검증 (start_date < end_date)
    3. work_days 계산 또는 검증
    4. 광고 생성 (status 기본값: 'pending')
    5. 데이터베이스 커밋
    6. 생성된 광고 정보 반환
    7. 에러 처리: 존재하지 않는 사용자, 잘못된 날짜
    """
    return {
        "success": False,
        "message": "광고 생성 API 구현 필요",
        "data": None
    }


# TODO: 광고 수정 API 구현
# - 광고 존재 확인
# - 권한 검증
# - 상태 변경 시 검증 (예: 종료된 광고는 수정 불가)
# - 광고 정보 업데이트
@router.put("/{ad_id}")
async def update_advertisement(
    ad_id: int,
    advertisement: AdvertisementUpdate,
    db: Session = Depends(get_db)
):
    """
    광고 수정 API
    
    TODO:
    1. ad_id로 광고 조회
    2. 광고가 존재하지 않으면 404 에러
    3. 권한 검증 (본인 또는 관리자만 수정 가능)
    4. 상태 변경 시 검증 (종료된 광고는 수정 불가 등)
    5. 날짜 변경 시 유효성 검증
    6. 광고 정보 업데이트
    7. 데이터베이스 커밋
    8. 업데이트된 광고 정보 반환
    """
    return {
        "success": False,
        "message": "광고 수정 API 구현 필요",
        "data": None
    }


# TODO: 광고 삭제 API 구현
# - 여러 광고 일괄 삭제
# - 관련 데이터 확인 (정산 로그 등)
# - 삭제 처리
@router.delete("")
async def delete_advertisements(
    delete_request: AdvertisementDelete,
    db: Session = Depends(get_db)
):
    """
    광고 삭제 API
    
    TODO:
    1. ad_ids 배열의 각 광고 조회
    2. 각 광고의 관련 데이터 확인 (정산 로그 등)
    3. 삭제 가능 여부 검증
    4. 광고 삭제 (소프트 삭제 또는 하드 삭제)
    5. 데이터베이스 커밋
    6. 삭제된 광고 수 반환
    7. 에러 처리: 관련 데이터가 있는 경우
    """
    return {
        "success": False,
        "message": "광고 삭제 API 구현 필요",
        "data": None
    }


# TODO: 광고 연장 API 구현
# - 여러 광고 일괄 연장
# - end_date에 extend_days 추가
# - 연장된 광고 정보 반환
@router.post("/extend")
async def extend_advertisements(
    extend_request: AdvertisementExtend,
    db: Session = Depends(get_db)
):
    """
    광고 연장 API
    
    TODO:
    1. ad_ids 배열의 각 광고 조회
    2. 각 광고의 end_date 확인
    3. end_date에 extend_days 추가하여 새로운 end_date 계산
    4. 광고 정보 업데이트 (end_date, work_days 재계산)
    5. 데이터베이스 커밋
    6. 연장된 광고 정보 반환 (ad_id, new_end_date)
    7. 에러 처리: 존재하지 않는 광고, 이미 종료된 광고
    """
    return {
        "success": False,
        "message": "광고 연장 API 구현 필요",
        "data": None
    }

