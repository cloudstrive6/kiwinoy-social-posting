"""Frame grabber — turn a gameplay/sports clip into a clean still image.

Pipeline: ffmpeg extracts candidate frames across the clip -> each is scored for
sharpness (variance of Laplacian, no AI) -> the free Claude CLI vision picks the
best frame (player/hero clearly visible, sharp, good composition) among the
sharpest -> Pillow enhances it (upscale + unsharp + contrast + color).

Honest limits: enhancement genuinely helps soft frames but cannot fully fix
heavy motion blur, so the real win is scoring + picking the sharpest candidate.
Everything fails open: returns None if ffmpeg/Pillow are unavailable.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from core import claude_code


def _ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def _duration(video: Path) -> float:
    fp = _ffprobe()
    if not fp:
        return 0.0
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, timeout=60,
        )
        return float((out.stdout or "0").strip())
    except Exception:
        return 0.0


def extract_candidates(video: Path, out_dir: Path, n: int = 10) -> list[Path]:
    """Extract ~n frames spread across the clip. Returns saved frame paths."""
    ff = _ffmpeg()
    if not ff:
        print("[frames] ffmpeg not found on PATH.", flush=True)
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = _duration(video)
    vf = f"fps={max(0.1, n / dur):.4f}" if dur > 0 else "fps=1/2"
    pattern = str(out_dir / "cand_%03d.png")
    try:
        proc = subprocess.run(
            [ff, "-hide_banner", "-loglevel", "error", "-i", str(video),
             "-vf", vf, "-frames:v", str(n * 2), "-q:v", "2", pattern],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            print(f"[frames] ffmpeg exit {proc.returncode} (dur={dur}, vf={vf}): "
                  f"{(proc.stderr or '')[-400:]}", flush=True)
    except Exception as e:
        print(f"[frames] ffmpeg error: {e!r}", flush=True)
        return []
    return sorted(out_dir.glob("cand_*.png"))


def sharpness(path: Path) -> float:
    """Variance-of-Laplacian sharpness score (higher = sharper). 0 on error."""
    try:
        from PIL import Image, ImageFilter, ImageStat
        im = Image.open(path).convert("L")
        im.thumbnail((720, 720))
        lap = im.filter(
            ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1)
        )
        return float(ImageStat.Stat(lap).var[0])
    except Exception:
        return 0.0


def enhance(in_path: Path, out_path: Path, target_min: int = 1280) -> Path:
    """Upscale (if small) + sharpen + lift contrast/colour. Returns out_path."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        im = Image.open(in_path).convert("RGB")
        w, h = im.size
        m = min(w, h)
        if m < target_min:
            f = target_min / m
            im = im.resize((round(w * f), round(h * f)), Image.LANCZOS)
        im = im.filter(ImageFilter.UnsharpMask(radius=2.2, percent=135, threshold=2))
        im = ImageEnhance.Contrast(im).enhance(1.07)
        im = ImageEnhance.Color(im).enhance(1.12)
        im = ImageEnhance.Brightness(im).enhance(1.02)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path)
    except Exception:
        shutil.copyfile(in_path, out_path)
    return out_path


def pick_best(brief: dict[str, Any], paths: list[Path]) -> Optional[Path]:
    """Pick the best frame: sharpest few -> free-vision chooses by composition."""
    if not paths:
        return None
    top = sorted(paths, key=sharpness, reverse=True)[:4]
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(top))
    prompt = (
        "Use the Read tool to open EACH of these image files, then choose the "
        "single best one to use as the background of a social media post about: "
        f"{brief.get('title', '')} ({brief.get('subject', '')}).\n"
        "Prefer: the player or game character clearly and prominently visible, "
        "sharp focus, strong composition, minimal motion blur, and NOT a blank, "
        "transition, or heavily UI-cluttered frame.\n\n"
        f"Images:\n{listing}\n\n"
        f"Reply with ONLY the number (1-{len(top)}) of the best image."
    )
    try:
        ans = claude_code.run(prompt, allowed_tools="Read", timeout=180).strip()
        m = re.search(r"[1-9]\d*", ans)
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(top):
                return top[idx]
    except Exception as e:
        print(f"[frames] vision pick failed ({e!r}); using sharpest frame.", flush=True)
    return top[0]


def grab(video: Path, brief: dict[str, Any], out_path: Path, n: int = 10) -> Optional[Path]:
    """Full pipeline: clip -> best enhanced still at out_path (or None)."""
    with tempfile.TemporaryDirectory() as tmp:
        cands = extract_candidates(Path(video), Path(tmp), n=n)
        if not cands:
            print("[frames] no candidates (ffmpeg missing or unreadable clip).", flush=True)
            return None
        best = pick_best(brief, cands)
        if best is None:
            return None
        enhance(best, out_path)
    return out_path
