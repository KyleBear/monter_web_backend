import os
import sys
import time
import re
import logging
import requests
import random
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from itertools import combinations
from urllib.parse import quote, urlparse, parse_qs
from dotenv import load_dotenv
import json
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from contextlib import contextmanager
import threading
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
# .env 파일 로드
load_dotenv()
# 순위 집계는 DB에 저장 안됩니다. 

# 셀루션 - CPC, 키워드가 너무 없을때 메인 키워드 로 조합해서 조합.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 만료일 설정
EXPIRATION_DATE = date(2026, 10, 1)  # 2026년 10월 1일까지 사용 가능

# 여러 계정의 NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 리스트
# 각 계정은 (client_id, secret) 튜플 형태
_NAVER_ACCOUNTS = [
    ("OUkrglPR4aNXUFG1uczo", "bEFr5g3MWR"),  # 계정 1
    ("ekrENufxs80GF1M3TC", "gI7WnZDVfv"),
    ("tKHGILSBqbkNUcu6YhAu", "onKA2Muf94"),
    ("KrEq2Kf3oMIv1PlXsW6N", "XixeT6bYgy"),
    ("mXGE2TH5veSBOIPKQRRO", "qczpqj2cCz"),
    ("0Sp_u7mF0nWSX2Os0yqB", "QTFdtNlTKQ"),
    ("vwoIWRFdxrJzRKRD5Tx5", "g3cmlqcAbB"),
    # 추가 계정을 여기에 추가하세요
    # ("client_id_2", "secret_2"),
    # ("client_id_3", "secret_3"),
]

# Client ID Rotation 관리 클래스
class ClientIDRotator:
    """여러 Client ID를 랜덤으로 사용하는 클래스"""
    def __init__(self, accounts: List[tuple]):
        """
        Args:
            accounts: [(client_id, secret), ...] 형태의 리스트
        """
        self.accounts = accounts
        self.lock = threading.Lock()
        self.failed_accounts = set()  # 실패한 계정 추적
    
    def get_next(self) -> tuple:
        """다음 Client ID/Secret 반환 (랜덤 선택)"""
        with self.lock:
            if not self.accounts:
                raise ValueError("사용 가능한 계정이 없습니다.")
            
            # 실패한 계정 제외하고 사용 가능한 계정만 필터링
            available_accounts = [acc for i, acc in enumerate(self.accounts) 
                                    if i not in self.failed_accounts]
            
            if not available_accounts:
                # 모든 계정이 실패한 경우, 실패 목록 초기화 후 재시도
                logger.warning("모든 계정이 실패했습니다. 실패 목록을 초기화하고 재시도합니다.")
                self.failed_accounts.clear()
                available_accounts = self.accounts
            
            # 랜덤으로 계정 선택
            account = random.choice(available_accounts)
            
            return account
    
    def mark_failed(self, client_id: str):
        """계정 실패 표시"""
        with self.lock:
            for i, (cid, _) in enumerate(self.accounts):
                if cid == client_id:
                    self.failed_accounts.add(i)
                    logger.warning(f"계정 실패 표시: {client_id}")
                    break
    
    def reset_failed(self):
        """실패한 계정 목록 초기화"""
        with self.lock:
            self.failed_accounts.clear()

# 만료일 확인 및 계정 필터링
def check_and_filter_accounts():
    """만료일 확인 후 만료되었으면 계정을 빈칸으로 설정"""
    today = date.today()
    if today > EXPIRATION_DATE:
        # 만료일이 지났으면 빈 계정 리스트 반환
        return [("", "")]
    else:
        # 정상적인 경우 계정 리스트 사용
        return _NAVER_ACCOUNTS

# 만료일 확인 후 계정 리스트 설정
NAVER_ACCOUNTS = check_and_filter_accounts()

# Client ID Rotator 인스턴스 생성
client_rotator = ClientIDRotator(NAVER_ACCOUNTS)

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 데이터랩 (쇼핑인사이트)

def get_shopping_rank_with_ad_flag(
    keyword: str,
    display: int = 100,
    start: int = 1,
    sort: str = "sim",
    filter: Optional[str] = None,
    exclude: Optional[str] = None
) -> List[Dict]:
    """
    네이버 오픈 API를 사용하여 쇼핑 검색 결과 조회
    
    Args:
        keyword: 검색어 (UTF-8 인코딩 필요)
        display: 한 번에 표시할 검색 결과 개수 (기본값: 100, 최댓값: 100)
        start: 검색 시작 위치 (기본값: 1, 최댓값: 1000)
        sort: 정렬 방법 (sim: 정확도순, date: 날짜순, asc: 가격 오름차순, dsc: 가격 내림차순)
        filter: 검색 결과에 포함할 상품 유형 (None: 모든 상품, "naverpay": 네이버페이 연동 상품)
        exclude: 검색 결과에서 제외할 상품 유형 (예: "used", "rental", "cbshop" 또는 "used:cbshop" 등)
    
    Returns:
        list: 검색 결과 리스트
        [
            {
                "keyword": str,
                "rank": int,
                "product_name": str,
                "mall_name": str,
                "price": str,
                "productId": str,  # nvmid 매칭용 -- product_id 와 nvmid 는 다른것입니다. 
                "link": str,  # nvmid 추출용
                "is_shopping_exposed": bool,
                ...
            },
            ...
        ]
    
    참고: https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
    """
    # display 값 검증 (1~100)
    if display < 1 or display > 100:
        raise ValueError("display 값은 1~100 사이여야 합니다.")
    # 상품정보 url, 
    # 상품 이미지 url
    
    # start 값 검증 (1~1000)
    if start < 1 or start > 1000:
        raise ValueError("start 값은 1~1000 사이여야 합니다.")
    
    # sort 값 검증
    valid_sorts = ["sim", "date", "asc", "dsc"]
    if sort not in valid_sorts:
        raise ValueError(f"sort 값은 {valid_sorts} 중 하나여야 합니다.")
    
    # filter 값 검증
    if filter is not None and filter not in ["naverpay"]:
        logger.warning(f"filter 값 '{filter}'는 유효하지 않습니다. 'naverpay'만 지원됩니다.")
        filter = None
    
    # exclude 값 검증 (used, rental, cbshop 조합 가능)
    if exclude is not None:
        valid_exclude_options = ["used", "rental", "cbshop"]
        exclude_parts = exclude.split(":")
        for part in exclude_parts:
            if part not in valid_exclude_options:
                logger.warning(f"exclude 값 '{part}'는 유효하지 않습니다. {valid_exclude_options}만 지원됩니다.")
                exclude = None
                break
    
    # 요청 파라미터 설정
    params = {
        "query": keyword,  # 검색어 (UTF-8 인코딩, requests가 자동 처리)
        "display": display,  # 한 번에 표시할 검색 결과 개수
        "start": start,  # 검색 시작 위치
        "sort": sort  # 정렬 방법
    }
    
    # filter 파라미터 추가 (None이 아니면 추가)
    if filter:
        params["filter"] = filter
    
    # exclude 파라미터 추가 (None이 아니면 추가)
    if exclude:
        params["exclude"] = exclude
    
    # Client ID Rotation: 여러 계정을 순환 사용
    max_retries = len(NAVER_ACCOUNTS) if NAVER_ACCOUNTS else 1
    last_error = None
    response = None
    
    for attempt in range(max_retries):
        try:
            # 다음 계정 가져오기 (rotation)
            client_id, client_secret = client_rotator.get_next()
            
            if not client_id or not client_secret:
                raise ValueError("유효한 Client ID와 Secret이 없습니다.")
            # HTTP 헤더 설정 (네이버 오픈 API 문서 참고)
            headers = {
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            }        
            # API 요청
            response = requests.get(API_URL, headers=headers, params=params, timeout=10)
            
            # 401 Unauthorized 오류 시 다른 계정으로 재시도
            if response.status_code == 401:
                logger.warning(f"401 Unauthorized - 계정 {client_id} 인증 실패, 다른 계정으로 재시도...")
                client_rotator.mark_failed(client_id)
                if attempt < max_retries - 1:
                    time.sleep(1)  # 잠시 대기 후 재시도
                    continue
                else:
                    raise ValueError("유효한 Client ID와 Secret이 없습니다.")
        
            # 429 Too Many Requests 오류 시 다른 계정으로 재시도
            if response.status_code == 429:
                logger.warning(f"429 Too Many Requests - 계정 {client_id} 제한 초과, 다른 계정으로 재시도...")
                client_rotator.mark_failed(client_id)
                if attempt < max_retries - 1:
                    time.sleep(1)  # 잠시 대기 후 재시도
                    continue
                else:
                    response.raise_for_status()
            
            # 403 Forbidden 오류 시 다른 계정으로 재시도
            if response.status_code == 403:
                logger.warning(f"403 Forbidden - 계정 {client_id} 권한 없음, 다른 계정으로 재시도...")
                client_rotator.mark_failed(client_id)
                if attempt < max_retries - 1:
                    time.sleep(1)  # 잠시 대기 후 재시도
                    continue
                else:
                    response.raise_for_status()
            
            # 기타 오류는 즉시 발생
            response.raise_for_status()
            
            # 성공 시 break
            break
            
        except requests.exceptions.HTTPError as e:
            last_error = e
            if e.response.status_code in [401, 429, 403]:
                # 이미 처리됨
                continue
            else:
                # 기타 HTTP 오류는 재시도하지 않음
                raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"API 요청 실패 (시도 {attempt + 1}/{max_retries}): {e}, 다른 계정으로 재시도...")
                time.sleep(1)
                continue
            else:
                raise
    
    # 모든 재시도 실패 시 마지막 오류 발생
    if last_error or response is None:
        if last_error:
            raise last_error
        else:
            raise ValueError("API 요청에 실패했습니다.")
    
    try:
        # JSON 응답 파싱
        data = response.json()
        
        items = data.get("items", [])
        total = data.get("total", 0)
        
        logger.info(f"네이버 오픈 API 응답: 총 {total}개 결과, {len(items)}개 반환")
        if filter:
            logger.info(f"필터 적용: {filter}")
        if exclude:
            logger.info(f"제외 옵션: {exclude}")
        
        results = []
        for rank, item in enumerate(items, start=1):
            # 네이버 오픈 API 응답 필드 (문서 참고)
            result = {
                "keyword": keyword,
                "rank": rank + start - 1,  # 전체 순위 (start 기준)
                "product_name": item.get("title", ""),  # 상품명
                "mall_name": item.get("mallName", ""),  # 쇼핑몰명
                "price": item.get("lprice", ""),  # 최저가
                "hprice": item.get("hprice", ""),  # 최고가
                "productId": item.get("productId", ""),  # 상품 ID (nvmid 매칭용)
                "link": item.get("link", ""),  # 상품 링크 (nvmid 추출용)
                "image": item.get("image", ""),  # 이미지 URL
                "productType": item.get("productType", ""),  # 상품 유형
                "brand": item.get("brand", ""),  # 브랜드
                "maker": item.get("maker", ""),  # 제조사
                "category1": item.get("category1", ""),  # 카테고리1
                "category2": item.get("category2", ""),  # 카테고리2
                "category3": item.get("category3", ""),  # 카테고리3
                "category4": item.get("category4", ""),  # 카테고리4
                "is_shopping_exposed": True,
            }
            
            results.append(result)
        
        return results
        
    except requests.exceptions.RequestException as e:
        logger.error(f"네이버 오픈 API 요청 실패: {e}", exc_info=True)
        raise
    except ValueError as e:
        logger.error(f"네이버 오픈 API 응답 파싱 실패: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"네이버 오픈 API 호출 중 예상치 못한 오류: {e}", exc_info=True)
        raise


# ============================================================================
# 키워드 조합 및 네이버 쇼핑 검색 기능
# ============================================================================

def split_keywords_by_space(keyword: str) -> List[str]:
    """키워드를 띄어쓰기로 나누어 단어 리스트 반환"""
    if not keyword:
        return []
    
    words = re.split(r'\s+', keyword.strip())
    words = [w for w in words if w]
    
    logger.info(f"키워드 분리: '{keyword}' → {words} ({len(words)}개 단어)")
    return words


def generate_keyword_combinations(words: list, min_length: int = 2, max_length: int = None) -> List[str]:
    """
    단어 리스트에서 순차 조합 생성 (2단어 -> 3단어 -> ... -> max_length 단어)
    keyword_search_v3.py의 generate_keyword_combinations 참고
    
    Args:
        words: 단어 리스트
        min_length: 최소 조합 길이 (기본값: 2)
        max_length: 최대 조합 길이 (None이면 words 길이)
    
    Returns:
        list: 조합된 키워드 문자열 리스트
    """
    if not words:
        return []
    
    if max_length is None:
        max_length = len(words)
    
    max_length = min(max_length, len(words))
    combinations_list = []
    
    # 2단어 조합부터 max_length 단어 조합까지
    for length in range(min_length, max_length + 1):
        for combo in combinations(range(len(words)), length):
            combo_words = [words[i] for i in combo]
            combo_keyword = ' '.join(combo_words)
            combinations_list.append(combo_keyword)
    
    logger.info(f"키워드 조합 생성: {len(words)}개 단어 → {len(combinations_list)}개 조합 (길이 {min_length}~{max_length})")
    return combinations_list


def check_shopping_rank_for_keyword(
    keyword: str,
    nvmid: str,
    driver: webdriver.Chrome
) -> Dict:
    """
    특정 키워드로 네이버 통합검색 후 nvmid의 광고 여부 및 노출 여부 확인
    (test5.py의 create_click_result_script 참조)
    
    Args:
        keyword: 검색 키워드
        nvmid: 찾을 상품의 nvmid
        driver: Selenium WebDriver 인스턴스
    
    Returns:
        dict: {
            "keyword": str,
            "is_shopping_exposed": bool,  # 통검 쇼핑 노출 여부 (boolean)
            "cpc": bool,  # 광고 여부 (boolean)
        }
    """
    result = {
        "keyword": keyword,
        "is_shopping_exposed": False,  # 통검에서 nvmid 노출 여부 (boolean)
        "cpc": False  # 광고 여부 (boolean)
    }
    
    try:
        # 네이버 통합검색 URL (모바일)
        encoded_keyword = quote(keyword)
        search_url = f"https://m.search.naver.com/search.naver?query={encoded_keyword}"
        
        logger.debug(f"통검 페이지 접속: {search_url}")
        driver.get(search_url)
        
        # 페이지 로딩 대기 최적화
        time.sleep(2)  # 5초 → 2초로 단축
        
        # 페이지 준비 상태 확인 (타임아웃 단축)
        try:
            WebDriverWait(driver, 5).until(  # 10초 → 5초로 단축
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception as e:
            logger.debug(f"페이지 로딩 대기 중 오류 (계속 진행): {e}")
        
        # 검색 결과에서 nvmid 찾기 (최적화된 스크롤 및 조기 종료)
        try:
            found_nvmid = False
            is_ad = False
            target_nvmid = str(nvmid).strip()
            
            # 최대 2번만 스크롤 (3번 → 2번으로 단축)
            scroll_attempts = 0
            max_scroll_attempts = 2
            
            while scroll_attempts < max_scroll_attempts:
                # 현재 페이지에서 nvmid 찾기 (스크롤 전에 먼저 확인)
                all_links = driver.find_elements(By.CSS_SELECTOR, 'a[aria-labelledby^="view_type_guide_"]')
            
            for link in all_links:
                try:
                    aria_id = link.get_attribute('aria-labelledby')
                    if aria_id and aria_id.startswith('view_type_guide_'):
                        extracted_nvmid = aria_id.replace('view_type_guide_', '')
                        
                        if extracted_nvmid == target_nvmid:
                            found_nvmid = True
                            
                            # 광고 여부 확인
                            try:
                                # 부모 li 요소 찾기 (XPath 사용)
                                parent_li = link.find_element(By.XPATH, './ancestor::li[1]')
                                
                                # 광고 태그 확인
                                # 방법 1: pbjVN80V 클래스 확인
                                try:
                                    parent_li.find_element(By.CSS_SELECTOR, '.pbjVN80V')
                                    is_ad = True
                                except:
                                    pass
                                
                                # 방법 2: SucLwbaS 클래스 확인
                                if not is_ad:
                                    try:
                                        parent_li.find_element(By.CSS_SELECTOR, 'a.SucLwbaS')
                                        is_ad = True
                                    except:
                                        pass
                                
                                # 방법 3: "광고" 텍스트를 가진 blind 클래스 span 확인
                                if not is_ad:
                                    try:
                                        blind_spans = parent_li.find_elements(By.CSS_SELECTOR, 'span.blind')
                                        for span in blind_spans:
                                            if '광고' in span.text:
                                                is_ad = True
                                                break
                                    except:
                                        pass
                            except Exception as e:
                                logger.debug(f"광고 여부 확인 중 오류: {e}")
                            
                                break  # nvmid를 찾았으므로 즉시 종료
                except Exception as e:
                    logger.debug(f"링크 처리 중 오류: {e}")
                    continue
            
                if found_nvmid:
                    break  # 찾으면 스크롤 중단
                
                # 스크롤
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)  # 3초 → 1.5초로 단축
                
                scroll_attempts += 1
            
            result["is_shopping_exposed"] = found_nvmid
            result["cpc"] = is_ad
            
            if found_nvmid:
                logger.debug(f"✓ 키워드 '{keyword}': 통검 노출={found_nvmid}, CPC={is_ad} (대상 nvmid: {nvmid})")
            else:
                logger.debug(f"✗ 키워드 '{keyword}': 통검 노출 없음 (대상 nvmid: {nvmid})")
                
        except Exception as e:
            logger.error(f"nvmid 검색 중 예외 발생: {e}", exc_info=True)
            result["is_shopping_exposed"] = False
            result["cpc"] = False
        
    except Exception as e:
        logger.error(f"키워드 '{keyword}' 검색 중 오류: {e}", exc_info=True)
    
    return result


# ============================================================================
# 스마트스토어 URL에서 nvmid 추출 및 상품 정보 조회
# ============================================================================

def extract_smart_store_product_id_from_url(smart_store_url: str) -> Optional[str]:
    """
    스마트스토어 URL에서 product_id(스마트스토어 상품 ID) 추출
    
    Args:
        smart_store_url: 스마트스토어 URL
            예: https://brand.naver.com/jungmiso/products/12954360478?...
    
    Returns:
        str or None: 추출된 스마트스토어 product_id (없으면 None)
    """
    if not smart_store_url:
        return None
    
    try:
        # URL 파싱
        parsed_url = urlparse(smart_store_url)
        path_match = re.search(r'/products/(\d+)', parsed_url.path)
        if path_match:
            product_id = path_match.group(1)
            logger.info(f"URL 경로에서 스마트스토어 product_id 추출: {product_id}")
            return product_id
        
        # 방법 2: 쿼리 파라미터에서 n_mall_pid 추출
        # 예: ?n_mall_pid=12954360478
        query_params = parse_qs(parsed_url.query)
        if 'n_mall_pid' in query_params:
            product_id = query_params['n_mall_pid'][0]
            logger.info(f"쿼리 파라미터에서 스마트스토어 product_id 추출: {product_id}")
            return product_id
        
        # 방법 3: URL 전체에서 숫자 패턴 찾기 (마지막 시도)
        # products/ 뒤의 숫자 또는 n_mall_pid= 뒤의 숫자
        patterns = [
            r'/products/(\d+)',
            r'n_mall_pid[=_](\d+)',
            r'products/(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, smart_store_url, re.IGNORECASE)
            if match:
                product_id = match.group(1)
                logger.info(f"패턴 매칭으로 스마트스토어 product_id 추출: {product_id} (패턴: {pattern})")
                return product_id
        
        logger.warning(f"스마트스토어 URL에서 product_id를 추출할 수 없습니다: {smart_store_url}")
        return None
        
    except Exception as e:
        logger.error(f"스마트스토어 URL 파싱 중 오류: {e}", exc_info=True)
        return None


def extract_nvmid_from_smart_store_product_id(
    keyword: str,
    smart_store_product_id: str
) -> Optional[str]:
    """
    스마트스토어 product_id로 네이버 쇼핑 API 검색하여 실제 nvmid 추출
    
    Args:
        keyword: 검색 키워드 (예: "두바이쫀득쿠키")
        smart_store_product_id: 스마트스토어 product_id (예: "12954360478")
    
    Returns:
        str or None: 추출된 nvmid (없으면 None)
    """
    if not NAVER_ACCOUNTS or not any(acc[0] and acc[1] for acc in NAVER_ACCOUNTS):
        logger.error("유효한 NAVER 계정이 필요합니다.")
        return None
    
    if not keyword or not smart_store_product_id:
        logger.error("keyword와 smart_store_product_id가 필요합니다.")
        return None
    
    try:
        # 키워드로 네이버 쇼핑 API 검색
        logger.info(f"키워드 '{keyword}'로 검색하여 스마트스토어 product_id '{smart_store_product_id}'의 nvmid 찾기")
        api_results = get_shopping_rank_with_ad_flag(keyword, display=100, filter=None)
        
        target_product_id = str(smart_store_product_id).strip()
        
        # 검색 결과에서 스마트스토어 product_id와 매칭되는 상품 찾기
        for item in api_results:
            link = item.get("link", "")
            
            if link:
                # link URL에서 스마트스토어 product_id 추출 시도
                # 스마트스토어 URL 패턴: brand.naver.com/.../products/{product_id}
                # 또는 n_mall_pid={product_id}
                patterns = [
                    r'/products/' + re.escape(target_product_id) + r'(?:\?|$|/)',  # /products/12954360478
                    r'n_mall_pid[=_]' + re.escape(target_product_id) + r'(?=&|$)',  # n_mall_pid=12954360478
                    r'brand\.naver\.com[^/]*/products/' + re.escape(target_product_id),  # brand.naver.com/.../products/12954360478
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, link, re.IGNORECASE)
                    if match:
                        # 스마트스토어 product_id와 매칭됨, 이제 실제 nvmid 추출
                        # 방법 1: productId가 nvmid일 수 있음
                        product_id = str(item.get("productId", "")).strip()
                        if product_id:
                            logger.info(f"스마트스토어 product_id '{target_product_id}' 매칭 성공, nvmid: {product_id}")
                            return product_id
                        
                        # 방법 2: link URL에서 nvmid 추출
                        nvmid_patterns = [
                            r'nv_mid[=_](\d+)',  # nv_mid= 또는 nv_mid_
                            r'nvmid[=_](\d+)',   # nvmid= 또는 nvmid_
                            r'nv-mid[=_](\d+)',  # nv-mid= 또는 nv-mid_
                        ]
                        
                        for nvmid_pattern in nvmid_patterns:
                            nvmid_match = re.search(nvmid_pattern, link, re.IGNORECASE)
                            if nvmid_match:
                                nvmid = nvmid_match.group(1)
                                logger.info(f"스마트스토어 product_id '{target_product_id}' 매칭 성공, nvmid: {nvmid}")
                                return nvmid
        
        logger.warning(f"키워드 '{keyword}' 검색 결과에서 스마트스토어 product_id '{target_product_id}'를 찾을 수 없습니다.")
        return None
        
    except Exception as e:
        logger.error(f"nvmid 추출 중 오류: keyword='{keyword}', product_id='{smart_store_product_id}', error={e}", exc_info=True)
        return None


def get_product_info_by_keyword_and_url(
    main_keyword: str,
    smart_store_url: str
) -> Dict:
    """
    메인 키워드와 스마트스토어 URL을 받아서 상품 순위, 상품명, 상품 nvmid를 반환
    
    Args:
        main_keyword: 메인 키워드 (예: "두바이쫀득쿠키")
        smart_store_url: 스마트스토어 URL
            예: "https://brand.naver.com/jungmiso/products/12954360478?..."
    
    Returns:
        dict: {
            "success": bool,
            "main_keyword": str,
            "smart_store_url": str,
            "nvmid": str or None,
            "rank": int or None,
            "product_name": str or None,
            "error": str or None
        }
    """
    result = {
        "success": False,
        "main_keyword": main_keyword,
        "smart_store_url": smart_store_url,
        "nvmid": None,
        "rank": None,
        "product_name": None,
        "error": None
    }
    
    try:
        # 계정 확인
        if not NAVER_ACCOUNTS or not any(acc[0] and acc[1] for acc in NAVER_ACCOUNTS):
            result["error"] = "유효한 NAVER 계정이 필요합니다."
            logger.error(result["error"])
            return result
        
        # 스마트스토어 URL에서 product_id 추출
        smart_store_product_id = extract_smart_store_product_id_from_url(smart_store_url)
        if not smart_store_product_id:
            result["error"] = f"스마트스토어 URL에서 product_id를 추출할 수 없습니다: {smart_store_url}"
            logger.error(result["error"])
            return result
        
        # 스마트스토어 product_id로 실제 nvmid 추출
        nvmid = extract_nvmid_from_smart_store_product_id(main_keyword, smart_store_product_id)
        if not nvmid:
            result["error"] = f"키워드 '{main_keyword}'로 검색하여 스마트스토어 product_id '{smart_store_product_id}'의 nvmid를 찾을 수 없습니다."
            logger.error(result["error"])
            return result
        
        result["nvmid"] = nvmid
        logger.info(f"추출된 nvmid: {nvmid} (스마트스토어 product_id: {smart_store_product_id})")
        
        # 메인 키워드로 네이버 쇼핑 API 검색
        logger.info(f"메인 키워드로 검색 시작: '{main_keyword}'")
        api_results = get_shopping_rank_with_ad_flag(main_keyword, display=100, filter=None)
        
        # nvmid 매칭하여 순위와 상품명 찾기
        target_nvmid = str(nvmid).strip()
        
        for item in api_results:
            # 네이버 오픈 API 응답에서 nvmid 추출
            # 방법 1: productId가 nvmid일 수 있음
            product_id = str(item.get("productId", "")).strip()
            
            # 방법 2: link URL에서 nvmid 추출
            link = item.get("link", "")
            nvmid_from_link = None
            
            if link:
                patterns = [
                    r'nv_mid[=_](\d+)',  # nv_mid= 또는 nv_mid_
                    r'nvmid[=_](\d+)',   # nvmid= 또는 nvmid_
                    r'nv-mid[=_](\d+)',  # nv-mid= 또는 nv-mid_
                    r'productId[=_](\d+)', # productId= 또는 productId_
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, link, re.IGNORECASE)
                    if match:
                        nvmid_from_link = match.group(1)
                        break
            
            # nvmid 매칭 (productId 또는 link에서 추출한 값과 비교)
            if (product_id and product_id == target_nvmid) or \
               (nvmid_from_link and nvmid_from_link == target_nvmid):
                rank = item.get("rank")
                product_name = item.get("product_name", "")
                
                result["success"] = True
                result["rank"] = rank
                result["product_name"] = product_name
                
                logger.info(
                    f"nvmid 매칭 성공: productId={product_id}, "
                    f"link_nvmid={nvmid_from_link}, target={target_nvmid}, "
                    f"rank={rank}, product_name={product_name}"
                )
                return result
        
        # 매칭 실패
        result["error"] = f"검색 결과에서 nvmid '{target_nvmid}'를 찾을 수 없습니다."
        logger.warning(result["error"])
        return result
        
    except Exception as e:
        result["error"] = f"상품 정보 조회 중 오류: {str(e)}"
        logger.error(result["error"], exc_info=True)
        return result


# ============================================================================
# Function A: API로 키워드의 순위를 조회
# ============================================================================

def get_api_rank_by_keyword(keyword: str, nvmid: str, max_rank: int = 1000) -> Optional[int]:
    """
    Function A: 네이버 오픈 API로 키워드의 순위 조회 (최대 1000등까지)
    
    Args:
        keyword: 검색 키워드
        nvmid: 찾을 상품의 nvmid
        max_rank: 최대 조회할 순위 (기본값: 1000)
    
    Returns:
        int or None: 순위 (없으면 None)
    """
    if not NAVER_ACCOUNTS or not any(acc[0] and acc[1] for acc in NAVER_ACCOUNTS):
        raise ValueError("유효한 NAVER 계정이 필요합니다.")
    
    try:
        # 최대 1000등까지 조회 (100개씩 10페이지)
        max_pages = min((max_rank + 99) // 100, 10)  # 최대 10페이지
        target_nvmid = str(nvmid).strip()
        
        logger.info(f"키워드 '{keyword}'로 nvmid '{target_nvmid}' 검색 시작 (최대 {max_pages}페이지, {max_rank}등까지)")
        
        for page in range(1, max_pages + 1):
            start = (page - 1) * 100 + 1  # 1, 101, 201, 301, ...
            
            try:
                # 네이버 오픈 API로 검색
                api_results = get_shopping_rank_with_ad_flag(keyword, display=100, start=start, filter=None)
                
                if not api_results:
                    logger.debug(f"페이지 {page}: 결과 없음, 검색 중단")
                    break
                
                logger.debug(f"페이지 {page} 검색 완료: {len(api_results)}개 결과 (start={start})")
                
                # 각 결과에서 nvmid 매칭 시도
                for item in api_results:
                    # 방법 1: productId가 nvmid일 수 있음
                    product_id = str(item.get("productId", "")).strip()
                    
                    # 방법 2: link URL에서 nvmid 추출
                    link = item.get("link", "")
                    nvmid_from_link = None
                    
                    if link:
                        patterns = [
                            r'nv_mid[=_](\d+)',  # nv_mid= 또는 nv_mid_
                            r'nvmid[=_](\d+)',   # nvmid= 또는 nvmid_
                            r'nv-mid[=_](\d+)',  # nv-mid= 또는 nv-mid_
                            r'productId[=_](\d+)', # productId= 또는 productId_
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, link, re.IGNORECASE)
                            if match:
                                nvmid_from_link = match.group(1)
                                break
                    
                    # nvmid 매칭 (productId 또는 link에서 추출한 값과 비교)
                    if (product_id and product_id == target_nvmid) or \
                       (nvmid_from_link and nvmid_from_link == target_nvmid):
                        rank = item.get("rank")
                        logger.info(f"✓ nvmid 매칭 성공: keyword='{keyword}', rank={rank}")
                        return rank
                
                # 마지막 결과의 rank가 max_rank를 초과하면 중단
                if api_results and api_results[-1].get("rank", 0) >= max_rank:
                    logger.debug(f"페이지 {page}: 최대 순위 {max_rank} 도달, 검색 중단")
                    break
                    
            except Exception as e:
                logger.warning(f"페이지 {page} 검색 중 오류 (계속 진행): {e}")
                continue
        
        logger.debug(f"API 순위 조회 실패: keyword='{keyword}', nvmid='{target_nvmid}' (검색 결과 없음)")
        return None
        
    except Exception as e:
        logger.error(f"API 순위 조회 중 오류: keyword='{keyword}', error={e}", exc_info=True)
        return None


# ============================================================================
# Function B: 통검에서 nvmid와 키워드로 광고 여부 및 통검 노출 여부 조회
# ============================================================================

def check_shopping_exposure_and_ad(keyword: str, nvmid: str, driver: webdriver.Chrome) -> Dict:
    """
    Function B: 통합검색에서 nvmid와 키워드로 광고 여부 및 통검 노출 여부 조회
    (test_web_sele_dbsection.py의 로직 참고)
    
    Args:
        keyword: 검색 키워드
        nvmid: 찾을 상품의 nvmid
        driver: Selenium WebDriver 인스턴스
    
    Returns:
        dict: {
            "is_shopping_exposed": bool,  # 통검 쇼핑 노출 여부
            "cpc": bool,  # 광고 여부 (CPC)
        }
    """
    return check_shopping_rank_for_keyword(keyword, nvmid, driver)


# ============================================================================
# 브라우저 풀 클래스
# ============================================================================

class BrowserPool:
    """브라우저 풀 - 브라우저 재사용으로 성능 향상"""
    
    def __init__(self, pool_size: int, headless: bool = True):
        """
        Args:
            pool_size: 풀에 생성할 브라우저 개수
            headless: headless 모드 여부
        """
        self.pool_size = pool_size
        self.headless = headless
        self.pool = Queue(maxsize=pool_size)
        self.lock = threading.Lock()
        self._initialized = False
    
    def _create_browser(self) -> webdriver.Chrome:
        """새 브라우저 인스턴스 생성"""
        options = Options()
        if self.headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-images')  # 이미지 로딩 비활성화로 속도 향상
        options.add_argument('--disable-plugins')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=options)
            
        # 모바일 모드 설정
        try:
            mobile_user_agent = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                'userAgent': mobile_user_agent,
                'acceptLanguage': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'platform': 'Linux armv8l'
            })
            driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                'width': 375,
                'height': 667,
                'deviceScaleFactor': 2.0,
                'mobile': True,
                'screenOrientation': {'angle': 0, 'type': 'portraitPrimary'}
            })
            driver.execute_cdp_cmd('Emulation.setTouchEmulationEnabled', {
                'enabled': True,
                'maxTouchPoints': 5
            })
        except Exception as e:
            logger.warning(f"모바일 모드 설정 중 오류 (계속 진행): {e}")
        
        return driver
    
    def initialize(self):
        """풀 초기화 - 브라우저 미리 생성"""
        if self._initialized:
            return
        
        with self.lock:
            if self._initialized:
                return
            
            logger.info(f"브라우저 풀 초기화 중... ({self.pool_size}개 브라우저 생성)")
            for _ in range(self.pool_size):
                try:
                    driver = self._create_browser()
                    self.pool.put(driver)
                except Exception as e:
                    logger.error(f"브라우저 생성 실패: {e}")
            
                self._initialized = True
                logger.info(f"브라우저 풀 초기화 완료 ({self.pool.qsize()}개 브라우저 준비됨)")
    
    @contextmanager
    def get_browser(self):
        """브라우저 가져오기 (컨텍스트 매니저)"""
        driver = None
        try:
            # 풀이 비어있으면 새로 생성 (동적 확장)
            if self.pool.empty():
                logger.debug("브라우저 풀이 비어있어 새 브라우저 생성")
                driver = self._create_browser()
            else:
                driver = self.pool.get(timeout=30)  # 최대 30초 대기
            
            yield driver
            
        except Exception as e:
            # 오류 발생 시 브라우저 재생성
            logger.warning(f"브라우저 사용 중 오류: {e}, 브라우저 재생성")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            driver = self._create_browser()
            yield driver
        finally:
            # 브라우저 반환 (정상 종료 또는 오류 후)
            if driver:
                try:
                    # 브라우저 상태 확인
                    try:
                        # 브라우저가 살아있는지 확인
                        driver.current_url
                        driver.get("about:blank")  # 빈 페이지로 이동하여 상태 초기화
                    except Exception as e:
                        # 브라우저가 죽었으면 종료 시도 후 무시
                        logger.debug(f"브라우저 상태 확인 실패 (종료 처리): {e}")
                        try:
                            driver.quit()
                        except:
                            pass
                        return  # 브라우저가 죽었으면 반환하지 않음
                    
                    if self.pool.qsize() < self.pool_size:
                        self.pool.put(driver)
                    else:
                        # 풀이 가득 차면 브라우저 종료
                        driver.quit()
                except Exception as e:
                    # 브라우저가 죽었으면 종료 시도 후 무시
                    logger.debug(f"브라우저 상태 확인 실패 (종료 처리): {e}")
                    try:
                        driver.quit()
                    except:
                        pass
                except Exception as e:
                    # 최종 안전장치: 모든 예외 무시
                    logger.debug(f"브라우저 반환 중 최종 오류 (무시): {e}")
                try:
                    driver.quit()
                except:
                    pass
    
    def close_all(self):
        """모든 브라우저 종료"""
        logger.info("브라우저 풀 종료 중...")
        closed_count = 0
        error_count = 0
        
        while not self.pool.empty():
            try:
                driver = self.pool.get_nowait()
                try:
                    # 브라우저가 살아있는지 확인
                    driver.current_url
                    driver.quit()
                    closed_count += 1
                except Exception as e:
                    # 이미 종료된 브라우저는 무시
                    logger.debug(f"브라우저가 이미 종료됨: {e}")
                    error_count += 1
                    try:
                        driver.quit()  # 한 번 더 시도
                    except:
                        pass
            except Exception as e:
                logger.debug(f"브라우저 풀에서 가져오기 실패: {e}")
                error_count += 1
        
        self._initialized = False
        logger.info(f"브라우저 풀 종료 완료 (종료: {closed_count}개, 오류: {error_count}개)")


# ============================================================================
# Function: 선택한 키워드들의 통검 노출 및 CPC 조회 (여러 브라우저 병렬 처리)
# ============================================================================

def check_exposure_and_cpc_for_keywords(
    keywords: List[str],
    nvmid: str,
    headless: bool = True,  # 기본값 True로 변경
    max_workers: int = 20  # 기본값 증가
) -> List[Dict]:
    """
    선택한 키워드들에 대해 통검 노출 여부와 CPC를 여러 브라우저로 병렬 조회 (브라우저 풀 사용)
    
    Args:
        keywords: 조회할 키워드 리스트
        nvmid: 찾을 상품의 nvmid
        headless: Selenium headless 모드
        max_workers: 동시 실행할 브라우저 개수 (기본값: 20)
    
    Returns:
        list: 각 키워드의 통검 노출 여부와 CPC 결과
    """
    results = []
    
    # 브라우저 풀 생성 및 초기화
    browser_pool = BrowserPool(pool_size=max_workers, headless=headless)
    browser_pool.initialize()
    
    def check_single_keyword(keyword: str) -> Dict:
        """단일 키워드 조회 (브라우저 풀 사용)"""
        result = {
            "keyword": keyword,
            "is_shopping_exposed": False,
            "cpc": False,
            "error": None
        }
        
        try:
            # 브라우저 풀에서 브라우저 가져오기
            with browser_pool.get_browser() as driver:
                # 통검 노출 및 CPC 조회
                exposure_result = check_shopping_rank_for_keyword(keyword, nvmid, driver)
                result["is_shopping_exposed"] = exposure_result.get("is_shopping_exposed", False)
                result["cpc"] = exposure_result.get("cpc", False)
                
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"키워드 '{keyword}' 조회 중 오류: {e}", exc_info=True)
        
        return result
    
    # ThreadPoolExecutor로 여러 브라우저 병렬 실행
    logger.info(f"총 {len(keywords)}개 키워드에 대해 {max_workers}개 브라우저 풀로 병렬 조회 시작")
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_keyword = {
                executor.submit(check_single_keyword, keyword): keyword 
                for keyword in keywords
            }
    finally:
        # 브라우저 풀 종료
        browser_pool.close_all()
    
    # 키워드 순서대로 정렬
    keyword_order = {kw: idx for idx, kw in enumerate(keywords)}
    results.sort(key=lambda x: keyword_order.get(x["keyword"], 999))
    
    return results


def main(keyword: str, nvmid: str, product_id: int = None, main_keyword: str = None, headless: bool = False, rank_filter: Optional[int] = None):
    """
    메인 함수: 키워드 조합 생성 후 순위만 API로 조회
    (통검 노출/CPC는 별도 함수로 분리)
    
    Args:
        keyword: 검색할 키워드 (띄어쓰기로 구분)
        nvmid: 찾을 상품의 nvmid
        product_id: 상품 ID (테이블 저장용, Optional)
        main_keyword: 메인 키워드 (테이블 저장용, Optional)
        headless: 사용 안함 (순위만 조회하므로 브라우저 불필요)
        rank_filter: 사용 안함 (순위만 조회)
    """
    # 계정 확인
    if not NAVER_ACCOUNTS or not any(acc[0] and acc[1] for acc in NAVER_ACCOUNTS):
        error_msg = "유효한 NAVER 계정이 필요합니다. _NAVER_ACCOUNTS 리스트에 계정을 추가하세요."
        raise ValueError(error_msg)
    
    # keyword_search_v3.py의 조합 로직 사용
    words = split_keywords_by_space(keyword)
    if len(words) < 2:
        logger.warning(f"키워드가 2개 미만입니다: {words}")
        return []
    
    keyword_combinations = generate_keyword_combinations(words, min_length=2, max_length=len(words))
    
    if not keyword_combinations:
        logger.warning("생성된 조합이 없습니다.")
        return []
    
    logger.info(f"총 {len(keyword_combinations)}개 조합으로 순위 조회 시작 (API만 사용)")
    
    results = []
    
    try:
        # 각 조합 키워드로 네이버 오픈 API 검색 (최대 1000등까지)
        for idx, combo_keyword in enumerate(keyword_combinations, 1):
            logger.info(f"[{idx}/{len(keyword_combinations)}] 키워드 순위 조회: '{combo_keyword}'")
            
            try:
                # Function A: 네이버 오픈 API로 순위 조회 (최대 1000등까지)
                rank = get_api_rank_by_keyword(combo_keyword, nvmid, max_rank=1000)
                
                result = {
                    "keyword": combo_keyword,
                    "rank": rank,  # API에서 직접 조회한 결과 (최대 1000등까지)
                    "is_shopping_exposed": None,  # 통검 노출은 별도 함수로 조회 (None = 미조회)
                    "cpc": None  # CPC는 별도 함수로 조회 (None = 미조회)
                }
                
                results.append(result)
                
                if rank:
                    logger.info(f"✓ 키워드 '{combo_keyword}': 순위 {rank} (API)")
                else:
                    logger.info(f"✗ 키워드 '{combo_keyword}': API에서 순위 없음")
                
                # API 호출 간격 (너무 빠르면 제한될 수 있음)
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"키워드 '{combo_keyword}' 검색 중 오류: {e}", exc_info=True)
                results.append({
                    "keyword": combo_keyword,
                    "rank": None,
                    "is_shopping_exposed": None,
                    "cpc": None
                })
        
        # 결과를 테이블에 저장 (product_id와 main_keyword가 제공된 경우)
        if product_id and main_keyword:
            try:
                # DB 관련 import
                sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from db_code.database import SessionLocal
                from db_code.models import KeywordSearch
                
                db = SessionLocal()
                try:
                    for result in results:
                        # KeywordSearch 테이블에 저장
                        keyword_search = KeywordSearch(
                            product_id=product_id,
                            main_keyword=main_keyword,
                            nvmid=nvmid,
                            base_search_keyword=result["keyword"]
                        )
                        db.add(keyword_search)
                    
                    db.commit()
                    logger.info(f"✓ {len(results)}개 결과를 KeywordSearch 테이블에 저장 완료")
                except Exception as e:
                    db.rollback()
                    logger.error(f"테이블 저장 중 오류: {e}", exc_info=True)
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"DB 연결 중 오류: {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"순위 조회 중 오류: {e}", exc_info=True)
    
    return results


# ============================================================================
# GUI 애플리케이션 (제거됨 - FastAPI로 대체)
# ============================================================================



