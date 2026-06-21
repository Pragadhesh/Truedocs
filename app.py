"""TrueDocs Slack application entry point.

Two modes (selected automatically by env vars):

  OAuth mode  — set SLACK_CLIENT_ID + SLACK_CLIENT_SECRET + SLACK_SIGNING_SECRET
                A Flask HTTP server on PORT (default 3000) handles:
                  GET /slack/install        → Slack install button redirect
                  GET /slack/oauth_redirect → OAuth callback
                  GET /health               → health check for Railway/Fly.io
                SocketModeHandler handles events/actions via WebSocket.

  Single-workspace mode — set only SLACK_BOT_TOKEN (local dev / simple deploy)
                          No HTTP server; no OAuth flow.
"""
import logging
import os
import threading

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from agent import get_model
from db.database import init_db
from listeners import register_listeners

load_dotenv(dotenv_path=".env", override=False)
init_db()
get_model()  # Fail fast if no AI provider key is configured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_SCOPES = [
    "channels:history",
    "channels:join",
    "channels:read",
    "chat:write",
    "app_mentions:read",
    "im:history",
    "im:write",
]

_client_id     = os.environ.get("SLACK_CLIENT_ID", "")
_client_secret = os.environ.get("SLACK_CLIENT_SECRET", "")
_oauth_mode    = bool(_client_id and _client_secret)

if _oauth_mode:
    from flask import Flask, request as flask_request
    from slack_bolt.adapter.flask import SlackRequestHandler
    from slack_bolt.oauth.oauth_settings import OAuthSettings
    from db.installation_store import SQLiteInstallationStore

    logger.info("Starting in OAuth (multi-workspace) mode")

    oauth_settings = OAuthSettings(
        client_id=_client_id,
        client_secret=_client_secret,
        scopes=_SCOPES,
        installation_store=SQLiteInstallationStore(),
        install_page_rendering_enabled=False,
    )
    app = App(
        signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
        oauth_settings=oauth_settings,
    )
else:
    logger.info("Starting in single-workspace mode (SLACK_BOT_TOKEN)")
    app = App(
        token=os.environ.get("SLACK_BOT_TOKEN"),
        signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
    )

register_listeners(app)


def _start_flask() -> None:
    """Run the OAuth + health-check HTTP server in a background thread."""
    from flask import Flask, request as flask_request
    from slack_bolt.adapter.flask import SlackRequestHandler

    flask_app = Flask(__name__)
    handler = SlackRequestHandler(app)

    @flask_app.route("/slack/install")
    def install():
        return handler.handle(flask_request)

    @flask_app.route("/slack/oauth_redirect")
    def oauth_redirect():
        return handler.handle(flask_request)

    @flask_app.route("/health")
    def health():
        return {"status": "ok"}, 200

    port = int(os.environ.get("PORT", 3000))
    logger.info("Flask OAuth server listening on port %d", port)
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    if _oauth_mode:
        flask_thread = threading.Thread(target=_start_flask, daemon=True)
        flask_thread.start()

    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()
