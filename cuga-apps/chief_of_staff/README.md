# Chief of Staff

A single chat UI that aggregates every MCP server in `mcp_servers/*` through
one cuga planner — and (in later phases) autonomously acquires new tools when
it hits a gap. Self-contained: nothing outside this directory is modified.

## What's in phase 1

- **Cuga adapter** — out-of-process FastAPI service wrapping `cuga.sdk.CugaAgent`. The only seam the orchestrator depends on (swap by writing a sibling adapter).
- **MCP discovery** — backend syncs the adapter's live tool list into a SQLite registry on startup and on demand.
- **Tools panel UI** — right-hand sidebar showing the live tool universe, grouped by source, with a refresh button.
- **Graceful stub fallback** — if the adapter is unreachable, `/chat` echoes instead of 500-ing, so the shell stays usable while you debug.

Not in phase 1 yet: catalog search, OpenAPI generation, browser fallback,
secrets vault, health checks. Those come in phases 2–5.

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

Open **http://localhost:5174**.

### ✅ Should pass — the shell

1. **Page loads with the chat surface and a right-hand "Tools" panel.**
2. **Header reads** `backend: backend-up · agent: reachable · tools: N` — `N`
   is the number of MCP tools discovered. Expect 30+ across 8 servers.
3. **Tools panel groups by source** under `MCP_SERVER` and lists each tool
   name + a one-line description (e.g. `web_search`, `get_weather`,
   `geocode`, `get_wikipedia_article`, …).
4. **Click "refresh"** in the tools panel — re-syncs from the adapter,
   number stays stable.
5. **Backend `/health` directly** at http://localhost:8765/health returns
   `{"status":"ok","agent_reachable":true,"tools_registered":N}`.
6. **Adapter `/tools` directly** at http://localhost:8000/tools returns
   the raw tool list the registry was built from.

### ✅ Should pass — graceful degradation

7. **Stop just the adapter:**
   ```bash
   docker stop cuga-apps-cos-adapter
   ```
   - Header switches to `agent: stub`.
   - Chat still responds, with `[stub:cuga-unreachable] echo: <your text>`.
   - Tools panel keeps showing the previously synced list (it's persisted
     in SQLite); refresh now reports 0 synced and clears the list.
   - Bring the adapter back: `docker start cuga-apps-cos-adapter`, then
     hit refresh — tools repopulate.

### ✅ Should pass — real planning (only if LLM key is set)

8. **Type:** *"What's the weather like in Paris this week?"*
   - cuga should pick `get_weather` from `mcp-geo`.
   - Response should be the agent's textual answer, not a tool dump.
   - Backend log shows the round-trip; adapter log shows tool calls.

9. **Type:** *"Search Wikipedia for the history of the Eiffel Tower"*
   - cuga should pick `get_wikipedia_article` or `search_wikipedia` from
     `mcp-knowledge`.

10. **Type something the agent has no tool for**, e.g.
    *"Place an order on DoorDash for my usual"*. The agent should respond
    with a `[TOOL GAP]` line declaring what it's missing — that's the
    signal phase 3's acquisition agent will hook into.

### What "passing" means right now

Phase 1's bar is: **a single chat surface that visibly aggregates the union
of all MCP tools and round-trips real planning through an out-of-process
agent backend.** Anything beyond that — actually growing the toolbox at
runtime — lands in phase 2 and phase 3.

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
