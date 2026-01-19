import os
import sys
import time
import re
import logging
import requests
from typing import List, Dict, Optional
from itertools import combinations
from urllib.parse import quote, urlparse
from dotenv import load_dotenv
import json
import sys
import os
# .env 파일 로드
load_dotenv()
# 순위 집계는 DB에 저장 안됩니다. 
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

API_URL = "https://openapi.naver.com/v1/search/shop.json"

# 처음에 가격비교 nvmid 인지, product_id 인지 확인한다. 사용자가 입력한 값을 확인 가능
# 그리고 입력한 값에 따라 순위 매칭 (rank 매서드를 다르게 줍니다) 

# 
# 

# 만약 productID 가 다이렉트이명 productid 로 매칭
# 가격 비교 순위 productId 로 매칭 = nvmid 로 매칭

# 데이터랩 (쇼핑인사이트)
# nvmid 로 통검 순위 조회하는 방법이 있냐고
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
                "productId": str,  # product_id 매칭용 -- product_id 와 nvmid 는 다른것입니다. 
                "link": str,  # nvmid 추출용
                "is_shopping_exposed": bool,
                ...
            },
            ...
        ]
    
    참고: https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경 변수가 필요합니다.")
    
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
    
    # HTTP 헤더 설정 (네이버 오픈 API 문서 참고)
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    # 스마트 스토어에서 조회 한 rank - 순위
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
    
    try:
        # API 요청
        response = requests.get(API_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
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
# 오픈마켓 URL로 네이버 순위 조회 기능
# ============================================================================

def extract_product_id_from_marketplace_url(marketplace_url: str) -> Dict:
    """
    오픈마켓 URL에서 마켓플레이스 타입과 상품 ID 추출 (일반 쇼핑몰 지원 추가)
    
    Args:
        marketplace_url: 오픈마켓 상품 URL
            누카
            https://nooka.co.kr/product/detail.html?product_no=60&cate_no=77&display_group=1

            롯데온
            https://www.lotteon.com/p/product/LO2532029028?sitmNo=LO2532029028_2532029029&ch_no=100065&ch_dtl_no=1000030

            쿠팡
            https://www.coupang.com/vp/products/8989686766?

            오늘의 집
            https://store.ohou.se/goods/3679724?

            이마트
            https://emart.ssg.com/item/itemView.ssg?itemId=1000716250779&siteNo=6001

            G마켓
            https://item.gmarket.co.kr/Item?goodscode=4254268378

            이마트
            https://emart.ssg.com/item/itemView.ssg?itemId=1000716250779

    
    Returns:
        {
            "marketplace": str,  # "coupang", "auction", "11st", "gmarket", "general"
            "product_id": str,   # 추출한 상품 ID (일반 쇼핑몰의 경우 도메인)
            "domain": str,       # 도메인 (일반 쇼핑몰의 경우)
            "normalized_url": str,  # 정규화된 URL (매칭용)
            "error": str or None
        }
    """
    result = {
        "marketplace": None,
        "product_id": None,
        "domain": None,
        "normalized_url": None,
        "error": None
    }
    
    url_lower = marketplace_url.lower()
    
    # 쿠팡 (네이버 리다이렉트 링크 또는 직접 링크)
    if "link.coupang.com" in url_lower or "coupang.com" in url_lower:
        # itemId 파라미터 추출 (우선순위 1)
        item_id_match = re.search(r'itemId=(\d+)', marketplace_url)
        # products/(\d+) 패턴 추출 (우선순위 2)
        product_id_match = re.search(r'coupang\.com/vp/products/(\d+)', marketplace_url)
        
        if item_id_match:
            result["marketplace"] = "coupang"
            result["product_id"] = item_id_match.group(1)  # itemId 사용
            result["normalized_url"] = marketplace_url
        elif product_id_match:
            result["marketplace"] = "coupang"
            result["product_id"] = product_id_match.group(1)  # products ID 사용
            result["normalized_url"] = marketplace_url
        else:
            result["error"] = "쿠팡 URL에서 상품 ID를 추출할 수 없습니다"
        return result
    
    # 옥션
    if "auction.co.kr" in url_lower:
        match = re.search(r'[?&]itemno=([A-Z0-9]+)', marketplace_url, re.IGNORECASE)
        if match:
            result["marketplace"] = "auction"
            result["product_id"] = match.group(1)
            result["normalized_url"] = marketplace_url
        else:
            result["error"] = "옥션 URL에서 itemno를 추출할 수 없습니다"
        return result
    
    # 11번가
    if "11st.co.kr" in url_lower:
        match = re.search(r'11st\.co\.kr/products/(\d+)', marketplace_url, re.IGNORECASE)
        if match:
            result["marketplace"] = "11st"
            result["product_id"] = match.group(1)
            result["normalized_url"] = marketplace_url
        else:
            result["error"] = "11번가 URL에서 상품 ID를 추출할 수 없습니다"
        return result
    
    # G마켓
    if "gmarket.co.kr" in url_lower:
        match = re.search(r'[?&]goodscode=(\d+)', marketplace_url)
        if not match:
            match = re.search(r'item-no=(\d+)', marketplace_url)
        if match:
            result["marketplace"] = "gmarket"
            result["product_id"] = match.group(1)
            result["normalized_url"] = marketplace_url
        else:
            result["error"] = "G마켓 URL에서 상품 ID를 추출할 수 없습니다"
        return result
    
    # 일반 쇼핑몰 (오늘의집, 롯데ON, 자사몰 등)
    # URL에서 도메인 및 상품 ID 추출 (도메인별 패턴 적용)
    try:
        parsed = urlparse(marketplace_url)
        domain = parsed.netloc.lower()
        
        # www. 제거
        if domain.startswith('www.'):
            domain = domain[4:]
        
        result["marketplace"] = "general"
        result["domain"] = domain
        
        # 도메인별 상품 ID 추출 패턴
        product_id_extracted = None
        
        # 롯데온: /p/product/LO2532029028
        if "lotteon.com" in domain:
            match = re.search(r'/p/product/([A-Z0-9]+)', marketplace_url, re.IGNORECASE)
            if match:
                product_id_extracted = match.group(1)
        
        # 오늘의집: /goods/3679724
        elif "ohou.se" in domain or "store.ohou.se" in domain:
            match = re.search(r'/goods/(\d+)', marketplace_url)
            if match:
                product_id_extracted = match.group(1)
        
        # 이마트몰(SSG): itemId=1000716250779
        elif "ssg.com" in domain or "emart.ssg.com" in domain:
            match = re.search(r'itemId=(\d+)', marketplace_url)
            if match:
                product_id_extracted = match.group(1)
        
        if product_id_extracted:
            result["product_id"] = product_id_extracted
        else:
            result["product_id"] = domain  # 상품 ID가 없으면 도메인 사용
        
        result["normalized_url"] = marketplace_url
        return result
    except Exception as e:
        result["error"] = f"URL 파싱 실패: {str(e)}"
        return result


def match_marketplace_url_in_naver_link(
    marketplace_url: str,
    naver_link: str,
    marketplace_info: Dict,
    mall_name: str = None
) -> bool:
    """
    네이버 API 응답의 link와 오픈마켓 URL 매칭 (일반 쇼핑몰 지원 추가)
    
    Args:
        marketplace_url: 사용자가 제공한 오픈마켓 URL
        naver_link: 네이버 API 응답의 link 필드
        marketplace_info: extract_product_id_from_marketplace_url의 결과
        mall_name: 네이버 API 응답의 mallName 필드 (선택)
    
    Returns:
        매칭 여부 (bool)
    """
    marketplace = marketplace_info.get("marketplace")
    product_id = marketplace_info.get("product_id")
    domain = marketplace_info.get("domain")
    
    if not marketplace:
        return False
    
    naver_link_lower = naver_link.lower()
    
    # 쿠팡: itemId 또는 products ID로 매칭
    if marketplace == "coupang":
        # 네이버 link에서 itemId 추출 (우선순위 1)
        item_id_match = re.search(r'itemId=(\d+)', naver_link)
        if item_id_match:
            naver_item_id = item_id_match.group(1)
            if naver_item_id == product_id:
                return True
        
        # 네이버 link에서 products/(\d+) 추출 (우선순위 2)
        product_id_match = re.search(r'coupang\.com/vp/products/(\d+)', naver_link)
        if product_id_match:
            naver_product_id = product_id_match.group(1)
            if naver_product_id == product_id:
                return True
        
        # 둘 다 매칭되지 않으면 False
        return False
    
    # 옥션: itemno 파라미터로 매칭
    if marketplace == "auction":
        match = re.search(r'itemno=([A-Z0-9]+)', naver_link, re.IGNORECASE)
        if match:
            naver_itemno = match.group(1)
            return naver_itemno.upper() == product_id.upper()
        return False
    
    # 11번가: products/{id} 패턴으로 매칭
    if marketplace == "11st":
        match = re.search(r'11st\.co\.kr/products/(\d+)', naver_link, re.IGNORECASE)
        if match:
            naver_product_id = match.group(1)
            return naver_product_id == product_id
        return False
    
    # G마켓: goodscode 또는 item-no 파라미터로 매칭
    if marketplace == "gmarket":
        match = re.search(r'goodscode=(\d+)', naver_link)
        if not match:
            match = re.search(r'item-no=(\d+)', naver_link)
        if match:
            naver_goodscode = match.group(1)
            return naver_goodscode == product_id
        return False
    
    # 일반 쇼핑몰: 도메인 및 상품 ID 기반 매칭 (도메인별 패턴 적용)
    if marketplace == "general" and domain:
        # 네이버 link에서 도메인 추출
        try:
            parsed_naver = urlparse(naver_link)
            naver_domain = parsed_naver.netloc.lower()
            
            # www. 제거
            if naver_domain.startswith('www.'):
                naver_domain = naver_domain[4:]
            
            # 도메인 매칭
            domain_matched = (domain in naver_domain or naver_domain in domain) or (domain in naver_link_lower)
            
            if not domain_matched:
                return False
            
            # 상품 ID가 도메인이 아닌 경우 (상품 ID가 추출된 경우) 상품 ID도 확인
            if product_id and product_id != domain:
                naver_product_id = None
                
                # 도메인별 상품 ID 추출 패턴
                # 롯데온: /p/product/LO2532029028
                if "lotteon.com" in domain:
                    match = re.search(r'/p/product/([A-Z0-9]+)', naver_link, re.IGNORECASE)
                    if match:
                        naver_product_id = match.group(1)
                
                # 오늘의집: /goods/3679724
                elif "ohou.se" in domain or "store.ohou.se" in domain:
                    match = re.search(r'/goods/(\d+)', naver_link)
                    if match:
                        naver_product_id = match.group(1)
                
                # 이마트몰(SSG): itemId=1000716250779
                elif "ssg.com" in domain or "emart.ssg.com" in domain:
                    match = re.search(r'itemId=(\d+)', naver_link)
                    if match:
                        naver_product_id = match.group(1)
                
                # 상품 ID 매칭
                if naver_product_id:
                    if naver_product_id.upper() == product_id.upper():  # 대소문자 무시
                        return True
                    else:
                        return False  # 도메인은 같지만 상품 ID가 다름
                else:
                    # 네이버 link에 상품 ID가 없으면 도메인만으로 매칭 (하지만 상품 ID가 있는 경우는 실패)
                    return False
            
            # 상품 ID가 없거나 도메인과 같은 경우 도메인만으로 매칭
            return True
                
        except Exception as e:
            logger.debug(f"도메인 매칭 중 오류: {e}")
            return False
    
    return False


def get_shopping_rank_with_ad_flag_copy(
    keyword: str,
    marketplace_url: str,
    display: int = 100,
    max_pages: int = 10
) -> Dict:
    """
    메인 키워드와 오픈마켓 URL을 받아서 네이버 순위 조회 (테스트용)
    
    처리 로직:
    1. 네이버 쇼핑 검색 API를 키워드로 호출하여 검색 결과를 받아옵니다.
    2. API 응답 결과에서 제공된 marketplace_url과 일치하는 링크를 찾습니다.
    3. 링크가 일치하는 경우, 해당 API 응답에서 productId를 확인합니다.
    4. 매칭된 상품의 상품명(product_name) 및 순위(rank)를 추출하여 반환합니다.
    
    주의: URL에서 상품 ID를 추출하는 것이 아니라, API 응답에서 링크 일치 여부를 확인한 후
    해당 상품의 productId를 API 응답에서 확인합니다.
    
    Args:
        keyword: 검색 키워드 (예: "게이밍의자")
        marketplace_url: 오픈마켓 상품 URL
            - 쿠팡: https://link.coupang.com/re/PCSNAVERPCSDP?itemId=24613356330&...
            - 옥션: https://itempage3.auction.co.kr/DetailView.aspx?itemno=E832249308
            - 11번가: https://www.11st.co.kr/products/7844692722
            - G마켓: https://item.gmarket.co.kr/Item?goodscode=4254268378
            - 오늘의집: https://store.ohou.se/goods/3679724?...
            - 롯데온: https://www.lotteon.com/p/product/LO2532029028?...
        display: 한 번에 표시할 검색 결과 개수 (기본값: 100, 최댓값: 100)
        max_pages: 최대 검색할 페이지 수 (기본값: 10, 최대 1000개 결과)
    
    Returns:
        {
            "success": bool,              # 매칭 성공 여부
            "marketplace": str,           # 마켓플레이스 타입 ("coupang", "auction", "11st", "gmarket", "general")
            "product_id": str,            # 추출한 상품 ID (매칭용, API에서 확인한 productId와는 다를 수 있음)
            "rank": int or None,          # 네이버 쇼핑 검색 결과에서의 순위
            "product_name": str or None,  # API 응답에서 추출한 상품명
            "mall_name": str or None,     # 쇼핑몰명
            "price": str or None,         # 가격
            "productId": str or None,     # API 응답에서 확인한 productId (네이버 상품 ID)
            "marketplace_url": str,       # 테스트에 사용된 원본 오픈마켓 URL
            "matched_link": str or None,  # 매칭된 네이버 API 응답의 link
            "error": str or None          # 오류 메시지
        }
    """
    result = {
        "success": False,
        "marketplace": None,
        "product_id": None,
        "domain": None,  # 일반 쇼핑몰의 경우 도메인
        "rank": None,
        "product_name": None,
        "mall_name": None,
        "price": None,
        "productId": None,
        "marketplace_url": marketplace_url,  # 테스트에 사용된 원본 오픈마켓 URL
        "matched_link": None,  # 매칭된 네이버 API 응답의 link
        "error": None
    }
    
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        result["error"] = "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경 변수가 필요합니다."
        return result
    
    try:
        # 1. 오픈마켓 URL에서 정보 추출
        marketplace_info = extract_product_id_from_marketplace_url(marketplace_url)
        if marketplace_info.get("error"):
            result["error"] = marketplace_info["error"]
            return result
        
        result["marketplace"] = marketplace_info["marketplace"]
        result["product_id"] = marketplace_info["product_id"]
        if marketplace_info.get("domain"):
            result["domain"] = marketplace_info["domain"]
        
        logger.info(
            f"오픈마켓 URL 분석: {result['marketplace']}, "
            f"상품ID: {result['product_id']}, "
            f"도메인: {marketplace_info.get('domain', 'N/A')}, 키워드: {keyword}"
        )
        
        # 2. 네이버 쇼핑 검색 API로 검색 (최대 1000개)
        logger.info(f"키워드 '{keyword}'로 순위 조회 시작 (최대 {max_pages}페이지)")
        
        for page in range(1, max_pages + 1):
            start = (page - 1) * display + 1  # 1, 101, 201, ...
            
            try:
                # 네이버 오픈 API로 검색
                api_results = get_shopping_rank_with_ad_flag(
                    keyword,
                    display=display,
                    start=start,
                    filter=None
                )
                
                if not api_results:
                    logger.debug(f"페이지 {page}: 결과 없음, 검색 중단")
                    break
                
                logger.debug(f"페이지 {page} 검색 완료: {len(api_results)}개 결과 (start={start})")
                
                # 3. 검색 결과에서 오픈마켓 URL 매칭
                for item in api_results:
                    naver_link = item.get("link", "")
                    mall_name = item.get("mall_name", "")
                    
                    # link와 오픈마켓 URL 매칭
                    if match_marketplace_url_in_naver_link(
                        marketplace_url,
                        naver_link,
                        marketplace_info,
                        mall_name=mall_name
                    ):
                        # 매칭 성공
                        result["success"] = True
                        result["rank"] = item.get("rank")
                        result["product_name"] = item.get("product_name", "")
                        result["mall_name"] = item.get("mall_name", "")
                        result["price"] = item.get("price", "")
                        result["productId"] = item.get("productId", "")
                        result["matched_link"] = naver_link  # 매칭된 링크 저장
                        
                        logger.info(
                            f"매칭 성공: {result['marketplace']} 상품ID={result['product_id']}, "
                            f"순위={result['rank']}, 쇼핑몰={result['mall_name']}, "
                            f"상품명={result['product_name']}, productId={result['productId']}, "
                            f"matched_link={naver_link}"
                        )
                        return result
                
                # 마지막 페이지면 중단
                if len(api_results) < display:
                    logger.debug(f"페이지 {page}: 마지막 페이지 (결과 {len(api_results)}개 < {display}개)")
                    break
                
                # API 호출 간격
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"페이지 {page} 검색 중 오류: {e}", exc_info=True)
                break
        
        # 매칭 실패 (테스트 URL은 항상 포함하여 반환)
        result["error"] = (
            f"네이버 쇼핑 검색 결과에서 {result['marketplace']} 상품ID {result['product_id']}를 "
            f"찾을 수 없습니다. (키워드: {keyword})"
        )
        logger.warning(
            f"매칭 실패: {result['marketplace']} 상품ID={result['product_id']}, 키워드={keyword}, "
            f"테스트 URL={result['marketplace_url']}"
        )
        # 매칭 실패 시에도 테스트 URL은 포함하여 반환
        return result
        
    except Exception as e:
        logger.error(f"순위 조회 중 오류: {e}", exc_info=True)
        result["error"] = str(e)
        return result


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




# ============================================================================
# API로 키워드의 순위를 조회
# ============================================================================

def get_api_rank_by_keyword(keyword: str, nvmid: str) -> Optional[int]:
    """
    네이버 오픈 API로 키워드의 순위 조회
    
    Args:
        keyword: 검색 키워드
        nvmid: 찾을 상품의 nvmid
    
    Returns:
        int or None: 순위 (없으면 None)
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경 변수가 필요합니다.")
    
    try:
        # 네이버 오픈 API로 검색 (최대 100개까지)
        api_results = get_shopping_rank_with_ad_flag(keyword, display=100, filter=None)
        
        # nvmid 매칭하여 순위 찾기
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
                logger.debug(f"nvmid 매칭 성공: productId={product_id}, link_nvmid={nvmid_from_link}, target={target_nvmid}, rank={rank}")
                return rank
        
        logger.debug(f"API 순위 조회 실패: keyword='{keyword}', nvmid='{nvmid}' (검색 결과에서 nvmid 매칭 실패)")
        return None
        
    except Exception as e:
        logger.error(f"API 순위 조회 중 오류: keyword='{keyword}', error={e}", exc_info=True)
        return None


# ============================================================================
# 통합 메서드: URL 타입 자동 감지 및 순위 조회
# ============================================================================

def get_rank_by_keyword_and_url(keyword: str, url: str) -> Dict:
    """
    키워드와 URL을 받아서 자동으로 타입을 확인하고 순위를 조회합니다.
    
    Args:
        keyword: 검색 키워드
        url: 스마트스토어 URL 또는 쇼핑 URL
            - 스마트스토어: https://smartstore.naver.com/loneque/products/6516355636
            - 쇼핑: https://search.shopping.naver.com/catalog/10639139232
    
    Returns:
        dict: {
            "success": bool,
            "url_type": str,  # "smartstore" or "shopping"
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
            # 스마트스토어 또는 브랜드 스토어 URL에서 product_id 추출
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
            # 쇼핑 URL에서 nvmid 추출
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
        logger.info(f"키워드 '{keyword}'로 순위 조회 시작 (최대 {max_pages}페이지, {max_pages * display}개 결과)")
        
        for page in range(1, max_pages + 1):
            start = (page - 1) * 100 + 1  # 1, 101, 201, 301, ...
            
            try:
                # 네이버 오픈 API로 검색
                api_results = get_shopping_rank_with_ad_flag(
                    keyword, 
                    display=display, 
                    start=start, 
                    filter=None
                )
                
                if not api_results:
                    logger.debug(f"페이지 {page}: 결과 없음, 검색 중단")
                    break
                
                logger.debug(f"페이지 {page} 검색 완료: {len(api_results)}개 결과 (start={start})")
                
                # 3. URL 타입에 따라 매칭 방식 결정
                if url_type == "smartstore":
                    # product_id 다이렉트 매칭
                    target_id = product_id
                    for item in api_results:
                        product_id_from_api = str(item.get("productId", "")).strip()
                        
                        # link URL에서 product_id 추출 시도
                        link = item.get("link", "")
                        product_id_from_link = None
                        
                        if link:
                            # link에서 product_id 패턴 찾기
                            link_patterns = [
                                r'/products/(\d+)',  # /products/숫자
                            ]
                            
                            for pattern in link_patterns:
                                match = re.search(pattern, link, re.IGNORECASE)
                                if match:
                                    product_id_from_link = match.group(1)
                                    break
                        
                        # product_id 매칭 (productId 또는 link에서 추출한 값)
                        if (product_id_from_api and product_id_from_api == target_id) or \
                           (product_id_from_link and product_id_from_link == target_id):
                            result["success"] = True
                            result["rank"] = item.get("rank")
                            result["product_name"] = item.get("product_name", "")
                            
                            # api_productId가 실제로는 nvmid이므로 이를 사용
                            # link에서 nvmid 추출 시도 (없으면 api_productId 사용)
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
                            result["link"] = link  # 디버깅용
                            
                            logger.info(f"product_id 매칭 성공: api_productId={product_id_from_api} (nvmid), link_productId={product_id_from_link} (product_id), target={target_id}, rank={result['rank']}, nvmid={nvmid} (페이지 {page})")
                            return result
                
                elif url_type == "shopping":
                    # nvmid 링크 매칭
                    target_nvmid = nvmid
                    if page == 1:
                        logger.info(f"쇼핑 URL nvmid 매칭 시작: target_nvmid={target_nvmid}, 검색 결과 수={len(api_results)}")
                    
                    for idx, item in enumerate(api_results, 1):
                        # 방법 1: productId가 nvmid일 수 있음
                        product_id = str(item.get("productId", "")).strip()
                        
                        # 방법 2: link URL에서 nvmid 추출
                        link = item.get("link", "")
                        nvmid_from_link = None
                        
                        if link:
                            patterns = [
                                r'nv_mid[=_](\d+)',
                                r'nvmid[=_](\d+)',
                                r'nv-mid[=_](\d+)',
                                r'/catalog/(\d+)',
                                r'catalog/(\d+)',  # 추가 패턴
                            ]
                            
                            for pattern in patterns:
                                match = re.search(pattern, link, re.IGNORECASE)
                                if match:
                                    nvmid_from_link = match.group(1)
                                    break
                        
                        # 디버깅 로그 (첫 페이지의 처음 5개만)
                        if page == 1 and idx <= 5:
                            logger.debug(f"매칭 시도 [{idx}]: productId={product_id}, link={link[:100]}, link_nvmid={nvmid_from_link}, target={target_nvmid}")
                        
                        # nvmid 매칭
                        if (product_id and product_id == target_nvmid) or \
                           (nvmid_from_link and nvmid_from_link == target_nvmid):
                            result["success"] = True
                            result["rank"] = item.get("rank")
                            result["product_name"] = item.get("product_name", "")
                            result["nvmid"] = nvmid  # nvmid 명시적으로 설정
                            logger.info(f"nvmid 매칭 성공: productId={product_id}, link_nvmid={nvmid_from_link}, target={target_nvmid}, rank={result['rank']}, product_name={result['product_name']} (페이지 {page})")
                            return result
                
                # 마지막 페이지면 중단
                if len(api_results) < display:
                    logger.debug(f"페이지 {page}: 마지막 페이지 (결과 {len(api_results)}개 < {display}개)")
                    break
                
                # API 호출 간격 (너무 빠르면 제한될 수 있음)
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"페이지 {page} 검색 중 오류: {e}", exc_info=True)
                break
        
        # 매칭 실패
        if url_type == "shopping":
            logger.warning(f"nvmid 매칭 실패: target_nvmid={nvmid}, 검색 결과에서 매칭되는 상품을 찾을 수 없습니다. (최대 {max_pages}페이지 검색)")
        result["error"] = f"검색 결과에서 매칭되는 상품을 찾을 수 없습니다. (최대 {max_pages}페이지 검색)"
        logger.warning(f"매칭 실패: keyword='{keyword}', url='{url}'")
        return result
        
    except Exception as e:
        result["error"] = f"순위 조회 중 오류: {str(e)}"
        logger.error(result["error"], exc_info=True)
        return result


def get_price_comparison_rank(keyword: str, product_id_or_nvmid: str) -> Optional[int]:
    """
    가격비교 순위를 조회합니다 (productId = nvmid로 매칭)
    
    Args:
        keyword: 검색 키워드
        product_id_or_nvmid: product_id 또는 nvmid (둘 다 동일하게 처리)
    
    Returns:
        순위 (int) 또는 None
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경 변수가 필요합니다.")
    
    try:
        api_results = get_shopping_rank_with_ad_flag(keyword, display=100, filter=None)
        target_id = str(product_id_or_nvmid).strip()
        
        for item in api_results:
            # productId로 다이렉트 매칭 (= nvmid로 매칭)
            product_id = str(item.get("productId", "")).strip()
            
            if product_id == target_id:
                rank = item.get("rank")
                logger.info(f"가격비교 순위 매칭 성공: id={target_id}, rank={rank}")
                return rank
        
        logger.debug(f"가격비교 순위 매칭 실패: keyword='{keyword}', id='{product_id_or_nvmid}'")
        return None
        
    except Exception as e:
        logger.error(f"가격비교 순위 조회 중 오류: keyword='{keyword}', id='{product_id_or_nvmid}', error={e}", exc_info=True)
        return None


def update_single_advertisement_rank(ad_id: int, db_session=None, store_url: Optional[str] = None, shopping_url: Optional[str] = None):
    """
    단일 광고의 순위와 상품명을 업데이트하는 함수
    광고 수정 시 호출됨
    
    Args:
        ad_id: 광고 ID
        db_session: SQLAlchemy 세션 (None이면 새로 생성)
        store_url: Optional 스마트스토어 URL
            - 예: https://smartstore.naver.com/loneque/products/6516355636
        shopping_url: Optional 쇼핑 검색 URL (가격비교 URL)
            - 예: https://search.shopping.naver.com/catalog/10639139232
            - 제공되면 해당 URL로 rank와 product_name 업데이트
    
    Returns:
        dict: {"rank": int or None, "product_name": str or None}
    """
    # 환경 변수 확인
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 설정되지 않아 순위 조회를 건너뜁니다.")
        return {"rank": None, "product_name": None}
    
    # DB 세션 처리 (순환 import 방지를 위해 함수 내부에서 import)
    should_close = False
    if db_session is None:

        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        from database import SessionLocal
        db = SessionLocal()
        should_close = True
    else:
        db = db_session
    
    # 모델 import (순환 import 방지를 위해 함수 내부에서 import)
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    from models import AdvertisementsAdmin
    
    try:
        # 광고 조회
        ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
        
        if not ad:
            logger.warning(f"Ad ID {ad_id}를 찾을 수 없습니다.")
            return {"rank": None, "product_name": None}
        
        # store_url 또는 shopping_url이 제공된 경우
        logger.info(f"Ad ID {ad_id}: URL 체크 - store_url={store_url}, shopping_url={shopping_url}")
        
        # store_url과 shopping_url이 모두 None이거나 빈 문자열인 경우
        store_url_empty = not store_url or (isinstance(store_url, str) and store_url.strip() == "")
        shopping_url_empty = not shopping_url or (isinstance(shopping_url, str) and shopping_url.strip() == "")
        
        if store_url_empty and shopping_url_empty:
            # 둘 다 없으면 rank, product_name, product_mid, price_comparison_mid를 NULL로 설정
            ad.rank = None
            ad.product_name = None
            ad.product_mid = None
            ad.price_comparison_mid = None
            logger.info(f"✓ Ad ID {ad_id}: store_url과 shopping_url이 모두 없어서 rank, product_name, product_mid, price_comparison_mid를 NULL로 설정")
            db.flush()
            if should_close:
                db.commit()
            return {"rank": None, "product_name": None}
        
        if store_url or shopping_url:
            # main_keyword는 프론트엔드에서 필수로 처리되므로 없을 경우는 없음
            # 하지만 안전성을 위해 체크는 유지
            if not ad.main_keyword:
                logger.warning(f"Ad ID {ad_id}: URL이 제공되었지만 main_keyword가 없습니다.")
                if should_close:
                    db.commit()
                return {"rank": None, "product_name": None}
            
            # store_url에서 product_id 추출 로직 제거 (방어로직 철회)
            # smartstore URL의 nvmid는 순위 조회에서만 가져와서 product_mid에 저장
            # product_id와 nvmid는 다른 값이므로 URL에서 추출한 product_id를 저장하지 않음
            
            # store_url이 없으면 product_mid를 None으로 설정
            if not store_url:
                ad.product_mid = None
                logger.info(f"✓ Ad ID {ad_id}: store_url이 없어 product_mid를 NULL로 설정")
            
            # shopping_url에서 nvmid 추출 (매칭 성공 여부와 관계없이)
            if shopping_url and shopping_url.strip():
                match = re.search(r'catalog/(\d+)', shopping_url)
                if match:
                    nvmid_from_url = match.group(1)
                    ad.price_comparison_mid = nvmid_from_url
                    logger.info(f"✓ Ad ID {ad_id}: shopping_url에서 price_comparison_mid 업데이트: {nvmid_from_url}")
            else:
                # shopping_url이 비어있으면 price_comparison_mid를 빈칸으로 업데이트
                ad.price_comparison_mid = None
                logger.info(f"✓ Ad ID {ad_id}: shopping_url이 비어있어 price_comparison_mid를 NULL로 설정")
            
            # 순위 조회 (shopping_url 우선, 둘 다 있으면 둘 다 처리)
            rank = None
            product_name = None
            shopping_rank = None
            shopping_product_name = None
            shopping_nvmid = None
            store_rank = None
            store_product_name = None
            store_nvmid = None
            
            # shopping_url 우선 시도
            if shopping_url:
                logger.info(f"Ad ID {ad_id}: shopping URL로 순위 조회 시도: {shopping_url}")
                result = get_rank_by_keyword_and_url(ad.main_keyword, shopping_url)
                
                if result.get("success"):
                    shopping_rank = result.get("rank")
                    shopping_product_name = result.get("product_name")
                    shopping_nvmid = result.get("nvmid")
                    
                    # SQLAlchemy NULL 처리: 빈 문자열이나 None을 명시적으로 None으로 변환
                    if shopping_product_name is not None and not shopping_product_name.strip():
                        shopping_product_name = None
                    
                    logger.info(f"Ad ID {ad_id}: shopping URL 매칭 성공 - rank={shopping_rank}, product_name={shopping_product_name}, nvmid={shopping_nvmid}")
                    
                    # nvmid가 있으면 price_comparison_mid 업데이트, 없으면 NULL로 설정
                    if shopping_nvmid:
                        ad.price_comparison_mid = shopping_nvmid
                        logger.info(f"✓ Ad ID {ad_id}: price_comparison_mid 업데이트 완료 (shopping URL 매칭): {shopping_nvmid}")
                    # else:
                    #     # 매칭 성공했지만 nvmid가 없으면 NULL로 설정
                    #     ad.price_comparison_mid = None
                    #     logger.info(f"✓ Ad ID {ad_id}: shopping URL 매칭 성공했지만 nvmid가 없어 price_comparison_mid를 NULL로 설정")
                # else:
                #     # 매칭 실패 시 price_comparison_mid를 NULL로 설정
                #     ad.price_comparison_mid = None
                #     error = result.get("error", "알 수 없는 오류")
                #     logger.warning(f"Ad ID {ad_id}: shopping URL로 순위 조회 실패: {error}, price_comparison_mid를 NULL로 설정")
            
            # store_url 처리 (shopping_url 매칭 여부와 관계없이)
            if store_url:
                logger.info(f"Ad ID {ad_id}: store URL로 순위 조회 시도: {store_url}")
                
                # smartstore 또는 brandstore URL인지 확인
                is_smartstore_url = False
                if store_url:
                    url_lower = store_url.lower()
                    if "smartstore.naver.com" in url_lower or "brand.naver.com" in url_lower:
                        is_smartstore_url = True
                
                result = get_rank_by_keyword_and_url(ad.main_keyword, store_url)
                
                if result.get("success"):
                    store_rank = result.get("rank")
                    store_product_name = result.get("product_name")
                    store_nvmid = result.get("nvmid")
                    
                    # SQLAlchemy NULL 처리: 빈 문자열이나 None을 명시적으로 None으로 변환
                    if store_product_name is not None and not store_product_name.strip():
                        store_product_name = None
                    
                    logger.info(f"Ad ID {ad_id}: store URL 매칭 성공 - rank={store_rank}, product_name={store_product_name}, nvmid={store_nvmid}")
                    
                    # nvmid가 있으면 product_mid 업데이트
                    if store_nvmid:
                        ad.product_mid = store_nvmid
                        logger.info(f"✓ Ad ID {ad_id}: product_mid 업데이트 완료 (store URL 매칭): {store_nvmid}")
                    else:
                        # 매칭 성공했지만 nvmid가 없으면 product_url_copy.py를 통해서 nvmid와 product_name 추출 시도
                        if is_smartstore_url:
                            try:
                                from api.routers.product_url_copy import get_nvmid_from_url
                                product_nvmid, product_name_from_url = get_nvmid_from_url(store_url, verbose=False)
                                if product_nvmid:
                                    ad.product_mid = product_nvmid
                                    logger.info(f"✓ Ad ID {ad_id}: product_url_copy.py를 통해 product_mid 업데이트 완료: {product_nvmid}")
                                else:
                                    ad.product_mid = None
                                    logger.info(f"✓ Ad ID {ad_id}: 매칭된 nvmid가 없어 product_mid를 NULL로 설정")
                                
                                # product_name도 업데이트 (있으면)
                                if product_name_from_url and product_name_from_url.strip():
                                    store_product_name = product_name_from_url.strip()
                                    logger.info(f"✓ Ad ID {ad_id}: product_url_copy.py를 통해 product_name 업데이트 완료: {product_name_from_url[:50]}...")
                            except Exception as e:
                                logger.warning(f"Ad ID {ad_id}: product_url_copy.py 호출 중 오류: {str(e)}")
                                ad.product_mid = None
                        else:
                            ad.product_mid = None
                            logger.info(f"✓ Ad ID {ad_id}: 매칭된 nvmid가 없어 product_mid를 NULL로 설정")
                else:
                    # 매칭 실패 시 product_url_copy.py를 통해서 nvmid와 product_name 추출 시도 (smartstore/brandstore URL인 경우만)
                    if is_smartstore_url:
                        try:
                            from api.routers.product_url_copy import get_nvmid_from_url
                            product_nvmid, product_name_from_url = get_nvmid_from_url(store_url, verbose=False)
                            if product_nvmid:
                                ad.product_mid = product_nvmid
                                logger.info(f"✓ Ad ID {ad_id}: 순위 조회 실패, product_url_copy.py를 통해 product_mid 업데이트 완료: {product_nvmid}")
                            else:
                                ad.product_mid = None
                                logger.warning(f"Ad ID {ad_id}: 순위 조회 실패 및 product_url_copy.py로도 nvmid 추출 실패, product_mid를 NULL로 설정")
                            
                            # product_name도 업데이트 (있으면)
                            if product_name_from_url and product_name_from_url.strip():
                                store_product_name = product_name_from_url.strip()
                                logger.info(f"✓ Ad ID {ad_id}: product_url_copy.py를 통해 product_name 업데이트 완료: {product_name_from_url[:50]}...")
                        except Exception as e:
                            logger.warning(f"Ad ID {ad_id}: product_url_copy.py 호출 중 오류: {str(e)}, product_mid를 NULL로 설정")
                            ad.product_mid = None
                    else:
                        # 매칭 실패 시에도 nvmid가 없으면 null 처리
                        ad.product_mid = None
                        logger.info(f"✓ Ad ID {ad_id}: 매칭 실패로 product_mid를 NULL로 설정")
            
            # 순위 및 상품명 결정 (shopping_url 우선, 둘 다 매칭되면 shopping_url의 순위 사용)
            if shopping_rank is not None:
                # shopping_url 매칭 성공 시 shopping_url의 순위 사용
                rank = shopping_rank
                # 상품명은 shopping_product_name 우선, 없으면 store_product_name 사용
                if shopping_product_name and shopping_product_name.strip():
                    product_name = shopping_product_name.strip()
                elif store_product_name and store_product_name.strip():
                    product_name = store_product_name.strip()
                else:
                    # 둘 다 없으면 None (크롤링 실패)
                    product_name = None
                logger.info(f"✓ Ad ID {ad_id}: shopping URL 순위 사용: {rank}")
            elif store_rank is not None:
                # shopping_url 매칭 실패 시 store_url의 순위 사용
                rank = store_rank
                if store_product_name and store_product_name.strip():
                    product_name = store_product_name.strip()
                else:
                    # 상품명이 없으면 None (크롤링 실패)
                    product_name = None
                logger.info(f"✓ Ad ID {ad_id}: store URL 순위 사용: {rank}")
            elif not store_url or store_url.strip() == "":
                # store_url이 없고 shopping_url도 매칭 실패한 경우
                rank = None
                product_name = None
                logger.info(f"✓ Ad ID {ad_id}: store_url이 없고 shopping_url 매칭도 실패하여 rank와 product_name을 NULL로 설정")
            else:
                # 둘 다 조회 실패 시 rank는 None이지만, store_product_name은 product_url_copy.py를 통해 업데이트되었을 수 있음
                rank = None
                # store_product_name이 있으면 사용, 없으면 None
                if store_product_name and store_product_name.strip():
                    product_name = store_product_name.strip()
                    logger.info(f"✓ Ad ID {ad_id}: 순위 조회 실패했지만 product_name은 product_url_copy.py를 통해 업데이트됨: {product_name[:50]}...")
                else:
                    product_name = None
                    logger.info(f"✓ Ad ID {ad_id}: 모든 URL 조회 실패로 rank와 product_name을 NULL로 설정")
            
            # rank와 product_name 업데이트 (SQLAlchemy NULL 처리: None이면 NULL로 저장)
            ad.rank = rank
            # product_name이 빈 문자열이거나 None이면 명시적으로 None으로 설정 (SQLAlchemy에서 NULL로 저장)
            if product_name is not None and not product_name.strip():
                product_name = None
            ad.product_name = product_name  # None이면 SQLAlchemy가 NULL로 저장
            if product_name:
                logger.info(f"✓ Ad ID {ad_id}: 상품명 업데이트 완료: {product_name}")
            else:
                logger.info(f"✓ Ad ID {ad_id}: 상품명을 NULL로 업데이트 완료 (크롤링 실패)")
            
            # 변경사항을 DB에 반영 (외부 세션에서 commit하기 전에 flush)
            db.flush()
            
            if should_close:
                db.commit()
            
            if rank:
                logger.info(f"✓ Ad ID {ad_id}: 순위 {rank} 업데이트 완료")
            else:
                logger.info(f"✗ Ad ID {ad_id}: 순위 없음 (NULL로 설정)")
            
            return {"rank": rank, "product_name": product_name}
            
            # 모든 URL 매칭 실패
            # 매칭 실패해도 product_mid와 price_comparison_mid는 이미 위에서 업데이트됨
            # 순위 조회 실패 시 명시적으로 rank를 None으로 설정
            # 상품명은 조회되면 사용하고, 없으면 기존 값 유지
            ad.rank = None
            logger.info(f"Ad ID {ad_id}: 순위 조회 실패로 rank를 NULL로 설정")
            
            if should_close:
                db.commit()
            
            logger.warning(f"Ad ID {ad_id}: 모든 URL로 순위 조회 실패")
            return {"rank": None, "product_name": None}
        
        # URL이 없는 경우 - 기존 로직 (main_keyword와 product_mid 사용)
        if not ad.main_keyword or not ad.product_mid:
            logger.info(f"Ad ID {ad_id}: main_keyword 또는 product_mid가 없어 순위 조회를 건너뜁니다.")
            return {"rank": None, "product_name": None}
        
        main_keyword = ad.main_keyword.strip()
        product_mid = ad.product_mid.strip()
        
        logger.info(f"Ad ID {ad_id}: '{main_keyword}' (product_mid: {product_mid}) 순위 및 상품명 조회 시작")
        
        # 네이버 오픈 API로 검색 (최대 100개까지)
        api_results = get_shopping_rank_with_ad_flag(main_keyword, display=100, filter=None)
        
        # product_mid 매칭하여 순위와 상품명 찾기
        target_product_mid = str(product_mid).strip()
        rank = None
        product_name = None
        
        for item in api_results:
            # 네이버 오픈 API 응답에서 productId 추출
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
            
            # product_mid 매칭 (productId 또는 link에서 추출한 값과 비교)
            if (product_id and product_id == target_product_mid) or \
               (nvmid_from_link and nvmid_from_link == target_product_mid):
                rank = item.get("rank")
                product_name = item.get("product_name", "") or item.get("title", "")  # 상품명 추출
                logger.info(f"product_mid 매칭 성공: productId={product_id}, link_nvmid={nvmid_from_link}, target={target_product_mid}, rank={rank}, product_name={product_name}")
                break
        
        # rank와 product_name 업데이트
        ad.rank = rank
        if product_name:
            ad.product_name = product_name.strip()
            logger.info(f"✓ Ad ID {ad_id}: 상품명 업데이트 완료: {product_name}")
        
        if should_close:
            db.commit()
        
        if rank:
            logger.info(f"✓ Ad ID {ad_id}: 순위 {rank} (업데이트 완료)")
        else:
            logger.info(f"✗ Ad ID {ad_id}: 순위 없음 (NULL로 설정)")
        
        return {"rank": rank, "product_name": product_name}
        
    except Exception as e:
        logger.error(f"Ad ID {ad_id} 순위 및 상품명 조회 중 오류: {e}", exc_info=True)
        if should_close:
            db.rollback()
        return {"rank": None, "product_name": None}
    finally:
        if should_close:
            db.close()


def update_advertisement_admin_ranks():
    """
    AdvertisementsAdmin 테이블을 순회하면서 각 advertisement의 main_keyword와 product_mid를 이용해
    순위를 조회한 후 rank 컬럼을 업데이트
    """
    # 환경 변수 확인
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        missing = []
        if not NAVER_CLIENT_ID:
            missing.append("NAVER_CLIENT_ID")
        if not NAVER_CLIENT_SECRET:
            missing.append("NAVER_CLIENT_SECRET")
        
        error_msg = (
            f"다음 환경 변수가 설정되지 않았습니다: {', '.join(missing)}\n"
            f"환경 변수 설정 방법:\n"
            f"  Windows: set NAVER_CLIENT_ID=your_client_id\n"
            f"           set NAVER_CLIENT_SECRET=your_client_secret\n"
            f"  Linux/Mac: export NAVER_CLIENT_ID=your_client_id\n"
            f"            export NAVER_CLIENT_SECRET=your_client_secret\n"
            f"  또는 .env 파일 사용 (python-dotenv 필요)"
        )
        raise ValueError(error_msg)
    
    # DB 관련 import
    import sys
    import os
    # 현재 파일의 경로에서 프로젝트 루트로 이동
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    sys.path.insert(0, project_root)
    
    from database import SessionLocal
    from models import AdvertisementsAdmin
    
    db = SessionLocal()
    # 쇼핑 검색 - 순위 업데이트
    # 통합 검색 - 순위 업데이트
    try:
        # AdvertisementsAdmin 테이블에서 main_keyword와 product_mid가 있는 모든 광고 조회
        advertisements = db.query(AdvertisementsAdmin).filter(
            AdvertisementsAdmin.main_keyword.isnot(None),
            AdvertisementsAdmin.main_keyword != '',
            AdvertisementsAdmin.product_mid.isnot(None),
            AdvertisementsAdmin.product_mid != ''
        ).all()
        
        logger.info(f"총 {len(advertisements)}개 광고의 순위를 조회합니다.")
        
        updated_count = 0
        not_found_count = 0
        error_count = 0
        
        for idx, ad in enumerate(advertisements, 1):
            try:
                main_keyword = ad.main_keyword.strip()
                product_mid = ad.product_mid.strip()
                
                logger.info(f"[{idx}/{len(advertisements)}] Ad ID {ad.ad_id}: '{main_keyword}' (product_mid: {product_mid})")
                
                # API로 순위 조회
                rank = get_api_rank_by_keyword(main_keyword, product_mid)
                
                # rank 컬럼 업데이트 (순위가 없으면 None으로 설정)
                ad.rank = rank
                
                if rank:
                    logger.info(f"✓ Ad ID {ad.ad_id}: 순위 {rank} (업데이트 완료)")
                    updated_count += 1
                else:
                    logger.info(f"✗ Ad ID {ad.ad_id}: 순위 없음 (NULL로 설정)")
                    not_found_count += 1
                
                # API 호출 간격 (너무 빠르면 제한될 수 있음)
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Ad ID {ad.ad_id} 순위 조회 중 오류: {e}", exc_info=True)
                # 오류 발생 시 rank를 None으로 설정
                ad.rank = None
                error_count += 1
        
        # 변경사항 커밋
        db.commit()
        logger.info(f"✓ 순위 업데이트 완료: 총 {len(advertisements)}개 광고 중 {updated_count}개 순위 발견, {not_found_count}개 순위 없음, {error_count}개 오류")
        
    except Exception as e:
        db.rollback()
        logger.error(f"순위 업데이트 중 오류: {e}", exc_info=True)
        raise
    finally:
        db.close()


def main(keyword: str, nvmid: str, product_id: int = None, main_keyword: str = None):
    """
    메인 함수: keyword_search_v3.py의 조합 로직을 사용하여 키워드 조합 생성 후
    API로 순위만 조회하고 결과를 테이블에 저장
    
    Args:
        keyword: 검색할 키워드 (띄어쓰기로 구분)
        nvmid: 찾을 상품의 nvmid
        product_id: 상품 ID (테이블 저장용, Optional)
        main_keyword: 메인 키워드 (테이블 저장용, Optional)
    """
    # 환경 변수 확인
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        missing = []
        if not NAVER_CLIENT_ID:
            missing.append("NAVER_CLIENT_ID")
        if not NAVER_CLIENT_SECRET:
            missing.append("NAVER_CLIENT_SECRET")
        
        error_msg = (
            f"다음 환경 변수가 설정되지 않았습니다: {', '.join(missing)}\n"
            f"환경 변수 설정 방법:\n"
            f"  Windows: set NAVER_CLIENT_ID=your_client_id\n"
            f"           set NAVER_CLIENT_SECRET=your_client_secret\n"
            f"  Linux/Mac: export NAVER_CLIENT_ID=your_client_id\n"
            f"            export NAVER_CLIENT_SECRET=your_client_secret\n"
            f"  또는 .env 파일 사용 (python-dotenv 필요)"
        )
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
    
    logger.info(f"총 {len(keyword_combinations)}개 조합으로 검색 시작")
    
    results = []
    
    try:
        # 각 조합 키워드로 네이버 오픈 API로 순위만 조회
        for idx, combo_keyword in enumerate(keyword_combinations, 1):
            logger.info(f"[{idx}/{len(keyword_combinations)}] 키워드 검색: '{combo_keyword}'")
            
            try:
                # API로 순위 조회
                rank = get_api_rank_by_keyword(combo_keyword, nvmid)
                
                result = {
                    "keyword": combo_keyword,
                    "rank": rank,  # API에서 조회한 순위
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
                })
        
        # 결과를 테이블에 저장 (product_id와 main_keyword가 제공된 경우)
        if product_id and main_keyword:
            try:
                # DB 관련 import
                import sys
                import os
                current_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(os.path.dirname(current_dir))
                sys.path.insert(0, project_root)
                
                from database import SessionLocal
                # KeywordSearch 모델이 없으면 주석 처리
                # from models import KeywordSearch
                
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
        logger.error(f"검색 중 오류: {e}", exc_info=True)
    
    return results


# 테스트 코드는 제거 (광고 수정 시 실행되는 함수이므로 print 문 제거)
# if __name__ == "__main__": 블록은 제거됨

if __name__ == "__main__":
    # 환경 변수 확인
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("=" * 70)
        print("환경 변수 오류")
        print("=" * 70)
        missing = []
        if not NAVER_CLIENT_ID:
            missing.append("NAVER_CLIENT_ID")
        if not NAVER_CLIENT_SECRET:
            missing.append("NAVER_CLIENT_SECRET")
        print(f"다음 환경 변수가 설정되지 않았습니다: {', '.join(missing)}")
        print("\n.env 파일에 다음을 추가하세요:")
        print("NAVER_CLIENT_ID=your_client_id")
        print("NAVER_CLIENT_SECRET=your_client_secret")
        sys.exit(1)
    
    # 테스트 실행
    print("=" * 70)
    print("오픈마켓 URL로 네이버 순위 조회 테스트")
    print("=" * 70)
    
    # 일반 쇼핑몰 테스트 (자사몰)
    print("\n[테스트 5] 자사몰 (누카) 링크")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://nooka.co.kr/product/detail.html?product_no=60&cate_no=77&display_group=1",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  도메인: {result.get('domain', 'N/A')}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
        # 상품명 일치 확인
        expected_name = "누카 커스텀체어 G900-MS 6D 컴퓨터의자 사무용 사무실 학생 메쉬 게이밍 책상의자"
        actual_name = result['product_name']
        # HTML 태그 제거
        import re
        clean_actual = re.sub(r'<[^>]+>', '', actual_name)
        if expected_name in clean_actual or clean_actual in expected_name:
            print(f"  [상품명 일치 확인] 예상: {expected_name}")
            print(f"  [상품명 일치 확인] 실제: {clean_actual}")
            print(f"  [상품명 일치 확인] 일치 여부: 일치")
        else:
            print(f"  [상품명 일치 확인] 예상: {expected_name}")
            print(f"  [상품명 일치 확인] 실제: {clean_actual}")
            print(f"  [상품명 일치 확인] 일치 여부: 불일치")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    # 일반 쇼핑몰 테스트 (오늘의집)
    print("\n[테스트 6] 오늘의집 링크")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://store.ohou.se/goods/3679724?",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  도메인: {result.get('domain', 'N/A')}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    # 제공된 테스트 데이터로 추가 테스트
    print("\n" + "=" * 70)
    print("제공된 테스트 데이터로 추가 테스트")
    print("=" * 70)
    
    # 롯데온 테스트
    print("\n[테스트 7] 롯데온 링크")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://www.lotteon.com/p/product/LO2532029028?sitmNo=LO2532029028_2532029029&ch_no=100065&ch_dtl_no=1000030",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  도메인: {result.get('domain', 'N/A')}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    # 쿠팡 테스트 (제공된 데이터)
    print("\n[테스트 8] 쿠팡 링크 (제공된 데이터)")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://www.coupang.com/vp/products/8989686766?",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  상품ID: {result['product_id']}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    # 오늘의집 테스트 (제공된 데이터)
    print("\n[테스트 9] 오늘의집 링크 (제공된 데이터)")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://store.ohou.se/goods/3679724?",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  도메인: {result.get('domain', 'N/A')}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    # 이마트몰(SSG) 테스트
    print("\n[테스트 10] 이마트몰(SSG) 링크")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://emart.ssg.com/item/itemView.ssg?itemId=1000716250779&siteNo=6001",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  도메인: {result.get('domain', 'N/A')}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    # G마켓 테스트
    print("\n[테스트 11] G마켓 링크")
    print("-" * 70)
    result = get_shopping_rank_with_ad_flag_copy(
        keyword="게이밍의자",
        marketplace_url="https://item.gmarket.co.kr/Item?goodscode=4254268378",
        max_pages=10  # 최대 1000개 결과 검색
    )
    
    if result["success"]:
        print(f"[SUCCESS] 매칭 성공!")
        print(f"  테스트 링크: {result['marketplace_url']}")
        print(f"  상품ID: {result['product_id']}")
        print(f"  순위: {result['rank']}")
        print(f"  상품명: {result['product_name']}")
        print(f"  쇼핑몰: {result['mall_name']}")
        print(f"  가격: {result['price']}원")
        print(f"  productId: {result['productId']}")
    else:
        print(f"[FAILED] 매칭 실패: {result['error']}")
    
    print("\n" + "=" * 70)
    print("테스트 완료")
    print("=" * 70)
