"""
SQLAlchemy ORM 모델
dbml.sql 스키마를 기반으로 생성
"""
from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, Date, JSON, Index
from sqlalchemy.sql import func
# from sqlalchemy.orm import relationship  # 관계 제거
from database import Base


# 데이터섹션(IP 그룹) 테이블
class DataSection(Base):
    __tablename__ = 'datasection'
    
    datasection_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_name = Column(String(255), comment='datasection 식별명')
    main_ip = Column(String(45), comment='메인 IP 주소')
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, comment='마지막 IP 체크 시간')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# 프록시 IP 테이블
class ProxyIP(Base):
    __tablename__ = 'proxy_ip'
    
    proxy_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_id = Column(BigInteger, nullable=False)
    proxy_ip = Column(String(45))
    proxy_port = Column(Integer)
    latency_ms = Column(Float, comment='Ping/RTT 측정(ms)')
    success_rate = Column(Float, comment='최근 요청 성공률 %')
    is_active = Column(Boolean, default=True, comment='현재 사용 가능한지')
    last_checked = Column(DateTime)
    


# 상품 테이블
class Product(Base):
    __tablename__ = 'product'
    
    product_id = Column(BigInteger, primary_key=True, autoincrement=True)
    main_keyword = Column(String(255))
    base_search_keyword = Column(String(255))
    temp_search_keyword = Column(String(255))
    nv_mid = Column(String(50))
    proxy_id = Column(BigInteger)
    proxy_ip = Column(String(45), comment='화면 랜더링용 비정규화 PROXY IP')
    datasection_id = Column(BigInteger, comment='관계 참조용')
    max_slot_per_hour = Column(Integer, default=7, comment='시간당 최대 허용 slot (기본 7)')
    slot = Column(Integer, default=0, comment='시간당 쳐야하는 slot 수 (고정값)')  # 추가
    slot_hit = Column(Integer, default=0, comment='가중치 hit (작업 수행 시 감소)')
    last_hit_reset = Column(DateTime, comment='마지막 hit 초기화 시간')
    is_active = Column(Boolean, default=True, comment='상품 활성화 여부')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    start_date = Column(DateTime, comment='작업 시작 날짜/시간')
    end_date = Column(DateTime, comment='작업 종료 날짜/시간')



# 상품 스케줄 테이블
class ProductSchedule(Base):
    __tablename__ = 'product_schedule'
    
    schedule_id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, nullable=False)
    start_time = Column(DateTime, comment='크롤링 시작 시간')
    end_time = Column(DateTime, comment='크롤링 종료 시간')
    is_active = Column(Boolean, comment='스케줄 활성화 여부')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    


# 상품 변경 로그 테이블
class ProductChangeLog(Base):
    __tablename__ = 'product_change_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, nullable=False)
    action_type = Column(String(50), comment='INSERT/UPDATE/DELETE/CANCEL')
    changed_fields = Column(JSON, comment='변경된 필드와 이전/이후 값')
    changed_by = Column(String(255), comment='변경 수행자')
    changed_at = Column(DateTime, default=func.now())
    


# 프록시 로그 테이블
class ProxyLog(Base):
    __tablename__ = 'proxy_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, nullable=False)
    proxy_id = Column(BigInteger, nullable=False)
    request_time = Column(DateTime)
    request_url = Column(String(500))
    status = Column(String(50), comment='success / fail')
    response_code = Column(Integer)
    response_time_ms = Column(Float)


# 프록시 IP 체크 로그 테이블
class IPCheckLog(Base):
    __tablename__ = 'ip_check_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_id = Column(BigInteger, nullable=False)
    proxy_id = Column(BigInteger, nullable=False)
    check_time = Column(DateTime, comment='체크 수행 시간')
    check_result = Column(String(50), comment='PASS/FAIL')
    error_message = Column(Text)

# 쿠키 수집 테이블
class CookieCollection(Base):
    __tablename__ = 'cookie_collection'
    
    cookie_index = Column(BigInteger, primary_key=True, autoincrement=True)
    proxy_id = Column(BigInteger, nullable=False)
    proxy_ip = Column(String(45), comment='비정규화 proxy_ip 추가 20251205')
    cookie_json = Column(Text, comment='JSON 형식의 쿠키 데이터')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    


# 쿠키 수집 작업 로그 테이블
class CookieCollectionLog(Base):
    __tablename__ = 'cookie_collection_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_id = Column(BigInteger, nullable=False)
    collection_date = Column(Date)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    status = Column(String(50), comment='SUCCESS/FAIL/IN_PROGRESS')
    collected_count = Column(Integer, comment='수집된 쿠키 수')
    error_message = Column(Text)

# 사용자/계정 테이블 (로그인 + 계정관리)
class UsersAdmin(Base):
    __tablename__ = 'users_admin'
    
    user_id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, comment='로그인 아이디')
    password_hash = Column(String(255), nullable=False, comment='암호화된 비밀번호')
    role = Column(String(50), nullable=False, comment='총판사(total)/대행사(agency)/광고주(advertiser)')
    parent_user_id = Column(BigInteger, comment='상위 계정 ID')
    affiliation = Column(String(255), comment='소속')
    memo = Column(Text, comment='메모')
    ad_count = Column(Integer, default=0, comment='광고 수량')
    active_ad_count = Column(Integer, default=0, comment='진행중인 광고 수')
    is_active = Column(Boolean, default=True, comment='계정 활성화 여부')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
# 사용자 세션 테이블
class UserSession(Base):
    __tablename__ = 'user_session'
    
    session_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='세션 ID')
    token = Column(String(255), unique=True, nullable=False, index=True, comment='세션 토큰')
    user_id = Column(BigInteger, nullable=False, index=True, comment='사용자 ID')
    username = Column(String(255), nullable=False, comment='사용자명')
    role = Column(String(50), nullable=False, comment='역할')
    created_at = Column(DateTime, default=func.now(), comment='생성일시')
    expires_at = Column(DateTime, nullable=False, index=True, comment='만료일시')
    
    __table_args__ = (
        Index('idx_token', 'token'),
        Index('idx_user_id', 'user_id'),
        Index('idx_expires_at', 'expires_at'),
    )

# 광고 테이블 (광고관리)
class AdvertisementsAdmin(Base):
    __tablename__ = 'advertisements_admin'
    
    ad_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, comment='광고주 계정 ID')
    status = Column(String(50), nullable=False, comment='정상(normal)/오류(error)/대기(pending)/종료예정(ending)/종료(ended)')
    main_keyword = Column(String(255), nullable=False, comment='메인키워드')
    price_comparison = Column(Boolean, default=False, comment='가격비교 여부 (Y/N)')
    plus = Column(Boolean, default=False, comment='플러스 여부 (Y/N)')
    product_name = Column(String(255), comment='상품명')
    product_mid = Column(String(255), comment='상품MID')
    price_comparison_mid = Column(String(255), comment='가격비교MID')
    work_days = Column(Integer, comment='작업일수')
    start_date = Column(Date, nullable=False, comment='시작일')
    end_date = Column(Date, nullable=False, comment='종료일')
    affiliation = Column(String(255), comment='소속')
    slot = Column(Integer, comment='슬롯')
    memo = Column(Text, comment='메모')
    rank = Column(Integer, comment='순위 (네이버 쇼핑 검색 결과)')
    store_url = Column(String(500), comment='스마트스토어 URL')
    shopping_url = Column(String(500), comment='쇼핑 검색 URL')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    

# 광고 순위 이력 테이블 (2주간 보관)
class AdvertisementRankHistory(Base):
    __tablename__ = 'advertisement_rank_history'
    
    rank_id = Column(BigInteger, primary_key=True, autoincrement=True)
    ad_id = Column(BigInteger, nullable=False, comment='광고 ID')
    rank_date = Column(Date, nullable=False, comment='순위 조회 일자')
    rank = Column(Integer, nullable=True, comment='순위 (없으면 NULL)')
    product_name = Column(String(100), nullable=True, comment='상품명')
    created_at = Column(DateTime, default=func.now(), comment='기록 생성 시간')
    
    # 인덱스: ad_id와 rank_date 조합으로 빠른 조회
    __table_args__ = (
        Index('idx_ad_rank_date', 'ad_id', 'rank_date'),
    )


# 정산 로그 테이블 (정산로그)
class SettlementAdmin(Base):
    __tablename__ = 'settlement_admin'
    
    settlement_id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_type = Column(String(50), nullable=False, comment='발주(order)/연장(extend)/환불(refund)/수정(update)')
    agency_user_id = Column(BigInteger, comment='대행사 계정 ID')
    advertiser_user_id = Column(BigInteger, comment='광고주 계정 ID')
    ad_id = Column(BigInteger, comment='관련 광고 ID')
    performed_by_user_id = Column(BigInteger, comment='작업 수행자 ID (발주/연장/수정한 유저)')
    quantity = Column(Integer, comment='수량')
    period_start = Column(Date, comment='기간 시작일')
    period_end = Column(Date, comment='기간 종료일')
    total_days = Column(Integer, comment='일수합계')
    created_at = Column(DateTime, default=func.now(), comment='생성일시')
    start_date = Column(Date, comment='시작일')
    ad_product_nm = Column(String(255), comment='광고 상품명 (광고 삭제 시에도 유지)')
    # 광고 id로 광고 소유자의 user_id 확인후 광고주 id, 및 대행사 id 의 대행사 이름 가져오기.


# 공지사항 테이블
class Notice(Base):
    __tablename__ = 'notices'
    
    notice_id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False, comment='공지사항 제목')
    content = Column(Text, nullable=False, comment='공지사항 내용')
    is_pinned = Column(Boolean, default=False, comment='고정 여부 (TINYINT(1))')
    created_by = Column(BigInteger, nullable=False, comment='작성자 user_id')
    updated_by = Column(BigInteger, comment='수정자 user_id')
    created_at = Column(DateTime, server_default=func.current_timestamp(), comment='생성일시')
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), comment='수정일시')


# 자주묻는 질문(FAQ) 테이블
class FAQ(Base):
    __tablename__ = 'faqs'
    
    faq_id = Column(BigInteger, primary_key=True, autoincrement=True)
    question = Column(String(255), nullable=False, comment='질문')
    answer = Column(Text, nullable=False, comment='답변')
    category = Column(String(100), comment='카테고리')
    sort_order = Column(Integer, default=0, comment='정렬 순서')
    created_by = Column(BigInteger, nullable=False, comment='작성자 user_id')
    updated_by = Column(BigInteger, comment='수정자 user_id')
    created_at = Column(DateTime, server_default=func.current_timestamp(), comment='생성일시')
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), comment='수정일시')


# 리워드 타겟 테이블
class RewardTarget(Base):
    __tablename__ = 'reward_target'
    
    reward_target_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='리워드 타겟 ID')
    keyword = Column(String(100), comment='키워드')
    nvmid = Column(String(100), comment='네이버 상품 ID')
    search_url = Column(Text, comment='검색 URL')
    product_url = Column(Text, comment='상품 URL')


# 리워드 순위 테이블
class RewardRank(Base):
    __tablename__ = 'reward_rank'
    
    reward_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='리워드 ID')
    keyword = Column(String(100), comment='키워드')
    store_name = Column(String(255), comment='스토어명')
    product_name = Column(String(255), comment='상품명')
    productid = Column(String(50), comment='상품 ID')
    search_url = Column(Text, comment='검색 URL')
    product_url = Column(String(400), comment='상품 URL')
    image_url = Column(Text, comment='이미지 URL')
    image_tag = Column(Text, comment='이미지 태그')
    created_at = Column(DateTime, default=func.now(), comment='생성일시')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='수정일시')
    nvmid = Column(String(100), comment='네이버 상품 ID')
    is_shopping_exposed = Column(Boolean, default=False, comment='통검 노출여부 (boolean)')
    cpc = Column(Boolean, default=False, comment='CPC 여부 (boolean)')
    mnc_idx = Column(Integer, nullable=True, comment='외부 파트너사 미션 IDX')
    signature = Column(String(255), nullable=True, comment='미션 등록 시 생성된 서명')
    mnc_limitcnt = Column(Integer, nullable=True, comment='미션 최대 참여 인원수')
    mnc_mission_starttime = Column(Date, nullable=True, comment='미션 시작일')
    mnc_mission_endtime = Column(Date, nullable=True, comment='미션 종료일')
    price = Column(Integer, nullable=True, comment='상품 가격')


# 리워드 랭크 작업 이력 테이블
class RewardRankHistory(Base):
    __tablename__ = 'reward_rank_history'
    
    history_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='이력 ID')
    reward_id = Column(BigInteger, nullable=False, comment='리워드 ID')
    operation_type = Column(String(20), nullable=False, comment='작업 타입 (CREATE, UPDATE, DELETE)')
    api_endpoint = Column(String(255), nullable=True, comment='API 엔드포인트')
    before_data = Column(JSON, nullable=True, comment='작업 전 데이터 (JSON)')
    after_data = Column(JSON, nullable=True, comment='작업 후 데이터 (JSON)')
    response_data = Column(JSON, nullable=True, comment='외부 API 응답 데이터 (JSON)')
    mnc_idx = Column(Integer, nullable=True, comment='외부 파트너사 미션 IDX')
    signature = Column(String(255), nullable=True, comment='미션 등록/수정 시 생성된 서명')
    success = Column(Boolean, nullable=False, default=False, comment='작업 성공 여부')
    error_message = Column(Text, nullable=True, comment='에러 메시지 (실패 시)')
    created_at = Column(DateTime, default=func.now(), nullable=False, comment='생성일시')
    
    # 인덱스
    __table_args__ = (
        Index('idx_reward_id', 'reward_id'),
    )


# 리워드 링크 테이블 (짧은 링크 관리)
class RewardLink(Base):
    __tablename__ = 'reward_link'
    
    link_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='링크 ID')
    short_code = Column(String(40), nullable=False, comment='짧은 링크 코드 (예: v8ZSBUT43vj)')
    product_name = Column(String(255), comment='상품명')
    nvmid = Column(String(100), comment='네이버 상품 ID')
    reward_link = Column(Text, comment='생성된 리다이렉트 링크 (예: https://domain.com/redirect/v8ZSBUT43vj)')
    created_at = Column(DateTime, default=func.now(), comment='생성일시')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='수정일시')


# 리워드 링크 키워드 조합 테이블
class RewardLinkKeyword(Base):
    __tablename__ = 'reward_link_keyword'
    
    keyword_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='키워드 ID')
    link_id = Column(BigInteger, nullable=False, comment='링크 ID')
    short_code = Column(String(40), nullable=False, comment='짧은 링크 코드 (예: v8ZSBUT43vj)')
    query_keyword = Column(String(255), nullable=False, comment='query 파라미터 키워드')
    acq_keyword = Column(String(255), nullable=False, comment='acq 파라미터 키워드')
    created_at = Column(DateTime, default=func.now(), comment='생성일시')
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment='수정일시')


# 랜덤 ACQ 테이블
class RandomAcq(Base):
    __tablename__ = 'random_acq'
    
    acq_id = Column(BigInteger, primary_key=True, autoincrement=True, comment='ACQ ID')
    acq_word = Column(String(50), nullable=False, comment='ACQ 단어')
    adj_word = Column(String(50), nullable=False, comment='형용사 단어')
    
