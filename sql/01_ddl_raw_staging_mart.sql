-- =============================================================================
-- E-commerce Growth Marketing — 3-Zone Data Architecture
-- =============================================================================
-- Zone 1  RAW      : API 원본 JSON 수집 (변환 전 Landing)
-- Zone 2  STAGING  : Human Defined 컬럼 표준화 · 검증 · 정제
-- Zone 3  MART     : 그로스 분석용 집계 (퍼널 · RFM)
--
-- 파이프라인 흐름 (자동 적재)
--   [AI GENERATED] API 호출 스크립트
--        → [RAW] 원본 JSON 수집
--        → [HUMAN DEFINED] 컬럼 표준화 · Staging 적재
--        → [DB] mart_user_funnel_daily · mart_user_rfm_scores
-- =============================================================================


-- =============================================================================
-- ZONE 1 — RAW (원본 JSON Landing)
-- =============================================================================

-- raw_ecommerce_orders
-- NAVER Commerce API / Amazon SP-API 응답 JSON을 그대로 보존
CREATE TABLE IF NOT EXISTS raw_ecommerce_orders (
    raw_id            TEXT        NOT NULL,  -- 수집 레코드 UUID
    source_api        TEXT        NOT NULL,  -- naver_commerce_api | amazon_sp_api
    batch_date        DATE        NOT NULL,  -- 수집 배치 기준일 (파티션 키)
    payload_json      TEXT        NOT NULL,  -- API 원본 JSON (비정형)
    fetched_at        TIMESTAMP   NOT NULL,  -- API 호출·적재 시각

    CONSTRAINT pk_raw_ecommerce_orders PRIMARY KEY (raw_id),
    CONSTRAINT chk_raw_orders_source
        CHECK (source_api IN ('naver_commerce_api', 'amazon_sp_api'))
);

-- raw_user_behavior_logs
-- GA4 Export / 내부 이벤트 API 응답 JSON을 그대로 보존
CREATE TABLE IF NOT EXISTS raw_user_behavior_logs (
    raw_id            TEXT        NOT NULL,
    source_api        TEXT        NOT NULL,  -- ga4_export | internal_event_api
    batch_date        DATE        NOT NULL,
    payload_json      TEXT        NOT NULL,
    fetched_at        TIMESTAMP   NOT NULL,

    CONSTRAINT pk_raw_user_behavior_logs PRIMARY KEY (raw_id),
    CONSTRAINT chk_raw_logs_source
        CHECK (source_api IN ('ga4_export', 'internal_event_api'))
);


-- =============================================================================
-- ZONE 2 — STAGING (Human Defined 표준 스키마)
-- =============================================================================

-- stg_ecommerce_orders : NAVER/AMAZON 주문 — 컬럼 표준화 완료본
CREATE TABLE IF NOT EXISTS stg_ecommerce_orders (
    order_id              TEXT           NOT NULL,
    user_id               TEXT           NOT NULL,
    product_id            TEXT           NOT NULL,
    payment_amount        NUMERIC(18, 2) NOT NULL,  -- KRW 표준화 금액
    discount_amount       NUMERIC(18, 2) NOT NULL DEFAULT 0,
    amount_before_fx      NUMERIC(18, 2) NOT NULL,  -- 환율 적용 전 원통화 금액
    currency_code         TEXT           NOT NULL,  -- 원본 통화 (ISO 4217)
    platform              TEXT           NOT NULL,
    paid_at               TIMESTAMP      NOT NULL,  -- KST 변환 완료
    order_status          TEXT           NOT NULL DEFAULT 'PAID',  -- PAID|SHIPPED|CANCELLED|REFUNDED
    fx_rate               NUMERIC(10, 4),           -- 수집 당일 적용 환율 (Audit)
    raw_id                TEXT,
    loaded_at             TIMESTAMP      NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT pk_stg_ecommerce_orders PRIMARY KEY (order_id),
    CONSTRAINT chk_stg_orders_platform CHECK (platform IN ('NAVER', 'AMAZON')),
    CONSTRAINT chk_stg_orders_status
        CHECK (order_status IN ('PAID', 'SHIPPED', 'CANCELLED', 'REFUNDED')),
    CONSTRAINT chk_stg_orders_currency CHECK (LENGTH(currency_code) = 3),
    CONSTRAINT chk_stg_orders_payment_nonneg CHECK (payment_amount >= 0),
    CONSTRAINT chk_stg_orders_discount_nonneg CHECK (discount_amount >= 0),
    CONSTRAINT chk_stg_orders_amount_before_fx_nonneg CHECK (amount_before_fx >= 0),
    CONSTRAINT fk_stg_orders_raw
        FOREIGN KEY (raw_id) REFERENCES raw_ecommerce_orders(raw_id)
);

-- stg_user_behavior_logs : event_date Range Partitioning 키
CREATE TABLE IF NOT EXISTS stg_user_behavior_logs (
    log_id                TEXT        NOT NULL,
    session_id            TEXT        NOT NULL,
    user_id               TEXT,
    event_name            TEXT        NOT NULL,
    utm_source            TEXT        NOT NULL DEFAULT '(direct)',
    utm_medium            TEXT        NOT NULL DEFAULT '(none)',
    device_type           TEXT        NOT NULL,
    event_at              TIMESTAMP   NOT NULL,  -- KST
    event_date            DATE        NOT NULL,  -- [04] 파티션 키 (KST DATE)
    raw_id                TEXT,
    loaded_at             TIMESTAMP   NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT pk_stg_user_behavior_logs PRIMARY KEY (log_id),
    CONSTRAINT chk_stg_logs_event_name
        CHECK (event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')),
    CONSTRAINT chk_stg_logs_device_type
        CHECK (device_type IN ('mobile', 'desktop', 'tablet', 'app')),
    CONSTRAINT fk_stg_logs_raw
        FOREIGN KEY (raw_id) REFERENCES raw_user_behavior_logs(raw_id)
);


-- =============================================================================
-- ZONE 3 — MART (그로스 분석 종착지)
-- =============================================================================

-- mart_user_funnel_daily : 일 × 플랫폼 × UTM 퍼널 집계
CREATE TABLE IF NOT EXISTS mart_user_funnel_daily (
    base_date                 DATE          NOT NULL,
    platform                  TEXT          NOT NULL,
    utm_source                TEXT          NOT NULL,
    total_visitors            INTEGER       NOT NULL DEFAULT 0,
    product_views             INTEGER       NOT NULL DEFAULT 0,
    add_to_cart_count         INTEGER       NOT NULL DEFAULT 0,
    checkout_started_count    INTEGER       NOT NULL DEFAULT 0,
    purchase_completed_count  INTEGER       NOT NULL DEFAULT 0,
    final_conversion_rate     NUMERIC(8, 4) NOT NULL DEFAULT 0,
    refreshed_at              TIMESTAMP     NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT pk_mart_user_funnel_daily PRIMARY KEY (base_date, platform, utm_source),
    CONSTRAINT chk_mart_funnel_platform CHECK (platform IN ('NAVER', 'AMAZON')),
    CONSTRAINT chk_mart_funnel_counts_nonneg CHECK (
        total_visitors >= 0 AND product_views >= 0 AND
        add_to_cart_count >= 0 AND checkout_started_count >= 0 AND
        purchase_completed_count >= 0
    ),
    CONSTRAINT chk_mart_funnel_conversion_rate
        CHECK (final_conversion_rate >= 0 AND final_conversion_rate <= 1)
);

-- mart_user_rfm_scores : 유저 RFM 세그먼트
CREATE TABLE IF NOT EXISTS mart_user_rfm_scores (
    user_id               TEXT          NOT NULL,
    last_purchase_date    DATE,
    recency_days          INTEGER,
    frequency_count       INTEGER       NOT NULL DEFAULT 0,
    monetary_amount       NUMERIC(18, 2) NOT NULL DEFAULT 0,
    r_score               SMALLINT      NOT NULL,
    f_score               SMALLINT      NOT NULL,
    m_score               SMALLINT      NOT NULL,
    segment_name          TEXT          NOT NULL,
    refreshed_at          TIMESTAMP     NOT NULL DEFAULT (datetime('now')),

    CONSTRAINT pk_mart_user_rfm_scores PRIMARY KEY (user_id),
    CONSTRAINT chk_mart_rfm_r_score CHECK (r_score BETWEEN 1 AND 5),
    CONSTRAINT chk_mart_rfm_f_score CHECK (f_score BETWEEN 1 AND 5),
    CONSTRAINT chk_mart_rfm_m_score CHECK (m_score BETWEEN 1 AND 5),
    CONSTRAINT chk_mart_rfm_segment
        CHECK (segment_name IN ('VIP', '이탈위기', '신규', '겨울잠')),
    CONSTRAINT chk_mart_rfm_frequency_nonneg CHECK (frequency_count >= 0),
    CONSTRAINT chk_mart_rfm_monetary_nonneg CHECK (monetary_amount >= 0),
    CONSTRAINT chk_mart_rfm_recency_nonneg CHECK (recency_days IS NULL OR recency_days >= 0)
);


-- =============================================================================
-- 인덱스
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_raw_orders_batch ON raw_ecommerce_orders (batch_date, source_api);
CREATE INDEX IF NOT EXISTS idx_raw_logs_batch   ON raw_user_behavior_logs (batch_date, source_api);

CREATE INDEX IF NOT EXISTS idx_stg_orders_user_paid    ON stg_ecommerce_orders (user_id, paid_at);
CREATE INDEX IF NOT EXISTS idx_stg_orders_platform_paid ON stg_ecommerce_orders (platform, paid_at);
CREATE INDEX IF NOT EXISTS idx_stg_logs_event_date      ON stg_user_behavior_logs (event_date);
CREATE INDEX IF NOT EXISTS idx_stg_logs_event_date_utm  ON stg_user_behavior_logs (event_date, utm_source, event_name);
CREATE INDEX IF NOT EXISTS idx_stg_orders_paid_date     ON stg_ecommerce_orders (DATE(paid_at));
CREATE INDEX IF NOT EXISTS idx_stg_orders_status          ON stg_ecommerce_orders (order_status);

CREATE INDEX IF NOT EXISTS idx_mart_funnel_date  ON mart_user_funnel_daily (base_date);
CREATE INDEX IF NOT EXISTS idx_mart_rfm_segment  ON mart_user_rfm_scores (segment_name);
