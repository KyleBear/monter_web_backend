"""
인증 헬퍼 함수
현재 사용자 정보 가져오기
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.session import get_session

security = HTTPBearer(auto_error=False)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    현재 로그인한 사용자 정보 가져오기
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
        "user_id": user_id,
        "username": session["username"],
        "role": session["role"]
    }

