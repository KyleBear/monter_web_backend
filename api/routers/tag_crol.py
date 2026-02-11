"""
reward_rank 테이블 크롤링 프로그램 (검색 기반 접속)
nvmid와 메인키워드를 사용하여 검색 후 상품 페이지에 접속하여 크롤링
"""
import logging
import time
import sys
import os
import random
import tempfile
import shutil
import requests
import re
import html
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs, quote_plus
from typing import Optional, Dict
from bs4 import BeautifulSoup
from lxml import etree

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# DB 관련
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_code.database import SessionLocal
from db_code.models import Product, ProxyIP
from models import RandomAcq  # random_acq 테이블 모델
from sqlalchemy import Column, BigInteger, String, DateTime, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# reward_target 테이블 모델
class RewardTarget(Base):
    __tablename__ = 'reward_target'
    
    reward_target_id = Column(String(100), primary_key=True)
    keyword = Column(String(255), nullable=True)
    product_url = Column(String(1000), nullable=True)

# reward_rank 테이블 모델
class RewardRank(Base):
    __tablename__ = 'reward_rank'
    
    reward_id = Column(BigInteger, primary_key=True, autoincrement=True)
    store_name = Column(String(255), nullable=True)
    product_name = Column(String(255), nullable=True)
    productid = Column(String(100), nullable=True)
    nvmid = Column(String(50), nullable=True)  # nvmid 추가 (DB에 컬럼 없음 - 임시 주석)
    keyword = Column(String(255), nullable=True)  # 검색에 사용한 키워드
    # main_keyword = Column(String(255), nullable=True)  # 메인키워드 추가 (DB에 컬럼 없음 - 임시 주석)
    search_url = Column(String(1000), nullable=True)
    product_url = Column(String(1000), nullable=True)
    image_url = Column(String(500), nullable=True)
    image_tag = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 사용한 프록시 추적 (프로세스 전체에서 공유)
USED_PROXIES = set()

# ========== Open API 설정 ==========
# 만료일 설정
EXPIRATION_DATE = date(2026, 10, 1)  # 2026년 10월 1일까지 사용 가능

# NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 하드코딩
_NAVER_CLIENT_ID = "OUkrglPR4aNXUFG1uczo"
_NAVER_CLIENT_SECRET = "bEFr5g3MWR"

def check_and_set_expiration():
    """만료일 확인 후 만료되었으면 client_id와 secret을 빈칸으로 설정"""
    today = date.today()
    if today > EXPIRATION_DATE:
        return "", ""
    else:
        return _NAVER_CLIENT_ID, _NAVER_CLIENT_SECRET

# 만료일 확인 후 client_id와 secret 설정
NAVER_CLIENT_ID, NAVER_CLIENT_SECRET = check_and_set_expiration()

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 네이버 모바일 첫 페이지 URL 리스트 (자연스러운 접근 패턴)
NAVER_FIRST_PAGES = [
    "https://m.comic.naver.com",
    "https://news.naver.com",
    "https://news.naver.com/section/101",
    "https://news.naver.com/section/102",
    "https://m.sports.naver.com",
    "https://m.stock.naver.com",
    "https://m.cafe.naver.com",
]

# 모바일 프리셋 정의
MOBILE_PRESETS = [
    {'width': 375, 'height': 667, 'dpr': 2.0, 'name': 'iPhone SE'},
    {'width': 390, 'height': 844, 'dpr': 3.0, 'name': 'iPhone 12/13'},
    {'width': 393, 'height': 852, 'dpr': 3.0, 'name': 'iPhone 14 Pro'},
    {'width': 360, 'height': 760, 'dpr': 3.0, 'name': 'Samsung Galaxy S10'},
    {'width': 360, 'height': 800, 'dpr': 3.0, 'name': 'Samsung Galaxy S21'},
    {'width': 360, 'height': 800, 'dpr': 2.0, 'name': 'Samsung Galaxy A51'},
    {'width': 393, 'height': 851, 'dpr': 2.75, 'name': 'Pixel 5'},
    {'width': 412, 'height': 915, 'dpr': 3.5, 'name': 'Samsung Galaxy S21 Ultra'},
]


def extract_nvmid_from_product_url(product_url: str) -> Optional[Dict]:
    """
    product_url에서 URL 타입에 따라 product_id 또는 nvmid 추출
    
    Args:
        product_url: 상품 URL
            - 스마트스토어: https://smartstore.naver.com/loneque/products/6516355636
            - 쇼핑: https://search.shopping.naver.com/catalog/10639139232
    
    Returns:
        dict: {
            'url_type': 'smartstore' or 'shopping',
            'product_id': str (smartstore인 경우),
            'nvmid': str (shopping인 경우)
        } 또는 None
    """
    try:
        url_lower = product_url.lower()
        
        if "smartstore.naver.com" in url_lower or "brand.naver.com" in url_lower:
            # 스마트스토어 URL에서 product_id 추출
            pattern = r'(?:smartstore|brand)\.naver\.com/[^/]+/products/(\d+)'
            match = re.search(pattern, product_url)
            if match:
                return {
                    'url_type': 'smartstore',
                    'product_id': match.group(1),
                    'nvmid': None
                }
        elif "search.shopping.naver.com/catalog" in url_lower:
            # 쇼핑 URL에서 nvmid 추출
            pattern = r'search\.shopping\.naver\.com/catalog/(\d+)'
            match = re.search(pattern, product_url)
            if match:
                return {
                    'url_type': 'shopping',
                    'product_id': None,
                    'nvmid': match.group(1)
                }
        
        logger.error(f"[URL 추출] 지원하지 않는 URL 형식: {product_url}")
        return None
    except Exception as e:
        logger.error(f"[URL 추출] 오류: {e}")
        return None


def get_shopping_rank_with_ad_flag(
    keyword: str,
    display: int = 100,
    start: int = 1,
    sort: str = "sim",
    filter: Optional[str] = None,
    exclude: Optional[str] = None
) -> list:
    """
    네이버 오픈 API를 사용하여 쇼핑 검색 결과 조회
    crol_test2.py의 함수 사용
    
    Args:
        keyword: 검색어
        display: 한 번에 표시할 검색 결과 개수 (기본값: 100, 최댓값: 100)
        start: 검색 시작 위치 (기본값: 1, 최댓값: 1000)
        sort: 정렬 방법
        filter: 검색 결과에 포함할 상품 유형
        exclude: 검색 결과에서 제외할 상품 유형
    
    Returns:
        list: 검색 결과 리스트
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경 변수가 필요합니다.")
    
    if display < 1 or display > 100:
        raise ValueError("display 값은 1~100 사이여야 합니다.")
    
    if start < 1 or start > 1000:
        raise ValueError("start 값은 1~1000 사이여야 합니다.")
    
    valid_sorts = ["sim", "date", "asc", "dsc"]
    if sort not in valid_sorts:
        raise ValueError(f"sort 값은 {valid_sorts} 중 하나여야 합니다.")
    
    if filter is not None and filter not in ["naverpay"]:
        logger.warning(f"filter 값 '{filter}'는 유효하지 않습니다. 'naverpay'만 지원됩니다.")
        filter = None
    
    if exclude is not None:
        valid_exclude_options = ["used", "rental", "cbshop"]
        exclude_parts = exclude.split(":")
        for part in exclude_parts:
            if part not in valid_exclude_options:
                logger.warning(f"exclude 값 '{part}'는 유효하지 않습니다. {valid_exclude_options}만 지원됩니다.")
                exclude = None
                break
    
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    
    params = {
        "query": keyword,
        "display": display,
        "start": start,
        "sort": sort
    }
    
    if filter:
        params["filter"] = filter
    
    if exclude:
        params["exclude"] = exclude
    
    try:
        response = requests.get(API_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        items = data.get("items", [])
        total = data.get("total", 0)
        
        logger.info(f"네이버 오픈 API 응답: 총 {total}개 결과, {len(items)}개 반환")
        
        results = []
        for rank, item in enumerate(items, start=1):
            result = {
                "keyword": keyword,
                "rank": rank + start - 1,
                "product_name": item.get("title", ""),
                "mall_name": item.get("mallName", ""),
                "price": item.get("lprice", ""),
                "hprice": item.get("hprice", ""),
                "productId": item.get("productId", ""),
                "link": item.get("link", ""),
                "image": item.get("image", ""),
                "productType": item.get("productType", ""),
                "brand": item.get("brand", ""),
                "maker": item.get("maker", ""),
                "category1": item.get("category1", ""),
                "category2": item.get("category2", ""),
                "category3": item.get("category3", ""),
                "category4": item.get("category4", ""),
                "is_shopping_exposed": True,
            }
            results.append(result)
        
        return results
        
    except requests.exceptions.RequestException as e:
        logger.error(f"네이버 오픈 API 요청 실패: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"네이버 오픈 API 호출 중 예상치 못한 오류: {e}", exc_info=True)
        raise


def get_rank_by_keyword_and_url(keyword: str, url: str) -> Dict:
    """
    키워드와 URL을 받아서 자동으로 타입을 확인하고 nvmid를 조회합니다.
    crol_test2.py의 로직 사용
    
    Args:
        keyword: 검색 키워드
        url: 스마트스토어 URL 또는 쇼핑 URL
    
    Returns:
        dict: {
            "success": bool,
            "url_type": str,
            "product_id": str or None,
            "nvmid": str or None,
            "rank": int or None,
            "product_name": str or None,
            "error": str or None
        }
    """
    result = {
        "success": False,
        "url_type": None,
        "product_id": None,
        "nvmid": None,
        "rank": None,
        "product_name": None,
        "image_url": None,
        "store_name": None,
        "error": None
    }
    
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        result["error"] = "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경 변수가 필요합니다."
        return result
    
    try:
        # 1. URL 타입 확인
        url_lower = url.lower()
        if "smartstore.naver.com" in url_lower or "brand.naver.com" in url_lower:
            url_type = "smartstore"
            pattern = r'(?:smartstore|brand)\.naver\.com/[^/]+/products/(\d+)'
            match = re.search(pattern, url)
            if not match:
                result["error"] = f"스마트스토어/브랜드 스토어 URL에서 product_id를 추출할 수 없습니다: {url}"
                return result
            product_id = match.group(1)
            result["product_id"] = product_id
            result["url_type"] = url_type
            
        elif "search.shopping.naver.com/catalog" in url_lower:
            url_type = "shopping"
            pattern = r'search\.shopping\.naver\.com/catalog/(\d+)'
            match = re.search(pattern, url)
            if not match:
                result["error"] = f"쇼핑 URL에서 nvmid를 추출할 수 없습니다: {url}"
                return result
            nvmid = match.group(1)
            result["nvmid"] = nvmid
            result["url_type"] = url_type
        else:
            result["error"] = f"지원하지 않는 URL 형식입니다: {url}"
            return result
        
        # 2. 여러 페이지 검색 (최대 1000개 결과)
        display = 100
        max_pages = 10
        logger.info(f"키워드 '{keyword}'로 nvmid 조회 시작 (최대 {max_pages}페이지)")
        
        for page in range(1, max_pages + 1):
            start = (page - 1) * 100 + 1
            
            try:
                api_results = get_shopping_rank_with_ad_flag(
                    keyword, 
                    display=display, 
                    start=start, 
                    filter=None
                )
                
                if not api_results:
                    break
                
                # 3. URL 타입에 따라 매칭 방식 결정
                if url_type == "smartstore":
                    target_id = product_id
                    for item in api_results:
                        product_id_from_api = str(item.get("productId", "")).strip()
                        link = item.get("link", "")
                        product_id_from_link = None
                        
                        if link:
                            link_patterns = [r'/products/(\d+)']
                            for pattern in link_patterns:
                                match = re.search(pattern, link, re.IGNORECASE)
                                if match:
                                    product_id_from_link = match.group(1)
                                    break
                        
                        if (product_id_from_api and product_id_from_api == target_id) or \
                           (product_id_from_link and product_id_from_link == target_id):
                            result["success"] = True
                            result["rank"] = item.get("rank")
                            result["product_name"] = item.get("product_name", "")
                            result["image_url"] = item.get("image", "")  # 이미지 URL 추가
                            result["store_name"] = item.get("mall_name", "")  # 스토어명 추가
                            
                            # nvmid 추출 (crol_test2.py 로직)
                            nvmid_from_link = None
                            if link:
                                patterns = [
                                    r'nv_mid[=_](\d+)',
                                    r'nvmid[=_](\d+)',
                                    r'nv-mid[=_](\d+)',
                                    r'/catalog/(\d+)',
                                    r'catalog/(\d+)',
                                ]
                                for pattern in patterns:
                                    match = re.search(pattern, link, re.IGNORECASE)
                                    if match:
                                        nvmid_from_link = match.group(1)
                                        break
                            
                            # nvmid 설정: link에서 추출한 값이 있으면 사용, 없으면 api_productId 사용
                            nvmid = nvmid_from_link if nvmid_from_link else product_id_from_api
                            result["nvmid"] = nvmid
                            logger.info(f"product_id 매칭 성공: api_productId={product_id_from_api} (nvmid), link_productId={product_id_from_link} (product_id), target={target_id}, rank={result['rank']}, nvmid={nvmid} (페이지 {page})")
                            return result
                
                elif url_type == "shopping":
                    target_nvmid = nvmid
                    for item in api_results:
                        product_id = str(item.get("productId", "")).strip()
                        link = item.get("link", "")
                        nvmid_from_link = None
                        
                        if link:
                            patterns = [
                                r'nv_mid[=_](\d+)',
                                r'nvmid[=_](\d+)',
                                r'nv-mid[=_](\d+)',
                                r'/catalog/(\d+)',
                                r'catalog/(\d+)',
                            ]
                            for pattern in patterns:
                                match = re.search(pattern, link, re.IGNORECASE)
                                if match:
                                    nvmid_from_link = match.group(1)
                                    break
                        
                        if (product_id and product_id == target_nvmid) or \
                           (nvmid_from_link and nvmid_from_link == target_nvmid):
                            result["success"] = True
                            result["rank"] = item.get("rank")
                            result["product_name"] = item.get("product_name", "")
                            result["image_url"] = item.get("image", "")  # 이미지 URL 추가
                            result["store_name"] = item.get("mall_name", "")  # 스토어명 추가
                            result["nvmid"] = nvmid
                            logger.info(f"nvmid 매칭 성공: productId={product_id}, link_nvmid={nvmid_from_link}, target={target_nvmid}, rank={result['rank']} (페이지 {page})")
                            return result
                
                if len(api_results) < display:
                    break
                
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"페이지 {page} 검색 중 오류: {e}", exc_info=True)
                break
        
        result["error"] = f"검색 결과에서 매칭되는 상품을 찾을 수 없습니다."
        return result
        
    except Exception as e:
        result["error"] = f"nvmid 조회 중 오류: {str(e)}"
        logger.error(result["error"], exc_info=True)
        return result


def get_product_info_by_api(product_url: str) -> Optional[Dict]:
    """
    Open API를 사용하여 product_url에서 상품 정보 가져오기
    
    Args:
        product_url: 상품 URL
    
    Returns:
        dict: {'image_url': str, 'store_name': str, 'product_name': str, 'nvmid': str} 또는 None
    """
    try:
        # URL 타입과 ID 추출
        url_info = extract_nvmid_from_product_url(product_url)
        if not url_info:
            logger.error(f"[API] product_url에서 ID 추출 실패: {product_url}")
            return None
        
        url_type = url_info['url_type']
        product_id = url_info.get('product_id')
        nvmid = url_info.get('nvmid')
        
        target_id = product_id if url_type == 'smartstore' else nvmid
        
        logger.info(f"[API] {url_type} URL로 상품 정보 조회: target_id={target_id}")
        
        # Open API로는 nvmid/product_id로 직접 조회가 불가능하므로,
        # 상품명을 알아야 검색 가능
        # 이 함수는 사용하지 않는 것으로 보이므로 경고만 출력
        logger.warning("[API] Open API로 nvmid/product_id 직접 조회는 불가능합니다. 상품명이 필요합니다.")
        return None
        
    except Exception as e:
        logger.error(f"[API] 상품 정보 가져오기 오류: {e}", exc_info=True)
        return None


def get_product_info_by_keyword_search(product_name: str, target_id: str, url_type: str = 'smartstore') -> Optional[Dict]:
    """
    상품명으로 검색하여 target_id(product_id 또는 nvmid)와 일치하는 상품 정보 가져오기
    
    Args:
        product_name: 상품명 (검색 키워드)
        target_id: 찾을 product_id 또는 nvmid
        url_type: 'smartstore' 또는 'shopping'
    
    Returns:
        dict: {'image_url': str, 'store_name': str, 'product_name': str, 'nvmid': str} 또는 None
    """
    try:
        if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
            logger.error("[API] NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 없습니다.")
            return None
        
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }
        
        # 여러 페이지 검색 (최대 1000개 결과)
        display = 100
        max_pages = 10
        
        for page in range(1, max_pages + 1):
            start = (page - 1) * 100 + 1
            
            params = {
                "query": product_name,
                "display": display,
                "start": start,
                "sort": "sim"
            }
            
            response = requests.get(API_URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            items = data.get("items", [])
            
            if not items:
                break
            
            logger.debug(f"[API] 페이지 {page} 검색 완료: {len(items)}개 결과 (start={start})")
            
            # items에서 target_id와 일치하는 상품 찾기
            for item in items:
                # 방법 1: productId 확인
                product_id = str(item.get("productId", "")).strip()
                
                # 방법 2: link URL에서 nvmid/product_id 추출
                link = item.get("link", "")
                nvmid_from_link = None
                product_id_from_link = None
                
                if link:
                    # nvmid 추출 패턴
                    nvmid_patterns = [
                        r'nv_mid[=_](\d+)',
                        r'nvmid[=_](\d+)',
                        r'nv-mid[=_](\d+)',
                        r'/catalog/(\d+)',
                        r'catalog/(\d+)',
                    ]
                    
                    # product_id 추출 패턴
                    product_id_patterns = [
                        r'/products/(\d+)',
                    ]
                    
                    for pattern in nvmid_patterns:
                        match = re.search(pattern, link, re.IGNORECASE)
                        if match:
                            nvmid_from_link = match.group(1)
                            break
                    
                    for pattern in product_id_patterns:
                        match = re.search(pattern, link, re.IGNORECASE)
                        if match:
                            product_id_from_link = match.group(1)
                            break
                
                # URL 타입에 따라 매칭 방식 결정
                if url_type == 'smartstore':
                    # product_id 다이렉트 매칭
                    if (product_id and product_id == target_id) or \
                       (product_id_from_link and product_id_from_link == target_id):
                        # nvmid 추출 (crol_test2.py 로직: link에서 추출한 값이 있으면 사용, 없으면 api_productId 사용)
                        nvmid = nvmid_from_link if nvmid_from_link else product_id
                        logger.info(f"[API] product_id 매칭 성공: api_productId={product_id} (nvmid), link_productId={product_id_from_link} (product_id), target={target_id}, nvmid={nvmid} (페이지 {page})")
                        return {
                            'image_url': item.get("image", ""),
                            'store_name': item.get("mallName", ""),
                            'product_name': item.get("title", ""),
                            'nvmid': nvmid
                        }
                elif url_type == 'shopping':
                    # nvmid 링크 매칭
                    if (product_id and product_id == target_id) or \
                       (nvmid_from_link and nvmid_from_link == target_id):
                        # nvmid는 URL에서 추출한 target_id 사용 (crol_test2.py와 동일)
                        logger.info(f"[API] nvmid 매칭 성공: productId={product_id}, link_nvmid={nvmid_from_link}, target={target_id} (페이지 {page})")
                        return {
                            'image_url': item.get("image", ""),
                            'store_name': item.get("mallName", ""),
                            'product_name': item.get("title", ""),
                            'nvmid': target_id
                        }
            
            # 마지막 페이지면 중단
            if len(items) < display:
                logger.debug(f"[API] 페이지 {page}: 마지막 페이지 (결과 {len(items)}개 < {display}개)")
                break
            
            # API 호출 간격
            time.sleep(0.2)
        
        logger.warning(f"[API] 검색 결과에서 target_id {target_id}를 찾지 못했습니다. (최대 {max_pages}페이지 검색)")
        return None
        
    except Exception as e:
        logger.error(f"[API] 상품 정보 검색 오류: {e}", exc_info=True)
        return None


def extract_search_params(search_url: str) -> Dict[str, Optional[str]]:
    """
    search_url에서 ackey, acq, acr, qdt 추출
    
    Args:
        search_url: 검색 URL
    
    Returns:
        dict: {'ackey': str, 'acq': str, 'acr': str, 'qdt': str} 또는 None
    """
    try:
        parsed = urlparse(search_url)
        params = parse_qs(parsed.query)
        
        result = {
            'ackey': params.get('ackey', [None])[0],
            'acq': params.get('acq', [None])[0],
            'acr': params.get('acr', [None])[0],
            'qdt': params.get('qdt', [None])[0]
        }
        
        logger.info(f"[파라미터 추출] ackey={result['ackey']}, acq={result['acq']}, acr={result['acr']}, qdt={result['qdt']}")
        return result
        
    except Exception as e:
        logger.error(f"[파라미터 추출] 오류: {e}", exc_info=True)
        return {'ackey': None, 'acq': None, 'acr': None, 'qdt': None}


def generate_ackey():
    """8자리 랜덤 ackey 생성 (영문+숫자)"""
    import string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def generate_acr():
    """1~10 사이 랜덤 숫자"""
    return random.randint(1, 10)

def generate_acq_from_random_table(db: SessionLocal = None) -> str:
    """
    random_acq 테이블에서 acq_word와 adj_word를 랜덤으로 선택하여 acq 생성
    
    Args:
        db: DB 세션 (없으면 새로 생성)
    
    Returns:
        str: 생성된 acq (acq_word + adj_word 형식)
    """
    try:
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            # random_acq 테이블에서 랜덤으로 acq_word와 adj_word 각각 선택
            acq_words = db.query(RandomAcq.acq_word).filter(
                RandomAcq.acq_word.isnot(None),
                RandomAcq.acq_word != ''
            ).all()
            
            adj_words = db.query(RandomAcq.adj_word).filter(
                RandomAcq.adj_word.isnot(None),
                RandomAcq.adj_word != ''
            ).all()
            
            if not acq_words or not adj_words:
                logger.warning("[acq 생성] random_acq 테이블에 데이터가 없습니다. 기본값 사용.")
                return "상품"  # 기본값
            
            # 랜덤 선택
            selected_acq_word = random.choice([w[0] for w in acq_words])
            selected_adj_word = random.choice([w[0] for w in adj_words])
            
            # acq_word + adj_word 형식으로 조합
            acq = f"{selected_acq_word}{selected_adj_word}"
            
            logger.info(f"[acq 생성] random_acq 테이블에서 생성: '{selected_acq_word}' + '{selected_adj_word}' = '{acq}'")
            return acq
        finally:
            if should_close:
                db.close()
        
    except Exception as e:
        logger.error(f"[acq 생성] 오류: {e}", exc_info=True)
        return "상품"  # 기본값

def create_search_url_with_params(keyword: str, ackey: str = None, acq: str = None, acr: int = None, qdt: int = 0, db: SessionLocal = None) -> str:
    """
    search_url 생성 (ackey, acq, acr, qdt 포함)
    쇼핑 검색 결과를 위한 URL 생성
    
    Args:
        keyword: 검색 키워드 (상품명)
        ackey: ackey (없으면 생성)
        acq: acq (없으면 random_acq 테이블에서 생성)
        acr: acr (없으면 생성)
        qdt: qdt (기본값: 0)
        db: DB 세션 (acq 생성용)
    
    Returns:
        str: 생성된 search_url (쇼핑 검색 결과)
    """
    if not ackey:
        ackey = generate_ackey()
    if acr is None:
        acr = generate_acr()
    if not acq:
        acq = generate_acq_from_random_table(db)
    
    # encoded_query = quote_plus(keyword)
    # encoded_acq = quote_plus(acq)
    encoded_query = keyword
    encoded_acq = acq
    
    # 쇼핑 검색 결과를 위한 URL 생성 (where=shopping 추가)
    url = f"https://m.search.naver.com/search.naver?sm=mtp_sug.top&where=shopping&query={encoded_query}&ackey={ackey}&acq={encoded_acq}&acr={acr}&qdt={qdt}"
    logger.info(f"[URL 생성] 생성된 search_url (쇼핑): {url}")
    return url


def get_random_proxy():
    """
    DB에서 활성화된 프록시를 랜덤으로 선택 (사용한 프록시 제외)
    
    Returns:
        tuple: (proxy_ip, proxy_port) 또는 (None, None)
    """
    global USED_PROXIES
    
    try:
        db = SessionLocal()
        
        # datasection_7의 활성화된 프록시만 조회
        available_proxies = db.query(ProxyIP).filter(
            ProxyIP.is_active == True,
            ProxyIP.datasection_id == 7
        ).all()
        
        db.close()
        
        if not available_proxies:
            logger.warning("[프록시] datasection_7에서 활성화된 프록시가 없습니다.")
            return None, None
        
        # 사용하지 않은 프록시만 필터링
        unused_proxies = []
        for proxy in available_proxies:
            proxy_key = f"{proxy.proxy_ip}:{proxy.proxy_port}"
            if proxy_key not in USED_PROXIES:
                unused_proxies.append(proxy)
        
        # 모든 프록시를 사용한 경우, 사용 기록 초기화
        if not unused_proxies:
            logger.info("[프록시] datasection_7의 모든 프록시를 사용했습니다. 사용 기록을 초기화합니다.")
            USED_PROXIES.clear()
            unused_proxies = available_proxies
        
        # 랜덤 선택
        selected_proxy = random.choice(unused_proxies)
        proxy_key = f"{selected_proxy.proxy_ip}:{selected_proxy.proxy_port}"
        
        # 사용 기록에 추가
        USED_PROXIES.add(proxy_key)
        
        logger.info(f"[프록시] datasection_7에서 선택된 프록시: {proxy_key} (사용된 프록시: {len(USED_PROXIES)}개)")
        
        return selected_proxy.proxy_ip, selected_proxy.proxy_port
        
    except Exception as e:
        logger.error(f"[프록시] 프록시 선택 중 오류: {e}", exc_info=True)
        return None, None


def create_click_result_script(nvmid):
    """
    NV MID로 검색 결과를 찾아 클릭하는 JavaScript 스크립트 생성
    test5.py의 원본 로직을 따름 (test_web_sele_db_copy21.py와 동일)
    """
    click_result_script = f"""
    (function() {{
        try {{
            var targetNvmid = '{nvmid}';
            var targetAriaId = 'view_type_guide_' + targetNvmid;
            var aTagToClick = null;  // 클릭할 a 태그
            var foundNvmid = null;
            var allFoundNvmids = [];  // 디버깅용
            
            // 광고 태그 확인 함수
            function isAdTag(listItem) {{
                // 방법 1: pbjVN80V 클래스를 가진 div가 있는지 확인
                if (listItem.querySelector('.pbjVN80V')) {{
                    return true;
                }}
                // 방법 2: SucLwbaS 클래스를 가진 a 태그가 있는지 확인
                if (listItem.querySelector('a.SucLwbaS')) {{
                    return true;
                }}
                // 방법 3: "광고" 텍스트를 가진 blind 클래스 span이 있는지 확인
                var blindSpans = listItem.querySelectorAll('span.blind');
                for (var i = 0; i < blindSpans.length; i++) {{
                    if (blindSpans[i].textContent.includes('광고')) {{
                        return true;
                    }}
                }}
                return false;
            }}
            
            // 요소가 나타날 때까지 대기 (최대 5초)
            var maxWait = 5000;
            var startTime = Date.now();
            var allLinks = [];
            
            // HTML 구조를 차례대로 타고 들어가면서 찾기
            while (aTagToClick === null && (Date.now() - startTime) < maxWait) {{
                // 1단계: .flicking-viewport 찾기
                var flickingViewport = document.querySelector('.flicking-viewport');
                
                if (flickingViewport) {{
                    // 2단계: flicking-viewport 안에서 li.ds9RptR1 찾기
                    var listItems = flickingViewport.querySelectorAll('li.ds9RptR1');
                    
                    // 3단계: 각 li를 순회하면서 a 태그 찾기 (광고 제외)
                    for (var i = 0; i < listItems.length; i++) {{
                        var listItem = listItems[i];
                        
                        // 광고 태그인지 확인 - 광고면 스킵
                        if (isAdTag(listItem)) {{
                            continue;
                        }}
                        
                        // ⭐ 수정: 각 li 안의 모든 a 태그를 확인
                        var aTags = listItem.querySelectorAll('a[aria-labelledby^="view_type_guide_"]');
                        
                        // 각 a 태그를 순회하면서 타겟 nvmid 찾기
                        for (var j = 0; j < aTags.length; j++) {{
                            var aTag = aTags[j];
                            var ariaId = aTag.getAttribute('aria-labelledby');
                            
                            if (ariaId && ariaId.startsWith('view_type_guide_')) {{
                                var nvmid = ariaId.replace('view_type_guide_', '');
                                allFoundNvmids.push(nvmid);
                                
                                // 타겟 nvmid와 일치하는지 확인
                                if (nvmid === targetNvmid) {{
                                    foundNvmid = nvmid;
                                    aTagToClick = aTag;
                                    break;  // 내부 for 루프 종료
                                }}
                            }}
                        }}
                        
                        // 타겟을 찾았으면 외부 for 루프도 종료
                        if (aTagToClick && foundNvmid) {{
                            break;
                        }}
                    }}
                }}
                
                // 찾지 못했으면 잠시 대기 후 재시도
                if (!aTagToClick) {{
                    var waitUntil = Date.now() + 100;
                    while (Date.now() < waitUntil) {{}}
                }}
            }}
            
            if (aTagToClick && foundNvmid) {{
                aTagToClick.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                setTimeout(() => {{
                    aTagToClick.click();
                }}, 500);
                return {{
                    success: true,
                    nvmid: foundNvmid,
                    allFoundNvmids: allFoundNvmids
                }};
            }} else {{
                return {{
                    success: false,
                    reason: "not_found",
                    nvmid: null,
                    allFoundNvmids: allFoundNvmids
                }};
            }}
        }} catch (error) {{
            return {{
                success: false,
                reason: "script_error",
                error: error.toString(),
                nvmid: null,
                allFoundNvmids: []
            }};
        }}
    }})();
    """
    return click_result_script


def _setup_chrome_driver(headless: bool = False, proxy_ip: str = None, proxy_port: int = None):
    """
    강화된 봇 감지 회피 기능이 적용된 Chrome WebDriver 생성
    
    Args:
        headless: Headless 모드 여부
        proxy_ip: 프록시 IP
        proxy_port: 프록시 포트
    """
    user_data_dir = tempfile.mkdtemp(prefix='chrome_data_reward_')
    logger.info(f"[Chrome 설정] User Data Directory: {user_data_dir}")
    
    options = Options()
    
    # User Data Directory 사용
    options.add_argument(f'--user-data-dir={user_data_dir}')
    
    # 강화된 봇 감지 회피 옵션
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # 추가 보안 우회 옵션
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins-discovery')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-application-cache')
    options.add_argument('--disable-logging')
    options.add_argument('--log-level=3')
    options.add_argument('--disable-gcm')
    
    # 프록시 설정
    if proxy_ip and proxy_port:
        proxy_url = f"http://{proxy_ip}:{proxy_port}"
        options.add_argument(f'--proxy-server={proxy_url}')
        logger.info(f"[프록시] Chrome에 프록시 설정: {proxy_url}")
    else:
        logger.info("[프록시] 프록시 없이 직접 연결")
    
    # 모바일 User-Agent 사용
    android_versions = ['10', '11', '12', '13']
    android_models = [
        'SM-G973F', 'SM-G991B', 'SM-G998B',
        'SM-A515F', 'SM-G975F', 'SM-N986B',
    ]
    android_version = random.choice(android_versions)
    android_model = random.choice(android_models)
    chrome_version = "143.0.0.0"
    mobile_user_agent = f'Mozilla/5.0 (Linux; Android {android_version}; {android_model}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Mobile Safari/537.36'
    options.add_argument(f'user-agent={mobile_user_agent}')
    logger.info(f"[Chrome 설정] 모바일 User-Agent: Android {android_version}, {android_model}")
    
    # 모바일 프리셋 사용
    mobile_preset = random.choice(MOBILE_PRESETS)
    options.add_argument(f'--window-size={mobile_preset["width"]},{mobile_preset["height"]}')
    logger.info(f"[Chrome 설정] 모바일 프리셋: {mobile_preset['name']} ({mobile_preset['width']}x{mobile_preset['height']}, DPR: {mobile_preset['dpr']})")
    
    # Headless 모드
    if headless:
        options.add_argument('--headless=new')
    
    driver = webdriver.Chrome(options=options)
    
    # ========== 쿠키 및 캐시 삭제 (21과 동일) ==========
    try:
        logger.info("[Chrome 설정] 쿠키 및 캐시 삭제 시작...")
        driver.delete_all_cookies()
        driver.execute_cdp_cmd('Network.clearBrowserCookies', {})
        driver.execute_cdp_cmd('Network.clearBrowserCache', {})
        logger.info("[Chrome 설정] ✓ 쿠키 및 캐시 삭제 완료")
    except Exception as e:
        logger.warning(f"[Chrome 설정] 쿠키 및 캐시 삭제 실패: {e}")
    
    # CDP를 통한 모바일 설정
    major_version = chrome_version.split('.')[0]
    platform_version_map = {
        '10': '10.0.0',
        '11': '11.0.0',
        '12': '12.0.0',
        '13': '13.0.0'
    }
    platform_version = platform_version_map.get(android_version, '11.0.0')
    
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        'userAgent': mobile_user_agent,
        'acceptLanguage': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'platform': 'Linux armv8l',
        'userAgentMetadata': {
            'brands': [
                {'brand': 'Chromium', 'version': major_version},
                {'brand': 'Google Chrome', 'version': major_version},
                {'brand': 'Not_A Brand', 'version': '99'}
            ],
            'fullVersionList': [
                {'brand': 'Chromium', 'version': chrome_version},
                {'brand': 'Google Chrome', 'version': chrome_version},
                {'brand': 'Not_A Brand', 'version': '99.0.0.0'}
            ],
            'fullVersion': chrome_version,
            'platform': 'Android',
            'platformVersion': platform_version,
            'architecture': 'arm',
            'model': android_model,
            'mobile': True,
            'bitness': '64'
        }
    })
    
    # 모바일 디바이스 메트릭 설정
    driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
        'width': mobile_preset['width'],
        'height': mobile_preset['height'],
        'deviceScaleFactor': mobile_preset['dpr'],
        'mobile': True,
        'screenOrientation': {'angle': 0, 'type': 'portraitPrimary'}
    })
    
    # 터치 이벤트 활성화
    driver.execute_cdp_cmd('Emulation.setTouchEmulationEnabled', {
        'enabled': True,
        'maxTouchPoints': 5
    })
    
    # 타임존 설정
    driver.execute_cdp_cmd('Emulation.setTimezoneOverride', {
        'timezoneId': 'Asia/Seoul'
    })
    
    # WebRTC 추가 제어
    try:
        driver.execute_cdp_cmd('Network.setWebRTCIPHandlingPolicy', {
            'policy': 'disable_non_proxied_udp'
        })
        logger.info("[Chrome 설정] WebRTC 정책 설정 완료")
    except Exception as e:
        logger.debug(f"[Chrome 설정] WebRTC 정책 설정 실패 (무시): {e}")
    
    # ========== Navigator 객체 속성 동기화 (21과 동일) ==========
    navigator_override_script = f"""
    (function() {{
        Object.defineProperty(navigator, 'userAgent', {{
            get: function() {{ return '{mobile_user_agent}'; }}
        }});
        Object.defineProperty(navigator, 'platform', {{
            get: function() {{ return 'Linux armv8l'; }}
        }});
        Object.defineProperty(navigator, 'maxTouchPoints', {{
            get: function() {{ return 5; }}
        }});
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: function() {{ return 8; }}
        }});
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: function() {{ return 4; }}
        }});
        Object.defineProperty(screen, 'width', {{
            get: function() {{ return {mobile_preset['width']}; }}
        }});
        Object.defineProperty(screen, 'height', {{
            get: function() {{ return {mobile_preset['height']}; }}
        }});
        Object.defineProperty(window, 'innerWidth', {{
            get: function() {{ return {mobile_preset['width']}; }}
        }});
        Object.defineProperty(window, 'innerHeight', {{
            get: function() {{ return {mobile_preset['height']}; }}
        }});
    }})();
    """
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": navigator_override_script
    })
    logger.info("[Chrome 설정] navigator 객체 속성 동기화 완료")
    
    # ========== navigator.webdriver 제거 (봇 감지 회피 핵심) ==========
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ko-KR', 'ko', 'en-US', 'en']
            });
            window.chrome = {
                runtime: {}
            };
            """
        }
    )
    
    # ========== Canvas/WebGL 핑거프린트 노이즈 주입 (21과 동일 - 중요!) ==========
    canvas_webgl_noise_script = """
    (function() {
        // Canvas 핑거프린트 노이즈 주입
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            const context = this.getContext('2d');
            if (context) {
                const imageData = context.getImageData(0, 0, this.width, this.height);
                for (let i = 0; i < imageData.data.length; i += 4) {
                    // 미세한 노이즈 추가 (랜덤화)
                    imageData.data[i] += Math.floor(Math.random() * 3) - 1;
                    imageData.data[i + 1] += Math.floor(Math.random() * 3) - 1;
                    imageData.data[i + 2] += Math.floor(Math.random() * 3) - 1;
                }
                context.putImageData(imageData, 0, 0);
            }
            return originalToDataURL.apply(this, arguments);
        };
        
        // WebGL 핑거프린트 노이즈 주입
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                return 'Google Inc. (Qualcomm)';
            }
            if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                return 'Adreno (TM) 640';
            }
            return getParameter.apply(this, arguments);
        };
        
        // getImageData 노이즈 주입
        const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function(sx, sy, sw, sh) {
            const imageData = originalGetImageData.apply(this, arguments);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] += Math.floor(Math.random() * 3) - 1;
                imageData.data[i + 1] += Math.floor(Math.random() * 3) - 1;
                imageData.data[i + 2] += Math.floor(Math.random() * 3) - 1;
            }
            return imageData;
        };
    })();
    """
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': canvas_webgl_noise_script
    })
    logger.info("[Chrome 설정] Canvas/WebGL 핑거프린트 노이즈 주입 완료")
    
    driver.implicitly_wait(10)
    
    return driver, user_data_dir


def search_keyword(driver, keyword):
    """
    키워드 검색 (JavaScript 기반)
    """
    logger.info(f"[검색] 키워드 검색: {keyword}")
    try:
        search_input_script = f"""
        (function() {{
            var searchInput = document.querySelector('#query') || 
                            document.querySelector('input.sch_input') ||
                            document.querySelector('input[type="search"]');
            if (searchInput) {{
                searchInput.focus();
                searchInput.click();
                searchInput.value = '';
                searchInput.value = '{keyword}';
                searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }})();
        """
        result = driver.execute_script(search_input_script)
        if result:
            logger.info(f"[검색] ✓ 검색어 입력 완료: {keyword}")
        else:
            logger.warning("[검색] ⚠ 검색창을 찾지 못했습니다.")
            time.sleep(2)
        
        search_button_script = """
        (function() {
            var searchButton = document.querySelector('button.sch_btn_search') ||
                            document.querySelector('button.MM_SEARCH_SUBMIT') ||
                            document.querySelector('#sch_w > div > form > button') ||
                            document.querySelector('button[type="submit"]');
            
            if (searchButton) {
                searchButton.click();
                return true;
            }
            
            var searchInput = document.querySelector('#query') || 
                            document.querySelector('input.sch_input');
            if (searchInput) {
                var form = searchInput.closest('form');
                if (form) {
                    form.submit();
                    return true;
                }
            }
            
            return false;
        })();
        """
        
        button_result = driver.execute_script(search_button_script)
        if button_result:
            logger.info("[검색] ✓ 검색 버튼 클릭 완료")
        else:
            enter_key_script = """
            (function() {
                var searchInput = document.querySelector('#query') || 
                                document.querySelector('input.sch_input');
                if (searchInput) {
                    var e = new KeyboardEvent('keydown', {
                        key: 'Enter',
                        code: 'Enter',
                        keyCode: 13,
                        bubbles: true
                    });
                    searchInput.dispatchEvent(e);
                    return true;
                }
                return false;
            })();
            """
            driver.execute_script(enter_key_script)
        
        time.sleep(3)
        
    except Exception as e:
        logger.error(f"[검색] 검색 실패: {e}", exc_info=True)
        raise


def find_nvmid_by_image_url(driver, target_image_url: str) -> str:
    """
    검색 결과에서 이미지 URL로 nvmid 찾기
    
    Args:
        driver: Selenium WebDriver
        target_image_url: 찾을 이미지 URL (일부만 매칭 가능)
    
    Returns:
        str: 찾은 nvmid, 없으면 None
    """
    logger.info(f"[이미지 검색] 이미지 URL로 nvmid 찾기: {target_image_url}")
    
    # 이미지 URL에서 파일명 추출 (예: https://shopping-phinf.pstatic.net/.../image.jpg -> image.jpg)
    import re
    image_filename = None
    if target_image_url:
        # URL에서 마지막 경로 추출
        match = re.search(r'/([^/]+\.(jpg|jpeg|png|gif|webp))', target_image_url, re.IGNORECASE)
        if match:
            image_filename = match.group(1)
        # 또는 URL의 일부만 추출 (도메인 제외)
        if not image_filename:
            # URL에서 마지막 부분 추출
            parts = target_image_url.split('/')
            if len(parts) > 0:
                image_filename = parts[-1].split('?')[0]  # 쿼리 파라미터 제거
    
    find_script = f"""
    (function() {{
        var targetImageUrl = '{target_image_url}';
        var targetImageFilename = '{image_filename or ''}';
        var foundNvmid = null;
        var foundElement = null;
        
        // 검색 결과에서 모든 상품 항목 찾기
        var listItems = document.querySelectorAll('li.ds9RptR1');
        
        for (var i = 0; i < listItems.length; i++) {{
            var listItem = listItems[i];
            
            // 광고 태그 확인
            if (listItem.querySelector('.pbjVN80V') || 
                listItem.querySelector('a.SucLwbaS')) {{
                continue;
            }}
            
            // 이미지 찾기
            var img = listItem.querySelector('img');
            if (img) {{
                var imgSrc = img.getAttribute('src') || img.getAttribute('data-src') || '';
                
                // 전체 URL 매칭 또는 파일명 매칭
                if (imgSrc && (
                    imgSrc.includes(targetImageUrl) || 
                    targetImageUrl.includes(imgSrc) ||
                    (targetImageFilename && imgSrc.includes(targetImageFilename))
                )) {{
                    // 해당 상품의 a 태그 찾기
                    var aTag = listItem.querySelector('a[aria-labelledby^="view_type_guide_"]');
                    if (aTag) {{
                        var ariaId = aTag.getAttribute('aria-labelledby');
                        if (ariaId && ariaId.startsWith('view_type_guide_')) {{
                            foundNvmid = ariaId.replace('view_type_guide_', '');
                            foundElement = aTag;
                            break;
                        }}
                    }}
                }}
            }}
        }}
        
        if (foundNvmid && foundElement) {{
            return {{
                success: true,
                nvmid: foundNvmid,
                imageUrl: foundElement.closest('li').querySelector('img')?.getAttribute('src') || ''
            }};
        }} else {{
            return {{
                success: false,
                reason: 'image_not_found',
                nvmid: null
            }};
        }}
    }})();
    """
    
    try:
        result = driver.execute_script(find_script)
        if result and isinstance(result, dict) and result.get('success'):
            found_nvmid = result.get('nvmid')
            logger.info(f"[이미지 검색] ✓ 이미지 URL로 nvmid 찾기 성공: {found_nvmid}")
            return found_nvmid
        else:
            logger.warning(f"[이미지 검색] 이미지 URL로 nvmid를 찾지 못했습니다: {result.get('reason') if result else 'unknown'}")
            return None
    except Exception as e:
        logger.error(f"[이미지 검색] 이미지 URL 검색 중 오류: {e}", exc_info=True)
        return None


def click_by_nvmid(driver, nvmid):
    """
    nvmid로 상품 클릭
    """
    logger.info(f"[클릭] 상품 클릭: nvmid={nvmid}")
    
    # 현재 URL 확인 및 쇼핑 검색 결과 페이지로 리다이렉트
    current_url = driver.current_url
    logger.info(f"[클릭] 현재 URL: {current_url}")
    
    # URL이 일반 검색 페이지(where=m)인 경우 쇼핑 검색 결과 페이지로 변경
    if 'where=m&' in current_url or (current_url.startswith('https://m.search.naver.com') and 'where=shopping' not in current_url):
        logger.warning("[클릭] ⚠️ 일반 검색 페이지 감지. 쇼핑 검색 결과 페이지로 리다이렉트합니다...")
        
        # URL에서 where=m을 where=shopping으로 변경
        if 'where=m&' in current_url:
            new_url = current_url.replace('where=m&', 'where=shopping&')
        elif 'where=m' in current_url and '&' not in current_url.split('where=m')[1]:
            # URL 끝에 where=m이 있는 경우
            new_url = current_url.replace('where=m', 'where=shopping')
        else:
            # where 파라미터가 없는 경우 추가
            if '?' in current_url:
                new_url = current_url + '&where=shopping'
            else:
                new_url = current_url + '?where=shopping'
        
        logger.info(f"[클릭] 쇼핑 검색 결과 페이지로 이동: {new_url}")
        driver.get(new_url)
        time.sleep(random.uniform(3, 5))  # 페이지 로딩 대기
    
    # 검색 결과 페이지가 완전히 로드될 때까지 대기
    try:
        wait = WebDriverWait(driver, 10)
        # flicking-viewport가 나타날 때까지 대기
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.flicking-viewport')))
        logger.info("[클릭] 검색 결과 페이지 로드 완료")
        
        # li.ds9RptR1 요소가 나타날 때까지 추가 대기
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.flicking-viewport li.ds9RptR1')))
            logger.info("[클릭] 상품 리스트 아이템 로드 완료")
        except TimeoutException:
            logger.warning("[클릭] li.ds9RptR1 요소를 찾지 못했습니다. 페이지 구조를 확인합니다...")
            # 페이지 구조 확인
            page_check = driver.execute_script("""
                return {
                    hasViewport: !!document.querySelector('.flicking-viewport'),
                    viewportItems: document.querySelector('.flicking-viewport') ? 
                        document.querySelector('.flicking-viewport').querySelectorAll('li').length : 0,
                    allListItems: document.querySelectorAll('li').length,
                    isShoppingPage: window.location.href.includes('where=shopping') || 
                                   window.location.href.includes('msearch.shopping.naver.com'),
                    currentUrl: window.location.href
                };
            """)
            logger.warning(f"[클릭] 페이지 구조 확인: {page_check}")
        
        time.sleep(2)  # 추가 대기 시간
    except TimeoutException:
        logger.warning("[클릭] flicking-viewport를 찾지 못했습니다. 계속 진행합니다...")
    
    # 스크립트 실행 전 상태 확인
    try:
        viewport_check = driver.execute_script("""
            var viewport = document.querySelector('.flicking-viewport');
            var listItems = viewport ? viewport.querySelectorAll('li.ds9RptR1') : [];
            return {
                hasViewport: !!viewport,
                listItemCount: listItems.length,
                currentUrl: window.location.href
            };
        """)
        logger.info(f"[클릭] 스크립트 실행 전 상태: {viewport_check}")
    except Exception as e:
        logger.warning(f"[클릭] 상태 확인 중 오류: {e}")
    
    click_script = create_click_result_script(nvmid)
    
    # 스크립트 실행 시 오류 처리
    try:
        # 스크립트를 직접 실행하고 결과 확인
        logger.debug(f"[클릭] 실행할 스크립트 길이: {len(click_script)} 문자")
        
        # 스크립트를 더 안전하게 실행 (명시적으로 반환값 확인)
        result = driver.execute_script(f"""
            try {{
                var scriptResult = {click_script.strip()};
                if (scriptResult === undefined || scriptResult === null) {{
                    return {{
                        success: false,
                        reason: "script_returned_null",
                        error: "스크립트가 undefined 또는 null을 반환했습니다"
                    }};
                }}
                return scriptResult;
            }} catch (e) {{
                return {{
                    success: false,
                    reason: "wrapper_error",
                    error: e.toString(),
                    stack: e.stack ? e.stack.toString() : 'no stack'
                }};
            }}
        """)
        
        # 결과가 None인 경우 추가 확인
        if result is None:
            logger.error("[클릭] ⚠️ 스크립트 실행 결과가 None입니다!")
            
            # 스크립트가 실제로 실행되었는지 확인
            try:
                test_result = driver.execute_script("""
                    return {
                        test: "script_execution_test",
                        hasViewport: !!document.querySelector('.flicking-viewport'),
                        timestamp: Date.now(),
                        jsWorking: true
                    };
                """)
                logger.warning(f"[클릭] JavaScript 실행 테스트 결과: {test_result}")
            except Exception as e:
                logger.error(f"[클릭] JavaScript 실행 테스트 실패: {e}")
            
            # 원본 스크립트를 직접 실행해보기
            try:
                direct_result = driver.execute_script(click_script)
                logger.warning(f"[클릭] 원본 스크립트 직접 실행 결과: {direct_result}")
                if direct_result is not None:
                    result = direct_result
            except Exception as e:
                logger.error(f"[클릭] 원본 스크립트 직접 실행 실패: {e}", exc_info=True)
            
            # 스크립트를 다시 간단한 버전으로 실행해보기
            try:
                simple_test = driver.execute_script(f"""
                    (function() {{
                        try {{
                            var targetNvmid = '{nvmid}';
                            var viewport = document.querySelector('.flicking-viewport');
                            if (!viewport) {{
                                return {{ success: false, reason: 'no_viewport' }};
                            }}
                            var listItems = viewport.querySelectorAll('li.ds9RptR1');
                            return {{
                                success: false,
                                reason: 'test_execution',
                                viewportExists: true,
                                listItemCount: listItems.length,
                                targetNvmid: targetNvmid
                            }};
                        }} catch (e) {{
                            return {{
                                success: false,
                                reason: 'test_error',
                                error: e.toString()
                            }};
                        }}
                    }})();
                """)
                logger.warning(f"[클릭] 간단한 테스트 스크립트 결과: {simple_test}")
            except Exception as e:
                logger.error(f"[클릭] 간단한 테스트 스크립트 실행 실패: {e}")
            
    except Exception as e:
        logger.error(f"[클릭] 스크립트 실행 중 Python 예외 발생: {e}", exc_info=True)
        result = None
    
    # result 전체 내용 로깅
    logger.info(f"[클릭] 스크립트 실행 결과 타입: {type(result)}")
    logger.info(f"[클릭] 스크립트 실행 결과 전체: {result}")
    
    if result and isinstance(result, dict) and result.get('success'):
        logger.info(f"[클릭] ✓ 상품 클릭 완료: {result.get('nvmid')}")
        logger.info(f"[클릭] ✅ click_by_nvmid 반환: True (성공)")
        time.sleep(random.uniform(3, 5))  # 페이지 로딩 대기
        return True
    else:
        # result가 None인 경우
        if result is None:
            logger.error("[클릭] 스크립트 실행 결과가 None입니다!")
            logger.error(f"[클릭] 현재 URL: {driver.current_url}")
            # 페이지 상태 다시 확인
            try:
                page_state = driver.execute_script("""
                    return {
                        hasViewport: !!document.querySelector('.flicking-viewport'),
                        viewportItems: document.querySelector('.flicking-viewport') ? 
                            document.querySelector('.flicking-viewport').querySelectorAll('li.ds9RptR1').length : 0,
                        allLinks: document.querySelectorAll('a[aria-labelledby^="view_type_guide_"]').length,
                        bodyHTML: document.body ? document.body.innerHTML.substring(0, 500) : 'no body'
                    };
                """)
                logger.error(f"[클릭] 페이지 상태: {page_state}")
            except Exception as e:
                logger.error(f"[클릭] 페이지 상태 확인 중 오류: {e}")
            logger.error("[클릭] ❌ click_by_nvmid 반환: False (이유: 스크립트 실행 결과가 None)")
            return False
        
        # result가 dict가 아닌 경우
        if not isinstance(result, dict):
            logger.error(f"[클릭] 스크립트 실행 결과가 dict가 아닙니다! 타입: {type(result)}, 값: {result}")
            logger.error(f"[클릭] ❌ click_by_nvmid 반환: False (이유: 스크립트 실행 결과가 dict가 아님, 타입: {type(result)})")
            return False
        
        reason = result.get('reason', 'unknown')
        all_found = result.get('allFoundNvmids', [])
        found_nvmid = result.get('nvmid')
        
        logger.warning(f"[클릭] 상품을 찾지 못했습니다: reason={reason}")
        logger.info(f"[클릭] 찾을 nvmid: {nvmid}")
        logger.info(f"[클릭] 발견된 nvmid (result.nvmid): {found_nvmid}")
        logger.info(f"[클릭] 전체 발견된 nvmid 개수: {len(all_found)}")
        
        if all_found:
            logger.info(f"[클릭] 발견된 nvmid 목록 (전체 {len(all_found)}개): {all_found}")
            # 타겟 nvmid가 목록에 있는지 확인
            if str(nvmid) in [str(n) for n in all_found]:
                logger.warning(f"[클릭] ⚠️ 타겟 nvmid '{nvmid}'가 발견된 목록에 있지만 클릭하지 못했습니다!")
            else:
                logger.warning(f"[클릭] ⚠️ 타겟 nvmid '{nvmid}'가 발견된 목록에 없습니다.")
        else:
            logger.warning(f"[클릭] ⚠️ 발견된 nvmid가 하나도 없습니다. 페이지 구조를 확인하세요.")
        
        # 추가 디버깅: 페이지에서 실제로 어떤 nvmid들이 있는지 확인
        try:
            debug_check = driver.execute_script("""
                var viewport = document.querySelector('.flicking-viewport');
                if (!viewport) return { error: 'no_viewport' };
                
                var listItems = viewport.querySelectorAll('li.ds9RptR1');
                var foundNvmids = [];
                var adCount = 0;
                
                // li.ds9RptR1이 없으면 다른 선택자 시도
                var allListItems = [];
                if (listItems.length === 0) {
                    // 다른 가능한 선택자들 시도
                    allListItems = viewport.querySelectorAll('li');
                    var otherSelectors = [
                        'li[class*="product"]',
                        'li[class*="item"]',
                        'li[class*="list"]',
                        'li a[aria-labelledby^="view_type_guide_"]'
                    ];
                    for (var s = 0; s < otherSelectors.length; s++) {
                        var found = viewport.querySelectorAll(otherSelectors[s]);
                        if (found.length > 0) {
                            allListItems = found;
                            break;
                        }
                    }
                } else {
                    allListItems = listItems;
                }
                
                for (var i = 0; i < allListItems.length; i++) {
                    var item = allListItems[i];
                    // 광고 확인
                    var isAd = item.querySelector('.pbjVN80V') || 
                               item.querySelector('a.SucLwbaS') ||
                               Array.from(item.querySelectorAll('span.blind')).some(s => s.textContent.includes('광고'));
                    
                    if (isAd) {
                        adCount++;
                        continue;
                    }
                    
                    var aTag = item.querySelector('a[aria-labelledby^="view_type_guide_"]');
                    if (aTag) {
                        var ariaId = aTag.getAttribute('aria-labelledby');
                        if (ariaId && ariaId.startsWith('view_type_guide_')) {
                            var nvmid = ariaId.replace('view_type_guide_', '');
                            foundNvmids.push(nvmid);
                        }
                    }
                }
                
                // 페이지 정보 추가
                var isShoppingPage = window.location.href.includes('where=shopping') || 
                                    window.location.href.includes('msearch.shopping.naver.com');
                
                return {
                    viewportExists: true,
                    totalListItems: listItems.length,
                    allListItemsInViewport: viewport.querySelectorAll('li').length,
                    adCount: adCount,
                    nonAdCount: allListItems.length - adCount,
                    foundNvmids: foundNvmids,
                    targetNvmid: arguments[0],
                    targetInList: foundNvmids.includes(arguments[0]),
                    isShoppingPage: isShoppingPage,
                    currentUrl: window.location.href,
                    viewportHTML: viewport.innerHTML.substring(0, 500)
                };
            """, str(nvmid))
            logger.info(f"[클릭] 상세 디버그 정보: {debug_check}")
            
            # 페이지가 쇼핑 검색 결과 페이지가 아닌 경우 경고
            if not debug_check.get('isShoppingPage', False):
                logger.error(f"[클릭] ⚠️ 쇼핑 검색 결과 페이지가 아닙니다! URL: {debug_check.get('currentUrl', 'unknown')}")
                logger.error(f"[클릭] ⚠️ 일반 검색 페이지에서는 li.ds9RptR1 요소가 없을 수 있습니다.")
        except Exception as e:
            logger.error(f"[클릭] 디버그 정보 수집 중 오류: {e}", exc_info=True)
        
        logger.error(f"[클릭] ❌ click_by_nvmid 반환: False (이유: 상품을 찾지 못함, reason={reason}, 찾을 nvmid={nvmid})")
        return False


def click_by_image_url(driver, target_image_url: str) -> bool:
    """
    이미지 URL로 상품 찾아서 클릭
    
    Args:
        driver: Selenium WebDriver
        target_image_url: 찾을 이미지 URL
    
    Returns:
        bool: 클릭 성공 여부
    """
    logger.info(f"[이미지 클릭] 이미지 URL로 상품 찾기: {target_image_url}")
    
    # 1단계: 이미지 URL로 nvmid 찾기
    found_nvmid = find_nvmid_by_image_url(driver, target_image_url)
    
    if not found_nvmid:
        logger.error("[이미지 클릭] ❌ 이미지 URL로 nvmid를 찾을 수 없습니다")
        return False
    
    # 2단계: 찾은 nvmid로 클릭
    logger.info(f"[이미지 클릭] 찾은 nvmid로 클릭: {found_nvmid}")
    click_result = click_by_nvmid(driver, found_nvmid)
    logger.info(f"[이미지 클릭] click_by_nvmid 반환값: {click_result} (타입: {type(click_result)})")
    return click_result


def crawl_smartstore_direct(product_url: str, headless: bool = False) -> dict:
    """
    직접 상품 URL로 접근하여 크롤링 (봇 탐지 테스트)
    
    Args:
        product_url: 크롤링할 상품 URL
        headless: Headless 모드
    
    Returns:
        dict: 크롤링 결과
    """
    result = {
        'store_name': None,
        'product_name': None,
        'productid': None,
        'nvmid': None,
        'main_keyword': None,
        'search_url': None,
        'image_url': None,
        'image_tag': None,
        'product_url': product_url
    }
    
    driver = None
    user_data_dir = None
    
    try:
        logger.info(f"[직접 크롤링] 직접 URL 접근 테스트 시작: {product_url}")
        
        # 랜덤 프록시 선택
        proxy_ip, proxy_port = get_random_proxy()
        
        # Chrome WebDriver 설정 (프록시 포함)
        driver, user_data_dir = _setup_chrome_driver(headless=headless, proxy_ip=proxy_ip, proxy_port=proxy_port)
        wait = WebDriverWait(driver, 20)
        
        # ========== 자연스러운 접근 패턴 ==========
        # 1단계: 뉴스, 웹툰 등 첫 페이지 방문
        first_page = random.choice(NAVER_FIRST_PAGES)
        logger.info(f"[직접 크롤링] 첫 페이지 방문 (자연스러운 패턴): {first_page}")
        driver.get(first_page)
        time.sleep(random.uniform(2.5, 4.5))
        
        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(random.uniform(0.5, 1.5))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1.5))
        
        # 2단계: 네이버 메인 접속
        logger.info("[직접 크롤링] 네이버 메인 페이지로 이동")
        driver.get("https://m.naver.com")
        time.sleep(random.uniform(1.5, 3.0))
        
        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 200);")
        time.sleep(random.uniform(0.5, 1.0))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1.0))
        
        # 3단계: 직접 상품 URL 접근
        logger.info(f"[직접 크롤링] 상품 URL로 직접 접근: {product_url}")
        driver.get(product_url)
        
        # 페이지 로딩 대기 (더 긴 대기)
        time.sleep(random.uniform(3, 5))
        
        # 봇 탐지 확인을 위한 긴 대기 (테스트용)
        logger.info("[직접 크롤링] 봇 탐지 테스트를 위해 20초 대기...")
        time.sleep(20)
        
        # 현재 페이지 URL 확인
        current_url = driver.current_url
        logger.info(f"[직접 크롤링] 현재 페이지 URL: {current_url}")
        
        # 보안 확인 페이지 감지
        if "security" in current_url.lower() or "captcha" in current_url.lower():
            logger.warning("[직접 크롤링] ⚠ 보안 확인 페이지 감지됨!")
            return result
        
        # 페이지 타이틀 확인
        try:
            page_title = driver.title
            logger.info(f"[직접 크롤링] 페이지 타이틀: {page_title}")
            
            if "보안" in page_title or "security" in page_title.lower():
                logger.warning("[직접 크롤링] ⚠ 보안 페이지로 리디렉션됨!")
                return result
                
        except Exception as e:
            logger.warning(f"[직접 크롤링] 페이지 타이틀 확인 실패: {e}")
        
        # ========== 상품 정보 크롤링 ==========
        logger.info("[직접 크롤링] 상품 정보 크롤링 시작...")
        
        # 이미지 URL 추출
        try:
            # reward_url_test.py와 동일한 XPath 사용
            image_element = wait.until(EC.presence_of_element_located(
                (By.XPATH, "/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/img")
            ))
            image_url = image_element.get_attribute('src')
            if image_url:
                image_url = image_url.strip()
                # 404 이미지 URL 필터링
                if '404' in image_url or 'grafolio' in image_url or 'ssl.pstatic.net/static/grafolio' in image_url:
                    logger.warning(f"[직접 크롤링] ⚠️ 404 이미지 URL 감지, 무시: {image_url[:100]}...")
                    result['image_url'] = None
                else:
                    result['image_url'] = image_url
                    logger.info(f"[직접 크롤링] ✓ 이미지 URL: {result['image_url']}")
        except TimeoutException:
            logger.error("[직접 크롤링] ❌ 이미지 크롤링 실패 (Timeout)")
        except Exception as e:
            logger.error(f"[직접 크롤링] ❌ 이미지 크롤링 실패: {e}")
        
        # 태그 추출
        try:
            # reward_url_test.py와 동일한 XPath 사용
            tag_element = wait.until(EC.presence_of_element_located(
                (By.XPATH, "/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[10]/div/ul/li[1]/a")
            ))
            result['image_tag'] = tag_element.text.strip()
            logger.info(f"[직접 크롤링] ✓ 태그: {result['image_tag']}")
        except TimeoutException:
            logger.error("[직접 크롤링] ❌ 태그 크롤링 실패 (Timeout)")
        except Exception as e:
            logger.error(f"[직접 크롤링] ❌ 태그 크롤링 실패: {e}")
        
        # 상품명, 스토어명 등 추가 정보 (선택사항)
        try:
            store_name_element = driver.find_element(By.CSS_SELECTOR, "a.seller_tit")
            result['store_name'] = store_name_element.text.strip()
            logger.info(f"[직접 크롤링] ✓ 스토어명: {result['store_name']}")
        except Exception as e:
            logger.debug(f"[직접 크롤링] 스토어명 추출 실패: {e}")
        
        try:
            product_name_element = driver.find_element(By.CSS_SELECTOR, "h2._22kNQuEXmb")
            result['product_name'] = product_name_element.text.strip()
            logger.info(f"[직접 크롤링] ✓ 상품명: {result['product_name']}")
        except Exception as e:
            logger.debug(f"[직접 크롤링] 상품명 추출 실패: {e}")
        
        # URL에서 nvmid 추출
        try:
            import re
            nvmid_match = re.search(r'/products/(\d+)', product_url)
            if nvmid_match:
                result['nvmid'] = nvmid_match.group(1)
                logger.info(f"[직접 크롤링] ✓ nvmid: {result['nvmid']}")
        except Exception as e:
            logger.debug(f"[직접 크롤링] nvmid 추출 실패: {e}")
        
        logger.info("[직접 크롤링] 직접 URL 크롤링 완료")
        
    except Exception as e:
        logger.error(f"[직접 크롤링] 크롤링 오류: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
        if user_data_dir and os.path.exists(user_data_dir):
            try:
                time.sleep(1)
                shutil.rmtree(user_data_dir, ignore_errors=True)
                logger.info(f"[직접 크롤링] User Data Directory 정리 완료: {user_data_dir}")
            except Exception as e:
                logger.warning(f"[직접 크롤링] User Data Directory 정리 실패: {e}")
    
    return result


def crawl_smartstore_via_search(nvmid: str, main_keyword: str, image_url: str = None, headless: bool = False) -> dict:
    """
    검색을 통해 스마트스토어 상품 페이지에 접속하여 크롤링
    (이미지 URL로 상품을 찾아서 클릭)
    
    Args:
        nvmid: 네이버 상품 ID (백업용, image_url이 없을 때 사용)
        main_keyword: 메인키워드 (검색에 사용)
        image_url: 찾을 이미지 URL (우선 사용)
        headless: Headless 모드
    
    Returns:
        dict: 크롤링 결과
    """
    result = {
        'store_name': None,
        'product_name': None,
        'productid': None,
        'nvmid': nvmid,
        'main_keyword': main_keyword,
        'search_url': None,
        'image_url': image_url,
        'image_tag': None,
        'product_url': None
    }
    
    driver = None
    user_data_dir = None
    
    try:
        logger.info(f"[크롤링] 검색 기반 크롤링 시작: keyword={main_keyword}, image_url={image_url}, nvmid={nvmid}")
        
        # 랜덤 프록시 선택
        proxy_ip, proxy_port = get_random_proxy()
        
        # Chrome WebDriver 설정 (프록시 포함)
        driver, user_data_dir = _setup_chrome_driver(headless=headless, proxy_ip=proxy_ip, proxy_port=proxy_port)
        wait = WebDriverWait(driver, 20)
        
        # ========== 세션 정리 (21과 동일) ==========
        try:
            logger.info("[크롤링] 세션 정리 시작...")
            driver.delete_all_cookies()
            driver.execute_cdp_cmd('Network.clearBrowserCookies', {})
            driver.execute_cdp_cmd('Network.clearBrowserCache', {})
            logger.info("[크롤링] ✓ 세션 정리 완료")
        except Exception as e:
            logger.warning(f"[크롤링] 세션 정리 실패: {e}")
        
        # ========== 자연스러운 접근 패턴 ==========
        # 1단계: 뉴스, 웹툰 등 첫 페이지 방문
        first_page = random.choice(NAVER_FIRST_PAGES)
        logger.info(f"[크롤링] 첫 페이지 방문 (자연스러운 패턴): {first_page}")
        driver.get(first_page)
        time.sleep(random.uniform(2.5, 4.5))
        
        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(random.uniform(0.5, 1.5))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1.5))
        
        # 2단계: 네이버 메인 접속
        logger.info("[크롤링] 네이버 메인 페이지로 이동")
        driver.get("https://m.naver.com")
        time.sleep(random.uniform(1.5, 3.0))
        
        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 200);")
        time.sleep(random.uniform(0.5, 1.0))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1.0))
    
        
        # 4단계: 키워드 검색 (메인키워드로 검색)
        logger.info(f"[크롤링] 메인키워드로 검색: {main_keyword}")
        search_keyword(driver, main_keyword)
        
        # 검색 결과 페이지 로딩 대기 (더 긴 대기)
        time.sleep(random.uniform(5, 8))
        
        # 검색 결과 페이지 URL 저장
        result['search_url'] = driver.current_url
        logger.info(f"[크롤링] 검색 결과 URL: {result['search_url']}")
        
        # 5단계: 이미지 URL로 상품 찾아서 클릭 (우선) 또는 nvmid로 클릭 (백업)
        click_success = False
        if image_url:
            logger.info(f"[크롤링] 이미지 URL로 상품 찾기: {image_url}")
            click_success = click_by_image_url(driver, image_url)
            if click_success:
                # 이미지 URL로 찾은 경우, 찾은 nvmid 업데이트
                found_nvmid = find_nvmid_by_image_url(driver, image_url)
                if found_nvmid:
                    result['nvmid'] = found_nvmid
                    logger.info(f"[크롤링] 이미지 URL로 찾은 nvmid: {found_nvmid}")
        
        # 이미지 URL로 찾지 못한 경우 nvmid로 시도
        if not click_success and nvmid:
            logger.info(f"[크롤링] 이미지 URL로 찾기 실패, nvmid로 상품 클릭: {nvmid}")
            click_success = click_by_nvmid(driver, nvmid)
            logger.info(f"[크롤링] click_by_nvmid 반환값: {click_success} (타입: {type(click_success)})")
        
        if not click_success:
            logger.error("[크롤링] ❌ 상품 클릭 실패 (이미지 URL 및 nvmid 모두 실패)")
            return result
        
        # 상품 페이지 URL 저장
        result['product_url'] = driver.current_url
        logger.info(f"[크롤링] 상품 페이지 URL: {result['product_url']}")
        
        # 페이지 로딩 대기
        time.sleep(random.uniform(3, 5))
        
        # 보안문자 감지
        page_source = driver.page_source.lower()
        captcha_keywords = ['captcha', '보안문자', '자동입력 방지', 'robot', 'recaptcha', 'security check']
        has_captcha = any(keyword in page_source for keyword in captcha_keywords)
        
        if has_captcha:
            logger.warning("[크롤링] ⚠ 보안문자 감지됨! 추가 대기 시간 적용...")
            time.sleep(random.uniform(8, 12))
            driver.refresh()
            time.sleep(random.uniform(3, 5))
        
        # 자연스러운 스크롤
        logger.info("[크롤링] 자연스러운 스크롤 동작")
        for i in range(3):
            scroll_amount = 300 * (i + 1)
            driver.execute_script(f"window.scrollTo(0, {scroll_amount});")
            time.sleep(random.uniform(0.3, 0.7))
        
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(1, 2))
        
        # productid 추출 (URL에서 product_id 추출)
        if result['product_url']:
            parsed = urlparse(result['product_url'])
            if '/products/' in parsed.path:
                parts = parsed.path.split('/products/')
                if len(parts) > 1:
                    result['productid'] = parts[1].split('?')[0].split('/')[0]
        
        # 스토어명 크롤링
        logger.info("[크롤링] 스토어명 크롤링...")
        try:
            store_selectors = [
                (By.CSS_SELECTOR, 'a._store_name'),
                (By.CSS_SELECTOR, '.store_name'),
                (By.CSS_SELECTOR, 'a[href*="/stores/"]'),
                (By.CSS_SELECTOR, 'div.store_name'),
                (By.CSS_SELECTOR, 'span.store_name'),
            ]
            
            for by, selector in store_selectors:
                try:
                    element = wait.until(EC.presence_of_element_located((by, selector)))
                    if element and element.text.strip():
                        result['store_name'] = element.text.strip()
                        logger.info(f"[크롤링] ✅ 스토어명: {result['store_name']}")
                        break
                except TimeoutException:
                    continue
        except Exception as e:
            logger.warning(f"[크롤링] 스토어명 크롤링 실패: {e}")
        
        # 상품명 크롤링
        logger.info("[크롤링] 상품명 크롤링...")
        try:
            product_selectors = [
                (By.CSS_SELECTOR, 'h1.product_title'),
                (By.CSS_SELECTOR, '.product_title'),
                (By.CSS_SELECTOR, 'h1[class*="title"]'),
                (By.CSS_SELECTOR, 'h2.product_title'),
                (By.CSS_SELECTOR, 'div.product_title'),
            ]
            
            for by, selector in product_selectors:
                try:
                    element = driver.find_element(by, selector)
                    if element and element.text.strip():
                        result['product_name'] = element.text.strip()
                        logger.info(f"[크롤링] ✅ 상품명: {result['product_name']}")
                        break
                except NoSuchElementException:
                    continue
        except Exception as e:
            logger.warning(f"[크롤링] 상품명 크롤링 실패: {e}")
        
        # 이미지 URL 크롤링
        logger.info("[크롤링] 이미지 URL 크롤링...")
        try:
            image_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/img'
            logger.info(f"[크롤링] 이미지 XPath 시도: {image_xpath}")
            try:
                image_element = wait.until(EC.presence_of_element_located((By.XPATH, image_xpath)))
                result['image_url'] = image_element.get_attribute('src')
                if result['image_url']:
                    logger.info(f"[크롤링] ✅ 이미지 URL: {result['image_url']}")
                else:
                    logger.warning("[크롤링] ⚠ 이미지 요소는 찾았지만 src 속성이 없음")
            except TimeoutException:
                logger.warning("[크롤링] XPath 타임아웃, CSS 선택자로 대체 시도...")
                image_selectors = [
                    'img.product_image',
                    '.product_image img',
                    'img[class*="product"]',
                    'div.product_image img',
                ]
                for selector in image_selectors:
                    try:
                        logger.info(f"[크롤링] 이미지 CSS 선택자 시도: {selector}")
                        image_element = driver.find_element(By.CSS_SELECTOR, selector)
                        result['image_url'] = image_element.get_attribute('src')
                        if result['image_url']:
                            logger.info(f"[크롤링] ✅ 이미지 URL (대체): {result['image_url']}")
                            break
                    except NoSuchElementException:
                        continue
                if not result['image_url']:
                    logger.error("[크롤링] ❌ 이미지 URL 크롤링 실패")
        except Exception as e:
            logger.error(f"[크롤링] 이미지 URL 크롤링 실패: {e}")
        
        # 태그 크롤링
        logger.info("[크롤링] 태그 크롤링...")
        try:
            tag_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[10]/div/ul/li[1]/a'
            logger.info(f"[크롤링] 태그 XPath 시도: {tag_xpath}")
            try:
                tag_element = wait.until(EC.presence_of_element_located((By.XPATH, tag_xpath)))
                result['image_tag'] = tag_element.text.strip()
                if result['image_tag']:
                    logger.info(f"[크롤링] ✅ 태그: {result['image_tag']}")
                else:
                    logger.warning("[크롤링] ⚠ 태그 요소는 찾았지만 텍스트가 없음")
            except TimeoutException:
                logger.warning("[크롤링] XPath 타임아웃, CSS 선택자로 대체 시도...")
                tag_selectors = [
                    'div.tag_list a:first-child',
                    '.tag_list li:first-child a',
                    'ul.tag_list li:first-child a',
                ]
                for selector in tag_selectors:
                    try:
                        logger.info(f"[크롤링] 태그 CSS 선택자 시도: {selector}")
                        tag_element = driver.find_element(By.CSS_SELECTOR, selector)
                        result['image_tag'] = tag_element.text.strip()
                        if result['image_tag']:
                            logger.info(f"[크롤링] ✅ 태그 (대체): {result['image_tag']}")
                            break
                    except NoSuchElementException:
                        continue
                if not result['image_tag']:
                    logger.error("[크롤링] ❌ 태그 크롤링 실패")
        except Exception as e:
            logger.error(f"[크롤링] 태그 크롤링 실패: {e}")
        
        logger.info("[크롤링] 크롤링 완료")
        
    except Exception as e:
        logger.error(f"[크롤링] 크롤링 오류: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
        if user_data_dir and os.path.exists(user_data_dir):
            try:
                time.sleep(1)
                shutil.rmtree(user_data_dir, ignore_errors=True)
                logger.info(f"[크롤링] User Data Directory 정리 완료: {user_data_dir}")
            except Exception as e:
                logger.warning(f"[크롤링] User Data Directory 정리 실패: {e}")
    
    return result


def crawl_tag_from_reward_rank(headless: bool = False, delay: int = 5) -> int:
    """
    reward_rank 테이블을 순회하면서 search_url로 접속 후 nvmid로 클릭하여 태그 크롤링
    
    Args:
        headless: Headless 모드
        delay: 크롤링 간 대기 시간 (초)
    
    Returns:
        int: 크롤링한 레코드 수
    """
    db = SessionLocal()
    crawled_count = 0
    
    try:
        # reward_rank 테이블에서 nvmid와 search_url이 있는 레코드 조회
        records = db.query(RewardRank).filter(
            RewardRank.nvmid.isnot(None),
            RewardRank.nvmid != '',
            RewardRank.search_url.isnot(None),
            RewardRank.search_url != ''
        ).order_by(RewardRank.reward_id).all()
        
        logger.info(f"[태그 크롤링] 크롤링 대상: {len(records)}개")
        
        if not records:
            logger.info("[태그 크롤링] 크롤링할 레코드가 없습니다.")
            return 0
        
        for idx, record in enumerate(records, 1):
            reward_id = record.reward_id
            nvmid = record.nvmid
            search_url = record.search_url
            
            logger.info(f"\n{'='*60}")
            logger.info(f"[태그 크롤링] {idx}/{len(records)} - reward_id={reward_id}")
            logger.info(f"  nvmid: {nvmid}")
            logger.info(f"  search_url: {search_url}")
            logger.info(f"{'='*60}\n")
            
            # 데이터 검증
            if not nvmid or not nvmid.strip():
                logger.warning(f"[태그 크롤링] ⚠ reward_id={reward_id}: nvmid가 없어 건너뜁니다.")
                continue
            
            if not search_url or not search_url.strip():
                logger.warning(f"[태그 크롤링] ⚠ reward_id={reward_id}: search_url이 없어 건너뜁니다.")
                continue
            
            driver = None
            user_data_dir = None
            
            try:
                # 랜덤 프록시 선택
                proxy_ip, proxy_port = get_random_proxy()
                
                if proxy_ip and proxy_port:
                    logger.info(f"[태그 크롤링] ✅ 프록시 연결: {proxy_ip}:{proxy_port}")
                else:
                    logger.warning("[태그 크롤링] ⚠️ 프록시를 사용하지 않고 직접 연결합니다.")
                
                # Chrome WebDriver 설정 (프록시 포함)
                driver, user_data_dir = _setup_chrome_driver(headless=headless, proxy_ip=proxy_ip, proxy_port=proxy_port)
                wait = WebDriverWait(driver, 20)
                
                # ========== 자연스러운 접근 패턴 ==========
                # 1단계: 뉴스, 웹툰 등 첫 페이지 방문
                first_page = random.choice(NAVER_FIRST_PAGES)
                logger.info(f"[태그 크롤링] 첫 페이지 방문 (자연스러운 패턴): {first_page}")
                driver.get(first_page)
                time.sleep(random.uniform(2.5, 4.5))
                
                # 자연스러운 스크롤
                driver.execute_script("window.scrollTo(0, 300);")
                time.sleep(random.uniform(0.5, 1.5))
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(random.uniform(0.5, 1.5))
                
                # 2단계: 네이버 메인 접속
                logger.info("[태그 크롤링] 네이버 메인 페이지로 이동")
                driver.get("https://m.naver.com")
                time.sleep(random.uniform(1.5, 3.0))
                
                # 자연스러운 스크롤
                driver.execute_script("window.scrollTo(0, 200);")
                time.sleep(random.uniform(0.5, 1.0))
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(random.uniform(0.5, 1.0))
                
                # 3단계: search_url로 접속
                logger.info(f"[태그 크롤링] search_url로 접속: {search_url}")
                driver.get(search_url)
                
                # 검색 결과 페이지 로딩 대기
                time.sleep(random.uniform(5, 8))
                
                # 4단계: nvmid로 상품 클릭
                logger.info(f"[태그 크롤링] nvmid로 상품 클릭: {nvmid}")
                click_success = click_by_nvmid(driver, nvmid)
                logger.info(f"[태그 크롤링] click_by_nvmid 반환값: {click_success} (타입: {type(click_success)})")
                
                if not click_success:
                    logger.error(f"[태그 크롤링] ❌ reward_id={reward_id}: 상품 클릭 실패 (nvmid={nvmid})")
                    continue
                
                # 상품 페이지 로딩 대기
                time.sleep(random.uniform(3, 5))
                
                # 보안문자 감지 (로깅만 하고 파싱은 계속 진행)
                page_source = driver.page_source.lower()
                captcha_keywords = ['captcha', '보안문자', '자동입력 방지', 'robot', 'recaptcha', 'security check',
                                   '서비스 접속이 불가능', '현재 서비스 접속이 불가능']
                has_captcha = any(keyword in page_source for keyword in captcha_keywords)
                
                if has_captcha:
                    logger.warning("[태그 크롤링] ⚠ 보안문자 감지됨! 하지만 BeautifulSoup 파싱 계속 진행...")
                    # refresh 제거 - 현재 DOM의 HTML을 그대로 사용
                
                # 자연스러운 스크롤 (보안문자 여부와 관계없이 실행)
                logger.info("[태그 크롤링] 자연스러운 스크롤 동작")
                for i in range(3):
                    scroll_amount = 300 * (i + 1)
                    driver.execute_script(f"window.scrollTo(0, {scroll_amount});")
                    time.sleep(random.uniform(0.3, 0.7))
                
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(random.uniform(1, 2))
                
                # 5단계: 태그 크롤링 (BeautifulSoup + lxml XPath 사용)
                # 보안문자 여부와 관계없이 현재 DOM의 HTML을 BeautifulSoup으로 파싱
                logger.info("[태그 크롤링] 태그 크롤링 시작...")
                logger.info(f"[태그 크롤링] 현재 URL: {driver.current_url}")
                
                if has_captcha:
                    logger.info("[태그 크롤링] 보안문자가 감지되었지만 BeautifulSoup 파싱을 계속합니다.")
                
                # 페이지 로드 상태 확인
                try:
                    page_ready = driver.execute_script("return document.readyState")
                    logger.info(f"[태그 크롤링] 페이지 로드 상태: {page_ready}")
                except Exception as e:
                    logger.warning(f"[태그 크롤링] 페이지 상태 확인 실패: {e}")
                
                # 추가 대기 시간 (동적 콘텐츠 로딩 대기)
                logger.info("[태그 크롤링] 동적 콘텐츠 로딩 대기 중...")
                time.sleep(random.uniform(2, 4))
                
                tag_value = None
                try:
                    # Selenium에서 HTML 소스 가져오기 (보안문자 여부와 관계없이)
                    html_source = driver.page_source
                    logger.info(f"[태그 크롤링] HTML 소스 길이: {len(html_source)} bytes")
                    
                    if has_captcha:
                        logger.info("[태그 크롤링] 보안문자 페이지이지만 BeautifulSoup으로 파싱 시도...")
                    
                    # BeautifulSoup으로 파싱 (보안문자 여부와 관계없이)
                    soup = BeautifulSoup(html_source, 'html.parser')
                    
                    # 방법 1: lxml etree를 사용한 XPath 직접 사용
                    tag_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[11]/div/ul/li[1]/a'
                    logger.info(f"[태그 크롤링] 태그 XPath 시도: {tag_xpath}")
                    
                    try:
                        # lxml HTMLParser로 파싱 (BeautifulSoup보다 XPath 지원이 좋음)
                        parser = etree.HTMLParser()
                        tree = etree.fromstring(html_source.encode('utf-8'), parser)
                        
                        # XPath로 요소 찾기
                        elements = tree.xpath(tag_xpath)
                        if elements and len(elements) > 0:
                            element = elements[0]
                            # 텍스트 추출
                            tag_value = element.text
                            if not tag_value:
                                # text가 없으면 tail이나 하위 요소의 text 확인
                                tag_value = element.tail or ''.join(element.itertext()).strip()
                            if tag_value:
                                tag_value = tag_value.strip()
                                logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (XPath): {tag_value}")
                    except Exception as e:
                        logger.warning(f"[태그 크롤링] XPath 직접 사용 실패: {e}")
                    
                    # 방법 2: XPath가 실패하면 BeautifulSoup의 find 메서드로 경로 따라가기
                    if not tag_value:
                        logger.info("[태그 크롤링] BeautifulSoup 경로 따라가기 시도...")
                        try:
                            # XPath: /html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[11]/div/ul/li[1]/a
                            # Python 인덱스로 변환: [0, 0, 3, 1, 1, 0, 2, 5, 0, 10, 0] (div 경로만, div[11] → 인덱스 10)
                            
                            # 방법 2-1: #INTRODUCE ID로 먼저 찾기
                            introduce = soup.find(id='INTRODUCE')
                            if introduce:
                                logger.debug("[태그 크롤링] #INTRODUCE 요소 찾음")
                                # #INTRODUCE > div > div:nth-child(11) > div > ul > li:nth-child(1) > a
                                divs = introduce.find_all('div', recursive=False)
                                if len(divs) > 0:
                                    first_div = divs[0]
                                    nested_divs = first_div.find_all('div', recursive=False)
                                    if len(nested_divs) >= 11:
                                        target_div = nested_divs[10]  # nth-child(11) → 인덱스 10
                                        inner_divs = target_div.find_all('div', recursive=False)
                                        if len(inner_divs) > 0:
                                            ul = inner_divs[0].find('ul')
                                            if ul:
                                                li = ul.find('li')
                                                if li:
                                                    a = li.find('a')
                                                    if a:
                                                        tag_value = a.get_text(strip=True)
                                                        if tag_value:
                                                            logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (#INTRODUCE 경로): {tag_value}")
                            
                            # 방법 2-2: #INTRODUCE로 찾지 못하면 기존 경로 따라가기
                            if not tag_value:
                                body = soup.find('body')
                                if body:
                                    divs = body.find_all('div', recursive=False)
                                    logger.debug(f"[태그 크롤링] body > div 개수: {len(divs)}")
                                    if len(divs) > 0:
                                        current = divs[0]  # div[1] → 인덱스 0
                                        # div 경로를 따라가기 (div[11] → 인덱스 10)
                                        div_path = [0, 3, 1, 1, 0, 2, 5, 0, 10, 0]  # XPath 인덱스를 Python 인덱스로 변환
                                    path_idx = 0
                                    for idx in div_path:
                                        divs = current.find_all('div', recursive=False)
                                        logger.debug(f"[태그 크롤링] 경로 단계 {path_idx}: div 개수={len(divs)}, 찾는 인덱스={idx}")
                                        if idx < len(divs):
                                            current = divs[idx]
                                            path_idx += 1
                                        else:
                                            logger.warning(f"[태그 크롤링] 경로 단계 {path_idx}에서 실패: div 개수={len(divs)}, 찾는 인덱스={idx}")
                                            current = None
                                            break
                                    
                                    if current:
                                        # ul 찾기
                                        ul = current.find('ul')
                                        logger.debug(f"[태그 크롤링] ul 찾기 결과: {ul is not None}")
                                        if ul:
                                            # li[1] → 인덱스 0
                                            li = ul.find('li')
                                            logger.debug(f"[태그 크롤링] li 찾기 결과: {li is not None}")
                                            if li:
                                                a = li.find('a')
                                                logger.debug(f"[태그 크롤링] a 찾기 결과: {a is not None}")
                                                if a:
                                                    tag_value = a.get_text(strip=True)
                                                    logger.debug(f"[태그 크롤링] a 태그 텍스트: '{tag_value}'")
                                                    if tag_value:
                                                        logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (경로 따라가기): {tag_value}")
                                    else:
                                        logger.warning("[태그 크롤링] 경로 따라가기 실패: current가 None")
                                else:
                                    logger.warning("[태그 크롤링] body > div가 없음")
                            else:
                                logger.warning("[태그 크롤링] body를 찾을 수 없음")
                        except Exception as e:
                            logger.warning(f"[태그 크롤링] 경로 따라가기 실패: {e}", exc_info=True)
                    
                    # 방법 3: CSS 선택자로 태그 찾기
                    if not tag_value:
                        logger.info("[태그 크롤링] CSS 선택자로 태그 찾기 시도...")
                        tag_selectors = [
                            '#INTRODUCE > div > div:nth-child(11) > div > ul > li:nth-child(1) > a',
                            '#INTRODUCE div:nth-child(11) ul li:first-child a',
                            '#INTRODUCE ul li:first-child a',
                            'a[data-shp-inventory="tag"]:first-of-type',
                            'a[data-shp-inventory="tag"]',
                            'div.tag_list a:first-child',
                            '.tag_list li:first-child a',
                            'ul.tag_list li:first-child a',
                            'div[class*="tag"] a:first-child',
                            'ul[class*="tag"] li:first-child a',
                            'div[class*="Tag"] a:first-child',
                            'a[href*="tag"]:first-of-type',
                        ]
                        
                        for selector in tag_selectors:
                            try:
                                element = soup.select_one(selector)
                                if element:
                                    tag_value = element.get_text(strip=True)
                                    logger.debug(f"[태그 크롤링] CSS 선택자 '{selector}'로 요소 찾음, 텍스트: '{tag_value}'")
                                    if tag_value:
                                        logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (CSS 선택자: {selector}): {tag_value}")
                                        break
                                else:
                                    logger.debug(f"[태그 크롤링] CSS 선택자 '{selector}'로 요소를 찾지 못함")
                            except Exception as e:
                                logger.debug(f"[태그 크롤링] CSS 선택자 '{selector}' 실패: {e}")
                                continue
                    
                    # 방법 4: data-shp-inventory="tag" 속성으로 찾기
                    if not tag_value:
                        logger.info("[태그 크롤링] data-shp-inventory='tag' 속성으로 태그 찾기...")
                        try:
                            tag_links = soup.find_all('a', attrs={'data-shp-inventory': 'tag'})
                            logger.debug(f"[태그 크롤링] data-shp-inventory='tag' 속성을 가진 링크 개수: {len(tag_links)}")
                            
                            if tag_links:
                                # 첫 번째 태그 링크 사용
                                first_tag_link = tag_links[0]
                                tag_value = first_tag_link.get_text(strip=True)
                                if tag_value:
                                    logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (data-shp-inventory 속성): {tag_value}")
                        except Exception as e:
                            logger.warning(f"[태그 크롤링] data-shp-inventory 속성 검색 실패: {e}")
                    
                    # 방법 5: 모든 ul > li > a 구조에서 태그 후보 찾기
                    if not tag_value:
                        logger.info("[태그 크롤링] ul > li > a 구조에서 태그 후보 찾기...")
                        try:
                            all_uls = soup.find_all('ul')
                            logger.debug(f"[태그 크롤링] 페이지의 ul 개수: {len(all_uls)}")
                            tag_candidates = []
                            
                            for ul_idx, ul in enumerate(all_uls):
                                lis = ul.find_all('li', limit=10)  # 처음 10개로 증가
                                logger.debug(f"[태그 크롤링] ul[{ul_idx}]의 li 개수: {len(lis)}")
                                
                                for li_idx, li in enumerate(lis):
                                    a = li.find('a')
                                    if a:
                                        text = a.get_text(strip=True)
                                        href = a.get('href', '')
                                        data_inventory = a.get('data-shp-inventory', '')
                                        
                                        # data-shp-inventory="tag" 속성이 있으면 우선
                                        if data_inventory == 'tag' and text:
                                            tag_value = text
                                            logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (ul 구조, data-shp-inventory): {tag_value}")
                                            break
                                        
                                        # 짧은 텍스트만 후보로 추가
                                        if text and 2 <= len(text) <= 30:
                                            is_tag_link = 'tag' in href.lower() or 'keyword' in href.lower() or 'search' in href.lower()
                                            tag_candidates.append({
                                                'text': text,
                                                'href': href[:100] if href else '',
                                                'is_tag_link': is_tag_link,
                                                'ul_idx': ul_idx,
                                                'li_idx': li_idx
                                            })
                                            logger.debug(f"[태그 크롤링] 후보 발견: '{text}' (href: {href[:50] if href else 'None'}, is_tag: {is_tag_link})")
                                
                                if tag_value:
                                    break
                                
                                # 태그 링크가 있으면 우선 사용
                                if not tag_value and tag_candidates:
                                    for candidate in tag_candidates:
                                        if candidate.get('is_tag_link') and candidate.get('text'):
                                            tag_value = candidate['text']
                                            logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (ul 구조, 태그 링크): {tag_value}")
                                            break
                                    
                                    # 태그 링크가 없으면 첫 번째 후보 사용 (더 짧은 텍스트 우선)
                                    if not tag_value and tag_candidates:
                                        # 텍스트 길이로 정렬 (짧은 것 우선)
                                        tag_candidates.sort(key=lambda x: len(x['text']))
                                        tag_value = tag_candidates[0]['text']
                                        logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (ul 구조, 첫 번째 후보): {tag_value}")
                            
                            if not tag_value and tag_candidates:
                                logger.warning(f"[태그 크롤링] ul 구조에서 {len(tag_candidates)}개의 후보를 찾았지만 태그로 인식하지 못함")
                        except Exception as e:
                            logger.warning(f"[태그 크롤링] ul 구조 검색 실패: {e}", exc_info=True)
                    
                    # 방법 6: JavaScript로 동적 로딩된 태그 확인
                    if not tag_value:
                        logger.info("[태그 크롤링] JavaScript로 동적 태그 확인...")
                        try:
                            # Selenium으로 JavaScript 실행하여 태그 텍스트 가져오기
                            # 방법 1: CSS 선택자 사용 (#INTRODUCE)
                            tag_text = driver.execute_script("""
                                try {
                                    var selector = '#INTRODUCE > div > div:nth-child(11) > div > ul > li:nth-child(1) > a';
                                    var element = document.querySelector(selector);
                                    if (element) {
                                        return element.textContent.trim();
                                    }
                                    
                                    // 방법 2: data-shp-inventory="tag" 속성 사용
                                    var tagElements = document.querySelectorAll('a[data-shp-inventory="tag"]');
                                    if (tagElements.length > 0) {
                                        return tagElements[0].textContent.trim();
                                    }
                                    
                                    // 방법 3: XPath 사용
                                    var xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[11]/div/ul/li[1]/a';
                                    var result = document.evaluate(
                                        xpath,
                                        document,
                                        null,
                                        XPathResult.FIRST_ORDERED_NODE_TYPE,
                                        null
                                    );
                                    var node = result.singleNodeValue;
                                    return node ? node.textContent.trim() : null;
                                } catch (e) {
                                    return null;
                                }
                            """)
                            if tag_text:
                                tag_value = tag_text
                                logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (JavaScript): {tag_value}")
                            else:
                                logger.debug("[태그 크롤링] JavaScript로 태그를 찾지 못함")
                        except Exception as e:
                            logger.debug(f"[태그 크롤링] JavaScript 태그 확인 실패: {e}")
                    
                    # 모든 방법 실패 시 HTML 구조 분석
                    if not tag_value:
                        logger.warning("[태그 크롤링] ❌ 모든 방법으로 태그를 찾지 못했습니다. HTML 구조 분석...")
                        try:
                            # ul > li > a 구조 분석
                            all_uls = soup.find_all('ul')
                            logger.info(f"[태그 크롤링] 페이지의 ul 개수: {len(all_uls)}")
                            
                            # 각 ul의 li와 a 개수 확인
                            for ul_idx, ul in enumerate(all_uls[:10]):  # 처음 10개만
                                lis = ul.find_all('li')
                                links = ul.find_all('a')
                                if lis and links:
                                    first_link_text = links[0].get_text(strip=True) if links else ''
                                    logger.info(f"[태그 크롤링] ul[{ul_idx}]: li={len(lis)}, a={len(links)}, 첫 번째 링크 텍스트='{first_link_text[:50]}'")
                            
                            # div[class*="tag"] 요소 찾기
                            tag_divs = soup.find_all('div', class_=lambda x: x and 'tag' in x.lower())
                            logger.info(f"[태그 크롤링] class에 'tag'가 포함된 div 개수: {len(tag_divs)}")
                            
                            # href에 'tag' 또는 'keyword'가 포함된 링크 찾기
                            tag_links = soup.find_all('a', href=lambda x: x and ('tag' in x.lower() or 'keyword' in x.lower()))
                            logger.info(f"[태그 크롤링] href에 'tag' 또는 'keyword'가 포함된 링크 개수: {len(tag_links)}")
                            for link in tag_links[:5]:  # 처음 5개만
                                text = link.get_text(strip=True)
                                href = link.get('href', '')
                                logger.info(f"[태그 크롤링] 태그 링크 후보: '{text}' (href: {href[:100]})")
                        except Exception as e:
                            logger.warning(f"[태그 크롤링] HTML 구조 분석 실패: {e}")
                    
                except Exception as e:
                    logger.error(f"[태그 크롤링] 태그 크롤링 실패: {e}", exc_info=True)
                
                # 6단계: DB 업데이트
                if tag_value:
                    db_session = SessionLocal()
                    try:
                        existing = db_session.query(RewardRank).filter(
                            RewardRank.reward_id == reward_id
                        ).first()
                        
                        if existing:
                            old_tag = existing.image_tag
                            existing.image_tag = tag_value
                            existing.updated_at = datetime.now()
                            db_session.commit()
                            logger.info(f"[DB] ✅ reward_id={reward_id} 태그 업데이트 완료")
                            logger.info(f"[DB]    이전 태그: {old_tag}")
                            logger.info(f"[DB]    새 태그: {tag_value}")
                            crawled_count += 1
                        else:
                            logger.warning(f"[DB] ⚠️ reward_id={reward_id} 레코드를 찾을 수 없습니다.")
                    except Exception as e:
                        db_session.rollback()
                        logger.error(f"[DB] ❌ reward_id={reward_id} 태그 업데이트 실패: {e}", exc_info=True)
                    finally:
                        db_session.close()
                else:
                    logger.warning(f"[태그 크롤링] ⚠️ reward_id={reward_id}: 태그를 크롤링하지 못했습니다.")
                
            except Exception as e:
                logger.error(f"[태그 크롤링] reward_id={reward_id} 크롤링 오류: {e}", exc_info=True)
            finally:
                if driver:
                    driver.quit()
                if user_data_dir and os.path.exists(user_data_dir):
                    try:
                        time.sleep(1)
                        shutil.rmtree(user_data_dir, ignore_errors=True)
                        logger.info(f"[태그 크롤링] User Data Directory 정리 완료: {user_data_dir}")
                    except Exception as e:
                        logger.warning(f"[태그 크롤링] User Data Directory 정리 실패: {e}")
            
            # 마지막 항목이 아닐 때만 대기
            if idx < len(records):
                delay_time = random.uniform(delay, delay + 5)
                logger.info(f"\n[대기] 다음 크롤링까지 {delay_time:.2f}초 대기...\n")
                time.sleep(delay_time)
        
        logger.info(f"[태그 크롤링] 완료: 총 {crawled_count}개 레코드 크롤링됨")
        
    except Exception as e:
        logger.error(f"[태그 크롤링] 오류: {e}", exc_info=True)
    finally:
        db.close()
    
    return crawled_count


def save_to_db(crawled_data: dict) -> int:
    """
    크롤링 데이터를 DB에 저장
    """
    db = SessionLocal()
    try:
        search_url = crawled_data.get('search_url')
        
        # product_name에서 HTML 태그 제거
        product_name = crawled_data.get('product_name')
        if product_name:
            import re
            product_name = re.sub(r'<[^>]+>', '', product_name).strip()
        
        # product_url 또는 nvmid로 기존 데이터 확인
        existing = None
        if crawled_data.get('product_url'):
            existing = db.query(RewardRank).filter(
                RewardRank.product_url == crawled_data.get('product_url')
            ).first()
        # elif crawled_data.get('nvmid'):
        #     existing = db.query(RewardRank).filter(
        #         RewardRank.nvmid == crawled_data.get('nvmid')
        #     ).first()
        
        if existing:
            # 업데이트
            existing.store_name = crawled_data.get('store_name')
            existing.product_name = product_name
            existing.productid = crawled_data.get('productid')  # productid에 상품 ID 저장
            existing.nvmid = crawled_data.get('nvmid')  # nvmid에 nvmid 저장
            existing.keyword = crawled_data.get('keyword')  # 키워드 저장
            logger.info(f"[DB] 저장할 키워드: {crawled_data.get('keyword')}")
            # existing.main_keyword = crawled_data.get('main_keyword')  # DB에 컬럼 없음
            if search_url:
                existing.search_url = search_url
            if crawled_data.get('product_url'):
                existing.product_url = crawled_data.get('product_url')
            existing.image_url = crawled_data.get('image_url')
            existing.image_tag = crawled_data.get('image_tag')
            existing.updated_at = datetime.now()
            db.commit()
            logger.info(f"[DB] 업데이트 완료: reward_id={existing.reward_id}, productid={existing.productid}, nvmid={existing.nvmid}, keyword={existing.keyword}")
            return existing.reward_id
        else:
            # 새로 추가
            reward_rank = RewardRank(
                store_name=crawled_data.get('store_name'),
                product_name=product_name,
                productid=crawled_data.get('productid'),  # productid에 상품 ID 저장
                nvmid=crawled_data.get('nvmid'),  # nvmid에 nvmid 저장
                keyword=crawled_data.get('keyword'),  # 키워드 저장
                # main_keyword=crawled_data.get('main_keyword'),  # DB에 컬럼 없음
                search_url=search_url,
                product_url=crawled_data.get('product_url'),
                image_url=crawled_data.get('image_url'),
                image_tag=crawled_data.get('image_tag')
            )
            db.add(reward_rank)
            db.commit()
            db.refresh(reward_rank)
            logger.info(f"[DB] 저장 완료: reward_id={reward_rank.reward_id}")
            return reward_rank.reward_id
            
    except Exception as e:
        db.rollback()
        logger.error(f"[DB] 저장 실패: {e}", exc_info=True)
        raise
    finally:
        db.close()


def update_search_url_for_reward_rank():
    """
    reward_rank 테이블에서 search_url이 없는 데이터에 대해 search_url을 생성하여 업데이트
    
    Returns:
        int: 업데이트된 레코드 수
    """
    db = SessionLocal()
    updated_count = 0
    
    try:
        # search_url이 NULL이거나 빈 문자열이고, product_name이 있는 데이터 조회
        records = db.query(RewardRank).filter(
            (RewardRank.search_url.is_(None)) | (RewardRank.search_url == ''),
            RewardRank.product_name.isnot(None),
            RewardRank.product_name != ''
        ).all()
        
        logger.info(f"[search_url 업데이트] 업데이트 대상: {len(records)}개")
        
        for record in records:
            try:
                if record.product_name:
                    # product_name으로 search_url 생성
                    search_url = create_search_url_with_params(record.product_name, db=db)
                    record.search_url = search_url
                    record.updated_at = datetime.now()
                    updated_count += 1
                    logger.info(f"[search_url 업데이트] reward_id={record.reward_id}: search_url 생성 완료")
            except Exception as e:
                logger.error(f"[search_url 업데이트] reward_id={record.reward_id} 업데이트 실패: {e}", exc_info=True)
                continue
        
        db.commit()
        logger.info(f"[search_url 업데이트] 총 {updated_count}개 레코드 업데이트 완료")
        
    except Exception as e:
        db.rollback()
        logger.error(f"[search_url 업데이트] 오류: {e}", exc_info=True)
        raise
    finally:
        db.close()
    
    return updated_count


def update_search_url_by_product_url(product_url: str) -> bool:
    """
    특정 product_url에 대해 search_url을 생성하여 업데이트
    
    Args:
        product_url: 상품 URL
    
    Returns:
        bool: 업데이트 성공 여부
    """
    db = SessionLocal()
    
    try:
        # product_url로 레코드 조회
        record = db.query(RewardRank).filter(
            RewardRank.product_url == product_url
        ).first()
        
        if not record:
            logger.warning(f"[search_url 업데이트] product_url로 레코드를 찾을 수 없습니다: {product_url}")
            return False
        
        # product_name이 있으면 search_url 생성
        if record.product_name:
            search_url = create_search_url_with_params(record.product_name, db=db)
            record.search_url = search_url
            record.updated_at = datetime.now()
            db.commit()
            logger.info(f"[search_url 업데이트] reward_id={record.reward_id}: search_url 업데이트 완료")
            return True
        else:
            logger.warning(f"[search_url 업데이트] product_name이 없어 search_url을 생성할 수 없습니다: product_url={product_url}")
            return False
        
    except Exception as e:
        db.rollback()
        logger.error(f"[search_url 업데이트] 오류: {e}", exc_info=True)
        return False
    finally:
        db.close()


def process_product_url_with_api(product_url: str, search_keyword: str = None) -> Dict:
    """
    product_url을 입력받아 Open API로 정보를 가져오고, DB에 저장한 후 search_url 생성
    
    Args:
        product_url: 상품 URL
        search_keyword: 검색 키워드 (필수)
    
    Returns:
        dict: 크롤링 결과 (search_url 포함)
    """
    result = {
        'store_name': None,
        'product_name': None,
        'productid': None,
        'nvmid': None,
        'main_keyword': None,
        'keyword': None,  # --search-keyword로 입력한 키워드 (나중에 설정)
        'search_url': None,
        'image_url': None,
        'image_tag': None,
        'product_url': product_url
    }
    
    try:
        logger.info(f"[처리] product_url 처리 시작: {product_url}, search_keyword: {search_keyword}")
        
        # search_keyword가 없으면 실패
        if not search_keyword or not search_keyword.strip():
            logger.error("[처리] search_keyword가 없어 처리할 수 없습니다.")
            return result
        
        search_keyword = search_keyword.strip()
        result['keyword'] = search_keyword  # --search-keyword로 입력한 키워드 저장
        logger.info(f"[처리] 사용할 search_keyword: '{search_keyword}' (DB에 저장될 키워드: {result['keyword']}')")
        
        # 1단계: product_url에서 URL 타입과 ID 추출
        url_info = extract_nvmid_from_product_url(product_url)
        if not url_info:
            logger.error("[처리] URL에서 ID 추출 실패")
            return result
        
        url_type = url_info['url_type']
        product_id = url_info.get('product_id')
        nvmid_from_url = url_info.get('nvmid')
        
        # productid와 nvmid 설정
        if url_type == 'smartstore':
            result['productid'] = product_id  # 상품 ID 그대로 저장
        else:  # shopping
            result['productid'] = None  # shopping URL에는 product_id가 없음
        
        logger.info(f"[처리] 추출된 정보: url_type={url_type}, product_id={product_id}, nvmid={nvmid_from_url}")
        
        # 2단계: Open API로 상품 정보 가져오기 (search_keyword 사용)
        logger.info(f"[처리] 키워드로 nvmid 조회: {search_keyword}")
        api_result = get_rank_by_keyword_and_url(search_keyword, product_url)
        
        if api_result and api_result.get("success"):
            # nvmid 업데이트 (crol_test2.py 로직 사용)
            result['nvmid'] = api_result.get('nvmid')  # nvmid 컬럼에 nvmid 저장
            # productid는 이미 URL에서 추출한 product_id로 설정됨 (smartstore인 경우)
            result['product_name'] = api_result.get('product_name')
            result['main_keyword'] = result['product_name']
            
            # 이미지 URL과 스토어명을 API 결과에서 가져오기
            result['image_url'] = api_result.get('image_url')
            result['store_name'] = api_result.get('store_name')
            
            # 3단계: search_url 생성 (DB 저장 전에 생성)
            if result['keyword']:
                # keyword를 사용하여 search_url 생성
                result['search_url'] = create_search_url_with_params(result['keyword'])
                logger.info(f"[처리] search_url 생성 완료: {result['search_url']}")
            
            # 4단계: DB 저장은 메인 루프에서 flush insert로 처리
            logger.info(f"[처리] 처리 완료 (저장할 키워드: {result.get('keyword')})")
        else:
            error_msg = api_result.get('error') if api_result else 'API 결과 없음'
            logger.error(f"[처리] nvmid 조회 실패: {error_msg} (키워드: {search_keyword})")
            # API 조회 실패해도 키워드는 저장 (메인 루프에서 flush insert로 처리)
            logger.info(f"[처리] API 조회 실패 (키워드: {result.get('keyword')})")
        
        logger.info("[처리] product_url 처리 완료")
        
    except Exception as e:
        logger.error(f"[처리] 오류: {e}", exc_info=True)
    
    return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='reward_rank 테이블 크롤링 프로그램 (Open API 기반)')
    parser.add_argument('--product-url', type=str, default=None, help='상품 URL (Open API로 정보 가져오기)')
    parser.add_argument('--search-keyword', type=str, default=None, help='검색 키워드 (Open API 검색용, 선택사항)')
    parser.add_argument('--nvmid', type=str, default=None, help='네이버 상품 ID')
    parser.add_argument('--keyword', type=str, default=None, help='메인키워드')
    parser.add_argument('--url', type=str, default=None, help='직접 접근할 상품 URL (봇 탐지 테스트용)')
    parser.add_argument('--headless', action='store_true', help='Headless 모드')
    parser.add_argument('--delay', type=int, default=5, help='크롤링 간 대기 시간 (초)')
    parser.add_argument('--update-search-url', action='store_true', help='reward_rank 테이블의 search_url 업데이트 (product_name이 있는데 search_url이 없는 경우)')
    parser.add_argument('--update-search-url-by-url', type=str, default=None, help='특정 product_url에 대해 search_url 업데이트')
    parser.add_argument('--crawl-tags', action='store_true', help='reward_rank 테이블을 순회하면서 search_url로 접속 후 nvmid로 클릭하여 태그 크롤링')
    
    args = parser.parse_args()
    
    # search_url 업데이트 옵션 처리
    if args.update_search_url:
        logger.info("reward_rank 테이블의 search_url 업데이트 시작...")
        updated_count = update_search_url_for_reward_rank()
        logger.info(f"search_url 업데이트 완료: {updated_count}개 레코드 업데이트됨")
        return
    elif args.update_search_url_by_url:
        logger.info(f"특정 product_url의 search_url 업데이트 시작: {args.update_search_url_by_url}")
        success = update_search_url_by_product_url(args.update_search_url_by_url)
        if success:
            logger.info("search_url 업데이트 완료")
        else:
            logger.error("search_url 업데이트 실패")
        return
    elif args.crawl_tags:
        # 태그 크롤링 옵션 처리
        logger.info("reward_rank 테이블 태그 크롤링 시작...")
        crawled_count = crawl_tag_from_reward_rank(headless=args.headless, delay=args.delay)
        logger.info(f"태그 크롤링 완료: {crawled_count}개 레코드 크롤링됨")
        return
    
    if args.product_url:
        # product_url 처리 (Open API 사용)
        logger.info(f"product_url 처리 시작: {args.product_url}")
        result = process_product_url_with_api(args.product_url, args.search_keyword)
        if result:
            logger.info(f"처리 결과: {result}")
            # process_product_url_with_api 내부에서 이미 DB 저장 및 search_url 생성 완료
    elif args.url:
        # 직접 URL 테스트
        logger.info(f"직접 URL 접근 테스트: {args.url}")
        result = crawl_smartstore_direct(args.url, headless=args.headless)
        if result:
            logger.info(f"직접 크롤링 결과: {result}")
            save_to_db(result)
    elif args.nvmid and args.keyword:
        # 단일 크롤링
        logger.info(f"단일 크롤링 시작: nvmid={args.nvmid}, keyword={args.keyword}")
        result = crawl_smartstore_via_search(args.nvmid, args.keyword, headless=args.headless)
        if result:
            logger.info(f"크롤링 결과: {result}")
            save_to_db(result)
    else:
        # reward_target 테이블에서 크롤링 대상 가져오기
        db = SessionLocal()
        try:
            logger.info("[DB] reward_target 테이블에서 크롤링 대상 조회...")
            # reward_target_id별로 keyword와 product_url을 함께 가져오기
            targets = db.query(RewardTarget).filter(
                RewardTarget.product_url.isnot(None),
                RewardTarget.product_url != '',
                RewardTarget.keyword.isnot(None),
                RewardTarget.keyword != ''
            ).order_by(RewardTarget.reward_target_id).all()
            
            logger.info(f"[DB] 크롤링 대상: {len(targets)}개")
            
            for idx, target in enumerate(targets, 1):
                # reward_target_id별로 keyword와 product_url 확인
                reward_target_id = target.reward_target_id
                keyword = target.keyword
                product_url = target.product_url
                
                logger.info(f"\n{'='*60}")
                logger.info(f"[진행] {idx}/{len(targets)} - reward_target_id={reward_target_id}")
                logger.info(f"  keyword: {keyword}")
                logger.info(f"  product_url: {product_url}")
                logger.info(f"{'='*60}\n")
                
                # 데이터 검증
                if not product_url or not product_url.strip():
                    logger.warning(f"[진행] ⚠ reward_target_id={reward_target_id}: product_url이 없어 건너뜁니다.")
                    continue
                
                if not keyword or not keyword.strip():
                    logger.warning(f"[진행] ⚠ reward_target_id={reward_target_id}: keyword가 없어 건너뜁니다.")
                    continue
                
                # reward_target_id별로 정확하게 매칭된 keyword와 product_url 사용
                logger.info(f"[처리] reward_target_id={reward_target_id} 처리 시작")
                logger.info(f"  - keyword: '{keyword}'")
                logger.info(f"  - product_url: '{product_url}'")
                
                # 각 reward_target_id별로 처리하고 flush insert
                result = process_product_url_with_api(product_url, keyword)
                if result:
                    logger.info(f"[처리] reward_target_id={reward_target_id} 처리 완료")
                    # flush insert: 각 레코드마다 즉시 commit
                    db_session = SessionLocal()
                    try:
                        # product_url로 기존 데이터 확인
                        existing = db_session.query(RewardRank).filter(
                            RewardRank.product_url == product_url
                        ).first()
                        
                        if existing:
                            # 업데이트
                            existing.store_name = result.get('store_name')
                            if result.get('product_name'):
                                import re
                                clean_product_name = re.sub(r'<[^>]+>', '', result.get('product_name')).strip()
                                existing.product_name = clean_product_name
                            existing.productid = result.get('productid')
                            existing.nvmid = result.get('nvmid')
                            existing.keyword = result.get('keyword')  # 키워드 저장
                            if result.get('search_url'):
                                existing.search_url = result.get('search_url')
                            existing.image_url = result.get('image_url')
                            existing.image_tag = result.get('image_tag')
                            existing.updated_at = datetime.now()
                            db_session.commit()
                            logger.info(f"[DB] reward_target_id={reward_target_id} 업데이트 완료: reward_id={existing.reward_id}")
                        else:
                            # 새로 추가
                            import re
                            product_name = result.get('product_name')
                            if product_name:
                                product_name = re.sub(r'<[^>]+>', '', product_name).strip()
                            
                            reward_rank = RewardRank(
                                store_name=result.get('store_name'),
                                product_name=product_name,
                                productid=result.get('productid'),
                                nvmid=result.get('nvmid'),
                                keyword=result.get('keyword'),  # 키워드 저장
                                search_url=result.get('search_url'),
                                product_url=result.get('product_url'),
                                image_url=result.get('image_url'),
                                image_tag=result.get('image_tag')
                            )
                            db_session.add(reward_rank)
                            db_session.commit()
                            db_session.refresh(reward_rank)
                            logger.info(f"[DB] reward_target_id={reward_target_id} 저장 완료: reward_id={reward_rank.reward_id}")
                    except Exception as e:
                        db_session.rollback()
                        logger.error(f"[DB] reward_target_id={reward_target_id} 저장 실패: {e}", exc_info=True)
                    finally:
                        db_session.close()
                else:
                    logger.warning(f"[처리] reward_target_id={reward_target_id} 처리 실패")
                
                # 마지막 항목이 아닐 때만 대기
                if idx < len(targets):
                    delay = random.uniform(args.delay, args.delay + 5)
                    logger.info(f"\n[대기] 다음 크롤링까지 {delay:.2f}초 대기...\n")
                    time.sleep(delay)
                    
        except Exception as e:
            logger.error(f"[DB] 크롤링 중 오류: {e}", exc_info=True)
        finally:
            db.close()


if __name__ == "__main__":
    main()
