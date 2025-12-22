"""
데이터베이스 연결 설정
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# 데이터베이스 연결 정보 (환경 변수에서 가져오기)
# DATABASE_URL이 직접 정의되어 있으면 사용, 없으면 개별 변수들을 조합
if os.getenv("DATABASE_URL"):
    DATABASE_URL = os.getenv("DATABASE_URL")
else:
    # 개별 변수들로부터 DATABASE_URL 구성
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "3306")
    db_user = os.getenv("DB_USER", "user")
    db_password = os.getenv("DB_PASSWORD", "password")
    db_name = os.getenv("DB_NAME", "monter_db")
    
    DATABASE_URL = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

# SQLAlchemy 엔진 생성
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False  # SQL 쿼리 로깅 (개발 시 True로 설정)
)

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스 (모델들이 상속받을 클래스)
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

