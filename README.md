# cuga-apps

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

Open **http://localhost:5174**

### Build for static hosting

```bash
cd ui
npm run build      # outputs to ui/dist/
npm run preview    # preview the build locally
```

---

## 📦 Using CUGA as a Python SDK 

CUGA can be easily integrated into your Python applications as a library. The SDK provides a clean, minimal API for creating and invoking agents with custom tools.

### Installation

CUGA must be installed before use:

```bash
pip install git+ssh://git@github.com/cuga-project/cuga-agent.git@main
```

> Requires Python >=3.10, <3.14

📚 **SDK Documentation**: [SDK Documentation](https://docs.cuga.dev/docs/sdk/cuga_agent/)

## Set up applications

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # installs cuga
pip install -r apps/<app-name>/requirements.txt
```

---

## Running Apps

### Individual app

Each app runs standalone from its own directory:

```bash
cd apps/drop_summarizer
python main.py
```

### All apps via launch.py

`apps/launch.py` starts, stops, and monitors all apps in one command. It reads shared environment variables from `apps/.env`.

```bash
cd apps

# Install dependencies for all apps
python launch.py install

# Install dependencies for specific apps
python launch.py install newsletter smart_todo

# Start all apps
python launch.py

# Start specific apps only
python launch.py start newsletter smart_todo

# Stop all apps
python launch.py stop

# Stop specific apps
python launch.py stop drop_summarizer

# Show running status
python launch.py status

# Tail logs (last 30 lines per app)
python launch.py logs

# Tail logs for specific apps
python launch.py logs newsletter stock_alert --tail 50
```

### App ports

| App | Port | URL |
|-----|------|-----|
| newsletter | 18793 | http://localhost:18793 |
| drop_summarizer | 18794 | http://localhost:18794 |
| web_researcher | 18798 | http://localhost:18798 |
| voice_journal | 18799 | http://localhost:18799 |
| smart_todo | 18800 | http://localhost:18800 |
| stock_alert | 18801 | http://localhost:18801 |
| deck_forge | 18802 | http://localhost:18802 |
| server_monitor | 8767 | http://localhost:8767 |
| video_qa | 8766 | http://localhost:8766 |
| travel_planner | 8090 | http://localhost:8090 |

### .env file

Create `apps/.env` with your keys — all apps share it:

```bash
# LLM
LLM_PROVIDER=rits
RITS_API_KEY=your_key
AGENT_SETTING_CONFIG=settings.rits.toml

# Email (newsletter, smart_todo, stock_alert, drop_summarizer)
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_TO=you@gmail.com
NEWSLETTER_TO=you@gmail.com

# Stock alerts
ALPHA_VANTAGE_API_KEY=your_key

# Web researcher
TAVILY_API_KEY=your_key
```

---

## Environment Variables

### LLM Provider

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_PROVIDER` | Yes | Which provider to use: `rits` \| `openai` \| `anthropic` \| `watsonx` \| `litellm` \| `ollama` |
| `LLM_MODEL` | No | Model name override. Defaults to provider-specific default |
| `AGENT_SETTING_CONFIG` | No | Cuga internal settings file, e.g. `settings.rits.toml`. Configures all sub-agents (planner, policy, etc.). Defaults to `settings.openai.toml` |

### RITS (IBM Research Inference Service)

| Variable | Required | Description |
|----------|----------|-------------|
| `RITS_API_KEY` | Yes | RITS API key |
| `RITS_BASE_URL` | No | Override RITS endpoint. Default: `https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com` |

To use RITS as the provider for all cuga internals:
```bash
export LLM_PROVIDER=rits
export RITS_API_KEY=your_key
export AGENT_SETTING_CONFIG=settings.rits.toml
```

### OpenAI

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |

### Anthropic

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |

### WatsonX

| Variable | Required | Description |
|----------|----------|-------------|
| `WATSONX_APIKEY` | Yes | WatsonX API key |
| `WATSONX_PROJECT_ID` | Yes* | WatsonX project ID (*or `WATSONX_SPACE_ID`) |
| `WATSONX_SPACE_ID` | Yes* | WatsonX space ID (*or `WATSONX_PROJECT_ID`) |
| `WATSONX_URL` | No | WatsonX endpoint. Default: `https://us-south.ml.cloud.ibm.com` |

### LiteLLM

| Variable | Required | Description |
|----------|----------|-------------|
| `LITELLM_API_KEY` | Yes | LiteLLM API key |
| `LITELLM_BASE_URL` | Yes | LiteLLM proxy base URL |

### Ollama (local, no key required)

| Variable | Required | Description |
|----------|----------|-------------|
| `OLLAMA_BASE_URL` | No | Ollama endpoint. Default: `http://localhost:11434` |

---

### App-specific Variables

#### Email (drop_summarizer, newsletter, smart_todo)

| Variable | Description |
|----------|-------------|
| `SMTP_USERNAME` | Sender email address |
| `SMTP_PASSWORD` | App password (not your login password) |
| `SMTP_HOST` | SMTP server. Default: `smtp.gmail.com` |
| `ALERT_TO` | Recipient email for alerts |
| `NEWSLETTER_TO` | Recipient email for newsletter delivery |

#### stock_alert

| Variable | Description |
|----------|-------------|
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API key for stock/crypto price data |

#### drop_summarizer

| Variable | Description |
|----------|-------------|
| `WATCH_DIR` | Folder to watch for dropped files. Default: `./inbox` |
| `POLL_SECONDS` | Polling interval in seconds. Default: `15` |

