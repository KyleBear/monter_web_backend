# FastAPI 서버 설정 가이드

## 서버 실행 방법

### 1. 환경 변수 설정

`.env` 파일을 생성하고 데이터베이스 연결 정보를 설정하세요:

```
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/monter_db
```

### 2. 서버 실행

#### 방법 1: Python으로 직접 실행
```bash
python main.py
```

#### 방법 2: Uvicorn으로 실행
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

서버가 실행되면:
- API 서버: http://localhost:8000
- API 문서 (Swagger): http://localhost:8000/docs
- API 문서 (ReDoc): http://localhost:8000/redoc

## API 엔드포인트

### 인증
- `POST /api/auth/login` - 로그인
- `POST /api/auth/logout` - 로그아웃
- `GET /api/auth/verify` - 세션 확인

### 계정 관리
- `GET /api/accounts` - 계정 목록 조회
- `GET /api/accounts/{user_id}` - 계정 상세 조회
- `POST /api/accounts` - 계정 생성
- `PUT /api/accounts/{user_id}` - 계정 수정
- `DELETE /api/accounts` - 계정 삭제

### 광고 관리
- `GET /api/advertisements` - 광고 목록 조회
- `GET /api/advertisements/{ad_id}` - 광고 상세 조회
- `POST /api/advertisements` - 광고 생성
- `PUT /api/advertisements/{ad_id}` - 광고 수정
- `DELETE /api/advertisements` - 광고 삭제
- `POST /api/advertisements/extend` - 광고 연장

### 정산 로그
- `GET /api/settlements` - 정산 로그 목록 조회
- `GET /api/settlements/{settlement_id}` - 정산 로그 상세 조회
- `POST /api/settlements` - 정산 로그 생성
- `PUT /api/settlements/{settlement_id}` - 정산 로그 수정

## API 설계서

자세한 API 설계서는 `api_design.txt` 파일을 참조하세요.

## TODO

각 API 라우터 파일(`api/routers/*.py`)에 TODO 주석으로 구현해야 할 내용이 명시되어 있습니다.

## 프론트엔드 연동

프론트엔드는 `C:\Users\dev\Desktop\monter_front\monter_front`에 있으며,
API 요청은 `http://localhost:8000`으로 전송됩니다.

CORS 설정이 이미 포함되어 있어 프론트엔드에서 바로 요청할 수 있습니다.

