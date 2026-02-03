"""
Google Sheets API 접근 테스트
서비스 계정 또는 Gmail 계정으로 스프레드시트에 접근
"""
import os
import sys
from dotenv import load_dotenv
import logging

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def authenticate():
    """
    Google Sheets API 인증
    서비스 계정 또는 OAuth2를 사용하여 인증
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
        from google.oauth2.credentials import Credentials as OAuthCredentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        import pickle
    except ImportError:
        logger.error("❌ 필요한 라이브러리가 설치되지 않았습니다.")
        logger.info("설치 명령어: pip install gspread google-auth google-auth-oauthlib google-auth-httplib2")
        return None
    
    # OAuth2 스코프
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
              'https://www.googleapis.com/auth/drive']
    
    # 서비스 계정 파일 경로 (우선순위 1)
    SERVICE_ACCOUNT_FILE = 'meal-planner-nrank.json'
    
    # OAuth2 파일 경로
    TOKEN_FILE = 'token.pickle'
    CREDENTIALS_FILE = 'credentials.json'
    
    creds = None
    
    # 방법 1: 서비스 계정 파일 사용 (우선순위)
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        logger.info(f"[인증] 서비스 계정 파일 사용: {SERVICE_ACCOUNT_FILE}")
        try:
            creds = ServiceAccountCredentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=SCOPES
            )
            logger.info("✅ 서비스 계정 인증 성공")
            logger.info(f"   서비스 계정 이메일: {creds.service_account_email}")
            logger.info("   ⚠️  스프레드시트에 이 이메일을 공유해야 합니다!")
            return creds
        except Exception as e:
            logger.error(f"❌ 서비스 계정 인증 실패: {e}")
            creds = None
    
    # 방법 2: OAuth2 사용 (Gmail 계정)
    # 기존 토큰 파일이 있으면 로드
    if os.path.exists(TOKEN_FILE):
        logger.info(f"[인증] 기존 토큰 파일 로드: {TOKEN_FILE}")
        try:
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            logger.warning(f"토큰 파일 로드 실패: {e}")
            creds = None
    
    # 토큰이 없거나 만료된 경우
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("[인증] 토큰 만료됨, 새로고침 시도...")
            try:
                creds.refresh(Request())
                logger.info("✅ 토큰 새로고침 성공")
            except Exception as e:
                logger.error(f"❌ 토큰 새로고침 실패: {e}")
                creds = None
        
        # 새로 인증 필요
        if not creds:
            logger.info("[인증] 새로운 OAuth2 인증 필요")
            
            # 방법 2-1: credentials.json 파일 사용
            if os.path.exists(CREDENTIALS_FILE):
                logger.info(f"[인증] credentials.json 파일 사용: {CREDENTIALS_FILE}")
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                    creds = flow.run_local_server(port=0)
                    logger.info("✅ OAuth2 인증 성공")
                except Exception as e:
                    logger.error(f"❌ OAuth2 인증 실패: {e}")
                    creds = None
            
            # 방법 2-2: 환경 변수에서 클라이언트 정보 사용
            else:
                google_client_id = os.getenv("GOOGLE_CLIENT_ID")
                google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
                
                if google_client_id and google_client_secret:
                    logger.info("[인증] 환경 변수에서 클라이언트 정보 사용")
                    try:
                        from google_auth_oauthlib.flow import Flow
                        
                        client_config = {
                            "installed": {
                                "client_id": google_client_id,
                                "client_secret": google_client_secret,
                                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                "token_uri": "https://oauth2.googleapis.com/token",
                                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                                "redirect_uris": ["http://localhost"]
                            }
                        }
                        
                        flow = Flow.from_client_config(client_config, SCOPES)
                        flow.redirect_uri = 'http://localhost'
                        auth_url, _ = flow.authorization_url(prompt='consent')
                        
                        logger.info("\n" + "=" * 60)
                        logger.info("다음 URL을 브라우저에서 열고 Gmail 계정으로 로그인하세요:")
                        logger.info("=" * 60)
                        logger.info(auth_url)
                        logger.info("=" * 60)
                        logger.info("\n인증 후 리다이렉트된 URL을 입력하세요:")
                        
                        redirect_response = input().strip()
                        flow.fetch_token(authorization_response=redirect_response)
                        creds = flow.credentials
                        logger.info("✅ OAuth2 인증 성공")
                    except Exception as e:
                        logger.error(f"❌ OAuth2 인증 실패: {e}")
                        creds = None
                else:
                    logger.error("❌ 인증 정보가 없습니다.")
                    logger.info("\n[설정 방법]")
                    logger.info("방법 1: 서비스 계정 파일 사용 (권장)")
                    logger.info("  - meal-planner-nrank.json 파일이 있으면 자동으로 사용됩니다")
                    logger.info("  - 스프레드시트에 서비스 계정 이메일을 공유해야 합니다")
                    logger.info("\n방법 2: OAuth2 credentials.json 파일 생성")
                    logger.info("  1. https://console.cloud.google.com 접속")
                    logger.info("  2. 프로젝트 생성 (또는 기존 프로젝트 선택)")
                    logger.info("  3. API 및 서비스 > 사용자 인증 정보")
                    logger.info("  4. '사용자 인증 정보 만들기' > 'OAuth 클라이언트 ID'")
                    logger.info("  5. 애플리케이션 유형: '데스크톱 앱' 선택")
                    logger.info("  6. 다운로드한 JSON 파일을 'credentials.json'으로 저장")
                    logger.info("\n방법 3: 환경 변수 설정")
                    logger.info("  GOOGLE_CLIENT_ID=your_client_id")
                    logger.info("  GOOGLE_CLIENT_SECRET=your_client_secret")
                    return None
        
        # 토큰 저장 (OAuth2만)
        if creds and isinstance(creds, OAuthCredentials):
            logger.info(f"[인증] 토큰 저장: {TOKEN_FILE}")
            try:
                with open(TOKEN_FILE, 'wb') as token:
                    pickle.dump(creds, token)
                logger.info("✅ 인증 완료")
            except Exception as e:
                logger.warning(f"토큰 저장 실패: {e}")
    
    return creds


def test_google_sheets_access():
    """
    서비스 계정 또는 Gmail 계정으로 스프레드시트 접근 테스트
    
    스프레드시트 URL: https://docs.google.com/spreadsheets/d/1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA/edit?gid=0#gid=0
    """
    try:
        logger.info("=" * 60)
        logger.info("Google Sheets API 접근 테스트 시작")
        logger.info("=" * 60)
        
        # 인증 (서비스 계정 또는 OAuth2)
        credentials = authenticate()
        
        if not credentials:
            logger.error("❌ 인증 실패")
            return False
        
        import gspread
        
        # gspread 클라이언트 생성
        try:
            logger.info("\n[gspread 클라이언트 생성 중...]")
            gc = gspread.authorize(credentials)
            logger.info("✅ gspread 클라이언트 생성 성공")
        except Exception as e:
            logger.error(f"❌ gspread 클라이언트 생성 실패: {e}")
            return False
        
        # 스프레드시트 ID
        spreadsheet_id = "1aJzc2kw9dLghK-ltp7B0jyAQT7SjcgYRd0l0qOl1FmA"
        
        # 스프레드시트 열기
        try:
            logger.info(f"\n[스프레드시트 열기 중...] (ID: {spreadsheet_id})")
            spreadsheet = gc.open_by_key(spreadsheet_id)
            logger.info(f"✅ 스프레드시트 열기 성공: {spreadsheet.title}")
        except gspread.exceptions.SpreadsheetNotFound:
            logger.error(f"❌ 스프레드시트를 찾을 수 없습니다. (ID: {spreadsheet_id})")
            logger.info("스프레드시트 ID가 올바른지 확인하세요.")
            return False
        except gspread.exceptions.APIError as e:
            logger.error(f"❌ API 오류: {e}")
            logger.info("스프레드시트에 대한 접근 권한이 있는지 확인하세요.")
            if hasattr(credentials, 'service_account_email'):
                logger.info(f"서비스 계정 이메일({credentials.service_account_email})을 스프레드시트에 공유해야 합니다.")
            else:
                logger.info("Gmail 계정으로 스프레드시트에 접근 권한이 있어야 합니다.")
            return False
        except Exception as e:
            logger.error(f"❌ 스프레드시트 열기 실패: {e}")
            return False
        
        # 첫 번째 시트 정보 확인
        try:
            logger.info("\n[시트 정보 확인 중...]")
            worksheet = spreadsheet.sheet1
            logger.info(f"✅ 첫 번째 시트: {worksheet.title}")
            logger.info(f"   행 수: {worksheet.row_count}")
            logger.info(f"   열 수: {worksheet.col_count}")
            
            # 첫 5행 데이터 읽기 테스트
            logger.info("\n[데이터 읽기 테스트] (처음 5행)")
            values = worksheet.get_all_values()[:5]
            if values:
                for i, row in enumerate(values, 1):
                    logger.info(f"   행 {i}: {row[:5]}")  # 처음 5열만 표시
            else:
                logger.info("   (데이터 없음)")
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ Google Sheets API 접근 테스트 성공!")
            logger.info("=" * 60)
            return True
            
        except Exception as e:
            logger.error(f"❌ 시트 정보 확인 실패: {e}")
            return False
    
    except Exception as e:
        logger.error(f"❌ 테스트 중 예외 발생: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = test_google_sheets_access()
    if not success:
        sys.exit(1)