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

**Phase 3 — OpenAPI generation + autoresearch probe**
- Source plugin pattern with `CatalogSource` + `OpenAPISource`
- Probe harness (structural + optional LLM judge) — the autoresearch keep/discard gate
- Live tool mounting via the cuga adapter's `extra_tools`

**Phase 3.6 — real code exec + auth UX + vault**
- **Adapter exec()s artifact code** with an import allowlist (httpx, json, re, datetime, urllib, asyncio, math, base64, hashlib, hmac, uuid, time, plus pydantic/typing). Disallowed imports register as error stubs that raise on call instead of crashing the adapter. ([adapters/cuga/server.py](adapters/cuga/server.py))
- **Auth-aware Coder** — the LLM/Claude Coder prompt knows the auth scheme and emits the secret as the last kwarg of the function signature, hidden from cuga's args_schema.
- **Auth-aware spec index** — `github_search` (bearer token) and `openweather` (api_key_query) added to [spec_index.yaml](backend/acquisition/sources/spec_index.yaml).
- **Vault** with optional OS keyring backend ([backend/acquisition/vault.py](backend/acquisition/vault.py)). Falls back to SQLite + base64-XOR when keyring isn't available. Toggle with `VAULT_BACKEND=keyring`.
- **Credential prompt UX** — when Toolsmith needs auth and the vault doesn't have it, `acquire` returns `needs_secrets` instead of failing silently. The UI renders a credential modal; user enters; backend stores in vault; user re-asks; Toolsmith retries.
- **Secrets injected at call time** — backend pulls per-tool secrets from Toolsmith's vault via `/effective_state`, hands them to the cuga adapter on `/agent/reload`. Adapter resolves them when the tool is invoked. Never logged.

**Phase 3.5 — Toolsmith service + Coder abstraction + persistent ToolArtifacts**
- **[Toolsmith service](toolsmith/)** — own FastAPI app on port 8001, LangGraph ReAct agent with its own tool belt. The cuga adapter is the swappable planner; Toolsmith is the durable, swap-resistant brain.
- **Internal tool belt** — search_catalog, search_openapi_index, generate_tool_code, probe_generated_tool, register_tool_artifact, etc. NOT MCP tools — agent tools the Toolsmith calls. ([toolsmith/tools/build.py](toolsmith/tools/build.py))
- **Coder abstraction** — pluggable code-generation specialist. `TOOLSMITH_CODER=gpt_oss` (RITS gpt-oss-120b) or `TOOLSMITH_CODER=claude` (Sonnet 4.6 via Anthropic SDK). One-line A/B switch.
- **ToolArtifact** — canonical disk-persisted tool format at `data/tools/<id>/{manifest.yaml, tool.py, probe.json}`. Multiple bindings (LangChain, MCP, OpenAPI doc) computed from one source of truth.
- **Reusability** — tools survive restarts; backend startup pulls Toolsmith's `/effective_state` and reloads cuga with the union.
- **Dumb UI** — chat surface plus tools panel. No consent modal. Toolsmith decides; UI shows what happened.

Not yet (phases 4+): web search for arbitrary specs, browser source for no-API sites, health checks + auto-quarantine, cross-domain mining.

## Run with Docker

The cleanest way to take a look. **Four** containers come up now (Toolsmith joined the party):

| Container | Port | What it does |
|---|---|---|
| `cuga-apps-cos-adapter` | 8000 | Wraps cuga.sdk — the swappable planner |
| `cuga-apps-cos-toolsmith` | 8001 | LangGraph ReAct acquisition agent — the durable brain |
| `cuga-apps-cos-backend` | 8765 | Thin orchestrator + SQLite registry |
| `cuga-apps-cos-frontend` | 5174 | Dumb React UI |

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

### Troubleshooting (phase 3)

| Symptom | Likely cause |
|---|---|
| No proposal card for OpenAPI gaps | Cuga isn't emitting `[[TOOL_GAP]]`. |
| `toolsmith_llm: false` after rebuild | RITS keys not propagated. `docker exec cuga-apps-cos-backend env \| grep RITS` |
| OpenAPI install fails with `probe failed: network error` | Public API down or container has no internet. |
| OpenAPI install fails with `judge: ...` | LLM judge thought the response looked fake. Disable judge by unsetting `TOOLSMITH_LLM_PROVIDER`. |

## Phase 3.5 test plan — the new architecture

### What changed since phase 3

- **The consent modal is gone.** The dumb UI doesn't gate Toolsmith — Toolsmith decides what to build and just builds it. The chat shows a green "Toolsmith built X" notice underneath the planner's reply.
- **Toolsmith runs as its own service** (`cuga-apps-cos-toolsmith` on port 8001). The backend talks to it via HTTP, mirroring the cuga adapter pattern.
- **Tool artifacts are persistent.** Every tool Toolsmith builds gets written to `data/tools/<id>/`. Backend restart re-mounts everything.
- **Coder is swappable.** `TOOLSMITH_CODER=gpt_oss` (default, free if you have RITS) or `TOOLSMITH_CODER=claude` (better code, costs Anthropic credits).

### Setup

```bash
cd cuga-apps/chief_of_staff

# Toolsmith orchestration LLM (drives the ReAct loop)
export TOOLSMITH_LLM_PROVIDER=rits
export TOOLSMITH_LLM_MODEL=gpt-oss-120b

# Coder selection — the A/B switch
export TOOLSMITH_CODER=gpt_oss        # or "claude" — both work, Claude is better at code

# Required keys (whichever provider you use)
# RITS_API_KEY, ANTHROPIC_API_KEY in apps/.env

docker compose down
docker compose build --no-cache       # mandatory — toolsmith image is new
docker compose up -d
sleep 30
docker compose ps                     # all 4 Up

# Toolsmith service health
curl -s http://localhost:8001/health | jq
# {"status":"ok","coder":"gpt_oss","orchestration_llm":true,"artifact_count":0}

# Backend should see toolsmith reachable
curl -s http://localhost:8765/health | jq
```

### Test 1 — Autonomous acquisition (the headline)

Open http://localhost:5174 in incognito.

**Type:** *"Tell me a random joke."*

✅ Pass criteria:
- Backend posts the gap to `http://chief-of-staff-toolsmith:8001/acquire`.
- Toolsmith ReAct loop runs: searches catalog (no match) → searches OpenAPI index (matches Joke API) → generates code via Coder → probes the URL → registers as a `data/tools/openapi__get_random_joke/` artifact.
- Chat shows a **green "Toolsmith built a tool" notice** with the artifact id.
- Tools panel shows `get_random_joke` (kind: `generated`).
- **Re-ask** the question → real joke.

### Test 2 — Coder A/B comparison

```bash
# Try gpt-oss
docker compose exec chief-of-staff-toolsmith env | grep TOOLSMITH_CODER
# → gpt_oss

# Switch to Claude (re-up only the toolsmith)
TOOLSMITH_CODER=claude docker compose up -d chief-of-staff-toolsmith
docker compose exec chief-of-staff-toolsmith env | grep TOOLSMITH_CODER
# → claude

# Trigger the same gap again ("Country information for Japan").
# Inspect both artifacts' tool.py — Claude's typically uses cleaner
# error handling and pagination logic. Both should pass the probe.
ls cuga-apps/chief_of_staff/data/tools/
cat cuga-apps/chief_of_staff/data/tools/openapi__get_country_by_name/tool.py
```

### Test 3 — Persistence (reusability)

Build a tool, then restart the backend:

```bash
docker compose restart chief-of-staff-backend
sleep 15
curl -s http://localhost:8000/health | jq '.tool_count, .extra_tool_count'
# extra_tool_count > 0 — the tool survived the restart and was re-mounted.
```

### Test 4 — Removing tools

```bash
# List artifacts
curl -s http://localhost:8765/toolsmith/artifacts | jq '.[].id'

# Remove one
curl -s -X DELETE http://localhost:8765/toolsmith/artifacts/openapi__get_random_joke

# Verify it's gone from the agent
curl -s http://localhost:8000/health | jq '.extra_tool_count'
```

### Test 5 — Probe still gates registration

Edit `chief_of_staff/toolsmith/Dockerfile` to bake in a `spec_index.yaml`
override that points at a 404 URL (or just trigger a gap with no OpenAPI
match), and confirm Toolsmith returns `success: false` with a clear
reason. The autoresearch keep/discard gate doesn't change.

### What "phase 3.5 passing" means

You've proven:
1. The brain (Toolsmith) is process-isolated from the planner (cuga adapter).
2. Tools persist as named artifacts and survive restarts.
3. The Coder is swappable mid-run via env var.
4. The probe still rejects unverified tools.
5. The UI is dumb — it shows what Toolsmith did, doesn't drive the decision.

## Phase 3.6 test plan — auth + real code execution

Same four containers, no compose changes. Force-rebuild because the adapter
and toolsmith images both changed.

```bash
cd cuga-apps/chief_of_staff
docker compose down
docker compose build --no-cache
docker compose up -d
sleep 30
curl -s http://localhost:8001/health | jq                  # toolsmith ok
```

### Test 1 — A no-auth API still works (regression)

UI: *"Tell me a random joke."*
Same flow as 3.5. Confirms the new exec path didn't break the simple case.

```bash
# Inspect the generated tool — under 3.6 the adapter actually exec()s it,
# rather than wrapping its URL with parameter substitution.
docker exec cuga-apps-cos-toolsmith \
  cat /app/chief_of_staff/data/tools/openapi__get_random_joke/tool.py
```

### Test 2 — The headline: an auth-required tool surfaces a credential prompt

UI: *"Search GitHub for popular Python repositories."*

✅ Pass criteria:
- Toolsmith matches the gap to `openapi:github_search`.
- Vault has no `github_token` for it.
- Toolsmith returns `success: false` with `needs_secrets`.
- Chat shows a **blue credential prompt card** below the agent's reply:
  > **GitHub Search API needs credentials**
  > github_token: [paste secret value] [Save]
  > (helpful instructions about generating a personal access token)
- Click into the field, paste a GitHub PAT, click **Save**.
- Card flips to green: *"Secret saved — re-ask your question."*

### Test 3 — Re-ask after providing the credential

UI: *"Search GitHub for popular Python repositories."* (again, same chat).

✅ Pass criteria:
- This time Toolsmith finds the secret, runs the probe (real GitHub API call),
  generates the tool via the Coder, registers it.
- Chat shows the green "Toolsmith built a tool" notice.
- Right-hand panel grows with `github_search_repos` (kind: generated).
- Re-asking gives a real list of repos.

### Test 4 — Direct vault interaction

```bash
# What's stored for a tool? (keys only, values never returned)
curl -s http://localhost:8765/vault/keys/openapi__github_search_repos | jq

# Set a secret directly
curl -s -X POST http://localhost:8765/vault/secret \
  -H 'Content-Type: application/json' \
  -d '{"tool_id":"openapi__openweather_current","secret_key":"openweather_api_key","value":"YOUR_KEY"}'

# Now ask "What's the current weather in Tokyo via OpenWeather?"
# Toolsmith should pick openweather (it's in the spec index now), find the
# key, build + probe + register the tool.
```

### Test 5 — Code execution sandbox

```bash
# Try to manually inject a hostile artifact and confirm the import allowlist blocks it.
docker exec cuga-apps-cos-toolsmith mkdir -p /app/chief_of_staff/data/tools/manual__danger
docker exec cuga-apps-cos-toolsmith bash -c 'cat > /app/chief_of_staff/data/tools/manual__danger/manifest.yaml << EOF
id: manual__danger
name: danger
description: hostile import
parameters_schema: {}
entry_point: tool.py
requires_secrets: []
provenance: {source: openapi}
version: 1
EOF'
docker exec cuga-apps-cos-toolsmith bash -c 'cat > /app/chief_of_staff/data/tools/manual__danger/tool.py << EOF
import subprocess
async def danger():
    return subprocess.check_output(["id"]).decode()
EOF'
# Force a backend resync. Adapter reload should NOT crash; instead the
# tool should be registered as an error stub that raises on call.
curl -s -X POST http://localhost:8765/internal/artifacts_changed | jq
docker logs cuga-apps-cos-adapter --tail 20 | grep "rejected"
# → "Artifact 'manual__danger' rejected: disallowed import: 'subprocess'"

# Confirm the tool exists in the agent but errors when invoked.
# Asking the chat to use 'danger' will surface the "disabled" error.
```

### Test 6 — Vault keyring backend (optional)

By default the vault uses SQLite + base64-XOR (clearly documented as
not-real-encryption). To switch to OS keyring:

```bash
# Linux containers usually don't have a working keyring backend; this is
# more meaningful when running the toolsmith service outside Docker.
TOOLSMITH_CMD="VAULT_BACKEND=keyring uvicorn chief_of_staff.toolsmith.server:app --port 8001"
# Then: curl -s http://localhost:8001/health | jq '.coder, .artifact_count'
# Backend reports the active backend in /vault/keys/<id> response.
```

### What "phase 3.6 passing" means

You've proven:
1. **Real code exec.** Coder-generated Python actually runs in the adapter.
2. **Auth UX.** Tools that need credentials surface a prompt; user provides; tool gets built.
3. **Sandboxing.** Hostile imports are caught before they execute.
4. **Vault separation.** Secrets travel from vault → adapter → tool, never to the UI or logs.
5. **Persistence still works.** Auth-aware artifacts survive restart; their secrets stay in the vault.

You can now wire any documented authenticated REST API into Toolsmith
just by adding it to spec_index.yaml — Stripe, Linear, Notion, Slack
webhooks, whatever fits the three supported auth schemes.

## Roadmap (phases 3.7+)

| Phase | Adds | Why |
|---|---|---|
| **3.7** | OAuth2 redirect flow + dynamic spec discovery (Smithery / openapi-directory search) | Unlocks Google / Microsoft / Slack / GitHub user-scoped APIs (calendar, drive, gmail, etc.) |
| **3.8** | Code-revision loop — failed probe → Coder is asked to revise based on the failure; up to N retries | Quality bump; closes the gap on flaky generation |
| **4** | Browser-task source — sites with no API at all; Toolsmith drives cuga's web-agent side | DoorDash / consumer-app class of problems |
| **4.5** | Tool composition — Toolsmith builds tools that compose existing tools. *"Ride summary"* = Uber API + receipt parser + categorizer. | Multi-step workflows |
| **5** | Health checks + auto-quarantine + auto-regenerate-from-provenance | Self-maintaining toolbox |
| **6** | Cross-domain mining over the unified data layer | Genuinely novel demos that siloed apps can't ship |

Phase 3.6 unlocked **bearer / api-key / query-param auth** — most documented REST APIs. Phase 3.7's OAuth2 flow is the next big jump because that's what every consumer-grade API uses.

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
