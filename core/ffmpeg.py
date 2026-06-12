"""ffmpeg helpers for the gameplay / commentary reel composer.

These reels are "gameplay footage + burned-on overlays + (optional) subtitles" —
no per-frame animation — so ffmpeg renders them far faster than Remotion (which
draws every frame in headless Chrome). ffmpeg handles 15-minute videos in a few
minutes; Remotion would blow the CI time limit.

Everything fails open / returns sensible defaults so a missing ffmpeg never
crashes a run (the caller logs + skips instead).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def ffmpeg_bin() -> Optional[str]:
    """Locate the ffmpeg binary: PATH, then the user's winget install, then C:\\."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import os
    cand = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
    ]
    for c in cand:
        if c.exists():
            return str(c)
    return None


def ffprobe_bin() -> Optional[str]:
    found = shutil.which("ffprobe")
    if found:
        return found
    import os
    cand = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffprobe.exe",
        Path("C:/ffmpeg/bin/ffprobe.exe"),
    ]
    for c in cand:
        if c.exists():
            return str(c)
    return None


def duration(video: Path) -> float:
    """Seconds of a media file (0.0 if unknown / ffprobe missing)."""
    fp = ffprobe_bin()
    if not fp:
        return 0.0
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, timeout=60,
        )
        return float((out.stdout or "0").strip() or 0.0)
    except Exception:
        return 0.0


def has_audio(video: Path) -> bool:
    """True if the file has at least one audio stream."""
    fp = ffprobe_bin()
    if not fp:
        return False
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, timeout=60,
        )
        return bool((out.stdout or "").strip())
    except Exception:
        return False


def run(args: list[str], timeout: int = 1800) -> tuple[int, str]:
    """Run `ffmpeg <args>` (binary auto-prepended). Returns (returncode, stderr tail)."""
    ff = ffmpeg_bin()
    if not ff:
        return 127, "ffmpeg not found on PATH"
    cmd = [ff, "-hide_banner", "-y"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stderr or "")[-3000:]
    except Exception as e:
        return 1, f"{e!r}"


def ass_time(seconds: float) -> str:
    """Format seconds as an ASS timestamp H:MM:SS.cs (centiseconds)."""
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs == 100:  # rounding spillover
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    """Escape a caption line for an ASS dialogue event."""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", "\\N")
    )
