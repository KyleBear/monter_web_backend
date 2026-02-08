"""
reward_rank 테이블의 태그와 가격 추출 스크립트 (DB 연동)
- reward_rank 테이블의 reward_id를 순회하면서 태그와 가격 업데이트
- 스토어명, 상품명을 DB에서 가져와서 크롤링
- product_name 우선, 없으면 keyword를 search_query로 사용
"""
import logging
import sys
import os
import random
import time
import tempfile
import shutil
import re
import asyncio
from typing import Optional, Tuple, List, Dict
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

# DB 관련 import
try:
    from database import SessionLocal
    from models import RewardRank
except ImportError:
    print("[오류] database 또는 models 모듈을 찾을 수 없습니다.")
    sys.exit(1)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def extract_store_name_from_product_url(product_url: str) -> Optional[str]:
    """
    product_url에서 스토어명 추출
    예: https://smartstore.naver.com/keyfinder/products/9612192197 -> keyfinder
    
    Args:
        product_url: 상품 URL
    
    Returns:
        str: 스토어명 또는 None
    """
    if not product_url:
        return None
    
    try:
        parsed = urlparse(product_url)
        path_parts = parsed.path.strip('/').split('/')
        
        # smartstore.naver.com/{store_name}/products/... 패턴
        if 'smartstore.naver.com' in parsed.netloc and len(path_parts) > 0:
            return path_parts[0]  # keyfinder
        
        return None
    except Exception as e:
        logger.error(f"[스토어명 추출 실패] product_url={product_url}, 오류: {e}")
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


def extract_tag_and_price_from_search_query(
    search_query: str,
    store_name: Optional[str] = None
) -> Tuple[Optional[str], Optional[int]]:
    """
    검색 쿼리로 첫 번째 제품을 찾아 태그와 가격 추출
    
    Args:
        search_query: 검색 쿼리 (product_name 또는 keyword)
        store_name: 스토어명 (선택사항, 있으면 해당 스토어에서 검색)
    
    Returns:
        tuple: (tag_text, price_value) - 태그 텍스트와 가격(정수) 또는 (None, None)
    """
    driver = None
    user_data_dir = None
    
    try:
        logger.info(f"[태그/가격 추출] 시작: 검색 쿼리={search_query}")
        if store_name:
            logger.info(f"[태그/가격 추출] 스토어명: {store_name}")
        
        # Chrome 드라이버 생성 (브라우저 창 표시)
        driver, user_data_dir = _setup_chrome_driver_visible()
        
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
        
        # 2단계: 검색 쿼리로 검색
        if store_name:
            # 특정 스토어에서 검색
            logger.info(f"[브라우징] 2단계: {store_name} 스토어 메인 페이지 방문...")
            store_main_url = f"https://smartstore.naver.com/{store_name}"
            driver.get(store_main_url)
            time.sleep(random.uniform(2, 3))
            
            # 자연스러운 스크롤
            driver.execute_script("window.scrollTo(0, 500);")
            time.sleep(random.uniform(0.5, 1.0))
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(random.uniform(0.5, 1.0))
            
            # 스토어 내 검색
            logger.info(f"[브라우징] 3단계: 스토어 내에서 검색 쿼리로 검색: {search_query}")
            search_url = f"https://smartstore.naver.com/{store_name}/search?q={quote(search_query)}"
        else:
            # 전체 스마트스토어에서 검색
            logger.info(f"[브라우징] 2단계: 검색 쿼리로 검색: {search_query}")
            search_url = f"https://smartstore.naver.com/search?q={quote(search_query)}"
        
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

        # 3단계: 첫 번째 상품 링크 클릭
        logger.info("[브라우징] 3단계: 첫 번째 상품 링크 클릭...")
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
            return None, None
        
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
        
        try:
            wait = WebDriverWait(driver, 10)

            # /html/head의 meta keywords에서 첫 번째 키워드 추출
            logger.info("[태그 추출] meta[name='keywords'] 찾기...")
            try:
                meta_keywords = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'meta[name="keywords"]')))
                logger.info("[태그 추출] ✅ meta[name='keywords'] 발견")
                
                # content 속성 가져오기
                keywords_content = meta_keywords.get_attribute('content')
                
                if keywords_content:
                    # 쉼표로 분리하고 첫 번째 키워드 추출
                    keywords_list = [k.strip() for k in keywords_content.split(',') if k.strip()]
                    if keywords_list:
                        tag_value = keywords_list[0]
                        logger.info(f"[태그 추출] ✅ 태그 추출 성공: {tag_value}")
                    else:
                        logger.warning("[태그 추출] ⚠️ keywords content가 비어있습니다.")
                else:
                    logger.warning("[태그 추출] ⚠️ meta keywords의 content 속성이 없습니다.")
                    
            except Exception as e:
                logger.warning(f"[태그 추출] meta keywords 탐색 실패: {e}")
                # 폴백: 기존 방식 (div.NAR95xKIue)
                logger.info("[태그 추출] 폴백: HTML 경로 기반 탐색 시도...")
                try:
                    div_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.NAR95xKIue')))
                    logger.info("[태그 추출] ✅ div.NAR95xKIue 발견")
                    
                    ul_element = div_element.find_element(By.CSS_SELECTOR, 'ul.lq1wDHp4iu')
                    logger.info("[태그 추출] ✅ ul.lq1wDHp4iu 발견")
                    
                    li_elements = ul_element.find_elements(By.CSS_SELECTOR, 'li.f_JzwGZdbu')
                    
                    if li_elements and len(li_elements) > 0:
                        first_li = li_elements[0]
                        a_element = first_li.find_element(By.TAG_NAME, 'a')
                        tag_text = a_element.text.strip() if a_element.text else ''
                        
                        if tag_text:
                            tag_text = tag_text.lstrip('#')
                            tag_value = tag_text
                            logger.info(f"[태그 추출] ✅ 태그 추출 성공 (폴백): {tag_value}")
                except Exception as e2:
                    logger.warning(f"[태그 추출] 폴백 방법도 실패: {e2}")
                    # 최종 폴백: data-shp-inventory="tag" 속성으로 찾기
                    logger.info("[태그 추출] 최종 폴백: data-shp-inventory='tag' 속성으로 태그 찾기...")
                    try:
                        tag_elements = driver.find_elements(By.CSS_SELECTOR, 'a[data-shp-inventory="tag"]')
                        if tag_elements and len(tag_elements) > 0:
                            tag_text = tag_elements[0].text.strip() if tag_elements[0].text else ''
                            if tag_text:
                                tag_text = tag_text.lstrip('#')
                                tag_value = tag_text
                                logger.info(f"[태그 추출] ✅ 태그 추출 성공 (최종 폴백): {tag_value}")
                    except Exception as e3:
                        logger.warning(f"[태그 추출] 최종 폴백 방법도 실패: {e3}")

            # 가격 추출 (meta property="kakao:commerce:price"에서 추출)
            price_value = None
            try:
                logger.info("[가격 추출] meta[property='kakao:commerce:price'] 찾기...")
                price_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'meta[property="kakao:commerce:price"]')))
                logger.info("[가격 추출] ✅ meta[property='kakao:commerce:price'] 발견")
                
                # meta 태그의 content 속성에서 가격 추출
                price_text = price_element.get_attribute('content') if price_element else ''
                
                if price_text:
                    # 쉼표 제거 후 숫자로 변환
                    price_text_clean = re.sub(r'[^\d]', '', price_text)
                    if price_text_clean:
                        price_value = int(price_text_clean)
                        logger.info(f"[가격 추출] ✅ 가격 추출 성공: {price_value}")
                    else:
                        logger.warning("[가격 추출] ⚠️ 가격 텍스트에서 숫자를 추출할 수 없습니다.")
                else:
                    logger.warning("[가격 추출] ⚠️ meta property의 content 속성이 없습니다.")
            except Exception as e:
                logger.warning(f"[가격 추출] 가격 추출 실패: {e}")

            if tag_value:
                logger.info(f"[태그 추출] ✅ 최종 태그: {tag_value}")
                if price_value:
                    logger.info(f"[가격 추출] ✅ 최종 가격: {price_value}")
                return tag_value, price_value
            else:
                logger.warning("[태그 추출] ⚠️ 태그를 찾을 수 없습니다.")
                return None, price_value
        
        except Exception as e:
            logger.error(f"[태그 추출] ❌ 태그 추출 중 오류 발생: {e}", exc_info=True)
            return None, None
    
    finally:
        if driver:
            logger.info("[태그 추출] 브라우저를 확인하실 수 있습니다.")
            logger.info("[태그 추출] 상품 페이지가 정상적으로 로드되었는지 확인해주세요.")
            logger.info("[태그 추출] 브라우저를 수동으로 닫으시거나, 10초 후 자동으로 닫힙니다.")
            time.sleep(4)  # 사용자가 브라우저를 확인할 시간 제공
            driver.quit()
            logger.info("[태그 추출] 브라우저 종료 완료")
        
        if user_data_dir and os.path.exists(user_data_dir):
            try:
                shutil.rmtree(user_data_dir)
                logger.info(f"[태그 추출] 임시 디렉토리 삭제 완료: {user_data_dir}")
            except Exception as e:
                logger.warning(f"[태그 추출] 임시 디렉토리 삭제 실패: {e}")


async def process_single_reward_rank(reward_rank: RewardRank, delay: float) -> Dict:
    """
    단일 reward_rank 레코드 처리 (비동기)
    
    Args:
        reward_rank: RewardRank 레코드
        delay: 대기 시간 (초)
    
    Returns:
        dict: 처리 결과
    """
    reward_id = reward_rank.reward_id
    result = {
        'reward_id': reward_id,
        'success': False,
        'updated': False,
        'error': None
    }
    
    try:
        # 검색 쿼리 결정 (product_name 우선, 없으면 keyword 사용)
        search_query = reward_rank.product_name or reward_rank.keyword
        if not search_query:
            result['error'] = 'product_name과 keyword가 모두 없습니다'
            logger.warning(f"[스킵] reward_id={reward_id}: {result['error']}")
            return result
        
        # store_name을 product_url에서 추출
        store_name = None
        if reward_rank.product_url:
            store_name = extract_store_name_from_product_url(reward_rank.product_url)
        
        # product_url에서 추출 실패 시 DB의 store_name 사용
        if not store_name:
            store_name = reward_rank.store_name
        
        logger.info(f"[처리 시작] reward_id={reward_id}, search_query={search_query}, store_name={store_name or '전체 스마트스토어'}")
        
        # 별도 스레드에서 동기 함수 실행 (Selenium은 동기 함수)
        loop = asyncio.get_event_loop()
        tag_value, price_value = await loop.run_in_executor(
            None,
            extract_tag_and_price_from_search_query,
            search_query,
            store_name
        )
        
        # DB 업데이트
        db = SessionLocal()
        try:
            # 레코드 다시 조회 (최신 상태)
            record = db.query(RewardRank).filter(RewardRank.reward_id == reward_id).first()
            if not record:
                result['error'] = '레코드를 찾을 수 없습니다'
                return result
            
            updated = False
            if tag_value:
                record.image_tag = tag_value
                updated = True
                logger.info(f"[DB 업데이트] reward_id={reward_id}: image_tag 업데이트: {tag_value}")
            
            if price_value is not None:
                record.price = price_value
                updated = True
                logger.info(f"[DB 업데이트] reward_id={reward_id}: price 업데이트: {price_value}")
            
            if updated:
                db.commit()
                logger.info(f"[DB 업데이트] ✅ reward_id={reward_id} 업데이트 완료")
                result['success'] = True
                result['updated'] = True
            else:
                logger.warning(f"[DB 업데이트] ⚠️ reward_id={reward_id}: 태그와 가격을 모두 추출하지 못했습니다.")
                result['success'] = True  # 크롤링은 성공했지만 업데이트할 데이터가 없음
                
        except Exception as e:
            db.rollback()
            result['error'] = str(e)
            logger.error(f"[오류] reward_id={reward_id} DB 업데이트 중 오류: {e}", exc_info=True)
        finally:
            db.close()
        
        # 대기 시간
        if delay > 0:
            await asyncio.sleep(delay)
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"[오류] reward_id={reward_id} 처리 중 오류: {e}", exc_info=True)
    
    return result


async def process_batch_parallel(reward_ranks: List[RewardRank], delay: float, max_workers: int = 4) -> Dict:
    """
    배치 단위로 병렬 처리 (4개 인스턴스)
    
    Args:
        reward_ranks: 처리할 레코드 리스트
        delay: 각 레코드 처리 후 대기 시간 (초)
        max_workers: 최대 병렬 작업 수 (기본값: 4)
    
    Returns:
        dict: 통계 정보
    """
    logger.info(f"[배치 처리] {len(reward_ranks)}개 레코드를 {max_workers}개 병렬 작업으로 처리")
    
    # 세마포어로 동시 실행 수 제한
    semaphore = asyncio.Semaphore(max_workers)
    
    async def process_with_semaphore(reward_rank):
        async with semaphore:
            return await process_single_reward_rank(reward_rank, delay)
    
    # 모든 작업을 병렬로 실행
    tasks = [process_with_semaphore(rank) for rank in reward_ranks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 결과 집계
    stats = {
        'total': len(reward_ranks),
        'success': 0,
        'updated': 0,
        'failed': 0
    }
    
    for result in results:
        if isinstance(result, Exception):
            stats['failed'] += 1
            logger.error(f"[예외 발생] {result}", exc_info=True)
        elif result.get('success'):
            stats['success'] += 1
            if result.get('updated'):
                stats['updated'] += 1
        else:
            stats['failed'] += 1
    
    return stats


async def update_reward_rank_tag_and_price_async(
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    delay: float = 5.0,
    max_workers: int = 4
):
    """
    reward_rank 테이블의 reward_id를 순회하면서 태그와 가격 업데이트 (비동기 병렬 처리)
    
    Args:
        start_id: 시작 reward_id (None이면 전체)
        end_id: 종료 reward_id (None이면 전체)
        delay: 각 레코드 처리 사이의 대기 시간 (초)
        max_workers: 최대 병렬 작업 수 (기본값: 4)
    """
    db = SessionLocal()
    try:
        # reward_rank 조회
        query = db.query(RewardRank)
        
        if start_id:
            query = query.filter(RewardRank.reward_id >= start_id)
        if end_id:
            query = query.filter(RewardRank.reward_id <= end_id)
        
        reward_ranks = query.all()
        total_count = len(reward_ranks)
        
        logger.info(f"[DB 조회] 총 {total_count}개의 reward_rank 레코드를 찾았습니다.")
        
        if total_count == 0:
            logger.warning("[DB 조회] 업데이트할 레코드가 없습니다.")
            return
        
        logger.info(f"[설정] 병렬 작업 수: {max_workers}개")
        logger.info(f"[설정] 레코드 간 대기 시간: {delay}초")
        logger.info("")
        
        # 병렬 처리 실행
        stats = await process_batch_parallel(reward_ranks, delay, max_workers)
        logger.info(f"[완료] 총 {stats['total']}개 중 성공: {stats['success']}개, 업데이트: {stats['updated']}개, 실패: {stats['failed']}개")
        
    except Exception as e:
        logger.error(f"[오류] DB 작업 중 오류 발생: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def update_reward_rank_tag_and_price(
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
    delay: float = 5.0,
    max_workers: int = 4
):
    """
    동기 래퍼 함수 (비동기 함수 호출)
    
    Args:
        start_id: 시작 reward_id (None이면 전체)
        end_id: 종료 reward_id (None이면 전체)
        delay: 각 레코드 처리 사이의 대기 시간 (초)
        max_workers: 최대 병렬 작업 수 (기본값: 4)
    """
    return asyncio.run(update_reward_rank_tag_and_price_async(
        start_id=start_id,
        end_id=end_id,
        delay=delay,
        max_workers=max_workers
    ))


def main():
    """메인 함수"""
    logger.info("reward_rank 태그 및 가격 업데이트 스크립트")
    
    try:
        # 명령줄 인자 파싱
        start_id = None
        end_id = None
        delay = 5.0
        
        if len(sys.argv) > 1:
            try:
                start_id = int(sys.argv[1])
            except ValueError:
                logger.error(f"[오류] 시작 ID는 숫자여야 합니다: {sys.argv[1]}")
                sys.exit(1)
        
        if len(sys.argv) > 2:
            try:
                end_id = int(sys.argv[2])
            except ValueError:
                logger.error(f"[오류] 종료 ID는 숫자여야 합니다: {sys.argv[2]}")
                sys.exit(1)
        
        if len(sys.argv) > 3:
            try:
                delay = float(sys.argv[3])
            except ValueError:
                logger.error(f"[오류] 대기 시간은 숫자여야 합니다: {sys.argv[3]}")
                sys.exit(1)
        
        if start_id or end_id:
            logger.info(f"[설정] reward_id 범위: {start_id or '전체'} ~ {end_id or '전체'}")
        else:
            logger.info("[설정] reward_id 범위: 전체")
        logger.info(f"[설정] 레코드 간 대기 시간: {delay}초")
        logger.info(f"[설정] 병렬 작업 수: 4개")
        
        # 업데이트 실행
        update_reward_rank_tag_and_price(
            start_id=start_id,
            end_id=end_id,
            delay=delay,
            max_workers=4
        )
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("\n[중단] 사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
