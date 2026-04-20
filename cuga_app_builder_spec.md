# CUGA Demo App — Builder Spec

## What is CUGA?

CUGA is a Python agent framework. You wrap an LLM with tools and a system prompt using `CugaAgent`, expose it via FastAPI, and serve a self-contained HTML UI from the same process. To know more about Cuga, refer to the code here: /Users/anu/Documents/GitHub/cuga-agent-apr10

---
## What should you build?

I want you to build a demo app for a use case that I will describe. Remember that the demo app should be run as a FastAPI Server and it should hold a pointer to all the tools. The demo app's job is to invoke CugaAgent to do any reasoning and provide all the tools it has. Once CugaAgent responds back, the demo app will mostly just render the output in the UI. The demo app by itself is not intelligent.

## Installation (one-time)

Before running any app, install the `cuga` package from the local repo:

```bash
pip install -e /Users/anu/Documents/GitHub/cuga-agent-apr10
```

This makes `from cuga.sdk import CugaAgent` and `from _llm import create_llm` available to every app.

---

## The Pattern (non-negotiable)

Each CUGA app lives in its own folder under `apps/`. **Always split the app into two files**: `main.py` for server logic and `ui.py` for the HTML — keeping them separate makes the code easier to read and maintain.

`_llm.py` is a shared file that lives at `apps/_llm.py` (one level above your app folder). The path bootstrap described below is what puts it on `sys.path` so your app can import it.

**Folder layout:**
```
apps/
  _llm.py               ← shared LLM factory, do not copy or modify
  your_app_name/
    main.py             ← server logic: tools, agent, FastAPI endpoints, CLI entry point
    ui.py               ← HTML UI exported as _HTML
    README.md           ← short: what it does, port, env vars, usage examples
    requirements.txt
```

---

## `main.py` Structure (in this order)

### 1. Module docstring
Describe what the app does, how to run it, and what env vars it needs.

### 2. Path bootstrap
```python
_DIR       = Path(__file__).parent
_DEMOS_DIR = _DIR.parent          # apps/ — this is where _llm.py lives
for _p in [str(_DIR), str(_DEMOS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
```
This is required. Don't skip it. It puts both the app folder and `apps/` on `sys.path`,
which is how `from _llm import create_llm` and `from ui import _HTML` resolve correctly.

### 3. Logging setup
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
```

### 4. LangChain tools (`_make_tools()`)
- Use `@tool` decorator from `langchain_core.tools`
- Each tool needs a clear docstring — the LLM reads it to decide when to call the tool
- Keep tools narrow and single-purpose
- Return JSON strings from tools

### 5. System prompt (`_SYSTEM`)
- Plain string, written like a concise instruction manual for the LLM
- Tell it: what it is, what tools to call in what situations, what format to reply in
- No padding, no pleasantries

### 6. `make_agent()`
```python
def make_agent():
    from cuga.sdk import CugaAgent   # note: cuga.sdk, not cuga directly
    from _llm import create_llm

    return CugaAgent(
        model=create_llm(
            provider=os.getenv("LLM_PROVIDER"),
            model=os.getenv("LLM_MODEL"),
        ),
        tools=_make_tools(),
        special_instructions=_SYSTEM,
        cuga_folder=str(_DIR / ".cuga"),
    )
```

### 7. FastAPI app (`_web(port)`)
Required endpoints:
- `POST /ask` — accepts `{"question": str}`, returns `{"answer": str}`
- `GET /` — serves `_HTML` as `HTMLResponse`

Optional but common:
- Data endpoints (`GET /items`, `POST /items/{id}/action`)
- Settings endpoints (`GET /settings`, `POST /settings/...`)
- Background task via `@app.on_event("startup")` + `asyncio.create_task()`

Import `_HTML` from `ui.py`:
```python
from ui import _HTML
```

### 8. CLI entry point
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=YOUR_PORT)
    parser.add_argument("--provider", "-p", default=None,
        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"])
    parser.add_argument("--model", "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    print(f"\n  Your App Name  →  http://127.0.0.1:{args.port}\n")
    _web(args.port)
```

---

## `ui.py` Structure

Export a single string `_HTML` — a fully self-contained HTML page. Requirements:
- **Dark theme** — background `#0f1117`, cards `#1a1a2e`, borders `#2d2d4a`
- **Sticky header** — app name + live status badge
- **Two-panel layout** — left: chat; right: result display
- **Chat panel** — input field + Send button + 6–10 clickable prompt chips
- Call `POST /ask` for the agent; render the response in both the chat and the right panel
- **Right panel**: show the latest agent result in a formatted card. Only add auto-refresh (every 10–15 seconds) if your app has genuine background state that changes on its own (e.g. a live feed, a price ticker). Do not add polling just to satisfy a UI checklist.
- No external JS/CSS dependencies — vanilla JS only

---

## LLM Provider (handled for you)

`_llm.py` is shared across all apps — it lives at `apps/_llm.py`. Call `create_llm(provider, model)` and it handles everything. Supported providers: `rits`, `anthropic`, `openai`, `watsonx`, `litellm`, `ollama`. Read env vars `LLM_PROVIDER` and `LLM_MODEL` — don't hardcode a provider.

---

## Required Environment Variables

CUGA always requires these environment variables to be set before starting any app:

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Always | The LLM backend to use — `rits` \| `anthropic` \| `openai` \| `watsonx` \| `litellm` \| `ollama` |
| `LLM_MODEL` | Always | The model name for the chosen provider (e.g. `llama-3-3-70b-instruct`, `claude-sonnet-4-6`) |
| `AGENT_SETTING_CONFIG` | Always | Path to the agent settings TOML file. A minimal starter file is at `/Users/anu/Documents/GitHub/cuga-agent-apr10/src/cuga/settings.toml` — copy it and point this var at your copy. |
| `RITS_API_KEY` | When using RITS | API key for the RITS inference service |
| `ANTHROPIC_API_KEY` | When using Anthropic | API key for Anthropic Claude |
| `OPENAI_API_KEY` | When using OpenAI | API key for OpenAI |

### RITS

When using RITS, set `AGENT_SETTING_CONFIG` to point at `settings.rits.toml`:

```bash
export LLM_PROVIDER=rits
export LLM_MODEL=llama-3-3-70b-instruct
export AGENT_SETTING_CONFIG=/path/to/settings.rits.toml
export RITS_API_KEY=<your-key>
```

The `settings.rits.toml` file configures RITS-specific parameters (base URL, timeouts, retry policy). Without it, the agent will not start correctly on RITS.

### Anthropic / OpenAI

```bash
export LLM_PROVIDER=anthropic
export LLM_MODEL=claude-sonnet-4-6
export AGENT_SETTING_CONFIG=/path/to/settings.toml
export ANTHROPIC_API_KEY=<your-key>
```

---

## Env Vars

- Always document `LLM_PROVIDER`, `LLM_MODEL`, and `AGENT_SETTING_CONFIG` in the README for every app
- If your app needs API keys beyond the LLM, document them in `.env.example` using the established format
- If no external API is needed — use free/public APIs (CoinGecko, Wikipedia REST, wttr.in, Nominatim) to avoid key requirements
- Env vars should have sensible defaults where possible

---

## Port

Assign a port that is unlikely to be used by other applications.

Document it in the README.

---

## Definition of Done

Before handing it back:

1. `python3 main.py` starts without errors
2. Opening the browser shows a working UI
3. The chat panel successfully calls the agent and shows a response
4. The right panel displays real output (not hardcoded placeholder text)
5. The app works with at least one LLM provider (`--provider anthropic` or `--provider openai`)
6. README documents the port, env vars, and 3+ example prompts the user can try

---

## What NOT to do

- No separate React/Vue frontend
- No Docker setup (that's handled at the repo level)
- No external CSS frameworks
- No hardcoded provider or model name
- No `global` state that breaks if two users hit the server simultaneously — use `thread_id` on agent invocations to keep sessions separate
- Don't add features that weren't asked for
- Don't add auto-refresh polling to the UI unless the app genuinely has live background data
