"""
Stage 2 — RAW: 원본 JSON 수집
==============================
API 응답 JSON을 파일(data/raw/) + DB(raw_*) 테이블에 Landing.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("ecommerce_pipeline.raw")

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest_raw_batch(
    conn: sqlite3.Connection,
    batch: dict[str, Any],
    batch_date: date,
) -> dict[str, int]:
    """
    API 패키지 → JSON 파일 저장 + raw_* 테이블 INSERT.
    Returns: {'orders': n, 'logs': n, 'files': n}
    """
    fetched_at = batch.get("fetched_at", datetime.now().isoformat(timespec="seconds"))
    date_str = batch_date.isoformat()
    day_dir = RAW_DIR / date_str

    order_rows: list[tuple] = []
    log_rows: list[tuple] = []
    file_count = 0

    # NAVER orders
    naver_payload = batch.get("naver_orders", [])
    if naver_payload:
        _write_json_file(day_dir / "orders_naver.json", naver_payload)
        file_count += 1
        for item in naver_payload:
            raw_id = str(uuid.uuid4())
            order_rows.append(
                (raw_id, "naver_commerce_api", date_str, json.dumps(item, ensure_ascii=False), fetched_at)
            )

    # Amazon orders
    amazon_payload = batch.get("amazon_orders", [])
    if amazon_payload:
        _write_json_file(day_dir / "orders_amazon.json", amazon_payload)
        file_count += 1
        for item in amazon_payload:
            raw_id = str(uuid.uuid4())
            order_rows.append(
                (raw_id, "amazon_sp_api", date_str, json.dumps(item, ensure_ascii=False), fetched_at)
            )

    # Behavior sessions
    sessions = batch.get("behavior_sessions", [])
    if sessions:
        _write_json_file(day_dir / "behavior_sessions.json", sessions)
        file_count += 1
        for session in sessions:
            raw_id = str(uuid.uuid4())
            log_rows.append(
                (
                    raw_id,
                    "ga4_export",
                    date_str,
                    json.dumps(session, ensure_ascii=False),
                    fetched_at,
                )
            )

    conn.executemany(
        """
        INSERT INTO raw_ecommerce_orders (raw_id, source_api, batch_date, payload_json, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        order_rows,
    )
    conn.executemany(
        """
        INSERT INTO raw_user_behavior_logs (raw_id, source_api, batch_date, payload_json, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        log_rows,
    )

    stats = {"orders": len(order_rows), "logs": len(log_rows), "files": file_count}
    logger.info(
        "RAW ingest [%s]: %d order JSON, %d session JSON, %d files",
        date_str,
        stats["orders"],
        stats["logs"],
        stats["files"],
    )
    return stats
