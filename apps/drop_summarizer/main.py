"""
Drop Summarizer — folder-watcher + web UI
==========================================

Drop any .txt, .md, .pdf, or image file into the inbox folder.
The background watcher detects it, summarizes/analyzes it with the agent,
and the result appears instantly in the browser.

Supports: .txt, .md, .pdf, .png, .jpg, .jpeg, .tiff, .bmp, .gif
Images and PDFs are processed via docling for rich content extraction.

Optional email alerts: configure keywords — if a summary contains them, an
email is sent to your configured address.

Run:
    python main.py
    python main.py --port 18794
    python main.py --provider anthropic

Then open: http://127.0.0.1:18794

Environment variables:
    LLM_PROVIDER     rits | anthropic | openai | ollama | watsonx | litellm
    LLM_MODEL        model override
    WATCH_DIR        folder to watch (default: ./inbox)
    POLL_SECONDS     polling interval (default: 15)
    SMTP_HOST        SMTP server (default: smtp.gmail.com)
    SMTP_USERNAME    sender email
    SMTP_PASSWORD    app password
    ALERT_TO         recipient email for alerts

Required for images/PDFs:
    pip install docling
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import smtplib
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

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

TEXT_EXTENSIONS  = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"}
PDF_EXTENSIONS   = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | PDF_EXTENSIONS

# ---------------------------------------------------------------------------
# Persistent store — .store.json
# ---------------------------------------------------------------------------

_STORE_PATH = _DIR / ".store.json"
_DEFAULT_STORE = {
    "poll_seconds": int(os.getenv("POLL_SECONDS", "15")),
    "watch_dir": os.getenv("WATCH_DIR", str(_DIR / "inbox")),
    "alert_keywords": [],
    "email": {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "user": os.getenv("SMTP_USERNAME", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "to": os.getenv("ALERT_TO", ""),
    },
}


def _load_store() -> dict:
    try:
        if _STORE_PATH.exists():
            return json.loads(_STORE_PATH.read_text())
    except Exception as exc:
        log.warning("Store read error: %s", exc)
    return {}


def _get_store() -> dict:
    stored = _load_store()
    result = dict(_DEFAULT_STORE)
    result.update({k: v for k, v in stored.items() if v})
    if "email" in stored:
        result["email"] = {**_DEFAULT_STORE["email"], **stored["email"]}
    return result


def _save_store(data: dict) -> None:
    try:
        _STORE_PATH.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        log.warning("Store write error: %s", exc)


# ---------------------------------------------------------------------------
# SQLite summary log
# ---------------------------------------------------------------------------

_DB_PATH = _DIR / "summaries.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS summaries (
    id         TEXT PRIMARY KEY,
    filename   TEXT NOT NULL,
    summary    TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    word_count INTEGER DEFAULT 0,
    alerted    INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _init_db() -> None:
    with _db() as con:
        con.execute(_CREATE_SQL)
        # migrate existing DBs that predate the content column
        try:
            con.execute("ALTER TABLE summaries ADD COLUMN content TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # column already exists


def _save_summary(filename: str, summary: str, content: str = "",
                  alerted: bool = False) -> dict:
    entry_id = uuid.uuid4().hex[:8]
    now      = datetime.now(timezone.utc).isoformat()
    wc       = len(summary.split())
    with _db() as con:
        con.execute(
            "INSERT INTO summaries (id, filename, summary, content, word_count, alerted, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (entry_id, filename, summary, content, wc, int(alerted), now),
        )
    return {"id": entry_id, "filename": filename, "summary": summary,
            "content": content, "word_count": wc, "alerted": alerted, "created_at": now}


def _list_summaries(limit: int = 50) -> list[dict]:
    with _db() as con:
        # exclude content from list view (can be large); content fetched per-file on demand
        rows = con.execute(
            "SELECT id, filename, summary, word_count, alerted, created_at "
            "FROM summaries ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def _get_summary_content(filename: str) -> str | None:
    """Return the stored full content for a specific filename (most recent)."""
    with _db() as con:
        row = con.execute(
            "SELECT content FROM summaries WHERE filename=? ORDER BY created_at DESC LIMIT 1",
            (filename,)
        ).fetchone()
    return row["content"] if row else None


# ---------------------------------------------------------------------------
# Content extraction — app-side, no agent involvement
# ---------------------------------------------------------------------------

def _extract_content(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        from docling.document_converter import DocumentConverter
        result   = DocumentConverter().convert(str(path))
        markdown = result.document.export_to_markdown()
        return markdown if markdown.strip() else "(no text extracted — file may be purely graphical)"
    except ImportError:
        return f"(docling not installed — run: pip install docling)\nFile: {path.name}"
    except Exception as exc:
        return f"(extraction error: {exc})"


# ---------------------------------------------------------------------------
# Agent — no tools, just text in / text out
# ---------------------------------------------------------------------------

def make_agent():
    from cuga import CugaAgent
    from cuga_skills import CugaSkillsPlugin
    from _llm import create_llm

    return CugaAgent(
        model=create_llm(
            provider=os.getenv("LLM_PROVIDER"),
            model=os.getenv("LLM_MODEL"),
        ),
        tools=[],
        plugins=[CugaSkillsPlugin(skills_dir=str(_DIR / "skills"))],
        cuga_folder=str(_DIR / ".cuga"),
    )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_email(subject: str, body: str) -> bool:
    cfg = _get_store().get("email", {})
    if not (cfg.get("to") and cfg.get("user") and cfg.get("password")):
        log.info("[EMAIL — not configured] %s", subject)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["user"]
        msg["To"]      = cfg["to"]
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL(cfg.get("host", "smtp.gmail.com"), 465) as smtp:
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        log.info("Email sent → %s", cfg["to"])
        return True
    except Exception as exc:
        log.error("Email failed: %s", exc)
        return False



# ---------------------------------------------------------------------------
# Background watcher loop
# ---------------------------------------------------------------------------

_watcher_status = {"running": False, "last_check": None, "processed": 0}


async def _watcher_loop(agent) -> None:
    _watcher_status["running"] = True
    while True:
        cfg        = _get_store()
        interval   = cfg.get("poll_seconds", 15)
        watch_path = Path(cfg.get("watch_dir", str(_DIR / "inbox")))
        keywords   = [kw.lower().strip() for kw in cfg.get("alert_keywords", []) if kw.strip()]

        _watcher_status["last_check"] = datetime.now(timezone.utc).isoformat()

        if watch_path.exists():
            processed_dir = watch_path / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)

            files = [
                f for f in watch_path.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            ]

            for file_path in files:
                dest = processed_dir / file_path.name
                try:
                    shutil.move(str(file_path), str(dest))
                except Exception as exc:
                    log.warning("Could not move %s: %s", file_path.name, exc)
                    continue

                log.info("Processing: %s", file_path.name)
                try:
                    # 1. App extracts content — no agent involvement
                    content = _extract_content(dest)

                    # 2. Agent summarizes the extracted text
                    result = await agent.invoke(
                        f"Summarize the following document.\n\nFilename: {file_path.name}\n\n{content[:12000]}",
                        thread_id=f"sum-{file_path.stem}",
                    )
                    summary = result.answer

                    # 3. Keyword alert check
                    alerted = False
                    if keywords and any(kw in summary.lower() for kw in keywords):
                        matched = [kw for kw in keywords if kw in summary.lower()]
                        subject = f"📄 Drop Alert: {file_path.name} — keywords: {', '.join(matched)}"
                        alerted = _send_email(subject, f"File: {file_path.name}\n\nSummary:\n{summary}")

                    # 4. Store summary (for display) and full content (for Q&A)
                    _save_summary(file_path.name, summary, content=content, alerted=alerted)
                    _watcher_status["processed"] += 1
                    log.info("Done: %s (%d words extracted)", file_path.name, len(content.split()))

                except Exception as exc:
                    log.error("Error processing %s: %s", file_path.name, exc)
                    _save_summary(file_path.name, f"Error: {exc}", content="", alerted=False)

        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class AskReq(BaseModel):
    question: str
    filename: str | None = None


class EmailConfigReq(BaseModel):
    host: str = "smtp.gmail.com"
    user: str = ""
    password: str = ""
    to: str = ""


class KeywordsReq(BaseModel):
    keywords: list[str] = []


class PollReq(BaseModel):
    poll_seconds: int = 15
    watch_dir: str = ""


# ---------------------------------------------------------------------------
# Web app
# ---------------------------------------------------------------------------

def _web(port: int) -> None:
    import uvicorn

    _init_db()
    agent = make_agent()

    app = FastAPI(title="Drop Summarizer")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.on_event("startup")
    async def _startup():
        # Create inbox
        watch_dir = Path(_get_store().get("watch_dir", str(_DIR / "inbox")))
        watch_dir.mkdir(parents=True, exist_ok=True)
        asyncio.create_task(_watcher_loop(agent))
        log.info("Watcher started — watching %s", watch_dir)

    # ── Summaries ──────────────────────────────────────────────────────────
    @app.get("/summaries")
    async def api_summaries():
        return _list_summaries()

    # ── Upload file directly ───────────────────────────────────────────────
    @app.post("/upload")
    async def api_upload(file: UploadFile = File(...)):
        store     = _get_store()
        watch_dir = Path(store.get("watch_dir", str(_DIR / "inbox")))
        watch_dir.mkdir(parents=True, exist_ok=True)
        dest = watch_dir / file.filename
        content = await file.read()
        dest.write_bytes(content)
        return {"ok": True, "filename": file.filename, "message": "File queued for summarization."}

    # ── Chat (ask over files) ──────────────────────────────────────────────
    @app.post("/ask")
    async def api_ask(req: AskReq):
        try:
            if req.filename:
                # Scoped to a specific file — use full extracted content
                full_content = _get_summary_content(req.filename)
                all_s  = _list_summaries(200)
                match  = next((s for s in all_s if s["filename"] == req.filename), None)
                thread = f"file-{match['id']}" if match else "chat"
                if full_content:
                    prompt = (
                        f"The user is asking about this specific file.\n\n"
                        f"File: {req.filename}\n"
                        f"Full content:\n{full_content[:16000]}\n\n"
                        f"Question: {req.question}"
                    )
                elif match:
                    # fallback to summary if content wasn't stored (legacy row)
                    prompt = (
                        f"File: {match['filename']}\n"
                        f"Summary:\n{match['summary']}\n\n"
                        f"Question: {req.question}"
                    )
                else:
                    prompt = req.question
                    thread = "chat"
            else:
                # General — inject recent summaries as context
                recent  = _list_summaries(10)
                context = "\n\n".join(
                    f"File: {s['filename']}\nSummary: {s['summary']}"
                    for s in recent
                )
                prompt = (
                    f"Recent file summaries:\n{context}\n\n"
                    f"User question: {req.question}"
                ) if recent else req.question
                thread = "chat"
            result = await agent.invoke(prompt, thread_id=thread)
            return {"answer": result.answer}
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ── Settings ───────────────────────────────────────────────────────────
    @app.get("/settings")
    async def api_get_settings():
        return _get_store()

    @app.post("/settings/email")
    async def api_email(req: EmailConfigReq):
        data = _load_store()
        data["email"] = req.model_dump()
        _save_store(data)
        return {"ok": True}

    @app.post("/settings/keywords")
    async def api_keywords(req: KeywordsReq):
        data = _load_store()
        data["alert_keywords"] = req.keywords
        _save_store(data)
        return {"ok": True}

    @app.post("/settings/poll")
    async def api_poll(req: PollReq):
        data = _load_store()
        data["poll_seconds"] = req.poll_seconds
        if req.watch_dir:
            data["watch_dir"] = req.watch_dir
            Path(req.watch_dir).mkdir(parents=True, exist_ok=True)
        _save_store(data)
        return {"ok": True}

    # ── Watcher status ─────────────────────────────────────────────────────
    @app.get("/watcher/status")
    async def api_watcher_status():
        return _watcher_status

    # ── HTML ───────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def ui():
        return HTMLResponse(_HTML)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# HTML UI
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Drop Summarizer</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f1117; color: #e2e8f0; min-height: 100vh; }

  header { background: #1a1a2e; border-bottom: 1px solid #2d2d4a;
    padding: 14px 28px; display: flex; align-items: center; gap: 12px;
    position: sticky; top: 0; z-index: 10; }
  header h1 { font-size: 16px; font-weight: 700; color: #fff; }
  .badge { padding: 3px 10px; border-radius: 12px; font-size: 11px;
    font-weight: 600; text-transform: uppercase; }
  .badge-green { background: #14532d; color: #4ade80; }
  .badge-gray  { background: #374151; color: #9ca3af; }
  .spacer { flex: 1; }
  .hdr-stat { font-size: 11px; color: #4b5563; }

  .layout { display: grid; grid-template-columns: 320px 1fr; gap: 20px;
    max-width: 1280px; margin: 0 auto; padding: 20px 24px; }

  .card { background: #1a1a2e; border: 1px solid #2d2d4a; border-radius: 10px;
    overflow: hidden; margin-bottom: 16px; }
  .card-header { padding: 12px 16px 10px; border-bottom: 1px solid #2d2d4a;
    display: flex; align-items: center; gap: 8px; }
  .card-header h2 { font-size: 13px; font-weight: 600; color: #c5cae9; }
  .card-body { padding: 16px; }

  /* Drop zone */
  .drop-zone { border: 2px dashed #374151; border-radius: 8px;
    padding: 28px 16px; text-align: center; cursor: pointer;
    transition: all .2s; position: relative; overflow: hidden; }
  .drop-zone:hover, .drop-zone.drag-over { border-color: #2563eb;
    background: rgba(37,99,235,.08); }
  .drop-zone input[type=file] { position: absolute; inset: 0; width: 100%; height: 100%;
    opacity: 0; cursor: pointer; z-index: 2; }
  .drop-zone .dz-icon { font-size: 32px; margin-bottom: 8px; }
  .drop-zone p { font-size: 13px; color: #9ca3af; line-height: 1.5; }
  .drop-zone small { font-size: 11px; color: #4b5563; }

  /* Settings rows */
  .srow { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
  .srow label { font-size: 12px; color: #9ca3af; min-width: 90px; }
  input[type=text], input[type=password], input[type=email], input[type=number] {
    flex: 1; padding: 5px 9px; border-radius: 5px; font-size: 12px;
    background: #0f1117; border: 1px solid #374151; color: #e2e8f0; outline: none; }
  input:focus { border-color: #2563eb; }
  .btn { padding: 5px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;
    cursor: pointer; border: none; background: #2563eb; color: #fff;
    transition: background .15s; }
  .btn:hover { background: #1d4ed8; }
  .btn:disabled { background: #374151; color: #6b7280; cursor: default; }
  .btn-sm { padding: 3px 10px; font-size: 11px; }
  .btn-ghost { background: #1f2937; border: 1px solid #374151; color: #9ca3af; }
  .btn-ghost:hover { background: #374151; }
  .save-ok { color: #4ade80; font-size: 11px; margin-left: 6px; display: none; }
  .section-label { font-size: 11px; font-weight: 600; color: #6b7280;
    text-transform: uppercase; letter-spacing: .5px; margin: 12px 0 6px; }

  /* Tags input */
  .tag-row { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
  .tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
    background: #1f2937; border: 1px solid #374151; border-radius: 10px;
    font-size: 11px; color: #9ca3af; }
  .tag-del { cursor: pointer; color: #6b7280; font-size: 12px; }
  .tag-del:hover { color: #f87171; }
  .kw-input-row { display: flex; gap: 6px; }

  /* Chat */
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .chip { padding: 4px 10px; border-radius: 12px; font-size: 11px;
    background: #1f2937; border: 1px solid #374151; color: #9ca3af;
    cursor: pointer; transition: all .15s; }
  .chip:hover { background: #2563eb; border-color: #2563eb; color: #fff; }
  .chat-row { display: flex; gap: 8px; }
  .chat-input { flex: 1; padding: 8px 12px; border-radius: 7px; font-size: 13px;
    background: #0f1117; border: 1px solid #374151; color: #e2e8f0; outline: none; }
  .chat-input:focus { border-color: #2563eb; }
  .chat-send { padding: 8px 16px; border-radius: 7px; font-size: 13px;
    cursor: pointer; border: none; background: #2563eb; color: #fff; white-space: nowrap; }
  .chat-send:hover { background: #1d4ed8; }
  .chat-send:disabled { background: #374151; color: #6b7280; cursor: default; }
  .chat-result { margin-top: 12px; padding: 12px; border-radius: 7px;
    background: #0f1117; border: 1px solid #2d2d4a; font-size: 13px;
    line-height: 1.6; color: #d1d5db; white-space: pre-wrap; display: none; }
  .chat-result.vis { display: block; }

  /* Summary feed */
  .sum-entry { border: 1px solid #2d2d4a; border-radius: 7px; margin-bottom: 10px; }
  .sum-header { padding: 10px 14px; display: flex; align-items: center; gap: 8px;
    cursor: pointer; }
  .sum-header:hover { background: #1f2937; border-radius: 7px 7px 0 0; }
  .sum-filename { font-size: 12px; font-weight: 600; color: #c5cae9; flex: 1;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sum-time { font-size: 10px; color: #6b7280; }
  .sum-wc { font-size: 10px; color: #4b5563; }
  .sum-alert-badge { font-size: 10px; background: #451a03; color: #fbbf24;
    padding: 1px 6px; border-radius: 8px; }
  .sum-body { padding: 10px 14px; font-size: 12px; line-height: 1.6;
    color: #d1d5db; white-space: pre-wrap; border-top: 1px solid #2d2d4a;
    background: #0f1117; display: none; }
  .sum-body.open { display: block; }
  .sum-entry.sum-active { border-color: #2563eb; background: #0f1e3a; }
  .sum-entry.sum-active .sum-header { background: #1e3a5f; border-radius: 6px 6px 0 0; }
  .empty-state { font-size: 13px; color: #4b5563; text-align: center; padding: 32px; }
</style>
</head>
<body>

<header>
  <h1>📄 Drop Summarizer</h1>
  <span class="badge badge-green" id="watcher-badge">Watching</span>
  <div class="spacer"></div>
  <span class="hdr-stat" id="hdr-stat">—</span>
</header>

<div class="layout">

  <!-- ── Left: Settings + Upload ─────────────────────────────── -->
  <div>

    <!-- Drop zone -->
    <div class="card">
      <div class="card-header"><h2>📥 Upload File</h2></div>
      <div class="card-body">
        <div class="drop-zone" id="drop-zone"
             ondragover="event.preventDefault();this.classList.add('drag-over')"
             ondragleave="this.classList.remove('drag-over')"
             ondrop="handleDrop(event)">
          <input type="file" id="file-input"
                 accept=".txt,.md,.pdf,.png,.jpg,.jpeg,.tiff,.bmp,.gif"
                 onchange="uploadFile(this.files[0])">
          <div class="dz-icon">⬆️</div>
          <p>Drop a file here or click to upload</p>
          <small>.txt · .md · .pdf · .png · .jpg · .tiff · .bmp</small>
        </div>
        <div id="upload-status" style="font-size:12px;margin-top:8px;display:none"></div>
      </div>
    </div>

    <!-- Watcher settings -->
    <div class="card">
      <div class="card-header"><h2>⚙️ Watcher Settings</h2></div>
      <div class="card-body">
        <div class="srow">
          <label>Poll every</label>
          <input type="number" id="poll-seconds" value="15" min="5" max="3600">
          <span style="font-size:11px;color:#6b7280">sec</span>
        </div>
        <div class="srow">
          <label>Watch folder</label>
          <input type="text" id="watch-dir" placeholder="./inbox">
        </div>
        <button class="btn btn-sm" onclick="savePoll()">Save</button>
        <span class="save-ok" id="poll-ok">✓ Saved</span>

        <div class="section-label" style="margin-top:14px">Email alert on keywords</div>
        <div class="tag-row" id="kw-tags"></div>
        <div class="kw-input-row">
          <input type="text" id="kw-input" placeholder="urgent, invoice, action…"
                 onkeydown="if(event.key==='Enter')addKeyword()">
          <button class="btn btn-sm btn-ghost" onclick="addKeyword()">+ Add</button>
        </div>
        <button class="btn btn-sm" style="margin-top:8px" onclick="saveKeywords()">Save keywords</button>
        <span class="save-ok" id="kw-ok">✓ Saved</span>
      </div>
    </div>

    <!-- Email credentials -->
    <div class="card">
      <div class="card-header"><h2>✉️ Email Alerts</h2></div>
      <div class="card-body">
        <div class="srow"><label>SMTP host</label>
          <input type="text" id="smtp-host" placeholder="smtp.gmail.com"></div>
        <div class="srow"><label>Username</label>
          <input type="email" id="smtp-user" placeholder="you@gmail.com"></div>
        <div class="srow"><label>Password</label>
          <input type="password" id="smtp-pass" placeholder="app password"></div>
        <div class="srow"><label>Alert to</label>
          <input type="email" id="smtp-to" placeholder="recipient@example.com"></div>
        <button class="btn btn-sm" onclick="saveEmail()">Save</button>
        <span class="save-ok" id="email-ok">✓ Saved</span>
      </div>
    </div>

  </div><!-- /left -->

  <!-- ── Right: Chat + Feed ───────────────────────────────────── -->
  <div>

    <!-- Chat -->
    <div class="card">
      <div class="card-header">
        <h2>💬 Ask About Your Documents</h2>
        <button id="clear-active-btn" class="btn btn-sm btn-ghost" style="margin-left:auto;display:none" onclick="clearActiveFile()">✕ Clear focus</button>
      </div>
      <div class="card-body">
        <!-- Active file banner -->
        <div id="active-file-banner" style="display:none;background:#1e3a5f;border:1px solid #2563eb;border-radius:8px;padding:8px 14px;margin-bottom:10px;display:none;align-items:center;gap:10px">
          <span style="font-size:.8rem;color:#93c5fd">Talking to:</span>
          <span id="active-file-name" style="font-size:.85rem;font-weight:600;color:#dbeafe;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
          <button onclick="clearActiveFile()" style="background:none;border:none;color:#93c5fd;cursor:pointer;font-size:.8rem;padding:0">✕ ask all docs</button>
        </div>
        <div class="chips">
          <span class="chip" onclick="ask(this.textContent)">What were today's key themes?</span>
          <span class="chip" onclick="ask(this.textContent)">Summarize everything from this week</span>
          <span class="chip" onclick="ask(this.textContent)">What action items were mentioned?</span>
          <span class="chip" onclick="ask(this.textContent)">Which documents had urgent items?</span>
          <span class="chip" onclick="ask(this.textContent)">List all decisions made</span>
          <span class="chip" onclick="ask(this.textContent)">Compare the last two documents</span>
          <span class="chip" onclick="ask(this.textContent)">What were the main topics?</span>
          <span class="chip" onclick="ask(this.textContent)">Any financial figures mentioned?</span>
        </div>
        <div class="chat-row">
          <input class="chat-input" id="chat-input" type="text"
            placeholder="Ask anything about your summarized documents…"
            onkeydown="if(event.key==='Enter')ask()">
          <button class="chat-send" id="chat-send" onclick="ask()">Ask</button>
        </div>
        <div class="chat-result" id="chat-result"></div>
      </div>
    </div>

    <!-- Summary feed -->
    <div class="card">
      <div class="card-header">
        <h2>📋 Summary Feed</h2>
        <span id="sum-count" style="font-size:11px;color:#6b7280;margin-left:auto"></span>
        <button class="btn btn-sm btn-ghost" style="margin-left:8px" onclick="loadSummaries()">↺ Refresh</button>
      </div>
      <div class="card-body" id="feed-body">
        <div class="empty-state">No summaries yet — drop a file into the inbox folder or upload one above.</div>
      </div>
    </div>

  </div><!-- /right -->
</div>

<script>
let _keywords = [];
let _activeFile = null;  // { filename, id }

function setActiveFile(filename, id) {
  _activeFile = { filename, id };
  const banner = document.getElementById('active-file-banner');
  banner.style.display = 'flex';
  document.getElementById('active-file-name').textContent = filename;
  document.getElementById('clear-active-btn').style.display = 'inline-block';
  document.getElementById('chat-input').placeholder = `Ask about "${filename}"…`;
  // highlight the active entry
  document.querySelectorAll('.sum-entry').forEach(el => el.classList.remove('sum-active'));
  const match = [...document.querySelectorAll('.sum-entry')].find(
    el => el.dataset.filename === filename
  );
  if (match) match.classList.add('sum-active');
}

function clearActiveFile() {
  _activeFile = null;
  document.getElementById('active-file-banner').style.display = 'none';
  document.getElementById('clear-active-btn').style.display = 'none';
  document.getElementById('chat-input').placeholder = 'Ask anything about your summarized documents…';
  document.querySelectorAll('.sum-entry').forEach(el => el.classList.remove('sum-active'));
}

// ── Init ───────────────────────────────────────────────────────────
async function init() {
  await loadSettings();
  await loadSummaries();
  setInterval(loadSummaries, 10000);
  setInterval(loadWatcherStatus, 8000);
}

async function loadWatcherStatus() {
  try {
    const s = await fetch('/watcher/status').then(r => r.json());
    const badge = document.getElementById('watcher-badge');
    badge.className = 'badge ' + (s.running ? 'badge-green' : 'badge-gray');
    badge.textContent = s.running ? 'Watching' : 'Stopped';
    document.getElementById('hdr-stat').textContent =
      `${s.processed} files processed · last check ${s.last_check ? new Date(s.last_check).toLocaleTimeString() : '—'}`;
  } catch(e) {}
}

async function loadSettings() {
  try {
    const s = await fetch('/settings').then(r => r.json());
    document.getElementById('poll-seconds').value = s.poll_seconds || 15;
    document.getElementById('watch-dir').value    = s.watch_dir    || '';
    document.getElementById('smtp-host').value    = s.email?.host  || '';
    document.getElementById('smtp-user').value    = s.email?.user  || '';
    document.getElementById('smtp-pass').value    = s.email?.password ? '••••••••' : '';
    document.getElementById('smtp-to').value      = s.email?.to   || '';
    _keywords = s.alert_keywords || [];
    renderKeywords();
  } catch(e) {}
}

// ── Keywords ────────────────────────────────────────────────────────
function renderKeywords() {
  const row = document.getElementById('kw-tags');
  row.innerHTML = _keywords.map((kw, i) =>
    `<span class="tag">${kw}<span class="tag-del" onclick="removeKw(${i})">×</span></span>`
  ).join('');
}
function addKeyword() {
  const inp = document.getElementById('kw-input');
  const val = inp.value.trim();
  if (val && !_keywords.includes(val)) { _keywords.push(val); renderKeywords(); }
  inp.value = '';
}
function removeKw(i) { _keywords.splice(i, 1); renderKeywords(); }

async function saveKeywords() {
  await fetch('/settings/keywords', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ keywords: _keywords }) });
  flash('kw-ok');
}

// ── Settings saves ──────────────────────────────────────────────────
async function savePoll() {
  await fetch('/settings/poll', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      poll_seconds: +document.getElementById('poll-seconds').value,
      watch_dir:     document.getElementById('watch-dir').value,
    }) });
  flash('poll-ok');
}

async function saveEmail() {
  const pass = document.getElementById('smtp-pass').value;
  await fetch('/settings/email', { method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      host:     document.getElementById('smtp-host').value,
      user:     document.getElementById('smtp-user').value,
      password: pass === '••••••••' ? undefined : pass,
      to:       document.getElementById('smtp-to').value,
    }) });
  flash('email-ok');
}

function flash(id) {
  const el = document.getElementById(id);
  el.style.display = 'inline';
  setTimeout(() => el.style.display = 'none', 2000);
}

// ── Upload ──────────────────────────────────────────────────────────
async function uploadFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  const status = document.getElementById('upload-status');
  status.style.display = 'block';
  status.textContent = `Uploading ${file.name}…`;
  try {
    const res = await fetch('/upload', { method: 'POST', body: fd });
    const data = await res.json();
    status.textContent = `✓ ${data.message}`;
    setTimeout(async () => {
      status.style.display = 'none';
      await loadSummaries();
      // Auto-focus the just-uploaded file once it appears
      if (data.filename) setActiveFile(data.filename, null);
    }, 3000);
  } catch(e) {
    status.style.color = '#f87171';
    status.textContent = 'Upload failed: ' + e.message;
  }
}

function handleDrop(event) {
  event.preventDefault();
  document.getElementById('drop-zone').classList.remove('drag-over');
  const file = event.dataTransfer.files[0];
  if (file) uploadFile(file);
}

// ── Summaries ───────────────────────────────────────────────────────
async function loadSummaries() {
  try {
    const entries = await fetch('/summaries').then(r => r.json());
    renderFeed(entries);
  } catch(e) {}
}

function fmtTime(iso) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}
function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderFeed(entries) {
  const body = document.getElementById('feed-body');
  document.getElementById('sum-count').textContent = entries.length + ' summaries';
  if (!entries.length) {
    body.innerHTML = '<div class="empty-state">No summaries yet — drop a file above or into the inbox folder.</div>';
    return;
  }
  body.innerHTML = entries.map((e, i) => `
    <div class="sum-entry" data-filename="${esc(e.filename)}" data-id="${e.id}">
      <div class="sum-header">
        <span class="sum-filename" style="cursor:pointer" onclick="setActiveFile('${esc(e.filename)}','${e.id}')" title="Focus chat on this file">${esc(e.filename)}</span>
        ${e.alerted ? '<span class="sum-alert-badge">📧 alerted</span>' : ''}
        <span class="sum-wc">${e.word_count}w</span>
        <span class="sum-time">${fmtTime(e.created_at)}</span>
        <button class="btn btn-sm" style="background:#1e3a5f;color:#93c5fd;border:1px solid #2563eb;padding:2px 8px;font-size:10px;border-radius:5px;margin-left:6px" onclick="setActiveFile('${esc(e.filename)}','${e.id}')">Focus</button>
        <span id="si-${i}" style="font-size:11px;color:#4b5563;margin-left:4px;cursor:pointer" onclick="toggleSum('se-${i}','si-${i}')">▸</span>
      </div>
      <div class="sum-body" id="se-${i}">${esc(e.summary)}</div>
    </div>`).join('');
}

function toggleSum(bodyId, iconId) {
  const body = document.getElementById(bodyId);
  const icon = document.getElementById(iconId);
  const open = body.classList.toggle('open');
  icon.textContent = open ? '▾' : '▸';
}

// ── Chat ─────────────────────────────────────────────────────────────
async function ask(question) {
  const inp = document.getElementById('chat-input');
  const res = document.getElementById('chat-result');
  const btn = document.getElementById('chat-send');
  const q   = question || inp.value.trim();
  if (!q) return;
  inp.value = '';
  btn.disabled = true; btn.textContent = 'Thinking…';
  res.className = 'chat-result vis';
  const focusLabel = _activeFile ? ` [${_activeFile.filename}]` : '';
  res.textContent = `Asking agent${focusLabel}…`;
  try {
    const body = { question: q };
    if (_activeFile) body.filename = _activeFile.filename;
    const r = await fetch('/ask', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body) });
    const d = await r.json();
    res.textContent = d.answer || d.error || '(no response)';
  } catch(e) { res.textContent = 'Error: ' + e.message; }
  btn.disabled = false; btn.textContent = 'Ask';
}

init();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drop Summarizer — docs & images web UI")
    parser.add_argument("--port",     type=int, default=18794)
    parser.add_argument("--provider", "-p", default=None,
        choices=["rits", "watsonx", "openai", "anthropic", "litellm", "ollama"])
    parser.add_argument("--model",    "-m", default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    print(f"\n  Drop Summarizer (docs + images)  →  http://127.0.0.1:{args.port}\n")
    _web(args.port)
