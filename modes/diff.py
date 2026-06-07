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
        "You are a documentation drift detector.\n\n"
        "You are given:\n"
        "1. The text of a Confluence documentation page\n"
        "2. A list of recent Slack messages from the team\n\n"
        "Your job: find Slack messages that announce changes, updates, exceptions, or new information "
        "that CONTRADICTS or EXTENDS what the Confluence doc currently says.\n\n"
        "Examples of drift:\n"
        "- Slack says 'deployment window changed to 4-9 PM this week' but doc says '2-7 PM'\n"
        "- Slack says 'deployments are on hold for the next 2 weeks' but doc has no freeze info\n"
        "- Slack says 'we are now using Kubernetes instead of ECS' but doc still mentions ECS\n"
        "- Slack says 'added a new approval step from the security team' but doc doesn't mention it\n\n"
        "For each change found, return:\n"
        "- section: which part of the doc this affects (e.g. 'Deployment Window', 'Prerequisites')\n"
        "- current_doc_value: what the doc currently says about this section\n"
        "- slack_announcement: a clear paraphrase of what the Slack message is announcing\n"
        "- evidence_message: the exact Slack message text that is the source of this change\n"
        "- is_temporary: True if the message clearly indicates this is temporary (e.g. 'this week', 'for December', 'until further notice')\n\n"
        "Only include genuine documentation-relevant changes. Ignore chit-chat, questions, status updates "
        "about ongoing work that matches the doc, or announcements that don't contradict or extend the documentation.\n\n"
        "If no Slack messages announce anything that differs from or extends the documentation, "
        "return has_changes=False with an empty changes list."
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


def analyze_changes(
    messages: list[dict],
    page_url: str,
    creds: dict,
) -> ChangeAnalysis:
    """Compare Slack messages against Confluence doc, return detected documentation changes."""
    _, doc_text = fetch_confluence_content(page_url, creds)

    msg_lines = []
    for m in messages:
        text = (m.get("text") or "").strip()
        if text:
            msg_lines.append(f"- {text}")
    messages_text = "\n".join(msg_lines) if msg_lines else "(no messages)"

    prompt = (
        f"Confluence documentation:\n{doc_text or '(could not fetch Confluence page)'}\n\n"
        f"Recent Slack messages:\n{messages_text}\n\n"
        "Which Slack messages announce changes that contradict or extend the documentation?"
    )

    result = _analysis_agent.run_sync(prompt, model=get_model())
    return result.output


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
