-- =============================================================================
-- 샘플 원천 데이터 (ETL 검증용)
-- =============================================================================

INSERT INTO stg_ecommerce_orders
    (order_id, user_id, product_id, payment_amount, discount_amount, amount_before_fx, currency_code, platform, paid_at)
VALUES
    ('ORD-NV-001', 'U001', 'P100', 89000.00,  5000.00,  89000.00, 'KRW', 'NAVER',  '2026-08-15 14:22:00'),
    ('ORD-NV-002', 'U001', 'P101', 45000.00,  0.00,     45000.00, 'KRW', 'NAVER',  '2026-08-18 09:10:00'),
    ('ORD-NV-003', 'U002', 'P102', 120000.00, 10000.00, 120000.00, 'KRW', 'NAVER',  '2026-08-10 18:45:00'),
    ('ORD-AM-001', 'U003', 'P200', 85000.00,  0.00,     65.00,    'USD', 'AMAZON', '2026-08-17 21:30:00'),
    ('ORD-AM-002', 'U003', 'P201', 42000.00,  3000.00,  32.00,    'USD', 'AMAZON', '2026-08-19 11:05:00'),
    ('ORD-NV-004', 'U004', 'P103', 29000.00,  0.00,     29000.00, 'KRW', 'NAVER',  '2026-06-01 10:00:00');

INSERT INTO stg_user_behavior_logs
    (log_id, session_id, user_id, event_name, utm_source, utm_medium, device_type, event_at)
VALUES
    ('LOG-001', 'S001', 'U001', 'view_item',       'naver',   'cpc',     'mobile',  '2026-08-18 09:00:00'),
    ('LOG-002', 'S001', 'U001', 'add_to_cart',     'naver',   'cpc',     'mobile',  '2026-08-18 09:02:00'),
    ('LOG-003', 'S001', 'U001', 'begin_checkout',  'naver',   'cpc',     'mobile',  '2026-08-18 09:05:00'),
    ('LOG-004', 'S001', 'U001', 'purchase',        'naver',   'cpc',     'mobile',  '2026-08-18 09:10:00'),
    ('LOG-005', 'S002', 'U002', 'view_item',       'google',  'organic', 'desktop', '2026-08-10 18:30:00'),
    ('LOG-006', 'S002', 'U002', 'add_to_cart',     'google',  'organic', 'desktop', '2026-08-10 18:35:00'),
    ('LOG-007', 'S002', 'U002', 'purchase',        'google',  'organic', 'desktop', '2026-08-10 18:45:00'),
    ('LOG-008', 'S003', 'U003', 'view_item',       'facebook','cpc',     'app',     '2026-08-19 10:50:00'),
    ('LOG-009', 'S003', 'U003', 'add_to_cart',     'facebook','cpc',     'app',     '2026-08-19 10:55:00'),
    ('LOG-010', 'S003', 'U003', 'begin_checkout',  'facebook','cpc',     'app',     '2026-08-19 11:00:00'),
    ('LOG-011', 'S003', 'U003', 'purchase',        'facebook','cpc',     'app',     '2026-08-19 11:05:00'),
    ('LOG-012', 'S004', NULL,   'view_item',       NULL,      NULL,      'mobile',  '2026-08-19 15:00:00');
