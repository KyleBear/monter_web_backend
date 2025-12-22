# 로컬 개발 환경 설정 가이드

## 개요
로컬에서 프론트엔드와 백엔드를 동시에 실행하고 수정하는 방법입니다.

## 사전 준비

### 1. 백엔드 의존성 설치
```bash
cd C:\Users\dev\Desktop\monter_web_backend
pip install -r requirements.txt
```

### 2. 프론트엔드 의존성 설치
```bash
cd C:\Users\dev\Desktop\monter_front\monter_front
npm install
```

### 3. 프론트엔드 프록시 패키지 설치 (선택사항)
프록시를 사용하려면:
```bash
cd C:\Users\dev\Desktop\monter_front\monter_front
npm install http-proxy-middleware
```

### 4. 환경 변수 설정
백엔드 루트 디렉토리에 `.env` 파일 생성:
```
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/monter_db
```
또는 개별 변수:
```
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=monter_db
```

## 실행 방법

### 방법 1: 배치 파일 사용 (가장 간단)

백엔드 루트 디렉토리에서:
```bash
start_dev.bat
```

이 배치 파일이 백엔드와 프론트엔드를 각각 새 창에서 실행합니다.

### 방법 2: 터미널 두 개 사용

#### 터미널 1: 백엔드 서버 실행
```bash
cd C:\Users\dev\Desktop\monter_web_backend
python main.py
```

백엔드 서버가 실행되면:
- API 서버: http://localhost:8000
- API 문서 (Swagger): http://localhost:8000/docs
- API 문서 (ReDoc): http://localhost:8000/redoc

**핫 리로드**: `main.py`에 `reload=True`가 설정되어 있어 코드 변경 시 자동으로 서버가 재시작됩니다.

#### 터미널 2: 프론트엔드 서버 실행

**옵션 A: 프록시 사용 (권장)**
```bash
cd C:\Users\dev\Desktop\monter_front\monter_front
node server_proxy.js
```

**옵션 B: 기본 서버 사용**
```bash
cd C:\Users\dev\Desktop\monter_front\monter_front
npm start
```
또는 배치 파일:
```bash
front_local.bat
```

프론트엔드 서버가 실행되면:
- 프론트엔드: http://localhost:3000

## API 연결 설정

### 방법 1: 프록시 사용 (권장)

프론트엔드 서버(`server_proxy.js`)가 `/api/*` 요청을 자동으로 백엔드(`http://localhost:8000`)로 전달합니다.

장점:
- 프론트엔드 코드 수정 불필요
- CORS 문제 없음
- 개발 환경과 프로덕션 환경 분리 용이

### 방법 2: JavaScript에서 API 기본 URL 설정

프론트엔드 JavaScript 파일에서 API 기본 URL을 설정:

```javascript
// 로컬 개발 환경
const API_BASE_URL = 'http://localhost:8000/api';

// 프로덕션 환경
// const API_BASE_URL = '/api';
```

그리고 모든 API 호출을 다음과 같이 수정:
```javascript
// 기존: fetch('/api/auth/login', ...)
// 변경: fetch(`${API_BASE_URL}/auth/login`, ...)
```

## 개발 워크플로우

### 1. 백엔드 수정
- `api/routers/` 폴더의 파일 수정
- `main.py`에 `reload=True`가 설정되어 있어 자동 재시작됨
- 변경 사항이 즉시 반영됨 (콘솔에서 "Reloading..." 메시지 확인)

### 2. 프론트엔드 수정
- `js/` 폴더의 JavaScript 파일 수정
- `css/` 폴더의 CSS 파일 수정
- `*.html` 파일 수정
- 브라우저에서 새로고침 (F5)하면 변경 사항 반영
- Express 서버는 정적 파일을 서빙하므로 자동 반영됨

### 3. 데이터베이스 변경
- `models.py` 수정 후 서버 재시작 필요
- 마이그레이션은 별도로 관리 필요

## 포트 설정

- **백엔드**: 포트 8000
- **프론트엔드**: 포트 3000

포트를 변경하려면:
- 백엔드: `main.py`의 `port=8000` 수정
- 프론트엔드: `server.js`의 `PORT` 변수 수정 또는 환경 변수 `PORT` 설정

## CORS 설정

백엔드의 `main.py`에 이미 CORS 설정이 포함되어 있습니다:
```python
allow_origins=[
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8080",
]
```

프론트엔드 포트를 변경하면 백엔드 CORS 설정도 함께 수정해야 합니다.

## 문제 해결

### 백엔드 서버가 시작되지 않음
1. `.env` 파일이 올바르게 설정되었는지 확인
2. 데이터베이스 연결 정보 확인
3. 포트 8000이 이미 사용 중인지 확인: `netstat -ano | findstr :8000`

### 프론트엔드에서 API 호출 실패
1. 백엔드 서버가 실행 중인지 확인
2. 프록시를 사용하는 경우 `http-proxy-middleware` 패키지 설치 확인
3. 브라우저 개발자 도구(F12)에서 네트워크 탭 확인
4. 콘솔에서 에러 메시지 확인

### 코드 변경이 반영되지 않음
1. 백엔드: 서버 로그에서 자동 재시작 메시지 확인
   - "Reloading..." 메시지가 보이면 정상
2. 프론트엔드: 브라우저 캐시 삭제 후 새로고침 (Ctrl+Shift+R)
3. 브라우저 개발자 도구에서 "Disable cache" 옵션 활성화

### 프록시 오류
프록시를 사용할 때 백엔드 서버가 실행되지 않으면:
```
[Proxy Error] connect ECONNREFUSED 127.0.0.1:8000
```
이 오류가 발생합니다. 백엔드 서버를 먼저 실행하세요.

## 개발 팁

1. **API 테스트**: Swagger UI (http://localhost:8000/docs)에서 API 직접 테스트 가능
2. **로그 확인**: 
   - 백엔드 콘솔에서 요청/응답 로그 확인
   - 프론트엔드 콘솔에서 프록시 로그 확인
3. **브라우저 개발자 도구**: 
   - F12로 네트워크 요청 및 JavaScript 오류 확인
   - Application 탭에서 sessionStorage/localStorage 확인
4. **핫 리로드**: 
   - 백엔드는 자동 재시작 (reload=True)
   - 프론트엔드는 브라우저 새로고침 필요

## 빠른 시작 체크리스트

- [ ] 백엔드 의존성 설치 (`pip install -r requirements.txt`)
- [ ] 프론트엔드 의존성 설치 (`npm install`)
- [ ] 프록시 패키지 설치 (`npm install http-proxy-middleware`) - 선택사항
- [ ] `.env` 파일 생성 및 데이터베이스 정보 설정
- [ ] 백엔드 서버 실행 (`python main.py`)
- [ ] 프론트엔드 서버 실행 (`npm start` 또는 `node server_proxy.js`)
- [ ] 브라우저에서 http://localhost:3000 접속
- [ ] Swagger UI에서 http://localhost:8000/docs 접속하여 API 테스트
