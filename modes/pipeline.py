"""Orchestrate: fetch channel messages → analyze vs Confluence → post drift card."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from blockkit.drift_card import build_drift_card
from modes.diff import analyze_changes, ConfluenceFetchError
from modes.observe import fetch_channel_messages, LOOKBACK_LABELS

logger = logging.getLogger(__name__)


def run_pipeline(
    client: WebClient,
    workspace_id: str,
    channel_id: str,
    thread_ts: str,
    process: dict,
) -> None:
    """Fetch channel messages, analyze against Confluence doc, post drift card in thread."""
    try:
        lookback = process.get("lookback_window", "1d")
        label = LOOKBACK_LABELS.get(lookback, lookback)

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":mag: Scanning the last *{label}* of #{process['name']} messages against the Confluence doc...",
        )

        messages = fetch_channel_messages(
            client, channel_id, lookback, exclude_thread_ts=thread_ts
        )
        logger.info(f"Fetched {len(messages)} messages from {channel_id} (window={lookback}, excluded trigger thread)")

        if not messages:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":information_source: No messages found in the last *{label}*. Nothing to compare.",
            )
            return

        creds = credentials.get(workspace_id)
        if not creds:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Confluence credentials not configured. Go to App Home → Step 1.",
            )
            return

        try:
            analysis = analyze_changes(messages, process["confluence_page_url"], creds)
        except ConfluenceFetchError as e:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":warning: *Could not read Confluence page* — {e}",
            )
            return

        logger.info(f"Analysis complete: has_changes={analysis.has_changes}, {len(analysis.changes)} changes")

        blocks = build_drift_card(process, analysis, thread_ts)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"TrueDocs — *{process['name']}* documentation check",
            blocks=blocks,
        )

        processes.update(
            process["id"],
            drift_detected=analysis.has_changes,
            last_observed_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.exception(f"Pipeline failed for process {process['id']}: {e}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: TrueDocs analysis failed: {e}",
        )
