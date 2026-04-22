#!/usr/bin/env python3
"""
launch.py — start / stop all CUGAAgent demo apps in one shot.

Usage:
    python launch.py           # start all apps
    python launch.py start     # same
    python launch.py stop      # kill all running apps
    python launch.py status    # show which apps are running
    python launch.py logs      # show last 30 lines of each app's log
    python launch.py install   # pip install requirements.txt for all apps
    python launch.py start newsletter smart_todo   # start specific apps only
    python launch.py install stock_alert           # install one app only

ENV variables:
    Loaded from .env in the same directory as this script.
    Copy .env.example to .env and fill in your keys — all apps share one file.

Adding a new app:
    Append an entry to the APPS list below.  That's all.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# App registry
# Each entry:
#   name         — short identifier, also used to match CLI filters
#   dir          — path relative to this script (or absolute)
#   default_port — preferred port; if busy, the occupying process is killed
#                  and the port is reclaimed
#   cmd          — callable(port, env) → list[str] command to launch the process
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent.resolve()

# Use the repo-level venv so editable installs are on the path for all apps
# that don't have their own pyproject.toml.
_REPO_ROOT = HERE.parent  # apps/ -> cuga-apps/
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python3.13"
PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable


def _python_cmd(script: str = "main.py"):
    """Launch using the repo venv Python."""
    def _cmd(port: int, env: dict) -> list:
        return [PYTHON, script, "--port", str(port)]
    return _cmd


def _port_env_cmd(script: str = "main.py"):
    """Launch using the repo venv Python; port is passed via PORT env var."""
    def _cmd(port: int, env: dict) -> list:
        env["PORT"] = str(port)
        return [PYTHON, script]
    return _cmd


def _video_qa_cmd():
    """video_qa uses run.py with --web flag in addition to --port."""
    def _cmd(port: int, _env: dict) -> list:
        return [PYTHON, "run.py", "--web", "--port", str(port)]
    return _cmd


APPS: list[dict] = [
    # ── Add / remove entries here to control which apps are managed ──────────
    dict(name="newsletter",      dir="newsletter",      default_port=18793, cmd=_python_cmd()),
    dict(name="drop_summarizer", dir="drop_summarizer", default_port=18794, cmd=_python_cmd()),
    dict(name="web_researcher",  dir="web_researcher",  default_port=18798, cmd=_python_cmd()),
    dict(name="voice_journal",   dir="voice_journal",   default_port=18799, cmd=_python_cmd()),
    dict(name="smart_todo",      dir="smart_todo",      default_port=18800, cmd=_python_cmd()),
    dict(name="server_monitor",  dir="server_monitor",  default_port=8767,  cmd=_python_cmd()),
    dict(name="stock_alert",     dir="stock_alert",     default_port=18801, cmd=_python_cmd()),
    dict(name="video_qa",        dir="video_qa",        default_port=8766,  cmd=_video_qa_cmd()),
    dict(name="travel_planner",  dir="travel_planner",  default_port=8090,  cmd=_port_env_cmd()),
    dict(name="deck_forge",      dir="deck_forge",      default_port=18802, cmd=_python_cmd()),
    dict(name="youtube_research", dir="youtube_research", default_port=18803, cmd=_python_cmd()),
    dict(name="arch_diagram",    dir="arch_diagram",    default_port=18804, cmd=_python_cmd()),
    dict(name="hiking_research",    dir="hiking_research",    default_port=18805, cmd=_python_cmd()),
    dict(name="movie_recommender",  dir="movie_recommender",  default_port=18806, cmd=_python_cmd()),
    dict(name="webpage_summarizer", dir="webpage_summarizer", default_port=8071,  cmd=_python_cmd()),
    dict(name="code_reviewer",      dir="code_reviewer",      default_port=18807, cmd=_python_cmd()),
    dict(name="paper_scout",        dir="paper_scout",        default_port=18808, cmd=_python_cmd()),
    dict(name="wiki_dive",          dir="wiki_dive",          default_port=18809, cmd=_python_cmd()),
    dict(name="ibm_cloud_advisor",  dir="ibm_cloud_advisor",  default_port=18812, cmd=_python_cmd()),
    dict(name="ibm_docs_qa",        dir="ibm_docs_qa",        default_port=18813, cmd=_python_cmd()),
    # ── To add a new app, copy one line above and adjust the fields ──────────
]

# PID file — one line per running process: "name port pid\n"
PID_FILE = HERE / ".launch_pids"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env(env_path: Path) -> dict:
    """Parse a .env file and return its key=value pairs (no shell expansion)."""
    env = {}
    if not env_path.exists():
        return env
    with open(env_path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.split("#")[0].strip().strip("'\"")
            env[key.strip()] = val
    return env


def _pid_on_port(port: int) -> Optional[int]:
    """Return the PID of the process listening on *port*, or None."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True
        )
        pids = [int(p) for p in result.stdout.split() if p.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _claim_port(port: int) -> bool:
    """Ensure *port* is free — kill whatever is holding it if needed.
    Returns True if the port is now free, False if it could not be freed.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True  # already free
        except OSError:
            pass

    pid = _pid_on_port(port)
    if pid is None:
        return False  # can't determine who owns it

    print(f"  [EVICT] port {port} held by pid={pid} — sending SIGTERM")
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as e:
        print(f"  [WARN]  could not kill pid={pid}: {e}")
        return False

    # Wait up to 3 s for the port to be released
    import time
    for _ in range(15):
        time.sleep(0.2)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                pass

    print(f"  [WARN]  port {port} still busy after SIGTERM — trying SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    time.sleep(0.5)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _read_pids() -> list[tuple[str, int, int]]:
    """Return [(name, port, pid), ...] from the PID file."""
    records = []
    if not PID_FILE.exists():
        return records
    with open(PID_FILE) as fh:
        for line in fh:
            parts = line.strip().split()
            if len(parts) == 3:
                records.append((parts[0], int(parts[1]), int(parts[2])))
    return records


def _write_pids(records: list[tuple[str, int, int]]):
    with open(PID_FILE, "w") as fh:
        for name, port, pid in records:
            fh.write(f"{name} {port} {pid}\n")


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_install(filter_names: Optional[list[str]]):
    """Run pip install -r requirements.txt for each app that has one."""
    targets = [a for a in APPS if (not filter_names or a["name"] in filter_names)]
    for app in targets:
        req = HERE / app["dir"] / "requirements.txt"
        if not req.exists():
            print(f"  [SKIP]  {app['name']:20s}  no requirements.txt")
            continue
        print(f"  [INSTALL] {app['name']:20s}  {req}")
        result = subprocess.run(
            [PYTHON, "-m", "pip", "install", "-r", str(req)],
            capture_output=False,
        )
        if result.returncode != 0:
            print(f"  [ERROR] {app['name']:20s}  pip install failed (exit {result.returncode})")


def cmd_start(filter_names: Optional[list[str]], env_file: Path):
    print("--- Installing dependencies ---")
    cmd_install(filter_names)
    print("--- Starting apps ---")

    dotenv = _load_env(env_file)
    merged_env = {**os.environ, **dotenv}

    existing = {name: (port, pid) for name, port, pid in _read_pids() if _is_running(pid)}
    new_records = list(_read_pids())

    targets = [a for a in APPS if (not filter_names or a["name"] in filter_names)]

    started = []
    skipped = []

    for app in targets:
        name = app["name"]
        if name in existing:
            skipped.append((name, existing[name][0]))
            continue

        port = app["default_port"]
        if not _claim_port(port):
            print(f"  [SKIP]  {name}: could not free port {port}")
            continue

        app_dir = HERE / app["dir"]
        command = app["cmd"](port, merged_env)

        log_path = HERE / f".{name}.log"
        log_fh = open(log_path, "w")

        proc = subprocess.Popen(
            command,
            cwd=str(app_dir),
            env=merged_env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        started.append((name, port, proc.pid))
        new_records = [(n, p, pid) for n, p, pid in new_records if n != name]
        new_records.append((name, port, proc.pid))
        print(f"  [START] {name:20s}  port={port}  pid={proc.pid}  log={log_path.name}")

    _write_pids(new_records)

    if skipped:
        for name, port in skipped:
            print(f"  [SKIP]  {name:20s}  already running on port={port}")

    if started:
        print(f"\nStarted {len(started)} app(s). Give them a few seconds to initialise.")
        print("Run `python3 launch.py status` to confirm.")
    else:
        print("Nothing new to start.")


def cmd_stop(filter_names: Optional[list[str]]):
    records = _read_pids()
    remaining = []
    stopped = []

    for name, port, pid in records:
        if filter_names and name not in filter_names:
            remaining.append((name, port, pid))
            continue
        if _is_running(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            stopped.append((name, pid))
            print(f"  [STOP]  {name:20s}  pid={pid}")
        else:
            print(f"  [GONE]  {name:20s}  pid={pid} (already dead)")

    _write_pids(remaining)

    if not stopped and not [r for r in records if not filter_names or r[0] in filter_names]:
        print("No running apps found.")


def cmd_status():
    records = _read_pids()
    if not records:
        print("No apps tracked (PID file empty or missing).")
        return

    print(f"  {'App':<20}  {'Port':>6}  {'PID':>7}  Status")
    print(f"  {'-'*20}  {'------':>6}  {'-------':>7}  ------")
    for name, port, pid in records:
        status = "running" if _is_running(pid) else "stopped"
        print(f"  {name:<20}  {port:>6}  {pid:>7}  {status}")


def cmd_logs(filter_names: Optional[list[str]], tail_lines: int = 30):
    targets = [a["name"] for a in APPS if (not filter_names or a["name"] in filter_names)]
    for name in targets:
        log_path = HERE / f".{name}.log"
        if not log_path.exists():
            print(f"=== {name} — no log found ===\n")
            continue
        lines = log_path.read_text().splitlines()
        shown = lines[-tail_lines:] if len(lines) > tail_lines else lines
        print(f"=== {name} (last {len(shown)} lines of {log_path.name}) ===")
        print("\n".join(shown))
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Start / stop all CUGAAgent demo apps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["start", "stop", "status", "logs", "install"],
        default="start",
        help="Action to perform (default: start)",
    )
    parser.add_argument(
        "apps",
        nargs="*",
        metavar="APP",
        help="Optional list of app names to target (default: all)",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=HERE / ".env",
        metavar="FILE",
        help="Path to .env file (default: .env next to this script)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=30,
        metavar="N",
        help="Number of log lines to show per app (default: 30, used with 'logs')",
    )

    args = parser.parse_args()
    filter_names = args.apps or None

    print(f"\n=== CUGAAgent Demo Launcher — {args.action.upper()} ===\n")

    if args.action == "install":
        cmd_install(filter_names)
    elif args.action == "start":
        cmd_start(filter_names, args.env)
    elif args.action == "stop":
        cmd_stop(filter_names)
    elif args.action == "status":
        cmd_status()
    elif args.action == "logs":
        cmd_logs(filter_names, args.tail)


if __name__ == "__main__":
    main()
