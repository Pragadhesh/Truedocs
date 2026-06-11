"""Build the Block Kit drift card for the propose step."""
from __future__ import annotations
from modes.diff import ChangeAnalysis, ChangeItem

_TYPE_ICON = {
    "VALUE_UPDATE":        ":pencil2:",
    "NEW_ADDITION":        ":new:",
    "REMOVAL":             ":x:",
    "TEMPORARY_EXCEPTION": ":clock3:",
}

_CONFIDENCE_LABEL = {
    "HIGH":   "",
    "MEDIUM": " _(medium confidence)_",
    "LOW":    " _(low confidence — verify before approving)_",
}


def _change_blocks(idx: int, c: ChangeItem, process_id: str, thread_ts: str) -> list[dict]:
    type_icon = _TYPE_ICON.get(c.change_type, ":pencil2:")
    temp_badge = " _(temporary)_" if c.is_temporary else ""
    confidence_note = _CONFIDENCE_LABEL.get(c.confidence, "")
    when = f"\n:calendar: *Effective:* {c.effective_when}" if c.effective_when not in ("", "not specified") else ""

    evidence = "\n".join(f'> _{e}_' for e in c.evidence_messages) if c.evidence_messages else ""

    clarification = ""
    if c.needs_clarification:
        clarification = f"\n:question: *Needs clarification:* {c.clarification_note}"

    text = (
        f"{type_icon} *{idx + 1}. {c.section}*{temp_badge}{confidence_note}\n"
        f":page_facing_up: *Currently says:* {c.current_doc_value}\n"
        f":arrow_right: *Proposed update:* {c.proposed_value}{when}{clarification}"
    )
    if evidence:
        text += f"\n:speech_balloon: *Evidence:*\n{evidence}"

    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    if c.status == "approved":
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Applied to Confluence*"}],
        })
    elif c.status == "rejected":
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": ":no_entry_sign: *Rejected — doc unchanged*"}],
        })
    else:
        blocks.append({
            "type": "actions",
            "block_id": f"drift_item_{idx}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "action_id": "approve_drift_item",
                    "style": "primary",
                    "value": f"{process_id}|{thread_ts}|{idx}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_drift_item",
                    "value": f"{process_id}|{thread_ts}|{idx}",
                },
            ],
        })

    return blocks


def build_drift_card(process: dict, analysis: ChangeAnalysis, thread_ts: str) -> list[dict]:
    if not analysis.has_changes:
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"TrueDocs — {process['name']}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":white_check_mark: *Documentation is up to date* — no conflicting announcements found.",
                },
            },
        ]

    needs_review = any(c.needs_clarification or c.confidence == "LOW" for c in analysis.changes)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"TrueDocs — {process['name']}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":rotating_light: *{len(analysis.changes)} documentation change(s) detected*"
                    + ("\n:warning: Some changes need clarification before approving." if needs_review else "")
                ),
            },
        },
        {"type": "divider"},
    ]

    for idx, change in enumerate(analysis.changes):
        blocks.extend(_change_blocks(idx, change, process["id"], thread_ts))
        blocks.append({"type": "divider"})

    return blocks
