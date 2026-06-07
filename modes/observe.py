"""Fetch channel messages within a lookback window for analysis."""
from __future__ import annotations
import logging
import time

from slack_sdk import WebClient

logger = logging.getLogger(__name__)

LOOKBACK_SECONDS: dict[str, int] = {
    "1h":  3_600,
    "4h":  3_600 * 4,
    "12h": 3_600 * 12,
    "1d":  86_400,
    "1w":  86_400 * 7,
}

LOOKBACK_LABELS: dict[str, str] = {
    "1h":  "1 hour",
    "4h":  "4 hours",
    "12h": "12 hours",
    "1d":  "1 day",
    "1w":  "1 week",
}


def fetch_channel_messages(
    client: WebClient, channel_id: str, lookback_window: str = "1d"
) -> list[dict]:
    """Return all human messages in the channel within the lookback window, oldest first."""
    seconds = LOOKBACK_SECONDS.get(lookback_window, LOOKBACK_SECONDS["1d"])
    oldest = str(time.time() - seconds)

    all_messages: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"channel": channel_id, "oldest": oldest, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        result = client.conversations_history(**kwargs)
        all_messages.extend(result.get("messages", []))
        meta = result.get("response_metadata", {})
        cursor = meta.get("next_cursor")
        if not cursor:
            break

    # conversations_history returns newest-first; reverse for chronological order
    all_messages.reverse()
    return [m for m in all_messages if not m.get("bot_id") and not m.get("subtype")]


def format_messages_for_prompt(messages: list[dict]) -> str:
    """Format messages into a readable string for Claude."""
    lines = []
    for m in messages:
        user = m.get("user", "unknown")
        text = (m.get("text") or "").strip()
        ts = m.get("ts", "")
        if text:
            lines.append(f"[{user} at {ts}]: {text}")
    return "\n".join(lines) if lines else "(no messages)"
