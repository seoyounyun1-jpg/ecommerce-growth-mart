"""
Stage 4 — DB Mart: Staging → Data Mart 갱신
============================================
Human Defined SQL(03_etl_staging_to_mart.sql) 실행.

mart_user_funnel_daily : [run_date - lookback_days, run_date] 구간만 삭제 후
                          재계산하는 증분(윈도우) 재적재 — 구간 밖 과거 행은 보존.
mart_user_rfm_scores    : 매번 전체 재적재 (SQL 파일 내 주석 참고 — Recency가
                          신규 주문 유무와 무관하게 매일 전체 유저에 대해
                          변하므로 윈도우 증분이 불가능한 구조).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from stages.clean_transform import ORDER_LOOKBACK_DAYS

logger = logging.getLogger("ecommerce_pipeline.mart")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ETL_PATH = PROJECT_ROOT / "sql" / "03_etl_staging_to_mart.sql"


def refresh_mart_tables(
    conn: sqlite3.Connection,
    run_date: date,
    lookback_days: int = ORDER_LOOKBACK_DAYS,
) -> dict[str, int]:
    lookback_start = run_date - timedelta(days=lookback_days)

    etl_script = ETL_PATH.read_text(encoding="utf-8")
    etl_script = etl_script.replace("__RUN_DATE__", run_date.isoformat())
    etl_script = etl_script.replace("__LOOKBACK_START__", lookback_start.isoformat())

    conn.executescript(etl_script)
    conn.commit()

    funnel_cnt = conn.execute("SELECT COUNT(*) FROM mart_user_funnel_daily").fetchone()[0]
    rfm_cnt = conn.execute("SELECT COUNT(*) FROM mart_user_rfm_scores").fetchone()[0]
    logger.info(
        "DB Mart refresh [window=%s~%s]: mart_user_funnel_daily=%d, mart_user_rfm_scores=%d",
        lookback_start.isoformat(),
        run_date.isoformat(),
        funnel_cnt,
        rfm_cnt,
    )
    return {"funnel": funnel_cnt, "rfm": rfm_cnt}
