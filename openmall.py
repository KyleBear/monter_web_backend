import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from urllib.parse import urlparse
import logging
import time
import re

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 오픈마켓별 URL과 XPath 매핑
OPENMALL_XPATH_MAPPING = {
    'coupang.com': '/html/body/div[3]/div/div[1]/main/div[1]/div[4]/div[1]/div[4]/div/h1/span',
    'auction.co.kr': '/html/body/div[9]/div[2]/div[2]/form/div[3]/div[1]/h1',
    '11st.co.kr': '/html/body/div[2]/div[2]/div/div[1]/div[2]/div/div[1]/div[2]/div[2]/div[2]/h1',
    'gmarket.co.kr': '/html/head/title'
}


def get_domain_from_url(url: str) -> str:
    """URL에서 도메인 추출"""
    parsed = urlparse(url)
    domain = parsed.netloc
    # www. 제거
    if domain.startswith('www.'):
        domain = domain[4:]
    return domain


def get_xpath_for_url(url: str) -> str:
    """URL에 맞는 XPath 반환"""
    domain = get_domain_from_url(url)
    
    # 도메인 매칭
    for key_domain, xpath in OPENMALL_XPATH_MAPPING.items():
        if key_domain in domain:
            return xpath
    
    # 매칭되지 않으면 None 반환
    return None


def get_product_name_by_selenium(url: str, xpath: str = None, timeout: int = 15) -> str:
    """
    Selenium을 사용하여 XPath로 상품명 추출
    
    Args:
        url: 크롤링할 URL
        xpath: XPath (None이면 URL에서 자동으로 찾음)
        timeout: 대기 시간 (초)
    
    Returns:
        str: 상품명 또는 None
    """
    if xpath is None:
        xpath = get_xpath_for_url(url)
        if xpath is None:
            logger.error(f"URL에 맞는 XPath를 찾을 수 없습니다: {url}")
            return None
    
    # Chrome 옵션 설정
    chrome_options = Options()
    # chrome_options.add_argument('--headless')  # 헤드리스 모드
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
# 
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    chrome_options.add_argument('--disable-web-security')
    chrome_options.add_argument('--allow-running-insecure-content')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    # chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    # 추가: 쿠키 및 로컬 스토리지 설정
    chrome_options.add_argument('--disable-web-security')
    chrome_options.add_argument('--allow-running-insecure-content')

    # 봇감지 회피 스크립트
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        
        # 봇 감지 회피 스크립트 추가 (driver 생성 후)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        
        driver.get(url)
        
        # 페이지 로딩 대기
        time.sleep(3)
        
        # 쿠팡의 경우 여러 패턴을 순차적으로 시도
        domain = get_domain_from_url(url)
        if 'coupang.com' in domain:
            # 쿠팡 대체 선택자 패턴들 (우선순위 순)
            coupang_selectors = [
                # 1번째 패턴
                (By.XPATH, '/html/body/div[3]/div/div[1]/main/div[1]/div[4]/div[1]/div[4]/div[1]/h1/span'),  # div[1] 있음
                # 2번째 패턴
                (By.CSS_SELECTOR, 'h1.prod-buy-header__title'),
                # 3번째 패턴
                (By.XPATH, '/html/body/div[3]/div/div[1]/main/div[1]/div[4]/div[1]/div[4]/div/h1/span'),  # div[1] 없이
                
                # 기타 CSS 선택자 시도
                (By.CSS_SELECTOR, 'h1[class*="title"]'),
                (By.CSS_SELECTOR, 'main h1'),
                (By.CSS_SELECTOR, '#__next h1'),
                
                # 기타 XPath 패턴들
                (By.XPATH, '//h1[@class="prod-buy-header__title"]'),
                (By.XPATH, '//h1[contains(@class, "title")]'),
                (By.XPATH, '//main//h1'),
                (By.XPATH, '//*[@id="__next"]//h1'),
                (By.XPATH, '//div[contains(@class, "prod-buy")]//h1'),
                (By.XPATH, '//h1//span'),
                (By.XPATH, '//h1'),
            ]
            
            for by, selector in coupang_selectors:
                try:
                    wait = WebDriverWait(driver, 5)
                    element = wait.until(EC.presence_of_element_located((by, selector)))
                    product_name = element.text.strip()
                    if product_name:
                        logger.info(f"✓ 상품명 추출 성공 (선택자: {by}={selector}): {product_name}")
                        return product_name
                except (TimeoutException, NoSuchElementException):
                    logger.debug(f"선택자 실패: {by}={selector}")
                    continue
            
            logger.error(f"✗ 모든 쿠팡 선택자 패턴 실패")
            # 마지막 시도: 페이지에서 h1 태그 찾기
            try:
                h1_elements = driver.find_elements(By.TAG_NAME, 'h1')
                for h1 in h1_elements:
                    text = h1.text.strip()
                    if text and len(text) > 5:  # 의미있는 텍스트인지 확인
                        logger.info(f"✓ h1 태그에서 상품명 추출: {text}")
                        return text
            except:
                pass
            return None
        
        # 11번가의 경우 여러 패턴을 순차적으로 시도
        elif '11st.co.kr' in domain:
            # 11번가 대체 XPath 패턴들 (우선순위 순)
            elevenst_xpaths = [
                # 1번째 패턴 (현재 코드)
                '/html/body/div[2]/div[2]/div/div[1]/div[2]/div/div[1]/div[2]/div[2]/div[2]/h1',
                # 2번째 패턴 (사용자 제공 1)
                '/html/body/div[2]/div[3]/div/div[1]/div[2]/div/div[1]/div[2]/div[2]/div[2]/h1',
                # 3번째 패턴 (사용자 제공 2)
                '/html/body/div[2]/div[3]/div/div[1]/div[2]/div/div[1]/div[2]/div[2]/div[3]/h1',
            ]
            
            for xpath_pattern in elevenst_xpaths:
                try:
                    wait = WebDriverWait(driver, 5)
                    element = wait.until(EC.presence_of_element_located((By.XPATH, xpath_pattern)))
                    product_name = element.text.strip()
                    if product_name:
                        logger.info(f"✓ 11번가 상품명 추출 성공 (XPath: {xpath_pattern}): {product_name}")
                        return product_name
                except (TimeoutException, NoSuchElementException):
                    logger.debug(f"11번가 XPath 실패: {xpath_pattern}")
                    continue
            
            logger.error(f"✗ 모든 11번가 XPath 패턴 실패")
            # 마지막 시도: 페이지에서 h1 태그 찾기
            try:
                h1_elements = driver.find_elements(By.TAG_NAME, 'h1')
                for h1 in h1_elements:
                    text = h1.text.strip()
                    if text and len(text) > 5:  # 의미있는 텍스트인지 확인
                        logger.info(f"✓ 11번가 h1 태그에서 상품명 추출: {text}")
                        return text
            except:
                pass
            return None
        
        # 다른 마켓플레이스는 기존 로직 사용
        wait = WebDriverWait(driver, timeout)
        element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        
        # 텍스트 추출
        # title 태그인 경우 textContent 또는 innerText 사용 (G마켓)
        if xpath.endswith('/title'):
            product_name = element.get_attribute('textContent')
            if not product_name:
                product_name = element.get_attribute('innerText')
            if not product_name:
                product_name = driver.title  # 폴백: driver.title 사용
        else:
            product_name = element.text.strip()
        
        logger.info(f"✓ 상품명 추출 성공: {product_name}")
        return product_name
        
    except TimeoutException:
        logger.error(f"✗ 타임아웃: XPath를 찾을 수 없습니다 - {xpath}")
        return None
    except NoSuchElementException:
        logger.error(f"✗ 요소를 찾을 수 없습니다 - {xpath}")
        return None
    except Exception as e:
        logger.error(f"✗ 오류 발생: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def get_product_name(url: str) -> str:
    """
    URL을 받아서 상품명을 추출하는 메인 함수
    
    Args:
        url: 크롤링할 URL
    
    Returns:
        str: 상품명 또는 None
    """
    logger.info(f"상품명 추출 시작: {url}")
    
    # URL에 맞는 XPath 찾기
    xpath = get_xpath_for_url(url)
    
    if xpath is None:
        logger.error(f"지원하지 않는 URL입니다: {url}")
        return None
    
    logger.info(f"사용할 XPath: {xpath}")
    
    # Selenium으로 상품명 추출
    product_name = get_product_name_by_selenium(url, xpath)
    
    return product_name


def match_marketplace_url_in_naver_link(marketplace: str, product_id: str, naver_link: str) -> bool:
    """
    네이버 쇼핑 API 응답의 link와 오픈마켓 URL을 매칭
    
    Args:
        marketplace: 마켓플레이스 타입 ("coupang", "auction", "11st", "gmarket")
        product_id: 오픈마켓에서 추출한 상품 ID
        naver_link: 네이버 쇼핑 API 응답의 link 필드
    
    Returns:
        bool: 매칭 성공 여부
    """
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
        
    return False


# 테스트 코드
if __name__ == "__main__":
    # 테스트 URL들
    test_urls = [
        "https://www.coupang.com/vp/products/321776051?itemId=9103929922",
        "https://itempage3.auction.co.kr/DetailView.aspx?itemno=E832249308",
        "https://item.gmarket.co.kr/Item?goodscode=4254268378",
        "https://www.11st.co.kr/products/6229184203?"
        # 11번가 URL은 검색 결과 페이지이므로 실제 상품 페이지 URL이 필요합니다
    ]
    
    print("=" * 70)
    print("오픈마켓 상품명 크롤링 테스트")
    print("=" * 70)
    
    for url in test_urls:
        print(f"\nURL: {url}")
        product_name = get_product_name(url)
        
        if product_name:
            print(f"✓ 상품명: {product_name}")
        else:
            print("✗ 상품명 추출 실패")
        
        print("-" * 70)
