"""
Google Sheets API 통합 파일
- J열 삽입 및 타임스탬프 기록
- Google Sheets 순위 업데이트
"""

import os
import sys
import time
import logging
import re
from typing import List, Optional, Dict, Union
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# 프로젝트 루트를 Python 경로에 추가 (직접 실행 시)
current_file = os.path.abspath(__file__)
project_root = os.path.abspath(os.path.join(os.path.dirname(current_file), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.requests import Request
from pydantic import BaseModel
import threading

# 네이버 API 함수 import (crol.py에서)
from api.routers.crol import (
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

# FastAPI 라우터 생성
router = APIRouter()

# Google Sheets API 설정
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
# 인증 파일 우선순위: meal-planner-nrank.json > credential.json
CREDENTIALS_FILE = 'meal-planner-nrank.json' if os.path.exists('meal-planner-nrank.json') else 'credential.json'
SHEET_NAME = 'N쇼핑'
DEFAULT_SPREADSHEET_ID = '1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA'
TIMESTAMP_ROW = 6  # 6행에 타임스탬프 기록

# 시작 행 (7행부터)
START_ROW = 7
# 업데이트할 최대 행 수
MAX_ROWS = 2000
# 읽을 최대 행 수 (3000개 행까지 읽기)
READ_MAX_ROWS = 3000


# Pydantic 모델
class SpreadsheetRequest(BaseModel):
    spreadsheet_id: Optional[str] = None


class InsertColumnResponse(BaseModel):
    success: bool
    message: str
    timestamp: str
    spreadsheet_id: str


class UpdateRanksResponse(BaseModel):
    success: bool
    message: str
    total_rows: int
    success_count: int
    unavailable_count: int
    empty_count: int
    spreadsheet_id: str


def insert_j_column_and_timestamp(spreadsheet_id: str = None):
    """
    J열 삽입 후 6행에 타임스탬프 기록
    
    Args:
        spreadsheet_id: Google 스프레드시트 ID (None이면 기본값 사용)
    
    Returns:
        dict: 결과 정보
    """
    try:
        # 인증
        if not os.path.exists(CREDENTIALS_FILE):
            raise FileNotFoundError(f"인증 파일을 찾을 수 없습니다: {CREDENTIALS_FILE}")
        
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=SCOPES
        )
        service = build('sheets', 'v4', credentials=credentials)
        logger.info("Google Sheets API 인증 성공")
        
        # 스프레드시트 ID
        if spreadsheet_id is None:
            spreadsheet_id = DEFAULT_SPREADSHEET_ID
        logger.info(f"스프레드시트 ID: {spreadsheet_id}")
        
        # 시트 ID 가져오기
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_id = None
        for sheet in spreadsheet.get('sheets', []):
            if sheet['properties']['title'] == SHEET_NAME:
                sheet_id = sheet['properties']['sheetId']
                break
        
        if sheet_id is None:
            raise ValueError(f"시트 '{SHEET_NAME}'를 찾을 수 없습니다.")
        
        logger.info(f"시트 ID: {sheet_id}")
        
        # 1. J열 위치에 새 열 삽입 (기존 J열이 K열로 이동, K열이 L열로 이동...)
        logger.info("J열 삽입 중... (기존 J열은 K열로 이동, K열은 L열로 이동...)")
        request_body = {
            'requests': [{
                'insertDimension': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': 9,  # J열 위치 (A=0, B=1, ..., J=9)
                        'endIndex': 10
                    },
                    'inheritFromBefore': False
                }
            }]
        }
        
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=request_body
        ).execute()
        logger.info("[OK] J열 삽입 완료 (기존 J열이 K열로 이동됨)")
        
        # 2. 새로 삽입된 J열 6행에 타임스탬프 기록
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"타임스탬프: {timestamp}")
        
        range_j6 = f"{SHEET_NAME}!J{TIMESTAMP_ROW}"
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_j6,
            valueInputOption='USER_ENTERED',
            body={'values': [[timestamp]]}
        ).execute()
        
        logger.info(f"[OK] J열 {TIMESTAMP_ROW}행에 타임스탬프 기록 완료: {timestamp}")
        
        return {
            'success': True,
            'timestamp': timestamp,
            'spreadsheet_id': spreadsheet_id
        }
        
    except HttpError as e:
        logger.error(f"[ERROR] 오류 발생: {e}")
        raise
    except Exception as e:
        logger.error(f"[ERROR] 오류 발생: {e}", exc_info=True)
        raise


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
        네이버 OpenAPI로 순위 조회
        
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
            
            logger.debug(f"OpenAPI 순위 조회: keyword='{keyword}', nvmid='{target_nvmid}'")
            
            # OpenAPI로 순위 조회 (최대 1000등까지, 여러 페이지 조회)
            # get_api_rank_by_keyword는 한 번에 100개까지만 조회하므로, 여러 페이지를 조회해야 함
            max_pages = min((max_rank + 99) // 100, 10)  # 최대 10페이지
            
            for page in range(1, max_pages + 1):
                start = (page - 1) * 100 + 1  # 1, 101, 201, ...
                
                if start > max_rank:
                    break
                
                try:
                    # OpenAPI로 검색 (100개씩)
                    api_results = get_shopping_rank_with_ad_flag(
                        keyword,
                        display=100,
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
                        
                        # nvmid 매칭
                        product_id = str(item.get('productId', '')).strip()
                        link = item.get('link', '')
                        nvmid_from_link = None
                        
                        if link:
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
                        
                        # nvmid 매칭 확인
                        if (product_id and product_id == target_nvmid) or \
                           (nvmid_from_link and nvmid_from_link == target_nvmid):
                            logger.info(f"OpenAPI 순위 매칭 성공: keyword='{keyword}', nvmid='{target_nvmid}', rank={rank}")
                            return rank
                    
                    # API 호출 간격 (3초)
                    time.sleep(3.0)
                    
                except Exception as e:
                    logger.error(f"페이지 {page} 조회 중 오류: {e}", exc_info=True)
                    continue
            
            # get_api_rank_by_keyword를 사용하여 추가 확인 (100개 이내에서 빠른 확인)
            try:
                rank = get_api_rank_by_keyword(keyword, target_nvmid)
                if rank:
                    logger.info(f"OpenAPI 순위 조회 성공 (get_api_rank_by_keyword): keyword='{keyword}', nvmid='{target_nvmid}', rank={rank}")
                    return rank
            except Exception as e:
                logger.debug(f"get_api_rank_by_keyword 호출 중 오류 (무시): {e}")
            
            logger.debug(f"순위 조회 실패: keyword='{keyword}', nvmid='{target_nvmid}' (1000등 이내에서 매칭 실패)")
            return "확인불가"
            
        except Exception as e:
            logger.error(f"순위 조회 중 오류: keyword='{keyword}', error={e}", exc_info=True)
            return None
    
    def update_ranks(self, ranks: List[Union[int, str, None]], start_index: int = 0):
        """
        J열에 순위 데이터 업데이트
        
        Args:
            ranks: 순위 리스트 (int: 순위, "확인불가": 1000등 밖, None: 빈칸)
            start_index: 시작 인덱스 (배치 업데이트용, 기본값: 0)
        """
        try:
            logger.info(f"J열에 순위 데이터 업데이트 시작 (인덱스 {start_index}부터 {len(ranks)}개 행)...")
            
            # 순위 값을 문자열 리스트로 변환
            values = []
            for rank in ranks:
                if rank is None:
                    values.append([''])
                elif isinstance(rank, str):
                    values.append([rank])  # "확인불가" 문자열 그대로 사용
                else:
                    values.append([str(rank)])  # int를 문자열로 변환
            
            # 업데이트할 범위 계산
            start_row = START_ROW + start_index
            end_row = start_row + len(values) - 1
            
            range_j = self._get_range('J', start_row, end_row)
            
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_j,
                valueInputOption='USER_ENTERED',
                body={'values': values}
            ).execute()
            
            logger.info(f"✅ J열 업데이트 완료 (행 {start_row}~{end_row}, {len(values)}개)")
            
        except HttpError as e:
            logger.error(f"J열 업데이트 실패: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"순위 업데이트 중 오류: {e}", exc_info=True)
            raise
    
    def update_all_ranks(self, insert_column_first: bool = True) -> Dict:
        """
        전체 순위 업데이트 프로세스 실행
        
        Args:
            insert_column_first: True이면 먼저 J열을 삽입하고 타임스탬프를 기록 (기본값: True)
        
        Returns:
            dict: 업데이트 결과 통계
        """
        try:
            logger.info("=" * 60)
            logger.info("Google Sheets 순위 업데이트 시작")
            logger.info(f"스프레드시트 ID: {self.spreadsheet_id}")
            logger.info(f"시트 이름: {SHEET_NAME}")
            logger.info("=" * 60)
            
            # 0. J열 삽입 및 타임스탬프 기록 (옵션)
            if insert_column_first:
                logger.info("\n[1단계] J열 삽입 및 타임스탬프 기록 시작...")
                try:
                    insert_j_column_and_timestamp(self.spreadsheet_id)
                    logger.info("✅ J열 삽입 및 타임스탬프 기록 완료")
                except Exception as e:
                    logger.warning(f"⚠️ J열 삽입 실패 (계속 진행): {e}")
                    # J열 삽입 실패해도 순위 업데이트는 계속 진행
            
            # 1. 입력 데이터 읽기
            logger.info("\n[2단계] 입력 데이터 읽기 시작...")
            input_data = self.read_input_data()
            
            if not input_data:
                logger.warning("읽을 데이터가 없습니다.")
                return {
                    'total_rows': 0,
                    'success_count': 0,
                    'unavailable_count': 0,
                    'empty_count': 0
                }
            
            # 2. 각 행에 대해 순위 조회 및 업데이트 (200개씩 배치 처리)
            logger.info("\n[3단계] 순위 조회 및 업데이트 시작 (200개씩 배치 처리)...")
            total_count = len(input_data)
            batch_size = 200  # 배치 크기
            
            # 전체 통계
            total_success_count = 0
            total_unavailable_count = 0
            total_empty_count = 0
            
            logger.info(f"총 {total_count}개 행을 {batch_size}개씩 {((total_count + batch_size - 1) // batch_size)}개 배치로 처리합니다.")
            
            # 배치별로 순차 처리
            for batch_start in range(0, total_count, batch_size):
                batch_end = min(batch_start + batch_size, total_count)
                batch_data = input_data[batch_start:batch_end]
                batch_num = (batch_start // batch_size) + 1
                total_batches = (total_count + batch_size - 1) // batch_size
                
                logger.info(f"\n[배치 {batch_num}/{total_batches}] {batch_start+1}~{batch_end}행 처리 시작 ({len(batch_data)}개)...")
                
                # 배치 내에서 병렬 처리
                batch_ranks = [None] * len(batch_data)
                stats_lock = Lock()
                batch_success_count = 0
                batch_empty_count = 0
                
                def process_single_rank(batch_idx: int, data: Dict) -> tuple:
                    """
                    단일 행의 순위를 조회하는 함수 (배치 내 인덱스 사용)
                    
                    Args:
                        batch_idx: 배치 내 인덱스 (0부터 시작)
                        data: {'keyword': str, 'nvmid': str, 'price_nvmid': str or None}
                    
                    Returns:
                        (batch_idx, rank): 배치 내 인덱스와 순위 결과
                    """
                    # 각 작업이 시작될 때 3초 간격을 두기 위해 지연
                    delay = batch_idx * 3.0
                    if delay > 0:
                        time.sleep(delay)
                    
                    keyword = data['keyword']
                    nvmid = data['nvmid']
                    price_nvmid = data['price_nvmid']
                    
                    # 키워드와 nvmid가 모두 있어야 조회
                    if keyword and nvmid:
                        rank = self.get_rank_by_naver_api(keyword, nvmid, price_nvmid)
                        
                        # 통계 업데이트 (스레드 안전)
                        with stats_lock:
                            nonlocal batch_success_count, batch_empty_count
                            if rank and isinstance(rank, int):
                                batch_success_count += 1
                            elif rank == "확인불가":
                                pass  # 확인불가는 별도 카운트
                            else:
                                batch_empty_count += 1
                        
                        return (batch_idx, rank)
                    else:
                        # 키워드 또는 nvmid가 없으면 빈칸
                        with stats_lock:
                            batch_empty_count += 1
                        return (batch_idx, None)
                
                # 배치 내 병렬 처리 실행
                max_workers = min(10, len(batch_data))  # 최대 10개의 워커 스레드 사용
                completed = 0
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 배치 내 모든 작업 제출
                    future_to_idx = {
                        executor.submit(process_single_rank, idx, data): idx 
                        for idx, data in enumerate(batch_data)
                    }
                    
                    # 완료된 작업 처리
                    for future in as_completed(future_to_idx):
                        try:
                            batch_idx, rank = future.result()
                            batch_ranks[batch_idx] = rank
                            completed += 1
                            
                            # 진행 상황 로깅 (50개마다)
                            if completed % 50 == 0:
                                with stats_lock:
                                    logger.info(f"  [배치 {batch_num} 진행] {completed}/{len(batch_data)} 행 처리 완료 (순위 발견: {batch_success_count}개)")
                        except Exception as e:
                            batch_idx = future_to_idx[future]
                            logger.error(f"  [배치 {batch_num}] 행 {batch_start + batch_idx + 1} 처리 중 오류: {e}", exc_info=True)
                            batch_ranks[batch_idx] = None
                            completed += 1
                
                # 배치 "확인불가" 개수 카운트
                batch_unavailable_count = sum(1 for r in batch_ranks if r == "확인불가")
                
                # 통계 누적
                total_success_count += batch_success_count
                total_unavailable_count += batch_unavailable_count
                total_empty_count += batch_empty_count
                
                logger.info(f"  [배치 {batch_num} 완료] 순위 발견: {batch_success_count}개, 확인불가: {batch_unavailable_count}개, 빈칸: {batch_empty_count}개")
                
                # 3-1. 배치별로 J열 업데이트 (즉시 반영)
                logger.info(f"  [배치 {batch_num}] J열 업데이트 중... (행 {START_ROW + batch_start}~{START_ROW + batch_end - 1})")
                try:
                    self.update_ranks(batch_ranks, start_index=batch_start)
                    logger.info(f"  ✅ [배치 {batch_num}] J열 업데이트 완료")
                except Exception as e:
                    logger.error(f"  ❌ [배치 {batch_num}] J열 업데이트 실패: {e}", exc_info=True)
                    # 배치 업데이트 실패해도 다음 배치 계속 진행
            
            # 전체 통계 출력
            logger.info(f"\n✅ 전체 순위 조회 완료: 총 {total_count}개 행, 순위 발견: {total_success_count}개, 확인불가: {total_unavailable_count}개, 빈칸: {total_empty_count}개")
            
            logger.info("=" * 60)
            logger.info("Google Sheets 순위 업데이트 완료!")
            logger.info("=" * 60)
            
            return {
                'total_rows': total_count,
                'success_count': total_success_count,
                'unavailable_count': total_unavailable_count,
                'empty_count': total_empty_count
            }
            
        except Exception as e:
            logger.error(f"순위 업데이트 프로세스 실패: {e}", exc_info=True)
            raise


# FastAPI 엔드포인트

@router.get("/insert-column-timestamp", response_model=InsertColumnResponse)
async def insert_column_timestamp_get(
    spreadsheet_id: Optional[str] = Query(None, description="Google 스프레드시트 ID (없으면 기본값 사용)")
):
    """
    J열 삽입 및 6행에 타임스탬프 기록 (GET 요청)
    
    - J열 위치에 새 열을 삽입합니다 (기존 J열은 K열로 이동)
    - 새로 삽입된 J열의 6행에 현재 타임스탬프를 기록합니다
    
    사용법:
    - Google Sheets에서 HYPERLINK 함수 사용:
      =HYPERLINK("http://localhost:8001/api/google-sheets/insert-column-timestamp?spreadsheet_id=1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA", "J열 삽입")
    - 또는 스프레드시트 ID를 셀에서 참조:
      =HYPERLINK("http://localhost:8001/api/google-sheets/insert-column-timestamp?spreadsheet_id=" & A1, "J열 삽입")
    """
    try:
        result = insert_j_column_and_timestamp(spreadsheet_id)
        
        return InsertColumnResponse(
            success=True,
            message="J열 삽입 및 타임스탬프 기록 완료",
            timestamp=result['timestamp'],
            spreadsheet_id=result['spreadsheet_id']
        )
    except Exception as e:
        logger.error(f"J열 삽입 및 타임스탬프 기록 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insert-column-timestamp", response_model=InsertColumnResponse)
async def insert_column_timestamp(request: Optional[SpreadsheetRequest] = None):
    """
    J열 삽입 및 6행에 타임스탬프 기록 (POST 요청)
    
    - J열 위치에 새 열을 삽입합니다 (기존 J열은 K열로 이동)
    - 새로 삽입된 J열의 6행에 현재 타임스탬프를 기록합니다
    """
    try:
        spreadsheet_id = request.spreadsheet_id if request and request.spreadsheet_id else None
        result = insert_j_column_and_timestamp(spreadsheet_id)
        
        return InsertColumnResponse(
            success=True,
            message="J열 삽입 및 타임스탬프 기록 완료",
            timestamp=result['timestamp'],
            spreadsheet_id=result['spreadsheet_id']
        )
    except Exception as e:
        logger.error(f"J열 삽입 및 타임스탬프 기록 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/update-ranks", response_model=UpdateRanksResponse)
async def update_ranks_endpoint_get(
    spreadsheet_id: Optional[str] = Query(None, description="Google 스프레드시트 ID (없으면 기본값 사용)"),
    insert_column_first: bool = Query(True, description="먼저 J열을 삽입할지 여부 (기본값: True)"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Google Sheets 순위 업데이트 (GET 요청) - 백그라운드 작업
    
    - 즉시 응답을 반환하고 작업은 백그라운드에서 실행됩니다 (504 타임아웃 방지)
    - (옵션) J열 삽입 및 타임스탬프 기록
    - G열(키워드), H열(원부 nvmid), I열(가격비교 nvmid)을 읽습니다
    - 네이버 OpenAPI로 순위를 조회합니다 (가격비교 nvmid가 있으면 우선 사용)
    - J열에 순위 값을 업데이트합니다 (J7부터 2000행까지)
    
    사용법:
    - Google Sheets에서 HYPERLINK 함수 사용:
      =HYPERLINK("https://re-switch.co.kr/api/google-sheets/update-ranks?spreadsheet_id=1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA", "순위 업데이트")
    - 또는 스프레드시트 ID를 셀에서 참조:
      =HYPERLINK("https://re-switch.co.kr/api/google-sheets/update-ranks?spreadsheet_id=" & A1, "순위 업데이트")
    - J열 삽입 없이 순위만 업데이트:
      =HYPERLINK("https://re-switch.co.kr/api/google-sheets/update-ranks?spreadsheet_id=...&insert_column_first=false", "순위만 업데이트")
    """
    try:
        if spreadsheet_id is None:
            spreadsheet_id = DEFAULT_SPREADSHEET_ID
        
        # 백그라운드 작업 함수 정의
        def run_update():
            try:
                logger.info(f"[백그라운드 작업 시작] 스프레드시트 ID: {spreadsheet_id}")
                updater = GoogleSheetsRankUpdater(spreadsheet_id)
                result = updater.update_all_ranks(insert_column_first=insert_column_first)
                logger.info(f"[백그라운드 작업 완료] 스프레드시트 ID: {spreadsheet_id}, 결과: {result}")
            except Exception as e:
                logger.error(f"[백그라운드 작업 실패] 스프레드시트 ID: {spreadsheet_id}, 오류: {e}", exc_info=True)
        
        # 백그라운드 작업 추가
        background_tasks.add_task(run_update)
        
        # 즉시 응답 반환 (504 타임아웃 방지)
        logger.info(f"[순위 업데이트 요청] 스프레드시트 ID: {spreadsheet_id}, 백그라운드 작업 시작")
        return UpdateRanksResponse(
            success=True,
            message="순위 업데이트가 백그라운드에서 시작되었습니다. 작업이 완료되면 J열이 업데이트됩니다.",
            total_rows=0,
            success_count=0,
            unavailable_count=0,
            empty_count=0,
            spreadsheet_id=spreadsheet_id
        )
    except Exception as e:
        logger.error(f"순위 업데이트 시작 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-ranks", response_model=UpdateRanksResponse)
async def update_ranks_endpoint(
    request: Optional[SpreadsheetRequest] = None,
    insert_column_first: bool = Query(True, description="먼저 J열을 삽입할지 여부 (기본값: True)"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Google Sheets 순위 업데이트 (POST 요청) - 백그라운드 작업
    
    - 즉시 응답을 반환하고 작업은 백그라운드에서 실행됩니다 (504 타임아웃 방지)
    - (옵션) J열 삽입 및 타임스탬프 기록
    - G열(키워드), H열(원부 nvmid), I열(가격비교 nvmid)을 읽습니다
    - 네이버 OpenAPI로 순위를 조회합니다 (가격비교 nvmid가 있으면 우선 사용)
    - J열에 순위 값을 업데이트합니다 (J7부터 2000행까지)
    """
    try:
        spreadsheet_id = request.spreadsheet_id if request and request.spreadsheet_id else DEFAULT_SPREADSHEET_ID
        
        # 백그라운드 작업 함수 정의
        def run_update():
            try:
                logger.info(f"[백그라운드 작업 시작] 스프레드시트 ID: {spreadsheet_id}")
                updater = GoogleSheetsRankUpdater(spreadsheet_id)
                result = updater.update_all_ranks(insert_column_first=insert_column_first)
                logger.info(f"[백그라운드 작업 완료] 스프레드시트 ID: {spreadsheet_id}, 결과: {result}")
            except Exception as e:
                logger.error(f"[백그라운드 작업 실패] 스프레드시트 ID: {spreadsheet_id}, 오류: {e}", exc_info=True)
        
        # 백그라운드 작업 추가
        background_tasks.add_task(run_update)
        
        # 즉시 응답 반환 (504 타임아웃 방지)
        logger.info(f"[순위 업데이트 요청] 스프레드시트 ID: {spreadsheet_id}, 백그라운드 작업 시작")
        return UpdateRanksResponse(
            success=True,
            message="순위 업데이트가 백그라운드에서 시작되었습니다. 작업이 완료되면 J열이 업데이트됩니다.",
            total_rows=0,
            success_count=0,
            unavailable_count=0,
            empty_count=0,
            spreadsheet_id=spreadsheet_id
        )
    except Exception as e:
        logger.error(f"순위 업데이트 시작 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class InsertLinkRequest(BaseModel):
    spreadsheet_id: Optional[str] = None
    target_cell: str = "A1"
    link_text: str = "API 실행"
    api_endpoint: str = "update-ranks"
    base_url: Optional[str] = None


class InsertLinkResponse(BaseModel):
    success: bool
    message: str
    cell: str
    api_url: str
    link_text: str
    spreadsheet_id: str


@router.post("/insert-link", response_model=InsertLinkResponse)
async def insert_link_endpoint(
    request: InsertLinkRequest,
    req: Request = None
):
    """
    Google Sheets의 특정 셀에 API 링크를 삽입합니다 (POST 요청)
    
    - 지정한 셀에 HYPERLINK 함수를 사용하여 API 링크를 삽입합니다.
    - 사용자가 링크를 더블클릭하면 해당 API가 실행됩니다.
    
    사용 예시:
    POST /api/google-sheets/insert-link
    {
        "spreadsheet_id": "1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA",
        "target_cell": "A1",
        "link_text": "순위 업데이트",
        "api_endpoint": "update-ranks"
    }
    """
    try:
        # base_url이 없으면 Request에서 가져오기
        if request.base_url is None and req:
            base_url = f"{req.url.scheme}://{req.url.hostname}"
            if req.url.port:
                base_url += f":{req.url.port}"
        elif request.base_url:
            base_url = request.base_url
        else:
            # 환경변수에서 가져오기
            base_url = os.getenv('GOOGLE_SHEETS_API_BASE_URL', 'http://localhost:8001')
        
        result = insert_api_link_to_sheet(
            spreadsheet_id=request.spreadsheet_id,
            target_cell=request.target_cell,
            link_text=request.link_text,
            api_endpoint=request.api_endpoint,
            base_url=base_url
        )
        
        return InsertLinkResponse(
            success=result['success'],
            message=result['message'],
            cell=result['cell'],
            api_url=result['api_url'],
            link_text=result['link_text'],
            spreadsheet_id=result['spreadsheet_id']
        )
    except Exception as e:
        logger.error(f"API 링크 삽입 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insert-link", response_model=InsertLinkResponse)
async def insert_link_endpoint_get(
    spreadsheet_id: Optional[str] = Query(None, description="Google 스프레드시트 ID"),
    target_cell: str = Query("A1", description="링크를 삽입할 셀 위치"),
    link_text: str = Query("순위 업데이트", description="링크에 표시될 텍스트"),
    api_endpoint: str = Query("update-ranks", description="API 엔드포인트 ('insert-column-timestamp' 또는 'update-ranks')"),
    base_url: Optional[str] = Query(None, description="기본 URL (없으면 자동 감지)"),
    req: Request = None
):
    """
    Google Sheets의 특정 셀에 API 링크를 삽입합니다 (GET 요청)
    
    사용 예시:
    GET /api/google-sheets/insert-link?target_cell=A1&link_text=순위 업데이트&api_endpoint=update-ranks
    """
    try:
        # base_url이 없으면 Request에서 가져오기
        if base_url is None and req:
            base_url = f"{req.url.scheme}://{req.url.hostname}"
            if req.url.port:
                base_url += f":{req.url.port}"
        elif base_url is None:
            # 환경변수에서 가져오기
            base_url = os.getenv('GOOGLE_SHEETS_API_BASE_URL', 'http://localhost:8001')
        
        result = insert_api_link_to_sheet(
            spreadsheet_id=spreadsheet_id,
            target_cell=target_cell,
            link_text=link_text,
            api_endpoint=api_endpoint,
            base_url=base_url
        )
        
        return InsertLinkResponse(
            success=result['success'],
            message=result['message'],
            cell=result['cell'],
            api_url=result['api_url'],
            link_text=result['link_text'],
            spreadsheet_id=result['spreadsheet_id']
        )
    except Exception as e:
        logger.error(f"API 링크 삽입 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup-update-link")
async def setup_update_link_endpoint(
    spreadsheet_id: Optional[str] = Query(None, description="Google 스프레드시트 ID"),
    target_cell: str = Query("A1", description="링크를 삽입할 셀 위치"),
    req: Request = None
):
    """
    순위 업데이트 API 링크를 시트에 삽입하는 편의 엔드포인트
    
    사용 예시:
    POST /api/google-sheets/setup-update-link?target_cell=A1
    """
    try:
        # base_url이 없으면 Request에서 가져오기
        if req:
            base_url = f"{req.url.scheme}://{req.url.hostname}"
            if req.url.port:
                base_url += f":{req.url.port}"
        else:
            base_url = os.getenv('GOOGLE_SHEETS_API_BASE_URL', 'http://localhost:8001')
        
        result = insert_api_link_to_sheet(
            spreadsheet_id=spreadsheet_id,
            target_cell=target_cell,
            link_text="순위 업데이트",
            api_endpoint="update-ranks",
            base_url=base_url
        )
        
        return InsertLinkResponse(
            success=result['success'],
            message=result['message'],
            cell=result['cell'],
            api_url=result['api_url'],
            link_text=result['link_text'],
            spreadsheet_id=result['spreadsheet_id']
        )
    except Exception as e:
        logger.error(f"API 링크 삽입 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/setup-update-link")
async def setup_update_link_endpoint_get(
    spreadsheet_id: Optional[str] = Query(None, description="Google 스프레드시트 ID"),
    target_cell: str = Query("A1", description="링크를 삽입할 셀 위치"),
    req: Request = None
):
    """
    순위 업데이트 API 링크를 시트에 삽입하는 편의 엔드포인트 (GET)
    
    사용 예시:
    GET /api/google-sheets/setup-update-link?target_cell=A1
    """
    return await setup_update_link_endpoint(spreadsheet_id, target_cell, req)


def insert_api_link_to_sheet(
    spreadsheet_id: str = None,
    target_cell: str = "A1",
    link_text: str = "API 실행",
    api_endpoint: str = "insert-column-timestamp",
    base_url: str = "http://localhost:8001"
):
    """
    Google Sheets의 특정 셀에 API 링크를 삽입하는 함수 (Python 테스트용)
    
    Args:
        spreadsheet_id: Google 스프레드시트 ID (None이면 기본값 사용)
        target_cell: 링크를 삽입할 셀 위치 (예: 'A1', 'B2')
        link_text: 링크에 표시될 텍스트
        api_endpoint: API 엔드포인트 ('insert-column-timestamp' 또는 'update-ranks')
        base_url: 기본 URL
    
    Returns:
        dict: 결과 정보
    """
    try:
        # 인증
        if not os.path.exists(CREDENTIALS_FILE):
            raise FileNotFoundError(f"인증 파일을 찾을 수 없습니다: {CREDENTIALS_FILE}")
        
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=SCOPES
        )
        service = build('sheets', 'v4', credentials=credentials)
        logger.info("Google Sheets API 인증 성공")
        
        # 스프레드시트 ID
        if spreadsheet_id is None:
            spreadsheet_id = DEFAULT_SPREADSHEET_ID
        logger.info(f"스프레드시트 ID: {spreadsheet_id}")
        
        # API URL 생성
        api_url = f"{base_url}/api/google-sheets/{api_endpoint}?spreadsheet_id={spreadsheet_id}"
        logger.info(f"API URL: {api_url}")
        
        # HYPERLINK 함수 생성
        hyperlink_formula = f'=HYPERLINK("{api_url}", "{link_text}")'
        logger.info(f"HYPERLINK 함수: {hyperlink_formula}")
        
        # 셀 범위 생성 (시트 이름 포함)
        cell_range = f"{SHEET_NAME}!{target_cell}"
        logger.info(f"셀 범위: {cell_range}")
        
        # 셀에 링크 삽입 (USER_ENTERED 옵션으로 수식 삽입)
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=cell_range,
            valueInputOption='USER_ENTERED',
            body={
                'values': [[hyperlink_formula]]
            }
        ).execute()
        
        logger.info(f"✅ 셀 {target_cell}에 API 링크 삽입 완료: {api_endpoint}")
        
        return {
            'success': True,
            'message': f'셀 {target_cell}에 API 링크 삽입 완료',
            'cell': target_cell,
            'api_url': api_url,
            'link_text': link_text,
            'spreadsheet_id': spreadsheet_id
        }
        
    except HttpError as e:
        logger.error(f"❌ API 링크 삽입 실패: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"❌ API 링크 삽입 중 오류: {e}", exc_info=True)
        raise


# 파일을 직접 실행할 때 테스트용
if __name__ == "__main__":
    import sys
    
    logger.info("=" * 60)
    logger.info("Google Sheets API 링크 삽입 테스트")
    logger.info("=" * 60)
    
    # 명령줄 인자 처리
    if len(sys.argv) < 2:
        logger.info("\n사용법:")
        logger.info("  python google_sheets_api.py <명령> [옵션]")
        logger.info("\n명령:")
        logger.info("  insert-link    - API 링크를 시트에 삽입")
        logger.info("  insert-column  - J열 삽입 및 타임스탬프 기록")
        logger.info("  update-ranks   - J열 삽입 후 순위 업데이트 (기본: J열 삽입 포함)")
        logger.info("\n예시:")
        logger.info("  python google_sheets_api.py insert-link A1 'J열 삽입' insert-column-timestamp")
        logger.info("  python google_sheets_api.py insert-link A2 '순위 업데이트' update-ranks")
        logger.info("  python google_sheets_api.py insert-column")
        logger.info("  python google_sheets_api.py update-ranks")
        logger.info("  python google_sheets_api.py update-ranks [스프레드시트ID] [insert_column_first]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    try:
        if command == "insert-link":
            # insert-link <셀위치> <링크텍스트> <API엔드포인트> [스프레드시트ID] [기본URL]
            if len(sys.argv) < 5:
                logger.error("❌ 인자가 부족합니다.")
                logger.info("사용법: python google_sheets_api.py insert-link <셀위치> <링크텍스트> <API엔드포인트> [스프레드시트ID] [기본URL]")
                logger.info("예시: python google_sheets_api.py insert-link A1 'J열 삽입' insert-column-timestamp")
                sys.exit(1)
            
            target_cell = sys.argv[2]
            link_text = sys.argv[3]
            api_endpoint = sys.argv[4]
            spreadsheet_id = sys.argv[5] if len(sys.argv) > 5 else None
            base_url = sys.argv[6] if len(sys.argv) > 6 else "http://localhost:8001"
            
            result = insert_api_link_to_sheet(
                spreadsheet_id=spreadsheet_id,
                target_cell=target_cell,
                link_text=link_text,
                api_endpoint=api_endpoint,
                base_url=base_url
            )
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ 성공!")
            logger.info(f"셀: {result['cell']}")
            logger.info(f"링크 텍스트: {result['link_text']}")
            logger.info(f"API URL: {result['api_url']}")
            logger.info("=" * 60)
            
        elif command == "insert-column":
            # insert-column [스프레드시트ID]
            spreadsheet_id = sys.argv[2] if len(sys.argv) > 2 else None
            
            result = insert_j_column_and_timestamp(spreadsheet_id)
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ 성공!")
            logger.info(f"타임스탬프: {result['timestamp']}")
            logger.info(f"스프레드시트 ID: {result['spreadsheet_id']}")
            logger.info("=" * 60)
            
        elif command == "update-ranks":
            # update-ranks [스프레드시트ID] [insert_column_first]
            spreadsheet_id = sys.argv[2] if len(sys.argv) > 2 else None
            insert_column_first = sys.argv[3].lower() == 'true' if len(sys.argv) > 3 else True
            
            if spreadsheet_id is None:
                spreadsheet_id = DEFAULT_SPREADSHEET_ID
            
            updater = GoogleSheetsRankUpdater(spreadsheet_id)
            result = updater.update_all_ranks(insert_column_first=insert_column_first)
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ 성공!")
            logger.info(f"총 행 수: {result['total_rows']}")
            logger.info(f"순위 발견: {result['success_count']}개")
            logger.info(f"확인불가: {result['unavailable_count']}개")
            logger.info(f"빈칸: {result['empty_count']}개")
            logger.info(f"스프레드시트 ID: {spreadsheet_id}")
            logger.info("=" * 60)
            
        else:
            logger.error(f"❌ 알 수 없는 명령: {command}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"❌ 실행 중 오류 발생: {e}", exc_info=True)
        sys.exit(1)
