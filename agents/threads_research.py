"""Threads Research agent — digs up a fresh, real, trending GAMES story.

Uses Claude (your subscription / CLAUDE_CODE_OAUTH_TOKEN) with web search, so it
pulls genuinely current game news, releases, updates, and reveals. Returns a brief
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
    brief["category"] = "games"
    brief.setdefault("key_facts", [])
    for k in ("title", "hook_idea", "angle"):
        if isinstance(brief.get(k), str):
            brief[k] = sanitize(brief[k])
    return brief


_FOCUS = """TRENDING-GAME FOCUS (important): KiwinoyGamer grows reach by RIDING the
single hottest game / gaming moment, not hopping between random games.
Step 1 - Use web search to identify THE single hottest game or gaming moment
RIGHT NOW: the marquee thing drawing the most attention this period (a big new
release, a major update/patch/DLC, a viral gaming moment, a showcase like a State
of Play or the Game Awards, a record-breaking launch). COMMIT to it. Do NOT flip
between games day to day. If nothing is clearly marquee, pick the game with the
most momentum now, or the one building toward the next big drop.
Step 2 - Within THAT game, find the most engaging, current, REAL story, using a
DIFFERENT angle than the recent posts listed below. The goal is many fresh angles
on the SAME hot game (a feature, a boss, a build, a stat, a reveal, a comparison).
The avoid-list below exists to stop you repeating the SAME angle. Do NOT switch
games to satisfy it - stay on the hottest game and find a fresh angle within it."""


def run(categories: list[str] | None = None) -> dict[str, Any]:
    """Find a trending GAMES brief. categories default to ["games"]; pass
    ["games","verdict"] for the daily verdict/breakdown post to widen the scope
    with the extra game franchises in config."""
    categories = categories or ["games"]
    t = CONFIG.threads_posts
    universe: list[str] = list(t.get("leagues", []))
    is_verdict = "verdict" in categories or "esports" in categories
    if is_verdict:
        universe += list(t.get("esports", []))  # extra game franchises
    angles = t.get("angles", [])
    # Trending-game focus applies to the regular update posts. The daily
    # verdict/breakdown post keeps the broader scope unchanged.
    focus = (
        _FOCUS + "\n\n"
        if (t.get("trending_focus", False) and not is_verdict)
        else ""
    )

    prompt = f"""You are the games research lead for KiwinoyGamer, a gaming channel
for young Filipino players. Use web search to find the SINGLE most engaging,
current, REAL gaming story to post on Threads right now.

AAA ONLY: cover only big-budget AAA titles (console/PC). Do NOT cover mobile,
gacha, or live-service games. Stay STRICTLY within this universe and follow each
bullet's EXACT scope - cover any entry it lists (games, plus the noted movies and
TV shows, e.g. The Last of Us Season 2 and The Last of Us Part III news), but
nothing outside it. Note: "Final Fantasy VII" means ONLY the FF7 compilation
listed, NOT any other Final Fantasy game.
{chr(10).join(f'- {x}' for x in universe)}

{focus}Surface whatever AAA story is genuinely hottest now within that universe.

Angle options:
{chr(10).join(f'- {a}' for a in angles)}

{_RECENCY}

{TOPIC_GUARDRAIL}

{avoid_block()}

Return ONLY this JSON (no prose, no code fences):
{{
  "title": "short human title",
  "subject": "the game / studio / characters involved",
  "focus_game": "the hot game you are riding (or this story's game)",
  "angle": "which angle and why it is hot right now",
  "key_facts": ["3-5 concrete, accurate, current facts (dates, prices, patch notes)"],
  "hook_idea": "a one-line scroll-stopping hook angle"
}}"""

    raw = claude_code.run(prompt, web=True)
    try:
        brief = extract_json(raw)
    except Exception:
        brief = {
            "title": "Trending in games", "subject": "games", "angle": "",
            "key_facts": [raw[:400]], "hook_idea": "",
        }
    return _clean(brief)
