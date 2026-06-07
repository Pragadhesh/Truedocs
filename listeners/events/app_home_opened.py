import os
from logging import Logger
from urllib.parse import urljoin

from slack_bolt import BoltContext
from slack_sdk import WebClient

from listeners.views.app_home_builder import build_app_home_view


def handle_app_home_opened(client: WebClient, context: BoltContext, logger: Logger):
    """Publish the App Home view when a user opens the app's Home tab."""
    try:
        user_id = context.user_id
        workspace_id = context.team_id

        install_url = None
        is_connected = False
        if os.environ.get("SLACK_CLIENT_ID"):
            if context.user_token:
                is_connected = True
            else:
                redirect_uri = os.environ.get("SLACK_REDIRECT_URI", "")
                install_url = urljoin(redirect_uri, "/slack/install")

        creds = None
        procs = []
        try:
            import db.credentials as credentials
            import db.processes as processes

            creds = credentials.get(workspace_id)
            procs = processes.list_by_workspace(workspace_id)
        except Exception as db_err:
            logger.warning(f"DB unavailable, showing App Home without process data: {db_err}")

        view = build_app_home_view(
            install_url=install_url,
            is_connected=is_connected,
            creds=creds,
            processes=procs,
        )
        client.views_publish(user_id=user_id, view=view)
    except Exception as e:
        logger.exception(f"Failed to publish App Home: {e}")
