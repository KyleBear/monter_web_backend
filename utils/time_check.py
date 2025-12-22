"""
시간 체크 유틸리티
오후 4시 30분 이후 수정 작업 차단
"""
from datetime import datetime, time
from fastapi import HTTPException, status


def check_edit_time_allowed():
    """
    오후 4시 30분 이후 수정 작업을 차단하는 함수
    
    Raises:
        HTTPException: 오후 4시 30분 이후인 경우 403 에러 발생
    """
    now = datetime.now()
    current_time = now.time()
    cutoff_time = time(16, 30)  # 오후 4시 30분
    
    if current_time >= cutoff_time:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="오후 4시 30분 이후에는 수정 작업을 할 수 없습니다."
        )

