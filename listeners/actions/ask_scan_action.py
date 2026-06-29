"""Action handler for the 'Run Scan' button on /truedocs-ask answer cards."""
from __future__ import annotations
import logging
import threading
from logging import Logger

from slack_sdk import WebClient

import db.processes as processes
from modes.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def handle_run_scan_from_ask(ack, body: dict, client: WebClient, logger: Logger):
    """Trigger a full pipeline scan when user clicks 'Run Scan' on an ask card."""
    ack()

    process_id = body["actions"][0]["value"]
    workspace_id = body["team"]["id"]
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]

    proc = next(
        (p for p in processes.list_by_workspace(workspace_id) if p["id"] == process_id),
        None,
    )
    if not proc:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=":warning: Process not found — it may have been deleted.",
        )
        return

    result = client.chat_postMessage(
        channel=channel_id,
        text=f":mag: <@{user_id}> triggered a scan — checking recent messages against the documentation...",
    )
    thread_ts = result["ts"]

    threading.Thread(
        target=run_pipeline,
        args=(client, workspace_id, channel_id, thread_ts, proc),
        daemon=True,
    ).start()
