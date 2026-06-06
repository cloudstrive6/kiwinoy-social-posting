"""Agent 1 — Research & Trending.

Given a category ("gacha" or "sports"), searches the live web for what's
trending RIGHT NOW across the configured games/leagues and angles, then returns
a tight creative brief the rest of the team builds on.
"""
from __future__ import annotations

from typing import Any

from core import openai_client as ai
from core.config import CONFIG
from core.style import sanitize

_SYSTEM = (
    "You are the Research & Trending lead for KiwinoyGamer, a gaming social "
    "channel. You find the single most engaging, timely, real topic to post "
    "about and brief the content team. You only report things that are actually "
    "current — use web search. Never invent scores, patch numbers, or news."
)


def _brief_prompt(category: str) -> str:
    t = CONFIG.topics[category]
    universe = t["games"] if category == "gacha" else t["leagues"]
    angles = t["angles"]
    return f"""Today you are sourcing ONE {category.upper()} topic for KiwinoyGamer.

Search the web for the most trending / newsworthy item RIGHT NOW from this set:
{chr(10).join(f"  - {x}" for x in universe)}

Pick an angle that fits the moment from:
{chr(10).join(f"  - {a}" for a in angles)}

Choose the topic with the most current buzz (a fresh banner, a tier shift, a
big fixture, an injury, a result, a leak). It must be real and timely.

Return ONLY a JSON object with exactly these keys:
{{
  "category": "{category}",
  "title": "short human title of the topic",
  "subject": "the specific game OR league/teams/players involved",
  "angle": "which angle you chose and why it's hot today",
  "key_facts": ["3-5 concrete, accurate facts/stats/dates that anchor the post"],
  "hook_idea": "a one-line scroll-stopping hook angle for the caption",
  "headline_idea": "a punchy 2-5 word on-image headline idea",
  "sources": ["1-3 source URLs you used"]
}}
Output the JSON only. No prose, no code fences."""


def run(category: str) -> dict[str, Any]:
    """Return a creative brief dict for the given category."""
    raw = ai.research(_brief_prompt(category), system=_SYSTEM)
    try:
        brief = ai.extract_json(raw)
    except Exception:
        # If parsing fails, wrap the raw text so the pipeline still proceeds.
        brief = {
            "category": category,
            "title": f"Trending in {category}",
            "subject": category,
            "angle": "",
            "key_facts": [raw[:500]],
            "hook_idea": "",
            "headline_idea": "",
            "sources": [],
        }
    brief["category"] = category
    # Clean the fields that flow into copy / the on-image headline.
    for k in ("title", "hook_idea", "headline_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief
