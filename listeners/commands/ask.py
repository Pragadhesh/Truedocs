"""Handler for /truedocs-ask — answer questions from the channel's Confluence page."""
from __future__ import annotations
import logging
import threading

from pydantic_ai import Agent
from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from agent.agent import get_model
from modes.diff import fetch_confluence_content
from prompts import ASK_PROMPT

logger = logging.getLogger(__name__)

_ask_agent = Agent(system_prompt=ASK_PROMPT)


def handle_truedocs_ask_command(ack, body: dict, client: WebClient):
    """/truedocs-ask <question> — answer from the registered Confluence page."""
    ack()

    question = (body.get("text") or "").strip()
    channel_id = body["channel_id"]
    workspace_id = body["team_id"]
    user_id = body["user_id"]

    if not question:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=":information_source: Usage: `/truedocs-ask <your question>`",
        )
        return

    proc = processes.get_by_channel(workspace_id, channel_id)
    if not proc:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=(
                ":warning: No documentation page is registered for this channel. "
                "Use `/truedocs` to connect a Confluence page first."
            ),
        )
        return

    result = client.chat_postMessage(
        channel=channel_id,
        text=f":books: <@{user_id}> asked: _{question}_\n:hourglass: Searching *{proc['name']}*...",
    )
    thread_ts = result["ts"]

    threading.Thread(
        target=_run_ask,
        args=(client, channel_id, thread_ts, question, proc, workspace_id),
        daemon=True,
    ).start()


def _run_ask(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    question: str,
    proc: dict,
    workspace_id: str,
) -> None:
    creds = credentials.get(workspace_id)
    if not creds:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":warning: Confluence credentials not configured. Go to App Home to set them up.",
        )
        return

    try:
        _, page_text = fetch_confluence_content(proc["confluence_page_url"], creds)
    except Exception as e:
        logger.exception("Failed to fetch Confluence page: %s", e)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: Could not read the Confluence page: {e}",
        )
        return

    if not page_text:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":warning: The Confluence page appears to be empty or unreadable.",
        )
        return

    prompt = f"Question: {question}\n\nDocumentation — {proc['name']}:\n{page_text}"

    try:
        ai_result = _ask_agent.run_sync(prompt, model=get_model())
        answer = (ai_result.output or "").strip()
    except Exception as e:
        logger.exception("AI ask failed: %s", e)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: AI lookup failed: {e}",
        )
        return

    if answer.upper() == "NOT_FOUND":
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                f":mag: I searched *{proc['name']}* but couldn't find an answer.\n"
                f"The documentation may not cover this yet — run `/truedocs-scan` "
                f"to check if recent Slack messages have the answer."
            ),
        )
    else:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"{answer}\n\n_Source: <{proc['confluence_page_url']}|{proc['name']}>_",
        )
