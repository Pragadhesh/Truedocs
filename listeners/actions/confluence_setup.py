import logging
from logging import Logger

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from listeners.views.confluence_modal import build_confluence_modal
from listeners.views.app_home_builder import build_app_home_view

logger = logging.getLogger(__name__)


def handle_configure_confluence(ack, body: dict, client: WebClient):
    """Open the Confluence credentials modal, pre-filling any saved values."""
    ack()
    workspace_id = body["team"]["id"]
    creds = credentials.get(workspace_id)
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_confluence_modal(prefill=creds),
    )


def handle_confluence_credentials_submission(
    ack, body: dict, view: dict, client: WebClient, logger: Logger
):
    """Save Confluence email and API token, then refresh App Home."""
    vals = view["state"]["values"]
    conf_email = vals["confluence_email_block"]["confluence_email"]["value"].strip()
    conf_token = vals["confluence_token_block"]["confluence_token"]["value"].strip()

    ack()

    workspace_id = body["team"]["id"]
    user_id = body["user"]["id"]

    try:
        credentials.upsert(
            workspace_id=workspace_id,
            confluence_email=conf_email,
            confluence_token=conf_token,
        )
    except Exception as e:
        logger.exception(f"Failed to save Confluence credentials: {e}")
        return

    _refresh_app_home(client, workspace_id, user_id, logger)


def _refresh_app_home(
    client: WebClient, workspace_id: str, user_id: str, logger: Logger
) -> None:
    try:
        creds = credentials.get(workspace_id)
        procs = processes.list_by_workspace(workspace_id)
    except Exception:
        creds = None
        procs = []
    try:
        client.views_publish(
            user_id=user_id,
            view=build_app_home_view(creds=creds, processes=procs),
        )
    except Exception as e:
        logger.exception(f"Failed to refresh App Home: {e}")
