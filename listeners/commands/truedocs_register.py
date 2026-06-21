"""Handle the /truedocs slash command and all its subcommands.

Usage:
  /truedocs             — open the register modal (same as /truedocs register)
  /truedocs register    — register or manage a Confluence process
  /truedocs scan        — scan this channel against Confluence and post a drift card
  /truedocs ask <q>     — answer a question from the registered Confluence page
  /truedocs help        — show available subcommands
"""
import logging
import threading

from slack_sdk import WebClient

import db.processes as processes
from listeners.views.register_modal import build_register_modal
from modes.pipeline import run_pipeline

logger = logging.getLogger(__name__)

_HELP_TEXT = (
    "*TrueDocs commands:*\n"
    "• `/truedocs register` — connect a Confluence page to this channel\n"
    "• `/truedocs scan` — check for drift between recent Slack messages and your doc\n"
    "• `/truedocs ask <question>` — get an answer straight from your Confluence page\n"
    "• `/truedocs help` — show this message"
)


def handle_truedocs_command(ack, body: dict, client: WebClient):
    """Route /truedocs <subcommand> to the right handler."""
    text = (body.get("text") or "").strip()
    parts = text.split(None, 1)
    subcommand = parts[0].lower() if parts else "register"
    rest = parts[1] if len(parts) > 1 else ""

    if subcommand in ("register", ""):
        ack()
        client.views_open(trigger_id=body["trigger_id"], view=build_register_modal())

    elif subcommand == "scan":
        _handle_scan(ack, body, client)

    elif subcommand == "ask":
        from listeners.commands.ask import handle_ask_body
        body_with_question = {**body, "text": rest}
        handle_ask_body(ack, body_with_question, client)

    elif subcommand == "help":
        ack()
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text=_HELP_TEXT,
        )

    else:
        ack()
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text=f":warning: Unknown subcommand `{subcommand}`.\n\n{_HELP_TEXT}",
        )


def _handle_scan(ack, body: dict, client: WebClient):
    """Run the drift-detection pipeline for the process registered in this channel."""
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
                "Use `/truedocs register` to set one up."
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
        logger.info("Scan started via /truedocs scan for process %s in %s", proc["id"], channel_id)
