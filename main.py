"""
FastAPI 메인 서버
포트 8001에서 실행
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import logging

# API 라우터 임포트
from api.routers import auth, accounts, advertisements, settlements, notices, rewards, rewards_link
from api.routers import keyword_search_api, keyword_search_api2

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
app.include_router(keyword_search_api.router, prefix="/keyword-search", tags=["키워드 검색"])
app.include_router(keyword_search_api2.router, prefix="/keyword-extract", tags=["키워드 추출"])

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

def schedule_reward_target_processing():
    """주기적으로 reward_target을 처리하여 reward_rank에 저장"""
    try:
        from api.routers.rewards import process_reward_targets
        logger.info("스케줄러: reward_target 처리 시작")
        process_reward_targets()
        logger.info("스케줄러: reward_target 처리 완료")
    except Exception as e:
        logger.error(f"스케줄러 reward_target 처리 중 오류: {e}", exc_info=True)

def schedule_tag_crawling():
    """매일 02시에 태그 크롤링 실행"""
    try:
        from api.routers.keyword_search_api2 import crawl_tags_for_all_rewards
        logger.info("스케줄러: 태그 크롤링 시작")
        crawled_count = crawl_tags_for_all_rewards(headless=True, delay=5)
        logger.info(f"스케줄러: 태그 크롤링 완료 (크롤링된 레코드: {crawled_count}개)")
    except Exception as e:
        logger.error(f"스케줄러 태그 크롤링 중 오류: {e}", exc_info=True)

# 매일 00시 01분에 광고 상태 업데이트 실행
scheduler.add_job(
    schedule_status_update,
    trigger=CronTrigger(hour=0, minute=1),
    id='update_statuses_daily',
    replace_existing=True
)

# 매일 01시에 reward_target 처리 실행
scheduler.add_job(
    schedule_reward_target_processing,
    trigger=CronTrigger(hour=1, minute=0),  # 매일 01시
    id='process_reward_targets',
    replace_existing=True
)

# 매일 02시에 태그 크롤링 실행
scheduler.add_job(
    schedule_tag_crawling,
    trigger=CronTrigger(hour=2, minute=0),  # 매일 02시
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
logger.info("- 매일 02시: 태그 크롤링 (reward_rank 테이블)")
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
        reload=False  # 개발 모드: 코드 변경 시 자동 재시작
    )




