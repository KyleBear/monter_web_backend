"""
Google Sheets 순위 업데이트 스크립트

기능:
1. Google Sheets에서 키워드(G열), 원부 nvmid(H열), 가격비교 nvmid(I열) 읽기
2. 네이버 API로 순위 조회 (가격비교 nvmid가 있으면 우선 사용)
3. J열에 새로운 순위 값 업데이트 (J7부터 2000행까지)

참고:
- J열 생성은 copy_j_to_k.py에서 insertDimension으로 처리됨
- 이 스크립트는 J열이 이미 존재한다고 가정하고 업데이트만 수행함

사용법:
    python google_sheets_rank_updater.py <SPREADSHEET_ID>
"""

import os
import sys
import time
import logging
from typing import List, Optional, Dict, Union
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# 네이버 API 함수 import
from keyword_search_api_ad_nvmidrank import (
    get_shopping_rank_with_ad_flag,
    get_api_rank_by_keyword,
    get_price_comparison_rank
)

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Google Sheets API 설정
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDENTIALS_FILE = 'credential.json'
SHEET_NAME = 'N쇼핑'

# 기본 스프레드시트 ID (하드코딩)
DEFAULT_SPREADSHEET_ID = '1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA'

# 시작 행 (7행부터)
START_ROW = 7
# 업데이트할 최대 행 수
MAX_ROWS = 2000
# 읽을 최대 행 수 (3000개 행까지 읽기)
READ_MAX_ROWS = 2000


class GoogleSheetsRankUpdater:
    """Google Sheets 순위 업데이트 클래스"""
    
    def __init__(self, spreadsheet_id: str):
        """
        초기화
        
        Args:
            spreadsheet_id: Google 스프레드시트 ID
        """
        self.spreadsheet_id = spreadsheet_id
        self.service = None
        self._authenticate()
    
    def _authenticate(self):
        """Google 서비스 계정으로 인증"""
        try:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"인증 파일을 찾을 수 없습니다: {CREDENTIALS_FILE}")
            
            credentials = service_account.Credentials.from_service_account_file(
                CREDENTIALS_FILE,
                scopes=SCOPES
            )
            
            self.service = build('sheets', 'v4', credentials=credentials)
            logger.info("Google Sheets API 인증 성공")
            
        except Exception as e:
            logger.error(f"Google Sheets API 인증 실패: {e}", exc_info=True)
            raise
    
    def _get_range(self, column: str, start_row: int, end_row: int) -> str:
        """
        범위 문자열 생성
        
        Args:
            column: 열 문자 (예: 'G', 'H', 'J')
            start_row: 시작 행 번호
            end_row: 끝 행 번호
        
        Returns:
            범위 문자열 (예: 'N쇼핑!G7:G3006')
        """
        return f"{SHEET_NAME}!{column}{start_row}:{column}{end_row}"
    
    def read_input_data(self) -> List[Dict]:
        """
        스프레드시트에서 입력 데이터 읽기 (G, H, I 열)
        
        Returns:
            입력 데이터 리스트 [{'keyword': str, 'nvmid': str, 'price_nvmid': str or None}, ...]
        """
        try:
            # G열 (키워드), H열 (원부 nvmid), I열 (가격비교 nvmid) 읽기
            range_g = self._get_range('G', START_ROW, START_ROW + READ_MAX_ROWS - 1)
            range_h = self._get_range('H', START_ROW, START_ROW + READ_MAX_ROWS - 1)
            range_i = self._get_range('I', START_ROW, START_ROW + READ_MAX_ROWS - 1)
            
            logger.info(f"스프레드시트에서 데이터 읽기 시작: {range_g}, {range_h}, {range_i}")
            
            # 배치로 읽기
            result = self.service.spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=[range_g, range_h, range_i]
            ).execute()
            
            value_ranges = result.get('valueRanges', [])
            
            if len(value_ranges) != 3:
                raise ValueError(f"예상과 다른 응답: {len(value_ranges)}개 범위 반환")
            
            keywords = [row[0] if row else '' for row in value_ranges[0].get('values', [])]
            nvmids = [row[0] if row else '' for row in value_ranges[1].get('values', [])]
            price_nvmids = [row[0] if row else '' for row in value_ranges[2].get('values', [])]
            
            # 데이터 정리
            input_data = []
            for i in range(len(keywords)):
                keyword = keywords[i].strip() if i < len(keywords) else ''
                nvmid = nvmids[i].strip() if i < len(nvmids) else ''
                price_nvmid = price_nvmids[i].strip() if i < len(price_nvmids) and price_nvmids[i] else None
                
                # 키워드와 nvmid가 모두 있어야 처리
                if keyword and nvmid:
                    input_data.append({
                        'keyword': keyword,
                        'nvmid': nvmid,
                        'price_nvmid': price_nvmid if price_nvmid else None
                    })
                elif keyword or nvmid:
                    # 키워드 또는 nvmid 중 하나만 있는 경우도 빈 데이터로 추가
                    input_data.append({
                        'keyword': keyword,
                        'nvmid': nvmid,
                        'price_nvmid': price_nvmid if price_nvmid else None
                    })
                else:
                    # 둘 다 없으면 빈 데이터로 추가
                    input_data.append({
                        'keyword': '',
                        'nvmid': '',
                        'price_nvmid': None
                    })
            
            logger.info(f"총 {len(input_data)}개 행 데이터 읽기 완료")
            return input_data
            
        except HttpError as e:
            logger.error(f"스프레드시트 읽기 실패: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"데이터 읽기 중 오류: {e}", exc_info=True)
            raise
    
    def get_rank_by_naver_api(self, keyword: str, nvmid: str, price_nvmid: Optional[str] = None, max_rank: int = 1000) -> Union[int, str, None]:
        """
        네이버 API로 순위 조회
        
        Args:
            keyword: 검색 키워드
            nvmid: 원부 nvmid
            price_nvmid: 가격비교 nvmid (옵션, 있으면 우선 사용)
            max_rank: 최대 조회할 순위 (기본값: 1000)
        
        Returns:
            순위 (int), "확인불가" (1000등 밖), 또는 None (키워드/nvmid 없음)
        """
        if not keyword or not nvmid:
            return None
        
        try:
            # 가격비교 nvmid가 있으면 우선 사용
            target_nvmid = price_nvmid if price_nvmid else nvmid
            use_price_comparison = bool(price_nvmid)
            
            logger.debug(f"순위 조회: keyword='{keyword}', nvmid='{target_nvmid}', 가격비교={use_price_comparison}")
            
            # 최대 1000등까지 조회 (10페이지, 각 페이지 100개)
            max_pages = 10
            display = 100
            
            for page in range(1, max_pages + 1):
                start = (page - 1) * 100 + 1  # 1, 101, 201, ...
                
                if start > max_rank:
                    break
                
                try:
                    # 네이버 API 호출
                    api_results = get_shopping_rank_with_ad_flag(
                        keyword,
                        display=display,
                        start=start,
                        filter=None
                    )
                    
                    if not api_results:
                        logger.debug(f"페이지 {page}: 결과 없음")
                        break
                    
                    # 매칭 시도
                    for item in api_results:
                        rank = item.get('rank')
                        
                        if rank and rank > max_rank:
                            # 최대 순위 초과
                            break
                        
                        # 가격비교 nvmid 사용 시: productId로 직접 매칭
                        if use_price_comparison:
                            product_id = str(item.get('productId', '')).strip()
                            if product_id == target_nvmid:
                                logger.info(f"가격비교 순위 매칭 성공: keyword='{keyword}', nvmid='{target_nvmid}', rank={rank}")
                                return rank
                        
                        # 원부 nvmid 사용 시: productId 또는 link에서 nvmid 추출하여 매칭
                        else:
                            product_id = str(item.get('productId', '')).strip()
                            link = item.get('link', '')
                            nvmid_from_link = None
                            
                            if link:
                                import re
                                patterns = [
                                    r'nv_mid[=_](\d+)',
                                    r'nvmid[=_](\d+)',
                                    r'nv-mid[=_](\d+)',
                                    r'/catalog/(\d+)',
                                ]
                                
                                for pattern in patterns:
                                    match = re.search(pattern, link, re.IGNORECASE)
                                    if match:
                                        nvmid_from_link = match.group(1)
                                        break
                            
                            if (product_id and product_id == target_nvmid) or \
                               (nvmid_from_link and nvmid_from_link == target_nvmid):
                                logger.info(f"원부 순위 매칭 성공: keyword='{keyword}', nvmid='{target_nvmid}', rank={rank}")
                                return rank
                    
                    # API 호출 간격
                    time.sleep(0.2)
                    
                except Exception as e:
                    logger.error(f"페이지 {page} 조회 중 오류: {e}", exc_info=True)
                    continue
            
            logger.debug(f"순위 조회 실패: keyword='{keyword}', nvmid='{target_nvmid}' (1000등 이내에서 매칭 실패)")
            return "확인불가"
            
        except Exception as e:
            logger.error(f"순위 조회 중 오류: keyword='{keyword}', error={e}", exc_info=True)
            return None
    
    def update_ranks(self, ranks: List[Union[int, str, None]]):
        """
        J열에 순위 데이터 업데이트
        
        Args:
            ranks: 순위 리스트 (int: 순위, "확인불가": 1000등 밖, None: 빈칸)
        """
        try:
            logger.info(f"J열에 순위 데이터 업데이트 시작 ({len(ranks)}개 행)...")
            
            # 순위 값을 문자열 리스트로 변환
            values = []
            for rank in ranks:
                if rank is None:
                    values.append([''])
                elif isinstance(rank, str):
                    values.append([rank])  # "확인불가" 문자열 그대로 사용
                else:
                    values.append([str(rank)])  # int를 문자열로 변환
            
            # MAX_ROWS만큼만 업데이트
            values = values[:MAX_ROWS]
            
            # 빈 셀도 포함하여 정확히 MAX_ROWS만큼 데이터 준비
            while len(values) < MAX_ROWS:
                values.append([''])
            
            range_j = self._get_range('J', START_ROW, START_ROW + MAX_ROWS - 1)
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_j,
                valueInputOption='USER_ENTERED',
                body={'values': values}
            ).execute()
            
            logger.info(f"J열 업데이트 완료 ({len(values)}개 행)")
            
        except HttpError as e:
            logger.error(f"J열 업데이트 실패: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"순위 업데이트 중 오류: {e}", exc_info=True)
            raise
    
    def update_all_ranks(self):
        """전체 순위 업데이트 프로세스 실행"""
        try:
            logger.info("=" * 60)
            logger.info("Google Sheets 순위 업데이트 시작")
            logger.info(f"스프레드시트 ID: {self.spreadsheet_id}")
            logger.info(f"시트 이름: {SHEET_NAME}")
            logger.info("=" * 60)
            
            # 1. 입력 데이터 읽기
            input_data = self.read_input_data()
            
            if not input_data:
                logger.warning("읽을 데이터가 없습니다.")
                return
            
            # 2. 각 행에 대해 순위 조회
            ranks = []
            total_count = len(input_data)
            success_count = 0
            empty_count = 0
            
            logger.info(f"총 {total_count}개 행의 순위 조회 시작...")
            
            for idx, data in enumerate(input_data, 1):
                keyword = data['keyword']
                nvmid = data['nvmid']
                price_nvmid = data['price_nvmid']
                
                # 키워드와 nvmid가 모두 있어야 조회
                if keyword and nvmid:
                    rank = self.get_rank_by_naver_api(keyword, nvmid, price_nvmid)
                    ranks.append(rank)
                    
                    if rank and isinstance(rank, int):
                        success_count += 1
                        if idx % 100 == 0:
                            logger.info(f"[진행상황] {idx}/{total_count} 행 처리 완료 (순위 발견: {success_count}개)")
                    elif rank == "확인불가":
                        # 확인불가는 empty_count에 포함하지 않음 (별도 카운트)
                        pass
                    else:
                        empty_count += 1
                else:
                    # 키워드 또는 nvmid가 없으면 빈칸
                    ranks.append(None)
                    empty_count += 1
                
                # API 호출 간격 (너무 빠르면 제한될 수 있음)
                if idx % 10 == 0:
                    time.sleep(0.5)
            
            # "확인불가" 개수도 카운트
            unavailable_count = sum(1 for r in ranks if r == "확인불가")
            logger.info(f"순위 조회 완료: 총 {total_count}개 행, 순위 발견: {success_count}개, 확인불가: {unavailable_count}개, 빈칸: {empty_count}개")
            
            # 5. J열에 순위 데이터 업데이트
            self.update_ranks(ranks)
            
            logger.info("=" * 60)
            logger.info("Google Sheets 순위 업데이트 완료!")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"순위 업데이트 프로세스 실패: {e}", exc_info=True)
            raise


def main():
    """메인 함수"""
    # 스프레드시트 ID: 명령줄 인자가 있으면 사용, 없으면 기본값 사용
    if len(sys.argv) >= 2:
        spreadsheet_id = sys.argv[1]
        logger.info(f"명령줄 인자에서 스프레드시트 ID 사용: {spreadsheet_id}")
    else:
        spreadsheet_id = DEFAULT_SPREADSHEET_ID
        logger.info(f"기본 스프레드시트 ID 사용: {spreadsheet_id}")
        print(f"기본 스프레드시트 ID 사용: {spreadsheet_id}")
        print("다른 스프레드시트를 사용하려면: python google_sheets_rank_updater.py <SPREADSHEET_ID>")
    
    try:
        updater = GoogleSheetsRankUpdater(spreadsheet_id)
        updater.update_all_ranks()
        
    except KeyboardInterrupt:
        logger.info("사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"프로그램 실행 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
