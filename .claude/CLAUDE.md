# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## What TrueDocs does

TrueDocs watches Slack channels for announcements that **contradict or extend** a linked Confluence page, then proposes (and on approval, applies) targeted doc updates. It does NOT compare step-by-step process execution — it finds semantic discrepancies between what the team said in Slack and what the doc currently says.

Example: Slack says "deployment window moving to 4–9 PM this week" but Confluence says "2–7 PM" → TrueDocs detects the conflict, posts a drift card, and can update the doc on approval.

## Running the app

```bash
uv run python app.py
```

Requires `.env` with `SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN`, and `ANTHROPIC_API_KEY`.

## Core pipeline

```
Trigger phrase in channel
  → modes/observe.py     fetch all channel messages in lookback window (pure Slack API, no Claude)
  → modes/diff.py        Claude compares messages vs Confluence doc → ChangeAnalysis
  → blockkit/drift_card  post card with ChangeItems (section, doc value, Slack announcement, evidence, temporary flag)
  → listeners/actions/drift_actions.py
      Approve: re-fetch → re-analyze → generate_updated_page_html → update Confluence
      Reject:  post dismissal message
```

## Key files

| File | Purpose |
|---|---|
| `modes/observe.py` | `fetch_channel_messages(client, channel_id, lookback_window)` — paginates `conversations.history`, returns human messages oldest-first |
| `modes/diff.py` | `ChangeItem`, `ChangeAnalysis` models; `analyze_changes()` runs Claude; `generate_updated_page_html()` rewrites affected doc sections |
| `modes/pipeline.py` | Orchestrates observe → analyze → post drift card |
| `blockkit/drift_card.py` | Block Kit card; one section per `ChangeItem` |
| `integrations/confluence.py` | `ConfluenceClient`: `get_page()`, `update_page_with_html()`, `can_access_page()` |
| `db/credentials.py` | File-backed JSON (`data/credentials.json`): `upsert`, `get` |
| `db/processes.py` | File-backed JSON (`data/processes.json`): `create`, `update`, `delete`, `list_by_workspace` |
| `listeners/events/message.py` | `_check_trigger()` — case-insensitive trigger phrase match → `run_pipeline()` in background thread |
| `listeners/actions/drift_actions.py` | `handle_approve_drift`, `handle_reject_drift` |
| `listeners/actions/register_process.py` | Validates Confluence page access before `ack()`; calls `conversations_join` after save |
| `listeners/views/register_modal.py` | Modal with lookback window dropdown (1h/4h/12h/1d/1w, default 1d) |

## PydanticAI conventions

- `Agent(output_type=MyModel)` — use `output_type=`, not `result_type=`
- Access result with `result.output`, not `result.data`
- `get_model()` in `agent/agent.py` picks provider at runtime from env vars (Anthropic preferred)
- Pass model at call site: `agent.run_sync(prompt, model=get_model())`

## Confluence API

- REST API v2: `GET /api/v2/pages/{id}?body-format=storage`, `PUT /api/v2/pages/{id}`
- Auth: Basic auth — base64 of `email:token`
- Page ID extracted from URL via regex `/pages/(\d+)`
- Base URL inferred from page URL: Cloud has `/wiki` in path; Server/DC does not
- Page body is **Confluence Storage Format** (HTML-like XML) — Claude must produce valid Storage Format when updating

## Persistence

- `data/` directory is gitignored
- Both JSON files are created on first write; read returns `{}` / `None` on missing file
- Credentials shape: `{"confluence_email": "...", "confluence_token": "..."}`
- Process shape includes: `id`, `name`, `channel_id`, `confluence_page_url`, `trigger_type`, `trigger_phrase`, `lookback_window`, `drift_detected`, `last_observed_at`

## Slack scopes required

`channels:history`, `channels:join`, `channels:read`, `chat:write`, `app_mentions:read`, `im:history`, `im:write`