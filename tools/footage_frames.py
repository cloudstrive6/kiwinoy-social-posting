"""Contact sheets for a game's analysis footage (read-only, 2026-11-12).

Per the analysis long-form rule (Bryce 2026-11-12), the source folders are B2
cutscenes/<game>/ and footage/<game>/ only. For each clip, grabs stills at 10%, 50% and 90%
over a short-lived presigned URL (ffmpeg seeks over HTTP, nothing is downloaded whole) and
lays them out 8 clips to a sheet, one row per clip, with the clip index and file name.
Writes output/inventory/frames/<game>/sheet_NN.jpg and index.json. Never uploads or deletes.

    python tools/footage_frames.py wolverine
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from core import b2_store  # noqa: E402

W, H = 320, 180
PER_SHEET = 8
LABEL_H = 22


def duration(url: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", url], capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def grab(url: str, t: float, out: Path) -> bool:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", url, "-frames:v", "1",
                        "-vf", f"scale={W}:{H}", str(out)], capture_output=True, timeout=90)
    return r.returncode == 0 and out.exists()


def main() -> int:
    game = (sys.argv[1] if len(sys.argv) > 1 else "wolverine").lower()
    clips = ([dict(c, pool="cutscenes") for c in b2_store.list_cutscenes(game)]
             + [dict(c, pool="footage") for c in b2_store.list_footage(game)])
    clips.sort(key=lambda c: (c["pool"], c["name"]))
    out = ROOT / "output" / "inventory" / "frames" / game
    tmp = out / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        font = ImageFont.load_default()

    index = []
    for i, c in enumerate(clips):
        url = b2_store.presigned_url(c["key"], valid_seconds=3600) or ""
        d = duration(url) if url else 0.0
        frames = []
        for j, frac in enumerate((0.1, 0.5, 0.9)):
            p = tmp / f"{i:04d}_{j}.jpg"
            if d and grab(url, d * frac, p):
                frames.append(str(p))
        index.append({"idx": i, "pool": c["pool"], "name": c["name"], "key": c["key"],
                      "seconds": round(d, 1), "frames": frames})
        if i % 20 == 0:
            print(f"{i + 1}/{len(clips)}", flush=True)

    for s in range(0, len(index), PER_SHEET):
        rows = index[s:s + PER_SHEET]
        sheet = Image.new("RGB", (W * 3, (H + LABEL_H) * len(rows)), "black")
        draw = ImageDraw.Draw(sheet)
        for r, item in enumerate(rows):
            y = r * (H + LABEL_H)
            draw.text((4, y + 3), f"#{item['idx']} {item['pool']} | {item['name']} | {item['seconds']} s",
                      fill="white", font=font)
            for j, fp in enumerate(item["frames"]):
                sheet.paste(Image.open(fp), (j * W, y + LABEL_H))
        sheet.save(out / f"sheet_{s // PER_SHEET + 1:02d}.jpg", quality=82)
    for item in index:
        item.pop("frames", None)
    (out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    for f in tmp.glob("*.jpg"):
        f.unlink()
    tmp.rmdir()
    print(f"{len(index)} clips, {(len(index) + PER_SHEET - 1) // PER_SHEET} sheets in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
