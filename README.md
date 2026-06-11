# TrueDocs

**TrueDocs** is a Slack agent that keeps your organisation's Confluence runbooks and SOPs automatically up to date by detecting when team announcements in Slack contradict or extend what's written in the documentation — and proposing targeted edits with per-item approval.

## The problem

Documentation rots. A deployment runbook gets written once. Then someone announces in Slack: *"deployment window is changing to 4–9 PM this week"* — but the doc still says 2–7 PM. Or: *"we're putting deploys on hold for December"* — the doc says nothing. A few weeks later, the runbook is wrong, people stop trusting it, and process knowledge collapses back into a few people's heads.

TrueDocs treats your Slack channels as the source of truth for what's *actually* happening, and automatically reconciles your Confluence docs against what the team announces.

## How it works

```
Slack announcement  →  TrueDocs detects drift  →  Posts diff card  →  Per-item Confluence update
```

1. **Register** — point TrueDocs at a Confluence page and a Slack channel via `/truedocs register` or the App Home.
2. **Scan** — run `/truedocs-run` in any registered channel. TrueDocs reads all messages in the configured time window.
3. **Analyze** — Claude (Sonnet 4.6) compares the messages against the Confluence page and identifies announcements that *contradict or extend* the documentation: changed values, new steps, temporary exceptions, updated ownership, etc.
4. **Review** — TrueDocs posts a drift card with a GitHub-style diff for each detected change (coloured sidebar: 🔵 modified · 🟢 added · 🔴 removed · 🟡 temporary).
5. **Apply** — click **Apply to Confluence** on each change you agree with, or **Skip** to leave that item unchanged. Each approval is independent and updates the live page immediately.

## Example drift card

```
TrueDocs — Deployment Runbook
─────────────────────────────────────────
🔵  1. Deployment Window   `Value Update`
    ```diff
    - Deployment window: 2:00 PM – 7:00 PM IST
    + Deployment window: 4:00 PM – 9:00 PM IST
    ```
    🗨 "deployment window is changing to 4–9 PM this week due to on-call rotation"
    [Apply to Confluence]  [Skip]

🟡  2. Deployment Freeze   `Temporary Exception`
    ```diff
    + All deployments are on hold through December.
    ```
    🗨 "freezing deploys for the whole of December — resume Jan 2"
    [Apply to Confluence]  [Skip]
```

## Setup

### Prerequisites

- Python 3.11+ with [uv](https://docs.astral.sh/uv/)
- A Slack workspace with permission to install apps
- A Confluence Cloud account with an API token
- An Anthropic API key

### Install

```bash
git clone https://github.com/your-org/truedocs
cd truedocs
uv sync
```

### Environment variables

Copy `.env.sample` to `.env` and fill in:

```bash
SLACK_APP_TOKEN=xapp-...          # Socket Mode app-level token
SLACK_BOT_TOKEN=xoxb-...          # Bot user token
ANTHROPIC_API_KEY=sk-ant-...      # Claude API key
```

### Create the Slack app

1. Go to [api.slack.com/apps/new](https://api.slack.com/apps/new) and choose **From an app manifest**
2. Paste the contents of [`manifest.json`](./manifest.json) and click **Next**
3. Review and click **Create**, then **Install to Workspace**
4. Copy the **Bot User OAuth Token** into `SLACK_BOT_TOKEN`
5. Under **Basic Information → App-Level Tokens**, create a token with `connections:write` scope and copy it into `SLACK_APP_TOKEN`

### Run

```bash
uv run python app.py
```

## Usage

### Step 1 — Connect Confluence

Open the TrueDocs App Home in Slack and click **Connect Confluence**. Enter your Atlassian email and API token.

### Step 2 — Register a process

Use `/truedocs register` (or click **Register New Process** in the App Home):

| Field | Description |
|---|---|
| **Name** | What this process is (e.g. *Deployment Runbook*) |
| **Channel** | The Slack channel where announcements are made |
| **Confluence page URL** | The page to keep up to date |
| **Observation window** | How far back to scan (1h / 4h / 12h / 1d / 1w) |
| **Trigger phrase** | Keyword for message-based triggering (optional) |

### Step 3 — Scan for drift

Run `/truedocs-run` in the registered channel. TrueDocs auto-discovers the process for that channel and starts scanning.

Alternatively, post your configured trigger phrase as a message in the channel.

### Step 4 — Review and apply

TrueDocs posts a drift card with a coloured diff for each detected change:

- **Apply to Confluence** — applies that single change to the live Confluence page immediately
- **Skip** — dismisses that item; the doc is left unchanged for it

Each item is independent — apply the ones you agree with and skip the rest.

## Project structure

```
truedocs/
├── app.py                        # Bolt entry point, listener registration
├── prompts.py                    # LLM system prompts (drift analysis, assistant)
├── modes/
│   ├── observe.py                # Fetch channel messages + thread replies (Slack API)
│   ├── diff.py                   # Claude drift analysis; deterministic Confluence HTML patching
│   ├── pipeline.py               # Orchestrate observe → analyze → post card
│   └── pending.py                # In-memory store for analyses awaiting approval
├── blockkit/
│   └── drift_card.py             # GitHub-style coloured diff card with per-item buttons
├── integrations/
│   └── confluence.py             # Confluence REST API v2 client
├── db/
│   ├── credentials.py            # Confluence credentials (file-backed JSON)
│   └── processes.py              # Process registry (file-backed JSON)
├── listeners/
│   ├── events/
│   │   ├── app_home_opened.py    # App Home view
│   │   ├── app_mentioned.py      # @mention handler (AI assistant)
│   │   ├── assistant_thread_started.py
│   │   └── message.py            # Trigger phrase detection → pipeline
│   ├── actions/
│   │   ├── confluence_setup.py   # Credential save handler
│   │   ├── register_process.py   # Process registration handler
│   │   └── drift_actions.py      # Per-item Apply / Skip handlers
│   ├── commands/
│   │   └── truedocs_register.py  # /truedocs register · /truedocs-run
│   └── views/
│       ├── app_home_builder.py   # App Home Block Kit builder
│       ├── confluence_modal.py   # Credential modal
│       └── register_modal.py     # Process registration modal
├── agent/                        # General-purpose Slack AI assistant (DM / @mention)
├── thread_context/               # Per-thread conversation history store
└── data/                         # Runtime data — gitignored
    ├── credentials.json
    └── processes.json
```

## Tech stack

| Component | Technology |
|---|---|
| Runtime | Python 3.11+ |
| Slack framework | slack-bolt (Socket Mode) |
| AI | Claude Sonnet 4.6 via PydanticAI |
| Documentation | Confluence REST API v2 (Storage Format) |
| HTML patching | BeautifulSoup4 (read-only) + deterministic string ops |
| Persistence | JSON files (`data/`) |
| HTTP client | httpx |
| Package manager | uv |

## Slash commands

| Command | Description |
|---|---|
| `/truedocs register` | Register a new process or open the App Home |
| `/truedocs-run` | Scan the current channel for documentation drift |

## Hackathon

Built for the **Slack Agent Builder Challenge** on Devpost.

**Track**: Slack Agent for Organizations

**Hero technologies**: Slack AI · MCP · Real-Time Search API
