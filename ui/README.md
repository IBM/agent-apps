# cuga++

cuga++ is the infrastructure layer for [cuga](https://github.com/cuga-ai/cuga) agents.

A cuga agent is a LLM brain — it can reason, use tools, and hold a conversation. cuga++ is the nervous system that connects it to the world: it routes messages in from email, RSS, Slack, and Telegram; it fires the agent on a schedule or on a webhook; it delivers results back out via email, SMS, or any output channel; and it keeps everything running as a persistent background daemon that survives restarts.

The division of responsibility is deliberate: **cuga owns cognition, cuga++ owns infrastructure**. You write the agent and the domain tools. cuga++ handles the plumbing.

---

## What you can build with cuga++

- **Scheduled AI pipelines** — poll RSS feeds, monitor inboxes, and deliver curated digests on a cron schedule
- **Always-on chat agents** — one agent, reachable simultaneously from a browser, Telegram, WhatsApp, and voice
- **Event-driven workflows** — wake the agent on a webhook, fire actions when a condition is met
- **Personal assistants** — manage todos and reminders through natural language, proactive reminders when items are due
- **Autonomous monitors** — watch a source, alert when a threshold is crossed, summarize and deliver on schedule

---

## Table of contents

- [Architecture](#architecture)
- [cuga vs cuga++ vs OpenClaw](#cuga-vs-cuga-vs-openclaw)
- [Packages](#packages)
- [Setup](#setup)
- [Daemon modes](#daemon-modes)
- [YAML pipeline config](#yaml-pipeline-config)
- [Writing your own app](#writing-your-own-app)
- [Dashboard UI](#dashboard-ui)
- [Development](#development)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  App                                                            │
│                                                                 │
│  cuga_pipelines.yaml   skills/*.md   agent.py   app.py         │
│       ↓                    ↓             ↓          ↓           │
└───────┼────────────────────┼─────────────┼──────────┼──────────┘
        │                    │             │          │
┌───────▼────────────────────▼─────────────▼──────────▼──────────┐
│  cuga++  (cuga-channels)                                        │
│                                                                 │
│  CugaHost          ← daemon, owns background pipelines         │
│  ├─ CugaRuntime    ← one pipeline instance                     │
│  │   ├─ RssChannel       ← polls RSS feeds, keyword-filters    │
│  │   ├─ CronChannel      ← fires on a cron schedule            │
│  │   ├─ ChannelBuffer    ← decouples data from trigger         │
│  │   └─ EmailChannel     ← delivers agent output               │
│  └─ (more runtimes...)                                          │
│                                                                 │
│  CugaHostClient    ← HTTP client (apps talk to CugaHost)       │
│  ConversationGateway ← browser chat UI + routing               │
│  ChannelPlanner    ← natural language → pipeline config        │
│  RuntimeFactory    ← declarative pipeline factory builder      │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│  cuga                                                           │
│                                                                 │
│  CugaAgent         ← LLM agent, thread history, tools          │
│  CugaSkillsPlugin  ← injects skills/*.md as system context     │
│  CugaWatcher       ← polls a source, fires on condition        │
└─────────────────────────────────────────────────────────────────┘
```

### The OpenClaw model

The **OpenClaw model**: one always-on agent, all capabilities as tools, the
user interacts through a chat interface.

```
User
 └─→ ConversationGateway (chat UI)
       └─→ CugaAgent (one agent — data tools + config tools)
             ├── start_monitor / stop_monitor / get_status   (pipeline config)
             ├── fetch_now / query_data / save_item          (data tools)
             └── CugaSkillsPlugin → skills/*.md              (domain knowledge)

CugaHost (background daemon)
 └─→ CugaRuntime
       ├── CronChannel  → fires trigger message
       ├── RssChannel   → polls feeds into buffer
       └── EmailChannel → delivers agent output
```

The agent controls the pipeline through the same chat interface used for
everything else. No separate config UI, no separate planner agent.

---

## cuga vs cuga++ vs OpenClaw

| Capability | cuga | cuga++ | OpenClaw |
|---|:---:|:---:|:---:|
| LLM agent + thread history | ✅ | — | ✅ |
| Tool calling | ✅ | — | ✅ |
| Skill files (`.md` context injection) | ✅ | — | — |
| Persistent background daemon | — | ✅ `CugaHost` | ✅ gateway process |
| Persists pipelines across restarts | — | ✅ `runtimes.json` | ✅ `jobs.json` |
| RSS data channel | — | ✅ `RssChannel` | ✅ |
| Cron trigger | — | ✅ `CronChannel` | ✅ |
| Email delivery | — | ✅ `EmailChannel` (owns SMTP) | ✅ via Resend/external |
| Slack channel | — | ❌ planned | ✅ |
| Webhook trigger | — | ❌ planned | ✅ |
| NL → pipeline config | — | ✅ `ChannelPlanner` | ✅ |
| Always-on chat UI | — | ✅ `ConversationGateway` | ✅ |
| YAML pipeline config | — | ✅ `cuga_pipelines.yaml` | ✅ |
| HTTP control API | — | ✅ REST on :18790 | ✅ WebSocket |
| System daemon (launchd/systemd) | — | ✅ `cugahost install-daemon` | ✅ |
| Cloud/hosted option | — | ❌ self-hosted only | ✅ |

**Key difference from OpenClaw**: cuga++ owns delivery infrastructure (SMTP,
logging) rather than delegating it to external hosted services. The pipeline
runs entirely on your own machine or server — no external dependencies beyond
your LLM provider.

---

## Packages

| Package | Description |
|---|---|
| `cuga-channels` | Channels, runtime, host, client, planner, conversation gateway |
| `cuga-skills` | Markdown skill loader — injects `.md` files as agent system context |
| `cuga-plugin-sdk` | Protocol + shared types for skill plugins |
| `cuga-runtime` | LangGraph ReAct runtime that hosts the plugin registry |
| `cuga-checkpointer` | Durable SQLite checkpointer factory for conversation history |
| `cuga-triggers` | Standalone cron and webhook triggers |
| `cuga-watcher` | In-process pub-sub: poll a source, fire handlers on conditions |
| `cuga-mcp` | Connects MCP servers as agent tools |

See [packages/README.md](packages/README.md) for a full breakdown of each package, its API, and when to use it.

---

## Setup

### Prerequisites

- **Python 3.11+** (3.12 recommended — used in `.venv` inside each package)
- **uv** (recommended) or pip — for package management
- An LLM API key for at least one provider (or Ollama running locally)

Check your Python version:
```bash
python3 --version
```

Install uv if you don't have it:
```bash
curl -LsSf https://astral.uv.dev/install.sh | sh
```

### 1. Clone and enter the repo

```bash
git clone <repo-url> cuga-plusplus
cd cuga-plusplus
```

### 2. Create a virtual environment

```bash
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

Or with plain Python:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the packages

```bash
# Core packages
pip install -e "packages/cuga-channels[all]"
pip install -e packages/cuga-runtime
pip install -e packages/cuga-skills
pip install -e packages/cuga-plugin-sdk
pip install -e packages/cuga-checkpointer
pip install -e packages/cuga-triggers
pip install -e packages/cuga-watcher

# LLM provider — pick one (or more)
pip install langchain-anthropic     # Anthropic Claude
pip install langchain-openai        # OpenAI / compatible APIs
# Ollama: no install needed — just run `ollama serve`
```

### 4. Set your LLM API key

Pick one provider and export the key:

| Provider | Environment variable | Notes |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Recommended default |
| OpenAI | `OPENAI_API_KEY` | |
| Ollama | `OLLAMA_BASE_URL` | Default: `http://localhost:11434` — no key needed |
| LiteLLM | `LITELLM_API_KEY` + `LITELLM_BASE_URL` | Any OpenAI-compatible endpoint |
| RITS | `RITS_API_KEY` | IBM internal |
| WatsonX | `WATSONX_APIKEY` + `WATSONX_PROJECT_ID` | IBM Cloud |

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...
```

For email delivery (optional — only needed for digest/notification features):
```bash
export SMTP_USERNAME=you@gmail.com
export SMTP_PASSWORD=your-app-password   # Gmail: Settings > Security > App Passwords
export DIGEST_TO=you@gmail.com
```

---

## Daemon modes

CugaHost (the background pipeline daemon) can run in three modes.

### Mode 1: Embedded (default)

The daemon runs as an asyncio task inside the app process. Dies when the app
exits. Good for development and single-process deployments.

```python
# connect_or_embed() starts an embedded host if none is running
host, client = await CugaHostClient.connect_or_embed(
    state_dir=".cuga/host",
    pipelines_config="cuga_pipelines.yaml",
)
```

```
python app.py
  └─ asyncio event loop
       ├─ ConversationGateway  (:8765)
       ├─ CugaHost             (:18790, embedded)
       └─ CugaWatcher
```

### Mode 2: Standalone daemon (separate process)

The daemon runs independently. The app connects as a thin HTTP client.
Runtimes survive app restarts.

```bash
# Terminal 1 — start the daemon
cugahost start --pipelines-config path/to/cuga_pipelines.yaml

# Terminal 2 — start the app (connect_or_embed detects the running daemon)
python app.py
```

```
cugahost process  (:18790)
  └─ CugaRuntime(s)

python app.py
  └─ ConversationGateway (:8765)
  └─ CugaHostClient → HTTP → :18790
```

`cugahost` commands:
```bash
cugahost start  --pipelines-config path/to/cuga_pipelines.yaml
cugahost status
cugahost list
cugahost stop
cugahost restart --pipelines-config path/to/cuga_pipelines.yaml
```

### Mode 3: System daemon (survives reboots)

Installs CugaHost as a launchd agent (macOS) or systemd unit (Linux).

```bash
# macOS
cugahost install-daemon --pipelines-config /abs/path/to/cuga_pipelines.yaml
launchctl load ~/Library/LaunchAgents/dev.cuga.host.plist

# Linux
cugahost install-daemon --pipelines-config /abs/path/to/cuga_pipelines.yaml
systemctl --user daemon-reload
systemctl --user enable --now cuga-host
```

Logs:
```bash
tail -f ~/.cuga/host/host.log
tail -f ~/.cuga/host/host.err
```

---

## YAML pipeline config

`cuga_pipelines.yaml` replaces `host_factories.py`. No Python needed.

```yaml
pipelines:
  - id: my-digest              # runtime id (also used as factory name by default)
    factory: my-factory        # factory name — optional, defaults to id
    agent: "agent:make_agent"  # module:function, called with no args
    thread_id: my-digest       # stable thread id for conversation history
    message: |                 # prompt sent to agent when trigger fires
      Good morning! Send the daily digest.
      Return HTML — do not call any send or email tools.
    trigger:
      type: cron
      default_schedule: "0 8 * * 1-5"   # overridden at runtime by user config
    data:                                 # optional data channels
      - type: rss
        default_sources:
          - "https://arxiv.org/rss/cs.AI"
        default_keywords:
          - "LLM"
          - "agent"
    output:
      type: email
      subject_prefix: "My Digest"
    require_buffer: false        # true = wait for data; false = agent fetches its own
```

Supported channel types:

| Section | `type` | What it builds |
|---|---|---|
| `trigger` | `cron` | `CronChannel` — fires on a schedule |
| `data` | `rss` | `RssChannel` — polls RSS/Atom feeds |
| `output` | `email` | `EmailChannel` — delivers via SMTP |

Runtime config (schedule, email, sources) is provided at `start_runtime()` time
and can be overridden by the user through natural language without changing the
YAML.

---

## Writing your own app

An app needs five things:

```
myapp/
  agent.py               # make_agent() — one function
  cuga_pipelines.yaml    # pipeline wiring — no Python
  skills/
    myapp.md             # domain knowledge for the agent
  app.py                 # ~20 lines of asyncio wiring (optional for chat UI)
  store.py               # your data layer (if needed)
```

### `agent.py`

```python
import os
from pathlib import Path

def make_agent(client):
    from cuga import CugaAgent
    from cuga_skills import CugaSkillsPlugin
    from _llm import create_llm

    return CugaAgent(
        model=create_llm(
            provider=os.getenv("LLM_PROVIDER"),
            model=os.getenv("LLM_MODEL"),
        ),
        tools=[...],   # your domain tools — can close over `client` for pipeline config
        plugins=[CugaSkillsPlugin(skills_dir=str(Path(__file__).parent / "skills"))],
        cuga_folder=str(Path(__file__).parent / ".cuga"),
    )
```

### `app.py` (for browser chat UI)

```python
import asyncio
from pathlib import Path
from cuga_channels import CugaHostClient, ConversationGateway
from agent import make_agent

_DIR = Path(__file__).parent

async def main():
    cuga_host, client = await CugaHostClient.connect_or_embed(
        state_dir=_DIR / ".cuga" / "host",
        pipelines_config=_DIR / "cuga_pipelines.yaml",
    )
    agent   = make_agent(client=client)
    gateway = ConversationGateway(agent=agent)
    gateway.add_browser_adapter(port=8765, title="My App")
    try:
        await gateway.start()
    finally:
        if cuga_host is not None:
            await cuga_host.stop()

asyncio.run(main())
```

### `skills/myapp.md`

```markdown
# My App

You are a helpful assistant. When the user says X, call save_item(...).
When the user says Y, call list_items().

Classify inputs as: task | reminder | note
Extract: content, priority (high/medium/low), due_date (ISO-8601)
```

The pipeline wiring, scheduling, delivery, and chat UI are entirely owned by
cuga++. The app provides the domain knowledge (skill file), the data tools, and
a one-function agent factory.

---

## Dashboard UI

`ui/` is a React/Vite planning and overview dashboard — use cases, feature
coverage, roadmap, comparison with OpenClaw, and similar reference material.
It is separate from the runtime: you don't need it to run agents or demo apps.

### Start the dashboard

```bash
cd ui
npm install        # first time only
npm run dev
```

Open **http://localhost:5173**

### Build for static hosting

```bash
cd ui
npm run build      # outputs to ui/dist/
npm run preview    # preview the build locally
```

---

## Development

### Repo layout

```
cuga-plusplus/
  packages/
    cuga-channels/      # channels, runtime host, client, planner, gateway
    cuga-runtime/       # LangGraph ReAct runtime + plugin registry
    cuga-skills/        # markdown skill loader
    cuga-plugin-sdk/    # shared types + plugin protocol
    cuga-checkpointer/  # SQLite conversation history
    cuga-triggers/      # standalone cron + webhook triggers
    cuga-watcher/       # in-process pub-sub watcher
    cuga-mcp/           # MCP server connector
  ui/                   # React/Vite planning dashboard (separate from runtime)
```

### Working on a package

Each package is a standalone Python project with its own `pyproject.toml`.
Install it editable into your shared venv:

```bash
# from repo root, with .venv active
pip install -e packages/cuga-channels
pip install -e packages/cuga-runtime
# etc.
```

All packages are installed editable (`-e`), so changes take effect immediately
without reinstalling.

### Keeping venvs lean

Each package directory may contain its own `.venv` from isolated installs.
For day-to-day development, use a single shared `.venv` at the repo root and
install all packages into it. The per-package `.venvs` can be deleted to save
disk space:

```bash
# remove per-package venvs (safe if you have a shared root venv)
find packages -name ".venv" -type d -maxdepth 2 -exec rm -rf {} +
```
