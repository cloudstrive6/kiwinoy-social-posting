"""Reel Script agent — writes the on-screen caption beats for a reel.

Applies the same storytelling spine as the captions (hook -> build -> payoff ->
CTA) but as SHORT on-screen text cards that appear over the video. Each beat is
a few words so it reads instantly on a phone. No em-dashes, no #Kiwinoy tags.
"""
from __future__ import annotations

from typing import Any

from core import writer as ai
from core.config import CONFIG
from core.style import HUMAN_VOICE, TAGLISH_VOICE, sanitize


def _system(taglish: bool = False) -> str:
    b = CONFIG.brand
    lang = "natural Taglish (Filipino + English)" if taglish else b["language"]
    base = (
        f"You are the short-video script lead for {b['name']} ({b['handle']}). "
        f"Write in {lang}. You write punchy on-screen caption beats for "
        f"12-15 second vertical reels that hook viewers in the first second and "
        f"keep them watching. Brand voice: {b['voice']}\n\n{HUMAN_VOICE}"
    )
    return base + ("\n\n" + TAGLISH_VOICE if taglish else "")


def run(
    brief: dict[str, Any],
    n_beats: int | None = None,
    taglish: bool = False,
    reel_format: str | None = None,
) -> list[dict[str, str]]:
    """Return a list of on-screen beats: [{kind, text}], story-ordered.

    taglish -> write the beats in Manila Gen-Z Taglish (PH-targeted reels).
    reel_format -> an optional recurring series template to shape the beats
    (e.g. "Sino panalo prediction", "hero spotlight").
    """
    n = int(n_beats or CONFIG.reels.get("beats", 4))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))
    fmt_line = (
        f"\nSERIES FORMAT (shape the beats around this recurring template): {reel_format}\n"
        if reel_format else ""
    )
    loop_line = (
        "- LOOP: make the final beat connect back to the hook so the reel loops "
        "cleanly (replays boost reach)."
    )

    prompt = f"""Write the on-screen text beats for ONE {brief['category']} reel about:

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (accurate only, never invent more):
{facts}
{fmt_line}
Make exactly {n} beats that flow as a mini story and keep viewers hooked:
- Beat 1 = HOOK: a scroll-stopping line that creates instant curiosity or stakes.
- Middle beats = the punchiest facts / the payoff, one idea each.
- Final beat = CTA: a quick question or "follow for more" style nudge.

Rules for EVERY beat:
- Ultra short: 2 to 6 words, readable in under a second. No full sentences.
- Punchy, spoken-aloud energy. Title-style, not paragraphs.
- No hashtags. No emojis inside the beat text. No em-dashes.
{loop_line}

Return ONLY this JSON (no prose, no code fences):
{{"beats": [{{"kind": "hook|fact|payoff|cta", "text": "..."}}]}}"""

    raw = ai.write(prompt, system=_system(taglish))
    beats: list[dict[str, str]] = []
    try:
        from core.openai_client import extract_json

        data = extract_json(raw)
        for b in data.get("beats", [])[:n]:
            text = sanitize(str(b.get("text", ""))).strip()
            # belt + suspenders: strip stray hashtags/emojis-only beats
            text = text.replace("#", "").strip()
            if text:
                beats.append({"kind": str(b.get("kind", "fact")), "text": text})
    except Exception:
        # Fallback: split lines into beats.
        for line in sanitize(raw).splitlines():
            line = line.strip("-* #").strip()
            if line:
                beats.append({"kind": "fact", "text": line})
            if len(beats) >= n:
                break

    # Guarantee at least a hook + cta so the reel is never empty.
    if not beats:
        beats = [
            {"kind": "hook", "text": sanitize(brief.get("headline_idea") or brief.get("title", "Big update"))},
            {"kind": "cta", "text": "Follow for more"},
        ]
    return beats


# Spoken Taglish words per second (commentary VO pacing). Used to size scripts.
_WORDS_PER_SEC = 2.2


def run_commentary(
    brief: dict[str, Any],
    target_seconds: float,
    taglish: bool = True,
) -> str:
    """Write the full spoken Taglish VOICEOVER for a commentary reel.

    Sized to ~target_seconds of speech and structured as a hook intro -> the
    talking points -> a follow CTA. Returns one plain-text script (no labels);
    subtitle timing is derived later from the TTS timestamps.
    """
    target_words = int(max(60, min(target_seconds * _WORDS_PER_SEC, 2400)))
    points = "\n".join(f"- {p}" for p in brief.get("key_facts", []))
    fmt = brief.get("format", "")

    prompt = f"""Write the SPOKEN voiceover script for ONE commentary reel about:

TITLE: {brief.get('title')}
GAME: {brief.get('subject')}
PROMISE: {brief.get('angle')}
FORMAT: {fmt}
TALKING POINTS (cover these, in a punchy order; stay accurate, never invent
spoilers or fake facts):
{points}

This is read aloud by a hype young Filipino narrator over gameplay b-roll.
- Natural Taglish, conversational, like talking to your barkada. NOT formal.
- FUNNY + ENTERTAINING + RELATABLE: this is the whole point. Land real jokes,
  playful exaggeration, and relatable Pinoy-gamer moments (the rage quits, the
  "load muna", the flex sa barkada, "grabe ang ganda", "di ko ma-gets noon").
  Make them laugh or go "totoo 'yan" while they watch. Light kausap-barkada
  banter, not a dry tutorial.
- Open with a 1-2 sentence HOOK that makes them stay, then deliver each point
  with energy + a little humor, then end on a quick "follow for more" style CTA.
- Keep it positive and hype - tease/joke with affection, never bash or complain
  about the game.
- Aim for about {target_words} words total (this fills ~{int(target_seconds)}s).
- Plain spoken sentences only. No hashtags, no emojis, no section labels, no
  stage directions, no quotation marks. Just the words to be read aloud.

Return ONLY the spoken script as plain text."""

    raw = ai.write(prompt, system=_system(taglish))
    text = sanitize(raw).strip().strip('"').strip()
    # Safety cap so a runaway generation never balloons TTS cost.
    words = text.split()
    hard_cap = int(target_words * 1.5)
    if len(words) > hard_cap:
        text = " ".join(words[:hard_cap]).rstrip(",.;: ") + "."
    return text
