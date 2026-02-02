"""
외부 파트너사 리워드 등록 API
POST /api/v1/mission/create - 정답 미션 등록
"""
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from database import get_db
from datetime import datetime, timedelta
import hmac
import hashlib
import json
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# API Key와 Secret Key (환경 변수에서 가져오기)
API_KEY = os.getenv("EXTERNAL_API_KEY", "default_api_key")
API_SECRET = os.getenv("EXTERNAL_API_SECRET", "default_api_secret")

# 타임스탬프 유효 기간 (5분)
TIMESTAMP_VALIDITY_MINUTES = 5


# ==================== 요청/응답 모델 ====================

class MissionCreateRequest(BaseModel):
    """정답 미션 등록 요청 모델"""
    mnc_type: str = Field(..., description="미션 타입: answer(정답형-내부), sharing(정답형-외부), ext_sharing(공유형)")
    mnc_ans_type: str = Field(..., description="정답 타입: answer(정답), general(일반)")
    title: Optional[str] = Field(None, description="미션 제목")
    description: Optional[str] = Field(None, description="미션 설명")
    answer: Optional[str] = Field(None, description="정답 (mnc_ans_type이 answer인 경우 필수)")
    reward_amount: Optional[float] = Field(None, description="리워드 금액")
    start_date: Optional[str] = Field(None, description="시작일 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="종료일 (YYYY-MM-DD)")
    extra_data: Optional[dict] = Field(None, description="추가 데이터")


class MissionCreateResponse(BaseModel):
    """정답 미션 등록 응답 모델"""
    success: bool
    message: str
    data: Optional[dict] = None


# ==================== 인증 헬퍼 함수 ====================

def verify_hmac_md5_signature(
    api_key: str,
    timestamp: str,
    signature: str,
    request_body: str
) -> bool:
    """
    HMAC-MD5 서명 검증
    
    Args:
        api_key: API Key
        timestamp: 타임스탬프
        signature: 전달받은 서명
        request_body: 요청 본문 (JSON 문자열)
    
    Returns:
        검증 성공 여부
    """
    # API Key 검증
    if api_key != API_KEY:
        return False
    
    # 서명 생성: timestamp + request_body를 조합하여 HMAC-MD5 생성
    message = f"{timestamp}{request_body}"
    expected_signature = hmac.new(
        API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    
    # 서명 비교 (타이밍 공격 방지를 위해 hmac.compare_digest 사용)
    return hmac.compare_digest(signature.lower(), expected_signature.lower())


def validate_timestamp(timestamp: str) -> bool:
    """
    타임스탬프 유효성 검증 (5분 이내)
    
    Args:
        timestamp: 타임스탬프 문자열 (Unix timestamp 또는 ISO format)
    
    Returns:
        유효 여부
    """
    try:
        # Unix timestamp인 경우
        if timestamp.isdigit():
            timestamp_int = int(timestamp)
            request_time = datetime.fromtimestamp(timestamp_int)
        else:
            # ISO format인 경우
            request_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # 현재 시간과 비교
        current_time = datetime.utcnow()
        time_diff = abs((current_time - request_time).total_seconds())
        
        # 5분(300초) 이내인지 확인
        return time_diff <= (TIMESTAMP_VALIDITY_MINUTES * 60)
    except (ValueError, TypeError):
        return False


async def verify_api_authentication(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_timestamp: Optional[str] = Header(None, alias="X-Timestamp"),
    x_signature: Optional[str] = Header(None, alias="X-Signature")
) -> dict:
    """
    API Key + HMAC-MD5 서명 인증
    
    헤더:
    - X-API-Key: API Key
    - X-Timestamp: 타임스탬프
    - X-Signature: HMAC-MD5 서명
    """
    # 필수 헤더 확인
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key 헤더가 필요합니다."
        )
    
    if not x_timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Timestamp 헤더가 필요합니다."
        )
    
    if not x_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Signature 헤더가 필요합니다."
        )
    
    # 타임스탬프 유효성 검증
    if not validate_timestamp(x_timestamp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"타임스탬프가 유효하지 않습니다. 요청은 {TIMESTAMP_VALIDITY_MINUTES}분 이내에 유효합니다."
        )
    
    # 요청 본문 읽기
    body_bytes = await request.body()
    request_body = body_bytes.decode('utf-8')
    
    # HMAC-MD5 서명 검증
    if not verify_hmac_md5_signature(x_api_key, x_timestamp, x_signature, request_body):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="서명이 유효하지 않습니다."
        )
    
    # Request body를 다시 사용할 수 있도록 저장 (FastAPI가 다시 읽을 수 있도록)
    async def receive_body():
        return body_bytes
    
    # Starlette의 Request 객체에 body를 다시 설정
    request._body = body_bytes
    
    return {
        "api_key": x_api_key,
        "timestamp": x_timestamp
    }


# ==================== API 엔드포인트 ====================

@router.post("/api/v1/mission/create", response_model=MissionCreateResponse)
async def create_mission(
    request: MissionCreateRequest,
    http_request: Request,
    auth_info: dict = Depends(verify_api_authentication),
    db: Session = Depends(get_db)
):
    """
    정답 미션 등록 API
    
    외부 파트너사에서 정답 미션을 등록합니다.
    
    인증 필요: API Key + HMAC-MD5 서명
    타임스탬프 유효 기간: 5분
    
    미션 타입 (mnc_type):
    - answer: 정답형(내부)
    - sharing: 정답형(외부)
    - ext_sharing: 공유형
    
    정답 타입 (mnc_ans_type):
    - answer: 정답
    - general: 일반
    """
    try:
        # 미션 타입 검증
        valid_mnc_types = ["answer", "sharing", "ext_sharing"]
        if request.mnc_type not in valid_mnc_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 미션 타입입니다. 허용된 값: {', '.join(valid_mnc_types)}"
            )
        
        # 정답 타입 검증
        valid_ans_types = ["answer", "general"]
        if request.mnc_ans_type not in valid_ans_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 정답 타입입니다. 허용된 값: {', '.join(valid_ans_types)}"
            )
        
        # 정답 타입이 'answer'인 경우 answer 필드 필수
        if request.mnc_ans_type == "answer" and not request.answer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="정답 타입이 'answer'인 경우 answer 필드가 필요합니다."
            )
        
        # 날짜 형식 검증 및 변환
        start_date = None
        end_date = None
        if request.start_date:
            try:
                start_date = datetime.strptime(request.start_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="시작일 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요."
                )
        
        if request.end_date:
            try:
                end_date = datetime.strptime(request.end_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="종료일 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요."
                )
        
        # 시작일이 종료일보다 늦은 경우 검증
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="시작일이 종료일보다 늦을 수 없습니다."
            )
        
        # 미션 데이터 준비
        mission_data = {
            "mnc_type": request.mnc_type,
            "mnc_ans_type": request.mnc_ans_type,
            "title": request.title,
            "description": request.description,
            "answer": request.answer,
            "reward_amount": request.reward_amount,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "extra_data": request.extra_data,
            "created_at": datetime.utcnow().isoformat(),
            "api_key": auth_info.get("api_key")
        }
        
        # TODO: 데이터베이스에 미션 저장
        # 현재는 로그만 출력하고 성공 응답 반환
        # 실제 구현 시 Mission 모델을 생성하여 DB에 저장해야 함
        
        # 예시: 로그 출력
        print(f"[미션 등록] 타입: {request.mnc_type}, 정답 타입: {request.mnc_ans_type}, 데이터: {json.dumps(mission_data, ensure_ascii=False, indent=2)}")
        
        # 성공 응답
        return MissionCreateResponse(
            success=True,
            message="미션이 성공적으로 등록되었습니다.",
            data={
                "mission_id": f"mission_{datetime.utcnow().timestamp()}",  # 임시 ID
                "mnc_type": request.mnc_type,
                "mnc_ans_type": request.mnc_ans_type,
                "created_at": mission_data["created_at"]
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"미션 등록 중 오류가 발생했습니다: {str(e)}"
        )

# 리워드 생성
# 리워드 조회 
# 리워드 삭제

