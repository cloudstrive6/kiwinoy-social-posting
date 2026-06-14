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

import re
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


def _reel_hashtags(brief: dict[str, Any], max_tags: int = 3) -> list[str]:
    """2-3 super-relevant hashtags for a reel: per-game config, else franchise,
    else a name-derived tag. Always game-specific, never a wall of tags."""
    game = brief.get("game", "")
    per_game = (CONFIG.reels.get("game_hashtags", {}) or {})
    tags = list(per_game.get(game, []))
    if not tags:
        fr = franchise.match(brief)
        tags = list((fr.get("hashtags") if fr else None) or [])
    if not tags:
        nm = re.sub(r"[^A-Za-z0-9]", "", brief.get("subject", "") or "")
        tags = [f"#{nm}"] if nm else ["#Gaming"]
    # de-dupe, keep order, cap.
    seen, out = set(), []
    for t in tags:
        t = t if t.startswith("#") else f"#{t}"
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:max_tags]


def run_short(brief: dict[str, Any], taglish: bool = False) -> str:
    """Short caption for a gameplay reel / video: ONE punchy line + 2-3 hashtags.

    Matches the user's sample style ("Fisk is caught #MarvelsSpiderManRemastered
    #spiderman"): a tiny moment caption, not a story. Hashtags are super-relevant
    and capped at 3.
    """
    prompt = f"""Write ONE very short caption for a gameplay reel/video about:

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
MOMENT / HOOK: {brief.get('hook') or brief.get('hook_idea') or brief.get('angle')}

Rules:
- ONE short line, about 3 to 10 words. Punchy, like a caption to a clip moment
  (e.g. "Fisk is caught", "Best swing in the game", "This boss almost had me").
- It can be natural Taglish if it fits.
- No hashtags, no emojis, no quotes, no preamble. Just the line.

Return ONLY the line."""
    raw = ai.write(prompt, system=_system(taglish))
    line = sanitize(raw).strip().splitlines()[0].strip().strip('"')[:90]
    if not line:
        line = sanitize(brief.get("hook") or brief.get("title", "")).strip()[:90]
    tags = _reel_hashtags(brief)
    return f"{line}\n\n{' '.join(tags)}".strip()


def _observe_clip(cands: list, gname: str) -> str:
    """Stage 1 (vision OBSERVER): describe ONLY what's literally on screen across
    the frames — setting, characters' appearance (no name-guessing), action and
    any on-screen text. This factual read is then handed to the captioner so it
    knows what's going on before it writes the line."""
    from core import claude_code

    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(cands))
    prompt = (
        f"Use the Read tool to open these {len(cands)} frames (in order) from ONE "
        f"short {gname} gameplay clip.\n"
        "Describe ONLY what you can literally SEE — do not guess names or backstory. "
        "Cover, in 3-5 plain sentences:\n"
        "- SETTING/location (indoor lab, rooftop, street, snow, etc.)\n"
        "- CHARACTERS visible, by APPEARANCE only (e.g. 'man in a lab coat', 'figure "
        "in a red-and-blue spider suit', 'teen in a hoodie') — never assume who they "
        "are.\n"
        "- The ACTION / what is happening or being done.\n"
        "- Any on-screen TEXT, subtitles, objective markers or UI you can read.\n\n"
        f"Frames:\n{listing}"
    )
    return sanitize(claude_code.run(prompt, allowed_tools="Read", timeout=180)).strip()


def _caption_with_lore(observation: str, game: str, gname: str, taglish: bool) -> str:
    """Stage 2 (lore-grounded CAPTIONER): map the observer's factual read onto the
    game's story/characters/locations, work out which moment it is, then write the
    short clip-title caption — accurately."""
    from core import claude_code, lore

    brief = lore.lore_for(game)
    lore_block = (
        f"GAME STORY / CHARACTERS / PLACES (use this to identify the scene "
        f"correctly):\n{brief}\n\n" if brief else ""
    )
    prompt = (
        f"You are writing a caption for a {gname} gameplay clip.\n\n"
        f"WHAT'S ON SCREEN (an observer's factual description):\n{observation}\n\n"
        f"{lore_block}"
        "First, silently work out WHICH character / location / story moment this is "
        "by matching the description against the game's story above. Respect the "
        "'DON'T CONFUSE' notes. Then write ONE short caption (3 to 8 words), like a "
        "clip title. Examples: \"Fisk is caught\", \"Best web-swing in the game\", "
        "\"This boss almost had me\".\n"
        "ACCURACY RULES:\n"
        "- Name a character ONLY if the story above makes it clear who it is; "
        "otherwise say \"Spider-Man\" or just describe the action.\n"
        "- Never mislabel a location or a relationship (e.g. don't call a mentor's "
        "lab a 'villain's lab', or an ally an 'enemy').\n"
        "- If you're unsure, caption the ACTION rather than guessing identities.\n"
        + ("Natural Taglish is welcome. " if taglish else "Write it in ENGLISH. ")
        + "No hashtags, no emojis, no quotes, no preamble — just the line."
    )
    return sanitize(claude_code.run(prompt, timeout=120)).strip()


def _hook_and_caption(observation: str, game: str, gname: str, taglish: bool) -> tuple[str, str]:
    """From the observer's read + the game lore, write BOTH the scroll-stopping
    on-screen HOOK (master-of-viewer-psychology) and the post caption, grounded
    in what THIS clip actually shows. Returns (hook, caption)."""
    from core import claude_code, lore

    brief = lore.lore_for(game)
    lore_block = (
        f"GAME STORY / CHARACTERS / PLACES (use this to identify the moment "
        f"correctly):\n{brief}\n\n" if brief else ""
    )
    cap_lang = "Natural Taglish is welcome." if taglish else "Write it in ENGLISH."
    prompt = (
        f"You are writing text for a {gname} gameplay reel. You are a MASTER of "
        "short-video viewer psychology and retention — your job is to stop the "
        "scroll in the first second.\n\n"
        f"WHAT'S ON SCREEN (an observer's factual description of THIS clip):\n"
        f"{observation}\n\n"
        f"{lore_block}"
        "STEP 1 — silently identify the exact character / location / moment by "
        "matching the description to the story above (respect any 'DON'T CONFUSE' "
        "notes). STEP 2 — write two things:\n\n"
        "ON-SCREEN HOOK (sits in a bar at the TOP, the viewer reads it before the "
        "clip plays — it ALONE must make them stay):\n"
        "- Use a real psychological hook: a curiosity gap, a pattern interrupt, a "
        "bold claim, rising stakes, or a relatable gamer emotion tied to THIS exact "
        "moment. Make them NEED to see what happens.\n"
        "- Be specific to what's actually on screen — never a vague, generic line, "
        "and don't keep leaning on the same idea every time (e.g. not always about "
        "'physics' or 'graphics').\n"
        "- 4 to 9 words. ENGLISH. No hashtags, no emojis, no quotes. Title-worthy, "
        "not a full sentence with punctuation.\n"
        "- Examples of the ENERGY (don't copy): \"Watch what he does at the end\", "
        "\"This is why Otto can't be trusted\", \"Nobody talks about this combo\".\n\n"
        "CAPTION (sits BELOW the video as the post caption):\n"
        "- ONE short clip-title line, 3 to 8 words, accurate to the moment.\n"
        f"- {cap_lang} No hashtags, no emojis, no quotes.\n\n"
        'Return ONLY this JSON: {"hook": "the on-screen hook", "caption": "the caption"}'
    )
    raw = claude_code.run(prompt, timeout=150)
    hook, caption = "", ""
    try:
        d = extract_json(raw)
        hook = sanitize(str(d.get("hook", ""))).strip().strip('"')
        caption = sanitize(str(d.get("caption", ""))).strip().strip('"')
    except Exception:
        # Fallback: first non-empty line is the hook.
        for ln in sanitize(raw).splitlines():
            if ln.strip():
                hook = ln.strip().strip('"')
                break
    return hook[:90], caption[:90]


def hook_and_caption_from_video(
    video_path, game: str = "", taglish: bool = False
) -> tuple[str, str]:
    """REVIEW a gameplay clip and write BOTH the on-screen hook and the caption,
    grounded in what the clip shows + the game's lore. One OBSERVER call shared
    by both, then one psychology-driven WRITER call. Returns (hook, caption);
    each falls back to a safe line. Caption already includes its hashtags."""
    import tempfile
    from pathlib import Path

    from core import frames

    hook, line = "", ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cands = frames.extract_candidates(Path(video_path), Path(tmp), n=4)
            if cands:
                gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
                observation = _observe_clip(cands, gname)
                if observation:
                    hook, line = _hook_and_caption(observation, game, gname, taglish)
    except Exception as e:
        print(f"[content] hook+caption from video failed ({e!r}); using fallbacks.", flush=True)
    if not hook:
        hook = "Wait for it"
    if not line:
        line = "Watch this clip"
    tags = _reel_hashtags({"game": game})
    return hook, f"{line}\n\n{' '.join(tags)}".strip()


def caption_from_video(video_path, game: str = "", taglish: bool = False) -> str:
    """REVIEW a gameplay clip and write an accurate clip-title caption.

    Two agents: an OBSERVER reports what's literally on screen, then a
    lore-grounded CAPTIONER maps that onto the game's story/characters to write
    the line — so it stops guessing wrong (e.g. Otto's lab, not a "villain's
    lab"). Returns one short line + 2-3 game hashtags.
    """
    import tempfile
    from pathlib import Path

    from core import frames

    line = ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cands = frames.extract_candidates(Path(video_path), Path(tmp), n=4)
            if cands:
                gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
                observation = _observe_clip(cands, gname)
                if observation:
                    raw = _caption_with_lore(observation, game, gname, taglish)
                    line = raw.splitlines()[0].strip().strip('"')[:90] if raw else ""
    except Exception as e:
        print(f"[content] vision caption failed ({e!r}); using a generic line.", flush=True)
    if not line:
        line = "Watch this clip"
    tags = _reel_hashtags({"game": game})
    return f"{line}\n\n{' '.join(tags)}".strip()
