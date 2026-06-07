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

Pick the SINGLE best, freshest story for a Threads post right now. Choose an angle
that fits:
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


def _last30days_research() -> dict[str, Any] | None:
    targets = CONFIG.research.get("targets", {}).get("sports", [])
    if not (last30days.available() and targets):
        return None
    target = random.choice(targets)
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


def run() -> dict[str, Any]:
    if CONFIG.research.get("engine", "last30days") == "last30days":
        try:
            brief = _last30days_research()
            if brief:
                return _clean(brief)
        except Exception as e:
            print(f"[threads_research] last30days failed ({e}); web-search fallback",
                  flush=True)
    return _clean(_websearch_research())
