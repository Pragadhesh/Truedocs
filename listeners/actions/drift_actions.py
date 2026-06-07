"""Approve / Reject handlers for the drift card."""
from __future__ import annotations
import logging
from logging import Logger

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from integrations.confluence import ConfluenceClient
from modes.observe import extract_steps

logger = logging.getLogger(__name__)


def handle_approve_drift(ack, body: dict, client: WebClient, logger: Logger):
    """Re-observe the thread, then update the Confluence page with observed steps."""
    ack()
    raw = body["actions"][0]["value"]
    process_id, thread_ts = raw.split("|", 1)
    workspace_id = body["team"]["id"]
    channel_id = body["container"]["channel_id"]
    user_id = body["user"]["id"]

    proc = next(
        (p for p in processes.list_by_workspace(workspace_id) if p["id"] == process_id),
        None,
    )
    if not proc:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":warning: Process not found.",
        )
        return

    creds = credentials.get(workspace_id)
    if not creds:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":warning: Confluence credentials not configured.",
        )
        return

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":hourglass: <@{user_id}> approved — updating Confluence...",
        )

        observed = extract_steps(client, channel_id, thread_ts, proc["name"])
        new_steps = [s.description for s in observed.steps]

        cf = ConfluenceClient.from_credentials_and_page_url(creds, proc["confluence_page_url"])
        success = cf.update_page(proc["confluence_page_url"], new_steps)

        if success:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":white_check_mark: Confluence page updated with {len(new_steps)} observed steps.",
            )
            processes.update(process_id, drift_detected=False)
        else:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Confluence update failed. Check your credentials and page permissions.",
            )
    except Exception as e:
        logger.exception(f"Approve drift failed: {e}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: Update failed: {e}",
        )


def handle_reject_drift(ack, body: dict, client: WebClient, logger: Logger):
    """Dismiss the drift card."""
    ack()
    raw = body["actions"][0]["value"]
    _, thread_ts = raw.split("|", 1)
    channel_id = body["container"]["channel_id"]
    user_id = body["user"]["id"]

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":no_entry_sign: <@{user_id}> rejected the drift — Confluence unchanged.",
    )
