"""Agent 2 — Content Creation.

Turns a research brief into a scroll-stopping, story-driven caption for the
Facebook + Instagram feed.

Engagement model:
  - The FIRST line is the "See More" hook. Facebook truncates long posts around
    140 chars, so the hook must be the single most compelling teaser/question/
    statement and stay UNDER the limit so people choose to expand.
  - Short by default (hook + a few tight lines). Long-form only when the topic
    is genuinely educational/entertaining/high-value, and even then it's broken
    into short paragraphs, never a dense wall.

The hook length is enforced mechanically: we regenerate if it's too long, then
trim at a word boundary as a last resort, so the rule never slips.
"""
from __future__ import annotations

from typing import Any

from core import franchise
from core import writer as ai
from core.config import CONFIG
from core.openai_client import extract_json
from core.style import DATETIME_RULE, HUMAN_VOICE, TAGLISH_VOICE, sanitize
from core.timeref import now_context


def _system(taglish: bool = False) -> str:
    b = CONFIG.brand
    lang = "natural Taglish (Filipino + English)" if taglish else b["language"]
    base = (
        f"You are the Content Creation lead for {b['name']} ({b['handle']}). "
        f"Write in {lang}. Brand voice: {b['voice']}\n\n{HUMAN_VOICE}"
    )
    return base + ("\n\n" + TAGLISH_VOICE if taglish else "")


def _prompt(brief: dict[str, Any], hook_max: int, retry_note: str = "") -> str:
    category = brief["category"]
    cap = CONFIG.caption
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))

    return f"""Write ONE story-driven caption for Facebook + Instagram about this topic.

{now_context()}
{DATETIME_RULE}

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
HOOK IDEA: {brief.get('hook_idea')}
KEY FACTS (use accurately, never invent more):
{facts}

STORYTELLING FRAMEWORK (use it, don't label it):
1. HOOK: open a curiosity gap, a bold claim, a stake, or a sharp question.
2. TENSION: one or two lines that build why this matters right now.
3. PAYOFF: the insight, take, tip, or prediction that rewards the reader.
4. CTA: invite a reply, a save, or a share with a real question.

HARD RULES:
- The "hook" field is the FIRST thing readers see before Facebook's "See More".
  It MUST be under {hook_max} characters and be the most compelling line you can
  write. No hashtags or emojis-only in the hook, make it land on its own.
- Keep it SHORT by default: the body is at most {cap['short_body_max_lines']} short lines.
- Only go long-form if: {cap['long_form_only_if']}
- Skimmable: short lines, line breaks, tasteful emoji (not in a tidy formula).
- Be genuinely useful or spicy. No fluff, no padding.
{retry_note}
Return ONLY this JSON (no prose, no code fences):
{{
  "hook": "the under-{hook_max}-char first line",
  "body": "the rest of the caption (no hashtags), with line breaks as \\n",
  "long_form": false
}}"""


def _trim_hook(hook: str, limit: int) -> str:
    """Last-resort: cut the hook to <= limit on a word boundary."""
    hook = hook.strip()
    if len(hook) <= limit:
        return hook
    cut = hook[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:") + "..."


def run(brief: dict[str, Any], taglish: bool = False) -> str:
    """Return a finished FB/IG caption: hook + body + hashtags.

    Set taglish=True (reels targeting the young PH audience) to write the caption
    in natural Manila Gen-Z Taglish instead of English.
    """
    category = brief["category"]
    hook_max = int(CONFIG.caption["hook_max_chars"])
    fr = franchise.match(brief) if category != "sports" else None
    tags = " ".join((fr.get("hashtags") if fr else None) or CONFIG.hashtags[category])

    hook, body = "", ""
    retry_note = ""
    for attempt in range(3):
        raw = ai.write(_prompt(brief, hook_max, retry_note), system=_system(taglish))
        try:
            data = extract_json(raw)
            hook = sanitize(str(data.get("hook", "")))
            body = sanitize(str(data.get("body", "")))
        except Exception:
            # Couldn't parse JSON: treat first line as hook, rest as body.
            text = sanitize(raw)
            parts = text.split("\n", 1)
            hook = parts[0].strip()
            body = parts[1].strip() if len(parts) > 1 else ""

        if hook and len(hook) <= hook_max:
            break
        # Too long -> nudge the model to tighten the hook and try again.
        retry_note = (
            f"\nYour last hook was {len(hook)} characters. Rewrite it shorter and "
            f"punchier, strictly under {hook_max} characters.\n"
        )

    hook = _trim_hook(hook, hook_max)

    caption = hook
    if body:
        caption += "\n\n" + body
    caption += "\n\n" + tags
    return sanitize(caption)
