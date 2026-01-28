"""
구간별 리워드 랭크 태그 크롤링 수동 실행 스크립트
- reward_rank 테이블의 특정 구간(reward_id 범위)에 대한 태그 및 이미지 URL 크롤링 수행
- 구간별로 배치 처리하여 효율적으로 크롤링
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

# 구간별 범위 정보
RANGE_INFO = {
    1: (1, 200),
    2: (201, 400),
    3: (401, 600),
    4: (601, 800),
    5: (801, 1000)
}


def print_range_info():
    """구간별 범위 정보 출력"""
    logger.info("=" * 60)
    logger.info("구간별 범위 정보")
    logger.info("=" * 60)
    for range_num, (start, end) in RANGE_INFO.items():
        logger.info(f"  구간 {range_num}: reward_id {start} ~ {end} ({end - start + 1}개)")
    logger.info("=" * 60)
    logger.info("")


def get_range_selection():
    """사용자로부터 구간 선택 받기"""
    logger.info("")
    logger.info("크롤링할 구간을 선택하세요:")
    logger.info("  1: reward_id 1 ~ 200")
    logger.info("  2: reward_id 201 ~ 400")
    logger.info("  3: reward_id 401 ~ 600")
    logger.info("  4: reward_id 601 ~ 800")
    logger.info("  5: reward_id 801 ~ 1000")
    logger.info("  all: 모든 구간 (1~5)")
    logger.info("  custom: 사용자 정의 구간")
    logger.info("")
    
    selection = input("선택 (1-5/all/custom): ").strip().lower()
    
    if selection == 'all':
        return list(RANGE_INFO.values())
    elif selection == 'custom':
        try:
            start_input = input("시작 reward_id: ").strip()
            end_input = input("종료 reward_id: ").strip()
            start_id = int(start_input)
            end_id = int(end_input)
            
            if start_id > end_id:
                logger.error(f"[오류] 시작 ID({start_id})가 종료 ID({end_id})보다 큽니다.")
                return None
            
            return [(start_id, end_id)]
        except ValueError:
            logger.error("[오류] 올바른 숫자를 입력해주세요.")
            return None
    elif selection in ['1', '2', '3', '4', '5']:
        range_num = int(selection)
        return [RANGE_INFO[range_num]]
    else:
        logger.error(f"[오류] 잘못된 선택: {selection}")
        return None


def main():
    """메인 함수"""
    logger.info("=" * 60)
    logger.info("구간별 리워드 랭크 태그 크롤링 수동 실행")
    logger.info("=" * 60)
    logger.info("")
    
    try:
        # 구간별 범위 정보 출력
        print_range_info()
        
        # 구간 선택
        ranges = get_range_selection()
        
        if not ranges:
            logger.error("[오류] 구간 선택이 취소되었습니다.")
            sys.exit(1)
        
        # headless 모드 선택
        headless_input = input("\nHeadless 모드로 실행하시겠습니까? (y/n, 기본값: y): ").strip().lower()
        headless = headless_input != 'n'
        
        # 크롤링 간 대기 시간 설정
        delay_input = input("크롤링 간 대기 시간(초, 기본값: 5): ").strip()
        try:
            delay = int(delay_input) if delay_input else 5
        except ValueError:
            delay = 5
            logger.warning(f"[경고] 잘못된 입력으로 기본값 5초를 사용합니다.")
        
        logger.info("")
        logger.info(f"Headless 모드: {headless}")
        logger.info(f"크롤링 간 대기 시간: {delay}초")
        logger.info("")
        
        # 구간별 크롤링 실행
        from api.routers.keyword_search_api2 import crawl_tags_for_range_rewards
        
        total_stats = {
            'total': 0,
            'crawled': 0,
            'failed': 0,
            'skipped': 0
        }
        
        for idx, (start_id, end_id) in enumerate(ranges, 1):
            logger.info("")
            logger.info("=" * 60)
            logger.info(f"구간 {idx}/{len(ranges)}: reward_id {start_id} ~ {end_id}")
            logger.info("=" * 60)
            logger.info("")
            
            stats = crawl_tags_for_range_rewards(
                start_id=start_id,
                end_id=end_id,
                headless=headless,
                delay=delay
            )
            
            # 전체 통계 누적
            total_stats['total'] += stats['total']
            total_stats['crawled'] += stats['crawled']
            total_stats['failed'] += stats['failed']
            total_stats['skipped'] += stats['skipped']
            
            logger.info("")
            logger.info(f"구간 {idx}/{len(ranges)} 완료: {stats['crawled']}개 성공, {stats['failed']}개 실패, {stats['skipped']}개 건너뜀")
        
        # 전체 결과 출력
        logger.info("")
        logger.info("=" * 60)
        logger.info("전체 크롤링 결과")
        logger.info("=" * 60)
        logger.info(f"  전체 레코드: {total_stats['total']}개")
        logger.info(f"  성공: {total_stats['crawled']}개")
        logger.info(f"  실패: {total_stats['failed']}개")
        logger.info(f"  건너뜀: {total_stats['skipped']}개")
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
