"""
인증 API 라우터
로그인, 로그아웃, 세션 확인
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging
from database import get_db
from models import UsersAdmin
from utils.password import verify_password
from utils.session import create_session, get_session, delete_session

router = APIRouter()
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


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
    try:
        username = request.username.strip() if request.username else ""
        password = request.password.strip() if request.password else ""
        remember_me = request.remember_me or False
        
        logger.info(f"[로그인 요청] username={username}")
        
        # 빈 값 체크
        if not username or not password:
            logger.warning(f"[로그인 실패] 빈 값 - username={username}, password={'*' if password else ''}")
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
                logger.warning(f"[로그인 실패] 하드코딩 계정 비밀번호 불일치 - username={username}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="아이디 또는 비밀번호가 일치하지 않습니다."
                )
            # 슈퍼유저는 users_admin 테이블 확인 없이 바로 로그인
            user_id = account["user_id"]
            role = account["role"]
            logger.info(f"[로그인 성공] 하드코딩 계정 - username={username}, user_id={user_id}, role={role}")
        else:
            # 데이터베이스에서 사용자 조회
            try:
                user = db.query(UsersAdmin).filter(UsersAdmin.username == username).first()
            except Exception as e:
                logger.error(f"[로그인 오류] DB 조회 실패 - username={username}, error={str(e)}", exc_info=True)
                try:
                    db.rollback()
                except:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"데이터베이스 연결 오류: {str(e)}"
                )
            
            if not user:
                logger.warning(f"[로그인 실패] 사용자 없음 - username={username}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="아이디 또는 비밀번호가 일치하지 않습니다."
                )
            
            # 계정 활성화 확인
            if not user.is_active:
                logger.warning(f"[로그인 실패] 비활성화 계정 - username={username}, user_id={user.user_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="비활성화된 계정입니다."
                )
            
            # 비밀번호 검증
            try:
                if not user.password_hash:
                    logger.warning(f"[로그인 실패] 비밀번호 해시 없음 - username={username}, user_id={user.user_id}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="비밀번호 정보가 없습니다. 관리자에게 문의하세요."
                    )
                
                # 비밀번호 검증 시도
                password_match = verify_password(password, user.password_hash)
                logger.debug(f"[비밀번호 검증] username={username}, match={password_match}, stored_hash_length={len(user.password_hash) if user.password_hash else 0}")
                
                if not password_match:
                    logger.warning(f"[로그인 실패] 비밀번호 불일치 - username={username}, user_id={user.user_id}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="아이디 또는 비밀번호가 일치하지 않습니다."
                    )
            except HTTPException:
                # HTTPException은 그대로 전달
                raise
            except Exception as e:
                # 예상치 못한 예외 (예: None 타입 에러, 문자열 비교 에러 등)
                logger.error(f"[로그인 오류] 비밀번호 검증 중 예외 - username={username}, user_id={user.user_id if user else None}, error={str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="비밀번호 검증 중 오류가 발생했습니다."
                )
            
            # 데이터베이스에서 조회한 실제 user_id 사용 (중요!)
            user_id = user.user_id
            role = user.role
            
            logger.info(f"[로그인 성공] DB 계정 - username={username}, user_id={user_id}, role={role}")
        
        # user_id 검증 (None이거나 0보다 작으면 에러)
        if user_id is None or user_id < 0:
            logger.error(f"[로그인 오류] 유효하지 않은 user_id - username={username}, user_id={user_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="사용자 ID를 가져올 수 없습니다."
            )
        
        # 세션 토큰 생성 (DB에 저장)
        try:
            session_token = create_session(user_id, username, role, remember_me, db=db)
            logger.info(f"[세션 생성 완료] username={username}, user_id={user_id}, role={role}")
        except Exception as e:
            logger.error(f"[로그인 오류] 세션 생성 실패 - username={username}, user_id={user_id}, error={str(e)}", exc_info=True)
            try:
                db.rollback()
            except:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"세션 생성 중 오류가 발생했습니다: {str(e)}"
            )
        
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
    
    except HTTPException:
        # HTTPException은 그대로 전달 (FastAPI가 처리)
        raise
    except Exception as e:
        # 예상치 못한 모든 예외를 잡아서 로그 기록 및 안전한 에러 응답
        username_str = request.username if request and hasattr(request, 'username') else 'unknown'
        logger.error(f"[로그인 오류] 예상치 못한 예외 - username={username_str}, error={str(e)}", exc_info=True)
        try:
            db.rollback()
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="로그인 처리 중 오류가 발생했습니다."
        )


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
    deleted = delete_session(token, db=db)
    
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
    session = get_session(token, db=db)
    
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

