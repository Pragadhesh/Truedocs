"""Handlers for /truedocs, /truedocs-scan, and /truedocs-ask slash commands."""
import logging
import threading

from slack_sdk import WebClient

import db.processes as processes
from listeners.views.register_modal import build_register_modal
from modes.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def handle_truedocs_command(ack, body: dict, client: WebClient):
    """/truedocs — open the register/manage modal."""
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_register_modal())


def handle_truedocs_scan_command(ack, body: dict, client: WebClient):
    """/truedocs-scan — run drift detection for this channel's registered process."""
    ack()
    channel_id = body["channel_id"]
    workspace_id = body["team_id"]
    user_id = body["user_id"]

    channel_procs = [
        p for p in processes.list_by_workspace(workspace_id)
        if p.get("channel_id") == channel_id
    ]

    if not channel_procs:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=(
                ":warning: No TrueDocs process is registered for this channel. "
                "Use `/truedocs` to set one up."
            ),
        )
        return

    for proc in channel_procs:
        result = client.chat_postMessage(
            channel=channel_id,
            text=f":mag: <@{user_id}> triggered a TrueDocs scan for *{proc['name']}*",
        )
        thread_ts = result["ts"]
        threading.Thread(
            target=run_pipeline,
            args=(client, workspace_id, channel_id, thread_ts, proc),
            daemon=True,
        ).start()
        logger.info("Scan started via /truedocs-scan for process %s in %s", proc["id"], channel_id)
