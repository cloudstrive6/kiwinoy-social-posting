"""Graphic renderer — designs a scroll-stopping on-image headline over a photo.

Takes one of the channel's curated photos + a headline and renders a single
designed PNG (KG brand theme: dark photo, bold red headline, logo) via Remotion's
`still` command. Used for FB/IG static + carousel posts and Threads image posts.
No per-image AI cost; the text is CSS so it's always perfectly spelled.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from core.config import CONFIG, ROOT

REELS_DIR = ROOT / "reels"
PUBLIC_DIR = REELS_DIR / "public"


class GraphicError(RuntimeError):
    pass


def _npx() -> str:
    found = shutil.which("npx.cmd") or shutil.which("npx")
    if found:
        return found
    return "npx.cmd" if os.name == "nt" else "npx"


def render(
    image_path: Path | None,
    headline: str,
    save_path: Path,
    sublabel: str = "",
    subheadline: str = "",
    accent: str | None = None,
    size: str = "1080x1350",
) -> bytes:
    """Render a designed graphic PNG to save_path and return its bytes."""
    g = CONFIG.graphics if hasattr(CONFIG, "graphics") else {}
    w, h = (int(x) for x in size.lower().split("x"))
    # Remotion runs with cwd=reels/, so the output path must be ABSOLUTE or it
    # would be written under reels/ and our existence check would miss it.
    save_path = Path(save_path).resolve()
    tag = save_path.stem
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    try:
        image_name = None
        if image_path is not None and Path(image_path).exists():
            image_name = f"{tag}_bg{Path(image_path).suffix.lower() or '.jpg'}"
            shutil.copyfile(image_path, PUBLIC_DIR / image_name)
            copied.append(image_name)

        logo_name = None
        logo_cfg = CONFIG.reels.get("brand_logo")
        if logo_cfg and (ROOT / logo_cfg).exists():
            logo_name = f"{tag}_logo{Path(logo_cfg).suffix.lower() or '.png'}"
            shutil.copyfile(ROOT / logo_cfg, PUBLIC_DIR / logo_name)
            copied.append(logo_name)

        props = {
            "image": image_name,
            "headline": headline,
            "sublabel": sublabel,
            "subheadline": subheadline,
            "footer": CONFIG.brand.get("handle", "@kiwinoygamer"),
            "accent": accent or (g.get("accent") if g else None) or "#E5322C",
            "logo": logo_name,
            "width": w,
            "height": h,
        }
        props_path = PUBLIC_DIR / f"{tag}_gprops.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        copied.append(props_path.name)

        save_path.parent.mkdir(parents=True, exist_ok=True)
        if save_path.exists():
            save_path.unlink()
        cmd = [
            _npx(), "remotion", "still", "src/index.ts", "Graphic",
            str(save_path), f"--props={props_path}", "--log=error",
        ]
        proc = subprocess.run(cmd, cwd=str(REELS_DIR), capture_output=True, text=True)
        if proc.returncode != 0 or not save_path.exists():
            raise GraphicError(
                f"Remotion still failed (exit {proc.returncode}).\n"
                f"STDERR:\n{proc.stderr[-2000:]}"
            )
        return save_path.read_bytes()
    finally:
        for name in copied:
            try:
                (PUBLIC_DIR / name).unlink(missing_ok=True)
            except Exception:
                pass
