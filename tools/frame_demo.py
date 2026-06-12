"""Demo: clip -> extracted player/hero frame -> enhance -> KG designed graphic.

Saves each stage to output/ so you can see the pipeline:
  frame_raw.png       the frame the vision agent picked (before enhancement)
  frame_enhanced.png  after sharpen/contrast/upscale
  frame_graphic.png   final post image with the KG headline

Usage:
  python tools/frame_demo.py                       # uses a committed MLBB clip
  python tools/frame_demo.py --video path.mp4 --headline "TEAMFIGHT DIFF"
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import graphic  # noqa: E402
from core import frames  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

p = argparse.ArgumentParser()
p.add_argument("--video", default=None)
p.add_argument("--headline", default="TEAMFIGHT DIFF")
p.add_argument("--sublabel", default="MPL PHILIPPINES")
a = p.parse_args()

video = Path(a.video) if a.video else None
if video is None:
    mlbb = Path("reels/assets/footage/mlbb")
    vids = (
        [x for x in mlbb.iterdir() if x.suffix.lower() in VIDEO_EXTS]
        if mlbb.exists() else []
    )
    if not vids:
        sys.exit("No MLBB clip found in reels/assets/footage/mlbb/")
    video = sorted(vids)[0]
print(f"video: {video.name}", flush=True)

out = Path("output")
out.mkdir(exist_ok=True)
brief = {"title": a.headline, "subject": "Mobile Legends MPL Philippines", "angle": ""}

with tempfile.TemporaryDirectory() as tmp:
    cands = frames.extract_candidates(video, Path(tmp), n=12)
    print(f"candidate frames: {len(cands)}", flush=True)
    best, head = frames.pick_best(brief, cands)
    if not best:
        sys.exit("Could not extract/pick a frame (ffmpeg present?).")
    print(f"picked sharpness {round(frames.sharpness(best), 1)}, head@{head:.2f}", flush=True)
    shutil.copyfile(best, out / "frame_raw.png")
    composed = Path(tmp) / "composed.png"
    frames.compose_portrait(best, composed, head_frac=head)
    frames.enhance(composed, out / "frame_enhanced.png")

graphic.render(out / "frame_enhanced.png", a.headline,
               out / "frame_graphic.png", sublabel=a.sublabel)
print("done -> output/frame_raw.png, frame_enhanced.png, frame_graphic.png", flush=True)
