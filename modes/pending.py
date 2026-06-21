"""Persistent store for drift analyses awaiting user approval.

Backed by SQLite — survives app restarts. Entries expire after 7 days.
Key: '{process_id}|{thread_ts}'
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

from modes.diff import ChangeAnalysis
from db.database import connect

_TTL_DAYS = 7


def put(process_id: str, thread_ts: str, analysis: ChangeAnalysis) -> None:
    key = f"{process_id}|{thread_ts}"
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO pending_analyses (key, analysis_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                analysis_json = excluded.analysis_json,
                created_at    = excluded.created_at
            """,
            (key, analysis.model_dump_json(), now),
        )


def get(process_id: str, thread_ts: str) -> ChangeAnalysis | None:
    _cleanup()
    key = f"{process_id}|{thread_ts}"
    with connect() as conn:
        row = conn.execute(
            "SELECT analysis_json FROM pending_analyses WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return ChangeAnalysis.model_validate_json(row["analysis_json"])


def delete(process_id: str, thread_ts: str) -> None:
    key = f"{process_id}|{thread_ts}"
    with connect() as conn:
        conn.execute("DELETE FROM pending_analyses WHERE key = ?", (key,))


def _cleanup() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_TTL_DAYS)).isoformat()
    with connect() as conn:
        conn.execute("DELETE FROM pending_analyses WHERE created_at < ?", (cutoff,))
