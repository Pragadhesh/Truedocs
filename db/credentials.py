"""SQLite-backed Confluence credentials per workspace.

Tokens are encrypted at rest using Fernet (ENCRYPTION_KEY env var).
Falls back to CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN env vars on first access.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from db.crypto import encrypt, decrypt
from db.database import connect


def get(workspace_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT confluence_email, confluence_token_enc FROM credentials WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
    if row:
        return {
            "id": workspace_id,
            "confluence_email": row["confluence_email"],
            "confluence_token": decrypt(row["confluence_token_enc"]),
        }
    # Seed from env vars if present (single-workspace / dev setup)
    email = os.environ.get("CONFLUENCE_EMAIL", "").strip()
    token = os.environ.get("CONFLUENCE_API_TOKEN", "").strip()
    if email and token:
        upsert(workspace_id, email, token)
        return {"id": workspace_id, "confluence_email": email, "confluence_token": token}
    return None


def upsert(workspace_id: str, confluence_email: str, confluence_token: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO credentials (workspace_id, confluence_email, confluence_token_enc, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                confluence_email     = excluded.confluence_email,
                confluence_token_enc = excluded.confluence_token_enc,
                updated_at           = excluded.updated_at
            """,
            (workspace_id, confluence_email, encrypt(confluence_token), now),
        )
