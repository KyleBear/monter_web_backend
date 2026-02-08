"""
세션 관리 모듈
데이터베이스 기반 세션 관리 (모든 워커가 공유)
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy.orm import Session
from models import UserSession


def create_session(
    user_id: int, 
    username: str, 
    role: str, 
    remember_me: bool = False,
    db: Session = None
) -> str:
    """
    세션 토큰 생성 및 저장 (DB)
    
    Args:
        user_id: 사용자 ID
        username: 사용자명
        role: 역할
        remember_me: 기억하기 옵션 (True면 30일, False면 1일)
        db: 데이터베이스 세션 (None이면 자동 생성)
    
    Returns:
        세션 토큰
    """
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        # 랜덤 토큰 생성
        token = secrets.token_urlsafe(32)
        
        # 세션 만료 시간 설정
        if remember_me:
            expires_at = datetime.now() + timedelta(days=30)
        else:
            expires_at = datetime.now() + timedelta(days=1)
        
        # DB에 세션 저장
        session = UserSession(
            token=token,
            user_id=user_id,
            username=username,
            role=role,
            expires_at=expires_at
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        
        return token
    except Exception as e:
        if should_close:
            db.rollback()
        raise
    finally:
        if should_close:
            db.close()


def get_session(token: str, db: Session = None) -> Optional[Dict]:
    """
    세션 정보 조회 (DB)
    
    Args:
        token: 세션 토큰
        db: 데이터베이스 세션 (None이면 자동 생성)
    
    Returns:
        세션 정보 또는 None
    """
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        # DB에서 세션 조회
        session = db.query(UserSession).filter(UserSession.token == token).first()
        
        if not session:
            return None
        
        # 만료 시간 확인
        if datetime.now() > session.expires_at:
            # 만료된 세션 삭제
            db.delete(session)
            db.commit()
            return None
        
        return {
            "user_id": session.user_id,
            "username": session.username,
            "role": session.role,
            "created_at": session.created_at,
            "expires_at": session.expires_at
        }
    finally:
        if should_close:
            db.close()


def delete_session(token: str, db: Session = None) -> bool:
    """
    세션 삭제 (DB)
    
    Args:
        token: 세션 토큰
        db: 데이터베이스 세션 (None이면 자동 생성)
    
    Returns:
        삭제 성공 여부
    """
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        session = db.query(UserSession).filter(UserSession.token == token).first()
        if session:
            db.delete(session)
            db.commit()
            return True
        return False
    except Exception as e:
        if should_close:
            db.rollback()
        return False
    finally:
        if should_close:
            db.close()


def cleanup_expired_sessions(db: Session = None):
    """
    만료된 세션 정리 (DB)
    
    Args:
        db: 데이터베이스 세션 (None이면 자동 생성)
    """
    if db is None:
        from database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        should_close = False
    
    try:
        now = datetime.now()
        # DB에서 만료된 세션 조회
        expired_sessions = db.query(UserSession).filter(
            UserSession.expires_at < now
        ).all()
        
        # 만료된 세션 삭제
        for session in expired_sessions:
            db.delete(session)
        
        db.commit()
    except Exception as e:
        if should_close:
            db.rollback()
    finally:
        if should_close:
            db.close()

