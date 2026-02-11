"""
RewardLink 테이블의 각 제품에 대해
통검 노출여부, 광고여부를 체크하고 업데이트 (단일 방식)
브라우저 풀 + 병렬 처리로 성능 향상
search_url 생성 및 sellution_rank3 로직 적용
"""
import logging
import time
import sys
import os
import random
import string
import re
from typing import Dict, Optional
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# 상위 디렉토리 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import RewardLink, RewardLinkKeyword, RandomAcq, RewardRank
from sellution_rank3 import BrowserPool

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

global_keywords = [
    '추천',
    '비교',
    '순위',
    '가성비',
    '최저가',
    '인기',
    '판매',
    '할인',
    '세일'
]

def generate_ackey(length: int = 8) -> str:
    """영문숫자 8글자 랜덤 문자열 생성"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_acr() -> int:
    """0~10 사이 랜덤 숫자"""
    return random.randint(0, 10)


def generate_short_code(length: int = 11) -> str:
    """
    짧은 링크 코드 생성 (영문+숫자)
    
    Args:
        length: 코드 길이 (기본값: 11)
    
    Returns:
        str: 생성된 short_code
    """
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def split_keywords_by_space(keyword: str) -> list:
    """
    키워드를 띄어쓰기로 나누어 단어 리스트 반환
    
    Args:
        keyword: 띄어쓰기로 구분된 키워드 문자열
    
    Returns:
        list: 단어 리스트
    """
    if not keyword:
        return []
    
    words = re.split(r'\s+', keyword.strip())
    words = [w for w in words if w]
    
    logger.info(f"키워드 분리: '{keyword}' → {words} ({len(words)}개 단어)")
    return words


def generate_keyword_combinations(words: list, min_length: int = 2, max_length: int = None) -> list:
    """
    단어 리스트에서 순차 조합 생성 (2단어 -> 3단어 -> ... -> max_length 단어)
    
    Args:
        words: 단어 리스트
        min_length: 최소 조합 길이 (기본값: 2)
        max_length: 최대 조합 길이 (None이면 words 길이)
    
    Returns:
        list: 조합된 키워드 문자열 리스트 (길이 순서대로 정렬)
    """
    if not words:
        return []
    
    if max_length is None:
        max_length = len(words)
    
    max_length = min(max_length, len(words))
    combinations_list = []
    
    # 2단어 조합부터 max_length 단어 조합까지
    for length in range(min_length, max_length + 1):
        # 길이에 맞는 모든 조합 생성
        for combo in combinations(range(len(words)), length):
            # 조합된 인덱스로 단어 조합
            combo_words = [words[i] for i in combo]
            combo_keyword = ' '.join(combo_words)
            combinations_list.append(combo_keyword)
    
    logger.info(f"키워드 조합 생성: {len(words)}개 단어 → {len(combinations_list)}개 조합 (길이 {min_length}~{max_length})")
    return combinations_list


def get_random_acq_from_db(db) -> Optional[str]:
    """random_acq 테이블에서 랜덤으로 ACQ 가져오기 (모든 데이터를 활성화된 것으로 간주)"""
    try:
        # adj_word 필터 제거 - 모든 레코드 조회
        acq_records = db.query(RandomAcq).all()
        
        if not acq_records:
            logger.warning("random_acq 테이블에 데이터가 없습니다.")
            return None
        
        selected_acq = random.choice(acq_records)
        # acq_word 반환
        logger.info(f"랜덤 ACQ 선택: {selected_acq.acq_word}")
        return selected_acq.acq_word
        
    except Exception as e:
        logger.error(f"random_acq 조회 중 오류: {e}", exc_info=True)
        return None


def create_search_url(query: str, acq: str, ackey: str = None, acr: int = None) -> str:
    """
    search_url 생성
    
    Args:
        query: 검색 쿼리 (query_keyword)
        acq: ACQ 파라미터 (random_acq 테이블에서 가져온 값)
        ackey: ackey (없으면 자동 생성)
        acr: acr (없으면 자동 생성)
    
    Returns:
        str: 생성된 search_url
    """
    if not ackey:
        ackey = generate_ackey()
    if acr is None:
        acr = generate_acr()
    
    encoded_query = quote(query)
    encoded_acq = quote(acq) if acq else ''
    
    url = (
        f"https://m.search.naver.com/search.naver?"
        f"sm=mtp_sug.top&"
        f"where=m&"
        f"query={encoded_query}&"
        f"ackey={ackey}&"
        f"acq={encoded_acq}&"
        f"acr={acr}&"
        f"qdt=0"
    )
    
    logger.info(f"[URL 생성] query='{query}', acq='{acq}' → {url[:100]}...")
    return url


def update_search_url_acq(existing_url: str, new_acq: str) -> str:
    """
    기존 search_url에서 acq 파라미터만 교체
    
    Args:
        existing_url: 기존 search_url (RewardLink.reward_link에서 가져온 값)
        new_acq: 새로운 acq 값
    
    Returns:
        str: acq가 교체된 새로운 search_url
    """
    try:
        # URL 파싱
        parsed = urlparse(existing_url)
        query_params = parse_qs(parsed.query)
        
        # acq 파라미터 교체
        query_params['acq'] = [new_acq]
        
        # URL 인코딩 (리스트를 문자열로 변환)
        new_query = urlencode(query_params, doseq=True)
        
        # 새로운 URL 생성
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        
        logger.info(f"[URL ACQ 교체] 기존 URL: {existing_url[:100]}..., 새 acq: {new_acq} → {new_url[:100]}...")
        return new_url
        
    except Exception as e:
        logger.error(f"URL ACQ 교체 실패: {e}", exc_info=True)
        # 실패 시 기존 URL 반환
        return existing_url


def check_shopping_exposure_and_cpc(search_url: str, nvmid: str, browser_pool: BrowserPool) -> Dict:
    """
    통검 노출 및 CPC 검사 (브라우저 풀 사용, sellution_rank3 로직)
    
    Args:
        search_url: 생성된 search_url
        nvmid: 네이버 상품 ID
        browser_pool: BrowserPool 인스턴스
    
    Returns:
        dict: {
            'is_shopping_exposed': bool,
            'cpc': bool
        }
    """
    result = {
        'is_shopping_exposed': False,
        'cpc': False
    }
    
    try:
        logger.info(f"통검/CPC 검사: search_url='{search_url[:100]}...', nvmid='{nvmid}'")
        
        # 브라우저 풀에서 브라우저 가져오기
        with browser_pool.get_browser() as driver:
            # 페이지 로드 (최소한의 렌더링)
            driver.get(search_url)
            
            # 페이지 로딩 대기 최소화 (2초 → 1초)
            time.sleep(1)
            
            # 페이지 준비 상태 확인 최소화 (5초 → 2초)
            try:
                WebDriverWait(driver, 2).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception as e:
                logger.debug(f"페이지 로딩 대기 중 오류 (계속 진행): {e}")
            
            # 검색 결과에서 nvmid 찾기 (최소한의 렌더링)
            try:
                found_nvmid = False
                is_ad = False
                target_nvmid = str(nvmid).strip()
                
                # 첫 페이지에서만 확인 (스크롤 최소화)
                scroll_attempts = 0
                max_scroll_attempts = 1  # 2번 → 1번으로 최소화
                
                while scroll_attempts < max_scroll_attempts:
                    # 현재 페이지에서 nvmid 찾기
                    all_links = driver.find_elements(By.CSS_SELECTOR, 'a[aria-labelledby^="view_type_guide_"]')
                    
                    for link in all_links:
                        try:
                            aria_id = link.get_attribute('aria-labelledby')
                            if aria_id and aria_id.startswith('view_type_guide_'):
                                extracted_nvmid = aria_id.replace('view_type_guide_', '')
                                
                                if extracted_nvmid == target_nvmid:
                                    found_nvmid = True
                                    
                                    # 광고 여부 확인 (주석 처리 - 나중에 적용)
                                    # try:
                                    #     parent_li = link.find_element(By.XPATH, './ancestor::li[1]')
                                    #     
                                    #     # 방법 1: pbjVN80V 클래스 확인
                                    #     try:
                                    #         parent_li.find_element(By.CSS_SELECTOR, '.pbjVN80V')
                                    #         is_ad = True
                                    #     except:
                                    #         pass
                                    #     
                                    #     # 방법 2: SucLwbaS 클래스 확인
                                    #     if not is_ad:
                                    #         try:
                                    #             parent_li.find_element(By.CSS_SELECTOR, 'a.SucLwbaS')
                                    #             is_ad = True
                                    #         except:
                                    #             pass
                                    #     
                                    #     # 방법 3: "광고" 텍스트를 가진 blind 클래스 span 확인
                                    #     if not is_ad:
                                    #         try:
                                    #             blind_spans = parent_li.find_elements(By.CSS_SELECTOR, 'span.blind')
                                    #             for span in blind_spans:
                                    #                 if '광고' in span.text:
                                    #                     is_ad = True
                                    #                     break
                                    #         except:
                                    #             pass
                                    # except Exception as e:
                                    #     logger.debug(f"광고 여부 확인 중 오류: {e}")
                                    
                                    break  # nvmid를 찾았으므로 즉시 종료
                        except Exception as e:
                            logger.debug(f"링크 처리 중 오류: {e}")
                            continue
                    
                    if found_nvmid:
                        break  # 찾으면 스크롤 중단
                    
                    # 스크롤 (최소화: 1번만, 대기 시간 단축)
                    if scroll_attempts < max_scroll_attempts - 1:  # 마지막이 아니면만 스크롤
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(1)  # 1.5초 → 1초로 단축
                    
                    scroll_attempts += 1
                
                result['is_shopping_exposed'] = found_nvmid
                result['cpc'] = is_ad  # 광고 체크 주석 처리로 항상 False
                
                if found_nvmid:
                    logger.info(f"✓ 통검 노출={found_nvmid}, CPC={is_ad} (대상 nvmid: {nvmid})")
                else:
                    logger.info(f"✗ 통검 노출 없음 (대상 nvmid: {nvmid})")
                    
            except Exception as e:
                logger.error(f"nvmid 검색 중 예외 발생: {e}", exc_info=True)
                result['is_shopping_exposed'] = False
                result['cpc'] = False
        
    except Exception as e:
        logger.error(f"통검/CPC 검사 중 오류: {e}", exc_info=True)
        
        # 연결 오류인지 확인
        error_str = str(e).lower()
        if 'connection' in error_str or 'connect' in error_str or '10061' in error_str or 'newconnectionerror' in error_str:
            logger.error("=== ChromeDriver 연결 오류 ===")
            logger.error(f"search_url: {search_url[:100]}...")
            logger.error(f"nvmid: {nvmid}")
            logger.error(f"오류 타입: {type(e).__name__}")
            logger.error(f"오류 메시지: {str(e)}")
            logger.error("통검 검사 실패로 인해 is_shopping_exposed=False로 설정됩니다.")
    
    return result


def get_existing_keywords_batch(link_id: int, query_keywords: list, db) -> set:
    """
    이미 존재하는 키워드를 한 번에 조회 (DB 쿼리 최적화)
    
    Args:
        link_id: link_id
        query_keywords: 조회할 키워드 리스트
        db: DB 세션
    
    Returns:
        set: 이미 존재하는 키워드 set
    """
    if not query_keywords:
        return set()
    
    existing = db.query(RewardLinkKeyword.query_keyword).filter(
        RewardLinkKeyword.link_id == link_id,
        RewardLinkKeyword.query_keyword.in_(query_keywords)
    ).all()
    
    return {kw[0] for kw in existing}


def check_rank_by_openapi(keyword: str, nvmid: str, account_index: int = None) -> Optional[Dict]:
    """
    openapi로 키워드 순위 조회 (3위 이내만 반환, image 포함)
    
    Args:
        keyword: 검색 키워드
        nvmid: 찾을 상품의 nvmid
        account_index: 사용할 계정 인덱스 (0-based, None이면 랜덤)
    
    Returns:
        dict or None: {'rank': int, 'image': str} (3위 이내면 반환, 아니면 None)
    """
    try:
        from sellution_rank3 import get_api_rank_by_keyword_with_image_by_account
        
        # 최대 3위까지만 조회
        result = get_api_rank_by_keyword_with_image_by_account(
            keyword, 
            nvmid, 
            max_rank=3,
            account_index=account_index
        )
        
        if result and result.get('rank') and result['rank'] <= 3:
            image = result.get('image', '')
            logger.info(f"✓ 키워드 '{keyword}' 순위: {result['rank']}위 (3위 이내, 계정 인덱스: {account_index}), image={image[:50] if image else '없음'}...")
            return result
        else:
            rank = result.get('rank') if result else None
            logger.info(f"✗ 키워드 '{keyword}' 순위: {rank if rank else '없음'} (3위 초과로 제외)")
            return None
            
    except Exception as e:
        logger.error(f"openapi 순위조회 중 오류: {e}", exc_info=True)
        return None


def get_keywords_from_link_id(link_id: int, db) -> Optional[Dict]:
    """
    RewardLinkKeyword에서 link_id로 조회하여 query_keyword와 acq_keyword 가져오기
    
    Args:
        link_id: link_id
        db: DB 세션
    
    Returns:
        dict: {
            'nvmid': str,
            'product_name': str,
            'keywords': List[dict]  # [{'query_keyword': str, 'acq_keyword': str}, ...]
        } 또는 None
    """
    try:
        # RewardLink에서 nvmid, product_name 조회
        reward_link = db.query(RewardLink).filter(
            RewardLink.link_id == link_id,
            RewardLink.nvmid.isnot(None),
            RewardLink.nvmid != ''
        ).first()
        
        if not reward_link:
            logger.warning(f"link_id={link_id}: RewardLink를 찾을 수 없습니다.")
            return None
        
        nvmid = reward_link.nvmid
        product_name = reward_link.product_name or ''
        
        # RewardLinkKeyword에서 link_id로 조회하여 모든 키워드 가져오기
        keyword_links = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link_id,
            RewardLinkKeyword.query_keyword.isnot(None),
            RewardLinkKeyword.query_keyword != ''
        ).all()
        
        if not keyword_links:
            logger.warning(f"link_id={link_id}: RewardLinkKeyword를 찾을 수 없습니다.")
            return None
        
        keywords = []
        for kl in keyword_links:
            keywords.append({
                'query_keyword': kl.query_keyword,
                'acq_keyword': kl.acq_keyword if kl.acq_keyword else None
            })
        
        logger.info(f"link_id={link_id}: {len(keywords)}개 키워드 조회 성공")
        
        return {
            'nvmid': nvmid,
            'product_name': product_name,
            'keywords': keywords
        }
        
    except Exception as e:
        logger.error(f"link_id={link_id} 키워드 조회 중 오류: {e}", exc_info=True)
        return None


def get_non_ad_image_url_via_browser(nvmid: str, keyword: str, browser_pool: BrowserPool) -> Optional[str]:
    """
    브라우저를 통해 nvmid로 검색하여 광고가 아닌 상품의 이미지 URL 가져오기
    
    Args:
        nvmid: 네이버 상품 ID
        keyword: 검색 키워드
        browser_pool: BrowserPool 인스턴스
    
    Returns:
        str or None: 이미지 URL (없으면 None)
    """
    try:
        logger.info(f"브라우저로 광고가 아닌 상품 이미지 URL 조회: nvmid={nvmid}, keyword={keyword}")
        
        # 검색 URL 생성
        encoded_keyword = quote(keyword)
        search_url = f"https://m.search.naver.com/search.naver?where=m&query={encoded_keyword}"
        
        target_nvmid = str(nvmid).strip()
        
        # 브라우저 풀에서 브라우저 가져오기
        with browser_pool.get_browser() as driver:
            driver.get(search_url)
            time.sleep(2)
            
            # 페이지 준비 상태 확인
            try:
                WebDriverWait(driver, 5).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception as e:
                logger.debug(f"페이지 로딩 대기 중 오류 (계속 진행): {e}")
            
            # JavaScript로 광고가 아닌 상품 찾기
            find_image_script = f"""
            (function() {{
                var targetNvmid = "{target_nvmid}";
                var allLinks = document.querySelectorAll('a[aria-labelledby^="view_type_guide_"]');
                
                for (var i = 0; i < allLinks.length; i++) {{
                    var link = allLinks[i];
                    var ariaId = link.getAttribute('aria-labelledby');
                    
                    if (ariaId && ariaId.startsWith('view_type_guide_')) {{
                        var extractedNvmid = ariaId.replace('view_type_guide_', '');
                        
                        if (extractedNvmid === targetNvmid) {{
                            // 광고 여부 확인
                            var parentLi = link.closest('li');
                            if (parentLi) {{
                                // 광고 태그 확인
                                var hasAdClass = parentLi.querySelector('.pbjVN80V') || 
                                                parentLi.querySelector('a.SucLwbaS');
                                
                                // "광고" 텍스트 확인
                                var blindSpans = parentLi.querySelectorAll('span.blind');
                                var hasAdText = false;
                                for (var j = 0; j < blindSpans.length; j++) {{
                                    if (blindSpans[j].textContent.includes('광고')) {{
                                        hasAdText = true;
                                        break;
                                    }}
                                }}
                                
                                // 광고가 아닌 경우에만 이미지 URL 반환
                                if (!hasAdClass && !hasAdText) {{
                                    // 이미지 찾기
                                    var img = parentLi.querySelector('img');
                                    if (img && img.src) {{
                                        return img.src;
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
                return null;
            }})();
            """
            
            image_url = driver.execute_script(find_image_script)
            
            if image_url:
                logger.info(f"✓ 브라우저로 광고가 아닌 상품 이미지 URL 찾음: nvmid={nvmid}, image_url={image_url[:100]}...")
                return image_url
            else:
                logger.warning(f"브라우저로 광고가 아닌 상품 이미지 URL을 찾을 수 없음: nvmid={nvmid}")
                return None
                
    except Exception as e:
        logger.error(f"브라우저 이미지 URL 조회 중 오류: {e}", exc_info=True)
        return None


def update_reward_rank_image_url(nvmid: str, image_url: str, db):
    """
    RewardRank 테이블의 image_url 업데이트 (nvmid로 찾기)
    
    Args:
        nvmid: 네이버 상품 ID
        image_url: 업데이트할 이미지 URL
        db: DB 세션
    """
    try:
        # nvmid로 RewardRank 찾기 (여러 개일 수 있으므로 모두 업데이트)
        reward_ranks = db.query(RewardRank).filter(
            RewardRank.nvmid == nvmid
        ).all()
        
        if reward_ranks:
            updated_count = 0
            for reward_rank in reward_ranks:
                reward_rank.image_url = image_url
                updated_count += 1
            
            db.commit()
            logger.info(f"RewardRank image_url 업데이트 완료: nvmid={nvmid}, 업데이트된 레코드 수={updated_count}, image_url={image_url[:100]}...")
        else:
            logger.warning(f"RewardRank에서 nvmid={nvmid}에 해당하는 레코드를 찾을 수 없습니다.")
            
    except Exception as e:
        db.rollback()
        logger.error(f"RewardRank image_url 업데이트 실패: nvmid={nvmid}, error={e}", exc_info=True)
        raise


def update_reward_link_exposure(link_id: int, search_url: str, query_keyword: str, is_shopping_exposed: bool, cpc: bool, image_url: Optional[str], db):
    """
    RewardLink 테이블 업데이트 (통검 노출 여부, query_keyword, image_url 업데이트)
    
    Args:
        link_id: link_id
        search_url: 생성된 search_url
        query_keyword: query_keyword
        is_shopping_exposed: 통검 노출 여부
        cpc: CPC 여부 (체크는 하지만 저장하지 않음, 나중에 처리할 예정)
        image_url: 상품 이미지 URL (순위 3위 이내일 때 OpenAPI에서 가져온 값)
        db: DB 세션
    """
    try:
        reward_link = db.query(RewardLink).filter(
            RewardLink.link_id == link_id
        ).first()
        
        if reward_link:
            reward_link.reward_link = search_url  # search_url 업데이트
            reward_link.query_keyword = query_keyword  # query_keyword 업데이트
            reward_link.is_shopping_exposed = is_shopping_exposed
            if image_url:  # image_url이 있으면 업데이트
                reward_link.image_url = image_url
            # reward_link.cpc = cpc  # CPC는 나중에 체크할 예정이므로 주석처리
            db.commit()
            logger.info(f"link_id={link_id} 업데이트: search_url 생성, query_keyword='{query_keyword}', 통검={is_shopping_exposed}, image_url={'있음' if image_url else '없음'}")
        else:
            logger.warning(f"link_id={link_id}를 찾을 수 없습니다.")
            
    except Exception as e:
        db.rollback()
        logger.error(f"link_id={link_id} 업데이트 실패: {e}", exc_info=True)
        raise


### 주의: 이 함수는 RewardLinkKeyword가 없을 때 자동으로 생성합니다.
### 필요 없으면 삭제하세요.
def create_missing_keywords_and_search_url(link_id: int, db, browser_pool: BrowserPool) -> Dict:
    """
    RewardLinkKeyword가 없으면 product_name으로 키워드 조합 생성하여
    OpenAPI로 3위 이내 확인 후 통검 진행하여 통검 노출된 키워드만 insert
    
    ### 주의: 이 함수는 RewardLinkKeyword가 없을 때 자동으로 생성합니다.
    ### 필요 없으면 삭제하세요.
    
    로직:
    1. product_name으로 키워드 200개씩 생성
    2. 각 키워드를 OpenAPI로 순위 조회 (3위 이내만)
    3. 3위 이내인 키워드에 대해 통검/CPC 검사 (무조건 진행)
    4. 통검 노출된 키워드만 RewardLinkKeyword에 insert
    
    Args:
        link_id: link_id
        db: DB 세션
        browser_pool: BrowserPool 인스턴스 (필수, 통검 검사용)
    
    Returns:
        dict: {
            'success': bool,
            'created_keywords': int,  # 생성된 키워드 개수
            'created_search_url': bool,  # search_url 생성 여부
            'message': str
        }
    """
    try:
        # browser_pool 검증
        if browser_pool is None:
            raise ValueError("browser_pool은 필수입니다.")
        
        # random_acq 리스트를 미리 가져와서 저장 (병렬 처리 시 DB 세션 충돌 방지)
        acq_records = db.query(RandomAcq).all()
        if not acq_records:
            logger.warning("random_acq 테이블에 데이터가 없습니다.")
            return {
                'success': False,
                'created_keywords': 0,
                'created_search_url': False,
                'message': 'random_acq 데이터가 없습니다.'
            }
        acq_list = [record.acq_word for record in acq_records]
        logger.info(f"link_id={link_id}: random_acq {len(acq_list)}개 미리 로드 완료")
        
        # 1. RewardLink 조회
        reward_link = db.query(RewardLink).filter(
            RewardLink.link_id == link_id,
            RewardLink.nvmid.isnot(None),
            RewardLink.nvmid != ''
        ).first()
        
        if not reward_link:
            logger.warning(f"link_id={link_id}: RewardLink를 찾을 수 없거나 nvmid가 없습니다.")
            return {
                'success': False,
                'created_keywords': 0,
                'created_search_url': False,
                'message': 'RewardLink를 찾을 수 없거나 nvmid가 없습니다.'
            }
        
        nvmid = reward_link.nvmid
        product_name = reward_link.product_name or ''
        
        if not product_name:
            logger.warning(f"link_id={link_id}: product_name이 없습니다.")
            return {
                'success': False,
                'created_keywords': 0,
                'created_search_url': False,
                'message': 'product_name이 없습니다.'
            }
        
        # 2. 기존 RewardLinkKeyword 확인
        existing_keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link_id,
            RewardLinkKeyword.query_keyword.isnot(None),
            RewardLinkKeyword.query_keyword != ''
        ).all()
        
        if existing_keywords:
            logger.info(f"link_id={link_id}: 이미 {len(existing_keywords)}개의 RewardLinkKeyword가 존재합니다.")
            # 기존 키워드가 있으면 search_url만 확인하고 생성
            if not reward_link.reward_link:
                # 첫 번째 키워드로 search_url 생성
                first_keyword = existing_keywords[0]
                acq = first_keyword.acq_keyword if first_keyword.acq_keyword else get_random_acq_from_db(db)
                if acq:
                    search_url = create_search_url(
                        query=first_keyword.query_keyword,
                        acq=acq,
                        ackey=None,
                        acr=None
                    )
                    reward_link.reward_link = search_url
                    db.commit()
                    logger.info(f"link_id={link_id}: search_url 생성 완료")
                    return {
                        'success': True,
                        'created_keywords': 0,
                        'created_search_url': True,
                        'message': f'기존 키워드 {len(existing_keywords)}개 존재, search_url만 생성'
                    }
            return {
                'success': True,
                'created_keywords': 0,
                'created_search_url': False,
                'message': f'기존 키워드 {len(existing_keywords)}개 존재, search_url도 이미 존재'
            }
        
        # 3. product_name으로 키워드 조합 생성
        logger.info(f"link_id={link_id}: product_name='{product_name}'로 키워드 조합 생성 시작")
        words = split_keywords_by_space(product_name)
        
        if len(words) < 3:
            logger.warning(f"link_id={link_id}: product_name 단어가 3개 미만입니다: {words}")
            return {
                'success': False,
                'created_keywords': 0,
                'created_search_url': False,
                'message': f'product_name 단어가 3개 미만입니다: {words}'
            }
        
        # 키워드 조합 생성 (3단어부터 전체 단어까지, 최소 40개 이상)
        keyword_combinations = generate_keyword_combinations(words, min_length=3, max_length=len(words))
        
        if not keyword_combinations:
            logger.warning(f"link_id={link_id}: 생성된 키워드 조합이 없습니다.")
            return {
                'success': False,
                'created_keywords': 0,
                'created_search_url': False,
                'message': '생성된 키워드 조합이 없습니다.'
            }
        
        # 40개 미만이면 2단어 조합도 추가하여 40개 이상 생성
        if len(keyword_combinations) < 40:
            logger.info(f"link_id={link_id}: 키워드 조합이 {len(keyword_combinations)}개로 부족하여 2단어 조합 추가 생성")
            two_word_combinations = generate_keyword_combinations(words, min_length=2, max_length=2)
            
            # 2단어 조합을 추가하되, 중복 제거
            existing_set = set(keyword_combinations)
            for combo in two_word_combinations:
                if combo not in existing_set:
                    keyword_combinations.append(combo)
                    existing_set.add(combo)
                    if len(keyword_combinations) >= 40:
                        break
            
            logger.info(f"link_id={link_id}: 2단어 조합 추가 후 총 {len(keyword_combinations)}개 조합 생성")
        
        # 최대 200개로 제한 (200개 이상이면 200개만 사용)
        if len(keyword_combinations) > 200:
            keyword_combinations = keyword_combinations[:200]
            logger.info(f"link_id={link_id}: 키워드 조합이 200개를 초과하여 200개로 제한")
        elif len(keyword_combinations) < 40:
            logger.warning(f"link_id={link_id}: 키워드 조합이 {len(keyword_combinations)}개로 40개 미만입니다. (단어 수 부족)")
        
        logger.info(f"link_id={link_id}: 최종 {len(keyword_combinations)}개 키워드 조합 생성 완료")
        
        # 4. short_code 확인 및 생성
        if not reward_link.short_code:
            short_code = generate_short_code()
            reward_link.short_code = short_code
            logger.info(f"link_id={link_id}: short_code 생성: {short_code}")
        else:
            short_code = reward_link.short_code
        
        # 5. 각 키워드를 OpenAPI로 순위 조회 (병렬 처리) → 통검 진행 → 통검 노출된 키워드만 insert
        created_count = 0
        first_search_url = None
        rank_checked_count = 0
        exposure_checked_count = 0
        min_keywords = 40  # 최소 40개
        max_keywords = 100  # 최대 100개
        keywords_to_add = []  # Bulk insert를 위한 리스트
        
        # 5-0. 먼저 모든 키워드에 global_keyword 추가 및 필터링
        processed_base_keywords = []
        for base_keyword in keyword_combinations:
            base_keyword_no_space = base_keyword.replace(' ', '')
            if len(base_keyword_no_space) <= 10:
                processed_base_keywords.append(base_keyword)
        
        logger.info(f"link_id={link_id}: 길이 필터링 후 {len(processed_base_keywords)}개 키워드 처리 대상")
        
        # 5-0-1. 모든 query_keyword 생성 (global_keyword 포함)
        all_query_keywords = []
        for base_keyword in processed_base_keywords:
            global_keyword = random.choice(global_keywords)
            query_keyword = f"{base_keyword} {global_keyword}"
            all_query_keywords.append((base_keyword, query_keyword))
        
        # 5-1. 존재하는 키워드 한 번에 조회 (DB 쿼리 최적화)
        query_keywords_list = [qk for _, qk in all_query_keywords]
        existing_keywords = get_existing_keywords_batch(link_id, query_keywords_list, db)
        logger.info(f"link_id={link_id}: 이미 존재하는 키워드 {len(existing_keywords)}개 스킵")
        
        # 존재하지 않는 키워드만 필터링
        keywords_to_check = [(bk, qk) for bk, qk in all_query_keywords if qk not in existing_keywords]
        logger.info(f"link_id={link_id}: 처리할 키워드 {len(keywords_to_check)}개")
        
        # 계정 개수 확인 (최대 10개)
        max_accounts = 10
        
        # 5-2. OpenAPI 순위 조회 병렬 처리 (최대 20개 동시)
        def process_single_keyword_for_rank(base_keyword, query_keyword, account_index):
            """단일 키워드에 대한 OpenAPI 순위 조회 (병렬 처리용)"""
            try:
                rank_result = check_rank_by_openapi(query_keyword, nvmid, account_index=account_index)
                return {
                    'base_keyword': base_keyword,
                    'query_keyword': query_keyword,
                    'rank_result': rank_result,
                    'account_index': account_index
                }
            except Exception as e:
                logger.error(f"link_id={link_id}: query_keyword='{query_keyword}' OpenAPI 조회 중 오류: {e}", exc_info=True)
                return None
        
        rank_results = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for idx, (base_keyword, query_keyword) in enumerate(keywords_to_check):
                # 계정 인덱스 할당 (0-9 순환)
                account_index = idx % max_accounts
                
                future = executor.submit(
                    process_single_keyword_for_rank,
                    base_keyword,
                    query_keyword,
                    account_index
                )
                futures.append((future, query_keyword))
            
            # 완료된 작업 수집
            for future, query_keyword in futures:
                try:
                    result = future.result()
                    if result and result.get('rank_result'):
                        rank_results.append(result)
                        rank_checked_count += 1
                except Exception as e:
                    logger.error(f"link_id={link_id}: OpenAPI 병렬 처리 중 오류: {e}", exc_info=True)
        
        logger.info(f"link_id={link_id}: OpenAPI 병렬 처리 완료 - 3위 이내 키워드 {len(rank_results)}개 발견")
        
        # 5-3. 3위 이내 키워드만 통검 검사 (병렬 처리)
        def process_single_keyword_for_exposure(rank_data):
            """단일 키워드에 대한 통검 검사 (병렬 처리용)"""
            query_keyword = rank_data['query_keyword']
            rank_result = rank_data['rank_result']
            
            try:
                # 미리 로드한 acq_list에서 랜덤 선택 (DB 조회 없음, 세션 충돌 방지)
                acq_keyword = random.choice(acq_list) if acq_list else None
                if not acq_keyword:
                    logger.warning(f"link_id={link_id}: ACQ를 가져올 수 없어 키워드 '{query_keyword}' 건너뜀")
                    return None
                
                # search_url 생성
                search_url = create_search_url(
                    query=query_keyword,
                    acq=acq_keyword,
                    ackey=None,
                    acr=None
                )
                
                # 통검 검사
                check_result = check_shopping_exposure_and_cpc(
                    search_url=search_url,
                    nvmid=nvmid,
                    browser_pool=browser_pool
                )
                
                is_shopping_exposed = check_result.get('is_shopping_exposed', False)
                
                return {
                    'query_keyword': query_keyword,
                    'acq_keyword': acq_keyword,
                    'search_url': search_url,
                    'rank': rank_result.get('rank'),
                    'is_shopping_exposed': is_shopping_exposed
                }
            except Exception as e:
                logger.error(f"link_id={link_id}: query_keyword='{query_keyword}' 통검 검사 중 오류: {e}", exc_info=True)
                return None
        
        exposure_results = []
        browser_pool_size = getattr(browser_pool, 'pool_size', 10) if browser_pool else 10
        with ThreadPoolExecutor(max_workers=browser_pool_size) as executor:
            futures = [executor.submit(process_single_keyword_for_exposure, rank_data) for rank_data in rank_results]
            
            # 완료된 통검 검사 결과 수집
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and result.get('is_shopping_exposed'):
                        exposure_results.append(result)
                        exposure_checked_count += 1
                except Exception as e:
                    logger.error(f"link_id={link_id}: 통검 검사 병렬 처리 중 오류: {e}", exc_info=True)
        
        logger.info(f"link_id={link_id}: 통검 검사 병렬 처리 완료 - 노출된 키워드 {len(exposure_results)}개 발견")
        
        # 5-4. 통검 통과 키워드만 저장 (최대 100개)
        for exposure_data in exposure_results[:max_keywords]:
            # DB 저장 시에만 띄어쓰기를 +로 변환
            query_keyword_for_db = exposure_data['query_keyword'].replace(' ', '+')
            
            keywords_to_add.append({
                'link_id': link_id,
                'query_keyword': query_keyword_for_db,  # 띄어쓰기를 +로 변환하여 저장
                'acq_keyword': exposure_data['acq_keyword'],
                'short_code': short_code
            })
            created_count += 1
            
            if not first_search_url and not reward_link.reward_link:
                first_search_url = exposure_data['search_url']
                reward_link.reward_link = first_search_url
                logger.info(f"link_id={link_id}: 첫 번째 통검 노출된 키워드로 search_url 생성 완료")
        
        # 최소 40개 미만이고 모든 키워드를 검사했는데도 부족하면 경고
        if len(keyword_combinations) > 0 and created_count < min_keywords:
            logger.warning(f"link_id={link_id}: 통검 통과 키워드가 {created_count}개로 최소 {min_keywords}개 미만입니다. (모든 키워드 검사 완료)")
        
        # 6. Bulk insert 및 DB 커밋
        if keywords_to_add:
            try:
                db.bulk_insert_mappings(RewardLinkKeyword, keywords_to_add)
                db.commit()
                if created_count >= min_keywords:
                    logger.info(f"link_id={link_id}: 총 {len(keywords_to_add)}개 RewardLinkKeyword bulk insert 완료 (띄어쓰기를 +로 변환하여 저장, 순위 조회: {rank_checked_count}개, 통검 검사: {exposure_checked_count}개, 목표 달성: 최소 {min_keywords}개 이상)")
                else:
                    logger.warning(f"link_id={link_id}: 총 {len(keywords_to_add)}개 RewardLinkKeyword bulk insert 완료 (띄어쓰기를 +로 변환하여 저장, 순위 조회: {rank_checked_count}개, 통검 검사: {exposure_checked_count}개, 목표 미달: 최소 {min_keywords}개 미만)")
            except Exception as e:
                db.rollback()
                logger.error(f"link_id={link_id}: bulk insert 실패: {e}", exc_info=True)
                raise
        else:
            logger.warning(f"link_id={link_id}: 통검 노출된 키워드가 없어 RewardLinkKeyword를 생성하지 않았습니다.")
        
        return {
            'success': True,
            'created_keywords': created_count,
            'created_search_url': first_search_url is not None,
            'message': f'{created_count}개 키워드 생성 완료 (순위 조회: {rank_checked_count}개, 통검 검사: {exposure_checked_count}개, 목표: 최소 {min_keywords}개 이상, 최대 {max_keywords}개), search_url 생성: {first_search_url is not None}'
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"link_id={link_id} 키워드 생성 중 오류: {e}", exc_info=True)
        return {
            'success': False,
            'created_keywords': 0,
            'created_search_url': False,
            'message': f'오류 발생: {str(e)}'
        }


def process_single_link(reward_link: RewardLink, browser_pool: BrowserPool = None) -> Dict:
    """
    단일 RewardLink 처리 (병렬 처리용)
    
    Args:
        reward_link: RewardLink 인스턴스
        browser_pool: BrowserPool 인스턴스 (None이면 자동 생성)
    
    Returns:
        dict: {
            'link_id': int,
            'success': bool,
            'is_shopping_exposed': bool,
            'cpc': bool,
            'processed_keywords': List[dict],  # 처리된 키워드 목록
            'error': str (optional)
        }
    """
    db = SessionLocal()
    result = {
        'link_id': reward_link.link_id,
        'success': False,
        'is_shopping_exposed': False,
        'cpc': False,
        'processed_keywords': []  # 처리된 키워드 목록
    }
    
    # browser_pool이 없으면 생성 (이 함수에서만 사용)
    created_browser_pool = False
    if browser_pool is None:
        logger.info(f"link_id={reward_link.link_id}: browser_pool이 없어 새로 생성합니다.")
        browser_pool = BrowserPool(pool_size=1, headless=True)
        browser_pool.initialize()
        created_browser_pool = True
    
    try:
        ### 주의: RewardLinkKeyword가 없으면 자동 생성
        create_result = create_missing_keywords_and_search_url(reward_link.link_id, db, browser_pool)
        if not create_result['success']:
            logger.warning(f"link_id={reward_link.link_id}: 키워드 생성 실패: {create_result['message']}")
            result['error'] = create_result['message']
            db.close()
            return result
        logger.info(f"link_id={reward_link.link_id}: 키워드 생성 결과: {create_result['message']}")
        
        # RewardLink에서 기존 search_url 가져오기
        existing_search_url = reward_link.reward_link
        
        if not existing_search_url:
            logger.warning(f"link_id={reward_link.link_id}: 기존 search_url(reward_link)이 없습니다. 건너뜁니다.")
            result['error'] = '기존 search_url 없음'
            db.close()
            return result
        
        # RewardLinkKeyword에서 link_id로 조회하여 키워드 정보 가져오기
        keyword_info = get_keywords_from_link_id(reward_link.link_id, db)
        
        if not keyword_info:
            logger.warning(f"link_id={reward_link.link_id}: 키워드 정보를 찾을 수 없습니다. 건너뜁니다.")
            result['error'] = '키워드 정보 없음'
            db.close()
            return result
        
        nvmid = keyword_info['nvmid']
        product_name = keyword_info.get('product_name', '')
        keywords = keyword_info['keywords']  # [{'query_keyword': str, 'acq_keyword': str}, ...]
        
        logger.info(f"link_id={reward_link.link_id}: 총 {len(keywords)}개 키워드 처리 시작")
        
        # (1) product_name과 nvmid로 먼저 순위조회 (참고용)
        if product_name:
            logger.info(f"link_id={reward_link.link_id}: product_name='{product_name}'로 순위조회 시작 (참고용)")
            product_name_rank_result = check_rank_by_openapi(product_name, nvmid)
            if product_name_rank_result is None:
                logger.info(f"link_id={reward_link.link_id}: product_name으로 순위조회 결과 3위 초과 또는 없음")
        
        # (2) 각 키워드를 순차적으로 처리
        reward_link_update = None  # 업데이트 정보 저장 (첫 번째 성공한 것만)
        
        for idx, keyword_data in enumerate(keywords, 1):
            query_keyword = keyword_data['query_keyword']
            acq_keyword = keyword_data['acq_keyword']
            
            logger.info(f"link_id={reward_link.link_id}: [{idx}/{len(keywords)}] query_keyword='{query_keyword}' 처리 중")
            
            # 이미 업데이트 정보가 저장되어 있으면 통검 체크 및 업데이트 건너뜀
            if reward_link_update is not None:
                logger.info(f"link_id={reward_link.link_id}: 이미 업데이트 정보가 저장되어 있어 query_keyword='{query_keyword}' 통검 체크 및 업데이트 건너뜀")
                result['processed_keywords'].append({
                    'keyword': query_keyword,
                    'rank': None,
                    'skipped': True,
                    'reason': '이미 업데이트됨'
                })
                continue  # 다음 키워드로
            
            # 순위조회 (순위와 image 함께 반환)
            rank_result = check_rank_by_openapi(query_keyword, nvmid)
            
            # 3위 이내인 경우만 통검/CPC 검사 진행
            if rank_result is None:
                logger.info(f"link_id={reward_link.link_id}: query_keyword='{query_keyword}' 순위 3위 초과, 다음 키워드로")
                result['processed_keywords'].append({
                    'keyword': query_keyword,
                    'rank': None,
                    'skipped': True,
                    'reason': '순위 3위 초과'
                })
                continue  # 다음 키워드로
            
            # 순위와 image 추출
            query_keyword_rank = rank_result.get('rank')
            image_url = rank_result.get('image', '') or None
            
            # 3위 이내인 경우 통검/CPC 검사 진행
            logger.info(f"link_id={reward_link.link_id}: query_keyword='{query_keyword}' 순위 {query_keyword_rank}위 확인, 통검/CPC 검사 진행")
            
            # acq_keyword가 없으면 랜덤 ACQ 사용
            if not acq_keyword:
                logger.warning(f"link_id={reward_link.link_id}: acq_keyword가 없습니다. 랜덤 ACQ 사용.")
                acq = get_random_acq_from_db(db)
                if not acq:
                    logger.warning(f"link_id={reward_link.link_id}: ACQ를 가져올 수 없습니다.")
                    result['processed_keywords'].append({
                        'keyword': query_keyword,
                        'rank': query_keyword_rank,
                        'skipped': True,
                        'reason': 'ACQ 없음'
                    })
                    continue
            else:
                acq = acq_keyword
            
            # 기존 search_url에서 acq만 교체하여 새로운 search_url 생성
            search_url = update_search_url_acq(existing_search_url, acq)
            
            # 통검/CPC 검사 (브라우저 풀 사용, sellution_rank3 로직)
            check_result = check_shopping_exposure_and_cpc(
                search_url=search_url,
                nvmid=nvmid,
                browser_pool=browser_pool
            )
            
            # 통검 노출된 경우, 첫 번째 것만 저장
            if check_result['is_shopping_exposed']:
                reward_link_update = {
                    'link_id': reward_link.link_id,
                    'search_url': search_url,
                    'query_keyword': query_keyword,
                    'is_shopping_exposed': True,
                    'image_url': image_url,
                    'rank': query_keyword_rank
                }
                logger.info(f"link_id={reward_link.link_id}: 통검 노출 확인, 업데이트 정보 저장 (query_keyword='{query_keyword}')")
                logger.info(f"link_id={reward_link.link_id}: 이후 키워드들은 통검 체크 및 업데이트를 건너뜁니다.")
            
            result['processed_keywords'].append({
                'keyword': query_keyword,
                'rank': query_keyword_rank,
                'is_shopping_exposed': check_result['is_shopping_exposed'],
                'cpc': check_result['cpc'],  # 체크는 하지만 저장하지 않음
                'image_url': image_url,  # OpenAPI에서 가져온 image_url
                'skipped': False
            })
            
            logger.info(f"link_id={reward_link.link_id}: query_keyword='{query_keyword}' 처리 완료 (통검={check_result['is_shopping_exposed']})")
        
        # 모든 키워드 처리 완료 후, bulk update (한 번만)
        if reward_link_update:
            try:
                db.bulk_update_mappings(
                    RewardLink,
                    [{
                        'link_id': reward_link_update['link_id'],
                        'reward_link': reward_link_update['search_url'],
                        'query_keyword': reward_link_update['query_keyword'],
                        'is_shopping_exposed': reward_link_update['is_shopping_exposed'],
                        'image_url': reward_link_update.get('image_url')
                    }]
                )
                db.commit()
                logger.info(f"link_id={reward_link.link_id}: RewardLink bulk update 완료 (query_keyword='{reward_link_update['query_keyword']}', 통검=True)")
                
                result['success'] = True
                result['is_shopping_exposed'] = True
            except Exception as e:
                db.rollback()
                logger.error(f"link_id={reward_link.link_id}: RewardLink bulk update 실패: {e}", exc_info=True)
                raise
        else:
            logger.info(f"link_id={reward_link.link_id}: 통검 노출된 키워드가 없어 RewardLink 업데이트하지 않음")
        
        logger.info(f"✅ link_id={reward_link.link_id}: 총 {len(keywords)}개 키워드 처리 완료 (성공: {sum(1 for kw in result['processed_keywords'] if not kw.get('skipped', False))}개)")
        
    except Exception as e:
        logger.error(f"link_id={reward_link.link_id} 처리 중 오류: {e}", exc_info=True)
        result['error'] = str(e)
    finally:
        # 생성한 browser_pool이면 닫기
        if created_browser_pool and browser_pool:
            try:
                browser_pool.close_all()
                logger.info(f"link_id={reward_link.link_id}: 생성한 browser_pool 종료 완료")
            except Exception as e:
                logger.error(f"link_id={reward_link.link_id}: browser_pool 종료 중 오류: {e}", exc_info=True)
        db.close()
    
    return result


def main():
    """
    메인 함수: RewardLink 테이블의 각 제품에 대해
    통검 노출여부, 광고여부를 체크하고 업데이트 (단일 방식)
    브라우저 풀 + 병렬 처리로 성능 향상 (약 10배 빠름)
    reward_link가 null이거나 빈 문자열인 신규 생성된 레코드만 처리
    """
    browser_pool = None
    
    try:
        # 브라우저 풀 초기화 (10개 브라우저)
        logger.info("브라우저 풀 초기화 중... (10개 브라우저 생성)")
        browser_pool = BrowserPool(pool_size=10, headless=True)
        browser_pool.initialize()
        logger.info("브라우저 풀 초기화 완료")
        
        # RewardLink 조회 - reward_link가 null이거나 빈 문자열인 것만
        db = SessionLocal()
        from sqlalchemy import or_
        reward_links = db.query(RewardLink).filter(
            or_(
                RewardLink.reward_link.is_(None),
                RewardLink.reward_link == ''
            )
        ).all()
        db.close()
        
        logger.info(f"총 {len(reward_links)}개 신규 RewardLink 검사 대상 (reward_link가 없는 것)")
        
        if len(reward_links) == 0:
            logger.info("처리할 신규 RewardLink가 없습니다.")
            return
        
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        # 병렬 처리 (ThreadPoolExecutor 사용)
        # 최대 10개 작업 동시 실행 (브라우저 풀 크기와 동일)
        with ThreadPoolExecutor(max_workers=10) as executor:
            # 모든 작업 제출
            future_to_link = {
                executor.submit(process_single_link, reward_link, browser_pool): reward_link
                for reward_link in reward_links
            }
            
            # 완료된 작업 처리
            for idx, future in enumerate(as_completed(future_to_link), 1):
                reward_link = future_to_link[future]
                try:
                    result = future.result()
                    
                    if result['success']:
                        updated_count += 1
                    else:
                        skipped_count += 1
                        if 'error' in result:
                            logger.warning(f"link_id={result['link_id']} 건너뜀: {result['error']}")
                    
                except Exception as e:
                    error_count += 1
                    logger.error(f"link_id={reward_link.link_id} 처리 중 예외: {e}", exc_info=True)
                
                # 진행 상황 로그
                if idx % 10 == 0 or idx == len(reward_links):
                    logger.info(f"진행 상황: {idx}/{len(reward_links)} 완료 (성공: {updated_count}, 건너뜀: {skipped_count}, 오류: {error_count})")
        
        logger.info(f"✅ 완료: 총 {updated_count}개 업데이트, {skipped_count}개 건너뜀, {error_count}개 오류")
        
    except Exception as e:
        logger.error(f"전체 프로세스 오류: {e}", exc_info=True)
        raise
    finally:
        # 브라우저 풀 종료
        if browser_pool:
            browser_pool.close_all()
            logger.info("브라우저 풀 종료 완료")


if __name__ == "__main__":
    main()
