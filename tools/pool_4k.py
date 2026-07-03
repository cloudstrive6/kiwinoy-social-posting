"""Extract 4K/60 HDR reel clips from long-form source parts into the YouTube Shorts
footage pool (reels/assets/footage-4k/<game>/), keeping HDR10 (Rec.2020 PQ) intact.

This is the HDR sibling of tools/hdr_to_reel.py: that tool TONE-MAPS 4K HDR down to
1080p SDR for the Post-for-Me feed reels; THIS one keeps the clip at native 4K HDR so
the dedicated YouTube Shorts track (run.py --youtube-short) can render it as a real
HDR10 Short (classic <-> triptych), matching the long-form's export.

Stream-copy by default (near-instant, lossless, HDR preserved) — cuts snap to the
nearest keyframe, which is fine for a b-roll reel clip. Use --reencode for a
frame-accurate cut (nvenc HEVC Main10, keeps HDR). Runs on YOUR machine (the source
parts are 10-40 GB 4K HDR; not in CI).

Usage:
  python tools/pool_4k.py <src-part> <game> --at 00:12:30 --len 40
  python tools/pool_4k.py <src-part> <game> --at 00:12:30 --to 00:13:10 --name sephiroth-reveal
  python tools/pool_4k.py <src-part> <game> --at 725 --len 35 --reencode
  python tools/pool_4k.py --list <game>            # show the current pool + used ledger

<game> = the footage subfolder key (ff7remake, thelastofus2, ...). The clip lands in
reels/assets/footage-4k/<game>/ and the Shorts track picks it up fresh-first.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ffmpeg  # noqa: E402
from core.config import CONFIG, ROOT  # noqa: E402


def _pool_dir(game: str) -> Path:
    base = (CONFIG.youtube_shorts or {}).get("footage_dir", "reels/assets/footage-4k")
    return ROOT / str(base) / game


def _is_hdr(path: Path) -> bool:
    fp = ffmpeg.ffprobe_bin()
    if not fp:
        return False
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=color_transfer", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return "smpte2084" in (out.stdout or "").lower() or "arib-std-b67" in (out.stdout or "").lower()
    except Exception:
        return False


def _secs(t: str) -> float:
    """Accept SS, MM:SS, HH:MM:SS(.ms)."""
    parts = str(t).split(":")
    try:
        return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
    except Exception:
        sys.exit(f"bad timestamp: {t}")


def _slug(s: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "clip")[:48]


def _list(game: str) -> int:
    d = _pool_dir(game)
    print(f"Pool: {d}")
    if not d.exists():
        print("  (empty — none extracted yet)")
        return 0
    clips = sorted(p for p in d.iterdir()
                   if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".m4v"})
    led = {}
    try:
        led = json.loads((d / ".used_shorts.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    used = set(led.get("used", []))
    for c in clips:
        gb = c.stat().st_size / 1024 ** 2
        print(f"  {'[used]' if c.name in used else '[fresh]':7} {c.name}  ({gb:.0f} MB)")
    print(f"{len(clips)} clip(s); {len(used)} used; {led.get('posts', 0)} Shorts posted.")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        if len(argv) < 2:
            sys.exit("usage: python tools/pool_4k.py --list <game>")
        return _list(argv[1])

    if len(argv) < 2:
        sys.exit("usage: python tools/pool_4k.py <src-part> <game> --at <t> (--len N | --to <t>)")
    src = Path(argv[0])
    game = argv[1]
    opt = argv[2:]
    if not src.exists():
        sys.exit(f"source not found: {src}")

    def _val(flag, default=None):
        return opt[opt.index(flag) + 1] if flag in opt and opt.index(flag) + 1 < len(opt) else default

    at = _val("--at")
    if at is None:
        sys.exit("--at <timestamp> is required (SS, MM:SS, or HH:MM:SS)")
    start = _secs(at)
    if "--to" in opt:
        dur = max(0.0, _secs(_val("--to")) - start)
    else:
        dur = float(_val("--len", 40) or 40)
    if dur <= 0:
        sys.exit("clip length resolved to <= 0 — check --at/--to/--len")
    reencode = "--reencode" in opt
    name = _val("--name") or _slug(f"{src.stem}-{at.replace(':', '')}")

    out_dir = _pool_dir(game)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{_slug(name)}.mp4"
    n = 1
    while out.exists():
        out = out_dir / f"{_slug(name)}-{n}.mp4"
        n += 1

    hdr = _is_hdr(src)
    if not hdr:
        print(f"WARNING: {src.name} is not tagged HDR (smpte2084/HLG). The Shorts track "
              f"expects 4K HDR source; continuing, but the output won't be true HDR.")
    if reencode:
        # Frame-accurate cut, keep HDR10 (nvenc Main10 + PQ/bt2020 tags).
        args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
                "-c:v", "hevc_nvenc", "-profile:v", "main10", "-pix_fmt", "p010le",
                "-rc", "vbr", "-b:v", "55M", "-maxrate", "75M", "-tag:v", "hvc1",
                "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc", "-color_range", "tv",
                "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
                "-movflags", "+faststart", str(out)]
        mode = "re-encode (nvenc Main10, frame-accurate)"
    else:
        # Stream-copy: fast, lossless, HDR untouched. -ss before -i = fast keyframe seek.
        args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
                "-c", "copy", "-map", "0", "-movflags", "+faststart", str(out)]
        mode = "stream-copy (keyframe cut, lossless)"
    print(f"Extracting {dur:.0f}s @ {at} from {src.name}  [{mode}]", flush=True)
    rc, err = ffmpeg.run(args, timeout=1800)
    if rc != 0 or not out.exists():
        sys.exit(f"extract failed: {err[-500:]}")
    mb = out.stat().st_size / 1024 ** 2
    print(f"  -> {out.relative_to(ROOT)}  ({mb:.0f} MB)", flush=True)
    print(f"Pool now has {len(list(out_dir.glob('*.mp4')))} clip(s). "
          f"Render + upload a Short with:  python run.py --youtube-short", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
