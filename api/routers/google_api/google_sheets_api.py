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
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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
CREDENTIALS_FILE = 'credential.json'
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
    
    def update_all_ranks(self) -> Dict:
        """
        전체 순위 업데이트 프로세스 실행
        
        Returns:
            dict: 업데이트 결과 통계
        """
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
                return {
                    'total_rows': 0,
                    'success_count': 0,
                    'unavailable_count': 0,
                    'empty_count': 0
                }
            
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
            
            return {
                'total_rows': total_count,
                'success_count': success_count,
                'unavailable_count': unavailable_count,
                'empty_count': empty_count
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
    spreadsheet_id: Optional[str] = Query(None, description="Google 스프레드시트 ID (없으면 기본값 사용)")
):
    """
    Google Sheets 순위 업데이트 (GET 요청)
    
    - G열(키워드), H열(원부 nvmid), I열(가격비교 nvmid)을 읽습니다
    - 네이버 API로 순위를 조회합니다
    - J열에 순위 값을 업데이트합니다 (J7부터 2000행까지)
    
    사용법:
    - Google Sheets에서 HYPERLINK 함수 사용:
      =HYPERLINK("http://localhost:8001/api/google-sheets/update-ranks?spreadsheet_id=1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA", "순위 업데이트")
    - 또는 스프레드시트 ID를 셀에서 참조:
      =HYPERLINK("http://localhost:8001/api/google-sheets/update-ranks?spreadsheet_id=" & A1, "순위 업데이트")
    """
    try:
        if spreadsheet_id is None:
            spreadsheet_id = DEFAULT_SPREADSHEET_ID
        
        updater = GoogleSheetsRankUpdater(spreadsheet_id)
        result = updater.update_all_ranks()
        
        return UpdateRanksResponse(
            success=True,
            message="순위 업데이트 완료",
            total_rows=result['total_rows'],
            success_count=result['success_count'],
            unavailable_count=result['unavailable_count'],
            empty_count=result['empty_count'],
            spreadsheet_id=spreadsheet_id
        )
    except Exception as e:
        logger.error(f"순위 업데이트 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-ranks", response_model=UpdateRanksResponse)
async def update_ranks_endpoint(request: Optional[SpreadsheetRequest] = None):
    """
    Google Sheets 순위 업데이트 (POST 요청)
    
    - G열(키워드), H열(원부 nvmid), I열(가격비교 nvmid)을 읽습니다
    - 네이버 API로 순위를 조회합니다
    - J열에 순위 값을 업데이트합니다 (J7부터 2000행까지)
    """
    try:
        spreadsheet_id = request.spreadsheet_id if request and request.spreadsheet_id else DEFAULT_SPREADSHEET_ID
        
        updater = GoogleSheetsRankUpdater(spreadsheet_id)
        result = updater.update_all_ranks()
        
        return UpdateRanksResponse(
            success=True,
            message="순위 업데이트 완료",
            total_rows=result['total_rows'],
            success_count=result['success_count'],
            unavailable_count=result['unavailable_count'],
            empty_count=result['empty_count'],
            spreadsheet_id=spreadsheet_id
        )
    except Exception as e:
        logger.error(f"순위 업데이트 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
