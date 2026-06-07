"""Orchestrate: observe thread → diff vs Confluence → post drift card."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from blockkit.drift_card import build_drift_card
from modes.diff import compare
from modes.observe import extract_steps

logger = logging.getLogger(__name__)


def run_pipeline(
    client: WebClient,
    workspace_id: str,
    channel_id: str,
    thread_ts: str,
    process: dict,
) -> None:
    """Observe thread → diff vs Confluence → post drift card in thread."""
    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":mag: Observing thread for *{process['name']}*...",
        )

        observed = extract_steps(client, channel_id, thread_ts, process["name"])

        creds = credentials.get(workspace_id)
        if not creds:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=":warning: Confluence credentials not configured. Go to App Home → Step 1.",
            )
            return

        drift = compare(observed, process["confluence_page_url"], creds)

        blocks = build_drift_card(process, drift, thread_ts)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"TrueDocs drift analysis for *{process['name']}*",
            blocks=blocks,
        )

        processes.update(
            process["id"],
            drift_detected=drift.has_drift,
            last_observed_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.exception(f"Pipeline failed for process {process['id']}: {e}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: TrueDocs analysis failed: {e}",
        )
