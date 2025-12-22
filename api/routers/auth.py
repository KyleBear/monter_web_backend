"""
인증 API 라우터
로그인, 로그아웃, 세션 확인
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from database import get_db
from models import UsersAdmin
from utils.password import verify_password
from utils.session import create_session, get_session, delete_session

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


# 하드코딩된 계정 (admin, monter)
HARDCODED_ACCOUNTS = {
    "admin": {
        "password": "1234",
        "user_id": 0,
        "role": "admin"
    },
    "monter": {
        "password": "monter",
        "user_id": 1,
        "role": "admin"
    }
}


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    로그인 API
    - admin/1234, monter/monter 계정은 하드코딩
    - 나머지 계정은 users_admin 테이블에서 조회
    """
    username = request.username
    password = request.password
    remember_me = request.remember_me or False
    
    user_id = None
    role = None
    
    # 하드코딩된 계정 확인
    if username in HARDCODED_ACCOUNTS:
        account = HARDCODED_ACCOUNTS[username]
        if password != account["password"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 일치하지 않습니다."
            )
        user_id = account["user_id"]
        role = account["role"]
    else:
        # 데이터베이스에서 사용자 조회
        user = db.query(UsersAdmin).filter(UsersAdmin.username == username).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 일치하지 않습니다."
            )
        
        # 계정 활성화 확인
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="비활성화된 계정입니다."
            )
        
        # 비밀번호 검증
        if not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 일치하지 않습니다."
            )
        
        user_id = user.user_id
        role = user.role
    
    # 세션 토큰 생성
    session_token = create_session(user_id, username, role, remember_me)
    
    return {
        "success": True,
        "message": "로그인 성공",
        "data": {
            "user_id": user_id,
            "username": username,
            "role": role,
            "session_token": session_token
        }
    }


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    로그아웃 API
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다."
        )
    
    token = credentials.credentials
    deleted = delete_session(token)
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다."
        )
    
    return {
        "success": True,
        "message": "로그아웃 성공"
    }


@router.get("/verify", response_model=VerifyResponse)
async def verify_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    세션 확인 API
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다."
        )
    
    token = credentials.credentials
    session = get_session(token)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다."
        )
    
    return {
        "success": True,
        "data": {
            "user_id": session["user_id"],
            "username": session["username"],
            "role": session["role"]
        }
    }

