"""
외부 파트너사 리워드 API
FastAPI 서버에서 moneydot.co.kr API로 요청을 전송하는 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request, File, UploadFile, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from database import get_db
from models import RewardRank
from datetime import datetime, timezone, timedelta
import requests
import hmac
import hashlib
import json
import os
import io
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter()

# API 설정 (환경 변수에서 가져오기)
PRD_SERVER = os.getenv("PRD_SERVER", "https://moneydot.co.kr/api_document/#/")
# 여러 가능한 환경 변수 이름 시도
API_KEY = os.getenv("EXTERNAL_API_KEY") or os.getenv("api_key") or os.getenv("API_KEY")
API_SECRET = os.getenv("EXTERNAL_API_SECRET") or os.getenv("api_secret") or os.getenv("API_SECRET")
API_KEY = os.getenv("api_key") or os.getenv("API_KEY")
API_SECRET = os.getenv("secret_key") or os.getenv("API_SECRET")

# 환경 변수 확인
if not API_KEY:
    logger.error("API_KEY 환경 변수가 설정되지 않았습니다. (EXTERNAL_API_KEY, api_key, API_KEY 중 하나 필요)")
    raise ValueError("API_KEY 환경 변수를 설정해주세요. (EXTERNAL_API_KEY, api_key, API_KEY 중 하나)")
if not API_SECRET:
    logger.error("API_SECRET 환경 변수가 설정되지 않았습니다. (EXTERNAL_API_SECRET, api_secret, API_SECRET 중 하나 필요)")
    raise ValueError("API_SECRET 환경 변수를 설정해주세요. (EXTERNAL_API_SECRET, api_secret, API_SECRET 중 하나)")

# PRD_SERVER에서 실제 API 서버 URL 추출
BASE_API_URL = PRD_SERVER.replace("/api_document/#/", "").rstrip("/")


# ==================== 요청/응답 모델 ====================

class MissionRegisterRequest(BaseModel):
    """미션 등록 요청 모델"""
    reward_id: int = Field(..., description="RewardRank의 reward_id")


class MissionReadRequest(BaseModel):
    """미션 조회 요청 모델"""
    api_key: Optional[str] = Field(None, description="API Key (없으면 env의 api_key 사용)")
    mnc_idx: Optional[int] = Field(None, description="미션 IDX로 단건 조회")
    search_title: Optional[str] = Field(None, description="제목으로 검색")
    search_memo: Optional[str] = Field(None, description="메모로 검색")


class MissionUpdateRequest(BaseModel):
    """미션 수정 요청 모델 (내부용, 실제로는 Form 파라미터 사용)"""
    api_key: Optional[str] = Field(None, description="API Key (없으면 env의 api_key 사용)")
    mnc_idx: int = Field(..., description="수정할 미션 IDX")
    reward_id: Optional[int] = Field(None, description="RewardRank의 reward_id (옵션)")
    mnc_type: Optional[str] = Field(None, description="미션 타입")
    mnc_title: Optional[str] = Field(None, description="미션 제목")
    mnc_point: Optional[int] = Field(None, description="적립 포인트")
    mnc_limitcnt: Optional[int] = Field(None, description="최대 참여 인원수")
    mnc_use_is: Optional[str] = Field(None, description="사용 여부 (Y/N)")


class MissionDeleteRequest(BaseModel):
    """미션 삭제 요청 모델"""
    api_key: Optional[str] = Field(None, description="API Key (없으면 env의 api_key 사용)")
    mnc_idx: int = Field(..., description="삭제할 미션 IDX")


class MissionResponse(BaseModel):
    """미션 응답 모델"""
    success: bool
    message: str
    data: Optional[dict] = None


# ==================== 헬퍼 함수 ====================

def generate_signature_for_register(
    api_key: str,
    timestamp: str,
    secret_key: str,
    mnc_title: str
) -> str:
    """
    미션 등록용 HMAC-MD5 서명 생성
    서명: api_key + timestamp + mnc_title (secret_key로 서명)
    
    Args:
        api_key: API Key
        timestamp: 타임스탬프
        secret_key: Secret Key
        mnc_title: 미션 제목
    
    Returns:
        서명 (hexdigest)
    """
    message = f"{api_key}{timestamp}{mnc_title}"
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    return signature


def download_image_from_url(image_url: str) -> Optional[bytes]:
    """
    URL에서 이미지 다운로드
    
    Args:
        image_url: 이미지 URL
    
    Returns:
        이미지 바이너리 데이터 또는 None
    """
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        
        # Content-Type 확인
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            logger.warning(f"URL이 이미지가 아닙니다: {content_type}")
            return None
        
        return response.content
    except Exception as e:
        logger.error(f"이미지 다운로드 실패: {image_url}, 오류: {e}")
        return None


def generate_signature_for_read(
    api_key: str,
    secret_key: str,
    timestamp: str,
    search_param: Optional[str] = None
) -> str:
    """
    미션 조회용 HMAC-MD5 서명 생성
    - mnc_idx로 검색: api_key + secret_key + timestamp + mnc_idx
    - search_title로 검색: api_key + secret_key + timestamp + search_title
    - search_memo로 검색: api_key + secret_key + timestamp + search_memo
    - 전체 조회: api_key + secret_key + timestamp
    
    Args:
        api_key: API Key
        secret_key: Secret Key
    - mnc_idx로 검색: api_key + timestamp + mnc_idx (secret_key로 해시)
    - search_title로 검색: api_key + timestamp + search_title (secret_key로 해시)
    - search_memo로 검색: api_key + timestamp + search_memo (secret_key로 해시)
    - 전체 조회: api_key + timestamp (secret_key로 해시)
    
    Args:
        api_key: API Key
        secret_key: Secret Key (해시 키로 사용)
        timestamp: 타임스탬프
        search_param: 검색 파라미터 (mnc_idx, search_title, search_memo 또는 None)
    
    Returns:
        서명 (hexdigest)
    """
    if search_param:
        message = f"{api_key}{secret_key}{timestamp}{search_param}"
    else:
        message = f"{api_key}{secret_key}{timestamp}"
    
        서명 (hexdigest) - 32자리 16진수 문자열
    """
    # 메시지 구성: api_key + timestamp + search_param (secret_key는 메시지에 포함하지 않음)
    if search_param:
        message = f"{api_key}{timestamp}{search_param}"
    else:
        message = f"{api_key}{timestamp}"
    
    # secret_key를 키로 사용하여 메시지를 HMAC-MD5 해시
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    return signature


def generate_signature_for_update_or_delete(
    api_key: str,
    secret_key: str,
    timestamp: str,
    mnc_idx: int
) -> str:
    """
    미션 수정/삭제용 HMAC-MD5 서명 생성
    서명: api_key + timestamp + mnc_idx (secret_key로 해시)
    
    Args:
        api_key: API Key
        secret_key: Secret Key (해시 키로 사용)
        timestamp: 타임스탬프
        mnc_idx: 미션 IDX
    
    Returns:
        서명 (hexdigest) - 32자리 16진수 문자열
    """
    # 메시지 구성: api_key + timestamp + mnc_idx
    message = f"{api_key}{timestamp}{mnc_idx}"
    
    # secret_key를 키로 사용하여 메시지를 HMAC-MD5 해시
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    return signature


def send_request_to_prd_server(
    endpoint: str,
    method: str = "POST",
    data: Optional[dict] = None,
    files: Optional[dict] = None,
    headers: Optional[dict] = None
) -> dict:
    """
    PRD 서버로 요청 전송
    
    Args:
        endpoint: API 엔드포인트 (예: "/api/v1/mission/create")
        method: HTTP 메서드 (기본: POST)
        data: 요청 데이터
        files: 파일 데이터 (multipart/form-data용)
        headers: 요청 헤더
    
    Returns:
        응답 딕셔너리
    """
    url = f"{BASE_API_URL}{endpoint}"
    
    try:
        if files:
            # 전송 전 timestamp 값 확인 (integer 타입 확인)
            if data and "timestamp" in data:
                timestamp_send = data["timestamp"]
                timestamp_send_type = type(timestamp_send).__name__
                logger.info(f"[send_request_to_prd_server] 전송 직전 timestamp: {timestamp_send}, 타입: {timestamp_send_type}")
                print(f"[send_request_to_prd_server] 전송 직전 timestamp: {timestamp_send}, 타입: {timestamp_send_type}")
                assert isinstance(timestamp_send, int), f"전송 직전 timestamp는 integer여야 합니다. 현재 타입: {timestamp_send_type}"
            
            # multipart/form-data 요청
            # requests 라이브러리는 data 딕셔너리의 integer 값을 문자열로 변환하지만,
            # 서버 측에서 파싱할 때 integer로 인식할 수 있도록 integer 타입을 유지
            response = requests.post(
                url,
                data=data,  # data에 integer 값이 포함되어 있으면 requests가 문자열로 변환
                files=files,
                headers=headers,
                timeout=60  # 이미지 업로드 시간 고려하여 증가
            )
        else:
            # JSON 요청
            response = requests.request(
                method,
                url,
                json=data,
            # form-data 요청 (JSON이 아닌 form-data로 전송)
            response = requests.post(
                url,
                data=data,  # form-data로 전송
                headers=headers,
                timeout=30
            )
        
        # 응답 처리
        try:
            response_json = response.json()
        except:
            response_json = {"raw_text": response.text}
        
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "data": response_json
        }
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PRD 서버 요청 실패: {str(e)}"
        )


# ==================== API 엔드포인트 ====================

@router.post("/api/v1/mission/register", response_model=MissionResponse)
async def register_mission(
    request: MissionRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    미션 등록 API
    미션 일괄 등록 API
    
    FastAPI 서버에서 외부 파트너사 API로 미션 등록 요청을 전송합니다.
    
    인증: API Key + HMAC-MD5 서명
    서명 생성: api_key + timestamp + mnc_title (secret_key로 서명)
    
    reward_id를 받아서 RewardRank 테이블에서 데이터를 조회하고,
    이미지를 다운로드하여 multipart/form-data 형식으로 업로드합니다.
    """
    try:
        # RewardRank 데이터 조회
        reward_rank = db.query(RewardRank).filter(
            RewardRank.reward_id == request.reward_id
        ).first()
        
        if not reward_rank:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"reward_id {request.reward_id}에 해당하는 데이터를 찾을 수 없습니다."
            )
        
        # 고정값 설정
        mnc_type = "answer"
        mnc_ans_type = "answer"
        mnc_title = f"몽테르 미션 {request.reward_id}"
        mnc_limitcnt = 1000
        mnc_mission_starttime = "2026-02-02"
        mnc_mission_endtime = "2026-02-27"
        ma_btype1 = "chrome"
        
        # RewardRank에서 데이터 가져오기
        ma_keyword1 = reward_rank.keyword or ""  # ma_keyword 컬럼이 없으므로 keyword 사용
        ma_reginum1 = str(reward_rank.reward_id)
        ma_link1 = reward_rank.product_url or ""
        ma_answer1 = reward_rank.nvmid or ""
        ma_answer_ios1 = reward_rank.nvmid or ""
        
        # 관리자 메모 생성 (유입 메모)
        # 형식: {agency: 몽테르|리워드, m_type: 네이버쇼핑-트래픽, code: {code}, mid: {mid}, product_name: {product_name}}
        agency = "몽테르|리워드"
        m_type = "네이버쇼핑-트래픽"
        code = reward_rank.productid or ""  # productid를 code로 사용
        mid = reward_rank.nvmid or ""
        product_name = reward_rank.product_name or ""
        
        mnc_memo = f"{{agency: {agency}, m_type: {m_type}, code: {code}, mid: {mid}, product_name: {product_name}}}"
        
        # 파일 데이터 준비
        files = {}
        
        # 이미지 다운로드 (메인 이미지와 힌트 이미지가 동일하므로 한 번만 다운로드)
        if reward_rank.image_url:
            image_data = download_image_from_url(reward_rank.image_url)
            if image_data:
                # 파일 확장자 추출
                file_ext = "jpg"  # 기본값
                if reward_rank.image_url.lower().endswith(('.png', '.gif')):
                    file_ext = reward_rank.image_url.split('.')[-1].lower()
                
                # 메인 이미지 (mnc_img) - 별도의 BytesIO 객체 생성
                files["mnc_img"] = (
                    f"mnc_img.{file_ext}",
                    io.BytesIO(image_data),
                    f"image/{file_ext}"
                )
                
                # 힌트 이미지 (ma_img1) - 별도의 BytesIO 객체 생성 (같은 데이터지만 별도 객체)
                files["ma_img1"] = (
                    f"ma_img1.{file_ext}",
                    io.BytesIO(image_data),
                    f"image/{file_ext}"
                )
        
        # 외부 API 요청 직전에 타임스탬프와 서명 재생성 (현재 시간 사용)
        # Unix timestamp (integer) - 현재 시간 기준 5분 이내
        # 한국 시간(KST, UTC+9) 기준으로 Unix timestamp 생성 (정수형)
        kst = timezone(timedelta(hours=9))
        kst_now = datetime.now(kst)
        timestamp_int = int(kst_now.timestamp())
        timestamp_str = str(timestamp_int)  # 서명 생성용 문자열
        
        # 타임스탬프 로그 출력 (전송 전)
        current_time_utc = datetime.utcnow()
        current_time_kst = datetime.now(timezone(timedelta(hours=9)))
        logger.info(f"[타임스탬프 생성] Unix Timestamp: {timestamp_int}")
        logger.info(f"[타임스탬프 생성] UTC 시간: {current_time_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        logger.info(f"[타임스탬프 생성] KST 시간: {current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")
        print(f"[타임스탬프] Unix Timestamp: {timestamp_int} (UTC: {current_time_utc.strftime('%Y-%m-%d %H:%M:%S')}, KST: {current_time_kst.strftime('%Y-%m-%d %H:%M:%S')})")
        
        # 서명 생성 (api_key + timestamp + mnc_title)
        signature = generate_signature_for_register(
            API_KEY,
            timestamp_str,
            API_SECRET,
            mnc_title
        )
        
        # 요청 데이터 준비 (multipart/form-data용)
        # timestamp만 integer로 전송, 나머지는 문자열로 명시적 변환
        form_data = {
            "api_key": str(API_KEY),
            "timestamp": timestamp_int,  # integer로 유지
            "signature": str(signature),
            "mnc_type": str(mnc_type),
            "mnc_ans_type": str(mnc_ans_type),
            "mnc_title": str(mnc_title),
            "mnc_point": int(0),  # integer로 명시적 변환
            "mnc_limitcnt": int(mnc_limitcnt),  # integer로 명시적 변환
            "mnc_mission_starttime": str(mnc_mission_starttime),
            "mnc_mission_endtime": str(mnc_mission_endtime),
            "mnc_memo": str(mnc_memo),
            "ma_keyword1": str(ma_keyword1) if ma_keyword1 else "",
            "ma_reginum1": str(ma_reginum1) if ma_reginum1 else "",
            "ma_btype1": str(ma_btype1),
            "ma_link1": str(ma_link1) if ma_link1 else "",
            "ma_answer1": str(ma_answer1) if ma_answer1 else "",
            "ma_answer_ios1": str(ma_answer_ios1) if ma_answer_ios1 else "",
        }
        
        # 전송되는 form_data 전체 로그 출력
        logger.info(f"[전송 데이터 전체] form_data: {json.dumps(form_data, indent=2, ensure_ascii=False, default=str)}")
        print(f"[전송 데이터 전체] form_data:")
        print(json.dumps(form_data, indent=2, ensure_ascii=False, default=str))
        
        # 전송되는 timestamp 값 확인 (integer 타입 확인)
        timestamp_value = form_data["timestamp"]
        timestamp_type = type(timestamp_value).__name__
        api_key_value = form_data["api_key"]
        logger.info(f"[전송 데이터 확인] api_key: {api_key_value[:10]}..., timestamp 값: {timestamp_value}, 타입: {timestamp_type}")
        print(f"[전송 데이터 확인] api_key: {api_key_value[:10]}..., timestamp 값: {timestamp_value}, 타입: {timestamp_type}")
        print(f"[전송 데이터 확인] timestamp (int): {int(timestamp_value)}, timestamp (str): {str(timestamp_value)}")
        
        # timestamp가 문자열로 변환되었는지 확인
        if not isinstance(timestamp_value, int):
            logger.warning(f"timestamp가 integer가 아닙니다. 현재 타입: {timestamp_type}, 값: {timestamp_value}")
            print(f"[경고] timestamp가 integer가 아닙니다. 현재 타입: {timestamp_type}, 값: {timestamp_value}")
        
        # 헤더 설정 (multipart/form-data는 Content-Type을 설정하지 않음)
        headers = {}
        
        # PRD 서버로 요청 전송
        logger.info(f"[외부 API 전송] endpoint: /api/v1/mission/create, timestamp: {timestamp_int} (type: {type(timestamp_int).__name__})")
        print(f"[외부 API 전송] endpoint: /api/v1/mission/create, timestamp: {timestamp_int} (type: {type(timestamp_int).__name__})")
        result = send_request_to_prd_server(
            endpoint="/api/v1/mission/create",
            method="POST",
            data=form_data,
            files=files if files else None,
            headers=headers
        )
        
        # 응답 처리
        if result["status_code"] == 200:
            response_data = result["data"]
            
            # 성공 응답
            if isinstance(response_data, dict) and response_data.get("result") == "Y":
                # 전송된 form_data를 응답에 포함 (디버깅용)
                response_data_with_form = response_data.get("data", {})
                if response_data_with_form:
                    response_data_with_form["_debug_form_data"] = form_data
                
                return MissionResponse(
                    success=True,
                    message=response_data.get("message", "미션이 성공적으로 등록되었습니다."),
                    data=response_data_with_form if response_data_with_form else response_data.get("data")
                )
            else:
                # 실패 응답에도 전송된 form_data 포함
                if isinstance(response_data, dict):
                    response_data["_debug_form_data"] = form_data
                
                return MissionResponse(
                    success=False,
                    message=response_data.get("message", "미션 등록 실패"),
                    data=response_data
                )
        else:
            raise HTTPException(
                status_code=result["status_code"],
                detail=f"미션 등록 실패: {result.get('data', {})}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"미션 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/api/v1/mission/read", response_model=MissionResponse)
async def read_mission(
    request: MissionReadRequest,
    db: Session = Depends(get_db)
):
    """
    미션 조회 API
    
    FastAPI 서버에서 외부 파트너사 API로 미션 조회 요청을 전송합니다.
    
    인증: API Key + HMAC-MD5 서명
    검색 조건:
    - mnc_idx: 미션 IDX로 단건 조회
    - search_title: 제목으로 검색
    - search_memo: 메모로 검색
    - 검색 조건 없음: 전체 미션 조회
    """
    try:
        # 타임스탬프 생성
        timestamp = str(int(datetime.utcnow().timestamp()))
        
        # 검색 파라미터 결정 및 서명 생성
        # API Key 결정 (요청에 없으면 env의 API_KEY 사용)
        api_key = request.api_key or API_KEY
        
        # 타임스탬프 생성 (현재 시간)
        kst = timezone(timedelta(hours=9))
        kst_now = datetime.now(kst)
        timestamp_int = int(kst_now.timestamp())
        timestamp_str = str(timestamp_int)

        # 검색 파라미터 결정
        search_param = None
        if request.mnc_idx:
            search_param = str(request.mnc_idx)
        elif request.search_title:
            search_param = request.search_title
        elif request.search_memo:
            search_param = request.search_memo
        
        # 서명 생성
        signature = generate_signature_for_read(
            API_KEY,
            API_SECRET,
            timestamp,
            search_param
        )
        
        # 요청 데이터 준비
        request_data = {
            "api_key": API_KEY,
            "timestamp": timestamp,
            "signature": signature,
        # 서명 생성 (generate_signature_for_read 함수 사용)
        signature = generate_signature_for_read(
            API_KEY,
            API_SECRET,
            timestamp_str,
            search_param
        )
        
        # 요청 데이터 준비 (form-data 형식)
        request_data = {
            "api_key": str(API_KEY),
            "timestamp": timestamp_int,  # 정수로 전송
            "signature": str(signature),
        }
        
        # 검색 조건 추가
        if request.mnc_idx:
            request_data["mnc_idx"] = request.mnc_idx
        elif request.search_title:
            request_data["search_title"] = request.search_title
        elif request.search_memo:
            request_data["search_memo"] = request.search_memo
        
        # 헤더 설정
        headers = {
            "Content-Type": "application/json"
        }
        
        # PRD 서버로 요청 전송
        result = send_request_to_prd_server(
            endpoint="/api/v1/mission/read",
            method="POST",
            data=request_data,
            request_data["mnc_idx"] = int(request.mnc_idx)
        elif request.search_title:
            request_data["search_title"] = str(request.search_title)
        elif request.search_memo:
            request_data["search_memo"] = str(request.search_memo)
        
        # 디버깅 로그
        logger.info(f"[미션 조회 요청] api_key: {api_key[:10]}..., timestamp: {timestamp_int}, signature: {signature[:20]}...")
        logger.info(f"[미션 조회 요청] request_data: {request_data}")
        print(f"[미션 조회 요청] api_key: {api_key[:10]}..., timestamp: {timestamp_int}, signature: {signature[:20]}...")
        
        # 헤더 제거 (form-data는 Content-Type을 자동 설정)
        headers = {}
        
        # PRD 서버로 요청 전송 (form-data 형식)
        result = send_request_to_prd_server(
            endpoint="/api/v1/mission/read",
            method="POST",
            data=request_data,  # form-data로 전송
            headers=headers
        )
        
        # 응답 처리
        if result["status_code"] == 200:
            response_data = result["data"]
            
            return MissionResponse(
                success=True,
                message="미션 조회 성공",
                data=response_data
            )
        else:
            raise HTTPException(
                status_code=result["status_code"],
                detail=f"미션 조회 실패: {result.get('data', {})}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"미션 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/api/v1/mission/update", response_model=MissionResponse)
async def update_mission(
    api_key: Optional[str] = Form(None),
    mnc_idx: int = Form(...),
    reward_id: Optional[int] = Form(None),
    mnc_type: Optional[str] = Form(None),
    mnc_title: Optional[str] = Form(None),
    mnc_point: Optional[int] = Form(None),
    mnc_limitcnt: Optional[int] = Form(None),
    mnc_use_is: Optional[str] = Form(None),
    mnc_img: Optional[UploadFile] = File(None),
    ma_img1: Optional[UploadFile] = File(None),
    ma_img2: Optional[UploadFile] = File(None),
    ma_img3: Optional[UploadFile] = File(None),
    ma_img4: Optional[UploadFile] = File(None),
    ma_img5: Optional[UploadFile] = File(None),
    ma_img6: Optional[UploadFile] = File(None),
    ma_img7: Optional[UploadFile] = File(None),
    ma_img8: Optional[UploadFile] = File(None),
    ma_img9: Optional[UploadFile] = File(None),
    ma_img10: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    미션 수정 API
    
    FastAPI 서버에서 외부 파트너사 API로 미션 수정 요청을 전송합니다.
    
    인증: API Key + HMAC-MD5 서명
    서명 생성: api_key + timestamp + mnc_idx (secret_key로 해시)
    
    옵션 파라미터:
    - reward_id: RewardRank의 reward_id (다른 파라미터가 없으면 사용)
    - mnc_type, mnc_title, mnc_point, mnc_limitcnt, mnc_use_is: 미션 정보
    - 이미지 파일들: mnc_img, ma_img1 ~ ma_img10
    """
    try:
        # API Key 결정 (요청에 없으면 env의 API_KEY 사용)
        api_key = api_key or API_KEY
        
        # RewardRank 데이터 조회 (reward_id가 제공된 경우)
        reward_rank = None
        if reward_id:
            reward_rank = db.query(RewardRank).filter(
                RewardRank.reward_id == reward_id
            ).first()
            
            if not reward_rank:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"reward_id {reward_id}에 해당하는 데이터를 찾을 수 없습니다."
                )
        
        # 미션 데이터 결정 (요청 파라미터가 있으면 사용, 없으면 reward_rank에서 가져오기)
        final_mnc_type = mnc_type or (reward_rank and "answer") or None
        final_mnc_title = mnc_title or (reward_rank and f"몽테르 미션 {reward_id}") or None
        final_mnc_point = mnc_point if mnc_point is not None else (reward_rank and 0) or None
        final_mnc_limitcnt = mnc_limitcnt if mnc_limitcnt is not None else (reward_rank and 1000) or None
        final_mnc_use_is = mnc_use_is
        
        # RewardRank에서 추가 데이터 가져오기 (reward_rank가 있는 경우)
        ma_keyword1 = ""
        ma_reginum1 = ""
        ma_link1 = ""
        ma_answer1 = ""
        ma_answer_ios1 = ""
        mnc_memo = ""
        ma_btype1 = ""
        
        if reward_rank:
            ma_keyword1 = reward_rank.keyword or ""
            ma_reginum1 = str(reward_rank.reward_id)
            ma_link1 = reward_rank.product_url or ""
            ma_answer1 = reward_rank.nvmid or ""
            ma_answer_ios1 = reward_rank.nvmid or ""
            ma_btype1 = "chrome"
            
            # 관리자 메모 생성
            agency = "몽테르|리워드"
            m_type = "네이버쇼핑-트래픽"
            code = reward_rank.productid or ""
            mid = reward_rank.nvmid or ""
            product_name = reward_rank.product_name or ""
            mnc_memo = f"{{agency: {agency}, m_type: {m_type}, code: {code}, mid: {mid}, product_name: {product_name}}}"
        
        # 파일 데이터 준비
        files = {}
        
        # 업로드된 이미지 파일 처리
        image_files = {
            "mnc_img": mnc_img,
            "ma_img1": ma_img1,
            "ma_img2": ma_img2,
            "ma_img3": ma_img3,
            "ma_img4": ma_img4,
            "ma_img5": ma_img5,
            "ma_img6": ma_img6,
            "ma_img7": ma_img7,
            "ma_img8": ma_img8,
            "ma_img9": ma_img9,
            "ma_img10": ma_img10,
        }
        
        for key, upload_file in image_files.items():
            if upload_file and upload_file.filename:
                file_content = await upload_file.read()
                file_ext = upload_file.filename.split('.')[-1].lower() if '.' in upload_file.filename else "jpg"
                files[key] = (
                    upload_file.filename,
                    io.BytesIO(file_content),
                    upload_file.content_type or f"image/{file_ext}"
                )
        
        # reward_rank에서 이미지 다운로드 (업로드된 파일이 없고 reward_rank가 있는 경우)
        if not files and reward_rank and reward_rank.image_url:
            image_data = download_image_from_url(reward_rank.image_url)
            if image_data:
                file_ext = "jpg"
                if reward_rank.image_url.lower().endswith(('.png', '.gif')):
                    file_ext = reward_rank.image_url.split('.')[-1].lower()
                
                files["mnc_img"] = (
                    f"mnc_img.{file_ext}",
                    io.BytesIO(image_data),
                    f"image/{file_ext}"
                )
                
                files["ma_img1"] = (
                    f"ma_img1.{file_ext}",
                    io.BytesIO(image_data),
                    f"image/{file_ext}"
                )
        
        # 타임스탬프 생성 (현재 시간)
        kst = timezone(timedelta(hours=9))
        kst_now = datetime.now(kst)
        timestamp_int = int(kst_now.timestamp())
        timestamp_str = str(timestamp_int)
        
        # 서명 생성 (api_key + timestamp + mnc_idx)
        signature = generate_signature_for_update_or_delete(
            api_key,
            API_SECRET,
            timestamp_str,
            mnc_idx
        )
        
        # 요청 데이터 준비 (multipart/form-data용)
        form_data = {
            "api_key": str(api_key),
            "timestamp": timestamp_int,
            "signature": str(signature),
            "mnc_idx": int(mnc_idx),
        }
        
        # 옵션 파라미터 추가 (값이 있는 경우만)
        if final_mnc_type:
            form_data["mnc_type"] = str(final_mnc_type)
        if final_mnc_title:
            form_data["mnc_title"] = str(final_mnc_title)
        if final_mnc_point is not None:
            form_data["mnc_point"] = int(final_mnc_point)
        if final_mnc_limitcnt is not None:
            form_data["mnc_limitcnt"] = int(final_mnc_limitcnt)
        if final_mnc_use_is:
            form_data["mnc_use_is"] = str(final_mnc_use_is)
        
        # RewardRank 데이터 추가 (있는 경우)
        if reward_rank:
            if ma_keyword1:
                form_data["ma_keyword1"] = str(ma_keyword1)
            if ma_reginum1:
                form_data["ma_reginum1"] = str(ma_reginum1)
            if ma_link1:
                form_data["ma_link1"] = str(ma_link1)
            if ma_answer1:
                form_data["ma_answer1"] = str(ma_answer1)
            if ma_answer_ios1:
                form_data["ma_answer_ios1"] = str(ma_answer_ios1)
            if mnc_memo:
                form_data["mnc_memo"] = str(mnc_memo)
            if ma_btype1:
                form_data["ma_btype1"] = str(ma_btype1)
        
        # 디버깅 로그
        logger.info(f"[미션 수정 요청] api_key: {api_key[:10]}..., mnc_idx: {mnc_idx}, timestamp: {timestamp_int}")
        logger.info(f"[미션 수정 요청] form_data: {json.dumps(form_data, indent=2, ensure_ascii=False, default=str)}")
        print(f"[미션 수정 요청] api_key: {api_key[:10]}..., mnc_idx: {mnc_idx}, timestamp: {timestamp_int}")
        
        # 헤더 설정 (multipart/form-data는 Content-Type을 설정하지 않음)
        headers = {}
        
        # PRD 서버로 요청 전송
        result = send_request_to_prd_server(
            endpoint="/api/v1/mission/update",
            method="POST",
            data=form_data,
            files=files if files else None,
            headers=headers
        )
        
        # 응답 처리
        if result["status_code"] == 200:
            response_data = result["data"]
            
            # 성공 응답
            if isinstance(response_data, dict) and response_data.get("result") == "Y":
                return MissionResponse(
                    success=True,
                    message=response_data.get("message", "미션이 성공적으로 수정되었습니다."),
                    data=response_data.get("data")
                )
            else:
                return MissionResponse(
                    success=False,
                    message=response_data.get("message", "미션 수정 실패"),
                    data=response_data
                )
        else:
            raise HTTPException(
                status_code=result["status_code"],
                detail=f"미션 수정 실패: {result.get('data', {})}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"미션 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/api/v1/mission/delete", response_model=MissionResponse)
async def delete_mission(
    request: MissionDeleteRequest,
    db: Session = Depends(get_db)
):
    """
    미션 삭제 API (소프트 삭제)
    
    FastAPI 서버에서 외부 파트너사 API로 미션 삭제 요청을 전송합니다.
    
    인증: API Key + HMAC-MD5 서명
    서명 생성: api_key + timestamp + mnc_idx (secret_key로 해시)
    """
    try:
        # API Key 결정 (요청에 없으면 env의 API_KEY 사용)
        api_key = request.api_key or API_KEY
        
        # 타임스탬프 생성 (현재 시간)
        kst = timezone(timedelta(hours=9))
        kst_now = datetime.now(kst)
        timestamp_int = int(kst_now.timestamp())
        timestamp_str = str(timestamp_int)
        
        # 서명 생성 (api_key + timestamp + mnc_idx)
        signature = generate_signature_for_update_or_delete(
            api_key,
            API_SECRET,
            timestamp_str,
            request.mnc_idx
        )
        
        # 요청 데이터 준비 (application/x-www-form-urlencoded 형식)
        request_data = {
            "api_key": str(api_key),
            "timestamp": timestamp_int,  # 정수로 전송
            "signature": str(signature),
            "mnc_idx": int(request.mnc_idx),  # 삭제할 미션 IDX
        }
        
        # 디버깅 로그
        logger.info(f"[미션 삭제 요청] api_key: {api_key[:10]}..., mnc_idx: {request.mnc_idx}, timestamp: {timestamp_int}")
        logger.info(f"[미션 삭제 요청] request_data: {request_data}")
        print(f"[미션 삭제 요청] api_key: {api_key[:10]}..., mnc_idx: {request.mnc_idx}, timestamp: {timestamp_int}")
        
        # 헤더 설정 (form-data는 Content-Type을 자동 설정)
        headers = {}
        
        # PRD 서버로 요청 전송 (form-data 형식)
        result = send_request_to_prd_server(
            endpoint="/api/v1/mission/delete",
            method="POST",
            data=request_data,  # form-data로 전송
            headers=headers
        )
        
        # 응답 처리
        if result["status_code"] == 200:
            response_data = result["data"]
            
            return MissionResponse(
                success=True,
                message=response_data.get("message", "미션이 성공적으로 삭제되었습니다."),
                data=response_data
            )
        else:
            raise HTTPException(
                status_code=result["status_code"],
                detail=f"미션 삭제 실패: {result.get('data', {})}"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"미션 삭제 중 오류가 발생했습니다: {str(e)}"
        )
