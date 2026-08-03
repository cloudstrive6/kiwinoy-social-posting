"""Google Gemini (AI Studio) client — used for the thumbnail RELIGHT pass.

We keep the character EXACT by scraping the real game render and rembg-cutting it,
then hand that cutout (+ optional background) to gemini-2.5-flash-image ("Nano
Banana") as an IMAGE EDIT — not a text-to-image generation — so Gemini only
relights / dramatizes / composites while preserving the character's identity.

Public API:
  edit_image(prompt, image_paths, ...) -> PNG bytes
  available() -> bool   (True if a GEMINI_API_KEY is set)
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Sequence

from core.config import CONFIG

# GA image-capable model. Override via config.models["gemini_image"] if needed.
_DEFAULT_MODEL = "gemini-2.5-flash-image"


def _model() -> str:
    try:
        return CONFIG.models.get("gemini_image", _DEFAULT_MODEL) or _DEFAULT_MODEL
    except Exception:
        return _DEFAULT_MODEL


def available() -> bool:
    return bool(CONFIG.gemini_api_key)


def _client():
    key = CONFIG.gemini_api_key
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to .env (get a key at "
            "https://aistudio.google.com/apikey).")
    from google import genai
    return genai.Client(api_key=key)


def _extract_image(resp) -> Optional[bytes]:
    """Return PNG bytes of the first image in a Gemini response, or None."""
    from PIL import Image
    for cand in (resp.candidates or []):
        content = getattr(cand, "content", None)
        for part in (getattr(content, "parts", None) or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                img = Image.open(io.BytesIO(inline.data)).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, "PNG")
                return buf.getvalue()
    return None


def edit_image(
    prompt: str,
    image_paths: Sequence[str],
    *,
    aspect_ratio: str = "16:9",
    model: Optional[str] = None,
    retries: int = 5,
) -> bytes:
    """Edit/compose the given input images per `prompt` with Gemini. The FIRST
    image is the primary subject (e.g. the character cutout); any others are
    references (e.g. a background plate). Returns PNG bytes of the first image
    Gemini emits.

    IMPORTANT re: copyrighted characters — Gemini's IP safety is STOCHASTIC: the
    SAME cutout can pass on one call and hit FinishReason.PROHIBITED_CONTENT on
    the next. Two mitigations: (1) the caller's `prompt` should describe the ART
    DIRECTION only and NOT name the IP ("Marvel's Spider-Man 2", "Symbiote suit",
    etc.) — we supply the exact character as an image, so naming it only raises
    the block rate; (2) we RETRY on a block/empty result up to `retries` times.
    Also note the Gemini-3 image models refuse IP far more aggressively than
    gemini-2.5-flash-image, so that stays the default."""
    from PIL import Image
    from google.genai import types

    client = _client()
    parts: list = [prompt]
    for p in image_paths:
        if p and Path(p).exists():
            parts.append(Image.open(p).convert("RGBA"))
    cfg = types.GenerateContentConfig(
        response_modalities=["Text", "Image"],
        image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
    )

    last = ""
    for attempt in range(max(1, retries)):
        resp = client.models.generate_content(
            model=model or _model(), contents=parts, config=cfg)
        img = _extract_image(resp)
        if img:
            return img
        cand = (resp.candidates or [None])[0]
        last = str(getattr(cand, "finish_reason", "") or "no-image")
    raise RuntimeError(
        f"Gemini returned no image after {retries} attempts (last: {last}). "
        "For copyrighted characters this is usually a stochastic PROHIBITED_CONTENT "
        "block — retry, or remove IP names from the prompt.")
