"""Fetch channel messages and thread replies within a lookback window."""
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
    client: WebClient,
    channel_id: str,
    lookback_window: str = "1d",
    exclude_thread_ts: str | None = None,
    exclude_phrases: list[str] | None = None,
) -> list[dict]:
    """Return top-level messages plus resolved Q&A thread replies, oldest first.

    exclude_thread_ts: skip the current trigger message and its thread.
    exclude_phrases:   skip any message whose text exactly matches one of these
                       (case-insensitive) — filters all past trigger invocations.
    Each reply dict has _is_thread_reply=True and _parent_text set.
    """
    seconds = LOOKBACK_SECONDS.get(lookback_window, LOOKBACK_SECONDS["1d"])
    oldest = str(int(time.time() - seconds))

    try:
        client.conversations_join(channel=channel_id)
    except Exception:
        pass

    all_messages: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"channel": channel_id, "oldest": oldest, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        result = client.conversations_history(**kwargs)
        if not result.get("ok"):
            raise RuntimeError(f"conversations.history failed: {result.get('error')}")
        all_messages.extend(result.get("messages", []))
        meta = result.get("response_metadata", {})
        cursor = meta.get("next_cursor")
        if not cursor:
            break

    # newest-first → oldest-first
    all_messages.reverse()

    _excluded_lower = [p.lower().strip() for p in (exclude_phrases or [])]

    def _keep_top_level(m: dict) -> bool:
        if m.get("bot_id") or m.get("subtype"):
            return False
        if exclude_thread_ts:
            if m.get("ts") == exclude_thread_ts:
                return False
            if m.get("thread_ts") == exclude_thread_ts:
                return False
        if _excluded_lower:
            if (m.get("text") or "").lower().strip() in _excluded_lower:
                return False
        return True

    kept = [m for m in all_messages if _keep_top_level(m)]
    logger.info("Fetched %d top-level messages from %s (window=%s)", len(kept), channel_id, lookback_window)

    # Fetch replies for threads that have them (Q&A detection)
    result_messages: list[dict] = []
    for m in kept:
        result_messages.append(m)
        if m.get("reply_count", 0) > 0:
            _append_thread_replies(client, channel_id, m, result_messages, _excluded_lower)

    return result_messages


def _append_thread_replies(
    client: WebClient,
    channel_id: str,
    parent: dict,
    out: list[dict],
    excluded_lower: list[str],
) -> None:
    """Fetch replies for a thread and append them to out (excluding bots and trigger phrases)."""
    try:
        result = client.conversations_replies(
            channel=channel_id,
            ts=parent["ts"],
            limit=50,
        )
        replies = result.get("messages", [])
    except Exception as e:
        logger.warning("Could not fetch thread replies for %s: %s", parent["ts"], e)
        return

    parent_text = (parent.get("text") or "").strip()
    for reply in replies[1:]:  # skip index 0 — it's the parent message
        if reply.get("bot_id") or reply.get("subtype"):
            continue
        text_lower = (reply.get("text") or "").lower().strip()
        if text_lower in excluded_lower:
            continue
        enriched = dict(reply)
        enriched["_is_thread_reply"] = True
        enriched["_parent_text"] = parent_text
        out.append(enriched)
