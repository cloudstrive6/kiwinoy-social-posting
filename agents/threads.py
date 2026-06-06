"""Agent 3 — Threads Creator.

Spins the same brief into a native Threads post — punchier, more conversational
and community-driven than the FB/IG caption. Threads rewards hot takes and
replies, so this leans into a discussion starter.
"""
from __future__ import annotations

from typing import Any

from core import writer as ai
from core.config import CONFIG
from core.style import HUMAN_VOICE, sanitize


def _system() -> str:
    b = CONFIG.brand
    return (
        f"You are the Threads voice for {b['name']} ({b['handle']}). "
        f"Write in {b['language']}. Threads is casual, fast, and reply-hungry, "
        f"hot takes and questions win. Brand voice: {b['voice']}\n\n{HUMAN_VOICE}"
    )


def run(brief: dict[str, Any]) -> str:
    """Return a native Threads post string."""
    category = brief["category"]
    # Threads caps hashtags hard — use 1-2 only.
    tags = " ".join(CONFIG.hashtags[category][:2])
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))

    prompt = f"""Write ONE native Threads post.

TOPIC: {brief.get('title')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (accurate only):
{facts}

Rules:
- Lead with a bold take or a curiosity-gap line.
- Keep it under ~480 characters. 1-3 short lines.
- End by inviting replies ("agree?", "who you got?", "drop your team").
- Light emoji ok. Add at most these hashtags at the end: {tags}
- Output the post text only."""

    return sanitize(ai.write(prompt, system=_system()))
