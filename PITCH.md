---
marp: true
theme: default
paginate: true
title: cuga-apps — what we built, and where CUGA falls short
---

# cuga-apps

### A multi-app agent platform on top of CUGA

What we built · How it's wired · Where CUGA leaves gaps

---

## The premise

> *"Stand up a fleet of demo agent-apps that share a common tool layer, a common UI, and a common test harness — using CUGA as the planner."*

Two questions this deck answers:

1. **What does it actually take to build a CUGA app at scale?**
2. **Which gaps in CUGA did we have to fill ourselves?**

---

## What we shipped

| | |
|---|---|
| **23** demo agent-apps | each its own FastAPI process, its own port |
| **8** MCP servers | 36+ shared tools (web, knowledge, geo, finance, code, local, text, invocable_apis) |
| **1** umbrella UI | discoverability + per-app deep links |
| **1** tool explorer | browse and invoke any MCP tool from the browser |
| **1** test harness | smoke + MCP + wiring tiers, ~120 tests, no LLM cost |
| **1** LLM factory | RITS / Anthropic / OpenAI / watsonx / litellm / ollama |

All in one `docker compose up`. ~5–10 min cold build, seconds after that.

---

## Architecture — the big picture

```
                ┌─────────────────────────────┐
                │   Umbrella UI  :3001        │
                │   (React + Vite + nginx)    │
                └──────────────┬──────────────┘
                               │ deep-links
                               ▼
   ┌──────────────────────┐         ┌────────────────────────┐
   │   23 FastAPI apps    │ ◄─────► │   8 MCP servers        │
   │   one CugaAgent each │  HTTP   │   (Dockerfile.mcp,     │
   │   ports 28xxx        │  MCP    │    8 entrypoints)      │
   └──────────┬───────────┘         └────────────┬───────────┘
              │                                  │
              │                                  ▼
              │                       ┌─────────────────────┐
              └──────────────────────►│ MCP Tool Explorer   │
                                      │ :28900              │
                                      └─────────────────────┘
```

Three layers: **apps** (per-use-case agents), **MCP servers** (shared primitives), **UI** (discovery + invocation). All over HTTP. No direct imports across layers.

---

## The container layout

11 services. Two images, eight entrypoints in one of them.

```
Dockerfile.apps  →  apps             (one container, 24 processes via start.sh)
Dockerfile.mcp   →  mcp-web          (port 29100)
                    mcp-knowledge    (29101)
                    mcp-geo          (29102)
                    mcp-finance      (29103)
                    mcp-code         (29104)
                    mcp-local        (29105)
                    mcp-text         (29106)
                    mcp-invocable_apis (29107)
ui/Dockerfile    →  ui               (3001, nginx)
mcp_tool_explorer/Dockerfile → tool explorer (28900)
```

Apps depend on MCP servers via `depends_on:`. Bind-mounts share the few stateful directories (drop_summarizer/inbox, voice_journal/storage, deck_forge/outputs, etc.).

---

## Why one image for 8 MCP servers?

Each server is `python -m mcp_servers.<name>.server`. They share:

- The `_core` envelope (`tool_result`, `tool_error`, FastMCP bootstrap)
- HTTP/HTML helpers, retry behavior, error normalization
- `requirements.mcp.txt` (one heavy install: docling, faster-whisper, tiktoken)

One build, many entrypoints — only the `command:` differs in compose. Cuts cold-build time and keeps tool semantics consistent across servers.

---

## The apps layer — 23 use cases, six shapes

| Shape | Examples |
|---|---|
| Pure MCP, single server, single `/ask` | `web_researcher`, `paper_scout`, `code_reviewer` |
| Pure MCP, multiple servers | `travel_planner`, `hiking_research` |
| MCP + inline session state | `movie_recommender`, `voice_journal` |
| MCP + heavy app-specific logic | `ibm_cloud_advisor`, `box_qa` |
| No MCP — purely app-state | `smart_todo`, `api_doc_gen` |
| Event-driven (cron / file watcher / polling) | `newsletter`, `drop_summarizer`, `stock_alert` |

Every app is a `CugaAgent` + `tools=…` + `special_instructions=…` wrapped in a FastAPI process.

---

## How an app actually wires CUGA

```python
from cuga import CugaAgent
from _llm        import create_llm
from _mcp_bridge import load_tools

def make_agent():
    return CugaAgent(
        model = create_llm(provider=os.getenv("LLM_PROVIDER"),
                           model=os.getenv("LLM_MODEL")),
        tools = load_tools(["knowledge", "web"]),   # ← MCP bridge
        special_instructions = _SYSTEM,
        cuga_folder = str(_DIR / ".cuga"),
    )
```

Three things CUGA itself does **not** ship that we had to fill in:
1. The **LLM factory** (multi-provider, env-driven)
2. The **MCP↔LangChain bridge** (CUGA only consumes LangChain tools)
3. The **HTTP surface** (CUGA is a library; FastAPI is ours)

---

## The bridge — LangChain ↔ MCP

`apps/_mcp_bridge.py` does one thing well:

```
load_tools(["web", "knowledge"])
        │
        ▼
   resolve URLs from MCP_<NAME>_URL or default
        │
        ▼
   MultiServerMCPClient(streamable_http)
        │
        ▼
   list[StructuredTool]   ← what CugaAgent expects
```

Plus `call_tool(server, tool, args)` for non-LLM code paths (cron jobs, file watchers).

**This bridge is pure glue.** It exists because CUGA doesn't speak MCP natively. Every CUGA-based project will end up writing this.

---

## Building a new CUGA app — the 9-step checklist

From [docs/ADDING_AN_APP.md](cuga-apps/docs/ADDING_AN_APP.md):

- [ ] port allocated in `apps/_ports.py`
- [ ] `apps/<name>/main.py` written
- [ ] `apps/<name>/README.md` with the MCP-usage block
- [ ] entry in `apps/launch.py` `PROCS`
- [ ] line in `start.sh`
- [ ] port mapping in `docker-compose.yml`
- [ ] env vars added to `apps/.env.example`
- [ ] entry in `ui/src/data/usecases.ts` with `mcpUsage`
- [ ] wiring test entries
- [ ] `docker compose build apps ui && docker compose up -d apps ui`
- [ ] `make test` passes

**8–9 files touched** per new app. Mostly bookkeeping.

---

## What's hard isn't the agent code

The agent code is small — **~30 lines of "real" CUGA wiring**. The other 90% of the work is registry plumbing across files that don't talk to each other:

```
apps/_ports.py            ←  Python registry
docker-compose.yml        ←  static YAML port mapping
ui/src/data/usecases.ts   ←  TypeScript registry
start.sh                  ←  shell loop
launch.py                 ←  Python process supervisor
tests/test_app_wiring.py  ←  pytest registry
```

**Three different registries of the same set of apps**, none aware of each other. That's the cost CUGA doesn't help with.

---

## Adding a new MCP tool — easier, but still 4 places

Per [docs/ADDING_A_TOOL.md](cuga-apps/docs/ADDING_A_TOOL.md):

1. `@mcp.tool()`-decorate a function in `mcp_servers/<server>/server.py`
2. `docker compose build mcp-<server> && up -d`
3. `docker compose restart apps`  ← bridge caches tool list at startup
4. Test entry in `tests/test_mcp_tools.py::TestMcp<Server>`

**Adding a whole new MCP server** is heavier: 6+ files (`_ports.py`, requirements, Dockerfile, compose service block, launcher, docs).

---

## Gaps in CUGA — the explicit list

| # | Gap | What we did |
|---|---|---|
| 1 | **No MCP support natively** — only LangChain tools | Wrote `_mcp_bridge.py` |
| 2 | **No multi-provider LLM factory** | Wrote `_llm.py` (6 providers) |
| 3 | **No HTTP surface** — agent is library-only | FastAPI shell per app |
| 4 | **No declarative app definition** — identity is scattered across files | Hand-maintained 3 registries |
| 5 | **No hot tool reload** — bridge caches at startup | Restart container to pick up new tools |
| 6 | **No streaming / step-trace exposure** in `agent.invoke()` | Single-shot `/ask` returns final answer only |
| 7 | **No multi-tenancy** — one `CugaAgent` per app process | 23 processes in one container |
| 8 | **No native gap detection** — agent can't say "I'd need a tool for X" | Solved separately in chief_of_staff (out of scope here) |
| 9 | **No discovery surface** — agent doesn't expose its tool list at runtime | Each app must self-document via README + usecases.ts |

---

## Gap #1 spotlight — MCP support

CUGA expects `tools: list[StructuredTool]`.
MCP speaks streamable HTTP and returns `{ok, data}` envelopes.

Without the bridge, every app would have to:

- Open an MCP session per server
- Translate MCP tool schemas → LangChain `StructuredTool` schemas
- Unwrap `{ok, data}` / `{ok: false, error}` envelopes
- Manage event loop reentrancy (sync code calling async MCP)

`_mcp_bridge.py` does this in 152 lines. Multiply that across every CUGA project that wants to use MCP. **This belongs upstream in CUGA.**

---

## Gap #4 spotlight — registry sprawl

To answer the question *"what apps does this deployment have?"* you need to read **three** files:

```
apps/_ports.py              # Python truth
docker-compose.yml          # static YAML
ui/src/data/usecases.ts     # TypeScript truth
```

None can be derived from another. They drift. We catch some drift via `tests/test_smoke.py` (compares against `set(MCP_PORTS)`) but most drift is invisible until a tile 404s in the UI.

**A declarative app manifest** (one YAML per app, registries auto-derived) would erase ~40% of the new-app friction.

---

## Gap #5 spotlight — hot tool reload

Today: add a tool → `docker compose restart apps` → wait 30s → tool now visible.

Why? `_mcp_bridge.load_tools()` is called once during `make_agent()`. The MCP client doesn't subscribe to `tools/list_changed`.

Fixing this would take CUGA exposing a `agent.reload_tools()` (chief_of_staff has a downstream version of this — `/agent/reload` — but it's not in CUGA itself).

---

## What we built around CUGA's edges

```
┌────────────────────────────────────────────────────────────┐
│                       cuga-apps                            │
│                                                            │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │ _llm.py  │   │ _mcp_bridge  │   │ _ports.py        │    │
│  │ multi-   │   │ LC↔MCP       │   │ single registry  │    │
│  │ provider │   │ glue         │   │                  │    │
│  └──────────┘   └──────────────┘   └──────────────────┘    │
│                                                            │
│  ┌─────────────────┐   ┌─────────────────┐                 │
│  │ umbrella UI     │   │ tool explorer   │                 │
│  │ (discovery)     │   │ (per-tool form) │                 │
│  └─────────────────┘   └─────────────────┘                 │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  test harness — smoke / mcp / wiring / llm tiers    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                            │
└────────────────────────────────────────────────────────────┘
                            ▲
                            │ depends on
                            ▼
                ┌────────────────────┐
                │       cuga         │
                │  (planner only)    │
                └────────────────────┘
```

CUGA is a thin slice of the actual stack. **Most of the value is the surrounding scaffolding.**

---

## Test harness

```
make test         # default: smoke + mcp + wiring (~13s, no LLM cost)
make test-quick   # smoke only (~5s)
make test-mcp     # MCP tool contracts
make test-wiring  # app REST routes
make test-llm     # opt-in LLM round-trips (slow, costs tokens)
```

- **Smoke tier** parametrizes over `APP_PORTS` — new apps are auto-covered.
- **MCP tier** pins each tool's `{ok, data}` contract.
- **Wiring tier** hits non-LLM REST routes (`/health`, `/settings`, etc.).
- **LLM tier** is opt-in and proves the agent can actually call the tool.

Three tiers because the cost / signal trade-off is different at each level.

---

## How easy is "easy" — concretely

Time to add a **new MCP tool** in an existing server:
- Code: ~10 min
- Build + restart: 1–2 min
- Test: 2 min
**Total: ~15 minutes** ← actually pleasant.

Time to add a **new CUGA app** (say, Recipe Finder from the docs):
- Code (main.py + README): ~30–60 min
- Registry edits across 5 files: ~15 min
- UI tile: ~10 min
- Tests: ~10 min
- Build + iterate: ~10 min
**Total: 75–105 minutes** ← bookkeeping dominates.

**The agent code isn't the bottleneck. The non-CUGA scaffolding is.**

---

## The story for upstream CUGA

If CUGA shipped four things, this stack shrinks by ~30%:

1. **Native MCP support** → delete `_mcp_bridge.py`
2. **Multi-provider LLM factory** → delete `_llm.py`
3. **Declarative agent manifest** → collapse 3 registries → 1
4. **Hot tool reload + runtime tool listing** → kill the `restart apps` step, kill `mcpUsage` drift in the UI

The umbrella UI, the tool explorer, the test harness, the docker stack — all of those are app-platform concerns and stay app-side. **They're not CUGA's job.** But the four above are.

---

## TL;DR

- Built a **23-app agent platform** on CUGA — running, tested, documented.
- The shape is **CUGA + MCP servers + umbrella UI**, all containerized.
- **CUGA is ~10% of the code** that actually runs. The rest is scaffolding we had to write because CUGA doesn't ship it.
- The **biggest fixable gaps** are: native MCP, LLM factory, declarative app manifest, hot tool reload.
- New apps cost ~90 min mostly because of registry sprawl, not agent logic. Closing the four gaps brings that to ~30 min.

---

# Questions?

Repo: `/home/amurthi/work/agent-apps/cuga-apps`
Docs: `cuga-apps/docs/{GETTING_STARTED,ADDING_AN_APP,ADDING_A_TOOL,TESTING}.md`
Stack: `docker compose up -d --build` → http://localhost:3001
