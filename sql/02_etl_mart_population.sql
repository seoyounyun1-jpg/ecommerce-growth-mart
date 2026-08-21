-- =============================================================================
-- Data Mart 적재 ETL (INSERT INTO ... SELECT)
-- 전제 : stg_ecommerce_orders, stg_user_behavior_logs 에 원천 데이터 적재 완료
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 공통 파라미터 (PostgreSQL: SET / SQLite: 서브쿼리 또는 애플리케이션에서 치환)
-- :analysis_date → RFM Recency 계산 기준일 (예: CURRENT_DATE)
-- -----------------------------------------------------------------------------


-- =============================================================================
-- 1. mart_user_funnel_daily 적재
-- =============================================================================
-- 로직 요약
--   · 행동 로그에 platform 컬럼이 없으므로, 세션·유저 단위로 주문 이력에서 플랫폼을 귀속
--   · utm_source NULL → '(direct)' 로 치환하여 PK 충돌 방지
--   · total_visitors = DISTINCT session_id
--   · final_conversion_rate = purchase_completed_count / NULLIF(total_visitors, 0)
-- =============================================================================

-- (선택) 증분 적재 시 해당 일자만 삭제 후 재적재
-- DELETE FROM mart_user_funnel_daily WHERE base_date = DATE('2026-08-19');

INSERT INTO mart_user_funnel_daily (
    base_date,
    platform,
    utm_source,
    total_visitors,
    product_views,
    add_to_cart_count,
    checkout_started_count,
    purchase_completed_count,
    final_conversion_rate
)
WITH
-- Step 1. 유저별 최다 구매 플랫폼 (행동 로그 platform 미수집 시 fallback 귀속)
user_platform AS (
    SELECT
        user_id,
        platform
    FROM (
        SELECT
            user_id,
            platform,
            ROW_NUMBER() OVER (
                PARTITION BY user_id
                ORDER BY COUNT(*) DESC, MAX(paid_at) DESC
            ) AS rn
        FROM stg_ecommerce_orders
        GROUP BY user_id, platform
    ) ranked
    WHERE rn = 1
),

-- Step 2. 세션별 UTM Source (세션 내 최초 이벤트 기준 First-Touch 어트리뷰션)
session_utm AS (
    SELECT
        session_id,
        COALESCE(utm_source, '(direct)') AS utm_source
    FROM (
        SELECT
            session_id,
            utm_source,
            ROW_NUMBER() OVER (
                PARTITION BY session_id
                ORDER BY event_at ASC
            ) AS rn
        FROM stg_user_behavior_logs
    ) first_touch
    WHERE rn = 1
),

-- Step 3. 로그 레코드에 platform·utm_source 귀속
enriched_logs AS (
    SELECT
        DATE(l.event_at)                          AS base_date,
        COALESCE(up.platform, 'NAVER')            AS platform,  -- 주문 이력 없는 세션 default
        COALESCE(su.utm_source, '(direct)')       AS utm_source,
        l.session_id,
        l.event_name
    FROM stg_user_behavior_logs l
    LEFT JOIN session_utm su
        ON l.session_id = su.session_id
    LEFT JOIN user_platform up
        ON l.user_id = up.user_id
),

-- Step 4. 일자 × 플랫폼 × UTM 별 퍼널 집계
funnel_agg AS (
    SELECT
        base_date,
        platform,
        utm_source,
        COUNT(DISTINCT session_id)                                              AS total_visitors,
        SUM(CASE WHEN event_name = 'view_item'       THEN 1 ELSE 0 END)         AS product_views,
        SUM(CASE WHEN event_name = 'add_to_cart'     THEN 1 ELSE 0 END)         AS add_to_cart_count,
        SUM(CASE WHEN event_name = 'begin_checkout'  THEN 1 ELSE 0 END)         AS checkout_started_count,
        SUM(CASE WHEN event_name = 'purchase'        THEN 1 ELSE 0 END)         AS purchase_from_logs
    FROM enriched_logs
    GROUP BY base_date, platform, utm_source
),

-- Step 5. 주문 테이블 기반 구매 확정 건 (로그 누락 보완)
order_purchases AS (
    SELECT
        DATE(o.paid_at)                           AS base_date,
        o.platform,
        COALESCE(su.utm_source, '(direct)')       AS utm_source,
        COUNT(DISTINCT o.order_id)                AS purchase_from_orders
    FROM stg_ecommerce_orders o
    LEFT JOIN (
        SELECT DISTINCT user_id, utm_source
        FROM (
            SELECT
                user_id,
                COALESCE(utm_source, '(direct)') AS utm_source,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY event_at DESC
                ) AS rn
            FROM stg_user_behavior_logs
            WHERE user_id IS NOT NULL
        ) u
        WHERE rn = 1
    ) su ON o.user_id = su.user_id
    GROUP BY DATE(o.paid_at), o.platform, COALESCE(su.utm_source, '(direct)')
)

SELECT
    f.base_date,
    f.platform,
    f.utm_source,
    f.total_visitors,
    f.product_views,
    f.add_to_cart_count,
    f.checkout_started_count,
    -- 로그 purchase 와 주문 확정 건 중 큰 값 사용 (이중집계 방지를 위해 MAX)
    CASE
        WHEN COALESCE(op.purchase_from_orders, 0) >= f.purchase_from_logs
            THEN COALESCE(op.purchase_from_orders, 0)
        ELSE f.purchase_from_logs
    END                                                         AS purchase_completed_count,
    ROUND(
        MIN(
            CASE
                WHEN COALESCE(op.purchase_from_orders, 0) >= f.purchase_from_logs
                    THEN COALESCE(op.purchase_from_orders, 0)
                ELSE f.purchase_from_logs
            END * 1.0 / NULLIF(f.total_visitors, 0),
            1.0
        ),
        4
    )                                                           AS final_conversion_rate
FROM funnel_agg f
LEFT JOIN order_purchases op
    ON  f.base_date   = op.base_date
    AND f.platform    = op.platform
    AND f.utm_source  = op.utm_source;


-- =============================================================================
-- 2. mart_user_rfm_scores 적재
-- =============================================================================
-- 로직 요약
--   · Recency  : 기준일(CURRENT_DATE) - MAX(paid_at) 일수
--   · Frequency: COUNT(DISTINCT order_id)
--   · Monetary : SUM(payment_amount)
--   · R/F/M 점수: NTILE(5) 기반 1~5 분위 (PostgreSQL / SQLite 3.25+ window function)
--   · 세그먼트 규칙
--       VIP     : R≥4 AND F≥4 AND M≥4
--       이탈위기: R≤2 AND (F≥3 OR M≥3)  — 과거 우수 고객의 최근 이탈 징후
--       신규    : F=1 AND R≥4           — 최근 첫 구매 고객
--       겨울잠  : R≤2 AND F≤2 AND M≤2   — 장기 비활성 저가치
--       (위 조건 미해당 시 F·M 가중으로 VIP/이탈위기/겨울잠 중 nearest 매핑)
-- =============================================================================

-- (선택) 전체 재적재
-- DELETE FROM mart_user_rfm_scores;

INSERT INTO mart_user_rfm_scores (
    user_id,
    last_purchase_date,
    recency_days,
    frequency_count,
    monetary_amount,
    r_score,
    f_score,
    m_score,
    segment_name
)
WITH
-- 기준일: SQLite는 DATE('now'), PostgreSQL은 CURRENT_DATE
analysis_params AS (
    SELECT DATE('now') AS analysis_date  -- PostgreSQL 사용 시: SELECT CURRENT_DATE AS analysis_date
),

user_rfm_raw AS (
    SELECT
        o.user_id,
        MAX(DATE(o.paid_at))                                    AS last_purchase_date,
        CAST(
            julianday(p.analysis_date) - julianday(MAX(DATE(o.paid_at)))
            AS INTEGER
        )                                                       AS recency_days,
        COUNT(DISTINCT o.order_id)                              AS frequency_count,
        SUM(o.payment_amount)                                   AS monetary_amount
    FROM stg_ecommerce_orders o
    CROSS JOIN analysis_params p
    GROUP BY o.user_id, p.analysis_date
),

-- NTILE(5): Recency는 값이 작을수록 좋음 → 역순 NTILE
scored AS (
    SELECT
        user_id,
        last_purchase_date,
        recency_days,
        frequency_count,
        monetary_amount,
        -- Recency: 최근일수록 5점 (ASC 정렬 후 역 NTILE)
        6 - NTILE(5) OVER (ORDER BY recency_days ASC)           AS r_score,
        NTILE(5) OVER (ORDER BY frequency_count ASC)            AS f_score,
        NTILE(5) OVER (ORDER BY monetary_amount ASC)            AS m_score
    FROM user_rfm_raw
)

SELECT
    user_id,
    last_purchase_date,
    recency_days,
    frequency_count,
    monetary_amount,
    r_score,
    f_score,
    m_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4
            THEN 'VIP'
        WHEN r_score <= 2 AND (f_score >= 3 OR m_score >= 3)
            THEN '이탈위기'
        WHEN frequency_count = 1 AND r_score >= 4
            THEN '신규'
        WHEN r_score <= 2 AND f_score <= 2 AND m_score <= 2
            THEN '겨울잠'
        WHEN r_score >= 3 AND f_score >= 3
            THEN 'VIP'
        WHEN r_score <= 2
            THEN '이탈위기'
        ELSE '겨울잠'
    END AS segment_name
FROM scored;


-- =============================================================================
-- PostgreSQL 전용 RFM ETL (julianday 대신 DATE 산술)
-- =============================================================================
/*
INSERT INTO mart_user_rfm_scores ( ... )
WITH analysis_params AS (
    SELECT CURRENT_DATE AS analysis_date
),
user_rfm_raw AS (
    SELECT
        o.user_id,
        MAX(o.paid_at::DATE)                                    AS last_purchase_date,
        (p.analysis_date - MAX(o.paid_at::DATE))                AS recency_days,
        COUNT(DISTINCT o.order_id)                              AS frequency_count,
        SUM(o.payment_amount)                                   AS monetary_amount
    FROM stg_ecommerce_orders o
    CROSS JOIN analysis_params p
    GROUP BY o.user_id, p.analysis_date
),
scored AS (
    SELECT
        *,
        6 - NTILE(5) OVER (ORDER BY recency_days ASC)           AS r_score,
        NTILE(5) OVER (ORDER BY frequency_count ASC)            AS f_score,
        NTILE(5) OVER (ORDER BY monetary_amount ASC)            AS m_score
    FROM user_rfm_raw
)
SELECT
    user_id, last_purchase_date, recency_days, frequency_count, monetary_amount,
    r_score, f_score, m_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'VIP'
        WHEN r_score <= 2 AND (f_score >= 3 OR m_score >= 3) THEN '이탈위기'
        WHEN frequency_count = 1 AND r_score >= 4 THEN '신규'
        WHEN r_score <= 2 AND f_score <= 2 AND m_score <= 2 THEN '겨울잠'
        WHEN r_score >= 3 AND f_score >= 3 THEN 'VIP'
        WHEN r_score <= 2 THEN '이탈위기'
        ELSE '겨울잠'
    END
FROM scored;
*/
