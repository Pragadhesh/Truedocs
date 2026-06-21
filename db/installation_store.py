"""SQLite-backed Slack InstallationStore for multi-workspace OAuth."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from slack_sdk.oauth.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation

from db.database import connect

logger = logging.getLogger(__name__)


class SQLiteInstallationStore(InstallationStore):
    def save(self, installation: Installation) -> None:
        team_id = installation.team_id or ""
        enterprise_id = installation.enterprise_id or ""
        now = datetime.now(timezone.utc).isoformat()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO installations
                    (team_id, enterprise_id, bot_token, bot_user_id, bot_scopes,
                     user_id, user_token, user_scopes, installed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, enterprise_id) DO UPDATE SET
                    bot_token    = excluded.bot_token,
                    bot_user_id  = excluded.bot_user_id,
                    bot_scopes   = excluded.bot_scopes,
                    user_id      = excluded.user_id,
                    user_token   = excluded.user_token,
                    user_scopes  = excluded.user_scopes,
                    installed_at = excluded.installed_at
                """,
                (
                    team_id,
                    enterprise_id,
                    installation.bot_token,
                    installation.bot_user_id,
                    ",".join(installation.bot_scopes or []),
                    installation.user_id,
                    installation.user_token,
                    ",".join(installation.user_scopes or []),
                    now,
                ),
            )
        logger.info("Installation saved: team=%s enterprise=%s", team_id, enterprise_id)

    def find_bot(
        self,
        *,
        enterprise_id: str | None,
        team_id: str | None,
        is_enterprise_install: bool = False,
    ) -> Bot | None:
        eid = enterprise_id or ""
        tid = team_id or ""
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM installations WHERE team_id = ? AND enterprise_id = ?",
                (tid, eid),
            ).fetchone()
        if row is None:
            return None
        return Bot(
            app_id=None,
            enterprise_id=eid or None,
            team_id=tid or None,
            bot_token=row["bot_token"],
            bot_user_id=row["bot_user_id"],
            bot_scopes=(row["bot_scopes"] or "").split(","),
            installed_at=datetime.fromisoformat(row["installed_at"]),
        )

    def find_installation(
        self,
        *,
        enterprise_id: str | None,
        team_id: str | None,
        user_id: str | None = None,
        is_enterprise_install: bool = False,
    ) -> Installation | None:
        eid = enterprise_id or ""
        tid = team_id or ""
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM installations WHERE team_id = ? AND enterprise_id = ?",
                (tid, eid),
            ).fetchone()
        if row is None:
            return None
        return Installation(
            app_id=None,
            enterprise_id=eid or None,
            team_id=tid or None,
            bot_token=row["bot_token"],
            bot_user_id=row["bot_user_id"],
            bot_scopes=(row["bot_scopes"] or "").split(","),
            user_id=row["user_id"],
            user_token=row["user_token"],
            user_scopes=(row["user_scopes"] or "").split(","),
            installed_at=datetime.fromisoformat(row["installed_at"]),
        )
