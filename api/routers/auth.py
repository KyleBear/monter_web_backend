"""
인증 API 라우터
로그인, 로그아웃, 세션 확인
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from db_code.database import get_db
from models import UsersAdmin
import hashlib
from datetime import datetime, timedelta

router = APIRouter()
security = HTTPBearer(auto_error=False)


# 요청/응답 모델
class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: Optional[bool] = False


class LoginResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


class VerifyResponse(BaseModel):
    success: bool
    data: Optional[dict] = None


# TODO: 로그인 API 구현
# - 사용자명과 비밀번호로 인증
# - 비밀번호 해시 검증
# - 세션 토큰 생성 및 반환
# - remember_me 옵션 처리
@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    로그인 API
    
    TODO:
    1. 데이터베이스에서 username으로 사용자 조회
    2. 비밀번호 해시 검증 (bcrypt 또는 hashlib 사용)
    3. 인증 성공 시 세션 토큰 생성
    4. 세션 정보 저장 (Redis 또는 데이터베이스)
    5. 사용자 정보 반환 (user_id, username, role)
    6. remember_me 옵션에 따른 세션 만료 시간 설정
    7. 에러 처리: 잘못된 아이디/비밀번호
    """
    # 임시 응답 (구현 필요)
    return {
        "success": False,
        "message": "로그인 API 구현 필요",
        "data": None
    }


# TODO: 로그아웃 API 구현
# - 세션 토큰 무효화
# - 세션 정보 삭제
@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    로그아웃 API
    
    TODO:
    1. 요청 헤더에서 세션 토큰 추출
    2. 세션 토큰 검증
    3. 세션 정보 삭제 (Redis 또는 데이터베이스)
    4. 성공 응답 반환
    5. 에러 처리: 유효하지 않은 토큰
    """
    return {
        "success": False,
        "message": "로그아웃 API 구현 필요"
    }


# TODO: 세션 확인 API 구현
# - 세션 토큰 검증
# - 사용자 정보 반환
@router.get("/verify", response_model=VerifyResponse)
async def verify_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    세션 확인 API
    
    TODO:
    1. 요청 헤더에서 세션 토큰 추출
    2. 세션 토큰 검증
    3. 세션에서 사용자 정보 조회
    4. 사용자 정보 반환 (user_id, username, role)
    5. 에러 처리: 유효하지 않은 토큰, 만료된 세션
    """
    return {
        "success": False,
        "data": None
    }

