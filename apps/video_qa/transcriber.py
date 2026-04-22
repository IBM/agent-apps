"""
Transcriber — extract audio from video and transcribe with Whisper.

Returns timestamped segments: [{text, start, end, start_fmt, end_fmt}, ...]

Dependencies (install once):
    pip install faster-whisper
    brew install ffmpeg   # or: conda install -c conda-forge ffmpeg

faster-whisper is ~4x faster than openai-whisper and returns word-level timestamps.
Falls back to openai-whisper if faster-whisper is not installed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / ".cache" / "transcripts"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def transcribe(video_path: str | Path, model_size: str = "base") -> list[dict[str, Any]]:
    """
    Transcribe a video or audio file and return timestamped segments.

    Each segment: {text, start, end, start_fmt, end_fmt}

    Results are cached on disk by file hash.

    Args:
        video_path: Path to .mp4, .mov, .mkv, .m4a, .wav, .mp3, etc.
        model_size: Whisper model size — "tiny", "base", "small", "medium", "large-v3".
    """
    video_path = Path(video_path)

    # When running in Docker, videos must be placed in apps/video_qa/videos/
    # on the host, which is mounted read-only at /videos inside the container.
    _videos_dir = Path("/videos")
    if _videos_dir.exists():
        try:
            video_path.resolve().relative_to(_videos_dir.resolve())
        except ValueError:
            raise ValueError(
                f"File must be inside /videos. "
                f"Copy your file to apps/video_qa/videos/ on the host and use "
                f"/videos/<filename> as the path. Got: {video_path}"
            )

    if not video_path.exists():
        raise FileNotFoundError(
            f"Video file not found: {video_path}. "
            f"Make sure the file is in apps/video_qa/videos/ and use /videos/<filename>."
        )

    cache_key  = _file_hash(video_path)
    cache_file = _CACHE_DIR / f"{cache_key}_{model_size}.json"

    if cache_file.exists():
        log.info("Transcript cache hit: %s", cache_file.name)
        return json.loads(cache_file.read_text())

    log.info("Transcribing %s with model=%s", video_path.name, model_size)

    audio_path = _extract_audio(video_path)

    try:
        segments = _run_whisper(audio_path, model_size)
    finally:
        if audio_path != video_path:
            audio_path.unlink(missing_ok=True)

    cache_file.write_text(json.dumps(segments, ensure_ascii=False, indent=2))
    log.info("Transcription complete — %d segments, cached at %s", len(segments), cache_file.name)
    return segments


def invalidate_cache(video_path: str | Path, model_size: str = "base") -> None:
    video_path = Path(video_path)
    cache_key  = _file_hash(video_path)
    cache_file = _CACHE_DIR / f"{cache_key}_{model_size}.json"
    if cache_file.exists():
        cache_file.unlink()
        log.info("Cache invalidated: %s", cache_file.name)


def fmt_time(seconds: float) -> str:
    """Format seconds as H:MM:SS (or MM:SS if under one hour)."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(str(path.stat().st_size).encode())
    with path.open("rb") as f:
        h.update(f.read(1024 * 1024))
    return h.hexdigest()[:16]


def _extract_audio(video_path: Path) -> Path:
    suffix = video_path.suffix.lower()
    if suffix in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}:
        return video_path

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(
            "ffmpeg is required to extract audio from video files.\n"
            "Install with: brew install ffmpeg"
        )

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out_path = Path(tmp.name)

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr.decode(errors='replace')}")
    log.info("Audio extracted: %s → %s", video_path.name, out_path)
    return out_path


def _run_whisper(audio_path: Path, model_size: str) -> list[dict[str, Any]]:
    try:
        return _faster_whisper(audio_path, model_size)
    except ImportError:
        log.warning("faster-whisper not installed — trying openai-whisper")
    return _openai_whisper(audio_path, model_size)


def _faster_whisper(audio_path: Path, model_size: str) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, compute_type="int8")
    log.info("Running faster-whisper (%s)…", model_size)

    segments_iter, _ = model.transcribe(
        str(audio_path), beam_size=5, vad_filter=True, word_timestamps=False,
    )

    segments = []
    for seg in segments_iter:
        segments.append({
            "text":      seg.text.strip(),
            "start":     round(seg.start, 2),
            "end":       round(seg.end, 2),
            "start_fmt": fmt_time(seg.start),
            "end_fmt":   fmt_time(seg.end),
        })
    return segments


def _openai_whisper(audio_path: Path, model_size: str) -> list[dict[str, Any]]:
    try:
        import whisper
    except ImportError:
        raise ImportError(
            "No Whisper library found. Install one of:\n"
            "  pip install faster-whisper   (recommended)\n"
            "  pip install openai-whisper"
        )

    log.info("Running openai-whisper (%s)…", model_size)
    model  = whisper.load_model(model_size)
    result = model.transcribe(str(audio_path), verbose=False)

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "text":      seg["text"].strip(),
            "start":     round(seg["start"], 2),
            "end":       round(seg["end"], 2),
            "start_fmt": fmt_time(seg["start"]),
            "end_fmt":   fmt_time(seg["end"]),
        })
    return segments
