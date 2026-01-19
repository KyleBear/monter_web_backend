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

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL별 XPath 매핑
URL_XPATH_MAPPING = {
    'rental-zon.com': '//*[@id="contents"]/div[3]/div[1]/div[2]/div[1]/h1',
    'hkoa1.com': '/html/body/div/div[5]/form/div[1]/section/strong',
    'funart.co.kr': '/html/head/title'
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
    for key_domain, xpath in URL_XPATH_MAPPING.items():
        if key_domain in domain:
            return xpath
    
    # 매칭되지 않으면 None 반환
    return None


def get_product_name_by_selenium(url: str, xpath: str = None, timeout: int = 10) -> str:
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
    chrome_options.add_argument('--headless')  # 헤드리스 모드
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        
        # 페이지 로딩 대기
        time.sleep(2)
        
        # XPath로 요소 찾기
        wait = WebDriverWait(driver, timeout)
        element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        
        # 텍스트 추출
        # title 태그인 경우 textContent 또는 innerText 사용
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


# 테스트 코드
if __name__ == "__main__":
    # 테스트 URL들
    test_urls = [
        "https://rental-zon.com/product/detail.html?product_no=27445",
        "http://hkoa1.com/m/shop/view.php?gs_id=537",
        "https://www.funart.co.kr/shop/shopdetail.html?branduid=10567668",
        "https://www.funart.co.kr/shop/shopdetail.html?branduid=8563"
    ]
    
    print("=" * 70)
    print("상품명 크롤링 테스트")
    print("=" * 70)
    
    for url in test_urls:
        print(f"\nURL: {url}")
        product_name = get_product_name(url)
        
        if product_name:
            print(f"✓ 상품명: {product_name}")
        else:
            print("✗ 상품명 추출 실패")
        
        print("-" * 70)
