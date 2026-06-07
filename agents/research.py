"""Agent 1 — Research & Trending.

PRIMARY engine: the vendored "last30days" skill — pulls the freshest, highest-
engagement community stories (Reddit, Hacker News, Polymarket, GitHub, YouTube)
for the category, then an LLM synthesizes them into a creative brief.

FALLBACK: if last30days is unavailable or returns nothing, fall back to OpenAI
web-search research so the pipeline never stalls.

Returns a brief dict: category, title, subject, angle, key_facts, hook_idea,
headline_idea, sources.
"""
from __future__ import annotations

import random
from typing import Any

from core import last30days
from core import openai_client as ai
from core.config import CONFIG
from core.style import TOPIC_GUARDRAIL, sanitize

_SYSTEM = (
    "You are the Research & Trending lead for KiwinoyGamer, a gaming social "
    "channel. You find the single most engaging, timely, real topic to post "
    "about and brief the content team. Never invent scores, patch numbers, or news."
)


def _clean(brief: dict[str, Any], category: str) -> dict[str, Any]:
    brief["category"] = category
    brief.setdefault("key_facts", [])
    brief.setdefault("sources", [])
    for k in ("title", "hook_idea", "headline_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief


# --- PRIMARY: last30days + LLM synthesis ----------------------------------

def _synthesize(category: str, query: str, stories: list[dict[str, Any]]) -> dict[str, Any]:
    t = CONFIG.topics[category]
    angles = t["angles"]
    prompt = f"""These are the most-discussed, highest-engagement {category} stories
from the last 30 days about "{query}" (real community threads, ranked by engagement):

{last30days.format_stories(stories)}

Pick the SINGLE best story to post about right now (freshest + most buzz). Choose
an angle that fits, from:
{chr(10).join(f"  - {a}" for a in angles)}

{TOPIC_GUARDRAIL}

Return ONLY a JSON object with exactly these keys:
{{
  "category": "{category}",
  "title": "short human title of the chosen story",
  "subject": "the specific game/league/teams/players involved",
  "angle": "which angle and why it's hot right now",
  "key_facts": ["3-5 concrete, accurate facts pulled from the stories above"],
  "hook_idea": "a one-line scroll-stopping hook angle",
  "headline_idea": "a punchy 2-5 word on-image headline idea",
  "sources": ["1-3 of the source URLs above"]
}}
Output the JSON only. No prose, no code fences."""
    raw = ai.write(prompt, system=_SYSTEM)
    return ai.extract_json(raw)


def _last30days_research(category: str) -> dict[str, Any] | None:
    targets = CONFIG.research.get("targets", {}).get(category, [])
    if not (last30days.available() and targets):
        return None
    target = random.choice(targets)
    stories = last30days.gather(target["query"], target.get("subreddits"))
    if not stories:
        return None
    return _synthesize(category, target["query"], stories)


# --- FALLBACK: OpenAI web search ------------------------------------------

def _websearch_prompt(category: str) -> str:
    t = CONFIG.topics[category]
    universe = t["games"] if category == "gacha" else t["leagues"]
    angles = t["angles"]
    return f"""Today you are sourcing ONE {category.upper()} topic for KiwinoyGamer.

Search the web for the most trending / newsworthy item RIGHT NOW from:
{chr(10).join(f"  - {x}" for x in universe)}

Pick an angle that fits from:
{chr(10).join(f"  - {a}" for a in angles)}

{TOPIC_GUARDRAIL}

It must be real and timely. Return ONLY a JSON object with these keys:
{{
  "category": "{category}",
  "title": "short human title",
  "subject": "the specific game OR league/teams/players",
  "angle": "which angle and why it's hot today",
  "key_facts": ["3-5 concrete, accurate facts/stats/dates"],
  "hook_idea": "a one-line scroll-stopping hook angle",
  "headline_idea": "a punchy 2-5 word on-image headline idea",
  "sources": ["1-3 source URLs you used"]
}}
Output the JSON only."""


def _websearch_research(category: str) -> dict[str, Any]:
    raw = ai.research(_websearch_prompt(category), system=_SYSTEM)
    try:
        return ai.extract_json(raw)
    except Exception:
        return {
            "category": category,
            "title": f"Trending in {category}",
            "subject": category,
            "angle": "",
            "key_facts": [raw[:500]],
            "hook_idea": "",
            "headline_idea": "",
            "sources": [],
        }


def run(category: str) -> dict[str, Any]:
    """Return a creative brief dict for the given category."""
    if CONFIG.research.get("engine", "last30days") == "last30days":
        try:
            brief = _last30days_research(category)
            if brief:
                return _clean(brief, category)
        except Exception as e:
            print(f"[research] last30days failed ({e}); using web-search fallback",
                  flush=True)
    return _clean(_websearch_research(category), category)
