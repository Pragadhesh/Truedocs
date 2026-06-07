# TrueDocs

**TrueDocs** is a Slack agent that keeps your organisation's Confluence runbooks and SOPs automatically up to date by detecting when team announcements in Slack contradict or extend what's written in the documentation — and proposing targeted edits with one-click approval.

## The problem

Documentation rots. A deployment runbook gets written once. Then someone announces in Slack: *"deployment window is changing to 4–9 PM this week"* — but the doc still says 2–7 PM. Or: *"we're putting deployments on hold for December"* — the doc says nothing. A few weeks later, the runbook is wrong, people stop trusting it, and process knowledge collapses back into a few people's heads.

TrueDocs treats your Slack channels as the source of truth for what's *actually* happening, and automatically reconciles your Confluence docs against what the team announces.

## How it works

```
Slack announcement  →  TrueDocs detects discrepancy  →  Posts drift card  →  One-click Confluence update
```

1. **Register** — point TrueDocs at a Confluence page and a Slack channel. Pick a trigger phrase (e.g. `run-check`) and how far back to scan (1 hour → 1 week).
2. **Observe** — when the trigger phrase is posted in the channel, TrueDocs reads all messages in the configured time window.
3. **Analyze** — Claude (Sonnet 4.6) compares the messages against the Confluence page and identifies any announcements that *contradict or extend* the documentation: changed values, new steps, temporary freezes, updated ownership, etc.
4. **Propose** — TrueDocs posts a drift card in the thread showing what changed, what the doc currently says, what Slack announced, and whether the change is temporary.
5. **Update** — click **Approve** and TrueDocs rewrites the affected sections of the Confluence page (preserving structure and formatting), then posts a link to the updated page. Click **Reject** to leave the doc unchanged.

## Example

> **Slack**: *"@team deployment window is changing from 2–7 PM to 4–9 PM this week due to the on-call rotation"*
>
> **Confluence doc says**: *Deployment window: 2:00 PM – 7:00 PM*

TrueDocs drift card:

| | |
|---|---|
| **Section** | Deployment Window _(temporary)_ |
| **Doc says** | Deployment window: 2:00 PM – 7:00 PM |
| **Slack says** | Deployment window changed to 4–9 PM this week |
| **Evidence** | *"deployment window is changing from 2–7 PM to 4–9 PM this week due to the on-call rotation"* |

→ Click **Approve & Update Confluence** → done. The page is updated and a link is posted in the thread.

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

# Optional: pre-seed default Confluence credentials
CONFLUENCE_EMAIL=you@company.com
CONFLUENCE_API_TOKEN=your-atlassian-token
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

Open the TrueDocs App Home in Slack and click **Connect Confluence**. Enter your Atlassian email and API token. TrueDocs stores the credentials and uses them to read and update Confluence pages.

### Step 2 — Register a process

Click **Register New Process** and fill in:

| Field | Description |
|---|---|
| **Name** | What this process is (e.g. *Deployment Runbook*) |
| **Channel** | The Slack channel where announcements are made |
| **Confluence page URL** | The page to keep up to date |
| **Observation window** | How far back to scan (1h / 4h / 12h / 1d / 1w) |
| **Trigger phrase** | A keyword that starts the check (e.g. `run-check`, `deploying`) |

TrueDocs verifies it can access the Confluence page before saving.

### Step 3 — Post the trigger phrase

Type your trigger phrase in the registered channel. TrueDocs scans the channel's recent messages against the Confluence doc and posts a drift card in the thread.

### Step 4 — Approve or reject

Review each detected change. Click **Approve & Update Confluence** to apply all changes, or **Reject** to leave the doc as is.

## Project structure

```
truedocs/
├── app.py                        # Bolt entry, event wiring
├── modes/
│   ├── observe.py                # Fetch channel messages (Slack API)
│   ├── diff.py                   # Claude analysis: Slack vs Confluence doc
│   └── pipeline.py               # Orchestrate observe → analyze → propose
├── blockkit/
│   └── drift_card.py             # Block Kit drift card with approve/reject buttons
├── integrations/
│   └── confluence.py             # Confluence REST API v2 client
├── db/
│   ├── credentials.py            # Confluence credentials (file-backed JSON)
│   └── processes.py              # Process registry (file-backed JSON)
├── listeners/
│   ├── events/
│   │   ├── app_home_opened.py    # App Home view
│   │   └── message.py            # Trigger phrase detection
│   ├── actions/
│   │   ├── confluence_setup.py   # Credential save handler
│   │   ├── register_process.py   # Process registration handler
│   │   └── drift_actions.py      # Approve / Reject handlers
│   └── views/
│       ├── app_home_builder.py   # App Home Block Kit builder
│       ├── confluence_modal.py   # Credential modal
│       └── register_modal.py     # Process registration modal
├── agent/                        # General-purpose Slack AI agent (DM/mention mode)
└── data/                         # Runtime data (gitignored)
    ├── credentials.json
    └── processes.json
```

## Tech stack

| Component | Technology |
|---|---|
| Runtime | Python 3.11+ |
| Slack framework | slack-bolt (Socket Mode) |
| AI | Claude Sonnet 4.6 via PydanticAI |
| Documentation | Confluence REST API v2 |
| Persistence | JSON files (`data/`) |
| HTTP client | httpx |
| Package manager | uv |

## Hackathon

Built for the **Slack Agent Builder Challenge** on Devpost.

**Track**: Slack Agent for Organizations

**Hero technologies**: Slack AI · MCP · Real-Time Search API
