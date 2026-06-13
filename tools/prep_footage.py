"""Prep raw gameplay recordings into small, reel-ready clips.

For each video (or every video in a dragged folder) this compresses to 1080p and
splits it into ~SEG-second clips written to a "_ready" subfolder. Those small
clips are what get uploaded to the footage Release.

Run via tools/win/prep_footage.bat (drag a game folder onto it), or directly:
    python tools/prep_footage.py "<folder-or-file>" ["<more>" ...] [--dry]

Python (not batch) does the path handling so spaces / parentheses / unicode in
filenames like "Spider-Man 1 (2026-06-14 00-44-51).mp4" never break it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".webm"}
SEG = 25       # seconds per output clip
MAXH = 1080    # max height
QUALITY = 26   # NVENC cq / x264 crf (higher = smaller)


def find_ffmpeg() -> str | None:
    f = shutil.which("ffmpeg")
    if f:
        return f
    for c in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
    ):
        if c.exists():
            return str(c)
    return None


def _sanitize(stem: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "clip"


def _seg_args(ff: str, src: Path, out_tmpl: str, gpu: bool) -> list[str]:
    vcodec = (["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq",
               str(QUALITY), "-b:v", "0"] if gpu else
              ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
               "-pix_fmt", "yuv420p"])
    return [
        ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vf", f"scale=-2:min({MAXH},ih)", *vcodec,
        "-c:a", "aac", "-b:a", "128k",
        "-f", "segment", "-segment_time", str(SEG), "-reset_timestamps", "1",
        out_tmpl,
    ]


def prep_one(ff: str, src: Path, dry: bool = False) -> int:
    """Compress + segment one video into its folder's _ready/. Returns clip count."""
    outdir = src.parent / "_ready"
    outdir.mkdir(exist_ok=True)
    nm = _sanitize(src.stem)
    out_tmpl = str(outdir / f"{nm}_%03d.mp4")
    chk = outdir / f"{nm}_000.mp4"
    print(f"Prepping {src.name}  ->  {SEG}s clips ...", flush=True)

    if dry:
        print("  GPU:", " ".join(_seg_args(ff, src, out_tmpl, True)), flush=True)
        return 0

    subprocess.run(_seg_args(ff, src, out_tmpl, True), capture_output=True, text=True)
    if not chk.exists():
        print("  GPU encoder unavailable - using CPU (libx264, slower) ...", flush=True)
        r = subprocess.run(_seg_args(ff, src, out_tmpl, False),
                           capture_output=True, text=True)
        if not chk.exists():
            print(f"  [x] FAILED: {(r.stderr or '')[-300:]}", flush=True)
            return 0
    n = len(list(outdir.glob(f"{nm}_*.mp4")))
    print(f"  done -> {n} clip(s) in {outdir}", flush=True)
    return n


def collect(paths: list[str]) -> list[Path]:
    vids: list[Path] = []
    for a in paths:
        p = Path(a)
        if p.is_dir():
            vids += [f for f in sorted(p.iterdir())
                     if f.is_file() and f.suffix.lower() in VIDEO_EXTS]
        elif p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            vids.append(p)
    return vids


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv[1:]
    if not args:
        print("Drag a game FOLDER (or video files) onto prep_footage.bat.")
        return
    ff = find_ffmpeg()
    if not ff:
        print("[x] ffmpeg not found. Install it (winget install Gyan.FFmpeg), "
              "restart your PC, and retry.")
        return
    vids = collect(args)
    if not vids:
        print("No video files found in what you dropped.")
        return
    print(f"Found {len(vids)} video(s). Output goes to each folder's '_ready'.\n")
    total = 0
    for v in vids:
        total += prep_one(ff, v, dry=dry)
    print(f"\nAll done. {total} clip(s) ready. Tell Claude the prep is finished "
          "and it will upload them to the cloud.")


if __name__ == "__main__":
    main()
