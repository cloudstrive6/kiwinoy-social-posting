"""ElevenLabs text-to-speech client (AI voiceover for reels).

Synthesizes a short Taglish narration line to MP3 bytes. Fully FAIL-OPEN: if
the API key is missing, the feature is disabled, or the request errors, it
returns None and the reel simply renders music-only (exactly as before). The
voiceover is a nice-to-have, never a reason a reel fails to post.
"""
from __future__ import annotations

from typing import Optional

import requests

from core.config import CONFIG

_BASE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


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
