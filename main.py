"""
FastAPI 메인 서버
포트 8001에서 실행
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import logging
import random
import time

# API 라우터 임포트
from api.routers import auth, accounts, advertisements, settlements, notices, rewards, rewards_link
from api.routers import keyword_search_api, keyword_search_api2
from api.routers.reward import reward_api_post, reward_api
from api.routers.google_api import google_sheets_api
from database import get_db
from models import RewardLink
from api.routers.rewards_link import generate_acq_from_random_table
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# 로깅 설정
logger = logging.getLogger(__name__)

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
app.include_router(notices.router, prefix="/notices", tags=["공지사항 및 FAQ"])
app.include_router(rewards.router, prefix="/rewards", tags=["리워드 관리"])
app.include_router(rewards_link.router, prefix="/rewards", tags=["리워드 링크 관리"])
app.include_router(reward_api_post.router, tags=["외부 파트너사 리워드 등록"])
app.include_router(reward_api.router, tags=["외부 파트너사 리워드 API (등록/조회)"])
app.include_router(keyword_search_api.router, prefix="/keyword-search", tags=["키워드 검색"])
app.include_router(keyword_search_api2.router, prefix="/keyword-extract", tags=["키워드 추출"])
app.include_router(google_sheets_api.router, prefix="/api/google-sheets", tags=["Google Sheets"])
# app.include_router(google_sheets_api.router, prefix="/google-sheets", tags=["Google Sheets"])  # /api/ 없이도 접근 가능

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


@app.get("/redirect/{short_code}")
async def public_redirect(
    short_code: str,
    db: Session = Depends(get_db)
):
    """
    공개 리다이렉션 엔드포인트 (인증 불필요)
    프론트엔드에서 /redirect/{short_code}로 접속 시 네이버로 리다이렉트
    short_code에 해당하는 RewardLinkKeyword에서 query_keyword를 랜덤으로 선택하여
    새로운 search_url을 생성하여 리다이렉트
    예: http://localhost:3000/redirect/CTTPA2YI1x
    """
    t1 = time.time()
    
    try:
        from models import RewardLinkKeyword
        from api.routers.rewards_link import generate_acq_from_random_table, generate_random_ackey, get_cached_keywords
        
        # 1. 키워드 조회 (캐시 사용)
        keywords = get_cached_keywords(short_code, db)
        t2 = time.time()
        
        if not keywords:
            raise HTTPException(
                status_code=404,
                detail=f"키워드를 찾을 수 없습니다: {short_code}"
            )
        
        # 랜덤으로 하나의 키워드 선택
        random_keyword = random.choice(keywords)
        query_keyword = random_keyword.query_keyword
        
        # random_acq 테이블에서 acq 생성 (캐시 사용)
        acq = generate_acq_from_random_table(db)
        t3 = time.time()
        
        # random_ackey_acq 테이블에서 ackey 가져오기 (캐시 사용)
        from api.routers.rewards_link import get_random_ackey_from_table
        ackey = get_random_ackey_from_table(db)
        
        # ackey가 없으면 랜덤 생성 (fallback)
        if not ackey:
            ackey = generate_random_ackey(8)
            logger.debug("random_ackey_acq 테이블에서 ackey를 가져오지 못해 랜덤 생성")
        
        # 새로운 search_url 생성
        acr = random.randint(1, 10)
        
        naver_url = (
            f"https://m.search.naver.com/search.naver?"
            f"sm=mtp_sug.top&"
            f"where=m&"
            f"query={query_keyword}&"
            f"ackey={ackey}&"
            f"acq={acq}&"
            f"acr={acr}&"
            f"qdt=0"
        )
        
        t4 = time.time()
        # 성능 로그는 DEBUG 레벨로 변경 (샘플링: 1%만 로깅)
        if random.random() < 0.01:  # 1% 샘플링
            logger.debug(f"[공개 리다이렉트 성능] 키워드 조회: {(t2-t1)*1000:.2f}ms, ACQ 생성: {(t3-t2)*1000:.2f}ms, URL 생성: {(t4-t3)*1000:.2f}ms, 전체: {(t4-t1)*1000:.2f}ms")
            logger.debug(f"[공개 리다이렉트] short_code={short_code}, keyword_id={random_keyword.keyword_id}, query='{query_keyword}', acq='{acq}', URL: {naver_url[:150]}...")
        
        # 리다이렉트
        return RedirectResponse(url=naver_url, status_code=302)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"공개 리다이렉트 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"리다이렉트 중 오류가 발생했습니다: {str(e)}"
        )


# 스케줄러 설정
scheduler = BackgroundScheduler()

def schedule_status_update():
    """매일 00시 01분에 실행되는 광고 상태 업데이트 함수"""
    try:
        from api.routers.crol import update_advertisement_statuses_daily
        logger.info("스케줄러: 광고 상태 업데이트 시작")
        update_advertisement_statuses_daily()
        logger.info("스케줄러: 광고 상태 업데이트 완료")
    except Exception as e:
        logger.error(f"스케줄러 상태 업데이트 중 오류: {e}", exc_info=True)

def schedule_rank_update():
    """매일 오전 10시에 실행되는 순위 업데이트 함수"""
    try:
        from api.routers.crol import update_advertisement_ranks_by_shopping_url
        logger.info("스케줄러: 순위 업데이트 시작")
        update_advertisement_ranks_by_shopping_url()
        logger.info("스케줄러: 순위 업데이트 완료")
    except Exception as e:
        logger.error(f"스케줄러 순위 업데이트 중 오류: {e}", exc_info=True)

# def schedule_reward_target_processing():
#     """주기적으로 reward_target을 처리하여 reward_rank에 저장"""
#     try:
#         from api.routers.rewards import process_reward_targets
#         logger.info("스케줄러: reward_target 처리 시작")
#         process_reward_targets()
#         logger.info("스케줄러: reward_target 처리 완료")
#     except Exception as e:
#         logger.error(f"스케줄러 reward_target 처리 중 오류: {e}", exc_info=True)

def schedule_tag_crawling():
    """매일 06시에 태그 및 가격 크롤링 실행 (reward_tag_price_crwaling_indb.py)"""
    try:
        import sys
        import os
        # 프로젝트 루트 경로 추가
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        from reward_tag_price_crwaling_indb import update_reward_rank_tag_and_price
        
        logger.info("스케줄러: 태그 및 가격 크롤링 시작 (reward_tag_price_crwaling_indb.py)")
        update_reward_rank_tag_and_price(
            start_id=None,  # 전체 처리
            end_id=None,    # 전체 처리
            delay=5.0,      # 5초 대기
            max_workers=4    # 병렬 작업 수
        )
        logger.info("스케줄러: 태그 및 가격 크롤링 완료")
    except Exception as e:
        logger.error(f"스케줄러 태그 크롤링 중 오류: {e}", exc_info=True)

# 매일 00시 01분에 광고 상태 업데이트 실행
scheduler.add_job(
    schedule_status_update,
    trigger=CronTrigger(hour=0, minute=1),
    id='update_statuses_daily',
    replace_existing=True
)

# ToDO reward_link 테이블 reward_rank 에 연결 _ 현재 수동 

# 매일 06시에 태그 크롤링 실행
scheduler.add_job(
    schedule_tag_crawling,
    trigger=CronTrigger(hour=6, minute=0),  # 매일 06시
    id='crawl_tags_daily',
    replace_existing=True
)

# 매일 오전 10시에 순위 업데이트 실행
scheduler.add_job(
    schedule_rank_update,
    trigger=CronTrigger(hour=10, minute=0),
    id='update_ranks_by_shopping_url_daily',
    replace_existing=True
)

# 스케줄러 시작
scheduler.start()
logger.info("스케줄러가 시작되었습니다.")
logger.info("- 매일 00시 01분: 광고 상태 업데이트 (pending→normal→ending→ended)")
logger.info("- 매일 01시: reward_target 처리 (reward_rank에 저장)")
logger.info("- 매일 06시: 태그 및 가격 크롤링 (reward_tag_price_crwaling_indb.py)")
logger.info("- 매일 오전 10시: 순위 업데이트")

# 서버 종료 시 스케줄러 종료
atexit.register(lambda: scheduler.shutdown())


if __name__ == "__main__":
    # 서버 실행 (포트 8001)
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        # reload=True  # 개발 모드: 코드 변경 시 자동 재시작
        limit_concurrency=100,
        workers=4, 
        reload=False  # 개발 모드: 코드 변경 시 자동 재시작
    )
