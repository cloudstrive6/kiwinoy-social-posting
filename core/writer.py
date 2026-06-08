"""Writer dispatcher — the caption/beats agents call this.

Routes text generation based on config.yaml:
  models.writer_provider =
    "claude_code"  -> Claude via CLAUDE_CODE_OAUTH_TOKEN (FREE on your plan)
    "openai"       -> gpt-4.1 (paid)
    "anthropic"    -> Anthropic API key (paid)

Switching providers is a one-line config change; no agent code changes.
"""
from __future__ import annotations

from core.config import CONFIG


def write(prompt: str, system: str = "") -> str:
    provider = str(CONFIG.models.get("writer_provider", "openai")).lower()

    if provider in ("claude_code", "oauth", "subscription"):
        from core import claude_code
        full = (system + "\n\n" + prompt).strip() if system else prompt
        return claude_code.run(full, web=False)

    if provider in ("anthropic", "claude"):
        from core import claude_client
        return claude_client.write(prompt, system=system)

    # default: OpenAI
    from core import openai_client
    model = CONFIG.models.get("writer_openai")
    return openai_client.write(prompt, system=system, model=model)
