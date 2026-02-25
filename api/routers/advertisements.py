"""
광고 관리 API 라우터
광고 조회, 생성, 수정, 삭제, 연장
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models import AdvertisementsAdmin, UsersAdmin, SettlementAdmin, AdvertisementRankHistory
from utils.time_check import check_edit_time_allowed
from utils.auth_helpers import get_current_user
from datetime import date, datetime, timedelta
from sqlalchemy import desc
import pandas as pd
from io import StringIO
import re
import csv

router = APIRouter()


# HTML 태그 제거 함수 (유틸리티)
def remove_html_tags(text):
    """HTML 태그 제거"""
    if not text:
        return text
    return re.sub(r'<[^>]+>', '', text).strip()


# 요청/응답 모델
class AdvertisementCreate(BaseModel):
    user_id: Optional[int] = None  # Optional로 변경 (없으면 현재 사용자 사용)
    main_keyword: Optional[str] = None  # URL에서 추출 가능하므로 Optional
    price_comparison: bool = False
    plus: bool = False
    product_name: Optional[str] = None
    # product_mid와 price_comparison_mid는 URL에서만 추출 (직접 입력 불가)
    store_url: Optional[str] = None
    shopping_url: Optional[str] = None
    work_days: Optional[int] = None  # Optional로 변경 (start_date와 end_date로 계산)
    start_date: date  # 필수
    end_date: date  # 필수
    slot: int  # 필수


class AdvertisementUpdate(BaseModel):
    status: Optional[str] = None
    main_keyword: Optional[str] = None
    product_name: Optional[str] = None
    product_mid: Optional[str] = None
    store_url: Optional[str] = None
    shopping_url: Optional[str] = None
    memo: Optional[str] = None
    slot: Optional[int] = None


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
    
    # 기본 쿼리 (admin은 LEFT JOIN, 일반 사용자는 INNER JOIN)
    current_username = current_user.get("username")
    if current_username in ["admin", "monteur"]:
        # admin은 사용자가 없어도 광고 조회 가능 (LEFT JOIN)
        query = db.query(AdvertisementsAdmin, UsersAdmin).outerjoin(
            UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
        )
    else:
        # 일반 사용자는 INNER JOIN
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
            # admin은 LEFT JOIN이므로 NULL 체크 필요
            if current_username in ["admin", "monteur"]:
                query = query.filter(
                    or_(
                        UsersAdmin.username.contains(search_keyword),
                        UsersAdmin.username.is_(None)  # 사용자가 없는 경우도 포함
                    )
                )
            else:
                query = query.filter(UsersAdmin.username.contains(search_keyword))
        elif search_type == "keyword":
            query = query.filter(AdvertisementsAdmin.main_keyword.contains(search_keyword))
        elif search_type == "product_id":
            query = query.filter(AdvertisementsAdmin.product_mid.contains(search_keyword))
        elif search_type == "vendor_id":
            query = query.filter(AdvertisementsAdmin.price_comparison_mid.contains(search_keyword))
        elif search_type == "all":
            # admin은 LEFT JOIN이므로 username 검색 시 NULL 체크 필요
            if current_username in ["admin", "monteur"]:
                query = query.filter(
                    or_(
                        AdvertisementsAdmin.product_name.contains(search_keyword),
                        UsersAdmin.username.contains(search_keyword),
                        AdvertisementsAdmin.main_keyword.contains(search_keyword),
                        AdvertisementsAdmin.product_mid.contains(search_keyword),
                        AdvertisementsAdmin.price_comparison_mid.contains(search_keyword)
                    )
                )
            else:
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
    
    # 페이지네이션 적용 (등록일자 기준 내림차순 정렬 - 최신순)
    results = query.order_by(desc(AdvertisementsAdmin.created_at)).offset(offset).limit(limit).all()
    
    # 광고 ID 목록 추출 (순위 이력 일괄 조회용)
    ad_ids = [ad.ad_id for ad, user in results]
    
    # 순위 이력을 한 번에 조회 (N+1 문제 해결)
    today = date.today()
    rank_dates = [
        today - timedelta(days=1),  # 1일전
        today - timedelta(days=2),   # 2일전
        today - timedelta(days=7)    # 7일전
    ]
    
    # 모든 순위 이력을 한 번에 조회
    rank_history_all = []
    if ad_ids:
        rank_history_all = db.query(AdvertisementRankHistory).filter(
            AdvertisementRankHistory.ad_id.in_(ad_ids),
            AdvertisementRankHistory.rank_date.in_(rank_dates)
        ).all()
    
    # ad_id와 rank_date별로 그룹화 (created_at 최신순으로 첫 번째만 사용)
    rank_history_map = {}
    for rank_record in rank_history_all:
        key = (rank_record.ad_id, rank_record.rank_date)
        if key not in rank_history_map:
            rank_history_map[key] = rank_record
        else:
            # 더 최신 기록이면 업데이트
            if rank_record.created_at and rank_history_map[key].created_at:
                if rank_record.created_at > rank_history_map[key].created_at:
                    rank_history_map[key] = rank_record
            elif rank_record.created_at:
                # 기존 기록에 created_at이 없으면 새 기록으로 업데이트
                rank_history_map[key] = rank_record
    
    # 광고 목록 구성
    advertisement_list = []
    for ad, user in results:
        # 순위 이력에서 조회 (메모리에서)
        rank_1day_ago = None
        rank_2days_ago = None
        rank_7days_ago = None
        
        key_1day = (ad.ad_id, today - timedelta(days=1))
        key_2days = (ad.ad_id, today - timedelta(days=2))
        key_7days = (ad.ad_id, today - timedelta(days=7))
        
        if key_1day in rank_history_map:
            rank_1day_ago = rank_history_map[key_1day].rank
        if key_2days in rank_history_map:
            rank_2days_ago = rank_history_map[key_2days].rank
        if key_7days in rank_history_map:
            rank_7days_ago = rank_history_map[key_7days].rank
        
        advertisement_list.append({
            "ad_id": ad.ad_id,
            "user_id": ad.user_id,
            "username": user.username if user else "삭제된 사용자",
            "status": ad.status,
            "main_keyword": ad.main_keyword,
            "price_comparison": ad.price_comparison,
            "plus": ad.plus,
            "product_name": ad.product_name or "",
            "product_mid": ad.product_mid or "",
            "price_comparison_mid": ad.price_comparison_mid or "",
            "rank": ad.rank,
            "rank_1day_ago": rank_1day_ago,
            "rank_2days_ago": rank_2days_ago,
            "rank_7days_ago": rank_7days_ago,
            "store_url": ad.store_url or "",
            "shopping_url": ad.shopping_url or "",
            "work_days": ad.work_days,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "affiliation": ad.affiliation or "",
            "slot": ad.slot,
            "created_at": ad.created_at.isoformat() if ad.created_at else None
        })
    
    # 상태별 통계 계산 (권한 범위 내에서만) - 한 번의 쿼리로 최적화
    stats_query = db.query(AdvertisementsAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    stats_query = _apply_advertisement_permission_filter(stats_query, current_user, db)
    
    # 한 번의 쿼리로 모든 상태별 개수 계산 (CASE WHEN 사용)
    from sqlalchemy import case
    stats_result = stats_query.with_entities(
        func.count(AdvertisementsAdmin.ad_id).label('total'),
        func.sum(case((AdvertisementsAdmin.status == "normal", 1), else_=0)).label('normal'),
        func.sum(case((AdvertisementsAdmin.status == "error", 1), else_=0)).label('error'),
        func.sum(case((AdvertisementsAdmin.status == "pending", 1), else_=0)).label('pending'),
        func.sum(case((AdvertisementsAdmin.status == "ending", 1), else_=0)).label('ending'),
        func.sum(case((AdvertisementsAdmin.status == "ended", 1), else_=0)).label('ended')
    ).first()
    
    total_count = stats_result.total or 0
    normal_count = stats_result.normal or 0
    error_count = stats_result.error or 0
    pending_count = stats_result.pending or 0
    ending_count = stats_result.ending or 0
    ended_count = stats_result.ended or 0
    
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


@router.get("/export")
async def export_advertisements(
    search_type: str = Query("all"),
    search_keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    광고 목록 CSV 내보내기 API
    - 검색 기능 지원 (No, 상품명, 아이디, 키워드, 프로덕트ID, 벤더ID)
    - 상태별 필터링 (정상/오류/대기/종료예정/종료)
    - 권한 기반 필터링
    - 페이지네이션 없이 모든 결과 내보내기
    """
    # 기본 쿼리 (JOIN users_admin)
    query = db.query(AdvertisementsAdmin, UsersAdmin).join(
        UsersAdmin, AdvertisementsAdmin.user_id == UsersAdmin.user_id
    )
    
    # 권한에 따른 조회 범위 필터링 (가장 먼저 적용)
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
    
    # 모든 광고 조회 (페이지네이션 없음)
    results = query.order_by(AdvertisementsAdmin.created_at.desc()).all()
    
    # CSV 생성
    output = StringIO()
    writer = csv.writer(output)
    
    # 헤더
    writer.writerow([
        "광고ID",
        "상태",
        "메인키워드",
        "상품명",
        "상품MID",
        "가격비교MID",
        "순위",
        "스마트스토어URL",
        "쇼핑URL",
        "작업일수",
        "시작일",
        "종료일",
        "소유자",
        "소속",
        "슬롯",
        "생성일시"
    ])
    
    # 데이터 행
    for ad, user in results:
        # HTML 태그 제거 (상품명에서)
        product_name = ad.product_name or ""
        if product_name:
            product_name = re.sub(r'<[^>]+>', '', product_name)
            product_name = product_name.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
            product_name = product_name.strip()
        
        writer.writerow([
            ad.ad_id or "",
            ad.status or "",
            ad.main_keyword or "",
            product_name,
            ad.product_mid or "",
            ad.price_comparison_mid or "",
            ad.rank or "",
            ad.store_url or "",
            ad.shopping_url or "",
            ad.work_days or "",
            ad.start_date.strftime("%Y-%m-%d") if ad.start_date else "",
            ad.end_date.strftime("%Y-%m-%d") if ad.end_date else "",
            user.username or "",
            ad.affiliation or "",
            str(ad.slot) if ad.slot is not None else "",
            ad.created_at.strftime("%Y-%m-%d %H:%M:%S") if ad.created_at else ""
        ])
    
    # UTF-8 BOM 추가 (한글 호환성)
    csv_data = output.getvalue()
    csv_bytes = '\ufeff' + csv_data
    
    return Response(
        content=csv_bytes.encode('utf-8-sig'),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=advertisements_export.csv"
        }
    )


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
            "store_url": ad.store_url,
            "shopping_url": ad.shopping_url,
            "work_days": ad.work_days,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "affiliation": ad.affiliation or "",
            "slot": ad.slot,
            "created_at": ad.created_at.isoformat() if ad.created_at else None,
            "updated_at": ad.updated_at.isoformat() if ad.updated_at else None
        }
    }


@router.get("/{ad_id}/rank-history")
async def get_advertisement_rank_history(
    ad_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    광고 순위 이력 조회 API (모달용)
    - ad_id를 받아서 최근 7일간의 순위 이력을 반환
    """
    # 광고 존재 및 권한 확인
    ad = db.query(AdvertisementsAdmin).filter(AdvertisementsAdmin.ad_id == ad_id).first()
    
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="광고를 찾을 수 없습니다."
        )
    
    # 권한 체크
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
    
    # 최근 7일간의 순위 이력 조회
    today = date.today()
    seven_days_ago = today - timedelta(days=7)
    
    # 상품명이 변경된 시점 찾기 (SettlementAdmin에서 최신 update 로그 확인)
    product_update_datetime = None
    old_product_name = None
    new_product_name = None
    
    latest_update_settlement = db.query(SettlementAdmin).filter(
        SettlementAdmin.ad_id == ad_id,
        SettlementAdmin.settlement_type == "update",
        SettlementAdmin.ad_product_nm.isnot(None)
    ).order_by(desc(SettlementAdmin.created_at)).first()
    
    if latest_update_settlement and latest_update_settlement.ad_product_nm:
        # 로그 형식: "상품명: 기존값 -> 새값 | ..."
        product_log = latest_update_settlement.ad_product_nm
        if "상품명:" in product_log and "->" in product_log:
            # 상품명이 변경된 경우
            product_update_datetime = latest_update_settlement.created_at
            # 로그에서 이전 상품명과 새 상품명 추출
            import re
            match = re.search(r'상품명:\s*([^|>-]+)\s*->\s*([^|]+)', product_log)
            if match:
                old_product_name = match.group(1).strip()
                new_product_name = match.group(2).strip()
                # "(없음)" 제거
                if old_product_name == "(없음)":
                    old_product_name = None
                if new_product_name == "(없음)":
                    new_product_name = None
    
    # 순위 이력 조회
    rank_history_query = db.query(AdvertisementRankHistory).filter(
        AdvertisementRankHistory.ad_id == ad_id,
        AdvertisementRankHistory.rank_date >= seven_days_ago,
        AdvertisementRankHistory.rank_date <= today
    )
    
    # 상품명이 변경된 경우: 변경 시점 기준으로 이전/이후 이력 분리
    if product_update_datetime:
        # 변경 전: 이전 상품명과 일치하는 이력 (created_at < 변경시점)
        # 변경 후: 현재 상품명과 일치하는 이력 (created_at >= 변경시점)
        # MS SQL Server는 REGEXP_REPLACE를 지원하지 않으므로 Python에서 필터링
        # 먼저 날짜 조건만으로 조회
        all_history = rank_history_query.all()
        
        rank_history = []
        
        # 변경 전 이력 (이전 상품명과 일치)
        if old_product_name:
            cleaned_old_product_name = remove_html_tags(old_product_name)
            for record in all_history:
                if record.created_at and record.created_at < product_update_datetime:
                    cleaned_history_name = remove_html_tags(record.product_name or "")
                    if cleaned_history_name == cleaned_old_product_name:
                        rank_history.append(record)
        elif old_product_name is None:
            # 이전 상품명이 없었던 경우 (None 또는 빈 문자열)
            for record in all_history:
                if record.created_at and record.created_at < product_update_datetime:
                    if not record.product_name or record.product_name.strip() == "":
                        rank_history.append(record)
        
        # 변경 후 이력 (현재 상품명과 일치)
        current_product_name = ad.product_name.strip() if ad.product_name and ad.product_name.strip() else None
        if current_product_name:
            cleaned_current_product_name = remove_html_tags(current_product_name)
            for record in all_history:
                if record.created_at and record.created_at >= product_update_datetime:
                    cleaned_history_name = remove_html_tags(record.product_name or "")
                    if cleaned_history_name == cleaned_current_product_name:
                        rank_history.append(record)
        else:
            # 현재 상품명이 없는 경우
            for record in all_history:
                if record.created_at and record.created_at >= product_update_datetime:
                    if not record.product_name or record.product_name.strip() == "":
                        rank_history.append(record)
        
        # 중복 제거 및 정렬
        seen_ids = set()
        unique_history = []
        for record in rank_history:
            if record.rank_id not in seen_ids:
                seen_ids.add(record.rank_id)
                unique_history.append(record)
        
        rank_history = sorted(unique_history, key=lambda x: (x.rank_date, x.created_at or datetime(1900, 1, 1)), reverse=True)
        rank_history_query = None  # 쿼리 실행 방지
    else:
        # 상품명이 변경되지 않은 경우: 현재 상품명과 일치하는 이력만 조회
        rank_history = None  # 초기화
        if ad.product_name and ad.product_name.strip():
            # 현재 광고의 상품명에서 HTML 태그 제거
            cleaned_product_name = remove_html_tags(ad.product_name.strip())
            
            # MS SQL Server는 REGEXP_REPLACE를 지원하지 않으므로 Python에서 필터링
            # 모든 결과를 가져온 후 Python에서 필터링
            all_rank_history = rank_history_query.all()
            rank_history = []
            for rank_record in all_rank_history:
                cleaned_history_name = remove_html_tags(rank_record.product_name or "")
                if cleaned_history_name == cleaned_product_name:
                    rank_history.append(rank_record)
            # rank_history는 이미 필터링된 리스트이므로 정렬 후 반환
            rank_history = sorted(rank_history, key=lambda x: (x.rank_date, x.created_at or datetime(1900, 1, 1)), reverse=True)
            # rank_history_query를 None으로 설정하여 아래 쿼리 실행 방지
            rank_history_query = None
        else:
            # 상품명이 없는 경우: product_name이 None이거나 빈 문자열인 이력만
            from sqlalchemy import or_
            rank_history_query = rank_history_query.filter(
                or_(
                    AdvertisementRankHistory.product_name.is_(None),
                    AdvertisementRankHistory.product_name == ""
                )
            )
    
    # rank_history_query가 None이 아닌 경우에만 쿼리 실행
    if rank_history_query is not None:
        rank_history = rank_history_query.order_by(
            desc(AdvertisementRankHistory.rank_date), 
            desc(AdvertisementRankHistory.created_at)
        ).all()
    # rank_history_query가 None인 경우 이미 필터링된 rank_history 사용 (예외 처리 블록에서 정의됨)
    
    # rank_history가 None이면 빈 리스트로 초기화
    if rank_history is None:
        rank_history = []
    
    # 일자별로 그룹화 (같은 날짜에 여러 기록이 있을 수 있으므로 최신 것만)
    rank_by_date = {}
    for rank_record in rank_history:
        rank_date_str = rank_record.rank_date.isoformat()
        # 같은 날짜의 기록이 없거나, 더 최신 기록이면 업데이트
        # created_at를 datetime 객체로 저장하여 비교 가능하게 함
        if rank_date_str not in rank_by_date:
            rank_by_date[rank_date_str] = {
                "rank_date": rank_record.rank_date.isoformat(),
                "rank": rank_record.rank,
                "product_name": rank_record.product_name or "",
                "created_at": rank_record.created_at  # datetime 객체로 저장
            }
        else:
            # 더 최신 기록이면 업데이트
            if rank_record.created_at and (not rank_by_date[rank_date_str]['created_at'] or rank_record.created_at > rank_by_date[rank_date_str]['created_at']):
                rank_by_date[rank_date_str] = {
                    "rank_date": rank_record.rank_date.isoformat(),
                    "rank": rank_record.rank,
                    "product_name": rank_record.product_name or "",
                    "created_at": rank_record.created_at  # datetime 객체로 저장
                }
    
    # 날짜순으로 정렬 (최신순)
    rank_list = sorted(rank_by_date.values(), key=lambda x: x['rank_date'], reverse=True)
    
    # 반환 시 created_at를 문자열로 변환
    for rank_item in rank_list:
        if rank_item['created_at']:
            rank_item['created_at'] = rank_item['created_at'].isoformat()
        else:
            rank_item['created_at'] = None
    
    return {
        "success": True,
        "data": {
            "ad_id": ad_id,
            "ranks": rank_list,
            "total_days": len(rank_list)
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
    # 오후 4시 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
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
    
    # user_id가 없으면 현재 사용자의 user_id 사용
    target_user_id = advertisement.user_id if advertisement.user_id else actual_user_id
    
    # 슬롯수 필수 체크
    if advertisement.slot is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="슬롯수는 필수입니다."
        )
    
    # 날짜 유효성 검증
    if advertisement.start_date >= advertisement.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="시작일은 종료일보다 이전이어야 합니다."
        )
    
    # 대행사는 소속 사용자 지정 필수
    if actual_role == "agency":
        # 대행사는 자신의 user_id가 아닌 다른 사용자를 지정해야 함
        if target_user_id == actual_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="대행사는 소속 사용자를 지정하여 광고를 등록해야 합니다."
            )
        
        # 소속 사용자인지 확인
        if not _check_user_access_permission(target_user_id, current_user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="계정 계층 구조 내의 사용자만 지정할 수 있습니다."
            )
    elif actual_role == "total":  # 총판사
        # 총판사는 계정 계층 구조 내의 사용자 지정 가능
        if target_user_id != actual_user_id:
            if not _check_user_access_permission(target_user_id, current_user, db):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="계정 계층 구조 내의 사용자만 지정할 수 있습니다."
            )
    # 슈퍼유저는 모든 사용자 지정 가능 (추가 체크 불필요)
    
    # 사용자 존재 확인
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == target_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다."
        )
    
    # main_keyword는 Optional이므로 없으면 빈 문자열 처리
    main_keyword = advertisement.main_keyword if advertisement.main_keyword else ""
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
            
            # 순위 조회 (shopping_url 우선, 둘 다 있으면 둘 다 처리)
            shopping_rank = None
            shopping_product_name = None
            shopping_nvmid = None
            store_rank = None
            store_product_name = None
            store_nvmid = None
            is_openmall = False
            is_basemall = False
            
            # shopping_url 우선 시도
            if advertisement.shopping_url:
                match = re.search(r'catalog/(\d+)', advertisement.shopping_url)
                if match:
                    # URL 파싱 성공 시 바로 nvmid로 사용 (smartstore와 다르게)
                    extracted_price_comparison_mid = match.group(1)
                try:
                    result = get_rank_by_keyword_and_url(advertisement.main_keyword, advertisement.shopping_url)
                    
                    if result.get("success"):
                        shopping_rank = result.get("rank")
                        shopping_product_name = result.get("product_name")
                        shopping_nvmid = result.get("nvmid")
                        
                        # nvmid가 있으면 price_comparison_mid에 저장, 없으면 NULL로 설정
                        if shopping_nvmid:
                            extracted_price_comparison_mid = shopping_nvmid
                        else:
                            extracted_price_comparison_mid = None
                    else:
                        # 매칭 실패 시 price_comparison_mid를 NULL로 설정
                        extracted_price_comparison_mid = None
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"shopping_url 순위 조회 실패: {e}", exc_info=True)
                    shopping_rank = None
                    shopping_product_name = None
                    shopping_nvmid = None
                    extracted_price_comparison_mid = None
            
            ### 오픈몰 및 basemall 선처리 로직 ###
            # store_url이 오픈마켓 또는 기본몰인 경우 선처리
            if advertisement.store_url:
                store_url_lower = advertisement.store_url.lower()
                
                # 오픈마켓 도메인 체크
                openmall_domains = ['coupang.com', 'auction.co.kr', '11st.co.kr', 'gmarket.co.kr']
                is_openmall = any(domain in store_url_lower for domain in openmall_domains)
                
                # 일반 쇼핑몰 도메인 체크
                basemall_domains = ['rental-zon.com', 'hkoa1.com', 'funart.co.kr']
                is_basemall = any(domain in store_url_lower for domain in basemall_domains)
                
                # 오픈마켓 URL: openmall 크롤링으로 상품명만 추출
                if is_openmall:
                    import os
                    import sys
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    project_root = os.path.dirname(os.path.dirname(current_dir))
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
                    
                    try:
                        from openmall import get_product_name as get_openmall_product_name
                        store_product_name = get_openmall_product_name(advertisement.store_url)
                        if store_product_name:
                            # "Access Denied" 필터링
                            if store_product_name.lower() not in ["access denied", "접근 거부", "forbidden"]:
                                extracted_product_name = store_product_name
                            else:
                                store_product_name = None
                        else:
                            store_product_name = None
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"openmall 크롤링 실패: {e}", exc_info=True)
                        store_product_name = None
                    
                    # 오픈마켓은 순위 조회 불가
                    store_rank = None
                    store_nvmid = None
                    extracted_product_mid = None
                
                # 일반 쇼핑몰 URL: basemall 크롤링으로 상품명만 추출
                elif is_basemall:
                    import os
                    import sys
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    project_root = os.path.dirname(os.path.dirname(current_dir))
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
                    
                    try:
                        from basemall_url import get_product_name as get_basemall_product_name
                        store_product_name = get_basemall_product_name(advertisement.store_url)
                        if store_product_name:
                            extracted_product_name = store_product_name
                        else:
                            store_product_name = None
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"basemall 크롤링 실패: {e}", exc_info=True)
                        store_product_name = None
                    
                    # 일반 쇼핑몰은 순위 조회 불가
                    store_rank = None
                    store_nvmid = None
                    extracted_product_mid = None
            ###
            
            # store_url 처리 (shopping_url 매칭 여부와 관계없이)
            # 오픈마켓/기본몰이 아닌 경우에만 실행
            if advertisement.store_url and not is_openmall and not is_basemall:
                try:
                    result = get_rank_by_keyword_and_url(advertisement.main_keyword, advertisement.store_url)
                    
                    if result.get("success"):
                        store_rank = result.get("rank")
                        store_product_name = result.get("product_name")
                        store_nvmid = result.get("nvmid")
                        
                        # nvmid가 있으면 product_mid에 저장, 없으면 NULL로 설정
                        if store_nvmid:
                            extracted_product_mid = store_nvmid
                        else:
                            # 매칭 성공했지만 nvmid가 없으면 NULL로 설정
                            extracted_product_mid = None
                    else:
                        # 매칭 실패 시 product_mid를 NULL로 설정
                        extracted_product_mid = None
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"store_url 순위 조회 실패: {e}", exc_info=True)
                    store_rank = None
                    store_product_name = None
                    store_nvmid = None
                    extracted_product_mid = None
            
            # 순위 및 상품명 결정 (shopping_url 우선, 둘 다 매칭되면 shopping_url의 순위 사용)
            if shopping_rank is not None:
                extracted_rank = shopping_rank
                if shopping_product_name:
                    extracted_product_name = shopping_product_name
            elif store_rank is not None:
                extracted_rank = store_rank
                if store_product_name:
                    extracted_product_name = store_product_name
            
            # store_url만 있을 때: price_comparison_mid를 None으로 설정
            if advertisement.store_url and not advertisement.shopping_url:
                extracted_price_comparison_mid = None
            
            # shopping_url만 있을 때: product_mid를 None으로 설정
            if advertisement.shopping_url and not advertisement.store_url:
                extracted_product_mid = None
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"URL에서 정보 추출 실패: {str(e)}")
            # URL 추출 실패해도 광고 등록은 계속 진행
    
    # store_url에서 product_mid 추출 (매칭 성공 여부와 관계없이)
    # 매칭된 nvmid가 없을 때만 URL에서 직접 추출
    # URL에서 직접 product_id를 추출하는 방어로직은 제거 (product_id와 nvmid는 다른 값)
    # if advertisement.store_url and not extracted_product_mid:
    #     match = re.search(r'(?:smartstore|brand)\.naver\.com/[^/]+/products/(\d+)', advertisement.store_url)
    #     if match:
    #         extracted_product_mid = match.group(1)
    
    # shopping_url에서 price_comparison_mid 추출 (매칭 성공 여부와 관계없이)
    # 매칭된 nvmid가 없을 때만 URL에서 직접 추출
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
        # 광고 생성 (날짜 기반 자동 상태 계산)
        # 사용자의 affiliation을 광고에 저장
        user_affiliation = user.affiliation if user.affiliation else None
        
        # 날짜 기반 자동 상태 계산
        today = date.today()
        auto_status = "pending"  # 기본값
        
        if advertisement.start_date and advertisement.end_date:
            if today < advertisement.start_date:
                # start_date가 오늘보다 이후(미래)이면 → pending (대기중)
                auto_status = "pending"
            elif today > advertisement.end_date:
                # 오늘 날짜가 end_date 이후이면 → ended
                auto_status = "ended"
            elif today == advertisement.end_date - timedelta(days=1):
                # 오늘 날짜가 end_date 1일전이면 → ending
                auto_status = "ending"
            elif advertisement.start_date <= today <= advertisement.end_date:
                # 오늘이 start_date와 end_date 사이면 → normal
                auto_status = "normal"
        
        new_advertisement = AdvertisementsAdmin(
            user_id=target_user_id,
            status=auto_status,  # 날짜 기반 자동 계산된 상태
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
            slot=advertisement.slot,
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
            advertiser_user_id=target_user_id,
            ad_id=new_advertisement.ad_id,
            performed_by_user_id=performed_by_user_id,
            quantity=advertisement.slot if advertisement.slot else 0,  # slot 수량 사용
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
    # 오후 4시 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
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
                slot = int(row['slot']) if 'slot' in row and pd.notna(row['slot']) else None
                
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
                
                # 광고 생성 (날짜 기반 자동 상태 계산)
                today = date.today()
                auto_status = "pending"  # 기본값
                
                if start_date and end_date:
                    if today < start_date:
                        # start_date가 오늘보다 이후(미래)이면 → pending (대기중)
                        auto_status = "pending"
                    elif today > end_date:
                        # 오늘 날짜가 end_date 이후이면 → ended
                        auto_status = "ended"
                    elif today == end_date - timedelta(days=1):
                        # 오늘 날짜가 end_date 1일전이면 → ending
                        auto_status = "ending"
                    elif start_date <= today <= end_date:
                        # 오늘이 start_date와 end_date 사이면 → normal
                        auto_status = "normal"
                
                new_advertisement = AdvertisementsAdmin(
                    user_id=row_user_id,
                    status=auto_status,  # 날짜 기반 자동 계산된 상태
                    main_keyword=main_keyword,
                    price_comparison=price_comparison,
                    plus=plus,
                    product_name=product_name,
                    product_mid=product_mid,
                    price_comparison_mid=price_comparison_mid,
                    work_days=work_days,
                    start_date=start_date,
                    end_date=end_date,
                    affiliation=row_user_affiliation,
                    slot=slot
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
                    quantity=slot if slot else 0,  # slot 수량 사용
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
    # 오후 4시 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
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
    
    # 메인 키워드 변경 (로그 기록을 위해 변경 전 값 저장)
    old_main_keyword = ad.main_keyword if ad.main_keyword else None
    main_keyword_changed = False
    
    if advertisement.main_keyword:
        new_main_keyword = advertisement.main_keyword
        if old_main_keyword != new_main_keyword:
            main_keyword_changed = True
            ad.main_keyword = new_main_keyword
    
    # store_url 저장 및 product_mid 추출 (로그 기록을 위해 변경 전 값 저장)
    old_store_url = ad.store_url if ad.store_url else None
    store_url_changed = False
    
    if advertisement.store_url is not None:
        # 빈 문자열 처리
        if advertisement.store_url and advertisement.store_url.strip():
            new_store_url = advertisement.store_url.strip()
            if old_store_url != new_store_url:
                store_url_changed = True
            ad.store_url = new_store_url
            store_url_lower = advertisement.store_url.lower()
            
            # 오픈마켓 도메인 체크
            openmall_domains = ['coupang.com', 'auction.co.kr', '11st.co.kr', 'gmarket.co.kr']
            is_openmall = any(domain in store_url_lower for domain in openmall_domains)
            
            # 일반 쇼핑몰 도메인 체크
            basemall_domains = ['rental-zon.com', 'hkoa1.com', 'funart.co.kr']
            is_basemall = any(domain in store_url_lower for domain in basemall_domains)
            
            # 네이버 스토어 URL 체크
            is_smartstore = "smartstore.naver.com" in store_url_lower or "brand.naver.com" in store_url_lower
            
            product_mid = None
            
            # 네이버 스마트스토어/브랜드스토어: product_id 추출
            if is_smartstore:
                match = re.search(r'(?:smartstore|brand)\.naver\.com/[^/]+/products/(\d+)', advertisement.store_url)
                if match:
                    product_mid = match.group(1)
            
            # 쿠팡: itemId 우선, 없으면 products ID
            elif "coupang.com" in store_url_lower:
                match = re.search(r'itemId=(\d+)', advertisement.store_url)
                if match:
                    product_mid = match.group(1)
                else:
                    match = re.search(r'coupang\.com/vp/products/(\d+)', advertisement.store_url)
                    if match:
                        product_mid = match.group(1)
            
            # 옥션: itemno 추출
            elif "auction.co.kr" in store_url_lower:
                match = re.search(r'itemno=([A-Z0-9]+)', advertisement.store_url, re.IGNORECASE)
                if match:
                    product_mid = match.group(1)
            
            # 11번가: products ID 추출
            elif "11st.co.kr" in store_url_lower:
                match = re.search(r'11st\.co\.kr/products/(\d+)', advertisement.store_url)
                if match:
                    product_mid = match.group(1)
            
            # G마켓: goodscode 또는 item-no 추출
            elif "gmarket.co.kr" in store_url_lower:
                match = re.search(r'goodscode=(\d+)', advertisement.store_url)
                if not match:
                    match = re.search(r'item-no=(\d+)', advertisement.store_url)
                if match:
                    product_mid = match.group(1)
            
            # 일반적인 마지막 숫자 (폴백)
            if not product_mid:
                match = re.search(r'/(\d+)(?:[/?#]|$)', advertisement.store_url)
                if match:
                    product_mid = match.group(1)
            
            # product_mid 저장 (추출 실패 시 None, 에러 발생하지 않음)
            ad.product_mid = product_mid
            if not product_mid and not is_openmall and not is_basemall:
                # 오픈마켓이나 일반 쇼핑몰이 아닌 경우에만 경고
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"store_url에서 product_mid를 추출할 수 없습니다: {advertisement.store_url}")
        else:
            # 빈 문자열이면 None으로 설정
            if old_store_url is not None:
                store_url_changed = True
            ad.store_url = None
            ad.product_mid = None
    
    # shopping_url 저장 및 price_comparison_mid 추출 (로그 기록을 위해 변경 전 값 저장)
    old_shopping_url = ad.shopping_url if ad.shopping_url else None
    shopping_url_changed = False
    
    if advertisement.shopping_url is not None:
        # 빈 문자열 처리
        if advertisement.shopping_url and advertisement.shopping_url.strip():
            new_shopping_url = advertisement.shopping_url.strip()
            if old_shopping_url != new_shopping_url:
                shopping_url_changed = True
            ad.shopping_url = new_shopping_url
            shopping_url_lower = advertisement.shopping_url.lower()
            
            # 네이버 쇼핑 URL 체크
            is_naver_shopping = "search.shopping.naver.com/catalog" in shopping_url_lower
            
            price_comparison_mid = None
            
            # 네이버 쇼핑 URL: nvmid 추출
            if is_naver_shopping:
                match = re.search(r'catalog/(\d+)', advertisement.shopping_url)
                if match:
                    price_comparison_mid = match.group(1)
            
            # 오픈마켓이나 일반 쇼핑몰 URL은 price_comparison_mid 추출 불가 (순위 조회 불가)
            # price_comparison_mid는 None으로 유지
            
            # price_comparison_mid 저장 (추출 실패 시 None, 에러 발생하지 않음)
            ad.price_comparison_mid = price_comparison_mid
            if not price_comparison_mid and is_naver_shopping:
                # 네이버 쇼핑 URL인데 추출 실패한 경우에만 경고
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"shopping_url에서 nvmid를 추출할 수 없습니다: {advertisement.shopping_url}")
        else:
            # 빈 문자열이면 None으로 설정
            if old_shopping_url is not None:
                shopping_url_changed = True
            ad.shopping_url = None
            ad.price_comparison_mid = None
    
    # 메모 변경
    if advertisement.memo is not None:
        ad.memo = advertisement.memo
    
    # 슬롯 변경
    if advertisement.slot is not None:
        ad.slot = advertisement.slot
    
    # 상품명 변경 (로그 기록을 위해 변경 전 값 저장)
    old_product_name = ad.product_name if ad.product_name else None
    product_name_changed = False
    
    if advertisement.product_name is not None:
        new_product_name = advertisement.product_name
        if old_product_name != new_product_name:
            product_name_changed = True
            ad.product_name = new_product_name
    
    # 상품 MID 변경 (직접 지정된 경우)
    if advertisement.product_mid is not None:
        ad.product_mid = advertisement.product_mid
    
    # 변경사항이 있으면 수정 로그 생성
    ad.updated_at = datetime.now()
    
    # 광고주 정보 조회 (대행사 ID 찾기 위해)
    user = db.query(UsersAdmin).filter(UsersAdmin.user_id == ad.user_id).first()
    
    # 작업 수행자 ID (실제로 수정한 유저)
    current_username = current_user.get("username")
    performed_by_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
    performed_by_user_id = performed_by_user.user_id if performed_by_user else None
    
    # 대행사 ID 설정
    agency_user_id = None
    if user:
        agency_user_id = user.parent_user_id if user.role == "advertiser" else None
    
    try:
        # 변경 로그 메시지 생성
        # 항상 세 가지 항목을 표시 (변경 없어도 로그 생성)
        
        # 1. 상품명 로그
        old_product_val = old_product_name if old_product_name else "(없음)"
        new_product_val = ad.product_name if ad.product_name else "(없음)"
        if product_name_changed:
            product_log = f"상품명: {old_product_val} -> {new_product_val}"
        else:
            product_log = f"상품명: 변경없음"
        
        # 2. 메인키워드 로그
        old_keyword_val = old_main_keyword if old_main_keyword else "(없음)"
        new_keyword_val = ad.main_keyword if ad.main_keyword else "(없음)"
        if main_keyword_changed:
            keyword_log = f"메인키워드: {old_keyword_val} -> {new_keyword_val}"
        else:
            keyword_log = f"메인키워드: 변경없음"
        
        # 3. URL 로그 (store_url 우선, 없으면 shopping_url)
        url_changed = store_url_changed or shopping_url_changed
        old_url_val = None
        new_url_val = None
        
        # 기존 URL 값 (store_url 우선)
        if old_store_url:
            old_url_val = old_store_url
        elif old_shopping_url:
            old_url_val = old_shopping_url
        else:
            old_url_val = "(없음)"
        
        # 새 URL 값 (store_url 우선)
        if ad.store_url:
            new_url_val = ad.store_url
        elif ad.shopping_url:
            new_url_val = ad.shopping_url
        else:
            new_url_val = "(없음)"
        
        if url_changed:
            url_log = f"URL: {old_url_val} -> {new_url_val}"
        else:
            url_log = f"URL: 변경없음"
        
        # 세 가지 로그를 항상 생성
        change_logs = [product_log, keyword_log, url_log]
        product_name_log = " | ".join(change_logs)  # 세 가지 항목을 |로 구분
        
        # 수정 로그 생성 (settlement_type='update')
        # 변경사항이 없어도 로그 생성
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
            ad_product_nm=product_name_log  # 변경 로그 형식으로 저장
        )
        
        db.add(new_settlement)
        db.flush()  # ID를 얻기 위해 flush

        # 순위 업데이트 (store_url, shopping_url이 있거나 main_keyword와 product_mid가 있는 경우)
        # 실패 시 예외가 발생하여 except로 이동, rollback됨
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
            db.refresh(ad)  # prod_name
            # ad_product_nm은 이미 정산 로그로 설정되었으므로 덮어쓰지 않음
        
        # commit도 try-except로 감싸기 (DB 오류 대비)
        try:
            db.commit()
            db.refresh(ad)
        except Exception as e:
            db.rollback()
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"광고 수정 commit 실패: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"광고 수정 중 데이터베이스 오류가 발생했습니다: {str(e)}"
            )

        return {
            "success": True,
            "message": "광고가 수정되었습니다.",
            "data": {
                "ad_id": ad.ad_id
            }
        }
    
    except HTTPException:
        # HTTPException은 그대로 전파 (rollback은 이미 내부에서 처리됨)
        db.rollback()
        raise
    except Exception as e:
        # 예상치 못한 오류 발생 시 rollback
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"광고 수정 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"광고 수정 중 오류가 발생했습니다: {str(e)}"
        )


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
    # 오후 4시 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
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
    failed_ads = []  # 환불 실패한 광고 목록
    
    try:
        for ad_id in delete_request.ad_ids:
            try:
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
                
                # 작업 수행자 ID (실제로 삭제한 유저) - user가 None이어도 설정
                current_username = current_user.get("username")
                performed_by_user = db.query(UsersAdmin).filter(UsersAdmin.username == current_username).first()
                performed_by_user_id = performed_by_user.user_id if performed_by_user else None
                performed_by_role = performed_by_user.role if performed_by_user else None
                
                # 작업 수행자의 role에 따라 advertiser_user_id와 agency_user_id 결정
                if current_username in ["admin", "monteur"]:
                    # 관리자가 삭제한 경우
                    if user and user.role == "advertiser":
                        agency_user_id = user.parent_user_id  # 광고주의 대행사
                        advertiser_user_id = ad.user_id  # 광고 소유자
                    else:
                        # 광고주가 대행사나 총판사이거나 user가 None인 경우
                        agency_user_id = None
                        advertiser_user_id = ad.user_id
                elif performed_by_role == "agency":
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
                    # 기타 (user가 None일 수 있음)
                    if user and user.role == "advertiser":
                        agency_user_id = user.parent_user_id
                        advertiser_user_id = ad.user_id
                    else:
                        agency_user_id = None
                        advertiser_user_id = ad.user_id
                
                # 삭제 로그 생성 (settlement_type='refund')
                # 이미 종료된 경우 환불 불가
                today = date.today()
                if ad.end_date and today > ad.end_date:
                    failed_ads.append({"ad_id": ad_id, "reason": "이미 종료된 광고는 환불할 수 없습니다."})
                    continue
                
                # 남은 일수 계산 (광고 시작일부터 종료일까지)
                # 오늘이 광고 기간 내에 있다면, 오늘 하루는 사용한 것으로 간주하고 환불에서 제외
                remaining_days = 0
                
                if ad.end_date and ad.start_date:
                    period_end = ad.end_date
                    
                    # 오늘이 광고 기간 내에 있는지 확인
                    if ad.start_date <= today <= ad.end_date:
                        # 오늘은 사용한 것으로 간주, 내일부터 환불
                        period_start = today + timedelta(days=1)  # 내일부터 환불 시작
                        
                        # 내일이 종료일보다 늦으면 환불 일수는 0
                        if period_start > period_end:
                            remaining_days = 0
                        else:
                            remaining_days = (period_end - period_start).days + 1  # 종료일 포함
                    else:
                        # 오늘이 광고 기간 밖에 있으면 기존 로직 사용
                        # period_start는 오늘과 광고 시작일 중 늦은 것 (실제 환불 기간 시작일)
                        period_start = max(today, ad.start_date)
                        # 실제 광고 진행 기간 계산 (시작일부터 종료일까지)
                        remaining_days = (period_end - period_start).days + 1  # 종료일 포함
                else:
                    period_start = None
                    period_end = None
                
                new_settlement = SettlementAdmin(
                    settlement_type="refund",
                    agency_user_id=agency_user_id,
                    advertiser_user_id=advertiser_user_id,
                    ad_id=ad.ad_id,
                    performed_by_user_id=performed_by_user_id,
                    quantity=ad.slot if ad.slot else 0,  # 남은 슬롯 수량
                    period_start=period_start,  # 현재 날짜 (환불일)
                    period_end=period_end,  # 종료 날짜
                    total_days=-remaining_days if remaining_days > 0 else 0,  # 환불 일수 (음수로 표시)
                    start_date=ad.start_date if ad.start_date else None,  # 원래 시작일
                    ad_product_nm=ad.product_name  # 일단 현재 값으로 설정
                )
                
                db.add(new_settlement)
                db.flush()  # ID를 얻기 위해 flush
                
                # ad.product_name이 None이면 기존 정산 로그에서 찾기
                # 선택적 작업이므로 내부에서 예외 처리
                if not ad.product_name:
                    try:
                        existing_settlement = db.query(SettlementAdmin).filter(
                            SettlementAdmin.ad_id == ad.ad_id,
                            SettlementAdmin.ad_product_nm.isnot(None)
                        ).order_by(SettlementAdmin.settlement_id.desc()).first()
                        
                        if existing_settlement and existing_settlement.ad_product_nm:
                            new_settlement.ad_product_nm = existing_settlement.ad_product_nm
                            ad.product_name = existing_settlement.ad_product_nm
                            db.refresh(ad)
                    except Exception as e:
                        # 기존 정산 로그 조회 실패해도 삭제는 계속 진행
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"광고 ID {ad.ad_id} 기존 정산 로그 조회 실패: {str(e)}")
            
                # 광고 삭제 (하드 삭제)
                db.delete(ad)
                deleted_count += 1
            except Exception as e:
                # 개별 광고 삭제 중 오류 발생 시 로그만 남기고 계속 진행
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"광고 ID {ad_id} 삭제 중 오류: {str(e)}", exc_info=True)
                not_found_ids.append(ad_id)  # 오류 발생 시 not_found로 처리
                continue
        
        # commit도 try-except로 감싸기
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"광고 삭제 commit 실패: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"광고 삭제 중 데이터베이스 오류가 발생했습니다: {str(e)}"
            )
    
    except HTTPException:
        # HTTPException은 그대로 전파 (rollback은 이미 내부에서 처리됨)
        db.rollback()
        raise
    except Exception as e:
        # 예상치 못한 오류 발생 시 rollback
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"광고 삭제 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"광고 삭제 중 오류가 발생했습니다: {str(e)}"
        )
    
    message_parts = []
    if deleted_count > 0:
        message_parts.append(f"{deleted_count}개의 광고가 삭제되었습니다.")
    if not_found_ids:
        message_parts.append(f"{len(not_found_ids)}개 광고를 찾을 수 없습니다.")
    if unauthorized_ids:
        message_parts.append(f"{len(unauthorized_ids)}개 광고는 삭제 권한이 없습니다.")
    if failed_ads:
        message_parts.append(f"{len(failed_ads)}개 광고는 환불 처리에 실패했습니다.")
    
    return {
        "success": True,
        "message": " ".join(message_parts) if message_parts else "광고 삭제가 완료되었습니다.",
        "data": {
            "deleted_count": deleted_count,
            "not_found_ids": not_found_ids,
            "unauthorized_ids": unauthorized_ids,
            "failed_ads": failed_ads
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
    # 오후 4시 이후 수정 차단 (슈퍼유저 제외)
    check_edit_time_allowed(
        username=current_user.get("username"),
        user_role=current_user.get("role")
    )
    
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
            # start_date는 원본 광고의 end_date 다음날부터 시작 (내일)
            new_start_date = ad.end_date + timedelta(days=1)
            # end_date는 start_date에서 연장 일수 - 1일을 더함 (시작일 포함)
            new_end_date = new_start_date + timedelta(days=extend_request.extend_days - 1)            
            # work_days 계산
            new_work_days = extend_request.extend_days
            
            # 날짜 기반 자동 상태 계산
            today = date.today()
            auto_status = "pending"  # 기본값
            
            if new_start_date and new_end_date:
                if today < new_start_date:
                    # start_date가 오늘보다 이후(미래)이면 → pending (대기중)
                    auto_status = "pending"
                elif today > new_end_date:
                    # 오늘 날짜가 end_date 이후이면 → ended
                    auto_status = "ended"
                elif today == new_end_date - timedelta(days=1):
                    # 오늘 날짜가 end_date 1일전이면 → ending
                    auto_status = "ending"
                elif new_start_date <= today <= new_end_date:
                    # 오늘이 start_date와 end_date 사이면 → normal
                    auto_status = "normal"
            
            # 새 광고 생성
            new_advertisement = AdvertisementsAdmin(
                user_id=ad.user_id,
                status=auto_status,  # 날짜 기반 자동 계산된 상태
                main_keyword=ad.main_keyword,
                price_comparison=ad.price_comparison,
                plus=ad.plus,
                product_name=ad.product_name,
                product_mid=ad.product_mid,
                price_comparison_mid=ad.price_comparison_mid,
                work_days=new_work_days,
                start_date=new_start_date,
                end_date=new_end_date,
                affiliation=ad.affiliation,
                slot=ad.slot,  # 슬롯 복사
                store_url=ad.store_url,  # store_url 복사
                shopping_url=ad.shopping_url,  # shopping_url 복사
                rank=ad.rank  # 순위 복사
            )
            
            db.add(new_advertisement)
            db.flush()  # ad_id를 얻기 위해 flush
            
            # 순위 이력 복사 (기존 광고의 순위 이력을 새 광고로 복사)
            existing_rank_history = db.query(AdvertisementRankHistory).filter(
                AdvertisementRankHistory.ad_id == ad.ad_id
            ).all()
            
            for rank_record in existing_rank_history:
                new_rank_history = AdvertisementRankHistory(
                    ad_id=new_advertisement.ad_id,  # 새 광고 ID
                    rank_date=rank_record.rank_date,  # 기존 순위 날짜
                    rank=rank_record.rank,  # 기존 순위
                    product_name=rank_record.product_name  # 기존 상품명
                )
                db.add(new_rank_history)
                
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
            quantity=ad.slot if ad.slot else 0,  # slot 수량 사용
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

