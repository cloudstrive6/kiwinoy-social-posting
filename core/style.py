"""Human-voice guidance + a mechanical "de-AI" cleanup pass.

HUMAN_VOICE is injected into every writing prompt. `sanitize()` is a safety net
that strips the tells a prompt might still let through (em/en dashes especially),
so nothing that screams "an AI wrote this" reaches the feed.
"""
from __future__ import annotations

import re

# Injected into caption + threads prompts.
HUMAN_VOICE = """WRITE LIKE A REAL PERSON, NOT AI. Non-negotiable rules:
- NEVER use em-dashes (—) or en-dashes (–). Use commas, periods, or parentheses instead.
- No "it's not just X, it's Y" and no "not only... but also" constructions.
- Ban these words/phrases: delve, dive in, dive into, unleash, elevate, game-changer,
  tapestry, testament, navigate, realm, in the world of, when it comes to, buckle up,
  embark, unlock the power, take it to the next level, look no further, that's right.
- Don't open with a rhetorical "Ever wondered..." cliche.
- No semicolons. Keep punctuation casual and simple.
- Vary sentence length. Use contractions. A short fragment is fine.
- Don't force rule-of-three lists or perfectly balanced sentences.
- Emojis only where they feel natural, not in a tidy formula.
- NEVER use the #KiwinoyGamer hashtag, or any channel-branded #Kiwinoy... hashtag.
- Sound like a hyped gamer / sports fan typing fast, not a brand bot."""

# Phrases we'll quietly strip if the model slips (kept short to avoid mangling).
_BANNED_OPENERS = (
    "let's be real, ",
    "let's be honest, ",
    "let's be real. ",
)


def sanitize(text: str) -> str:
    """Remove the most common AI giveaways, especially em/en dashes."""
    if not text:
        return text

    # 1) Kill em/en dashes used as punctuation. " word — word " -> " word, word ".
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    # Stray non-breaking / figure dashes -> normal hyphen.
    text = text.replace("‑", "-").replace("‐", "-")

    # 2) Tidy artifacts the replacement can create.
    text = re.sub(r",\s*,", ", ", text)      # double commas
    text = re.sub(r"\s+,", ",", text)         # space before comma
    text = re.sub(r",\s*([.!?])", r"\1", text)  # ", ." -> "."
    text = re.sub(r"[ \t]{2,}", " ", text)     # collapse runs of spaces

    # 2b) Strip any channel-branded hashtag the model may have added on its own
    #     (e.g. #KiwinoyGamer). We never want these on a post.
    text = re.sub(r"(?i)#\s*kiwinoy\w*", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)

    # 3) Drop a couple of formulaic openers if they lead the text.
    low = text.lstrip()
    for opener in _BANNED_OPENERS:
        if low.lower().startswith(opener):
            text = low[len(opener):]
            text = text[:1].upper() + text[1:]
            break

    # 4) Normalize excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text
