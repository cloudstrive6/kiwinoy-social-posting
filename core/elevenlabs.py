"""ElevenLabs text-to-speech client (AI voiceover for reels).

Synthesizes a short Taglish narration line to MP3 bytes. Fully FAIL-OPEN: if
the API key is missing, the feature is disabled, or the request errors, it
returns None and the reel simply renders music-only (exactly as before). The
voiceover is a nice-to-have, never a reason a reel fails to post.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Optional

import requests

from core.config import CONFIG

_BASE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_BASE_TS = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"


def tts(text: str) -> Optional[bytes]:
    """Return MP3 bytes for `text`, or None if unavailable (never raises)."""
    text = (text or "").strip()
    cfg = CONFIG.reels.get("narration", {}) or {}
    key = CONFIG.elevenlabs_api_key
    if not text or not key or not cfg.get("enabled", True):
        return None

    voice_id = str(cfg.get("voice_id", "")).strip()
    if not voice_id:
        return None

    try:
        resp = requests.post(
            _BASE.format(voice_id=voice_id),
            headers={
                "xi-api-key": key,
                "accept": "audio/mpeg",
                "content-type": "application/json",
            },
            json={
                "text": text,
                "model_id": cfg.get("model_id", "eleven_multilingual_v2"),
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.75,
                    "style": 0.5,
                    "use_speaker_boost": True,
                },
            },
            timeout=90,
        )
        if resp.status_code == 200 and resp.content:
            return resp.content
        print(
            f"[elevenlabs] TTS failed ({resp.status_code}): {resp.text[:200]}",
            flush=True,
        )
    except Exception as e:  # network / SSL / timeout — fail open
        print(f"[elevenlabs] TTS error: {e!r}", flush=True)
    return None


# ---------------------------------------------------------- timestamped TTS

def _voice_cfg() -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    cfg = CONFIG.reels.get("narration", {}) or {}
    key = CONFIG.elevenlabs_api_key
    voice_id = str(cfg.get("voice_id", "")).strip()
    if not key or not voice_id or not cfg.get("enabled", True):
        return None, None, cfg
    return key, voice_id, cfg


def _chunk_text(text: str, max_chars: int = 2200) -> list[str]:
    """Split into <=max_chars chunks at sentence boundaries (TTS request limit)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if not s:
            continue
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur.strip())
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur.strip())
    return chunks or [text.strip()]


def _lines_from_alignment(
    align: dict[str, Any], offset: float, line_max: int = 34
) -> list[dict[str, Any]]:
    """Turn ElevenLabs character timings into short subtitle lines (offset added)."""
    chars = align.get("characters") or []
    starts = align.get("character_start_times_seconds") or []
    ends = align.get("character_end_times_seconds") or []
    n = min(len(chars), len(starts), len(ends))
    lines: list[dict[str, Any]] = []
    buf, b_start, b_end = "", None, 0.0
    for i in range(n):
        ch = chars[i]
        if b_start is None and ch.strip():
            b_start = float(starts[i])
        buf += ch
        b_end = float(ends[i])
        long_enough = len(buf.strip()) >= line_max and ch == " "
        sentence_end = ch in ".!?" and len(buf.strip()) >= 12
        if long_enough or sentence_end:
            t = buf.strip()
            if t and b_start is not None:
                lines.append({"start": b_start + offset, "end": b_end + offset, "text": t})
            buf, b_start = "", None
    t = buf.strip()
    if t and b_start is not None:
        lines.append({"start": b_start + offset, "end": b_end + offset, "text": t})
    return lines


def tts_timed(text: str, out_audio: Path) -> tuple[Optional[Path], list[dict[str, Any]]]:
    """Synthesize a (possibly long) script to one MP3 + synced subtitle lines.

    Chunks the text, calls the with-timestamps endpoint per chunk, concatenates
    the audio (ffmpeg) and merges character timings into subtitle lines. Returns
    (audio_path, subtitles) or (None, []) on any failure (fail-open: caller skips
    the commentary reel). Subtitles are [{start, end, text}] in seconds.
    """
    from core import ffmpeg as ff  # local import to avoid a cycle

    text = (text or "").strip()
    key, voice_id, cfg = _voice_cfg()
    if not text or not key or not voice_id:
        return None, []

    out_audio = Path(out_audio)
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    work = out_audio.parent
    chunks = _chunk_text(text)
    part_files: list[Path] = []
    subtitles: list[dict[str, Any]] = []
    offset = 0.0
    try:
        for idx, chunk in enumerate(chunks):
            resp = requests.post(
                _BASE_TS.format(voice_id=voice_id),
                headers={"xi-api-key": key, "content-type": "application/json"},
                json={
                    "text": chunk,
                    "model_id": cfg.get("model_id", "eleven_multilingual_v2"),
                    "voice_settings": {
                        "stability": 0.45, "similarity_boost": 0.75,
                        "style": 0.5, "use_speaker_boost": True,
                    },
                },
                timeout=180,
            )
            if resp.status_code != 200:
                print(f"[elevenlabs] timed TTS failed ({resp.status_code}): "
                      f"{resp.text[:200]}", flush=True)
                return None, []
            data = resp.json()
            audio_b64 = data.get("audio_base64")
            if not audio_b64:
                return None, []
            part = work / f"_vo_part{idx}.mp3"
            part.write_bytes(base64.b64decode(audio_b64))
            part_files.append(part)
            align = data.get("normalized_alignment") or data.get("alignment") or {}
            subtitles += _lines_from_alignment(align, offset)
            offset += ff.duration(part) or 0.0

        if not part_files:
            return None, []
        if len(part_files) == 1:
            part_files[0].replace(out_audio)
        else:
            listing = work / "_vo_concat.txt"
            listing.write_text(
                "".join(f"file '{p.name}'\n" for p in part_files), encoding="utf-8"
            )
            rc, err = ff.run(
                ["-f", "concat", "-safe", "0", "-i", str(listing),
                 "-c:a", "aac", "-b:a", "160k", str(out_audio)], timeout=600,
            )
            if rc != 0 or not out_audio.exists():
                print(f"[elevenlabs] VO concat failed (rc={rc}): {err}", flush=True)
                return None, []
        return out_audio, subtitles
    except Exception as e:
        print(f"[elevenlabs] timed TTS error: {e!r}", flush=True)
        return None, []
    finally:
        for p in part_files:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
