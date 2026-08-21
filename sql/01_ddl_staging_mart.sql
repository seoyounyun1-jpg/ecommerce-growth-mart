-- DEPRECATED: sql/01_ddl_raw_staging_mart.sql 로 대체됨 (Raw → Staging → Mart 3-Zone)
-- 이 파일은 하위 호환용으로만 유지합니다.
-- 작성 목적 : 네이버·아마존 멀티 플랫폼 그로스 마케팅 분석용 데이터 파이프라인 종착지
-- 영역 구분 : Staging Zone → Data Mart Zone
-- =============================================================================

-- -----------------------------------------------------------------------------
-- [Staging] stg_ecommerce_orders
-- 설명 : 국내(NAVER) / 해외(AMAZON) 주문 원천 데이터를 적재하는 스테이징 테이블.
--        ETL 전 정제·검증 대상이며, RFM·매출 집계의 Single Source of Truth.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg_ecommerce_orders (
    order_id              TEXT        NOT NULL,  -- 주문 고유 ID (플랫폼별 원천 키)
    user_id               TEXT        NOT NULL,  -- 구매 유저 ID
    product_id            TEXT        NOT NULL,  -- 상품 ID
    payment_amount        NUMERIC(18, 2) NOT NULL,  -- 최종 결제금액 (기준통화 KRW 환산 후)
    discount_amount       NUMERIC(18, 2) NOT NULL DEFAULT 0,  -- 할인 적용 금액 (쿠폰·프로모션 등)
    amount_before_fx      NUMERIC(18, 2) NOT NULL,  -- 환율 변환 전 원통화 결제 금액
    currency_code         TEXT        NOT NULL,  -- 통화 코드 (ISO 4217: KRW, USD, JPY 등)
    platform              TEXT        NOT NULL,  -- 플랫폼 구분: NAVER | AMAZON
    paid_at               TIMESTAMP   NOT NULL,  -- 결제 완료 일시 (UTC 또는 KST, 파이프라인 표준 TZ 통일)

    CONSTRAINT pk_stg_ecommerce_orders
        PRIMARY KEY (order_id),

    CONSTRAINT chk_stg_orders_platform
        CHECK (platform IN ('NAVER', 'AMAZON')),

    CONSTRAINT chk_stg_orders_currency
        CHECK (LENGTH(currency_code) = 3),  -- LENGTH: SQLite·PostgreSQL 공통

    CONSTRAINT chk_stg_orders_payment_nonneg
        CHECK (payment_amount >= 0),

    CONSTRAINT chk_stg_orders_discount_nonneg
        CHECK (discount_amount >= 0),

    CONSTRAINT chk_stg_orders_amount_before_fx_nonneg
        CHECK (amount_before_fx >= 0)
);

-- PostgreSQL 전용 테이블/컬럼 주석 (SQLite는 무시됨 — 아래 -- 주석으로 대체)
-- COMMENT ON TABLE  stg_ecommerce_orders IS '국내외 이커머스 주문 원천 스테이징 테이블';
-- COMMENT ON COLUMN stg_ecommerce_orders.payment_amount IS '환율 변환·할인 반영 후 KRW 기준 결제금액';


-- -----------------------------------------------------------------------------
-- [Staging] stg_user_behavior_logs
-- 설명 : 웹/앱 사용자 행동 이벤트 로그. 퍼널 분석·UTM 어트리뷰션의 원천 데이터.
--        view_item → add_to_cart → begin_checkout → purchase 전환 경로 추적.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg_user_behavior_logs (
    log_id                TEXT        NOT NULL,  -- 로그 레코드 고유 ID
    session_id            TEXT        NOT NULL,  -- 세션 ID (동일 방문 세션 내 이벤트 묶음)
    user_id               TEXT,                 -- 로그인 유저 ID (비로그인 시 NULL 허용)
    event_name            TEXT        NOT NULL,  -- 이벤트명: view_item | add_to_cart | begin_checkout | purchase
    utm_source            TEXT,                 -- UTM Source (예: naver, google, facebook)
    utm_medium            TEXT,                 -- UTM Medium (예: cpc, organic, email)
    device_type           TEXT        NOT NULL,  -- 기기 유형 (mobile | desktop | tablet | app)
    event_at              TIMESTAMP   NOT NULL,  -- 이벤트 발생 일시

    CONSTRAINT pk_stg_user_behavior_logs
        PRIMARY KEY (log_id),

    CONSTRAINT chk_stg_logs_event_name
        CHECK (event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')),

    CONSTRAINT chk_stg_logs_device_type
        CHECK (device_type IN ('mobile', 'desktop', 'tablet', 'app'))
);

-- 선택적 FK: 유저 ID가 존재할 때만 참조 무결성 검증 (dim_users 별도 구축 시 활성화)
-- ALTER TABLE stg_user_behavior_logs
--     ADD CONSTRAINT fk_stg_logs_user
--     FOREIGN KEY (user_id) REFERENCES dim_users(user_id);


-- -----------------------------------------------------------------------------
-- [Data Mart] mart_user_funnel_daily
-- 설명 : 일자 × 플랫폼 × UTM Source 단위 퍼널 전환 집계 마트.
--        그로스 마케팅 채널별 ROI·전환율 대시보드의 핵심 Fact 테이블.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mart_user_funnel_daily (
    base_date                 DATE          NOT NULL,  -- 집계 기준일 (event_at / paid_at 의 DATE 파티션)
    platform                  TEXT          NOT NULL,  -- 플랫폼: NAVER | AMAZON
    utm_source                TEXT          NOT NULL,  -- UTM Source (NULL 대체값: '(direct)' 사용)
    total_visitors            INTEGER       NOT NULL DEFAULT 0,  -- 총 방문자 수 (distinct session_id)
    product_views             INTEGER       NOT NULL DEFAULT 0,  -- 상품 조회 수 (view_item 이벤트)
    add_to_cart_count         INTEGER       NOT NULL DEFAULT 0,  -- 장바구니 담기 수 (add_to_cart)
    checkout_started_count    INTEGER       NOT NULL DEFAULT 0,  -- 결제 시작 수 (begin_checkout)
    purchase_completed_count  INTEGER       NOT NULL DEFAULT 0,  -- 구매 완료 수 (purchase 이벤트 또는 주문 확정)
    final_conversion_rate     NUMERIC(8, 4) NOT NULL DEFAULT 0,  -- 최종 구매 전환율 = purchase / total_visitors

    CONSTRAINT pk_mart_user_funnel_daily
        PRIMARY KEY (base_date, platform, utm_source),

    CONSTRAINT chk_mart_funnel_platform
        CHECK (platform IN ('NAVER', 'AMAZON')),

    CONSTRAINT chk_mart_funnel_counts_nonneg
        CHECK (
            total_visitors           >= 0 AND
            product_views            >= 0 AND
            add_to_cart_count        >= 0 AND
            checkout_started_count   >= 0 AND
            purchase_completed_count >= 0
        ),

    CONSTRAINT chk_mart_funnel_conversion_rate
        CHECK (final_conversion_rate >= 0 AND final_conversion_rate <= 1)
);


-- -----------------------------------------------------------------------------
-- [Data Mart] mart_user_rfm_scores
-- 설명 : 유저 단위 RFM(Recency·Frequency·Monetary) 점수 및 세그먼트 마트.
--        CRM 타겟팅·리텐션 캠페인(VIP 혜택, 이탈 방지, 재활성화)의 기준 테이블.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mart_user_rfm_scores (
    user_id               TEXT          NOT NULL,  -- 유저 고유 ID
    last_purchase_date    DATE,                   -- 최근 구매일 (주문 이력 없으면 NULL)
    recency_days          INTEGER,                -- Recency: 기준일 대비 최근 구매일까지 경과 일수
    frequency_count       INTEGER       NOT NULL DEFAULT 0,  -- Frequency: 누적 구매 횟수
    monetary_amount       NUMERIC(18, 2) NOT NULL DEFAULT 0,  -- Monetary: 누적 결제 금액 (KRW)
    r_score               SMALLINT      NOT NULL,  -- Recency 점수 (1~5, 5=최근 구매)
    f_score               SMALLINT      NOT NULL,  -- Frequency 점수 (1~5, 5=고빈도)
    m_score               SMALLINT      NOT NULL,  -- Monetary 점수 (1~5, 5=고객단가)
    segment_name          TEXT          NOT NULL,  -- 최종 세그먼트: VIP | 이탈위기 | 신규 | 겨울잠

    CONSTRAINT pk_mart_user_rfm_scores
        PRIMARY KEY (user_id),

    CONSTRAINT chk_mart_rfm_r_score
        CHECK (r_score BETWEEN 1 AND 5),

    CONSTRAINT chk_mart_rfm_f_score
        CHECK (f_score BETWEEN 1 AND 5),

    CONSTRAINT chk_mart_rfm_m_score
        CHECK (m_score BETWEEN 1 AND 5),

    CONSTRAINT chk_mart_rfm_segment
        CHECK (segment_name IN ('VIP', '이탈위기', '신규', '겨울잠')),

    CONSTRAINT chk_mart_rfm_frequency_nonneg
        CHECK (frequency_count >= 0),

    CONSTRAINT chk_mart_rfm_monetary_nonneg
        CHECK (monetary_amount >= 0),

    CONSTRAINT chk_mart_rfm_recency_nonneg
        CHECK (recency_days IS NULL OR recency_days >= 0)
);


-- =============================================================================
-- 인덱스 (조회·ETL 성능 최적화)
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_stg_orders_user_paid
    ON stg_ecommerce_orders (user_id, paid_at);

CREATE INDEX IF NOT EXISTS idx_stg_orders_platform_paid
    ON stg_ecommerce_orders (platform, paid_at);

CREATE INDEX IF NOT EXISTS idx_stg_logs_event_at
    ON stg_user_behavior_logs (event_at);

CREATE INDEX IF NOT EXISTS idx_stg_logs_session_event
    ON stg_user_behavior_logs (session_id, event_name);

CREATE INDEX IF NOT EXISTS idx_stg_logs_utm_event
    ON stg_user_behavior_logs (utm_source, event_name, event_at);

CREATE INDEX IF NOT EXISTS idx_mart_funnel_date
    ON mart_user_funnel_daily (base_date);

CREATE INDEX IF NOT EXISTS idx_mart_rfm_segment
    ON mart_user_rfm_scores (segment_name);
