"""Image-set post agent (e.g. a daily Final Fantasy VII post).

Works off a large curated image set stored on a GitHub Release. Each run:
  1. samples a handful of images from the set (or a local folder)
  2. the free Claude vision groups duplicates, proposes ONE coherent theme
     (a location like Junon, a character, a battle), picks 3-5 DISTINCT images
     that fit, and writes a short 3-line caption
  3. each image is lightly enhanced (brightness/contrast/colour) and branded with
     the circular KG logo top-right (Pillow only -- no AI, no Remotion)
  4. publishes a carousel (3-5) or a single static post to Facebook + Instagram

All free: vision + caption on the Claude subscription token, imaging via Pillow.
"""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from typing import Any, Optional

from core import claude_code, gh_release
from core.config import CONFIG, ROOT
from core.openai_client import extract_json
from core.style import HUMAN_VOICE, sanitize

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_LOGO_CACHE: dict[int, Any] = {}


def _circular_logo(size: int):
    """Circular-cropped KG logo (RGBA) at the given pixel size, cached."""
    if size in _LOGO_CACHE:
        return _LOGO_CACHE[size]
    from PIL import Image, ImageDraw, ImageOps
    logo_cfg = CONFIG.reels.get("brand_logo")
    src = ROOT / logo_cfg if logo_cfg else None
    if not src or not src.exists():
        return None
    logo = Image.open(src).convert("RGBA")
    side = min(logo.size)
    logo = ImageOps.fit(logo, (side, side), Image.LANCZOS).resize(
        (size, size), Image.LANCZOS
    )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    logo.putalpha(mask)
    _LOGO_CACHE[size] = logo
    return logo


def brand_image(in_path: Path, out_path: Path, w: int = 1080, h: int = 1350,
                centering: tuple[float, float] = (0.5, 0.42)) -> Path:
    """Crop to 4:5 (toward the subject), enhance, stamp the circular KG logo.

    centering = the subject's (cx, cy) as fractions, so an off-centre character
    is kept in frame instead of cropped out by a dead-centre crop.
    """
    from PIL import Image, ImageEnhance, ImageOps
    im = Image.open(in_path).convert("RGB")
    cx = min(1.0, max(0.0, centering[0]))
    cy = min(1.0, max(0.0, centering[1]))
    im = ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(cx, cy))
    im = ImageEnhance.Brightness(im).enhance(1.03)
    im = ImageEnhance.Contrast(im).enhance(1.07)
    im = ImageEnhance.Color(im).enhance(1.10)
    im = ImageEnhance.Sharpness(im).enhance(1.15)
    logo = _circular_logo(132)
    if logo is not None:
        ring = Image.new("RGBA", im.size, (0, 0, 0, 0))
        margin = 44
        ring.paste(logo, (w - 132 - margin, margin), logo)
        im = Image.alpha_composite(im.convert("RGBA"), ring).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, quality=92)
    return out_path


def _all_release_assets(bucket: str) -> list[dict]:
    """Aggregate assets across all of a bucket's releases (handles the GitHub
    1000-assets/release cap: <bucket>-images, <bucket>-images-2, ...)."""
    out: list[dict] = []
    n = 1
    while n <= 20:
        tag = f"{bucket}-images" if n == 1 else f"{bucket}-images-{n}"
        assets = gh_release.list_release_assets(tag)
        if not assets and n > 1:
            break
        out += assets
        n += 1
    return out


def _sample(bucket: str, work_dir: Path, k: int) -> list[Path]:
    """Download a random sample of k images from the Release(s) (or local folder)."""
    assets = _all_release_assets(bucket)
    if assets:
        chosen = random.sample(assets, min(k, len(assets)))
        cache = work_dir / "dl"
        out = [gh_release.download(a, cache) for a in chosen]
        return [p for p in out if p]
    # Fallback: a local folder (useful for testing before the upload finishes).
    local = ROOT / "assets" / "images" / bucket
    if local.exists():
        imgs = [p for p in local.iterdir() if p.suffix.lower() in IMG_EXTS]
        return random.sample(imgs, min(k, len(imgs))) if imgs else []
    return []


def _plan(bucket: str, paths: list[Path], n_min: int, n_max: int) -> dict[str, Any]:
    """Vision (acting as a photo editor): theme + well-composed subject-focused
    picks (each with the subject's center for cropping) + a short caption."""
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(paths))
    names = CONFIG.reels.get("game_names", {}) or {}
    label = names.get(bucket, bucket.replace("-", " ").title())
    prompt = (
        f"You are a PROFESSIONAL PHOTO EDITOR for a gaming page. Use the Read tool "
        f"to open EACH of these {label} screenshots, then design ONE short post.\n\n"
        f"STEP 1 - THEME: group near-DUPLICATES (same moment/angle); pick ONE "
        f"coherent theme several share - usually a CHARACTER, or a location/battle.\n"
        f"STEP 2 - PICK {n_min} to {n_max} DISTINCT images with real photographic "
        f"judgment. The SUBJECT of the theme (usually a character) MUST be the clear "
        f"focus of each pick:\n"
        f"  - STRONGLY PREFER frames where the subject is LARGE, sharp, well-framed "
        f"and visible (hero shots, close/medium shots, expressive or action moments).\n"
        f"  - REJECT frames where the subject is tiny, cut off at an edge, turned "
        f"away, or swallowed by background/scenery/architecture (a building, an empty "
        f"room, a wide landscape) UNLESS the theme is explicitly that location.\n"
        f"  - Good composition: the subject occupies a meaningful part of the frame, "
        f"not lost in a corner.\n"
        f"STEP 3 - For EACH pick, give the SUBJECT'S CENTER as fractions cx,cy "
        f"(0,0 = top-left .. 1,1 = bottom-right) so we crop around the subject, not "
        f"the scenery.\n"
        f"STEP 4 - Write a SHORT caption (<=3 lines), hype but natural, no em-dashes, "
        f"no hashtags.\n\n"
        f"{HUMAN_VOICE}\n\n"
        f"Images:\n{listing}\n\n"
        "Reply with ONLY this JSON, no prose:\n"
        '{"theme": "...", "picks": [{"n": <image number>, "cx": <0..1>, '
        '"cy": <0..1>}], "caption": "...(<=3 lines)"}'
    )
    raw = claude_code.run(prompt, allowed_tools="Read", timeout=240)
    data = extract_json(raw)
    # Accept the new shape (picks with subject centers) or the old one (images).
    rows = data.get("picks")
    if not rows:
        rows = [{"n": n, "cx": 0.5, "cy": 0.42} for n in (data.get("images") or [])]
    picks: list[Path] = []
    centers: list[tuple[float, float]] = []
    seen: set[Path] = set()
    for row in rows:
        try:
            i = int(row.get("n")) - 1
        except Exception:
            continue
        if not (0 <= i < len(paths)) or paths[i] in seen:
            continue
        cx = _frac(row.get("cx"), 0.5)
        cy = _frac(row.get("cy"), 0.42)
        picks.append(paths[i])
        centers.append((cx, cy))
        seen.add(paths[i])
    if not picks:
        picks = paths[:n_min]
        centers = [(0.5, 0.42)] * len(picks)
    return {
        "theme": str(data.get("theme", "")).strip(),
        "caption": sanitize(str(data.get("caption", "")).strip()),
        "images": picks[:n_max],
        "centers": centers[:n_max],
    }


def _frac(v: Any, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except Exception:
        return default


def run(bucket: str = "ff7", dry_run: bool = False,
        scheduled_at: Optional[str] = None) -> dict[str, Any]:
    """One image-set post for the given bucket (carousel if >=3 images, else static)."""
    from agents import publisher
    from core.config import OUTPUT_DIR

    cfg = CONFIG.photoposts if hasattr(CONFIG, "photoposts") else {}
    k = int(cfg.get("sample_size", 24))
    n_min = int(cfg.get("slides_min", 3))
    n_max = int(cfg.get("slides_max", 5))

    stamp = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = OUTPUT_DIR / f"{stamp}_photo_{bucket}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[photo {bucket}] {m}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        log(f"Sampling {k} images from the set...")
        sample = _sample(bucket, Path(tmp), k)
        if not sample:
            log("No images available (Release empty + no local folder). Skipping.")
            return {"published": False, "skipped": "no_images"}
        log(f"Got {len(sample)} images. Vision picking a theme + set...")
        plan = _plan(bucket, sample, n_min, n_max)
        log(f"Theme: {plan['theme']} | {len(plan['images'])} images")

        centers = plan.get("centers") or [(0.5, 0.42)] * len(plan["images"])
        branded: list[bytes] = []
        for i, p in enumerate(plan["images"]):
            o = run_dir / f"slide{i + 1}.png"
            brand_image(p, o, centering=centers[i] if i < len(centers) else (0.5, 0.42))
            branded.append(o.read_bytes())

    caption = plan["caption"]
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
    result: dict[str, Any] = {
        "bucket": bucket, "theme": plan["theme"], "caption": caption,
        "n_images": len(branded), "dry_run": dry_run,
    }

    if dry_run or not branded:
        log("DRY RUN — not publishing." if dry_run else "No branded images; skip.")
        result["published"] = False
        (run_dir / "result.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8")
        return result

    if len(branded) >= 3:
        log("Publishing carousel to Facebook + Instagram...")
        api = publisher.run_carousel(caption=caption, images=branded,
                                     scheduled_at=scheduled_at)
    else:
        log("Publishing static post to Facebook + Instagram...")
        api = publisher.run(caption=caption, image_bytes=branded[0],
                            platform_keys=["facebook", "instagram"],
                            scheduled_at=scheduled_at)
    result["published"] = True
    result["postforme_result"] = api
    log(f"Published. id: {api.get('id', '(see result.json)')}")
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result
