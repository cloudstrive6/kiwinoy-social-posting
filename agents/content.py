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

import random
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


def generic_game_caption(game: str, max_tags: int = 5) -> str:
    """GENERIC (game-level, NOT clip-specific) caption for the full-bleed 'fill'
    vertical reels — the raw footage isn't reviewed, so the caption hypes the GAME in
    the sample style: a punchy title line + 1-2 vibe lines + the game name, then 3-5
    game hashtags. Threads uses #GamingThreads only (handled by the publisher)."""
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
    prompt = f"""Write a short, generic hype caption for a gameplay reel of the game
"{gname}". It is NOT about a specific moment — it celebrates the game/its vibe overall.

Match THIS style exactly (title line, 1-2 vibe lines, then the game name):
---
Spiderman Cinematic Parkour ✨
Fluid movement, wall runs, and cinematic flow ✨
Marvel's Spider-Man turns NYC into a parkour playground.
Marvel's Spider-Man Remastered 💗
---

Rules:
- 3-4 short lines total. First line = a punchy title (1 tasteful emoji ok).
- 1-2 lines on the vibe/feel of the game (generic, not a specific scene).
- Final line = the game's proper name (a heart or sparkle emoji ok).
- NO hashtags (added separately), no quotes, no preamble. Return ONLY the caption."""
    raw = _text(prompt)
    body = "\n".join(l.strip() for l in sanitize(raw).strip().splitlines() if l.strip())[:400]
    if not body:
        body = f"{gname} gameplay\nPure vibes, edge to edge.\n{gname}"
    tags = _reel_hashtags({"game": game}, max_tags=max_tags)
    return f"{body}\n\n{' '.join(tags)}".strip()


# --- RELATABLE full-bleed (FILL) captions ---------------------------------------
# The FILL reels are pure footage posted for the AUDIENCE to relate to and share —
# we do NOT promote the game. So the caption reviews the clip and speaks like a real
# person captioning their own video (a feeling, a little life-moment), with NO game
# name and no marketing. Rotating 'life-moment' angles keep captions varied across
# posts (the old game-level caption repeated because it never looked at the clip).
_FILL_ANGLES = [
    "a relatable daily-life parallel — a work break, the commute, lunch hour, chores, needing to decompress",
    "the raw FEELING of this exact moment — calm, freedom, relief, focus, being in the zone",
    'a "POV:" line the viewer instantly sees themselves in',
    "a tiny diary/mood caption, like you're texting a close friend about your day",
    "the little escape this gives you after a long, draining day",
    "a small everyday win, or a 'treat yourself for five minutes' moment",
]
_FILL_FALLBACKS = [
    "POV: you just needed to clear your head for a bit",
    "the little escape after a long day",
    "when you finally get a quiet moment to yourself",
    "just needed ten minutes to breathe",
    "some days you just wanna log off reality for a while",
    "me pretending my problems don't exist for 30 minutes",
]
# Relatable NICHE tags for FILL (the '1-2 niche' slots of the 3-5 formula).
_FILL_NICHE = ["#gamingreels", "#gamingclips", "#gamingcommunity", "#gamerlife", "#relatable"]


def _max_tags() -> int:
    """Global hashtag cap (reels.max_hashtags, hard-limited to 5 per platform guidance)."""
    try:
        return max(1, min(5, int(CONFIG.reels.get("max_hashtags", 5) or 5)))
    except Exception:
        return 5


def _dedupe_cap(tags: list, cap: int) -> list[str]:
    """Normalize to #tags, drop dupes (case-insensitive), keep order, hard-cap at `cap`."""
    seen, out = set(), []
    for t in tags:
        t = str(t).strip()
        if not t:
            continue
        t = t if t.startswith("#") else f"#{t}"
        if t.lower() not in seen and len(out) < cap:
            seen.add(t.lower())
            out.append(t)
    return out


def _fill_tags(game: str = "") -> list[str]:
    """Up to reels.max_hashtags (<=5) tags for a FILL reel, per the 3-5 formula:
    1-2 CORE topic (the game tag), 1-2 NICHE (relatable gaming), 1 BRAND (the channel)."""
    cap = _max_tags()
    override = CONFIG.reels.get("fill_hashtags", None)
    if override:
        return _dedupe_cap(list(override), cap)
    core = list((CONFIG.reels.get("game_hashtags", {}) or {}).get(game, []))[:2]   # CORE topic
    niche = _FILL_NICHE[:]
    random.shuffle(niche)
    brand = str(CONFIG.reels.get("brand_hashtag", "") or "").strip()
    reserve = 1 if brand else 0                     # keep the last slot for the brand tag
    out = _dedupe_cap(core, cap - reserve)          # 1-2 core
    out = _dedupe_cap(out + niche, cap - reserve)   # niche fills the middle
    if brand:
        out = _dedupe_cap(out + [brand], cap)       # brand takes the final slot
    return out


def _reel_tags_with_brand(game: str) -> list[str]:
    """CORE game tags (<=3) + the 1 BRAND tag, capped at reels.max_hashtags. For the
    classic/triptych + vision caption paths. Stays <=4 so IG's later +1 #gamingreels
    keeps the post within the 5-tag limit."""
    brand = str(CONFIG.reels.get("brand_hashtag", "") or "").strip()
    base = list(_reel_hashtags({"game": game}))
    return _dedupe_cap(base + ([brand] if brand else []), _max_tags())


def _relatable_caption(observation: str, angle: str, avoid: str = "") -> str:
    """Write ONE short, human, relatable FIRST-PERSON caption from the observer's read
    of the clip — the moment/feeling, NOT the game. No game/character names, no hype.
    `avoid` feeds back a critic's rejection reason for a corrected second attempt."""
    fix = (f"\nA PREVIOUS attempt was REJECTED because: {avoid}\nWrite a new line that "
           "fixes that.\n" if avoid else "")
    prompt = (
        "You write captions for full-screen vertical gameplay reels. This is NOT an ad — "
        "we do NOT promote the game. We post gameplay so the audience LIKES it, RELATES to "
        "it, feels something, and SHARES it because it mirrors their own life or mood.\n\n"
        f"WHAT'S ON SCREEN (an observer's factual read of THIS clip):\n{observation}\n\n"
        "Write ONE short, human, FIRST-PERSON caption about the moment/feeling in this clip "
        "— the way a real person captions their own video.\n\n"
        "Match the VIBE of these (do NOT copy them):\n"
        '- "The peace of flying after a battle"\n'
        '- "Got 10 mins before lunch ends, might as well swing across the city"\n'
        '- "POV: you just needed to clear your head"\n'
        '- "when the grind finally slows down for a second"\n\n'
        f"Use THIS lens for your caption: {angle}.\n"
        f"{fix}\n"
        "GROUNDING — this is the rule people notice when it's broken:\n"
        "- Only reference actions/places the observation ACTUALLY describes. Do NOT invent "
        "concrete specifics — no 'rooftop', 'landed', 'sat down', 'found a spot', 'stopped' "
        "unless the observer explicitly says so. If the clip is continuous swinging / flying "
        "/ gliding / falling, your caption is about MOVEMENT, air, speed or freedom — NEVER "
        "about stopping, landing, resting, or staying put.\n"
        "- The FEELING is yours to choose; the physical action must match the clip.\n\n"
        "POV — keep it coherent:\n"
        "- If you start with 'POV:', it must describe the VIEWER'S OWN relatable situation or "
        "feeling (something a person scrolling recognizes from their real life). It must NOT "
        "read as the on-screen character narrating what they're doing. If in doubt, drop "
        "'POV:' and just say the feeling in first person.\n\n"
        "OTHER RULES:\n"
        "- NO game name, NO character names, NO 'this game'; NO marketing words "
        "(masterpiece, insane graphics, must-play, underrated, stunning).\n"
        "- Max ~14 words, ONE line. 0-1 tasteful emoji is fine. No hashtags, no quotes, "
        "no preamble. Return ONLY the caption line."
    )
    raw = sanitize(_text(prompt, timeout=120)).strip()
    return (raw.splitlines()[0].strip().strip('"') if raw else "")[:120]


def _verify_caption(caption: str, observation: str) -> tuple[bool, str]:
    """Adversarial critic: reject a caption that invents on-screen facts, contradicts the
    action, uses an incoherent POV, or promotes the game. Returns (ok, issues). Fail-OPEN
    (ok=True) if the critic itself errors, so a transient model issue never blocks posting."""
    prompt = (
        "You are a STRICT fact-checker for a short, relatable social caption on a gameplay "
        "clip. Your job is to catch captions that don't match the video or confuse the reader.\n\n"
        f"OBSERVER'S FACTUAL READ OF THE CLIP:\n{observation}\n\n"
        f'CAPTION TO CHECK:\n"{caption}"\n\n'
        "Mark it BAD if ANY of these are true:\n"
        "1. It states a concrete visual fact the observation does NOT support (e.g. says "
        "'rooftop', 'landed', 'sat down', 'found a spot', a specific object/place that isn't "
        "described).\n"
        "2. It CONTRADICTS the action — e.g. implies stopping/landing/stillness while the clip "
        "is continuous swinging, flying, gliding, or falling.\n"
        "3. The POV is incoherent — a 'POV:' line that reads as the character narrating their "
        "in-game action instead of a situation/feeling the VIEWER relates to.\n"
        "4. It names the game or a character, or uses marketing words.\n\n"
        "A relatable FEELING (needing air, decompressing, escaping for a minute) is FINE as "
        "long as the physical anchor matches the clip. Be strict but reasonable.\n"
        'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=90))
        return bool(d.get("ok", True)), str(d.get("issues", "")).strip()
    except Exception:
        return True, ""


def relatable_fill_caption(video_path, game: str = "") -> str:
    """RELATABLE caption for the full-bleed FILL vertical reels. REVIEWS the clip (shared
    vision OBSERVER), writes a short human first-person moment/feeling line (no game name,
    no marketing), then FACT-CHECKS it against the observation — regenerating once if the
    critic flags an invented fact / contradiction / confused POV. Falls back to a safe
    feeling-only line if vision is unavailable or both attempts fail. Includes hashtags."""
    import tempfile
    from pathlib import Path

    from core import frames

    line = ""
    angle = random.choice(_FILL_ANGLES)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cands = frames.extract_candidates(Path(video_path), Path(tmp), n=4)
            if cands:
                gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
                observation = _observe_clip(cands, gname)
                if observation:
                    cand = _relatable_caption(observation, angle)
                    ok, issues = _verify_caption(cand, observation) if cand else (False, "")
                    if not ok and cand:                      # one grounded correction pass
                        print(f"[content] FILL caption rejected ({issues or 'unclear'}); "
                              "regenerating.", flush=True)
                        cand = _relatable_caption(observation, angle, avoid=issues)
                        ok, _ = _verify_caption(cand, observation) if cand else (False, "")
                    if ok and cand:
                        line = cand
    except Exception as e:
        print(f"[content] relatable FILL caption failed ({e!r}); using a fallback line.", flush=True)
    if not line:                                             # SAFE: feeling-only, always grounded
        line = random.choice(_FILL_FALLBACKS)
    return f"{line}\n\n{' '.join(_fill_tags(game))}".strip()


def _text(prompt: str, timeout: int = 120) -> str:
    """Claude text generation with an OpenAI fallback. Tries the Claude chain
    (Max OAuth -> Anthropic API key); if BOTH are unavailable (expired token, out
    of usage, $0 API credits), falls back to the funded OpenAI writer so we keep
    getting real hooks/captions instead of generic placeholders."""
    from core import claude_code, openai_client

    try:
        return claude_code.run(prompt, timeout=timeout)
    except claude_code.ClaudeCodeError as e:
        print(f"[content] Claude unavailable ({e}); falling back to OpenAI.", flush=True)
        return openai_client.write(prompt)


def _observe_clip(cands: list, gname: str) -> str:
    """Stage 1 (vision OBSERVER): describe ONLY what's literally on screen across
    the frames — setting, characters' appearance (no name-guessing), action and
    any on-screen text. This factual read is then handed to the captioner so it
    knows what's going on before it writes the line. Claude vision first, then the
    OpenAI vision fallback if Claude is unavailable."""
    from core import claude_code, openai_client

    instruction = (
        f"These are {len(cands)} frames (in order) from ONE short {gname} gameplay "
        "clip.\nDescribe ONLY what you can literally SEE — do not guess names or "
        "backstory. Cover, in 3-5 plain sentences:\n"
        "- SETTING/location (indoor lab, rooftop, street, snow, etc.)\n"
        "- CHARACTERS visible, by APPEARANCE only (e.g. 'man in a lab coat', 'figure "
        "in a red-and-blue spider suit', 'teen in a hoodie') — never assume who they "
        "are.\n"
        "- The ACTION / what is happening or being done.\n"
        "- Any on-screen TEXT, subtitles, objective markers or UI you can read."
    )
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(cands))
    claude_prompt = (
        f"Use the Read tool to open these frames first.\n\n{instruction}\n\n"
        f"Frames:\n{listing}"
    )
    try:
        return sanitize(claude_code.run(claude_prompt, allowed_tools="Read", timeout=180)).strip()
    except claude_code.ClaudeCodeError as e:
        print(f"[content] observer: Claude unavailable ({e}); using OpenAI vision.", flush=True)
        return sanitize(openai_client.vision(instruction, cands)).strip()


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
    return sanitize(_text(prompt, timeout=120)).strip()


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
    raw = _text(prompt, timeout=150)
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


def game_title_line(game: str) -> str:
    """The '<Game Title> <emoji>' line that sits BETWEEN the caption body and the
    hashtags on classic/triptych reel captions (per user 2026-07-14), e.g.
    "Marvel's Spider-Man 2 🕸️". Name from reels.game_names, emoji from
    reels.game_emoji (fallback 🎮). Empty string if the game has no real display
    name, so the caller just omits the line."""
    gname = str((CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "").strip()
    if not gname or gname.lower() == "this game":
        return ""
    emo = str((CONFIG.reels.get("game_emoji", {}) or {}).get(game, "🎮") or "").strip()
    return f"{gname} {emo}".strip()


def hook_and_caption_from_video(
    video_path, game: str = "", taglish: bool = False, with_game_title: bool = False
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
    tags = _reel_tags_with_brand(game)
    # with_game_title=True (classic/triptych reels -> FB/IG/TikTok) inserts the game
    # title + emoji between the body and the hashtags. Off by default so other callers
    # (e.g. the YouTube Short description) keep the plain body+hashtags caption.
    parts = [line]
    if with_game_title:
        gt = game_title_line(game)
        if gt:
            parts.append(gt)
    if tags:
        parts.append(" ".join(tags))
    return hook, "\n\n".join(parts).strip()


def youtube_longform_meta(game: str = "", gname: str = "") -> dict:
    """YouTube metadata for a FULL-GAME long-form video: a clickable title, a few
    PUNCHY thumbnail words, an SEO description, and search tags. Falls back to safe
    values if the model is unavailable."""
    gname = gname or "this game"
    prompt = (
        f"You are writing YouTube metadata for a FULL-GAME long-form video of "
        f"{gname} (a complete playthrough, 4K 60fps HDR). Return ONLY this JSON:\n"
        '{"title": "...", "thumbnail": "...", "description": "...", "tags": ["..."]}\n'
        "- title: follow this proven full-game format EXACTLY, with the real game "
        "name: '<GAME> Gameplay Walkthrough FULL GAME [4K 60FPS HDR] - No Commentary' "
        "(<=100 chars).\n"
        "- thumbnail: short BIG-CAPS words for the thumbnail box; default 'FULL GAME' "
        "(or a punchy variant like 'THE FULL GAME', 'EVERY BOSS').\n"
        "- description: 2-3 sentence description (mention full game, 4K 60fps HDR, "
        "no commentary).\n"
        "- tags: 8-15 lowercase search tags.\n"
        "No markdown, no preamble — just the JSON."
    )
    title = thumb = desc = ""
    tags: list[str] = []
    try:
        d = extract_json(_text(prompt, timeout=150))
        title = sanitize(str(d.get("title", ""))).strip()[:100]
        thumb = sanitize(str(d.get("thumbnail", ""))).strip()[:40]
        desc = sanitize(str(d.get("description", ""))).strip()[:4900]
        tags = [sanitize(str(t)).strip() for t in (d.get("tags") or []) if str(t).strip()][:15]
    except Exception as e:
        print(f"[content] longform meta failed ({e!r}); using fallbacks.", flush=True)
    if not title:
        title = f"{gname} Gameplay Walkthrough FULL GAME [4K 60FPS HDR] - No Commentary"[:100]
    if not thumb:
        thumb = "FULL GAME"
    if not desc:
        desc = (f"The complete {gname} playthrough in 4K 60fps HDR — the full game, "
                f"no commentary, start to finish.")
    if not tags:
        tags = [gname.lower(), "full game", "walkthrough", "gameplay walkthrough",
                "no commentary", "playthrough", "longplay", "4k", "hdr", "60fps"]
    return {"title": title, "thumbnail": thumb, "description": desc, "tags": tags}


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
    tags = _reel_tags_with_brand(game)
    return f"{line}\n\n{' '.join(tags)}".strip()
