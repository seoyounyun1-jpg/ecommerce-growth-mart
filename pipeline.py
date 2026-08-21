#!/usr/bin/env python3
"""
E-commerce Growth Marketing — 자동 적재 파이프라인
====================================================

아키텍처 (4-Stage)
------------------
  [1] AI GENERATED  api_client.py     — NAVER/Amazon/GA4 API 호출 스크립트
  [2] RAW           raw_ingest.py       — 원본 JSON 수집 (파일 + raw_* 테이블)
  [3] HUMAN DEFINED transform.py       — 컬럼 표준화 · Staging 적재
  [4] DB            mart_refresh.py    — mart_user_funnel_daily · mart_user_rfm_scores

의존성: Python 3.9+ 표준 라이브러리
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence

from stages.api_client import fetch_all_for_date, fetch_order_status_updates
from stages.clean_transform import ORDER_LOOKBACK_DAYS
from stages.mart_refresh import refresh_mart_tables
from stages.raw_ingest import ingest_raw_batch
from stages.transform import apply_staging_from_raw

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "ecommerce.db"
DDL_PATH = PROJECT_ROOT / "sql" / "01_ddl_raw_staging_mart.sql"

MIN_LOG_RECORDS = 1_000
DEFAULT_SESSIONS_PER_DAY = 70  # 7일 × 70세션 ≈ 1,000+ 이벤트

logger = logging.getLogger("ecommerce_pipeline")


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    logger.info("[INIT] Schema from %s", DDL_PATH.name)
    conn.executescript(DDL_PATH.read_text(encoding="utf-8"))
    conn.commit()


def run_pipeline(
    db_path: Path = DEFAULT_DB_PATH,
    target_dates: Sequence[date] | None = None,
    sessions_per_day: int = DEFAULT_SESSIONS_PER_DAY,
    seed: int | None = 42,
) -> None:
    started_at = datetime.now()
    logger.info("=" * 60)
    logger.info("Pipeline START | db=%s", db_path)

    if target_dates is None:
        today = date.today()
        target_dates = [today - timedelta(days=i) for i in range(7)]

    if seed is not None:
        import random
        random.seed(seed)

    conn = connect_db(db_path)
    init_schema(conn)

    total_raw_orders = total_raw_logs = total_stg_orders = total_stg_logs = 0
    total_cancelled = total_refunded = 0

    try:
        # 일별 크론이 순차 실행된 것처럼 오래된 날짜부터 처리 — 이래야 각 날짜의
        # 주문 상태 갱신(취소/환불) 조회가 그 이전 날짜까지의 Staging 상태를 기준으로
        # 정확히 샘플링되고, 같은 배치(batch_date)로 착지해 바로 그날 Staging에 반영된다.
        for target_date in sorted(target_dates):
            date_str = target_date.isoformat()
            logger.info("--- batch_date=%s ---", date_str)

            # Stage 1: AI GENERATED — API 호출 (신규 주문/행동 + 기존 주문 상태 갱신)
            logger.info("[1/4] AI GENERATED — API fetch")
            batch = fetch_all_for_date(target_date, sessions_per_day)

            with conn:
                status_updates = fetch_order_status_updates(conn, target_date, ORDER_LOOKBACK_DAYS)
            batch["naver_orders"] = batch["naver_orders"] + status_updates["naver_orders"]
            batch["amazon_orders"] = batch["amazon_orders"] + status_updates["amazon_orders"]
            total_cancelled += status_updates["cancelled"]
            total_refunded += status_updates["refunded"]
            if status_updates["cancelled"] or status_updates["refunded"]:
                logger.info(
                    "Order status update: cancelled=%d, refunded=%d (Lookback=%dd 재처리 대상)",
                    status_updates["cancelled"],
                    status_updates["refunded"],
                    ORDER_LOOKBACK_DAYS,
                )

            with conn:
                # Stage 2: RAW — 원본 JSON 수집 (append-only Landing)
                # 같은 batch_date를 재실행(예: 크론 재시도)해도 Staging이 이미
                # 참조 중인 과거 raw_id를 삭제하지 않는다 — 삭제하면
                # fk_stg_orders_raw/fk_stg_logs_raw 위반. 중복/최신화는 Staging
                # Upsert(order_id PK, log_id Insert-Ignore)가 책임진다.
                logger.info("[2/4] RAW — JSON landing")
                raw_stats = ingest_raw_batch(conn, batch, target_date)
                total_raw_orders += raw_stats["orders"]
                total_raw_logs += raw_stats["logs"]

            # Stage 3: HUMAN DEFINED — 컬럼 표준화 → Staging
            logger.info("[3/4] HUMAN DEFINED — transform → Staging (lookback)")
            with conn:
                stg_stats = apply_staging_from_raw(conn, target_date)
            total_stg_orders += stg_stats["orders"]
            total_stg_logs += stg_stats["logs"]

        # Stage 4: DB — Mart 갱신 (funnel은 윈도우 증분 재적재)
        # 이번 run이 처리한 실제 기간이 ORDER_LOOKBACK_DAYS보다 길면(예: 장기
        # 백필) 그 기간 전체를 윈도우로 사용 — 그렇지 않으면 lookback 밖 날짜의
        # mart 행이 아예 계산되지 않고 누락된다.
        logger.info("[4/4] DB — mart_user_funnel_daily · mart_user_rfm_scores")
        run_date = max(target_dates)
        backfill_span_days = (max(target_dates) - min(target_dates)).days
        mart_lookback_days = max(ORDER_LOOKBACK_DAYS, backfill_span_days)
        mart_stats = refresh_mart_tables(conn, run_date, lookback_days=mart_lookback_days)

        log_count = conn.execute(
            "SELECT COUNT(*) FROM stg_user_behavior_logs"
        ).fetchone()[0]

        if log_count < MIN_LOG_RECORDS:
            logger.warning(
                "Behavior logs (%d) below minimum %d — increase --sessions-per-day",
                log_count,
                MIN_LOG_RECORDS,
            )

        elapsed = (datetime.now() - started_at).total_seconds()
        logger.info(
            "Pipeline SUCCESS in %.2fs | raw(o=%d,l=%d) stg(o=%d,l=%d) mart(f=%d,r=%d) "
            "status_updates(cancelled=%d,refunded=%d)",
            elapsed,
            total_raw_orders,
            total_raw_logs,
            total_stg_orders,
            total_stg_logs,
            mart_stats["funnel"],
            mart_stats["rfm"],
            total_cancelled,
            total_refunded,
        )
        logger.info("=" * 60)

    except Exception:
        logger.exception("Pipeline FAILED at %s", datetime.now().isoformat(timespec="seconds"))
        raise
    finally:
        conn.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="E-commerce 4-Stage auto-loading pipeline (API→RAW→Staging→Mart)",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=7, help="과거 N일치 배치 (default: 7)")
    parser.add_argument(
        "--sessions-per-day",
        type=int,
        default=DEFAULT_SESSIONS_PER_DAY,
        help=f"일별 세션 수 (default: {DEFAULT_SESSIONS_PER_DAY})",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(verbose=args.verbose)

    today = date.today()
    target_dates = [today - timedelta(days=i) for i in range(args.days)]

    try:
        run_pipeline(
            db_path=args.db,
            target_dates=target_dates,
            sessions_per_day=args.sessions_per_day,
            seed=args.seed,
        )
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
