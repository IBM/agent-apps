# Running cuga-apps with Docker / Podman

All demo apps run in a single container alongside the umbrella UI and Arize Phoenix observability.

## Prerequisites

Install [Podman Desktop](https://podman-desktop.io) (Mac/Windows) or Docker Desktop, then make sure a VM is running:

```bash
# Podman — one-time VM setup
podman machine init
podman machine start

# Verify
podman info
```

## Build

```bash
# From the repo root
podman-compose build
# or: docker compose build
```

This builds two images:
- `Dockerfile.apps` — all 16 Python demo apps
- `ui/Dockerfile` — the React/nginx umbrella UI

Build takes several minutes the first time (downloads ~1 GB of Python deps including PyTorch). Subsequent builds reuse the layer cache and are fast.

## Start

```bash
podman-compose up -d
```

Services:

| Service | URL |
|---------|-----|
| Umbrella UI | http://localhost:3000 |
| Phoenix observability | http://localhost:6006 |
| All demo apps | see port table below |

## Stop

```bash
podman-compose down
```

## Logs

```bash
# All apps (streaming)
podman-compose logs -f apps

# UI or Phoenix
podman-compose logs -f ui
podman-compose logs -f phoenix

# Last 100 lines from apps
podman logs --tail 100 cuga-apps_apps_1
```

## App ports

| App | Port | URL |
|-----|------|-----|
| newsletter | 18793 | http://localhost:18793 |
| drop_summarizer | 18794 | http://localhost:18794 |
| web_researcher | 18798 | http://localhost:18798 |
| voice_journal | 18799 | http://localhost:18799 |
| smart_todo | 18800 | http://localhost:18800 |
| stock_alert | 18801 | http://localhost:18801 |
| video_qa | 8766 | http://localhost:8766 |
| server_monitor | 8767 | http://localhost:8767 |
| travel_planner | 8090 | http://localhost:8090 |
| deck_forge | 18802 | http://localhost:18802 |
| youtube_research | 18803 | http://localhost:18803 |
| arch_diagram | 18804 | http://localhost:18804 |
| hiking_research | 18805 | http://localhost:18805 |
| movie_recommender | 18806 | http://localhost:18806 |
| webpage_summarizer | 8071 | http://localhost:8071 |
| code_reviewer | 18807 | http://localhost:18807 |

## Tuning Podman VM memory

All 16 apps run in one container. Each Python process uses ~800 MB, so the VM needs at least 12 GB to run comfortably (default is 8 GB).

```bash
podman machine stop
podman machine set --memory 12288   # 12 GB — recommended
# podman machine set --memory 16384 # 16 GB — if you have it
podman machine start
```

Check current allocation:

```bash
podman machine inspect | grep -i memory
```

## Rebuilding after code changes

Changes to app code only (no new dependencies):

```bash
podman-compose build apps
podman-compose up -d
```

After adding a new package to `requirements.apps.txt`:

```bash
podman-compose build --no-cache apps
podman-compose up -d
```

## Troubleshooting

**"Cannot connect to Podman" / SSH handshake failed**

The Podman VM dropped its connection. Restart it:

```bash
podman machine stop && podman machine start
```

**"No space left on device" during build**

The Podman VM's disk is full. Prune unused images and build cache:

```bash
podman system prune -f
podman image prune -f
```

If it recurs, increase the VM disk size (requires recreating the machine):

```bash
podman machine stop
podman machine rm
podman machine init --disk-size 150   # GB
podman machine start
```

**"Container name already in use"**

Stale containers from a previous run. Remove them:

```bash
podman-compose down
podman container prune -f
```

Then retry `podman-compose up -d`.
