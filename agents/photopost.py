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


def brand_image(in_path: Path, out_path: Path, w: int = 1080, h: int = 1350) -> Path:
    """Crop to 4:5, enhance, and stamp the circular KG logo top-right."""
    from PIL import Image, ImageEnhance, ImageOps
    im = Image.open(in_path).convert("RGB")
    im = ImageOps.fit(im, (w, h), Image.LANCZOS)
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
    """Vision: theme + 3-5 distinct non-duplicate images + a short caption."""
    listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(paths))
    label = {"ff7": "Final Fantasy VII Rebirth"}.get(bucket, bucket.upper())
    prompt = (
        f"Use the Read tool to open EACH of these {label} screenshots.\n"
        "Then design one short social post:\n"
        f"1. Group any near-DUPLICATE images (same moment/angle).\n"
        f"2. Pick ONE coherent theme several of them share - a location (e.g. "
        f"Junon, Midgar, Costa del Sol), a character, or a battle/moment.\n"
        f"3. Choose {n_min} to {n_max} DISTINCT (non-duplicate) images that best "
        f"fit that theme.\n"
        f"4. Write a SHORT caption, no more than 3 lines, hype but natural, no "
        f"em-dashes, no hashtags.\n\n"
        f"{HUMAN_VOICE}\n\n"
        f"Images:\n{listing}\n\n"
        "Reply with ONLY this JSON, no prose:\n"
        '{"theme": "...", "images": [<image numbers>], "caption": "...(<=3 lines)"}'
    )
    raw = claude_code.run(prompt, allowed_tools="Read", timeout=240)
    data = extract_json(raw)
    nums = data.get("images") or []
    picks: list[Path] = []
    for x in nums:
        try:
            i = int(x) - 1
            if 0 <= i < len(paths) and paths[i] not in picks:
                picks.append(paths[i])
        except Exception:
            continue
    if not picks:
        picks = paths[:n_min]
    return {
        "theme": str(data.get("theme", "")).strip(),
        "caption": sanitize(str(data.get("caption", "")).strip()),
        "images": picks[:n_max],
    }


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

        branded: list[bytes] = []
        for i, p in enumerate(plan["images"]):
            o = run_dir / f"slide{i + 1}.png"
            brand_image(p, o)
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
