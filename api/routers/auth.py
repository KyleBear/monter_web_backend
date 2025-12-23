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


# 하드코딩된 슈퍼유저 계정 (users_admin 테이블과 무관하게 로그인 가능)
HARDCODED_ACCOUNTS = {
    "admin": {
        "password": "monteur1234",  # monter1234 → monteur1234
        "user_id": 6,
        "role": "admin"
    },
    "monteur": {  # monter → monteur
        "password": "monteur1234",  # monter → monteur1234
        "user_id": 7,
        "role": "admin"
    }
}


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    로그인 API
    """
    username = request.username.strip() if request.username else ""
    password = request.password.strip() if request.password else ""
    remember_me = request.remember_me or False
    
    # 빈 값 체크
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="아이디와 비밀번호를 입력해주세요."
        )
    
    user_id = None
    role = None
    
    # 하드코딩된 슈퍼유저 계정 확인 (우선 처리)
    if username in HARDCODED_ACCOUNTS:
        account = HARDCODED_ACCOUNTS[username]
        if password != account["password"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 일치하지 않습니다."
            )
        # 슈퍼유저는 users_admin 테이블 확인 없이 바로 로그인
        user_id = account["user_id"]
        role = account["role"]
    else:
        # 데이터베이스에서 사용자 조회
        try:
            user = db.query(UsersAdmin).filter(UsersAdmin.username == username).first()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"데이터베이스 연결 오류: {str(e)}"
            )
        
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
        if not user.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="비밀번호 정보가 없습니다. 관리자에게 문의하세요."
            )
        
        if not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="아이디 또는 비밀번호가 일치하지 않습니다."
            )
        
        # 데이터베이스에서 조회한 실제 user_id 사용 (중요!)
        user_id = user.user_id
        role = user.role
        
        # 디버깅: 실제 user_id 확인
        print(f"[DEBUG] Login - Username: {username}, DB user_id: {user_id}, Role: {role}")
    
    # user_id 검증 (None이거나 0보다 작으면 에러)
    if user_id is None or user_id < 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="사용자 ID를 가져올 수 없습니다."
        )
    
    # 세션 토큰 생성
    session_token = create_session(user_id, username, role, remember_me)
    
    # 디버깅: 세션에 저장된 user_id 확인
    print(f"[DEBUG] Session created - user_id: {user_id}, username: {username}, role: {role}")
    
    return {
        "success": True,
        "message": "로그인 성공",
        "data": {
            "user_id": user_id,  # 실제 DB의 user_id 반환
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
    
    # 세션의 user_id 검증
    user_id = session.get("user_id")
    if user_id is None or user_id < 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 세션 정보입니다."
        )
    
    return {
        "success": True,
        "data": {
            "user_id": user_id,
            "username": session["username"],
            "role": session["role"]
        }
    }

