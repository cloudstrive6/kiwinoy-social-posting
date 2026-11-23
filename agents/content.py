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
  (e.g. "Caught him mid-escape", "That takedown was clean", "This boss almost had me").
  Fit the ACTUAL moment above — do not default to swinging/traversal wording.
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
"{gname}". It is NOT about a specific moment and the clip was NOT reviewed — so it must
celebrate the ENERGY/FEEL only and NEVER claim anything specific that happens on screen.

Match THIS shape (a punchy title line, 1-2 vibe lines about the energy, then the game name).
The example below is only for SHAPE — do NOT copy its words:
---
Locked In ✨
Pure momentum, edge to edge — no filler, all payoff.
{gname} 💗
---

Rules:
- 3 short lines total. First line = a punchy title (1 tasteful emoji ok).
- Middle line = the vibe/energy ONLY. Do NOT name any specific action, move, weapon,
  character, or place (NO "swinging", "web-slinging", "parkour", "traversal", "driving",
  "NYC"/"the city", boss names, etc.) — this caption must never claim what's on screen.
- Final line = the game's proper name "{gname}" (a heart or sparkle emoji ok).
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
# Relatable NICHE tags for FILL (the '1-2 niche' slots of the 3-5 formula). NB: no
# "#relatable" — it's a huge generic tag with no gaming-discovery value (dropped per user).
_FILL_NICHE = ["#gamingreels", "#gamingclips", "#gamingcommunity", "#gamerlife"]


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
        "- The FEELING is yours to choose; the physical action must match the clip.\n"
        "- If the observation's TONE line says funny, the caption is the JOKE: the relatable "
        "self-own or deadpan line a person posts under their own fail ('me trying to look "
        "cool for exactly one second', 'my plans vs what actually happened'), about the real "
        "silly thing the observation describes (Bryce, 2026-11-20).\n\n"
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
        "4. It names the game or a character, or uses marketing words.\n"
        "5. It claims a fail, mishap or joke premise ('one job', 'that went wrong') that the "
        "observation's ACTION sentences do not describe. A 'TONE: funny' line is only a mood "
        "label, never evidence of what happened.\n\n"
        "A relatable FEELING (needing air, decompressing, escaping for a minute) is FINE as "
        "long as the physical anchor matches the clip. Be strict but reasonable.\n"
        'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=90))
        return bool(d.get("ok", True)), str(d.get("issues", "")).strip()
    except Exception:
        return True, ""


def _verify_descriptive(caption: str, observation: str) -> tuple[bool, str]:
    """Fact-check the DESCRIPTIVE/hype FILL caption. Unlike _verify_caption, it ALLOWS
    naming the game + hype/marketing words — it ONLY catches an ACTION/setting that
    doesn't match the clip (the 'swinging' on a ground-fight bug, per user 2026-08-09).
    Fail-OPEN on critic error so a transient issue never blocks posting."""
    prompt = (
        "You are a fact-checker for a short HYPE caption on a gameplay clip. The caption is "
        "ALLOWED to name the game and use hype/marketing/vibe words — do NOT flag that.\n\n"
        f"OBSERVER'S FACTUAL READ OF THE CLIP:\n{observation}\n\n"
        f'CAPTION TO CHECK:\n"{caption}"\n\n'
        "Mark it BAD if the caption names or implies ANY action, move, or setting the "
        "observation does NOT support — EVEN IF other parts of the caption are accurate:\n"
        "1. A single unsupported action/place makes it BAD (e.g. 'swinging'/'web-slinging'/"
        "'parkour'/'traversal'/'flying'/'gliding'/'driving' when the clip is a GROUND fight; "
        "'NYC'/'the city'/a rooftop when the clip is indoors; any location/object not shown).\n"
        "2. Do NOT excuse a false action just because another clause is true — 'snappy combat' "
        "being real does NOT make an added 'seamless swinging' acceptable.\n"
        "3. It CONTRADICTS what is happening on screen.\n"
        "4. It claims a fail, mishap or joke premise the observation's ACTION sentences do not "
        "describe ('TONE: funny' is a mood label, not evidence).\n"
        "Generic energy/vibe words with NO specific action (e.g. 'pure momentum', 'locked in') "
        "are fine. Judge the ACTION/SETTING accuracy only.\n"
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

    from core import ffmpeg, frames

    line = ""
    angle = random.choice(_FILL_ANGLES)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _dur = ffmpeg.duration(Path(video_path))
            cands = frames.extract_candidates(Path(video_path), Path(tmp),
                                              n=observe_frame_count(_dur))
            if cands:
                gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
                observation = _observe_clip(cands, gname, _dur)
                if observation:                              # + full-clip subtitle speakers
                    observation = _with_subs(observation, _scan_subtitles(video_path, gname))
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
    if line:                                                 # tidy casing (per user): first letter + standalone "i"
        line = line[0].upper() + line[1:]
        line = re.sub(r"\bi\b", "I", line)                   # "where i breathe" -> "where I breathe"
    return f"{line}\n\n{' '.join(_fill_tags(game))}".strip()


def _descriptive_caption(observation: str, gname: str, avoid: str = "") -> str:
    """Write the descriptive/hype FILL body (punchy title + vibe lines + game name)
    GROUNDED in the observer's read of THIS clip, so the hype matches what's actually
    on screen (no inventing 'swinging' on a ground-fight clip)."""
    prompt = f"""Write a short, punchy HYPE caption for a gameplay reel of "{gname}", GROUNDED in
what ACTUALLY happens in THIS clip. Every action, move, and place you mention MUST come from the
observation below — never from your prior knowledge of the game.

WHAT'S ON SCREEN (an observer's factual read of THIS clip):
{observation}

The caption has this SHAPE only (punchy title line, 1-2 vibe lines, then the game name). The
example shows SHAPE, not words — do NOT reuse its wording, and note it is deliberately action-free:
---
<punchy title describing THE ACTUAL on-screen moment> ✨
<1-2 lines on the feel of THAT specific action — only what the observation supports>
{gname} 💗
---

Rules:
- First line = a punchy title (1 tasteful emoji ok) that fits the ACTUAL on-screen action.
- 1-2 vibe lines about THIS specific moment (accurate to the clip, not generic).
- Do NOT name any action, move, or place the observation does NOT show. If the clip is a fight,
  do NOT say "swinging"/"web-slinging"/"parkour"/"traversal"; if there is no city skyline, do NOT
  say "NYC"/"the city". When unsure, stay on feeling/energy words rather than naming a move.
- Final line = the game's proper name "{gname}" (a heart or sparkle emoji ok).
- If the observation's TONE line says funny, make it a FUNNY caption instead of hype: a dry,
  deadpan title about the real silly thing (a laughing emoji ok), vibe lines that play the joke
  straight. Only the silliness the observation shows (Bryce, 2026-11-20).
- NO hashtags (added separately), no quotes, no preamble. Return ONLY the caption.""" + (
        f"\n- AVOID (a prior draft was wrong): {avoid}" if avoid else "")
    return sanitize(_text(prompt)).strip()


def descriptive_fill_caption(video_path=None, game: str = "") -> str:
    """The descriptive/hype FILL caption style (punchy title + vibe lines + game name),
    now GROUNDED IN THE CLIP: it REVIEWS the footage first (shared vision OBSERVER) so
    the hype matches the actual action — per user 2026-08-09, a fill caption said
    "swinging" on a Spider-Man GROUND-FIGHT clip because this variant never looked at
    the footage. Fact-checks against the observation (regenerates once on a flagged
    invention/contradiction). Uses the EXACT GAME-ONLY hashtags (config game_hashtags,
    <=5, NO brand tag — per user 2026-07-28) that the winning reels ran with. Falls back
    to the game-level generic_game_caption if no clip is given or vision is unavailable."""
    import tempfile
    from pathlib import Path

    from core import ffmpeg, frames

    body = ""
    if video_path:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _dur = ffmpeg.duration(Path(video_path))
                cands = frames.extract_candidates(Path(video_path), Path(tmp),
                                                  n=observe_frame_count(_dur))
                if cands:
                    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
                    observation = _observe_clip(cands, gname, _dur)
                    if observation:                          # + full-clip subtitle speakers
                        observation = _with_subs(observation, _scan_subtitles(video_path, gname))
                        cand = _descriptive_caption(observation, gname)
                        ok, issues = _verify_descriptive(cand, observation) if cand else (False, "")
                        if not ok and cand:                  # one grounded correction pass
                            print(f"[content] descriptive FILL caption rejected "
                                  f"({issues or 'unclear'}); regenerating.", flush=True)
                            cand = _descriptive_caption(observation, gname, avoid=issues)
                            ok, _ = _verify_descriptive(cand, observation) if cand else (False, "")
                        if ok and cand:
                            body = cand
        except Exception as e:
            print(f"[content] descriptive FILL caption failed ({e!r}); game-level fallback.",
                  flush=True)
    if not body:                                             # no clip / vision down -> game-level
        return generic_game_caption(game)
    body = "\n".join(l.strip() for l in sanitize(body).strip().splitlines() if l.strip())[:400]
    tags = _reel_hashtags({"game": game}, max_tags=_max_tags())   # GAME-ONLY tags (per user)
    return f"{body}\n\n{' '.join(tags)}".strip()


# Inside hook_and_caption_from_video the critics FAIL CLOSED (review 2026-11-23): a timeout or
# an unreadable reply used to count as a pass, so an unchecked hook could ship. Elsewhere they
# keep failing open, as their callers expect.
_STRICT_CRITICS = False


def _critic_down(name: str) -> tuple[bool, str]:
    return (False, f"{name} unavailable") if _STRICT_CRITICS else (True, "")


def _writer_model() -> str | None:
    """Model for the reel OBSERVER and the hook/caption WRITERS (config
    models.hook_writer_model, Bryce 2026-11-21: Opus writes the line viewers see). The
    yes/no critics keep the cheaper default (models.claude_model). None = that default."""
    m = str((CONFIG.models or {}).get("hook_writer_model", "") or "").strip()
    return m or None


def _text(prompt: str, timeout: int = 120, model: str | None = None) -> str:
    """Claude text generation with an OpenAI fallback. Tries the Claude chain
    (Max OAuth -> Anthropic API key); if BOTH are unavailable (expired token, out
    of usage, $0 API credits), falls back to the funded OpenAI writer so we keep
    getting real hooks/captions instead of generic placeholders."""
    from core import claude_code, openai_client

    try:
        return claude_code.run(prompt, timeout=timeout, model=model,
                               api_fallback_model=(CONFIG.models.get("claude_model") if model else None))
    except Exception as e:   # ClaudeCodeError, a timeout, anything — never lose the write
        print(f"[content] Claude unavailable ({e!r}); falling back to OpenAI.", flush=True)
        return openai_client.write(prompt)


def observe_frame_count(duration: float) -> int:
    """How many frames the observer should look at: ~1 per 3s of clip, 6..18. Four frames
    for a 150s reel (one every ~37s) meant the writer narrated a video it had barely seen —
    it welded together scenes minutes apart and the critics rightly rejected it (per user
    2026-10-02: 16 of 32 recent rejections were 'the dialogue says X but the footage shows Y')."""
    # ~1 per 3s, 6..18 (2026-11-20): at 1 per 10s a 2-second gag (an ATV straight into a palm
    # tree) fell between frames, so funny moments went unseen. 18 matches the moment picker.
    if duration <= 0:
        return 6
    return max(6, min(18, round(duration / 3)))


def _observe_clip(cands: list, gname: str, duration: float = 0.0) -> str:
    """Stage 1 (vision OBSERVER): describe ONLY what's literally on screen across
    the frames — setting, characters' appearance (no name-guessing), action and
    any on-screen text. This factual read is then handed to the captioner so it
    knows what's going on before it writes the line. Claude vision first, then the
    OpenAI vision fallback if Claude is unavailable."""
    from core import claude_code, openai_client

    n = len(cands)
    # Frames are spread evenly across the clip, so frame i sits at ~this timestamp. Telling
    # the observer WHEN each frame is lets it report the clip as a sequence, so the writer can
    # line the dialogue up with what is on screen instead of guessing.
    def _stamp(i: int) -> str:
        if duration <= 0:
            return f"frame {i + 1}"
        t = duration * (i + 0.5) / max(1, n)
        return f"frame {i + 1} at ~{int(t // 60)}:{int(t % 60):02d}"

    span = f" spanning about {int(duration // 60)}:{int(duration % 60):02d}" if duration > 0 else ""
    instruction = (
        f"These are {n} frames (in order) from ONE gameplay clip{span}, evenly spaced across "
        "it.\nDescribe ONLY what you can literally SEE — do not guess names or "
        "backstory. Cover, in 4-7 plain sentences:\n"
        "- SETTING/location (indoor lab, rooftop, street, snow, etc.), and SAY WHEN IT "
        "CHANGES — if the frames move from a fight to a corridor to a cabin, report that "
        "ORDER with the timestamps, because later frames are a LATER part of the clip.\n"
        "- CHARACTERS visible, by APPEARANCE only (e.g. 'man in a lab coat', 'figure "
        "in a red-and-blue spider suit', 'teen in a hoodie') — never assume who they "
        "are. Note which frames each one appears in.\n"
        "- The ACTION / what is happening or being done, in sequence.\n"
        "- Any on-screen TEXT, subtitles, objective markers, BOSS-BAR NAMES or UI you can "
        "read, with the frame it appears in.\n"
        "- SUMMARY, on its own line before TONE: 'SUMMARY: ' then ONE plain sentence of 5 to "
        "11 words saying who does what, where, as a viewer would put it (e.g. 'SUMMARY: A "
        "jet ski races through a canal toward a yacht'). Only what the frames show; no frame "
        "numbers, timestamps, markdown, or words like clip, frame, footage or scene.\n"
        "- TONE, as the last line: 'TONE: funny' only if something plainly silly visibly "
        "happens (a ragdoll or tumble that clearly was not meant, a botched jump or landing, "
        "a car flipping or crashing in a ridiculous way, a bystander's absurd reaction, "
        "physics chaos, a glitch, a goofy pose or line), and describe that mishap in the "
        "ACTION sentences above with its frames; otherwise 'TONE: serious' or 'TONE: "
        "neutral'. A story cutscene, a death or injury, a deliberate stunt and an ordinary "
        "crash in a chase or fight are NOT funny on their own, and the game's reputation for "
        "humour never makes a clip funny (Bryce, 2026-11-20).\n"
        "- ADULT, as the very last line: 'ADULT: yes' if any frame shows sexual activity "
        "(simulated sex, people having sex on a bed or floor, explicit sexual posing or "
        "grinding) or real nudity (exposed nipples or genitals, or a person wearing nothing); "
        "otherwise 'ADULT: no'. Swimwear of any cut (bikinis and thongs included), lingerie-like "
        "club outfits, a party, dancing, flirting or kissing on its own is 'ADULT: no'."
    )
    _who = _who_note(gname)
    if _who:   # the one naming exception: the game's playable leads (GTA 6, 2026-11-20)
        instruction += ("\n\nTHE ONE EXCEPTION to 'never assume who they are', for this game's "
                        "playable leads only: " + _who + " For each person, say whether the "
                        "player is visibly controlling them (name the on-screen cue) and, if so, "
                        "give their name; everyone else stays described by appearance.")
    listing = "\n".join(f"{_stamp(i)}: {p}" for i, p in enumerate(cands))
    claude_prompt = (
        f"Use the Read tool to open these frames first.\n\n{instruction}\n\n"
        f"Frames:\n{listing}"
    )
    # Without an observation every hook path is dead and the canned line ships, and the OpenAI
    # fallback has had no credit since 2026-07-31, so Claude gets a second try first (2026-11-23).
    for _try in range(2):
        try:
            return sanitize(claude_code.run(claude_prompt, allowed_tools="Read", timeout=180,
                                            model=_writer_model(),
                                            api_fallback_model=CONFIG.models.get("claude_model"))).strip()
        except claude_code.ClaudeCodeError as e:
            hard = bool(re.search(r"usage|limit|credit|auth|login|401|403", str(e), re.I))
            print(f"[content] observer: Claude unavailable ({e})"
                  + ("; retrying once." if not (_try or hard) else "; using OpenAI vision."),
                  flush=True)
            if hard:                       # a usage, credit or login error will not clear
                break
    # Still raises when this fails too: the fact-card writer (tools/lore_short.py) must refuse a
    # card it could not look at, never treat an empty read as "nothing adult on screen".
    return sanitize(openai_client.vision(instruction, cands)).strip()


def adult_on_screen(observation: str) -> bool:
    """True when the frame observer reported sexual activity or nudity ('ADULT: yes').
    Meta removes sexual activity and YouTube age-restricts it, so posts skip those moments
    (2026-11-21, after the GTA 6 recordings of that night included a hotel-suite sex scene)."""
    return bool(re.search(r"(?im)^\W*ADULT\W*:\W*yes\b", observation or ""))


def _transcribe_clip(video_path, gname: str = "") -> str:
    """Whisper transcript of the clip's spoken DIALOGUE, word-for-word (per user 2026-07-31),
    so the writer + critics know exactly WHO says WHAT — not just what a few frames show.
    Extracts a small mono audio track and transcribes it (biased by the game name for
    spelling). Fail-open to '' (silent/no-dialogue clips + any error don't block a post)."""
    import tempfile
    from pathlib import Path

    from core import elevenlabs, ffmpeg, openai_client
    try:
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "audio.mp3"
            # cap at 240s -> bounds cost (a reel is <=180s anyway); mono 16k mp3 = tiny.
            rc, _ = ffmpeg.run(["-i", str(video_path), "-t", "240", "-vn", "-ac", "1",
                                "-ar", "16000", "-b:a", "64k", str(a)], timeout=120)
            if rc != 0 or not a.exists() or a.stat().st_size < 1024:
                return ""
            # ElevenLabs Scribe first (better on non-speech — it annotates, doesn't invent),
            # then OpenAI Whisper. Either provider depleted just means no dialogue grounding.
            t = _clean_transcript(elevenlabs.speech_to_text(a))
            if not t:
                t = _clean_transcript(openai_client.transcribe(a, prompt=(gname or "").strip()))
            return sanitize(t).strip()
    except Exception as e:
        print(f"[content] transcribe failed ({e!r}); proceeding without dialogue.", flush=True)
        return ""


def _scan_subtitles(video_path, gname: str = "", max_strips: int = 120) -> str:
    """Read the ON-SCREEN SUBTITLES of the WHOLE clip, speaker labels included (per user
    2026-09-22 — a Wolverine hook said 'his ally' when the subtitles read 'Jean: ...'
    seven times; the observer's 4 frames missed every label). GAME-AGNOSTIC: crops the
    bottom band of every frame at ~1 fps, tiles the strips into contact sheets and has
    vision transcribe every subtitle line verbatim with its speaker name. The audio
    transcript can't give names; this can. Returns a formatted block ('' if the clip has
    no subtitles / on any error — fail-open, never blocks a post)."""
    import tempfile
    from pathlib import Path

    from core import ffmpeg
    try:
        dur = ffmpeg.duration(Path(video_path)) or 60.0
        fps = min(1.0, max_strips / dur)
        with tempfile.TemporaryDirectory() as tmp:
            pattern = str(Path(tmp) / "subs_%02d.jpg")
            # 2 columns x SUB_ROWS rows per sheet, read left->right, top->bottom.
            rc, _ = ffmpeg.run(["-i", str(video_path), "-an", "-vf",
                                f"fps={fps:.4f},{SUB_CROP},tile=2x{SUB_ROWS}",
                                "-q:v", "2", pattern], timeout=300)
            sheets = sorted(Path(tmp).glob("subs_*.jpg"))
            if rc != 0 or not sheets:
                return ""
            # 3 sheets per vision call, in parallel, re-joined in order.
            from concurrent.futures import ThreadPoolExecutor
            batches = [sheets[i:i + 3] for i in range(0, len(sheets), 3)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                lines = [ln for part in pool.map(lambda b: read_subtitle_sheets(b, gname), batches)
                         for ln in part]
    except Exception as e:
        print(f"[content] subtitle scan failed ({e!r}); proceeding without it.", flush=True)
        return ""
    rows, speakers = [], []
    for sp, tx in lines:
        rows.append(f"{sp}: {tx}" if sp != "?" else tx)
        if sp != "?" and sp not in speakers:
            speakers.append(sp)
    if rows:
        print(f"[content] subtitle scan: {len(rows)} line(s); speakers={speakers}", flush=True)
    return format_subtitles(rows, speakers)


# Bottom-centre band (76%-95% height, middle 60% width) where games put subtitles.
SUB_CROP = "crop=iw*0.6:ih*0.19:iw*0.2:ih*0.76,scale=800:-2"
# Strips per sheet column. 12 rows (24/sheet) got downscaled by the vision reader until faint
# text on hazy scenes was unreadable ("MK2 Sentinel:" missed, 2026-09-22); 6 rows reads it.
SUB_ROWS = 6


def read_subtitle_sheets(sheets: list, gname: str, what: str = "clip",
                         timeout: int = 420) -> list[tuple[str, str]]:
    """Vision-read contact sheets of subtitle strips (2 columns, read LEFT->RIGHT then
    TOP->BOTTOM, sheets in order). Returns [(speaker or '?', text)] verbatim. Raises on
    a vision/parse failure (callers fail open)."""
    from pathlib import Path

    from core import claude_code, openai_client
    instruction = (
        f"These {len(sheets)} image(s) are contact sheets of the SUBTITLE area of a "
        f"{gname} gameplay {what}, one strip per ~1s, read LEFT->RIGHT then TOP->BOTTOM, "
        "sheets in order. Transcribe EVERY distinct subtitle line you can read, in order, "
        "VERBATIM, including the SPEAKER LABEL before the colon exactly as printed (e.g. "
        "'Jean: Need a terminal.'). Merge repeats of the same line. Ignore HUD/UI, button "
        "prompts and objective text. ACCURACY over completeness: OMIT any line you can't read "
        "with certainty rather than guessing its words, and never guess a speaker that isn't "
        "printed — use '?' if a line has no label. If there are NO subtitles, return an empty "
        'list.\nReturn ONLY JSON: {"lines": [{"speaker": "Jean", "text": "Need a terminal."}]}'
    )
    sheets = [Path(s).resolve() for s in sheets]      # the CLI's cwd differs -> absolute paths
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(sheets))
    try:
        raw = claude_code.run(f"Use the Read tool to open these images first.\n\n"
                              f"{instruction}\n\nImages:\n{listing}",
                              allowed_tools="Read", timeout=timeout)
    except claude_code.ClaudeCodeError as e:
        print(f"[content] subtitle scan: Claude unavailable ({e}); OpenAI vision.", flush=True)
        raw = openai_client.vision(instruction, sheets)
    out = []
    for ln in (extract_json(raw) or {}).get("lines") or []:
        sp = sanitize(str(ln.get("speaker", "") or "?")).strip() or "?"
        tx = sanitize(str(ln.get("text", ""))).strip()
        if tx:
            out.append((sp, tx))
    return out


def caption_body_ok(body: str, hook: str, game: str = "") -> tuple[bool, str]:
    """Is this caption body worth posting? Blocks the filler and the duplicate-title case —
    a caption came back as just 'The Last of Us Part II 🍄', which compose_reel_caption then
    adds AGAIN as the game-title line (user, 2026-10-08)."""
    b = re.sub(r"[^\w ]", "", (body or "")).strip().lower()
    if not b:
        return False, "empty"
    if b in {"watch this clip", "wait for it", "gameplay"}:
        return False, "filler"
    if hook and b == re.sub(r"[^\w ]", "", hook).strip().lower():
        return False, "same as the hook"
    gname = re.sub(r"[^\w ]", "", (CONFIG.reels.get("game_names", {}) or {}).get(
        game, "") or game or "").strip().lower()
    # token subset, so "Spider-Man 2" is caught against "Marvel's Spider-Man 2"
    if gname:
        gt, bt = set(gname.split()), set(b.split())
        if bt and (bt <= gt or b in {gname, f"{gname} gameplay", f"{gname} clip"}):
            return False, "just the game title (compose adds that line already)"
    if len(b.split()) < 2:
        return False, "too short to be a caption"
    return True, ""


def format_subtitles(rows: list[str], speakers: list[str], what: str = "clip",
                     cap: int = 60) -> str:
    """The subtitle-evidence block handed to writers + critics ('' if no rows)."""
    if not rows:
        return ""
    return (f"ON-SCREEN SUBTITLES (read off the {what}, speaker labels VERBATIM — a name "
            f"before the ':' is WHO is speaking; these speakers are CONFIRMED present in the "
            f"{what} and MAY be named; a nickname inside a line is still not an "
            "identification):\n" + "\n".join(rows[:cap])
            + (f"\nCONFIRMED SPEAKERS: {', '.join(speakers)}" if speakers else ""))


def _with_subs(text: str, subs: str) -> str:
    """Append the subtitle-scan block to an observation/dialogue string."""
    return f"{text.strip()}\n\n{subs}".strip() if subs else text


# Whisper hallucinates these on silent / music-only / non-speech audio — treat as NO dialogue.
_STT_HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "please subscribe", "like and subscribe",
    "subscribe to my channel", "see you next time", "thank you", "thanks", "you", "bye",
    "thank you very much", "thank you so much",
}


def _clean_transcript(t: str) -> str:
    """Drop known STT hallucinations + pure non-speech annotations so only REAL dialogue
    reaches the hook writer. '' means no usable dialogue (hook the action instead)."""
    t = (t or "").strip()
    if not t:
        return ""
    if t.lower().strip(".!?, ") in _STT_HALLUCINATIONS:
        return ""
    if not re.sub(r"\[[^\]]*\]", "", t).strip():   # only "[walking]" / "[music]" etc. = no speech
        return ""
    return t


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
        "clip title that fits THIS clip's actual action. Examples (for shape only — do not "
        "reuse the wording or the action): \"Caught him mid-escape\", \"That takedown was "
        "clean\", \"This boss almost had me\".\n"
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


def _hook_and_caption(observation: str, game: str, gname: str, taglish: bool,
                      avoid: str = "", dialogue: str = "") -> tuple[str, str]:
    """From the observer's read + the clip's DIALOGUE + the game lore, write BOTH the
    scroll-stopping on-screen HOOK and the post caption, grounded in what THIS clip
    actually shows AND says. Returns (hook, caption). `avoid` feeds back a critic's
    rejection reason for a corrected retry; `dialogue` is the Whisper transcript."""
    from core import claude_code, lore

    brief = lore.lore_for(game)
    lore_block = (
        f"GAME STORY / CHARACTERS / PLACES (use this to identify the moment "
        f"correctly):\n{brief}\n\n" if brief else ""
    )
    dlg_block = (
        f"EXACT SPOKEN DIALOGUE in this clip (transcript — the STRONGEST evidence of "
        f"who/what this moment is about):\n\"{dialogue.strip()}\"\n\n" if dialogue.strip() else ""
    )
    cap_lang = "Natural Taglish is welcome." if taglish else "Write it in ENGLISH."
    fix = (f"A PREVIOUS attempt was REJECTED for a lore/accuracy error: {avoid}\n"
           "Fix it — write hook + caption that only reference what THIS clip actually "
           "shows. Fix it by REMOVING or making generic the unsupported claim — do NOT swap "
           "in a DIFFERENT character name unless a subtitle speaker label or unmistakable "
           "visual shows that exact character. A nickname in the dialogue ('Red', 'Kid', "
           "'Bub') is NOT an identification.\n\n" if avoid else "")
    prompt = (
        f"You are writing text for a {gname} gameplay reel. You are a MASTER of "
        "short-video viewer psychology and retention — your job is to stop the "
        "scroll in the first second.\n\n"
        f"WHAT'S ON SCREEN (an observer's factual description of THIS clip):\n"
        f"{observation}\n\n"
        f"{dlg_block}{lore_block}{fix}"
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
        "- THE TEST IT MUST PASS: if someone can watch two seconds, see that your line "
        "is simply TRUE, and scroll on satisfied, you wrote a caption, not a hook. It "
        "has to leave something unanswered that only watching settles. 'Spider-Man "
        "stops a getaway car by landing on it' went out on a real post and a viewer "
        "replied with an 'ok, obviously' GIF — never write that line (user, "
        "2026-10-12).\n"
        "- Take the SAME moment and find the angle the footage does not already "
        "answer: the choice behind it ('why land on the car instead of webbing it'), "
        "what it costs, who is about to regret it, or what the dialogue reveals that "
        "the action does not. Describing the action is the one thing the hook must "
        "not do — the video already does that.\n"
        "- Examples of the ENERGY (don't copy): \"This is why Otto can't be trusted\", "
        "\"Nobody talks about this combo\", \"He had one shot to not kill the driver\". "
        "Avoid hollow directives — a bare \"Watch what he does\" puts no weight behind "
        "the question and scores as filler.\n"
        "- FUNNY MOMENTS (Bryce, 2026-11-20): when the description's TONE says funny, play "
        "it for laughs. A dry, deadpan or mock-serious hook about the real silly thing beats "
        "a dramatic one (energy, don't copy: \"He had one job and it was the landing\", "
        "\"This NPC has seen enough for one day\", \"That landing was a choice\"). Still only the "
        "silliness the frames show; never invent a mishap for a joke.\n\n"
        "CAPTION (sits BELOW the video as the post caption):\n"
        "- ONE short clip-title line, 3 to 8 words, accurate to the moment.\n"
        f"- {cap_lang} No hashtags, no emojis, no quotes.\n\n"
        "GROUNDING — accuracy is NON-NEGOTIABLE (viewers call out lore mistakes):\n"
        "- BE BOLD and scroll-stopping — a strong curiosity gap is GOOD — but the tease MUST "
        "PAY OFF in THIS clip: only promise/imply something the footage actually delivers. "
        "Never invent an object, prop, weapon, food, vehicle, action, conflict, or event that "
        "isn't on screen just to bait a click or be funny — NOT 'why is Spider-Man pulling out a "
        "gun?' with no gun, NOT 'why are they fighting over a donut?' with no donut and no fight, "
        "NOT a made-up 'chase' or 'argument'. If the clip is just web-swinging or exploring, hook "
        "THAT (the traversal, the view, the speed) — never a fabricated premise. Bait the REAL "
        "payoff, hard.\n"
        "- Name a character ONLY if THIS clip actually shows or names them — a visible "
        "character in the description, OR an on-screen SUBTITLE that names the speaker. "
        "If a subtitle reads e.g. 'JOHNSON: ...', the one talking is JOHNSON; never credit "
        "a different character. A CONFIRMED SUBTITLE SPEAKER should be NAMED — don't write a "
        "vague 'his ally' / 'someone' when the subtitles show who it is.\n"
        "- Do NOT invoke an iconic character just because they're famous in this game. If "
        "they are not seen or heard in THIS clip, they are NOT in it — e.g. don't mention "
        "Cortana for an Operation-METEORITE / prequel mission she isn't part of and whose "
        "voice isn't in the clip.\n"
        "- Don't assert a story EVENT / plan / relationship the description doesn't support. "
        "When unsure who or what it is, hook the ACTION, the setting, or a gamer FEELING — "
        "never a guessed identity or plot point. Respect any 'DON'T CONFUSE' notes above.\n"
        "- USE THE DIALOGUE above as the source of truth for WHO and WHAT. The character you "
        "control/play is NOT necessarily who the moment is ABOUT — e.g. you may control Miles "
        "in a scene set inside PETER's mind; then it's PETER's inner conflict, not the player's. "
        "Whose name/mind/story the dialogue points to is who the hook is about — attribute by "
        "the DIALOGUE, never by the on-screen avatar. Don't write an ambiguous 'he/his own mind' "
        "when the dialogue makes the person explicit.\n\n"
        'Return ONLY this JSON: {"hook": "the on-screen hook", "caption": "the caption"}'
    )
    raw = _text(prompt, timeout=150, model=_writer_model())
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


def _verify_hook(hook: str, caption: str, observation: str, game: str = "",
                 dialogue: str = "") -> tuple[bool, str]:
    """Adversarial LORE/ACCURACY critic for the classic/triptych on-screen hook + caption:
    reject a CHARACTER not seen/heard in the clip, a subtitle attributed to the wrong
    speaker, a story event the observation doesn't support, or a wrong attribution the
    DIALOGUE contradicts. Returns (ok, issues). Fail-OPEN (ok=True) if the critic errors."""
    from core import lore
    brief = lore.lore_for(game) if game else ""
    lore_block = (f"GAME CONTEXT (use this to know WHO the player-character is + any "
                  f"first-person / naming notes):\n{brief}\n\n" if brief else "")
    dlg_block = (f"EXACT SPOKEN DIALOGUE (transcript — the strongest evidence of who/what "
                 f"this moment is about):\n\"{dialogue.strip()}\"\n\n" if dialogue.strip() else "")
    prompt = (
        "You are a STRICT lore/accuracy checker for a gameplay reel's ON-SCREEN hook + "
        "caption. Viewers publicly call out mistakes, so be rigorous.\n\n"
        f"{lore_block}{dlg_block}"
        f"OBSERVER'S FACTUAL READ OF THE CLIP (only what is actually visible/readable):\n"
        f"{observation}\n\n"
        + (f'HOOK: "{hook}"\nCAPTION: "{caption}"\n\n' if str(caption).strip() else
           f'HOOK: "{hook}"\n(There is no caption — judge the HOOK ALONE. A missing or empty '
           'caption is NOT a fault and must not count against the hook.)\n\n')
        +
        "Naming the game's established PLAYER-CHARACTER / protagonist is ALWAYS OK even if "
        "they aren't visible — MANY games are FIRST-PERSON, where you play as them but only "
        "see their weapon/hands (e.g. Halo's Master Chief; an alien-looking gun in the "
        "player's hands is a weapon they're HOLDING, not the character's identity). Only "
        "OTHER characters (companions, NPCs, villains) must actually be shown/heard.\n\n"
        "Mark it BAD if ANY of these are true:\n"
        "1. It names or clearly implies a NON-player CHARACTER the observation does NOT show "
        "or name (an iconic-but-ABSENT companion/NPC, e.g. crediting Cortana when she isn't "
        "seen/heard). Do NOT flag the established player-character just for being unseen.\n"
        "2. It contradicts an on-screen SUBTITLE speaker — e.g. the subtitle says 'JOHNSON:' "
        "but the text credits or implies a different character.\n"
        "3. It asserts a story EVENT / plan / relationship the observation doesn't support.\n"
        "4. It CONTRADICTS the DIALOGUE, or mis-attributes the moment. The character the player "
        "CONTROLS is NOT necessarily who the scene is about — if the dialogue shows it's set "
        "inside PETER's mind while the player is Miles, a hook saying the player 'fights himself "
        "in his own mind' is WRONG (it's Peter's). Flag ambiguous/mis-attributed 'he/his' when "
        "the dialogue names the actual person.\n"
        "5. It INVENTS a concrete OBJECT, prop, item, food, or vehicle that the observation does "
        "NOT mention — e.g. 'fighting over a DONUT', 'why is he holding a GUN', a 'briefcase', a "
        "'ring' — when no such thing is on screen. Bait the REAL footage, never a made-up object.\n"
        "6. It INVENTS an ACTION, conflict, or PARTICIPANTS the observation doesn't support — e.g. "
        "'why are THEY FIGHTING' when it's one character just swinging/traversing, or a 'chase' / "
        "'argument' / 'boss fight' that isn't happening. Web-swinging or exploring is NOT a fight.\n"
        "7. It turns a NICKNAME or partial name heard in dialogue ('Red', 'Kid', 'Bub', 'Chief', "
        "'Boss', 'Doc') into a specific named character (e.g. 'Red' -> Omega Red) when no subtitle "
        "speaker label or unmistakable visual shows who is being addressed. A nickname is NOT an "
        "identification.\n"
        "8. It gets the STORY BACKWARDS even though the individual words trace to a line of "
        "dialogue. Hold it against what the GAME CONTEXT above says these characters WANT and "
        "DO: a character described as doing the opposite of their established motive — a "
        "father who refuses to lose his son written as 'agreeing to let his son die', someone "
        "giving up on what the story shows them never giving up on — is a LORE ERROR, and the "
        "fact that a subtitle can be read that way does not save it (user, 2026-10-09).\n"
        "A hook about the ACTION THAT IS ACTUALLY SHOWN, the setting, or a general gamer feeling is "
        "FINE — but it must match what the observation describes.\n"
        "JUDGE SUBSTANCE, NOT WORDING (2026-11-23: good hooks were thrown out over word choice and "
        "the post fell back to a generic line). A fair everyday word for what the observation "
        "describes is SUPPORTED: smoke or steam from a hood = 'smoking hood'; a bandana over the "
        "face = 'masked'; driving calmly = 'calm'; a group cheering = 'cheering'. A question, a "
        "tease, a dry joke or a stake ('one wrong move...') is FINE when everything it takes for "
        "granted is on screen: a question's PREMISE is a claim ('why is he holding a gun' "
        "claims a gun; 'why is Jason robbing the store' claims a robbery). Mark BAD only for a claim that is INVENTED, CONTRADICTED, or "
        "given to the WRONG person (rules 1 to 8). Never mark BAD for being only 'partly' "
        "supported when every concrete thing in it is on screen or in the dialogue.\n"
        "IMPORTANT: your 'issues' text is fed back to the writer. ONLY say what is wrong. NEVER "
        "suggest who a character might be or propose a different name — that plants a NEW guess "
        "(a Sabretooth hook was once 'fixed' into an equally wrong Omega Red one this way).\n"
        'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=90))
        if not isinstance(d, dict) or "ok" not in d:
            raise ValueError("no verdict")
        return bool(d.get("ok")), str(d.get("issues", "")).strip()
    except Exception:
        return _critic_down("text critic")


def _plain_action_hook(observation: str, gname: str = "", avoid: str = "",
                       dialogue: str = "") -> str:
    """LAST-RESORT hook when both written attempts fail the accuracy critics. Built from the
    SAFEST evidence we have: first what a character actually SAYS (a subtitle line is quoted
    proof — per user 2026-10-02, a fallback described 'rainy street, glowing eyes' while the
    clip had Jean pleading 'Fight it, Logan!'), then what they DO. It only has to avoid
    INVENTING things, not avoid the story. '' on any error."""
    dlg = (f"WHAT IS SAID IN THE CLIP (transcript + subtitle speaker labels — a name before "
           f"':' is PROOF that character is in it and said that line):\n{dialogue.strip()}\n\n"
           if dialogue.strip() else "")
    prompt = (
        f"{dlg}An observer's factual read of a {gname or 'gameplay'} clip:\n{observation}\n\n"
        "Write ONE short on-screen hook, 4 to 8 words, that makes a scroller stop.\n"
        "BUILD IT FROM, IN THIS ORDER OF PREFERENCE:\n"
        "1. WHAT THE MOMENT IS ABOUT, taken from the dialogue — but in YOUR OWN WORDS. NEVER "
        "copy a line verbatim and never put a character's words in quotes: the hook is burned "
        "onto the video, and a quoted line can drag in profanity or threats that get the post "
        "age-restricted or demonetised. A subtitle 'Jean: Fight it, Logan!' becomes \"Jean is "
        "losing him to the rage\" — the same beat, re-angled. You MAY name a character whose "
        "SPEAKER LABEL appears above — that is confirmed.\n"
        "2. WHAT THEY DO — the action in the observation ('Claws out against three armoured "
        "soldiers', 'Cornered on a rooftop in the rain').\n"
        "3. Only if there is neither: the setting or mood.\n"
        "IT MUST READ LIKE A HOOK, NOT A DESCRIPTION. Grounded does NOT mean flat: a caption "
        "that merely lists what is on screen ('Plunging toward waterfall cliffs, clawing at "
        "purple robots mid-air') is a FAILURE — nobody stops scrolling for a label. Take the "
        "same true facts and give them TENSION, using one of these, which assert nothing "
        "extra:\n"
        "  - stakes already visible: 'No parachute, no plan, just claws'\n"
        "  - a question about what IS on screen: 'Why is Logan falling with the Sentinels?'\n"
        "  - second person, pointing at the moment: 'Watch what he does with the last one'\n"
        "  - a dry reaction to the situation: 'Commandeer a Banshee they said'\n"
        "  - the turn the dialogue sets up: 'Jean is losing him to the rage'\n"
        "Write the line a person would say about this moment, not the line a camera would.\n"
        "THE TEST: after reading it, the viewer should feel they will MISS something if they "
        "scroll past. Open a gap and let the clip close it — hint at what happens without "
        "stating it. If your line could be swapped onto any other clip from this game, or if "
        "it already tells the whole moment, it is not a hook yet: rewrite it.\n"
        "HARD RULES: invent NOTHING. No event, motive, relationship or outcome that the "
        "dialogue and observation don't plainly support — do not say a plea 'works', that "
        "someone 'wins', or why anyone acts. Do not name a character who has no speaker label "
        "and is not unmistakably on screen. A smaller true detail beats a bigger guess.\n"
        "Never generic: no 'watch this play', no 'you won't believe this'. A flat scenery "
        "line ('rainy street, glowing eyes') is a FAILURE — the clip's words or action almost "
        "always give you something better.\n"
        + (("SWEARING: a swear word is allowed when it is the point of the moment (it is starred "
            "out automatically, e.g. 'f**k'), but never a slur. Ordinary action words (kill, die, "
            "blood, hell) are FINE; don't tiptoe around the game.\n") if _swear_ok_name(gname) else
           ("ADVERTISER-SAFE: no profanity or censored profanity (f-word, s-word, 'wtf') and no "
            "slurs — if a line you're drawing on contains them, re-angle it without them. Ordinary "
            "action words (kill, die, blood, hell) are FINE; don't tiptoe around the game.\n")) +
        "ENGLISH. No hashtags, no emojis, no preamble — just the line."
        + (f"\nA PREVIOUS attempt was rejected: {avoid}\nFix THAT specific problem; keep using "
           "the dialogue and action, just drop the unsupported part." if avoid else "")
    )
    try:
        line = _strip_md(sanitize(_text(_with_who(prompt, gname), timeout=90, model=_writer_model())).strip().splitlines()[0])
        if line.count('"') % 2:        # a stray quote left by stripping one wrapper quote
            line = line.replace('"', "").strip()
        return line.strip(" ,;:-")[:90]
    except Exception:
        return ""


# Words that make a post advertiser-unfriendly or age-restricted on YouTube when they are
# BURNED ON SCREEN or sit in the caption (per user 2026-10-06: hooks were quoting subtitles
# verbatim, profanity and all). Matched whole-word, case-insensitive, incl. common censoring.
# PROFANITY AND SLURS ONLY. Ordinary action vocabulary — kill, die, dead, blood, hell — is
# fine for a gaming channel and is NOT filtered (user, 2026-10-06): the problem was never the
# word 'killin'', it was burning "Fuck the plan, let's get to killin'" on screen verbatim.
_UNSAFE_WORDS = (
    r"f+u+c+k\w*|f\*+c?k\w*|f#+\w*|fuk\w*|motherf\w+|wtf|stfu|"
    r"s+h+i+t\w*|sh\*+t\w*|bullshit|"
    r"b+i+t+c+h\w*|bastard\w*|asshole\w*|arsehole\w*|dumbass|jackass|"
    r"c+u+n+t\w*|whore\w*|slut\w*|rape\w*|retard\w*|f[a4]gg?\w*|n[i1]gg\w*"
)
_UNSAFE_RE = re.compile(rf"\b(?:{_UNSAFE_WORDS})\b", re.I)


def unsafe_terms(text: str) -> list[str]:
    """Advertiser-unfriendly words in `text` (on-screen hooks + captions). [] when clean."""
    seen, out = set(), []
    for m in _UNSAFE_RE.finditer(text or ""):     # group(0): the whole match, not a subgroup
        w = m.group(0)
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out


# SWEAR RULE, per game (Bryce, 2026-11-20, GTA 6 only for now): instead of rewording a hook or
# caption, star the swear word out ("f**k", "b**ch"), and beep only the spoken word in the audio
# (core/bleep.py). Slurs are never starred: they are still reworded by _make_safe.
_SLUR_RE = re.compile(r"\b(?:rape\w*|retard\w*|f[a4]gg?\w*|n[i1]gg\w*)\b", re.I)
_MASK_ROOTS = ("fuck", "shit", "bitch", "cunt", "ass")


def swear_rule_game(game: str) -> bool:
    """True when this game uses the star-and-beep rule (config reels.swear_rule.games)."""
    g = (CONFIG.reels.get("swear_rule", {}) or {})
    return bool(game) and str(game).strip().lower() in {str(x).lower() for x in (g.get("games") or [])}


def _with_who(prompt: str, gname: str) -> str:
    """Prompt plus the who-is-who note for games with fixed playable leads (GTA 6): the
    fallback writers otherwise only see the observation and their 'name nobody without a
    speaker label' rule (review 2026-11-20)."""
    w = _who_note(gname)
    return (prompt + "\n\nNAMING EXCEPTION, overrides any rule above about not naming "
            "characters: " + w) if w else prompt


def _who_note(gname: str) -> str:
    """core.lore.PLAYABLE note for a game known only by its display name ('Grand Theft Auto VI')."""
    from core import lore
    names = CONFIG.reels.get("game_names", {}) or {}
    for k, v in names.items():
        if str(v) == str(gname or "") and lore.playable_note(k):
            return lore.playable_note(k)
    return lore.playable_note(gname)


def _swear_ok_name(gname: str) -> bool:
    """swear_rule_game() for callers that only know the display name ('Grand Theft Auto VI')."""
    names = CONFIG.reels.get("game_names", {}) or {}
    return any(swear_rule_game(k) for k, v in names.items() if str(v) == str(gname or ""))


def swear_allowed(word: str) -> bool:
    """A swear word the rule lets through untouched, in text and audio (config
    reels.swear_rule.allow, matched as a root: 'shit' also covers 'bullshit', 'shitty')."""
    allow = [str(x).lower() for x in ((CONFIG.reels.get("swear_rule", {}) or {}).get("allow") or [])]
    w = str(word or "").lower()
    return any(a and a in w for a in allow)


def slur_terms(text: str) -> list[str]:
    return [m.group(0) for m in _SLUR_RE.finditer(text or "")]


def _mask_word(w: str) -> str:
    low = w.lower()
    for root in _MASK_ROOTS:
        i = low.find(root)
        if i >= 0:
            return w[:i + 1] + "**" + w[i + 3:]
    if len(w) <= 4:
        return w[0] + "*" * (len(w) - 2) + w[-1]
    return w[0] + "**" + w[3:]


def mask_swears(text: str) -> str:
    """'fuck' -> 'f**k', 'bitch' -> 'b**ch', 'bullshit' -> 'bulls**t'. Slurs are left for the
    rewrite gate. Idempotent ('f**k' stays 'f**k')."""
    return _UNSAFE_RE.sub(lambda m: m.group(0) if (_SLUR_RE.fullmatch(m.group(0))
                                                   or swear_allowed(m.group(0)))
                          else _mask_word(m.group(0)), text or "")


def apply_swear_rule(text: str, kind: str, game: str, gname: str = "") -> str:
    """The advertiser-safety gate for one hook/caption. Star-and-beep games get their swear words
    starred out; a slur still means a rewrite. Every other game keeps the rewrite gate as before."""
    if not text:
        return text
    if swear_rule_game(game):
        if slur_terms(text):
            return mask_swears(_make_safe(text, kind, gname, starred_ok=True) or "")
        return mask_swears(text)
    if unsafe_terms(text):
        return _make_safe(text, kind, gname) or ""
    return text


def _make_safe(text: str, kind: str, gname: str = "", starred_ok: bool = False) -> str:
    """Rewrite a hook/caption that trips the advertiser-safety gate, keeping the MEANING.
    Returns '' if it still isn't clean, so the caller can fall back rather than publish it.
    starred_ok (swear-rule games): only slurs must go; swear words get starred afterwards."""
    bad = slur_terms(text) if starred_ok else unsafe_terms(text)
    if not bad:
        return text
    print(f"[content] {kind} flagged as advertiser-unsafe ({', '.join(bad)}); rewriting.",
          flush=True)
    prompt = (
        f'This {kind} for a {gname or "gameplay"} video is not advertiser-friendly because of: '
        f'{", ".join(bad)}.\n\n"{text}"\n\n'
        "Rewrite it keeping the SAME meaning and energy, but with none of those words and no "
        "censored spellings. Swap graphic wording for impact wording: 'kills him' -> 'takes "
        "him down', 'everyone dies' -> 'nobody walks away', profanity -> drop it entirely. "
        "Same length or shorter. Return ONLY the rewritten line."
    )
    try:
        out = sanitize(_text(prompt, timeout=90)).strip().splitlines()[0].strip().strip('"')
    except Exception:
        return ""
    out = out.strip(" ,;:-")[:90]
    if not out or (slur_terms(out) if starred_ok else unsafe_terms(out)):
        print(f"[content] {kind} still unsafe after a rewrite — using a safe fallback.",
              flush=True)
        return ""
    print(f"[content] {kind} rewritten safe: {out}", flush=True)
    return out


# Words that give away text written ABOUT the footage rather than FOR the viewer. A hook is
# burned onto the video, so "The whole clip is set outdoors in an industrial shipping-yard"
# is never acceptable, no matter which stage produced it (user, 2026-10-08).
_META_RE = re.compile(
    r"\b(?:clips?|frames?|footage|screenshots?|videos?|scene is set|is set (?:in|at|outdoors)|"
    r"observer|subtitles?|on-screen text|the whole|throughout|depicts?|shown here|"
    r"this (?:short|reel|post)|descriptions?|literal(?:ly)?|summary|as requested|"
    r"here(?:'s| is| are)|the following)\b", re.I)


def hook_shape_ok(hook: str) -> tuple[bool, str]:
    """Is this usable as an ON-SCREEN hook? Deterministic guard applied to EVERY candidate,
    so a stage direction or an over-long description can never reach a post."""
    h = (hook or "").strip()
    if not h:
        return False, "empty"
    n = len(h.split())
    if n < 3:
        return False, f"too short ({n} words)"
    if n > 12:
        return False, f"too long for a hook ({n} words)"
    m = _META_RE.search(h)
    if m:
        return False, f"talks about the footage ('{m.group(0)}') instead of to the viewer"
    if h.endswith(":"):
        return False, "ends with a colon"
    return True, ""


def _has_verb_hint(clause: str) -> bool:
    """Rough check that a clause has a verb ('kneels', 'is', 'driving'), so a cut never leaves
    a bare noun phrase like 'A woman in black'. A heuristic: a plural noun can pass it."""
    words = [w.strip(".,;:!?\"'").lower() for w in clause.split()[1:]]
    aux = {"is", "are", "was", "were", "has", "have", "had", "gets", "can", "will"}
    # clothing and look words that end like verbs ('backwards cap and sunglasses')
    not_verbs = {"sunglasses", "glasses", "shorts", "pants", "jeans", "clothes", "trousers",
                 "boots", "shoes", "sneakers", "tattoos", "dreadlocks", "braids", "curls",
                 "lips", "eyes", "arms", "legs", "backwards", "towards", "upwards", "always"}
    # An '-ed' or '-ing' word before a noun is an adjective ('patterned shirt', 'flashing
    # lights'); as a verb it ends the clause or leads into an article or a preposition.
    lead = {"a", "an", "the", "to", "into", "onto", "on", "in", "at", "up", "down", "off",
            "out", "over", "away", "back", "his", "her", "their", "its", "by", "with", "from",
            "through", "across", "toward", "towards", "past", "around", "along", "and", ""}
    for i, w in enumerate(words):
        if w in aux:
            return True
        if len(w) <= 2 or w in not_verbs or "-" in w:
            continue
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if re.search(r"[^s]s$", w) or w.endswith("ing"):
            return True                    # 'kneels', 'driving fast', 'cops chasing Jason'
        if w.endswith("ed") and nxt in lead:
            return True                    # 'parked', 'walked into', not 'patterned shirt'
    return False


def _observation_hook(observation: str) -> str:
    """ABSOLUTE last resort before the canned line: restate the OBSERVER'S OWN first clause.
    No model call, so there is nothing to invent — the text is literally the ground truth the
    critics judge against. Beats 'You have to see this play', which kept reaching live posts
    when every written attempt was rejected (user, 2026-10-07)."""
    # 1) The observer's own SUMMARY line, written for exactly this (2026-11-23). Before it the
    # first sentence was taken, and the observer writes a markdown list ("1. **Setting:** The
    # whole clip is on open water...") with a preamble, so this rung returned "1" or a line
    # about "the whole clip" and never once shipped: the canned line went out instead.
    hs = _observation_hooks(observation)
    return hs[0] if hs else ""


def _observation_hooks(observation: str, limit: int = 4) -> list[str]:
    """Ranked on-screen lines taken from the observer's read: its SUMMARY line, then cleaned
    sentences from the ACTION part. They are model text, so the chain still runs the critics on
    each before one ships (review 2026-11-23: a SUMMARY can name the wrong lead)."""
    out: list[str] = []

    def _add(h: str) -> bool:
        if h and h.lower() not in {x.lower() for x in out}:
            out.append(h)
        return len(out) >= limit

    m = re.search(r"(?im)^\W*SUMMARY\W*:\s*(.+)$", observation or "")
    if m:
        h = _trim_clause(_clean_obs_text(m.group(1)))
        if h and hook_shape_ok(h)[0] and _add(h):
            return out
    # 2) Else the first cleaned sentence that is about the game, not about the footage, from
    # the ACTION part of the read first, then the rest.
    body = re.split(r"(?im)^\W*ON-SCREEN SUBTITLES", observation or "")[0]   # not the subs block
    lines = [ln for ln in body.splitlines()
             if ln.strip() and not re.match(r"^\W*(?:TONE|ADULT|SUMMARY)\W*:", ln, re.I)]
    sents = []                       # (0 for the ACTION part, sentence)
    for ln in lines:
        is_action = bool(re.match(r"^\W*(?:\d+[.)]\s*)?\W*action\b", ln, re.I))
        # quoted dialogue out before splitting: its own '!' and '.' cut sentences mid-quote
        ln = re.sub(r'"[^"]*"', lambda q: "" if re.search(r"[a-z]", q.group(0)) else q.group(0),
                    ln.replace("“", '"').replace("”", '"'))   # pairs, left to right
        for s in re.split(r"(?<=[.;!?])\s+", _clean_obs_text(ln)):
            is_act = is_action or bool(re.match(r"^(?:the )?action\b", s, re.I))
            sents.append((0 if is_act else 1, _clean_obs_text(s)))
    # "The action is ...", "3. **Action:** ..." first: that is where the observer says what
    # happens; scene-setting, cast lists and filming notes make flat, odd hooks.
    sents.sort(key=lambda p: p[0])
    good: list[tuple[int, int, str]] = []      # (action part?, no action verb?, line)
    for rank, sent in sents:
        sent = re.sub(r"^(?:the )?action (?:is|:)\s*", "", sent, flags=re.I)
        if re.search(r"\b(?:camera|shot|angle|close-up|overhead|setting|location|recurring|"
                     r"background|entire|single|opened|literally|people are|cutscene|cinematic|"
                     r"hud|health bar|minimap|ui|mood|tone|no mishap)\b", sent, re.I):
            continue                     # about the filming, the game's UI, cast or mood
        if re.search(r"\b(?:subtitles?|on-screen text|reads?|caption|objective)\b", sent, re.I):
            continue                                   # a report of on-screen text, not action
        sq = sent.replace("“", '"').replace("”", '"')
        if sq.count('"') % 2 or any(re.search(r"[a-z]", q) for q in re.findall(r'"([^"]*)"', sq)):
            continue                     # quoted dialogue, or a piece of it ('"POLICE" sign' is fine)
        h = _trim_clause(sent)
        if h and (h.count('"') + h.count("“") + h.count("”")) % 2:
            continue
        if h and hook_shape_ok(h)[0] and _has_verb_hint(h):
            # 'The pickup drives past...' before 'The driver is a man in a cap': a line with a
            # real action verb says what happens; an 'is' line only describes someone
            bare = re.sub(r"\b(?:is|are|was|were|has|have|had)\b", " ", h, flags=re.I)
            good.append((rank, 0 if _has_verb_hint(bare) else 1, h))
    for _, _, h in sorted(good, key=lambda g: (g[0], g[1])):
        if _add(h):
            break
    return out


def _clean_obs_text(text: str) -> str:
    """Observer prose without markdown, list numbers, section labels, frame references or a
    'These frames show' lead-in, so a sentence of it can stand as on-screen text."""
    t = re.sub(r"(\*\*|__|`)", "", text or "")
    t = re.sub(r"^\s*(?:[-*#>]+|\d+[.)])\s*", "", t)                      # list / heading marks
    t = re.sub(r"^\s*(?:setting|location|characters?|people|action|on-screen text|text|ui|"
               r"tone|scene|summary)\s*:\s+", "", t, flags=re.I)     # "Setting: ", not "Jason: "
    t = re.sub(r"\s*\((?=[^)]*(?:frame|\d|~))[^)]*\)", "", t, flags=re.I)  # "(frames 1, 6, ~0:01)"
    t = re.sub(r"^\s*(?:from|at|around|by)?\s*~?\d+:\d\d(?:\s*(?:to|-)\s*~?\d+:\d\d)?,?\s*", "",
               t, flags=re.I)                                            # "From 0:01 to 0:42 "
    t = re.sub(r"^(?:these frames?|the clip|this clip|the footage|the scene)\s+"
               r"(?:show|shows|depicts?|opens with)\s+", "", t.strip(), flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def _trim_clause(first: str) -> str:
    """One observer sentence cut to an on-screen line of at most 12 words."""
    first = (first or "").strip(" .;:,")
    if not first:
        return ""
    if len(first.split()) > 12:                      # prefer a clause boundary over a hard cut
        head = first.split(",")[0]
        if not (4 <= len(head.split()) <= 12 and _has_verb_hint(head)):
            # a joining word is the next best break: "A man in a striped shirt kneels and works
            # on an ankle monitor..." -> "A man in a striped shirt kneels", not "...on an ankle"
            # (2026-11-21)
            # Only a break that leaves 4 to 12 words: "A woman in black and white clothes" must
            # not become "A woman in black" (review 2026-11-21).
            head = ""
            for jm in re.finditer(r"\s+(?:and|while|as|before|after|then|but)\s+", first):
                if 4 <= len(first[:jm.start()].split()) <= 12:
                    cand = first[:jm.start()]
                    if _has_verb_hint(cand):
                        head = cand
                        break
        first = head if 4 <= len(head.split()) <= 12 else " ".join(first.split()[:12])
    # never end on a dangling function word ("stands over a")
    while first.split() and first.split()[-1].lower() in {
            "a", "an", "the", "on", "in", "at", "of", "to", "with", "over", "under", "and",
            "by", "for", "from", "into", "as", "his", "her", "their", "its"}:
        first = " ".join(first.split()[:-1])
    first = first.strip(" ,;:-")
    return ((first[0].upper() + first[1:])[:90] if first else "")


def _hookify_observation(observation: str, gname: str = "", avoid: str = "",
                         dialogue: str = "") -> str:
    """Turn the observer's description INTO a hook, reading like something written for a
    viewer rather than a stage direction. It is meant to add no fact, but a rewrite CAN
    invent one: on 2026-11-21 it put "Why is he fitting that monitor to a stranger's driveway
    plan?" on a TikTok draft (no driveway, no stranger's plan). So the caller now runs the
    same accuracy critics on it as on every other hook. '' on error."""
    dlg = (f"WHAT IS SAID IN THE CLIP (the strongest evidence of what the moment is about):\n"
           f"{dialogue.strip()}\n\n" if dialogue.strip() else "")
    prompt = (
        f"{dlg}A factual description of a {gname or 'gameplay'} clip:\n{observation}\n\n"
        "Rewrite the single most interesting thing in it as an ON-SCREEN HOOK for the video.\n"
        "- 4 to 9 words, present tense\n"
        "- use ONLY what the description states: no new objects, actions, names or outcomes\n"
        "- it must READ LIKE A HOOK, not a label. Listing what is on screen ('Plunging toward "
        "waterfall cliffs, clawing at purple robots mid-air') FAILS. Give the same facts "
        "tension: name the stakes ('No parachute, no plan, just claws'), ask about what is "
        "shown ('Why is he falling with them?'), or point at it ('Watch the last few seconds'). "
        "If the TONE line says funny, a dry deadpan line about the silly thing it describes "
        "works too ('That landing was a choice')\n"
        "- it must OPEN A CURIOSITY GAP: the viewer should feel they'll miss something by "
        "scrolling. Hint at what happens; never state the whole moment outright\n"
        "- write it TO the viewer, never ABOUT the video: never say clip, frames, footage, "
        "scene, 'the whole', 'is set in'. 'The whole clip is set in a shipping yard' is WRONG; "
        "'Cornered in a shipping yard at night' is right\n"
        "- every word must trace to the description or the dialogue above. Do not add a "
        "place, object, motive, owner or plan they do not state; a plainer true line beats "
        "a vivid made-up one\n"
        "- no hashtags, no emojis, no quotes, no preamble — just the line"
        + (f"\nA PREVIOUS attempt was rejected: {avoid}\nFix THAT specific problem."
           if avoid else "")
    )
    try:
        return _strip_md(sanitize(_text(_with_who(prompt, gname), timeout=90, model=_writer_model())).strip().splitlines()[0])[:90]
    except Exception:
        return ""


def _strip_md(line: str) -> str:
    """Drop markdown the model sometimes wraps a line in (**bold**, *italics*, `code`) —
    '**Williams calls the win before Chief fires**' reached a hook (user, 2026-10-08)."""
    t = (line or "").strip()
    t = re.sub(r"^\s*[#>\-\*\d.\)]+\s+", "", t)       # list/heading markers
    t = re.sub(r"(\*\*|__|[*_`])", "", t)
    return t.strip().strip('"').strip(" ,;:-")


def _verify_hooky(hook: str, gname: str = "", min_score: int = 5) -> tuple[bool, str]:
    """CURIOSITY gate for the FALLBACK hooks (per user 2026-10-08: 'hooks should induce
    curiosity and make the viewers watch'). Grounded fallbacks were coming out as stage
    directions — accurate and dead. Scored blind on a benchmark: stage directions and the
    canned line rate 2-3/10, real hooks 6-8/10, so 5 is the line. Fail-OPEN on error."""
    if not hook.strip():
        return False, "empty"
    prompt = (
        f'A {gname or "gameplay"} short burns this text across the top of the video:\n'
        f'"{hook}"\n\n'
        "You are a short-form editor. Would a cold scroller STOP for this line?\n"
        "A hook has tension, curiosity, stakes, a question, a dry joke, or points at "
        "something about to happen. A line that merely DESCRIBES what is on screen, like a "
        "stage direction or a shot list ('Claws out, one word said, against an explosion', "
        "'Plunging toward waterfall cliffs'), is NOT a hook — it labels the frame.\n"
        "THE TEST THAT MATTERS: if a viewer could watch two seconds, see that the line is "
        "simply TRUE, and scroll on satisfied, it is a caption, not a hook. It has to leave "
        "something unanswered that only watching settles. 'SPIDER-MAN STOPS A GETAWAY CAR BY "
        "LANDING ON IT' went out on a real post and a viewer replied with an 'ok, obviously' "
        "GIF — that line is a 2/10 and so is anything shaped like it (user, 2026-10-12).\n"
        "FUNNY CLIPS (Bryce, 2026-11-20, post the silly moments too): a deadpan setup for a "
        "mishap the viewer has not seen yet ('The ramp looked like a good idea', 'He had one "
        "job') IS a gap, because the payoff is watching it go wrong; score it like a question. "
        "A joke only fails if it gives the punchline away so there is nothing left to see.\n"
        "Score 0-3: states the visible action and nothing else. 4-5: a flicker of attitude "
        "but still answers itself. 6-7: opens a real gap — a question, a stake, a 'wait, "
        "why?'. 8-10: that gap plus a reason to keep watching to the end.\n"
        '- "is_hook": true/false   - "stop_score": 0-10   - "issues": what is missing if low\n'
        'Return ONLY JSON: {"is_hook": true, "stop_score": 7, "issues": ""}'
    )
    try:
        d = extract_json(_text(prompt, timeout=90)) or {}
        score = int(d.get("stop_score", 0) or 0)
        if bool(d.get("is_hook")) and score >= min_score:
            return True, ""
        return False, (f"reads as a description, not a hook ({score}/10): "
                       f"{str(d.get('issues', '')).strip()}")
    except Exception:
        return _critic_down("curiosity check")


def _plain_caption(observation: str, gname: str, hook: str, dialogue: str = "") -> str:
    """A caption to go WITH the plain fallback hook. The fallback used to reuse the hook text
    verbatim, so the post's hook and caption read identically (per user 2026-10-06). Same
    safe evidence, but a clip-title line that says something the hook doesn't. '' on error."""
    dlg = (f"WHAT IS SAID IN THE CLIP:\n{dialogue.strip()}\n\n" if dialogue.strip() else "")
    prompt = (
        f"{dlg}An observer's factual read of a {gname or 'gameplay'} clip:\n{observation}\n\n"
        f'The on-screen hook already says: "{hook}"\n\n'
        "Write the POST CAPTION: ONE short line, 3 to 8 words, Title Case. It is a LABEL for "
        "the moment — who, what and where — the way a clip is listed, e.g. 'Logan vs MK2 "
        "Sentinel, Wave 23', 'Ellie Tracks Down Nora in Seattle', 'Banshee Heist Under "
        "Fire'.\n"
        "The hook does the teasing; the caption just NAMES the scene. So:\n"
        "- do NOT repeat the hook's wording\n"
        "- do NOT claim an OUTCOME or a motive ('beats', 'wins', 'escapes', 'because he "
        "wants'). Captions keep getting rejected for exactly that. Name the confrontation, "
        "not how it ends.\n"
        "- use only what the dialogue and observation support; you may name a character whose "
        "subtitle SPEAKER LABEL appears above\n"
        "No hashtags, no emojis, no quotes, no preamble — just the line."
    )
    try:
        return _strip_md(sanitize(_text(_with_who(prompt, gname), timeout=90, model=_writer_model())).strip().splitlines()[0])[:90]
    except Exception:
        return ""


def _angle_caption(observation: str, gname: str, hook: str, dialogue: str = "",
                   avoid: str = "") -> str:
    """A caption from a DIFFERENT ANGLE than the hook, for when the scene-label caption keeps
    getting rejected for asserting something the footage doesn't show. It adds no new facts:
    it reacts, frames the stakes, or asks the viewer something. '' on error."""
    dlg = (f"WHAT IS SAID IN THE CLIP:\n{dialogue.strip()}\n\n" if dialogue.strip() else "")
    prompt = (
        f"{dlg}An observer's factual read of a {gname or 'gameplay'} clip:\n{observation}\n\n"
        f'The on-screen hook already says: "{hook}"\n\n'
        "Write the POST CAPTION. It must say something ELSE about this moment than the hook "
        "does — a different angle on the same clip:\n"
        "- what is at stake, or what this moment costs someone\n"
        "- an honest reaction to it (a dry joke, if the TONE line says funny)\n"
        "- a question to the viewer about it\n\n"
        "RULES:\n"
        "- ONE line, 5 to 16 words. Plain English, no Title Case\n"
        "- it must NOT repeat the hook's wording or simply restate the hook\n"
        "- add NO new facts. Everything it implies must already be in the hook, the dialogue "
        "or the observation above. A reaction or a question asserts nothing, which is why "
        "they are safe here\n"
        "- no outcome claims ('beats', 'escapes', 'dies'), no hashtags, no emojis, no quotes\n"
        + (f"\nA previous attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + "Just the line."
    )
    try:
        return _strip_md(sanitize(_text(_with_who(prompt, gname), timeout=90, model=_writer_model())).strip().splitlines()[0])[:120]
    except Exception:
        return ""


_HOOK_OPENER = re.compile(
    r"^(why (?:is|are|was|were|does|do|did)|what happens when|how (?:does|did|is|do)|"
    r"watch (?:how|what|as)|when |the moment )", re.I)

# A hook that ASKS something: an interrogative or an inverted auxiliary up front. Stripping
# these leaves a clause with no verb, so _recast_hook keeps a question whole.
_QUESTION_START = re.compile(
    r"^(?:why|how|what|who|whose|which|where|is|are|was|were|does|do|did|can|could|will|"
    r"would|should|has|have|had)\b", re.I)

# First words that are never a NAME, so they can be lowercased after "Watch closely:" /
# "Worth a rewind:" (a name such as Lucia keeps its capital).
_LOWER_OK = re.compile(
    r"^(?:why|how|what|who|whose|which|where|when|is|are|was|were|does|do|did|can|could|will|"
    r"would|should|has|have|had|he|she|they|it|we|you|this|that|these|those|there|nobody|"
    r"someone|everyone|no|one|the|a|an|his|her|their|its|watch|that's|it's|he's|she's)\b", re.I)

# "Why is he fitting X" -> "why he is fitting X": the same question as an embedded clause, so the
# caption says the hook's point in a different word order instead of repeating it (2026-11-21).
_SIMPLE_Q = re.compile(
    r"^((?i:why|how|what|where|who)) ((?i:is|are|was|were|has|have|can|will|would|could|"
    r"should)) ((?i:he|she|they|it|we|you|this|that)|[A-Z][a-z]+) (.+)$")


def _lower_first(text: str) -> str:
    return (text[0].lower() + text[1:]) if text and _LOWER_OK.match(text) else text


def _avoid_from_trace(limit: int = 6) -> str:
    """Every hook rejected so far in this call, with why, for the next writer. Each fallback
    used to see only the LAST reason, so it repeated an earlier mistake (2026-11-22: Lucia given
    a jet ski that Jason rides; 'cops' made from a line of dialogue, twice)."""
    rows = [r for r in LAST_HOOK_TRACE.get("attempts", []) if not r.get("ok") and r.get("hook")]
    if not rows:
        return ""
    keep = rows if len(rows) <= limit else rows[:2] + rows[-(limit - 2):]   # the first two teach most
    return "\n".join(f'- "{r["hook"]}": {str(r.get("why", ""))[:260]}' for r in keep)


CANDIDATE_COUNT = 8          # hooks written in one call by the candidate batch
CANDIDATE_BUDGET_S = 600     # stop checking candidates after this long; later rungs remain
# The whole hook chain stops starting optional rungs this long after it began (review
# 2026-11-23: worst case was unbounded against the 45-minute TikTok job). One checked candidate
# can take about 6 minutes when calls time out, hence the 300 to 400 s margins below. The flat
# observer line always runs, so time running out never means the canned line on its own.
HOOK_CHAIN_BUDGET_S = 1200
_CHAIN_T0 = [0.0]


def _time_left() -> float:
    import time
    if not _CHAIN_T0[0]:
        return float(HOOK_CHAIN_BUDGET_S)
    return HOOK_CHAIN_BUDGET_S - (time.monotonic() - _CHAIN_T0[0])


def _hook_candidates(observation: str, game: str, gname: str, dialogue: str = "",
                     n: int = CANDIDATE_COUNT) -> list[str]:
    """Several DIFFERENT on-screen hooks in one writer call, told every rejection so far.
    [] on error."""
    from core import lore
    brief = lore.lore_for(game)
    rejected = _avoid_from_trace(limit=8)
    prompt = (
        f"Write {n} DIFFERENT on-screen hooks for a {gname} gameplay reel. Each is burned on "
        "the video's top bar and must make a scroller stop.\n\n"
        f"WHAT IS ON SCREEN (an observer's factual read):\n{observation}\n\n"
        + (f"WHAT IS SAID IN THE CLIP:\n{dialogue.strip()}\n\n" if dialogue.strip() else "")
        + (f"GAME CONTEXT:\n{brief}\n\n" if brief else "")
        + (f"ALREADY REJECTED BY THE FACT-CHECKER (never repeat these mistakes):\n{rejected}\n\n"
           if rejected else "")
        + "RULES:\n"
        "- 4 to 10 words each. ENGLISH. No hashtags, emojis or quotes.\n"
        "- Every concrete thing a hook mentions (person, object, action, place) must be in "
        "the read or the dialogue above. Name Jason or Lucia only as the game context allows. "
        "Never turn a line of dialogue into an event, and never give a line to a speaker the "
        "clip does not show saying it.\n"
        "- Each must open a curiosity gap: a question about what is shown, a stake already "
        "on screen, a dry deadpan setup, or the turn the dialogue sets up. A line a viewer "
        "can confirm in two seconds and scroll past is a caption, not a hook. No hollow "
        "directives ('watch what he does', 'you have to see this').\n"
        "- Make them truly different: different angles, not rewordings of one idea. Put the "
        "safest strong one first.\n"
        f'Return ONLY JSON: {{"hooks": ["...", "..."]}} with {n} items.'
    )
    try:
        d = extract_json(_text(_with_who(prompt, gname), timeout=150, model=_writer_model())) or {}
        out = []
        for h in d.get("hooks", []) or []:
            h = _strip_md(sanitize(str(h))).strip().strip('"')[:90]
            if h and h.lower() not in {x.lower() for x in out}:
                out.append(h)
        return out[:n]
    except Exception as e:
        print(f"[content] candidate hooks failed ({e!r}).", flush=True)
        return []


def _check_candidate(h: str, observation: str, game: str, gname: str, dialogue: str,
                     cands: list) -> tuple[bool, str]:
    """The full gate for one candidate, cheapest check first: shape, curiosity (one text
    call), then the text and vision accuracy critics."""
    oks, whys = hook_shape_ok(h)
    if not oks:
        return False, whys
    okh, whyh = _verify_hooky(h, gname, min_score=6)
    if not okh:
        return False, whyh
    okt, whyt = _verify_hook(h, "", observation, game, dialogue=dialogue)
    if not okt:
        return False, whyt or "lore mismatch"
    okv, whyv = _verify_hook_vision(h, "", cands, gname, dialogue=dialogue)
    if not okv:
        return False, whyv or "hook not supported by the footage"
    return True, ""


def _best_candidate(observation: str, game: str, gname: str, dialogue: str,
                    cands: list) -> tuple[str, bool, str]:
    """(hook, True, '') for the first candidate that passes every gate, else ('', False, why)."""
    import time
    t0 = time.monotonic()
    hooks = _hook_candidates(observation, game, gname, dialogue)
    print(f"[content] candidate batch: {len(hooks)} hook(s) to check.", flush=True)
    why = "no candidates written"
    for h in hooks:
        if time.monotonic() - t0 > CANDIDATE_BUDGET_S - 360 or _time_left() < 400:
            why = "candidate time budget used up"
            break
        ok, why = _check_candidate(h, observation, game, gname, dialogue, cands)
        _trace_add("candidate", h, ok, why)
        if ok:
            print(f"[content] candidate passed: {h}", flush=True)
            return h, True, ""
    return "", False, why


# What the LAST hook_and_caption_from_video call saw and tried (observation, dialogue, every
# candidate hook with its verdict, the path that won). The reel runner saves it as
# hook_trace.json in the run folder, so a bad hook can be traced (Bryce, 2026-11-21: the
# observation behind a made-up hook had not been kept anywhere).
LAST_HOOK_TRACE: dict[str, Any] = {}


def _trace_add(stage: str, hook: str, ok: bool, why: str = "", caption: str = "") -> None:
    row = {"stage": stage, "hook": hook or "", "ok": bool(ok), "why": (why or "")[:600]}
    if caption:
        row["caption"] = caption
    LAST_HOOK_TRACE.setdefault("attempts", []).append(row)


def _recast_hook(hook: str) -> str:
    """ABSOLUTE LAST RESORT: the hook's own point, worded differently and from a 'what to
    watch' angle. Never word-for-word the hook (user, 2026-10-09), and it adds no claim the
    hook has not already made — so it cannot fail the accuracy critics."""
    raw = re.sub(r"\s+", " ", (hook or "").strip()).strip('"“” ')
    h = raw.rstrip("?.!… ")
    if not h:
        return ""
    # A QUESTION never loses its opener: cutting "Why is" off one left no verb, and "Why is he
    # fitting that monitor..." became "Worth a rewind: he fitting that monitor..." on a TikTok
    # draft (2026-11-21). A simple one is turned into a clause ("why he is fitting..."); any
    # other is pointed at whole.
    if raw.endswith("?") or re.match(r"(?:why|how) (?:is|are|was|were|does|do|did)\b", h, re.I):
        sq = _SIMPLE_Q.match(h)
        if sq:
            wh, aux, subj, rest = sq.groups()
            line = f"Worth a rewind to see {wh.lower()} {_lower_first(subj)} {aux.lower()} {rest}."
            if len(line) <= 120:
                return line
        line = f"Watch closely: {_lower_first(h)}?"
        return line if len(line) <= 120 else line[:116].rsplit(" ", 1)[0] + "...?"
    m = _HOOK_OPENER.match(h)
    core = (h[m.end():] if m else h).strip().rstrip(",;:")
    if not core:
        return ""
    line = f"Worth a rewind: {_lower_first(core)}."   # a NAME keeps its capital
    return line if len(line) <= 120 else line[:117].rsplit(" ", 1)[0] + "."


def _verify_hook_vision(hook: str, caption: str, cands: list, gname: str = "",
                        dialogue: str = "") -> tuple[bool, str]:
    """VISION critic (per user 2026-07-30): re-check the on-screen HOOK against the ACTUAL
    clip FRAMES + the spoken DIALOGUE — not just the text observation — so it catches a
    FABRICATED premise (e.g. 'a gun' when none is shown) AND a mis-attribution the dialogue
    contradicts (e.g. crediting the controlled character for another character's moment).
    Returns (ok, issues). Fail-OPEN (ok=True) if vision is unavailable — never blocks a post
    on a transient error, only on a confident rejection. Claude vision first, OpenAI fallback."""
    from core import claude_code, openai_client
    if not hook or not cands:
        return True, ""
    dlg = (f'\nEXACT SPOKEN DIALOGUE in the clip (transcript): "{dialogue.strip()}"\n'
           if dialogue.strip() else "")
    instruction = (
        f"You are a STRICT accuracy checker for a {gname} gameplay reel's ON-SCREEN hook. "
        "These are frames from the ACTUAL clip.\n\n"
        + (f'ON-SCREEN HOOK: "{hook}"\nPOST CAPTION: "{caption}"\n{dlg}\n' if str(caption).strip()
           else f'ON-SCREEN HOOK: "{hook}"\n(No caption — judge the HOOK ALONE; a missing '
                f'caption is NOT a fault.)\n{dlg}\n')
        +
        "Judge from what is literally visible in these frames AND what the dialogue says. Mark "
        "it BAD if the hook's central claim/premise is NOT supported — e.g. it claims an OBJECT "
        "(a gun/weapon), an ACTION, or a CHARACTER that does not actually appear, OR it "
        "MIS-ATTRIBUTES the moment (the dialogue shows it's about/inside a DIFFERENT character "
        "than the one being played — e.g. inside Peter's mind while controlling Miles). "
        "Clickbait/curiosity is fine ONLY if TRUE to what's shown/said; a hook about the visible "
        "action, setting, or mood is fine. Be suspicious of props a character wouldn't use "
        "(Spider-Man does not use guns).\n"
        "Judge substance, not wording: a fair everyday word for what is visible ('masked' for a "
        "bandana over the face, 'smoking' for smoke or steam) is supported. A question's premise "
        "is a claim ('why is he holding a gun' claims a gun). BAD only for an invented, "
        "contradicted or mis-attributed claim.\n"
        + (f"{_who_note(gname)} So naming the controlled lead is CORRECT, never a fault.\n"
           if _who_note(gname) else "")
        + 'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(cands))
    try:
        raw = claude_code.run(
            f"Use the Read tool to open these frames first.\n\n{instruction}\n\nFrames:\n{listing}",
            allowed_tools="Read", timeout=180)
    except claude_code.ClaudeCodeError as e:
        print(f"[content] vision hook-check: Claude unavailable ({e}); trying OpenAI vision.", flush=True)
        try:
            raw = openai_client.vision(instruction, cands)
        except Exception:
            return _critic_down("vision critic")   # fails open outside the hook chain
    except Exception:
        return _critic_down("vision critic")
    try:
        d = extract_json(raw)
        if not isinstance(d, dict) or "ok" not in d:
            raise ValueError("no verdict")
        return bool(d.get("ok")), str(d.get("issues", "")).strip()
    except Exception:
        return _critic_down("vision critic")


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


# ---- self-describing DRAFT filenames (per user 2026-07-30) --------------------------
# B2 draft files are named <platform>_<game>_<format>_<keyword>_<NZ stamp>.<ext>, e.g.
# ig_spider-man2_triptych_rooftop_20260730-221553.mp4 — so a glance tells you the game,
# format, a footage keyword (location/action), and WHEN it was sent (NZ local time).
_FOOTAGE_KEYWORDS = [
    "rooftop", "street", "subway", "bridge", "harbor", "dock", "pier", "park", "alley",
    "skyscraper", "tower", "construction", "museum", "lab", "hospital", "school", "warehouse",
    "factory", "train", "highway", "beach", "boardwalk", "carnival", "interior", "cutscene",
    "night", "rain", "storm", "snow", "sunset", "chase", "swing", "dive", "freefall", "glide",
    "fight", "boss", "brawl", "stealth", "takedown", "ambush", "escape", "rescue", "battle",
    "vortex", "portal", "hunter", "symbiote", "venom", "kraven", "lizard", "stakeout", "gadget",
    "web", "perch", "skydive", "downtown", "harbor", "sewer", "prison", "arena",
]


def footage_keyword(*texts: str, fallback: str = "clip") -> str:
    """One lowercase location/action keyword from the clip's caption/hook (for the draft
    filename). Curated vocab first (prefix match, so swing/swings/swinging all hit), else
    the first salient non-stopword, else `fallback`."""
    blob = re.sub(r"#\w+", " ", " ".join(str(t or "") for t in texts)).lower()
    for kw in _FOOTAGE_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}", blob):
            return kw
    stop = {"the", "and", "that", "this", "with", "for", "was", "just", "live", "while", "when",
            "across", "city", "game", "gameplay", "spider", "spiderman", "marvel", "marvels",
            "from", "into", "your", "have", "been", "they", "them", "their", "what", "does",
            "did", "almost", "something", "watch", "wait", "here"}
    for w in re.findall(r"[a-z]{4,}", blob):
        if w not in stop:
            return w
    return fallback


def draft_stamp() -> str:
    """Draft-filename timestamp in NZ LOCAL time (the user's tz), %Y%m%d-%H%M%S — so it
    reads right no matter where the render ran (local PC or a UTC CI runner)."""
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Pacific/Auckland")).strftime("%Y%m%d-%H%M%S")
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y%m%d-%H%M%S")


def draft_filename(platform: str, game: str, fmt: str, keyword: str, ext: str = "mp4") -> str:
    """<platform>_<game>_<format>_<keyword>_<NZ stamp>.<ext>."""
    kw = re.sub(r"[^a-z0-9]+", "-", (keyword or "clip").lower()).strip("-") or "clip"
    return f"{platform}_{game}_{fmt}_{kw}_{draft_stamp()}.{ext}"


def hook_and_caption_from_video(
    video_path, game: str = "", taglish: bool = False, with_game_title: bool = False
) -> tuple[str, str]:
    """REVIEW a gameplay clip and write BOTH the on-screen hook and the caption,
    grounded in what the clip shows + the game's lore. One OBSERVER call shared
    by both, then one psychology-driven WRITER call. Returns (hook, caption);
    each falls back to a safe line. Caption already includes its hashtags.
    The critics fail CLOSED and the chain runs on a clock while it works (2026-11-23)."""
    import time
    global _STRICT_CRITICS
    prev = _STRICT_CRITICS
    _STRICT_CRITICS, _CHAIN_T0[0] = True, time.monotonic()
    try:
        return _hook_and_caption_from_video(video_path, game, taglish, with_game_title)
    finally:
        _STRICT_CRITICS, _CHAIN_T0[0] = prev, 0.0


def _hook_and_caption_from_video(
    video_path, game: str = "", taglish: bool = False, with_game_title: bool = False
) -> tuple[str, str]:
    import tempfile
    from pathlib import Path

    from core import ffmpeg, frames

    hook, line = "", ""
    observation, dialogue = "", ""
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
    LAST_HOOK_TRACE.clear()
    LAST_HOOK_TRACE.update({"game": game, "clip": str(video_path), "path": "none",
                            "attempts": []})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _dur = ffmpeg.duration(Path(video_path))
            cands = frames.extract_candidates(Path(video_path), Path(tmp),
                                              n=observe_frame_count(_dur))
            if cands:
                gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
                observation = _observe_clip(cands, gname, _dur)
                # DIALOGUE (per user 2026-07-31): transcribe the clip's actual spoken words so
                # the writer + critics know WHO says WHAT — e.g. a scene set inside PETER's mind
                # while you CONTROL Miles must be about Peter, not the controlled character.
                dialogue = _transcribe_clip(video_path, gname)
                # SUBTITLES (per user 2026-09-22): full-clip speaker-label scan, so a
                # 'Jean: ...' line names Jean instead of a vague 'his ally'. Fed to the
                # writer + BOTH critics (observation + dialogue).
                subs = _scan_subtitles(video_path, gname)
                observation = _with_subs(observation, subs) if observation else observation
                dialogue = _with_subs(dialogue, subs)
                LAST_HOOK_TRACE.update({"observation": observation, "dialogue": dialogue,
                                        "frames": len(cands)})
                if observation:
                    hook, line = _hook_and_caption(observation, game, gname, taglish, dialogue=dialogue)
                    # ACCURACY GATE (two critics): (1) TEXT lore critic — invented character /
                    # wrong subtitle speaker / unshown story event; (2) VISION critic that
                    # re-checks the hook against the ACTUAL FRAMES, catching a FABRICATED premise
                    # the text read missed (e.g. "Why is Spider-Man pulling out a gun?" when no
                    # gun is on screen — flagged by user 2026-07-30). Both also get the DIALOGUE.
                    # Regenerate once, feeding the reason back; else fall back to a safe hook.
                    def _check_hook(h: str, l: str) -> tuple[bool, str]:
                        if not h:
                            return False, "empty hook"
                        oks, whys = hook_shape_ok(h)      # cheap, before any model call
                        if not oks:
                            return False, whys
                        ok1, i1 = _verify_hook(h, l, observation, game, dialogue=dialogue)
                        if not ok1:
                            return False, i1 or "lore mismatch"
                        ok2, i2 = _verify_hook_vision(h, l, cands, gname, dialogue=dialogue)
                        if not ok2:
                            return False, i2 or "hook not supported by the footage"
                        # CURIOSITY, not just accuracy. This gate only ran on the FALLBACK
                        # hooks, so a perfectly accurate description sailed through the
                        # primary path: "SPIDER-MAN STOPS A GETAWAY CAR BY LANDING ON IT"
                        # went live on IG and a viewer replied with an "ok, obviously" GIF
                        # (user, 2026-10-12). The written hook is held HIGHER than the
                        # fallbacks: it has the whole clip and the dialogue to work with.
                        ok3, i3 = _verify_hooky(h, gname, min_score=6)
                        if not ok3:
                            return False, i3 or "accurate, but it is not a hook"
                        return True, ""

                    ok, issues = _check_hook(hook, line)
                    _trace_add("written", hook, ok, issues, caption=line)
                    if ok:
                        LAST_HOOK_TRACE["path"] = "written"
                    else:
                        # Drop the rejected pair NOW: if a later call raised, the except below
                        # used to ship this hook the critics had just turned down (review 2026-11-21).
                        hook, line = "", ""
                        print(f"[content] hook rejected ({issues}); regenerating.", flush=True)
                        h2, l2 = _hook_and_caption(observation, game, gname, taglish, avoid=issues, dialogue=dialogue)
                        ok2, i2 = _check_hook(h2, l2)
                        _trace_add("written retry", h2, ok2, i2, caption=l2)
                        if ok2:
                            hook, line = h2, l2
                            LAST_HOOK_TRACE["path"] = "written retry"
                        else:
                            # Both attempts failed the accuracy critics. Rather than the canned
                            # line (per user 2026-09-30 — it kept showing up on real posts), ask
                            # for ONE plain hook describing only the VISIBLE ACTION: no names, no
                            # story claims, so there is almost nothing left to get wrong.
                            print(f"[content] 2nd hook also rejected ({i2}); writing a plain "
                                  "action hook.", flush=True)
                            # Judge the plain hook ALONE. Passing the failed attempt's caption
                            # made the critics reject the HOOK for the CAPTION's errors ("the
                            # caption misquotes the line..."), which is why the canned line kept
                            # reaching TikTok. The stale caption is dropped either way — it was
                            # just judged wrong, so it must not be published.
                            def _check_fallback(h: str) -> tuple[bool, str]:
                                """Accurate AND actually a hook — a grounded stage direction
                                is a failure here (user, 2026-10-08)."""
                                if not h:
                                    return False, "empty hook"
                                oka, ia = _check_hook(h, "")
                                if not oka:
                                    return False, ia
                                return _verify_hooky(h, gname)

                            # CANDIDATE BATCH (2026-11-23): two of five hooked Instagram reels
                            # shipped the canned line, because each fallback wrote ONE line that
                            # repeated the last one's mistake. Now one call writes several
                            # different hooks that know every rejection so far, and each is
                            # checked in turn, so one weak idea no longer sinks the reel.
                            h3, ok3, i3 = _best_candidate(observation, game, gname, dialogue,
                                                          cands)
                            src3 = "candidate"
                            if not ok3 and _time_left() > 400:
                                src3 = "plain action"
                                h3 = _plain_action_hook(observation, gname,
                                                        avoid=_avoid_from_trace(),
                                                        dialogue=dialogue)
                                ok3, i3 = _check_fallback(h3)
                                _trace_add("plain action", h3, ok3, i3)
                                if h3 and not ok3 and _time_left() > 400:   # one corrective retry
                                    print(f"[content] plain hook rejected ({i3}); retrying "
                                          "tighter.", flush=True)
                                    h3b = _plain_action_hook(observation, gname,
                                                             avoid=_avoid_from_trace(),
                                                             dialogue=dialogue)
                                    if h3b:
                                        ok3b, i3b = _check_fallback(h3b)
                                        _trace_add("plain action retry", h3b, ok3b, i3b)
                                        if ok3b:
                                            h3, ok3 = h3b, True
                                        else:
                                            i3 = i3b
                            if ok3:
                                # A caption of its OWN (reusing the hook made the post's hook
                                # and caption identical); falls back to the safe default line
                                # if it can't be written or doesn't pass the critics.
                                hook = h3
                                LAST_HOOK_TRACE["path"] = src3
                                # Judge the caption ON ITS OWN (as a pair with the hook, one
                                # weak half sank both and the post fell back to "Watch this
                                # clip" — user, 2026-10-07), and say WHY when it fails.
                                def _cap_ok(c: str) -> tuple[bool, str]:
                                    okb, whyb = caption_body_ok(c, h3, game)
                                    if not okb:
                                        return False, whyb
                                    return _verify_hook(c, "", observation, game,
                                                        dialogue=dialogue)

                                cap3 = _plain_caption(observation, gname, h3, dialogue)
                                okc3, cwhy = _cap_ok(cap3)
                                if not okc3:
                                    print(f"[content] plain caption rejected ({cwhy}); "
                                          "retrying.", flush=True)
                                    cap3b = _plain_caption(observation, gname, h3, dialogue)
                                    okc3b, cwhy2 = _cap_ok(cap3b)
                                    if okc3b:
                                        cap3, okc3 = cap3b, True
                                    else:
                                        cwhy = cwhy2
                                line = cap3 if okc3 else ""
                                print(f"[content] {src3} hook: {h3}"
                                      + (f" | caption: {cap3}" if okc3 else
                                         f" | caption: (safe default — {cwhy})"), flush=True)
                            else:
                                # Still nothing. Three last resorts, in order. EVERY line that a
                                # model wrote faces the same two accuracy critics as the first
                                # hook: the observation rewrite used to skip them and put "Why is
                                # he fitting that monitor to a stranger's driveway plan?" on a
                                # TikTok draft (2026-11-21; no driveway, no stranger's plan).
                                def _check_last(h: str) -> tuple[bool, str]:
                                    if not h:
                                        return False, "empty hook"
                                    oks, whys = hook_shape_ok(h)
                                    if not oks:
                                        return False, whys
                                    okt, it = _verify_hook(h, "", observation, game,
                                                           dialogue=dialogue)
                                    if not okt:
                                        return False, it or "lore mismatch"
                                    okv, iv = _verify_hook_vision(h, "", cands, gname,
                                                                  dialogue=dialogue)
                                    if not okv:
                                        return False, iv or "hook not supported by the footage"
                                    return _verify_hooky(h, gname)

                                def _accurate(h: str) -> tuple[bool, str]:
                                    """Text and vision critics only (no curiosity bar)."""
                                    okt, it = _verify_hook(h, "", observation, game,
                                                           dialogue=dialogue)
                                    if not okt:
                                        return False, it or "lore mismatch"
                                    okv, iv = _verify_hook_vision(h, "", cands, gname,
                                                                  dialogue=dialogue)
                                    return (True, "") if okv else (
                                        False, iv or "hook not supported by the footage")

                                h4, path4 = "", ""
                                # The observer's own lines (its SUMMARY, then ACTION sentences).
                                # Model text too, so each meets the critics (review 2026-11-23: a
                                # SUMMARY can name the wrong lead).
                                obs_lines = _observation_hooks(observation)
                                checked: dict[str, tuple[bool, str]] = {}

                                def _obs_ok(h: str) -> tuple[bool, str]:
                                    if h not in checked:
                                        checked[h] = _accurate(h)
                                    return checked[h]

                                # (1) an observer line that already reads as a hook
                                for obs in obs_lines[:2]:
                                    okh, whyh = _verify_hooky(obs, gname)
                                    oko, whyo = _obs_ok(obs) if okh else (False, whyh)
                                    _trace_add("observation", obs, oko, whyo)
                                    if oko:
                                        h4, path4 = obs, "observation"
                                        break
                                # (2) a rewrite of it INTO a hook, gated like every hook.
                                if not h4:
                                    why4 = ""
                                    for _try in range(2):
                                        if _time_left() < 300:
                                            break
                                        cand = _hookify_observation(observation, gname,
                                                                    avoid=_avoid_from_trace(),
                                                                    dialogue=dialogue)
                                        okr, why4 = _check_last(cand)
                                        _trace_add("observation rewrite", cand, okr, why4)
                                        if okr:
                                            h4, path4 = cand, "observation rewrite"
                                            break
                                # (3) an observer line even if it reads flat: a dull TRUE line
                                # beats a vivid FALSE one and beats the canned line. Always runs,
                                # whatever the clock says: it is the last thing before canned.
                                if not h4:
                                    for obs in obs_lines:
                                        oko, whyo = _obs_ok(obs)
                                        _trace_add("observation (flat)", obs, oko, whyo)
                                        if oko:
                                            h4, path4 = obs, "observation (flat)"
                                            break
                                if h4:
                                    print(f"[content] plain hook rejected ({i3}); last resort "
                                          f"[{path4}]: {h4}", flush=True)
                                    hook, line = h4, ""
                                    LAST_HOOK_TRACE["path"] = path4
                                else:
                                    print(f"[content] plain hook rejected too ({i3}); generic "
                                          "fallback.", flush=True)
                                    hook, line = "You have to see this play", ""
                                    LAST_HOOK_TRACE["path"] = "canned"
        # A FALLBACK HOOK used to leave the caption empty, which became the filler "Watch
        # this clip" on a real post. Write a caption for it from the same evidence; if that
        # can't be done, leave the body EMPTY — compose_reel_caption then posts the game
        # title + hashtags, which beats filler (user, 2026-10-08).
        if hook and not line and observation:
            # Two writers, in order: the scene LABEL, then a DIFFERENT-ANGLE line. The label
            # keeps getting rejected for asserting an event the footage doesn't show, and an
            # empty caption is not an option — a reel always ships with one (user,
            # 2026-10-09), and it must not be the hook word-for-word either.
            cwhy = ""
            for _writer in (_plain_caption, _angle_caption):
                for _try in range(2):
                    cap = (_writer(observation, gname, hook, dialogue, avoid=cwhy)
                           if _writer is _angle_caption and _try
                           else _writer(observation, gname, hook, dialogue))
                    if not cap:
                        continue
                    okb, cwhy = caption_body_ok(cap, hook, game)
                    if not okb:
                        continue
                    okc, cwhy = _verify_hook(cap, "", observation, game, dialogue=dialogue)
                    if okc:
                        line = cap
                        break
                if line:
                    break
            if line:
                print(f"[content] fallback caption: {line}", flush=True)
            else:
                print(f"[content] every caption was rejected ({cwhy}) — recasting the hook "
                      "from a different angle.", flush=True)
    except Exception as e:
        print(f"[content] hook+caption from video failed ({e!r}); using fallbacks.", flush=True)
        LAST_HOOK_TRACE["error"] = repr(e)[:300]
        if LAST_HOOK_TRACE.get("path") == "none":   # nothing had passed the gates yet
            hook, line = "", ""
            LAST_HOOK_TRACE["path"] = "error"
    # ADVERTISER-SAFETY GATE (per user 2026-10-06): whatever path wrote them, the hook is
    # BURNED ON the video and the caption ships with it, so profanity or graphic wording
    # risks demonetisation / age-restriction. Rewrite, then drop to a safe line if needed.
    # GTA 6 (config reels.swear_rule, 2026-11-20): star the swear words out instead of rewording.
    _pre_safe = hook
    hook = apply_swear_rule(hook, "hook", game, gname)
    if hook and hook != _pre_safe and hook != mask_swears(_pre_safe):
        # A MODEL rewrote the hook (a slur or profanity in it): that new line never met the
        # accuracy critic, so it meets it here (review 2026-11-21).
        LAST_HOOK_TRACE["path"] = f"{LAST_HOOK_TRACE.get('path')} + safety rewrite"
        if observation:
            oks, whys = _verify_hook(hook, "", observation, game, dialogue=dialogue)
            _trace_add("safety rewrite", hook, oks, whys)
            if not oks:
                hook = ""
    line = apply_swear_rule(line, "caption", game, gname)
    if not hook:
        hook = "Wait for it"
        LAST_HOOK_TRACE["path"] = "canned"
    # A REEL ALWAYS SHIPS WITH A CAPTION (user, 2026-10-09). Leaving the body empty posted a
    # live TikTok reel with nothing but the game title + hashtags. When every caption writer
    # has been rejected, use the HOOK as the body: it already passed the shape and accuracy
    # gates and it reads like a title of the video, which is what the caption is for. Only
    # filler is banned — a repeat of the hook is not filler.
    if not line:
        # NEVER the hook word-for-word (user, 2026-10-09): say its point a different way.
        line = _recast_hook(hook)
        if swear_rule_game(game):            # the recast must not un-star a starred hook word
            line = apply_swear_rule(line, "caption", game, gname)
        print(f"[content] caption recast from the hook: {line}", flush=True)
        LAST_HOOK_TRACE["caption_path"] = "recast from hook"
    LAST_HOOK_TRACE.update({"hook": hook, "caption_body": line})
    return hook, compose_reel_caption(line, game, with_game_title)


def hook_is_fallback() -> bool:
    """True when the LAST hook_and_caption_from_video call shipped anything other than a
    hook the main writer wrote and every gate passed (see LAST_HOOK_TRACE['path'])."""
    return str(LAST_HOOK_TRACE.get("path", "")) not in ("", "written", "written retry", "candidate")


def compose_reel_caption(body: str, game: str = "", with_game_title: bool = False) -> str:
    """Assemble a reel caption the house way: BODY, then the '<Game Title> <emoji>' line,
    then the brand-capped hashtags. with_game_title=True for classic/triptych reels
    (FB/IG/TikTok); off for callers like the YouTube Short description that want the plain
    body+hashtags. Shared by the AI writer AND a manual `--caption` override, so a
    hand-written body still gets the usual title line + hashtags."""
    tags = _reel_tags_with_brand(game)
    parts = [str(body or "").strip()]
    if with_game_title:
        gt = game_title_line(game)
        if gt:
            parts.append(gt)
    if tags:
        parts.append(" ".join(tags))
    return "\n\n".join(p for p in parts if p).strip()


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

    from core import ffmpeg, frames

    line = ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _dur = ffmpeg.duration(Path(video_path))
            cands = frames.extract_candidates(Path(video_path), Path(tmp),
                                              n=observe_frame_count(_dur))
            if cands:
                gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or "this game"
                observation = _observe_clip(cands, gname, _dur)
                if observation:                              # + full-clip subtitle speakers
                    observation = _with_subs(observation, _scan_subtitles(video_path, gname))
                    raw = _caption_with_lore(observation, game, gname, taglish)
                    line = raw.splitlines()[0].strip().strip('"')[:90] if raw else ""
    except Exception as e:
        print(f"[content] vision caption failed ({e!r}); using a generic line.", flush=True)
    if not line:
        line = "Watch this clip"
    tags = _reel_tags_with_brand(game)
    return f"{line}\n\n{' '.join(tags)}".strip()
