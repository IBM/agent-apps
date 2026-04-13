"""
VideoQAAgent — CugaAgent-backed video Q&A with timestamps.

Exposes three tools to CugaAgent:
  transcribe_video    — run Whisper on a file, index segments in ChromaDB
  search_transcript   — semantic search → returns segments with timestamps
  get_segment_at_time — what was said at a specific second?

Usage
-----
    from agent import VideoQAAgent

    agent = VideoQAAgent()
    await agent.transcribe("meeting.mp4")
    answer = await agent.ask("Where was M3 discussed?")
    print(answer)
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_EXAMPLE_DIR = Path(__file__).parent
_DEMOS_DIR   = _EXAMPLE_DIR.parent

_SYSTEM = """\
# Video Q&A

You are a video Q&A assistant. You answer questions about the content of a transcribed video, always citing exact timestamps so the user can jump to the source.

## Tools available

| Tool | When to use |
|---|---|
| `transcribe_video` | When the user provides a video/audio file path that hasn't been indexed yet |
| `search_transcript` | For any content question — retrieves relevant segments with timestamps |
| `get_segment_at_time` | When the user asks what was said at a specific time |

## Answering questions

For every content question:
1. Call `search_transcript` with a focused query
2. Read the returned segments — each has `start_fmt` (e.g. "00:10:02") and `end_fmt`
3. Compose your answer, quoting or paraphrasing the relevant content
4. **Always** cite the timestamp(s) at the end: "→ discussed at **10:02**"

If multiple segments are relevant, list all timestamps.

## Timestamp format

- Use `MM:SS` for videos under an hour: `10:02`
- Use `H:MM:SS` for videos over an hour: `1:10:02`
- Always bold the timestamp: **10:02**

## Location questions

When the user asks "where", "when", or "at what point" something was discussed:
- Search for the topic
- Lead with the timestamp, then summarise what was said
- Example: "M3 was discussed at **10:02 – 11:45**. The speaker introduced..."

## No answer found

If `search_transcript` returns no relevant results, say:
"I didn't find any discussion of [topic] in the transcript. The video may not cover it."

Never guess or hallucinate content that isn't in the retrieved segments.

## Multiple related questions

If the user asks a broad question ("summarise the key points"), call `search_transcript` 2–3 times with different focused queries, then synthesise the results into a structured answer with timestamps for each point.
"""

for _p in [str(_EXAMPLE_DIR), str(_DEMOS_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------

def _make_tools(video_path_ref: dict):
    """
    Build the three tools. video_path_ref["path"] is set after transcription
    so the search tools always operate on the right file.
    """
    from langchain_core.tools import tool
    import transcriber as tr
    import index as idx

    @tool
    def transcribe_video(video_path: str, model_size: str = "base") -> str:
        """
        Transcribe a video or audio file and index it for Q&A.

        Extracts audio with ffmpeg (video files), runs Whisper, stores segments
        in ChromaDB. Cached on disk — same file is never re-transcribed.

        Args:
            video_path: Absolute or relative path to the video/audio file.
            model_size: Whisper model size — tiny | base | small | medium | large-v3.

        Returns:
            JSON with segments_count and duration_fmt.
        """
        segments = tr.transcribe(video_path, model_size=model_size)
        idx.index_segments(video_path, segments)
        video_path_ref["path"]     = video_path
        video_path_ref["segments"] = segments
        duration = segments[-1]["end"] if segments else 0
        return json.dumps({
            "segments_count": len(segments),
            "duration_fmt":   tr.fmt_time(duration),
            "video_path":     video_path,
        })

    @tool
    def search_transcript(query: str, n_results: int = 6) -> str:
        """
        Semantic search over the indexed transcript.

        Args:
            query:     Natural language query.
            n_results: Max number of segments to return (default 6).

        Returns:
            JSON array of matching segments with text, start_fmt, end_fmt, distance.
        """
        path = video_path_ref.get("path")
        if not path:
            return json.dumps({"error": "No video indexed. Call transcribe_video first."})
        hits = idx.search(path, query, n_results=n_results)
        return json.dumps(hits)

    @tool
    def get_segment_at_time(seconds: float) -> str:
        """
        Return the transcript segment that covers a given timestamp.

        Args:
            seconds: Time offset in seconds from the start of the video.

        Returns:
            JSON with text, start_fmt, end_fmt for that moment.
        """
        segments = video_path_ref.get("segments", [])
        if not segments:
            return json.dumps({"error": "No transcript loaded. Call transcribe_video first."})
        import index as idx
        seg = idx.get_at_time(video_path_ref.get("path", ""), seconds, segments)
        return json.dumps(seg) if seg else json.dumps({"error": "No segment found."})

    return [transcribe_video, search_transcript, get_segment_at_time]


# ---------------------------------------------------------------------------
# VideoQAAgent — high-level wrapper
# ---------------------------------------------------------------------------

class VideoQAAgent:
    """
    High-level wrapper around CugaAgent for video Q&A.

    Manages a shared video_path_ref so all three tools operate on the
    same video after transcription.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        whisper_model: str = "base",
    ):
        self._provider     = provider
        self._model        = model
        self._whisper_model = whisper_model
        self._video_path_ref: dict = {}
        self._agent = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def video_path(self) -> str | None:
        return self._video_path_ref.get("path")

    @property
    def segments(self) -> list[dict]:
        return self._video_path_ref.get("segments", [])

    # ------------------------------------------------------------------
    # Agent lazy-init
    # ------------------------------------------------------------------

    def _get_agent(self):
        if self._agent is None:
            from cuga import CugaAgent
            from _llm import create_llm
            llm = create_llm(provider=self._provider, model=self._model)

            self._agent = CugaAgent(
                model=llm,
                tools=_make_tools(self._video_path_ref),
                special_instructions=_SYSTEM,
                cuga_folder=str(_EXAMPLE_DIR / ".cuga"),
            )
            log.info("VideoQAAgent CugaAgent ready")
        return self._agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe(self, video_path: str, force: bool = False) -> dict:
        """
        Transcribe and index a video file.

        Args:
            video_path: Path to the video/audio file.
            force:      Re-index even if already cached.

        Returns:
            {"segments_count": N, "duration_fmt": "MM:SS", "video_path": "..."}
        """
        import transcriber as tr
        import index as idx

        segments = tr.transcribe(video_path, model_size=self._whisper_model)
        idx.index_segments(video_path, segments, force=force)

        self._video_path_ref["path"]     = video_path
        self._video_path_ref["segments"] = segments

        duration = segments[-1]["end"] if segments else 0
        return {
            "segments_count": len(segments),
            "duration_fmt":   tr.fmt_time(duration),
            "video_path":     video_path,
        }

    async def ask(self, question: str, thread_id: str = "video-qa") -> str:
        """
        Ask a question about the indexed video.

        Args:
            question:  Natural language question.
            thread_id: Thread for multi-turn context.

        Returns:
            Agent's answer string with timestamps.
        """
        agent = self._get_agent()
        result = await agent.invoke(question, thread_id=thread_id)
        return result.answer
