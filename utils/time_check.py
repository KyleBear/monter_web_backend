"""
시간 체크 유틸리티
오후 4시 30분 이후 수정 작업 차단 (슈퍼유저 제외)
"""
from datetime import datetime, time
from fastapi import HTTPException, status

# 슈퍼유저 username 목록
SUPERUSER_USERNAMES = {"admin", "monteur"}


def check_edit_time_allowed(username: str = None, user_role: str = None):
    """
    오후 4시 30분 이후 수정 작업을 차단하는 함수
    슈퍼유저(admin, monter)는 시간 제한 없이 사용 가능
    
    Args:
        username: 사용자명 (슈퍼유저 체크용)
        user_role: 사용자 역할 (하위 호환성을 위해 유지, "admin"이면 체크 안함)
    
    Raises:
        HTTPException: 오후 4시 30분 이후이고 슈퍼유저가 아닌 경우 403 에러 발생
    """
    # 슈퍼유저는 시간 제한 없음 (username 기반 체크)
    if username and username in SUPERUSER_USERNAMES:
        return
    
    # 하위 호환성: role="admin"도 체크 (슈퍼유저는 role="admin"으로 설정됨)
    if user_role == "admin":
        return
    
    now = datetime.now()
    current_time = now.time()
    cutoff_time = time(16, 30)  # 오후 4시 30분
    
    if current_time >= cutoff_time:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="오후 4시 30분 이후에는 수정 작업을 할 수 없습니다."
        )

