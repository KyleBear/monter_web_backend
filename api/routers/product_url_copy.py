import requests
import re
import time
import json
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def extract_product_info_from_url(url):
    """URL에서 채널ID와 상품ID 추출 (smartstore, brand.naver.com 지원)"""
    parsed = urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    
    # smartstore.naver.com 또는 brand.naver.com 지원
    if 'smartstore.naver.com' in parsed.netloc or 'm.smartstore.naver.com' in parsed.netloc or 'brand.naver.com' in parsed.netloc:
    if len(path_parts) >= 3 and path_parts[1] == 'products':
            channel_id = path_parts[0]
            product_id = path_parts[2]
            return channel_id, product_id
    
    return None, None


def get_nvmid_from_url(url, verbose=False):
    """
    URL에서 nvMid와 상품명 추출
    
    Args:
        url: 스마트스토어 또는 브랜드 스토어 URL
        verbose: 상세 로그 출력 여부
    
    Returns:
        (nvmid, product_name) 튜플 또는 (None, None)
    """
    channel_id, product_id = extract_product_info_from_url(url)
    
    if not product_id:
        if verbose:
            logger.warning(f"URL에서 상품 ID를 추출할 수 없습니다: {url}")
        return None, None
    
    if verbose:
        logger.info(f"채널ID: {channel_id}, 상품ID: {product_id}")
    
    # 방법 1: 모바일 User-Agent
    mobile_url = f"https://m.smartstore.naver.com/{channel_id}/products/{product_id}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
        }
        response = requests.get(mobile_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            html = response.text
            
            # nvMid 패턴 찾기
            patterns = [
                r'"syncNvMid"\s*:\s*(\d+)',
                r'"nvMid"\s*:\s*(\d+)',
                r'syncNvMid\s*:\s*(\d+)',
                r'nvMid\s*:\s*(\d+)',
                r'data-nv-mid="(\d+)"',
                r'nvMid=(\d+)',
            ]
            
            found_nvmids = set()
            
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    if len(match) >= 10:  # nvMid는 보통 10자리 이상
                        found_nvmids.add(match)
            
            # 첫 번째 name 텍스트 추출 (상품명) - 정규식 우선 사용
            product_name = None
            
            # 먼저 정규식으로 직접 "name" 필드 찾기 (더 정확하고 빠름)
            name_pattern = r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"'  # 이스케이프 문자 처리 포함
            matches = re.findall(name_pattern, html, re.IGNORECASE)
            
            if matches:
                if verbose:
                    logger.debug(f"발견된 'name' 필드 개수: {len(matches)}")
                
                # 가장 긴 name 값을 선택 (일반적으로 상품명이 가장 길음)
                best_match = None
                best_length = 0
                
                for match in matches:
                    cleaned = match.strip()
                    # 이스케이프 문자 처리
                    cleaned = cleaned.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                    # HTML 엔티티 디코딩
                    cleaned = cleaned.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
                    
                    # 가장 긴 것을 선택 (상품명은 보통 가장 길다)
                    if len(cleaned) > best_length and len(cleaned) > 5:  # 최소 5자 이상
                        best_match = cleaned
                        best_length = len(cleaned)
                
                if best_match:
                    product_name = best_match
                    if verbose:
                        logger.info(f"상품명 추출 성공 (정규식, 가장 긴 값 선택): {product_name[:50]}...")
                else:
                    # 폴백: 첫 번째 매칭된 name 값 사용
                    product_name = matches[0].strip()
                    product_name = product_name.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                    product_name = product_name.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
                    if product_name and len(product_name) > 0:
                        if verbose:
                            logger.info(f"상품명 추출 성공 (정규식, 첫 번째 값): {product_name[:50]}...")
            
            # 정규식이 실패한 경우 JSON 파싱 시도
            if not product_name:
                # HTML에서 JSON 부분 찾기
                json_patterns = [
                    r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',  # application/json 스크립트
                    r'<script[^>]*>(.*?\{.*?"name".*?\}.*?)</script>',  # 일반 스크립트 태그 내 JSON
                ]
                
                for json_pattern in json_patterns:
                    json_matches = re.findall(json_pattern, html, re.DOTALL | re.IGNORECASE)
                    for json_str in json_matches:
                        try:
                            # JSON 파싱 시도
                            data = json.loads(json_str.strip())
                            # 재귀적으로 첫 번째 "name" 키 찾기
                            def find_first_name(obj):
                                if isinstance(obj, dict):
                                    if 'name' in obj:
                                        return obj['name']
                                    for value in obj.values():
                                        result = find_first_name(value)
                                        if result:
                                            return result
                                elif isinstance(obj, list):
                                    for item in obj:
                                        result = find_first_name(item)
                                        if result:
                                            return result
                                return None
                            
                            product_name = find_first_name(data)
                            if product_name:
                                product_name = str(product_name).strip()
                                # HTML 엔티티 디코딩
                                product_name = product_name.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
                                if product_name and len(product_name) > 0:
                                    if verbose:
                                        logger.info(f"상품명 추출 성공 (JSON 파싱): {product_name[:50]}...")
                                    break
                        except (json.JSONDecodeError, ValueError) as e:
                            continue
                    
                    if product_name:
                        break
            
            if found_nvmids:
                nvmid = sorted(found_nvmids)[0]
                if verbose:
                    logger.info(f"nvMid 추출 성공: {nvmid}")
                return nvmid, product_name
            else:
                if verbose:
                    logger.warning("nvMid 패턴을 찾을 수 없습니다")
                return None, product_name  # nvmid는 없지만 상품명은 있을 수 있음
    
    except Exception as e:
        if verbose:
            logger.warning(f"모바일 User-Agent 방법 실패: {str(e)}")
    
    time.sleep(2)
    
    # 방법 2: Session 사용
    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        
        # 메인 페이지 먼저 방문
        session.get('https://m.smartstore.naver.com', headers=headers, timeout=10)
        time.sleep(1)
        
        # 상품 페이지
        response = session.get(mobile_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            html = response.text
            
            patterns = [
                r'"syncNvMid"\s*:\s*(\d+)',
                r'"nvMid"\s*:\s*(\d+)',
                r'syncNvMid\s*:\s*(\d+)',
                r'nvMid\s*:\s*(\d+)',
                r'data-nv-mid="(\d+)"',
                r'nvMid=(\d+)',
            ]
            
            found_nvmids = set()
            
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    if len(match) >= 10:
                        found_nvmids.add(match)
            
            # 첫 번째 name 텍스트 추출 (상품명) - 정규식 우선 사용
            product_name = None
            
            # 먼저 정규식으로 직접 "name" 필드 찾기 (더 정확하고 빠름)
            name_pattern = r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"'  # 이스케이프 문자 처리 포함
            matches = re.findall(name_pattern, html, re.IGNORECASE)
            
            if matches:
                if verbose:
                    logger.debug(f"발견된 'name' 필드 개수: {len(matches)}")
                
                # 가장 긴 name 값을 선택 (일반적으로 상품명이 가장 길음)
                best_match = None
                best_length = 0
                
                for match in matches:
                    cleaned = match.strip()
                    # 이스케이프 문자 처리
                    cleaned = cleaned.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                    # HTML 엔티티 디코딩
                    cleaned = cleaned.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
                    
                    # 가장 긴 것을 선택 (상품명은 보통 가장 길다)
                    if len(cleaned) > best_length and len(cleaned) > 5:  # 최소 5자 이상
                        best_match = cleaned
                        best_length = len(cleaned)
                
                if best_match:
                    product_name = best_match
                    if verbose:
                        logger.info(f"상품명 추출 성공 (정규식, 가장 긴 값 선택): {product_name[:50]}...")
                else:
                    # 폴백: 첫 번째 매칭된 name 값 사용
                    product_name = matches[0].strip()
                    product_name = product_name.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                    product_name = product_name.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
                    if product_name and len(product_name) > 0:
                        if verbose:
                            logger.info(f"상품명 추출 성공 (정규식, 첫 번째 값): {product_name[:50]}...")
            
            # 정규식이 실패한 경우 JSON 파싱 시도
            if not product_name:
                # HTML에서 JSON 부분 찾기
                json_patterns = [
                    r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',  # application/json 스크립트
                    r'<script[^>]*>(.*?\{.*?"name".*?\}.*?)</script>',  # 일반 스크립트 태그 내 JSON
                ]
                
                for json_pattern in json_patterns:
                    json_matches = re.findall(json_pattern, html, re.DOTALL | re.IGNORECASE)
                    for json_str in json_matches:
                        try:
                            # JSON 파싱 시도
                            data = json.loads(json_str.strip())
                            # 재귀적으로 첫 번째 "name" 키 찾기
                            def find_first_name(obj):
                                if isinstance(obj, dict):
                                    if 'name' in obj:
                                        return obj['name']
                                    for value in obj.values():
                                        result = find_first_name(value)
                                        if result:
                                            return result
                                elif isinstance(obj, list):
                                    for item in obj:
                                        result = find_first_name(item)
                                        if result:
                                            return result
                                return None
                            
                            product_name = find_first_name(data)
                            if product_name:
                                product_name = str(product_name).strip()
                                # HTML 엔티티 디코딩
                                product_name = product_name.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
                                if product_name and len(product_name) > 0:
                                    if verbose:
                                        logger.info(f"상품명 추출 성공 (JSON 파싱): {product_name[:50]}...")
                                    break
                        except (json.JSONDecodeError, ValueError) as e:
                            continue
                    
                    if product_name:
                        break
            
            if found_nvmids:
                nvmid = sorted(found_nvmids)[0]
                if verbose:
                    logger.info(f"nvMid 추출 성공: {nvmid}")
                return nvmid, product_name
            else:
                if verbose:
                    logger.warning("nvMid 패턴을 찾을 수 없습니다")
                return None, product_name  # nvmid는 없지만 상품명은 있을 수 있음
    
    except Exception as e:
        if verbose:
            logger.warning(f"Session 방법 실패: {str(e)}")
    
    return None, None


# 실행
if __name__ == "__main__":
    # url = "https://brand.naver.com/jipban/products/5565421632"
    url = "https://smartstore.naver.com/pettimes/products/10861603621"
    # url = "https://m.brand.naver.com/jipban/products/5565421632"
    print("="*60)
    print(f"테스트 URL: {url}")
    print("="*60)
    
    nvmid, product_name = get_nvmid_from_url(url)
    
    print("\n" + "="*60)
    print("최종 결과")
    print("="*60)
    
    if nvmid:
        print(f"✓ 성공!")
        print(f"nvMid: {nvmid}")
    else:
        print("✗ nvMid 추출 실패")
        print("\n가능한 해결 방법:")
        print("1. Selenium/Playwright로 JavaScript 렌더링 후 추출")
        print("2. 브라우저 개발자 도구에서 수동 확인")
        print("3. API 응답에서 직접 추출 (제공된 JSON 데이터 사용)")
    
    if product_name:
        print(f"상품명: {product_name}")
    else:
        print("✗ 상품명 추출 실패")