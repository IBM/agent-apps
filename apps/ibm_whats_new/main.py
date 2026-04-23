"""
IBM What's New Monitor — web UI powered by CugaAgent
=====================================================
Tracks IBM Cloud service release notes and "What's New" announcements.
Configure which services to watch, then get a scheduled digest or ask
ad-hoc questions about recent IBM Cloud changes.

Run:
    python main.py
    python main.py --port 18814
    python main.py --provider anthropic

Then open: http://127.0.0.1:18814

Prerequisites:
    pip install -r requirements.txt
    export TAVILY_API_KEY=...   # required

Environment variables:
    LLM_PROVIDER         rits | anthropic | openai | ollama | watsonx | litellm
    LLM_MODEL            model override
    AGENT_SETTING_CONFIG path to agent settings TOML
    TAVILY_API_KEY       Tavily API key (required)
    SMTP_HOST            smtp.gmail.com (optional)
    SMTP_USERNAME        sender email
    SMTP_PASSWORD        app password
    DIGEST_TO            recipient email for digests
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import smtplib
import sys
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
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

_DEFAULT_SERVICES = [
    "Code Engine",
    "watsonx.ai",
    "IBM Kubernetes Service",
    "Databases for PostgreSQL",
    "Cloud Object Storage",
]


def _load_store() -> dict:
    try:
        return json.loads(_STORE_PATH.read_text()) if _STORE_PATH.exists() else {}
    except Exception as exc:
        log.warning("Could not read store: %s", exc)
        return {}


def _save_store(data: dict) -> None:
    try:
        _STORE_PATH.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        log.warning("Could not write store: %s", exc)


def _update_store(**fields) -> None:
    data = _load_store()
    data.update(fields)
    _save_store(data)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _make_tools():
    from langchain_core.tools import tool

    def _is_ibm_url(url: str) -> bool:
        try:
            from urllib.parse import urlparse
            host = urlparse(url).netloc.lstrip("www.")
            return any(host == d or host.endswith("." + d)
                       for d in {"ibm.com", "cloud.ibm.com"})
        except Exception:
            return False

    @tool
    def search_ibm_updates(query: str) -> str:
        """Search IBM Cloud documentation for recent updates, release notes, and what's new
        announcements. Use focused queries like 'IBM Code Engine release notes 2026' or
        'IBM watsonx.ai what is new April 2026'. Run one search per service or topic.

        Args:
            query: Search terms targeting a specific IBM service and recency,
                   e.g. 'IBM Event Streams what is new 2026',
                        'IBM Cloud Object Storage release notes recent changes'.

        Returns:
            JSON with search results: title, url, content snippet.
        """
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return json.dumps({"error": "TAVILY_API_KEY not set."})
        try:
            from tavily import TavilyClient
            client  = TavilyClient(api_key=api_key)
            results = client.search(
                f"{query} site:ibm.com OR site:cloud.ibm.com",
                max_results=5,
                search_depth="advanced",
            )
            items = [
                {
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "snippet": r.get("content", "")[:500],
                }
                for r in results.get("results", [])
            ]
            log.info("search_ibm_updates(%r): %d results", query, len(items))
            return json.dumps({"query": query, "results": items})
        except Exception as exc:
            return json.dumps({"error": str(exc), "results": []})

    @tool
    def fetch_release_notes(url: str) -> str:
        """Fetch and read the full text of an IBM Cloud release notes or what's new page.
        Use this after search_ibm_updates when a result looks highly relevant and you need
        the complete content rather than just the snippet.
        Only fetches URLs on cloud.ibm.com or ibm.com.

        Args:
            url: Full URL of an IBM docs page, e.g.
                 'https://cloud.ibm.com/docs/code-engine?topic=code-engine-release-notes'

        Returns:
            JSON with page title and extracted text (up to 6000 chars).
        """
        if not _is_ibm_url(url):
            return json.dumps({"error": f"Refused: only IBM URLs are allowed, got: {url}"})
        try:
            import httpx
            from bs4 import BeautifulSoup

            resp  = httpx.get(url, timeout=15, follow_redirects=True,
                              headers={"User-Agent": "cuga-ibm-whats-new/1.0"})
            soup  = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else url

            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
                tag.decompose()

            content = soup.find("main") or soup.find("article") or soup.body
            if not content:
                return json.dumps({"error": "Could not extract content."})

            lines = [l for l in content.get_text(separator="\n", strip=True).splitlines() if l.strip()]
            text  = "\n".join(lines)[:6000]
            log.info("fetch_release_notes(%r): %d chars", url, len(text))
            return json.dumps({"url": url, "title": title, "content": text})
        except Exception as exc:
            return json.dumps({"error": str(exc), "url": url})

    return [search_ibm_updates, fetch_release_notes]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
# IBM What's New Monitor

You track IBM Cloud service release notes and "What's New" announcements.

## Tools

| Tool | When to use |
|---|---|
| `search_ibm_updates(query)` | Find recent IBM Cloud updates. Use targeted queries: "IBM <service> release notes 2026" or "IBM <service> what is new". One search per service. |
| `fetch_release_notes(url)` | Read the full release notes page when a search result looks highly relevant. |

Always call tools. Never fabricate dates, version numbers, or feature names.

---

## Digest mode (checking a service for updates)

When asked to check what is new for a specific IBM Cloud service:
1. Call `search_ibm_updates("IBM <service> release notes what is new 2026")`.
2. If a release notes page appears in the results, call `fetch_release_notes(url)` on it.
3. Extract: new features, fixes, breaking changes, deprecations — with dates where available.
4. If meaningful updates were found, begin your response with exactly `UPDATE:` on the first line.
5. If nothing new or relevant: respond with exactly `No updates found for: <service>` — nothing more.

Format for updates:
  **IBM Code Engine** — release notes
  - [Apr 2026] Support for custom domain mapping in private visibility apps
  - [Mar 2026] Cold start latency reduced by up to 40%

---

## Query mode (ad-hoc chat)

For free-form questions about IBM Cloud changes:
- Use `search_ibm_updates` with targeted terms, then optionally fetch 1–2 pages for depth.
- Answer concisely and cite every source with title + URL.
- Include dates where available.

---

## Format rules

- **Bold** service names and key feature names.
- No fabricated facts — if you cannot find it, say so.
- No filler, no disclaimers.
"""


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def make_agent():
    _provider_toml = {
        "rits":      "settings.rits.toml",
        "watsonx":   "settings.watsonx.toml",
        "openai":    "settings.openai.toml",
        "anthropic": "settings.openai.toml",
        "litellm":   "settings.litellm.toml",
        "ollama":    "settings.openai.toml",
    }
    provider = (os.getenv("LLM_PROVIDER") or "").lower()
    os.environ.setdefault("AGENT_SETTING_CONFIG",
                          _provider_toml.get(provider, "settings.rits.toml"))

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
# Email
# ---------------------------------------------------------------------------

_email_config: dict = {}


def _get_email_cfg() -> dict:
    return {
        "host":     _email_config.get("host")     or os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "user":     _email_config.get("user")     or os.getenv("SMTP_USERNAME", ""),
        "password": _email_config.get("password") or os.getenv("SMTP_PASSWORD", ""),
        "to":       _email_config.get("to")       or os.getenv("DIGEST_TO", ""),
    }


def _send_email(subject: str, body: str) -> bool:
    cfg = _get_email_cfg()
    if not (cfg["to"] and cfg["user"] and cfg["password"]):
        log.info("[EMAIL — not configured] %s", subject)
        return False
    msg            = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = cfg["user"]
    msg["To"]      = cfg["to"]
    try:
        with smtplib.SMTP_SSL(cfg["host"], 465) as smtp:
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        log.info("Email sent → %s  subject=%s", cfg["to"], subject)
        return True
    except Exception as exc:
        log.error("Failed to send email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Digest runner + background scheduler
# ---------------------------------------------------------------------------

_digest_log: list[dict] = []   # capped at 15 entries


async def _run_digest(agent, services: list[str]) -> dict:
    """Check all tracked services for new updates. Returns a log entry."""
    if not services:
        return {
            "id":        str(uuid.uuid4())[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary":   "No services configured.",
            "updates":   [],
            "sent":      False,
        }

    updates: list[str] = []
    for service in services:
        prompt = (
            f"Check what is new for IBM Cloud service: {service}\n"
            f"Use search_ibm_updates to find recent release notes for {service}.\n"
            f"If you find updates, start with 'UPDATE:' and list them.\n"
            f"If nothing found, respond with 'No updates found for: {service}'"
        )
        try:
            result = await agent.invoke(prompt, thread_id=f"digest-{service.replace(' ', '-')}")
            answer = result.answer
        except Exception as exc:
            answer = f"Error checking {service}: {exc}"

        log.info("[DIGEST] %s → %s", service, answer[:80])
        if answer.strip().startswith("UPDATE:"):
            updates.append(answer)

    sent = False
    if updates:
        body    = "\n\n---\n\n".join(updates)
        subject = f"IBM What's New — {datetime.now(timezone.utc).strftime('%b %d, %Y')}"
        sent    = _send_email(subject, body)

    entry = {
        "id":        str(uuid.uuid4())[:8],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary":   f"{len(updates)} service(s) updated out of {len(services)} checked.",
        "updates":   updates,
        "sent":      sent,
    }
    _digest_log.insert(0, entry)
    if len(_digest_log) > 15:
        _digest_log.pop()

    _update_store(last_run=entry["timestamp"])
    return entry


async def _digest_scheduler(agent) -> None:
    """Background task: checks whether a scheduled digest is due every 5 minutes."""
    while True:
        await asyncio.sleep(300)  # check every 5 minutes
        data     = _load_store()
        schedule = data.get("schedule", "daily")
        if schedule == "off":
            continue

        last_run = data.get("last_run")
        now      = datetime.now(timezone.utc)
        due      = False

        if last_run is None:
            due = True
        else:
            try:
                elapsed = (now - datetime.fromisoformat(last_run)).total_seconds()
                if schedule == "daily"  and elapsed >= 86400:
                    due = True
                elif schedule == "weekly" and elapsed >= 604800:
                    due = True
            except Exception:
                due = True

        if not due:
            continue

        services = data.get("services", [])
        log.info("[SCHEDULER] Digest due (%s) — checking %d services", schedule, len(services))
        await _run_digest(agent, services)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class AskReq(BaseModel):
    question: str


class ServiceAddReq(BaseModel):
    name: str


class ServiceRemoveReq(BaseModel):
    name: str


class ScheduleReq(BaseModel):
    schedule: str   # "daily" | "weekly" | "off"


class EmailConfigReq(BaseModel):
    host: str = "smtp.gmail.com"
    user: str
    password: str
    to: str


class EmailSendReq(BaseModel):
    subject: str
    body: str


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def _web(port: int) -> None:
    import uvicorn
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    from ui import _HTML

    _agent = make_agent()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        asyncio.create_task(_digest_scheduler(_agent))
        yield

    app = FastAPI(title="IBM What's New Monitor", docs_url=None, redoc_url=None,
                  lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    # Restore persisted state
    stored = _load_store()
    if stored.get("email"):
        global _email_config
        _email_config = stored["email"]
        log.info("Restored email config → %s", _email_config.get("to"))
    if not stored.get("services"):
        _update_store(services=_DEFAULT_SERVICES, schedule="daily")
        log.info("Initialized default services")
    else:
        log.info("Restored %d service(s), schedule=%s",
                 len(stored.get("services", [])), stored.get("schedule", "daily"))

    # ── Chat ──────────────────────────────────────────────────────────────────

    @app.post("/ask")
    async def api_ask(req: AskReq):
        try:
            result = await _agent.invoke(req.question, thread_id="chat")
            return {"answer": result.answer}
        except Exception as exc:
            log.exception("Agent error")
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ── Services ──────────────────────────────────────────────────────────────

    @app.get("/services")
    def services_list():
        data = _load_store()
        return {"services": data.get("services", []), "schedule": data.get("schedule", "daily")}

    @app.post("/services/add")
    def services_add(req: ServiceAddReq):
        data     = _load_store()
        services = data.get("services", [])
        name     = req.name.strip()
        if name and name not in services:
            services.append(name)
            data["services"] = services
            _save_store(data)
        return {"services": _load_store().get("services", [])}

    @app.post("/services/remove")
    def services_remove(req: ServiceRemoveReq):
        data     = _load_store()
        services = [s for s in data.get("services", []) if s != req.name]
        data["services"] = services
        _save_store(data)
        return {"services": services}

    @app.post("/schedule")
    def schedule_set(req: ScheduleReq):
        _update_store(schedule=req.schedule)
        return {"schedule": req.schedule}

    # ── Digest ────────────────────────────────────────────────────────────────

    @app.post("/digest/run")
    async def digest_run():
        services = _load_store().get("services", [])
        entry    = await _run_digest(_agent, services)
        return entry

    @app.get("/digest/recent")
    def digest_recent():
        return {"log": _digest_log}

    # ── Email ─────────────────────────────────────────────────────────────────

    @app.post("/email/config")
    def email_config(req: EmailConfigReq):
        global _email_config
        _email_config = {"host": req.host, "user": req.user,
                         "password": req.password, "to": req.to}
        _update_store(email=_email_config)
        log.info("Email config updated → %s", req.to)
        return {"status": "saved", "to": req.to}

    @app.get("/email/status")
    def email_status():
        cfg        = _get_email_cfg()
        configured = bool(cfg["to"] and cfg["user"] and cfg["password"])
        return {"configured": configured, "to": cfg["to"],
                "host": cfg["host"], "user": cfg["user"]}

    @app.post("/email/send")
    def email_send(req: EmailSendReq):
        sent = _send_email(req.subject, req.body)
        return {"status": "sent" if sent else "not_configured"}

    # ── UI ────────────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def ui():
        return HTMLResponse(_HTML)

    print(f"\n  IBM What's New Monitor  →  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IBM What's New Monitor")
    parser.add_argument("--port",     type=int, default=18814)
    parser.add_argument("--provider", "-p", default=None,
        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"])
    parser.add_argument("--model", "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    _web(args.port)
