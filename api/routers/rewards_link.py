"""
리워드 링크 관리 API 라우터
- 짧은 링크 생성 및 관리
- 키워드 조합 관리
- 랜덤 리다이렉트
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import Optional, List
from database import get_db, SessionLocal
from models import RewardLink, RewardLinkKeyword, UsersAdmin
from utils.auth_helpers import get_current_user
from datetime import datetime
import random
import string
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


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


# ==================== Pydantic 모델 ====================

class KeywordCombination(BaseModel):
    # 프론트엔드 호환성을 위해 두 가지 형식 모두 지원
    query_keyword: Optional[str] = None
    acq_keyword: Optional[str] = None
    query: Optional[str] = None  # 프론트엔드 형식
    acq: Optional[str] = None    # 프론트엔드 형식
    
    def get_query(self) -> str:
        """query_keyword 또는 query 반환"""
        return self.query_keyword or self.query or ""
    
    def get_acq(self) -> str:
        """acq_keyword 또는 acq 반환"""
        return self.acq_keyword or self.acq or ""


class RewardLinkCreate(BaseModel):
    product_name: Optional[str] = None
    short_link: Optional[str] = None  # 프론트엔드에서 생성한 링크 (선택사항)
    keywords: List[KeywordCombination] = []
    query_list: Optional[List[str]] = None  # query 키워드 리스트
    acq_list: Optional[List[str]] = None    # acq 키워드 리스트


class RewardLinkUpdate(BaseModel):
    product_name: Optional[str] = None
    keywords: Optional[List[KeywordCombination]] = None


class KeywordAdd(BaseModel):
    query_keyword: Optional[str] = None
    acq_keyword: Optional[str] = None
    query: Optional[str] = None  # 프론트엔드 형식
    acq: Optional[str] = None    # 프론트엔드 형식
    
    def get_query(self) -> str:
        """query_keyword 또는 query 반환"""
        return self.query_keyword or self.query or ""
    
    def get_acq(self) -> str:
        """acq_keyword 또는 acq 반환"""
        return self.acq_keyword or self.acq or ""


# ==================== 유틸리티 함수 ====================

def generate_short_code(length: int = 10) -> str:
    """랜덤 짧은 코드 생성 (영문숫자)"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def generate_random_ackey(length: int = 8) -> str:
    """랜덤 ackey 생성 (영문숫자 8글자)"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


# ==================== API 엔드포인트 ====================

@router.get("/links")
async def get_all_links(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    모든 링크 목록 조회 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        links = db.query(RewardLink).order_by(desc(RewardLink.created_at)).all()
        
        result = []
        for link in links:
            # 키워드 조합 조회
            keywords = db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.link_id == link.link_id
            ).all()
            
            keyword_list = [
                {
                    "keyword_id": kw.keyword_id,
                    "query_keyword": kw.query_keyword,
                    "acq_keyword": kw.acq_keyword
                }
                for kw in keywords
            ]
            
            result.append({
                "link_id": link.link_id,
                "short_code": link.short_code,
                "product_name": link.product_name or "",
                "reward_link": link.reward_link or "",  # reward_link 포함
                "keyword_count": len(keyword_list),
                "keywords": keyword_list,
                "created_at": link.created_at.isoformat() if link.created_at else None,
                "updated_at": link.updated_at.isoformat() if link.updated_at else None,
            })
        
        return {
            "success": True,
            "data": {
                "links": result
            }
        }
    
    except Exception as e:
        logger.error(f"링크 목록 조회 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/links/{short_code}")
async def get_link_by_code(
    short_code: str,
    db: Session = Depends(get_db)
):
    """
    짧은 코드로 링크 정보 조회 (공개, 리다이렉트용)
    """
    try:
        link = db.query(RewardLink).filter(RewardLink.short_code == short_code).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {short_code}"
            )
        
        # 키워드 조합 조회
        keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link.link_id
        ).all()
        
        if not keywords:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="등록된 키워드가 없습니다."
            )
        
        keyword_list = [
            {
                "query_keyword": kw.query_keyword,
                "acq_keyword": kw.acq_keyword
            }
            for kw in keywords
        ]
        
        return {
            "success": True,
            "data": {
                "link": {
                    "link_id": link.link_id,
                    "short_code": link.short_code,
                    "product_name": link.product_name or "",
                    "reward_link": link.reward_link or "",  # reward_link 포함
                    "keywords": keyword_list
                }
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"링크 조회 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/redirect/{short_code}")
async def redirect_to_naver(
    short_code: str,
    db: Session = Depends(get_db)
):
    """
    짧은 링크로 접속 시 랜덤 네이버 URL로 리다이렉트
    short_code에 해당하는 모든 RewardLink 중 랜덤으로 하나를 선택하여 reward_link로 리다이렉트
    """
    try:
        # short_code로 모든 RewardLink 레코드 조회 (같은 short_code를 가진 여러 레코드)
        links = db.query(RewardLink).filter(
            RewardLink.short_code == short_code
        ).all()
        
        if not links:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {short_code}"
            )
        
        # reward_link가 있는 레코드만 필터링
        valid_links = [link for link in links if link.reward_link and link.reward_link.strip()]
        
        if not valid_links:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="등록된 네이버 URL이 없습니다."
            )
        
        # 랜덤으로 하나의 레코드 선택
        random_link = random.choice(valid_links)
        naver_url = random_link.reward_link.strip()
        
        logger.info(f"[리다이렉트] short_code={short_code}, 선택된 link_id={random_link.link_id}, 네이버 URL: {naver_url[:100]}...")
        
        # 리다이렉트
        return RedirectResponse(url=naver_url, status_code=302)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"리다이렉트 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"리다이렉트 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/links")
async def create_link(
    link_data: RewardLinkCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    새 링크 생성 (관리자용)
    query_list와 acq_list가 제공되면 모든 조합을 생성
    keywords가 제공되면 그대로 사용
    각 조합마다 별도의 link_id를 생성하되, 모두 같은 short_code를 사용
    """
    check_admin_permission(current_user, db)
    
    try:
        # query_list와 acq_list가 제공되면 모든 조합 생성
        keyword_combinations = []
        
        if link_data.query_list and link_data.acq_list:
            # 모든 조합 생성
            logger.info(f"query_list 개수: {len(link_data.query_list)}, acq_list 개수: {len(link_data.acq_list)}")
            for query in link_data.query_list:
                if not query or not query.strip():
                    continue
                for acq in link_data.acq_list:
                    if not acq or not acq.strip():
                        continue
                    keyword_combinations.append({
                        "query": query.strip(),
                        "acq": acq.strip()
                    })
            logger.info(f"생성된 조합 개수: {len(keyword_combinations)}")
        elif link_data.keywords:
            # keywords가 제공되면 그대로 사용
            for kw in link_data.keywords:
                query = kw.get_query()
                acq = kw.get_acq()
                if query and acq:
                    keyword_combinations.append({
                        "query": query,
                        "acq": acq
                    })
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query_list/acq_list 또는 keywords를 제공해주세요."
            )
        
        if len(keyword_combinations) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효한 키워드 조합이 없습니다."
            )
        
        # 입력 데이터 로깅
        logger.info(f"링크 생성 요청: product_name={link_data.product_name}, 조합 개수={len(keyword_combinations)}")
        for idx, comb in enumerate(keyword_combinations):
            logger.info(f"  조합[{idx}]: query={comb['query']}, acq={comb['acq']}")
        
        # 하나의 short_code 생성 (모든 레코드가 공유)
        max_attempts = 10
        short_code = None
        
        for _ in range(max_attempts):
            candidate = generate_short_code(10)
            existing = db.query(RewardLink).filter(RewardLink.short_code == candidate).first()
            if not existing:
                short_code = candidate
                break
        
        if not short_code:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="짧은 코드 생성에 실패했습니다. 다시 시도해주세요."
            )
        
        logger.info(f"생성된 short_code (공통): {short_code}")
        
        # 네이버 URL 생성을 위한 import
        from urllib.parse import quote
        
        # 각 키워드 조합마다 별도의 reward_link 레코드 생성 (모두 같은 short_code 사용)
        created_links = []
        saved_keywords = []
        failed_combinations = []
        
        for idx, comb in enumerate(keyword_combinations):
            query = comb['query']
            acq = comb['acq']
            
            logger.info(f"조합[{idx}] 처리 시작: query='{query}', acq='{acq}'")
            
            try:
                # 각 조합마다 네이버 검색 URL 생성 (reward_link에 저장)
                ackey = generate_random_ackey(8)
                acr = random.randint(0, 10)
                
                naver_url = (
                    f"https://m.search.naver.com/search.naver?"
                    f"sm=mtp_sug.top&"
                    f"where=m&"
                    f"query={quote(query)}&"
                    f"ackey={ackey}&"
                    f"acq={quote(acq)}&"
                    f"acr={acr}&"
                    f"qdt=0"
                )
                
                logger.info(f"조합[{idx}] - 생성된 네이버 URL: {naver_url}")
                
                # 각 키워드 조합마다 별도의 reward_link 레코드 생성 (같은 short_code 사용)
                new_link = RewardLink(
                    short_code=short_code,  # 모두 같은 short_code 사용
                    product_name=link_data.product_name,
                    reward_link=naver_url  # 네이버 검색 URL 저장
                )
                db.add(new_link)
                db.flush()  # link_id를 얻기 위해 flush
                
                logger.info(f"조합[{idx}] - 생성된 link_id: {new_link.link_id}, short_code: {short_code}, reward_link: {naver_url}")
                
                # 각 reward_link에 하나의 키워드 조합만 저장
                keyword = RewardLinkKeyword(
                    link_id=new_link.link_id,
                    short_code=short_code,  # 각각 다른 link_id
                    query_keyword=query,
                    acq_keyword=acq
                )
                db.add(keyword)
                db.flush()  # keyword_id를 얻기 위해 flush
                
                logger.info(f"조합[{idx}] 저장 완료: link_id={new_link.link_id}, keyword_id={keyword.keyword_id}, query='{query}', acq='{acq}'")
                
                created_links.append({
                    "link_id": new_link.link_id,
                    "short_code": new_link.short_code,  # 모두 같은 short_code
                    "reward_link": new_link.reward_link,  # 각각 다른 네이버 URL
                    "keyword_id": keyword.keyword_id,
                    "query": query,
                    "acq": acq
                })
                
                saved_keywords.append({
                    "link_id": new_link.link_id,
                    "query": query,
                    "acq": acq
                })
            except Exception as e:
                logger.error(f"조합[{idx}] 저장 중 오류 발생: query='{query}', acq='{acq}', 오류: {e}", exc_info=True)
                failed_combinations.append({
                    "index": idx,
                    "query": query,
                    "acq": acq,
                    "error": str(e)
                })
                # 개별 레코드 저장 실패 시에도 계속 진행
                continue
        
        if len(created_links) == 0:
            db.rollback()
            logger.error("저장된 링크가 없습니다. 롤백합니다.")
            error_detail = "링크 생성에 실패했습니다."
            if failed_combinations:
                error_detail += f" 실패한 조합: {failed_combinations}"
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail
            )
        
        # 일부 조합이 실패했어도 성공한 레코드는 커밋
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"커밋 중 오류 발생: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"링크 저장 중 오류가 발생했습니다: {str(e)}"
            )
        
        logger.info(f"링크 생성 완료: 총 {len(created_links)}개의 링크 생성됨 (모두 같은 short_code: {short_code})")
        if failed_combinations:
            logger.warning(f"일부 조합 저장 실패: {len(failed_combinations)}개 실패")
            for failed in failed_combinations:
                logger.warning(f"  실패한 조합: query='{failed['query']}', acq='{failed['acq']}', 오류: {failed['error']}")
        
        for link_info in created_links:
            logger.info(f"  - link_id={link_info['link_id']}, short_code={link_info['short_code']}, reward_link={link_info['reward_link']}, query='{link_info['query']}', acq='{link_info['acq']}'")
        
        response_message = f"{len(created_links)}개의 링크가 생성되었습니다."
        if failed_combinations:
            response_message += f" ({len(failed_combinations)}개 조합 저장 실패)"
        
        return {
            "success": True,
            "message": response_message,
            "data": {
                "short_code": short_code,  # 공통 short_code 반환
                "created_count": len(created_links),
                "failed_count": len(failed_combinations),
                "links": created_links,  # 생성된 모든 링크 정보 (같은 short_code, 각각 다른 네이버 URL)
                "keywords": saved_keywords,  # 저장된 키워드 목록
                "failed_combinations": failed_combinations if failed_combinations else []  # 실패한 조합 목록
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"링크 생성 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 생성 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/links/{link_id}/keywords/{keyword_id}")
async def update_keyword(
    link_id: int,
    keyword_id: int,
    keyword_data: KeywordAdd,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 조합 수정 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        # 링크 확인
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        # 키워드 조회
        keyword = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.keyword_id == keyword_id,
            RewardLinkKeyword.link_id == link_id
        ).first()
        
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"키워드를 찾을 수 없습니다: {keyword_id}"
            )
        
        query = keyword_data.get_query()
        acq = keyword_data.get_acq()
        
        if not query or not acq:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query와 acq 키워드를 모두 입력해주세요."
            )
        
        # 키워드 수정
        keyword.query_keyword = query
        keyword.acq_keyword = acq
        keyword.short_code = link.short_code  # short_code도 업데이트
        keyword.updated_at = datetime.now()
        
        db.commit()
        db.refresh(keyword)
        
        return {
            "success": True,
            "message": "키워드가 수정되었습니다.",
            "data": {
                "keyword_id": keyword.keyword_id,
                "query_keyword": keyword.query_keyword,
                "acq_keyword": keyword.acq_keyword,
                "short_code": keyword.short_code
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"키워드 수정 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"키워드 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.put("/links/{link_id}")
async def update_link(
    link_id: int,
    link_data: RewardLinkUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    링크 정보 수정 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        # 상품명 업데이트
        if link_data.product_name is not None:
            link.product_name = link_data.product_name
            link.updated_at = datetime.now()
        
        # 키워드 조합 업데이트
        if link_data.keywords is not None:
            # 기존 키워드 삭제
            db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.link_id == link_id
            ).delete()
            
            # 새 키워드 추가
            for kw in link_data.keywords:
                query = kw.get_query()
                acq = kw.get_acq()
                
                if not query or not acq:
                    continue  # 빈 키워드는 건너뛰기
                
                keyword = RewardLinkKeyword(
                    link_id=link_id,
                    short_code=link.short_code,  # short_code 추가
                    query_keyword=query,
                    acq_keyword=acq
                )
                db.add(keyword)
        
        db.commit()
        db.refresh(link)
        
        # 업데이트된 키워드 조합 조회
        keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.link_id == link_id
        ).all()
        
        keyword_list = [
            {
                "keyword_id": kw.keyword_id,
                "query_keyword": kw.query_keyword,
                "acq_keyword": kw.acq_keyword
            }
            for kw in keywords
        ]
        
        return {
            "success": True,
            "message": "링크가 수정되었습니다.",
            "data": {
                "link_id": link.link_id,
                "short_code": link.short_code,
                "product_name": link.product_name,
                "reward_link": link.reward_link or "",  # reward_link 포함
                "keywords": keyword_list
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"링크 수정 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"링크 수정 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/links/{link_id}/keywords")
async def add_keyword(
    link_id: int,
    keyword_data: KeywordAdd,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 조합 추가 (관리자용)
    """
    check_admin_permission(current_user, db)
    
    try:
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"링크를 찾을 수 없습니다: {link_id}"
            )
        
        query = keyword_data.get_query()
        acq = keyword_data.get_acq()
        
        if not query or not acq:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query와 acq 키워드를 모두 입력해주세요."
            )
        
        # 키워드 조합 추가
        keyword = RewardLinkKeyword(
            link_id=link_id,
            short_code=link.short_code,
            query_keyword=query,
            acq_keyword=acq
        )
        db.add(keyword)
        db.commit()
        db.refresh(keyword)
        
        return {
            "success": True,
            "message": "키워드가 추가되었습니다.",
            "data": {
                "keyword_id": keyword.keyword_id,
                "query_keyword": keyword.query_keyword,
                "acq_keyword": keyword.acq_keyword
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"키워드 추가 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"키워드 추가 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/links/{link_id}/keywords/{keyword_id}")
async def delete_keyword(
    link_id: int,
    keyword_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    키워드 조합 삭제 (관리자용)
    키워드 삭제 시 해당 reward_link 레코드도 함께 삭제
    """
    check_admin_permission(current_user, db)
    
    try:
        # 키워드 조회
        keyword = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.keyword_id == keyword_id,
            RewardLinkKeyword.link_id == link_id
        ).first()
        
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"키워드를 찾을 수 없습니다: {keyword_id}"
            )
        
        # 키워드 삭제
        db.delete(keyword)
        
        # 해당 link_id의 reward_link 레코드 조회
        link = db.query(RewardLink).filter(RewardLink.link_id == link_id).first()
        
        if link:
            # 해당 link_id에 연결된 다른 키워드가 있는지 확인
            remaining_keywords = db.query(RewardLinkKeyword).filter(
                RewardLinkKeyword.link_id == link_id
            ).count()
            
            # 다른 키워드가 없으면 reward_link 레코드도 삭제
            if remaining_keywords == 0:
                logger.info(f"link_id {link_id}에 연결된 키워드가 없어 reward_link 레코드도 삭제합니다.")
                db.delete(link)
            else:
                logger.info(f"link_id {link_id}에 연결된 키워드가 {remaining_keywords}개 남아있어 reward_link 레코드는 유지합니다.")
        
        db.commit()
        
        return {
            "success": True,
            "message": "키워드가 삭제되었습니다."
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"키워드 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"키워드 삭제 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/links/{short_code}")
async def delete_link(
    short_code: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    SHORT_CODE 기준으로 모든 링크 및 키워드 삭제 (관리자용)
    RANDOM_LINK 버튼의 작업삭제 기능
    """
    check_admin_permission(current_user, db)
    
    try:
        # short_code로 모든 RewardLink 레코드 조회
        links = db.query(RewardLink).filter(
            RewardLink.short_code == short_code
        ).all()
        
        if not links:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"short_code '{short_code}'에 해당하는 링크를 찾을 수 없습니다."
            )
        
        # short_code 기준으로 모든 키워드 삭제
        deleted_keywords = db.query(RewardLinkKeyword).filter(
            RewardLinkKeyword.short_code == short_code
        ).all()
        deleted_keyword_count = len(deleted_keywords)
        
        for keyword in deleted_keywords:
            db.delete(keyword)
        
        # 모든 링크 삭제
        deleted_link_count = len(links)
        for link in links:
            db.delete(link)
        
        db.commit()
        
        logger.info(f"[작업삭제] short_code '{short_code}': {deleted_link_count}개 링크, {deleted_keyword_count}개 키워드 삭제 완료")
        
        return {
            "success": True,
            "message": f"short_code '{short_code}'에 해당하는 모든 항목이 삭제되었습니다.",
            "deleted_links": deleted_link_count,
            "deleted_keywords": deleted_keyword_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[작업삭제] short_code '{short_code}' 삭제 중 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"삭제 중 오류가 발생했습니다: {str(e)}"
        )
