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


_NGPLUS_RE = re.compile(r"new\s*game\s*(?:\+|plus)|\bng\s*\+|\bng[-_ ]?plus\b", re.I)


def _enrich(f: dict) -> dict:
    stem = Path(f["name"]).stem
    base, run = _base_game(f["game"])
    if _NGPLUS_RE.search(stem):                  # "Wolverine - New Game+ (...)" in a plain folder
        run = "New Game Plus"
    pm = _PART_RE.search(stem)
    return {**f, "stem": stem, "base": base, "run_label": run,
            "series": f"{base}|{run}",           # parts are numbered PER series (NG+ vs normal)
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
    # Game folders starting with "_" are a STAGING area (tests, holds) — never auto-queued;
    # they can still be run explicitly with --key.
    items = [_enrich(f) for f in files if f["key"] not in done and not f["game"].startswith("_")]
    per: dict[str, list[dict]] = {}
    for it in items:
        per.setdefault(it["game"], []).append(it)
    ordered: dict[str, list[dict]] = {}
    for game, its in per.items():
        parts = [i for i in its if i["kind"] == "parts"]
        for series in {i["series"] for i in parts}:        # monotonic time PER series
            running = float("-inf")
            for p in sorted((i for i in parts if i["series"] == series),
                            key=lambda i: (i["part_no"] if i["part_no"] is not None else 10**6,
                                           i["order"])):
                running = max(running, p["order"])
                p["eff"] = running
        segs = [dict(i, eff=i["order"]) for i in its if i["kind"] == "segments"]
        ordered[game] = sorted(parts + segs, key=lambda i: (i["eff"], i["kind"] != "parts"))
    out: list[dict] = []
    for g in priority:
        out += ordered.pop(g, [])
    rest = sorted((i for its in ordered.values() for i in its), key=lambda i: i["eff"])
    return out + rest


def _series_title(series: str) -> str:
    """'wolverine|New Game Plus' -> the title prefix its videos carry on YouTube."""
    base, _, run = series.partition("|")
    return f"{_game_name(base)} {run}".strip()


def youtube_part_max() -> dict[str, int]:
    """Highest 'Part N' ALREADY ON THE CHANNEL per series title, read from YouTube itself
    (uploads include private/scheduled videos). The channel is the authoritative record:
    the ledger is a Release asset, and if a write is ever lost or two runs overlap, numbering
    alone would repeat a number that is already published. Returns {} if the lookup fails."""
    from core import youtube as yt
    out: dict[str, int] = {}
    try:
        for v in yt.list_uploads(300):
            m = re.match(r"^(.*?)\s+Part\s+(\d+)\s*\(", str(v.get("title", "")), re.I)
            if m:
                pre, n = m.group(1).strip().lower(), int(m.group(2))
                out[pre] = max(out.get(pre, 0), n)
    except Exception as e:
        log(f"couldn't read existing part numbers from YouTube ({e!r}) — ledger only")
    return out


def _part_numbers(files: list[dict], ledger: Optional[dict] = None,
                  yt_max: Optional[dict[str, int]] = None) -> dict[str, int]:
    """Part number for every part: 'Part N' from the filename if present, else the next
    number in its SERIES (e.g. wolverine|New Game Plus) after every part already booked in
    the ledger AND every 'Part N' already on the YouTube channel — so numbering never
    restarts when old sources are cleaned off B2, and never collides with a published part."""
    nums: dict[str, int] = {}
    used: dict[str, set] = {}
    for k, v in (ledger or {}).items():
        if not k.startswith("__") and v.get("part_no") and v.get("series"):
            nums[k] = int(v["part_no"])
            used.setdefault(v["series"], set()).add(int(v["part_no"]))
    by: dict[str, list[dict]] = {}
    for f in (_enrich(x) for x in files if x["kind"] == "parts" and x["key"] not in nums):
        by.setdefault(f["series"], []).append(f)
    for series, its in by.items():
        its.sort(key=lambda i: (i["part_no"] if i["part_no"] is not None else 10**6, i["order"]))
        taken = used.get(series, set()) | {i["part_no"] for i in its if i["part_no"]}
        live = (yt_max or {}).get(_series_title(series).lower(), 0)   # already on the channel
        nxt = max(taken | {0, live}) + 1
        for it in its:
            if it["part_no"]:
                nums[it["key"]] = it["part_no"]
            else:
                nums[it["key"]] = nxt
                nxt += 1
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
    taken = {v.get("publish_at") for k, v in ledger.items() if not k.startswith("__")
             and v.get("status") in ("uploading", "scheduled") and v.get("publish_at")}
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


def _tile(strips: list[Path], out: Path, stem: str, per: int = 12) -> list[Path]:
    """Tile subtitle strips into 2-column contact sheets (read left->right, top->bottom)."""
    from PIL import Image
    sheets = []
    for n in range(0, len(strips), per):
        group = [Image.open(p).convert("RGB") for p in strips[n:n + per]]
        w, h = group[0].size
        rows = (len(group) + 1) // 2
        sheet = Image.new("RGB", (w * 2, h * rows))
        for j, im in enumerate(group):
            sheet.paste(im.resize((w, h)), ((j % 2) * w, (j // 2) * h))
        p = out / f"{stem}_{n // per:02d}.jpg"
        sheet.save(p, quality=88)
        sheets.append(p)
    return sheets


def sample_dialogue(url: str, dur: float, gname: str, windows: int = 8,
                    secs: int = 75) -> tuple[str, str]:
    """Spoken dialogue AND on-screen subtitles from `windows` evenly spaced `secs`-long
    stretches (not the whole file: bounded cost + no full download). Returns
    (dialogue, subtitles).

    Dialogue: ElevenLabs Scribe first, then Whisper. SUBTITLES (per user 2026-09-22): the
    SAME ffmpeg read also saves the subtitle band of every KEYFRAME (~1/s on the Elgato
    4K60 recordings; -skip_frame nokey = no full 4K decode), which vision reads verbatim
    WITH speaker labels — the audio can't say who is talking, the subtitles can ('Jean:
    ...'), so titles/descriptions name the right people. Both fail open to ''."""
    from concurrent.futures import ThreadPoolExecutor

    from agents.content import (SUB_CROP, _clean_transcript, format_subtitles,
                                read_subtitle_sheets, sanitize)
    from core import elevenlabs, openai_client
    parts, stamps, win_sheets = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        for i in range(windows):
            t = max(0.0, dur * (0.04 + 0.92 * i / max(1, windows - 1)) - secs / 2)
            stamp = f"~{int(t // 60)}:{int(t % 60):02d}"
            a = tmpd / f"a{i}.mp3"
            # -t BEFORE -i = an INPUT limit, so it bounds BOTH outputs (after -i it only
            # capped the audio and the strips ran on to the end of the file).
            _ff(["-ss", f"{t:.2f}", "-t", str(secs), "-skip_frame", "nokey", "-i", url,
                 "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(a),
                 "-map", "0:v:0", "-an", "-vf", SUB_CROP, "-fps_mode", "vfr", "-q:v", "3",
                 str(tmpd / f"w{i}_%03d.jpg")], timeout=420)
            strips = sorted(tmpd.glob(f"w{i}_*.jpg"))
            if strips:
                try:
                    stamps.append(stamp)
                    win_sheets.append(_tile(strips, tmpd, f"sheet{i}"))
                except Exception as e:
                    stamps.pop()
                    log(f"subtitle tiling failed for window {i} ({e!r})")
            if not a.exists():
                continue
            try:
                txt = _clean_transcript(elevenlabs.speech_to_text(a))
                if not txt:
                    txt = _clean_transcript(openai_client.transcribe(a, prompt=gname))
            except Exception:
                txt = ""
            if txt:
                parts.append(f"[{stamp}] {sanitize(txt).strip()}")

        def _read(sheets: list[Path]) -> list[tuple[str, str]]:
            try:
                return read_subtitle_sheets(sheets, gname, what="video stretch")
            except Exception as e:
                log(f"subtitle read failed ({e!r})")
                return []

        # 3 sheets (of 12 strips) per vision call (a whole window in one call timed out on a
        # dialogue-heavy stretch), 4 in parallel; results re-joined in window/sheet order.
        jobs = [(w, sheets[i:i + 3]) for w, sheets in enumerate(win_sheets)
                for i in range(0, len(sheets), 3)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda j: _read(j[1]), jobs))
    rows, speakers, seen_win, prev = [], [], set(), None
    for (w, _), lines in zip(jobs, results):
        for sp, tx in lines:
            line = f"{sp}: {tx}" if sp != "?" else tx
            if line == prev:                                  # same line spanning two sheets
                continue
            prev = line
            rows.append((f"[{stamps[w]}] " if w not in seen_win else "") + line)
            seen_win.add(w)
            if sp != "?" and sp not in speakers:
                speakers.append(sp)
    if rows:
        log(f"subtitles: {len(rows)} line(s) across {len(stamps)} window(s); speakers={speakers}")
    return "\n".join(parts), format_subtitles(rows, speakers, what="video", cap=200)


def _vision(prompt: str, images: list[Path], timeout: int = 240) -> str:
    """Claude vision (Read tool) first, OpenAI vision fallback."""
    from core import claude_code, openai_client
    images = [Path(p).resolve() for p in images]       # the CLI's cwd differs -> absolute paths
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


def write_meta(it: dict, part_no: Optional[int], observation: str, dialogue: str,
               subtitles: str = "") -> dict:
    """Title + REAL written description + hashtags + tags, grounded in the footage and the
    game's lore bible, then an adversarial fact-check pass that fixes anything unsupported."""
    from agents.content import _text, extract_json
    from core import lore
    gname = _game_name(it["base"])
    bible = lore.lore_for(it["base"]) or "(no lore bible for this game — describe only what is shown)"
    is_part = it["kind"] == "parts"
    evidence = (f"WHAT THE FRAMES SHOW:\n{observation or '(none)'}\n\n"
                f"SAMPLED DIALOGUE (timestamped, may be partial):\n{(dialogue or '(none)')[:9000]}"
                + (f"\n\n{subtitles[:9000]}" if subtitles else ""))
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
        "them — and DO name the CONFIRMED SUBTITLE SPEAKERS who matter to the moment rather "
        "than a vague 'an ally' / 'someone'. Use the subtitle LINES (who says what to whom) as "
        "the main evidence of what the scene is about. Never invent events, quotes, motives or who is talking to whom. Do not spoil "
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
        "A name printed as a subtitle SPEAKER LABEL (CONFIRMED SPEAKERS) IS evidence — keep it; "
        "don't genericise a confirmed speaker into 'an ally'.\n"
        "Check EVERY claim in moment/summary against the evidence and the lore rules: invented "
        "names, wrong speaker/target/motive, calling allies enemies (or vice versa), events not "
        "shown, spoilers beyond the video, and NICKNAMES turned into a named character (e.g. "
        "'Red' is NOT automatically Omega Red — in Marvel's Wolverine it's Logan's name for Jean). "
        "Rewrite anything unsupported so it is plainly true — by REMOVING or genericising the "
        "claim, never by swapping in a different guessed name. Return ONLY JSON with the SAME keys, "
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

_YUNET = ROOT / "assets" / "models" / "face_detection_yunet_2023mar.onnx"


def _faces(path: Path) -> list[tuple[float, float, float, float, float]]:
    """Faces in an image as normalised (x, y, w, h, score), largest first. [] if OpenCV or
    the YuNet model is unavailable (the caller falls back to the action-frame picker)."""
    try:
        import os
        os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # silence per-call dnn WARN spam
        import cv2
        img = cv2.imread(str(path))
        if img is None or not _YUNET.exists():
            return []
        h, w = img.shape[:2]
        det = cv2.FaceDetectorYN.create(str(_YUNET), "", (w, h), 0.75, 0.3, 5000)
        _, found = det.detect(img)
        out = [(float(f[0]) / w, float(f[1]) / h, float(f[2]) / w, float(f[3]) / h, float(f[14]))
               for f in (found if found is not None else [])]
        return sorted(out, key=lambda f: f[2] * f[3], reverse=True)
    except Exception as e:
        log(f"face detection unavailable ({e!r})")
        return []


def _grab(url: str, t: float, p: Path, scale: str = "") -> Optional[Path]:
    vf = ["-vf", scale] if scale else []
    _ff(["-ss", f"{t:.3f}", "-i", url, "-frames:v", "1", *vf, "-q:v", "2", str(p)], timeout=240)
    return p if p.exists() and p.stat().st_size > 5000 else None


# Face height as a share of the thumbnail height (per user 2026-09-23: faces should fill at
# least ~1/3 of the thumbnail); the crop never goes tighter than MIN_CROP of the source
# height (keeps a 4K source >= ~600 px tall before the 720p resize — no mushy upscale).
FACE_SHARE, MIN_CROP = 0.42, 0.28


SUB_TOP = 0.80          # subtitles live below this share of the frame height


def _above_subs(y0: float, ch: float, H: int, keep_below: float = 0.0) -> tuple[float, float]:
    """Pull a crop's bottom edge ABOVE the subtitle band (per user 2026-09-23: zoom past a
    subtitle instead of discarding the frame — no retouching artifacts). Keeps `keep_below`
    (e.g. the chin) inside; gives up if that can't fit."""
    limit = SUB_TOP * H
    if y0 + ch <= limit or keep_below > limit:
        return y0, ch
    if ch <= limit:                                   # same zoom, shifted up
        return max(0.0, min(y0, limit - ch)), ch
    return 0.0, limit                                 # too tall to shift -> zoom in


def _face_crop(face: tuple, W: int, H: int) -> tuple[tuple[int, int, int, int], str]:
    """16:9 crop box around a face (face fills ~FACE_SHARE of the height, placed on a
    rule-of-thirds line, eyes in the upper half) + the top corner the logo should use
    (the one AWAY from the face)."""
    fx, fy, fw, fh = face[0] * W, face[1] * H, face[2] * W, face[3] * H
    ch = min(float(H), max(fh / FACE_SHARE, MIN_CROP * H))
    cw = ch * 16 / 9
    if cw > W:
        cw, ch = float(W), W * 9 / 16
    cx = fx + fw / 2
    right = cx >= W / 2                                   # keep the face on the side it's on
    x0 = cx - cw * (0.64 if right else 0.36)
    y0 = (fy + fh / 2) - ch * 0.42
    x0 = max(0.0, min(W - cw, x0))
    y0 = max(0.0, min(H - ch, y0))
    y0, ch = _above_subs(y0, ch, H, keep_below=fy + fh)   # never frame a subtitle line
    cw = min(float(W), ch * 16 / 9)
    x0 = max(0.0, min(W - cw, cx - cw * (0.64 if right else 0.36)))
    face_cx = (cx - x0) / cw
    return (int(x0), int(y0), int(x0 + cw), int(y0 + ch)), ("top-left" if face_cx >= 0.5 else "top-right")


def _nominate_wildcards(grabs: list, work: Path, gname: str, want: int = 8) -> list:
    """Vision picks the most THUMBNAIL-WORTHY no-face frames (a sharpness ranking picked
    menus and static UI instead). Sheets of 12 scan frames, read in parallel; returns
    [(t, path)] best-first. Falls back to sharpness order if vision is unavailable."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image, ImageDraw

    from agents.content import extract_json
    from core import frames as fr
    grabs = [g for g in grabs if fr.sharpness(g[1]) > 60]     # drop only the truly smeared
    if not grabs:
        return []
    sheets = []
    for n in range(0, len(grabs), 12):
        group = grabs[n:n + 12]
        tw, th = 480, 270
        sheet = Image.new("RGB", (tw * 3, th * ((len(group) + 2) // 3)), "black")
        d = ImageDraw.Draw(sheet)
        for j, (_, p) in enumerate(group):
            x, y = (j % 3) * tw, (j // 3) * th
            sheet.paste(Image.open(p).convert("RGB").resize((tw, th)), (x, y))
            d.rectangle([x, y, x + 46, y + 38], fill="black")
            d.text((x + 14, y + 8), str(n + j + 1), fill="yellow")
        sp = work / f"wildsheet{n // 12:02d}.jpg"
        sheet.save(sp, quality=88)
        sheets.append(sp)

    def _ask(sp: Path) -> list:
        try:
            j = extract_json(_vision(
                f"Numbered frames from a {gname} gameplay video, as candidate YouTube "
                "THUMBNAILS.\nPick AT MOST 2 that would make the most clickable thumbnail: a "
                "big striking subject — a character, a robot/creature head, glowing eyes, a "
                "boss, a dramatic action beat. Atmospheric haze, bloom or shallow focus is FINE "
                "if the subject reads clearly; do not prefer a frame merely for being sharp.\n"
                "NEVER pick a menu, map, inventory, loading, cutscene-black, dialogue-text or "
                "HUD/UI-heavy screen, or a plain empty wide shot. Pick NOTHING if none qualify.\n"
                'Return ONLY JSON: {"picks": [<numbers>], "why": "<short>"}', [sp])) or {}
            return [int(x) - 1 for x in (j.get("picks") or []) if str(x).isdigit()]
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=4) as pool:
        per_sheet = list(pool.map(_ask, sheets))
    # round-robin across sheets: taking them in sheet order let the FIRST sheets use up every
    # slot, so a strong frame late in the video (44 min in) never made the shortlist.
    idxs = [i for rank in range(max((len(p) for p in per_sheet), default=0))
            for p in per_sheet if rank < len(p) for i in [p[rank]]]
    out = [grabs[i] for i in idxs if 0 <= i < len(grabs)][:want]
    if out:
        log(f"thumbnail: vision nominated {len(out)} wildcard frame(s)")
        return out
    return sorted(grabs, key=lambda g: fr.sharpness(g[1]), reverse=True)[:want]


def _face_thumbnail(url: str, dur: float, title: str, work: Path, n: int = 96,
                    hero: str = "", hero_look: str = ""):
    """HIGH-CTR FACE THUMBNAIL (per user 2026-09-23 — 20 evenly spaced frames gave distant
    wide shots with no readable faces/emotion). Scans ~n frames across the whole video,
    keeps the ones with the LARGEST sharp faces (YuNet), punches in on the 4K source so
    the face fills ~42% of the frame on a thirds line, then a vision judge picks the most
    EMOTIONALLY INTENSE crop among clean (subtitle-free) ones. Returns (PIL image 1280x720,
    logo corner) or None when the video has no usable close-up faces."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image, ImageDraw

    from agents.content import extract_json
    from core import frames as fr
    work.mkdir(parents=True, exist_ok=True)
    ts = [dur * (0.05 + 0.90 * i / max(1, n - 1)) for i in range(n)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        grabs = list(pool.map(lambda it: (it[1], _grab(url, it[1], work / f"c{it[0]:03d}.jpg",
                                                         "scale=960:-2")), enumerate(ts)))
    cands = []
    for t, p in grabs:
        if not p:
            continue
        faces = _faces(p)
        if not faces or faces[0][3] < 0.10:              # face < 10% of height = too small to punch in
            continue
        sharp = fr.sharpness(p)
        cands.append({"t": t, "p": p, "face": faces[0], "score": faces[0][3] * (1 + min(sharp, 800) / 800)})
    log(f"thumbnail: {len(cands)} of {len(ts)} frames have a usable close-up face")
    if not cands:
        return None
    cands.sort(key=lambda c: c["score"], reverse=True)
    picked: list[dict] = []
    for c in cands:                                       # distinct moments, not 8 frames of one shot
        if all(abs(c["t"] - q["t"]) > 20 for q in picked):
            picked.append(c)
        if len(picked) == 10:
            break
    crops = []
    for i, c in enumerate(picked):
        full = _grab(url, c["t"], work / f"full{i}.jpg")
        if not full:
            continue
        im = Image.open(full).convert("RGB")
        faces = _faces(full) or [c["face"]]              # re-detect at full resolution
        box, corner = _face_crop(faces[0], *im.size)
        crops.append({"img": im.crop(box).resize((1280, 720), Image.LANCZOS), "corner": corner,
                      "t": c["t"]})
    # WILDCARDS (per user 2026-09-23): striking frames with NO detected face, so a non-human
    # close-up (Master Mold's glowing head, a Sentinel, a creature) can still compete. VISION
    # nominates them — ranking by sharpness picked menu/collectible screens (static UI scores
    # "sharpest") and buried the shot the user wanted, a soft, bloom-heavy glowing-eyes head
    # that ranked 76th of 96. Cropped above the subtitle band, so these are clean by design.
    wilds = _nominate_wildcards([g for g in grabs if g[1]
                                 and all(abs(g[0] - c["t"]) > 20 for c in picked)], work, title)
    used: list[float] = []
    for t, p in wilds:
        if len(used) == 6:
            break
        if any(abs(t - u) <= 20 for u in used):
            continue
        full = _grab(url, t, work / f"wild{len(used)}.jpg")
        if not full:
            continue
        im = Image.open(full).convert("RGB")
        W, H = im.size
        y0, ch = _above_subs(0.0, float(H), H)
        cw = min(float(W), ch * 16 / 9)
        crops.append({"img": im.crop((int((W - cw) / 2), int(y0), int((W + cw) / 2),
                                      int(y0 + ch))).resize((1280, 720), Image.LANCZOS),
                      "corner": "top-right", "t": t})
        used.append(t)
    if not crops:
        return None
    tw, th = 640, 360                                     # big tiles: the judge must SEE expressions
    rows = (len(crops) + 1) // 2
    sheet = Image.new("RGB", (tw * 2, th * rows), "black")
    d = ImageDraw.Draw(sheet)
    for i, c in enumerate(crops):
        x, y = (i % 2) * tw, (i // 2) * th
        sheet.paste(c["img"].resize((tw, th)), (x, y))
        d.rectangle([x, y, x + 54, y + 44], fill="black")
        d.text((x + 16, y + 10), str(i + 1), fill="yellow")
    sheet_p = work / "face_sheet.jpg"
    sheet.save(sheet_p, quality=90)
    # PER-IMAGE SCORECARD (a single "pick the best" let the judge rationalise — it called a
    # cyborg villain "Wolverine unmasked" and chose downcast eyes right after being told not
    # to). The judge rates every crop on fixed questions; CODE applies the hard rules + score.
    look = f" The hero looks like: {hero_look}." if hero_look else ""
    try:
        j = extract_json(_vision(
            f"These {len(crops)} numbered images are candidate YouTube THUMBNAIL crops for a "
            f"{hero or 'gameplay'} video titled “{title}”.{look}\nAssess EVERY image honestly "
            "and independently; do not assume a face is the hero.\n"
            "For each give:\n"
            "- subtitles: true if ANY subtitle/caption/dialogue text is visible\n"
            "- face: true if a clear FACE fills a good part of the image, OR a striking "
            "character/robot/creature HEAD does (a Sentinel or Master Mold head with glowing "
            "eyes counts) — false for the back of a head, a blur, or a plain wide shot\n"
            "- eyes_open: true only if the eyes are OPEN and looking forward/at something — false "
            "if closed, mid-blink, or looking DOWN (a full-face MASK, visor or a robot head "
            "counts as eyes_open when its lenses / glowing eyes face forward)\n"
            "- sharp: true only if the FACE is in focus — false for motion blur or a soft/"
            "smeared face, or if the head is badly cut off by the frame edge\n"
            f"- hero: true ONLY if you are confident this is {hero or 'the game’s main character'} "
            "(an iconic mask/costume counts; a different character or a villain is false)\n"
            "- emotion: 0-10 intensity of a READABLE emotion (10 = rage, a snarl or shout, terror, "
            "agony; 5 = a focused/tense look; 0-2 = neutral, tired, bored)\n"
            "- iconic: 0-10 how recognisable/striking the look is (signature costume or mask, "
            "blood, battle damage, dramatic lighting)\n"
            "- appeal: 0-10 how strongly YOU would click this as a YouTube thumbnail, judging "
            "the whole image (subject size, drama, colour, contrast, curiosity)\n"
            'Return ONLY JSON: {"items": [{"n": 1, "subtitles": false, "face": true, '
            '"eyes_open": true, "sharp": true, "hero": true, "emotion": 7, "iconic": 6, '
            '"appeal": 8, "note": "<short>"}]}',
            [sheet_p])) or {}
        rows = {int(r.get("n", 0)) - 1: r for r in (j.get("items") or []) if str(r.get("n", "")).isdigit()}
    except Exception as e:
        log(f"face judge failed ({e!r}) — action-frame fallback")
        return None

    def score(i: int) -> float:
        r = rows.get(i) or {}
        # The hero is a mild tiebreaker only (per user 2026-09-24: "we don't always want
        # Wolverine to be the thumbnail") — a striking villain or ally close-up can win.
        return (float(r.get("appeal", 0) or 0) + 0.5 * float(r.get("emotion", 0) or 0)
                + 0.4 * float(r.get("iconic", 0) or 0) + (0.5 if r.get("hero") else 0.0))

    ok = [i for i in range(len(crops)) if (rows.get(i) or {}).get("face")
          and (rows.get(i) or {}).get("eyes_open") and (rows.get(i) or {}).get("sharp")
          and not (rows.get(i) or {}).get("subtitles")]
    if not ok:
        log("thumbnail: no crop passed (face + eyes open + sharp + no subtitles) — action-frame fallback")
        return None
    # HERO CHECK, one crop at a time at full size (the grid judge ticked 'hero' for a
    # buzz-cut cyborg villain with no sideburns). First crop, best score first, that a focused
    # single-image check confirms is the hero wins; else the best-scoring passing crop.
    best = max(ok, key=score)
    # No hero VERIFICATION pass any more: the hero is only a 0.5 tiebreaker, so a wrong
    # 'hero' tick barely moves the ranking, and the check itself was unreliable (it flip-
    # flopped on the same cyborg crop between runs). Fewer calls, fewer failure modes.
    #
    # FINAL GATE, on the winner alone at full size: the grid judge waved through a mask seen
    # from ABOVE with the face hidden while claiming "eye openings prominent". One image, one
    # question set — judging a single image reliably is what this stage is for.
    passed = False
    for _ in range(len(crops)):            # every candidate gets gated; an unchecked pick is
        p = work / f"gate{best}.jpg"       # exactly how a face-down side view slipped through
        crops[best]["img"].save(p, quality=90)
        try:
            g = extract_json(_vision(
                "Judge this image as a YouTube thumbnail.\n"
                "- eyes_visible: are the subject's eyes (or a mask's eye lenses / a robot's "
                "glowing eyes) clearly visible and facing roughly toward the viewer? false if "
                "the head is turned away, tilted down, or the face is hidden\n"
                "- text_or_hud: is ANY subtitle, dialogue text, objective text, menu or "
                "health-bar/HUD overlay visible?\n"
                "- badly_cropped: is the head or subject cut off awkwardly by the frame edge?\n"
                'Return ONLY JSON: {"eyes_visible": true, "text_or_hud": false, '
                '"badly_cropped": false, "why": "<short>"}', [p])) or {}
        except Exception:
            passed = True             # vision down -> keep the pick, don't bin the whole pass
            break
        if g.get("eyes_visible") and not g.get("text_or_hud") and not g.get("badly_cropped"):
            passed = True
            break
        log(f"thumbnail: crop #{best + 1} failed the final gate ({g.get('why', '')}) — re-ranking")
        ok = [i for i in ok if i != best]
        if not ok:
            log("thumbnail: no crop survived the final gate — action-frame fallback")
            return None
        best = max(ok, key=score)
    if not passed:
        log("thumbnail: nothing passed the final gate — action-frame fallback")
        return None
    r = rows[best]
    log(f"thumbnail: face crop #{best + 1} at {crops[best]['t'] / 60:.1f} min — hero={r.get('hero')} "
        f"emotion={r.get('emotion')} iconic={r.get('iconic')} ({r.get('note', '')}); "
        f"passed {sorted(i + 1 for i in ok)} of {len(crops)}")
    return crops[best]["img"], crops[best]["corner"]


def make_thumbnail(frames: list[Path], base: str, title: str, out: Path,
                   url: str = "", dur: float = 0.0) -> Optional[Path]:
    """HIGH-CTR thumbnail + the game logo in the top corner away from the subject. First
    choice: an emotional close-up FACE punched in from the 4K source (_face_thumbnail);
    fallback: the most clickable action frame (vision-judged). No text, no 4K badge."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    from agents.content import extract_json
    from core import frames as fr
    face = None
    if url and dur:
        try:
            heroes = (_cfg().get("thumbnail_heroes", {}) or {}).get(base, {}) or {}
            face = _face_thumbnail(url, dur, title, out.parent / "thumb_faces",
                                   hero=str(heroes.get("name", "")),
                                   hero_look=str(heroes.get("look", "")))
        except Exception as e:
            log(f"face thumbnail failed ({e!r}) — action-frame fallback")
    if face:
        return _finish_thumbnail(face[0], face[1], base, out)
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
        # SUBTITLES ARE A HARD RULE (per user review of NG+ Part 1, 2026-09-22): the judge first
        # lists which frames carry subtitle/caption text, then must pick among the CLEAN ones.
        j = extract_json(_vision(
            f"This contact sheet shows {len(scored)} numbered frames from a YouTube gameplay "
            f"video titled “{title}”.\nSTEP 1: list every frame number that shows ANY subtitle, "
            "caption or dialogue text line (usually a white line near the bottom, often "
            "'Name: ...').\nSTEP 2: from the frames NOT in that list, pick the ONE that makes "
            "the most compelling, highest click-through thumbnail: a clear face or character "
            "in a dramatic moment, strong action, sharp, well-lit; NOT a menu/loading/black/"
            "HUD-cluttered frame, and not dominated by a blurry foreground object. Only if "
            "EVERY frame has subtitles may you pick one with them.\n"
            'Return ONLY JSON: {"subtitled": [<numbers>], "best": <number>, "why": "<short>"}',
            [sheet_p])) or {}
        best = max(0, min(len(scored) - 1, int(j.get("best", 1)) - 1))
        subs = {int(x) - 1 for x in (j.get("subtitled") or []) if str(x).isdigit()}
        if best in subs and len(subs) < len(scored):       # judge ignored the rule -> enforce
            best = next(i for i in range(len(scored)) if i not in subs)
            log("thumbnail judge picked a subtitled frame — switched to the best clean one")
        log(f"thumbnail frame #{best + 1} (subtitled frames: {sorted(i + 1 for i in subs)}): "
            f"{j.get('why', '')}")
    except Exception as e:
        log(f"thumbnail judge failed ({e!r}) — using the sharpest frame")
    frame = scored[best]
    corner = "top-left"
    try:
        # NEVER bottom-right: YouTube overlays the video DURATION badge there. Bottom-left is a
        # last resort (subtitle lines + progress bar). The logo box is ~400x170 px.
        j = extract_json(_vision(
            "A game LOGO (about 400x170 px, i.e. ~31% of the width and ~24% of the height) will "
            "be placed in ONE corner of this 1280x720 YouTube thumbnail, 34 px from the edges. "
            "Choose the corner where that box covers NO face, NO part of the main character's "
            "body, NO text and no important action. Allowed: top-left, top-right, bottom-left "
            "(bottom-right is NOT allowed — YouTube's duration badge sits there). Prefer "
            "top-left, then top-right; bottom-left only if both top corners are occupied. "
            'Return ONLY JSON: {"corner": "top-left|top-right|bottom-left", "why": "<short>"}',
            [frame])) or {}
        c = str(j.get("corner", "")).lower().strip()
        if c in ("top-left", "top-right", "bottom-left"):
            corner = c
        log(f"logo corner reasoning: {j.get('why', '')}")
    except Exception as e:
        log(f"logo-corner judge failed ({e!r}) — top-left")
    log(f"logo corner: {corner}")
    return _finish_thumbnail(Image.open(frame).convert("RGB").resize((1280, 720)), corner, base, out)


def _finish_thumbnail(img, corner: str, base: str, out: Path) -> Path:
    """Light grade + the game logo (with a legibility halo) in `corner`; saves a JPEG."""
    from PIL import Image, ImageEnhance, ImageFilter
    log(f"logo corner: {corner}")
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
        ((k, v) for k, v in ledger.items() if not k.startswith("__")
         and v.get("status") == "uploading"), None)
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
            # UNKNOWN GAME FOLDER GUARD: a folder that isn't a known game key would publish
            # with a guessed name, no logo, no lore and no playlist — HOLD it instead and
            # Telegram once per folder (e.g. "Marvel's Wolverine" instead of "wolverine").
            known = set((CONFIG.reels.get("game_names", {}) or {}))
            unknown = sorted({i["game"] for i in pool if i["base"] not in known})
            if unknown:
                meta_ = ledger.setdefault("__meta__", {})
                new = [g for g in unknown if g not in meta_.get("warned_unknown", [])]
                if new:
                    notify.telegram("⚠️ 4K long-form: these footage folders aren't a known game, "
                                    f"so I'm HOLDING them (not uploading): {', '.join(new)}. "
                                    "Rename the folder to the game key (e.g. wolverine, "
                                    f"spider-man2, halo) — known: {', '.join(sorted(known))}.")
                    meta_["warned_unknown"] = sorted(set(meta_.get("warned_unknown", [])) | set(new))
                    _save_ledger(ledger)
                pool = [i for i in pool if i["base"] in known]
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
    frames = extract_frames(url, dur, run_dir / "frames", n=20)   # more candidates -> a clean cinematic frame is likelier
    log(f"{len(frames)} frames extracted")

    if entry.get("title"):                               # resume: reuse the booked metadata
        meta = {k: entry[k] for k in ("title", "description", "tags") if k in entry}
    else:
        yt_max = youtube_part_max() if it["kind"] == "parts" else {}
        part_no = _part_numbers(files, ledger, yt_max).get(it["key"]) if it["kind"] == "parts" else None
        if part_no:
            log(f"part number {part_no} (highest on the channel for this series: "
                f"{yt_max.get(_series_title(it['series']).lower(), 0)})")
        obs = observe(frames, gname) if frames else ""
        dialogue, subs = sample_dialogue(url, dur, gname) if dur else ("", "")
        meta = write_meta(it, part_no, obs, dialogue, subs)
        (run_dir / "analysis.txt").write_text(f"OBSERVATION:\n{obs}\n\nDIALOGUE:\n{dialogue}"
                                              f"\n\n{subs}",
                                              encoding="utf-8")
    thumb = make_thumbnail(frames, it["base"], meta["title"], run_dir / "thumbnail.jpg",
                           url=url, dur=dur)
    (run_dir / "meta.json").write_text(json.dumps({**meta, "key": it["key"],
                                                   "publish_at": publish_at}, indent=2,
                                                  ensure_ascii=False), encoding="utf-8")
    log(f"TITLE: {meta['title']}")
    log(f"DESCRIPTION:\n{meta['description']}")
    log(f"TAGS: {', '.join(meta['tags'])}")
    if dry_run:
        log(f"DRY RUN — nothing uploaded. Review: {run_dir}")
        return {"dry_run": True, "dir": str(run_dir), **meta}

    if it["kind"] == "parts" and not entry.get("part_no"):
        entry = {**entry, "part_no": _part_numbers(files, ledger, youtube_part_max()).get(it["key"]),
                 "series": it["series"]}
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
        else:                                            # will retry next run — still say so
            notify.telegram(f"⚠️ Long-form upload attempt {ledger[it['key']]['attempts']} failed "
                            f"(retrying on the next run, slot kept): {meta['title']}\n{msg[:200]}")
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
    # Send the THUMBNAIL itself (per user review 2026-09-23: the auto-pick is good but not
    # infallible — seeing it lets the user swap one before the video goes public).
    msg = (f"🎬 Long-form scheduled: {meta['title']}\n"
           f"Goes public {_nz(publish_at)}\nhttps://youtu.be/{vid}")
    if not (thumb and Path(thumb).exists() and notify.telegram_photo(thumb, msg)):
        notify.telegram(msg)
    log(f"DONE https://youtu.be/{vid} (public at {_nz(publish_at)})")
    return {"video_id": vid, "publish_at": publish_at, **meta}


def stuck_uploads(hours: float = 24.0) -> list[dict]:
    """Uploads YouTube never finished processing (per user 2026-09-24: two orphaned Part 1
    attempts from a buggy B2 reader sat on 'Processing will begin shortly' for days, unseen
    because they aren't in the ledger). Telegrams ONCE per video id."""
    from core import notify
    from core import youtube as yt
    try:
        vids = [v for v in yt.list_uploads(300)
                if str(v.get("privacy")) != "deleted" and v.get("id")]
        st = yt.video_status([v["id"] for v in vids])
    except Exception as e:
        log(f"stuck-upload check failed ({e!r})")
        return []
    cutoff = time.time() - hours * 3600
    out = []
    for v in vids:
        s = st.get(v["id"]) or {}
        if s.get("upload") == "processed" or s.get("processing") not in ("processing", "failed"):
            continue
        try:
            ts = datetime.strptime(str(v.get("publishedAt", "")), "%Y-%m-%dT%H:%M:%SZ")
            ts = ts.replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            ts = 0.0
        if ts and ts > cutoff:
            continue                                   # give a fresh upload time to process
        out.append({**v, **s})
    if not out:
        return []
    ledger = _ledger()
    seen = set((ledger.get("__meta__", {}) or {}).get("stuck_reported", []))
    fresh = [v for v in out if v["id"] not in seen]
    if fresh:
        lines = "\n".join(f"• {v.get('title', '?')[:60]}\n  https://youtu.be/{v['id']}" for v in fresh)
        notify.telegram(f"⚠️ {len(fresh)} YouTube upload(s) stuck in processing for over "
                        f"{hours:.0f}h (they'll never publish — delete them in Studio):\n{lines}")
        meta = ledger.setdefault("__meta__", {})
        meta["stuck_reported"] = sorted(seen | {v["id"] for v in fresh})
        _save_ledger(ledger)
    for v in out:
        log(f"stuck upload: {v['id']} {v.get('title', '')[:50]} ({v.get('processing')})")
    return out


def cleanup(dry_run: bool = False) -> int:
    """Delete source footage from B2 `delete_after_days` after a CONFIRMED upload (YouTube
    reports the video 'processed'). A video that's gone from YouTube keeps its footage.
    Also flags uploads YouTube never finished processing."""
    from core import b2_store
    from core import youtube as yt
    stuck_uploads()
    days = float(_cfg().get("delete_after_days", 15))
    ledger = _ledger()
    due = {k: v for k, v in ledger.items() if not k.startswith("__")
           and v.get("status") == "scheduled" and v.get("video_id") and not v.get("b2_deleted")
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
