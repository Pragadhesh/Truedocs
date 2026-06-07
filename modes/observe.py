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
    client: WebClient,
    channel_id: str,
    lookback_window: str = "1d",
    exclude_thread_ts: str | None = None,
) -> list[dict]:
    """Return all human messages in the channel within the lookback window, oldest first.

    exclude_thread_ts: skip the trigger message and any replies in its thread,
    so the 'run-truedocs' invocation itself is not analyzed as content.
    """
    seconds = LOOKBACK_SECONDS.get(lookback_window, LOOKBACK_SECONDS["1d"])
    oldest = str(int(time.time() - seconds))  # integer seconds — float formatting breaks Slack's oldest filter

    # Ensure the bot is in the channel before reading history
    try:
        client.conversations_join(channel=channel_id)
    except Exception as e:
        print(f"[TrueDocs DEBUG] conversations_join: {e}")

    all_messages: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"channel": channel_id, "oldest": oldest, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        result = client.conversations_history(**kwargs)
        ok = result.get("ok")
        error = result.get("error")
        batch = result.get("messages", [])
        print(f"[TrueDocs DEBUG] conversations_history ok={ok} error={error} msgs={len(batch)}")
        if not ok:
            raise RuntimeError(f"conversations.history failed: {error}")
        all_messages.extend(batch)
        meta = result.get("response_metadata", {})
        cursor = meta.get("next_cursor")
        if not cursor:
            break

    # conversations_history returns newest-first; reverse for chronological order
    all_messages.reverse()

    def _keep(m: dict) -> bool:
        if m.get("bot_id") or m.get("subtype"):
            return False
        if exclude_thread_ts:
            # Drop the trigger message itself and any thread children under it
            if m.get("ts") == exclude_thread_ts:
                return False
            if m.get("thread_ts") == exclude_thread_ts:
                return False
        return True

    # ── TEMPORARY DEBUG ──────────────────────────────────────────────────────
    print(f"\n[TrueDocs DEBUG] channel={channel_id} window={lookback_window} oldest={oldest}")
    print(f"[TrueDocs DEBUG] Raw messages from API: {len(all_messages)}")
    for m in all_messages:
        reason = ""
        if m.get("bot_id"):
            reason = "SKIP(bot)"
        elif m.get("subtype"):
            reason = f"SKIP(subtype={m.get('subtype')})"
        elif exclude_thread_ts and m.get("ts") == exclude_thread_ts:
            reason = "SKIP(trigger msg)"
        elif exclude_thread_ts and m.get("thread_ts") == exclude_thread_ts:
            reason = "SKIP(trigger thread)"
        else:
            reason = "KEEP"
        print(f"  {reason} [{m.get('ts')}] user={m.get('user','?')} subtype={m.get('subtype')} bot_id={m.get('bot_id')} text={repr((m.get('text') or '')[:80])}")
    print("[TrueDocs DEBUG] ─────────────────────────────────────────────────\n")
    # ────────────────────────────────────────────────────────────────────────

    return [m for m in all_messages if _keep(m)]


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
