# Contributing a New App

This guide explains what it means to add a new demo app to the cuga-apps repo and exactly what you need to touch.

---

## What a "demo app" is

Each app is a self-contained FastAPI server that showcases a CugaAgent capability. It has its own directory under `apps/`, runs on a dedicated port, and gets a card in the umbrella UI. Apps share a single `.env` file and a single repo-level virtual environment.

---

## 1. Pick a port

Ports are assigned in blocks to avoid conflicts:

| Range | Used by |
|-------|---------|
| 8071–8090 | Miscellaneous / travel / summarizer |
| 8766–8767 | Video QA / Server Monitor |
| 18793–18807+ | Main demo app block |

**Rule:** use the next free integer in the `18xxx` block. Check the table in `README.md` to find the highest allocated port, then add 1.

Never hardcode a port that is already listed there.

---

## 2. Create the app directory

```
apps/
└── your_app_name/       # snake_case, matches the name in launch.py
    ├── main.py          # FastAPI server + CugaAgent + embedded HTML UI
    ├── requirements.txt # app-specific extra dependencies only
    └── README.md        # port, quick-start, env vars, example prompts
```

### main.py conventions

- Accept `--port` via argparse; default must match your chosen port.
- Bootstrap `sys.path` to include `apps/` so `from _llm import create_llm` works:
  ```python
  _DIR = Path(__file__).parent
  for _p in [str(_DIR), str(_DIR.parent)]:
      if _p not in sys.path:
          sys.path.insert(0, _p)
  ```
- Use `_llm.create_llm(provider=os.getenv("LLM_PROVIDER"), model=os.getenv("LLM_MODEL"))` — don't hardcode a provider.
- Agent should be lazily initialised on first request (avoids slow startup).
- Always expose a `GET /health` endpoint that returns `{"status": "ok"}`.

### requirements.txt conventions

Only list dependencies that are **not** already in `requirements.apps.txt`. At the top, leave a comment naming the shared packages you rely on:

```
# Code Reviewer — extra requirements
# (fastapi, uvicorn, pydantic, langchain-core, cuga are in the shared requirements)
some-extra-package
```

### README.md minimum content

- **Port** — the exact port number.
- **Quick start** — copy-pasteable `export` + `python main.py` commands.
- **Environment variables table** — which vars are required and why.
- **Example prompts** — 4–6 things a user can type to see the app work.

---

## 3. Register in launch.py

Open `apps/launch.py` and add one line to the `APPS` list, just before the closing comment:

```python
dict(name="your_app_name", dir="your_app_name", default_port=XXXXX, cmd=_python_cmd()),
```

- `name` — used as the CLI filter (`python launch.py start your_app_name`).
- `dir` — directory name under `apps/`.
- `default_port` — the port you picked in step 1.
- `cmd` — use `_python_cmd()` for `python main.py --port PORT`; use `_port_env_cmd()` if the app reads `PORT` from the environment instead.

---

## 4. Update requirements.apps.txt

If your app introduces a dependency that is **not** already in `requirements.apps.txt`, add it at the bottom with a section comment:

```
# ── your_app_name ─────────────────────────────────────────────
some-new-package
```

Do not add packages that are already listed (check before adding).

---

## 5. Add a card to the umbrella UI

Edit `ui/src/data/usecases.ts` and add a `UseCase` object to the `USE_CASES` array. Copy an existing entry and fill in all fields — nothing should be left blank or `null` for a working app.

Key fields to get right:

| Field | Notes |
|-------|-------|
| `id` | kebab-case, unique, matches the app name |
| `type` | `'other'` \| `'event-driven'` \| `'documents'` \| `'audio'` \| `'video'` \| `'images'` \| `'ppt'` |
| `surface` | `'gateway'` (human talks in real-time) or `'pipeline'` (runs on schedule/event) |
| `status` | `'working'` once the app runs end-to-end |
| `appUrl` | `http://localhost:YOUR_PORT` — must match the port you registered |
| `howToRun.command` | Copy-pasteable; include `--port YOUR_PORT` |
| `examples` | 4–6 real prompts a user can copy-paste |

---

## 6. Update README.md

Add a row to the **App ports** table:

```markdown
| your_app_name | XXXXX | http://localhost:XXXXX |
```

---

## Checklist

Before opening a PR, confirm every box:

- [ ] `apps/your_app_name/main.py` — uses `--port`, `/health`, lazy agent init
- [ ] `apps/your_app_name/requirements.txt` — only new deps, shared deps commented out
- [ ] `apps/your_app_name/README.md` — port, quick-start, env vars, examples
- [ ] `apps/launch.py` — new entry in `APPS` with correct port
- [ ] `requirements.apps.txt` — new packages added (if any)
- [ ] `ui/src/data/usecases.ts` — `UseCase` entry with matching `appUrl`
- [ ] `README.md` — port table updated
- [ ] Port does not conflict with any existing app (checked against README table)
- [ ] App starts cleanly: `python apps/your_app_name/main.py` → `GET /health` returns 200
