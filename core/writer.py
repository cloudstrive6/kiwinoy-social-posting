"""Writer dispatcher — the captions/Threads agents call this.

Routes text generation to OpenAI or Claude based on config.yaml:
  models.writer_provider = "openai" | "anthropic"

Switching providers is a one-line config change; no agent code changes.
"""
from __future__ import annotations

from core.config import CONFIG


def write(prompt: str, system: str = "") -> str:
    provider = str(CONFIG.models.get("writer_provider", "openai")).lower()
    if provider in ("anthropic", "claude"):
        from core import claude_client
        return claude_client.write(prompt, system=system)
    # default: OpenAI
    from core import openai_client
    model = CONFIG.models.get("writer_openai")
    return openai_client.write(prompt, system=system, model=model)
