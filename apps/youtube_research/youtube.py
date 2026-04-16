"""
YouTube tools for the YouTube Research agent.

Two LangChain tools the agent can call:
  get_video_info   — YouTube oEmbed API (no key required)
  get_transcript   — youtube-transcript-api (no key required)
"""
from __future__ import annotations

import json
import re

import requests
from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_video_id(url: str) -> str | None:
    """Extract an 11-character YouTube video ID from various URL formats."""
    patterns = [
        r'(?:youtube\.com/watch\?.*?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    # Bare video ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url.strip()):
        return url.strip()
    return None


def _format_ts(seconds: float) -> str:
    """Convert seconds to MM:SS or H:MM:SS."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def get_video_info(youtube_url: str) -> str:
    """
    Get metadata for a YouTube video: title, channel name, and URL.

    Uses the YouTube oEmbed endpoint — no API key required.
    Call this before get_transcript to check if the video is relevant.

    Args:
        youtube_url: Full YouTube URL (or video ID).
    """
    video_id = _extract_video_id(youtube_url)
    if not video_id:
        return json.dumps({"error": f"Could not parse video ID from: {youtube_url}"})

    canonical = f"https://www.youtube.com/watch?v={video_id}"
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": canonical, "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return json.dumps({
            "video_id": video_id,
            "title": data.get("title", ""),
            "channel": data.get("author_name", ""),
            "channel_url": data.get("author_url", ""),
            "url": canonical,
        })
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            return json.dumps({"error": "Video is private or unavailable", "video_id": video_id})
        return json.dumps({"error": str(exc), "video_id": video_id})
    except Exception as exc:
        return json.dumps({"error": str(exc), "video_id": video_id})


@tool
def get_transcript(youtube_url: str) -> str:
    """
    Fetch the transcript (captions) for a YouTube video with timestamps.

    Returns timestamped text segments. Will fail if the video has no
    captions or subtitles available.

    Args:
        youtube_url: Full YouTube URL (or video ID).
    """
    video_id = _extract_video_id(youtube_url)
    if not video_id:
        return json.dumps({"error": f"Could not parse video ID from: {youtube_url}"})

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return json.dumps({
            "error": "youtube-transcript-api not installed. Run: pip install youtube-transcript-api"
        })

    # Fetch transcript — try English first, then fall back to any language
    try:
        ytt = YouTubeTranscriptApi()
        try:
            fetched = ytt.fetch(video_id, languages=["en", "en-US", "en-GB"])
        except Exception:
            fetched = ytt.fetch(video_id)
        segments = [
            {"start": s.start, "text": s.text, "duration": s.duration}
            for s in fetched
        ]
    except Exception as exc:
        return json.dumps({
            "error": f"Transcript unavailable: {exc}",
            "video_id": video_id,
        })

    if not segments:
        return json.dumps({"error": "No transcript segments found", "video_id": video_id})

    # Format with timestamps, cap at ~5 000 words to stay within context limits
    lines: list[str] = []
    word_count = 0
    max_words = 5000
    truncated = False

    for seg in segments:
        ts = _format_ts(seg["start"])
        text = seg["text"].strip()
        if not text:
            continue
        lines.append(f"[{ts}] {text}")
        word_count += len(text.split())
        if word_count > max_words:
            truncated = True
            break

    last_seg = segments[-1]
    total_duration = _format_ts(last_seg["start"] + last_seg.get("duration", 0))

    transcript_text = "\n".join(lines)
    if truncated:
        cutoff = _format_ts(segments[len(lines) - 1]["start"])
        transcript_text += f"\n\n[TRUNCATED at {cutoff} — full video is {total_duration}]"

    return json.dumps({
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "segments_returned": len(lines),
        "total_segments": len(segments),
        "total_duration": total_duration,
        "truncated": truncated,
        "transcript": transcript_text,
    })


def make_youtube_tools():
    return [get_video_info, get_transcript]
