"""Reel Composer agent — turns shots + beats into a rendered MP4 via Remotion.

Copies the generated background shots (and an optional royalty-free music track)
into reels/public/, writes a props file, and runs the Remotion renderer to
produce a 9:16 12-15s reel. Returns the MP4 bytes.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.config import CONFIG, ROOT

REELS_DIR = ROOT / "reels"
PUBLIC_DIR = REELS_DIR / "public"
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}


class ReelRenderError(RuntimeError):
    pass


def _npx() -> str:
    found = shutil.which("npx.cmd") or shutil.which("npx")
    if found:
        return found
    return "npx.cmd" if os.name == "nt" else "npx"


def _pick_music(tag: str) -> str | None:
    """Copy a random royalty-free track into public/, return its filename."""
    music_dir = ROOT / CONFIG.reels.get("music_dir", "reels/assets/music")
    if not music_dir.exists():
        return None
    tracks = [p for p in music_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS]
    if not tracks:
        return None
    chosen = random.choice(tracks)
    name = f"{tag}_music{chosen.suffix.lower()}"
    shutil.copyfile(chosen, PUBLIC_DIR / name)
    return name


def run(
    brief: dict[str, Any],
    beats: list[dict[str, str]],
    image_paths: list[Path],
    save_path: Path,
) -> bytes:
    """Render the reel MP4 to save_path and return its bytes."""
    reel = CONFIG.reels
    fps = int(reel.get("fps", 30))
    duration_frames = int(round(float(reel.get("duration_seconds", 14)) * fps))
    tag = save_path.stem  # unique-ish per run (e.g. timestamped name)

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    try:
        # 1) Stage background shots in public/ under unique names.
        image_names: list[str] = []
        for i, src in enumerate(image_paths):
            name = f"{tag}_shot{i}{Path(src).suffix.lower() or '.png'}"
            shutil.copyfile(src, PUBLIC_DIR / name)
            image_names.append(name)
            copied.append(name)

        music_name = _pick_music(tag)
        if music_name:
            copied.append(music_name)

        # 2) Write the props the Remotion composition reads.
        props = {
            "fps": fps,
            "durationInFrames": duration_frames,
            "width": int(reel.get("width", 1080)),
            "height": int(reel.get("height", 1920)),
            "category": brief.get("category", "gacha"),
            "images": image_names,
            "beats": beats,
            "music": music_name,
            "brand": CONFIG.brand.get("handle", "@kiwinoygamer"),
        }
        props_path = PUBLIC_DIR / f"{tag}_props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        copied.append(props_path.name)

        # 3) Render with Remotion.
        save_path.parent.mkdir(parents=True, exist_ok=True)
        if save_path.exists():
            save_path.unlink()
        cmd = [
            _npx(), "remotion", "render", "src/index.ts", "Reel",
            str(save_path),
            f"--props={props_path}",
            "--log=error",
        ]
        proc = subprocess.run(
            cmd, cwd=str(REELS_DIR), capture_output=True, text=True
        )
        if proc.returncode != 0 or not save_path.exists():
            raise ReelRenderError(
                f"Remotion render failed (exit {proc.returncode}).\n"
                f"STDOUT:\n{proc.stdout[-2000:]}\nSTDERR:\n{proc.stderr[-2000:]}"
            )
        return save_path.read_bytes()
    finally:
        # 4) Clean the per-run files we staged in public/.
        for name in copied:
            try:
                (PUBLIC_DIR / name).unlink(missing_ok=True)
            except Exception:
                pass
