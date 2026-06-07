"""Threads Research agent — digs up a fresh, real, trending SPORTS story.

PRIMARY: the vendored "last30days" skill (real Reddit/Polymarket/HN engagement),
synthesized by Claude (your subscription token).
FALLBACK: Claude web search if last30days returns nothing or errors.

Returns a brief for the Threads writer.
"""
from __future__ import annotations

import random
from typing import Any

from core import claude_code, last30days
from core.config import CONFIG
from core.openai_client import extract_json
from core.style import TOPIC_GUARDRAIL, sanitize


def _clean(brief: dict[str, Any]) -> dict[str, Any]:
    brief["category"] = "sports"
    brief.setdefault("key_facts", [])
    for k in ("title", "hook_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief


def _synthesize(query: str, stories: list[dict[str, Any]]) -> dict[str, Any]:
    angles = CONFIG.threads_posts.get("angles", [])
    prompt = f"""These are the most-discussed, highest-engagement sports stories from
the last 30 days about "{query}" (real community threads, ranked by engagement):

{last30days.format_stories(stories)}

Each story shows its date. STRONGLY prefer the MOST RECENT one (ideally the last
few days) — freshness beats raw engagement. Pick what is breaking or newest right
now for a Threads post, then choose an angle that fits:
{chr(10).join(f'- {a}' for a in angles)}

{TOPIC_GUARDRAIL}

Return ONLY this JSON (no prose, no code fences):
{{
  "title": "short human title",
  "subject": "league / teams / players involved",
  "angle": "which angle and why it's hot right now",
  "key_facts": ["3-5 concrete, accurate facts pulled from the stories above"],
  "hook_idea": "a one-line scroll-stopping hook angle"
}}"""
    raw = claude_code.run(prompt, web=False)
    return extract_json(raw)


def _last30days_research(categories: list[str]) -> dict[str, Any] | None:
    pool: list[dict] = []
    for cat in categories:
        pool += CONFIG.research.get("targets", {}).get(cat, [])
    if not (last30days.available() and pool):
        return None
    target = random.choice(pool)
    stories = last30days.gather(target["query"], target.get("subreddits"))
    if not stories:
        return None
    return _synthesize(target["query"], stories)


def _websearch_research() -> dict[str, Any]:
    t = CONFIG.threads_posts
    leagues = t.get("leagues", [])
    angles = t.get("angles", [])
    prompt = f"""You are the sports research lead for KiwinoyGamer. Use web search to
find the SINGLE most engaging, current, REAL sports story to post on Threads now,
from:
{chr(10).join(f'- {x}' for x in leagues)}

Angle options:
{chr(10).join(f'- {a}' for a in angles)}

{TOPIC_GUARDRAIL}

Verify with web search; never invent scores or news. Return ONLY this JSON:
{{
  "title": "...",
  "subject": "league / teams / players",
  "angle": "which angle and why it is hot now",
  "key_facts": ["3-5 concrete, accurate facts/stats/scores/dates"],
  "hook_idea": "a one-line scroll-stopping hook angle"
}}"""
    raw = claude_code.run(prompt, web=True)
    try:
        return extract_json(raw)
    except Exception:
        return {
            "title": "Trending in sports", "subject": "sports", "angle": "",
            "key_facts": [raw[:400]], "hook_idea": "",
        }


def run(categories: list[str] | None = None) -> dict[str, Any]:
    """Find a trending brief. categories default to sports; pass
    ["sports","esports"] for prediction posts to include esports."""
    categories = categories or ["sports"]
    if CONFIG.research.get("engine", "last30days") == "last30days":
        try:
            brief = _last30days_research(categories)
            if brief:
                return _clean(brief)
        except Exception as e:
            print(f"[threads_research] last30days failed ({e}); web-search fallback",
                  flush=True)
    return _clean(_websearch_research())
