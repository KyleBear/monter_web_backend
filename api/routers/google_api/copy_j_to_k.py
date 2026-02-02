"""
J열 삽입 후 6행에 타임스탬프를 찍는 스크립트
"""

import os
import sys
import logging
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 설정
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDENTIALS_FILE = 'credential.json'
SHEET_NAME = 'N쇼핑'
DEFAULT_SPREADSHEET_ID = '1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA'
TIMESTAMP_ROW = 6  # 6행에 타임스탬프 기록


def insert_j_column_and_timestamp():
    """J열 삽입 후 6행에 타임스탬프 기록"""
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
        spreadsheet_id = sys.argv[1] if len(sys.argv) >= 2 else DEFAULT_SPREADSHEET_ID
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
        logger.info("✅ J열 삽입 완료 (기존 J열이 K열로 이동됨)")
        
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
        
        logger.info(f"✅ J열 {TIMESTAMP_ROW}행에 타임스탬프 기록 완료: {timestamp}")
        
    except HttpError as e:
        logger.error(f"❌ 오류 발생: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 오류 발생: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    insert_j_column_and_timestamp()
