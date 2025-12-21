// 데이터섹션(IP 그룹) 테이블
Table datasection {
  datasection_id bigint [primary key, note: 'AUTO_INCREMENT']
  datasection_name varchar [note: 'datasection 식별명']
  main_ip varchar [note: '메인 IP 주소']
  is_active boolean
  last_checked timestamp [note: '마지막 IP 체크 시간']
  created_at timestamp
  updated_at timestamp
}

// 상품 테이블
Table product {
  product_id bigint [primary key, note: 'AUTO_INCREMENT']
  main_keyword varchar
  base_search_keyword varchar
  temp_search_keyword varchar
  nv_mid varchar
  proxy_id bigint
  proxy_ip varchar [note: '화면 랜더링용 비정규화 PROXY IP']
  datasection_id bigint [note: '관계 참조용']
  max_slot_per_hour int [note: '시간당 최대 허용 slot (기본 7)']
  // current_hour_hit int [note: '현재 시간 사용 ht']
  slot_hit int [note: '가중치 hit']

  last_hit_reset timestamp [note: '마지막 hit 초기화 시간']
  is_active boolean [note: '상품 활성화 여부']
  created_at timestamp
  updated_at timestamp
}
// 20251205 비정규화 프록시 id ip 추가 상품 크롤링시 hit 추가 및 최종 ip 업데이트
// 쿠키 는 어플에서 교체

// 상품 스케줄 테이블 예약시간 크롤링 스케줄이 돌아갑니다.
Table product_schedule {
  schedule_id bigint [primary key, note: 'AUTO_INCREMENT']
  product_id bigint [not null]
  start_time timestamp [note: '크롤링 시작 시간']
  end_time timestamp [note: '크롤링 종료 시간']
  is_active boolean [note: '스케줄 활성화 여부']
  created_at timestamp
  updated_at timestamp
}

// 상품 변경 로그 테이블
Table product_change_log {
  log_id bigint [primary key, note: 'AUTO_INCREMENT']
  product_id bigint [not null]
  action_type varchar [note: 'INSERT/UPDATE/DELETE/CANCEL']
  changed_fields json [note: '변경된 필드와 이전/이후 값']
  changed_by varchar [note: '변경 수행자']
  changed_at timestamp
}

// 프록시 ip 테이블
Table proxy_ip {
  proxy_id bigint [primary key, note: 'AUTO_INCREMENT']
  datasection_id bigint [not null]
  proxy_ip varchar
  proxy_port int
  latency_ms float [note: 'Ping/RTT 측정(ms)']
  success_rate float [note: '최근 요청 성공률 %']
  is_active boolean [note: '현재 사용 가능한지']
  last_checked timestamp
}

// 프록시 로그 테이블
Table proxy_log {
  log_id bigint [primary key, note: 'AUTO_INCREMENT']
  product_id bigint [not null]
  proxy_id bigint [not null]
  request_time timestamp
  request_url varchar
  status varchar [note: 'success / fail']
  response_code int
  response_time_ms float
}

// 프록시 IP 체크 로그 테이블 
Table ip_check_log {
  log_id bigint [primary key, note: 'AUTO_INCREMENT']
  datasection_id bigint [not null]
  proxy_id bigint [not null]
  check_time timestamp [note: '체크 수행 시간']
  check_result varchar [note: 'PASS/FAIL']
  error_message text
}

// 쿠키 수집 테이블
Table cookie_collection {
  cookie_index bigint [primary key, note: 'AUTO_INCREMENT']
  proxy_id bigint [not null]
  proxy_ip varchar
  cookie_json json
  created_at timestamp
  updated_at timestamp
}
// 쿠키수집 테이블 비정규화 proxy_ip 추가 20251205


// 쿠키 수집 작업 로그 테이블
Table cookie_collection_log {
  log_id bigint [primary key, note: 'AUTO_INCREMENT']
  datasection_id bigint [not null]
  collection_date date
  start_time timestamp
  end_time timestamp
  status varchar [note: 'SUCCESS/FAIL/IN_PROGRESS']
  collected_count int [note: '수집된 쿠키 수']
  error_message text
}

// 사용자/계정 테이블 (로그인 + 계정관리)
// 사용자/계정 테이블 (로그인 + 계정관리)
Table users_admin{
  user_id bigint [primary key, note: 'AUTO_INCREMENT']
  username varchar [unique, not null, note: '로그인 아이디']
  password_hash varchar [not null, note: '암호화된 비밀번호']
  role varchar [not null, note: '총판사(total)/대행사(agency)/광고주(advertiser)']
  parent_user_id bigint [note: '상위 계정 ID (총판사는 null, 대행사는 총판사 ID, 광고주는 대행사 ID)']
  affiliation varchar [note: '소속']
  memo text [note: '메모']
  ad_count int [default: 0, note: '광고 수량']
  active_ad_count int [default: 0, note: '진행중인 광고 수']
  is_active boolean [default: true, note: '계정 활성화 여부']
  created_at timestamp
  updated_at timestamp
}

// 광고 테이블 (광고관리)
Table advertisements_admin {
  ad_id bigint [primary key, note: 'AUTO_INCREMENT']
  user_id bigint [not null, note: '광고주 계정 ID']
  status varchar [not null, note: '정상(normal)/오류(error)/대기(pending)/종료예정(ending)/종료(ended)']
  main_keyword varchar [not null, note: '메인키워드']
  price_comparison boolean [default: false, note: '가격비교 여부 (Y/N)']
  plus boolean [default: false, note: '플러스 여부 (Y/N)']
  product_name varchar [note: '상품명']
  product_mid varchar [note: '상품MID']
  price_comparison_mid varchar [note: '가격비교MID']
  work_days int [note: '작업일수']
  start_date date [not null, note: '시작일']
  end_date date [not null, note: '종료일']
  created_at timestamp
  updated_at timestamp
}

// 정산 로그 테이블 (정산로그)
Table settlement_admin {
  settlement_id bigint [primary key, note: 'AUTO_INCREMENT']
  settlement_type varchar [not null, note: '발주(order)/연장(extend)/환불(refund)']
  agency_user_id bigint [note: '대행사 계정 ID']
  advertiser_user_id bigint [note: '광고주 계정 ID']
  ad_id bigint [note: '관련 광고 ID']
  quantity int [note: '수량']
  period_start date [note: '기간 시작일']
  period_end date [note: '기간 종료일']
  total_days int [note: '일수합계']
  created_at timestamp [note: '생성일시']
  start_date date [note: '시작일']
}

// Relationships 추가
Ref: users.user_id < users.parent_user_id [note: '상위 계정 참조']
Ref: users.user_id < advertisements.user_id
Ref: users.user_id < settlement_logs.agency_user_id
Ref: users.user_id < settlement_logs.advertiser_user_id
Ref: advertisements.ad_id < settlement_logs.ad_id

// Relationships
Ref: datasection.datasection_id < proxy_ip.datasection_id
Ref: datasection.datasection_id < ip_check_log.datasection_id
Ref: datasection.datasection_id < cookie_collection_log.datasection_id

Ref: product.product_id < product_schedule.product_id
Ref: product.product_id < product_change_log.product_id
Ref: product.product_id < proxy_log.product_id

Ref: proxy_ip.proxy_id < proxy_log.proxy_id
Ref: proxy_ip.proxy_id < ip_check_log.proxy_id
Ref: proxy_ip.proxy_id < cookie_collection.proxy_id

Ref: "proxy_log"."log_id" < "proxy_log"."request_time"