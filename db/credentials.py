"""File-backed Confluence credentials per workspace.

Persisted to data/credentials.json so they survive app restarts.
Falls back to CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN env vars on first access.
"""

from __future__ import annotations
import json
import os
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_CREDS_FILE = _DATA_DIR / "credentials.json"


def _load() -> dict[str, dict]:
    if not _CREDS_FILE.exists():
        return {}
    try:
        return json.loads(_CREDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(store: dict[str, dict]) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _CREDS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def get(workspace_id: str) -> dict | None:
    store = _load()
    if workspace_id not in store:
        seeded = _from_env(workspace_id)
        if seeded:
            store[workspace_id] = seeded
            _save(store)
    return store.get(workspace_id)


def upsert(
    workspace_id: str,
    confluence_email: str,
    confluence_token: str,
) -> None:
    store = _load()
    store[workspace_id] = {
        "id": workspace_id,
        "confluence_email": confluence_email,
        "confluence_token": confluence_token,
    }
    _save(store)


def _from_env(workspace_id: str) -> dict | None:
    email = os.environ.get("CONFLUENCE_EMAIL", "").strip()
    token = os.environ.get("CONFLUENCE_API_TOKEN", "").strip()
    if email and token:
        return {
            "id": workspace_id,
            "confluence_email": email,
            "confluence_token": token,
        }
    return None
