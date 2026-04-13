# Stock Alert

Monitor crypto and stock prices in a browser UI. Ask market questions on demand,
or set a threshold alert that emails you when a price is crossed.

**Port:** 18801

---

## Division of Responsibilities

### The App (main.py)

- **Manages watch state** — tracks active watches (symbol, threshold, direction) in memory and persists to `.store.json`
- **Runs the watch loop** — asyncio background task polls the agent on a configurable schedule
- **Decides to alert** — checks if the agent's response contains `"PRICE ALERT"` (string match, no LLM)
- **Sends email** — `smtplib` delivery when alert condition is met
- **Restores state on restart** — reads `.store.json` on startup and re-launches any persisted watches
- **Serves the web UI** — market query panel, price watch panel, email settings (FastAPI)

### CugaAgent

The agent fetches live prices using tools, checks whether a threshold is crossed,
and responds in natural language. It earns its place by contextualizing price
moves — not just reporting a number.

| Invocation | Input | Output |
|---|---|---|
| Watch loop fires | Symbol + threshold + direction | Price + whether threshold crossed |
| User market query | Symbol + free-form question | Natural-language answer with prices |

The watch loop message format is: `"Check BTC (crypto) price. Alert threshold: $90,000 (above)."` — the agent decides whether to include `"PRICE ALERT"` in its response. The app reads that signal to trigger email.

### Agent Tools

| Tool | What it does | API / Key required |
|---|---|---|
| `get_crypto_price` | Current price, 24h change, market cap | CoinGecko public API — no key |
| `get_stock_quote` | Current quote, change %, volume | Alpha Vantage — `ALPHA_VANTAGE_API_KEY` |

Provided by `market.make_market_tools()`.

### Agent Instructions

Tool usage, alert format (`PRICE ALERT` sentinel), and query format are inlined as `special_instructions` in `make_agent()` inside `main.py`.

---

## Quick Start

```bash
pip install -r requirements.txt
python main.py
# open http://127.0.0.1:18801
```

For stock quotes (crypto works without a key):
```bash
export ALPHA_VANTAGE_API_KEY=your_key   # free tier at alphavantage.co
```

---

## How the Watch Loop Works

```
App: asyncio.create_task(_watch_loop(agent, symbol, threshold, direction))
       │
       └── while True:
               agent.invoke("Check BTC price. Alert threshold: $90,000 (above).")
                     │
                     ▼
               agent calls get_crypto_price("BTC")
                     │
                     ▼
               price > $90,000?
                 yes → "PRICE ALERT\nBTC crossed above $90,412..."
                 no  → "BTC at $88,200 — below threshold. No action."
                     │
                     ▼
               App: "PRICE ALERT" in response?
                 yes → smtplib.send_email(response)
               await asyncio.sleep(300)
```

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `rits` \| `anthropic` \| `openai` \| `watsonx` \| `litellm` \| `ollama` |
| `LLM_MODEL` | Model name override |
| `ALPHA_VANTAGE_API_KEY` | Required for stock quotes |
| `SMTP_HOST` | SMTP server (default: `smtp.gmail.com`) |
| `SMTP_USERNAME` | Sender email |
| `SMTP_PASSWORD` | App password |
| `ALERT_TO` | Alert recipient email |

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Agent, watch loop, email, FastAPI UI |
| `market.py` | `make_market_tools()` — CoinGecko and Alpha Vantage API calls |
| `_SYSTEM` in `main.py` | Agent instructions — alert format, query format, tool usage (inlined) |
| `requirements.txt` | Python dependencies |
| `.store.json` | Persisted watches + email config (created on first save) |
