"""
Stock Alert Agent — web UI powered by cuga++
=============================================

Starts a browser UI with two panels:

  Market Query  — ask any price question (BTC price, compare ETH/SOL, AAPL quote)
  Price Watch   — configure a threshold alert; fires an email when crossed

Run:
    python main.py
    python main.py --port 8080
    python main.py --provider anthropic

Then open: http://127.0.0.1:18794

Prerequisites:
    Crypto (no key needed — CoinGecko public API):
        No setup required.

    Stocks (requires Alpha Vantage free API key):
        export ALPHA_VANTAGE_API_KEY=your_key   # get at alphavantage.co

    Email alerts (optional — falls back to server log if not set):
        export SMTP_HOST=smtp.gmail.com
        export SMTP_USERNAME=you@example.com
        export SMTP_PASSWORD=your_app_password
        export ALERT_TO=you@example.com

Environment variables:
    LLM_PROVIDER    rits | anthropic | openai | ollama | watsonx | litellm
    LLM_MODEL       model override
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

_DIR       = Path(__file__).parent
_DEMOS_DIR = _DIR.parent

for _p in [str(_DIR), str(_DEMOS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistent store — .store.json next to main.py
# ---------------------------------------------------------------------------

import json

_STORE_PATH = _DIR / ".store.json"


def _load_store() -> dict:
    try:
        return json.loads(_STORE_PATH.read_text()) if _STORE_PATH.exists() else {}
    except Exception as exc:
        log.warning("Could not read store: %s", exc)
        return {}


def _save_store(data: dict) -> None:
    try:
        _STORE_PATH.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        log.warning("Could not write store: %s", exc)


def _update_store(**fields) -> None:
    data = _load_store()
    data.update(fields)
    _save_store(data)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

_SYSTEM = """\
# Stock Alert

You are a market monitoring assistant. You watch prices and surface alerts that are actually worth attention.

## Tools available

| Tool | When to use |
|---|---|
| `get_crypto_price` | Fetch current price and 24h change for a cryptocurrency (BTC, ETH, SOL, etc.) |
| `get_stock_quote` | Fetch current price and change for a stock ticker (AAPL, TSLA, NVDA, etc.) |

Always call the appropriate tool before answering. Never guess a price.

## Watch mode — threshold alerts

When given a symbol and a threshold:

1. Fetch the current price with the appropriate tool
2. Compare against the threshold

**If the threshold is crossed:**
- Lead with `PRICE ALERT` on its own line
- State the symbol, current price, and which direction (crossed above / dropped below)
- Include the 24h change %
- One sentence of context: is this a big move? is it continuing a trend?
- Keep it under 5 lines total

**If the threshold is NOT crossed:**
- One line: `{SYMBOL} at ${price} — {direction} alert at ${threshold}. No action needed.`
- Nothing else

## Watch mode — no threshold

When given a symbol with no threshold, report a concise status:
`{SYMBOL} ${price} ({change%} 24h)`

## Query mode — on-demand questions

When a user asks a free-form market question:
1. Identify the symbol(s) from the query
2. Call the appropriate tool(s)
3. Answer directly with price, change, and any directly relevant data the tool returns
4. Be concise — one to three lines

For comparisons ("compare ETH and SOL"), call both tools then summarise side by side.

## Format rules

- Always include the 24h change % when available
- Dollar amounts: use commas for thousands (`$84,200`)
- Change %: always include sign (`+2.4%`, `-1.1%`)
- Never include disclaimers, "not financial advice", or hedging language
- Never fabricate data — if a tool call fails, say so clearly
"""


def make_agent():
    from cuga import CugaAgent
    from market import make_market_tools
    from _llm import create_llm

    return CugaAgent(
        model=create_llm(
            provider=os.getenv("LLM_PROVIDER"),
            model=os.getenv("LLM_MODEL"),
        ),
        tools=make_market_tools(),
        special_instructions=_SYSTEM,
        cuga_folder=str(_DIR / ".cuga"),
    )


# ---------------------------------------------------------------------------
# Email — in-memory config (UI-settable, falls back to env vars)
# ---------------------------------------------------------------------------

_email_config: dict = {}


def _get_email_cfg() -> dict:
    """Merge env vars (base) with UI-supplied config (override)."""
    return {
        "host":     _email_config.get("host")     or os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "user":     _email_config.get("user")     or os.getenv("SMTP_USERNAME", ""),
        "password": _email_config.get("password") or os.getenv("SMTP_PASSWORD", ""),
        "to":       _email_config.get("to")       or os.getenv("ALERT_TO", ""),
    }


def _send_alert(symbol: str, body: str) -> None:
    cfg = _get_email_cfg()
    if not (cfg["to"] and cfg["user"] and cfg["password"]):
        log.info("[ALERT — email not configured] %s", body)
        return

    msg            = MIMEText(body)
    msg["Subject"] = f"Stock Alert — {symbol}"
    msg["From"]    = cfg["user"]
    msg["To"]      = cfg["to"]

    try:
        with smtplib.SMTP_SSL(cfg["host"], 465) as smtp:
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        log.info("Alert email sent → %s", cfg["to"])
    except Exception as exc:
        log.error("Failed to send alert email: %s", exc)


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------

async def _watch_loop(
    agent,
    symbol: str,
    threshold: float,
    direction: str,
    is_stock: bool,
    interval_s: int = 300,
) -> None:
    asset = "stock" if is_stock else "crypto"
    prompt = (
        f"Check {symbol} ({asset}) price now.\n"
        f"Alert threshold: ${threshold:,.2f} ({direction})."
    )
    while True:
        try:
            result = await agent.invoke(prompt, thread_id=f"watch-{symbol.lower()}")
            answer = result.answer
            log.info("[WATCH] %s", answer)
            if "PRICE ALERT" in answer:
                _send_alert(symbol, answer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("Watch error: %s", exc)
        await asyncio.sleep(interval_s)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class AskReq(BaseModel):
    symbol: str
    question: str
    is_stock: bool = False


class WatchReq(BaseModel):
    symbol: str
    threshold: float
    direction: str        # "above" | "below"
    is_stock: bool = False


class EmailConfigReq(BaseModel):
    host: str = "smtp.gmail.com"
    user: str
    password: str
    to: str


class ApiConfigReq(BaseModel):
    alpha_vantage_key: str


class WatchStopReq(BaseModel):
    symbol: str


class EmailSendReq(BaseModel):
    subject: str
    body: str


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

def _web(port: int) -> None:
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="Stock Alert · CugaAgent", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    _agent = make_agent()
    _watches: dict[str, dict] = {}   # symbol → {"task": Task, "config": dict}

    # -- restore persisted state on startup ----------------------------------
    _stored = _load_store()

    if _stored.get("email"):
        global _email_config
        _email_config = _stored["email"]
        log.info("Restored email config → %s", _email_config.get("to"))

    if _stored.get("alpha_vantage_key"):
        os.environ["ALPHA_VANTAGE_API_KEY"] = _stored["alpha_vantage_key"]
        log.info("Restored Alpha Vantage key")

    def _start_watch(cfg: dict):
        symbol = cfg["symbol"]
        task   = asyncio.get_event_loop().create_task(
            _watch_loop(_agent, symbol, cfg["threshold"], cfg["direction"], cfg["is_stock"])
        )
        _watches[symbol] = {"task": task, "config": {**cfg, "email_to": _get_email_cfg()["to"] or "(not configured)"}}

    def _persist_watches():
        _update_store(watches=[w["config"] for w in _watches.values() if not w["task"].done()])

    for cfg in _stored.get("watches", []):
        _start_watch(cfg)
        log.info("Restored watch: %s", cfg)

    @app.post("/ask")
    async def ask(req: AskReq):
        symbol = req.symbol.strip().upper()
        asset  = "stock" if req.is_stock else "crypto"
        prompt = f"Symbol: {symbol} ({asset})\nQuestion: {req.question}"
        try:
            result = await _agent.invoke(prompt, thread_id=f"query-{symbol.lower()}")
            return {"answer": result.answer}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/watch/start")
    async def watch_start(req: WatchReq):
        symbol = req.symbol.strip().upper()
        # cancel existing watch for this symbol if already running
        if symbol in _watches and not _watches[symbol]["task"].done():
            _watches[symbol]["task"].cancel()

        cfg = {"symbol": symbol, "threshold": req.threshold,
               "direction": req.direction, "is_stock": req.is_stock}
        _start_watch(cfg)
        _persist_watches()
        log.info("Watch started: %s %s $%.2f", symbol, req.direction, req.threshold)
        return {"status": "started", **_watches[symbol]["config"]}

    @app.post("/watch/stop")
    async def watch_stop(req: WatchStopReq):
        symbol = req.symbol.strip().upper()
        if symbol in _watches:
            if not _watches[symbol]["task"].done():
                _watches[symbol]["task"].cancel()
            del _watches[symbol]
        _persist_watches()
        return {"status": "stopped", "symbol": symbol}

    @app.get("/watch/status")
    def watch_status():
        # prune completed tasks
        dead = [s for s, w in _watches.items() if w["task"].done()]
        for s in dead:
            del _watches[s]
        return [w["config"] for w in _watches.values()]

    @app.post("/api/config")
    def api_config(req: ApiConfigReq):
        if req.alpha_vantage_key:
            os.environ["ALPHA_VANTAGE_API_KEY"] = req.alpha_vantage_key
            _update_store(alpha_vantage_key=req.alpha_vantage_key)
            log.info("Alpha Vantage key updated")
        return {"status": "saved", "alpha_vantage": bool(req.alpha_vantage_key)}

    @app.get("/api/status")
    def api_status():
        return {"alpha_vantage_configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY"))}

    @app.post("/email/send")
    def email_send(req: EmailSendReq):
        _send_alert(req.subject, req.body)
        return {"status": "sent"}

    @app.post("/email/config")
    def email_config(req: EmailConfigReq):
        global _email_config
        _email_config = {"host": req.host, "user": req.user, "password": req.password, "to": req.to}
        _update_store(email=_email_config)
        log.info("Email config updated → %s via %s", req.to, req.host)
        return {"status": "saved", "to": req.to, "host": req.host, "user": req.user}

    @app.get("/email/status")
    def email_status():
        cfg = _get_email_cfg()
        configured = bool(cfg["to"] and cfg["user"] and cfg["password"])
        return {"configured": configured, "to": cfg["to"], "host": cfg["host"], "user": cfg["user"]}

    @app.get("/", response_class=HTMLResponse)
    def ui():
        return _WEB_HTML

    print(f"\n  Stock Alert · CugaAgent  →  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_WEB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Alert · CugaAgent</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0f0f13;color:#e2e2e8;min-height:100vh;padding:40px 24px 80px}
header{text-align:center;margin-bottom:32px}
h1{font-size:22px;font-weight:700;color:#fff;margin-bottom:4px}
.sub{font-size:13px;color:#6b6b7e}.sub span{color:#7c7cf8;font-weight:500}
.layout{display:grid;grid-template-columns:280px 1fr;gap:20px;max-width:1020px;margin:0 auto;align-items:start}
@media(max-width:720px){.layout{grid-template-columns:1fr}}
.card{background:#1a1a24;border:1px solid #2e2e40;border-radius:12px;padding:18px;margin-bottom:16px}
.card:last-child{margin-bottom:0}
.card-title{font-size:11px;font-weight:700;color:#6b6b7e;letter-spacing:.08em;text-transform:uppercase;margin-bottom:14px}
.section-label{font-size:11px;font-weight:600;color:#4a4a60;letter-spacing:.06em;text-transform:uppercase;margin:16px 0 10px;padding-top:16px;border-top:1px solid #1e1e2e}
.section-label:first-child{margin-top:0;padding-top:0;border-top:none}
label{display:block;font-size:11px;color:#6b6b7e;margin-bottom:4px;font-weight:500;text-transform:uppercase;letter-spacing:.05em}
input[type=text],input[type=number],input[type=password],select{width:100%;background:#0f0f13;border:1px solid #2e2e40;border-radius:7px;padding:8px 12px;font-size:13px;color:#e2e2e8;outline:none;transition:border-color .15s}
input:focus,select:focus{border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.12)}
input::placeholder{color:#4a4a60}
.field{margin-bottom:10px}
.field:last-of-type{margin-bottom:0}
.row{display:flex;gap:8px;margin-top:10px}.row>*{flex:1}
.row-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:10px}
button{background:#6366f1;color:#fff;border:none;border-radius:7px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s,opacity .15s;white-space:nowrap;width:100%;margin-top:10px}
button:hover{background:#4f52d9}button:disabled{opacity:.45;cursor:default}
button.danger{background:#7f1d1d;color:#fca5a5;margin-top:0}
button.danger:hover{background:#991b1b}
.status-row{display:flex;align-items:center;gap:7px;margin-top:10px;padding:8px 12px;background:#0f0f13;border:1px solid #1e1e2e;border-radius:7px;font-size:12px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.on{background:#10b981;box-shadow:0 0 5px #10b981}.dot.off{background:#374151}
.status-text{color:#6b6b7e;flex:1}.status-text strong{color:#e2e2e8}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:#111827;border:1px solid #1e293b;border-radius:6px;padding:5px 10px;font-size:12px;color:#94a3b8;cursor:pointer;transition:background .1s}
.chip:hover{background:#1e293b;color:#e2e8f0}
.result{margin-top:14px;padding:14px;background:#111827;border:1px solid #1e293b;border-radius:9px;font-size:14px;line-height:1.7;color:#e2e8f0;display:none}
.result.visible{display:block}
.thinking{color:#6b6b7e;font-style:italic;font-size:13px}
.spinner{display:inline-block;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.fadein{animation:fadein .2s ease}
</style>
</head>
<body>
<header>
  <h1>Stock Alert</h1>
  <p class="sub">Powered by <span>CugaAgent</span> · live market data</p>
</header>

<div class="layout">

  <!-- ══ Left panel — settings ══ -->
  <div>

    <div class="card">

      <div class="section-label">API Keys</div>
      <div class="field">
        <label>Alpha Vantage <span style="font-weight:400;text-transform:none;letter-spacing:0;color:#4a4a60">— stocks</span></label>
        <input id="avKey" type="password" placeholder="get free key at alphavantage.co" />
      </div>
      <button id="apiSaveBtn" onclick="saveApi()">Save key</button>
      <div class="status-row">
        <span class="dot off" id="apiDot"></span>
        <span class="status-text" id="apiLabel">Not configured</span>
      </div>

      <div class="section-label">Email Alerts</div>
      <div class="field">
        <label>SMTP Host</label>
        <input id="eHost" type="text" placeholder="smtp.gmail.com" value="smtp.gmail.com" />
      </div>
      <div class="field">
        <label>Username</label>
        <input id="eUser" type="text" placeholder="you@example.com" />
      </div>
      <div class="field">
        <label>Password</label>
        <input id="ePassword" type="password" placeholder="app password" />
      </div>
      <div class="field">
        <label>Send alerts to</label>
        <input id="eTo" type="text" placeholder="recipient@example.com" />
      </div>
      <button id="emailSaveBtn" onclick="saveEmail()">Save email settings</button>
      <div class="status-row">
        <span class="dot off" id="emailDot"></span>
        <span class="status-text" id="emailLabel">Not configured</span>
      </div>

    </div>

  </div>

  <!-- ══ Right panel — query + watch ══ -->
  <div>

    <!-- Market Query -->
    <div class="card">
      <div class="card-title">Market Query</div>
      <div class="row" style="margin-top:0">
        <div>
          <label>Symbol</label>
          <input id="qSymbol" type="text" placeholder="BTC  ETH  AAPL  TSLA …" style="text-transform:uppercase" />
        </div>
        <div style="flex:0 0 auto;width:110px">
          <label>Type</label>
          <select id="qType">
            <option value="crypto">Crypto</option>
            <option value="stock">Stock</option>
          </select>
        </div>
      </div>
      <div class="field" style="margin-top:10px">
        <label>Question</label>
        <div class="row" style="margin-top:0">
          <input id="qQuestion" type="text" placeholder="What is the current price?" onkeydown="if(event.key==='Enter')ask()" />
          <button id="askBtn" onclick="ask()" style="width:auto;margin-top:0">Ask</button>
        </div>
      </div>
      <div class="chips">
        <span class="chip" onclick="quickAsk('What is the current price and 24h change?')">Price + 24h change</span>
        <span class="chip" onclick="quickAsk('What is the 24h trading volume? Is it high or low?')">Volume</span>
        <span class="chip" onclick="quickAsk('What is the market cap?')">Market cap</span>
        <span class="chip" onclick="quickAsk('Is this price move notable or just normal volatility?')">Notable move?</span>
        <span class="chip" onclick="quickAsk('Give me a quick bull or bear read on this asset right now.')">Bull / bear?</span>
        <span class="chip" onclick="quickAsk('Is this a good entry point or should I wait?')">Entry signal?</span>
        <span class="chip" onclick="quickAsk('What would a 5% swing from the current price look like in dollars?')">5% swing in $</span>
        <span class="chip" onclick="quickAsk('Is this near a psychological price level like a round number?')">Key level?</span>
        <span class="chip" onclick="quickAsk('How has this asset moved over the last 24 hours — steady or volatile?')">24h movement</span>
        <span class="chip" onclick="quickAsk('What is the risk if I enter at the current price?')">Risk at entry</span>
        <span class="chip" onclick="quickAsk('Compare BTC and ETH — which is performing better today?')">BTC vs ETH</span>
        <span class="chip" onclick="quickAsk('Compare SOL, AVAX, and BNB prices right now.')">SOL / AVAX / BNB</span>
        <span class="chip" onclick="quickAsk('Summarise the current market conditions for this asset.')">Market summary</span>
        <span class="chip" onclick="quickAsk('Should I be concerned about this price movement?')">Cause for concern?</span>
        <span class="chip" onclick="quickAsk('Where would a reasonable stop loss be from the current price?')">Stop loss level</span>
      </div>
      <div class="result" id="askResult"></div>
      <div id="emailNowRow" style="display:none;margin-top:8px;text-align:right">
        <button id="emailNowBtn" onclick="emailNow()" style="width:auto;padding:6px 14px;font-size:12px;background:#1e1e2e;border:1px solid #2e2e40;color:#94a3b8">Email this</button>
      </div>
    </div>

    <!-- Price Watch -->
    <div class="card">
      <div class="card-title">Price Watch</div>
      <div class="row-3">
        <div>
          <label>Symbol</label>
          <input id="wSymbol" type="text" placeholder="BTC" style="text-transform:uppercase" />
        </div>
        <div>
          <label>Type</label>
          <select id="wType">
            <option value="crypto">Crypto</option>
            <option value="stock">Stock</option>
          </select>
        </div>
        <div>
          <label>Direction</label>
          <select id="wDirection">
            <option value="above">Above</option>
            <option value="below">Below</option>
          </select>
        </div>
      </div>
      <div class="field" style="margin-top:10px">
        <label>Threshold ($)</label>
        <input id="wThreshold" type="number" placeholder="90000" min="0" step="any" />
      </div>
      <div class="row" style="margin-top:10px">
        <button onclick="startWatch()">Start Watch</button>
      </div>
      <div id="watchList" style="margin-top:12px"></div>
    </div>

  </div>
</div>

<script>
let _lastAnswer = '', _lastSymbol = ''

function quickAsk(q) {
  document.getElementById('qQuestion').value = q
  ask()
}

async function ask() {
  const symbol = document.getElementById('qSymbol').value.trim().toUpperCase()
  const q      = document.getElementById('qQuestion').value.trim()
  if (!symbol || !q) return
  const isStock = document.getElementById('qType').value === 'stock'

  const btn    = document.getElementById('askBtn')
  const result = document.getElementById('askResult')
  document.getElementById('emailNowRow').style.display = 'none'
  btn.disabled = true
  result.className = 'result visible fadein'
  result.innerHTML = '<span class="thinking"><span class="spinner">⟳</span> Thinking…</span>'

  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol, question: q, is_stock: isStock})
    })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    _lastAnswer = data.answer
    _lastSymbol = symbol
    result.innerHTML = renderAnswer(data.answer)
    document.getElementById('emailNowRow').style.display = ''
  } catch (err) {
    result.style.color = '#f87171'
    result.textContent = 'Error: ' + err.message
  } finally {
    btn.disabled = false
  }
}

async function emailNow() {
  if (!_lastAnswer) return
  const btn = document.getElementById('emailNowBtn')
  btn.disabled = true; btn.textContent = 'Sending…'
  try {
    const res = await fetch('/email/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({subject: `Stock Alert — ${_lastSymbol}`, body: _lastAnswer})
    })
    if (!res.ok) throw new Error(await res.text())
    btn.textContent = 'Sent ✓'
    btn.style.color = '#34d399'
    setTimeout(() => { btn.textContent = 'Email this'; btn.style.color = ''; btn.disabled = false }, 2500)
  } catch (err) {
    btn.textContent = 'Failed'
    btn.style.color = '#f87171'
    setTimeout(() => { btn.textContent = 'Email this'; btn.style.color = ''; btn.disabled = false }, 2500)
  }
}

function renderAnswer(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\\*\\*(.*?)\\*\\*/g,'<strong>$1</strong>')
    .replace(/\\b(\\+?-?\\d+\\.?\\d*%)\\b/g, s => `<span style="color:${s.startsWith('-')?'#f87171':'#34d399'};font-weight:600">${s}</span>`)
    .replace(/\\$[\\d,]+(?:\\.\\d+)?/g, s => `<span style="color:#818cf8;font-weight:600">${s}</span>`)
    .replace(/\\n/g,'<br>')
}

async function startWatch() {
  const symbol    = document.getElementById('wSymbol').value.trim().toUpperCase()
  const threshold = parseFloat(document.getElementById('wThreshold').value)
  const direction = document.getElementById('wDirection').value
  const isStock   = document.getElementById('wType').value === 'stock'
  if (!symbol || isNaN(threshold)) return

  try {
    const res = await fetch('/watch/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol, threshold, direction, is_stock: isStock})
    })
    if (!res.ok) throw new Error(await res.text())
    await refreshWatchList()
    document.getElementById('wSymbol').value    = ''
    document.getElementById('wThreshold').value = ''
  } catch (err) {
    alert('Failed to start watch: ' + err.message)
  }
}

async function stopWatch(symbol) {
  await fetch('/watch/stop', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({symbol})
  })
  await refreshWatchList()
}

async function refreshWatchList() {
  const res   = await fetch('/watch/status')
  const list  = await res.json()
  const el    = document.getElementById('watchList')
  if (!list.length) {
    el.innerHTML = '<div class="status-row"><span class="dot off"></span><span class="status-text">No active watches</span></div>'
    return
  }
  el.innerHTML = list.map(w => {
    const dir   = w.direction === 'above' ? '↑' : '↓'
    const email = w.email_to && w.email_to !== '(not configured)' ? ` · ${w.email_to}` : ''
    return `<div class="status-row" style="margin-bottom:6px">
      <span class="dot on"></span>
      <span class="status-text"><strong>${w.symbol}</strong> ${dir} $${Number(w.threshold).toLocaleString()}${email}</span>
      <button class="danger" onclick="stopWatch('${w.symbol}')" style="width:auto;margin:0;padding:4px 10px;font-size:12px">Stop</button>
    </div>`
  }).join('')
}

// ── API Keys ───────────────────────────────────────────────────────────────

async function saveApi() {
  const key = document.getElementById('avKey').value.trim()
  if (!key) return
  const btn = document.getElementById('apiSaveBtn')
  btn.disabled = true; btn.textContent = '…'
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({alpha_vantage_key: key})
    })
    if (!res.ok) throw new Error(await res.text())
    setApiUI(true)
  } catch (err) {
    alert('Failed to save API key: ' + err.message)
  } finally {
    btn.disabled = false; btn.textContent = 'Save'
  }
}

function setApiUI(configured) {
  document.getElementById('apiDot').className = 'dot ' + (configured ? 'on' : 'off')
  document.getElementById('apiLabel').textContent = configured
    ? 'Alpha Vantage key configured'
    : 'Alpha Vantage key not set'
}

fetch('/api/status').then(r => r.json()).then(s => setApiUI(s.alpha_vantage_configured))

// ── Email ──────────────────────────────────────────────────────────────────

async function saveEmail() {
  const host     = document.getElementById('eHost').value.trim()
  const user     = document.getElementById('eUser').value.trim()
  const password = document.getElementById('ePassword').value
  const to       = document.getElementById('eTo').value.trim()
  if (!user || !password || !to) return

  const btn = document.getElementById('emailSaveBtn')
  btn.disabled = true; btn.textContent = '…'
  try {
    const res = await fetch('/email/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({host, user, password, to})
    })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    setEmailUI(true, data)
  } catch (err) {
    alert('Failed to save email config: ' + err.message)
  } finally {
    btn.disabled = false; btn.textContent = 'Save'
  }
}

function setEmailUI(configured, cfg) {
  document.getElementById('emailDot').className = 'dot ' + (configured ? 'on' : 'off')
  const label = document.getElementById('emailLabel')
  if (configured && cfg) {
    label.innerHTML = `Alerts → <strong>${cfg.to}</strong> via ${cfg.host}`
  } else {
    label.innerHTML = 'Not configured'
  }
}

// Restore state on load
fetch('/email/status').then(r => r.json()).then(s => {
  if (s.configured) {
    document.getElementById('eHost').value = s.host || 'smtp.gmail.com'
    document.getElementById('eUser').value = s.user || ''
    document.getElementById('eTo').value   = s.to   || ''
    setEmailUI(true, s)
  }
})

refreshWatchList()
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Stock Alert Agent — web UI")
    parser.add_argument("--port",     type=int, default=18794)
    parser.add_argument("--provider", "-p", default=None,
                        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"])
    parser.add_argument("--model",    "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    _web(args.port)


if __name__ == "__main__":
    main()
