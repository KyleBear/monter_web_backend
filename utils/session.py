"""
세션 관리 모듈
간단한 메모리 기반 세션 관리
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict

# 세션 저장소 (메모리 기반)
# 프로덕션 환경에서는 Redis 등을 사용하는 것을 권장
sessions: Dict[str, Dict] = {}


def create_session(user_id: int, username: str, role: str, remember_me: bool = False) -> str:
    """
    세션 토큰 생성 및 저장
    
    Args:
        user_id: 사용자 ID
        username: 사용자명
        role: 역할
        remember_me: 기억하기 옵션 (True면 30일, False면 1일)
    
    Returns:
        세션 토큰
    """
    # 랜덤 토큰 생성
    token = secrets.token_urlsafe(32)
    
    # 세션 만료 시간 설정
    if remember_me:
        expires_at = datetime.now() + timedelta(days=30)
    else:
        expires_at = datetime.now() + timedelta(days=1)
    
    # 세션 정보 저장
    sessions[token] = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "created_at": datetime.now(),
        "expires_at": expires_at
    }
    
    return token


def get_session(token: str) -> Optional[Dict]:
    """
    세션 정보 조회
    
    Args:
        token: 세션 토큰
    
    Returns:
        세션 정보 또는 None
    """
    if token not in sessions:
        return None
    
    session = sessions[token]
    
    # 만료 시간 확인
    if datetime.now() > session["expires_at"]:
        # 만료된 세션 삭제
        del sessions[token]
        return None
    
    return session


def delete_session(token: str) -> bool:
    """
    세션 삭제
    
    Args:
        token: 세션 토큰
    
    Returns:
        삭제 성공 여부
    """
    if token in sessions:
        del sessions[token]
        return True
    return False


def cleanup_expired_sessions():
    """
    만료된 세션 정리
    """
    now = datetime.now()
    expired_tokens = [
        token for token, session in sessions.items()
        if now > session["expires_at"]
    ]
    for token in expired_tokens:
        del sessions[token]

