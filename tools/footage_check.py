"""Footage truth check (Bryce, 2026-11-23: "You need to watch/analyze more the scenes and really know each
of the videos/footage/scenes/gameplay well"). The beginners guide said "I held up Tucker's farm stand"
when Bryce had stopped a robbery in progress and the cashier offered a reward: the script was written
from 3 stills per clip and never heard the dialogue.

For one stretch of a B2 clip this writes, under output/footage-check/<name>/:
  frames/<mm>m<ss.s>s.jpg   one frame every --step seconds (HUD kept), 640 px wide
  sheet<n>.jpg              20 frames per labelled contact sheet
  dialogue.txt              every spoken line with its time (faster-whisper small.en on CPU)
so a writer, a reviewer or the claims check (tools/claims_check.py) can see what really happened. Read-only
on B2, CPU only (Bryce streams on the GPU). Used locally and on GitHub Actions.

    python tools/footage_check.py "cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p05.mp4" 0 130 --name tucker
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def dialogue_lines(wav: Path, gap: float = 1.0) -> list[tuple[float, str]]:
    from analysis_shorts import whisper_words
    words = whisper_words(wav, "", model="small.en", vad=True)
    lines, cur, t0, prev = [], [], None, 0.0
    for w in words:
        if cur and w["s"] - prev > gap:
            lines.append((t0, " ".join(cur)))
            cur, t0 = [], None
        if t0 is None:
            t0 = w["s"]
        cur.append(w["w"])
        prev = w["e"]
    if cur:
        lines.append((t0, " ".join(cur)))
    return lines


def run_check(key: str, start: float, end: float, name: str, step: float = 2.0, audio: bool = True) -> Path:
    """Frames, labelled sheets and dialogue for key[start:end]; returns the output folder. Reuses a
    finished folder (dialogue.txt present) for the same range."""
    from core import b2_store
    out = ROOT / "output" / "footage-check" / name
    done = out / "dialogue.txt"
    if done.exists() and done.read_text(encoding="utf-8").startswith(f"{key} {start}-{end} s"):
        return out
    if out.exists():
        shutil.rmtree(out)
    url = b2_store.presigned_url(key, valid_seconds=3600)
    if not url:
        raise SystemExit("no B2 link (check the B2 keys)")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    piece = out / "piece.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-reconnect", "1", "-ss", f"{start}", "-i", url, "-t",
                    f"{end - start}", "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=640:-2,fps=10", "-c:v",
                    "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k", str(piece)],
                   check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(piece), "-vf", f"fps=1/{step}",
                    str(out / "frames" / "f%04d.jpg")], check=True)
    for i, f in enumerate(sorted((out / "frames").glob("f*.jpg"))):
        t = start + i * step
        f.rename(out / "frames" / f"{int(t // 60):02d}m{t % 60:05.1f}s.jpg")
    from PIL import Image, ImageDraw  # labelled sheets, 20 frames each (ffmpeg drawtext needs fontconfig)
    named = sorted((out / "frames").glob("*.jpg"))
    for n0 in range(0, len(named), 20):
        part = named[n0:n0 + 20]
        ims = [Image.open(f).resize((384, 216)) for f in part]
        sheet = Image.new("RGB", (384 * 5, 216 * (-(-len(ims) // 5))))
        for i, (im, f) in enumerate(zip(ims, part)):
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, 92, 16), fill=(0, 0, 0))
            d.text((4, 2), f.stem, fill=(255, 230, 0))
            sheet.paste(im, ((i % 5) * 384, (i // 5) * 216))
        sheet.save(out / f"sheet{n0 // 20 + 1}.jpg", quality=85)
    lines = []
    if audio:
        wav = out / "audio.wav"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(piece), "-vn", "-ac", "1", "-ar", "16000",
                            str(wav)])
        if r.returncode == 0 and wav.exists():
            lines = dialogue_lines(wav)
            wav.unlink()
    txt = "\n".join(f"[{start + t:7.1f} s] {s}" for t, s in lines) or "(no speech heard)"
    piece.unlink()
    done.write_text(f"{key} {start}-{end} s\n\n{txt}\n", encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key", help="B2 key of the clip")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("--name", required=True)
    ap.add_argument("--step", type=float, default=2.0)
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()
    out = run_check(a.key, a.start, a.end, a.name, a.step, not a.no_audio)
    print(json.dumps({"out": str(out), "frames": len(list((out / "frames").glob("*.jpg")))}))
    print((out / "dialogue.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
