"""Handler for /truedocs-ask — answer questions using Slack RTS + Confluence in parallel."""
from __future__ import annotations
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic_ai import Agent
from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from agent.agent import get_model
from blockkit.ask_card import AskResult, build_ask_card
from modes.diff import fetch_confluence_content
from prompts import ASK_PROMPT

logger = logging.getLogger(__name__)

_SLACK_LOOKBACK_SECONDS = 7 * 24 * 3600  # 7 days

_ask_agent = Agent(output_type=AskResult, system_prompt=ASK_PROMPT)


def _relative_time(ts_str: str) -> str:
    """Convert a Slack timestamp to a human-readable relative time label."""
    try:
        diff = time.time() - float(ts_str)
        if diff < 3600:
            return f"{max(1, int(diff / 60))}m ago"
        if diff < 86400:
            return f"{int(diff / 3600)}h ago"
        return f"{int(diff / 86400)}d ago"
    except Exception:
        return ""


def _fetch_recent_messages(client: WebClient, channel_id: str) -> list[dict]:
    """Fetch recent human messages newest-first from the channel using the bot token."""
    try:
        client.conversations_join(channel=channel_id)
    except Exception:
        pass
    oldest = str(int(time.time() - _SLACK_LOOKBACK_SECONDS))
    try:
        result = client.conversations_history(channel=channel_id, oldest=oldest, limit=200)
        messages = result.get("messages", [])
        # conversations.history returns newest-first; keep that order so [:50]
        # gives the most recent messages.
        return [
            m for m in messages
            if not m.get("bot_id") and not m.get("subtype") and (m.get("text") or "").strip()
        ]
    except Exception as e:
        logger.warning("Failed to fetch channel messages: %s", e)
        return []


def handle_truedocs_ask_command(ack, body: dict, client: WebClient):
    """/truedocs-ask <question> — answer from Confluence + Slack Real-Time Search."""
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

    post = client.chat_postMessage(
        channel=channel_id,
        text=f":books: <@{user_id}> asked: _{question}_\n:mag: Searching documentation and Slack...",
    )
    thread_ts = post["ts"]

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

    # Parallel fetch: Confluence doc + recent channel messages
    with ThreadPoolExecutor(max_workers=2) as executor:
        confluence_future = executor.submit(fetch_confluence_content, proc["confluence_page_url"], creds)
        slack_future = executor.submit(_fetch_recent_messages, client, channel_id)

    try:
        _, page_text = confluence_future.result()
    except Exception as e:
        logger.exception("Failed to fetch Confluence page: %s", e)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: Could not read the Confluence page: {e}",
        )
        return

    slack_messages = slack_future.result()

    slack_text = ""
    if slack_messages:
        lines = []
        for m in slack_messages[:50]:
            text = (m.get("text") or "").strip()
            if text:
                age = _relative_time(m.get("ts", ""))
                prefix = f"[{age}] " if age else ""
                lines.append(f"- {prefix}{text}")
        slack_text = "\n".join(lines)

    prompt = (
        f"Question: {question}\n\n"
        f"Confluence documentation ({proc['name']}):\n{page_text or '(empty)'}\n\n"
        f"Recent Slack messages from the channel (Real-Time Search results):\n{slack_text or '(no results)'}"
    )

    try:
        ai_result = _ask_agent.run_sync(prompt, model=get_model())
        ask_result = ai_result.output
    except Exception as e:
        logger.exception("AI ask failed: %s", e)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: AI lookup failed: {e}",
        )
        return

    card = build_ask_card(question, ask_result, proc)
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f"TrueDocs — answer for: {question}",
        **card,
    )
