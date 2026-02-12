import requests
import time
from concurrent.futures import ThreadPoolExecutor

url = "https://re-switch.co.kr/redirect/4e6P53l8pS"
total = 100
concurrent = 20

def test(i):
    start = time.time()
    r = requests.get(url, allow_redirects=False, verify=False)  # ← verify=False 추가
    print(f"{i}: {r.status_code} - {time.time()-start:.3f}s")
    return r.status_code == 302

# 경고 메시지 숨기기
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

start_time = time.time()
with ThreadPoolExecutor(max_workers=concurrent) as executor:
    results = list(executor.map(test, range(total)))

total_time = time.time() - start_time
success = sum(results)

print(f"\n총 {total}개 요청")
print(f"성공: {success}")
print(f"시간: {total_time:.2f}초")
print(f"RPS: {total/total_time:.2f}")