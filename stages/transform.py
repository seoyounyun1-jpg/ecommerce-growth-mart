"""
Stage 3 — HUMAN DEFINED: 컬럼 표준화 · 적재 기획
=================================================
clean_transform.py 의 Clean & Transform 함수를 호출하여 Staging Upsert.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date

from stages.clean_transform import (
    BEHAVIOR_LOOKBACK_DAYS,
    ORDER_LOOKBACK_DAYS,
    build_collection_plan,
    clean_behavior_session,
    clean_order_amazon,
    clean_order_naver,
    upsert_behavior_logs,
    upsert_orders,
)

logger = logging.getLogger("ecommerce_pipeline.transform")

# Human Defined — API → Staging 컬럼 매핑 (참조용)
NAVER_ORDER_MAP = {
    "orderNo": "order_id",
    "buyerId": "user_id",
    "productNo": "product_id",
    "totalPayment": "payment_amount",
    "discountAmt": "discount_amount",
    "originAmt": "amount_before_fx",
    "currency": "currency_code",
    "paidDatetime": "paid_at",
    "orderStatus": "order_status",
}

AMAZON_ORDER_MAP = {
    "AmazonOrderId": "order_id",
    "BuyerEmail": "user_id",
    "ASIN": "product_id",
    "OrderTotal.Amount": "payment_amount",
    "OrderStatus": "order_status",
    "PurchaseDate": "paid_at",
}

GA4_EVENT_MAP = {
    "event_id": "log_id",
    "session_id": "session_id",
    "user_pseudo_id": "user_id",
    "event_name": "event_name",
    "traffic_source.source": "utm_source",
    "traffic_source.medium": "utm_medium",
    "device.category": "device_type",
    "event_timestamp": "event_at",
}


def raw_orders_to_staging(
    conn: sqlite3.Connection,
    batch_date: str,
    rate_date: date,
) -> dict[str, int]:
    """Raw 주문 JSON → Clean → Upsert (order_id PK)."""
    order_rows: list[tuple] = []

    raw_orders = conn.execute(
        """
        SELECT raw_id, source_api, payload_json
        FROM raw_ecommerce_orders
        WHERE batch_date = ?
        """,
        (batch_date,),
    ).fetchall()

    for raw_id, source_api, payload_json in raw_orders:
        payload = json.loads(payload_json)
        if source_api == "naver_commerce_api":
            order_rows.append(clean_order_naver(raw_id, payload, rate_date))
        elif source_api == "amazon_sp_api":
            order_rows.append(clean_order_amazon(raw_id, payload, rate_date))

    return upsert_orders(conn, order_rows)


def raw_logs_to_staging(conn: sqlite3.Connection, batch_date: str) -> dict[str, int]:
    """Raw 행동 JSON → Clean → Upsert (log_id PK, Lookback=0)."""
    log_rows: list[tuple] = []

    raw_logs = conn.execute(
        """
        SELECT raw_id, payload_json
        FROM raw_user_behavior_logs
        WHERE batch_date = ?
        """,
        (batch_date,),
    ).fetchall()

    for raw_id, payload_json in raw_logs:
        payload = json.loads(payload_json)
        log_rows.extend(clean_behavior_session(raw_id, payload))

    return upsert_behavior_logs(conn, log_rows)


def apply_staging_from_raw(
    conn: sqlite3.Connection,
    run_date: date,
) -> dict[str, int]:
    """
    [01] Lookback Window 반영 Staging 적재
    - 주문: run_date 기준 ORDER_LOOKBACK_DAYS 재처리 + Upsert
    - 행동: run_date 당일만 (BEHAVIOR_LOOKBACK_DAYS=0)
    """
    plan = build_collection_plan(run_date)
    total_orders = total_logs = 0

    for order_date in plan.order_dates:
        stats = raw_orders_to_staging(conn, order_date.isoformat(), order_date)
        total_orders += stats["submitted"]

    for behavior_date in plan.behavior_dates:
        stats = raw_logs_to_staging(conn, behavior_date.isoformat())
        total_logs += stats["submitted"]

    logger.info(
        "Staging apply [run=%s]: orders=%d (lookback=%dd), logs=%d (lookback=%dd)",
        run_date.isoformat(),
        total_orders,
        ORDER_LOOKBACK_DAYS,
        total_logs,
        BEHAVIOR_LOOKBACK_DAYS,
    )
    return {"orders": total_orders, "logs": total_logs}
