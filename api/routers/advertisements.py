"""
광고 관리 API 라우터
광고 조회, 생성, 수정, 삭제, 연장
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import AdvertisementsAdmin, UsersAdmin, SettlementAdmin
from utils.time_check import check_edit_time_allowed
from utils.auth_helpers import get_current_user
from datetime import date, datetime, timedelta
import pandas as pd
from io import StringIO
import re

router = APIRouter()


# 요청/응답 모델
class AdvertisementCreate(BaseModel):
    user_id: int
    main_keyword: Optional[str] = None  # URL에서 추출 가능하므로 Optional
    price_comparison: bool = False
    plus: bool = False
    product_name: Optional[str] = None
    # product_mid와 price_comparison_mid는 URL에서만 추출 (직접 입력 불가)
    store_url: Optional[str] = None
    shopping_url: Optional[str] = None
    work_days: int
    start_date: date
    end_date: date


class AdvertisementUpdate(BaseModel):
    status: Optional[str] = None
    main_keyword: Optional[str] = None
    product_name: Optional[str] = None
    product_mid: Optional[str] = None
    store_url: Optional[str] = None
    shopping_url: Optional[str] = None
    memo: Optional[str] = None


class AdvertisementDelete(BaseModel):
    ad_ids: List[int]


class AdvertisementExtend(BaseModel):
    ad_ids: List[int]
    extend_days: int


def _apply_advertisement_permission_filter(
    query,
    current_user: dict,
    db: Session
):
    """
    광고 조회 권한에 따른 필터링 적용
    parent_user_id 기반으로 필터링 (계정 계층 구조 기반)
    - 총판사: 자신 + 직접 하위 대행사 + 그 대행사들의 광고주가 등록한 광고
    - 대행사: 자신 + 직접 하위 광고주가 등록한 광고
    - 광고주: 자신이 등록한 광고만
    """
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 슈퍼유저는 모든 광고 조회 가능
    if current_username in ["admin", "monteur"]:
        return query  # 필터링 없음
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 정보를 찾을 수 없습니다."
        )
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    if actual_role != current_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한 정보가 일치하지 않습니다. 다시 로그인해주세요."
        )
    
    if actual_role == "total":  # 총판사
        # 자신 + 직접 하위 대행사 + 그 대행사들의 광고주가 등록한 광고
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        
        filter_conditions = [
            AdvertisementsAdmin.user_id == actual_user_id  # 자신
        ]
        
        # 직접 하위 대행사
        if agency_ids:
            filter_conditions.append(AdvertisementsAdmin.user_id.in_(agency_ids))
        
        # 간접 하위 (대행사의 광고주)
        if agency_ids:
            advertiser_ids = db.query(UsersAdmin.user_id).filter(
                UsersAdmin.parent_user_id.in_(agency_ids),
                UsersAdmin.role == "advertiser"
            ).all()
            advertiser_id_list = [adv[0] for adv in advertiser_ids]
            if advertiser_id_list:
                filter_conditions.append(AdvertisementsAdmin.user_id.in_(advertiser_id_list))
        
        return query.filter(or_(*filter_conditions))
    
    elif actual_role == "agency":  # 대행사
        # 자신 + 직접 하위 광고주만
        advertiser_ids = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "advertiser"
        ).all()
        advertiser_id_list = [adv[0] for adv in advertiser_ids]
        
        filter_conditions = [
            AdvertisementsAdmin.user_id == actual_user_id  # 자신
        ]
        
        if advertiser_id_list:
            filter_conditions.append(AdvertisementsAdmin.user_id.in_(advertiser_id_list))
        
        return query.filter(or_(*filter_conditions))
    
    elif actual_role == "advertiser":  # 광고주
        # 자신이 등록한 광고 + 상위 대행사가 등록한 광고 조회 가능
        filter_conditions = [
            AdvertisementsAdmin.user_id == actual_user_id  # 자신
        ]
        
        # 상위 대행사가 등록한 광고
        if actual_user.parent_user_id:
            filter_conditions.append(AdvertisementsAdmin.user_id == actual_user.parent_user_id)
        
        return query.filter(or_(*filter_conditions))
    
    return query.filter(AdvertisementsAdmin.user_id == actual_user_id)


def _check_advertisement_ownership(
    ad: AdvertisementsAdmin,
    current_user: dict,
    db: Session
) -> bool:
    """
    광고 소유권 체크
    username 기반으로 실제 user_id 조회 후 체크 이유가 ? 
    """
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 슈퍼유저는 모든 광고 수정/삭제 가능
    if current_username in ["admin", "monteur"]:
        return True
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        return False
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    # 자신이 등록한 광고는 항상 수정 가능
    if ad.user_id == actual_user_id:
        return True
    
    # 광고주 정보 조회
    advertiser = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
    if not advertiser:
        return False
    
    if actual_role == "total":  # 총판사
        # 직접 하위 대행사가 등록한 광고
        if advertiser.parent_user_id == actual_user_id and advertiser.role == "agency":
            return True
        
        # 간접 하위 (대행사의 광고주)가 등록한 광고
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        if advertiser.parent_user_id in agency_ids and advertiser.role == "advertiser":
            return True
        
        return False
    
    elif actual_role == "agency":  # 대행사
        # 자신이 등록한 광고는 수정 가능
        if ad.user_id == actual_user_id:
            return True
        
        # 직접 하위 광고주가 등록한 광고만 수정 가능
        if advertiser.parent_user_id == actual_user_id and advertiser.role == "advertiser":
            return True

        return False
    
    elif actual_role == "advertiser":  # 광고주
        # 자신이 등록한 광고는 수정 가능
        # affiliation + user_id 를 허용한 규칙 으로 총판 규칙을 나중에 추가.
        if ad.user_id == actual_user_id:
            return True
        
        # 상위 대행사가 등록한 광고도 수정 가능
        if actual_user.parent_user_id and ad.user_id == actual_user.parent_user_id:
            # 광고를 등록한 사용자가 대행사인 경우
            if advertiser.role == "agency":
                return True
        
        return False
    
    return False


def _check_user_access_permission(
    target_user_id: int,
    current_user: dict,
    db: Session
) -> bool:
    """
    현재 사용자가 지정한 user_id에 대한 광고 생성 권한이 있는지 확인
    계정 계층 구조 기반
    - 총판사: 자신 + 직접 하위 대행사 + 그 대행사들의 광고주
    - 대행사: 자신 + 직접 하위 광고주
    """
    current_username = current_user.get("username")
    
    # 슈퍼유저는 모든 사용자에 대해 권한 있음
    if current_username in ["admin", "monteur"]:
        return True
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        return False
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    # 자신이면 항상 권한 있음
    if target_user_id == actual_user_id:
        return True
    
    # 대상 사용자 조회
    target_user = db.query(UsersAdmin).filter(UsersAdmin.user_id == target_user_id).first()
    if not target_user:
        return False
    
    if actual_role == "total":  # 총판사
        # 직접 하위 대행사
        if target_user.parent_user_id == actual_user_id and target_user.role == "agency":
            return True
        
        # 간접 하위 (대행사의 광고주)
        direct_agencies = db.query(UsersAdmin.user_id).filter(
            UsersAdmin.parent_user_id == actual_user_id,
            UsersAdmin.role == "agency"
        ).all()
        agency_ids = [agency[0] for agency in direct_agencies]
        if target_user.parent_user_id in agency_ids and target_user.role == "advertiser":
            return True
        
        return False
    
    elif actual_role == "agency":  # 대행사
        # 직접 하위 광고주만
        if target_user.parent_user_id == actual_user_id and target_user.role == "advertiser":
            return True
        return False
    
    return False


@router.get("")
async def get_advertisements(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    search_type: str = Query("all"),
    search_keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    광고 목록 조회 API
    - 페이지네이션 처리
    - 검색 기능 (No, 상품명, 아이디, 키워드, 프로덕트ID, 벤더ID)
    - 상태별 필터링 (정상/오류/대기/종료예정/종료)
    - 권한 기반 필터링 (화면 시작 시부터 적용)
    - 통계 정보 포함
    """
    # 페이지네이션 계산
    offset = (page - 1) * limit
    
    # 기본 쿼리 (JOIN users_admin)
    query = db.query(AdvertisementsAdmin, UsersAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    
    # 권한에 따른 조회 범위 필터링 (가장 먼저 적용 - 화면 시작 시부터)
    query = _apply_advertisement_permission_filter(query, current_user, db)
    
    # 상태 필터링
    if status:
        query = query.filter(AdvertisementsAdmin.status == status)
    
    # 검색 필터링
    if search_keyword:
        if search_type == "no":
            try:
                ad_id = int(search_keyword)
                query = query.filter(AdvertisementsAdmin.ad_id == ad_id)
            except ValueError:
                query = query.filter(False)  # 숫자가 아니면 결과 없음
        elif search_type == "product_name":
            query = query.filter(AdvertisementsAdmin.product_name.contains(search_keyword))
        elif search_type == "userid":
            query = query.filter(UsersAdmin.username.contains(search_keyword))
        elif search_type == "keyword":
            query = query.filter(AdvertisementsAdmin.main_keyword.contains(search_keyword))
        elif search_type == "product_id":
            query = query.filter(AdvertisementsAdmin.product_mid.contains(search_keyword))
        elif search_type == "vendor_id":
            query = query.filter(AdvertisementsAdmin.price_comparison_mid.contains(search_keyword))
        elif search_type == "all":
            query = query.filter(
                or_(
                    AdvertisementsAdmin.product_name.contains(search_keyword),
                    UsersAdmin.username.contains(search_keyword),
                    AdvertisementsAdmin.main_keyword.contains(search_keyword),
                    AdvertisementsAdmin.product_mid.contains(search_keyword),
                    AdvertisementsAdmin.price_comparison_mid.contains(search_keyword)
                )
            )
    
    # 전체 개수 조회
    total = query.count()
    
    # 페이지네이션 적용
    results = query.offset(offset).limit(limit).all()
    
    # 광고 목록 구성
    advertisement_list = []
    for ad, user in results:
        advertisement_list.append({
            "ad_id": ad.ad_id,
            "user_id": ad.user_id,
            "username": user.username,
            "status": ad.status,
            "main_keyword": ad.main_keyword,
            "price_comparison": ad.price_comparison,
            "plus": ad.plus,
            "product_name": ad.product_name or "",
            "product_mid": ad.product_mid or "",
            "price_comparison_mid": ad.price_comparison_mid or "",
            "rank": ad.rank,
            "work_days": ad.work_days,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "affiliation": ad.affiliation or "",
            "created_at": ad.created_at.isoformat() if ad.created_at else None
        })
    
    # 상태별 통계 계산 (권한 범위 내에서만)
    stats_query = db.query(AdvertisementsAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    stats_query = _apply_advertisement_permission_filter(stats_query, current_user, db)
    
    total_count = stats_query.count()
    normal_count = stats_query.filter(AdvertisementsAdmin.status == "normal").count()
    error_count = stats_query.filter(AdvertisementsAdmin.status == "error").count()
    pending_count = stats_query.filter(AdvertisementsAdmin.status == "pending").count()
    ending_count = stats_query.filter(AdvertisementsAdmin.status == "ending").count()
    ended_count = stats_query.filter(AdvertisementsAdmin.status == "ended").count()
    
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    
    return {
        "success": True,
        "data": {
            "advertisements": advertisement_list,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages
        },
        "stats": {
            "total": total_count,
            "normal": normal_count,
            "error": error_count,
            "pending": pending_count,
            "ending": ending_count,
            "ended": ended_count
        }
    }


@router.get("/{ad_id}")
async def get_advertisement(
    ad_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    광고 상세 조회 API
    - 권한 체크 포함
    """
    ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고를 찾을 수 없습니다."
        )
    
    # 권한 체크 (조회 가능한 광고인지 확인)
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고 소유자를 찾을 수 없습니다."
        )
    
    # 권한 필터링 적용하여 조회 가능한지 확인
    query = db.query(AdvertisementsAdmin, UsersAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    ).filter(AdvertisementsAdmin.ad_id == ad_id)
    
    query = _apply_advertisement_permission_filter(query, current_user, db)
    result = query.first()
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 광고를 조회할 권한이 없습니다."
        )
    
    ad, user = result
    
    return {
        "success": True,
        "data": {
            "ad_id": ad.ad_id,
            "user_id": ad.user_id,
            "username": user.username,
            "status": ad.status,
            "main_keyword": ad.main_keyword,
            "price_comparison": ad.price_comparison,
            "plus": ad.plus,
            "product_name": ad.product_name,
            "product_mid": ad.product_mid,
            "price_comparison_mid": ad.price_comparison_mid,
            "rank": ad.rank,
            "work_days": ad.work_days,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "affiliation": ad.affiliation or "",
            "created_at": ad.created_at.isoformat() if ad.created_at else None,
            "updated_at": ad.updated_at.isoformat() if ad.updated_at else None
        }
    }


@router.post("")
async def create_advertisement(
    advertisement: AdvertisementCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 생성 API
    - 광고주는 사용 불가 (광고 수정만 가능)
    - 대행사는 소속 사용자 지정 필수
    - 총판사는 계정 계층 구조 내의 사용자 지정 가능
    - 광고 등록과 동시에 정산 로그 생성 (order 타입)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    # check_edit_time_allowed(
    #     username=current_user.get("username"),
    #     user_role=current_user.get("role")
    # )
    
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 광고주는 사용 불가
    if current_role == "advertiser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="광고주는 광고 등록 API를 사용할 수 없습니다."
        )
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 정보를 찾을 수 없습니다."
        )
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    
    # 세션의 role과 실제 role이 다르면 에러
    if actual_role != current_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한 정보가 일치하지 않습니다. 다시 로그인해주세요."
        )
    
    # 대행사는 소속 사용자 지정 필수
    if actual_role == "agency":
        # 대행사는 자신의 user_id가 아닌 다른 사용자를 지정해야 함
        if advertisement.user_id == actual_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="대행사는 소속 사용자를 지정하여 광고를 등록해야 합니다."
            )
        
        # 소속 사용자인지 확인
        if not _check_user_access_permission(advertisement.user_id, current_user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="계정 계층 구조 내의 사용자만 지정할 수 있습니다."
            )
    elif actual_role == "total":  # 총판사
        # 총판사는 계정 계층 구조 내의 사용자 지정 가능
        if advertisement.user_id != actual_user_id:
            if not _check_user_access_permission(advertisement.user_id, current_user, db):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="계정 계층 구조 내의 사용자만 지정할 수 있습니다."
                )
    # 슈퍼유저는 모든 사용자 지정 가능 (추가 체크 불필요)
    
    # 사용자 존재 확인
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == advertisement.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다."
        )
    
    # 날짜 유효성 검증
    if advertisement.start_date >= advertisement.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="시작일은 종료일보다 이전이어야 합니다."
        )
    
    # main_keyword 필수 체크 (입력받은 값 사용)
    if not advertisement.main_keyword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="main_keyword는 필수입니다."
        )
    
    # 입력받은 main_keyword 사용
    main_keyword = advertisement.main_keyword
    extracted_product_name = None
    extracted_product_mid = None  # URL에서만 추출
    extracted_price_comparison_mid = None  # URL에서만 추출
    extracted_rank = None
    extracted_store_url = advertisement.store_url
    extracted_shopping_url = advertisement.shopping_url
    
    # store_url 또는 shopping_url이 있고 main_keyword가 있으면 순위 조회
    if advertisement.store_url or advertisement.shopping_url:
        try:
            from api.routers.crol import get_rank_by_keyword_and_url
            
            # shopping_url 우선 시도
            url_to_use = None
            if advertisement.shopping_url:
                url_to_use = advertisement.shopping_url
            elif advertisement.store_url:
                url_to_use = advertisement.store_url
            
            if url_to_use:
                # 입력받은 main_keyword를 API로 전달
                result = get_rank_by_keyword_and_url(advertisement.main_keyword, url_to_use)
                
                if result.get("success"):
                    extracted_rank = result.get("rank")
                    # API 매칭 성공 시 API에서 가져온 상품명 사용
                    extracted_product_name = result.get("product_name")                    

                    
                    # product_id가 있으면 product_mid 업데이트 (스마트스토어 URL의 경우)
                    product_id = result.get("product_id")
                    if product_id:
                        extracted_product_mid = product_id
                    
                    # nvmid가 있으면 price_comparison_mid 업데이트 (쇼핑 URL의 경우)
                    nvmid = result.get("nvmid")
                    if nvmid:
                        extracted_price_comparison_mid = nvmid
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"URL에서 정보 추출 실패: {str(e)}")
            # URL 추출 실패해도 광고 등록은 계속 진행
    
    # store_url에서 product_mid 추출 (매칭 성공 여부와 관계없이)
    if advertisement.store_url and not extracted_product_mid:
        match = re.search(r'smartstore\.naver\.com/[^/]+/products/(\d+)', advertisement.store_url)
        if match:
            extracted_product_mid = match.group(1)
    
    # shopping_url에서 price_comparison_mid 추출 (매칭 성공 여부와 관계없이)
    if advertisement.shopping_url and not extracted_price_comparison_mid:
        match = re.search(r'catalog/(\d+)', advertisement.shopping_url)
        if match:
            extracted_price_comparison_mid = match.group(1)
    
    # main_keyword는 이미 위에서 필수 체크 완료
    
    # work_days 계산 (날짜 차이)
    delta = advertisement.end_date - advertisement.start_date
    work_days = delta.days + 1  # 시작일과 종료일 포함
    
    # 트랜잭션 시작 (광고 생성 + 정산 로그 생성)
    try:
        # 광고 생성 (status 기본값: 'pending')
        # 사용자의 affiliation을 광고에 저장
        user_affiliation = user.affiliation if user.affiliation else None
        
        new_advertisement = AdvertisementsAdmin(
            user_id=advertisement.user_id,
            status="pending",
            main_keyword=main_keyword,
            price_comparison=advertisement.price_comparison,
            plus=advertisement.plus,
            product_name=extracted_product_name,
            product_mid=extracted_product_mid,
            price_comparison_mid=extracted_price_comparison_mid,
            work_days=work_days,
            start_date=advertisement.start_date,
            end_date=advertisement.end_date,
            affiliation=user_affiliation,
            rank=extracted_rank,
            store_url=extracted_store_url,
            shopping_url=extracted_shopping_url
        )
        
        db.add(new_advertisement)
        db.flush()  # ad_id를 얻기 위해 flush
        
        # 정산 로그 생성 (order 타입)
        # 대행사 ID 찾기 (광고주의 parent_user_id)
        agency_user_id = user.parent_user_id if user.role == "advertiser" else None
        
        # 작업 수행자 ID (실제로 발주한 유저)
        performed_by_user_id = actual_user_id
        
        new_settlement = SettlementAdmin(
            settlement_type="order",
            agency_user_id=agency_user_id,
            advertiser_user_id=advertisement.user_id,
            ad_id=new_advertisement.ad_id,
            performed_by_user_id=performed_by_user_id,
            quantity=1,
            period_start=advertisement.start_date,
            period_end=advertisement.end_date,
            total_days=work_days,
            start_date=advertisement.start_date,
            ad_product_nm=extracted_product_name  # URL에서 추출한 상품명 사용
        )
        
        db.add(new_settlement)
        db.commit()
        db.refresh(new_advertisement)
        db.refresh(new_settlement)
        
        return {
            "success": True,
            "message": "광고가 생성되었습니다.",
            "data": {
                "ad_id": new_advertisement.ad_id,
                "settlement_id": new_settlement.settlement_id
            }
        }
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"광고 등록 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/upload-csv")
async def upload_advertisements_csv(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    CSV 파일을 통한 광고 일괄 등록 API
    CSV 형식:
    - main_keyword (필수): 메인 키워드
    - price_comparison (선택): Y/N 또는 True/False, 기본값: False
    - product_name (선택): 상품명
    - product_mid (선택): 상품 MID
    - price_comparison_mid (선택): 가격비교 MID
    - start_date (필수): 시작일 (YYYY-MM-DD 형식)
    - end_date (필수): 종료일 (YYYY-MM-DD 형식)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    # check_edit_time_allowed(
    #     username=current_user.get("username"),
    #     user_role=current_user.get("role")
    # )
    
    current_username = current_user.get("username")
    current_role = current_user.get("role")
    
    # 광고주는 사용 불가
    if current_role == "advertiser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="광고주는 CSV 업로드 API를 사용할 수 없습니다."
        )
    
    # username으로 실제 user_id 조회
    actual_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    if not actual_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 정보를 찾을 수 없습니다."
        )
    
    actual_user_id = actual_user.user_id
    actual_role = actual_user.role
    user_affiliation = actual_user.affiliation if actual_user.affiliation else None
    
    # 세션의 role과 실제 role이 다르면 에러
    if actual_role != current_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="권한 정보가 일치하지 않습니다. 다시 로그인해주세요."
        )
    
    # 파일 확장자 확인
    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV 파일만 업로드 가능합니다."
        )
    
    try:
        # 파일 내용 읽기
        contents = await file.read()
        file_content = contents.decode('utf-8-sig')  # BOM 제거
        
        # pandas DataFrame으로 변환
        df = pd.read_csv(StringIO(file_content))
        
        # 빈 파일 체크
        if df.empty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV 파일이 비어있습니다."
            )
        
        # 필수 컬럼 확인
        required_columns = ['main_keyword', 'start_date', 'end_date']
        # 대행사는 user_id 컬럼 필수
        if actual_role == "agency":
            required_columns.append('user_id')
        
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"필수 컬럼이 없습니다: {', '.join(missing_columns)}"
            )
        
        # 결과 저장용
        success_count = 0
        error_count = 0
        errors = []
        created_ad_ids = []
        
        # 각 행 처리
        for index, row in df.iterrows():
            try:
                # user_id 처리 (대행사는 필수, 총판사는 선택)
                if actual_role == "agency":
                    # 대행사는 user_id 필수
                    if 'user_id' not in row or pd.isna(row['user_id']):
                        errors.append(f"행 {index + 2}: 대행사는 user_id를 지정해야 합니다.")
                        error_count += 1
                        continue
                    
                    try:
                        target_user_id = int(row['user_id'])
                    except (ValueError, TypeError):
                        errors.append(f"행 {index + 2}: user_id는 숫자여야 합니다.")
                        error_count += 1
                        continue
                    
                    # 대행사는 자신의 user_id가 아닌 소속 사용자를 지정해야 함
                    if target_user_id == actual_user_id:
                        errors.append(f"행 {index + 2}: 대행사는 소속 사용자를 지정하여 광고를 등록해야 합니다.")
                        error_count += 1
                        continue
                    
                    # 소속 사용자인지 확인
                    if not _check_user_access_permission(target_user_id, current_user, db):
                        errors.append(f"행 {index + 2}: 계정 계층 구조 내의 사용자만 지정할 수 있습니다.")
                        error_count += 1
                        continue
                    
                    # 대상 사용자 존재 확인
                    target_user = db.query(UsersAdmin).filter(UsersAdmin.user_id == target_user_id).first()
                    if not target_user:
                        errors.append(f"행 {index + 2}: 지정한 사용자를 찾을 수 없습니다.")
                        error_count += 1
                        continue
                    
                    row_user_id = target_user_id
                    row_user_affiliation = target_user.affiliation if target_user.affiliation else None
                elif actual_role == "total":
                    # 총판사는 user_id가 있으면 사용, 없으면 자신의 user_id 사용
                    if 'user_id' in row and pd.notna(row['user_id']):
                        try:
                            target_user_id = int(row['user_id'])
                        except (ValueError, TypeError):
                            errors.append(f"행 {index + 2}: user_id는 숫자여야 합니다.")
                            error_count += 1
                            continue
                        
                        # 자신이 아니면 권한 확인
                        if target_user_id != actual_user_id:
                            if not _check_user_access_permission(target_user_id, current_user, db):
                                errors.append(f"행 {index + 2}: 계정 계층 구조 내의 사용자만 지정할 수 있습니다.")
                                error_count += 1
                                continue
                            
                            # 대상 사용자 존재 확인
                            target_user = db.query(UsersAdmin).filter(UsersAdmin.user_id == target_user_id).first()
                            if not target_user:
                                errors.append(f"행 {index + 2}: 지정한 사용자를 찾을 수 없습니다.")
                                error_count += 1
                                continue
                            
                            row_user_id = target_user_id
                            row_user_affiliation = target_user.affiliation if target_user.affiliation else None
                        else:
                            row_user_id = actual_user_id
                            row_user_affiliation = user_affiliation
                    else:
                        row_user_id = actual_user_id
                        row_user_affiliation = user_affiliation
                else:
                    # 슈퍼유저
                    if 'user_id' in row and pd.notna(row['user_id']):
                        try:
                            row_user_id = int(row['user_id'])
                        except (ValueError, TypeError):
                            errors.append(f"행 {index + 2}: user_id는 숫자여야 합니다.")
                            error_count += 1
                            continue
                        
                        target_user = db.query(UsersAdmin).filter(UsersAdmin.user_id == row_user_id).first()
                        if not target_user:
                            errors.append(f"행 {index + 2}: 지정한 사용자를 찾을 수 없습니다.")
                            error_count += 1
                            continue
                        
                        row_user_affiliation = target_user.affiliation if target_user.affiliation else None
                    else:
                        row_user_id = actual_user_id
                        row_user_affiliation = user_affiliation
                
                # 데이터 추출 및 변환
                main_keyword = str(row['main_keyword']).strip()
                if not main_keyword:
                    errors.append(f"행 {index + 2}: main_keyword가 비어있습니다.")
                    error_count += 1
                    continue
                
                # price_comparison 처리
                price_comparison = False
                if 'price_comparison' in row and pd.notna(row['price_comparison']):
                    pc_value = str(row['price_comparison']).strip().upper()
                    price_comparison = pc_value in ['Y', 'TRUE', '1', 'YES']
                
                # plus 처리 (기본값 False)
                plus = False
                if 'plus' in row and pd.notna(row['plus']):
                    plus_value = str(row['plus']).strip().upper()
                    plus = plus_value in ['Y', 'TRUE', '1', 'YES']
                
                # 선택적 필드
                product_name = str(row['product_name']).strip() if 'product_name' in row and pd.notna(row['product_name']) else None
                product_mid = str(row['product_mid']).strip() if 'product_mid' in row and pd.notna(row['product_mid']) else None
                price_comparison_mid = str(row['price_comparison_mid']).strip() if 'price_comparison_mid' in row and pd.notna(row['price_comparison_mid']) else None
                
                # 날짜 파싱
                try:
                    start_date = pd.to_datetime(row['start_date']).date()
                    end_date = pd.to_datetime(row['end_date']).date()
                except Exception as e:
                    errors.append(f"행 {index + 2}: 날짜 형식 오류 - {str(e)}")
                    error_count += 1
                    continue
                
                # 날짜 유효성 검증
                if start_date >= end_date:
                    errors.append(f"행 {index + 2}: 시작일은 종료일보다 이전이어야 합니다.")
                    error_count += 1
                    continue
                
                # work_days 계산
                delta = end_date - start_date
                work_days = delta.days + 1
                
                # 대상 사용자 정보 조회 (정산 로그용)
                row_user = db.query(UsersAdmin).filter(UsersAdmin.user_id == row_user_id).first()
                if not row_user:
                    errors.append(f"행 {index + 2}: 사용자를 찾을 수 없습니다.")
                    error_count += 1
                    continue
                
                # 광고 생성
                new_advertisement = AdvertisementsAdmin(
                    user_id=row_user_id,
                    status="pending",
                    main_keyword=main_keyword,
                    price_comparison=price_comparison,
                    plus=plus,
                    product_name=product_name,
                    product_mid=product_mid,
                    price_comparison_mid=price_comparison_mid,
                    work_days=work_days,
                    start_date=start_date,
                    end_date=end_date,
                    affiliation=row_user_affiliation
                )
                
                db.add(new_advertisement)
                db.flush()
                
                # 정산 로그 생성
                # 대행사 ID 찾기 (광고주의 parent_user_id)
                agency_user_id = row_user.parent_user_id if row_user.role == "advertiser" else None
                
                # 작업 수행자 ID (실제로 발주한 유저)
                performed_by_user_id = actual_user_id
                
                new_settlement = SettlementAdmin(
                    settlement_type="order",
                    agency_user_id=agency_user_id,
                    advertiser_user_id=row_user_id,
                    ad_id=new_advertisement.ad_id,
                    performed_by_user_id=performed_by_user_id,
                    quantity=1,
                    period_start=start_date,
                    period_end=end_date,
                    total_days=work_days,
                    start_date=start_date,
                    ad_product_nm=product_name
                )
                
                db.add(new_settlement)
                created_ad_ids.append(new_advertisement.ad_id)
                success_count += 1
                
            except Exception as e:
                errors.append(f"행 {index + 2}: {str(e)}")
                error_count += 1
                continue
        
        # 트랜잭션 커밋
        db.commit()
        
        return {
            "success": True,
            "message": f"CSV 업로드 완료: {success_count}개 성공, {error_count}개 실패",
            "data": {
                "success_count": success_count,
                "error_count": error_count,
                "created_ad_ids": created_ad_ids,
                "errors": errors[:20] if len(errors) > 20 else errors  # 최대 20개만 반환
            }
        }
    
    except pd.errors.EmptyDataError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV 파일이 비어있습니다."
        )
    except pd.errors.ParserError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV 파싱 오류: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CSV 업로드 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/{ad_id}")
async def update_advertisement(
    ad_id: int,
    advertisement: AdvertisementUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 수정 API
    - 자신의 광고 또는 하위 계정의 광고 수정 가능
    - 총판사: 자신 + 직접 하위 대행사 + 간접 하위(대행사의 광고주)가 등록한 광고 수정 가능
    - 대행사: 자신 + 직접 하위 광고주가 등록한 광고 수정 가능
    - 광고주: 자신이 등록한 광고만 수정 가능
    - store_url에서 마지막 숫자를 추출하여 product_mid로 저장
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    # check_edit_time_allowed(
    #     username=current_user.get("username"),
    #     user_role=current_user.get("role")
    # )
    
    # 광고 조회
    ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고를 찾을 수 없습니다."
        )
    
    # 권한 체크 (총판사/대행사는 하위 계정의 광고도 수정 가능)
    if not _check_advertisement_ownership(ad, current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 광고를 수정할 권한이 없습니다."
        )
    
    # 종료된 광고는 수정 불가
    if ad.status == "ended":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="종료된 광고는 수정할 수 없습니다."
        )
    
    # 상태 변경
    if advertisement.status:
        valid_statuses = ["normal", "error", "pending", "ending", "ended"]
        if advertisement.status not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 상태입니다. 가능한 상태: {', '.join(valid_statuses)}"
            )
        ad.status = advertisement.status
    
    # 메인 키워드 변경
    if advertisement.main_keyword:
        ad.main_keyword = advertisement.main_keyword
    
    # store_url 저장 및 product_mid 추출
    if advertisement.store_url is not None:
        ad.store_url = advertisement.store_url
        # URL에서 마지막 숫자 추출하여 product_mid로 저장
        if advertisement.store_url:
            match = re.search(r'/(\d+)(?:[/?#]|$)', advertisement.store_url)
            if match:
                ad.product_mid = match.group(1)
            else:
                # 숫자를 찾을 수 없으면 에러 처리
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="store_url에서 상품 ID를 추출할 수 없습니다."
                )
    
    # shopping_url 저장 및 price_comparison_mid 추출
    if advertisement.shopping_url is not None:
        ad.shopping_url = advertisement.shopping_url
        # 쇼핑 URL에서 nvmid 추출하여 price_comparison_mid로 저장
        if advertisement.shopping_url:
            # 쇼핑 URL 패턴: https://search.shopping.naver.com/catalog/10639139232
            match = re.search(r'catalog/(\d+)', advertisement.shopping_url)
            if match:
                ad.price_comparison_mid = match.group(1)
            else:
                # 숫자를 찾을 수 없으면 에러 처리
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="shopping_url에서 nvmid를 추출할 수 없습니다."
                )
    
    # 메모 변경
    if advertisement.memo is not None:
        ad.memo = advertisement.memo
    
    # 상품명 변경
    if advertisement.product_name is not None:
        ad.product_name = advertisement.product_name
    
    # 상품 MID 변경 (직접 지정된 경우)
    if advertisement.product_mid is not None:
        ad.product_mid = advertisement.product_mid
    
    # 변경사항이 있으면 수정 로그 생성
    ad.updated_at = datetime.now()
    
    # 광고주 정보 조회 (대행사 ID 찾기 위해)
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
    if user:
        agency_user_id = user.parent_user_id if user.role == "advertiser" else None
        
        # 작업 수행자 ID (실제로 수정한 유저)
        current_username = current_user.get("username")
        performed_by_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
        performed_by_user_id = performed_by_user.user_id if performed_by_user else None
        
        # 수정 로그 생성 (settlement_type='update')
        new_settlement = SettlementAdmin(
            settlement_type="update",
            agency_user_id=agency_user_id,
            advertiser_user_id=ad.user_id,
            ad_id=ad.ad_id,
            performed_by_user_id=performed_by_user_id,
            quantity=None,
            period_start=None,
            period_end=None,
            total_days=None,
            start_date=None,
            ad_product_nm=ad.product_name
        )
        
        db.add(new_settlement)
    
    # 순위 업데이트 (store_url, shopping_url이 있거나 main_keyword와 product_mid가 있는 경우)
    try:
        store_url = advertisement.store_url
        shopping_url = advertisement.shopping_url
        
        if store_url or shopping_url or (ad.main_keyword and ad.product_mid):
            # 순환 import 방지를 위해 함수 내부에서 import
            from api.routers.crol import update_single_advertisement_rank
            update_single_advertisement_rank(
                ad_id=ad.ad_id, 
                db_session=db, 
                store_url=store_url,
                shopping_url=shopping_url
            )
    except Exception as e:
        # 순위 업데이트 실패해도 광고 수정은 계속 진행
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"광고 ID {ad.ad_id} 순위 업데이트 실패: {str(e)}")
    
    db.commit()
    db.refresh(ad)
    
    return {
        "success": True,
        "message": "광고가 수정되었습니다.",
        "data": {
            "ad_id": ad.ad_id
        }
    }


@router.delete("")
async def delete_advertisements(
    delete_request: AdvertisementDelete,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 삭제 API
    - 여러 광고 일괄 삭제
    - 광고주는 사용 불가, 총판사와 대행사만 사용 가능
    - 하드 삭제 (실제 데이터베이스에서 삭제)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    # check_edit_time_allowed(
    #     username=current_user.get("username"),
    #     user_role=current_user.get("role")
    # )
    
    # 광고주는 사용 불가
    current_role = current_user.get("role")
    if current_role == "advertiser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="광고주는 광고 삭제 API를 사용할 수 없습니다."
        )
    
    deleted_count = 0
    not_found_ids = []
    unauthorized_ids = []
    
    for ad_id in delete_request.ad_ids:
        ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
        
        if not ad:
            not_found_ids.append(ad_id)
            continue
        
        # 권한 체크 (총판사/대행사는 하위 계정의 광고도 삭제 가능)
        if not _check_advertisement_ownership(ad, current_user, db):
            unauthorized_ids.append(ad_id)
            continue
        
        # 광고주 정보 조회
        user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
        if user:
            # 작업 수행자 ID (실제로 삭제한 유저)
            current_username = current_user.get("username")
            performed_by_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
            performed_by_user_id = performed_by_user.user_id if performed_by_user else None
            performed_by_role = performed_by_user.role if performed_by_user else None
            
            # 작업 수행자의 role에 따라 advertiser_user_id와 agency_user_id 결정
            if performed_by_role == "agency":
                # 대행사가 삭제한 경우
                agency_user_id = performed_by_user_id  # 작업 수행자
                advertiser_user_id = ad.user_id  # 광고 소유자
            elif performed_by_role == "total":
                # 총판사가 삭제한 경우
                if user.role == "advertiser":
                    agency_user_id = user.parent_user_id  # 광고주의 대행사
                    advertiser_user_id = ad.user_id  # 광고 소유자
                else:
                    agency_user_id = None
                    advertiser_user_id = ad.user_id
            else:
                # 관리자나 기타
                agency_user_id = user.parent_user_id if user.role == "advertiser" else None
                advertiser_user_id = ad.user_id
            
            # 삭제 로그 생성 (settlement_type='refund')
            new_settlement = SettlementAdmin(
                settlement_type="refund",
                agency_user_id=agency_user_id,
                advertiser_user_id=advertiser_user_id,
                ad_id=ad.ad_id,
                performed_by_user_id=performed_by_user_id,
                quantity=None,
                period_start=None,
                period_end=None,
                total_days=None,
                start_date=None,
                ad_product_nm=ad.product_name
            )
            
            db.add(new_settlement)
        
        # 광고 삭제 (하드 삭제)
        db.delete(ad)
        deleted_count += 1
    
    db.commit()
    
    message_parts = []
    if deleted_count > 0:
        message_parts.append(f"{deleted_count}개의 광고가 삭제되었습니다.")
    if not_found_ids:
        message_parts.append(f"{len(not_found_ids)}개 광고를 찾을 수 없습니다.")
    if unauthorized_ids:
        message_parts.append(f"{len(unauthorized_ids)}개 광고는 삭제 권한이 없습니다.")
    
    return {
        "success": True,
        "message": " ".join(message_parts) if message_parts else "광고 삭제가 완료되었습니다.",
        "data": {
            "deleted_count": deleted_count,
            "not_found_ids": not_found_ids,
            "unauthorized_ids": unauthorized_ids
        }
    }


@router.post("/extend")
async def extend_advertisements(
    extend_request: AdvertisementExtend,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    광고 연장 API
    - 여러 광고 일괄 연장
    - 광고를 복사하여 새 광고 생성 (원본 광고는 수정하지 않음)
    - 새 광고의 start_date와 end_date는 원본 광고의 end_date부터 시작
    - 광고주는 사용 불가, 대행사와 총판사만 사용 가능
    - 광고 연장과 동시에 정산 로그 생성 (extend 타입)
    """
    # 오후 4시 30분 이후 수정 차단 (슈퍼유저 제외)
    # check_edit_time_allowed(
    #     username=current_user.get("username"),
    #     user_role=current_user.get("role")
    # )
    
    # 광고주는 사용 불가
    current_role = current_user.get("role")
    if current_role == "advertiser":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="광고주는 광고 연장 API를 사용할 수 없습니다."
        )
    
    extended_ads = []
    not_found_ids = []
    ended_ads = []
    unauthorized_ids = []
    failed_ads = []
    
    for ad_id in extend_request.ad_ids:
        try:
            ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
            
            if not ad:
                not_found_ids.append(ad_id)
                continue
            
            # 권한 체크 (총판사/대행사는 하위 계정의 광고도 연장 가능)
            if not _check_advertisement_ownership(ad, current_user, db):
                unauthorized_ids.append(ad_id)
                continue
            
            # 이미 종료된 광고는 연장 불가
            if ad.status == "ended":
                ended_ads.append(ad_id)
                continue
            
            # 광고주 정보 조회
            user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
            if not user:
                failed_ads.append({"ad_id": ad_id, "reason": "광고주 정보를 찾을 수 없습니다."})
                continue
            
            # end_date가 없으면 연장 불가
            if not ad.end_date:
                failed_ads.append({"ad_id": ad_id, "reason": "종료일 정보가 없습니다."})
                continue
            
            # 새 광고 생성 (원본 광고 복사)
            # start_date와 end_date는 원본 광고의 end_date부터 시작
            new_start_date = ad.end_date
            new_end_date = ad.end_date + timedelta(days=extend_request.extend_days)
            
            # work_days 계산
            new_work_days = extend_request.extend_days
            
            # 새 광고 생성
            new_advertisement = AdvertisementsAdmin(
                user_id=ad.user_id,
                status="pending",  # 새 광고는 pending 상태로 시작
                main_keyword=ad.main_keyword,
                price_comparison=ad.price_comparison,
                plus=ad.plus,
                product_name=ad.product_name,
                product_mid=ad.product_mid,
                price_comparison_mid=ad.price_comparison_mid,
                work_days=new_work_days,
                start_date=new_start_date,
                end_date=new_end_date,
                affiliation=ad.affiliation
            )
            
            db.add(new_advertisement)
            db.flush()  # ad_id를 얻기 위해 flush
            
            # 정산 로그 생성 (extend 타입)
            agency_user_id = user.parent_user_id if user.role == "advertiser" else None
            
            # 작업 수행자 ID (실제로 연장한 유저)
            current_username = current_user.get("username")
            performed_by_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
            performed_by_user_id = performed_by_user.user_id if performed_by_user else None
            
            new_settlement = SettlementAdmin(
                settlement_type="extend",
                agency_user_id=agency_user_id,
                advertiser_user_id=ad.user_id,
                ad_id=new_advertisement.ad_id,
                performed_by_user_id=performed_by_user_id,
                quantity=1,
                period_start=new_start_date,
                period_end=new_end_date,
                total_days=new_work_days,
                start_date=new_start_date,
                ad_product_nm=ad.product_name
            )
            
            db.add(new_settlement)
            
            extended_ads.append({
                "original_ad_id": ad.ad_id,
                "new_ad_id": new_advertisement.ad_id,
                "new_start_date": new_start_date.isoformat(),
                "new_end_date": new_end_date.isoformat(),
                "settlement_id": new_settlement.settlement_id
            })
        
        except Exception as e:
            db.rollback()
            failed_ads.append({"ad_id": ad_id, "reason": f"연장 처리 중 오류: {str(e)}"})
            continue
    
    # 모든 작업이 성공한 경우에만 commit
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"광고 연장 중 오류가 발생했습니다: {str(e)}"
        )
    
    message_parts = []
    if extended_ads:
        message_parts.append(f"{len(extended_ads)}개의 광고가 연장되었습니다.")
    if not_found_ids:
        message_parts.append(f"{len(not_found_ids)}개 광고를 찾을 수 없습니다.")
    if ended_ads:
        message_parts.append(f"{len(ended_ads)}개 광고는 이미 종료되어 연장할 수 없습니다.")
    if unauthorized_ids:
        message_parts.append(f"{len(unauthorized_ids)}개 광고는 연장 권한이 없습니다.")
    if failed_ads:
        message_parts.append(f"{len(failed_ads)}개 광고는 연장 처리에 실패했습니다.")
    
    return {
        "success": True,
        "message": " ".join(message_parts) if message_parts else "광고 연장이 완료되었습니다.",
        "data": {
            "extended_count": len(extended_ads),
            "extended_ads": extended_ads,
            "not_found_ids": not_found_ids,
            "ended_ads": ended_ads,
            "unauthorized_ids": unauthorized_ids,
            "failed_ads": failed_ads
        }
    }

