"""AUTOMATED 4K 60FPS LONG-FORM YOUTUBE TRACK (per user 2026-09-21).

The user records 4K60 SDR on the Elgato and drops files into
    reels/assets/4k60fps/<game-folder>/parts/      full playthrough, ~30-60 min each
    reels/assets/4k60fps/<game-folder>/segments/   standalone moments, ~10-45 min each
tools/longform_sync.py moves them to B2 (4k60fps/...). This module then, fully in the
cloud (.github/workflows/longform.yml, NO re-render, NO local disk):

  1. builds the queue — oldest recording first (timestamp in the filename, else the
     file's modified time), parts always in part-number order, priority games first;
  2. claims the NEXT publish slot (3/day, every 8h, in NZ time, config
     longform_auto.slots_local) and uploads early as PRIVATE + publishAt, so the video goes
     public exactly at its slot however long the upload takes;
  3. "watches" the video (frames across its length + sampled dialogue) and writes a
     lore-checked title, a REAL written description (not hashtag-only), hashtags + tags;
  4. builds a thumbnail from the most clickable frame + the game logo in a corner that
     doesn't cover a face or the subject (no 4K badge, per user);
  5. streams the file straight from B2 into YouTube's resumable upload (a run that hits
     the 6h job limit hands the session to the next run, which resumes);
  6. 15 days after a confirmed upload, deletes the source file from B2.

Folder naming: '<game>' = a normal playthrough ("Walkthrough"); '<game>-ngplus' =
"New Game Plus". A suit is added to a title ONLY when the filename carries it, e.g.
'Wolverine Part 3 - Classic Brown Suit.mp4' -> '... Part 3 (4K 60FPS) + Classic Brown Suit'.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import CONFIG, ROOT

LEDGER_ASSET = "_longform_ledger.json"      # {b2_key: {status, title, publish_at, video_id, ...}}
PRIORITY_ASSET = "_longform_priority.json"  # {"games": ["wolverine", ...]}
OUTPUT_DIR = ROOT / "output"

_TS_RE = re.compile(r"(20\d{2})[-_.](\d{2})[-_.](\d{2})[ _T-]+(\d{2})[-_.:](\d{2})[-_.:](\d{2})")
_PART_RE = re.compile(r"\bpart\s*[-_#]?\s*(\d{1,3})\b", re.I)


def log(m: str) -> None:
    print(f"[longform] {m}", flush=True)


def _cfg() -> dict:
    return CONFIG.raw().get("longform_auto", {}) or {}


# ----------------------------------------------------------------------------- items

def _base_game(folder: str) -> tuple[str, str]:
    """('wolverine', 'Walkthrough') / ('wolverine', 'New Game Plus') for 'wolverine-ngplus'."""
    f = folder.lower()
    for suf in ("-ngplus", "-newgameplus", "-ng-plus"):
        if f.endswith(suf):
            return folder[: -len(suf)], "New Game Plus"
    return folder, str(_cfg().get("run_label", "Walkthrough"))


def _suit(stem: str) -> Optional[str]:
    """The suit, ONLY if the filename names one: 'Wolverine Part 3 - Classic Brown Suit'."""
    for seg in reversed([s.strip() for s in stem.split(" - ")[1:]]):
        seg = re.sub(r"\s*\([^)]*\)", "", seg).strip()   # drop a recorder timestamp "(2026-...)"
        if re.search(r"\bsuit$", seg, re.I):
            return seg
    return None


def _order_ts(item: dict) -> float:
    """Recording order: the timestamp in the filename (recorders stamp it and it survives
    copying), else the file's modified time (rclone keeps it on B2), else B2 upload time."""
    m = _TS_RE.search(item["name"])
    if m:
        try:
            return datetime(*map(int, m.groups()), tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    return (item.get("mtime_ms") or item.get("upload_ms") or 0) / 1000.0


def _enrich(f: dict) -> dict:
    stem = Path(f["name"]).stem
    base, run = _base_game(f["game"])
    pm = _PART_RE.search(stem)
    return {**f, "stem": stem, "base": base, "run_label": run,
            "part_no": int(pm.group(1)) if pm else None,
            "suit": _suit(stem), "order": _order_ts(f)}


def _game_name(base: str) -> str:
    return str((CONFIG.reels.get("game_names", {}) or {}).get(base) or base.replace("-", " ").title())


# ------------------------------------------------------------------------ ledger/state

def _ledger() -> dict:
    from core import gh_release
    d = gh_release._read_json_asset(LEDGER_ASSET)
    return d if isinstance(d, dict) else {}


def _save_ledger(led: dict) -> bool:
    from core import gh_release
    return gh_release._write_json_asset(LEDGER_ASSET, led)


def _priority() -> list[str]:
    from core import gh_release
    d = gh_release._read_json_asset(PRIORITY_ASSET)
    return [str(g) for g in ((d or {}).get("games") or [])] if isinstance(d, dict) else []


def set_priority(game: Optional[str]) -> str:
    """Telegram 'prioritise <game>' / 'prioritise clear'. Returns a confirmation line."""
    from core import b2_store, gh_release
    folders = sorted({f["game"] for f in b2_store.list_longform()})
    if not game or game.lower() in ("clear", "none", "off", "reset"):
        gh_release._write_json_asset(PRIORITY_ASSET, {"games": []})
        return "Long-form priority cleared — back to oldest-recording-first across all games."
    g = game.strip().lower().replace(" ", "-")
    match = [f for f in folders if f.lower() == g] or [f for f in folders if g in f.lower()]
    if not match:
        return (f"No long-form footage folder matches “{game}”. Folders on B2: "
                f"{', '.join(folders) or '(none yet)'}")
    gh_release._write_json_asset(PRIORITY_ASSET, {"games": match})
    return f"Long-form priority set: {', '.join(match)} goes first, then oldest-first for the rest."


# ------------------------------------------------------------------------------ queue

def build_queue(files: list[dict], ledger: dict, priority: list[str]) -> list[dict]:
    """Pending items in upload order. Per game: parts in part-number order (a later part
    never jumps ahead of an earlier one), segments by recording time, merged by time.
    Priority games first (in the given order), then every other game oldest-first."""
    done = set(ledger)                                    # uploaded / uploading / failed
    items = [_enrich(f) for f in files if f["key"] not in done]
    per: dict[str, list[dict]] = {}
    for it in items:
        per.setdefault(it["game"], []).append(it)
    ordered: dict[str, list[dict]] = {}
    for game, its in per.items():
        parts = sorted([i for i in its if i["kind"] == "parts"],
                       key=lambda i: (i["part_no"] if i["part_no"] is not None else 10**6, i["order"]))
        running = float("-inf")
        for p in parts:                                   # monotonic effective time for parts
            running = max(running, p["order"])
            p["eff"] = running
        segs = [dict(i, eff=i["order"]) for i in its if i["kind"] == "segments"]
        ordered[game] = sorted(parts + segs, key=lambda i: (i["eff"], i["kind"] != "parts"))
    out: list[dict] = []
    for g in priority:
        out += ordered.pop(g, [])
    rest = sorted((i for its in ordered.values() for i in its), key=lambda i: i["eff"])
    return out + rest


def _part_numbers(files: list[dict]) -> dict[str, int]:
    """Parts without 'Part N' in the filename get their position within the game's parts."""
    nums: dict[str, int] = {}
    by: dict[str, list[dict]] = {}
    for f in (_enrich(x) for x in files if x["kind"] == "parts"):
        by.setdefault(f["game"], []).append(f)
    for its in by.values():
        its.sort(key=lambda i: (i["part_no"] if i["part_no"] is not None else 10**6, i["order"]))
        for n, it in enumerate(its, 1):
            nums[it["key"]] = it["part_no"] or n
    return nums


# ------------------------------------------------------------------------------ slots

def _tz():
    name = str(_cfg().get("timezone", "Pacific/Auckland"))
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=12))            # fallback (no tzdata on this box)


def next_slot(ledger: dict, now: Optional[datetime] = None) -> Optional[datetime]:
    """The NEXT publish slot inside [now+lead, now+lead+gap] that nothing is booked for, or
    None. The workflow runs every few hours; each 8h slot is claimed by the first run that
    sees it in that window, so it's exactly 3/day with no drift and no pre-filling days
    ahead. A slot no run reached in time is simply skipped (never double-booked)."""
    c = _cfg()
    now = now or datetime.now(timezone.utc)
    lead = timedelta(hours=float(c.get("lead_hours", 6.5)))
    gap = timedelta(hours=24.0 / max(1, len(c.get("slots_local", ["23:00", "07:00", "15:00"]))))
    tz = _tz()
    taken = {v.get("publish_at") for v in ledger.values()
             if v.get("status") in ("uploading", "scheduled") and v.get("publish_at")}
    local_today = now.astimezone(tz).date()
    cands = []
    for d in range(-1, 4):
        day = local_today + timedelta(days=d)
        for hhmm in c.get("slots_local", ["23:00", "07:00", "15:00"]):
            hh, mm = (int(x) for x in str(hhmm).split(":"))
            cands.append(datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
                         .astimezone(timezone.utc))
    for t in sorted(cands):
        if now + lead <= t <= now + lead + gap and _iso(t) not in taken:
            return t
    return None


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nz(iso: str) -> str:
    t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return t.astimezone(_tz()).strftime("%a %d %b %I:%M %p NZ").replace(" 0", " ")


# -------------------------------------------------------------------------- analysis

def _ff(args: list, timeout: int = 300) -> int:
    try:
        return subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True,
                              timeout=timeout).returncode
    except Exception:
        return 1


def _duration(url: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", url], capture_output=True, text=True,
                           timeout=180)
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def extract_frames(url: str, dur: float, out: Path, n: int = 14) -> list[Path]:
    """n frames evenly across 8%-92% of the video, each fetched by an HTTP seek (only the
    bytes around each timestamp are downloaded). 1280x720, ready for vision + thumbnail."""
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n):
        t = dur * (0.08 + 0.84 * i / max(1, n - 1))
        p = out / f"f{i:02d}.jpg"
        _ff(["-ss", f"{t:.2f}", "-i", url, "-frames:v", "1", "-vf",
             "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
             "-q:v", "2", str(p)], timeout=240)
        if p.exists() and p.stat().st_size > 5000:
            frames.append(p)
    return frames


def sample_dialogue(url: str, dur: float, gname: str, windows: int = 8, secs: int = 75) -> str:
    """Spoken dialogue from `windows` evenly spaced `secs`-long stretches (not the whole
    file: bounded cost + no full download). ElevenLabs Scribe first, then Whisper."""
    from agents.content import _clean_transcript, sanitize
    from core import elevenlabs, openai_client
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(windows):
            t = max(0.0, dur * (0.04 + 0.92 * i / max(1, windows - 1)) - secs / 2)
            a = Path(tmp) / f"a{i}.mp3"
            if _ff(["-ss", f"{t:.2f}", "-i", url, "-t", str(secs), "-vn", "-ac", "1",
                    "-ar", "16000", "-b:a", "48k", str(a)], timeout=240) != 0 or not a.exists():
                continue
            try:
                txt = _clean_transcript(elevenlabs.speech_to_text(a))
                if not txt:
                    txt = _clean_transcript(openai_client.transcribe(a, prompt=gname))
            except Exception:
                txt = ""
            if txt:
                parts.append(f"[~{int(t // 60)}:{int(t % 60):02d}] {sanitize(txt).strip()}")
    return "\n".join(parts)


def _vision(prompt: str, images: list[Path], timeout: int = 240) -> str:
    """Claude vision (Read tool) first, OpenAI vision fallback."""
    from core import claude_code, openai_client
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(images))
    try:
        return claude_code.run(f"Use the Read tool to open these images first.\n\n{prompt}\n\n"
                               f"Images:\n{listing}", allowed_tools="Read", timeout=timeout)
    except claude_code.ClaudeCodeError as e:
        log(f"Claude vision unavailable ({e}); using OpenAI vision.")
        return openai_client.vision(prompt, images)


def observe(frames: list[Path], gname: str) -> str:
    return _vision(
        f"These are {len(frames)} frames, in order, spread across ONE long {gname} gameplay "
        "video. Describe ONLY what you can literally see, in 5-8 plain sentences: the "
        "settings/locations, the characters by APPEARANCE (never guess who they are), what "
        "happens across the video in order (fights, bosses, cutscenes, exploration), any "
        "boss health-bar names, and any readable subtitles or on-screen text (quote them).",
        frames)


# --------------------------------------------------------------------------- metadata

def _brand_tag() -> str:
    return str(CONFIG.reels.get("brand_hashtag", "#KiwinoyGaming"))


def write_meta(it: dict, part_no: Optional[int], observation: str, dialogue: str) -> dict:
    """Title + REAL written description + hashtags + tags, grounded in the footage and the
    game's lore bible, then an adversarial fact-check pass that fixes anything unsupported."""
    from agents.content import _text, extract_json
    from core import lore
    gname = _game_name(it["base"])
    bible = lore.lore_for(it["base"]) or "(no lore bible for this game — describe only what is shown)"
    is_part = it["kind"] == "parts"
    evidence = (f"WHAT THE FRAMES SHOW:\n{observation or '(none)'}\n\n"
                f"SAMPLED DIALOGUE (timestamped, may be partial):\n{(dialogue or '(none)')[:9000]}")
    ask_title = "" if is_part else (
        "- \"moment\": the video's MAIN event as a YouTube title phrase, 3-9 words, Title Case, "
        "like: 'Sabretooth Boss Fight', 'Wolverine Helps Jean Grey Save The Mutants', 'Logan "
        "Remembers His Past', 'Mr. Sinister Gets Revenge on Trask Scene'. No emojis, no hype "
        "words (Epic/Insane/INSANE), no clickbait caps. Do NOT include the game name.\n")
    prompt = (
        f"You write YouTube metadata for a no-commentary 4K 60FPS {gname} gameplay video "
        f"({'a walkthrough PART' if is_part else 'a standalone gameplay SEGMENT'}).\n\n"
        f"GAME LORE BIBLE (follow its NAMING, DIALOGUE & RELATIONSHIP and DON'T-FABRICATE "
        f"rules strictly):\n{bible}\n\n{evidence}\n\n"
        "Return ONLY JSON with:\n" + ask_title +
        "- \"summary\": 2-4 sentences for the description saying what actually happens in "
        "this video, in order, present tense, like a good video description. Name a character "
        "ONLY when a subtitle speaker label, a boss health bar or unmistakable visuals show "
        "them. Never invent events, quotes, motives or who is talking to whom. Do not spoil "
        "beyond what this video shows.\n"
        "- \"hashtags\": 6-9 lowercase hashtags (no spaces) relevant to the game, franchise "
        "and what is shown, e.g. #marvelswolverine #wolverine #xmen.\n"
        "- \"tags\": 15-25 lowercase YouTube search keyword phrases (game name variants, "
        "'<game> gameplay', '<game> walkthrough', '4k 60fps', characters/bosses that are "
        "evidenced, 'no commentary').")
    try:
        draft = extract_json(_text(prompt, timeout=240)) or {}
    except Exception as e:
        log(f"metadata writer failed ({e!r}) — using safe fallbacks")
        draft = {}
    critic = (
        "You are a strict fact-checker for YouTube metadata about a gameplay video.\n\n"
        f"GAME LORE BIBLE:\n{bible}\n\n{evidence}\n\nDRAFT:\n{json.dumps(draft, ensure_ascii=False)}\n\n"
        "Check EVERY claim in moment/summary against the evidence and the lore rules: invented "
        "names, wrong speaker/target/motive, calling allies enemies (or vice versa), events not "
        "shown, spoilers beyond the video. Rewrite anything unsupported so it is plainly true "
        "(prefer describing the action over guessing). Return ONLY JSON with the SAME keys, "
        "fully corrected, plus \"issues\": [short list of what you fixed].")
    try:
        fixed = extract_json(_text(critic, timeout=240)) or {}
        if fixed.get("issues"):
            log(f"fact-check fixed: {fixed.get('issues')}")
        draft = {**draft, **{k: v for k, v in fixed.items() if v and k != "issues"}}
    except Exception as e:
        log(f"fact-check pass failed ({e!r}) — keeping the draft")

    suit = f" + {it['suit']}" if it.get("suit") else ""
    if is_part:
        title = f"{gname} {it['run_label']} Part {part_no} (4K 60FPS){suit}"
    else:
        moment = str(draft.get("moment") or "")
        moment = re.sub(re.escape(gname), "", moment, flags=re.I)      # game name goes after the dash
        moment = re.sub(r"\s+", " ", moment).strip(" .-|:") or "Gameplay"
        title = f"{moment} - {gname} (4K 60FPS){suit}"
    title = title[:100]

    summary = str(draft.get("summary") or "").strip() or (
        f"{'Part ' + str(part_no) + ' of the ' if is_part else ''}{gname} "
        f"{'walkthrough' if is_part else 'gameplay'} in 4K 60FPS.")
    kind_line = (f"{gname} {it['run_label']} — Part {part_no}. Full gameplay in 4K 60FPS, "
                 "no commentary." if is_part else
                 f"{gname} gameplay in 4K 60FPS, no commentary.")
    if it.get("suit"):
        kind_line += f" Suit: {it['suit']}."
    tags_h = [t if str(t).startswith("#") else f"#{t}" for t in (draft.get("hashtags") or [])]
    game_tag = "#" + re.sub(r"[^a-z0-9]", "", gname.lower())
    hashtags: list[str] = []
    for t in [game_tag, *tags_h, _brand_tag()]:
        t = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if len(t) > 1 and t.lower() not in {h.lower() for h in hashtags}:
            hashtags.append(t)
    hashtags = hashtags[:10]
    gear = str(CONFIG.reels.get("gear_cta", "") or "").strip()
    description = "\n\n".join(x for x in [summary, kind_line, gear, " ".join(hashtags)] if x)

    kw, total = [], 0
    for t in [gname.lower(), f"{gname.lower()} gameplay", f"{gname.lower()} 4k 60fps",
              *[str(x).lower().strip() for x in (draft.get("tags") or [])]]:
        t = re.sub(r"[<>\"]", "", t)[:80]
        if t and t not in kw and total + len(t) + 1 <= 480:
            kw.append(t)
            total += len(t) + 1
    return {"title": title, "description": description[:5000], "tags": kw,
            "hashtags": hashtags, "moment": draft.get("moment", ""), "summary": summary}


# ------------------------------------------------------------------------- thumbnail

def make_thumbnail(frames: list[Path], base: str, title: str, out: Path) -> Optional[Path]:
    """Most clickable frame (vision-judged from the sharpest candidates) + the game logo in
    the corner that covers no face / subject. No text, no 4K badge (per user)."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    from agents.content import extract_json
    from core import frames as fr
    if not frames:
        return None
    scored = sorted(frames, key=lambda p: fr.sharpness(p), reverse=True)[:8]
    # contact sheet: 4 x 2 numbered tiles
    tw, th = 480, 270
    sheet = Image.new("RGB", (tw * 4, th * 2), "black")
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(scored):
        im = Image.open(p).convert("RGB").resize((tw, th))
        sheet.paste(im, ((i % 4) * tw, (i // 4) * th))
        d.rectangle([(i % 4) * tw, (i // 4) * th, (i % 4) * tw + 54, (i // 4) * th + 44], fill="black")
        d.text(((i % 4) * tw + 14, (i // 4) * th + 8), str(i + 1), fill="yellow")
    sheet_p = out.parent / "contact_sheet.jpg"
    sheet.save(sheet_p, quality=85)
    best = 0
    try:
        j = extract_json(_vision(
            f"This contact sheet shows {len(scored)} numbered frames from a YouTube gameplay "
            f"video titled “{title}”. Pick the ONE frame that would make the most compelling, "
            "highest click-through thumbnail: a clear face or character in a dramatic moment, "
            "strong action, sharp and well-lit, NOT a menu/loading/black/HUD-cluttered frame. "
            "Prefer frames WITHOUT subtitle text or on-screen captions (they look cluttered "
            "at thumbnail size) unless every good frame has them. "
            'Return ONLY JSON: {"best": <number>, "why": "<short>"}', [sheet_p])) or {}
        best = max(0, min(len(scored) - 1, int(j.get("best", 1)) - 1))
        log(f"thumbnail frame #{best + 1}: {j.get('why', '')}")
    except Exception as e:
        log(f"thumbnail judge failed ({e!r}) — using the sharpest frame")
    frame = scored[best]
    corner = "top-left"
    try:
        j = extract_json(_vision(
            "A game LOGO will be placed in ONE corner of this 1280x720 thumbnail. Choose the "
            "corner where it covers NO face, NO main character/subject and no important "
            "action. Prefer top-left when it is free. Return ONLY JSON: "
            '{"corner": "top-left|top-right|bottom-left|bottom-right"}', [frame])) or {}
        c = str(j.get("corner", "")).lower().strip()
        if c in ("top-left", "top-right", "bottom-left", "bottom-right"):
            corner = c
    except Exception as e:
        log(f"logo-corner judge failed ({e!r}) — top-left")
    log(f"logo corner: {corner}")

    img = Image.open(frame).convert("RGB").resize((1280, 720))
    img = ImageEnhance.Contrast(img).enhance(1.06)
    img = ImageEnhance.Color(img).enhance(1.10)
    img = ImageEnhance.Sharpness(img).enhance(1.25)
    from orchestrator import _game_logo
    lp = _game_logo(base)
    if lp and Path(lp).exists():
        logo = Image.open(lp).convert("RGBA")
        bbox = logo.getchannel("A").getbbox()
        if bbox:
            logo = logo.crop(bbox)
        s = min(400 / logo.width, 170 / logo.height)
        logo = logo.resize((max(1, int(logo.width * s)), max(1, int(logo.height * s))))
        m = 34
        x = m if "left" in corner else 1280 - logo.width - m
        y = m if "top" in corner else 720 - logo.height - m
        region = img.crop((x, y, x + logo.width, y + logo.height)).convert("L")
        bg_lum = sum(region.getdata()) / max(1, logo.width * logo.height)
        a = logo.getchannel("A")
        lum = [v for v, al in zip(logo.convert("L").getdata(), a.getdata()) if al > 128]
        logo_lum = sum(lum) / max(1, len(lum))
        # legibility halo: white glow for a dark logo on a dark frame, else a soft dark shadow
        glow_col = (255, 255, 255) if (logo_lum < 90 and bg_lum < 90) else (0, 0, 0)
        pad = 24
        halo = Image.new("RGBA", (logo.width + pad * 2, logo.height + pad * 2), (0, 0, 0, 0))
        halo.paste(Image.new("RGBA", logo.size, glow_col + (255,)), (pad, pad), a)
        halo = halo.filter(ImageFilter.GaussianBlur(12))
        halo.putalpha(halo.getchannel("A").point(lambda v: int(v * 0.65)))
        base_rgba = img.convert("RGBA")
        base_rgba.alpha_composite(halo, (x - pad, y - pad + 3))
        base_rgba.alpha_composite(logo, (x, y))
        img = base_rgba.convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=90)
    return out


# ------------------------------------------------------------------------------ run

def run_once(dry_run: bool = False, only_key: Optional[str] = None) -> dict:
    """Upload the next long-form video into the next free publish slot (or resume one)."""
    from core import b2_store, notify
    from core import youtube as yt
    c = _cfg()
    if not c.get("enabled", False) and not dry_run:
        log("disabled (longform_auto.enabled: false) — skipping.")
        return {"skipped": "disabled"}
    files = b2_store.list_longform()
    ledger = _ledger()
    resume = None if only_key else next(
        ((k, v) for k, v in ledger.items() if v.get("status") == "uploading"), None)
    if resume:
        key, entry = resume
        it = next((_enrich(f) for f in files if f["key"] == key), None)
        if not it:
            log(f"in-progress item {key} is gone from B2 — marking failed")
            ledger[key] = {**entry, "status": "failed", "error": "source missing"}
            _save_ledger(ledger)
            return {"skipped": "source_missing"}
        publish_at = entry["publish_at"]
        log(f"RESUMING {it['name']} -> {entry.get('title')} (slot {_nz(publish_at)})")
    else:
        if only_key:
            pool = [_enrich(f) for f in files if f["key"] == only_key]
            slot = next_slot(ledger) or (datetime.now(timezone.utc) + timedelta(hours=8))
        else:
            slot = next_slot(ledger)
            if slot is None:
                log("next publish slot is already booked / not due yet — nothing to do.")
                return {"skipped": "no_slot"}
            pool = build_queue(files, ledger, _priority())
        if not pool:
            log("queue empty — no new long-form footage on B2.")
            return {"skipped": "empty"}
        it, entry, publish_at = pool[0], {}, _iso(slot)
        log(f"next: [{it['game']}/{it['kind']}] {it['name']} ({it['size'] / 1e9:.1f} GB) "
            f"-> slot {_nz(publish_at)}")

    run_dir = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_longform"
    run_dir.mkdir(parents=True, exist_ok=True)
    url = b2_store.presigned_url(it["key"], valid_seconds=7 * 24 * 3600)
    if not url:
        raise RuntimeError("could not sign a B2 download URL")
    dur = _duration(url)
    log(f"duration {dur / 60:.1f} min")
    gname = _game_name(it["base"])
    frames = extract_frames(url, dur, run_dir / "frames")
    log(f"{len(frames)} frames extracted")

    if entry.get("title"):                               # resume: reuse the booked metadata
        meta = {k: entry[k] for k in ("title", "description", "tags") if k in entry}
    else:
        part_no = _part_numbers(files).get(it["key"]) if it["kind"] == "parts" else None
        obs = observe(frames, gname) if frames else ""
        dialogue = sample_dialogue(url, dur, gname) if dur else ""
        meta = write_meta(it, part_no, obs, dialogue)
        (run_dir / "analysis.txt").write_text(f"OBSERVATION:\n{obs}\n\nDIALOGUE:\n{dialogue}",
                                              encoding="utf-8")
    thumb = make_thumbnail(frames, it["base"], meta["title"], run_dir / "thumbnail.jpg")
    (run_dir / "meta.json").write_text(json.dumps({**meta, "key": it["key"],
                                                   "publish_at": publish_at}, indent=2,
                                                  ensure_ascii=False), encoding="utf-8")
    log(f"TITLE: {meta['title']}")
    log(f"DESCRIPTION:\n{meta['description']}")
    log(f"TAGS: {', '.join(meta['tags'])}")
    if dry_run:
        log(f"DRY RUN — nothing uploaded. Review: {run_dir}")
        return {"dry_run": True, "dir": str(run_dir), **meta}

    ledger[it["key"]] = {**entry, "status": "uploading", "publish_at": publish_at,
                         "title": meta["title"], "description": meta["description"],
                         "tags": meta["tags"], "game": it["game"], "kind": it["kind"],
                         "file_id": it["file_id"], "started_at": entry.get("started_at") or time.time(),
                         "attempts": int(entry.get("attempts", 0)) + 1}
    _save_ledger(ledger)
    last_saved = [0]

    def _progress(uri: str, done: int) -> None:          # persist the session every ~2 GB
        if done - last_saved[0] >= 2 * 1024 ** 3:
            ledger[it["key"]].update(resume_uri=uri, bytes_done=done)
            _save_ledger(ledger)
            last_saved[0] = done

    reader = b2_store.B2RangeReader(url, it["size"])
    try:
        resp = yt.upload_video(None, meta["title"], meta["description"], meta["tags"],
                               publish_at=publish_at, category_id="20", made_for_kids=False,
                               thumbnail=str(thumb) if thumb else None,
                               chunk_mb=int(c.get("chunk_mb", 512)), stream=reader,
                               resume_uri=entry.get("resume_uri"), on_progress=_progress)
    except Exception as e:
        msg = str(e)
        quota = "quotaExceeded" in msg or "uploadLimitExceeded" in msg
        if quota or ledger[it["key"]]["attempts"] >= int(c.get("max_attempts", 3)):
            # quota: free the slot so it re-queues; repeated failure: park it + alert
            if quota:
                ledger.pop(it["key"], None)
            else:
                ledger[it["key"]].update(status="failed", error=msg[:300])
            _save_ledger(ledger)
            notify.telegram(("⚠️ Long-form upload hit the YouTube API quota — it'll retry at "
                             "the next slot." if quota else
                             f"❌ Long-form upload FAILED {ledger.get(it['key'], {}).get('attempts', '')}x "
                             f"and was parked: {meta['title']}\n{msg[:200]}"))
        raise
    vid = resp.get("id", "")
    ledger[it["key"]].update(status="scheduled", video_id=vid, done_at=time.time(),
                             resume_uri=None, bytes_done=it["size"])
    for k in ("description", "tags"):                    # keep the ledger small once done
        ledger[it["key"]].pop(k, None)
    _save_ledger(ledger)
    pl = ((CONFIG.reels.get("youtube", {}) or {}).get("playlists", {}) or {}).get(it["base"])
    if pl and vid:
        try:
            yt.add_to_playlist(vid, pl)
        except Exception as e:
            log(f"playlist add failed ({e!r})")
    notify.telegram(f"🎬 Long-form scheduled: {meta['title']}\n"
                    f"Goes public {_nz(publish_at)}\nhttps://youtu.be/{vid}")
    log(f"DONE https://youtu.be/{vid} (public at {_nz(publish_at)})")
    return {"video_id": vid, "publish_at": publish_at, **meta}


def cleanup(dry_run: bool = False) -> int:
    """Delete source footage from B2 `delete_after_days` after a CONFIRMED upload (YouTube
    reports the video 'processed'). A video that's gone from YouTube keeps its footage."""
    from core import b2_store
    from core import youtube as yt
    days = float(_cfg().get("delete_after_days", 15))
    ledger = _ledger()
    due = {k: v for k, v in ledger.items()
           if v.get("status") == "scheduled" and v.get("video_id") and not v.get("b2_deleted")
           and time.time() - float(v.get("done_at", time.time())) >= days * 86400}
    if not due:
        log("cleanup: nothing due.")
        return 0
    st = yt.video_status([v["video_id"] for v in due.values()])
    n = 0
    for k, v in due.items():
        s = st.get(v["video_id"])
        if not s or s.get("upload") != "processed":
            log(f"cleanup: keeping {k} (YouTube status {s or 'missing'})")
            continue
        if dry_run:
            log(f"cleanup (dry): would delete {k}")
            continue
        if b2_store.delete_file(k, v.get("file_id", "")):
            v["b2_deleted"] = time.time()
            n += 1
            log(f"cleanup: deleted {k} from B2")
    if n:
        _save_ledger(ledger)
    return n
