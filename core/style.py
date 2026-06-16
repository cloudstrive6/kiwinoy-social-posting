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

# Injected when a piece targets the young Philippine audience (reels). Aims for
# natural Manila Gen-Z gaming Taglish, NOT textbook Tagalog or a translated feel.
TAGLISH_VOICE = """WRITE IN NATURAL TAGLISH (Filipino + English code-switch), the way
young Pinoy gamers actually talk online, NOT formal/deep Tagalog and NOT a literal
translation of English.
- Mix Tagalog and English mid-sentence the natural way (e.g. "Grabe yung comeback,
  one more round and tapos na sila"). English carries most gaming/esports terms.
- Casual Manila register: use particles like na, lang, talaga, kasi, yung, pa, eh,
  diba. Light, hype, conversational. Sound like a barkada groupchat, not a textbook.
- Common gamer Taglish is welcome when it fits, never forced: solid, sana all, GG,
  carry, sakto, panalo, laro, push, lakas, walang kalaban-laban. Don't stack slang.
- AVOID: stiff/deep Tagalog words no one says casually, over-translated English,
  and anything that reads like a Tagalog phrasebook or news anchor.
- Keep it readable for a wide PH audience. When unsure, lean to how a 20-year-old
  Filipino gamer would actually caption it."""


# Phrases we'll quietly strip if the model slips (kept short to avoid mangling).
_BANNED_OPENERS = (
    "let's be real, ",
    "let's be honest, ",
    "let's be real. ",
)


# Injected into writer prompts (alongside the current date) so any time always
# carries an explicit date and resolved relative-day wording.
DATETIME_RULE = (
    "DATES WITH TIMES: whenever you mention a specific time (kickoff, tip-off, "
    "event start, banner drop, etc.), ALWAYS put the explicit calendar DATE and the "
    "timezone right next to it, e.g. 'Mon, Jun 9 at 8:30 PM ET'. Never write a bare "
    "'tomorrow 8:30 ET' or 'tonight at 8' with no date. Resolve "
    "'today'/'tonight'/'tomorrow' to the real date using the current date given above."
)


# Injected into research-synthesis prompts. Keeps the autonomous hype voice away
# from tragedy and unverified rumor.
TOPIC_GUARDRAIL = """TOPIC SAFETY (important): KiwinoyGamer is an upbeat hype gaming
and sports channel. Do NOT pick somber, tragic, or sensitive stories: deaths,
serious injuries or illness, tragedies, violence, crime, legal cases, politics, or
heavy controversy. If the highest-engagement story is sensitive, SKIP it and choose
a different, upbeat story instead: results, standout performances, big matchups,
predictions, positive signings/transfers, banners, tier lists, records, hype
moments. Only use widely-reported, well-established facts. Never present an
unverified rumor or leak as confirmed fact."""


POSITIVE_TONE = """TONE - HYPE/CURIOUS, NOT COMPLAINTS (important): KiwinoyGamer is an
upbeat fan channel. Do NOT write complaint or outrage-bait posts about a game. No
whiny "what did they do to this game / to this character", no "they ruined X", no
"this is a disaster", no manufactured controversy or dunking on the developers'
choices. A spicy take is fine ONLY when it is a confident, FUN opinion or a genuine
fan debate - never a negative grievance. Frame a new feature, change, or design
choice with excitement or honest curiosity (or balanced analysis), celebrating the
game, not mocking it. When in doubt, hype it up or ask a fun question - don't
complain."""


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
