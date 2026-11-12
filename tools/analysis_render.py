"""Render a KG analysis long-form from its edit list (2026-11-12, manual runs first).

Inputs: data/analysis/<game>/edl.json (beats from the approved script), gfx.json (graphics),
clips.json (clip index to B2 key) and the narration from tools/analysis_narrate.py. Footage
streams from B2 over short-lived presigned URLs (rule: any footage of the same game; automated
runs use B2 only). Plain code, no AI.

Each beat renders to its own segment (1920x1080, 60 fps, PCM audio):
  narr: the cue's shots are fitted to the paragraph (jump cuts inside long ranges, gentle slow
        motion up to 1.5x when a range is short), game audio ducked to -24 dB under the voice,
        graphics faded on top.
  game: the clip's own audio at full level (normalised), narration paused, 15 s or less.
Then: concat, two-pass loudnorm to -14 LUFS / -1.5 dBTP, chapters from the real cut, QC
(resolution, fps, loudness, black frames, freezes over 2 s), three thumbnails, and an upload
of the render to B2 renders/analysis/<game>/ (kept for good) with a 7-day review link. Never posts to any platform.

    python tools/analysis_render.py wolverine [--only b000,b001] [--no-upload]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from fractions import Fraction
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import analysis_brand as brand_lt  # noqa: E402
import analysis_gfx as gfx  # noqa: E402
from core import b2_store  # noqa: E402

FPS = 60
MAX_SHOT = 7.0     # longest single shot before a jump cut inside the range
MAX_SLOW = 1.5     # most slow motion used to stretch a short range
LEAD, TAIL = 0.15, 0.35  # breath before and after each narration paragraph
FADE = 0.25


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


class Clips:
    def __init__(self, game: str):
        self.map = json.loads((ROOT / "data/analysis" / game / "clips.json").read_text(encoding="utf-8"))["clips"]
        self._urls: dict[int, tuple[str, float]] = {}

    def url(self, idx: int) -> str:
        u, t = self._urls.get(idx, ("", 0.0))
        if not u or time.time() - t > 2400:
            u = b2_store.presigned_url(self.map[str(idx)]["key"], valid_seconds=3600) or ""
            if not u:
                raise RuntimeError(f"no presigned URL for clip {idx}")
            self._urls[idx] = (u, time.time())
        return u

    def fetch(self, idx: int, src: float, span: float, work: Path) -> Path:
        """Copy one source range to a local file first (fix 2026-11-12): with many B2 inputs
        open in one ffmpeg graph, a later shot's HTTP connection idled while earlier shots
        encoded, B2 closed it, and the shot ran out of frames after about 2 s (stuck frames in
        the first test render). One input at a time, with reconnects, then a length check."""
        out = work / "pieces" / f"{idx:03d}_{src:.3f}_{span:.3f}.mkv"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            return out
        want = span + 0.3
        for attempt in range(3):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-reconnect", "1", "-reconnect_at_eof", "1",
                            "-reconnect_streamed", "1", "-reconnect_on_network_error", "1",
                            "-reconnect_delay_max", "10", "-ss", f"{src:.3f}", "-i", self.url(idx),
                            "-t", f"{want:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
                            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)], check=False)
            got = probe_seconds(out, "v") if out.exists() else 0.0
            if got >= want - 0.25:
                return out
            print(f"clip {idx}@{src:.1f}: fetched {got:.2f}s of {want:.2f}s, retry {attempt + 1}", flush=True)
            self._urls.pop(idx, None)
        raise RuntimeError(f"could not fetch clip {idx} at {src:.1f}s for {want:.1f}s")

    def fetch_clean(self, idx: int, src: float, span: float, work: Path) -> Path:
        """fetch(), then make sure the range has no black or frozen stretch (clip ends often
        hold a still or fade to black: clips 33 and 37 in the first full render). If it does,
        slide the window clear of it and fetch again."""
        clip_len = self.length(idx)
        for attempt in range(4):
            path = self.fetch(idx, src, span, work)
            bad = bad_interval(path)
            if not bad:
                return path
            b0, b1 = bad
            new_src = src - (span - b0) - 0.3 if b0 > 0.6 else src + b1 + 0.3
            new_src = min(max(0.0, new_src), max(0.0, clip_len - span - 1.0))
            print(f"clip {idx}@{src:.1f}+{span:.1f}: black or frozen {b0:.1f}-{b1:.1f}s, "
                  f"moving to {new_src:.1f}", flush=True)
            if abs(new_src - src) < 0.05:
                return path
            src = new_src
        return path

    def length(self, idx: int) -> float:
        return float(self.map[str(idx)]["seconds"])

    def grab(self, idx: int, sec: float) -> Image.Image:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{sec:.2f}", "-i", self.url(idx),
                              "-frames:v", "1", "-f", "image2", "-c:v", "png", "-"],
                             capture_output=True, check=True).stdout
        return Image.open(BytesIO(raw)).convert("RGB")


def probe_seconds(path: Path, stream: str = "v") -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"{stream}:0", "-count_packets",
                          "-show_entries", "stream=nb_read_packets,r_frame_rate", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    try:
        st = json.loads(out)["streams"][0]
        return int(st["nb_read_packets"]) / float(Fraction(st["r_frame_rate"]))
    except Exception:
        return 0.0


def bad_interval(path: Path) -> tuple[float, float] | None:
    """First black (0.3 s+) or frozen (1.5 s+) stretch in a local piece, or None."""
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
                          "blackdetect=d=0.3:pix_th=0.08,freezedetect=n=-70dB:d=1.5", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    hits = []
    for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log):
        hits.append((float(a), float(b)))
    fs = re.findall(r"freeze_start: ([\d.]+)", log)
    fe = re.findall(r"freeze_end: ([\d.]+)", log)
    for i, a in enumerate(fs):
        hits.append((float(a), float(fe[i]) if i < len(fe) else probe_seconds(path)))
    return min(hits) if hits else None


def plan_shots(shots: list[dict], dur: float, clips: Clips) -> list[dict]:
    """Fit the cue's shots to `dur` seconds. Returns pieces: {clip, src, span, out, flags} where
    span is source seconds and out is screen seconds (out/span is the slow-motion factor)."""
    lens = [max((x["out"] - x["in"]) for x in s["split"]) if "split" in s else s["out"] - s["in"]
            for s in shots]
    total = sum(lens)
    pieces = []
    for s, L in zip(shots, lens):
        a = dur * L / total
        if "split" in s:
            pieces.append({"split": s["split"], "out": a})
            continue
        clip_len = clips.length(s["clip"])
        if L >= a:  # enough source: jump cuts spread across the range
            n = max(1, math.ceil(a / MAX_SHOT))
            piece = a / n
            free = L - a
            for i in range(n):
                start = s["in"] + i * piece + (free * i / (n - 1) if n > 1 else 0)
                pieces.append({**s, "src": start, "span": piece, "out": piece})
        else:  # short range: slow it down a little, then run on past the cue if still short
            f = min(a / L, MAX_SLOW)
            span = a / f
            start = s["in"]
            if start + span > clip_len - 1.0:
                start = max(0.0, clip_len - 1.0 - span)
            pieces.append({**s, "src": start, "span": span, "out": a})
    return pieces


def vchain(label_in: str, p: dict, out_label: str) -> str:
    f = []
    crop = p.get("crop")
    if crop == "sub":
        f.append("crop=iw*0.78:ih*0.78:(iw-ow)/2:ih*0.012")  # game subtitles sit at 82-84% height
    elif crop == "hud":
        f.append("crop=iw*0.70:ih*0.70:(iw-ow)/2:ih*0.10")  # boss bars (to ~10%) plus subtitles (82%+)
    f.append("scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1")
    if p.get("blur"):
        f.append("gblur=sigma=14")
    if p.get("gray"):
        f.append("hue=s=0")
    slow = p["out"] / p["span"]
    f.append(f"setpts=(PTS-STARTPTS)*{slow:.5f}")
    f.append(f"fps={FPS}")
    f.append(f"trim=duration={p['out']:.4f},setpts=PTS-STARTPTS")
    if p.get("push"):
        frames = max(1, int(p["out"] * FPS))
        f.append("scale=3840:2160")
        f.append(f"zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                 f":d=1:s=1920x1080:fps={FPS}")
    f.append("setsar=1,format=yuv420p")
    return f"[{label_in}]{','.join(f)}[{out_label}]"


def achain(label_in: str, p: dict, out_label: str, gain_db: float) -> str:
    slow = p["out"] / p["span"]
    f = ["asetpts=PTS-STARTPTS", "aformat=sample_rates=48000:channel_layouts=stereo"]
    if abs(slow - 1) > 0.01:
        f.append(f"atempo={1 / slow:.5f}")
    f += [f"volume={gain_db}dB", f"apad,atrim=duration={p['out']:.4f}"]
    return f"[{label_in}]{','.join(f)}[{out_label}]"


def render_beat(b: dict, dur: float, clips: Clips, gfx_specs: dict, work: Path, under_db: float,
                narr_wav: Path | None, seg: Path, brand: tuple | None = None) -> None:
    inputs: list[str] = []
    graph: list[str] = []
    vlabels, alabels = [], []

    def add_input(args: list[str]) -> int:
        inputs.extend(args)
        return sum(1 for x in inputs if x == "-i") - 1

    if b["type"] == "game":
        p = {**b, "src": b["in"], "span": b["out"] - b["in"], "out": b["out"] - b["in"]}
        pieces = [p]
    else:
        pieces = plan_shots(b["shots"], dur, clips)
        for p in pieces:  # game subtitles under the voice show lines nobody hears
            if "split" not in p and not p.get("crop"):
                p["crop"] = "sub"
    for k, p in enumerate(pieces):
        if "split" in p:
            l, r = p["split"]
            il = add_input(["-i", str(clips.fetch_clean(l["clip"], l["in"], p["out"] + 0.2, work))])
            ir = add_input(["-i", str(clips.fetch_clean(r["clip"], r["in"], p["out"] + 0.2, work))])
            graph.append(f"color=c=0x0c0c10:s=1920x1080:r={FPS}:d={p['out']:.4f}[bg{k}]")
            for side, ii in (("l", il), ("r", ir)):
                graph.append(f"[{ii}:v]crop=iw*0.78:ih*0.78:(iw-ow)/2:ih*0.012,scale=944:531,setsar=1,setpts=PTS-STARTPTS,fps={FPS},"
                             f"trim=duration={p['out']:.4f},setpts=PTS-STARTPTS[s{side}{k}]")
            graph.append(f"[bg{k}][sl{k}]overlay=12:300[t{k}];[t{k}][sr{k}]overlay=964:300,"
                         f"format=yuv420p[v{k}]")
            graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={p['out']:.4f}[a{k}]")
        else:
            i = add_input(["-i", str(clips.fetch_clean(p["clip"], p["src"], p["span"], work))])
            graph.append(vchain(f"{i}:v", p, f"v{k}"))
            if b["type"] == "game":
                graph.append(f"[{i}:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                             f"atrim=duration={p['out']:.4f},loudnorm=I=-18:TP=-2:LRA=11,"
                             f"aformat=sample_rates=48000:channel_layouts=stereo,"
                             f"afade=t=in:d=0.08,afade=t=out:st={max(0, p['out'] - 0.12):.3f}:d=0.12,"
                             f"apad,atrim=duration={p['out']:.4f}[a{k}]")
            else:
                graph.append(achain(f"{i}:a", p, f"a{k}", under_db))
        vlabels.append(f"[v{k}]")
        alabels.append(f"[a{k}]")
    n = len(pieces)
    graph.append(f"{''.join(v + a for v, a in zip(vlabels, alabels))}concat=n={n}:v=1:a=1[vb][ab]")
    # Graphics layers.
    cur = "vb"
    li = 0
    for gid in b.get("gfx", []):
        for si, spec in enumerate(gfx_specs.get(gid, [])):
            for png, s, e, fi, fo in gfx.layers(spec, dur, work, f"{b['id']}_{gid}_{si}", clips.grab):
                if e - s < 0.05:
                    continue
                ii = add_input(["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(png)])
                fl = ["format=rgba"]
                if fi:
                    fl.append(f"fade=t=in:st={s:.3f}:d={FADE}:alpha=1")
                if fo:
                    fl.append(f"fade=t=out:st={max(s, e - FADE):.3f}:d={FADE}:alpha=1")
                graph.append(f"[{ii}:v]{','.join(fl)}[g{li}]")
                graph.append(f"[{cur}][g{li}]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'[o{li}]")
                cur = f"o{li}"
                li += 1
    if brand:  # the Subscribe To Boss KG lower third (analysis_brand.py), offset from this beat's start
        mov, off, secs = brand
        bi = add_input(["-i", str(mov)])
        sh = f"trim=start={-off:.4f},setpts=PTS-STARTPTS" if off < 0 else f"setpts=PTS-STARTPTS+{off:.4f}/TB"
        graph.append(f"[{bi}:v]format=rgba,{sh}[brd]")
        graph.append(f"[{cur}][brd]overlay=0:0:eof_action=pass:enable='between(t,{max(0.0, off):.3f},{off + secs:.3f})'[obr]")
        cur = "obr"
    graph.append(f"[{cur}]format=yuv420p[vout]")
    if narr_wav is not None:
        ni = add_input(["-i", str(narr_wav)])
        graph.append(f"[{ni}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"adelay={int(LEAD * 1000)}:all=1,apad,atrim=duration={dur:.4f}[nv]")
        graph.append("[ab][nv]amix=inputs=2:normalize=0:duration=first[aout]")
    else:
        graph.append("[ab]anull[aout]")
    script = work / f"{b['id']}.filter"
    script.write_text(";\n".join(graph), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", str(script),
         "-map", "[vout]", "-map", "[aout]", "-t", f"{dur:.4f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "faster", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "120",
         "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(seg)])


SR = 48000


def _decode(path) -> "np.ndarray":
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-af", "loudnorm=I=-16:TP=-2:LRA=11",
                          "-ar", str(SR), "-ac", "2", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def _looped(track: "np.ndarray", offset: float, n: int, xf: int) -> "np.ndarray":
    """n samples of the track from `offset`; when it runs out it restarts just after the intro,
    crossfaded over xf samples."""
    out = track[int(offset * SR) % max(1, len(track) - xf):].copy()
    loop = track[2 * SR:] if len(track) > 4 * SR + xf else track
    while len(out) < n:
        k = min(xf, len(out), len(loop))
        ramp = np.linspace(0, 1, k, dtype=np.float32)[:, None]
        head = loop[:k] * ramp
        out[-k:] = out[-k:] * (1 - ramp) + head
        out = np.concatenate([out, loop[k:]])
    return out[:n].copy()


def build_music(game: str, timeline: list[dict], total: float, work: Path) -> Path | None:
    """The orchestral bed (data/analysis/<game>/music.json): sections that start at beats,
    crossfaded, levelled under the voice and ducked further under game-audio bursts."""
    cfg_path = ROOT / "data/analysis" / game / "music.json"
    if not cfg_path.exists():
        return None
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    starts = {b["id"]: b["start"] for b in timeline}
    n = int(total * SR) + 1
    bed = np.zeros((n, 2), dtype=np.float32)
    xf = int(float(cfg.get("xfade", 2.5)) * SR)
    cache: dict[str, np.ndarray] = {}
    secs = cfg["sections"]
    base = float(cfg.get("under_narration_db", -19))
    for i, sec in enumerate(secs):
        s0 = int(starts[sec["from"]] * SR)
        s1 = int(starts[secs[i + 1]["from"]] * SR) if i + 1 < len(secs) else n
        if not sec.get("track"):
            continue
        if sec["track"] not in cache:
            ref = cfg["tracks"][sec["track"]]
            local = ROOT / ref
            # Tracks live on private B2 (music/analysis/), never in this public repo.
            src = local if local.exists() else b2_store.presigned_url(ref, valid_seconds=3600)
            cache[sec["track"]] = _decode(src)
        tr = cache[sec["track"]]
        a = max(0, s0 - xf // 2)
        b = min(n, s1 + xf // 2)
        seg = _looped(tr, float(sec.get("offset", 0)), b - a, xf)
        fin = xf if s0 > 0 else int(0.6 * SR)
        fout = xf if s1 < n else int(4 * SR)
        seg[:fin] *= np.linspace(0, 1, fin, dtype=np.float32)[:, None]
        seg[-fout:] *= np.linspace(1, 0, fout, dtype=np.float32)[:, None]
        seg *= 10 ** (float(sec.get("gain_db", base)) / 20)
        bed[a:b] += seg
    # Duck under game-audio bursts (the game's own dialogue), relative to the section level.
    env = np.ones(n, dtype=np.float32)
    duck = 10 ** ((float(cfg.get("under_game_db", -30)) - base) / 20)
    ramp = int(0.3 * SR)
    for bt in timeline:
        if bt["type"] != "game":
            continue
        g0, g1 = int(bt["start"] * SR), int((bt["start"] + bt["seconds"]) * SR)
        env[g0:g1] = np.minimum(env[g0:g1], duck)
        lo = max(0, g0 - ramp)
        env[lo:g0] = np.minimum(env[lo:g0], np.linspace(1, duck, g0 - lo, dtype=np.float32))
        hi = min(n, g1 + ramp)
        env[g1:hi] = np.minimum(env[g1:hi], np.linspace(duck, 1, hi - g1, dtype=np.float32))
    bed *= env[:, None]
    out = work / "music_bed.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_f32le", str(out)], input=bed.tobytes(), check=True)
    (work.parent / "music-credits.txt").write_text("Music:" + chr(10) + chr(10).join(cfg.get("credits", [])) + chr(10),
                                                  encoding="utf-8")
    return out


def mix_music(video: Path, bed: Path | None, out: Path, start: float = 0.0, pieces=None) -> Path:
    """Audio of `video` plus the bed (whole timeline, or the given [start, seconds] pieces)."""
    if bed is None:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-c:a", "pcm_f32le", str(out)])
        return out
    if pieces:
        parts = "".join(f"[1:a]atrim=start={s:.3f}:duration={d:.3f},asetpts=PTS-STARTPTS[m{i}];"
                        for i, (s, d) in enumerate(pieces))
        cat = "".join(f"[m{i}]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=0:a=1[bed];"
        graph = parts + cat + "[0:a][bed]amix=inputs=2:normalize=0:duration=first[a]"
    else:
        graph = "[0:a][1:a]amix=inputs=2:normalize=0:duration=first[a]"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(bed), "-filter_complex", graph,
         "-map", "[a]", "-c:a", "pcm_f32le", str(out)])
    return out


RENDER_VER = "2026-11-13a"  # bump when a change to this file should re-render every beat
GFX_SRC = hashlib.sha1((ROOT / "tools/analysis_gfx.py").read_bytes()).hexdigest()[:10]
BRAND_SRC = hashlib.sha1((ROOT / "tools/analysis_brand.py").read_bytes() + (ROOT / "assets/brand/kg-avatar.png").read_bytes()
                         + GFX_SRC.encode()).hexdigest()[:10]


def brand_config(gfx_specs: dict) -> dict | None:
    """Subscribe lower third settings: defaults, then data/analysis/brand.json, then the game's
    gfx.json "brand" key (false turns it off for that video)."""
    over = gfx_specs.get("brand", {})
    if over is False:
        return None
    cfg = dict(brand_lt.DEFAULTS)
    shared = ROOT / "data/analysis/brand.json"
    if shared.exists():
        cfg.update(json.loads(shared.read_text(encoding="utf-8")).get("subscribe", {}))
    if isinstance(over, dict):
        cfg.update(over)
    return cfg


def brand_side(beats_t: list[tuple[dict, float, float]], gfx_specs: dict, cfg: dict) -> str:
    """Keep the lower third clear of a title lower third: switch sides if one is on screen."""
    a, z = float(cfg["at"]), float(cfg["at"]) + brand_lt.total_seconds(cfg)
    for b, start, dur in beats_t:
        if start >= z or start + dur <= a:
            continue
        for gid in b.get("gfx", []):
            for spec in gfx_specs.get(gid, []):
                if spec.get("kind") != "lower":
                    continue
                s0 = start + max(0.0, gfx._t(spec, "at", "at_frac", dur, 0.0))
                s1 = start + (min(dur, s0 - start + float(spec["dur"])) if spec.get("dur") else dur)
                if s0 < z and s1 > a:
                    return "right" if cfg.get("side", "left") == "left" else "left"
    return cfg.get("side", "left")


def beat_signature(b: dict, gfx_specs: dict, timings: dict, dur: float, brand: tuple | None = None,
                   brand_cfg: dict | None = None) -> str:
    parts = [RENDER_VER, json.dumps(b, sort_keys=True), f"{dur:.3f}",
             json.dumps(timings.get(b["id"], {}), sort_keys=True)]
    if brand:  # only the beats the lower third crosses change when it does
        parts += [BRAND_SRC, f"{brand[1]:.3f}", json.dumps(brand_cfg, sort_keys=True)]
    if b.get("gfx"):
        parts += [GFX_SRC, json.dumps([gfx_specs.get(g) for g in b["gfx"]], sort_keys=True)]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def fmt_ts(t: float) -> str:
    t = int(t)
    return f"{t // 60}:{t % 60:02d}" if t < 3600 else f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def qc(path: Path) -> dict:
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                    "stream=codec_type,width,height,r_frame_rate:format=duration",
                                    "-of", "json", str(path)], capture_output=True, text=True).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                          "-vf", "blackdetect=d=0.1:pix_th=0.08,freezedetect=n=-60dB:d=2",
                          "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = log[log.rfind("Summary:"):]
    i_m = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    p_m = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)
    freezes = re.findall(r"freeze_start: ([\d.]+)", log)
    fps = float(Fraction(v["r_frame_rate"]))  # e.g. "60/1"
    res = {"width": v["width"], "height": v["height"], "fps": round(fps, 2),
           "seconds": round(float(pr["format"]["duration"]), 2),
           "lufs": float(i_m.group(1)) if i_m else None,
           "true_peak": float(p_m.group(1)) if p_m else None,
           "black": [[float(a), float(b)] for a, b in blacks], "freezes": [float(x) for x in freezes]}
    res["pass"] = (res["width"] == 1920 and res["height"] == 1080 and abs(res["fps"] - 60) < 0.1
                   and res["lufs"] is not None and abs(res["lufs"] + 14) <= 1
                   and res["true_peak"] is not None and res["true_peak"] <= -1.0
                   and not res["black"] and not res["freezes"])
    return res


def b2_env() -> dict:
    env = dict(os.environ)
    env["RCLONE_CONFIG_KGB2_TYPE"] = "b2"
    env["RCLONE_CONFIG_KGB2_ACCOUNT"] = os.environ.get("B2_KEY_ID", "")
    env["RCLONE_CONFIG_KGB2_KEY"] = os.environ.get("B2_APP_KEY", "")
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game", nargs="?", default="wolverine")
    ap.add_argument("--only", default="", help="comma list of beat ids (test renders)")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--version", default="v1")
    a = ap.parse_args()
    game = a.game
    d = ROOT / "data/analysis" / game
    edl = json.loads((d / "edl.json").read_text(encoding="utf-8"))
    gfx_specs = json.loads((d / "gfx.json").read_text(encoding="utf-8"))
    tails = gfx_specs.get("beat_tail", {})
    out = ROOT / "output/analysis" / game
    narr_dir = out / "narration"
    timings = json.loads((narr_dir / "timings.json").read_text(encoding="utf-8"))
    work = out / "work"
    segs = out / "segs"
    work.mkdir(parents=True, exist_ok=True)
    segs.mkdir(parents=True, exist_ok=True)
    clips = Clips(game)
    only = set(filter(None, a.only.split(",")))

    beats = edl["beats"]
    edits_path = d / "edits.json"  # post-review edit changes that are not in the script cues
    if edits_path.exists():
        over = json.loads(edits_path.read_text(encoding="utf-8")).get("shots", {})
        for b in beats:
            if b["id"] in over:
                b["shots"] = over[b["id"]]
    def beat_dur(b: dict) -> float:
        if b["type"] == "narr":
            return LEAD + timings[b["id"]]["seconds"] + TAIL + float(tails.get(b["id"], 0))
        return b["out"] - b["in"]

    beats_t, acc = [], 0.0
    for b in beats:
        beats_t.append((b, acc, beat_dur(b)))
        acc += beats_t[-1][2]
    bcfg = brand_config(gfx_specs)
    bmov, bsecs = None, 0.0
    if bcfg:
        bcfg["side"] = brand_side(beats_t, gfx_specs, bcfg)
        bmov = work / f"brand-{hashlib.sha1((BRAND_SRC + json.dumps(bcfg, sort_keys=True)).encode()).hexdigest()[:10]}.mov"
        bsecs = brand_lt.total_seconds(bcfg)
        if not bmov.exists():
            brand_lt.render_mov(bmov, bcfg)
        print(f"subscribe lower third at {bcfg['at']:.1f}s for {bsecs:.2f}s on the {bcfg['side']}", flush=True)
    t = 0.0
    chapters, timeline = [], []
    t0 = time.time()
    for b in beats:
        dur = beat_dur(b)
        bt = None
        if bmov and t < float(bcfg["at"]) + bsecs and t + dur > float(bcfg["at"]):
            bt = (bmov, float(bcfg["at"]) - t, bsecs)
        if b.get("chapter"):
            chapters.append((t, b["chapter"]))
        timeline.append({"id": b["id"], "type": b["type"], "start": round(t, 2), "seconds": round(dur, 2)})
        t += dur
        if only and b["id"] not in only:
            continue
        seg = segs / f"{b['id']}.mkv"
        sig = beat_signature(b, gfx_specs, timings, dur, bt, bcfg if bt else None)
        sigf = segs / f"{b['id']}.sig"
        if seg.exists() and sigf.exists() and sigf.read_text() == sig:
            continue  # unchanged since a cached render (segments are cached between runs)
        wav = narr_dir / f"{b['id']}.wav" if b["type"] == "narr" else None
        render_beat(b, dur, clips, gfx_specs, work, float(edl.get("under_narration_db", -24)), wav, seg, bt)
        sigf.write_text(sig)
        for f in (work / "pieces").glob("*.mkv"):
            f.unlink()
        print(f"{b['id']} {b['type']} {dur:.1f}s done ({time.time() - t0:.0f}s elapsed)", flush=True)
    (out / "timeline.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
    chap_txt = "\n".join(f"{fmt_ts(s)} {title}" for s, title in chapters)
    (out / "chapters.txt").write_text(chap_txt + "\n", encoding="utf-8")
    print(f"planned runtime {fmt_ts(t)} ({t:.1f} s)\n{chap_txt}", flush=True)
    if only:  # test render: one small preview of just those beats, in edit order
        lst = work / "preview.txt"
        lst.write_text("".join(f"file '{(segs / (b['id'] + '.mkv')).as_posix()}'\n" for b in beats
                               if b["id"] in only), encoding="utf-8")
        joined = work / "preview.mkv"
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
        bed = build_music(game, timeline, t, work)
        pieces = [(x["start"], x["seconds"]) for x in timeline if x["id"] in only]
        mixed = mix_music(joined, bed, work / "preview_mix.wav", pieces=pieces)
        run(["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-i", str(mixed), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out / "preview.mp4")])
        return 0

    # Concat, then two-pass loudness to -14 LUFS.
    lst = work / "segs.txt"
    lst.write_text("".join(f"file '{(segs / (b['id'] + '.mkv')).as_posix()}'\n" for b in beats), encoding="utf-8")
    joined = work / "joined.mkv"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    bed = build_music(game, timeline, t, work)
    mixed = mix_music(joined, bed, work / "mixed.wav")
    meas = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mixed), "-vn", "-af",
                           "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    m = json.loads(meas[meas.rfind("{"):meas.rfind("}") + 1])
    final = out / f"{game}-analysis-{a.version}.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-i", str(mixed), "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-af",
         f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
         f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
         "linear=true,aresample=48000", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(final)])
    joined.unlink(missing_ok=True)
    mixed.unlink(missing_ok=True)
    report = qc(final)
    report["chapters"] = chap_txt
    (out / "qc.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1), flush=True)

    # Thumbnails: script packaging, frames picked by eye after review v1 (3 words or fewer).
    thumbs = [(33, 60.0, "HE FORGOT HER", None, 1.0, 1.08),
              (32, 44.0, "HE CHOSE THIS", "sub", 0.82, 1.25),
              (33, 14.0, "NOTHING LEFT", None, 1.0, 1.08)]
    for i, (c, sec, words, crop, br, ct) in enumerate(thumbs, 1):
        im = clips.grab(c, sec)
        if crop == "sub":
            w, h = im.size
            im = im.crop((int(w * 0.11), int(h * 0.01), int(w * 0.89), int(h * 0.79)))
        # orange accent vanishes on the orange Phoenix frame, so thumb 2 is all white
        gfx.thumbnail(im, words, out / f"thumb-{i}.jpg", br, ct, gfx.WHITE if c == 32 else gfx.ORANGE)

    if a.no_upload:
        return 0 if report["pass"] else 2
    # Every render is kept on B2 under renders/analysis/<game>/ (Bryce, 2026-11-13: "save our renders
    # for these kinds of long form videos in a folder in B2"), with its thumbnails, chapters and QC.
    folder = f"renders/analysis/{game}"
    key = f"{folder}/{final.name}"
    rc = subprocess.run(["rclone", "copyto", str(final), f"kgb2:{b2_store._bucket()}/{key}",
                         "--b2-chunk-size", "100M"], env=b2_env()).returncode
    for extra in [*sorted(out.glob("thumb-*.jpg")), out / "chapters.txt", out / "music-credits.txt",
                  out / "qc.json", out / "timeline.json"]:
        if extra.exists():
            subprocess.run(["rclone", "copyto", str(extra),
                            f"kgb2:{b2_store._bucket()}/{folder}/{a.version}/{extra.name}"], env=b2_env())
    if rc == 0:
        link = b2_store.presigned_url(key, valid_seconds=7 * 24 * 3600) or ""
        (out / "review-link.txt").write_text(f"{key}\n{link}\n", encoding="utf-8")
        print(f"uploaded render to B2 {key} (review link in the artifact)", flush=True)
    else:
        print(f"B2 upload failed rc={rc}", flush=True)
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
