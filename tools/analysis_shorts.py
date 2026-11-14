"""Cut YouTube Shorts from a finished KG analysis long-form (2026-11-13, Bryce: "build a Shorts
version of our narrated analysis long-forms and post 2 Shorts per day on YouTube").

Inputs: the final long-form render and its timeline on private B2
(renders/analysis/<game>/<game>-analysis-<version>.mp4 and <version>/timeline.json), the edit list
data/analysis/<game>/edl.json (narration text per beat, game-audio cues) and the picks in
data/analysis/<game>/shorts.json. Plain code, no AI.

Each pick is one question and its answer, cut on sentence boundaries of the narration. A part is a
run of beats with an optional first phrase ("from") and last phrase ("to"); a pick can join parts
(a hard cut). Word times come from faster-whisper (word_timestamps) on each beat's own audio,
snapped to the known narration text so the spelling is the script's.

Layout (1080x1920, 60 fps): blurred, darkened fill of the same frames; the 16:9 picture full
width in the middle band (or "zoom": a 4:3 centre crop, larger); the hook at the top (Anton,
off-white #F2EEE8, one KG red #FF3D46 word); word-by-word captions in the lower-middle safe area
(above the bottom 20%), centred on the frame but never past x=918 where the Shorts buttons sit,
active word on a red box; BOSS KG and the KG avatar as a small watermark on the left; an optional
SPOILERS tag on the right; the last 1.5 s holds the frame with the
end line "Full video on the channel". Audio: two-pass loudnorm to -14 LUFS, true peak -1 dBTP or
lower. Fonts only from assets/fonts.

    py tools/analysis_shorts.py wolverine                 # words, resolve, render all, QC, sheets
    py tools/analysis_shorts.py wolverine --only s01,s04  # some picks
    py tools/analysis_shorts.py wolverine --resolve       # word times and cut points only
    py tools/analysis_shorts.py wolverine --dry-run       # print the upload slot plan
    py tools/analysis_shorts.py wolverine --upload        # private + publishAt, 2 a day (never run by an agent unasked)
    py tools/analysis_shorts.py wolverine --upload --facebook   # also schedule each on the Boss KG Facebook page

Uploads only ever go to YouTube as private with a publishAt; nothing is posted publicly by hand.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

W, H, FPS = 1080, 1920, 60
OFFWHITE = (242, 238, 232)
RED = (255, 61, 70)
INK = (12, 12, 14)
FONT_DIR = ROOT / "assets" / "fonts"
ANTON = FONT_DIR / "anton" / "Anton-Regular.ttf"
MONT = FONT_DIR / "montserrat" / "Montserrat.ttf"
AVATAR = ROOT / "assets" / "brand" / "kg-avatar.png"

# Layout, in 1080x1920 pixels.
HOOK_TOP, HOOK_BOT = 230, 560          # hook text block
ROW_Y = 600                            # watermark and SPOILERS row (centre)
BAND = {"band": (650, 1080, 608),      # top, width, height of the picture
        "zoom": (600, 1080, 810)}
CAP_Y = {"band": 1395, "zoom": 1468}   # caption line centre
# Hook, captions and end card are centred on the frame (Bryce, 2026-11-13: "align-center").
# To stay clear of the right 15% where the Shorts buttons are, every line is kept narrow enough
# to end before x=918 while centred on 540 (so it spans at most 162..918).
SAFE_L, SAFE_R = 54, 918
EDGE = 57                              # outer margin of the watermark row, both sides
CX = W // 2                            # 540, the centre line for hook, captions and end card
HALF = SAFE_R - CX                     # 378: the widest half-line that still clears the buttons
CAP_MAX_W = 2 * HALF - 76              # 680: text 200..880; the active box and its pop stay inside
HOOK_MAX_W = 2 * HALF - 20             # 736
WATERMARK = "BOSS KG"                  # channel name, not the @handle (Bryce, 2026-11-13)
SAFE_BOTTOM = int(H * 0.80)            # nothing of ours below this line
TAIL = 1.5                             # end line hold
END_LINE = "Full video on the channel"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


# ----------------------------------------------------------------------------- inputs

class Paths:
    def __init__(self, game: str, version: str):
        self.game, self.version = game, version
        self.data = ROOT / "data/analysis" / game
        self.out = ROOT / "output/analysis" / game / "shorts"
        self.src = self.out / "src"
        self.words = self.out / "words"
        self.work = self.out / "work"
        self.sheets = self.out / "sheets"
        for p in (self.src, self.words, self.work, self.sheets):
            p.mkdir(parents=True, exist_ok=True)
        self.video = self.src / f"{game}-analysis-{version}.mp4"
        self.timeline = self.src / f"timeline-{version}.json"  # per version: a stale v3 timeline broke the v8 re-cut
        self.picks = self.data / "shorts.json"
        self.b2_video = f"renders/analysis/{game}/{game}-analysis-{version}.mp4"
        self.b2_timeline = f"renders/analysis/{game}/{version}/timeline.json"


def fetch_sources(p: Paths) -> None:
    """Download the final render and its timeline from private B2 when they are not local."""
    import requests

    from core import b2_store
    for key, dst in [(p.b2_timeline, p.timeline), (p.b2_video, p.video)]:
        if dst.exists() and dst.stat().st_size > 0:
            continue
        url = b2_store.presigned_url(key, valid_seconds=3 * 3600)
        if not url:
            raise SystemExit(f"cannot sign B2 key {key} (check B2_KEY_ID / B2_APP_KEY)")
        print(f"downloading {key}", flush=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(8 << 20):
                    f.write(chunk)
        tmp.replace(dst)


def load_beats(p: Paths) -> dict[str, dict]:
    """Beats from edl.json with their real start and length in the render (timeline.json)."""
    edl = json.loads((p.data / "edl.json").read_text(encoding="utf-8"))
    tl = {x["id"]: x for x in json.loads(p.timeline.read_text(encoding="utf-8"))}
    beats = {}
    order = [b["id"] for b in edl["beats"]]
    for i, b in enumerate(edl["beats"]):
        t = tl[b["id"]]
        b = dict(b)
        b["start"], b["seconds"], b["idx"] = float(t["start"]), float(t["seconds"]), i
        if b["type"] == "game":  # the quoted game line(s) of the cue, minus the editor's note
            cue = re.sub(r"\s*\([^()]*\)\s*$", "", b.get("cue", ""))
            b["text"] = " ".join(re.findall(r'"([^"]+)"', cue))
        beats[b["id"]] = b
    beats["_order"] = order  # type: ignore[assignment]
    return beats


# ------------------------------------------------------------------------ word times

def norm(tok: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tok.lower().replace("’", "'"))


_MODELS: dict = {}
# Names only: prompting with the whole known paragraph made Whisper skip most of the speech
# (2026-11-13, 30 of 57 beats came back with one sentence and "Thanks for watching").
VOCAB = ("Logan, Jean Grey, Red, Nathaniel Essex, Mister Sinister, Sabretooth, Victor Creed, Apocalypse, "
         "Team X, Trask, Reavers, Walter, Tyger, Lowtown, Helix Engine, Phoenix Force, Shinigami, Sentinels.")


def whisper_words(wav: Path, prompt: str, model: str = "medium.en", vad: bool = False) -> list[dict]:
    if model not in _MODELS:
        from faster_whisper import WhisperModel
        _MODELS[model] = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=16)
    _MODEL = _MODELS[model]
    import numpy as np  # decode with ffmpeg: the installed PyAV is newer than faster-whisper expects
    raw = run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
              capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    segs, _ = _MODEL.transcribe(audio, language="en", word_timestamps=True, beam_size=5,
                                initial_prompt=prompt[:600] or None, vad_filter=vad,
                                condition_on_previous_text=False)
    out = []
    for s in segs:
        for w in s.words or []:
            out.append({"w": w.word.strip(), "s": float(w.start), "e": float(w.end)})
    return out


def match_ratio(known: str, heard: list[dict]) -> float:
    kn = [norm(x) for x in known.split()]
    hn = [norm(x["w"]) for x in heard]
    m = sum(bl.size for bl in difflib.SequenceMatcher(None, kn, hn, autojunk=False).get_matching_blocks())
    return m / max(1, len(kn))


def snap(known: str, heard: list[dict], t0: float, t1: float) -> list[dict]:
    """Give every word of the known text a time: matched words take Whisper's time, the rest
    are spread over the gap between their matched neighbours by character length."""
    kw = known.split()
    kn = [norm(x) for x in kw]
    hn = [norm(x["w"]) for x in heard]
    times: list[tuple[float, float] | None] = [None] * len(kw)
    sm = difflib.SequenceMatcher(None, kn, hn, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (heard[j1 + k]["s"], heard[j1 + k]["e"])
        elif tag == "replace" and j2 > j1:  # different counts: share the heard span
            s, e = heard[j1]["s"], heard[j2 - 1]["e"]
            lens = [max(1, len(kn[i])) for i in range(i1, i2)]
            tot, acc = sum(lens), s
            for i, ln in zip(range(i1, i2), lens):
                d = (e - s) * ln / tot
                times[i] = (acc, acc + d)
                acc += d
    i = 0
    while i < len(kw):  # words Whisper missed: interpolate between neighbours
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(kw) and times[j] is None:
            j += 1
        s = times[i - 1][1] if i > 0 else t0
        e = times[j][0] if j < len(kw) else t1
        if e <= s:
            e = s + 0.15 * (j - i)
        lens = [max(1, len(kn[k])) for k in range(i, j)]
        tot, acc = sum(lens), s
        for k, ln in zip(range(i, j), lens):
            d = (e - s) * ln / tot
            times[k] = (acc, acc + d)
            acc += d
        i = j
    out = []
    for k, w in enumerate(kw):
        s, e = times[k]
        out.append({"w": w, "s": round(s, 3), "e": round(max(e, s + 0.06), 3)})
    for a, b in zip(out, out[1:]):  # keep words in order and non-overlapping
        if b["s"] < a["s"]:
            b["s"] = a["s"] + 0.01
        if a["e"] > b["s"]:
            a["e"] = b["s"]
    return out


def beat_words(p: Paths, b: dict) -> list[dict]:
    """Absolute (render-time) word times for one beat, cached per beat."""
    cache = p.words / f"{b['id']}.json"
    sig = f"{p.version}|{b['start']}|{b['seconds']}|{b['text']}"
    if cache.exists():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("sig") == sig:
            return c["words"]
    if not b["text"]:
        return []
    wav = p.work / f"{b['id']}.wav"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{b['start']:.3f}", "-t", f"{b['seconds']:.3f}",
         "-i", str(p.video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    heard = whisper_words(wav, VOCAB)
    ratio = match_ratio(b["text"], heard)
    if ratio < 0.6:  # game lines under music or effects: try the large model without the prompt
        alt = whisper_words(wav, "", model="large-v3", vad=True)
        if match_ratio(b["text"], alt) > ratio:
            heard, ratio = alt, match_ratio(b["text"], alt)
    words = snap(b["text"], heard, 0.0, b["seconds"])
    for w in words:
        w["s"] = round(w["s"] + b["start"], 3)
        w["e"] = round(w["e"] + b["start"], 3)
    cache.write_text(json.dumps({"sig": sig, "match": round(ratio, 2), "heard": " ".join(x["w"] for x in heard), "words": words},
                                indent=0), encoding="utf-8")
    wav.unlink(missing_ok=True)
    return words


# -------------------------------------------------------------------------- resolve

def find_phrase(words: list[dict], phrase: str, last: bool) -> int:
    """Index of the first (or, with last=True, the final) word of `phrase` in `words`."""
    want = [norm(x) for x in phrase.split() if norm(x)]
    have = [norm(w["w"]) for w in words]
    hits = [i for i in range(len(have) - len(want) + 1) if have[i:i + len(want)] == want]
    if not hits:
        raise ValueError(f"phrase not found: {phrase!r}")
    return hits[-1] + len(want) - 1 if last else hits[0]


# The long-form's crops (tools/analysis_render.py vchain): "sub" hides game subtitles under
# narration, "hud" also hides boss bars.
CROPS = {"sub": "crop=iw*0.78:ih*0.78:(iw-ow)/2:ih*0.012,",
         "hud": "crop=iw*0.70:ih*0.70:(iw-ow)/2:ih*0.10,"}


def fetch_clip(p: Paths, part: dict) -> Path:
    """A source clip range from B2 (clips.json), local, 1920x1080 at 60 fps with PCM audio,
    with the long-form's crop when asked ("sub" or "hud")."""
    idx, t0, t1 = int(part["clip"]), float(part["in"]), float(part["out"])
    crop = part.get("crop") or ""
    out = p.out / "clips" / f"c{idx:03d}_{t0:.2f}_{t1:.2f}{'_' + crop if crop else ''}.mkv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return out
    from core import b2_store
    key = json.loads((p.data / "clips.json").read_text(encoding="utf-8"))["clips"][str(idx)]["key"]
    url = b2_store.presigned_url(key, valid_seconds=3600)
    if not url:
        raise SystemExit(f"cannot sign B2 key {key}")
    run(["ffmpeg", "-v", "error", "-y", "-reconnect", "1", "-reconnect_on_network_error", "1",
         "-ss", f"{t0:.3f}", "-i", url, "-t", f"{t1 - t0:.3f}", "-map", "0:v:0", "-map", "0:a:0",
         "-vf", f"{CROPS.get(crop, '')}scale=1920:1080:flags=lanczos,fps=60,setsar=1", "-c:v", "libx264",
         "-preset", "fast", "-crf", "12", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)])
    return out


def loudness(path: Path) -> float:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    return float(m[-1]) if m else -70.0


def resolve_clip_part(part: dict, p: Paths) -> dict:
    """A range straight from a source clip, for a game line the long-form cut missed."""
    path = fetch_clip(p, part)
    dur = float(part["out"]) - float(part["in"])
    bid = f"c{int(part['clip']):03d}"
    cache = p.words / f"{bid}_{part['in']}_{part['out']}.json"
    if cache.exists() and json.loads(cache.read_text(encoding="utf-8")).get("text") == part["text"]:
        words = json.loads(cache.read_text(encoding="utf-8"))["words"]
    else:
        words = snap(part["text"], whisper_words(path, VOCAB), 0.0, dur)
        cache.write_text(json.dumps({"text": part["text"], "words": words}), encoding="utf-8")
    gain = max(-6.0, min(24.0, float(part.get("lufs", -15.5)) - loudness(path)))
    words = [dict(w, beat=bid, kind="game") for w in words]
    return {"beats": [bid], "src": str(path), "start": 0.0, "end": round(dur, 3), "words": words,
            "gain_db": round(gain, 1), "clip": int(part["clip"]), "in": part["in"], "out": part["out"]}


def swap_picture(p: Paths, pt: dict, pics) -> None:
    """Replace stretches of a part's picture and keep its own audio. Each entry covers part
    seconds [at, until) (until defaults to the part's end) with either a clean source clip range
    ({"clip", "in", "crop"}) or a later stretch of the long-form itself ({"lf": render seconds}).
    Uses: a long-form chapter card over a Short's opening, a bloodied close-up held too long.
    The result is a local file the render reads instead of the long-form."""
    pics = pics if isinstance(pics, list) else [pics]
    dur = pt["end"] - pt["start"]
    segs, t = [], 0.0
    for pic in sorted(pics, key=lambda x: float(x["at"])):
        a, u = float(pic["at"]), float(pic.get("until", dur))
        if a > t:
            segs.append({"lf": pt["start"] + t, "at": t, "until": a})
        segs.append(dict(pic, at=a, until=u))
        t = u
    if t < dur - 1e-3:
        segs.append({"lf": pt["start"] + t, "at": t, "until": dur})
    tag = hashlib.sha1(json.dumps([pt["start"], pt["end"], segs], sort_keys=True).encode()).hexdigest()[:10]
    out = p.out / "clips" / f"swap_{tag}.mkv"
    if not out.exists():
        inputs, chains = ["-ss", f"{pt['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(p.video)], []
        for k, sg in enumerate(segs):
            n = sg["until"] - sg["at"]
            if "clip" in sg:
                src = fetch_clip(p, {"clip": sg["clip"], "in": sg["in"], "out": float(sg["in"]) + n + 0.2,
                                     "crop": sg.get("crop")})
                inputs += ["-i", str(src)]
            else:
                inputs += ["-ss", f"{sg['lf']:.3f}", "-t", f"{n + 0.1:.3f}", "-i", str(p.video)]
            chains.append(f"[{k + 1}:v]trim=duration={n:.4f},setpts=PTS-STARTPTS,fps={FPS},setsar=1,"
                          f"format=yuv420p[s{k}]")
        graph = ";".join(chains) + ";" + "".join(f"[s{k}]" for k in range(len(segs))) +             f"concat=n={len(segs)}:v=1:a=0[v]"
        run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-c:a", "pcm_s16le", "-ar", "48000",
             "-t", f"{dur:.4f}", str(out)])
    pt["src"] = str(out)
    pt["picture"] = segs
    for w in pt["words"]:
        w["s"], w["e"] = w["s"] - pt["start"], w["e"] - pt["start"]
    pt["start"], pt["end"] = 0.0, round(dur, 3)


def first_cut(src: str, start: float, window: float = 0.65) -> float | None:
    """Seconds after `start` of a picture cut inside the first `window` seconds (the tail of the
    previous long-form shot would flash on screen and on every loop), or None."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{window:.3f}",
                          "-i", src, "-an", "-vf", "scale=480:-2,select='gt(scene,0.2)',showinfo",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", log) if float(x) > 0.02]
    return cuts[-1] if cuts else None


def resolve_part(part: dict, beats: dict, p: Paths) -> dict:
    """A part's cut in render time, plus its caption words (narration and game lines)."""
    if "clip" in part:
        return resolve_clip_part(part, p)
    pt = resolve_part_lf(part, beats, p)
    pt["lf"] = [pt["start"], pt["end"]]
    if part.get("picture"):
        swap_picture(p, pt, part["picture"])
    cut = first_cut(pt.get("src", str(p.video)), pt["start"])
    if cut is not None:  # hold the first clean frame over the flash instead (audio untouched)
        pt["vskip"] = round(cut + 1 / FPS, 4)
    return pt


def resolve_part_lf(part: dict, beats: dict, p: Paths) -> dict:
    order = beats["_order"]
    ids = order[order.index(part["beats"][0]): order.index(part["beats"][-1]) + 1]
    seq = []
    for bid in ids:
        b = beats[bid]
        for w in beat_words(p, b):
            seq.append(dict(w, beat=bid, kind=b["type"]))
    first, last = beats[ids[0]], beats[ids[-1]]
    # start
    gs = 0
    if part.get("from"):
        fb = [w for w in seq if w["beat"] == ids[0]]
        gs = seq.index(fb[find_phrase(fb, part["from"], last=False)])
        prev_e = seq[gs - 1]["e"] if gs > 0 else first["start"]
        start = max(seq[gs]["s"] - 0.12, prev_e + 0.04, first["start"])
    else:
        start = first["start"] + (0.0 if first["type"] == "game" else 0.05)
    # end
    ge = len(seq) - 1
    if part.get("to"):
        lb = [w for w in seq if w["beat"] == ids[-1]]
        ge = seq.index(lb[find_phrase(lb, part["to"], last=True)])
        nxt = seq[ge + 1]["s"] if ge + 1 < len(seq) else last["start"] + last["seconds"]
        end = min(seq[ge]["e"] + 0.40, nxt - 0.05, last["start"] + last["seconds"])
    else:
        end = last["start"] + last["seconds"]
        if last["type"] == "narr" and seq:
            end = min(end, seq[-1]["e"] + 0.40)
    words = []
    for w in seq[gs:ge + 1]:
        w = dict(w, s=max(w["s"], start), e=min(w["e"], end))
        words.append(w)
    return {"beats": ids, "start": round(start, 3), "end": round(end, 3), "words": words}


def credits_text(p: Paths) -> str:
    music = json.loads((p.data / "music.json").read_text(encoding="utf-8"))
    return "Music:\n" + "\n".join(music.get("credits", []))


def gear_cta() -> str:
    try:
        from core.config import CONFIG
        return str(CONFIG.reels.get("gear_cta", "") or "").strip()
    except Exception:
        return ""


def build_description(cfg: dict, s: dict, p: Paths) -> str:
    tags = cfg["hashtags_base"] + s.get("hashtags_extra", [])
    parts = [f"Full video: {cfg['full_video']}", s["blurb"]]
    if s.get("spoilers"):
        parts[-1] += " Spoilers for the ending."
    parts.append(credits_text(p))
    cta = gear_cta()
    if cta:
        parts.append(cta)
    parts.append("KG")
    parts.append(" ".join(tags[:5]))
    return "\n\n".join(parts)


def resolve(p: Paths, cfg: dict, beats: dict, only: set[str]) -> None:
    for s in cfg["shorts"]:
        if only and s["id"] not in only:
            continue
        parts = [resolve_part(pt, beats, p) for pt in s["parts"]]
        s["_parts"] = parts
        s["start"] = parts[0].get("lf", [parts[0]["start"]])[0]
        s["end"] = parts[-1].get("lf", [0, parts[-1]["end"]])[1]
        s["flash_holds"] = {str(k): x["vskip"] for k, x in enumerate(parts) if x.get("vskip")}
        s["seconds"] = round(sum(x["end"] - x["start"] for x in parts) + TAIL, 2)
        s["cuts"] = [{"clip": x["clip"], "in": x["in"], "out": x["out"]} if "clip" in x else
                     x.get("lf", [x["start"], x["end"]]) for x in parts]
        s["description"] = build_description(cfg, s, p)
        s["tags"] = list(dict.fromkeys(cfg["tags_base"] + s.get("tags_extra", [])))
        first = " ".join(w["w"] for w in parts[0]["words"][:12])
        lastw = " ".join(w["w"] for w in parts[-1]["words"][-10:])
        print(f"{s['id']} {s['seconds']:5.1f}s  {s['start']:.2f}-{s['end']:.2f}  [{first} ...] ... [{lastw}]",
              flush=True)


def save_picks(p: Paths, cfg: dict) -> None:
    keep = json.loads(json.dumps(cfg, default=str))
    for s in keep["shorts"]:
        s.pop("_parts", None)
    text = json.dumps(keep, indent=1, ensure_ascii=False)
    if "\u2014" in text:
        raise SystemExit("em-dash found in shorts.json; fix the picks")
    p.picks.write_text(text + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- drawing

def font(path: Path, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise SystemExit(f"missing repo font {path}")
    f = ImageFont.truetype(str(path), size)
    if weight:
        f.set_variation_by_name(weight)
    return f


def text_w(f, s: str) -> int:
    l, t, r, b = f.getbbox(s)
    return r - l


def draw_shadowed(im: Image.Image, xy, text, f, fill, stroke=6, shadow=10):
    """Text with a soft drop shadow and a dark outline so it reads on any frame."""
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((xy[0], xy[1] + shadow * 0.6), text, font=f, fill=(0, 0, 0, 170),
                            stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(shadow)))
    ImageDraw.Draw(im).text(xy, text, font=f, fill=fill, stroke_width=stroke, stroke_fill=(*INK, 255))


def hook_layer(s: dict, frame: str) -> Image.Image:
    """Static layer: hook (top), watermark and SPOILERS row above the picture."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    words = [w if any(c.isdigit() for c in w) else w.upper() for w in s["hook"].split()]
    accent = {norm(x) for x in s.get("accent", "").upper().split()}
    lines: list[list[str]] = []
    size = 128
    while size > 70:
        f = font(ANTON, size)
        if text_w(f, " ".join(words)) <= HOOK_MAX_W and len(words) <= 3:
            lines = [words]
        else:  # two lines, split where the longer line is shortest
            best = None
            for k in range(1, len(words)):
                wmax = max(text_w(f, " ".join(words[:k])), text_w(f, " ".join(words[k:])))
                if best is None or wmax < best[0]:
                    best = (wmax, k)
            lines = [words] if best is None else [words[:best[1]], words[best[1]:]]
            if best is not None and best[0] > HOOK_MAX_W:
                size -= 6
                continue
        lh = int(size * 1.08)
        if len(lines) <= 2 and lh * len(lines) <= HOOK_BOT - HOOK_TOP:
            break
        size -= 6
    f = font(ANTON, size)
    lh = int(size * 1.08)
    y = (HOOK_TOP + HOOK_BOT) // 2 - lh * len(lines) // 2
    sp = text_w(f, " ")
    for line in lines:
        x = CX - text_w(f, " ".join(line)) // 2
        for w in line:
            col = RED if norm(w) in accent else OFFWHITE
            draw_shadowed(im, (x, y), w, f, (*col, 255), stroke=5, shadow=12)
            x += text_w(f, w) + sp
        y += lh
    # watermark: KG avatar + BOSS KG, left, just above the picture
    top = BAND[frame][0]
    row = top - 50 if frame == "band" else top - 46
    av = Image.open(AVATAR).convert("RGBA").resize((60, 60), Image.LANCZOS)
    mask = Image.new("L", (60, 60), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 59, 59), fill=255)
    av.putalpha(Image.composite(av.getchannel("A"), Image.new("L", (60, 60), 0), mask))
    ring = Image.new("RGBA", (66, 66), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, 65, 65), fill=(*OFFWHITE, 230))
    im.alpha_composite(ring, (57, row - 33))
    im.alpha_composite(av, (60, row - 30))
    fw = font(MONT, 34, "Bold")
    ImageDraw.Draw(im).text((138, row), WATERMARK, font=fw, fill=(*OFFWHITE, 225), anchor="lm",
                            stroke_width=2, stroke_fill=(*INK, 200))
    if s.get("spoilers"):
        ft = font(ANTON, 36)
        label = "SPOILERS"
        tw = text_w(ft, label)
        x1 = W - EDGE                    # right-aligned, mirroring the avatar's left margin
        x0 = x1 - tw - 36
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((x0, row - 26, x1, row + 26), radius=10, fill=(*RED, 240))
        d.text(((x0 + x1) // 2, row + 1), label, font=ft, fill=(*OFFWHITE, 255), anchor="mm")
    return im


def end_layer(frame: str) -> Image.Image:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top, _, bh = BAND[frame]
    ImageDraw.Draw(im).rectangle((0, top, W, top + bh), fill=(0, 0, 0, 110))
    f = font(ANTON, 84)
    y = CAP_Y[frame] - 50
    # one line: "FULL VIDEO" in red, the rest off-white
    a, b = "FULL VIDEO", " ON THE CHANNEL"
    tw = text_w(f, a + b)
    if tw > 2 * HALF - 40:
        f = font(ANTON, int(84 * (2 * HALF - 40) / tw))
        tw = text_w(f, a + b)
    x = CX - tw // 2
    draw_shadowed(im, (x, y), a, f, (*RED, 255), stroke=5, shadow=12)
    draw_shadowed(im, (x + text_w(f, a) + text_w(f, " "), y), b.strip(), f, (*OFFWHITE, 255),
                  stroke=5, shadow=12)
    # a small play triangle under it, pointing at nothing in particular: the channel
    cx, cy = CX, y + 150
    ImageDraw.Draw(im).polygon([(cx - 18, cy - 22), (cx - 18, cy + 22), (cx + 22, cy)], fill=(*OFFWHITE, 235))
    return im


# --------------------------------------------------------------------------- captions

CAP_SIZE = 68                          # was 80; Bryce asked for a little smaller (2026-11-13)
CAP_STRIP_H = 220


def caption_pages(words: list[dict]) -> list[list[dict]]:
    """1 to 3 words per page; a page ends at a sentence or clause end, a pause or the width."""
    f = font(MONT, CAP_SIZE, "Black")
    pages, cur = [], []
    for i, w in enumerate(words):
        if cur:
            prev = cur[-1]
            text = " ".join(x["disp"] for x in cur + [w])
            if (len(cur) >= 3 or w["s"] - prev["e"] > 0.35 or prev["kind"] != w["kind"]
                    or prev.get("part") != w.get("part") or re.search(r"[.?!,:;]$", prev["w"].rstrip('"”'))
                    or text_w(f, text) > CAP_MAX_W - 40):
                pages.append(cur)
                cur = []
        cur.append(w)
    if cur:
        pages.append(cur)
    return pages


def draw_caption(page: list[dict], active: int, pop: float) -> Image.Image:
    """One caption state as a 1080 x CAP_STRIP_H RGBA strip."""
    f = font(MONT, CAP_SIZE, "Black")
    im = Image.new("RGBA", (W, CAP_STRIP_H), (0, 0, 0, 0))
    game = page[0]["kind"] == "game"
    toks = [w["disp"] for w in page]
    if game:  # quote marks open the line's first page and close its last
        if page[0].get("q_open"):
            toks[0] = "\u201c" + toks[0]
        if page[-1].get("q_close"):
            toks[-1] = toks[-1] + "\u201d"
    sp = int(text_w(f, " ") * 1.7)
    widths = [text_w(f, t) for t in toks]
    total = sum(widths) + sp * (len(toks) - 1)
    scale = min(1.0, (CAP_MAX_W - 30) / max(1, total))
    if scale < 1.0:
        f = font(MONT, int(CAP_SIZE * scale), "Black")
        sp = int(text_w(f, " ") * 1.7)
        widths = [text_w(f, t) for t in toks]
        total = sum(widths) + sp * (len(toks) - 1)
    x = CX - total // 2
    cy = CAP_STRIP_H // 2
    asc, desc = f.getmetrics()
    for i, (t, wd) in enumerate(zip(toks, widths)):
        if i == active:
            # the live word sits on a red box (dialogue: off-white box) that pops in
            padx, pady = 14, 8
            bw, bh = (wd + 2 * padx) * pop, (asc * 0.78 + 2 * pady) * pop
            bx, by = x + wd / 2, cy + 2
            box = (*(RED if not game else OFFWHITE), 255)
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle((bx - bw / 2, by - bh / 2 + 6, bx + bw / 2, by + bh / 2 + 6),
                                                 radius=12, fill=(0, 0, 0, 150))
            im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
            ImageDraw.Draw(im).rounded_rectangle((bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2),
                                                 radius=12, fill=box)
            fill = OFFWHITE if not game else INK
            ImageDraw.Draw(im).text((x + wd / 2, cy), t, font=f, fill=(*fill, 255), anchor="mm",
                                    stroke_width=0)
        else:
            col = OFFWHITE
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((x + wd / 2, cy + 5), t, font=f, fill=(0, 0, 0, 160), anchor="mm",
                                    stroke_width=6, stroke_fill=(0, 0, 0, 160))
            im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5)))
            ImageDraw.Draw(im).text((x + wd / 2, cy), t, font=f, fill=(*col, 255), anchor="mm",
                                    stroke_width=5, stroke_fill=(*INK, 255))
        x += wd + sp
    return im


def caption_track(s: dict, work: Path) -> tuple[Path, float]:
    """Caption strip as an ffconcat list of PNG states on the Short's own clock."""
    words, off = [], 0.0
    for k, pt in enumerate(s["_parts"]):
        for w in pt["words"]:
            disp = w["w"].strip('"').upper()
            if not disp:
                continue
            words.append({"w": w["w"], "disp": disp, "kind": w["kind"], "part": k, "beat": w["beat"],
                          "s": max(0.0, w["s"] - pt["start"] + off), "e": w["e"] - pt["start"] + off})
        off += pt["end"] - pt["start"]
    for i, w in enumerate(words):  # where each quoted game line opens and closes
        if w["kind"] == "game":
            w["q_open"] = i == 0 or words[i - 1]["beat"] != w["beat"]
            w["q_close"] = i == len(words) - 1 or words[i + 1]["beat"] != w["beat"]
    total = off + TAIL
    n_frames = int(round(total * FPS))
    pages = caption_pages(words)
    # page index and active word for each frame
    spans = []
    for pi, pg in enumerate(pages):
        nxt = pages[pi + 1][0]["s"] if pi + 1 < len(pages) else off
        spans.append((pg[0]["s"], min(nxt, pg[-1]["e"] + 0.5), pi))
    POP = [1.16, 1.09, 1.04]
    states, keys = {}, []
    for fi in range(n_frames):
        t = fi / FPS
        key = None
        for a, b, pi in spans:
            if a <= t < b:
                pg = pages[pi]
                act = 0
                for j, w in enumerate(pg):
                    if t >= w["s"]:
                        act = j
                since = int((t - pg[act]["s"]) * FPS)
                pop = POP[since] if 0 <= since < len(POP) else 1.0
                key = (pi, act, pop)
                break
        keys.append(key)
    cdir = work / f"{s['id']}-cap"
    cdir.mkdir(exist_ok=True)
    for f in cdir.glob("*.png"):
        f.unlink()
    blank = cdir / "blank.png"
    Image.new("RGBA", (W, CAP_STRIP_H), (0, 0, 0, 0)).save(blank)
    lines, i = ["ffconcat version 1.0"], 0
    while i < len(keys):
        j = i
        while j < len(keys) and keys[j] == keys[i]:
            j += 1
        key = keys[i]
        if key is None:
            path = blank
        else:
            if key not in states:
                pi, act, pop = key
                path = cdir / f"c{len(states):04d}.png"
                draw_caption(pages[pi], act, pop).save(path, compress_level=1)
                states[key] = path
            path = states[key]
        lines.append(f"file '{path.as_posix()}'")
        lines.append(f"duration {(j - i) / FPS:.6f}")
        i = j
    lines.append(f"file '{blank.as_posix()}'")
    lst = work / f"{s['id']}-cap.ffconcat"
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lst, total


# ----------------------------------------------------------------------------- render

def audio_graph(parts: list[dict]) -> tuple[str, str]:
    """Filter text joining the parts' audio with short fades, then the silent tail."""
    chains, labels = [], []
    for i, pt in enumerate(parts):
        d = pt["end"] - pt["start"]
        last = i == len(parts) - 1
        fo = 0.35 if last else 0.06
        gain = f"volume={pt['gain_db']}dB," if pt.get("gain_db") else ""
        chains.append(f"[{i}:a]aresample=48000,{gain}afade=t=in:d=0.03,afade=t=out:st={d - fo:.3f}:d={fo}[a{i}]")
        labels.append(f"[a{i}]")
    chains.append("".join(labels) + f"concat=n={len(parts)}:v=0:a=1,apad=pad_dur={TAIL}[acat]")
    return ";".join(chains), "[acat]"


def render_short(s: dict, p: Paths, src: Path) -> Path:
    parts = s["_parts"]
    frame = s.get("frame", "band")
    work = p.work
    hook = work / f"{s['id']}-hook.png"
    hook_layer(s, frame).save(hook)
    endp = work / f"{s['id']}-end.png"
    end_layer(frame).save(endp)
    cap, total = caption_track(s, work)
    body = total - TAIL
    inputs = []
    for pt in parts:
        inputs += ["-ss", f"{pt['start']:.3f}", "-t", f"{pt['end'] - pt['start']:.3f}", "-i", pt.get("src", str(src))]
    part_inputs = list(inputs)
    n = len(parts)
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(hook)]
    inputs += ["-f", "concat", "-safe", "0", "-i", str(cap)]
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(endp)]
    ih, ic, ie = n, n + 1, n + 2
    top, bw, bh = BAND[frame]
    norm_v = "".join(
        f"[{i}:v]" + (f"trim=start={pt['vskip']:.4f},setpts=PTS-STARTPTS,tpad=start_mode=clone:"
                      f"start_duration={pt['vskip']:.4f}," if pt.get("vskip") else "")
        + f"scale=1920:1080,fps={FPS},setsar=1,format=yuv420p[n{i}];" for i, pt in enumerate(parts))
    vparts = norm_v + "".join(f"[n{i}]" for i in range(n))
    afil, alab = audio_graph(parts)
    if frame == "zoom":
        fg = f"[fgsrc]crop=1440:1080:240:0,scale={bw}:{bh}:flags=lanczos,setsar=1[fg]"
    else:
        fg = f"[fgsrc]scale={bw}:{bh}:flags=lanczos,setsar=1[fg]"
    cap_y = CAP_Y[frame] - CAP_STRIP_H // 2
    vf = (f"{vparts}concat=n={n}:v=1:a=0,fps={FPS},tpad=stop_mode=clone:stop_duration={TAIL},"
          f"trim=duration={total:.4f},setpts=PTS-STARTPTS,split[bgsrc][fgsrc];"
          f"[bgsrc]scale=-2:480,crop=270:480,boxblur=10:2,scale={W}:{H}:flags=bicubic,"
          f"colorchannelmixer=rr=0.42:gg=0.42:bb=0.42,setsar=1[bg];"
          f"{fg};"
          f"[bg][fg]overlay=0:{top}[v1];"
          f"[{ih}:v]format=rgba,trim=duration={total:.4f}[hk];"
          f"[v1][hk]overlay=0:0:shortest=0[v2];"
          f"[{ic}:v]fps={FPS},format=rgba,trim=duration={total:.4f},setpts=PTS-STARTPTS[cp];"
          f"[v2][cp]overlay=0:{cap_y}:eof_action=pass[v3];"
          f"[{ie}:v]format=rgba,trim=duration={total:.4f},fade=t=in:st={body:.3f}:d=0.25:alpha=1[en];"
          f"[v3][en]overlay=0:0:enable='gte(t,{body:.3f})',format=yuv420p[vout]")
    # pass 1: loudness of the joined audio
    meas = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *part_inputs,
                           "-filter_complex", afil + f";{alab}loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[ao]",
                           "-map", "[ao]", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(meas[meas.rfind("{"):meas.rfind("}") + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
          "linear=true,aresample=48000,alimiter=limit=0.84:level=false:attack=2:release=60")
    out = p.out / f"{s['id']}.mp4"
    tmp = p.out / f"{s['id']}.part.mp4"
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
         vf + ";" + afil + f";{alab}{ln},atrim=duration={total:.4f}[aout]",
         "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{total:.4f}",
         "-movflags", "+faststart", str(tmp)])
    tmp.replace(out)
    return out


# --------------------------------------------------------------------------------- QC

def qc(path: Path, frame: str = "band") -> dict:
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                    "stream=codec_type,width,height,r_frame_rate:format=duration",
                                    "-of", "json", str(path)], capture_output=True, text=True).stdout)
    v = next(x for x in pr["streams"] if x["codec_type"] == "video")
    top, bw, bh = BAND[frame]
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-vf", f"crop={bw}:{bh}:0:{top},blackdetect=d=0.1:pix_th=0.08,freezedetect=n=-60dB:d=2",
                          "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = log[log.rfind("Summary:"):]
    i_m = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    p_m = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)
    freezes = re.findall(r"freeze_start: ([\d.]+)", log)
    res = {"width": v["width"], "height": v["height"], "fps": round(float(Fraction(v["r_frame_rate"])), 2),
           "seconds": round(float(pr["format"]["duration"]), 2),
           "lufs": float(i_m.group(1)) if i_m else None, "true_peak": float(p_m.group(1)) if p_m else None,
           "black": [[float(a), float(b)] for a, b in blacks], "freezes": [float(x) for x in freezes]}
    res["pass"] = (res["width"] == W and res["height"] == H and abs(res["fps"] - FPS) < 0.1
                   and 15 <= res["seconds"] <= 62 and res["lufs"] is not None and abs(res["lufs"] + 14) <= 1
                   and res["true_peak"] is not None and res["true_peak"] <= -1.0
                   and not res["black"] and not res["freezes"])
    return res


def contact_sheet(s: dict, video: Path, dst: Path) -> None:
    secs = s["seconds"]
    ts = [0.4, secs * 0.2, secs * 0.4, secs * 0.6, secs * 0.8, secs - 0.5]
    tiles = []
    f = font(MONT, 26, "Bold")
    for t in ts:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=360:640", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, check=True)
        from io import BytesIO
        im = Image.open(BytesIO(r.stdout)).convert("RGB")
        ImageDraw.Draw(im).text((8, 606), f"{t:5.1f}s", font=f, fill=(255, 255, 0), stroke_width=2,
                                stroke_fill=(0, 0, 0))
        tiles.append(im)
    sheet = Image.new("RGB", (360 * 3 + 20, 640 * 2 + 10), (30, 30, 30))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % 3) * 370, (i // 3) * 650))
    sheet.save(dst, quality=88)


# --------------------------------------------------------------------------- schedule

def slot_plan(cfg: dict, taken: list[str], now: dt.datetime | None = None) -> list[tuple[dict, str]]:
    """Next free slots (2 a day, UTC) for every pick not yet uploaded, in pick order."""
    now = now or dt.datetime.now(dt.timezone.utc)
    hours = [int(x.split(":")[0]) for x in cfg["slots_utc"]]
    busy = []
    for t in taken:
        try:
            busy.append(dt.datetime.fromisoformat(t.replace("Z", "+00:00")))
        except ValueError:
            pass
    for s in cfg["shorts"]:
        if s.get("youtube", {}).get("publish_at"):
            busy.append(dt.datetime.fromisoformat(s["youtube"]["publish_at"].replace("Z", "+00:00")))
    todo = sorted([s for s in cfg["shorts"] if not s.get("youtube", {}).get("id")], key=lambda x: x["order"])
    plan = []
    day = now.date()
    earliest = now + dt.timedelta(hours=2)  # leave time for processing
    while len(plan) < len(todo):
        for h in hours:
            slot = dt.datetime(day.year, day.month, day.day, h, tzinfo=dt.timezone.utc)
            if slot < earliest:
                continue
            if any(abs((slot - b).total_seconds()) < 3600 for b in busy):
                continue
            if len(plan) < len(todo):
                plan.append((todo[len(plan)], slot.strftime("%Y-%m-%dT%H:%M:%SZ")))
                busy.append(slot)
        day += dt.timedelta(days=1)
    return plan


def nz(slot: str) -> str:
    from zoneinfo import ZoneInfo
    t = dt.datetime.fromisoformat(slot.replace("Z", "+00:00")).astimezone(ZoneInfo("Pacific/Auckland"))
    return t.strftime("%a %Y-%m-%d %H:%M NZ")


def scheduled_publish_times(offline: bool) -> list[str]:
    if offline:
        return []
    try:
        from core import youtube
        ups = youtube.list_uploads(max_items=150)
        return [u["publishAt"] for u in ups if u.get("publishAt") and u.get("privacy") == "private"]
    except Exception as e:  # dry runs still work without YouTube credentials
        print(f"(could not list scheduled uploads: {e!r}; plan ignores them)", flush=True)
        return []


def upload_all(p: Paths, cfg: dict, plan: list[tuple[dict, str]]) -> None:
    from core import youtube
    from core.config import CONFIG
    playlist = (CONFIG.reels.get("youtube", {}) or {}).get("playlists", {}).get(p.game)
    for s, slot in plan:
        video = p.out / f"{s['id']}.mp4"
        if not video.exists():
            print(f"{s['id']}: no render at {video}, skipped", flush=True)
            continue
        res = youtube.upload_video(video, s["title"], s["description"], s["tags"], privacy="private",
                                   publish_at=slot)
        vid = res.get("id")
        s["youtube"] = {"id": vid, "publish_at": slot,
                        "uploaded_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        save_picks(p, cfg)  # record each id at once so a crash never double-uploads
        if vid and playlist:
            s["youtube"]["playlist"] = bool(youtube.add_to_playlist(vid, playlist))
            save_picks(p, cfg)
        print(f"{s['id']} uploaded https://youtu.be/{vid} private, publishes {slot} ({nz(slot)})", flush=True)


def b2_all(p: Paths, cfg: dict, only: set[str]) -> None:
    """Copy each rendered Short to private B2 (shorts/analysis/<game>/<id>.mp4) and record the key,
    so the Instagram and TikTok reel tracks can post it as the "analysis" format (2026-11-14)."""
    from core import b2_store
    from tools.footage import _b2_env
    env = _b2_env("kgb2")
    for s in sorted(cfg["shorts"], key=lambda x: x["order"]):
        if only and s["id"] not in only:
            continue
        video = p.out / f"{s['id']}.mp4"
        if not video.exists():
            continue
        key = f"shorts/analysis/{p.game}/{s['id']}.mp4"
        rc = subprocess.run(["rclone", "copyto", str(video), f"kgb2:{b2_store._bucket()}/{key}"],
                            env=env).returncode
        if rc == 0:
            s["b2_key"] = key
            save_picks(p, cfg)
            print(f"{s['id']} on B2: {key}", flush=True)
        else:
            print(f"{s['id']}: B2 copy failed rc={rc}", flush=True)


def facebook_all(p: Paths, cfg: dict, only: set[str]) -> None:
    """Schedule each Short on the Boss KG Facebook page at its YouTube slot (Bryce, 2026-11-14:
    Facebook posts the analysis Shorts instead of the fill and lore reels). Post for Me with
    scheduled_at; the post id is written to the pick so a rerun never posts twice."""
    from agents import publisher
    for s in sorted(cfg["shorts"], key=lambda x: x["order"]):
        if only and s["id"] not in only:
            continue
        slot = (s.get("youtube") or {}).get("publish_at")
        if not slot or (s.get("facebook") or {}).get("id"):
            continue
        video = p.out / f"{s['id']}.mp4"
        if not video.exists():
            print(f"{s['id']}: no render at {video}, skipped", flush=True)
            continue
        caption = s["title"] + "\n\n" + s["description"]
        res = publisher.publish_video(caption, video.read_bytes(), title=s["title"], short=True,
                                      scheduled_at=slot, targets=["facebook"])
        pid = (res or {}).get("id")
        s["facebook"] = {"id": pid, "scheduled_at": slot,
                         "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        save_picks(p, cfg)
        print(f"{s['id']} Facebook post {pid} scheduled {slot} ({nz(slot)})", flush=True)


# ------------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game", nargs="?", default="wolverine")
    ap.add_argument("--version", default="v3", help="long-form render version on B2")
    ap.add_argument("--only", default="", help="comma list of pick ids")
    ap.add_argument("--resolve", action="store_true", help="word times and cut points only")
    ap.add_argument("--no-render", action="store_true", help="skip rendering (QC and sheets on existing files)")
    ap.add_argument("--dry-run", action="store_true", help="print the upload slot plan, upload nothing")
    ap.add_argument("--upload", action="store_true", help="upload rendered Shorts as private with publishAt")
    ap.add_argument("--offline", action="store_true", help="dry run without asking YouTube for taken slots")
    ap.add_argument("--start", default="", help="first allowed slot, ISO UTC (e.g. after the long-form goes public)")
    ap.add_argument("--b2", action="store_true",
                    help="copy rendered Shorts to B2 for the Instagram/TikTok analysis format")
    ap.add_argument("--facebook", action="store_true",
                    help="schedule uploaded Shorts on the Boss KG Facebook page at their YouTube slots")
    a = ap.parse_args()
    p = Paths(a.game, a.version)
    cfg = json.loads(p.picks.read_text(encoding="utf-8"))
    only = set(filter(None, a.only.split(",")))

    if (a.facebook or a.b2) and not (a.dry_run or a.upload):
        if a.b2:
            b2_all(p, cfg, only)
        if a.facebook:
            facebook_all(p, cfg, only)
        return 0
    if a.dry_run or a.upload:
        start = None
        if a.start:  # slot_plan leaves 2 h from "now", so step back 2 h to allow the given slot itself
            start = dt.datetime.fromisoformat(a.start.replace("Z", "+00:00")) - dt.timedelta(hours=2)
        plan = slot_plan(cfg, scheduled_publish_times(a.offline), now=start)
        if only:
            plan = [x for x in plan if x[0]["id"] in only]
        print(f"{'order':>5} {'id':4} {'publishAt (UTC)':21} {'NZ time':24} title")
        for s, slot in plan:
            print(f"{s['order']:>5} {s['id']:4} {slot:21} {nz(slot):24} {s['title']}")
        if a.upload:
            upload_all(p, cfg, plan)
            if a.b2:
                b2_all(p, cfg, only)
            if a.facebook:
                facebook_all(p, cfg, only)
        return 0

    fetch_sources(p)
    beats = load_beats(p)
    for bid, line in cfg.get("game_lines", {}).items():  # game lines checked against the game's subtitles
        if bid in beats and not bid.startswith("_"):
            beats[bid]["text"] = line
    resolve(p, cfg, beats, only)
    save_picks(p, cfg)
    if a.resolve:
        return 0
    rows = []
    for s in sorted(cfg["shorts"], key=lambda x: x["order"]):
        if only and s["id"] not in only:
            continue
        t0 = time.time()
        if not a.no_render:
            render_short(s, p, p.video)
        video = p.out / f"{s['id']}.mp4"
        r = qc(video, s.get("frame", "band"))
        contact_sheet(s, video, p.sheets / f"{s['id']}.jpg")
        rows.append((s, r))
        print(f"{s['id']} rendered and checked in {time.time() - t0:.0f}s", flush=True)
    print(f"\n{'id':4} {'size':10} {'fps':>5} {'secs':>6} {'LUFS':>6} {'TP':>5} {'black':>5} {'freeze':>6}  pass")
    for s, r in rows:
        print(f"{s['id']:4} {r['width']}x{r['height']} {r['fps']:5.1f} {r['seconds']:6.2f} {r['lufs']:6.1f} "
              f"{r['true_peak']:5.1f} {len(r['black']):5d} {len(r['freezes']):6d}  {'PASS' if r['pass'] else 'FAIL'}")
    (p.out / "qc.json").write_text(json.dumps({s["id"]: r for s, r in rows}, indent=1), encoding="utf-8")
    return 0 if all(r["pass"] for _, r in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
