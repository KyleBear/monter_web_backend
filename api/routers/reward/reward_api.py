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
    mnc_idx: Optional[int] = Field(None, description="미션 IDX로 단건 조회")
    search_title: Optional[str] = Field(None, description="제목으로 검색")
    search_memo: Optional[str] = Field(None, description="메모로 검색")


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
        timestamp: 타임스탬프
        search_param: 검색 파라미터 (mnc_idx, search_title, search_memo 또는 None)
    
    Returns:
        서명 (hexdigest)
    """
    if search_param:
        message = f"{api_key}{secret_key}{timestamp}{search_param}"
    else:
        message = f"{api_key}{secret_key}{timestamp}"
    
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
