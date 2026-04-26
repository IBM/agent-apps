# Chief of Staff

A single chat UI that aggregates every MCP server in `mcp_servers/*` through
one cuga planner — and (in later phases) autonomously acquires new tools when
it hits a gap. Self-contained: nothing outside this directory is modified.

## What's shipped

**Phase 1 — registry + adapter + discovery**
- Out-of-process cuga adapter wrapping `cuga.sdk.CugaAgent`
- MCP discovery → SQLite registry, with retry on cold start
- Stub fallback when adapter is unreachable

**Phase 2 — catalog acquisition**
- Structured `[[TOOL_GAP]]` signal; orchestrator parses it
- Curated YAML catalog with token-overlap matcher
- Consent prompt; live agent reload; per-acquisition activations

**Phase 3 — Toolsmith agent + OpenAPI generation + autoresearch probe**
- **Toolsmith agent** ([backend/acquisition/toolsmith.py](backend/acquisition/toolsmith.py)) — the durable, LLM-driven acquisition agent. Defaults to RITS `gpt-oss-120b`. Cuga is the swappable planner; Toolsmith is the brain that owns acquisition.
- **Source plugin pattern** ([backend/acquisition/sources/](backend/acquisition/sources/)) — `CatalogSource` + `OpenAPISource`. Adding sources is one new file.
- **OpenAPI source** with curated spec index for no-auth public APIs (Country Info, Open-Meteo, Joke API). Picks an endpoint, builds an executable tool spec.
- **Probe harness** ([backend/acquisition/probe.py](backend/acquisition/probe.py)) — the autoresearch keep/discard gate. Structural check (HTTP 2xx + valid JSON + non-empty payload) plus optional LLM judge for plausibility. Failed probes block registration.
- **Live tool mount** — the adapter's `/agent/reload` now accepts an `extra_tools` list. Generated specs become httpx-backed `StructuredTool` instances merged into cuga's tool set, no MCP subprocess.
- **Vault skeleton** ([backend/acquisition/vault.py](backend/acquisition/vault.py)) — SQLite secrets store, ready for phase 3.5 to wire up auth-required APIs.

Not yet (phases 3.5–6): credential prompt UI, Smithery / openapi-directory search, browser fallback, health checks, cross-domain mining.

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
your questions, with explicit consent, no container restarts.**

Phase 3 adds the OpenAPI-generated source and the probe loop — the
catalog and OpenAPI sources both surface in the same proposal cards now
(look for the purple "Generated from OpenAPI" tag).

## Phase 3 test plan

### Setup (one-time per build)

```bash
cd cuga-apps/chief_of_staff

# Optional: configure Toolsmith's LLM. If unset, ranking falls back to
# pure score order — the loop still works, just less smart about ties.
export TOOLSMITH_LLM_PROVIDER=rits          # default
export TOOLSMITH_LLM_MODEL=gpt-oss-120b     # default
export RITS_API_KEY=...                     # required for the LLM path

docker compose down
docker compose build --no-cache
docker compose up -d
sleep 30
docker compose ps                           # all 3 Up
curl -s http://localhost:8765/health | jq   # toolsmith_llm should be true
```

### Demo 1 — catalog still works (regression)

Same as phase-2 demo: ask *"What's the weather in Tokyo?"* → install the
**Geo MCP** card → ask again → real answer. Phase 3 must not break this.

### Demo 2 — OpenAPI source (the headline)

Ask: *"Give me information about France: capital, population, currency."*

✅ **Pass:**
1. Agent emits a gap (no countries tool in default load).
2. Proposal cards appear. **Country Info API** has a purple `Generated
   from OpenAPI` tag and shows a preview endpoint (`get_country_by_name`)
   plus the base URL `https://restcountries.com/v3.1`.
3. Click **Generate + probe**. Button shows `...`.
4. Behind the scenes:
   - Toolsmith calls `OpenAPISource.realize()` → emits a `RealizedTool`
     with `invoke_url=https://restcountries.com/v3.1/name/{name}` and
     `sample_input={"name": "France"}`
   - Probe harness substitutes the path param, calls `GET .../name/France`,
     verifies 200 + JSON + non-empty payload (and, if RITS is configured,
     LLM-judges that the response looks like real country data)
   - On pass, the tool spec is sent to the adapter via `/agent/reload`
     under `extra_tools`; cuga rebuilds with `get_country_by_name` mounted
5. Tools panel shows `get_country_by_name` (kind: `generated`).
6. Re-ask the same question → cuga calls `get_country_by_name(name="France")`
   → real answer (capital: Paris, population: ~67M, currency: EUR).

### Demo 3 — Probe rejects a broken tool (autoresearch in action)

You can force this by editing [spec_index.yaml](backend/acquisition/sources/spec_index.yaml)
to point one entry at a URL that 404s, then triggering its acquisition.
The proposal card will display `error: probe failed: http 404` and the
tool will **not** be registered. That's the keep/discard gate doing its
job — phase 3 ships *no* unverified tools.

### Demo 4 — Toolsmith ranking

When both catalog and OpenAPI propose for the same gap, the Toolsmith
LLM (if configured) re-ranks them. Check the order of cards — the more
fitting source should be first. With `TOOLSMITH_LLM_PROVIDER` unset the
ordering falls back to pure score (catalog usually wins for narrow
gaps; OpenAPI for niche/long-tail).

### API-level checks

```bash
# Both sources are loaded by the Toolsmith
curl -s http://localhost:8765/health | jq '.toolsmith_llm'

# Adapter exposes generated-tool count separately
curl -s http://localhost:8000/health | jq '{tool_count, extra_tool_count}'

# Approve programmatically (skip the UI)
curl -s -X POST http://localhost:8765/tools/approve \
  -H 'Content-Type: application/json' \
  -d '{"proposal":{"id":"openapi:countries","name":"Country Info","description":"x","capabilities":[],"source":"openapi","score":0.5,"auth":[],"spec":{"spec_id":"countries","base_url":"https://restcountries.com/v3.1"}}}' \
  | jq '{success, reason, "probe_ok": .probe.ok}'
```

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| No proposal card for OpenAPI gaps | Cuga isn't emitting `[[TOOL_GAP]]`. Phase 4 will replace the marker with structured-output enforcement. |
| `toolsmith_llm: false` after rebuild | RITS keys not propagated. `docker exec cuga-apps-cos-backend env \| grep RITS` |
| OpenAPI install fails with `probe failed: network error` | Public API down or container has no internet. Try a different demo. |
| OpenAPI install fails with `judge: ...` | LLM judge thought the response looked fake. Often false positive — disable by unsetting `TOOLSMITH_LLM_PROVIDER`. |

## Roadmap (phases 4+)

| Phase | Adds | Why |
|---|---|---|
| **3.5** | Credential prompt UI + OS keyring integration; auth-required APIs (Stripe, GitHub, Notion) added to spec index | Unlocks the most useful APIs — most of the world's APIs need a key |
| **3.6** | Smithery / openapi-directory search → catalog grows automatically; LLM matcher replaces token overlap | Removes manual curation as the bottleneck |
| **4** | Browser-task source — when no API exists at all, drive cuga's web-agent side. Per-task, not persistent. | Covers DoorDash / consumer-app class of problems |
| **5** | Daily probe of registered tools; quarantine on failure; user notifications | Makes the toolbox self-maintaining as it grows past ~20 tools |
| **6** | Cross-domain mining over user data the unified app aggregates ("you spend more on Uber Eats the week after a bad sleep score") | The thing siloed apps literally can't ship |

Phase 3.5 is the next stop and probably the biggest user-visible jump,
because it brings the whole authenticated-API economy into reach.

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
