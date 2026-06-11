"""Fetch channel messages and thread replies within a lookback window."""
from __future__ import annotations
import json
import logging
import time
from pathlib import Path

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
    exclude_phrases:   skip any message whose text CONTAINS one of these
                       phrases (case-insensitive substring match, consistent
                       with trigger detection) — filters all past trigger
                       invocations regardless of surrounding text.
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

    # Normalise trigger phrases once; use substring match (same logic as
    # _check_trigger) so "hey run-truedocs please" is excluded just like
    # an exact "run-truedocs" message.
    _excluded_phrases = [p.lower().strip() for p in (exclude_phrases or []) if p.strip()]

    def _contains_trigger(text: str) -> bool:
        t = text.lower()
        return any(phrase in t for phrase in _excluded_phrases)

    def _keep_top_level(m: dict) -> bool:
        if m.get("bot_id") or m.get("subtype"):
            return False
        if exclude_thread_ts:
            if m.get("ts") == exclude_thread_ts:
                return False
            if m.get("thread_ts") == exclude_thread_ts:
                return False
        if _excluded_phrases and _contains_trigger(m.get("text") or ""):
            return False
        return True

    kept = [m for m in all_messages if _keep_top_level(m)]
    logger.info(
        "Fetched %d top-level messages from %s (window=%s, oldest=%s)",
        len(kept), channel_id, lookback_window, oldest,
    )

    # Fetch replies for threads that have them (Q&A detection).
    # Pass oldest so replies are bounded to the same lookback window and
    # paginated so large threads don't silently truncate at 50 replies.
    result_messages: list[dict] = []
    for m in kept:
        result_messages.append(m)
        if m.get("reply_count", 0) > 0:
            _append_thread_replies(
                client, channel_id, m, result_messages, _excluded_phrases, oldest
            )

    _save_debug_snapshot(channel_id, lookback_window, oldest, result_messages)
    return result_messages


def _save_debug_snapshot(
    channel_id: str,
    lookback_window: str,
    oldest: str,
    messages: list[dict],
) -> None:
    """Write the fetched message list to data/debug_messages.json.

    Overwrites the file on every run so there is always exactly one snapshot
    to inspect.  The file is in data/ which is gitignored.
    """
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    snapshot = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channel_id": channel_id,
        "lookback_window": lookback_window,
        "oldest_ts": oldest,
        "message_count": len(messages),
        "messages": messages,
    }
    path = data_dir / "debug_messages.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Debug snapshot saved → %s (%d messages)", path, len(messages))


def _append_thread_replies(
    client: WebClient,
    channel_id: str,
    parent: dict,
    out: list[dict],
    excluded_phrases: list[str],
    oldest: str,
) -> None:
    """Fetch replies within the lookback window and append to out.

    Paginates conversations_replies with oldest= so only replies inside the
    scan window are returned, and large threads (>50 replies) are fully
    consumed rather than silently truncated.
    """
    parent_text = (parent.get("text") or "").strip()
    all_replies: list[dict] = []
    cursor = None
    try:
        while True:
            kwargs: dict = {
                "channel": channel_id,
                "ts": parent["ts"],
                "oldest": oldest,
                "limit": 50,
            }
            if cursor:
                kwargs["cursor"] = cursor
            result = client.conversations_replies(**kwargs)
            if not result.get("ok"):
                logger.warning(
                    "conversations_replies failed for %s: %s",
                    parent["ts"], result.get("error"),
                )
                return
            all_replies.extend(result.get("messages", []))
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:
        logger.warning("Could not fetch thread replies for %s: %s", parent["ts"], e)
        return

    for reply in all_replies:
        # conversations_replies includes the parent as the first message even
        # with oldest=; skip it by comparing ts.
        if reply.get("ts") == parent["ts"]:
            continue
        if reply.get("bot_id") or reply.get("subtype"):
            continue
        reply_text = (reply.get("text") or "").lower()
        if excluded_phrases and any(phrase in reply_text for phrase in excluded_phrases):
            continue
        enriched = dict(reply)
        enriched["_is_thread_reply"] = True
        enriched["_parent_text"] = parent_text
        out.append(enriched)
