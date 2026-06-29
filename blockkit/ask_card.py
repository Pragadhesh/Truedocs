"""Block Kit card for /truedocs-ask responses.

Styled consistently with drift_card.py — coloured attachment sidebars,
header block, context rows for source attribution.
"""
from __future__ import annotations
from typing import Literal

from pydantic import BaseModel


class AskResult(BaseModel):
    outcome: Literal["SAME", "CONFLUENCE_ONLY", "SLACK_ONLY", "CONTRADICTION", "NOT_FOUND"]
    answer: str
    confluence_answer: str = ""
    slack_answer: str = ""

_BLUE   = "#0070d2"   # Confluence-only — official doc source
_GREEN  = "#2da44e"   # Same — both sources agree
_ORANGE = "#e67e22"   # Slack-only — found in Slack, not yet in doc
_RED    = "#cf222e"   # Contradiction — sources disagree


def build_ask_card(question: str, result: AskResult, proc: dict) -> dict:
    """Return {"blocks": […], "attachments": […]} ready for chat_postMessage."""
    doc_link = f"<{proc['confluence_page_url']}|{proc['name']}>"

    header_blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "TrueDocs — Ask"},
        },
        {"type": "divider"},
    ]

    if result.outcome == "NOT_FOUND":
        return {
            "blocks": header_blocks + [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            ":mag: *No answer found* in the documentation or recent Slack messages.\n"
                            "Run `/truedocs-scan` to check if there are recent updates not yet captured."
                        ),
                    },
                },
            ],
            "attachments": [],
        }

    if result.outcome == "SAME":
        return {
            "blocks": header_blocks,
            "attachments": [
                {
                    "color": _GREEN,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": result.answer},
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f":white_check_mark: Consistent across {doc_link} and recent Slack discussions",
                                }
                            ],
                        },
                    ],
                }
            ],
        }

    if result.outcome == "CONFLUENCE_ONLY":
        return {
            "blocks": header_blocks,
            "attachments": [
                {
                    "color": _BLUE,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": result.answer},
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f":blue_book: Source: {doc_link}",
                                }
                            ],
                        },
                    ],
                }
            ],
        }

    if result.outcome == "SLACK_ONLY":
        return {
            "blocks": header_blocks,
            "attachments": [
                {
                    "color": _ORANGE,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": result.answer},
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f":left_speech_bubble: Found in Slack — not yet in {doc_link}.",
                                }
                            ],
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Update Documentation"},
                                    "action_id": "run_scan_from_ask",
                                    "style": "primary",
                                    "value": proc["id"],
                                }
                            ],
                        },
                    ],
                }
            ],
        }

    if result.outcome == "CONTRADICTION":
        return {
            "blocks": header_blocks,
            "attachments": [
                {
                    "color": _BLUE,
                    "blocks": [
                        {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": f":blue_book: *From {doc_link}*"}],
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": result.confluence_answer},
                        },
                    ],
                },
                {
                    "color": _RED,
                    "blocks": [
                        {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": ":left_speech_bubble: *From recent Slack*"}],
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": result.slack_answer},
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": ":warning: Sources disagree — scan and update the documentation.",
                                }
                            ],
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Run Truedocs-scan"},
                                    "action_id": "run_scan_from_ask",
                                    "style": "danger",
                                    "value": proc["id"],
                                }
                            ],
                        },
                    ],
                },
            ],
        }

    # Fallback
    return {
        "blocks": header_blocks + [
            {"type": "section", "text": {"type": "mrkdwn", "text": result.answer or "No response."}}
        ],
        "attachments": [],
    }
