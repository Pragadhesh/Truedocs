"""Build the Block Kit drift card for the propose step.

Each change item is rendered as a Slack attachment with a coloured left
sidebar (GitHub's file-status palette) so the change type is immediately
visible at a glance.  The header summary lives in top-level blocks.

Callers receive a dict and unpack it:
    client.chat_postMessage(channel=…, text=…, **build_drift_card(…))
"""
from __future__ import annotations
from collections import Counter
from modes.diff import ChangeAnalysis, ChangeItem

_TYPE_LABELS = {
    "VALUE_UPDATE":        "Value Update",
    "NEW_ADDITION":        "New Addition",
    "REMOVAL":             "Removal",
    "TEMPORARY_EXCEPTION": "Temporary Exception",
}

# GitHub file-status colours
_TYPE_COLORS = {
    "VALUE_UPDATE":        "#0969da",  # blue  — modified
    "NEW_ADDITION":        "#2da44e",  # green — added
    "REMOVAL":             "#cf222e",  # red   — deleted
    "TEMPORARY_EXCEPTION": "#9a6700",  # amber — warning
}

_CONFIDENCE_NOTE = {
    "HIGH":   "",
    "MEDIUM": "  •  medium confidence",
    "LOW":    "  •  ⚠️ low confidence",
}


def _is_noop(c: ChangeItem) -> bool:
    """True when the proposed value is identical to what's already in the doc."""
    return (
        c.change_type in ("VALUE_UPDATE", "TEMPORARY_EXCEPTION")
        and (c.current_doc_value or "").strip() == (c.proposed_value or "").strip()
    )


def _diff_text(c: ChangeItem) -> str:
    """Render a ```diff``` block. Slack colours - lines red and + lines green."""
    current  = (c.current_doc_value or "").strip()
    proposed = (c.proposed_value or "").strip()

    def _prefix(text: str, char: str) -> str:
        return "\n".join(f"{char} {line}" for line in text.splitlines()) if text else char

    if c.change_type == "REMOVAL":
        body = _prefix(current, "-")
    elif c.change_type == "NEW_ADDITION":
        body = _prefix(proposed, "+")
    else:
        body = _prefix(current, "-") + "\n" + _prefix(proposed, "+")

    return f"```diff\n{body}\n```"


def _change_attachment(
    real_idx: int,
    display_num: int,
    c: ChangeItem,
    process_id: str,
    thread_ts: str,
) -> dict:
    """Build one coloured attachment block for a single ChangeItem."""
    type_label      = _TYPE_LABELS.get(c.change_type, c.change_type)
    color           = _TYPE_COLORS.get(c.change_type, "#888888")
    confidence_note = _CONFIDENCE_NOTE.get(c.confidence, "")
    temp_note       = "  •  temporary" if c.is_temporary else ""
    when_note       = f"  •  {c.effective_when}" if c.effective_when not in ("", "not specified") else ""

    meta = f"`{type_label}`{temp_note}{confidence_note}{when_note}"
    diff = _diff_text(c)

    att_blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{display_num}. {c.section}*   {meta}\n{diff}",
            },
        }
    ]

    # Evidence — up to 2 messages, truncated to 120 chars each
    if c.evidence_messages:
        snippets = []
        for e in c.evidence_messages[:2]:
            t = e.strip().replace("\n", " ")
            snippets.append(f"_{t[:120]}{'…' if len(t) > 120 else ''}_")
        att_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":speech_balloon: " + "   |   ".join(snippets)}],
        })

    # Clarification warning
    if c.needs_clarification and c.clarification_note:
        att_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":question: *Clarify before applying:* {c.clarification_note}"}],
        })

    # Status badge or action buttons
    if c.status == "approved":
        att_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Applied to Confluence*"}],
        })
    elif c.status == "rejected":
        att_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":no_entry_sign: *Skipped*"}],
        })
    else:
        att_blocks.append({
            "type": "actions",
            "block_id": f"drift_item_{real_idx}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Apply to Confluence"},
                    "action_id": "approve_drift_item",
                    "style": "primary",
                    "value": f"{process_id}|{thread_ts}|{real_idx}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Skip"},
                    "action_id": "reject_drift_item",
                    "style": "danger",
                    "value": f"{process_id}|{thread_ts}|{real_idx}",
                },
            ],
        })

    return {"color": color, "blocks": att_blocks}


def build_drift_card(process: dict, analysis: ChangeAnalysis, thread_ts: str) -> dict:
    """Return {"blocks": […], "attachments": […]} ready to unpack into chat_postMessage / chat_update."""

    def _no_change(msg: str) -> dict:
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"TrueDocs — {process['name']}"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": msg},
                },
            ],
            "attachments": [],
        }

    if not analysis.has_changes:
        return _no_change(":white_check_mark: *Documentation is up to date* — no conflicting announcements found.")

    visible = [(i, c) for i, c in enumerate(analysis.changes) if not _is_noop(c)]

    if not visible:
        return _no_change(":white_check_mark: *Documentation is up to date* — proposed values already match the doc.")

    # Build summary line with per-type counts
    counts = Counter(c.change_type for _, c in visible)
    parts: list[str] = []
    for key, label in [
        ("VALUE_UPDATE",        "value update"),
        ("NEW_ADDITION",        "new addition"),
        ("REMOVAL",             "removal"),
        ("TEMPORARY_EXCEPTION", "temporary exception"),
    ]:
        n = counts[key]
        if n:
            parts.append(f"{n} {label}{'s' if n > 1 else ''}")

    summary = "  •  ".join(parts)
    needs_review = any(c.needs_clarification or c.confidence == "LOW" for _, c in visible)
    review_note = "\n:warning: One or more changes need clarification before applying." if needs_review else ""

    header_blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"TrueDocs — {process['name']}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":mag: *{len(visible)} change{'s' if len(visible) > 1 else ''} detected*"
                    f"   {summary}{review_note}"
                ),
            },
        },
    ]

    attachments = [
        _change_attachment(real_idx, display_num, change, process["id"], thread_ts)
        for display_num, (real_idx, change) in enumerate(visible, 1)
    ]

    return {"blocks": header_blocks, "attachments": attachments}
