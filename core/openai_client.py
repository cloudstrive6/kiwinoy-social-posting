"""Shared OpenAI helpers used by the agents.

Three capabilities:
  - research():  Responses API + built-in web_search tool for live trends
  - write():     plain text generation (captions, threads)
  - image():     gpt-image-1 image generation, returns PNG bytes

Models are read from config.yaml -> models.* so you can swap them without
touching code.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Optional

from openai import OpenAI

from .config import CONFIG

_client: Optional[OpenAI] = None


def client() -> OpenAI:
    global _client
    if _client is None:
        key = CONFIG.openai_api_key
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env (local) or to your "
                "GitHub Actions secrets (cloud)."
            )
        # Generous retries/backoff so transient upstream blips (429, 5xx,
        # Cloudflare 520) don't kill an autonomous run.
        _client = OpenAI(api_key=key, max_retries=5, timeout=120.0)
    return _client


def research(prompt: str, system: str = "") -> str:
    """Run a research prompt with the built-in web_search tool. Returns text.

    Falls back to a plain (no-tools) call if web search is unavailable, so the
    pipeline degrades gracefully instead of crashing.
    """
    model = CONFIG.models["research"]
    tool = CONFIG.models.get("web_search_tool", "web_search")
    full_input = (system + "\n\n" + prompt).strip() if system else prompt
    try:
        resp = client().responses.create(
            model=model,
            tools=[{"type": tool}],
            input=full_input,
        )
        return (resp.output_text or "").strip()
    except Exception:
        # Web-search tool not enabled / name changed -> degrade to no tools.
        resp = client().responses.create(model=model, input=full_input)
        return (resp.output_text or "").strip()


def write(prompt: str, system: str = "", model: str | None = None) -> str:
    """Plain text generation (no web tool). Returns text. Used as the OpenAI
    writer for captions/threads via core.writer."""
    model = model or CONFIG.models.get("writer_openai") or CONFIG.models["research"]
    full_input = (system + "\n\n" + prompt).strip() if system else prompt
    resp = client().responses.create(model=model, input=full_input)
    return (resp.output_text or "").strip()


def image(prompt: str, size: str | None = None, quality: str | None = None) -> bytes:
    """Generate one image with gpt-image-1. Returns PNG bytes."""
    cfg = CONFIG.image
    resp = client().images.generate(
        model=CONFIG.models["image"],
        prompt=prompt,
        size=size or cfg.get("size", "1024x1024"),
        quality=quality or cfg.get("quality", "high"),
        n=1,
    )
    b64 = resp.data[0].b64_json
    return base64.b64decode(b64)


def extract_json(text: str) -> dict[str, Any]:
    """Best-effort: pull the first JSON object out of a model response."""
    text = text.strip()
    # Strip ```json fences if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    # Otherwise grab from first { to last }.
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    return json.loads(text)
