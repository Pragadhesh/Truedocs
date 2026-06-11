"""File-backed process registry per workspace.

Persisted to data/processes.json so registered processes survive app restarts.
"""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_PROCS_FILE = _DATA_DIR / "processes.json"


def _load() -> dict[str, list[dict]]:
    if not _PROCS_FILE.exists():
        return {}
    try:
        return json.loads(_PROCS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(store: dict[str, list[dict]]) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _PROCS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def list_by_workspace(workspace_id: str) -> list[dict]:
    return list(_load().get(workspace_id, []))


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
    store = _load()
    item: dict = {
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
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_observed_at": "",
        "drift_detected": False,
    }
    store.setdefault(workspace_id, []).append(item)
    _save(store)
    return item


def update(process_id: str, **fields) -> dict | None:
    store = _load()
    for procs in store.values():
        for i, p in enumerate(procs):
            if p["id"] == process_id:
                procs[i] = {**p, **fields}
                _save(store)
                return procs[i]
    return None


def delete(process_id: str) -> None:
    store = _load()
    for procs in store.values():
        for i, p in enumerate(procs):
            if p["id"] == process_id:
                procs.pop(i)
                _save(store)
                return
