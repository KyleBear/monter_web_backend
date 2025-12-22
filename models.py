"""
SQLAlchemy ORM 모델
dbml.sql 스키마를 기반으로 생성
"""
from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, Date, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
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
    
    # 관계
    proxy_ips = relationship("ProxyIP", back_populates="datasection")
    ip_check_logs = relationship("IPCheckLog", back_populates="datasection")
    cookie_collection_logs = relationship("CookieCollectionLog", back_populates="datasection")


# 프록시 IP 테이블
class ProxyIP(Base):
    __tablename__ = 'proxy_ip'
    
    proxy_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_id = Column(BigInteger, ForeignKey('datasection.datasection_id'), nullable=False)
    proxy_ip = Column(String(45))
    proxy_port = Column(Integer)
    latency_ms = Column(Float, comment='Ping/RTT 측정(ms)')
    success_rate = Column(Float, comment='최근 요청 성공률 %')
    is_active = Column(Boolean, default=True, comment='현재 사용 가능한지')
    last_checked = Column(DateTime)
    
    # 관계
    datasection = relationship("DataSection", back_populates="proxy_ips")
    proxy_logs = relationship("ProxyLog", back_populates="proxy")
    ip_check_logs = relationship("IPCheckLog", back_populates="proxy")
    cookie_collections = relationship("CookieCollection", back_populates="proxy")
    products = relationship("Product", back_populates="proxy")


# 상품 테이블
class Product(Base):
    __tablename__ = 'product'
    
    product_id = Column(BigInteger, primary_key=True, autoincrement=True)
    main_keyword = Column(String(255))
    base_search_keyword = Column(String(255))
    temp_search_keyword = Column(String(255))
    nv_mid = Column(String(50))
    proxy_id = Column(BigInteger, ForeignKey('proxy_ip.proxy_id'))
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
    # 관계
    proxy = relationship("ProxyIP", back_populates="products")
    schedules = relationship("ProductSchedule", back_populates="product")
    change_logs = relationship("ProductChangeLog", back_populates="product")
    proxy_logs = relationship("ProxyLog", back_populates="product")


# 상품 스케줄 테이블
class ProductSchedule(Base):
    __tablename__ = 'product_schedule'
    
    schedule_id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey('product.product_id'), nullable=False)
    start_time = Column(DateTime, comment='크롤링 시작 시간')
    end_time = Column(DateTime, comment='크롤링 종료 시간')
    is_active = Column(Boolean, comment='스케줄 활성화 여부')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 관계
    product = relationship("Product", back_populates="schedules")


# 상품 변경 로그 테이블
class ProductChangeLog(Base):
    __tablename__ = 'product_change_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey('product.product_id'), nullable=False)
    action_type = Column(String(50), comment='INSERT/UPDATE/DELETE/CANCEL')
    changed_fields = Column(JSON, comment='변경된 필드와 이전/이후 값')
    changed_by = Column(String(255), comment='변경 수행자')
    changed_at = Column(DateTime, default=func.now())
    
    # 관계
    product = relationship("Product", back_populates="change_logs")


# 프록시 로그 테이블
class ProxyLog(Base):
    __tablename__ = 'proxy_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, ForeignKey('product.product_id'), nullable=False)
    proxy_id = Column(BigInteger, ForeignKey('proxy_ip.proxy_id'), nullable=False)
    request_time = Column(DateTime)
    request_url = Column(String(500))
    status = Column(String(50), comment='success / fail')
    response_code = Column(Integer)
    response_time_ms = Column(Float)
    
    # 관계
    product = relationship("Product", back_populates="proxy_logs")
    proxy = relationship("ProxyIP", back_populates="proxy_logs")


# 프록시 IP 체크 로그 테이블
class IPCheckLog(Base):
    __tablename__ = 'ip_check_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_id = Column(BigInteger, ForeignKey('datasection.datasection_id'), nullable=False)
    proxy_id = Column(BigInteger, ForeignKey('proxy_ip.proxy_id'), nullable=False)
    check_time = Column(DateTime, comment='체크 수행 시간')
    check_result = Column(String(50), comment='PASS/FAIL')
    error_message = Column(Text)
    
    # 관계
    datasection = relationship("DataSection", back_populates="ip_check_logs")
    proxy = relationship("ProxyIP", back_populates="ip_check_logs")


# 쿠키 수집 테이블
class CookieCollection(Base):
    __tablename__ = 'cookie_collection'
    
    cookie_index = Column(BigInteger, primary_key=True, autoincrement=True)
    proxy_id = Column(BigInteger, ForeignKey('proxy_ip.proxy_id'), nullable=False)
    proxy_ip = Column(String(45), comment='비정규화 proxy_ip 추가 20251205')
    cookie_json = Column(Text, comment='JSON 형식의 쿠키 데이터')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 관계
    proxy = relationship("ProxyIP", back_populates="cookie_collections")


# 쿠키 수집 작업 로그 테이블
class CookieCollectionLog(Base):
    __tablename__ = 'cookie_collection_log'
    
    log_id = Column(BigInteger, primary_key=True, autoincrement=True)
    datasection_id = Column(BigInteger, ForeignKey('datasection.datasection_id'), nullable=False)
    collection_date = Column(Date)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    status = Column(String(50), comment='SUCCESS/FAIL/IN_PROGRESS')
    collected_count = Column(Integer, comment='수집된 쿠키 수')
    error_message = Column(Text)
    
    # 관계
    datasection = relationship("DataSection", back_populates="cookie_collection_logs")


# 사용자/계정 테이블 (로그인 + 계정관리)
class UsersAdmin(Base):
    __tablename__ = 'users_admin'
    
    user_id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False, comment='로그인 아이디')
    password_hash = Column(String(255), nullable=False, comment='암호화된 비밀번호')
    role = Column(String(50), nullable=False, comment='총판사(total)/대행사(agency)/광고주(advertiser)')
    parent_user_id = Column(BigInteger, ForeignKey('users_admin.user_id'), comment='상위 계정 ID')
    affiliation = Column(String(255), comment='소속')
    memo = Column(Text, comment='메모')
    ad_count = Column(Integer, default=0, comment='광고 수량')
    active_ad_count = Column(Integer, default=0, comment='진행중인 광고 수')
    is_active = Column(Boolean, default=True, comment='계정 활성화 여부')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 관계
    parent_user = relationship("UsersAdmin", remote_side=[user_id], backref="child_users")
    advertisements = relationship("AdvertisementsAdmin", back_populates="user")


# 광고 테이블 (광고관리)
class AdvertisementsAdmin(Base):
    __tablename__ = 'advertisements_admin'
    
    ad_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users_admin.user_id'), nullable=False, comment='광고주 계정 ID')
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
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 관계
    user = relationship("UsersAdmin", back_populates="advertisements")
    settlements = relationship("SettlementAdmin", back_populates="advertisement")


# 정산 로그 테이블 (정산로그)
class SettlementAdmin(Base):
    __tablename__ = 'settlement_admin'
    
    settlement_id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_type = Column(String(50), nullable=False, comment='발주(order)/연장(extend)/환불(refund)')
    agency_user_id = Column(BigInteger, ForeignKey('users_admin.user_id'), comment='대행사 계정 ID')
    advertiser_user_id = Column(BigInteger, ForeignKey('users_admin.user_id'), comment='광고주 계정 ID')
    ad_id = Column(BigInteger, ForeignKey('advertisements_admin.ad_id'), comment='관련 광고 ID')
    quantity = Column(Integer, comment='수량')
    period_start = Column(Date, comment='기간 시작일')
    period_end = Column(Date, comment='기간 종료일')
    total_days = Column(Integer, comment='일수합계')
    created_at = Column(DateTime, default=func.now(), comment='생성일시')
    start_date = Column(Date, comment='시작일')
    
    # 관계
    agency_user = relationship("UsersAdmin", foreign_keys=[agency_user_id], backref="agency_settlements")
    advertiser_user = relationship("UsersAdmin", foreign_keys=[advertiser_user_id], backref="advertiser_settlements")
    advertisement = relationship("AdvertisementsAdmin", back_populates="settlements")
