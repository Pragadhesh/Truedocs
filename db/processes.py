"""SQLite-backed process registry per workspace."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from db.database import connect


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["drift_detected"]   = bool(d.get("drift_detected", 0))
    d["trigger_phrase"]   = d.get("trigger_phrase")   or ""
    d["trigger_time"]     = d.get("trigger_time")     or ""
    d["trigger_day"]      = d.get("trigger_day")      or ""
    d["last_observed_at"] = d.get("last_observed_at") or ""
    return d


def get_by_channel(workspace_id: str, channel_id: str) -> dict | None:
    """Return the process registered for a channel, or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM processes WHERE workspace_id = ? AND channel_id = ?",
            (workspace_id, channel_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_by_workspace(workspace_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM processes WHERE workspace_id = ? ORDER BY created_at ASC",
            (workspace_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create(
    workspace_id: str,
    name: str,
    channel_id: str,
    confluence_page_url: str,
    trigger_type: str,
    trigger_phrase: str | None,
    trigger_time: str | None,
    trigger_day: str | None,
    lookback_window: str,
    created_by: str,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "name": name,
        "channel_id": channel_id,
        "confluence_page_url": confluence_page_url,
        "trigger_type": trigger_type,
        "trigger_phrase": trigger_phrase or "",
        "trigger_time": trigger_time or "",
        "trigger_day": trigger_day or "",
        "lookback_window": lookback_window,
        "created_by": created_by,
        "created_at": now,
        "last_observed_at": "",
        "drift_detected": False,
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO processes
                (id, workspace_id, name, channel_id, confluence_page_url,
                 trigger_type, trigger_phrase, trigger_time, trigger_day,
                 lookback_window, created_by, created_at, last_observed_at, drift_detected)
            VALUES
                (:id, :workspace_id, :name, :channel_id, :confluence_page_url,
                 :trigger_type, :trigger_phrase, :trigger_time, :trigger_day,
                 :lookback_window, :created_by, :created_at, :last_observed_at, :drift_detected)
            """,
            {**item, "drift_detected": int(item["drift_detected"])},
        )
    return item


def update(process_id: str, **fields) -> dict | None:
    if not fields:
        return None
    if "drift_detected" in fields:
        fields = {**fields, "drift_detected": int(fields["drift_detected"])}
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    with connect() as conn:
        conn.execute(
            f"UPDATE processes SET {set_clause} WHERE id = :_id",
            {**fields, "_id": process_id},
        )
        row = conn.execute("SELECT * FROM processes WHERE id = ?", (process_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete(process_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM processes WHERE id = ?", (process_id,))
