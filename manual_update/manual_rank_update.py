"""
순위 업데이트 수동 실행 스크립트
스케줄러 없이 수동으로 광고 순위를 업데이트할 때 사용
"""
import sys
import os

# 프로젝트 루트 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from api.routers.crol import update_advertisement_ranks_by_shopping_url

if __name__ == "__main__":
    print("=" * 60)
    print("순위 업데이트 수동 실행")
    print("=" * 60)
    print()
    
    try:
        print("순위 업데이트 시작...")
        update_advertisement_ranks_by_shopping_url()
        print()
        print("=" * 60)
        print("[성공] 순위 업데이트 완료!")
        print("=" * 60)
    except Exception as e:
        print()
        print("=" * 60)
        print("[오류] 오류 발생!")
        print("=" * 60)
        print(f"오류 내용: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
