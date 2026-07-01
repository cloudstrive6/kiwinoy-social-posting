"""Vision judge for thumbnails — Claude Haiku (cheap) rates RELEVANCE + QUALITY.

Used by the long-form thumbnail pipeline (agents/thumbnail.py via the orchestrator)
to PICK the best of the rendered variants: does the image match the video's topic,
and is it a bold, scroll-stopping thumbnail? ~half a cent per thumbnail on Haiku.

FAILS OPEN: if there's no ANTHROPIC_API_KEY, the `anthropic` SDK is missing, or any
call errors, it returns None and the caller falls back to the free heuristic
inspector — so the judge can never block a thumbnail from being generated.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = "claude-haiku-4-5"   # cheapest tier ($1/$5 per 1M); plenty for QC

_PROMPT = (
    "You are a YouTube gaming thumbnail art director judging one thumbnail for a "
    "specific video.\n\nVIDEO: {topic}\n\nRate THIS thumbnail. Be strict — most "
    "thumbnails are mediocre. Return ONLY minified JSON, no prose:\n"
    '{{"relevant": <0-10: does the background scene / character actually match THIS '
    'video and game>, "scroll_stopping": <0-10: one clear bold subject, high '
    'contrast, readable at a glance, would stop a scroll>, "issues": ["<=4 short '
    'problems"], "verdict": "<one short line>"}}'
)


def judge_thumbnail(image_path, *, topic: str,
                    model: str = DEFAULT_MODEL) -> Optional[dict]:
    """Ask Haiku to rate a thumbnail. Returns {relevant, scroll_stopping, score
    (0-1), issues, verdict, model} or None on any failure (caller falls back)."""
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import anthropic
    except Exception:
        return None
    try:
        b64 = base64.standard_b64encode(Path(image_path).read_bytes()).decode("ascii")
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=model, max_tokens=320,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": _PROMPT.format(topic=topic)},
            ]}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        d = json.loads(text[text.find("{"): text.rfind("}") + 1])
        rel = max(0.0, min(10.0, float(d.get("relevant", 0))))
        ss = max(0.0, min(10.0, float(d.get("scroll_stopping", 0))))
        # weight relevance a touch higher — a gorgeous but off-topic thumb still misleads
        return {"relevant": rel, "scroll_stopping": ss,
                "score": round((rel * 0.55 + ss * 0.45) / 10.0, 3),
                "issues": [str(x) for x in (d.get("issues") or [])][:4],
                "verdict": str(d.get("verdict", "")).strip()[:120], "model": model}
    except Exception as e:
        print(f"[vision] judge failed ({e!r}) — falling back to heuristic.", flush=True)
        return None
