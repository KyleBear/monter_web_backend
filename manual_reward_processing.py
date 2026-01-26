"""
리워드 타겟 처리 및 태그 크롤링 수동 실행 스크립트
- reward_target을 읽어서 reward_rank에 저장 (이미지, product_url 추출)
- reward_rank의 태그 크롤링
"""
import logging
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def main():
    """메인 함수"""
    logger.info("=" * 60)
    logger.info("리워드 타겟 처리 및 태그 크롤링 수동 실행 시작")
    logger.info("=" * 60)
    
    try:
        # 1. reward_target 처리 (이미지, product_url 추출하여 reward_rank에 저장)
        logger.info("\n[1단계] reward_target 처리 시작...")
        from api.routers.rewards import process_reward_targets
        process_reward_targets()
        logger.info("[1단계] reward_target 처리 완료\n")
        
        # 2. 태그 크롤링
        logger.info("\n[2단계] 태그 크롤링 시작...")
        from api.routers.keyword_search_api2 import crawl_tags_for_all_rewards
        crawled_count = crawl_tags_for_all_rewards(headless=True, delay=5)
        logger.info(f"[2단계] 태그 크롤링 완료 (크롤링된 레코드: {crawled_count}개)\n")
        
        logger.info("=" * 60)
        logger.info("모든 작업 완료!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
