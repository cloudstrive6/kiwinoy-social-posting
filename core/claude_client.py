"""Claude (Anthropic) helper — the writer brain for captions + Threads posts.

Model is read from config.yaml -> models.writer so you can swap it without code
changes (claude-sonnet-4-6 by default; bump to claude-opus-4-8 for max quality).
"""
from __future__ import annotations

from typing import Optional

from anthropic import Anthropic

from .config import CONFIG

_client: Optional[Anthropic] = None


def client() -> Anthropic:
    global _client
    if _client is None:
        key = CONFIG.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env (local) or to your "
                "GitHub Actions secrets (cloud)."
            )
        _client = Anthropic(api_key=key)
    return _client


def write(prompt: str, system: str = "") -> str:
    """Generate text with Claude. Returns the message text."""
    model = CONFIG.models["writer"]
    max_tokens = int(CONFIG.models.get("writer_max_tokens", 1024))
    msg = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or None,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
    return "".join(parts).strip()
