export type Status = 'working' | 'partial' | 'gap'
export type Category =
  | 'monitoring'
  | 'communication'
  | 'productivity'
  | 'devtools'
  | 'content'
  | 'documents'
  | 'finance'
  | 'infrastructure'

export type Surface = 'gateway' | 'pipeline'

/**
 * event-driven   — triggered by time (CronChannel) or external events
 *                  (WebhookChannel, IMAPChannel, RssChannel, CugaWatcher).
 * multimodal     — involves non-text data: audio/voice (AudioChannel,
 *                  TTSChannel, Whisper), images (vision, DALL-E), or
 *                  documents (DoclingChannel / PDF).
 * both           — event-driven trigger AND multimodal data processing.
 * conversational — real-time, human-in-loop, text-based, on-demand.
 */
export type UseCaseType = 'event-driven' | 'documents' | 'ppt' | 'audio' | 'video' | 'images' | 'other'

export interface UseCase {
  id: string
  name: string
  tagline: string
  description: string
  category: Category
  status: Status
  type: UseCaseType
  /**
   * 'gateway'  — a human talks to the agent in real-time (browser, Telegram, WhatsApp, phone).
   * 'pipeline' — the agent runs automatically on a schedule or system event (cron, webhook, folder).
   */
  surface: Surface
  /** Which channels power this demo */
  channels: string[]
  /** Which tool factories are used */
  tools: string[]
  /** Path relative to repo root */
  demoPath: string | null
  /** Runnable command (copy-pasteable) */
  howToRun: {
    setup: string[]
    command: string
    envVars: string[]
  }
  /** High-level architecture description */
  architecture: string
  /** ASCII/text diagram of the pipeline */
  diagram: string
  /** What CUGA specifically contributes */
  cugaContribution: string[]
  /** Future: URL of the live app (empty until implemented) */
  appUrl: string | null
  /** If true, show "Coming soon" badge instead of a launch button */
  comingSoon?: boolean
  /** Copy-pasteable examples — chat messages for web UI apps, commands for CLI apps */
  examples?: string[]
}

export const USE_CASES: UseCase[] = [
  // ── TRY IT NOW ────────────────────────────────────────────────────────────
  {
    id: 'stock-alert',
    name: 'Stock & Crypto Alert',
    tagline: 'Ask market questions or set a threshold alert — browser UI, live data',
    description:
      'A browser UI with two panels. Market Query: type any symbol and ask a free-form question — the agent fetches live data and answers with prices and % changes highlighted. Price Watch: configure a background monitor (symbol, threshold, above/below); a custom asyncio loop checks every 5 minutes and emails you when crossed. Crypto uses CoinGecko (no key needed); stocks require an Alpha Vantage key.',
    category: 'monitoring',
    type: 'event-driven',
    surface: 'pipeline',
    status: 'working',
    channels: ['EmailChannel'],
    tools: ['make_market_tools()'],
    demoPath: 'apps/stock_alert',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'ALPHA_VANTAGE_API_KEY', 'SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'ALERT_TO'],
      setup: [
        'cd apps/stock_alert',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI web server serves the single-page UI. Market Query: POST /ask → CugaAgent.invoke(symbol + question) → make_market_tools() fetches live data → answer. Price Watch: POST /watch/start → asyncio task loops every 5 min → agent checks price against threshold → if "PRICE ALERT" in answer, sends SMTP email. Watch state persists in .store.json across restarts.',
    diagram: `python main.py  →  http://127.0.0.1:18801

Panel 1 — Market Query (on-demand):
User: "What is the current price and 24h change?"
Symbol: BTC  Type: Crypto
      │  POST /ask
      ▼
CugaAgent + make_market_tools()
      │  get_crypto_price("BTC")   ← CoinGecko public API
      ▼
"BTC is $84,230 (+2.3% in 24h)…"

Panel 2 — Price Watch (background loop):
User: Start Watch  BTC  Above  $90,000
      │  POST /watch/start
      ▼
asyncio task (every 5 min)
      │  agent.invoke("Check BTC price. Alert threshold: $90,000 (above).")
      ▼
"PRICE ALERT — BTC crossed $90,000"  →  SMTP email`,
    cugaContribution: [
      'make_market_tools() wraps CoinGecko and Alpha Vantage APIs — agent gets live prices, volume, and market cap without any HTTP code',
      'CugaAgent + skills/stock_alert.md — the skill file defines alert format and reasoning rules; swap to change behaviour',
      'Persistent watch state — .store.json restores active watches and email config on restart',
      'Email config is settable from the UI — no restart needed to change SMTP credentials',
    ],
    examples: [
      'What is the current price and 24h change?',
      'Is this a good entry point compared to recent range?',
      'Compare BTC and ETH — which is performing better today?',
      'Give me a quick bull or bear read on SOL right now.',
      'Set a watch: BTC above $90,000, email me when crossed',
      'Set a watch: AAPL below $180',
    ],
    appUrl: 'http://localhost:18801',
  },
  {
    id: 'server-monitor',
    name: 'Server Monitor',
    tagline: 'Real-time server health gauges, chat diagnostics, and threshold alerts',
    type: 'event-driven',
    description:
      'A browser UI with four panels: Live Metrics (CPU/RAM/Disk/load gauges, colour-coded, auto-refreshed every 15s), Chat (ask the DevOps agent anything about system health), Alert Log (background asyncio monitor logs threshold breaches with full diagnoses), and Alert Settings (configure poll interval, cooldown, and thresholds — persisted to .store.json). No CugaHost, no channels — just CugaAgent + psutil + FastAPI.',
    category: 'infrastructure',
    surface: 'pipeline',
    status: 'working',
    channels: [],
    tools: ['get_system_metrics()', 'list_top_processes()', 'check_disk_usage()', 'find_large_files()', 'get_service_status()', 'run_safe_command()'],
    demoPath: 'apps/server_monitor',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL'],
      setup: [
        'cd apps/server_monitor',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. Chat: POST /ask → CugaAgent.invoke(question) → psutil-based tools → diagnosis. Background monitor: asyncio loop polls metrics every N seconds; when a threshold is breached and cooldown has elapsed, the agent diagnoses and appends to the Alert Log. Thresholds, poll interval, and cooldown are configurable in the UI and persisted to .store.json.',
    diagram: `python main.py  →  http://127.0.0.1:8767

Live Metrics panel (auto-refresh every 15s):
  CPU 45% ██████░░░░  RAM 61% ████████░░  Disk 72% █████████░

Chat panel (on-demand):
User: "What's eating my disk?"
      │  POST /ask
      ▼
CugaAgent + check_disk_usage() + find_large_files()
      │  check_disk_usage("/")
      │  find_large_files("/", min_mb=500)
      ▼
"/var/log is 12 GB (47% of disk). Largest file: app.log 8.2 GB"

Alert Log (background asyncio loop):
asyncio loop (every 60s)
      │  get_system_metrics() → CPU 92% > critical threshold
      ▼
CugaAgent ("CPU critical: 92%. Diagnose and recommend action.")
      │  list_top_processes(sort_by="cpu")
      ▼
Alert entry: "python train.py consuming 88% CPU since 14:02"`,
    cugaContribution: [
      'CugaAgent + skills/server_health.md — the skill defines severity levels, report format, and safety rules (never rm, never kill PIDs)',
      'run_safe_command() enforces an allowlist (df, du, uptime, ps, netstat, …) — agent gets shell access without arbitrary execution risk',
      'Background asyncio monitor replaces a separate cron daemon — threshold polling and cooldown logic are self-contained in main.py',
      'All settings configurable from the UI without restart — thresholds, poll interval, and cooldown persist to .store.json',
    ],
    examples: [
      "What's the current server health?",
      "What's using the most CPU right now?",
      "What's eating my disk?",
      "Why is the server slow?",
      "Is nginx running?",
      "Find files larger than 500MB",
      "Give me a full health briefing",
    ],
    appUrl: 'http://localhost:8767',
  },

  {
    id: 'newsletter',
    name: 'Newsletter Intelligence',
    tagline: 'Monitor RSS feeds, ask questions over live articles, set keyword alerts',
    type: 'event-driven',
    surface: 'pipeline',
    description:
      'A browser UI with two panels. Feed Query: ask any question over your configured RSS feeds — the agent fetches live articles and answers in plain language, with an Email this button to send the response to your inbox. Scheduled Alerts: configure keyword monitors that run hourly or daily; the agent searches your feeds and emails you when matches are found. State (feeds, email settings, alerts) persists in .store.json across restarts.',
    category: 'content',
    status: 'working',
    channels: ['EmailChannel'],
    tools: ['make_feed_tools()'],
    demoPath: 'apps/newsletter',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'ALERT_TO'],
      setup: [
        'cd apps/newsletter',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI web server serves the single-page UI. Feed Query: POST /ask → CugaAgent.invoke(question) → make_feed_tools() fetches and parses RSS/Atom feeds → answer. Scheduled Alerts: asyncio background scheduler checks each alert on its cron interval → agent searches feeds for keyword matches → if "ALERT:" in response, sends SMTP email. All state saved to .store.json.',
    diagram: `python main.py  →  http://127.0.0.1:18793

Panel 1 — Feed Query (on-demand):
User: "Find anything about agentic AI this week"
      │  POST /ask
      ▼
CugaAgent + make_feed_tools()
      │  fetch_feed("https://arxiv.org/rss/cs.AI")
      │  search_feeds(keywords="agentic AI")
      ▼
"Found 3 matching articles: …"  [Email this]

Panel 2 — Scheduled Alerts (background scheduler):
Alert: keywords="LLM release"  schedule=hourly
      │  asyncio scheduler fires
      ▼
agent.invoke("Check feeds for: LLM release …")
      │  "ALERT: Found 2 matches …"
      ▼
SMTP email → ALERT_TO`,
    cugaContribution: [
      'make_feed_tools() wraps feedparser — agent gets structured article lists (title, URL, summary, published) without any HTTP or XML code',
      'CugaAgent + skills/newsletter.md — the skill file defines search format and alert rules; swap to change behaviour',
      'Persistent state — .store.json restores feeds, email config, and alert schedules on restart',
      'Email config is settable from the UI — no restart needed to change SMTP credentials',
    ],
    examples: [
      'Summarize the latest AI research papers from my feeds',
      'Find anything about agentic AI or multi-agent systems',
      'What new LLM releases happened this week?',
      'What are the key AI trends from my feeds today?',
      'Add alert: keywords="agent frameworks", schedule=daily',
    ],
    appUrl: 'http://localhost:18793',
  },

  {
    id: 'video-qa',
    name: 'Video Q&A',
    tagline: 'Transcribe a video, then ask questions with exact timestamps',
    type: 'video',
    surface: 'pipeline',
    description:
      'Load a video or audio file and ask questions about it in natural language. faster-whisper transcribes locally (cached on disk after the first run), sentence-transformers embeds each segment into ChromaDB, and CugaAgent answers with bold timestamps. Runs as a CLI REPL or a browser UI with a searchable transcript panel.',
    category: 'content',
    status: 'working',
    channels: [],
    tools: ['transcribe_video()', 'search_transcript()', 'get_segment_at_time()'],
    demoPath: 'apps/video_qa',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL'],
      setup: [
        'cd apps/video_qa',
        'pip install -r requirements.txt',
        'brew install ffmpeg',
      ],
      command: 'python run.py --web',
    },
    architecture:
      'Two phases: Phase 1 (Python only) — ffmpeg extracts audio, faster-whisper transcribes to timestamped segments, sentence-transformers embeds, ChromaDB stores on disk. Phase 2 (CugaAgent) — user question → search_transcript() cosine similarity → get_segment_at_time() timestamp lookup → answer with citations. The LLM only handles retrieval and reasoning.',
    diagram: `Phase 1 — Transcription (Python, no LLM, cached)
meeting.mp4
      │  ffmpeg extract audio
      ▼
faster-whisper → [{start, end, text}, ...]
      │  sentence-transformers embed
      ▼
ChromaDB (disk cache)

Phase 2 — Q&A (CugaAgent)
User: "Where was M3 discussed?"
      │
      ▼
CugaAgent (guided by skills/video_qa.md)
      ├─ search_transcript("M3")      ← ChromaDB cosine similarity
      └─ get_segment_at_time(600)     ← timestamp lookup
            │
            ▼
"M3 was introduced at **00:04** and benchmarks covered at **10:02–11:45**"`,
    cugaContribution: [
      'CugaAgent + skills/video_qa.md — the skill file defines tool usage, timestamp format, and citation rules; swap it to change behaviour without touching agent code',
      'Two-phase architecture — transcription is deterministic Python (zero LLM tokens); the LLM only reasons over search results',
      'Transcript cached on disk — re-running the app on the same file skips transcription entirely',
      'Browser UI (python run.py --web) adds a filterable transcript panel; clicking a segment pre-fills the question box',
    ],
    examples: [
      'python run.py meeting.mp4',
      'python run.py meeting.mp4 --ask "where was M3 discussed?"',
      'python run.py --web',
      'Where was the Q2 budget discussed?',
      'What decisions were made?',
      'What was said around the 30-minute mark?',
      'Summarise the key action items',
    ],
    appUrl: 'http://localhost:8766',
  },

  {
    id: 'drop-summarizer',
    name: 'Drop Summarizer',
    tagline: 'Drop any file into the inbox — get a plain-English summary instantly',
    type: 'documents',
    surface: 'pipeline',
    description:
      'A browser UI with an upload panel and a summary feed. Drop any .txt, .md, .pdf, or image file into the inbox folder (or upload via the browser) — the agent uses an extract_document tool (docling for PDF/images) to read each file, summarises it, and the result appears instantly in the feed. Click any file to ask follow-up questions via get_document_content. Optional keyword email alerts trigger when a summary matches configured terms. Summaries stored in SQLite.',
    category: 'documents',
    status: 'working',
    channels: [],
    tools: ['extract_document', 'get_document_content'],
    demoPath: 'apps/drop_summarizer',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'ALERT_TO'],
      setup: [
        'cd apps/drop_summarizer',
        'pip install -r requirements.txt',
        'pip install docling  # optional: for PDF and image support',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. Background watcher: asyncio loop polls ./inbox/ every N seconds; on new file, agent calls extract_document tool (.txt/.md read directly; .pdf/images via docling), then summarises. App stores content + summary in SQLite. Chat: POST /ask → for specific files, agent calls get_document_content tool; for general queries, recent summaries injected as context. Keyword alert check runs after summarisation — pure string match, no LLM.',
    diagram: `python main.py  →  http://127.0.0.1:18794

File lands in ./inbox/report.pdf
      │  (background watcher polls every 15s)
      ▼
CugaAgent: extract_document(file_path)
      │  .txt/.md → read text
      │  .pdf/image → docling OCR/parse
      ▼
CugaAgent: summarize → summary
      │
      ▼
SQLite: store { filename, summary, full_content }
      │
      ▼
UI: summary card appears in feed

Chat panel (click any file to focus):
User: "What were the key risks in this report?"
      │  POST /ask
      ▼
CugaAgent: get_document_content(filename) → answer

Keyword alert (post-summary, no LLM):
summary contains "critical" → SMTP email → ALERT_TO`,
    cugaContribution: [
      'Agent uses extract_document tool to drive docling extraction — the LLM decides when and how to extract, not the app',
      'Agent uses get_document_content tool for Q&A — retrieves stored content on demand instead of having it injected by the app',
      'Background asyncio watcher replaces inotify/polling boilerplate — file arrives, summary appears automatically',
      'Persistent SQLite store — summaries and full content survive restarts; click any past file to resume Q&A',
    ],
    examples: [
      'cp ~/Downloads/q1_report.pdf ./inbox/',
      'cp ~/Downloads/meeting_notes.md ./inbox/',
      'cp ~/Downloads/research_paper.pdf ./inbox/',
      'What were the key risks in this report?',
      'Summarise the action items from the meeting notes',
      'What is the main conclusion?',
    ],
    appUrl: 'http://localhost:18794',
  },

  {
    id: 'web-researcher',
    name: 'Web Researcher',
    tagline: 'Schedule recurring web research — results logged and optionally emailed',
    type: 'event-driven',
    surface: 'pipeline',
    description:
      'A browser UI for scheduling recurring web research tasks. Add topics with hourly / daily / weekly cadences — the background scheduler runs overdue topics every 5 minutes using Tavily, logs results to SQLite, and optionally emails them. Also supports ad-hoc searches via the chat panel. Research history persists across restarts.',
    category: 'content',
    status: 'working',
    channels: ['EmailChannel'],
    tools: ['web_search()'],
    demoPath: 'apps/web_researcher',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'TAVILY_API_KEY', 'SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'ALERT_TO'],
      setup: [
        'cd apps/web_researcher',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. Chat: POST /ask → CugaAgent calls web_search (Tavily) → answer. Scheduled topics: asyncio background scheduler checks every 5 minutes for overdue topics; when due, runs the agent, logs to SQLite, and optionally emails the result. Topic schedule and email settings persisted in .store.json.',
    diagram: `python main.py  →  http://127.0.0.1:18798

Chat panel (ad-hoc):
User: "What's the latest news on quantum computing?"
      │  POST /ask
      ▼
CugaAgent + web_search()
      │  web_search("quantum computing news 2026")
      ▼
"IBM announced a 1000-qubit processor..."

Scheduled topics panel:
Topic: "AI agent frameworks"  Schedule: daily
      │  asyncio scheduler fires (every 5 min — checks overdue)
      ▼
CugaAgent + web_search()
      │  web_search("AI agent frameworks 2026")
      ▼
SQLite: log result in research.db
      │  (if email configured)
      ▼
SMTP email → ALERT_TO`,
    cugaContribution: [
      'CugaAgent synthesises multiple Tavily search results into a structured report — not just a list of links',
      'Background scheduler checks overdue topics every 5 minutes without a cron daemon or external task runner',
      'Persistent log in SQLite — all research results survive restarts and are viewable in the history panel',
      'Email config settable from the UI — no restart needed to change SMTP credentials or recipient',
    ],
    examples: [
      "What's the latest news on quantum computing?",
      'Search for Python 3.13 release notes',
      'Find recent papers on RAG architectures',
      'What are the top stories about climate policy this week?',
      'Add topic: "AI agent frameworks" → daily',
    ],
    appUrl: 'http://localhost:18798',
  },
  {
    id: 'voice-journal',
    name: 'Voice Journal',
    tagline: 'Drop a voice memo — Whisper transcribes, agent structures, SQLite stores',
    type: 'audio',
    surface: 'pipeline',
    description:
      'A personal journal that accepts audio recordings (.m4a, .mp3, .wav) and text entries via a browser UI. OpenAI Whisper API transcribes audio automatically (local Whisper as fallback). The agent structures each entry and stores it in SQLite alongside a Markdown file. A background watcher monitors ./inbox for new files. A configurable email digest sends a summary of recent entries on schedule.',
    category: 'content',
    status: 'working',
    channels: ['EmailChannel'],
    tools: [],
    demoPath: 'apps/voice_journal',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'OPENAI_API_KEY', 'SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'DIGEST_TO'],
      setup: [
        'cd apps/voice_journal',
        'pip install -r requirements.txt',
        '# optional local whisper fallback:',
        'pip install openai-whisper',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. Inbox watcher: asyncio loop monitors ./inbox for new audio/text files; audio is transcribed via OpenAI Whisper API, then the agent structures the entry and stores it in SQLite + a Markdown file under ./entries/. Email digest: configurable schedule sends a summary of recent entries via SMTP.',
    diagram: `python main.py  →  http://127.0.0.1:18799

Inbox watcher (background, auto):
./inbox/memo_20260421.m4a  (new file detected)
      │
      ▼
OpenAI Whisper API → clean transcript text
      │
      ▼
CugaAgent ("Structure this journal entry: mood, topics, action items")
      │
      ▼
SQLite (journal.db) + ./entries/memo_20260421.md

Upload / quick-write panel:
User uploads audio or types an entry
      │  POST /entry or file upload
      ▼
Same transcribe → structure → store pipeline

Chat panel (on-demand):
User: "What themes came up this week?"
      │  POST /ask (recent entries injected as context)
      ▼
CugaAgent → "You mentioned deadlines and team collaboration…"`,
    cugaContribution: [
      'Agent structures raw transcripts into mood, topics, and action items — not just a plain text dump',
      'Whisper API handles transcription; agent only sees clean text — zero transcription tokens wasted',
      'Inbox watcher processes audio automatically on drop — no manual trigger needed',
      'Configurable email digest keeps you connected to your journal without opening the app',
    ],
    examples: [
      'Click 📎 and upload a .m4a or .mp3 voice note',
      'What did I write about last week?',
      'Summarize my entries from this month',
      'What themes keep coming up in my journal?',
      'Show me everything I recorded on Monday',
    ],
    appUrl: 'http://localhost:18799',
  },
  {
    id: 'smart-todo',
    name: 'Smart Todo',
    type: 'event-driven',
    tagline: 'AI-powered task management with natural language input and email reminders',
    surface: 'pipeline',
    description:
      'A conversational todo manager with a browser UI. Add tasks in natural language ("remind me to review the PR before EOD"), set due dates, and get email reminders when items come due. Tasks stored in SQLite survive restarts. The tabbed board shows Todos, Reminders, Notes, and Done.',
    category: 'productivity',
    status: 'working',
    channels: ['EmailChannel'],
    tools: [],
    demoPath: 'apps/smart_todo',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'ALERT_TO'],
      setup: [
        'cd apps/smart_todo',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. Chat: POST /ask → CugaAgent parses natural language → adds todos to SQLite (todos.db) with due dates extracted from context. Background reminder watcher: asyncio loop checks for overdue items and sends SMTP email. Todo board renders Todos / Reminders / Notes / Done tabs from SQLite on each load.',
    diagram: `python main.py  →  http://127.0.0.1:18800

Chat panel (on-demand):
User: "Remind me to review the PR before EOD"
      │  POST /ask
      ▼
CugaAgent → parses due date, category, priority
      │  inserts todo into todos.db
      ▼
"Got it! PR review added — due today at 17:00."

Todo board (tabbed, loaded from SQLite):
  Todos | Reminders | Notes | Done
  ─────────────────────────────────
  ● Review the PR            due today 17:00
  ● Deploy to production     due Friday 17:00

Background reminder watcher:
asyncio loop (every 60s)
      │  query todos.db for overdue items
      ▼
SMTP email → ALERT_TO: "Reminder: Review the PR is due now"`,
    cugaContribution: [
      'Natural language due-date extraction — "by EOD", "Friday at 5pm", "tomorrow morning" all resolve to timestamps',
      'Categorises input automatically into Todos, Reminders, or Notes based on phrasing',
      'Persistent SQLite store — todos and notes survive restarts; no reconfiguration needed',
      'Background email watcher fires on due time without a separate cron daemon',
    ],
    examples: [
      'Remind me to review the PR by EOD',
      'Add high priority: deploy to production by Friday at 5pm',
      "What are my open todos?",
      "What's due today?",
      'Mark the PR review as done',
      'Add a note: check with Alice about the project timeline',
    ],
    appUrl: 'http://localhost:18800',
  },
  {
    id: 'travel-agent',
    name: 'Travel Planner',
    tagline: 'Plan a full trip in a conversation — live weather, attractions, and web search',
    type: 'other',
    surface: 'gateway',
    description:
      'A conversational travel planning agent with a browser UI. Describe your trip and the agent builds a day-by-day itinerary using live data: Wikipedia city overviews, real-time weather (wttr.in), geocoding (Nominatim/OSM), points of interest (OpenTripMap), and web search (Tavily). Also showcases CugaAgent vs LangGraph ReAct side-by-side on the same tools — same task, two architectures, one UI.',
    category: 'productivity',
    status: 'working',
    channels: [],
    tools: ['get_city_overview()', 'get_weather()', 'search_attractions()', 'web_search()'],
    demoPath: 'apps/travel_planner',
    howToRun: {
      envVars: ['ANTHROPIC_API_KEY', 'TAVILY_API_KEY', 'OPENTRIPMAP_API_KEY'],
      setup: [
        'cd apps/travel_planner',
      ],
      command: 'uv run --project . main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /plan → CugaAgent calls get_city_overview(), get_weather(), search_attractions(), web_search() → full day-by-day itinerary with budget breakdown. POST /chat → multi-turn follow-up on the same plan. POST /configure injects API keys at runtime — no restart needed. The LangGraph ReAct backend is available as an alternative via the same UI toggle.',
    diagram: `uv run main.py  →  http://127.0.0.1:8090

User: "5 days in Kyoto in March, mid-range budget"
      │  POST /plan
      ▼
CugaAgent
      ├─ get_city_overview("Kyoto")    ← Wikipedia REST API
      ├─ get_weather("Kyoto", "March") ← wttr.in
      ├─ search_attractions("Kyoto")   ← OpenTripMap
      └─ web_search("Kyoto March tips")← Tavily
            │
            ▼
Day-by-day itinerary + budget breakdown

POST /chat — follow-up in the same session:
User: "Move the temple visit to Day 2 and add a tea ceremony"
      │
      ▼
CugaAgent (full plan in context) → updated itinerary`,
    cugaContribution: [
      'CugaAgent coordinates four live data sources in a single pass — no orchestration glue code required',
      'Side-by-side CugaAgent vs LangGraph ReAct on identical tools — same prompt, same task, toggle between architectures in the UI',
      'POST /configure injects API keys at runtime — demo audience can provide keys without restarting the server',
      'Multi-turn POST /chat preserves the full itinerary as conversation context — follow-up edits just work',
    ],
    examples: [
      '5 days in Kyoto in March, mid-range budget',
      'Weekend in Barcelona — focus on food and architecture',
      '10 days in Japan: Tokyo, Kyoto, and Osaka',
      'Family trip to Rome, 7 days, two kids under 10',
      'Move the temple visit to Day 2 and add a tea ceremony',
      'What\'s the weather like during my trip?',
    ],
    appUrl: 'http://localhost:8090',
  },
  {
    id: 'deck-forge',
    name: 'Deck Forge',
    tagline: 'Point at a folder of docs, PDFs, and recordings — get a polished slide deck',
    type: 'ppt',
    surface: 'pipeline',
    description:
      'An AI presentation architect powered by a LangGraph ReAct agent and a RAG knowledge base. Give it a local directory (PDFs, slides, markdown, recordings) and a topic — the agent discovers every file, extracts and indexes the content with ChromaDB + sentence-transformers, reasons about a narrative arc, and builds a coherent slide deck with speaker notes. Output: a .pptx file and a structured Markdown report. Progress streams live to the browser via SSE.',
    category: 'productivity',
    status: 'working',
    channels: [],
    tools: ['list_directory()', 'extract_and_index()', 'search_knowledge_base()', 'add_slide()', 'finalize()'],
    demoPath: 'apps/deck_forge',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'ANTHROPIC_API_KEY', 'RITS_API_KEY', 'OPENAI_API_KEY'],
      setup: [
        'cd apps/deck_forge',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py --port 18802',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /api/generate creates a session and launches an asyncio task that runs the LangGraph ReAct agent. The agent calls five async tools (closed over the session): list_directory discovers files; extract_and_index uses pdfplumber / python-pptx / faster-whisper to extract text and chunk-embed it into an ephemeral ChromaDB collection; search_knowledge_base retrieves relevant chunks by semantic similarity; add_slide accumulates slides; finalize writes deck.pptx and deck.md. Each tool pushes typed events to session.queue, which the SSE endpoint streams to the browser in real time.',
    diagram: `python main.py  →  http://127.0.0.1:18802

User: directory=/research/transformers  topic="Self-Attention in Transformers"
      │  POST /api/generate
      ▼
LangGraph ReAct Agent
      ├─ list_directory("/research/transformers")
      │    → 3 PDFs, 1 PPTX, 2 Markdown files
      │
      ├─ extract_and_index("attention_paper.pdf")
      │    → pdfplumber → 847 chunks → ChromaDB
      ├─ extract_and_index("overview.md") → 23 chunks
      ├─ extract_and_index("slides.pptx") → 41 chunks
      │
      ├─ search_knowledge_base("self-attention query key value")
      │    → top 5 chunks from 3 sources
      │
      ├─ [agent reasons: 9 slides needed, sections: intro, mechanism, BERT, scaling, takeaways]
      │
      ├─ add_slide("Introduction to Transformers", bullets=[...], notes="...")
      ├─ add_slide("The Self-Attention Mechanism", ...)
      ├─ ... (9 slides total)
      │
      └─ finalize("Transformer Architecture")
           → deck.pptx  (10 slides incl. title)
           → deck.md    (structured text report)

SSE stream → browser: live progress per tool call`,
    cugaContribution: [
      'Agent owns all content decisions — which files are relevant, narrative arc, section structure, slide count, deduplication across sources; the app is a thin shell',
      'Chunked RAG retrieval — each slide gets a targeted search query, pulling the most relevant content from the indexed corpus',
      'Five async tools push typed SSE events (directory_scanned, indexed, search, slide_added, done) — live progress without polling',
      'Works on any LLM provider via the shared _llm.py factory — RITS, Anthropic, OpenAI, WatsonX, or local Ollama',
      'LangGraph ReAct graph with CugaAgent placeholder — toggle between architectures in the UI once CugaAgent is wired',
    ],
    examples: [
      'directory=/Users/me/research/transformers, topic="Self-Attention and BERT"',
      'directory=/Users/me/project/design_docs, topic="Vakra Architecture Overview"',
      'directory=/Users/me/talks/ai_summit, topic="Enterprise AI Deployment Challenges"',
      'directory=/Users/me/papers/multimodal, topic="Vision Transformers and DALL-E"',
    ],
    appUrl: 'http://localhost:18802',
  },
  {
    id: 'youtube-research',
    name: 'YouTube Research',
    tagline: 'Research any topic via YouTube — find videos, fetch transcripts, synthesise with citations',
    type: 'video',
    surface: 'gateway',
    description:
      'A browser UI for topic research powered by YouTube content. Topic mode: type a subject and the agent searches the web for relevant YouTube videos, fetches their transcripts, and synthesises findings organised by theme with citations and timestamps. URL mode: paste one or more YouTube links directly for instant summaries with key moments. Research history stored in SQLite.',
    category: 'content',
    status: 'working',
    channels: [],
    tools: ['web_search()', 'get_video_info()', 'get_transcript()'],
    demoPath: 'apps/youtube_research',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'TAVILY_API_KEY'],
      setup: [
        'cd apps/youtube_research',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /ask → CugaAgent uses web_search (Tavily) to find YouTube videos, get_video_info (oEmbed) for metadata, get_transcript (youtube-transcript-api) for captions → synthesises across transcripts with citations and timestamps. Research log stored in SQLite.',
    diagram: `python main.py  →  http://127.0.0.1:18803

Topic mode:
User: "Latest developments in AI agents"
      │  POST /ask
      ▼
CugaAgent
      ├─ web_search("AI agents youtube 2026")
      ├─ web_search("AI agent frameworks site:youtube.com")
      │     → 5 YouTube URLs found
      │
      ├─ get_video_info(url1..url5) → titles, channels
      ├─ get_transcript(url1..url4) → timestamped captions
      │     (url5: no captions — skipped)
      ▼
Synthesis by theme with citations:
"Both Channel A ([12:30]) and Channel B ([08:15]) emphasise…"

URL mode:
User: "https://youtube.com/watch?v=abc — summarise this"
      │
      ▼
CugaAgent → get_video_info + get_transcript → summary with timestamps`,
    cugaContribution: [
      'CugaAgent decides search strategy — generates 2-3 varied queries to surface the best YouTube results',
      'Agent synthesises across multiple video transcripts by theme, not per-video — cross-referencing what different creators say',
      'Citation format with channel attribution and timestamps is enforced by the skill prompt',
      'Transcripts capped at ~5000 words per video to stay within context limits; agent handles truncation gracefully',
    ],
    examples: [
      'Latest developments in AI agents',
      'How does RLHF work?',
      'Best practices for RAG pipelines',
      'https://youtube.com/watch?v=VIDEO_ID — summarise this video',
      'Compare what these creators say about fine-tuning: [url1] [url2]',
      'What did they say about scaling laws around the 20-minute mark?',
    ],
    appUrl: 'http://localhost:18803',
  },
  {
    id: 'arch-diagram',
    name: 'Architecture Diagram Generator',
    tagline: 'Describe a system in plain English, get a rendered architecture diagram',
    type: 'images',
    surface: 'gateway',
    description:
      'A browser UI that turns natural-language system descriptions into rendered architecture diagrams. The agent generates Mermaid.js code (flowcharts, sequence diagrams, ER diagrams, state diagrams) and the browser renders it as interactive SVG. Supports iterative refinement — ask the agent to add, remove, or change components and it updates the diagram. Optionally uses web search to research unfamiliar technologies before diagramming. Diagrams downloadable as SVG.',
    category: 'devtools',
    status: 'working',
    channels: [],
    tools: ['web_search()'],
    demoPath: 'apps/arch_diagram',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'TAVILY_API_KEY'],
      setup: [
        'cd apps/arch_diagram',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI with mermaid.js loaded from CDN. POST /ask → CugaAgent generates Mermaid code in a fenced code block → server extracts the code via regex → frontend renders SVG via mermaid.js. The system prompt includes full Mermaid syntax reference with examples for each diagram type to minimise invalid output. Iterative refinement works via the agent thread — the agent remembers the previous diagram and modifies it.',
    diagram: `python main.py  →  http://127.0.0.1:18804

User: "Design a microservices e-commerce platform"
      │  POST /ask
      ▼
CugaAgent (system prompt includes Mermaid syntax reference)
      │  (optional) web_search("microservices patterns")
      ▼
Response contains:
  \`\`\`mermaid
  graph TD
    Client["Browser"] -->|HTTPS| GW["API Gateway"]
    GW --> UserSvc["User Service"]
    GW --> OrderSvc["Order Service"]
    OrderSvc --> MQ["Message Queue"]
    MQ --> PaySvc["Payment Service"]
  \`\`\`
  + explanation of each component
      │
      ▼
Frontend: mermaid.js renders SVG → Download SVG / Copy code

User: "Add a Redis cache between services and the database"
      ▼
CugaAgent → updated diagram with cache node added`,
    cugaContribution: [
      'CugaAgent picks the best diagram type (flowchart, sequence, ER, state) based on what the user describes',
      'System prompt includes full Mermaid syntax reference with correct examples — minimises invalid diagram code',
      'Iterative refinement via conversation thread — "add a cache", "show as sequence diagram" modifies the existing diagram',
      'Optional web_search lets the agent research unfamiliar technologies before diagramming',
    ],
    examples: [
      'Microservices e-commerce platform with API gateway, user service, order service, and payment processing',
      'CI/CD pipeline from git push to production with testing, staging, and rollback',
      'Real-time chat system with WebSockets, load balancer, and Redis pub/sub',
      'OAuth2 login flow as a sequence diagram',
      'E-commerce database schema as an ER diagram',
      'Order lifecycle as a state diagram',
      'Add a Redis cache between the services and the database',
      'Show me the auth flow as a sequence diagram instead',
    ],
    appUrl: 'http://localhost:18804',
  },
  {
    id: 'hiking-research',
    name: 'Hiking Research',
    tagline: 'Discover and compare hiking trails near any location with AI-synthesised reviews',
    type: 'other',
    surface: 'gateway',
    description:
      'A browser UI for exploring hiking trails. Type any location and the agent geocodes it, queries OpenStreetMap via the Overpass API for named hiking route relations, and presents trails filtered by difficulty and kid-friendliness. Click any trail name to view it on OpenStreetMap. Tap "Get Reviews" on any trail to get an AI-synthesised summary of hiker reviews from the web via Tavily.',
    category: 'content',
    status: 'working',
    channels: [],
    tools: ['geocode_location()', 'find_hikes()', 'get_review_summary()'],
    demoPath: 'apps/hiking_research',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'TAVILY_API_KEY'],
      setup: [
        'cd apps/hiking_research',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /ask → CugaAgent calls geocode_location (Nominatim/OpenStreetMap) to convert a place name to lat/lon, then find_hikes (Overpass API) to fetch named hiking route relations, filtered by difficulty and kid-friendliness. GET /hikes returns the cached results for the live trail-card panel. get_review_summary uses Tavily to search for and synthesise hiker reviews for a specific trail.',
    diagram: `python main.py  →  http://127.0.0.1:18805

User: "Easy hikes near Yosemite, CA"
      │  POST /ask
      ▼
CugaAgent
      ├─ geocode_location("Yosemite, CA")
      │     → lat=37.7489, lon=-119.5885
      │
      ├─ find_hikes(lat, lon, radius_km=25, difficulty="easy")
      │     → Overpass API: hiking route relations
      │     → filter by sac_scale / distance
      │     → _last_hikes updated (30 results)
      ▼
Summary: "Found 12 easy trails near Yosemite…"

GET /hikes → trail cards rendered in the right panel
  Each card: name (→ OSM link), difficulty, distance, kid-friendly badge

User: "Tell me about reviews for: Mist Trail"
      │
      ▼
CugaAgent → get_review_summary("Mist Trail", "Yosemite")
          → Tavily search → synthesised review summary`,
    cugaContribution: [
      'Agent chains geocode → find_hikes automatically — user just names any place, no coordinates needed',
      'Difficulty inferred from OSM sac_scale tag with a distance-based fallback for untagged routes',
      'Kid-friendly flag combines difficulty, distance, and an explicit OSM child= tag',
      'Review synthesis via Tavily search gives real hiker opinions without fabricating trail details',
    ],
    examples: [
      'Easy hikes near Yosemite, CA',
      'Kid-friendly trails near Boulder, CO',
      'Moderate hikes near Asheville, NC within 40 km',
      'Hard hikes near Denver, CO',
      'Family hikes near Lake Tahoe',
      'Tell me about user reviews for: Half Dome Trail',
    ],
    appUrl: 'http://localhost:18805',
  },
  {
    id: 'movie-recommender',
    name: 'Movie Recommender',
    tagline: 'Tell the agent what you love — get a personalised watch-next list',
    type: 'other',
    surface: 'gateway',
    description:
      'A conversational movie recommendation agent with a browser UI. Tell it about films you enjoy, genres, favourite directors and actors, or your current mood — the agent builds a taste profile and recommends 5–8 films you will love. Movie details are verified via the Wikipedia REST API (no extra API key needed). Recommendations appear as cards in the right panel alongside a live view of your taste profile.',
    category: 'content',
    status: 'working',
    channels: [],
    tools: ['lookup_movie()', 'save_preference()', 'get_preferences()', 'save_recommendations()'],
    demoPath: 'apps/movie_recommender',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'ANTHROPIC_API_KEY'],
      setup: [
        'cd apps/movie_recommender',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py --port 18806',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /ask → CugaAgent uses save_preference to record genres, liked/disliked films, actors, directors, and moods; get_preferences recalls the full profile; lookup_movie verifies details via Wikipedia; save_recommendations persists the structured card list. GET /session/{thread_id} returns the live profile and recommendation cards.',
    diagram: `python main.py  →  http://127.0.0.1:18806

User: "I love Inception and The Dark Knight"
      │  POST /ask
      ▼
CugaAgent
      ├─ save_preference(category="liked_movie", value="Inception")
      ├─ save_preference(category="liked_movie", value="The Dark Knight")
      │
User: "Recommend something similar"
      ├─ get_preferences()  → liked_movies, genres, moods …
      ├─ lookup_movie("Memento")   ← Wikipedia REST API
      ├─ lookup_movie("Prisoners")
      │
      ├─ save_recommendations([{title, year, genre, reason, rating}, ...])
      ▼
Recommendation cards rendered in the right panel`,
    cugaContribution: [
      'save_preference / get_preferences build a persistent taste profile within the session — the agent never forgets what you said earlier',
      'lookup_movie verifies film details via Wikipedia before suggesting — no hallucinated plot descriptions',
      'save_recommendations pushes structured JSON to the UI so cards render automatically without UI polling logic',
      'Warm, film-enthusiast persona defined in the skill prompt — swap the prompt to change tone or domain (books, games, etc.)',
    ],
    examples: [
      "I love Inception and The Dark Knight — what should I watch next?",
      "I enjoy sci-fi and psychological thrillers, suggest 5 films",
      "My favourite director is Denis Villeneuve",
      "I'm in the mood for something light and funny tonight",
      "I dislike jump-scare horror — what else is good?",
      "Recommend something with Tom Hanks I might have missed",
    ],
    appUrl: 'http://localhost:18806',
  },
  {
    id: 'webpage-summarizer',
    name: 'Webpage Summarizer',
    tagline: 'Paste any URL — get a structured plain-English summary instantly',
    type: 'other',
    surface: 'gateway',
    description:
      'A browser UI that fetches and summarises any webpage you provide. Paste a URL into the chat and the agent retrieves the page, strips HTML boilerplate (scripts, nav, footers), extracts readable text, and returns a structured summary: title, source URL, 2–3 sentence overview, key topics as bullet points, important facts, and a bottom-line takeaway. Also lists hyperlinks found on the page on request.',
    category: 'content',
    status: 'working',
    channels: [],
    tools: ['fetch_webpage()', 'fetch_webpage_links()'],
    demoPath: 'apps/webpage_summarizer',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'ANTHROPIC_API_KEY'],
      setup: [
        'cd apps/webpage_summarizer',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py --port 8071',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /ask → CugaAgent calls fetch_webpage (httpx + BeautifulSoup, truncated to 12 000 chars) → produces structured summary. fetch_webpage_links returns the list of external links for site exploration. No state is stored between requests.',
    diagram: `python main.py  →  http://127.0.0.1:8071

User: "Summarize https://en.wikipedia.org/wiki/Large_language_model"
      │  POST /ask
      ▼
CugaAgent
      └─ fetch_webpage("https://en.wikipedia.org/wiki/Large_language_model")
           │  httpx GET + BeautifulSoup strip
           │  title, meta description, body text (≤12 000 chars)
           ▼
Structured summary:
  Title: Large language model — Wikipedia
  Overview: A large language model (LLM) is …
  Key topics: • Architecture • Training • RLHF • Applications …
  Bottom line: LLMs are transformer-based models …

User: "List all links on https://news.ycombinator.com"
      └─ fetch_webpage_links(url) → up to 40 external links`,
    cugaContribution: [
      'fetch_webpage strips nav, header, footer, script, and style tags before sending text to the LLM — agent only sees signal, not boilerplate',
      'Content truncated to 12 000 chars to stay within context limits; the agent handles truncation gracefully',
      'Structured summary format (overview → bullets → bottom line) enforced by the system prompt — consistent output regardless of page type',
      'fetch_webpage_links enables lightweight site exploration without a separate crawling tool',
    ],
    examples: [
      "Summarize https://en.wikipedia.org/wiki/Large_language_model",
      "What is this page about? https://python.org",
      "Key takeaways from https://openai.com/blog",
      "List all links on https://news.ycombinator.com",
      "https://github.com/langchain-ai/langchain — give me a one-paragraph overview",
    ],
    appUrl: 'http://localhost:8071',
  },
  {
    id: 'code-reviewer',
    name: 'Code Reviewer',
    tagline: 'Paste or upload code — get structured bug, security, and style feedback',
    type: 'other',
    surface: 'gateway',
    description:
      'An AI-powered code review tool with a browser UI. Paste a snippet or upload a source file (.py, .js, .ts, .java, .go, .rs, .cpp, .sql, .sh, and more) and choose a focus mode: Full Review, Security, Performance, Style, Bugs, Architecture, or Testability. The agent detects the language, validates Python syntax via AST, extracts code metrics (LOC, complexity, top-level definitions), and returns a structured review with severity-rated issues, concrete suggestions, and deeper insights. Ask follow-up questions about the loaded code without re-submitting. Session review history is collapsible and copyable.',
    category: 'devtools',
    status: 'working',
    channels: [],
    tools: ['check_python_syntax()', 'extract_code_metrics()', 'detect_language()'],
    demoPath: 'apps/code_reviewer',
    howToRun: {
      envVars: ['LLM_PROVIDER', 'LLM_MODEL', 'ANTHROPIC_API_KEY'],
      setup: [
        'cd apps/code_reviewer',
        'pip install -r requirements.txt',
      ],
      command: 'python main.py --port 18807',
    },
    architecture:
      'FastAPI serves the single-page UI. POST /review → CugaAgent calls detect_language, check_python_syntax (Python only, AST-based), and extract_code_metrics → structured review with severity badges. POST /ask → free-form follow-up on any loaded code. POST /upload → reads a source file and returns its text so the UI can populate the code area. GET /history → in-memory list of last 50 reviews (session-scoped).',
    diagram: `python main.py  →  http://127.0.0.1:18807

User: pastes Python function, selects "Security" focus, clicks Review
      │  POST /review  {code, language:"python", focus:"security"}
      ▼
CugaAgent
      ├─ detect_language(code)          → {"language":"python","confidence":"high"}
      ├─ check_python_syntax(code)      → {"valid":true,"error":null}
      ├─ extract_code_metrics(code)     → {total_lines:42, branch_complexity:7, ...}
      ▼
Structured review:
  ### Summary  — Good overall, one injection risk
  ### Issues Found
    [HIGH] Unsanitised user input passed to subprocess.run() — line 14
  ### Suggestions
    1. Use shlex.quote() or subprocess list-form …
  ### Metrics  — Lines: 42 (non-blank: 36), Complexity: 7

User: "How would you refactor this using the strategy pattern?"
      │  POST /ask
      ▼
CugaAgent (code injected as context) → refactoring walkthrough`,
    cugaContribution: [
      'check_python_syntax runs AST.parse before the LLM sees the code — syntax errors reported instantly, no token waste',
      'extract_code_metrics gives the agent concrete numbers (LOC, branch count, top-level defs) to ground its review in facts',
      'Focus mode chips translate to a focus_hint injected into the prompt — same agent, different lens, no code duplication',
      'Session review history (last 50) is maintained in-memory and displayed as collapsible cards with copy-to-clipboard',
    ],
    examples: [
      "Paste a Python function and select Bugs focus",
      "Upload a JavaScript file and select Security focus",
      "Paste a SQL query and ask: How could I optimise this for 10M rows?",
      "Load a Go file and click Architecture",
      "How would you refactor this using the strategy pattern?",
      "Is there any XSS risk in the current code?",
    ],
    appUrl: 'http://localhost:18807',
  },
]

export const CATEGORIES: Record<Category, { label: string; color: string }> = {
  monitoring: { label: 'Monitoring', color: 'blue' },
  communication: { label: 'Communication', color: 'purple' },
  productivity: { label: 'Productivity', color: 'green' },
  devtools: { label: 'Dev Tools', color: 'orange' },
  content: { label: 'Content', color: 'pink' },
  documents: { label: 'Documents', color: 'cyan' },
  finance: { label: 'Finance', color: 'yellow' },
  infrastructure: { label: 'Infrastructure', color: 'red' },
}

export const STATUS_LABELS: Record<Status, { label: string; color: string }> = {
  working: { label: 'Working', color: 'green' },
  partial: { label: 'Partial', color: 'yellow' },
  gap: { label: 'Gap', color: 'red' },
}

export const SURFACES: Record<Surface, { label: string; tagline: string; color: string; icon: string }> = {
  gateway: {
    label: 'Conversation Gateways',
    tagline: 'A human talks to the agent in real-time — browser, Telegram, WhatsApp, or phone. One agent, any channel.',
    color: 'indigo',
    icon: '💬',
  },
  pipeline: {
    label: 'Automated Pipelines',
    tagline: 'The agent runs on a schedule or reacts to system events — cron, webhooks, folder drops, IMAP, audio/video files. No human in the loop.',
    color: 'emerald',
    icon: '⚡',
  },
}
