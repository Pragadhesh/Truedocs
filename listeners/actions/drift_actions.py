"""Approve / Reject handlers for the drift card."""
from __future__ import annotations
import logging
from logging import Logger

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from blockkit.drift_card import build_drift_card
from integrations.confluence import ConfluenceClient
from modes.diff import ChangeAnalysis, fetch_confluence_content, generate_updated_page_html
import modes.pending as pending

logger = logging.getLogger(__name__)


def _get_proc(workspace_id: str, process_id: str) -> dict | None:
    return next(
        (p for p in processes.list_by_workspace(workspace_id) if p["id"] == process_id),
        None,
    )


def handle_approve_drift_item(ack, body: dict, client: WebClient, logger: Logger):
    """Apply a single drift item to Confluence and update the card in-place."""
    ack()
    raw = body["actions"][0]["value"]
    process_id, thread_ts, idx_str = raw.split("|", 2)
    item_idx = int(idx_str)
    workspace_id = body["team"]["id"]
    channel_id = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]
    user_id = body["user"]["id"]

    proc = _get_proc(workspace_id, process_id)
    if not proc:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=":warning: Process not found.")
        return

    creds = credentials.get(workspace_id)
    if not creds:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=":warning: Confluence credentials not configured.")
        return

    analysis = pending.get(process_id, thread_ts)
    if not analysis:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":warning: The pending update has expired (app may have restarted). Run `/truedocs-scan` again.",
        )
        return

    if item_idx >= len(analysis.changes):
        return

    change = analysis.changes[item_idx]
    if change.status != "pending":
        return  # already actioned — stale button click

    try:
        raw_html, _ = fetch_confluence_content(proc["confluence_page_url"], creds)
        if not raw_html:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Could not re-fetch the Confluence page. Check credentials and try again.",
            )
            return

        single = ChangeAnalysis(has_changes=True, changes=[change], ignored_messages=[])
        new_html = generate_updated_page_html(raw_html, single)

        cf = ConfluenceClient.from_credentials_and_page_url(creds, proc["confluence_page_url"])
        success = cf.update_page_with_html(proc["confluence_page_url"], new_html)

        if success:
            analysis.changes[item_idx].status = "approved"
            all_done = all(c.status != "pending" for c in analysis.changes)
            if all_done:
                pending.delete(process_id, thread_ts)
                processes.update(process_id, drift_detected=False)
            else:
                pending.put(process_id, thread_ts, analysis)

            card = build_drift_card(proc, analysis, thread_ts)
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text="TrueDocs",
                **card,
            )
        else:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Confluence update failed. Check credentials and page permissions.",
            )

    except Exception as e:
        logger.exception(f"Approve drift item failed: {e}")
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f":warning: Update failed: {e}")


def handle_reject_drift_item(ack, body: dict, client: WebClient, logger: Logger):
    """Dismiss a single drift item and update the card in-place."""
    ack()
    raw = body["actions"][0]["value"]
    process_id, thread_ts, idx_str = raw.split("|", 2)
    item_idx = int(idx_str)
    workspace_id = body["team"]["id"]
    channel_id = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]

    analysis = pending.get(process_id, thread_ts)
    if not analysis or item_idx >= len(analysis.changes):
        return

    if analysis.changes[item_idx].status != "pending":
        return

    analysis.changes[item_idx].status = "rejected"

    all_done = all(c.status != "pending" for c in analysis.changes)
    if all_done:
        pending.delete(process_id, thread_ts)
    else:
        pending.put(process_id, thread_ts, analysis)

    proc = _get_proc(workspace_id, process_id)
    if proc:
        card = build_drift_card(proc, analysis, thread_ts)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="TrueDocs",
            **card,
        )


def handle_approve_drift(ack, body: dict, client: WebClient, logger: Logger):
    """Legacy handler — kept for cards posted before per-item buttons."""
    ack()
    raw = body["actions"][0]["value"]
    process_id, thread_ts = raw.split("|", 1)
    workspace_id = body["team"]["id"]
    channel_id = body["container"]["channel_id"]
    user_id = body["user"]["id"]

    proc = _get_proc(workspace_id, process_id)
    if not proc:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=":warning: Process not found.")
        return

    creds = credentials.get(workspace_id)
    if not creds:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=":warning: Confluence credentials not configured.")
        return

    analysis = pending.get(process_id, thread_ts)
    if not analysis:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                ":warning: The pending update has expired (app may have restarted). "
                "Please run `/truedocs-scan` again to generate a fresh drift card."
            ),
        )
        return

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":hourglass: <@{user_id}> approved — fetching latest page and applying changes...",
        )

        raw_html, _ = fetch_confluence_content(proc["confluence_page_url"], creds)
        if not raw_html:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Could not re-fetch the Confluence page. Check credentials and try again.",
            )
            return

        new_html = generate_updated_page_html(raw_html, analysis)

        cf = ConfluenceClient.from_credentials_and_page_url(creds, proc["confluence_page_url"])
        success = cf.update_page_with_html(proc["confluence_page_url"], new_html)

        if success:
            pending.delete(process_id, thread_ts)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=(
                    f":white_check_mark: Confluence page updated successfully.\n"
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
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=f":warning: Update failed: {e}")


def handle_reject_drift(ack, body: dict, client: WebClient, logger: Logger):
    """Legacy handler — kept for cards posted before per-item buttons."""
    ack()
    raw = body["actions"][0]["value"]
    process_id, thread_ts = raw.split("|", 1)
    channel_id = body["container"]["channel_id"]
    user_id = body["user"]["id"]

    pending.delete(process_id, thread_ts)

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f":no_entry_sign: <@{user_id}> rejected the update — Confluence unchanged.",
    )
