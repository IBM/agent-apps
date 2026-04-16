"""
Architecture Diagram Generator — web UI powered by CugaAgent
=============================================================

Describe a system in plain English, get a rendered architecture diagram.
The agent generates Mermaid.js code and the browser renders it as SVG.
Supports iterative refinement — ask the agent to add, remove, or change
components and it updates the diagram.

Run:
    python main.py
    python main.py --port 18804
    python main.py --provider anthropic

Then open: http://127.0.0.1:18804

Environment variables:
    LLM_PROVIDER      rits | anthropic | openai | ollama | watsonx | litellm
    LLM_MODEL         model override
    TAVILY_API_KEY    (optional) Tavily search key for researching unfamiliar systems
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
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
# Persistent store
# ---------------------------------------------------------------------------

_STORE_PATH = _DIR / ".store.json"


def _load_store() -> dict:
    try:
        return json.loads(_STORE_PATH.read_text()) if _STORE_PATH.exists() else {}
    except Exception:
        return {}


def _save_store(data: dict) -> None:
    _STORE_PATH.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# SQLite diagram log
# ---------------------------------------------------------------------------

_DB_PATH = _DIR / "diagrams.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS diagram_log (
    id         TEXT PRIMARY KEY,
    query      TEXT NOT NULL,
    response   TEXT NOT NULL,
    mermaid    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _init_db() -> None:
    with _db() as con:
        con.execute(_CREATE_SQL)


def _save_diagram(query: str, response: str, mermaid: str = "") -> dict:
    rid = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).isoformat()
    with _db() as con:
        con.execute(
            "INSERT INTO diagram_log (id, query, response, mermaid, created_at) VALUES (?,?,?,?,?)",
            (rid, query, response, mermaid, now),
        )
    return {"id": rid, "query": query, "response": response, "mermaid": mermaid, "created_at": now}


def _list_diagrams(limit: int = 30) -> list[dict]:
    with _db() as con:
        rows = con.execute(
            "SELECT * FROM diagram_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Web search tool (optional — for researching unfamiliar systems)
# ---------------------------------------------------------------------------

def _make_tools():
    from langchain_core.tools import tool as _tool

    @_tool
    def web_search(query: str, max_results: int = 5) -> str:
        """
        Search the web for information about a technology, architecture
        pattern, or system design.  Use this when the user asks about a
        system you want to verify details on before diagramming.

        Args:
            query:       Search query string.
            max_results: Number of results to return (default 5).
        """
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return json.dumps({"error": "TAVILY_API_KEY not set — web search unavailable. Proceed using your own knowledge."})
        try:
            from tavily import TavilyClient
            client  = TavilyClient(api_key=api_key)
            results = client.search(query, max_results=max_results)
            return json.dumps(results, ensure_ascii=False)
        except ImportError:
            return json.dumps({"error": "tavily-python not installed"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return [web_search]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = r"""
# Architecture Diagram Generator

You are an expert software architect who creates clear, accurate architecture
diagrams from natural-language descriptions.  You produce Mermaid.js diagram
code that renders in the browser.

## Your workflow

1. Read the user's description carefully.
2. Decide which Mermaid diagram type best fits (see reference below).
3. Generate valid Mermaid code inside a fenced code block:  ```mermaid ... ```
4. BELOW the diagram, provide a brief explanation of the architecture:
   what each component does and why it's there.
5. If the user asks to modify an existing diagram, update the Mermaid code —
   do not start from scratch unless asked.

## Choosing the right diagram type

| User is describing… | Use this type |
|---|---|
| System components and how they connect | `graph TD` or `graph LR` |
| A request/response flow over time | `sequenceDiagram` |
| Database tables and relationships | `erDiagram` |
| Object-oriented class structure | `classDiagram` |
| States and transitions (e.g. order lifecycle) | `stateDiagram-v2` |

Default to `graph TD` (top-down flowchart) when uncertain.

## Mermaid syntax reference with examples

### Flowchart (graph)

```mermaid
graph TD
    Client["Browser Client"]
    LB["Load Balancer"]
    S1["App Server 1"]
    S2["App Server 2"]
    DB[("PostgreSQL")]
    Cache[("Redis Cache")]

    Client -->|HTTPS| LB
    LB --> S1
    LB --> S2
    S1 --> DB
    S2 --> DB
    S1 -.->|cache read| Cache
    S2 -.->|cache read| Cache
```

Key syntax rules for flowcharts:
- Node IDs must be alphanumeric (no spaces, no hyphens). Use: `APIGateway`, `S1`, `UserSvc`
- Labels with special characters MUST be in double quotes: `APIGateway["API Gateway"]`
- Database/cylinder shape: `DB[("PostgreSQL")]`
- Dotted lines: `A -.-> B` or `A -.->|label| B`
- Solid lines: `A --> B` or `A -->|label| B`
- Subgraphs for grouping:
  ```
  subgraph VPC["AWS VPC"]
      S1["Server 1"]
      S2["Server 2"]
  end
  ```
- NEVER use parentheses `()` in labels without wrapping in quotes
- NEVER use hyphens in node IDs — use camelCase or underscores

### Sequence diagram

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as API Server
    participant Auth as Auth Service
    participant DB as Database

    User->>FE: Click login
    FE->>API: POST /auth/login
    API->>Auth: Validate credentials
    Auth->>DB: Query user record
    DB-->>Auth: User data
    Auth-->>API: JWT token
    API-->>FE: 200 OK + token
    FE-->>User: Redirect to dashboard

    Note over API,Auth: Token expires in 1 hour
```

Key syntax rules for sequence diagrams:
- `actor` for human participants, `participant` for systems
- Solid arrow: `->>` (request)
- Dashed arrow: `-->>` (response)
- Aliases: `participant API as "API Server"`
- Notes: `Note over A,B: text` or `Note right of A: text`
- Loops: `loop Every 30s` / `end`
- Alt paths: `alt Success` / `else Failure` / `end`

### ER diagram

```mermaid
erDiagram
    USER {
        int id PK
        string email
        string name
        datetime created_at
    }
    ORDER {
        int id PK
        int user_id FK
        decimal total
        string status
    }
    ORDER_ITEM {
        int id PK
        int order_id FK
        int product_id FK
        int quantity
    }
    PRODUCT {
        int id PK
        string name
        decimal price
    }

    USER ||--o{ ORDER : places
    ORDER ||--|{ ORDER_ITEM : contains
    PRODUCT ||--o{ ORDER_ITEM : "included in"
```

Key syntax rules for ER diagrams:
- Relationship symbols: `||--o{` (one-to-many), `||--|{` (one-to-many required),
  `}o--o{` (many-to-many), `||--||` (one-to-one)
- Every relationship needs a label after the colon
- Field types: `int`, `string`, `datetime`, `decimal`, `boolean`
- PK and FK markers go after the field name

### State diagram

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Review: Submit
    Review --> Approved: Approve
    Review --> Draft: Request changes
    Approved --> Published: Publish
    Published --> Archived: Archive
    Archived --> [*]

    state Review {
        [*] --> Pending
        Pending --> InReview: Assign reviewer
        InReview --> [*]
    }
```

Key syntax rules for state diagrams:
- Start/end: `[*]`
- Transitions: `State1 --> State2: Label`
- Nested states use `state Name { ... }`
- No quotes needed for simple state names
- Use camelCase for multi-word state names: `InReview`

## Critical rules

- ALWAYS wrap the diagram in a ```mermaid fenced code block
- ALWAYS define nodes before using them in connections when using labels
- ALWAYS use double quotes for labels that contain spaces, special characters,
  parentheses, slashes, or colons
- NEVER use hyphens (-) in node IDs — use underscores or camelCase
- NEVER put spaces in node IDs
- Keep diagrams readable: 6-15 nodes is ideal. If a system has more components,
  group them with subgraphs or split into multiple diagrams
- If the user asks for changes to a previous diagram, reproduce the full updated
  Mermaid code — do not use pseudocode or partial snippets
- Below every diagram, include a brief "Components" section explaining what
  each node does and why it's in the architecture
- If you are unsure about a specific technology's architecture, use `web_search`
  to look it up before generating the diagram

## Iterative refinement

When the user says things like "add a cache", "remove the queue", "show me
the auth flow as a sequence diagram", or "make it more detailed":
1. Start from the previous Mermaid code
2. Apply the requested changes
3. Output the complete updated diagram (never a partial diff)
4. Briefly note what changed
"""


def make_agent():
    from cuga import CugaAgent
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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class AskReq(BaseModel):
    question: str


class CredentialsReq(BaseModel):
    tavily_key: str = ""


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

def _web(port: int) -> None:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse

    _init_db()

    app = FastAPI(title="Architecture Diagram Generator", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    _agent = make_agent()

    stored_key = _load_store().get("tavily_key", "")
    if stored_key and not os.getenv("TAVILY_API_KEY"):
        os.environ["TAVILY_API_KEY"] = stored_key

    @app.post("/ask")
    async def api_ask(req: AskReq):
        question = req.question.strip()
        if not question:
            return JSONResponse({"error": "Empty question"}, status_code=400)
        try:
            result = await _agent.invoke(question, thread_id="diagram")
            answer = result.answer

            # Extract mermaid code block for separate storage
            import re
            mermaid_match = re.search(r'```mermaid\s*\n(.*?)```', answer, re.DOTALL)
            mermaid_code = mermaid_match.group(1).strip() if mermaid_match else ""

            _save_diagram(question, answer, mermaid_code)
            return {"answer": answer, "mermaid": mermaid_code}
        except Exception as exc:
            log.error("Agent error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/diagrams")
    async def api_diagrams():
        return _list_diagrams()

    @app.get("/settings")
    async def api_settings():
        return {"tavily_configured": bool(os.getenv("TAVILY_API_KEY"))}

    @app.post("/settings/credentials")
    async def api_creds(req: CredentialsReq):
        data = _load_store()
        if req.tavily_key and not req.tavily_key.startswith("•"):
            os.environ["TAVILY_API_KEY"] = req.tavily_key
            data["tavily_key"] = req.tavily_key
        _save_store(data)
        return {"ok": True, "tavily_configured": bool(os.getenv("TAVILY_API_KEY"))}

    @app.get("/", response_class=HTMLResponse)
    async def ui():
        return HTMLResponse(_WEB_HTML)

    print(f"\n  Architecture Diagram Generator  →  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Architecture Diagram Generator</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:#0f0f13;color:#e2e2e8;min-height:100vh}

header{background:#1a1a24;border-bottom:1px solid #2e2e40;padding:14px 28px;
  display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10}
header h1{font-size:17px;font-weight:700;color:#fff}
.sub{font-size:12px;color:#6b6b7e}.sub span{color:#818cf8;font-weight:600}
.spacer{flex:1}

.layout{display:grid;grid-template-columns:280px 1fr;gap:20px;
  max-width:1280px;margin:0 auto;padding:20px 24px}
@media(max-width:720px){.layout{grid-template-columns:1fr}}

.card{background:#1a1a24;border:1px solid #2e2e40;border-radius:12px;
  padding:18px;margin-bottom:16px}
.card:last-child{margin-bottom:0}
.card-title{font-size:11px;font-weight:700;color:#6b6b7e;letter-spacing:.08em;
  text-transform:uppercase;margin-bottom:14px}
.section-label{font-size:11px;font-weight:600;color:#4a4a60;letter-spacing:.06em;
  text-transform:uppercase;margin:16px 0 10px;padding-top:16px;
  border-top:1px solid #1e1e2e}
.section-label:first-child{margin-top:0;padding-top:0;border-top:none}

label{display:block;font-size:11px;color:#6b6b7e;margin-bottom:4px;font-weight:500;
  text-transform:uppercase;letter-spacing:.05em}
input[type=text],input[type=password],textarea{width:100%;background:#0f0f13;
  border:1px solid #2e2e40;border-radius:7px;padding:8px 12px;font-size:13px;
  color:#e2e2e8;outline:none;transition:border-color .15s;font-family:inherit}
input:focus,textarea:focus{border-color:#818cf8;box-shadow:0 0 0 3px rgba(129,140,248,.1)}
input::placeholder,textarea::placeholder{color:#4a4a60}
textarea{resize:vertical;min-height:80px;line-height:1.5}
.field{margin-bottom:10px}

button{background:#6366f1;color:#fff;border:none;border-radius:7px;
  padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;
  transition:background .15s,opacity .15s;white-space:nowrap;width:100%;margin-top:10px}
button:hover{background:#4f46e5}
button:disabled{opacity:.45;cursor:default}
.btn-sm{padding:6px 12px;font-size:12px;width:auto;margin-top:0}
.btn-ghost{background:#1f2937;border:1px solid #374151;color:#9ca3af}
.btn-ghost:hover{background:#374151}

.status-row{display:flex;align-items:center;gap:7px;margin-top:10px;
  padding:8px 12px;background:#0f0f13;border:1px solid #1e1e2e;border-radius:7px;
  font-size:12px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.on{background:#10b981;box-shadow:0 0 5px #10b981}
.dot.off{background:#374151}
.status-text{color:#6b6b7e;flex:1}

.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}
.chip{background:#111827;border:1px solid #1e293b;border-radius:6px;
  padding:5px 10px;font-size:12px;color:#94a3b8;cursor:pointer;transition:all .15s}
.chip:hover{background:#6366f1;border-color:#6366f1;color:#fff}

.thinking{color:#6b6b7e;font-style:italic;font-size:13px}
.spinner{display:inline-block;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.fadein{animation:fadein .25s ease}

/* Diagram display */
#diagramPanel{display:none;margin-top:14px}
#diagramPanel.visible{display:block}
#diagramRender{background:#fff;border-radius:10px;padding:20px;text-align:center;
  min-height:200px;overflow-x:auto}
#diagramRender svg{max-width:100%;height:auto}
.diagram-actions{display:flex;gap:8px;margin-top:10px;justify-content:flex-end}
#diagramError{display:none;margin-top:10px;padding:10px 14px;background:#451a03;
  border:1px solid #78350f;border-radius:7px;font-size:12px;color:#fbbf24}

/* Explanation text */
#explanation{margin-top:14px;padding:14px;background:#111827;border:1px solid #1e293b;
  border-radius:9px;font-size:13px;line-height:1.7;color:#d1d5db;display:none}
#explanation.visible{display:block}
#explanation strong{color:#fff}
#explanation a{color:#818cf8}

/* History */
.hist-item{border:1px solid #2e2e40;border-radius:8px;margin-bottom:8px;overflow:hidden}
.hist-header{padding:10px 14px;display:flex;align-items:center;gap:8px;cursor:pointer}
.hist-header:hover{background:#1f2937}
.hist-query{font-size:12px;font-weight:600;color:#c5cae9;flex:1;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hist-time{font-size:10px;color:#6b7280}
.hist-toggle{font-size:11px;color:#4b5563}
.hist-body{padding:12px 14px;border-top:1px solid #2e2e40;background:#0f0f13;display:none}
.hist-body.open{display:block}
.empty{font-size:13px;color:#4b5563;text-align:center;padding:28px}
</style>
</head>
<body>

<header>
  <h1>Architecture Diagram Generator</h1>
  <p class="sub">Powered by <span>CugaAgent</span> + Mermaid.js</p>
  <div class="spacer"></div>
</header>

<div class="layout">

  <!-- ══ Left panel ══ -->
  <div>

    <div class="card">
      <div class="section-label">Settings</div>
      <div class="field">
        <label>Tavily key <span style="font-weight:400;text-transform:none;letter-spacing:0;color:#4a4a60">— optional, for research</span></label>
        <input id="tavilyKey" type="password" placeholder="tvly-…" />
      </div>
      <button id="saveBtn" onclick="saveCreds()">Save</button>
      <div class="status-row">
        <span class="dot off" id="apiDot"></span>
        <span class="status-text" id="apiLabel">Web search not configured</span>
      </div>
    </div>

    <div class="card">
      <div class="section-label">Diagram types</div>
      <p style="font-size:12px;color:#6b6b7e;line-height:1.7">
        The agent automatically picks the best diagram type:<br><br>
        <strong style="color:#e2e2e8">Flowchart</strong> — system components &amp; connections<br>
        <strong style="color:#e2e2e8">Sequence</strong> — request flows over time<br>
        <strong style="color:#e2e2e8">ER diagram</strong> — database schema<br>
        <strong style="color:#e2e2e8">State diagram</strong> — lifecycles &amp; transitions<br><br>
        <span style="color:#4a4a60">Or ask for a specific type: "show it as a sequence diagram"</span>
      </p>
    </div>

  </div>

  <!-- ══ Right panel ══ -->
  <div>

    <!-- Input -->
    <div class="card">
      <div class="card-title">Describe your system</div>
      <div class="chips">
        <span class="chip" onclick="ask(this.textContent)">Microservices e-commerce platform</span>
        <span class="chip" onclick="ask(this.textContent)">CI/CD pipeline from git push to production</span>
        <span class="chip" onclick="ask(this.textContent)">Real-time chat system with WebSockets</span>
        <span class="chip" onclick="ask(this.textContent)">RAG pipeline for document Q&A</span>
        <span class="chip" onclick="ask(this.textContent)">OAuth2 login flow as a sequence diagram</span>
        <span class="chip" onclick="ask(this.textContent)">Kafka event streaming architecture</span>
        <span class="chip" onclick="ask(this.textContent)">Order lifecycle as a state diagram</span>
        <span class="chip" onclick="ask(this.textContent)">E-commerce database schema as ER diagram</span>
      </div>
      <div style="display:flex;gap:8px;align-items:flex-end">
        <textarea id="chatInput" rows="2"
          placeholder="Describe the system or architecture you want to diagram…"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();ask()}"></textarea>
        <button class="btn-sm" id="chatSend" onclick="ask()"
          style="height:42px;padding:0 20px">Generate</button>
      </div>
    </div>

    <!-- Diagram output -->
    <div class="card" id="diagramPanel">
      <div class="card-title">Diagram</div>
      <div id="diagramRender"></div>
      <div id="diagramError"></div>
      <div class="diagram-actions">
        <button class="btn-sm btn-ghost" onclick="downloadSVG()">Download SVG</button>
        <button class="btn-sm btn-ghost" onclick="copyMermaid()">Copy Mermaid code</button>
      </div>
    </div>

    <!-- Explanation -->
    <div id="explanation"></div>

    <!-- History -->
    <div class="card">
      <div class="card-title">History</div>
      <div id="histList">
        <div class="empty">No diagrams yet — describe a system above.</div>
      </div>
    </div>

  </div>
</div>

<script>
mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'loose',
  flowchart: { htmlLabels: true, curve: 'basis' }
})

let _lastMermaid = ''

async function ask(question) {
  const inp = document.getElementById('chatInput')
  const btn = document.getElementById('chatSend')
  const panel = document.getElementById('diagramPanel')
  const render = document.getElementById('diagramRender')
  const errEl = document.getElementById('diagramError')
  const expl = document.getElementById('explanation')
  const q = question || inp.value.trim()
  if (!q) return
  inp.value = q

  btn.disabled = true; btn.textContent = 'Generating…'
  panel.className = 'card visible fadein'
  render.innerHTML = '<span class="thinking"><span class="spinner">⟳</span> Generating architecture diagram…</span>'
  errEl.style.display = 'none'
  expl.className = ''; expl.innerHTML = ''

  try {
    const r = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ question: q })
    })
    if (!r.ok) {
      const e = await r.json()
      throw new Error(e.error || r.statusText)
    }
    const data = await r.json()

    // Render mermaid diagram
    if (data.mermaid) {
      _lastMermaid = data.mermaid
      try {
        const { svg } = await mermaid.render('diag-' + Date.now(), data.mermaid)
        render.innerHTML = svg
        errEl.style.display = 'none'
      } catch (mermErr) {
        render.innerHTML = '<pre style="text-align:left;font-size:12px;color:#1a1a2e;white-space:pre-wrap;margin:0">' +
          esc(data.mermaid) + '</pre>'
        errEl.innerHTML = 'Mermaid rendering failed: ' + esc(mermErr.message) +
          '<br>The raw code is shown above — you can ask the agent to fix the syntax.'
        errEl.style.display = 'block'
      }
    } else {
      render.innerHTML = '<span style="color:#6b7280">No diagram code found in response.</span>'
    }

    // Show explanation (everything outside the mermaid block)
    const explText = data.answer
      .replace(/```mermaid[\s\S]*?```/g, '')
      .trim()
    if (explText) {
      expl.innerHTML = renderMd(explText)
      expl.className = 'visible fadein'
    }

    await loadHistory()

  } catch (err) {
    render.innerHTML = '<span style="color:#f87171">Error: ' + esc(err.message) + '</span>'
  } finally {
    btn.disabled = false; btn.textContent = 'Generate'
  }
}

function downloadSVG() {
  const svg = document.querySelector('#diagramRender svg')
  if (!svg) return
  const blob = new Blob([svg.outerHTML], {type: 'image/svg+xml'})
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'architecture.svg'
  a.click()
}

function copyMermaid() {
  if (!_lastMermaid) return
  navigator.clipboard.writeText(_lastMermaid).then(() => {
    const btn = event.target
    const orig = btn.textContent
    btn.textContent = 'Copied!'
    setTimeout(() => btn.textContent = orig, 1500)
  })
}

function renderMd(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:#1e293b;padding:1px 5px;border-radius:3px;font-size:12px">$1</code>')
    .replace(/^### (.+)$/gm, '<div style="font-size:13px;font-weight:700;color:#fff;margin:14px 0 6px">$1</div>')
    .replace(/^## (.+)$/gm, '<div style="font-size:14px;font-weight:700;color:#fff;margin:18px 0 8px">$1</div>')
    .replace(/^- (.+)$/gm, '<div style="padding-left:16px;margin:3px 0">&#8226; $1</div>')
    .replace(/\n/g, '<br>')
}

async function loadHistory() {
  try {
    const items = await fetch('/diagrams').then(r => r.json())
    renderHistory(items)
  } catch(e) {}
}

function renderHistory(items) {
  const el = document.getElementById('histList')
  if (!items.length) {
    el.innerHTML = '<div class="empty">No diagrams yet.</div>'
    return
  }
  el.innerHTML = items.map((r, i) => `
    <div class="hist-item">
      <div class="hist-header" onclick="toggleHist(${i})">
        <span class="hist-query">${esc(r.query)}</span>
        <span class="hist-time">${new Date(r.created_at).toLocaleString()}</span>
        <span class="hist-toggle" id="hi${i}">&#9656;</span>
      </div>
      <div class="hist-body" id="hb${i}">
        ${r.mermaid ? '<pre style="font-size:11px;color:#94a3b8;white-space:pre-wrap;margin:0 0 10px">' + esc(r.mermaid) + '</pre>' : ''}
        <button class="btn-sm btn-ghost" onclick="loadDiagram(${i})" style="margin-bottom:8px">Load this diagram</button>
        <div style="font-size:12px;line-height:1.6;color:#9ca3af">${renderMd(r.response.replace(/\x60\x60\x60mermaid[\\s\\S]*?\x60\x60\x60/g, '').trim())}</div>
      </div>
    </div>`).join('')
  // Store for loading
  el._items = items
}

function toggleHist(i) {
  const body = document.getElementById('hb'+i)
  const icon = document.getElementById('hi'+i)
  body.classList.toggle('open')
  icon.innerHTML = body.classList.contains('open') ? '&#9662;' : '&#9656;'
}

async function loadDiagram(i) {
  const el = document.getElementById('histList')
  const item = el._items && el._items[i]
  if (!item || !item.mermaid) return
  _lastMermaid = item.mermaid
  const panel = document.getElementById('diagramPanel')
  const render = document.getElementById('diagramRender')
  panel.className = 'card visible fadein'
  try {
    const { svg } = await mermaid.render('hist-' + Date.now(), item.mermaid)
    render.innerHTML = svg
  } catch(e) {
    render.innerHTML = '<pre style="text-align:left;font-size:12px;color:#1a1a2e">' + esc(item.mermaid) + '</pre>'
  }
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}

/* --- Settings --- */
async function saveCreds() {
  const key = document.getElementById('tavilyKey').value.trim()
  if (!key) return
  const btn = document.getElementById('saveBtn')
  btn.disabled = true; btn.textContent = '…'
  try {
    const r = await fetch('/settings/credentials', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ tavily_key: key })
    })
    const d = await r.json()
    setApiUI(d.tavily_configured)
  } catch(e) {}
  finally { btn.disabled = false; btn.textContent = 'Save' }
}

function setApiUI(ok) {
  document.getElementById('apiDot').className = 'dot ' + (ok ? 'on' : 'off')
  document.getElementById('apiLabel').textContent = ok
    ? 'Web search available' : 'Web search not configured (optional)'
}

fetch('/settings').then(r => r.json()).then(s => {
  setApiUI(s.tavily_configured)
  if (s.tavily_configured)
    document.getElementById('tavilyKey').value = '••••••••••'
})
loadHistory()
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Architecture Diagram Generator — web UI")
    parser.add_argument("--port",     type=int, default=18804)
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
