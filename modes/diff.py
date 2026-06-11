"""Analyze Slack messages against Confluence docs to detect documentation drift."""
from __future__ import annotations
import re
import logging

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from pydantic_ai import Agent

from agent.agent import get_model
from integrations.confluence import ConfluenceClient
from prompts import DRIFT_ANALYSIS_PROMPT

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)

_ADDRESSABLE_TAGS = ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th")


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
    # Anchor fields — used by the deterministic replacement pipeline.
    anchor_text: str = ""
    context_before: str = ""
    operation: Literal["replace", "insert_after", "delete"] = "replace"
    status: Literal["pending", "approved", "rejected"] = "pending"


class ChangeAnalysis(BaseModel):
    has_changes: bool
    changes: list[ChangeItem]
    ignored_messages: list[str]


_analysis_agent = Agent(
    output_type=ChangeAnalysis,
    system_prompt=DRIFT_ANALYSIS_PROMPT,
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
) -> tuple[ChangeAnalysis, str | None]:
    """Compare Slack messages against Confluence doc.

    Returns (ChangeAnalysis, original_html).  original_html is the raw
    Confluence Storage Format HTML at analysis time; it is None when the
    page could not be fetched (in which case ConfluenceFetchError is raised).
    Callers that need the latest HTML at write time should re-fetch via
    fetch_confluence_content rather than caching this value.
    """
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
    return output, raw_html


# ─────────────────────────────────────────────────────────────────────────────
# Anchor-based deterministic HTML update.
#
# The LLM specifies WHERE to change (anchor_text + context_before) and WHAT
# the new value is (proposed_value).  All addressing and mutation is handled
# by deterministic code — no LLM involvement in producing HTML.
#
# BeautifulSoup is used read-only to locate anchors in the parsed DOM.
# Actual replacements are always applied as string operations on the original
# HTML, so Confluence macros, CDATA sections, and namespace attributes are
# never touched by the BS4 serializer.
# ─────────────────────────────────────────────────────────────────────────────


def _el_text(el) -> str:
    """Normalized visible text of a BeautifulSoup element."""
    return re.sub(r"\s+", " ", el.get_text(separator=" ")).strip()


def find_anchor(soup, change: "ChangeItem") -> "Tag | None":
    """Return the addressable DOM element that contains change.anchor_text.

    Falls back to change.current_doc_value when anchor_text is empty.
    Returns None when the anchor is absent or ambiguous — callers must not
    guess; they should surface the failure or skip the change.
    """
    anchor = (change.anchor_text or change.current_doc_value or "").strip()
    if not anchor or anchor == "Not currently documented":
        return None

    anchor_norm = re.sub(r"\s+", " ", anchor)

    candidates = [
        el for el in soup.find_all(list(_ADDRESSABLE_TAGS))
        if anchor_norm.lower() in re.sub(r"\s+", " ", _el_text(el)).lower()
    ]

    if len(candidates) == 0:
        logger.warning("find_anchor: anchor_lost — %r not found in any addressable element", anchor[:60])
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Multiple matches — disambiguate with context_before.
    ctx = re.sub(r"\s+", " ", (change.context_before or "").strip()).lower()
    if ctx:
        narrowed = []
        for el in candidates:
            prev = el.find_previous(list(_ADDRESSABLE_TAGS))
            prev_text = re.sub(r"\s+", " ", _el_text(prev)).lower() if prev else ""
            if ctx in prev_text:
                narrowed.append(el)
        if len(narrowed) == 1:
            return narrowed[0]

    logger.warning(
        "find_anchor: ambiguous — %d elements contain %r; skipping",
        len(candidates), anchor[:60],
    )
    return None


def generate_updated_page_html(original_html: str, analysis: ChangeAnalysis) -> str:
    """Apply detected changes to the Confluence Storage Format HTML.

    Uses anchor-based lookup (BeautifulSoup, read-only) to verify each
    change location, then applies targeted string operations on the original
    HTML.  The BS4 tree is never serialized, so macros, CDATA sections, and
    namespace attributes are left untouched.
    """
    if not analysis.changes:
        return original_html

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(original_html, "html.parser")

    html = original_html
    applied = 0

    for change in analysis.changes:
        op = change.operation or _infer_operation(change.change_type)

        if change.change_type == "NEW_ADDITION":
            html = _apply_addition(html, change.section, change.proposed_value)
            applied += 1
            continue

        # TEMPORARY_EXCEPTION (and any other type) where the doc has no existing
        # text yet — "Not currently documented" means there's nothing to replace,
        # so insert as new content instead of attempting a replace that will silently
        # fail.
        if (change.current_doc_value or "").strip() == "Not currently documented":
            logger.info(
                "change_type=%s, current_doc_value='Not currently documented' → routing to _apply_addition",
                change.change_type,
            )
            html = _apply_addition(html, change.section, change.proposed_value)
            applied += 1
            continue

        el = find_anchor(soup, change)

        if el is None:
            # Anchor not found or ambiguous — fall back to current_doc_value string ops.
            if op == "replace":
                html = _apply_value_update(html, change.current_doc_value, change.proposed_value)
            elif op == "delete":
                html = _apply_removal(html, change.current_doc_value)
            continue

        # anchor_text was used ONLY for BS4 disambiguation above.
        # The actual replacement always targets current_doc_value → proposed_value
        # so the full scope is correct and no surrounding context is duplicated.
        # anchor_text (a short sub-phrase) is tried only when current_doc_value
        # cannot be found in the raw HTML even with tag-tolerant search.
        if op == "replace":
            updated = _replace_anchor_in_html(
                html, change.current_doc_value, change.proposed_value
            )
            if updated is None:
                # current_doc_value not found — narrow to anchor_text as last resort.
                anchor = (change.anchor_text or "").strip()
                if anchor and anchor != change.current_doc_value:
                    logger.warning(
                        "replace: current_doc_value not found; narrowing to anchor_text %r",
                        anchor[:60],
                    )
                    updated = _replace_anchor_in_html(html, anchor, change.proposed_value)
            if updated is None:
                logger.warning(
                    "replace: could not locate %r in raw HTML — skipping",
                    change.current_doc_value[:60],
                )
            else:
                html = updated
                applied += 1

        elif op == "delete":
            updated = _remove_anchor_from_html(html, change.current_doc_value)
            if updated is None:
                anchor = (change.anchor_text or "").strip()
                if anchor and anchor != change.current_doc_value:
                    updated = _remove_anchor_from_html(html, anchor)
            if updated is None:
                html = _apply_removal(html, change.current_doc_value)
            else:
                html = updated
                applied += 1

    logger.info(
        "Anchor-based update: %d/%d changes applied via anchor, %d → %d chars",
        applied, len(analysis.changes), len(original_html), len(html),
    )
    return html


def _infer_operation(change_type: str) -> str:
    return {
        "VALUE_UPDATE": "replace",
        "TEMPORARY_EXCEPTION": "replace",
        "REMOVAL": "delete",
        "NEW_ADDITION": "insert_after",
    }.get(change_type, "replace")


def _tag_tolerant_search(html: str, text: str):
    """Find text in raw HTML allowing inline tags between words.

    Confluence stores user mentions, links, and formatting as inline tags
    (e.g. <ac:mention>, <a>, <strong>) that break simple string or
    whitespace-only regex matching.  This builds a pattern that allows any
    HTML tag(s) or whitespace to appear between consecutive words, so a
    phrase like "approval from @sarah-chen (tech lead)" is found even when
    the HTML has "<ac:mention ...>@sarah-chen</ac:mention>" in the middle.

    The full matched span (including any embedded tags) is replaced, so the
    caller gets clean output free of dangling inline tags.

    Returns a regex Match or None.
    """
    words = text.split()
    if len(words) < 2:
        return None
    # Between each pair of words allow any mix of whitespace and HTML tags.
    between = r"(?:\s|<[^>]*>)*"
    pattern = between.join(re.escape(w) for w in words)
    return re.search(pattern, html, re.IGNORECASE | re.DOTALL)


def _replace_anchor_in_html(html: str, anchor: str, replacement: str) -> str | None:
    """Replace the first occurrence of anchor text in raw HTML with replacement.

    Returns the updated HTML, or None if the anchor cannot be found.
    Tries three strategies in order: exact match, whitespace-normalised match,
    and tag-tolerant match (handles Confluence macros like <ac:mention>).
    """
    anchor = (anchor or "").strip()
    replacement = (replacement or "").strip()
    if not anchor:
        return None

    if anchor in html:
        return html.replace(anchor, replacement, 1)

    words = anchor.split()
    if len(words) > 1:
        pattern = r"\s+".join(re.escape(w) for w in words)
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return html[: m.start()] + replacement + html[m.end():]

        m = _tag_tolerant_search(html, anchor)
        if m:
            return html[: m.start()] + replacement + html[m.end():]

    return None


def _remove_anchor_from_html(html: str, anchor: str) -> str | None:
    """Remove the first occurrence of anchor text from raw HTML.

    Returns the updated HTML, or None if the anchor cannot be found.
    """
    anchor = (anchor or "").strip()
    if not anchor:
        return None

    if anchor in html:
        return html.replace(anchor, "", 1)

    words = anchor.split()
    if len(words) > 1:
        pattern = r"\s+".join(re.escape(w) for w in words)
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return html[: m.start()] + html[m.end():]

        m = _tag_tolerant_search(html, anchor)
        if m:
            return html[: m.start()] + html[m.end():]

    return None


def _apply_value_update(html: str, old_val: str, new_val: str) -> str:
    old_val = (old_val or "").strip()
    new_val = (new_val or "").strip()
    if not old_val or old_val == "Not currently documented":
        return html

    if old_val in html:
        logger.info("VALUE_UPDATE: exact replace %r → %r", old_val[:80], new_val[:80])
        return html.replace(old_val, new_val, 1)

    words = old_val.split()
    if len(words) > 1:
        pattern = r"\s+".join(re.escape(w) for w in words)
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            logger.info("VALUE_UPDATE: whitespace-normalised replace %r → %r", old_val[:80], new_val[:80])
            return html[: m.start()] + new_val + html[m.end():]

        # Tag-tolerant match for text split across inline Confluence macros.
        m = _tag_tolerant_search(html, old_val)
        if m:
            logger.info("VALUE_UPDATE: tag-tolerant replace %r → %r", old_val[:80], new_val[:80])
            return html[: m.start()] + new_val + html[m.end():]

    logger.warning("VALUE_UPDATE: could not find %r in HTML — skipping", old_val[:80])
    return html


def _apply_removal(html: str, old_val: str) -> str:
    old_val = (old_val or "").strip()
    if not old_val or old_val == "Not currently documented":
        return html

    if old_val in html:
        logger.info("REMOVAL: removed %r", old_val[:80])
        return html.replace(old_val, "", 1)

    words = old_val.split()
    if len(words) > 1:
        pattern = r"\s+".join(re.escape(w) for w in words)
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            logger.info("REMOVAL: whitespace-normalised remove %r", old_val[:80])
            return html[: m.start()] + html[m.end():]

        m = _tag_tolerant_search(html, old_val)
        if m:
            logger.info("REMOVAL: tag-tolerant remove %r", old_val[:80])
            return html[: m.start()] + html[m.end():]

    logger.warning("REMOVAL: could not find %r in HTML — skipping", old_val[:80])
    return html


def _apply_addition(html: str, section: str, proposed_value: str) -> str:
    """Append new content at the END of the named section, or at end of page."""
    proposed_value = (proposed_value or "").strip()
    section = (section or "").strip()

    if section.upper() in ("FAQ", "FREQUENTLY ASKED QUESTIONS"):
        return _apply_faq_entry(html, proposed_value)

    new_block = f"<p>{_escape_html(proposed_value)}</p>"

    if section:
        updated = _insert_at_section_end(html, section, new_block)
        if updated is not None:
            logger.info("NEW_ADDITION: appended to end of section %r", section)
            return updated

    # No matching heading — append at the end of the page body.
    logger.info("NEW_ADDITION: heading %r not found; appending at end", section)
    return html + "\n" + new_block


def _apply_faq_entry(html: str, proposed_value: str) -> str:
    """Add a Q&A entry to the FAQ section, creating the section if needed.

    Appends to the END of an existing FAQ section (not after the heading, which
    would push it above existing entries).  Creates <h2>FAQ</h2> when the page
    has no FAQ heading yet.
    """
    new_block = _build_faq_html(proposed_value)
    heading_re = re.compile(r"<h[1-6][^>]*>.*?</h[1-6]>", re.IGNORECASE | re.DOTALL)
    headings = list(heading_re.finditer(html))

    faq_idx = None
    for i, m in enumerate(headings):
        plain = re.sub(r"<[^>]+>", "", m.group()).strip().lower()
        if "faq" in plain or "frequently asked" in plain:
            faq_idx = i
            break

    if faq_idx is None:
        # No FAQ section — create one at the end of the page.
        logger.info("FAQ: no FAQ section found; creating one at end of page")
        return html + f"\n<h2>FAQ</h2>\n{new_block}"

    # FAQ section exists — insert the new entry just before the next heading
    # (or at the very end of the page if FAQ is the last section).
    if faq_idx + 1 < len(headings):
        insert_pos = headings[faq_idx + 1].start()
    else:
        insert_pos = len(html)

    logger.info("FAQ: appending entry to existing FAQ section")
    return html[:insert_pos] + new_block + "\n" + html[insert_pos:]


def _build_faq_html(proposed_value: str) -> str:
    """Build a <p> FAQ entry from 'Q: ...\nA: ...' text."""
    lines = proposed_value.strip().splitlines()
    q_parts = [l.strip() for l in lines if l.strip().upper().startswith("Q:")]
    a_parts = [l.strip() for l in lines if l.strip().upper().startswith("A:")]
    if q_parts and a_parts:
        q = _escape_html(q_parts[0])
        a = _escape_html(" ".join(a_parts))
        return f"<p><strong>{q}</strong><br />{a}</p>"
    return f"<p>{_escape_html(proposed_value)}</p>"


def _insert_at_section_end(html: str, section_name: str, new_content: str) -> str | None:
    """Find the heading that contains section_name and append new_content at the END of that section.

    "End of section" = just before the next heading, or at the end of the document.
    Inserting here means new items land AFTER all existing content in the section,
    not at the top right after the heading.
    Returns the updated HTML string, or None if no matching heading was found.
    """
    heading_pattern = re.compile(r"<h[1-6][^>]*>.*?</h[1-6]>", re.IGNORECASE | re.DOTALL)
    section_lower = section_name.lower()
    headings = list(heading_pattern.finditer(html))

    for i, m in enumerate(headings):
        heading_plain = re.sub(r"<[^>]+>", "", m.group()).strip().lower()
        if section_lower in heading_plain:
            insert_pos = headings[i + 1].start() if i + 1 < len(headings) else len(html)
            return html[:insert_pos] + "\n" + new_content + "\n" + html[insert_pos:]

    return None


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for text being inserted into Storage Format."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
