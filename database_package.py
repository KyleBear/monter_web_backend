"""
데이터베이스 연결 설정 (패키징용 - 하드코딩된 DB 정보)
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 패키징된 실행 파일용 - 하드코딩된 DB 정보
# 실제 DB 정보로 변경 필요
DB_HOST = "115.68.195.145"
DB_PORT = 3306
DB_USER = "monter"
DB_PASSWORD = "monter"
DB_NAME = "monter"
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# DATABASE_URL = "mysql+pymysql://your_user:your_password@your_host:3306/your_database"

# SQLAlchemy 엔진 생성
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=50,  # 기본 풀 크기 (각 인스턴스당)
    max_overflow=50,  # 추가 연결 허용 (각 인스턴스당)
    pool_timeout=30,  # 연결 대기 시간 (초)    
    echo=False
)

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스
Base = declarative_base()

def get_db():
    """
    데이터베이스 세션 의존성 함수
    FastAPI에서 사용
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
