"""
리워드 관리 API 라우터
- 리워드 목록 조회 (GET /rewards)
- 리워드 타겟 등록 (POST /rewards/targets)
- 리워드 이미지 태그 업데이트 (PUT /rewards/{reward_id})
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import RewardTarget, RewardRank, UsersAdmin
from utils.auth_helpers import get_current_user
from datetime import datetime
import random

router = APIRouter()


# Admin 권한 체크 함수
def check_admin_permission(current_user: dict, db: Session):
    """admin 권한 체크"""
    username = current_user.get("username")
    user = db.query(UsersAdmin).filter(UsersAdmin.username == username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다."
        )
    
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다."
        )
    
    return user


# ==================== 리워드 타겟 등록 ====================

class RewardTargetCreate(BaseModel):
    reward_target_id: str
    keyword: Optional[str] = None
    product_url: Optional[str] = None


# ==================== 리워드 이미지 태그 업데이트 ====================

class RewardImageTagUpdate(BaseModel):
    image_tag: str


# ==================== API 엔드포인트 ====================

@router.get("")
async def get_rewards(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    리워드 목록 조회 API (랜덤 1개)
    관리자만 접근 가능
    """
    # 관리자 권한 체크
    check_admin_permission(current_user, db)
    
    try:
        # image_url이 있는 리워드만 조회
        # image_url이 NULL이 아니고 빈 문자열이 아닌 조건
        query = db.query(RewardRank).filter(
            RewardRank.image_url.isnot(None),
            RewardRank.image_url != ''
        )
        
        # 전체 리워드 개수 조회 (image_url이 있는 것만)
        total_count = query.count()
        
        if total_count == 0:
            return {
                "success": True,
                "data": {
                    "rewards": []
                }
            }
        
        # 랜덤으로 한 개만 조회
        # 방법 1: Python에서 랜덤 인덱스 선택 후 조회
        random_index = random.randint(0, total_count - 1)
        reward = query.offset(random_index).limit(1).first()
        
        # 방법 2 (대안): SQL의 RAND() 함수 사용 (MySQL의 경우)
        # reward = query.order_by(func.rand()).limit(1).first()
        
        if not reward:
            return {
                "success": True,
                "data": {
                    "rewards": []
                }
            }
        
        # 응답 데이터 변환
        reward_data = {
            "id": reward.reward_id,
            "reward_id": reward.reward_id,
            "keyword": reward.keyword or "",
            "store_name": reward.store_name or "",
            "product_name": reward.product_name or "",
            "productid": reward.productid or "",
            "search_url": reward.search_url or "",
            "product_url": reward.product_url or "",
            "image_url": reward.image_url or "",
            "image_tag": reward.image_tag or "",
            "nvmid": reward.nvmid or "",
            "created_at": reward.created_at.isoformat() if reward.created_at else None,
            "updated_at": reward.updated_at.isoformat() if reward.updated_at else None,
        }
        
        return {
            "success": True,
            "data": {
                "rewards": [reward_data]
            }
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"리워드 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/targets")
async def create_reward_target(
    target: RewardTargetCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    리워드 타겟 등록 API
    관리자만 접근 가능
    
    Args:
        target: 리워드 타겟 정보 (reward_target_id, keyword, product_url)
    """
    # 관리자 권한 체크
    check_admin_permission(current_user, db)
    
    try:
        # reward_target_id 중복 체크
        existing_target = db.query(RewardTarget).filter(
            RewardTarget.reward_target_id == target.reward_target_id
        ).first()
        
        if existing_target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"이미 존재하는 리워드 타겟 ID입니다: {target.reward_target_id}"
            )
        
        # 새 리워드 타겟 생성
        new_target = RewardTarget(
            reward_target_id=target.reward_target_id,
            keyword=target.keyword,
            product_url=target.product_url
        )
        
        db.add(new_target)
        db.commit()
        db.refresh(new_target)
        
        return {
            "success": True,
            "message": "리워드 타겟이 등록되었습니다.",
            "data": {
                "reward_target_id": new_target.reward_target_id,
                "keyword": new_target.keyword,
                "product_url": new_target.product_url
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"리워드 타겟 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/{reward_id}")
async def update_reward_image_tag(
    reward_id: int,
    update_data: RewardImageTagUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    리워드 이미지 태그 업데이트 API
    관리자만 접근 가능
    
    Args:
        reward_id: 리워드 ID
        update_data: 이미지 태그 정보
    """
    # 관리자 권한 체크
    check_admin_permission(current_user, db)
    
    try:
        # 리워드 조회
        reward = db.query(RewardRank).filter(RewardRank.reward_id == reward_id).first()
        
        if not reward:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"리워드를 찾을 수 없습니다: {reward_id}"
            )
        
        # 이미지 태그 업데이트
        reward.image_tag = update_data.image_tag
        reward.updated_at = datetime.now()
        
        db.commit()
        db.refresh(reward)
        
        return {
            "success": True,
            "message": "이미지 태그가 업데이트되었습니다.",
            "data": {
                "reward_id": reward.reward_id,
                "image_tag": reward.image_tag
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"이미지 태그 업데이트 중 오류가 발생했습니다: {str(e)}"
        )


