# Stock Alert — Architecture

## Design principle

**The app owns the schedule, state, and delivery. The agent owns price fetching
and threshold judgment.**

The threshold check is not a simple `price > X` rule — the agent contextualizes
the move ("continuing a 4-day rally" vs. "spike on low volume") and the skill
instructs it to include a `PRICE ALERT` sentinel only when the threshold is
genuinely crossed. The app reads that sentinel to trigger email.

---

## Component map

```
┌─────────────────────────────────────────────────────────────────┐
│  App layer (main.py)                                            │
│                                                                 │
│  ┌──────────────────────────────────────┐                       │
│  │ asyncio watch loop per symbol        │                       │
│  │ fires every N seconds (default 300)  │                       │
│  └──────────────┬───────────────────────┘                       │
│                 │                                               │
│                 ▼                                               │
│          ┌──────────────────┐                                   │
│          │   CugaAgent      │                                   │
│          │                  │                                   │
│          │ tools:           │                                   │
│          │  get_crypto_price│ ← CoinGecko API                  │
│          │  get_stock_quote │ ← Alpha Vantage API              │
│          │                  │                                   │
│          │ skill:           │                                   │
│          │  stock_alert.md  │                                   │
│          │                  │                                   │
│          │ → response       │                                   │
│          └──────┬───────────┘                                   │
│                 │                                               │
│                 ▼                                               │
│  "PRICE ALERT" in response?                                     │
│         │                                                       │
│    yes  ▼                                                       │
│  smtplib.send_email(response)   ← app-layer, no LLM            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  FastAPI web UI                                          │   │
│  │  /ask        → agent.invoke(symbol + question)          │   │
│  │  /watch/start → asyncio.create_task(_watch_loop(...))   │   │
│  │  /watch/stop  → task.cancel()                          │   │
│  │  /settings   → read/write .store.json                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## What the app owns

| Responsibility | How |
|---|---|
| Watch loop scheduling | `asyncio.create_task` + `asyncio.sleep` |
| Watch state (active symbols) | `_watches` dict in memory |
| State persistence | `.store.json` — restored on startup |
| Alert signal detection | `"PRICE ALERT" in response` — string check |
| Email delivery | `smtplib` — no LLM involved |
| Email config | `_email_config` dict — settable via UI, falls back to env vars |

## What CugaAgent owns

| Responsibility | How |
|---|---|
| Price fetching | `get_crypto_price` / `get_stock_quote` tool calls |
| Threshold judgment | Agent decides — skill instructs when to emit `PRICE ALERT` |
| Price contextualization | "crossed above after 4-day rally" vs. just a number |
| Free-form market Q&A | Fetches prices on demand, answers in natural language |

---

## Agent configuration

```python
CugaAgent(
    model   = create_llm(...),
    tools   = make_market_tools(),   # get_crypto_price, get_stock_quote
    plugins = [CugaSkillsPlugin(...)],
)
```

## Agent tools

| Tool | Source | Key needed |
|---|---|---|
| `get_crypto_price(symbol)` | CoinGecko `/simple/price` | No |
| `get_stock_quote(symbol)` | Alpha Vantage `GLOBAL_QUOTE` | `ALPHA_VANTAGE_API_KEY` |

Both tools are implemented in `market.py` and return structured data (price,
24h change %, volume, market cap where applicable).

---

## Watch loop data flow

```
1.  User: POST /watch/start { symbol: "BTC", threshold: 90000, direction: "above" }
2.  App: asyncio.create_task(_watch_loop(agent, "BTC", 90000, "above", interval=300))
3.  App: persist watch config to .store.json

Every 300 seconds:
4.  agent.invoke(
      "Check BTC (crypto) price now. Alert threshold: $90,000 (above).",
      thread_id="watch-btc"
    )
      → agent calls get_crypto_price("BTC") → { price: 90412, change_24h: +2.1% }
      → price > 90000 → agent includes "PRICE ALERT" in response
      → response: "PRICE ALERT\nBTC crossed above $90,000 at $90,412 (+2.1% 24h)..."

5.  App: "PRICE ALERT" in response → smtplib sends email
6.  await asyncio.sleep(300)
```

## Market query data flow

```
1.  User: POST /ask { symbol: "ETH", question: "compare with SOL", is_stock: false }
2.  agent.invoke("Symbol: ETH (crypto)\nQuestion: compare with SOL")
      → get_crypto_price("ETH") → { price: 3410, change_24h: +1.2% }
      → get_crypto_price("SOL") → { price: 142, change_24h: -0.4% }
      → "ETH $3,410 (+1.2%)  ·  SOL $142 (-0.4%)..."
3.  Return answer to UI
```

---

## Alert sentinel design

The skill instructs the agent to begin its response with `PRICE ALERT` when and
only when the threshold is crossed. The app checks for this exact string. This
keeps alert logic simple (one string check in the app) while still allowing the
agent to contextualize the move in the rest of the response. No JSON parsing,
no structured output schema needed.
