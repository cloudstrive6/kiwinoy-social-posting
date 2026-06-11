"""Narration agent — writes the spoken Taglish voiceover line for a reel.

Produces ONE tight, hype, spoken-aloud Taglish script (a couple of sentences,
sized to the reel length) that an ElevenLabs voice reads over the video. This is
the spoken track; the on-screen beats (reel_script) are the visual captions.
Kept short on purpose so the VO fits the 12-15s runtime.
"""
from __future__ import annotations

from typing import Any

from core import writer as ai
from core.config import CONFIG
from core.style import HUMAN_VOICE, TAGLISH_VOICE, sanitize


def _system() -> str:
    b = CONFIG.brand
    return (
        f"You are the voiceover scriptwriter for {b['name']} ({b['handle']}). "
        f"You write ONE short, hype, spoken-aloud Taglish line for a vertical reel "
        f"that a young Filipino voice will narrate. Brand voice: {b['voice']}\n\n"
        f"{HUMAN_VOICE}\n\n{TAGLISH_VOICE}"
    )


def write_script(brief: dict[str, Any], caption: str = "") -> str:
    """Return a short spoken Taglish VO line for the reel (plain text, no labels)."""
    max_words = int(CONFIG.reels.get("narration", {}).get("max_words", 34))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", [])[:4])

    prompt = f"""Write the SPOKEN voiceover for ONE short {brief['category']} reel.

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
KEY FACTS (accurate only, never invent):
{facts}

This is SPOKEN out loud by a hype young Filipino narrator over the video.
- Natural Taglish, conversational, like talking to your barkada. NOT formal.
- Open with a 1-second hook, deliver the point, end on a quick question/CTA.
- STRICTLY {max_words} words or fewer (it must fit a 12-15 second reel).
- Plain spoken sentences only. No hashtags, no emojis, no stage directions,
  no quotation marks, no labels. Just the words to be read aloud.

Return ONLY the spoken line(s) as plain text."""

    raw = ai.write(prompt, system=_system())
    text = sanitize(raw).strip().strip('"').strip()
    # Hard cap on length as a safety net so TTS never runs long.
    words = text.split()
    if len(words) > max_words + 6:
        text = " ".join(words[: max_words + 6]).rstrip(",.;: ") + "."
    return text
