# TrueDocs — Your Confluence Docs, Always Current

---

## Inspiration

Every developer has been there.

You're on-call, something breaks at 11 PM, and you pull up the runbook. It says the deployment window is 2–7 PM. But you *vaguely* remember someone saying in Slack last week that it changed. So you start scrolling through `#deployments`, hunting for that message, trying to figure out if it's still the case or if that was a one-time thing. By the time you find the answer, fifteen minutes have passed.

I've lived this exact situation more times than I can count — and not just for deployment windows. On-call handoff times, rollback procedures, escalation contacts, environment URLs... all of it slowly drifts out of sync with the actual team docs while the *real* knowledge quietly accumulates in Slack threads that nobody goes back to update. The same goes for solved issues and FAQs — someone figures out a tricky setup problem, posts the fix in a thread, gets a few 👍s, and that's where it stays. The next person with the same problem either finds it by luck or spends an hour solving it again from scratch.

The documentation doesn't go bad all at once. It happens one announcement at a time. Someone posts *"heads up, we're freezing deploys for December"* in the channel. Nobody updates the runbook. Six months later, a new engineer follows the doc and wonders why they can't push anything.

I built TrueDocs because I wanted the docs to update themselves — or at least ask me to update them, at the right moment, with the right information already filled in.

---

## What it does

TrueDocs is a Slack agent that watches your channels for announcements that contradict or extend what's written in your Confluence documentation, then proposes targeted updates — with one-click approval to apply them live.

### The two commands that matter

**`/truedocs-scan`**

Run this in any registered Slack channel. TrueDocs looks back over the configured time window (1 hour to 1 week), reads all the human messages, and compares them against the linked Confluence page. If anything changed — a value, a step, a deadline, a contact — it posts a drift card right in the channel.

The drift card looks like a code review diff. You see exactly what the doc currently says, what the Slack announcement suggests it should say, and which specific message triggered the flag. Then you click **Apply to Confluence** or **Skip** on each item, one by one. No bulk updates. You stay in control.

**`/truedocs-ask`**

Ask any question about a linked Confluence page directly in Slack. Instead of opening a browser, navigating to the page, and Ctrl+F-ing your way through it, you just type the question. TrueDocs pulls the answer from the live page and replies in the thread — sourced directly from the doc, not from its own memory.

### What a drift card looks like

```
TrueDocs — On-Call Rotation Runbook
────────────────────────────────────────────────────────
🔵  Deployment Window                      VALUE UPDATE
    Was: 2:00 PM – 7:00 PM IST
    Now: 4:00 PM – 9:00 PM IST
    Evidence: "deployment window moving to 4–9 PM this week due to rotation"
    [ Apply to Confluence ]   [ Skip ]

🟡  December Deploy Freeze            TEMPORARY EXCEPTION
    Adding: All deployments are on hold through December 31.
    Evidence: "freezing deploys for the whole month, resume Jan 2"
    [ Apply to Confluence ]   [ Skip ]
```

Four change types:
- 🔵 **Value Update** — something changed to a new value
- 🟢 **New Addition** — something exists now that wasn't documented
- 🔴 **Removal** — something was deprecated or stopped
- 🟡 **Temporary Exception** — time-boxed change, shouldn't permanently rewrite the doc

---

## How we built it

### Architecture

![TrueDocs System Architecture](https://raw.githubusercontent.com/Pragadhesh/Truedocs/master/images/architecture.png)

### Tech stack

| Layer | Technology |
|---|---|
| Slack integration | `slack-bolt` — Socket Mode for real-time events, slash commands, Block Kit actions |
| AI / LLM | Claude Sonnet 4.6 via Anthropic API |
| Agent framework | PydanticAI — structured output with `Agent(output_type=ChangeAnalysis)` |
| MCP integration | `pydantic_ai.mcp.MCPServerStreamableHTTP` — tool use over MCP protocol |
| Documentation | Confluence REST API v2 — `GET` for page content, `PUT` for targeted updates |
| Page patching | Deterministic anchor-based replacement on Confluence Storage Format (XML/HTML) |
| OAuth | Flask + `slack_bolt.oauth` with SQLite installation store for multi-workspace |
| Deployment | Docker on GCP e2-micro (Dockerfile + docker-compose) |
| Runtime | Python 3.11+, managed with `uv` |

### How the AI piece works

The drift analysis isn't a simple keyword search. Claude reads the full Confluence page in Storage Format alongside all the Slack messages from the lookback window, then produces a structured `ChangeAnalysis` — a list of `ChangeItem` objects, each with:

- Which section of the doc is affected
- What it currently says
- What the Slack announcement implies it should say
- The exact message that triggered the detection
- Whether the change is permanent or temporary
- Confidence level (HIGH / MEDIUM / LOW)

When you click Apply, TrueDocs re-fetches both the latest doc and the messages, re-runs the analysis, finds the affected paragraph by its anchor text, and patches only that specific node. Nothing else in the doc changes.

For `/truedocs-ask`, the agent gets the full Confluence page as context and answers in Slack with a citation to the specific section it pulled from.

### Qualifying technologies used

**Slack AI capabilities** — The entire product runs inside Slack. Socket Mode keeps the connection live. Block Kit renders the drift cards with interactive buttons. The assistant responds in DMs and threads via `@TrueDocs`. Slash commands (`/truedocs-scan`, `/truedocs-ask`, `/truedocs register`) are the primary entry points.

**MCP server integration** — PydanticAI's `MCPServerStreamableHTTP` is wired into the agent for tool-use over the Model Context Protocol, making it straightforward to give the agent structured access to external data sources.

**Real-Time Search** — Confluence pages are fetched live at analysis time and again at approval time, ensuring the AI always reasons over the current state of the doc, not a stale cache. `/truedocs-ask` answers are sourced directly from the live page at the moment of the question.

---

## Challenges we ran into

**Getting Claude to not over-trigger.** The first version flagged everything. Someone mentions "thanks everyone" and Claude would find a way to interpret it as a documentation change. Significant prompt engineering went into teaching the model to distinguish between *announcements that change a process* and *conversational messages that happen to mention a process*. The system prompt now has explicit criteria: the message must contradict or extend a specific claim in the doc, not just reference the same topic.

**Deterministic page patching.** Replacing text in Confluence Storage Format is trickier than it sounds. The page body is XML with Confluence-specific macro tags, table structures, and nested formatting. Using BeautifulSoup to find the right node and replace only that node (without mangling anything around it) required building an anchor-based matching system — Claude identifies the `anchor_text` and `context_before` for each change, and the patching code uses those to locate the exact element.

**Slack's Block Kit character limits.** Drift cards hit Slack's 3,000-character block limit quickly when docs have long paragraphs. Had to implement truncation logic that keeps the diff readable while staying within limits.

**MCP on older pydantic-ai versions.** `MCPServerStreamableHTTP` didn't exist in earlier releases. Added a graceful fallback with a try/except import so the app still runs on environments without the latest pydantic-ai.

---

## Accomplishments that we're proud of

The moment it just *works* in a real channel is genuinely satisfying in a way that's hard to describe.

We ran TrueDocs on our own `#deployments` channel during development. The very first real scan — not a test, an actual production channel — came back with three genuine drift items. One was a deployment window change from three weeks prior that nobody had ever updated in the doc. Another was a rollback command that had been replaced with a newer version and the old one was sitting there in the runbook, quietly wrong.

We showed it to a friend who runs a 20-person engineering team. He said: *"I have a Google Doc that hasn't been touched in eight months but the process changed at least four times."* He set it up in ten minutes.

That's the validation. Not lines of code or architectural elegance — the fact that it immediately found real problems in real docs that real people were relying on.

The per-item approval model is something we're especially proud of. Early designs applied all changes at once. But documentation changes are judgment calls — sometimes the Slack message is context-specific and shouldn't update the permanent doc. Giving each item its own Approve/Skip keeps the human in the loop without making the whole flow tedious.

---

## What we learned

Claude is remarkably good at understanding the *intent* of documentation change — better than we expected. The hard part isn't the AI; it's the surrounding system: the structured output contract, the deterministic patching, the Slack UX that makes it feel natural rather than intrusive.

PydanticAI's structured output approach (`output_type=`) made a real difference. Having Claude return a typed `ChangeAnalysis` instead of free-form text means the rest of the pipeline is pure Python — no parsing, no fragile JSON extraction, just attributes.

We also learned that the "lookback window" setting matters a lot more than we initially thought. A 1-day scan of a busy channel produces noise. A 1-week scan of a slow channel misses nothing. Letting teams configure this per-process was the right call.

---

## What's next for TrueDocs

**More documentation platforms.** Confluence is where a lot of engineering docs live, but it's not the only place. Google Docs, Notion, and GitHub wikis are next on the list. The core architecture is platform-agnostic — swapping the Confluence client for a Google Docs client is a contained change.

**Scheduled scans.** Right now you run `/truedocs-scan` manually. The natural next step is letting teams schedule automated scans — daily at 9 AM, weekly on Mondays — so drift gets caught without anyone having to remember to run the command.

**Proactive mode.** Instead of waiting for a scan, watch the channel in real time and flag potential drift *as it happens* — posting a lightweight notice immediately after an announcement that looks like it contradicts the doc: *"This might conflict with your runbook — want me to check?"*

**Cross-channel awareness.** A process might be discussed in multiple channels. A deployment announcement in `#releases` should be able to update the doc that's registered in `#deployments`.

**Audit trail.** Every applied change should generate a log entry with the Slack message, the old doc value, the new value, and who approved it. Right now that history lives nowhere. Teams need this for compliance and for understanding *why* a doc looks the way it does.

**Jira & Linear integration.** When drift is detected, optionally create a ticket in the team's issue tracker so the doc update goes through the normal review process rather than being applied immediately.

The goal has always been the same: close the gap between what teams *say* and what docs *show*. There's a lot of ground left to cover.

---

## Built with

`Python` · `slack-bolt` · `Anthropic Claude Sonnet 4.6` · `PydanticAI` · `MCP (Model Context Protocol)` · `Confluence REST API v2` · `Flask` · `Docker` · `uv`
