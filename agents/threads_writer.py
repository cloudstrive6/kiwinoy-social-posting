"""Threads Writer agent — writes the Threads post (text only, <=500 chars).

Storytelling spine (hook -> point -> reply-bait question) with a scroll-stopping
first line. Written by Claude via your subscription (CLAUDE_CODE_OAUTH_TOKEN).
The 500-char cap is enforced: regenerate if over, then trim as a last resort.
"""
from __future__ import annotations

import random
from typing import Any

from core import claude_code
from core.config import CONFIG
from core.style import DATETIME_RULE, HUMAN_VOICE, sanitize
from core.timeref import now_context


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

    base = f"""Write ONE Threads post about this sports story.

{now_context()}
{DATETIME_RULE}

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (use accurately, never invent more):
{facts}

Rules:
- The FIRST line must be a scroll-stopping hook (a bold take, a wild stat, or a
  sharp question) that makes people stop and read.
- Then a tight mini story: the hook, the point/insight, and a question that
  invites replies. A couple of short lines, conversational hype sports-fan voice.
- HARD LIMIT: {limit} characters or less for the ENTIRE post. Count carefully.
- At most one hashtag, only if it feels natural: {tag}
- Output ONLY the post text. No preamble, no surrounding quotes, no labels.

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
    """Detailed esports/sports prediction breakdown (bullets: stats, form, % odds)."""
    t = CONFIG.threads_posts
    limit = int(t.get("max_chars", 500))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))
    tag = " ".join(t.get("hashtags", [])[:1])

    prompt = f"""Write ONE Threads PREDICTION BREAKDOWN about this matchup / story.

{now_context()}
{DATETIME_RULE}

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
KEY FACTS (use accurately, never invent more):
{facts}

Write like a sharp analyst breaking down an upcoming match or tournament:
- Line 1: a confident hook / your headline call.
- Then 2 to 4 tight BULLET lines (start each with "- ") with the sharpest evidence:
  key player stats, form / win streak, head-to-head, and a percentage win-odds call.
- End with a quick reply-bait question ("who you got?").
- Be specific and analytical, not vague. Only use the facts above; never invent a
  stat or number that isn't given.
- HARD LIMIT: {limit} characters or less for the ENTIRE post. At most one hashtag
  if natural: {tag}
- Output ONLY the post text. No preamble, no labels.

{HUMAN_VOICE}"""
    return _generate(prompt, limit)


def run_poll() -> str:
    """Risk/probability hot take + a 2-option 'reply-to-vote' poll."""
    t = CONFIG.threads_posts
    limit = int(t.get("max_chars", 500))
    domains = t.get("poll_domains", [])
    domain = random.choice(domains) if domains else "risk vs reward"

    samples = """STYLE GUIDE (do NOT copy these, invent a fresh take + your own numbers):
- Hot take: calculated risks build empires; most people play too safe and miss the
  expected value. Poll: guaranteed $10,000 now, or a 10% shot at $250,000?
- Hot take: betting the Grand Final favorite is a trap, give me the underdog with
  the big payout. Poll: favorite wins easy, or the underdog pulls the upset?
- Hot take: hoarding currency for the safe pity drop is boring, blow it on the 1%
  banner. Poll: hoard for the guaranteed drop, or gamble it all on 1%?"""

    prompt = f"""Write ONE Threads "reply-to-vote" POLL post on this theme: {domain}.

Structure:
- Open with a punchy HOT TAKE (1 to 2 lines): a strong, debatable opinion about
  risk, odds, probability, or expected value. Make people want to argue.
- Then a blank line, a one-line poll question, then exactly TWO options on their
  own lines, labelled like:
    A) <the safe / certain choice>
    B) <the risky / high-upside choice>
- End with: Reply A or B 👇
- Be CREATIVE and original. Vary the scenario, the numbers, and the domain feel.
- HARD LIMIT: {limit} characters or less. No hashtags.
- Output ONLY the post text.

{samples}

{HUMAN_VOICE}"""
    return _generate(prompt, limit)
