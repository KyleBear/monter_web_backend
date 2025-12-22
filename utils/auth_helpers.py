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
    
    Returns:
        dict: 사용자 정보 (user_id, username, role)
    
    Raises:
        HTTPException: 인증되지 않은 경우
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
        "user_id": session["user_id"],
        "username": session["username"],
        "role": session["role"]
    }

