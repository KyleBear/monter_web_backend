"""
FastAPI 메인 서버
포트 8001에서 실행
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# API 라우터 임포트
from api.routers import auth, accounts, advertisements, settlements

# FastAPI 앱 생성
app = FastAPI(
    title="Monter Web Backend API",
    description="Monter 웹 백엔드 API 서버",
    version="1.0.0"
)

# CORS 설정 (프론트엔드에서 요청 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8080",
        # 프론트엔드 주소 추가 가능
        # 프로덕션 환경 (도메인)
        "https://re-switch.co.kr",
        "http://115.68.195.145:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth.router, prefix="/auth", tags=["인증"])
app.include_router(accounts.router, prefix="/accounts", tags=["계정 관리"])
app.include_router(advertisements.router, prefix="/advertisements", tags=["광고 관리"])
app.include_router(settlements.router, prefix="/settlements", tags=["정산 로그"])

# 로컬개발용 API 라우터 등록
# app.include_router(auth.router, prefix="/api/auth", tags=["인증"])
# app.include_router(accounts.router, prefix="/api/accounts", tags=["계정 관리"])
# app.include_router(advertisements.router, prefix="/api/advertisements", tags=["광고 관리"])
# app.include_router(settlements.router, prefix="/api/settlements", tags=["정산 로그"])

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "Monter Web Backend API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}


if __name__ == "__main__":
    # 서버 실행 (포트 8001)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True  # 개발 모드: 코드 변경 시 자동 재시작
    )

