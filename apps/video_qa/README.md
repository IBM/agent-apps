# Video Q&A

Transcribe a video or audio recording, then ask questions about it in natural
language and get timestamped answers. Transcription and indexing happen entirely
in Python — the LLM only runs when answering questions.

```bash
python run.py meeting.mp4                                # interactive CLI
python run.py meeting.mp4 --ask "where was M3 discussed?"  # single question
python run.py --web                                      # browser UI at localhost:8766
```

---

## Division of Responsibilities

### The App (transcriber.py + index.py + run.py)

- **Extracts audio** from video files via ffmpeg — no LLM
- **Transcribes** using faster-whisper (local model) — no LLM
- **Embeds and indexes** transcript segments in ChromaDB via sentence-transformers — no LLM
- **Caches** transcripts and vectors on disk — same file is never re-transcribed
- **Retrieves semantically similar segments** via ChromaDB cosine similarity — no LLM
- **Serves the web UI** — transcript panel, Q&A, keyword filter (FastAPI)

The app does all the heavy lifting before the agent is involved.

### CugaAgent

The agent receives a question and uses tools to retrieve relevant transcript
segments, then composes a timestamped answer.

| Invocation | Input | Output |
|---|---|---|
| User question | Natural language question | Answer with `[MM:SS]` timestamps |
| Timestamp query | "What was said at 10:23?" | Transcript text at that time |

### Agent Tools

| Tool | What it does | Implemented in |
|---|---|---|
| `transcribe_video` | Run Whisper on a file, index segments in ChromaDB | `transcriber.py` + `index.py` |
| `search_transcript` | Semantic search → segments with timestamps | `index.py` (ChromaDB) |
| `get_segment_at_time` | Return the segment covering a given second | `index.py` |

All tools call Python functions directly — no external API calls, no network.

### Agent Instructions

Tool usage, timestamp format, citation rules, and "not found" behaviour are inlined as `special_instructions` in `_get_agent()` inside `agent.py`.

---

## Quick Start

```bash
pip install -r requirements.txt
brew install ffmpeg       # for .mp4, .mov, .mkv files

python run.py meeting.mp4
```

### Using the Docker web UI

Videos must be placed in `apps/video_qa/videos/` on the host. That directory
is mounted read-only at `/videos` inside the container.

```bash
cp ~/Downloads/meeting.mp4 apps/video_qa/videos/
# Then enter /videos/meeting.mp4 in the UI
```

---

## How Files Are Processed

```
Phase 1 — App only, no LLM:

  meeting.mp4
      → ffmpeg: extract audio
      → faster-whisper: [{start, end, text}, ...]   (cached to .cache/transcripts/)
      → sentence-transformers: embed each segment
      → ChromaDB: store vectors                     (cached to .cache/chroma/)

Phase 2 — CugaAgent answers questions:

  "Where was M3 discussed?"
      → agent calls search_transcript("M3")
            → ChromaDB cosine similarity → top 6 matching segments
      → agent composes: "[00:04] M3 was introduced... [10:02–11:45] benchmarks covered..."
```

Phase 1 runs once per file. Subsequent runs skip it entirely.

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `rits` \| `anthropic` \| `openai` \| `watsonx` \| `ollama` \| `litellm` |
| `LLM_MODEL` | Model name override |

---

## Files

| File | Purpose |
|---|---|
| `run.py` | Entry point — CLI REPL and FastAPI web UI |
| `agent.py` | `VideoQAAgent` — wraps CugaAgent with three tools |
| `transcriber.py` | Whisper pipeline, ffmpeg extraction, segment caching |
| `index.py` | ChromaDB — embed, store, search, timestamp lookup |
| `_SYSTEM` in `agent.py` | Agent instructions — tool usage, timestamp format, citation rules (inlined) |
| `requirements.txt` | Python dependencies |
| `.cache/` | Transcripts + ChromaDB vectors (auto-created, safe to delete to re-transcribe) |
