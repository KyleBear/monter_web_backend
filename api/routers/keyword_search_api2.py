"""
키워드 검색 API 라우터
- 메인키워드 추출 API (10개, 20개, 30개, 50개)
- GUI 제거, FastAPI 라우터로 변환
- 태그 크롤링 기능 통합
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Tuple, Dict
try:
    # 패키징된 exe에서는 database_package 사용
    from database_package import get_db, SessionLocal
except ImportError:
    # 일반 개발 환경에서는 database 사용
    from database import get_db, SessionLocal
from models import RewardRank, RewardTarget, UsersAdmin, ProxyIP
from utils.auth_helpers import get_current_user
from datetime import datetime
from urllib.parse import quote
import random
import string
import re
import time
import tempfile
import shutil
import logging
from bs4 import BeautifulSoup
from lxml import etree

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# keyword_search.py의 함수들 import
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# keyword_search.py의 함수들 import
from api.routers.keyword_search import (
    split_keywords_by_space,
    generate_keyword_combinations,
    get_api_rank_by_keyword,
    get_shopping_rank_with_ad_flag,
    check_exposure_and_cpc_for_keywords
)

router = APIRouter()
logger = logging.getLogger(__name__)

# ==================== 태그 크롤링 관련 상수 및 함수 ====================

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

# 사용한 프록시 추적 (프로세스 전체에서 공유)
USED_PROXIES = set()


# ==================== 유틸리티 함수 ====================

def remove_html_tags(text: str) -> str:
    """
    HTML 태그를 제거하고 텍스트만 반환
    
    Args:
        text: HTML 태그가 포함될 수 있는 텍스트
    
    Returns:
        HTML 태그가 제거된 텍스트
    """
    if not text:
        return ""
    
    # 문자열로 변환 (혹시 다른 타입일 경우 대비)
    text = str(text)
    
    # 먼저 정규표현식으로 HTML 태그 제거 (더 확실함)
    cleaned_text = re.sub(r'<[^>]+>', '', text)
    
    # BeautifulSoup으로도 한 번 더 정제 (HTML 엔티티 처리)
    try:
        soup = BeautifulSoup(cleaned_text, "html.parser")
        cleaned_text = soup.get_text(separator=" ", strip=True)
    except Exception:
        pass  # BeautifulSoup 실패해도 이미 정규표현식으로 처리했으므로 계속 진행
    
    # HTML 엔티티 디코딩 (예: &lt; -> <, &gt; -> >, &amp; -> &)
    try:
        import html
        cleaned_text = html.unescape(cleaned_text)
    except Exception:
        pass
    
    # 여러 공백을 하나로 통합
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    return cleaned_text


def generate_ackey(length: int = 8) -> str:
    """소문자 영문숫자 랜덤 문자열 생성 (ackey용)"""
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def generate_search_url(keyword: str, all_keywords: List[str] = None) -> str:
    """
    네이버 모바일 검색 URL 생성
    
    Args:
        keyword: 검색할 키워드 (query 파라미터용)
        all_keywords: 저장된 모든 키워드 리스트 (acq 파라미터용, 랜덤 선택)
    
    Returns:
        네이버 모바일 검색 URL
    """
    # query 파라미터: 현재 키워드 사용
    encoded_keyword = quote(keyword)
    
    # ackey: 영문숫자 8글자 랜덤
    ackey = generate_ackey(8)
    
    # acq: 저장된 키워드 중 랜덤 (없으면 현재 키워드 사용)
    if all_keywords and len(all_keywords) > 0:
        acq_keyword = random.choice(all_keywords)
    else:
        acq_keyword = keyword
    encoded_acq = quote(acq_keyword)
    
    # acr: 0~10 랜덤
    acr = random.randint(0, 10)
    
    # search_url 생성
    search_url = (
        f"https://m.search.naver.com/search.naver?"
        f"sm=mtp_sug.top&"
        f"where=m&"
        f"query={encoded_keyword}&"
        f"ackey={ackey}&"
        f"acq={encoded_acq}&"
        f"acr={acr}&"
        f"qdt=0"
    )
    
    return search_url


# ==================== 태그 크롤링 핵심 함수 ====================

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
    # Windows에서 안전한 경로 생성
    import platform
    if platform.system() == 'Windows':
        # Windows에서는 임시 디렉토리를 명시적으로 지정
        base_temp_dir = os.path.join(os.environ.get('TEMP', os.environ.get('TMP', 'C:\\temp')), 'chrome_data')
        os.makedirs(base_temp_dir, exist_ok=True)
        user_data_dir = tempfile.mkdtemp(prefix='chrome_', dir=base_temp_dir)
    else:
        user_data_dir = tempfile.mkdtemp(prefix='chrome_data_reward_')
    
    # 경로 정규화 (Windows 경로 구분자 처리)
    user_data_dir = os.path.abspath(os.path.normpath(user_data_dir))
    logger.info(f"[Chrome 설정] User Data Directory: {user_data_dir}")
    
    # 디렉토리가 실제로 존재하는지 확인
    if not os.path.exists(user_data_dir):
        try:
            os.makedirs(user_data_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"[Chrome 설정] User Data Directory 생성 실패: {e}")
            raise
    
    options = Options()
    
    # User Data Directory 사용 (Windows 경로 처리)
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
    
    # ChromeDriver 자동 다운로드 및 설정
    try:
        logger.info("[Chrome 설정] ChromeDriver 확인 중...")
        service = Service(ChromeDriverManager().install())
        logger.info("[Chrome 설정] ChromeDriver 준비 완료")
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        logger.error(f"[Chrome 설정] ChromeDriver 설정 실패: {e}", exc_info=True)
        logger.info("[Chrome 설정] ChromeDriver 없이 시도 중...")
        # ChromeDriver 없이도 시도 (시스템 PATH에 있는 경우)
        try:
            driver = webdriver.Chrome(options=options)
        except Exception as driver_error:
            logger.error(f"[Chrome 설정] Chrome WebDriver 초기화 실패: {driver_error}", exc_info=True)
            raise Exception(f"Chrome WebDriver를 초기화할 수 없습니다. ChromeDriver가 필요합니다. 오류: {str(driver_error)}")
    
    # ========== 쿠키 및 캐시 삭제 ==========
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
    
    # navigator.webdriver 제거 (봇 감지 회피 핵심)
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
    
    driver.implicitly_wait(10)
    
    return driver, user_data_dir


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
        
        time.sleep(2)  # 추가 대기 시간
    except TimeoutException:
        logger.warning("[클릭] flicking-viewport를 찾지 못했습니다. 계속 진행합니다...")
    
    click_script = create_click_result_script(nvmid)
    
    # 스크립트 실행 시 오류 처리
    try:
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
        
        if result and isinstance(result, dict) and result.get('success'):
            logger.info(f"[클릭] ✓ 상품 클릭 완료: {result.get('nvmid')}")
            time.sleep(random.uniform(3, 5))  # 페이지 로딩 대기
            return True
        else:
            logger.error(f"[클릭] ❌ 상품 클릭 실패: {result.get('reason') if result else 'unknown'}")
            return False
            
    except Exception as e:
        logger.error(f"[클릭] 스크립트 실행 중 오류: {e}", exc_info=True)
        return False


def crawl_image_tag(nvmid: str, reward_id: int, search_url: Optional[str] = None, headless: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """
    search_url 또는 nvmid로 접속하여 이미지 태그 및 이미지 URL 크롤링
    
    Args:
        nvmid: 네이버 상품 ID (필수)
        reward_id: reward_rank의 reward_id (DB 업데이트용)
        search_url: 검색 URL (옵셔널, 없으면 nvmid로 직접 접근)
        headless: Headless 모드
    
    Returns:
        tuple: (태그 텍스트, 이미지 URL) 또는 (None, None)
    """
    driver = None
    user_data_dir = None
    
    try:
        logger.info(f"[태그 크롤링] 시작: reward_id={reward_id}, nvmid={nvmid}, search_url={search_url if search_url else '없음 (nvmid로 직접 접근)'}")
        
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
        
        # 3단계: search_url이 있으면 검색 결과 페이지로, 없으면 nvmid로 직접 상품 페이지 접근
        if search_url and search_url.strip():
            # 검색 결과 페이지를 거쳐서 접근
            logger.info(f"[태그 크롤링] search_url로 접속: {search_url}")
            try:
                driver.get(search_url)
                # 검색 결과 페이지 로딩 대기
                time.sleep(random.uniform(5, 8))
                
                # 4단계: nvmid로 상품 클릭
                logger.info(f"[태그 크롤링] nvmid로 상품 클릭: {nvmid}")
                click_success = click_by_nvmid(driver, nvmid)
                
                if not click_success:
                    logger.error(f"\n{'='*60}")
                    logger.error(f"[태그 크롤링] ❌ reward_id={reward_id}: 검색 결과에서 상품 클릭 실패 (nvmid={nvmid})")
                    logger.error(f"[태그 크롤링] 현재 페이지 URL: {driver.current_url if driver else 'N/A'}")
                    logger.error(f"[태그 크롤링] search_url: {search_url}")
                    
                    try:
                        if driver:
                            html_source = driver.page_source
                            logger.error(f"[태그 크롤링] HTML 소스 길이: {len(html_source)} bytes")
                            
                            # nvmid가 포함된 링크 확인
                            soup = BeautifulSoup(html_source, 'html.parser')
                            links_with_nvmid = soup.find_all('a', href=lambda x: x and nvmid in str(x))
                            logger.error(f"[태그 크롤링] nvmid({nvmid})가 포함된 링크 개수: {len(links_with_nvmid)}")
                            
                            if links_with_nvmid:
                                logger.error("[태그 크롤링] 발견된 nvmid 링크:")
                                for idx, link in enumerate(links_with_nvmid[:5], 1):
                                    href = link.get('href', '')
                                    text = link.get_text(strip=True)
                                    logger.error(f"[태그 크롤링]   [{idx}] href: {href[:150]}, 텍스트: '{text[:50]}'")
                            else:
                                logger.error("[태그 크롤링] ⚠️ nvmid가 포함된 링크를 찾을 수 없음")
                            
                            # data-nv-mid 속성 확인
                            elements_with_nvmid = soup.find_all(attrs={'data-nv-mid': nvmid})
                            logger.error(f"[태그 크롤링] data-nv-mid={nvmid} 속성을 가진 요소 개수: {len(elements_with_nvmid)}")
                            
                            # 보안문자 감지
                            if 'captcha' in html_source.lower() or '보안문자' in html_source or '자동입력 방지' in html_source:
                                logger.error("[태그 크롤링] ⚠️ 보안문자 감지됨!")
                    except Exception as e:
                        logger.error(f"[태그 크롤링] 클릭 실패 분석 중 오류: {e}", exc_info=True)
                    
                    # 클릭 실패 시 nvmid로 직접 접근 시도
                    logger.info(f"[태그 크롤링] 검색 결과에서 클릭 실패, nvmid로 직접 접근 시도: {nvmid}")
                    try:
                        direct_url = f"https://m.shopping.naver.com/catalog/{nvmid}"
                        logger.info(f"[태그 크롤링] 직접 접근 URL: {direct_url}")
                        driver.get(direct_url)
                        time.sleep(random.uniform(3, 5))
                        logger.info(f"[태그 크롤링] 직접 접근 성공: {direct_url}")
                    except Exception as e:
                        logger.error(f"[태그 크롤링] 직접 접근 실패: {e}", exc_info=True)
                        logger.error(f"{'='*60}\n")
                        return (None, None)
                else:
                    logger.info(f"[태그 크롤링] ✅ 검색 결과에서 상품 클릭 성공 (nvmid={nvmid})")
            except Exception as e:
                logger.error(f"[태그 크롤링] search_url 접속 실패: {e}", exc_info=True)
                logger.info(f"[태그 크롤링] search_url 접속 실패로 인해 nvmid로 직접 접근 시도: {nvmid}")
                try:
                    direct_url = f"https://m.shopping.naver.com/catalog/{nvmid}"
                    logger.info(f"[태그 크롤링] 직접 접근 URL: {direct_url}")
                    driver.get(direct_url)
                    time.sleep(random.uniform(3, 5))
                    logger.info(f"[태그 크롤링] 직접 접근 성공: {direct_url}")
                except Exception as direct_e:
                    logger.error(f"[태그 크롤링] 직접 접근 실패: {direct_e}", exc_info=True)
                    return (None, None)
        else:
            # search_url이 없으면 nvmid로 직접 상품 페이지 접근
            logger.info(f"[태그 크롤링] search_url 없음, nvmid로 직접 상품 페이지 접근: {nvmid}")
            try:
                # 네이버 쇼핑 모바일 상품 페이지 URL
                direct_url = f"https://m.shopping.naver.com/catalog/{nvmid}"
                logger.info(f"[태그 크롤링] 직접 접근 URL: {direct_url}")
                driver.get(direct_url)
                time.sleep(random.uniform(3, 5))
                logger.info(f"[태그 크롤링] 직접 접근 성공: {direct_url}")
            except Exception as e:
                logger.error(f"[태그 크롤링] 직접 접근 실패: {e}", exc_info=True)
                logger.error(f"[태그 크롤링] nvmid: {nvmid}, reward_id: {reward_id}")
                return (None, None)
        
        # 상품 페이지 로딩 대기
        time.sleep(random.uniform(3, 5))
        
        # 자연스러운 스크롤
        logger.info("[태그 크롤링] 자연스러운 스크롤 동작")
        for i in range(3):
            scroll_amount = 300 * (i + 1)
            driver.execute_script(f"window.scrollTo(0, {scroll_amount});")
            time.sleep(random.uniform(0.3, 0.7))
        
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(1, 2))
        
        # 5단계: 태그 및 이미지 URL 크롤링 (BeautifulSoup + lxml XPath 사용)
        logger.info("[태그 크롤링] 태그 및 이미지 URL 크롤링 시작...")
        logger.info(f"[태그 크롤링] 현재 URL: {driver.current_url}")
        
        # 추가 대기 시간 (동적 콘텐츠 로딩 대기)
        logger.info("[태그 크롤링] 동적 콘텐츠 로딩 대기 중...")
        time.sleep(random.uniform(2, 4))
        
        tag_value = None
        image_url_value = None
        
        try:
            # Selenium에서 HTML 소스 가져오기
            html_source = driver.page_source
            logger.info(f"[태그 크롤링] HTML 소스 길이: {len(html_source)} bytes")
            
            # BeautifulSoup으로 파싱
            soup = BeautifulSoup(html_source, 'html.parser')
            
            # ========== 이미지 URL 크롤링 ==========
            logger.info("[이미지 URL 크롤링] 이미지 URL 크롤링 시작...")
            
            # 방법 1: alt="대표이미지" 속성으로 찾기 (우선)
            logger.info("[이미지 URL 크롤링] alt='대표이미지' 속성으로 이미지 찾기 시도...")
            try:
                img_with_alt = soup.find('img', alt='대표이미지')
                if img_with_alt:
                    image_url_value = img_with_alt.get('src') or img_with_alt.get('data-src')
                    if image_url_value:
                        image_url_value = image_url_value.strip()
                        # 404 이미지 URL 필터링
                        if '404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value:
                            logger.warning(f"[이미지 URL 크롤링] ⚠️ 404 이미지 URL 감지, 무시: {image_url_value[:100]}...")
                            image_url_value = None
                        else:
                            logger.info(f"[이미지 URL 크롤링] ✅ 이미지 URL 크롤링 성공 (alt='대표이미지'): {image_url_value[:100]}...")
            except Exception as e:
                logger.warning(f"[이미지 URL 크롤링] alt 속성 검색 실패: {e}")
            
            # 방법 2: 상대 XPath로 이미지 찾기
            if not image_url_value:
                relative_xpath = '//*[@id="content"]/div/div[2]/div[1]/div[1]/div[2]/img'
                logger.info(f"[이미지 URL 크롤링] 상대 XPath 시도: {relative_xpath}")
                
                try:
                    parser = etree.HTMLParser()
                    tree = etree.fromstring(html_source.encode('utf-8'), parser)
                    elements = tree.xpath(relative_xpath)
                    if elements and len(elements) > 0:
                        element = elements[0]
                        image_url_value = element.get('src') or element.get('data-src')
                        if image_url_value:
                            image_url_value = image_url_value.strip()
                            # 404 이미지 URL 필터링
                            if '404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value:
                                logger.warning(f"[이미지 URL 크롤링] ⚠️ 404 이미지 URL 감지, 무시: {image_url_value[:100]}...")
                                image_url_value = None
                            else:
                                logger.info(f"[이미지 URL 크롤링] ✅ 이미지 URL 크롤링 성공 (상대 XPath): {image_url_value[:100]}...")
                except Exception as e:
                    logger.warning(f"[이미지 URL 크롤링] 상대 XPath 사용 실패: {e}")
            
            # 방법 3: Full XPath로 이미지 찾기
            if not image_url_value:
                image_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/img'
                logger.info(f"[이미지 URL 크롤링] Full XPath 시도: {image_xpath}")
                
                try:
                    parser = etree.HTMLParser()
                    tree = etree.fromstring(html_source.encode('utf-8'), parser)
                    elements = tree.xpath(image_xpath)
                    if elements and len(elements) > 0:
                        element = elements[0]
                        image_url_value = element.get('src') or element.get('data-src')
                        if image_url_value:
                            image_url_value = image_url_value.strip()
                            # 404 이미지 URL 필터링
                            if '404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value:
                                logger.warning(f"[이미지 URL 크롤링] ⚠️ 404 이미지 URL 감지, 무시: {image_url_value[:100]}...")
                                image_url_value = None
                            else:
                                logger.info(f"[이미지 URL 크롤링] ✅ 이미지 URL 크롤링 성공 (Full XPath): {image_url_value[:100]}...")
                except Exception as e:
                    logger.warning(f"[이미지 URL 크롤링] Full XPath 직접 사용 실패: {e}")
            
            # 방법 4: CSS 선택자로 이미지 찾기
            if not image_url_value:
                logger.info("[이미지 URL 크롤링] CSS 선택자로 이미지 찾기 시도...")
                image_selectors = [
                    '#content > div > div.Cpf2P_YsRS > div.OaKLUocIcJ > div.PYE1T66W79.JUPB3aUHbH > div.mdFeBiFowv.S0Yy3ca55r > img',  # 제공된 선택자
                    '#content img[alt="대표이미지"]',  # alt 속성과 함께
                    '#content img',
                    '#INTRODUCE img',
                    'img[alt="대표이미지"]',  # alt 속성만으로
                    'div.product_image img',
                    'img.product_image',
                    '.product_image img',
                    'img[class*="product"]',
                    'div[class*="product"] img',
                ]
                
                for selector in image_selectors:
                    try:
                        element = soup.select_one(selector)
                        if element:
                            image_url_value = element.get('src') or element.get('data-src')
                            if image_url_value:
                                image_url_value = image_url_value.strip()
                                # 404 이미지 URL 필터링
                                if '404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value:
                                    logger.warning(f"[이미지 URL 크롤링] ⚠️ 404 이미지 URL 감지, 무시: {image_url_value[:100]}...")
                                    image_url_value = None
                                    continue
                                else:
                                    logger.info(f"[이미지 URL 크롤링] ✅ 이미지 URL 크롤링 성공 (CSS 선택자: {selector}): {image_url_value[:100]}...")
                                    break
                    except Exception as e:
                        logger.debug(f"[이미지 URL 크롤링] CSS 선택자 '{selector}' 실패: {e}")
                        continue
            
            # 방법 5: JavaScript로 동적 로딩된 이미지 확인
            if not image_url_value:
                logger.info("[이미지 URL 크롤링] JavaScript로 동적 이미지 확인...")
                try:
                    image_url_js = driver.execute_script("""
                        try {
                            // alt="대표이미지" 속성으로 찾기 (우선)
                            var img = document.querySelector('img[alt="대표이미지"]');
                            if (img) {
                                return img.src || img.getAttribute('data-src') || null;
                            }
                            
                            // 상대 XPath 시도
                            var xpath = '//*[@id="content"]/div/div[2]/div[1]/div[1]/div[2]/img';
                            var element = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (element) {
                                return element.src || element.getAttribute('data-src') || null;
                            }
                            
                            // Full XPath 시도
                            xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[2]/div[1]/div[1]/div[2]/img';
                            element = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (element) {
                                return element.src || element.getAttribute('data-src') || null;
                            }
                            
                            // CSS 선택자 시도
                            img = document.querySelector('#content > div > div.Cpf2P_YsRS > div.OaKLUocIcJ > div.PYE1T66W79.JUPB3aUHbH > div.mdFeBiFowv.S0Yy3ca55r > img');
                            if (img) {
                                return img.src || img.getAttribute('data-src') || null;
                            }
                            
                            // #content 내 이미지 찾기
                            img = document.querySelector('#content img');
                            if (img) {
                                return img.src || img.getAttribute('data-src') || null;
                            }
                            
                            // #INTRODUCE 내 이미지 찾기
                            img = document.querySelector('#INTRODUCE img');
                            if (img) {
                                return img.src || img.getAttribute('data-src') || null;
                            }
                            
                            return null;
                        } catch (e) {
                            return null;
                        }
                    """)
                    if image_url_js:
                        image_url_value = image_url_js.strip()
                        # 404 이미지 URL 필터링
                        if '404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value:
                            logger.warning(f"[이미지 URL 크롤링] ⚠️ 404 이미지 URL 감지, 무시: {image_url_value[:100]}...")
                            image_url_value = None
                        else:
                            logger.info(f"[이미지 URL 크롤링] ✅ 이미지 URL 크롤링 성공 (JavaScript): {image_url_value[:100]}...")
                except Exception as e:
                    logger.debug(f"[이미지 URL 크롤링] JavaScript 이미지 확인 실패: {e}")
            
            # ========== 태그 크롤링 ==========
            # 방법 1: lxml etree를 사용한 XPath 직접 사용
            tag_xpath = '/html/body/div[1]/div/div[4]/div[2]/div[2]/div/div[3]/div[6]/div/div[11]/div/ul/li[1]/a'
            logger.info(f"[태그 크롤링] 태그 XPath 시도: {tag_xpath}")
            
            try:
                # lxml HTMLParser로 파싱
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
            
            # 방법 2: #INTRODUCE ID로 찾기
            if not tag_value:
                logger.info("[태그 크롤링] #INTRODUCE 요소로 태그 찾기 시도...")
                try:
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
                except Exception as e:
                    logger.warning(f"[태그 크롤링] #INTRODUCE 경로 따라가기 실패: {e}")
            
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
                ]
                
                for selector in tag_selectors:
                    try:
                        element = soup.select_one(selector)
                        if element:
                            tag_value = element.get_text(strip=True)
                            if tag_value:
                                logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (CSS 선택자: {selector}): {tag_value}")
                                break
                    except Exception as e:
                        logger.debug(f"[태그 크롤링] CSS 선택자 '{selector}' 실패: {e}")
                        continue
            
            # 방법 4: data-shp-inventory="tag" 속성으로 찾기
            if not tag_value:
                logger.info("[태그 크롤링] data-shp-inventory='tag' 속성으로 태그 찾기...")
                try:
                    tag_links = soup.find_all('a', attrs={'data-shp-inventory': 'tag'})
                    if tag_links:
                        first_tag_link = tag_links[0]
                        tag_value = first_tag_link.get_text(strip=True)
                        if tag_value:
                            logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (data-shp-inventory 속성): {tag_value}")
                except Exception as e:
                    logger.warning(f"[태그 크롤링] data-shp-inventory 속성 검색 실패: {e}")
            
            # 방법 5: JavaScript로 동적 로딩된 태그 확인
            if not tag_value:
                logger.info("[태그 크롤링] JavaScript로 동적 태그 확인...")
                try:
                    tag_text = driver.execute_script("""
                        try {
                            var selector = '#INTRODUCE > div > div:nth-child(11) > div > ul > li:nth-child(1) > a';
                            var element = document.querySelector(selector);
                            if (element) {
                                return element.textContent.trim();
                            }
                            
                            var tagElements = document.querySelectorAll('a[data-shp-inventory="tag"]');
                            if (tagElements.length > 0) {
                                return tagElements[0].textContent.trim();
                            }
                            
                            return null;
                        } catch (e) {
                            return null;
                        }
                    """)
                    if tag_text:
                        tag_value = tag_text
                        logger.info(f"[태그 크롤링] ✅ 태그 크롤링 성공 (JavaScript): {tag_value}")
                except Exception as e:
                    logger.debug(f"[태그 크롤링] JavaScript 태그 확인 실패: {e}")
            
        except Exception as e:
            logger.error(f"[태그 크롤링] 태그 크롤링 실패: {e}", exc_info=True)
        
        # 태그를 찾지 못한 경우 상세 분석
        if not tag_value:
            logger.warning(f"\n{'='*60}")
            logger.warning(f"[태그 크롤링 실패 분석] reward_id={reward_id}")
            logger.warning(f"{'='*60}")
            logger.warning(f"현재 페이지 URL: {driver.current_url if driver else 'N/A'}")
            
            try:
                if driver:
                    html_source = driver.page_source
                    logger.warning(f"HTML 소스 길이: {len(html_source)} bytes")
                    
                    # BeautifulSoup으로 페이지 구조 분석
                    soup = BeautifulSoup(html_source, 'html.parser')
                    
                    # #INTRODUCE 요소 확인
                    introduce = soup.find(id='INTRODUCE')
                    if introduce:
                        logger.warning("✅ #INTRODUCE 요소 발견")
                        
                        # ul 태그 개수 확인
                        uls = introduce.find_all('ul')
                        logger.warning(f"  - ul 태그 개수: {len(uls)}")
                        
                        # li 태그 개수 확인
                        lis = introduce.find_all('li')
                        logger.warning(f"  - li 태그 개수: {len(lis)}")
                        
                        # a 태그 개수 확인
                        links = introduce.find_all('a')
                        logger.warning(f"  - a 태그 개수: {len(links)}")
                        
                        # data-shp-inventory="tag" 속성을 가진 링크 확인
                        tag_links = introduce.find_all('a', attrs={'data-shp-inventory': 'tag'})
                        logger.warning(f"  - data-shp-inventory='tag' 링크 개수: {len(tag_links)}")
                        
                        if tag_links:
                            logger.warning("  - 발견된 태그 링크 텍스트:")
                            for idx, link in enumerate(tag_links[:5], 1):  # 최대 5개만 출력
                                text = link.get_text(strip=True)
                                href = link.get('href', '')
                                logger.warning(f"    [{idx}] 텍스트: '{text}', href: {href[:100]}")
                        
                        # 첫 번째 ul의 구조 확인
                        if uls:
                            first_ul = uls[0]
                            first_ul_lis = first_ul.find_all('li')
                            logger.warning(f"  - 첫 번째 ul의 li 개수: {len(first_ul_lis)}")
                            if first_ul_lis:
                                first_li = first_ul_lis[0]
                                first_li_links = first_li.find_all('a')
                                logger.warning(f"  - 첫 번째 li의 a 태그 개수: {len(first_li_links)}")
                                if first_li_links:
                                    first_link_text = first_li_links[0].get_text(strip=True)
                                    first_link_href = first_li_links[0].get('href', '')
                                    logger.warning(f"  - 첫 번째 링크 텍스트: '{first_link_text}'")
                                    logger.warning(f"  - 첫 번째 링크 href: {first_link_href[:100]}")
                    else:
                        logger.warning("❌ #INTRODUCE 요소를 찾을 수 없음")
                    
                    # 보안문자 감지
                    if 'captcha' in html_source.lower() or '보안문자' in html_source or '자동입력 방지' in html_source:
                        logger.warning("⚠️ 보안문자 감지됨!")
                    
                    # 페이지 제목 확인
                    title = soup.find('title')
                    if title:
                        logger.warning(f"페이지 제목: {title.get_text(strip=True)}")
                    
                    # body 내 div 개수 확인
                    body = soup.find('body')
                    if body:
                        divs = body.find_all('div')
                        logger.warning(f"body 내 div 태그 개수: {len(divs)}")
                        
                        # class에 'tag'가 포함된 요소 확인
                        tag_elements = soup.find_all(class_=lambda x: x and 'tag' in x.lower())
                        logger.warning(f"class에 'tag'가 포함된 요소 개수: {len(tag_elements)}")
                        
                        # href에 'tag' 또는 'keyword'가 포함된 링크 확인
                        tag_href_links = soup.find_all('a', href=lambda x: x and ('tag' in x.lower() or 'keyword' in x.lower()))
                        logger.warning(f"href에 'tag'/'keyword'가 포함된 링크 개수: {len(tag_href_links)}")
                        if tag_href_links:
                            logger.warning("  - 발견된 링크:")
                            for idx, link in enumerate(tag_href_links[:5], 1):
                                text = link.get_text(strip=True)
                                href = link.get('href', '')
                                logger.warning(f"    [{idx}] 텍스트: '{text}', href: {href[:100]}")
                    
            except Exception as e:
                logger.error(f"[태그 크롤링 실패 분석] 분석 중 오류: {e}", exc_info=True)
            
            logger.warning(f"{'='*60}\n")
        
        # 6단계: DB 업데이트 (태그 및 이미지 URL 모두)
        if tag_value or image_url_value:
            db = SessionLocal()
            try:
                existing = db.query(RewardRank).filter(
                    RewardRank.reward_id == reward_id
                ).first()
                
                if existing:
                    updated = False
                    if tag_value:
                        old_tag = existing.image_tag
                        existing.image_tag = tag_value
                        updated = True
                        logger.info(f"[DB] ✅ reward_id={reward_id} 태그 업데이트 완료")
                        logger.info(f"[DB]    이전 태그: {old_tag}")
                        logger.info(f"[DB]    새 태그: {tag_value}")
                    
                    if image_url_value:
                        # image_url이 이미 있으면 업데이트하지 않음 (404 이미지 방지)
                        if existing.image_url and existing.image_url.strip() and existing.image_url.strip() != '':
                            # 404 이미지 URL인 경우는 업데이트
                            if '404' in existing.image_url or 'grafolio' in existing.image_url:
                                old_image_url = existing.image_url
                                existing.image_url = image_url_value
                                updated = True
                                logger.info(f"[DB] ✅ reward_id={reward_id} 이미지 URL 업데이트 완료 (404 이미지 교체)")
                                logger.info(f"[DB]    이전 이미지 URL: {old_image_url}")
                                logger.info(f"[DB]    새 이미지 URL: {image_url_value[:100]}...")
                            else:
                                logger.info(f"[DB] ⏭️ reward_id={reward_id} 이미지 URL이 이미 존재하여 업데이트하지 않음: {existing.image_url[:100]}...")
                        else:
                            # image_url이 없거나 빈 문자열인 경우만 업데이트
                            old_image_url = existing.image_url
                            existing.image_url = image_url_value
                            updated = True
                            logger.info(f"[DB] ✅ reward_id={reward_id} 이미지 URL 업데이트 완료")
                            logger.info(f"[DB]    이전 이미지 URL: {old_image_url}")
                            logger.info(f"[DB]    새 이미지 URL: {image_url_value[:100]}...")
                    
                    if updated:
                        existing.updated_at = datetime.now()
                        db.commit()
                else:
                    logger.warning(f"[DB] ⚠️ reward_id={reward_id} 레코드를 찾을 수 없습니다.")
            except Exception as e:
                db.rollback()
                logger.error(f"[DB] ❌ reward_id={reward_id} 업데이트 실패: {e}", exc_info=True)
            finally:
                db.close()
        else:
            logger.warning(f"[태그 크롤링] ⚠️ reward_id={reward_id}: 태그 및 이미지 URL을 크롤링하지 못했습니다.")
        
        return (tag_value, image_url_value)
        
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        import traceback
        error_traceback = traceback.format_exc()
        
        logger.error(f"\n{'='*60}")
        logger.error(f"[태그 크롤링] ❌ reward_id={reward_id} 크롤링 중 예외 발생")
        logger.error(f"{'='*60}")
        logger.error(f"예외 타입: {error_type}")
        logger.error(f"예외 메시지: {error_msg}")
        logger.error(f"nvmid: {nvmid}")
        logger.error(f"search_url: {search_url if search_url else '없음 (nvmid로 직접 접근)'}")
        logger.error(f"headless: {headless}")
        logger.error(f"스택 트레이스:\n{error_traceback}")
        logger.error(f"{'='*60}\n")
        
        return (None, None)
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


def crawl_tags_for_all_rewards(headless: bool = True, delay: int = 5) -> int:
    """
    reward_rank 테이블의 모든 레코드에 대해 태그 크롤링 수행
    스케줄러에서 호출하는 함수
    
    Args:
        headless: Headless 모드
        delay: 크롤링 간 대기 시간 (초)
    
    Returns:
        int: 크롤링한 레코드 수
    """
    db = SessionLocal()
    crawled_count = 0
    
    try:
        # reward_rank 테이블에서 nvmid와 search_url이 있고, image_tag가 비어있거나 없는 레코드 조회
        records = db.query(RewardRank).filter(
            RewardRank.nvmid.isnot(None),
            RewardRank.nvmid != '',
            RewardRank.search_url.isnot(None),
            RewardRank.search_url != '',
            # image_tag가 비어있거나 None인 경우만 크롤링 (이미 태그가 있으면 스킵)
            (RewardRank.image_tag.is_(None) | (RewardRank.image_tag == ''))
        ).order_by(RewardRank.reward_id).all()
        
        logger.info(f"[태그 크롤링 스케줄러] 크롤링 대상: {len(records)}개")
        
        if not records:
            logger.info("[태그 크롤링 스케줄러] 크롤링할 레코드가 없습니다.")
            return 0
        
        for idx, record in enumerate(records, 1):
            reward_id = record.reward_id
            nvmid = record.nvmid
            search_url = record.search_url
            
            logger.info(f"\n{'='*60}")
            logger.info(f"[태그 크롤링 스케줄러] {idx}/{len(records)} - reward_id={reward_id}")
            logger.info(f"  nvmid: {nvmid}")
            logger.info(f"  search_url: {search_url}")
            logger.info(f"{'='*60}\n")
            
            # 데이터 검증
            if not nvmid or not nvmid.strip():
                logger.warning(f"[태그 크롤링 스케줄러] ⚠ reward_id={reward_id}: nvmid가 없어 건너뜁니다.")
                continue
            
            # search_url이 없어도 nvmid만으로 크롤링 가능
            final_search_url = search_url if (search_url and search_url.strip()) else None
            if not final_search_url:
                logger.info(f"[태그 크롤링 스케줄러] reward_id={reward_id}: search_url 없음, nvmid로 직접 접근 시도")
            
            try:
                # 태그 및 이미지 URL 크롤링 수행
                tag_value, image_url_value = crawl_image_tag(
                    nvmid=nvmid,
                    reward_id=reward_id,
                    search_url=final_search_url,
                    headless=headless
                )
                
                if tag_value or image_url_value:
                    crawled_count += 1
                    if tag_value:
                        logger.info(f"[태그 크롤링 스케줄러] ✅ reward_id={reward_id} 태그 크롤링 완료: {tag_value}")
                    if image_url_value:
                        logger.info(f"[태그 크롤링 스케줄러] ✅ reward_id={reward_id} 이미지 URL 크롤링 완료: {image_url_value[:100]}...")
                else:
                    logger.warning(f"[태그 크롤링 스케줄러] ⚠️ reward_id={reward_id}: 태그 및 이미지 URL을 크롤링하지 못했습니다.")
                
            except Exception as e:
                logger.error(f"[태그 크롤링 스케줄러] reward_id={reward_id} 크롤링 오류: {e}", exc_info=True)
                continue
            
            # 마지막 항목이 아닐 때만 대기
            if idx < len(records):
                delay_time = random.uniform(delay, delay + 5)
                logger.info(f"\n[대기] 다음 크롤링까지 {delay_time:.2f}초 대기...\n")
                time.sleep(delay_time)
        
        logger.info(f"[태그 크롤링 스케줄러] 완료: 총 {crawled_count}개 레코드 크롤링됨")
        
    except Exception as e:
        logger.error(f"[태그 크롤링 스케줄러] 오류: {e}", exc_info=True)
    finally:
        db.close()
    
    return crawled_count


def crawl_tag_for_single_reward(reward_id: int, headless: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """
    특정 reward_id의 태그 및 이미지 URL 크롤링 수행
    
    Args:
        reward_id: 크롤링할 reward_rank의 reward_id
        headless: Headless 모드
    
    Returns:
        tuple: (태그 텍스트, 이미지 URL) 또는 (None, None)
    """
    db = SessionLocal()
    
    try:
        # reward_rank 테이블에서 특정 reward_id 조회
        record = db.query(RewardRank).filter(
            RewardRank.reward_id == reward_id
        ).first()
        
        if not record:
            logger.error(f"[태그 크롤링] reward_id={reward_id} 레코드를 찾을 수 없습니다.")
            return (None, None)
        
        nvmid = record.nvmid
        search_url = record.search_url
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[태그 크롤링] reward_id={reward_id} 크롤링 시작")
        logger.info(f"  nvmid: {nvmid}")
        logger.info(f"  search_url: {search_url}")
        logger.info(f"{'='*60}\n")
        
        # 데이터 검증
        if not nvmid or not nvmid.strip():
            logger.warning(f"[태그 크롤링] ⚠ reward_id={reward_id}: nvmid가 없어 크롤링할 수 없습니다.")
            return (None, None)
        
        # search_url이 없어도 nvmid만으로 크롤링 가능
        final_search_url = search_url if (search_url and search_url.strip()) else None
        if not final_search_url:
            logger.info(f"[태그 크롤링] reward_id={reward_id}: search_url 없음, nvmid로 직접 접근 시도")
        
        # 태그 및 이미지 URL 크롤링 수행
        tag_value, image_url_value = crawl_image_tag(
            nvmid=nvmid,
            reward_id=reward_id,
            search_url=final_search_url,
            headless=headless
        )
        
        if tag_value or image_url_value:
            logger.info(f"[태그 크롤링] ✅ reward_id={reward_id} 크롤링 완료")
            if tag_value:
                logger.info(f"  - 태그: {tag_value}")
            if image_url_value:
                logger.info(f"  - 이미지 URL: {image_url_value[:100]}...")
        else:
            logger.warning(f"[태그 크롤링] ⚠️ reward_id={reward_id}: 태그 및 이미지 URL을 크롤링하지 못했습니다.")
        
        return (tag_value, image_url_value)
        
    except Exception as e:
        logger.error(f"[태그 크롤링] reward_id={reward_id} 크롤링 오류: {e}", exc_info=True)
        return (None, None)
    finally:
        db.close()


def crawl_tags_for_range_rewards_parallel(start_id: int, end_id: int, headless: bool = True, max_workers: int = 5) -> Dict[str, int]:
    """
    reward_rank 테이블의 특정 구간(reward_id 범위)에 대해 태그 및 이미지 URL 크롤링 수행 (병렬 처리)
    
    Args:
        start_id: 시작 reward_id (포함)
        end_id: 종료 reward_id (포함)
        headless: Headless 모드 (기본값: True)
        max_workers: 병렬 실행할 최대 브라우저 수 (기본값: 5)
    
    Returns:
        dict: {
            'total': 전체 레코드 수,
            'crawled': 크롤링 성공한 레코드 수,
            'failed': 크롤링 실패한 레코드 수,
            'skipped': 건너뛴 레코드 수 (nvmid 또는 search_url 없음)
        }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    db = SessionLocal()
    crawled_count = 0
    failed_count = 0
    skipped_count = 0
    total_count = 0
    
    try:
        # reward_rank 테이블에서 구간 내의 레코드 조회
        # search_url 필터 제거 (nvmid만 필터링)
        records = db.query(RewardRank).filter(
            RewardRank.reward_id >= start_id,
            RewardRank.reward_id <= end_id,
            RewardRank.nvmid.isnot(None),
            RewardRank.nvmid != ''
        ).order_by(RewardRank.reward_id).all()
        
        total_count = len(records)
        logger.info(f"[구간 태그 크롤링 병렬] reward_id {start_id}~{end_id} 구간 크롤링 대상: {total_count}개 (병렬 작업자: {max_workers}개)")
        
        if not records:
            logger.info(f"[구간 태그 크롤링 병렬] reward_id {start_id}~{end_id} 구간에 크롤링할 레코드가 없습니다.")
            return {
                'total': 0,
                'crawled': 0,
                'failed': 0,
                'skipped': 0
            }
        
        # 병렬 처리 함수
        def crawl_single_record(record):
            reward_id = record.reward_id
            nvmid = record.nvmid
            search_url = record.search_url
            product_url = record.product_url
            image_url = record.image_url  # 이미 image_url이 있으면 크롤링하지 않음
            
            # image_url이 이미 있으면 크롤링 스킵 (404 이미지 제외)
            if image_url and image_url.strip() and image_url.strip() != '':
                if '404' not in image_url and 'grafolio' not in image_url and 'ssl.pstatic.net/static/grafolio' not in image_url:
                    logger.info(f"[구간 태그 크롤링 병렬] reward_id={reward_id}: image_url이 이미 존재하여 크롤링 스킵: {image_url[:100]}...")
                    # 태그만 크롤링 시도 (product_url이 있으면 직접 크롤링)
                    if product_url and product_url.strip():
                        try:
                            from api.routers.tag_crol import crawl_smartstore_direct
                            crawl_result = crawl_smartstore_direct(product_url, headless=headless)
                            tag_value = crawl_result.get('image_tag')
                            if tag_value:
                                # DB 업데이트 (태그만)
                                thread_db = SessionLocal()
                                try:
                                    existing = thread_db.query(RewardRank).filter(RewardRank.reward_id == reward_id).first()
                                    if existing:
                                        existing.image_tag = tag_value
                                        existing.updated_at = datetime.now()
                                        thread_db.commit()
                                        logger.info(f"[구간 태그 크롤링 병렬] ✅ reward_id={reward_id} 태그만 업데이트 완료: {tag_value}")
                                finally:
                                    thread_db.close()
                            return {'status': 'success', 'reward_id': reward_id, 'tag': tag_value, 'image_url': image_url}
                        except Exception as e:
                            logger.warning(f"[구간 태그 크롤링 병렬] reward_id={reward_id} 태그 크롤링 실패: {e}")
                    return {'status': 'skipped', 'reward_id': reward_id, 'reason': 'image_url이 이미 존재하여 크롤링 스킵'}
            
            # 데이터 검증
            if not nvmid or not nvmid.strip():
                # product_url이 있으면 직접 크롤링 시도
                if product_url and product_url.strip():
                    try:
                        from api.routers.tag_crol import crawl_smartstore_direct
                        crawl_result = crawl_smartstore_direct(product_url, headless=headless)
                        tag_value = crawl_result.get('image_tag')
                        image_url_value = crawl_result.get('image_url')
                        
                        # 404 이미지 URL 필터링
                        if image_url_value and ('404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value):
                            logger.warning(f"[구간 태그 크롤링 병렬] ⚠️ reward_id={reward_id} 404 이미지 URL 감지, 무시")
                            image_url_value = None
                        
                        if tag_value or image_url_value:
                            # DB 업데이트
                            thread_db = SessionLocal()
                            try:
                                existing = thread_db.query(RewardRank).filter(RewardRank.reward_id == reward_id).first()
                                if existing:
                                    updated = False
                                    if tag_value:
                                        existing.image_tag = tag_value
                                        updated = True
                                    if image_url_value:
                                        existing.image_url = image_url_value
                                        updated = True
                                    if updated:
                                        existing.updated_at = datetime.now()
                                        thread_db.commit()
                            finally:
                                thread_db.close()
                            return {'status': 'success', 'reward_id': reward_id, 'tag': tag_value, 'image_url': image_url_value}
                        else:
                            return {'status': 'failed', 'reward_id': reward_id, 'reason': 'product_url 직접 크롤링 실패 (태그 및 이미지 URL 모두 None)'}
                    except Exception as e:
                        logger.error(f"[구간 태그 크롤링 병렬] reward_id={reward_id} product_url 직접 크롤링 오류: {e}", exc_info=True)
                        return {'status': 'failed', 'reward_id': reward_id, 'reason': f'product_url 직접 크롤링 중 예외 발생: {str(e)}'}
                return {'status': 'skipped', 'reward_id': reward_id, 'reason': 'nvmid 없음 (reward_rank 테이블에 nvmid가 없거나 빈 문자열)'}
            
            # search_url이 없으면 키워드로부터 생성 시도
            final_search_url = search_url if (search_url and search_url.strip()) else None
            
            if not final_search_url:
                logger.info(f"[구간 태그 크롤링 병렬] reward_id={reward_id}: search_url 없음, 키워드로부터 생성 시도")
                try:
                    # 각 스레드에서 독립적인 DB 세션 생성 (병렬 처리 안전)
                    thread_db = SessionLocal()
                    try:
                        # from models import RewardTarget
                        # reward_target = thread_db.query(RewardTarget).filter(
                        #     RewardTarget.reward_target_id == reward_id
                        # ).first()
                        
                        # if reward_target and reward_target.keyword:
                        #     # 키워드로부터 search_url 생성
                        if record.keyword:
                            final_search_url = generate_search_url(record.keyword)
                            logger.info(f"[구간 태그 크롤링 병렬] reward_id={reward_id}: search_url 생성 성공 (키워드: {record.keyword})")
                    finally:
                        thread_db.close()
                except Exception as e:
                    logger.warning(f"[구간 태그 크롤링 병렬] reward_id={reward_id} search_url 생성 실패: {e}, nvmid로 직접 접근 시도")
            
            # product_url이 있으면 직접 크롤링 우선 시도
            if product_url and product_url.strip():
                try:
                    from api.routers.tag_crol import crawl_smartstore_direct
                    logger.info(f"[구간 태그 크롤링 병렬] reward_id={reward_id}: product_url 직접 크롤링 시도: {product_url}")
                    crawl_result = crawl_smartstore_direct(product_url, headless=headless)
                    tag_value = crawl_result.get('image_tag')
                    image_url_value = crawl_result.get('image_url')
                    
                    # 404 이미지 URL 필터링
                    if image_url_value and ('404' in image_url_value or 'grafolio' in image_url_value or 'ssl.pstatic.net/static/grafolio' in image_url_value):
                        logger.warning(f"[구간 태그 크롤링 병렬] ⚠️ reward_id={reward_id} 404 이미지 URL 감지, 무시")
                        image_url_value = None
                    
                    if tag_value or image_url_value:
                        # DB 업데이트
                        thread_db = SessionLocal()
                        try:
                            existing = thread_db.query(RewardRank).filter(RewardRank.reward_id == reward_id).first()
                            if existing:
                                updated = False
                                if tag_value:
                                    existing.image_tag = tag_value
                                    updated = True
                                if image_url_value:
                                    # image_url이 이미 있으면 업데이트하지 않음 (404 이미지 제외)
                                    if not existing.image_url or not existing.image_url.strip() or '404' in existing.image_url or 'grafolio' in existing.image_url:
                                        existing.image_url = image_url_value
                                        updated = True
                                if updated:
                                    existing.updated_at = datetime.now()
                                    thread_db.commit()
                        finally:
                            thread_db.close()
                        return {'status': 'success', 'reward_id': reward_id, 'tag': tag_value, 'image_url': image_url_value}
                    else:
                        logger.warning(f"[구간 태그 크롤링 병렬] reward_id={reward_id}: product_url 직접 크롤링 결과 없음, nvmid 기반 크롤링으로 폴백")
                except Exception as e:
                    logger.warning(f"[구간 태그 크롤링 병렬] reward_id={reward_id} product_url 직접 크롤링 실패: {e}, nvmid 기반 크롤링으로 폴백")
            
            try:
                # 태그 및 이미지 URL 크롤링 수행 (nvmid 기반)
                tag_value, image_url_value = crawl_image_tag(
                    nvmid=nvmid,
                    reward_id=reward_id,
                    search_url=final_search_url,
                    headless=headless
                )
                
                if tag_value or image_url_value:
                    return {'status': 'success', 'reward_id': reward_id, 'tag': tag_value, 'image_url': image_url_value}
                else:
                    return {'status': 'failed', 'reward_id': reward_id, 'reason': '태그 및 이미지 URL 크롤링 실패 (태그와 이미지 URL 모두 None 반환)'}
            except Exception as e:
                error_msg = str(e)
                error_traceback = None
                try:
                    import traceback
                    error_traceback = traceback.format_exc()
                except:
                    pass
                
                logger.error(f"[구간 태그 크롤링 병렬] reward_id={reward_id} 크롤링 오류: {error_msg}", exc_info=True)
                if error_traceback:
                    logger.error(f"[구간 태그 크롤링 병렬] reward_id={reward_id} 스택 트레이스:\n{error_traceback}")
                
                return {'status': 'failed', 'reward_id': reward_id, 'reason': f'크롤링 중 예외 발생: {error_msg}'}
        
        # 병렬 실행
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_record = {executor.submit(crawl_single_record, record): record for record in records}
            
            completed = 0
            for future in as_completed(future_to_record):
                completed += 1
                result = future.result()
                reward_id = result['reward_id']
                
                if result['status'] == 'success':
                    crawled_count += 1
                    logger.info(f"[구간 태그 크롤링 병렬] [{completed}/{total_count}] ✅ reward_id={reward_id} 크롤링 완료")
                elif result['status'] == 'failed':
                    failed_count += 1
                    logger.warning(f"[구간 태그 크롤링 병렬] [{completed}/{total_count}] ❌ reward_id={reward_id} 크롤링 실패: {result.get('reason', '')}")
                elif result['status'] == 'skipped':
                    skipped_count += 1
                    logger.warning(f"[구간 태그 크롤링 병렬] [{completed}/{total_count}] ⏭️ reward_id={reward_id} 건너뜀: {result.get('reason', '')}")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[구간 태그 크롤링 병렬] 완료: reward_id {start_id}~{end_id} 구간")
        logger.info(f"  전체: {total_count}개")
        logger.info(f"  성공: {crawled_count}개")
        logger.info(f"  실패: {failed_count}개")
        logger.info(f"  건너뜀: {skipped_count}개")
        logger.info(f"{'='*60}\n")
        
    except Exception as e:
        logger.error(f"[구간 태그 크롤링 병렬] 오류: {e}", exc_info=True)
    finally:
        db.close()
    
    return {
        'total': total_count,
        'crawled': crawled_count,
        'failed': failed_count,
        'skipped': skipped_count
    }


def crawl_tags_for_range_rewards(start_id: int, end_id: int, headless: bool = True, delay: int = 5) -> Dict[str, int]:
    """
    reward_rank 테이블의 특정 구간(reward_id 범위)에 대해 태그 및 이미지 URL 크롤링 수행
    
    Args:
        start_id: 시작 reward_id (포함)
        end_id: 종료 reward_id (포함)
        headless: Headless 모드
        delay: 크롤링 간 대기 시간 (초)
    
    Returns:
        dict: {
            'total': 전체 레코드 수,
            'crawled': 크롤링 성공한 레코드 수,
            'failed': 크롤링 실패한 레코드 수,
            'skipped': 건너뛴 레코드 수 (nvmid 또는 search_url 없음)
        }
    """
    db = SessionLocal()
    crawled_count = 0
    failed_count = 0
    skipped_count = 0
    total_count = 0
    
    try:
        # reward_rank 테이블에서 구간 내의 레코드 조회
        # nvmid와 search_url이 있는 레코드만 조회
        records = db.query(RewardRank).filter(
            RewardRank.reward_id >= start_id,
            RewardRank.reward_id <= end_id,
            RewardRank.nvmid.isnot(None),
            RewardRank.nvmid != '',
            RewardRank.search_url.isnot(None),
            RewardRank.search_url != ''
        ).order_by(RewardRank.reward_id).all()
        
        total_count = len(records)
        logger.info(f"[구간 태그 크롤링] reward_id {start_id}~{end_id} 구간 크롤링 대상: {total_count}개")
        
        if not records:
            logger.info(f"[구간 태그 크롤링] reward_id {start_id}~{end_id} 구간에 크롤링할 레코드가 없습니다.")
            return {
                'total': 0,
                'crawled': 0,
                'failed': 0,
                'skipped': 0
            }
        
        for idx, record in enumerate(records, 1):
            reward_id = record.reward_id
            nvmid = record.nvmid
            search_url = record.search_url
            
            logger.info(f"\n{'='*60}")
            logger.info(f"[구간 태그 크롤링] {idx}/{total_count} - reward_id={reward_id} (구간: {start_id}~{end_id})")
            logger.info(f"  nvmid: {nvmid}")
            logger.info(f"  search_url: {search_url}")
            logger.info(f"{'='*60}\n")
            
            # 데이터 검증
            if not nvmid or not nvmid.strip():
                logger.warning(f"[구간 태그 크롤링] ⚠ reward_id={reward_id}: nvmid가 없어 건너뜁니다.")
                skipped_count += 1
                continue
            
            # search_url이 없어도 nvmid만으로 크롤링 가능
            final_search_url = search_url if (search_url and search_url.strip()) else None
            if not final_search_url:
                logger.info(f"[구간 태그 크롤링] reward_id={reward_id}: search_url 없음, nvmid로 직접 접근 시도")
            
            try:
                # 태그 및 이미지 URL 크롤링 수행
                tag_value, image_url_value = crawl_image_tag(
                    nvmid=nvmid,
                    reward_id=reward_id,
                    search_url=final_search_url,
                    headless=headless
                )
                
                if tag_value or image_url_value:
                    crawled_count += 1
                    if tag_value:
                        logger.info(f"[구간 태그 크롤링] ✅ reward_id={reward_id} 태그 크롤링 완료: {tag_value}")
                    if image_url_value:
                        logger.info(f"[구간 태그 크롤링] ✅ reward_id={reward_id} 이미지 URL 크롤링 완료: {image_url_value[:100]}...")
                else:
                    logger.warning(f"[구간 태그 크롤링] ⚠️ reward_id={reward_id}: 태그 및 이미지 URL을 크롤링하지 못했습니다.")
                    failed_count += 1
                
            except Exception as e:
                logger.error(f"[구간 태그 크롤링] reward_id={reward_id} 크롤링 오류: {e}", exc_info=True)
                failed_count += 1
                continue
            
            # 마지막 항목이 아닐 때만 대기
            if idx < total_count:
                delay_time = random.uniform(delay, delay + 5)
                logger.info(f"\n[대기] 다음 크롤링까지 {delay_time:.2f}초 대기...\n")
                time.sleep(delay_time)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[구간 태그 크롤링] 완료: reward_id {start_id}~{end_id} 구간")
        logger.info(f"  전체: {total_count}개")
        logger.info(f"  성공: {crawled_count}개")
        logger.info(f"  실패: {failed_count}개")
        logger.info(f"  건너뜀: {skipped_count}개")
        logger.info(f"{'='*60}\n")
        
    except Exception as e:
        logger.error(f"[구간 태그 크롤링] 오류: {e}", exc_info=True)
    finally:
        db.close()
    
    return {
        'total': total_count,
        'crawled': crawled_count,
        'failed': failed_count,
        'skipped': skipped_count
    }


# Admin 권한 체크 함수
def check_admin_permission(current_user: dict, db: Session):
    """admin 권한 체크"""
    username = current_user.get("username")
    user = db.query(UsersAdmin).filter(UsersAdmin.username == username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다."
        )
    
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다."
        )
    
    return user


# ==================== 요청/응답 모델 ====================

class KeywordExtractRequest(BaseModel):
    keyword: str  # 검색할 키워드 (띄어쓰기로 구분)
    nvmid: str  # 찾을 상품의 nvmid
    count: int  # 추출할 메인키워드 개수 (10, 20, 30, 50)
    product_url: Optional[str] = None  # 상품 URL (선택)


class KeywordExtractResponse(BaseModel):
    success: bool
    message: str
    data: dict


# ==================== API 엔드포인트 ====================

@router.post("/extract")
async def extract_main_keywords(
    request: KeywordExtractRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    메인키워드 추출 API
    키워드 조합을 생성하고 순위를 조회한 후, 상위 N개를 랜덤으로 선택하여 reward_target 테이블에 저장
    (상세 정보 추출은 스케줄러에서 처리하여 reward_rank에 저장)
    
    Args:
        request: 키워드 추출 요청 (keyword, nvmid, count)
    
    Returns:
        추출된 메인키워드 리스트
    """
    # 관리자 권한 체크
    check_admin_permission(current_user, db)
    
    # count 검증 (10, 20, 30, 50만 허용)
    if request.count not in [10, 20, 30, 50]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="count는 10, 20, 30, 50 중 하나여야 합니다."
        )
    
    try:
        # 1. 키워드 분리 및 조합 생성
        words = split_keywords_by_space(request.keyword)
        if len(words) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="키워드는 최소 2개 단어 이상이어야 합니다."
            )
        
        keyword_combinations = generate_keyword_combinations(words, min_length=2, max_length=len(words))
        
        if not keyword_combinations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="키워드 조합을 생성할 수 없습니다."
            )
        
        # 2. 각 조합 키워드로 순위 조회 (요청한 개수의 2배 정도만 조회하여 충분한 후보 확보)
        keyword_rank_results = []
        
        # 요청한 개수의 2배 정도만 조회 (상위 N개를 확보하기 위해 여유있게 조회)
        # 순위가 없는 키워드가 있을 수 있으므로 여유있게 조회
        max_check_count = min(request.count * 2, len(keyword_combinations))
        
        for idx, combo_keyword in enumerate(keyword_combinations[:max_check_count], 1):
            try:
                # API로 순위 조회 (최대 1000등까지)
                rank = get_api_rank_by_keyword(combo_keyword, request.nvmid, max_rank=1000)
                
                if rank:  # 순위가 있는 키워드만 저장
                    keyword_rank_results.append({
                        "keyword": combo_keyword,
                        "rank": rank
                    })
                    
                    # 요청한 개수만큼 순위가 있는 키워드를 찾았으면 더 이상 조회하지 않음
                    if len(keyword_rank_results) >= request.count:
                        break
                
                # API 호출 간격
                import time
                time.sleep(0.5)
                
            except Exception as e:
                # 개별 키워드 조회 실패는 무시하고 계속 진행
                continue
        
        if not keyword_rank_results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="순위가 있는 키워드를 찾을 수 없습니다."
            )
        
        # 3. 순위가 있는 키워드 중에서 앞에서부터 N개 선택
        # 순위가 낮을수록(숫자가 작을수록) 우선순위가 높으므로 정렬
        keyword_rank_results.sort(key=lambda x: x["rank"])
        
        # 요청한 개수만큼 앞에서부터 순서대로 선택 (순위가 있는 키워드가 부족하면 모두 선택)
        selected_count = min(request.count, len(keyword_rank_results))
        selected_keywords = keyword_rank_results[:selected_count]  # 랜덤이 아닌 순서대로 선택
        
        # 3-1. 선택된 키워드들의 통검 노출여부와 CPC 여부 조회 (병렬 처리)
        selected_keyword_list = [s["keyword"] for s in selected_keywords]
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"선택된 {len(selected_keyword_list)}개 키워드에 대해 통검 노출여부와 CPC 조회 시작")
        
        exposure_results = []
        try:
            # 통검 노출여부와 CPC 조회 (병렬 처리, headless=True로 빠르게)
            exposure_results = check_exposure_and_cpc_for_keywords(
                keywords=selected_keyword_list,
                nvmid=request.nvmid,
                headless=True,
                max_workers=min(10, len(selected_keyword_list))  # 최대 10개 브라우저 병렬
            )
            logger.info(f"통검 노출여부와 CPC 조회 완료: {len(exposure_results)}개 결과")
        except Exception as e:
            logger.error(f"통검 노출여부와 CPC 조회 중 오류 발생: {e}", exc_info=True)
            # 오류 발생 시 모든 키워드에 대해 False로 설정
            exposure_results = [
                {"keyword": kw, "is_shopping_exposed": False, "cpc": False, "error": str(e)}
                for kw in selected_keyword_list
            ]
        
        # 키워드별 통검 노출여부와 CPC 결과를 딕셔너리로 변환 (빠른 조회용)
        exposure_dict = {
            result["keyword"]: {
                "is_shopping_exposed": bool(result.get("is_shopping_exposed", False)),
                "cpc": bool(result.get("cpc", False))
            }
            for result in exposure_results
        }
        
        # 4. 통검 노출된 키워드들을 reward_target 테이블에 저장
        # (상세 정보 추출은 스케줄러에서 처리하여 reward_rank에 저장)
        saved_rewards = []
        
        # 같은 nvmid의 기존 키워드들 조회 (acq 파라미터용)
        existing_keywords = db.query(RewardTarget.keyword).filter(
            RewardTarget.keyword.isnot(None),
            RewardTarget.keyword != ''
        ).all()
        existing_keyword_list = [kw[0] for kw in existing_keywords if kw[0]]
        
        # 현재 저장할 키워드들도 리스트에 추가
        all_available_keywords = existing_keyword_list + [s["keyword"] for s in selected_keywords]
        
        import logging
        logger = logging.getLogger(__name__)
        
        for selected in selected_keywords:
            keyword = selected["keyword"]
            rank = selected["rank"]
            
            try:
                # 통검 노출여부와 CPC 여부 가져오기
                exposure_info = exposure_dict.get(keyword, {"is_shopping_exposed": False, "cpc": False})
                is_shopping_exposed = exposure_info["is_shopping_exposed"]
                cpc = exposure_info["cpc"]
                
                # 통검 노출된 키워드만 reward_target에 저장
                # if is_shopping_exposed:  # 주석처리: 통검 노출 여부와 관계없이 모든 키워드 저장
                # search_url 생성 (네이버 모바일 검색 URL 형식)
                # acq는 저장된 키워드 중 랜덤 선택 (현재 키워드 포함)
                search_url = generate_search_url(keyword, all_available_keywords)
                
                # 중복 체크 (같은 nvmid와 keyword 조합이 이미 있는지 확인)
                # existing_target = db.query(RewardTarget).filter(
                #     RewardTarget.keyword == keyword,
                #     RewardTarget.nvmid == request.nvmid,
                #     RewardTarget.product_url == (request.product_url or "")
                # ).first()
                
                # if not existing_target:  # 주석처리: 이미 존재하는 키워드도 저장
                try:
                    # reward_target 테이블에 저장 (키워드, nvmid, search_url, product_url)
                    # reward_target_id는 auto increment이므로 제거
                    reward_target = RewardTarget(
                        keyword=keyword,
                        nvmid=request.nvmid,
                        search_url=search_url,
                        product_url=request.product_url or ""
                    )
                    
                    db.add(reward_target)
                    db.flush()  # ID를 얻기 위해 flush
                    
                    # reward_target_id는 flush 후 자동 생성됨
                    reward_target_id = reward_target.reward_target_id
                    
                    # 개별 커밋 (롤백 문제 방지)
                    db.commit()
                    
                    logger.info(f"[reward_target] 키워드 저장: {keyword} (reward_target_id: {reward_target_id}, nvmid: {request.nvmid}, search_url 길이: {len(search_url)})")
                    
                    # 저장된 키워드 리스트에 추가 (다음 키워드의 acq 선택에 사용)
                    all_available_keywords.append(keyword)
                    
                    saved_rewards.append({
                        "reward_target_id": reward_target_id,
                        "keyword": keyword,
                        "rank": rank,
                        "search_url": search_url,
                        "nvmid": request.nvmid,
                        "product_url": request.product_url or "",
                        "is_shopping_exposed": is_shopping_exposed,  # 통검 노출여부 (boolean)
                        "cpc": cpc  # CPC 여부 (boolean)
                    })
                except Exception as e:
                    # 개별 키워드 저장 실패 시 롤백 후 계속 진행
                    db.rollback()
                    logger.error(f"[reward_target] 키워드 '{keyword}' 저장 실패: {e}, search_url 길이: {len(search_url)}", exc_info=True)
                    
                    # search_url이 너무 긴 경우 acq 없이 재시도
                    if "Data too long" in str(e) or len(search_url) > 2000:
                        try:
                            search_url_short = generate_search_url(keyword, [])  # acq 없이 생성
                            reward_target = RewardTarget(
                                keyword=keyword,
                                nvmid=request.nvmid,
                                search_url=search_url_short,
                                product_url=request.product_url or ""
                            )
                            db.add(reward_target)
                            db.flush()
                            reward_target_id = reward_target.reward_target_id
                            db.commit()  # 재시도 시 즉시 커밋
                            
                            logger.info(f"[reward_target] 짧은 search_url로 재시도 성공: {keyword} (reward_target_id: {reward_target_id})")
                            
                            all_available_keywords.append(keyword)
                            
                            saved_rewards.append({
                                "reward_target_id": reward_target_id,
                                "keyword": keyword,
                                "rank": rank,
                                "search_url": search_url_short,
                                "nvmid": request.nvmid,
                                "product_url": request.product_url or "",
                                "is_shopping_exposed": is_shopping_exposed,
                                "cpc": cpc
                            })
                        except Exception as e2:
                            db.rollback()
                            logger.error(f"[reward_target] 재시도도 실패: {keyword}, 오류: {e2}")
                    continue
                # else:
                #     logger.info(f"[reward_target] 이미 존재하는 키워드 스킵: {keyword}")  # 주석처리
                # else:
                #     logger.info(f"[reward_target] 통검 노출되지 않은 키워드 스킵: {keyword} (is_shopping_exposed: {is_shopping_exposed})")  # 주석처리
                
            except Exception as e:
                logger.error(f"[reward_target] 키워드 '{keyword}' 처리 중 오류: {e}", exc_info=True)
                db.rollback()  # 오류 발생 시 롤백
                continue
        
        return {
            "success": True,
            "message": f"{len(saved_rewards)}개의 통검 노출 키워드가 reward_target에 저장되었습니다. (상세 정보는 스케줄러에서 처리됩니다.)",
            "data": {
                "count": len(saved_rewards),
                "rewards": saved_rewards
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"메인키워드 추출 중 오류가 발생했습니다: {str(e)}"
        )


