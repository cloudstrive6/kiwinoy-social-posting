"""Vision judge for thumbnails — rates RELEVANCE + QUALITY, cheapest-first.

Used by the long-form thumbnail pipeline (via the orchestrator) to PICK the best of
the rendered variants: does the image match the video's topic, and is it a bold,
scroll-stopping thumbnail?

Chain (each fails open to the next): Claude **Haiku** (~$0.006/thumbnail) ->
**OpenAI** vision -> None (the caller then uses the free heuristic inspector). So the
judge can never block a thumbnail from being generated.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

ANTHROPIC_MODEL = "claude-haiku-4-5"   # $1/$5 per 1M — plenty for QC
OPENAI_MODEL = "gpt-4o-mini"           # cheap OpenAI vision fallback

_PROMPT = (
    "You are a YouTube gaming thumbnail art director judging one thumbnail for a "
    "specific video.\n\nVIDEO: {topic}\n\nRate THIS thumbnail. Be strict — most "
    "thumbnails are mediocre. Return ONLY minified JSON, no prose:\n"
    '{{"relevant": <0-10: does the background scene / character actually match THIS '
    'video and game>, "scroll_stopping": <0-10: one clear bold subject, high '
    'contrast, readable at a glance, would stop a scroll>, "issues": ["<=4 short '
    'problems"], "verdict": "<one short line>"}}'
)


def _normalize(d: dict, model: str) -> dict:
    rel = max(0.0, min(10.0, float(d.get("relevant", 0))))
    ss = max(0.0, min(10.0, float(d.get("scroll_stopping", 0))))
    return {  # relevance weighted a touch higher — a pretty but off-topic thumb misleads
        "relevant": rel, "scroll_stopping": ss,
        "score": round((rel * 0.55 + ss * 0.45) / 10.0, 3),
        "issues": [str(x) for x in (d.get("issues") or [])][:4],
        "verdict": str(d.get("verdict", "")).strip()[:120], "model": model,
    }


def _b64(image_path) -> str:
    return base64.standard_b64encode(Path(image_path).read_bytes()).decode("ascii")


def _judge_anthropic(image_path, topic: str, model: str) -> Optional[dict]:
    try:
        from core.config import CONFIG  # importing loads .env
        key = (CONFIG.anthropic_api_key or "").strip()
    except Exception:
        import os
        key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    try:
        import json

        import anthropic
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=model, max_tokens=320,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg", "data": _b64(image_path)}},
                {"type": "text", "text": _PROMPT.format(topic=topic)},
            ]}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return _normalize(json.loads(text[text.find("{"): text.rfind("}") + 1]), model)
    except Exception as e:
        print(f"[vision] anthropic judge failed ({e!r})", flush=True)
        return None


def _judge_openai(image_path, topic: str, model: str) -> Optional[dict]:
    try:
        from core import openai_client
        from core.config import CONFIG
        if not CONFIG.openai_api_key:
            return None
        content = [
            {"type": "input_text", "text": _PROMPT.format(topic=topic)},
            {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_b64(image_path)}"},
        ]
        resp = openai_client.client().responses.create(
            model=model, input=[{"role": "user", "content": content}])
        return _normalize(openai_client.extract_json(resp.output_text or ""), model)
    except Exception as e:
        print(f"[vision] openai judge failed ({e!r})", flush=True)
        return None


def judge_thumbnail(image_path, *, topic: str, model: str = ANTHROPIC_MODEL,
                    openai_model: str = OPENAI_MODEL) -> Optional[dict]:
    """Rate a thumbnail. Tries Claude Haiku, then OpenAI, then returns None (the
    caller falls back to the free heuristic). Returns {relevant, scroll_stopping,
    score (0-1), issues, verdict, model}."""
    return (_judge_anthropic(image_path, topic, model)
            or _judge_openai(image_path, topic, openai_model))
