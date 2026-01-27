"""
단일 광고 순위 업데이트 수동 실행 스크립트
스케줄러 없이 수동으로 특정 광고의 순위를 업데이트할 때 사용
"""
import sys
import os

# 프로젝트 루트 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from api.routers.crol import update_single_advertisement_rank

if __name__ == "__main__":
    print("=" * 60)
    print("단일 광고 순위 업데이트 수동 실행")
    print("=" * 60)
    print()
    
    try:
        # 광고 ID 입력
        ad_id_input = input("광고 ID를 입력하세요: ").strip()
        
        if not ad_id_input:
            print("[오류] 광고 ID를 입력해주세요.")
            sys.exit(1)
        
        try:
            ad_id = int(ad_id_input)
        except ValueError:
            print(f"[오류] 올바른 숫자를 입력해주세요: {ad_id_input}")
            sys.exit(1)
        
        # 선택적 URL 입력
        print()
        print("URL을 직접 지정하려면 입력하세요 (엔터 시 광고의 기존 URL 사용):")
        store_url = input("스마트스토어 URL (선택사항): ").strip() or None
        shopping_url = input("쇼핑 검색 URL (선택사항): ").strip() or None
        
        print()
        print(f"광고 ID {ad_id}의 순위 업데이트 시작...")
        if store_url:
            print(f"  - 스마트스토어 URL: {store_url}")
        if shopping_url:
            print(f"  - 쇼핑 검색 URL: {shopping_url}")
        print()
        
        # 순위 업데이트 실행
        result = update_single_advertisement_rank(
            ad_id=ad_id,
            db_session=None,  # 새 세션 생성
            store_url=store_url,
            shopping_url=shopping_url
        )
        
        print()
        print("=" * 60)
        print("[성공] 순위 업데이트 완료!")
        print("=" * 60)
        print(f"순위: {result.get('rank', 'N/A')}")
        print(f"상품명: {result.get('product_name', 'N/A')}")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print()
        print("\n[중단] 사용자에 의해 중단되었습니다.")
        sys.exit(0)
    except Exception as e:
        print()
        print("=" * 60)
        print("[오류] 오류 발생!")
        print("=" * 60)
        print(f"오류 내용: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)