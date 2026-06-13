"""Media resolver + post-image designer.

Turns a research brief into a finished, KG-designed post image by sourcing a base
photo in priority order, then rendering the headline on it:
  1. a CURATED photo you dropped in assets/images/<bucket>/ (free vision picks the
     most relevant one + finds the face)
  2. a frame grabbed from your gameplay/sports FOOTAGE (footage/<bucket>/ or the
     GitHub Release)
  3. (none) -> caller falls back to gpt-image-1

Everything is your own media, so it's copyright-clean and free.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agents import graphic, reel_composer
from core import frames
from core.config import CONFIG, ROOT

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Short uppercase context labels recognised in a topic, used as the sublabel.
_LABELS = [
    "MPL PHILIPPINES", "MPL", "M-SERIES", "MSC", "MLBB", "MOBILE LEGENDS",
    "THE INTERNATIONAL", "DOTA 2", "DOTA", "CS2", "COUNTER-STRIKE", "VALORANT",
    "WORLDS", "MSI", "LEAGUE OF LEGENDS", "WILD RIFT",
    "NBA FINALS", "NBA", "NFL", "PREMIER LEAGUE", "EPL", "UEFA", "GRAND SLAM",
    "GENSHIN IMPACT", "HONKAI", "STAR RAIL", "FINAL FANTASY", "RESIDENT EVIL", "HALO",
]


def bucket_for(brief: dict[str, Any]) -> str:
    """The image folder / footage key for this topic (sports, mlbb, dota2, ...)."""
    if brief.get("category") == "sports":
        return "sports"
    return reel_composer._footage_key_for(brief)


def _curated(bucket: str) -> list[Path]:
    d = ROOT / "assets" / "images" / bucket
    if not d.exists():
        return []
    return [p for p in d.iterdir() if p.suffix.lower() in IMG_EXTS]


def _sublabel(brief: dict[str, Any]) -> str:
    hay = f"{brief.get('subject', '')} {brief.get('title', '')}".upper()
    for label in _LABELS:
        if label in hay:
            return label
    return ""


def _headline(brief: dict[str, Any]) -> str:
    return (brief.get("headline_idea") or brief.get("title", "") or "").strip()


def _subheadline(brief: dict[str, Any]) -> str:
    """A short white supporting line for the lower half of a designed image.

    Prefers an explicit subhead, else the audience-facing topic title, else the
    editorial angle; trimmed to ~2 lines so it never crowds the logo/handle. The
    `title` reads to the viewer ("PH Sends Two Squads to MSC 2026 Paris"), whereas
    `angle` is internal editorial meta, so title wins.
    """
    s = (brief.get("subhead") or brief.get("title") or brief.get("angle", "")).strip()
    # Don't echo the headline back as the subheadline.
    if s and s.lower() == _headline(brief).lower():
        s = (brief.get("angle", "") or "").strip()
    if len(s) > 96:
        s = s[:96].rsplit(" ", 1)[0].rstrip(",.;:") + "..."
    return s


def resolve_base_image(brief: dict[str, Any], work_dir: Path) -> Optional[Path]:
    """Resolve ONE base photo: curated (vision-picked + face-framed) else a frame."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / "base.png"
    imgs = _curated(bucket_for(brief)) or _curated("general")
    if imgs:
        best, head = frames.pick_best(brief, imgs)
        if best:
            frames.compose_portrait(best, out, head_frac=head)
            return out
    clips = reel_composer.resolve_clips(brief)
    if clips and frames.grab(clips[0], brief, out):
        return out
    return None


def resolve_base_images(brief: dict[str, Any], n: int, work_dir: Path) -> list[Path]:
    """Resolve up to n distinct base photos (for carousels)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    imgs = _curated(bucket_for(brief)) or _curated("general")
    if imgs:
        out = []
        for i, p in enumerate(imgs[:n]):
            o = work_dir / f"base{i}.png"
            frames.compose_portrait(p, o, head_frac=0.2)
            out.append(o)
        return out
    clips = reel_composer.resolve_clips(brief)
    if clips:
        return frames.grab_n(clips[0], brief, n, work_dir)
    return []


def design(
    brief: dict[str, Any], save_path: Path, headline: str | None = None,
    sublabel: str | None = None, subheadline: str | None = None,
    size: str = "1080x1350", work_dir: Path | None = None,
) -> Optional[bytes]:
    """Design a finished post image (your media + KG headline). None if no media."""
    save_path = Path(save_path)
    base = resolve_base_image(brief, work_dir or save_path.parent)
    if base is None:
        return None
    graphic.render(
        base,
        headline if headline is not None else _headline(brief),
        save_path,
        sublabel=sublabel if sublabel is not None else _sublabel(brief),
        subheadline=subheadline if subheadline is not None else _subheadline(brief),
        size=size,
    )
    return save_path.read_bytes()
