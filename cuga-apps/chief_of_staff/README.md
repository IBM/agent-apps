# Chief of Staff

A single chat UI that aggregates every MCP server in `mcp_servers/*` through
one cuga planner — and (in later phases) autonomously acquires new tools when
it hits a gap. Self-contained: nothing outside this directory is modified.

## What's shipped

**Phase 1 — registry + adapter + discovery**
- Out-of-process cuga adapter wrapping `cuga.sdk.CugaAgent`
- MCP discovery → SQLite registry, with retry on cold start
- Right-hand tools panel grouped by source
- Stub fallback when adapter is unreachable

**Phase 2 — catalog acquisition**
- **Structured `[[TOOL_GAP]]` signal** — the agent emits a JSON gap when it can't fulfill a request; orchestrator parses it
- **Catalog** — curated YAML of installable MCP servers ([backend/acquisition/catalog.yaml](backend/acquisition/catalog.yaml))
- **Token-overlap matcher** — scores catalog entries against the gap; no LLM call needed for phase 2's small catalog
- **Consent prompt** — modal in chat with Install / Skip per proposal
- **Live agent reload** — adapter rebuilds the planner with the approved tool included (~30 s)
- **Activations SQLite** — approved entries persist; orchestrator merges them with the always-on baseline (`MCP_SERVERS` env)

Not yet (phases 3–5): OpenAPI generation + probe loop, browser fallback, secrets vault, health checks.

## Run with Docker

The cleanest way to take a look. Three containers come up:

| Container | Port | What it does |
|---|---|---|
| `cuga-apps-cos-adapter` | 8000 | Wraps cuga.sdk + all 8 MCP tool sets |
| `cuga-apps-cos-backend` | 8765 | FastAPI shell + SQLite registry |
| `cuga-apps-cos-frontend` | 5174 | React UI (built + served by nginx) |

### Prereqs

1. **The parent cuga-apps stack must be running** so the MCP servers are
   reachable on the `cuga-apps_default` network:

   ```bash
   cd cuga-apps
   docker compose up -d            # brings up mcp-web, mcp-knowledge, …
   ```

2. **An LLM API key** in `cuga-apps/apps/.env` (the same file the rest of
   cuga-apps reads). Without one, the adapter still loads tools — but
   `/chat` will return errors when it tries to plan. You can verify the
   shell + tool discovery without one; you need a key to see real planning.

### Up

```bash
cd cuga-apps/chief_of_staff
docker compose up --build
```

First build of the adapter image takes 5–10 minutes (cuga + LangChain).
Backend and frontend builds are seconds. Subsequent rebuilds are fast.

### Down

```bash
docker compose down
```

This only tears down chief_of_staff containers — the parent cuga-apps
stack is untouched.

## What to look at / test

The phase-2 demo flow: start with a small toolbox, ask something it can't
answer, watch it offer to install the missing tool, approve, and ask again.

### Setup

```bash
# Pull the latest changes, then force-rebuild (the adapter and frontend both
# changed; the backend changed too).
cd cuga-apps/chief_of_staff
docker compose down
docker compose build --no-cache
docker compose up -d
docker compose ps   # all 3 should be Up
```

Open **http://localhost:5174**.

### ✅ Initial state — small toolbox by design

1. **Header** reads `backend: backend-up · agent: reachable · tools: 10–15`.
   That's intentionally a subset — the adapter's `MCP_SERVERS` defaults to
   `web,local,code` so phase 2 has real gaps to fill.
2. **Tools panel** shows entries from those three servers only. No `geo`,
   `knowledge`, `finance`, etc. yet.

### ✅ The acquisition flow

3. **Type:** *"What's the weather in Tokyo right now?"*
   - The agent should reply that it can't help with weather, and the
     orchestrator should attach **proposal cards** under the agent's reply.
   - Top proposal should be **"Geo MCP"** with a high match score.
4. **Click "Install"** on the Geo MCP card.
   - The button shows `...` for ~30 s while the adapter rebuilds with
     `web,local,code,geo`.
   - When done, the proposal disappears and the right-hand Tools panel
     refreshes — you should now see a `geo` group with `get_weather`,
     `geocode`, etc.
5. **Re-type:** *"What's the weather in Tokyo right now?"*
   - This time the agent should call `get_weather` and return a real answer.

### ✅ More variations to try

| Ask | Expected proposal | Expected tools after install |
|---|---|---|
| *"Look up the Eiffel Tower on Wikipedia"* | Knowledge MCP | `get_wikipedia_article`, `search_wikipedia` |
| *"What's NVIDIA's stock price?"* | Finance MCP | `get_quote`, market data tools |
| *"Extract the text from this PDF"* | Text MCP | document parsing tools |

### ✅ Decline path

6. Trigger another gap (e.g. *"find me a hike near Boulder"*) → click
   **"Skip"** on the Geo proposal (if you had reverted) → the proposal
   disappears, the agent stays as-is, and the activation is recorded as
   denied (won't be auto-mounted on next restart).

### ✅ API-level checks (skip if UI works)

```bash
# Catalog with current activation state
curl -s http://localhost:8765/catalog | jq

# What the agent currently has
curl -s http://localhost:8000/tools | jq 'length'   # tool count
curl -s http://localhost:8765/tools | jq 'length'   # registry count — should match

# Approve programmatically
curl -s -X POST http://localhost:8765/tools/approve \
  -H 'Content-Type: application/json' \
  -d '{"catalog_id":"geo"}'

# Check the agent now has more tools
curl -s http://localhost:8000/health | jq '.tool_count'
```

### What "passing" means at this stage

Phase 2's bar is: **the agent visibly grows its toolbox in response to
your questions, with explicit consent, no container restarts.** Phase 3
will replace the curated catalog with on-the-fly OpenAPI code generation
and add the autoresearcher-pattern probe loop that gates registration.

## Run without Docker

If you'd rather hack on it locally:

```bash
cd cuga-apps/chief_of_staff
./start.sh
```

Assumes Python deps for the adapter (cuga, langchain, …) are already in
your active env, and that the MCP servers are running (`python apps/launch.py`).

## Layout

```
backend/
  main.py                 FastAPI shell
  orchestrator.py         coordinates planner + (future) acquisition
  agents/
    base.py               AgentClient Protocol (the swap point)
    cuga_client.py        out-of-process HTTP client to the adapter
  registry/
    store.py              SQLite tool registry
    discovery.py          adapter→registry sync
adapters/
  cuga/
    server.py             FastAPI wrapper around CugaAgent
    requirements.txt      adapter-only deps (assumes cuga env present)
frontend/                 React + Vite + Tailwind UI
  src/components/Chat.tsx
  src/components/ToolsPanel.tsx
  nginx.conf              reverse proxy /api → backend container
Dockerfile.adapter        cuga-deps image
Dockerfile.backend        lightweight FastAPI image
Dockerfile.frontend       multi-stage Vite build + nginx
docker-compose.yml        wires the three services + external cuga network
data/                     SQLite registry + logs (gitignored)
tests/                    isolated test dir (pytest)
```

## Swapping the agent backend

The orchestrator only knows the `AgentClient` Protocol in
[backend/agents/base.py](backend/agents/base.py). To replace cuga, drop a
sibling under `adapters/` (e.g. `adapters/gpt_oss/server.py`) that exposes
the same three endpoints — `/health`, `/tools`, `/chat` — and point
`CUGA_URL` at it. No changes anywhere else in the codebase.
