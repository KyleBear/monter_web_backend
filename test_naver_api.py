import os
import requests
from dotenv import load_dotenv

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

API_URL = "https://openapi.naver.com/v1/search/shop.json"

headers = {
    "X-Naver-Client-Id": NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}

params = {
    "query": "게이밍의자",
    "display": 100,  # 최대 100개
    "start": 1,
    "sort": "sim"
}

print("=" * 70)
print("네이버 쇼핑 API 테스트: '게이밍의자' 검색")
print("=" * 70)

try:
    response = requests.get(API_URL, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    
    data = response.json()
    items = data.get("items", [])
    total = data.get("total", 0)
    
    print(f"\n총 검색 결과: {total}개")
    print(f"반환된 결과: {len(items)}개 (순위 1~{len(items)}위)\n")
    
    for idx, item in enumerate(items, 1):
        print(f"[순위 {idx}]")
        print(f"  상품명: {item.get('title', '')}")
        print(f"  쇼핑몰: {item.get('mallName', '')}")
        print(f"  가격: {item.get('lprice', '')}원")
        print(f"  productId: {item.get('productId', '')}")
        print(f"  link: {item.get('link', '')}")
        print()
    
    print("=" * 70)
    
except Exception as e:
    print(f"오류 발생: {e}")
