"""Build the Block Kit drift card for the propose step."""
from __future__ import annotations
from modes.diff import DriftResult


def build_drift_card(process: dict, drift: DriftResult, thread_ts: str) -> list[dict]:
    status_icon = ":rotating_light:" if drift.has_drift else ":white_check_mark:"
    status_text = "Drift detected" if drift.has_drift else "No drift — process matches documentation"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"TrueDocs — {process['name']}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{status_icon} *{status_text}*\n{drift.summary}",
            },
        },
        {"type": "divider"},
    ]

    if drift.documented_steps:
        doc_text = "\n".join(f"• {s}" for s in drift.documented_steps)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":page_facing_up: *Documented steps:*\n{doc_text}"},
        })

    if drift.observed_steps:
        obs_text = "\n".join(f"• {s}" for s in drift.observed_steps)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":speech_balloon: *Observed steps:*\n{obs_text}"},
        })

    if not drift.has_drift:
        return blocks

    blocks.append({"type": "divider"})

    if drift.added_steps:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":new: *New steps (not in doc):*\n" + "\n".join(f"• {s}" for s in drift.added_steps),
            },
        })
    if drift.removed_steps:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":x: *Documented steps not observed:*\n" + "\n".join(f"• {s}" for s in drift.removed_steps),
            },
        })
    if drift.changed_steps:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":pencil2: *Changed steps:*\n" + "\n".join(f"• {s}" for s in drift.changed_steps),
            },
        })

    blocks.extend([
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "drift_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Update Confluence"},
                    "action_id": "approve_drift",
                    "style": "primary",
                    "value": f"{process['id']}|{thread_ts}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_drift",
                    "value": f"{process['id']}|{thread_ts}",
                },
            ],
        },
    ])

    return blocks
