"""Threads Research agent — digs up a fresh, real, trending SPORTS/ESPORTS story.

Uses Claude (your subscription / CLAUDE_CODE_OAUTH_TOKEN) with web search, so it
pulls genuinely current results, news, and player/team analysis. Returns a brief
for the Threads writer.
"""
from __future__ import annotations

from typing import Any

from core import claude_code
from core.config import CONFIG
from core.dedup import avoid_block
from core.openai_client import extract_json
from core.style import TOPIC_GUARDRAIL, sanitize

_RECENCY = (
    "RECENCY + ACCURACY (critical): confirm via web search that the news is CURRENT "
    "and has NOT already been decided, announced, or superseded. Prefer the very "
    "latest (today or the last few days). Never post speculation about something "
    "that has already been settled. Verify scores, names, and dates."
)


def _clean(brief: dict[str, Any]) -> dict[str, Any]:
    brief["category"] = "sports"
    brief.setdefault("key_facts", [])
    for k in ("title", "hook_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief


def run(categories: list[str] | None = None) -> dict[str, Any]:
    """Find a trending brief. categories default to sports; pass
    ["sports","esports"] for prediction posts to include esports."""
    categories = categories or ["sports"]
    t = CONFIG.threads_posts
    universe: list[str] = list(t.get("leagues", []))
    if "esports" in categories:
        universe += list(t.get("esports", []))
    angles = t.get("angles", [])

    prompt = f"""You are the sports research lead for KiwinoyGamer. Use web search to
find the SINGLE most engaging, current, REAL story to post on Threads right now,
from:
{chr(10).join(f'- {x}' for x in universe)}

Angle options:
{chr(10).join(f'- {a}' for a in angles)}

{_RECENCY}

{TOPIC_GUARDRAIL}

{avoid_block()}

Return ONLY this JSON (no prose, no code fences):
{{
  "title": "short human title",
  "subject": "league / teams / players involved",
  "angle": "which angle and why it is hot right now",
  "key_facts": ["3-5 concrete, accurate, current facts/stats/scores/dates"],
  "hook_idea": "a one-line scroll-stopping hook angle"
}}"""

    raw = claude_code.run(prompt, web=True)
    try:
        brief = extract_json(raw)
    except Exception:
        brief = {
            "title": "Trending in sports", "subject": "sports", "angle": "",
            "key_facts": [raw[:400]], "hook_idea": "",
        }
    return _clean(brief)
