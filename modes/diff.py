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

CRITICAL: Do NOT create a REMOVAL item just because a documented step was not
mentioned in the Slack messages. Absence of mention is NOT evidence of removal.
A REMOVAL requires an explicit announcement that something is being dropped.
Example of a valid REMOVAL: "We're dropping the Jira update step from our process."
Example of NOT a REMOVAL: The doc has 10 steps but Slack only mentioned 2.

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
PRINCIPLE 8 — QUESTION-AND-ANSWER THREADS
═══════════════════════════════════════════════════════════
Thread replies are included with the format:
  ↳ [reply to "<parent message>"]: <reply text>

If a question was asked in the channel and clearly answered in a reply thread,
treat the ANSWER as documentation drift if it contains useful process knowledge
not already in the doc.

Pattern: someone asks a process question, a team member gives an authoritative answer.
Action: flag as NEW_ADDITION with section "FAQ" (or an existing section if it fits better).
  - current_doc_value: "Not currently documented"
  - proposed_value: "Q: <the question>\nA: <the confirmed answer>"
  - change_type: NEW_ADDITION
  - evidence_messages: include both the question and the answer

Do NOT flag a Q&A thread if:
- The question is just logistics ("who's on call today?")
- The answer is "I don't know" or non-committal
- The topic is already well-documented in the Confluence page
- The answer is opinion rather than authoritative process guidance

═══════════════════════════════════════════════════════════
PRINCIPLE 9 — PRESERVE FORMAT AND PRECISION
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
    system_prompt="""You are a surgical Confluence Storage Format editor.

You will receive the COMPLETE original Confluence Storage Format HTML and a numbered list of
FIND / REPLACE substitutions to apply to it.

YOUR ONLY JOB: copy the original HTML exactly as-is, applying ONLY the specified text substitutions.

STRICT RULES:
1. Start with the full original HTML — do NOT omit, reorder, or restructure any element.
2. For each substitution: find the FIND text inside HTML text nodes and replace it with the REPLACE text.
   If you cannot find the exact FIND text, leave that section unchanged.
3. Make NO other changes — do not reformat, prettify, add sections, or rewrite anything.
4. Do NOT wrap the output in markdown code fences (no ```html or ``` ).
5. Do NOT add <!DOCTYPE>, <html>, <head>, or <body> tags — output only what was in the original.
6. At the very end append exactly: <p><em>(TrueDocs) Last synced DATE_PLACEHOLDER</em></p>
   where DATE_PLACEHOLDER is the date provided in the prompt.
7. Return ONLY the raw Confluence Storage Format HTML — nothing before or after it.""",
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
        if not text:
            continue
        if m.get("_is_thread_reply"):
            parent = (m.get("_parent_text") or "")[:80]
            msg_lines.append(f'  ↳ [reply to "{parent}"]: {text}')
        else:
            msg_lines.append(f"- {text}")
    messages_text = "\n".join(msg_lines) if msg_lines else "(no messages)"

    logger.info(
        "Running drift analysis — doc_text=%d chars, messages=%d",
        len(doc_text), len(msg_lines),
    )
    logger.debug("Messages:\n%s", messages_text)

    prompt = (
        f"Confluence documentation:\n{doc_text}\n\n"
        f"Recent Slack messages (↳ lines are thread replies):\n{messages_text}\n\n"
        "Which messages announce changes or contain resolved Q&A that contradicts or extends the documentation?"
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
    """Apply approved changes to the original Confluence Storage Format HTML.

    Passes explicit FIND/REPLACE pairs to Claude so it makes surgical edits
    instead of regenerating the whole page.
    """
    from datetime import date

    today = date.today().isoformat()

    substitutions = []
    for i, c in enumerate(analysis.changes, 1):
        temp_note = " (temporary — as announced in Slack)" if c.is_temporary else ""
        when_note = f" Effective: {c.effective_when}." if c.effective_when not in ("", "not specified") else ""
        substitutions.append(
            f"Substitution {i} [{c.change_type}]:\n"
            f"  FIND:        {c.current_doc_value}\n"
            f"  REPLACE WITH: {c.proposed_value}{temp_note}{when_note}"
        )

    substitutions_text = "\n\n".join(substitutions)

    prompt = (
        f"ORIGINAL CONFLUENCE PAGE (Storage Format — copy this exactly with only the substitutions below):\n"
        f"{original_html}\n\n"
        f"SUBSTITUTIONS TO APPLY:\n{substitutions_text}\n\n"
        f"TODAY'S DATE (use in the TrueDocs footer): {today}\n\n"
        f"Apply the substitutions to the original HTML and return the result."
    )

    result = _html_agent.run_sync(prompt, model=get_model())
    html = result.output

    # Strip any markdown code fences Claude might have added
    html = re.sub(r"^```[a-z]*\n?", "", html.strip())
    html = re.sub(r"\n?```$", "", html)

    return html.strip()
