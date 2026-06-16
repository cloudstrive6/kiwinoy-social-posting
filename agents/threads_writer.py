"""Threads Writer agent — writes the Threads post (text only, <=500 chars).

Storytelling spine (hook -> point -> reply-bait question) with a scroll-stopping
first line. Written by Claude via your subscription (CLAUDE_CODE_OAUTH_TOKEN).
The 500-char cap is enforced: regenerate if over, then trim as a last resort.
"""
from __future__ import annotations

import random
from typing import Any

from core import claude_code, lore
from core.config import CONFIG
from core.style import DATETIME_RULE, HUMAN_VOICE, POSITIVE_TONE, sanitize
from core.timeref import now_context


def _lore_block(brief: dict[str, Any]) -> str:
    """A lore-accuracy section: the canonical story bible for the brief's game (if
    we have one) plus a hard rule against inventing games/events. Keeps the writer
    honest about a game's actual story instead of guessing (e.g. FF7's Weapons)."""
    key = lore.lore_key_for_text(
        str(brief.get("subject", "")), str(brief.get("focus_game", "")),
        str(brief.get("title", "")),
    )
    brief_lore = lore.lore_for(key)
    rule = (
        "LORE ACCURACY (critical): be an EXPERT on this game's real story and stay "
        "true to its canon. Never invent in-game events, characters, plot, or game "
        "TITLES. Only reference games that actually exist; if a game is unannounced "
        "or untitled, do not invent its contents. If you are not certain a lore "
        "detail is canon, leave it out."
    )
    if brief_lore:
        return f"{rule}\n\nGAME LORE (canon — match this exactly):\n{brief_lore}\n"
    return rule + "\n"


def _trim(text: str, limit: int) -> str:
    """Last resort: cut to <= limit, preferring a sentence end, then a word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > limit * 0.6:
            return cut[: idx + 1].strip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:") + "..."


def run(brief: dict[str, Any]) -> str:
    t = CONFIG.threads_posts
    limit = int(t.get("max_chars", 500))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))
    tag = " ".join(t.get("hashtags", [])[:1])

    base = f"""Write ONE Threads post about this gaming story.

{now_context()}
{DATETIME_RULE}

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (use accurately, never invent more):
{facts}

{_lore_block(brief)}
Rules:
- The FIRST line must be a scroll-stopping hook (a bold take, a wild detail, or a
  sharp question) that makes people stop and read.
- Then a tight mini story: the hook, the point/insight, and a question that
  invites replies. A couple of short lines, conversational hype gamer voice.
- HARD LIMIT: {limit} characters or less for the ENTIRE post. Count carefully.
- At most one hashtag, only if it feels natural: {tag}
- Output ONLY the post text. No preamble, no surrounding quotes, no labels.

{POSITIVE_TONE}

{HUMAN_VOICE}"""

    return _generate(base, limit)


def _generate(prompt: str, limit: int) -> str:
    """Generate text, regenerating if over the char limit, then trim as last resort."""
    text, note = "", ""
    for _ in range(3):
        text = sanitize(claude_code.run(prompt + note, web=False))
        if text and len(text) <= limit:
            break
        note = (
            f"\n\nYour last version was {len(text)} characters. Rewrite it tighter "
            f"and shorter, strictly under {limit} characters total."
        )
    return _trim(text, limit)


def run_prediction(brief: dict[str, Any]) -> str:
    """Daily VERDICT / breakdown post about a game (is it worth it? hype vs reality)."""
    t = CONFIG.threads_posts
    limit = int(t.get("max_chars", 500))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))
    tag = " ".join(t.get("hashtags", [])[:1])

    prompt = f"""Write ONE Threads VERDICT / BREAKDOWN about this game.

{now_context()}
{DATETIME_RULE}

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
KEY FACTS (use accurately, never invent more):
{facts}

{_lore_block(brief)}
Write like a sharp gamer giving the real verdict (worth it? hype vs reality?):
- Line 1: a confident hook / your headline call (e.g. "worth every peso" or "wait
  for the patch").
- Then 2 to 4 tight BULLET lines (start each with "- ") with the sharpest points:
  what's great, what's weak, who it's for, price/value, performance.
- End with a quick reply-bait question ("bibilhin niyo ba?").
- Be specific, not vague. Only use the facts above; never invent a number/date.
- HARD LIMIT: {limit} characters or less for the ENTIRE post. At most one hashtag
  if natural: {tag}
- Output ONLY the post text. No preamble, no labels.

{POSITIVE_TONE}

{HUMAN_VOICE}"""
    return _generate(prompt, limit)


def run_poll() -> str:
    """Risk/probability hot take + a 2-option 'reply-to-vote' poll."""
    t = CONFIG.threads_posts
    limit = int(t.get("max_chars", 500))
    domains = t.get("poll_domains", [])
    domain = random.choice(domains) if domains else "risk vs reward"

    samples = """STYLE GUIDE (do NOT copy these, invent a fresh take + your own angle):
- Hot take: preordering is a trap, wait a week for reviews and a day-one patch.
  Poll: preorder for the hype, or wait for the reviews?
- Hot take: remakes that change the story are braver than 1:1 nostalgia copies.
  Poll: faithful remake, or bold reimagining?
- Hot take: hoarding gacha currency for the safe pity is boring, blow it on the 1%
  banner. Poll: hoard for the guaranteed drop, or gamble it all on 1%?"""

    prompt = f"""Write ONE Threads "reply-to-vote" POLL post for GAMERS on this theme: {domain}.

Structure:
- Open with a punchy HOT TAKE (1 to 2 lines): a strong, debatable gaming opinion
  (buying, value, remakes vs originals, single-player vs live-service, gacha luck).
  Make people want to argue.
- Then a blank line, a one-line poll question, then exactly TWO options on their
  own lines, labelled like:
    A) <the safe / certain choice>
    B) <the risky / high-upside choice>
- End with: Reply A or B 👇
- Be CREATIVE and original. Vary the scenario and the domain feel.
- HARD LIMIT: {limit} characters or less. No hashtags.
- Output ONLY the post text.

{samples}

{POSITIVE_TONE}

{HUMAN_VOICE}"""
    return _generate(prompt, limit)
