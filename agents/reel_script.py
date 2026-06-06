"""Reel Script agent — writes the on-screen caption beats for a reel.

Applies the same storytelling spine as the captions (hook -> build -> payoff ->
CTA) but as SHORT on-screen text cards that appear over the video. Each beat is
a few words so it reads instantly on a phone. No em-dashes, no #Kiwinoy tags.
"""
from __future__ import annotations

from typing import Any

from core import writer as ai
from core.config import CONFIG
from core.style import HUMAN_VOICE, sanitize


def _system() -> str:
    b = CONFIG.brand
    return (
        f"You are the short-video script lead for {b['name']} ({b['handle']}). "
        f"Write in {b['language']}. You write punchy on-screen caption beats for "
        f"12-15 second vertical reels that hook viewers in the first second and "
        f"keep them watching. Brand voice: {b['voice']}\n\n{HUMAN_VOICE}"
    )


def run(brief: dict[str, Any], n_beats: int | None = None) -> list[dict[str, str]]:
    """Return a list of on-screen beats: [{kind, text}], story-ordered."""
    n = int(n_beats or CONFIG.reels.get("beats", 4))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))

    prompt = f"""Write the on-screen text beats for ONE {brief['category']} reel about:

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (accurate only, never invent more):
{facts}

Make exactly {n} beats that flow as a mini story and keep viewers hooked:
- Beat 1 = HOOK: a scroll-stopping line that creates instant curiosity or stakes.
- Middle beats = the punchiest facts / the payoff, one idea each.
- Final beat = CTA: a quick question or "follow for more" style nudge.

Rules for EVERY beat:
- Ultra short: 2 to 6 words, readable in under a second. No full sentences.
- Punchy, spoken-aloud energy. Title-style, not paragraphs.
- No hashtags. No emojis inside the beat text. No em-dashes.

Return ONLY this JSON (no prose, no code fences):
{{"beats": [{{"kind": "hook|fact|payoff|cta", "text": "..."}}]}}"""

    raw = ai.write(prompt, system=_system())
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
