# TrueDocs — Project Context

## What this project is
TrueDocs is a Slack agent that keeps an organisation's runbooks and SOPs
continuously accurate by comparing documented processes against how work
actually happens in Slack, and proposing updates when the two drift apart.
It is a self-healing knowledge base.

## The core problem
Documentation rots. Teams write a deploy guide or SOP once, reality drifts
within weeks, and process knowledge collapses back into a few people's heads.
TrueDocs treats Slack threads as ground truth and reconciles docs against
observed reality.

## The five-mode core loop
1. Register  — user points TrueDocs at a doc and a channel/trigger phrase
2. Observe   — RTS API gathers the execution thread, Claude extracts steps
3. Diff      — compare observed steps vs documented steps, detect drift
4. Propose   — surface drift with evidence via Block Kit, human approves/rejects
5. Serve     — drop verified checklist into thread, capture run as fresh data

## Hackathon context
- Event: Slack Agent Builder Challenge (Devpost)
- Track: Slack Agent for Organizations
- Must submit to Slack Marketplace before deadline
- Uses all three hero technologies: RTS API + MCP + Slack AI

## Tech stack
- Language: Python 3.11+
- Slack: slack-bolt AsyncApp
- AI framework: PydanticAI
- LLM: Claude Sonnet 4.6 (observe/diff/propose), Claude Haiku (classify)
- MCP: official Python MCP SDK
- Database: Supabase (PostgreSQL with RLS)
- HTTP: httpx (async)
- Package manager: uv

## Project structure
truedocs/
├── app.py                  ← Bolt entry, all event wiring
├── modes/
│   ├── register.py         ← /truedocs register slash command
│   ├── observe.py          ← RTS + Claude step extraction (build first)
│   ├── diff.py             ← compare observed vs documented
│   ├── propose.py          ← Block Kit drift card builder
│   └── serve.py            ← checklist drop + nudge skipped steps
├── mcp/
│   ├── client.py           ← MCP client setup
│   ├── notion.py           ← read/write Notion docs
│   ├── github.py           ← verify GitHub Actions ran
│   └── jira.py             ← verify Jira ticket moved
├── ai/
│   ├── claude.py           ← PydanticAI agent definitions
│   └── prompts.py          ← all system prompts in one file
├── db/
│   ├── client.py           ← Supabase client singleton
│   ├── processes.py        ← process registry queries
│   └── runs.py             ← run history queries
├── blockkit/
│   ├── drift_card.py       ← documented vs observed table + buttons
│   └── checklist.py        ← serve-mode checklist
└── utils/
    └── rts.py              ← Real-Time Search API wrapper

## Key data models (Pydantic)
- ProcessStep: step_name, actor, status (done/skipped/blocked), notes
- ObservedRun: steps: list[ProcessStep], blockers, undocumented_steps
- DriftResult: has_drift, skipped_steps, new_steps, reordered, summary
- Process: id, workspace_id, name, channel_id, trigger, doc_url, doc_source
- Run: id, process_id, workspace_id, thread_ts, steps_observed, drift_detected, status

## Build order
1. observe.py   ← hardest, most important, build and test first
2. diff.py      ← pure comparison logic, no LLM needed
3. propose.py   ← Block Kit card, the visual wow moment
4. serve.py     ← checklist drop, closes the loop
5. register.py  ← slash command, needed for demo but not the core

## External integrations (via MCP)
- Notion MCP server: read canonical docs, write approved changes
- GitHub MCP server: verify Actions ran (step verification)
- Jira MCP server: verify ticket status changed

## Multi-tenancy
All DB tables have workspace_id. Supabase RLS policy:
workspace_id = auth.jwt() ->> 'workspace_id'
Every customer workspace is automatically isolated.

## Demo script (3 minutes)
1. Type "deploying v2.3" in #deployments
2. Thread unfolds with realistic steps
3. TrueDocs posts drift card: "step 3 skipped, new step 4a seen 6 times"
4. Click Approve — Notion doc updates live on screen
5. Show /truedocs register command
6. Show App Home process registry