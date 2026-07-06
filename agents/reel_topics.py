"""Reel Topic agent — invents relatable topics for footage-driven reels.

Two kinds of reel use this instead of the news-research path:
  - gameplay : a standalone gameplay clip with one scroll-stopping HOOK caption
               (Gameranx style, e.g. "Whoever scripted this deserves a raise").
  - commentary: a "Top N" / "X things you must do" / retrospective / meta take
               that a Taglish voiceover narrates over gameplay b-roll.

Topics are GROUNDED IN OUR FOOTAGE: the agent may only pick a game we actually
have clips for (passed in as `games`). Topics are evergreen / experiential
(moments, tips, rankings, character takes) rather than breaking news, so they
need no live research and stay accurate to the footage we can show.
"""
from __future__ import annotations

import random
from typing import Any

from core import writer as ai
from core.config import CONFIG
from core.openai_client import extract_json
from core.style import HUMAN_VOICE, TAGLISH_VOICE, sanitize

# game folder key -> esports (real competitive title) vs general game.
_ESPORTS_KEYS = {"mlbb", "dota2", "cs2", "lol"}


def _game_names() -> dict[str, str]:
    return CONFIG.reels.get("game_names", {}) or {}


def _display(key: str) -> str:
    return _game_names().get(key, key.replace("_", " ").title())


def _category_for(key: str) -> str:
    return "esports" if key in _ESPORTS_KEYS else "gacha"


def _system(taglish: bool) -> str:
    b = CONFIG.brand
    base = (
        f"You are the short-video ideas lead for {b['name']} ({b['handle']}), a "
        f"gaming channel for young Filipino players. Brand voice: {b['voice']}\n\n"
        f"{HUMAN_VOICE}"
    )
    return base + ("\n\n" + TAGLISH_VOICE if taglish else "")


def _formats() -> list[str]:
    return CONFIG.reels.get("commentary", {}).get("formats", []) or [
        "Top N ranking (rank moments / heroes / bosses, count down to #1)",
        "X Things You Must Do (practical tips a new player needs)",
        "Why this game / character hits different (a heartfelt or hyped take)",
        "Underrated moments most players miss",
        "Beginner mistakes to avoid",
    ]


def run(
    kind: str,
    games: dict[str, int],
    length: str = "short",
    taglish: bool = True,
) -> dict[str, Any]:
    """Return a brief-like dict for a footage reel.

    kind   -> 'gameplay' or 'commentary'.
    games  -> {game_key: clip_count}; the agent may only choose from these.
    length -> 'short' or 'long' (commentary only; long needs more footage).
    """
    if not games:
        return {}
    # Double down on preferred games (e.g. Spider-Man) when they have footage.
    prefer = CONFIG.preferred_footage_games()   # honors a time-boxed prefer_override
    preferred = {k: v for k, v in games.items() if k in prefer}
    if preferred:
        games = preferred
    # Long-form needs enough distinct clips to fill the runtime; bias the choice.
    min_clips = int(CONFIG.reels.get("commentary", {}).get("long_min_clips", 12))
    eligible = games
    if kind == "commentary" and length == "long":
        big = {k: v for k, v in games.items() if v >= min_clips}
        eligible = big or games
    game_key = random.choice(list(eligible.keys()))
    name = _display(game_key)
    category = _category_for(game_key)

    if kind == "gameplay":
        prompt = f"""Write ONE scroll-stopping HOOK caption for a gameplay clip from {name}.

This caption sits in a bar at the TOP of a vertical gameplay video. The viewer
then just watches the raw gameplay. The caption alone must stop the scroll.

GREAT hooks are relatable, funny, or jaw-dropping reactions to what's happening
on screen, like:
- "Whoever scripted this deserves a raise"
- "When the devs anticipate your IQ"
- "POV: di mo alam na ganito kaganda 'to"
- "Bakit walang nag-uusap about this?"

Rules:
- ONE line, 4 to 9 words. Punchy. No hashtags, no emojis, no quotes.
- {('Natural Taglish (Manila gamer talk) or punchy English.' if taglish else 'Write it in ENGLISH only.')}
- It must make sense over generic {name} gameplay (do not name a specific
  scripted moment we may not have footage of).

Return ONLY this JSON:
{{"hook": "the caption", "subject": "{name}",
  "angle": "what feeling/idea the hook plays on"}}"""
        raw = ai.write(prompt, system=_system(taglish))
        try:
            d = extract_json(raw)
            hook = sanitize(str(d.get("hook", ""))).strip().strip('"')
        except Exception:
            hook = ""
        if not hook:
            hook = "Wait for it" if not taglish else "Tignan mo 'tong clip na 'to"
        return {
            "kind": "gameplay", "category": category, "game": game_key,
            "title": f"{name} gameplay", "hook": hook, "subject": name,
            "angle": "standalone gameplay hook", "key_facts": [],
        }

    # commentary
    fmt = random.choice(_formats())
    prompt = f"""Pitch ONE {('long-form' if length == 'long' else 'short')} COMMENTARY reel about {name}.

A Taglish voiceover will narrate it over {name} gameplay b-roll. Choose a topic
in roughly this format: {fmt}

Rules:
- The topic must work with GENERIC {name} gameplay footage (no need for one exact
  scripted scene). Evergreen / experiential, not breaking news.
- Title: punchy, specific, scroll-stopping. If it is a ranking, include the
  number (e.g. "Top 5 ...").
- Give 4 to 7 accurate, non-spoilery talking-point bullets the VO can expand.

Return ONLY this JSON:
{{"title": "the reel title",
  "subject": "{name}",
  "angle": "the core promise to the viewer in one sentence",
  "points": ["talking point", "talking point", "..."]}}"""
    raw = ai.write(prompt, system=_system(taglish))
    try:
        d = extract_json(raw)
        title = sanitize(str(d.get("title", ""))).strip().strip('"')
        angle = sanitize(str(d.get("angle", ""))).strip()
        points = [sanitize(str(p)).strip() for p in (d.get("points") or []) if str(p).strip()]
    except Exception:
        title, angle, points = "", "", []
    if not title:
        title = f"{name}: things every player should know"
    return {
        "kind": "commentary", "category": category, "game": game_key,
        "title": title, "subject": name, "angle": angle or title,
        "format": fmt, "key_facts": points, "length": length,
    }
