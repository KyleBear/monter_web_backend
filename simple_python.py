import requests
import json
import sys
import os
import io
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from database import SessionLocal
from models import RewardRank
from PIL import Image

load_dotenv()

# API 설정 (환경 변수에서 가져오기)
BASE_API_URL = os.getenv("PRD_SERVER", "https://moneydot.co.kr").replace("/api_document/#/", "").rstrip("/")

# 환경 변수에서 가져오기 (api_key, secret_key)
API_KEY = os.getenv("api_key")
API_SECRET = os.getenv("secret_key")

# 환경 변수 확인
if not API_KEY:
    print("[오류] api_key 환경 변수가 설정되지 않았습니다.")
    print("  .env 파일에 'api_key=...' 형식으로 설정해주세요.")
    sys.exit(1)
if not API_SECRET:
    print("[오류] secret_key 환경 변수가 설정되지 않았습니다.")
    print("  .env 파일에 'secret_key=...' 형식으로 설정해주세요.")
    sys.exit(1)


def generate_signature_for_register(api_key: str, timestamp: str, secret_key: str, mnc_title: str) -> str:
    """HMAC-MD5 서명 생성"""
    message = f"{api_key}{timestamp}{mnc_title}"
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    return signature


def download_image_from_url(image_url: str) -> bytes:
    """URL에서 이미지 다운로드 및 JPG로 변환"""
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            print(f"[경고] URL이 이미지가 아닙니다: {content_type}")
            return None
        
        # 이미지 데이터를 JPG로 변환
        image_data = response.content
        try:
            # PIL로 이미지 열기
            image = Image.open(io.BytesIO(image_data))
            
            # RGB 모드로 변환 (RGBA, P 등 다른 모드 지원)
            if image.mode in ('RGBA', 'LA', 'P'):
                # 투명도가 있는 경우 흰색 배경으로 변환
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                rgb_image.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = rgb_image
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # JPG로 변환 (BytesIO에 저장)
            jpg_buffer = io.BytesIO()
            image.save(jpg_buffer, format='JPEG', quality=95)
            jpg_data = jpg_buffer.getvalue()
            
            print(f"[이미지 변환] 원본 형식: {image.format or 'Unknown'}, 크기: {len(image_data)} bytes")
            print(f"[이미지 변환] JPG 변환 완료, 크기: {len(jpg_data)} bytes")
            
            return jpg_data
        except Exception as img_error:
            print(f"[경고] 이미지 변환 실패, 원본 사용: {img_error}")
            return image_data  # 변환 실패 시 원본 반환
            
    except Exception as e:
        print(f"[오류] 이미지 다운로드 실패: {image_url}, 오류: {e}")
        return None


def register_reward_mission(reward_id: int):
    """
    내부 DB에서 외부 파트너사에 리워드 등록 (직접 요청)
    
    Args:
        reward_id: RewardRank의 reward_id
    
    Returns:
        dict: 응답 데이터
    """
    db = SessionLocal()
    try:
        # RewardRank 데이터 조회
        reward_rank = db.query(RewardRank).filter(
            RewardRank.reward_id == reward_id
        ).first()
        
        if not reward_rank:
            print(f"[오류] reward_id {reward_id}에 해당하는 데이터를 찾을 수 없습니다.")
            return None
        
        # 고정값 설정
        mnc_type = "answer"
        mnc_ans_type = "answer"
        mnc_title = f"몽테르 미션 {reward_id}"
        mnc_limitcnt = 1000
        mnc_mission_starttime = "2026-02-02"
        mnc_mission_endtime = "2026-02-27"
        ma_btype1 = "chrome"
        
        # RewardRank에서 데이터 가져오기
        ma_keyword1 = reward_rank.keyword or ""
        ma_reginum1 = str(reward_rank.reward_id)
        ma_link1 = reward_rank.product_url or ""
        ma_answer1 = reward_rank.nvmid or ""
        ma_answer_ios1 = reward_rank.nvmid or ""
        
        # 관리자 메모 생성
        agency = "몽테르|리워드"
        m_type = "네이버쇼핑-트래픽"
        code = reward_rank.productid or ""
        mid = reward_rank.nvmid or ""
        product_name = reward_rank.product_name or ""
        mnc_memo = f"{{agency: {agency}, m_type: {m_type}, code: {code}, mid: {mid}, product_name: {product_name}}}"
        
        # 파일 데이터 준비 (이미지를 JPG로 변환)
        files = {}
        if reward_rank.image_url:
            print(f"[이미지 다운로드] URL: {reward_rank.image_url}")
            image_data = download_image_from_url(reward_rank.image_url)
            if image_data:
                # 모든 이미지를 JPG로 변환했으므로 항상 jpg 확장자 사용
                file_ext = "jpg"
                
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
                print(f"[이미지 준비 완료] mnc_img, ma_img1 (JPG 형식)")
        
        # 요청 데이터 준비 (multipart/form-data용) - 타임스탬프 제외
        form_data_base = {
            "api_key": str(API_KEY),
            # timestamp와 signature는 전송 직전에 추가
            "mnc_type": str(mnc_type),
            "mnc_ans_type": str(mnc_ans_type),
            "mnc_title": str(mnc_title),
            "mnc_point": int(0),
            "mnc_limitcnt": int(mnc_limitcnt),
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
        
        print(f"\n[전송 데이터 준비 완료] (타임스탬프 제외)")
        
        # 외부 서버로 직접 요청
        url = f"{BASE_API_URL}/api/v1/mission/create"
        
        # 실제 전송 직전에 타임스탬프 생성 (KST 기준)
        # KST 시간을 기준으로 Unix timestamp 생성 (Unix timestamp는 UTC 기준이지만 KST 시간을 변환)
        kst = timezone(timedelta(hours=9))
        kst_now = datetime.now(kst)
        timestamp_int = int(kst_now.timestamp())
        timestamp_str = str(timestamp_int)
        
        # 타임스탬프 로그 출력
        current_time_utc = datetime.utcnow()
        current_time_kst = datetime.now(timezone(timedelta(hours=9)))
        print(f"\n[타임스탬프 생성 (전송 직전)] Unix Timestamp: {timestamp_int}")
        print(f"[타임스탬프 생성] KST 시간: {current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")
        print(f"[타임스탬프 생성] UTC 시간: {current_time_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"[타임스탬프 검증] KST 기준 생성: {kst_now.strftime('%Y-%m-%d %H:%M:%S')} KST → Unix timestamp: {timestamp_int}")
        
        # 서명 생성 (타임스탬프 포함)
        signature = generate_signature_for_register(
            API_KEY,
            timestamp_str,
            API_SECRET,
            mnc_title
        )
        
        # form_data에 타임스탬프와 서명 추가
        form_data = form_data_base.copy()
        form_data["timestamp"] = timestamp_int  # integer로 유지
        form_data["signature"] = str(signature)
        
        # 전송되는 form_data 전체 로그 출력
        print(f"\n[전송 데이터 전체] form_data:")
        print(json.dumps(form_data, indent=2, ensure_ascii=False, default=str))
        print(f"\n[전송 데이터 확인]")
        print(f"  api_key: {form_data['api_key'][:10]}...")
        print(f"  timestamp 값: {form_data['timestamp']}, 타입: {type(form_data['timestamp']).__name__}")
        print(f"  signature: {form_data['signature'][:20]}...")
        
        print(f"\n[외부 API 전송]")
        print(f"  URL: {url}")
        print(f"  endpoint: /api/v1/mission/create")
        print(f"  timestamp: {timestamp_int} (type: {type(timestamp_int).__name__})")
        
        try:
            response = requests.post(
                url,
                data=form_data,
                files=files if files else None,
                timeout=60
            )
            
            # 응답 상태 코드 확인
            print(f"\n[응답] Status Code: {response.status_code}")
            print(f"[응답] Headers: {dict(response.headers)}")
            
            # 응답 본문 확인
            print(f"[응답 본문 (Raw)]")
            print(f"응답 텍스트 길이: {len(response.text)} bytes")
            
            if not response.text:
                print(f"[오류] 응답 본문이 비어있습니다.")
                return None
            
            print(f"응답 텍스트: {response.text[:500]}")
            
            # JSON 파싱 시도
            try:
                result = response.json()
                print(f"\n[응답 JSON]")
                print(json.dumps(result, indent=2, ensure_ascii=False))
            except json.JSONDecodeError as e:
                print(f"[오류] JSON 파싱 실패: {e}")
                print(f"응답 텍스트 전체:")
                print(response.text)
                return None
            
            # HTTP 에러 상태 코드 확인
            response.raise_for_status()
            
            # 성공 여부 확인
            if isinstance(result, dict) and result.get("result") == "Y":
                print(f"\n[성공] reward_id {reward_id} 미션 등록 완료")
                print(f"   메시지: {result.get('message')}")
                if result.get("data"):
                    data = result["data"]
                    print(f"   mnc_idx: {data.get('mnc_idx')}")
                    print(f"   mnc_uniqnum: {data.get('mnc_uniqnum')}")
                return result
            else:
                print(f"\n[실패] reward_id {reward_id} 미션 등록 실패")
                print(f"   메시지: {result.get('message')}")
                return result
                
        except requests.exceptions.HTTPError as e:
            print(f"[오류] HTTP 에러: {e}")
            if 'response' in locals():
                print(f"   Status Code: {response.status_code}")
                print(f"   Response Text: {response.text}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[오류] API 요청 실패: {e}")
            return None
        except Exception as e:
            print(f"[오류] 예상치 못한 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
            
    finally:
        db.close()


if __name__ == "__main__":
    # reward_id 168 등록
    reward_id = 169
    result = register_reward_mission(reward_id)
    
    if result and result.get("result") == "Y":
        sys.exit(0)
    else:
        sys.exit(1)
