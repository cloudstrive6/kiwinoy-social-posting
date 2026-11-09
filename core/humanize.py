"""Humanize pass for lore Shorts/Reels text (Bryce, 2026-11-09).

Runs the humanizer skill (blader/humanizer, MIT, vendored in assets/skills/humanizer/) over:
  * the ON-SCREEN card: the body paragraph and the @kiwinoygaming comment line
  * the POST text: the caption and the YouTube title

The skill strips AI tells (not-X-but-Y contrasts, one-line closers, forced triads, dashes,
stock AI words, sales language) without changing what the text says. Every rewrite is
checked against the format's own rules; if it breaks one, the original text is kept, so the
pass can never make a post worse or block it. Callers run this BEFORE the fact-checker, so
the checker always verifies the words that actually ship.

Off with reels.gameplay.lore.humanize: false in config.yaml.
"""
from __future__ import annotations

import re
from pathlib import Path

_SKILL = Path(__file__).resolve().parents[1] / "assets" / "skills" / "humanizer" / "SKILL.md"
_DASHES = ("—", "–", " -- ")


def enabled() -> bool:
    try:
        from core.config import CONFIG
        lcfg = (CONFIG.reels.get("gameplay", {}) or {}).get("lore", {}) or {}
        return bool(lcfg.get("humanize", True))
    except Exception:
        return True


def _skill_text() -> str:
    try:
        t = _SKILL.read_text(encoding="utf-8")
        return re.sub(r"\A---.*?---\s*", "", t, flags=re.S)       # drop the frontmatter
    except Exception:
        return ""


def _ask(task: str, payload: str) -> dict:
    from agents.content import _text
    from core.openai_client import extract_json
    skill = _skill_text()
    if not skill:
        return {}
    prompt = (
        "Apply this editing skill in EMBEDDED MODE (return only the final text).\n\n"
        f"<skill>\n{skill}\n</skill>\n\n"
        "The text below is short-form social video copy for a gaming page. Voice: a gamer "
        "talking to other gamers, plain spoken English, present tense, a little punchy. "
        "EDIT LIGHTLY: change only the phrases that show a pattern from the skill and "
        "leave every other sentence word for word. Keep the meaning exactly: every fact, "
        "name and quoted line stays as given, nothing is added, nothing is softened or "
        "sharpened. If the text has no tells, return it unchanged. No dashes of any kind, "
        "no emojis, no hashtags.\n\n"
        f"{task}\n\n{payload}")
    try:
        d = extract_json(_text(prompt, timeout=150))
        return d if isinstance(d, dict) else {}
    except Exception as e:
        print(f"[humanize] skipped ({e!r})", flush=True)
        return {}


def _clean(s) -> str:
    from agents.content import sanitize
    return re.sub(r"\s+", " ", sanitize(str(s or ""))).strip().strip('"')


def _has_dash(s: str) -> bool:
    return any(d in s for d in _DASHES)


# A single quote opens after a non-letter and closes before a non-letter, so apostrophes
# inside the quote ("doesn't") or in possessives ("Joel's") never end or start one.
_QUOTE_RE = re.compile(r"(?<![A-Za-z])['‘](.{3,}?)['’](?![A-Za-z])"
                       r"|[\"“]([^\"”]{3,}?)[\"”]")


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s or "").strip().lower()


def _lost_quotes(old: str, new: str) -> bool:
    """True when a quoted line ('...' or "...") in the old text is missing from the new one."""
    flat = _norm(new)
    quotes = [_norm(a or b) for a, b in _QUOTE_RE.findall(old or "")]
    return any(q and q not in flat for q in quotes)


def card(c: dict, gname: str, words_min: int = 45, words_max: int = 65) -> dict:
    """Humanized copy of a lore card {body, highlight, comment}; the original on any failure."""
    if not enabled() or not c.get("body"):
        return c
    task = (
        "Rewrite this on-screen card. Rules for the result:\n"
        f"- body: ONE paragraph, {words_min}-{words_max} words, still opening with "
        f"'In {gname}', same four beats in the same order (context, the detail, a short "
        "verdict, a comparison).\n"
        "- highlight: 2-6 words copied EXACTLY from your new body, the same pivot the "
        "original highlight marks.\n"
        "- comment: the short reaction line, under 90 characters.\n"
        'Return ONLY JSON: {"body": "...", "highlight": "...", "comment": "..."}')
    payload = (f"BODY: {c.get('body', '')}\nHIGHLIGHT: {c.get('highlight', '')}\n"
               f"COMMENT: {c.get('comment', '')}")
    d = _ask(task, payload)
    body, hl, com = _clean(d.get("body")), _clean(d.get("highlight")), _clean(d.get("comment"))
    why = ""
    n = len(body.split())
    if not body:
        why = "no rewrite"
    elif not (words_min <= n <= words_max):
        why = f"{n} words"
    elif not body.lower().startswith(f"in {gname}".lower()):
        why = "lost the 'In <game>' opening"
    elif _lost_quotes(c.get("body", ""), body) or _lost_quotes(c.get("comment", ""), com):
        why = "dropped or changed a quoted line"
    elif c.get("highlight") and (not hl or hl.lower() not in body.lower()):
        why = "highlight is not in the new body"
    elif _has_dash(body) or _has_dash(com):
        why = "dash"
    elif c.get("comment") and not (com and len(com) <= 90):
        why = "comment too long or missing"
    if why:
        print(f"[humanize] card kept as written ({why}).", flush=True)
        return c
    out = dict(c)
    out.update({"body": body, "highlight": hl[:60] or c.get("highlight", ""),
                "comment": com or c.get("comment", "")})
    print(f"[humanize] card: {body}", flush=True)
    return out


def post_text(caption: str, title: str) -> tuple[str, str]:
    """Humanized (caption, title); each falls back to its original on any failure."""
    if not enabled() or not (caption or title):
        return caption, title
    task = (
        "Rewrite the post CAPTION (one sentence, 12-28 words) and the YouTube TITLE "
        "(4-10 words, under 60 characters, no full stop at the end, keep the curiosity "
        "gap). Return ONLY JSON: {\"caption\": \"...\", \"title\": \"...\"}")
    d = _ask(task, f"CAPTION: {caption}\nTITLE: {title}")
    cap, ttl = _clean(d.get("caption")), _clean(d.get("title"))
    if not cap or not (8 <= len(cap.split()) <= 34) or _has_dash(cap):
        cap = caption
    if (not ttl or not (3 <= len(ttl.split()) <= 12) or len(ttl) > 62
            or ttl.endswith(".") or _has_dash(ttl)):
        ttl = title
    if (cap, ttl) != (caption, title):
        print(f"[humanize] caption: {cap} | title: {ttl}", flush=True)
    return cap, ttl
