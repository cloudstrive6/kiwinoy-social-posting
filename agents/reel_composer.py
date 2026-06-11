"""Reel Composer agent — turns shots + beats into a rendered MP4 via Remotion.

Copies the generated background shots (and an optional royalty-free music track)
into reels/public/, writes a props file, and runs the Remotion renderer to
produce a 9:16 12-15s reel. Returns the MP4 bytes.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.config import CONFIG, ROOT

REELS_DIR = ROOT / "reels"
PUBLIC_DIR = REELS_DIR / "public"
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def _has_clips(d: Path) -> bool:
    return d.exists() and any(p.suffix.lower() in VIDEO_EXTS for p in d.iterdir())


def _footage_dir_for(brief: dict[str, Any]) -> Path | None:
    """Resolve the footage subfolder for this topic (game-specific, else general)."""
    fcfg = CONFIG.reels.get("footage", {}) or {}
    base = ROOT / fcfg.get("dir", "reels/assets/footage")
    hay = " ".join(
        str(brief.get(k, "")) for k in ("title", "subject", "angle")
    ).lower()
    for entry in fcfg.get("map", []) or []:
        for kw in entry.get("match", []):
            if re.search(r"\b" + re.escape(str(kw).lower().strip()) + r"\b", hay):
                d = base / str(entry.get("dir", ""))
                if _has_clips(d):
                    return d
    gen = base / "general"
    return gen if _has_clips(gen) else None


def resolve_clips(brief: dict[str, Any]) -> list[Path]:
    """Pick gameplay clips for this reel, or [] to fall back to AI stills.

    Looks in the topic's footage folder (e.g. .../mlbb/), else .../general/.
    Returns up to `max_clips` distinct clips (random order).
    """
    fcfg = CONFIG.reels.get("footage", {}) or {}
    if not fcfg.get("enabled", False):
        return []
    folder = _footage_dir_for(brief)
    if folder is None:
        return []
    vids = [p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS]
    if not vids:
        return []
    hi = int(fcfg.get("max_clips", 4))
    return random.sample(vids, min(hi, len(vids)))


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
    narration_path: Path | None = None,
    clips: list[Path] | None = None,
) -> bytes:
    """Render the reel MP4 to save_path and return its bytes.

    clips: optional gameplay footage. When given, the reel is built from these
    clips (spliced + captioned) instead of the AI background stills.
    narration_path: optional ElevenLabs VO audio; if given it plays over the
    reel and the background music is ducked underneath it.
    """
    reel = CONFIG.reels
    fps = int(reel.get("fps", 30))
    tag = save_path.stem  # unique-ish per run (e.g. timestamped name)

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    try:
        # 1) Stage either gameplay clips (preferred) or AI background shots.
        image_names: list[str] = []
        clip_props: list[dict[str, Any]] = []
        if clips:
            clip_secs = float((reel.get("footage", {}) or {}).get("clip_seconds", 4))
            clip_frames = int(round(clip_secs * fps))
            for i, src in enumerate(clips):
                name = f"{tag}_clip{i}{Path(src).suffix.lower() or '.mp4'}"
                shutil.copyfile(src, PUBLIC_DIR / name)
                copied.append(name)
                clip_props.append({"src": name, "durationInFrames": clip_frames})
            duration_frames = sum(c["durationInFrames"] for c in clip_props)
        else:
            duration_frames = int(round(float(reel.get("duration_seconds", 14)) * fps))
            for i, src in enumerate(image_paths):
                name = f"{tag}_shot{i}{Path(src).suffix.lower() or '.png'}"
                shutil.copyfile(src, PUBLIC_DIR / name)
                image_names.append(name)
                copied.append(name)

        music_name = _pick_music(tag)
        if music_name:
            copied.append(music_name)

        # Stage the AI voiceover (if provided) so Remotion can play it.
        narration_name = None
        if narration_path is not None and Path(narration_path).exists():
            narration_name = f"{tag}_vo{Path(narration_path).suffix.lower() or '.mp3'}"
            shutil.copyfile(narration_path, PUBLIC_DIR / narration_name)
            copied.append(narration_name)

        # Stage the channel logo (if configured) so the reel can show it.
        logo_name = None
        logo_cfg = CONFIG.reels.get("brand_logo")
        if logo_cfg:
            logo_src = ROOT / logo_cfg
            if logo_src.exists():
                logo_name = f"{tag}_logo{logo_src.suffix.lower() or '.png'}"
                shutil.copyfile(logo_src, PUBLIC_DIR / logo_name)
                copied.append(logo_name)

        # 2) Write the props the Remotion composition reads.
        props = {
            "fps": fps,
            "durationInFrames": duration_frames,
            "width": int(reel.get("width", 1080)),
            "height": int(reel.get("height", 1920)),
            "category": brief.get("category", "gacha"),
            "images": image_names,
            "clips": clip_props,
            "beats": beats,
            "music": music_name,
            "narration": narration_name,
            "brand": CONFIG.reels.get("brand_badge", "KG"),
            "logo": logo_name,
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
