"""Build the Block Kit drift card for the propose step."""
from __future__ import annotations
from modes.diff import ChangeAnalysis


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
                    "text": f":white_check_mark: *Documentation is up to date*\n{analysis.summary}",
                },
            },
        ]

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
                    f":rotating_light: *Documentation drift detected* — "
                    f"{len(analysis.changes)} change(s) found\n{analysis.summary}"
                ),
            },
        },
        {"type": "divider"},
    ]

    for i, change in enumerate(analysis.changes, 1):
        temp_badge = " _(temporary)_" if change.is_temporary else ""
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{i}. {change.section}*{temp_badge}\n"
                    f":page_facing_up: *Doc says:* {change.current_doc_value}\n"
                    f":mega: *Slack says:* {change.slack_announcement}\n"
                    f":speech_balloon: _\"{change.evidence_message}\"_"
                ),
            },
        })

    blocks.extend([
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":point_up: Approve to let TrueDocs update the Confluence page automatically. "
                    "Reject to leave the doc unchanged."
                ),
            },
        },
        {
            "type": "actions",
            "block_id": "drift_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Approve & Update Confluence"},
                    "action_id": "approve_drift",
                    "style": "primary",
                    "value": f"{process['id']}|{thread_ts}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject — Keep Doc As Is"},
                    "action_id": "reject_drift",
                    "value": f"{process['id']}|{thread_ts}",
                },
            ],
        },
    ])

    return blocks
