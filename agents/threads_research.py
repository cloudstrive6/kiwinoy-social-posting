"""Threads Research agent — digs up a fresh, real, trending SPORTS story.

Uses Claude (via your subscription / CLAUDE_CODE_OAUTH_TOKEN) with web search,
so it can pull current results, news, and player/team analysis. Returns a tight
brief for the Threads writer.
"""
from __future__ import annotations

from typing import Any

from core import claude_code
from core.config import CONFIG
from core.openai_client import extract_json
from core.style import sanitize


def run() -> dict[str, Any]:
    t = CONFIG.threads_posts
    leagues = t.get("leagues", [])
    angles = t.get("angles", [])

    prompt = f"""You are the sports research lead for KiwinoyGamer, a sports + gaming
social channel. Use web search to find the SINGLE most engaging, current, REAL
sports story to post about on Threads right now, drawn from:
{chr(10).join(f'- {x}' for x in leagues)}

Pick the angle that fits the moment:
{chr(10).join(f'- {a}' for a in angles)}

Prioritise the freshest buzz: a result that just happened, breaking news, a
record, an injury or transfer, or a big upcoming matchup. It must be real and
current. Verify with web search. Never invent scores, stats, or news.

Return ONLY this JSON (no prose, no code fences):
{{
  "title": "short human title of the story",
  "subject": "league / teams / players involved",
  "angle": "which angle you chose and why it is hot right now",
  "key_facts": ["3-5 concrete, accurate facts/stats/scores/dates"],
  "hook_idea": "a one-line scroll-stopping hook angle"
}}"""

    raw = claude_code.run(prompt, web=True)
    try:
        brief = extract_json(raw)
    except Exception:
        brief = {
            "title": "Trending in sports",
            "subject": "sports",
            "angle": "",
            "key_facts": [raw[:400]],
            "hook_idea": "",
        }
    brief["category"] = "sports"
    for k in ("title", "hook_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief
