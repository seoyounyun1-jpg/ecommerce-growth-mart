"""
Clean & Transform — 데이터 정제 함수 모음
==========================================
01. 수집 주기 · Lookback Window
02. 단위 표준화 (KRW · KST · Null)
03. 중복 제거 (Upsert / Idempotency)
04. 적재 단위 · 파티셔닝 (event_date)
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence, TypeVar

logger = logging.getLogger("ecommerce_pipeline.clean_transform")

# =============================================================================
# 01. 수집 주기 · Lookback Window
# =============================================================================
ORDER_BATCH_CRON = "0 2 * * *"       # 일별 1회 — 새벽 2시 (KST)
ORDER_LOOKBACK_DAYS = 14             # 주문: 14일 재수집 (취소/환불 반영)
BEHAVIOR_LOOKBACK_DAYS = 0           # 행동 로그: Lookback 없음 (불변)
BEHAVIOR_BATCH_INTERVAL = "hourly"   # 행동 로그: 실시간~매시간 집계

KST = timezone(timedelta(hours=9))

# =============================================================================
# 02. 단위 표준화 — 환율 (수집 당일 기준, Mock FX API)
# =============================================================================
DEFAULT_FX_TABLE: dict[str, float] = {
    "KRW": 1.0,
    "USD": 1_350.0,
    "JPY": 9.2,
}

NULL_DEFAULTS = {
    "utm_source": "(direct)",
    "utm_medium": "(none)",
    "discount_amount": 0.0,
    "user_id": None,  # 비로그인 허용
}


@dataclass(frozen=True)
class CollectionPlan:
    """단일 배치 실행(run_date) 기준 수집 범위."""

    run_date: date
    order_dates: tuple[date, ...]   # 14일 Lookback 포함
    behavior_dates: tuple[date, ...]  # Lookback=0 → run_date만


def build_collection_plan(
    run_date: date,
    order_lookback_days: int = ORDER_LOOKBACK_DAYS,
    behavior_lookback_days: int = BEHAVIOR_LOOKBACK_DAYS,
) -> CollectionPlan:
    """
    [01] 수집 주기 판단
    - 주문: run_date 포함 과거 order_lookback_days일 재수집
    - 행동: behavior_lookback_days=0 → run_date 당일만

    order_dates는 과거→run_date(오름차순) 순서로 반환한다. Upsert는 order_id
    PK 기준 마지막 반영이 최종 상태가 되므로, run_date(가장 최근 배치 —
    취소/환불 등 상태 갱신이 착지하는 지점)를 마지막에 처리해야 오래된
    배치의 원본 상태로 덮어써지지 않는다.
    """
    order_dates = tuple(
        run_date - timedelta(days=i) for i in range(order_lookback_days, -1, -1)
    )
    behavior_dates = (
        tuple(run_date - timedelta(days=i) for i in range(behavior_lookback_days + 1))
        if behavior_lookback_days > 0
        else (run_date,)
    )
    return CollectionPlan(
        run_date=run_date,
        order_dates=order_dates,
        behavior_dates=behavior_dates,
    )


def fetch_fx_rate(currency: str, rate_date: date) -> float:
    """수집 당일 환율 (Mock — 실 운영 시 환율 API 연동)."""
    base = DEFAULT_FX_TABLE.get(currency.upper())
    if base is None:
        raise ValueError(f"Unsupported currency: {currency}")
    # 일자별 미세 변동 시뮬레이션 (재현성)
    jitter = ((rate_date.toordinal() % 7) - 3) * 0.002
    return round(base * (1 + jitter), 4)


def standardize_currency(
    amount: float,
    currency: str,
    rate_date: date,
) -> tuple[float, float, float, str]:
    """
    [02] 통화 표준화 → KRW
    Returns: (payment_krw, amount_before_fx, fx_rate, original_currency)
    """
    currency = currency.upper()
    fx_rate = fetch_fx_rate(currency, rate_date)
    if currency == "KRW":
        return round(amount, 2), round(amount, 2), fx_rate, currency
    payment_krw = round(amount * fx_rate, 2)
    return payment_krw, round(amount, 2), fx_rate, currency


def standardize_timestamp(ts_raw: str) -> datetime:
    """
    [02] 타임스탬프 KST 변환
    UTC(Z suffix) · naive(KST 가정) 모두 처리.
    """
    normalized = ts_raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        dt = datetime.strptime(ts_raw[:19], "%Y-%m-%dT%H:%M:%S")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    else:
        dt = dt.astimezone(KST)
    return dt


def to_kst_string(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    else:
        dt = dt.astimezone(KST)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def extract_event_date(dt: datetime) -> str:
    """[04] event_date 파티션 키 (KST 기준 DATE)."""
    return to_kst_string(dt)[:10]


def standardize_null(value: Any, field: str) -> Any:
    """[02] 결측치 · Null 정제 — 마트 SUM/AVG 안전."""
    if value is not None and value != "":
        return value
    default = NULL_DEFAULTS.get(field)
    if field in ("utm_source", "utm_medium") and default:
        return default
    return default


def standardize_device(device: str | None) -> str:
    allowed = {"mobile", "desktop", "tablet", "app"}
    if device in allowed:
        return device
    return "mobile"


T = TypeVar("T")


def dedupe_by_key(rows: Sequence[T], key_index: int) -> list[T]:
    """
    [03] 메모리 수준 중복 제거 (동일 PK 마지막 값 우선 — Upsert 전처리).
    key_index: tuple 내 PK 컬럼 위치.
    """
    seen: dict[Any, T] = {}
    for row in rows:
        seen[row[key_index]] = row
    return list(seen.values())


# =============================================================================
# Clean & Transform — 주문 · 행동 로그
# =============================================================================

def clean_order_naver(
    raw_id: str,
    payload: dict[str, Any],
    rate_date: date,
) -> tuple:
    paid_at = standardize_timestamp(payload["paidDatetime"])
    payment, before_fx, fx_rate, orig_currency = standardize_currency(
        float(payload["totalPayment"]),
        payload.get("currency", "KRW"),
        rate_date,
    )
    discount = float(payload.get("discountAmt") or 0)
    if orig_currency != "KRW":
        discount = round(discount * fx_rate, 2)

    return (
        payload["orderNo"],
        standardize_null(payload.get("buyerId"), "user_id") or "UNKNOWN",
        payload["productNo"],
        payment,
        discount,
        before_fx,
        orig_currency,
        "NAVER",
        to_kst_string(paid_at),
        payload.get("orderStatus", "PAID"),
        fx_rate,
        raw_id,
    )


def clean_order_amazon(
    raw_id: str,
    payload: dict[str, Any],
    rate_date: date,
) -> tuple:
    paid_at = standardize_timestamp(payload["PurchaseDate"])
    usd_net = float(payload["OrderTotal"]["Amount"])
    discount_usd = float(payload.get("PromotionDiscount", {}).get("Amount", 0))
    gross_usd = usd_net + discount_usd
    currency = payload["OrderTotal"]["CurrencyCode"]
    fx_rate = fetch_fx_rate(currency, rate_date)
    payment = round(usd_net * fx_rate, 2)
    discount_krw = round(discount_usd * fx_rate, 2)

    return (
        payload["AmazonOrderId"],
        standardize_null(payload.get("BuyerEmail"), "user_id") or "UNKNOWN",
        payload["ASIN"],
        payment,
        discount_krw,
        round(gross_usd, 2),
        currency,
        "AMAZON",
        to_kst_string(paid_at),
        payload.get("OrderStatus", "PAID"),
        fx_rate,
        raw_id,
    )


def clean_behavior_event(raw_id: str, event: dict[str, Any]) -> tuple:
    """GA4 이벤트 1건 → Staging row (KST · Null · event_date)."""
    event_at = standardize_timestamp(event["event_timestamp"])
    utm_source = standardize_null(
        _get_nested(event, "traffic_source.source"), "utm_source"
    )
    utm_medium = standardize_null(
        _get_nested(event, "traffic_source.medium"), "utm_medium"
    )

    return (
        event["event_id"],
        event["session_id"],
        event.get("user_pseudo_id"),
        event["event_name"],
        utm_source,
        utm_medium,
        standardize_device(_get_nested(event, "device.category")),
        to_kst_string(event_at),
        extract_event_date(event_at),
        raw_id,
    )


def clean_behavior_session(raw_id: str, payload: dict[str, Any]) -> list[tuple]:
    return [clean_behavior_event(raw_id, ev) for ev in payload.get("events", [])]


def _get_nested(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# =============================================================================
# 03. DB 레벨 Upsert (멱등성)
# =============================================================================

ORDER_UPSERT_SQL = """
INSERT INTO stg_ecommerce_orders (
    order_id, user_id, product_id, payment_amount, discount_amount,
    amount_before_fx, currency_code, platform, paid_at,
    order_status, fx_rate, raw_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(order_id) DO UPDATE SET
    user_id          = excluded.user_id,
    product_id       = excluded.product_id,
    payment_amount   = excluded.payment_amount,
    discount_amount  = excluded.discount_amount,
    amount_before_fx = excluded.amount_before_fx,
    currency_code    = excluded.currency_code,
    platform         = excluded.platform,
    paid_at          = excluded.paid_at,
    order_status     = excluded.order_status,
    fx_rate          = excluded.fx_rate,
    raw_id           = excluded.raw_id,
    loaded_at        = datetime('now')
"""

BEHAVIOR_UPSERT_SQL = """
INSERT INTO stg_user_behavior_logs (
    log_id, session_id, user_id, event_name,
    utm_source, utm_medium, device_type, event_at, event_date, raw_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(log_id) DO NOTHING
"""


def upsert_orders(conn: sqlite3.Connection, rows: Sequence[tuple]) -> dict[str, int]:
    """[03] order_id 기반 Upsert — 취소/환불 상태 갱신."""
    deduped = dedupe_by_key(rows, key_index=0)
    before = conn.total_changes
    conn.executemany(ORDER_UPSERT_SQL, deduped)
    affected = conn.total_changes - before
    logger.info("Order Upsert: %d rows submitted, %d DB changes", len(deduped), affected)
    return {"submitted": len(deduped), "changes": affected}


def upsert_behavior_logs(conn: sqlite3.Connection, rows: Sequence[tuple]) -> dict[str, int]:
    """
    [03] log_id 기반 Insert-Ignore — Lookback=0, 불변 로그 멱등 적재.
    [04] event_date 파티션 키 포함.
    """
    deduped = dedupe_by_key(rows, key_index=0)
    before = conn.total_changes
    conn.executemany(BEHAVIOR_UPSERT_SQL, deduped)
    inserted = conn.total_changes - before
    logger.info(
        "Behavior Upsert (ignore dup): %d submitted, %d new inserts",
        len(deduped),
        inserted,
    )
    return {"submitted": len(deduped), "inserted": inserted}


def delete_behavior_partition(conn: sqlite3.Connection, event_date: str) -> int:
    """[04] event_date 파티션 단위 삭제 (재적재 시 — Lookback=0이면 당일만)."""
    cur = conn.execute(
        "DELETE FROM stg_user_behavior_logs WHERE event_date = ?",
        (event_date,),
    )
    return cur.rowcount
