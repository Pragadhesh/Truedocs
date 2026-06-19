"""Build the Block Kit drift card for the propose step.

Each change item is rendered as GitHub PR "Files changed" style:
  red   left-sidebar attachment  = deletion row  (GitHub #ffebe9 background)
  green left-sidebar attachment  = addition row  (GitHub #e6ffec background)

VALUE_UPDATE / TEMPORARY_EXCEPTION produce two stacked attachments (red then
green), giving the same visual rhythm as an inline diff in a GitHub PR.
REMOVAL produces one red attachment; NEW_ADDITION one green attachment.

Callers receive a dict and unpack it:
    client.chat_postMessage(channel=…, text=…, **build_drift_card(…))
"""
from __future__ import annotations
from modes.diff import ChangeAnalysis, ChangeItem

# GitHub PR diff row colours
_RED   = "#cf222e"   # deletion  row — matches GitHub's red   (#ffebe9 bg / #cf222e text)
_GREEN = "#2da44e"   # addition  row — matches GitHub's green (#e6ffec bg / #2da44e text)


def _is_noop(c: ChangeItem) -> bool:
    """True when the proposed value is identical to what's already in the doc."""
    return (
        c.change_type in ("VALUE_UPDATE", "TEMPORARY_EXCEPTION")
        and (c.current_doc_value or "").strip() == (c.proposed_value or "").strip()
    )


def _diff_block(text: str, char: str) -> str:
    """Render changed lines as a ```diff``` block.

    The red/green attachment sidebar provides the row-level colour signal.
    The - / + prefix keeps the diff semantic clear.
    """
    lines = text.splitlines() if text else [""]
    body = "\n".join(f"{char} {line}" for line in lines)
    return f"```diff\n{body}\n```"


def _change_attachments(
    real_idx: int,
    display_num: int,
    c: ChangeItem,
    process_id: str,
    thread_ts: str,
) -> list[dict]:
    """Return 1–2 attachments that together render like a GitHub PR diff row.

    VALUE_UPDATE / TEMPORARY_EXCEPTION:
        [RED   sidebar]  *N. Section*  `type`  …meta
                         ```diff
                         - old value
                         ```
        [GREEN sidebar]  ```diff
                         + new value
                         ```
                         🗣 evidence  |  buttons

    REMOVAL:
        [RED   sidebar]  *N. Section*  `Removal`  …meta
                         ```diff
                         - removed value
                         ```
                         🗣 evidence  |  buttons

    NEW_ADDITION:
        [GREEN sidebar]  *N. Section*  `New Addition`  …meta
                         ```diff
                         + added value
                         ```
                         🗣 evidence  |  buttons
    """
    current  = (c.current_doc_value or "").strip()
    proposed = (c.proposed_value or "").strip()

    # ── Tail blocks — evidence, clarification, status/buttons ─────────────────
    # Always attached to the LAST (green / only) attachment in the group so the
    # action buttons sit below the addition row, matching GitHub's convention.
    tail: list[dict] = []

    if c.evidence_messages:
        snippets = []
        for e in c.evidence_messages[:2]:
            t = e.strip().replace("\n", " ")
            snippets.append(f"_{t[:120]}{'…' if len(t) > 120 else ''}_")
        tail.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "   |   ".join(snippets)}],
        })

    if c.needs_clarification and c.clarification_note:
        tail.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":question: *Clarify before applying:* {c.clarification_note}"}],
        })

    if c.status == "approved":
        tail.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Applied to Confluence*"}],
        })
    elif c.status == "rejected":
        tail.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":no_entry_sign: *Skipped*"}],
        })
    else:
        tail.append({
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

    # ── REMOVAL — single red attachment ───────────────────────────────────────
    if c.change_type == "REMOVAL":
        return [{"color": _RED, "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*{display_num}. {c.section}*\n{_diff_block(current, '-')}"}},
            *tail,
        ]}]

    # ── NEW_ADDITION — single green attachment ─────────────────────────────────
    if c.change_type == "NEW_ADDITION":
        return [{"color": _GREEN, "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*{display_num}. {c.section}*\n{_diff_block(proposed, '+')}"}},
            *tail,
        ]}]

    # ── VALUE_UPDATE / TEMPORARY_EXCEPTION — red row then green row ───────────
    # The two stacked attachments mirror GitHub's inline diff layout:
    #   [red   row]  - old value
    #   [green row]  + new value
    removed_att: dict = {"color": _RED, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*{display_num}. {c.section}*\n{_diff_block(current, '-')}"}},
    ]}
    added_att: dict = {"color": _GREEN, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": _diff_block(proposed, "+")}},
        *tail,
    ]}
    return [removed_att, added_att]


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
                "text": f"*{len(visible)} change{'s' if len(visible) > 1 else ''} detected*{review_note}",
            },
        },
    ]

    attachments: list[dict] = []
    for display_num, (real_idx, change) in enumerate(visible, 1):
        attachments.extend(
            _change_attachments(real_idx, display_num, change, process["id"], thread_ts)
        )

    return {"blocks": header_blocks, "attachments": attachments}
