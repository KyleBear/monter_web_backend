"""
product_url에서 태그 추출 스크립트 (브라우저 표시 모드)
- 쿠키 없이 자연스러운 브라우징 패턴으로 차단 우회
- 브라우저 창을 직접 보여줌 (headless=False)
- BeautifulSoup으로 태그 추출
- Smartstore mall에 가서 상품명으로 검색 후 상품 클릭
"""
import logging
import sys
import os
import random
import time
import tempfile
import shutil
from typing import Optional
from bs4 import BeautifulSoup
from lxml import etree
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse, quote, unquote

# 프로젝트 루트를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def extract_store_name_from_url(product_url: str) -> Optional[str]:
    """
    URL에서 쇼핑몰 이름 추출
    
    Args:
        product_url: 상품 URL
    
    Returns:
        str: 쇼핑몰 이름 또는 None
    """
    try:
        parsed = urlparse(product_url)
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) > 0:
            return path_parts[0]  # mymedisolu
        return None
    except Exception:
        return None


def extract_product_name_from_url(product_url: str) -> Optional[str]:
    """
    URL에서 상품명 추출 (products/ 뒤의 숫자 제외)
    또는 상품명을 직접 입력받아 사용
    
    Args:
        product_url: 상품 URL
    
    Returns:
        str: 상품명 또는 None
    """
    # 실제로는 상품명을 별도로 입력받거나, 상품 페이지에서 추출해야 함
    # 여기서는 None을 반환하고, main 함수에서 입력받도록 함
    return None


def _setup_chrome_driver_visible():
    """
    브라우저 창을 표시하는 Chrome WebDriver 생성 (차단 우회 옵션 포함)
    
    Returns:
        tuple: (driver, user_data_dir)
    """
    user_data_dir = tempfile.mkdtemp(prefix='chrome_data_visible_')
    logger.info(f"[Chrome 설정] User Data Directory: {user_data_dir}")
    
    options = Options()
    
    # User Data Directory 사용
    options.add_argument(f'--user-data-dir={user_data_dir}')
    
    # 봇 감지 회피 옵션
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # 기본 옵션
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    # Headless 모드 해제 (브라우저 창 표시)
    logger.info("[Chrome 설정] 브라우저 창 표시 모드 (headless=False)")
    
    driver = webdriver.Chrome(options=options)
    
    # navigator.webdriver 제거
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        }
    )
    
    driver.implicitly_wait(5)
    
    return driver, user_data_dir


def extract_tag_from_product_url(product_url: str, product_name: Optional[str] = None) -> Optional[str]:
    """
    product_url에서 태그 추출 (자연스러운 브라우징 패턴)
    - Smartstore mall에 가서 상품명으로 검색 후 상품 클릭
    
    Args:
        product_url: 크롤링할 상품 URL
        product_name: 검색에 사용할 상품명 (없으면 URL에서 추출 시도)
    
    Returns:
        str: 태그 텍스트 또는 None
    """
    driver = None
    user_data_dir = None
    
    try:
        logger.info(f"[태그 추출] 시작: {product_url}")
        
        # Chrome 드라이버 생성 (브라우저 창 표시)
        driver, user_data_dir = _setup_chrome_driver_visible()
        
        # 쇼핑몰 이름 추출
        store_name = extract_store_name_from_url(product_url)
        if not store_name:
            logger.error("[브라우징] 쇼핑몰 이름을 추출할 수 없습니다.")
            return None
        
        
        # 상품명 필수 체크
        if not product_name:
            logger.error("[브라우징] 상품명이 필요합니다. 상품명을 입력해주세요.")
            return None
        logger.info("[브라우징] 자연스러운 접근 패턴 시작...")
        
        # 1단계: 스마트스토어 메인 페이지 방문
        logger.info("[브라우징] 1단계: 스마트스토어 메인 페이지 방문...")
        driver.get("https://smartstore.naver.com")
        time.sleep(random.uniform(2, 3))
        
        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 400);")
        time.sleep(random.uniform(0.5, 1.0))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1.0))
        
        # 2단계: 쇼핑몰 메인 페이지 방문
        logger.info(f"[브라우징] 2단계: 쇼핑몰 메인 페이지 방문: {store_name}")
        store_main_url = f"https://smartstore.naver.com/{store_name}"
        driver.get(store_main_url)
        time.sleep(random.uniform(2, 3))
        
        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(random.uniform(0.5, 1.0))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1.0))
        
        # 3단계: 상품명으로 검색
        logger.info(f"[브라우징] 3단계: 상품명으로 검색: {product_name}")
        # URL 쿼리로 검색
        search_url = f"https://smartstore.naver.com/{store_name}/search?q={quote(product_name)}"
        logger.info(f"[브라우징] 검색 URL: {search_url}")
        driver.get(search_url)
        time.sleep(random.uniform(3, 5))

        # 페이지 로딩 대기
        wait = WebDriverWait(driver, 10)
        try:
            wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
        except:
            pass

        # 자연스러운 스크롤
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(1, 2))

        # 4단계: 첫 번째 상품 링크 클릭
        logger.info("[브라우징] 4단계: 첫 번째 상품 링크 클릭...")
        first_product_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[2]/div[3]/ul/li/div/div[2]/div/a'

        try:
            # XPath로 요소 찾기 및 클릭
            wait = WebDriverWait(driver, 10)
            first_product_link = wait.until(
                EC.element_to_be_clickable((By.XPATH, first_product_xpath))
            )
            
            # 요소가 보일 때까지 스크롤
            driver.execute_script("arguments[0].scrollIntoView(true);", first_product_link)
            time.sleep(random.uniform(0.5, 1.0))
            
            # 클릭
            first_product_link.click()
            logger.info("[브라우징] ✅ 첫 번째 상품 링크 클릭 완료")
            
            # 페이지 로딩 대기
            time.sleep(random.uniform(3, 5))
            wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
            time.sleep(random.uniform(2, 3))
            
            current_url = driver.current_url
            logger.info(f"[브라우징] 클릭 후 현재 URL: {current_url}")
            
        except Exception as e:
            logger.error(f"[브라우징] ❌ 첫 번째 상품 링크 클릭 실패: {e}")
            return None
        logger.info("[태그 추출] 페이지 스크롤하여 콘텐츠 로딩...")
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, 1500);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(1, 2))
        
        # 추가 대기 시간 (동적 콘텐츠 로딩 대기)
        time.sleep(random.uniform(3, 5))
        
        # 태그 추출
        logger.info("[태그 추출] 태그 추출 시작...")
        logger.info(f"[태그 추출] 현재 URL: {driver.current_url}")
        
        tag_value = None
        
        # 잘못된 텍스트 필터링 함수
        def is_valid_tag(text):
            if not text or not text.strip():
                return False
            text = text.strip()
            # 잘못된 텍스트 패턴 제외
            invalid_patterns = [
                '상품상세로 이동',
                '상품상세',
                '더보기',
                '보기',
                '이동',
                '상세',
                '링크',
                'click',
                'Click',
                'CLICK'
            ]
            for pattern in invalid_patterns:
                if pattern in text:
                    return False
            # 너무 짧거나 긴 텍스트 제외
            if len(text) < 2 or len(text) > 50:
                return False
            return True
        
        try:
            wait = WebDriverWait(driver, 10)

            # 방법 1: Selenium으로 직접 XPath 시도 (div[10], div[11] 둘 다 시도)
            tag_xpaths = [
                '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[10]/div/ul/li[1]/a',
                '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[11]/div/ul/li[1]/a',
            ]

            for tag_xpath in tag_xpaths:
                try:
                    logger.info(f"[태그 추출] Selenium XPath 시도: {tag_xpath}")
                    tag_element = wait.until(EC.presence_of_element_located((By.XPATH, tag_xpath)))
                    tag_text = tag_element.text.strip() if tag_element.text else ''
                    if tag_text and is_valid_tag(tag_text):
                        tag_value = tag_text
                        logger.info(f"[태그 추출] ✅ 태그 추출 성공 (Selenium XPath): {tag_value}")
                        break
                    elif tag_text:
                        logger.debug(f"[태그 추출] 잘못된 태그 필터링됨 (Selenium XPath): {tag_text}")
                except Exception as e:
                    logger.debug(f"[태그 추출] XPath '{tag_xpath}' 실패: {e}")
                    continue

            # 방법 2: data-shp-inventory="tag" 속성으로 찾기 (Selenium)
            if not tag_value:
                logger.info("[태그 추출] data-shp-inventory='tag' 속성으로 태그 찾기 (Selenium)...")
                try:
                    tag_elements = driver.find_elements(By.CSS_SELECTOR, 'a[data-shp-inventory="tag"]')
                    logger.info(f"[태그 추출] data-shp-inventory='tag' 요소 {len(tag_elements)}개 발견")
                    for element in tag_elements:
                        try:
                            tag_text = element.text.strip() if element.text else ''
                            if tag_text and is_valid_tag(tag_text):
                                tag_value = tag_text
                                logger.info(f"[태그 추출] ✅ 태그 추출 성공 (data-shp-inventory Selenium): {tag_value}")
                                break
                            elif tag_text:
                                logger.debug(f"[태그 추출] 잘못된 태그 필터링됨 (data-shp-inventory Selenium): {tag_text}")
                        except Exception as e:
                            logger.debug(f"[태그 추출] 요소 텍스트 추출 실패: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"[태그 추출] data-shp-inventory 속성 찾기 실패: {e}")

            # 방법 3: #INTRODUCE 내부의 ul > li > a 요소들 확인 (Selenium)
            if not tag_value:
                logger.info("[태그 추출] #INTRODUCE 내부 태그 찾기 시도 (Selenium)...")
                try:
                    introduce = wait.until(EC.presence_of_element_located((By.ID, 'INTRODUCE')))
                    # #INTRODUCE 내부의 모든 ul > li > a 요소 찾기
                    tag_links = introduce.find_elements(By.CSS_SELECTOR, 'ul li a')
                    logger.info(f"[태그 추출] #INTRODUCE 내부 링크 {len(tag_links)}개 발견")
                    for link in tag_links:
                        try:
                            tag_text = link.text.strip() if link.text else ''
                            if tag_text and is_valid_tag(tag_text):
                                tag_value = tag_text
                                logger.info(f"[태그 추출] ✅ 태그 추출 성공 (#INTRODUCE 내부 Selenium): {tag_value}")
                                break
                            elif tag_text:
                                logger.debug(f"[태그 추출] 잘못된 태그 필터링됨 (#INTRODUCE 내부 Selenium): {tag_text}")
                        except Exception as e:
                            logger.debug(f"[태그 추출] 링크 텍스트 추출 실패: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"[태그 추출] #INTRODUCE 요소 찾기 실패: {e}")

            # 가격 추출
            price_value = None
            try:
                price_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[2]/div[2]/fieldset/div[1]/div[2]/div/strong/span[2]'
                logger.info(f"[가격 추출] 가격 XPath 시도: {price_xpath}")
                price_element = wait.until(EC.presence_of_element_located((By.XPATH, price_xpath)))
                price_value = price_element.text.strip() if price_element.text else ''
                if price_value:
                    logger.info(f"[가격 추출] ✅ 가격 추출 성공: {price_value}")
                else:
                    logger.warning("[가격 추출] ⚠️ 가격을 찾을 수 없습니다.")
            except Exception as e:
                logger.warning(f"[가격 추출] 가격 추출 실패: {e}")

            if tag_value:
                logger.info(f"[태그 추출] ✅ 최종 태그: {tag_value}")
                if price_value:
                    logger.info(f"[가격 추출] ✅ 최종 가격: {price_value}")
                return tag_value
            else:
                logger.warning("[태그 추출] ⚠️ 태그를 찾을 수 없습니다.")
                return None
    
        
        except Exception as e:
            logger.error(f"[태그 추출] ❌ 태그 추출 중 오류 발생: {e}", exc_info=True)
            return None
    
    
    finally:
        if driver:
            logger.info("[태그 추출] 브라우저를 확인하실 수 있습니다.")
            logger.info("[태그 추출] 상품 페이지가 정상적으로 로드되었는지 확인해주세요.")
            logger.info("[태그 추출] 브라우저를 수동으로 닫으시거나, 60초 후 자동으로 닫힙니다.")
            time.sleep(60)  # 사용자가 브라우저를 확인할 시간 제공
            driver.quit()
            logger.info("[태그 추출] 브라우저 종료 완료")
        
        if user_data_dir and os.path.exists(user_data_dir):
            try:
                shutil.rmtree(user_data_dir)
                logger.info(f"[태그 추출] 임시 디렉토리 삭제 완료: {user_data_dir}")
            except Exception as e:
                logger.warning(f"[태그 추출] 임시 디렉토리 삭제 실패: {e}")


def main():
    """메인 함수"""
    logger.info("=" * 60)
    logger.info("product_url 태그 추출 스크립트 (브라우저 표시 모드)")
    logger.info("=" * 60)
    logger.info("")
    
    try:
        # product_url 입력
        if len(sys.argv) > 1:
            product_url_input = sys.argv[1].strip()
        else:
            product_url_input = input("태그를 추출할 product_url을 입력하세요: ").strip()
        
        if not product_url_input:
            logger.error("[오류] product_url을 입력해주세요.")
            sys.exit(1)
        
        # product_name 입력 (필수)
        product_name_input = None
        if len(sys.argv) > 2:
            product_name_input = sys.argv[2].strip()
        else:
            product_name_question = input("검색에 사용할 상품명을 입력하세요: ").strip()
            if product_name_question:
                product_name_input = product_name_question
        
        if not product_name_input:
            logger.error("[오류] 상품명을 입력해주세요.")
            sys.exit(1)
        
        logger.info("")
        logger.info(f"product_url={product_url_input}")
        logger.info(f"product_name={product_name_input}")
        logger.info("")
        
        # 태그 추출 실행
        tag = extract_tag_from_product_url(product_url_input, product_name_input)
        
        logger.info("")
        logger.info("=" * 60)
        if tag:
            logger.info(f"[성공] 태그 추출 완료: {tag}")
        else:
            logger.warning("[실패] 태그를 추출할 수 없습니다.")
        logger.info("=" * 60)
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("\n[중단] 사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
