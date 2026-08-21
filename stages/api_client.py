"""
Stage 1 — AI GENERATED: API 호출 스크립트
==========================================
NAVER Commerce API / Amazon SP-API / GA4 Export 를 모의 호출하여
플랫폼별 **비표준 JSON** 응답을 반환합니다.
(실 운영 시 requests + API Key 로 교체)
"""

from __future__ import annotations

import random
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Mock API 설정
# ---------------------------------------------------------------------------
UTM_SOURCES = ("google", "instagram", "naver_blog", "direct")
UTM_MEDIUMS = {
    "google": ("cpc", "organic"),
    "instagram": ("social", "cpc"),
    "naver_blog": ("referral", "organic"),
    "direct": (None,),
}
DEVICES = ("mobile", "desktop", "tablet", "app")
PLATFORMS = ("NAVER", "AMAZON")
PLATFORM_WEIGHTS = (0.65, 0.35)
FX_USD_TO_KRW = 1_350.0

DROP_AFTER_VIEW = 0.30
DROP_AFTER_CART = 0.50
DROP_AFTER_CHECKOUT = 0.20

# ---------------------------------------------------------------------------
# 주문 상태 갱신(취소/환불) — 14일 Lookback Window 존재 이유를 실증하기 위한 모의
# 실 운영에서는 order API를 동일 기간으로 재조회하면 최근 PAID 주문 중 일부가
# CANCELLED/REFUNDED로 바뀐 상태로 돌아오는 것에 해당.
# ---------------------------------------------------------------------------
CANCEL_SAMPLE_RATE = 0.05
CANCEL_STATUSES = ("CANCELLED", "REFUNDED")
CANCEL_STATUS_WEIGHTS = (0.7, 0.3)


def _pick_utm() -> tuple[str | None, str | None]:
    source = random.choice(UTM_SOURCES)
    if source == "direct":
        return None, None
    return source, random.choice(UTM_MEDIUMS[source])


def _advance_time(base: datetime, minutes: int) -> datetime:
    return base + timedelta(minutes=minutes, seconds=random.randint(5, 55))


def _naver_order_payload(user_id: str, product_id: str, paid_at: datetime) -> dict[str, Any]:
    base = round(random.uniform(15_000, 350_000), -2)
    discount = round(base * random.uniform(0, 0.15), -1)
    return {
        "orderNo": f"NV-{uuid.uuid4().hex[:10].upper()}",
        "buyerId": user_id,
        "productNo": product_id,
        "totalPayment": max(base - discount, 0),
        "discountAmt": discount,
        "originAmt": base,
        "currency": "KRW",
        "paidDatetime": paid_at.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _amazon_order_payload(user_id: str, product_id: str, paid_at: datetime) -> dict[str, Any]:
    usd = round(random.uniform(12.0, 280.0), 2)
    discount = round(usd * random.uniform(0, 0.12), 2)
    # Amazon SP-API는 UTC(Z suffix)로 응답 — paid_at(KST 기준 구매 시각)을
    # UTC로 역변환해 담아야 clean_transform.standardize_timestamp의 +9h 변환 후
    # 원래 의도한 KST 시각으로 정확히 복원됨.
    purchase_utc = paid_at - timedelta(hours=9)
    return {
        "AmazonOrderId": f"AMZ-{uuid.uuid4().hex[:10].upper()}",
        "BuyerEmail": user_id,
        "ASIN": product_id,
        "OrderTotal": {"Amount": max(usd - discount, 0), "CurrencyCode": "USD"},
        "PromotionDiscount": {"Amount": discount, "CurrencyCode": "USD"},
        "PurchaseDate": purchase_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _ga4_event_payload(
    session_id: str,
    user_id: str | None,
    event_name: str,
    utm_source: str | None,
    utm_medium: str | None,
    device: str,
    event_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:16]}",
        "session_id": session_id,
        "user_pseudo_id": user_id,
        "event_name": event_name,
        "traffic_source": {"source": utm_source, "medium": utm_medium},
        "device": {"category": device},
        "event_timestamp": event_at.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def fetch_naver_orders(target_date: date, count: int) -> list[dict[str, Any]]:
    """NAVER Commerce API 모의 호출."""
    user_pool = [f"U{idx:05d}" for idx in range(1, 801)]
    payloads = []
    for _ in range(count):
        user_id = random.choice(user_pool)
        product_id = f"P-NV-{random.randint(1000, 9999)}"
        paid_at = datetime.combine(target_date, datetime.min.time()).replace(
            hour=random.randint(8, 22), minute=random.randint(0, 59)
        )
        payloads.append(_naver_order_payload(user_id, product_id, paid_at))
    return payloads


def fetch_amazon_orders(target_date: date, count: int) -> list[dict[str, Any]]:
    """Amazon SP-API 모의 호출."""
    user_pool = [f"U{idx:05d}" for idx in range(1, 801)]
    payloads = []
    for _ in range(count):
        user_id = random.choice(user_pool)
        product_id = f"P-AM-{random.randint(1000, 9999)}"
        paid_at = datetime.combine(target_date, datetime.min.time()).replace(
            hour=random.randint(8, 22), minute=random.randint(0, 59)
        )
        payloads.append(_amazon_order_payload(user_id, product_id, paid_at))
    return payloads


def fetch_behavior_sessions(
    target_date: date,
    session_count: int,
    user_pool: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    GA4 Export / Internal Event API 모의 호출.
    세션 단위 JSON 배열(events[]) 반환 — 퍼널 이탈 확률 반영.
    """
    if user_pool is None:
        user_pool = [f"U{idx:05d}" for idx in range(1, 801)]

    sessions: list[dict[str, Any]] = []

    for _ in range(session_count):
        session_id = f"S-{uuid.uuid4().hex[:12]}"
        user_id = random.choice(user_pool) if random.random() < 0.85 else None
        utm_source, utm_medium = _pick_utm()
        device = random.choice(DEVICES)
        platform = random.choices(PLATFORMS, weights=PLATFORM_WEIGHTS, k=1)[0]
        product_id = f"P-{platform[:2]}-{random.randint(1000, 9999)}"

        event_at = datetime.combine(target_date, datetime.min.time()).replace(
            hour=random.randint(8, 22), minute=random.randint(0, 59)
        )

        events: list[dict[str, Any]] = [
            _ga4_event_payload(session_id, user_id, "view_item", utm_source, utm_medium, device, event_at)
        ]

        if random.random() >= DROP_AFTER_VIEW:
            event_at = _advance_time(event_at, random.randint(1, 8))
            events.append(
                _ga4_event_payload(session_id, user_id, "add_to_cart", utm_source, utm_medium, device, event_at)
            )
            if random.random() >= DROP_AFTER_CART:
                event_at = _advance_time(event_at, random.randint(2, 15))
                events.append(
                    _ga4_event_payload(session_id, user_id, "begin_checkout", utm_source, utm_medium, device, event_at)
                )
                if random.random() >= DROP_AFTER_CHECKOUT:
                    event_at = _advance_time(event_at, random.randint(1, 10))
                    purchase_user = user_id or random.choice(user_pool)
                    events.append(
                        _ga4_event_payload(
                            session_id, purchase_user, "purchase", utm_source, utm_medium, device, event_at
                        )
                    )
                    sessions.append(
                        {
                            "session_id": session_id,
                            "platform_hint": platform,
                            "product_id": product_id,
                            "purchase_user_id": purchase_user,
                            "purchase_at": event_at.isoformat(),
                            "events": events,
                        }
                    )
                    continue

        sessions.append({"session_id": session_id, "platform_hint": platform, "product_id": product_id, "events": events})

    return sessions


def fetch_all_for_date(target_date: date, session_count: int) -> dict[str, Any]:
    """단일 기준일에 대해 모든 API를 호출하고 Raw Zone 적재용 패키지 반환."""
    sessions = fetch_behavior_sessions(target_date, session_count)
    purchase_sessions = [s for s in sessions if any(e["event_name"] == "purchase" for e in s["events"])]

    naver_purchases = [s for s in purchase_sessions if s.get("platform_hint") == "NAVER"]
    amazon_purchases = [s for s in purchase_sessions if s.get("platform_hint") == "AMAZON"]

    return {
        "batch_date": target_date.isoformat(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "naver_orders": [
            _naver_order_payload(
                s["purchase_user_id"],
                s["product_id"],
                datetime.fromisoformat(s["purchase_at"]),
            )
            for s in naver_purchases
        ],
        "amazon_orders": [
            _amazon_order_payload(
                s["purchase_user_id"],
                s["product_id"],
                datetime.fromisoformat(s["purchase_at"]),
            )
            for s in amazon_purchases
        ],
        "behavior_sessions": sessions,
    }


def _naver_status_update_payload(row: sqlite3.Row, new_status: str) -> dict[str, Any]:
    """기존 NAVER 주문의 상태만 변경된 재조회 결과 (금액 필드는 원본 유지)."""
    paid_at = datetime.strptime(row["paid_at"], "%Y-%m-%d %H:%M:%S")
    return {
        "orderNo": row["order_id"],
        "buyerId": row["user_id"],
        "productNo": row["product_id"],
        "totalPayment": row["payment_amount"],
        "discountAmt": row["discount_amount"],
        "originAmt": row["amount_before_fx"],
        "currency": row["currency_code"],
        "paidDatetime": paid_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "orderStatus": new_status,
    }


def _amazon_status_update_payload(row: sqlite3.Row, new_status: str) -> dict[str, Any]:
    """기존 AMAZON 주문의 상태만 변경된 재조회 결과 (UTC PurchaseDate로 역변환)."""
    paid_at = datetime.strptime(row["paid_at"], "%Y-%m-%d %H:%M:%S")
    purchase_utc = paid_at - timedelta(hours=9)
    fx_rate = row["fx_rate"] or 1.0
    usd_net = round(row["payment_amount"] / fx_rate, 2)
    discount_usd = round(row["discount_amount"] / fx_rate, 2)
    return {
        "AmazonOrderId": row["order_id"],
        "BuyerEmail": row["user_id"],
        "ASIN": row["product_id"],
        "OrderTotal": {"Amount": usd_net, "CurrencyCode": row["currency_code"]},
        "PromotionDiscount": {"Amount": discount_usd, "CurrencyCode": row["currency_code"]},
        "PurchaseDate": purchase_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "OrderStatus": new_status,
    }


def fetch_order_status_updates(
    conn: sqlite3.Connection,
    target_date: date,
    lookback_days: int,
    sample_rate: float = CANCEL_SAMPLE_RATE,
) -> dict[str, Any]:
    """
    Stage 1 — AI GENERATED (모의): 주문 API를 Lookback 기간으로 재조회하면
    최근 PAID 주문 중 일부가 CANCELLED/REFUNDED로 바뀌어 돌아온다고 가정.
    이 결과가 14일 Lookback Window(ORDER_LOOKBACK_DAYS)로 재처리되어야 하는 이유.
    """
    window_start = (target_date - timedelta(days=lookback_days)).isoformat()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT order_id, user_id, product_id, payment_amount, discount_amount,
               amount_before_fx, currency_code, platform, paid_at, fx_rate
        FROM stg_ecommerce_orders
        WHERE order_status = 'PAID'
          AND DATE(paid_at) >= ?
          AND DATE(paid_at) < ?
        """,
        (window_start, target_date.isoformat()),
    ).fetchall()

    naver_updates: list[dict[str, Any]] = []
    amazon_updates: list[dict[str, Any]] = []
    cancelled = refunded = 0

    for row in rows:
        if random.random() >= sample_rate:
            continue
        new_status = random.choices(CANCEL_STATUSES, weights=CANCEL_STATUS_WEIGHTS, k=1)[0]
        if new_status == "CANCELLED":
            cancelled += 1
        else:
            refunded += 1

        if row["platform"] == "NAVER":
            naver_updates.append(_naver_status_update_payload(row, new_status))
        else:
            amazon_updates.append(_amazon_status_update_payload(row, new_status))

    return {
        "naver_orders": naver_updates,
        "amazon_orders": amazon_updates,
        "cancelled": cancelled,
        "refunded": refunded,
    }
