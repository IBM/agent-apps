# Server Monitor

Real-time server health monitoring with a browser UI. The app collects metrics,
checks thresholds, and only calls the agent when something needs diagnosing.
The agent answers natural-language health questions and writes alert reports.

**Port:** 8767

---

## Division of Responsibilities

### The App (main.py + metrics.py)

- **Collects metrics** via `psutil` — CPU, RAM, disk, load averages (no LLM)
- **Checks thresholds** — pure numeric comparison against configurable warn/critical levels
- **Decides when to alert** — cooldown logic prevents alert spam (no LLM)
- **Calls the agent** only when a threshold is breached, passing a pre-built metrics snapshot
- **Serves the web UI** — live gauges, chat, alert log, settings (FastAPI)
- **Persists settings** to `.store.json` (thresholds, poll interval, cooldown)

### CugaAgent

The agent receives system metrics (already collected) and answers with a diagnosis
or a direct response. It has read-only tools to drill deeper when needed.

| Invocation | Input | Output |
|---|---|---|
| Threshold breach | Metrics snapshot + alert context | Diagnosis report |
| User chat question | Free-form question | Health answer |

### Agent Tools

| Tool | What it does | Data source |
|---|---|---|
| `get_system_metrics` | Full health snapshot: CPU/RAM/disk/load/severity | psutil |
| `list_top_processes` | Top N processes by CPU or memory | psutil |
| `check_disk_usage` | Directory-level disk breakdown under a path | psutil |
| `find_large_files` | Files exceeding N MB under a path | os.walk |
| `get_service_status` | Status of a named service | systemctl / launchctl |
| `run_safe_command` | Read-only allowlisted shell commands | subprocess |

Tools are **read-only**. The agent is a diagnostician, not an operator — it
never modifies the system, never kills processes, never restarts services.

### Agent Instructions

Tool usage order, severity levels, report format, and safety constraints are inlined as `special_instructions` in `make_agent()` inside `main.py`.

---

## Quick Start

```bash
pip install -r requirements.txt
python main.py
# open http://127.0.0.1:8767
```

---

## UI Panels

**Live Metrics** — CPU, RAM, disk, load gauges. Colour-coded (green → yellow → red).
Auto-refreshes every 15 seconds.

**Ask the Agent** — natural-language chat. Example questions:
```
What's the current server health?
What's using the most CPU right now?
What's eating my disk?
Why is the server slow?
Is nginx running?
Find files larger than 500MB
```

**Alert Log** — threshold breach diagnoses from the background monitor. Click any
entry to expand. Use **Check now** to trigger an immediate check.

**Alert Settings** — configure poll interval, cooldown, and warn/critical
thresholds for CPU, RAM, and disk. Changes persist to `.store.json`.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | — | `rits` \| `anthropic` \| `openai` \| `ollama` \| `watsonx` |
| `LLM_MODEL` | — | Model override |
| `POLL_INTERVAL_SECONDS` | `60` | Metric poll frequency |
| `ALERT_COOLDOWN_SECONDS` | `900` | Min seconds between repeated alerts |
| `CPU_THRESHOLD` | `75` | CPU warn % |
| `CPU_CRITICAL` | `90` | CPU critical % |
| `RAM_THRESHOLD` | `80` | RAM warn % |
| `RAM_CRITICAL` | `92` | RAM critical % |
| `DISK_THRESHOLD` | `80` | Disk warn % |
| `DISK_CRITICAL` | `90` | Disk critical % |
| `ALLOWED_SERVICES` | `nginx,postgres,redis,docker,sshd,cron` | Services the agent may query |

Env vars set initial defaults. UI settings (persisted in `.store.json`) take
precedence after the first save.

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Agent, background monitor, FastAPI UI |
| `metrics.py` | Pure metric functions — psutil + stdlib, no LLM |
| `_SYSTEM` in `main.py` | Agent instructions — tools, severity levels, report formats, safety rules (inlined) |
| `requirements.txt` | Python dependencies |
| `.store.json` | Persisted thresholds and poll settings |
