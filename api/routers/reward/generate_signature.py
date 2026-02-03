"""
서명 발급 유틸리티
HMAC-MD5 서명 생성 도구
"""
import hmac
import hashlib
import time
from datetime import datetime, timezone, timedelta

# API 설정
API_KEY = "53fecc7c7c0862714392995f89859a7f"
SECRET_KEY = "29eac57eca9d72d00b5454c60a8463be29e6d1ef42ca19d952af469f79358c56"

# 테스트 데이터
MNC_TITLE = "라봉홈"
MNC_POINT = 100


def generate_signature_method1(api_key: str, timestamp: str, mnc_title: str, mnc_point: int) -> str:
    """
    방법 1: hmac.new(api_key, message, md5)
    API Key를 키로 사용하여 서명 생성
    
    Args:
        api_key: API Key
        timestamp: 타임스탬프 (문자열)
        mnc_title: 미션 제목
        mnc_point: 미션 포인트 (정수, 문자열로 변환됨)
    
    Returns:
        서명 (hexdigest)
    """
    # Message: api_key + timestamp + mnc_title + mnc_point
    message = f"{api_key}{timestamp}{mnc_title}{mnc_point}"
    
    # hmac.new(api_key, message, md5)
    signature = hmac.new(
        api_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    
    return signature


def generate_signature_method2(api_key: str, secret_key: str, timestamp: str, mnc_title: str, mnc_point: int) -> str:
    """
    방법 2: hmac.new(secret_key, message, md5)
    Secret Key를 키로 사용하여 서명 생성
    
    Args:
        api_key: API Key
        secret_key: Secret Key
        timestamp: 타임스탬프 (문자열)
        mnc_title: 미션 제목
        mnc_point: 미션 포인트 (정수, 문자열로 변환됨)
    
    Returns:
        서명 (hexdigest)
    """
    # Message: api_key + timestamp + mnc_title + mnc_point
    message = f"{api_key}{timestamp}{mnc_title}{str(mnc_point)}"
    
    # hmac.new(secret_key, message, md5)
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.md5
    ).hexdigest()
    
    return signature


def main():
    """메인 함수 - 서명 생성 예시"""
    print("=" * 70)
    print("서명 발급 유틸리티")
    print("=" * 70)
    
    # 현재 Unix timestamp 사용 (UTC 기준)
    timestamp = int(datetime.utcnow().timestamp())
    timestamp_str = str(timestamp)
    
    print(f"\n[입력 값]")
    print(f"API Key: {API_KEY}")
    print(f"Secret Key: {SECRET_KEY[:20]}... (전체 길이: {len(SECRET_KEY)})")
    print(f"MNC Title: {MNC_TITLE}")
    print(f"MNC Point: {MNC_POINT}")
    print(f"\n[현재 Timestamp (UTC)]")
    print(f"Unix Timestamp: {timestamp}")
    current_time_utc = datetime.utcnow()
    current_time_kst = datetime.now(timezone(timedelta(hours=9)))
    print(f"해당 시간 (UTC): {current_time_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"해당 시간 (KST): {current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")
    print(f"타임스탬프 유효 기간: 5분 (현재 시간 기준 ±5분)")
    
    # Message 생성
    message = f"{API_KEY}{timestamp_str}{MNC_TITLE}{MNC_POINT}"
    print(f"\n[Message 구성]")
    print(f"Message = api_key + timestamp + mnc_title + mnc_point")
    print(f"Message = {API_KEY} + {timestamp_str} + {MNC_TITLE} + {MNC_POINT}")
    print(f"Message: {message}")
    
    # 방법 1: API Key를 키로 사용
    print(f"\n{'=' * 70}")
    print("[방법 1] hmac.new(api_key, message, md5)")
    print(f"{'=' * 70}")
    signature1 = generate_signature_method1(API_KEY, timestamp_str, MNC_TITLE, MNC_POINT)
    print(f"서명: {signature1}")
    print(f"서명 길이: {len(signature1)} characters")
    
    # 방법 2: Secret Key를 키로 사용
    print(f"\n{'=' * 70}")
    print("[방법 2] hmac.new(secret_key, message, md5)")
    print(f"{'=' * 70}")
    signature2 = generate_signature_method2(API_KEY, SECRET_KEY, timestamp_str, MNC_TITLE, MNC_POINT)
    print(f"서명: {signature2}")
    print(f"서명 길이: {len(signature2)} characters")
    
    print(f"\n{'=' * 70}")
    print("서명 생성 완료")
    print(f"{'=' * 70}")
    
    # 사용 예시
    print(f"\n[사용 예시 코드]")
    print("""
# 방법 1 사용
signature1 = generate_signature_method1(api_key, timestamp, mnc_title, mnc_point)

# 방법 2 사용
signature2 = generate_signature_method2(api_key, secret_key, timestamp, mnc_title, mnc_point)
    """)


if __name__ == "__main__":
    main()
