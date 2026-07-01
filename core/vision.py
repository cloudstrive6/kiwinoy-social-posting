"""Vision judge — rates thumbnails and character renders, cheapest-first.

Two public raters, both over the same fail-open chain (Claude **Haiku** ~$0.006 ->
**OpenAI** vision -> None so the caller falls back to a free heuristic / keeps going):
  - judge_thumbnail(...)        : does a finished thumbnail match its video + stop a scroll?
  - rate_character_render(...)  : is an image a clean, front-facing, high-quality render
                                  of a given character (for the thumbnail foreground)?
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Callable, Optional

ANTHROPIC_MODEL = "claude-haiku-4-5"   # $1/$5 per 1M — plenty for QC
OPENAI_MODEL = "gpt-4o-mini"           # cheap OpenAI vision fallback

_THUMB_PROMPT = (
    "You are a YouTube gaming thumbnail art director judging one thumbnail for a "
    "specific video.\n\nVIDEO: {topic}\n\nRate THIS thumbnail. Be strict — most "
    "thumbnails are mediocre. Return ONLY minified JSON, no prose:\n"
    '{{"relevant": <0-10: does the background scene / character actually match THIS '
    'video and game>, "scroll_stopping": <0-10: one clear bold subject, high '
    'contrast, readable at a glance, would stop a scroll>, "issues": ["<=4 short '
    'problems"], "verdict": "<one short line>"}}'
)

_PORTRAIT_PROMPT = (
    "You are choosing a CHARACTER RENDER to use as the bold foreground subject of a "
    "YouTube gaming thumbnail.\n\nCHARACTER: {subject}\n\nRate THIS image. Return ONLY "
    "minified JSON, no prose:\n"
    '{{"is_subject": <0-10: clearly this exact character, ONE character, not a group / '
    'scene / logo / text>, "front_facing": <0-10: faces the camera or 3/4 view — a pure '
    'side-profile or back view scores low>, "quality": <0-10: sharp, hi-res, clean '
    'official-looking render, not blurry / tiny / artifacted / a screenshot with HUD>, '
    '"clean_cutout": <0-10: isolated on a plain/transparent background with clean edges, '
    'head + upper body visible>, "issues": ["<=4 short problems"], "verdict": "<one line>"}}'
)


def _clamp10(v) -> float:
    try:
        return max(0.0, min(10.0, float(v)))
    except Exception:
        return 0.0


def _norm_thumb(d: dict, model: str) -> dict:
    rel, ss = _clamp10(d.get("relevant", 0)), _clamp10(d.get("scroll_stopping", 0))
    return {"relevant": rel, "scroll_stopping": ss,
            "score": round((rel * 0.55 + ss * 0.45) / 10.0, 3),
            "issues": [str(x) for x in (d.get("issues") or [])][:4],
            "verdict": str(d.get("verdict", "")).strip()[:120], "model": model}


def _norm_portrait(d: dict, model: str) -> dict:
    su, ff = _clamp10(d.get("is_subject", 0)), _clamp10(d.get("front_facing", 0))
    q, cc = _clamp10(d.get("quality", 0)), _clamp10(d.get("clean_cutout", 0))
    return {"is_subject": su, "front_facing": ff, "quality": q, "clean_cutout": cc,
            "score": round((su * 0.30 + ff * 0.25 + q * 0.25 + cc * 0.20) / 10.0, 3),
            "issues": [str(x) for x in (d.get("issues") or [])][:4],
            "verdict": str(d.get("verdict", "")).strip()[:120], "model": model}


def _b64(image_path) -> str:
    return base64.standard_b64encode(Path(image_path).read_bytes()).decode("ascii")


def _judge_anthropic(image_path, prompt: str, model: str) -> Optional[dict]:
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
                {"type": "text", "text": prompt},
            ]}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as e:
        print(f"[vision] anthropic judge failed ({e!r})", flush=True)
        return None


def _judge_openai(image_path, prompt: str, model: str) -> Optional[dict]:
    try:
        from core import openai_client
        from core.config import CONFIG
        if not CONFIG.openai_api_key:
            return None
        content = [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_b64(image_path)}"},
        ]
        resp = openai_client.client().responses.create(
            model=model, input=[{"role": "user", "content": content}])
        return openai_client.extract_json(resp.output_text or "")
    except Exception as e:
        print(f"[vision] openai judge failed ({e!r})", flush=True)
        return None


def _rate(image_path, prompt: str, normalize: Callable, model: str, openai_model: str) -> Optional[dict]:
    d = _judge_anthropic(image_path, prompt, model)
    used = model
    if d is None:
        d = _judge_openai(image_path, prompt, openai_model)
        used = openai_model
    return normalize(d, used) if d is not None else None


def judge_thumbnail(image_path, *, topic: str, model: str = ANTHROPIC_MODEL,
                    openai_model: str = OPENAI_MODEL) -> Optional[dict]:
    """Rate a finished thumbnail. Haiku -> OpenAI -> None (caller uses the heuristic).
    Returns {relevant, scroll_stopping, score (0-1), issues, verdict, model}."""
    return _rate(image_path, _THUMB_PROMPT.format(topic=topic), _norm_thumb, model, openai_model)


def rate_character_render(image_path, *, subject: str, model: str = ANTHROPIC_MODEL,
                          openai_model: str = OPENAI_MODEL) -> Optional[dict]:
    """Rate an image as a foreground character render for `subject`. Haiku -> OpenAI ->
    None. Returns {is_subject, front_facing, quality, clean_cutout, score (0-1),
    issues, verdict, model}."""
    return _rate(image_path, _PORTRAIT_PROMPT.format(subject=subject), _norm_portrait,
                 model, openai_model)
