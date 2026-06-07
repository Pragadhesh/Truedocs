"""Diff: compare observed steps against the Confluence doc using Claude."""
from __future__ import annotations
import re
import logging

from pydantic import BaseModel
from pydantic_ai import Agent

from agent.agent import get_model
from integrations.confluence import ConfluenceClient
from modes.observe import ObservedRun

logger = logging.getLogger(__name__)


class DriftResult(BaseModel):
    has_drift: bool
    added_steps: list[str]
    removed_steps: list[str]
    changed_steps: list[str]
    documented_steps: list[str]
    observed_steps: list[str]
    summary: str


_agent = Agent(
    output_type=DriftResult,
    system_prompt=(
        "You compare documented process steps against what was actually observed in a Slack thread.\n\n"
        "Given:\n"
        "- Documented steps: the official process as written in Confluence\n"
        "- Observed steps: what actually happened during this run\n\n"
        "Return:\n"
        "- documented_steps: clean list of steps as written in the doc\n"
        "- observed_steps: clean list of steps that were observed\n"
        "- added_steps: steps observed but NOT in documentation\n"
        "- removed_steps: documented steps that were NOT observed\n"
        "- changed_steps: steps done significantly differently than documented\n"
        "- has_drift: True if any meaningful differences exist\n"
        "- summary: 1-2 sentence summary of the drift situation\n\n"
        "Be pragmatic — minor wording differences are not drift. Focus on actual process differences."
    ),
)


def fetch_confluence_text(page_url: str, creds: dict) -> str | None:
    cf = ConfluenceClient.from_credentials_and_page_url(creds, page_url)
    page = cf.get_page(page_url)
    if not page:
        return None
    body = page.get("body", {}).get("storage", {}).get("value", "")
    text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text).strip() or None


def compare(observed: ObservedRun, page_url: str, creds: dict) -> DriftResult:
    doc_content = fetch_confluence_text(page_url, creds)
    observed_text = "\n".join(f"- {s.description}" for s in observed.steps)

    prompt = (
        f"Documented process (from Confluence):\n{doc_content or '(could not fetch Confluence page)'}\n\n"
        f"Observed steps (from Slack thread):\n{observed_text}\n\n"
        "Compare these and identify drift."
    )

    result = _agent.run_sync(prompt, model=get_model())
    return result.output
