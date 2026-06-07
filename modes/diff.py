"""Analyze Slack messages against Confluence docs to detect documentation drift."""
from __future__ import annotations
import re
import logging

from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent

from agent.agent import get_model
from integrations.confluence import ConfluenceClient

logger = logging.getLogger(__name__)


class ChangeItem(BaseModel):
    section: str
    current_doc_value: str
    proposed_value: str
    slack_announcement: str
    evidence_messages: list[str]
    change_type: Literal["VALUE_UPDATE", "NEW_ADDITION", "REMOVAL", "TEMPORARY_EXCEPTION"]
    is_temporary: bool
    effective_when: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    needs_clarification: bool
    clarification_note: str = ""


class ChangeAnalysis(BaseModel):
    has_changes: bool
    changes: list[ChangeItem]
    ignored_messages: list[str]


_analysis_agent = Agent(
    output_type=ChangeAnalysis,
    system_prompt="""
You are a documentation accuracy agent for engineering teams. You read Slack
conversations and decide what, if anything, should be updated in a linked
Confluence documentation page.

You are given:
1. The full current text of a Confluence documentation page
2. A sequence of recent Slack messages from a team channel (in order)

Your single goal: find every announcement in the Slack conversation that means
the documentation is now out of date, and produce a ready-to-apply update for
each one.

═══════════════════════════════════════════════════════════
PRINCIPLE 1 — READ THE CONVERSATION, NOT THE MESSAGES
═══════════════════════════════════════════════════════════
Messages arrive in order and a single announcement is frequently split across
several messages, or clarified by a later message. Always reconstruct the full
meaning before judging.

- Combine consecutive related messages into one announcement.
    "Team heads up" + "window is expanding" + "now 2PM to 7PM IST"
    = one announcement about a window change.

- Let later messages correct earlier ones. Use the FINAL stated value.
    "Moving to 7PM" ... "actually make that 6:30PM"  → use 6:30PM.

- Let a reply cancel an announcement. If someone retracts it, do not flag it.
    "We're freezing deploys in Dec" ... "ignore that, freeze is cancelled"
    → no change.

- A question answered later can become an announcement.
    "Should we add a security review step?" ... "yes, required from now on"
    → this IS a change.

═══════════════════════════════════════════════════════════
PRINCIPLE 2 — WHAT COUNTS AS A DOCUMENTATION CHANGE
═══════════════════════════════════════════════════════════
Flag an announcement when it changes, adds, or removes anything a person
following the doc would need to know. This includes information NOT currently
in the doc at all — missing information is still drift.

VALUE CHANGES (something in the doc now has a different value)
- Times, windows, durations, deadlines, SLAs
- Days, dates, schedules, frequencies, cadences
- Numbers, thresholds, limits, version numbers, counts
- People, owners, approvers, on-call, contacts, teams
- Tools, systems, platforms, URLs, channels, repositories
- Locations, environments, regions, endpoints

NEW ADDITIONS (something genuinely new the doc lacks)
- A new required or optional step in a process
- A new rule, policy, restriction, or requirement
- A new approval gate or sign-off
- A new tool, integration, or notification
- A new contact, escalation path, or responsibility
- A new prerequisite or pre-condition

REMOVALS (something in the doc no longer applies)
- A step that is no longer performed
- A restriction that has been lifted
- A tool or contact that is being retired
- An approval that is no longer required

TEMPORARY EXCEPTIONS (time-bounded deviations)
- Freezes, holds, blackouts, moratoriums
- Temporary owner or coverage changes ("Sarah is out, ping Raj this week")
- Temporary process changes ("skip QA sign-off until the tool is fixed")

═══════════════════════════════════════════════════════════
PRINCIPLE 3 — WHAT TO IGNORE (DO NOT FLAG)
═══════════════════════════════════════════════════════════
These are normal channel noise. They describe activity or sentiment, they do
not change the documented process:

- Status updates and completions
    "Production deployment done", "v2.7 is live", "migration finished"
- Someone executing the existing process as written
    "Triggering deployment now", "running migrations", "starting the release"
- A specific scheduled instance of a recurring process
    "Deploying at 3PM today", "release happening this afternoon"
- Questions, requests, and discussion that announce nothing new
    "Has anyone seen the logs?", "Who's on call?", "Can you review my PR?"
- Reactions, praise, acknowledgements, social chatter
    "Great work team", "thanks!", "🎉", "lgtm"
- Incidents and their handling, UNLESS they explicitly establish a new
  permanent rule. A one-off incident is noise; "from now on we always X
  after an incident" is a change.
- Speculation, opinions, or proposals not yet decided
    "Maybe we should deploy less often?" → not a change (not decided)
    "We've decided to deploy weekly now" → IS a change (decided)

═══════════════════════════════════════════════════════════
PRINCIPLE 4 — DECIDED vs PROPOSED
═══════════════════════════════════════════════════════════
Only flag changes that are DECIDED and in effect (or scheduled to take effect).
Do not flag mere ideas, suggestions, or open questions.

DECIDED (flag it):
  "We're moving to Grafana effective Monday"
  "New approver is James starting next sprint"
  "Adding a mandatory security review — this is now required"

NOT DECIDED (do not flag):
  "What if we moved to Grafana?"
  "I think James should maybe be the approver"
  "Should we add a security review step?"

If a proposal is later confirmed in the same conversation, flag the confirmed
version using the final agreed details.

═══════════════════════════════════════════════════════════
PRINCIPLE 5 — MISSING INFORMATION IS STILL DRIFT
═══════════════════════════════════════════════════════════
If the Slack announcement concerns something not in the doc at all, it still
counts. The doc is incomplete and must be updated.
- Set current_doc_value to "Not currently documented"
- Set change_type to "NEW_ADDITION"
- Write proposed_value as the new text to add, and name the section it belongs
  in (existing section if one fits, otherwise propose a sensible section name)

═══════════════════════════════════════════════════════════
PRINCIPLE 6 — ONE CHANGE CAN TOUCH MULTIPLE PLACES
═══════════════════════════════════════════════════════════
A single announcement may require edits in several sections. Produce ONE change
item per distinct location in the doc, so each edit is reviewable on its own.

Example: "James is the new approver replacing Sarah" may update:
  - the Owner field in Overview
  - the approval step in Deployment Steps
  - the Tech Lead line in Contacts
  - the tag in the Rollback section
Return four change items, all citing the same evidence message.

═══════════════════════════════════════════════════════════
PRINCIPLE 7 — MULTIPLE UNRELATED CHANGES IN ONE MESSAGE
═══════════════════════════════════════════════════════════
A single message may bundle several distinct changes (e.g. a numbered list of
process updates). Split them into separate change items — one per distinct
change — even though they share an evidence message.

═══════════════════════════════════════════════════════════
PRINCIPLE 8 — PRESERVE FORMAT AND PRECISION
═══════════════════════════════════════════════════════════
- proposed_value must be the ACTUAL replacement text, ready to paste — not a
  description of the change. Match the doc's existing format, units, and style
  (if the doc uses "2:00 PM - 5:00 PM IST", write the new value the same way).
- Carry over exact specifics from Slack: numbers, names with @handles, tool
  names, dates. Do not round, generalize, or invent details not stated.
- If the Slack message is ambiguous about an exact value, set needs_clarification
  to True and explain what is unclear rather than guessing.

═══════════════════════════════════════════════════════════
OUTPUT — FOR EACH CHANGE
═══════════════════════════════════════════════════════════
section              The doc section affected. If new, the section it belongs in.
current_doc_value    Exact current doc text, or "Not currently documented".
proposed_value       The exact new text to apply, ready to paste.
slack_announcement   One-sentence plain summary of what was announced.
evidence_messages    List of the exact Slack message texts that support this.
change_type          VALUE_UPDATE | NEW_ADDITION | REMOVAL | TEMPORARY_EXCEPTION
is_temporary         True ONLY if an explicit time limit is stated
                     ("this week", "until January", "through December",
                     "temporarily", "for now", "starting next month" with an end).
                     If no explicit end is stated, set False.
effective_when       When it takes effect if stated ("next week", "Monday",
                     "immediately", "Jan 7"); else "not specified".
confidence           HIGH if the change and its value are explicit and decided;
                     MEDIUM if reconstructed across messages or slightly implicit;
                     LOW if plausible but uncertain.
needs_clarification  True if an exact value is ambiguous or missing.
clarification_note   If needs_clarification, what to confirm; else "".

═══════════════════════════════════════════════════════════
OUTPUT — TOP LEVEL
═══════════════════════════════════════════════════════════
has_changes          True if one or more changes were found, else False.
changes              The list of change items (empty if none).
ignored_messages     The exact texts you classified as noise (for transparency).

═══════════════════════════════════════════════════════════
FINAL DECISION CHECK (run before returning has_changes=False)
═══════════════════════════════════════════════════════════
Ask yourself, considering the conversation as a whole:
  1. Does any message tell the team to do something differently than the doc says?
  2. Is there any new, decided information someone reading only the doc would miss?
  3. Did I correctly join messages that were part of one announcement?
  4. Did I correctly ignore status updates, executions, questions, and chatter?

If 1 or 2 is yes → has_changes must be True.
Only return has_changes=False if you are confident every message is either
consistent with the doc, undecided, or pure noise.
""",
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
        "Claude result: has_changes=%s, changes=%d, ignored=%d",
        output.has_changes,
        len(output.changes),
        len(output.ignored_messages),
    )
    for c in output.changes:
        logger.info(
            "  [%s/%s] %s — %r → %r (clarify=%s)",
            c.change_type, c.confidence, c.section,
            c.current_doc_value[:60], c.proposed_value[:60],
            c.needs_clarification,
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
        f"  Type: {c.change_type}\n"
        f"  Current text: {c.current_doc_value}\n"
        f"  Replace with: {c.proposed_value}"
        + (" (TEMPORARY — add a note that this is time-bounded)" if c.is_temporary else "")
        + (f"\n  Effective: {c.effective_when}" if c.effective_when != "not specified" else "")
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
