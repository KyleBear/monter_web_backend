"""
특정 리워드 랭크 ID 태그 크롤링 수동 실행 스크립트
- reward_rank 테이블의 특정 reward_id에 대한 태그 크롤링 수행
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
    logger.info("특정 리워드 랭크 ID 태그 크롤링 수동 실행")
    logger.info("=" * 60)
    logger.info("")
    
    try:
        # reward_id 입력
        reward_id_input = input("크롤링할 reward_id를 입력하세요: ").strip()
        
        if not reward_id_input:
            logger.error("[오류] reward_id를 입력해주세요.")
            sys.exit(1)
        
        try:
            reward_id = int(reward_id_input)
        except ValueError:
            logger.error(f"[오류] 올바른 숫자를 입력해주세요: {reward_id_input}")
            sys.exit(1)
        
        # headless 모드 선택
        headless_input = input("Headless 모드로 실행하시겠습니까? (y/n, 기본값: y): ").strip().lower()
        headless = headless_input != 'n'
        
        logger.info("")
        logger.info(f"reward_id={reward_id} 태그 크롤링 시작...")
        logger.info(f"Headless 모드: {headless}")
        logger.info("")
        
        # 태그 및 이미지 URL 크롤링 실행
        from api.routers.keyword_search_api2 import crawl_tag_for_single_reward
        tag_value, image_url_value = crawl_tag_for_single_reward(reward_id=reward_id, headless=headless)
        
        logger.info("")
        logger.info("=" * 60)
        if tag_value or image_url_value:
            logger.info("[성공] 크롤링 완료!")
            if tag_value:
                logger.info(f"크롤링된 태그: {tag_value}")
            if image_url_value:
                logger.info(f"크롤링된 이미지 URL: {image_url_value[:100]}...")
        else:
            logger.warning("[실패] 태그 및 이미지 URL을 크롤링하지 못했습니다.")
        logger.info("=" * 60)
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("\n[중단] 사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
