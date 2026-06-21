"""PostgreSQL (Supabase) connection pool and schema initialization.

Set DATABASE_URL to your Supabase connection string, e.g.:
  postgresql://postgres.xxxxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres

The public interface is identical to the previous SQLite version — all other
db/ modules call connect() and conn.execute() without knowing the backend.
"""
from __future__ import annotations
import logging
import os
import re
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None

# ── Schema ────────────────────────────────────────────────────────────────────
# Each item is one CREATE TABLE statement executed separately.
_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS credentials (
        workspace_id         TEXT PRIMARY KEY,
        confluence_email     TEXT NOT NULL,
        confluence_token_enc TEXT NOT NULL,
        updated_at           TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processes (
        id                  TEXT PRIMARY KEY,
        workspace_id        TEXT NOT NULL,
        name                TEXT NOT NULL,
        channel_id          TEXT NOT NULL,
        confluence_page_url TEXT NOT NULL,
        trigger_type        TEXT NOT NULL DEFAULT 'manual',
        trigger_phrase      TEXT,
        trigger_time        TEXT,
        trigger_day         TEXT,
        lookback_window     TEXT NOT NULL DEFAULT '1d',
        created_by          TEXT,
        created_at          TEXT NOT NULL,
        last_observed_at    TEXT,
        drift_detected      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_analyses (
        key           TEXT PRIMARY KEY,
        analysis_json TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS installations (
        team_id       TEXT NOT NULL,
        enterprise_id TEXT NOT NULL DEFAULT '',
        bot_token     TEXT,
        bot_user_id   TEXT,
        bot_scopes    TEXT,
        user_id       TEXT,
        user_token    TEXT,
        user_scopes   TEXT,
        installed_at  TEXT NOT NULL,
        PRIMARY KEY (team_id, enterprise_id)
    )
    """,
]


# ── SQL dialect shim ──────────────────────────────────────────────────────────

def _sqlite_to_pg(sql: str) -> str:
    """Convert SQLite placeholder style to psycopg2 style.

    :name  →  %(name)s   (named, must run before ? replacement)
    ?      →  %s         (positional)
    """
    sql = re.sub(r"(?<!:):(\w+)", r"%(\1)s", sql)
    sql = sql.replace("?", "%s")
    return sql


# ── Thin wrappers that keep the sqlite3-style call sites unchanged ────────────

class _Cursor:
    def __init__(self, cur: psycopg2.extensions.cursor) -> None:
        self._cur = cur

    def fetchone(self) -> dict | None:
        row = self._cur.fetchone()
        return dict(row) if row else None

    def fetchall(self) -> list[dict]:
        return [dict(r) for r in self._cur.fetchall()]



class _Connection:
    """Wraps a psycopg2 connection with a sqlite3-compatible execute() API."""

    def __init__(self, raw: psycopg2.extensions.connection) -> None:
        self._raw = raw
        self._cur = raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql: str, params=None) -> _Cursor:
        self._cur.execute(_sqlite_to_pg(sql), params)
        return _Cursor(self._cur)


# ── Pool management ───────────────────────────────────────────────────────────

def _parse_dsn(url: str) -> dict:
    """Parse a postgres:// URL into keyword args for psycopg2.connect().

    Handles passwords that contain special characters (@ # : etc.) by
    using urllib.parse rather than letting psycopg2 parse the raw URL.
    """
    import urllib.parse
    r = urllib.parse.urlparse(url)
    return {
        "host":     r.hostname,
        "port":     r.port or 5432,
        "dbname":   r.path.lstrip("/"),
        "user":     urllib.parse.unquote(r.username or ""),
        "password": urllib.parse.unquote(r.password or ""),
        "sslmode":  "prefer",
    }


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        dsn = (os.environ.get("POOLER_URL") or os.environ.get("DATABASE_URL") or "").strip()
        if not dsn:
            raise RuntimeError(
                "No database URL found. Set POOLER_URL (or DATABASE_URL) in .env:\n"
                "  POOLER_URL=postgresql://postgres.xxxxx:password@aws-0-[region].pooler.supabase.com:6543/postgres"
            )
        kwargs = _parse_dsn(dsn)
        logger.info("Connecting to %s:%s as %s", kwargs["host"], kwargs["port"], kwargs["user"])
        _pool = ThreadedConnectionPool(minconn=1, maxconn=5, **kwargs)
        logger.info("PostgreSQL connection pool ready")
    return _pool


@contextmanager
def connect() -> Generator[_Connection, None, None]:
    """Yield a connection, committing on success or rolling back on error."""
    pool = _get_pool()
    raw = pool.getconn()
    try:
        yield _Connection(raw)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        pool.putconn(raw)


def init_db() -> None:
    """Create all tables (idempotent — uses IF NOT EXISTS)."""
    with connect() as conn:
        for stmt in _DDL:
            conn.execute(stmt)
    logger.info("Database schema initialized")
