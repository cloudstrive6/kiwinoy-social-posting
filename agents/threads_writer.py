"""Threads Writer agent — writes the Threads post (text only, <=500 chars).

Storytelling spine (hook -> point -> reply-bait question) with a scroll-stopping
first line. Written by Claude via your subscription (CLAUDE_CODE_OAUTH_TOKEN).
The 500-char cap is enforced: regenerate if over, then trim as a last resort.
"""
from __future__ import annotations

from typing import Any

from core import claude_code
from core.config import CONFIG
from core.style import HUMAN_VOICE, sanitize


def _trim(text: str, limit: int) -> str:
    """Last resort: cut to <= limit, preferring a sentence end, then a word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > limit * 0.6:
            return cut[: idx + 1].strip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:") + "..."


def run(brief: dict[str, Any]) -> str:
    t = CONFIG.threads_posts
    limit = int(t.get("max_chars", 500))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))
    tag = " ".join(t.get("hashtags", [])[:1])

    base = f"""Write ONE Threads post about this sports story.

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (use accurately, never invent more):
{facts}

Rules:
- The FIRST line must be a scroll-stopping hook (a bold take, a wild stat, or a
  sharp question) that makes people stop and read.
- Then a tight mini story: the hook, the point/insight, and a question that
  invites replies. A couple of short lines, conversational hype sports-fan voice.
- HARD LIMIT: {limit} characters or less for the ENTIRE post. Count carefully.
- At most one hashtag, only if it feels natural: {tag}
- Output ONLY the post text. No preamble, no surrounding quotes, no labels.

{HUMAN_VOICE}"""

    text, note = "", ""
    for _ in range(3):
        text = sanitize(claude_code.run(base + note, web=False))
        if text and len(text) <= limit:
            break
        note = (
            f"\n\nYour last version was {len(text)} characters. Rewrite it tighter "
            f"and shorter, strictly under {limit} characters total."
        )
    return _trim(text, limit)
