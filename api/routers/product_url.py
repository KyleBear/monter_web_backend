import requests
import re
import time
from urllib.parse import urlparse


class NaverSmartStoreScraper:
    """네이버 스마트스토어 nvMid 추출 클래스"""
    
    def __init__(self, delay=2):
        """
        Args:
            delay: 요청 간 대기 시간 (초)
        """
        self.delay = delay
        self.session = requests.Session()
    
    def extract_product_info(self, url):
        """
        URL에서 채널ID와 상품ID 추출
        
        Args:
            url: 스마트스토어 상품 URL
            
        Returns:
            (channel_id, product_id) 튜플 또는 (None, None)
        """
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        
        if len(path_parts) >= 3 and path_parts[1] == 'products':
            channel_id = path_parts[0]
            product_id = path_parts[2]
            return channel_id, product_id
        
        if 'smartstore.naver.com' in parsed.netloc or 'm.smartstore.naver.com' in parsed.netloc:
            if len(path_parts) >= 3:
                channel_id = path_parts[0]
                product_id = path_parts[2]
                return channel_id, product_id
        
        return None, None
    
    def extract_nvmid_from_html(self, html):
        """
        HTML에서 nvMid 추출
        
        Args:
            html: HTML 문자열
            
        Returns:
            nvmid 문자열 또는 None
        """
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
        
        if found_nvmids:
            return sorted(found_nvmids)[0]
        
        return None
    
    def get_nvmid_mobile(self, channel_id, product_id):
        """
        모바일 User-Agent로 nvMid 추출
        
        Args:
            channel_id: 채널 ID
            product_id: 상품 ID
            
        Returns:
            nvmid 문자열 또는 None
        """
        mobile_url = f"https://m.smartstore.naver.com/{channel_id}/products/{product_id}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
        }
        
        try:
            response = requests.get(mobile_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return self.extract_nvmid_from_html(response.text)
        
        except Exception as e:
            pass
        
        return None
    
    def get_nvmid_session(self, channel_id, product_id):
        """
        Session + 쿠키를 사용하여 nvMid 추출
        
        Args:
            channel_id: 채널 ID
            product_id: 상품 ID
            
        Returns:
            nvmid 문자열 또는 None
        """
        mobile_url = f"https://m.smartstore.naver.com/{channel_id}/products/{product_id}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        
        try:
            # 메인 페이지 먼저 방문
            self.session.get('https://m.smartstore.naver.com', headers=headers, timeout=10)
            time.sleep(1)
            
            # 상품 페이지
            response = self.session.get(mobile_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return self.extract_nvmid_from_html(response.text)
        
        except Exception as e:
            pass
        
        return None
    
    def get_nvmid(self, url, verbose=False):
        """
        URL에서 nvMid 추출 (메인 함수)
        
        Args:
            url: 스마트스토어 상품 URL
            verbose: 상세 출력 여부
            
        Returns:
            nvmid 문자열 또는 None
        """
        channel_id, product_id = self.extract_product_info(url)
        
        if not product_id:
            if verbose:
                print("✗ URL에서 상품 ID를 추출할 수 없습니다")
            return None
        
        if verbose:
            print(f"채널ID: {channel_id}, 상품ID: {product_id}")
        
        # 방법 1: 모바일 User-Agent
        if verbose:
            print("\n방법 1: 모바일 User-Agent 시도...")
        
        nvmid = self.get_nvmid_mobile(channel_id, product_id)
        
        if nvmid:
            if verbose:
                print(f"✓ nvMid 추출 성공: {nvmid}")
            return nvmid
        
        if verbose:
            print("✗ 방법 1 실패")
        
        time.sleep(self.delay)
        
        # 방법 2: Session 사용
        if verbose:
            print("\n방법 2: Session + 쿠키 시도...")
        
        nvmid = self.get_nvmid_session(channel_id, product_id)
        
        if nvmid:
            if verbose:
                print(f"✓ nvMid 추출 성공: {nvmid}")
            return nvmid
        
        if verbose:
            print("✗ 방법 2 실패")
            print("✗ nvMid 추출 실패")
        
        return None


# 편의 함수
def get_nvmid_from_url(url, verbose=False):
    """
    URL에서 nvMid를 추출하는 편의 함수
    
    Args:
        url: 스마트스토어 상품 URL
        verbose: 상세 출력 여부
        
    Returns:
        nvmid 문자열 또는 None
    
    Example:
        >>> nvmid = get_nvmid_from_url("https://smartstore.naver.com/pettimes/products/10861603621")
        >>> print(nvmid)
        83109917539
    """
    scraper = NaverSmartStoreScraper()
    return scraper.get_nvmid(url, verbose=verbose)


# 실행 예시
if __name__ == "__main__":
    # 예시 1: 클래스 직접 사용
    print("="*60)
    print("예시 1: 클래스 직접 사용")
    print("="*60)
    
    scraper = NaverSmartStoreScraper(delay=2)
    url1 = "https://smartstore.naver.com/pettimes/products/10861603621"
    
    nvmid = scraper.get_nvmid(url1, verbose=True)
    
    if nvmid:
        print(f"\n✓ 최종 결과: {nvmid}")
        print(f"네이버 쇼핑: https://search.shopping.naver.com/catalog/{nvmid}")
    else:
        print("\n✗ nvMid 추출 실패")
    
    print("\n" + "="*60)
    print("예시 2: 편의 함수 사용")
    print("="*60)
    
    url2 = "https://brand.naver.com/jipban/products/5565421632"
    
    nvmid = get_nvmid_from_url(url2, verbose=False)
    
    if nvmid:
        print(f"✓ nvMid: {nvmid}")
    else:
        print("✗ 추출 실패")