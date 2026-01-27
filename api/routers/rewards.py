"""
리워드 관리 API 라우터
- 리워드 목록 조회 (GET /rewards)
- 리워드 타겟 등록 (POST /rewards/targets)
- 리워드 이미지 태그 업데이트 (PUT /rewards/{reward_id})
- reward_target 처리 함수 (process_reward_targets)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import Optional, List
from database import get_db, SessionLocal
from models import RewardTarget, RewardRank, UsersAdmin
from utils.auth_helpers import get_current_user
from datetime import datetime
import random
import logging
import re
from urllib.parse import quote

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
    reward_target_id: Optional[int] = None  # auto increment이므로 Optional
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
            "is_shopping_exposed": reward.is_shopping_exposed if reward.is_shopping_exposed is not None else False,  # 통검 노출여부 (boolean)
            "cpc": reward.cpc if reward.cpc is not None else False,  # CPC 여부 (boolean)
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


@router.get("/public")
async def get_rewards_public(
    db: Session = Depends(get_db)
):
    """
    리워드 목록 조회 API (공개, 인증 불필요)
    랜덤 1개 반환
    """
    try:
        # image_url이 있는 리워드만 조회
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
        random_index = random.randint(0, total_count - 1)
        reward = query.offset(random_index).limit(1).first()
        
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
            "is_shopping_exposed": reward.is_shopping_exposed if reward.is_shopping_exposed is not None else False,
            "cpc": reward.cpc if reward.cpc is not None else False,
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
        # 새 리워드 타겟 생성 (reward_target_id는 auto increment이므로 제거)
        new_target = RewardTarget(
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


@router.put("/{reward_id}/public")
async def update_reward_image_tag_public(
    reward_id: int,
    update_data: RewardImageTagUpdate,
    db: Session = Depends(get_db)
):
    """
    리워드 이미지 태그 업데이트 API (공개, 인증 불필요)
    
    Args:
        reward_id: 리워드 ID
        update_data: 이미지 태그 정보
    """
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


# ==================== reward_target 처리 함수 ====================

def extract_nvmid_from_product_url(product_url: str) -> Optional[str]:
    """
    product_url에서 nvmid 추출
    
    Args:
        product_url: 상품 URL (스마트스토어 URL 또는 네이버 쇼핑 URL)
    
    Returns:
        nvmid 문자열 또는 None
    """
    if not product_url:
        return None
    
    try:
        # product_url.py의 함수 사용
        from api.routers.product_url import get_nvmid_from_url
        nvmid = get_nvmid_from_url(product_url, verbose=False)
        return nvmid
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"product_url에서 nvmid 추출 실패: {product_url}, error: {e}")
        return None


def process_reward_targets():
    """
    reward_target 테이블을 읽어서 키워드 정보 추출 후 reward_rank에 저장
    """
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    
    try:
        # reward_target에서 모든 항목 조회
        targets = db.query(RewardTarget).all()
        
        if not targets:
            logger.info("처리할 reward_target이 없습니다.")
            return
        
        logger.info(f"처리할 reward_target 개수: {len(targets)}")
        
        # keyword_search 관련 함수 import
        from api.routers.keyword_search import (
            get_api_rank_by_keyword,
            get_shopping_rank_with_ad_flag,
            check_exposure_and_cpc_for_keywords
        )
        from api.routers.keyword_search_api2 import (
            remove_html_tags,
            generate_search_url
        )
        
        for idx, target in enumerate(targets, 1):
            try:
                logger.info(f"[{idx}/{len(targets)}] reward_target_id: {target.reward_target_id}, keyword: {target.keyword}")
                
                # nvmid 가져오기 (reward_target에 저장된 nvmid 사용, 없으면 product_url에서 추출)
                nvmid = target.nvmid
                if not nvmid:
                    nvmid = extract_nvmid_from_product_url(target.product_url)
                    if not nvmid:
                        logger.warning(f"reward_target_id {target.reward_target_id}: nvmid 추출 실패, product_url: {target.product_url}")
                        # 처리 실패로 표시하지 않고 다음에 재시도
                        continue
                
                logger.info(f"사용할 nvmid: {nvmid}")
                
                # 키워드로 순위 조회
                rank = get_api_rank_by_keyword(target.keyword, nvmid, max_rank=1000)
                
                if not rank:
                    logger.info(f"키워드 '{target.keyword}': 순위 없음 (nvmid: {nvmid})")
                    # 순위가 없어도 저장은 진행 (통검 노출여부/CPC는 조회)
                    rank = None
                
                # 상품 정보 조회
                api_results = get_shopping_rank_with_ad_flag(target.keyword, display=100, start=1)
                
                if not api_results or len(api_results) == 0:
                    logger.warning(f"키워드 '{target.keyword}': API 결과 없음")
                    continue
                
                # nvmid 매칭 로직 (keyword_search_api2.py와 동일)
                target_nvmid = str(nvmid).strip()
                item = None
                
                for result_item in api_results:
                    # 방법 1: productId가 nvmid와 일치하는지 확인
                    product_id = str(result_item.get("productId", "")).strip()
                    if product_id == target_nvmid:
                        item = result_item
                        break
                    
                    # 방법 2: link URL에서 nvmid 추출하여 비교
                    link = result_item.get("link", "")
                    if link:
                        nvmid_patterns = [
                            r'nv_mid[=_](\d+)',
                            r'nvmid[=_](\d+)',
                            r'nv-mid[=_](\d+)',
                        ]
                        
                        for pattern in nvmid_patterns:
                            match = re.search(pattern, link, re.IGNORECASE)
                            if match and match.group(1) == target_nvmid:
                                item = result_item
                                break
                    
                    if item:
                        break
                
                # nvmid 매칭 성공 여부 확인
                nvmid_matched = item is not None
                
                # nvmid와 일치하는 상품을 찾지 못한 경우 첫 번째 결과 사용
                if not item:
                    item = api_results[0]
                    logger.warning(f"키워드 '{target.keyword}'로 검색한 결과에서 nvmid '{target_nvmid}'를 찾지 못해 첫 번째 결과 사용")
                
                # search_url 가져오기 (reward_target에 저장된 search_url 사용, 없으면 생성)
                search_url = target.search_url
                if not search_url:
                    # 같은 nvmid의 기존 키워드들 조회 (acq 파라미터용)
                    existing_keywords = db.query(RewardRank.keyword).filter(
                        RewardRank.nvmid == nvmid,
                        RewardRank.keyword.isnot(None),
                        RewardRank.keyword != ''
                    ).all()
                    existing_keyword_list = [kw[0] for kw in existing_keywords if kw[0]]
                    all_available_keywords = existing_keyword_list + [target.keyword]
                    
                    search_url = generate_search_url(target.keyword, all_available_keywords)
                    logger.info(f"search_url 생성: {search_url}")
                else:
                    logger.info(f"reward_target에서 search_url 사용: {search_url}")
                
                # HTML 태그 제거된 상품명 및 스토어명 가져오기
                raw_product_name = item.get("product_name", "")
                cleaned_product_name = remove_html_tags(raw_product_name)
                
                raw_store_name = item.get("mall_name", "")
                cleaned_store_name = remove_html_tags(raw_store_name)
                
                # 이미지 URL: nvmid 매칭 성공한 경우에만 저장
                image_url = item.get("image", "") if nvmid_matched else ""
                
                # 통검 노출여부와 CPC 조회
                try:
                    exposure_results = check_exposure_and_cpc_for_keywords(
                        keywords=[target.keyword],
                        nvmid=nvmid,
                        headless=True,
                        max_workers=1
                    )
                    
                    exposure_info = exposure_results[0] if exposure_results else {}
                    is_shopping_exposed = exposure_info.get("is_shopping_exposed", False)
                    cpc = exposure_info.get("cpc", False)
                except Exception as e:
                    logger.error(f"통검 노출여부/CPC 조회 중 오류: {e}", exc_info=True)
                    is_shopping_exposed = False
                    cpc = False
                
                # reward_rank에 저장
                reward_rank = RewardRank(
                    keyword=target.keyword,
                    store_name=cleaned_store_name,
                    product_name=cleaned_product_name,
                    productid=item.get("productId", ""),
                    search_url=search_url,
                    product_url=target.product_url or "",
                    image_url=image_url,
                    image_tag="",  # 나중에 태그 크롤링으로 업데이트
                    nvmid=nvmid,
                    is_shopping_exposed=is_shopping_exposed,
                    cpc=cpc
                )
                
                db.add(reward_rank)
                db.flush()
                
                # reward_target 삭제 (처리 완료 후 제거)
                db.delete(target)
                db.flush()
                
                db.commit()
                
                logger.info(f"✓ reward_target_id {target.reward_target_id}: reward_rank에 저장 완료 (reward_id: {reward_rank.reward_id})")
                
                # 태그 크롤링은 별도로 처리 (나중에 구현)
                # TODO: 이미지 태그 크롤링 로직 추가
                
            except Exception as e:
                logger.error(f"reward_target_id {target.reward_target_id} 처리 중 오류: {e}", exc_info=True)
                db.rollback()
                continue
                
    except Exception as e:
        logger.error(f"process_reward_targets 실행 중 오류: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
