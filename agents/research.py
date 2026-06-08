"""Agent 1 — Research & Trending.

Searches the live web (OpenAI Responses + web search) for what's trending RIGHT
NOW across the configured games/leagues, then returns a tight creative brief.

Returns: category, title, subject, angle, key_facts, hook_idea, headline_idea,
sources.
"""
from __future__ import annotations

from typing import Any

from core import openai_client as ai
from core.config import CONFIG
from core.style import TOPIC_GUARDRAIL, sanitize

_SYSTEM = (
    "You are the Research & Trending lead for KiwinoyGamer, a gaming social "
    "channel. You find the single most engaging, timely, real topic to post "
    "about and brief the content team. Use web search. Never invent scores, "
    "patch numbers, or news."
)

_RECENCY = (
    "RECENCY + ACCURACY (critical): use web search to confirm the news is CURRENT "
    "and has NOT already been superseded or decided. Prefer the very latest (today "
    "or the last few days). Never post speculation about something that has already "
    "been announced, revealed, or settled. Double-check the freshest source."
)


def _clean(brief: dict[str, Any], category: str) -> dict[str, Any]:
    brief["category"] = category
    brief.setdefault("key_facts", [])
    brief.setdefault("sources", [])
    for k in ("title", "hook_idea", "headline_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief


def _prompt(category: str) -> str:
    t = CONFIG.topics[category]
    universe = t["games"] if category == "gacha" else t["leagues"]
    angles = t["angles"]
    return f"""Today you are sourcing ONE {category.upper()} topic for KiwinoyGamer.

Search the web for the most trending / newsworthy item RIGHT NOW from:
{chr(10).join(f"  - {x}" for x in universe)}

Pick an angle that fits from:
{chr(10).join(f"  - {a}" for a in angles)}

{_RECENCY}

{TOPIC_GUARDRAIL}

Return ONLY a JSON object with these keys:
{{
  "category": "{category}",
  "title": "short human title",
  "subject": "the specific game OR league/teams/players",
  "angle": "which angle and why it's hot today",
  "key_facts": ["3-5 concrete, accurate, current facts/stats/dates"],
  "hook_idea": "a one-line scroll-stopping hook angle",
  "headline_idea": "a punchy 2-5 word on-image headline idea",
  "sources": ["1-3 source URLs you used"]
}}
Output the JSON only. No prose, no code fences."""


def run(category: str) -> dict[str, Any]:
    """Return a creative brief dict for the given category."""
    raw = ai.research(_prompt(category), system=_SYSTEM)
    try:
        brief = ai.extract_json(raw)
    except Exception:
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
    return _clean(brief, category)
