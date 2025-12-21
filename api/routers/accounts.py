"""
계정 관리 API 라우터
계정 조회, 생성, 수정, 삭제
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from db_code.database import get_db
from models import UsersAdmin
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


# TODO: 계정 목록 조회 API 구현
# - 페이지네이션 처리
# - 검색 기능 (아이디, 소속, 메모)
# - 역할별 필터링
# - 통계 정보 포함 (전체, 총판사, 대행사, 광고주 수)
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
    
    TODO:
    1. 페이지네이션 계산 (offset, limit)
    2. 검색 조건에 따른 쿼리 필터링
       - search_type: all/userid/group/memo
       - search_keyword: 검색어
       - role: 총판사/대행사/광고주
    3. 데이터베이스에서 계정 목록 조회
    4. 각 계정의 통계 정보 계산 (ad_count, active_ad_count)
    5. 전체 통계 계산 (전체, 총판사, 대행사, 광고주 수)
    6. 응답 데이터 구성 및 반환
    """
    return {
        "success": False,
        "message": "계정 목록 조회 API 구현 필요",
        "data": None
    }


# TODO: 계정 상세 조회 API 구현
@router.get("/{user_id}")
async def get_account(user_id: int, db: Session = Depends(get_db)):
    """
    계정 상세 조회 API
    
    TODO:
    1. user_id로 계정 조회
    2. 계정이 존재하지 않으면 404 에러
    3. 계정 정보 반환
    """
    return {
        "success": False,
        "message": "계정 상세 조회 API 구현 필요",
        "data": None
    }


# TODO: 계정 생성 API 구현
# - 중복 아이디 체크
# - 비밀번호 해시화
# - 역할별 parent_user_id 검증
# - 계정 생성 및 반환
@router.post("")
async def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    """
    계정 생성 API
    
    TODO:
    1. username 중복 체크
    2. 비밀번호 해시화 (bcrypt 또는 hashlib)
    3. role 검증 (총판사/대행사/광고주)
    4. parent_user_id 검증 (대행사는 총판사, 광고주는 대행사)
    5. 계정 생성
    6. 데이터베이스 커밋
    7. 생성된 계정 정보 반환
    8. 에러 처리: 중복 아이디, 잘못된 역할/상위 계정
    """
    return {
        "success": False,
        "message": "계정 생성 API 구현 필요",
        "data": None
    }


# TODO: 계정 수정 API 구현
# - 계정 존재 확인
# - 비밀번호 변경 시 해시화
# - 권한 검증 (본인 또는 관리자만 수정 가능)
# - 계정 정보 업데이트
@router.put("/{user_id}")
async def update_account(
    user_id: int,
    account: AccountUpdate,
    db: Session = Depends(get_db)
):
    """
    계정 수정 API
    
    TODO:
    1. user_id로 계정 조회
    2. 계정이 존재하지 않으면 404 에러
    3. 권한 검증 (본인 또는 관리자만 수정 가능)
    4. 비밀번호 변경 시 해시화
    5. 계정 정보 업데이트
    6. 데이터베이스 커밋
    7. 업데이트된 계정 정보 반환
    """
    return {
        "success": False,
        "message": "계정 수정 API 구현 필요",
        "data": None
    }


# TODO: 계정 삭제 API 구현
# - 여러 계정 일괄 삭제
# - 관련 데이터 확인 (광고 등)
# - 소프트 삭제 또는 하드 삭제 결정
# - 삭제 처리
@router.delete("")
async def delete_accounts(
    delete_request: AccountDelete,
    db: Session = Depends(get_db)
):
    """
    계정 삭제 API
    
    TODO:
    1. user_ids 배열의 각 계정 조회
    2. 각 계정의 관련 데이터 확인 (광고, 정산 등)
    3. 삭제 가능 여부 검증
    4. 계정 삭제 (소프트 삭제: is_active=False 또는 하드 삭제)
    5. 데이터베이스 커밋
    6. 삭제된 계정 수 반환
    7. 에러 처리: 관련 데이터가 있는 경우
    """
    return {
        "success": False,
        "message": "계정 삭제 API 구현 필요",
        "data": None
    }

