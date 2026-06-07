"""Approve / Reject handlers for the drift card."""
from __future__ import annotations
import logging
from logging import Logger

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from integrations.confluence import ConfluenceClient
from modes.diff import analyze_changes, generate_updated_page_html, fetch_confluence_content
from modes.observe import fetch_channel_messages

logger = logging.getLogger(__name__)


def handle_approve_drift(ack, body: dict, client: WebClient, logger: Logger):
    """Re-analyze channel messages, generate updated page HTML, push to Confluence."""
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
            text=f":hourglass: <@{user_id}> approved — analyzing changes and updating Confluence...",
        )

        lookback = proc.get("lookback_window", "1d")
        trigger_phrase = proc.get("trigger_phrase") or ""
        messages = fetch_channel_messages(
            client,
            channel_id,
            lookback,
            exclude_phrases=[trigger_phrase] if trigger_phrase else None,
        )

        analysis = analyze_changes(messages, proc["confluence_page_url"], creds)
        if not analysis.has_changes:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":white_check_mark: No documentation changes found on re-analysis. Confluence unchanged.",
            )
            return

        original_html, _ = fetch_confluence_content(proc["confluence_page_url"], creds)
        if not original_html:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Could not fetch Confluence page content.",
            )
            return

        new_html = generate_updated_page_html(original_html, analysis)

        cf = ConfluenceClient.from_credentials_and_page_url(creds, proc["confluence_page_url"])
        success = cf.update_page_with_html(proc["confluence_page_url"], new_html)

        if success:
            change_count = len(analysis.changes)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=(
                    f":white_check_mark: Confluence page updated with {change_count} change(s).\n"
                    f"<{proc['confluence_page_url']}|View updated page>"
                ),
            )
            processes.update(process_id, drift_detected=False)
        else:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Confluence update failed. Check credentials and page permissions.",
            )
    except Exception as e:
        logger.exception(f"Approve drift failed: {e}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: Update failed: {e}",
        )


def handle_reject_drift(ack, body: dict, client: WebClient, logger: Logger):
    """Dismiss the drift card — leave Confluence unchanged."""
    ack()
    raw = body["actions"][0]["value"]
    _, thread_ts = raw.split("|", 1)
    channel_id = body["container"]["channel_id"]
    user_id = body["user"]["id"]

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":no_entry_sign: <@{user_id}> rejected the update — Confluence unchanged.",
    )
