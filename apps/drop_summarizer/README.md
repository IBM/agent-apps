# Drop Summarizer

Watches an inbox folder for new files. Each file is extracted, summarized by the
agent, stored with its full content, and optionally triggers an email alert when
the summary matches configured keywords. Files can then be queried via chat.

**Port:** 18794  
**Supported file types:** `.txt`, `.md`, `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.gif`

---

## Division of Responsibilities

### The App (main.py)

- **Watches** the inbox folder — asyncio background loop polls every N seconds
- **Extracts content** from each file before the agent sees it:
  - `.txt`, `.md` — reads text directly
  - `.pdf`, images — calls docling for OCR / layout-aware extraction
- **Stores** both the extracted content and the agent's summary in SQLite (`summaries.db`)
- **Checks keywords** against the summary and sends email alerts — no LLM involved
- **Injects full content** as context when a user asks a question about a specific file
- **Serves the web UI** — upload, summary feed, chat, settings (FastAPI)
- **Persists settings** to `.store.json` (poll interval, watch dir, keywords, email config)

### CugaAgent

The agent is given **no tools**. It receives plain text and returns plain text.

| Invocation | Input | Output |
|---|---|---|
| New file arrives | Extracted content (up to 12 000 chars) | Summary |
| User asks about a file | Full stored content + question | Answer |
| User asks generally | Recent summaries as context + question | Answer |

### Agent Instructions

Summarization style and format rules are inlined as `special_instructions` in `make_agent()` inside `main.py`.

---

## Quick Start

```bash
pip install -r requirements.txt
python main.py
# open http://127.0.0.1:18794
```

For PDF and image support:
```bash
pip install docling
```

---

## How Files Flow Through the App

```
File lands in ./inbox/
       │
       ▼  (watcher polls every N seconds)
App: _extract_content(file)
       │  .txt/.md → read text
       │  .pdf/image → docling OCR/parse
       ▼
Agent: summarize(content[:12000])
       │
       ▼
SQLite: store { filename, summary, full_content }
       │
       ▼
UI: summary card appears in feed
       │
       ▼  (user clicks "Focus" or filename)
Agent: answer(full_content + question)
```

Email alert check runs after summarization — pure string matching, no LLM.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | — | `rits` \| `anthropic` \| `openai` \| `ollama` \| `watsonx` |
| `LLM_MODEL` | — | Model override |
| `WATCH_DIR` | `./inbox` | Folder to watch |
| `POLL_SECONDS` | `15` | Inbox poll interval |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server |
| `SMTP_USERNAME` | — | Sender email |
| `SMTP_PASSWORD` | — | App password |
| `ALERT_TO` | — | Alert recipient email |

---

## Files

| File | Purpose |
|---|---|
| `main.py` | Everything: watcher, extraction, agent, FastAPI UI |
| `_SYSTEM` in `main.py` | Agent instructions — summary style and format (inlined) |
| `summaries.db` | SQLite — full content + summaries (created on first run) |
| `.store.json` | Persisted settings (created on first save) |
| `requirements.txt` | Python dependencies |
