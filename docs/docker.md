# Running cuga-apps with Docker / Podman

All 16 demo apps, the umbrella UI, and Arize Phoenix observability run in three containers managed by a single `docker compose up`.

## Prerequisites

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) or [Podman Desktop](https://podman-desktop.io) (Mac/Windows).

**Podman only** — start the VM first:

```bash
podman machine init     # one-time setup
podman machine start
podman info             # verify
```

---

## Quick start

```bash
# 1. Clone the repo
git clone <repo-url>
cd cuga-apps

# 2. Create your environment file
cp apps/.env.example apps/.env
#    → open apps/.env and fill in at least LLM_PROVIDER + the matching API key

# 3. Build the images (takes several minutes on first run)
docker compose build        # or: podman-compose build

# 4. Start everything
docker compose up -d        # or: podman-compose up -d
```

Open **http://localhost:3000** — the umbrella UI lists every demo app with a "Try it now" button.

---

## Environment variables

All apps read from `apps/.env`. The file is pre-documented with every variable — see [`apps/.env.example`](../apps/.env.example) for the full reference. The essentials are:

### Step 1 — choose an LLM provider (required)

Set exactly one block. Most apps work with any provider; a few hardcode Anthropic (noted below).

**Anthropic** (recommended for external users)
```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**OpenAI**
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

**IBM RITS**
```bash
LLM_PROVIDER=rits
RITS_API_KEY=<your-key>
RITS_BASE_URL=https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com
```

**watsonx.ai**
```bash
LLM_PROVIDER=watsonx
WATSONX_APIKEY=<your-key>
WATSONX_PROJECT_ID=<your-project-id>   # or WATSONX_SPACE_ID
```

**LiteLLM proxy**
```bash
LLM_PROVIDER=litellm
LITELLM_API_KEY=<your-key>
LITELLM_BASE_URL=https://your-proxy/
```

**Ollama (local, no key)**
```bash
LLM_PROVIDER=ollama
# In Docker, point to the host machine:
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### Step 2 — app-specific keys (set what you need)

| Variable | Used by | Where to get it |
|----------|---------|-----------------|
| `TAVILY_API_KEY` | web_researcher, travel_planner, hiking_research, youtube_research, arch_diagram | [tavily.com](https://tavily.com) |
| `ALPHA_VANTAGE_API_KEY` | stock_alert | [alphavantage.co](https://www.alphavantage.co/support/#api-key) |
| `OPENTRIPMAP_API_KEY` | travel_planner | [opentripmap.io](https://opentripmap.io/product) |
| `OPENAI_API_KEY` | voice_journal (Whisper transcription) | [platform.openai.com](https://platform.openai.com) |

### Step 3 — email alerts (optional)

Apps with email alerts (newsletter, stock_alert, drop_summarizer, web_researcher, voice_journal, smart_todo) fall back gracefully to logging if SMTP is not configured.

```bash
SMTP_HOST=smtp.gmail.com
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your-gmail-app-password   # not your login password

ALERT_TO=you@gmail.com      # newsletter, drop_summarizer, stock_alert
DIGEST_TO=you@gmail.com     # voice_journal
RESEARCH_TO=you@gmail.com   # web_researcher
```

> **Gmail tip:** create an [App Password](https://myaccount.google.com/apppasswords) under your Google account security settings — your normal login password won't work.

---

## Services and ports

| Service | URL | Notes |
|---------|-----|-------|
| **Umbrella UI** | http://localhost:3000 | App gallery with "Try it now" links |
| **Phoenix** | http://localhost:6006 | LLM observability (traces, spans) |

| App | Port | URL |
|-----|------|-----|
| newsletter | 18793 | http://localhost:18793 |
| drop_summarizer | 18794 | http://localhost:18794 |
| web_researcher | 18798 | http://localhost:18798 |
| voice_journal | 18799 | http://localhost:18799 |
| smart_todo | 18800 | http://localhost:18800 |
| stock_alert | 18801 | http://localhost:18801 |
| video_qa | 8766 | http://localhost:8766 |
| server_monitor | 8767 | http://localhost:8767 |
| travel_planner | 8090 | http://localhost:8090 |
| deck_forge | 18802 | http://localhost:18802 |
| youtube_research | 18803 | http://localhost:18803 |
| arch_diagram | 18804 | http://localhost:18804 |
| hiking_research | 18805 | http://localhost:18805 |
| movie_recommender | 18806 | http://localhost:18806 |
| webpage_summarizer | 8071 | http://localhost:8071 |
| code_reviewer | 18807 | http://localhost:18807 |

---

## Common commands

```bash
# Stop everything
docker compose down

# View streaming logs
docker compose logs -f apps       # all demo apps
docker compose logs -f ui         # nginx / UI
docker compose logs -f phoenix    # observability

# Last 100 lines
docker compose logs --tail 100 apps
```

---

## Rebuilding after changes

Code changes only (no new packages):
```bash
docker compose build apps
docker compose up -d
```

After adding a package to `requirements.apps.txt`:
```bash
docker compose build --no-cache apps
docker compose up -d
```

After changing the UI (`ui/src/`):
```bash
docker compose build ui
docker compose up -d
```

---

## Memory (Podman only)

16 Python processes share one container. Each uses roughly 600–800 MB with models loaded, so the Podman VM needs at least **12 GB**:

```bash
podman machine stop
podman machine set --memory 12288   # 12 GB
podman machine start
```

Check current allocation:
```bash
podman machine inspect | grep -i memory
```

---

## Troubleshooting

**"Cannot connect to Podman" / SSH handshake failed**
```bash
podman machine stop && podman machine start
```

**"No space left on device" during build**
```bash
podman system prune -f
podman image prune -f
```

If it recurs, increase the VM disk (requires recreating the machine):
```bash
podman machine stop
podman machine rm
podman machine init --disk-size 150   # GB
podman machine start
```

**"Container name already in use"**
```bash
docker compose down
docker container prune -f
docker compose up -d
```

**App not responding after `docker compose up`**

Check the startup logs — an app may have exited due to a missing dependency:
```bash
docker compose logs apps | grep -E "ERROR|Traceback|ImportError"
```

**"Try it now" opens but nothing loads**

The app may have failed to start. Check:
```bash
docker compose logs apps | grep -i "Starting\|Error\|port"
```
