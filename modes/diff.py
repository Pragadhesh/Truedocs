"""Analyze Slack messages against Confluence docs to detect documentation drift."""
from __future__ import annotations
import re
import logging

from pydantic import BaseModel
from pydantic_ai import Agent

from agent.agent import get_model
from integrations.confluence import ConfluenceClient

logger = logging.getLogger(__name__)


class ChangeItem(BaseModel):
    section: str
    current_doc_value: str
    slack_announcement: str
    evidence_message: str
    is_temporary: bool


class ChangeAnalysis(BaseModel):
    has_changes: bool
    changes: list[ChangeItem]
    summary: str


_analysis_agent = Agent(
    output_type=ChangeAnalysis,
    system_prompt=(
        "You are a documentation drift detector for engineering teams.\n\n"
        "You are given:\n"
        "1. The current text of a Confluence documentation page\n"
        "2. Recent Slack messages from the team channel\n\n"
        "Your job: identify every Slack message that announces a CHANGE to something the doc specifies — "
        "any new value, updated time, added step, removed restriction, temporary exception, or new policy "
        "that differs from what the doc currently says.\n\n"
        "Be INCLUSIVE, not conservative. If a message says something that disagrees with a number, "
        "time, day, person, tool, or step in the doc — that is drift. Err on the side of reporting it.\n\n"
        "Common patterns to catch:\n"
        "- A time or window changed (e.g. doc: '2-5 PM', Slack: 'expanding to 7 PM')\n"
        "- A day or schedule changed (e.g. doc: 'Tuesdays only', Slack: 'adding Wednesdays')\n"
        "- A freeze or hold announced (e.g. 'no deployments this week', 'on hold until January')\n"
        "- An owner or contact changed (e.g. 'Sarah is now the tech lead instead of John')\n"
        "- A new required step added (e.g. 'security review now required before prod deploy')\n"
        "- A tool or system changed (e.g. 'we moved from Jira to Linear')\n\n"
        "For EACH change found, return:\n"
        "- section: the section of the doc this affects (e.g. 'Deployment Window')\n"
        "- current_doc_value: EXACTLY what the doc currently says for that section\n"
        "- slack_announcement: clear paraphrase of what the Slack message announced\n"
        "- evidence_message: the exact Slack message text verbatim\n"
        "- is_temporary: True only if the message explicitly signals a time limit "
        "('this week', 'until January', 'temporarily', 'for now')\n\n"
        "Return has_changes=True and populate the changes list if ANY drift is found. "
        "Return has_changes=False only if you are certain that every Slack message is consistent "
        "with or irrelevant to the documented content."
    ),
)

_html_agent = Agent(
    output_type=str,
    system_prompt=(
        "You are a Confluence documentation editor.\n\n"
        "You will receive:\n"
        "1. The current Confluence page body in Confluence Storage Format (HTML-like XML)\n"
        "2. A list of approved changes derived from Slack announcements\n\n"
        "Your job: produce the updated Confluence Storage Format page body that incorporates all the changes.\n\n"
        "Rules:\n"
        "- Keep the existing structure and formatting of the document\n"
        "- Update only the sections that changed\n"
        "- For temporary changes, add a note like '(temporary — as announced in Slack)'\n"
        "- At the end, add: <p><em>(TrueDocs) Last synced {date}</em></p>\n"
        "- Return ONLY the updated Confluence Storage Format HTML, nothing else\n"
        "- Preserve all Confluence macros and special tags\n"
        "- Do NOT add markdown — this is Confluence Storage Format HTML"
    ),
)


def fetch_confluence_content(page_url: str, creds: dict) -> tuple[str, str] | tuple[None, None]:
    """Return (raw_html, plain_text) for a Confluence page, or (None, None) on failure."""
    cf = ConfluenceClient.from_credentials_and_page_url(creds, page_url)
    page = cf.get_page(page_url)
    if not page:
        return None, None
    raw_html = page.get("body", {}).get("storage", {}).get("value", "")
    plain = re.sub(r"<[^>]+>", " ", raw_html)
    plain = re.sub(r"\s+", " ", plain).strip()
    return raw_html, plain or None


class ConfluenceFetchError(Exception):
    """Raised when the Confluence page cannot be fetched."""


def analyze_changes(
    messages: list[dict],
    page_url: str,
    creds: dict,
) -> ChangeAnalysis:
    """Compare Slack messages against Confluence doc, return detected documentation changes."""
    raw_html, doc_text = fetch_confluence_content(page_url, creds)

    if not doc_text:
        raise ConfluenceFetchError(
            "Could not fetch the Confluence page. Check that your credentials are correct "
            "and the page URL is accessible."
        )

    msg_lines = []
    for m in messages:
        text = (m.get("text") or "").strip()
        if text:
            msg_lines.append(f"- {text}")
    messages_text = "\n".join(msg_lines) if msg_lines else "(no messages)"

    logger.info(
        "Running drift analysis — doc_text length=%d, message_count=%d",
        len(doc_text),
        len(msg_lines),
    )
    logger.debug("Doc text (first 500 chars): %s", doc_text[:500])
    logger.debug("Messages sent to Claude:\n%s", messages_text)

    prompt = (
        f"Confluence documentation:\n{doc_text}\n\n"
        f"Recent Slack messages:\n{messages_text}\n\n"
        "Which Slack messages announce changes that contradict or extend the documentation?"
    )

    result = _analysis_agent.run_sync(prompt, model=get_model())
    output = result.output
    logger.info(
        "Claude result: has_changes=%s, changes=%d, summary=%r",
        output.has_changes,
        len(output.changes),
        output.summary,
    )
    return output


def generate_updated_page_html(
    original_html: str,
    analysis: ChangeAnalysis,
) -> str:
    """Use Claude to produce updated Confluence Storage Format HTML incorporating all approved changes."""
    from datetime import date

    changes_text = "\n".join(
        f"- Section: {c.section}\n"
        f"  Current doc says: {c.current_doc_value}\n"
        f"  Should now say: {c.slack_announcement}"
        + (" (TEMPORARY)" if c.is_temporary else "")
        for c in analysis.changes
    )

    today = date.today().isoformat()
    prompt = (
        f"Current Confluence page (Storage Format):\n{original_html}\n\n"
        f"Approved changes to incorporate:\n{changes_text}\n\n"
        f"Today's date: {today}\n\n"
        "Produce the updated Confluence Storage Format page."
    )

    result = _html_agent.run_sync(prompt, model=get_model())
    return result.output
