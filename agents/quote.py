"""Motivational gaming quotes — text for Threads/X, and a designed quote CARD
(quote overlaid on a gameplay photo) for Facebook.

Quotes are ORIGINAL one-liners (no copyrighted lines from real games/people) so
they're always safe to post. The card is rendered with Pillow (no Remotion, so
it's safe to run locally too).
"""
from __future__ import annotations

import random
import textwrap
from pathlib import Path
from typing import Optional

from core import writer as ai
from core.config import CONFIG, ROOT
from core.dedup import avoid_block
from core.style import HUMAN_VOICE, sanitize

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Bold fonts to try in order: cloud (DejaVu via fonts-dejavu-core) then local
# Windows. Avoids bundling a font; production (cloud) is consistent on DejaVu.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
]


def _font(size: int):
    from PIL import ImageFont
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _system() -> str:
    b = CONFIG.brand
    return (
        f"You are the motivational-content writer for {b['name']} ({b['handle']}), "
        f"a gaming channel. You write original, punchy, genuinely inspiring quotes "
        f"about gaming + life.\n\n{HUMAN_VOICE}"
    )


def generate(extra_avoid: Optional[list[str]] = None) -> str:
    """Return ONE original English motivational gaming quote (no attribution)."""
    avoid = avoid_block()
    prompt = f"""Write ONE original, scroll-stopping MOTIVATIONAL quote about GAMING and life.

Like a shareable quote-card line. Use a gaming metaphor or idea (respawn, boss
fight, the grind, level up, checkpoint, co-op, hard mode, bad RNG, comeback) and
turn it into real-life motivation that hits.

Rules:
- Genuinely inspiring, not cheesy or corny. Confident, a little bold.
- ENGLISH. 6 to 18 words. One line (one sentence, or two very short ones).
- FULLY ORIGINAL: do NOT quote or paraphrase real people, games, movies, or any
  known quote. Invent it.
- No hashtags, no emojis, no quotation marks, no author/attribution. Just the line.

{avoid}

Return ONLY the quote line."""
    raw = ai.write(prompt, system=_system())
    line = sanitize(raw).strip().strip('"').splitlines()[0].strip().strip('"')
    return line[:160] or "Every pro was once a beginner who refused to hit quit."


def threads_text() -> str:
    """A motivational quote formatted for a Threads/X post: the quote + one tag."""
    q = generate()
    tags = (CONFIG.raw().get("quotes", {}) or {}).get("hashtags", ["#GamingMotivation"])
    tag = tags[0] if tags else ""
    return f"{q}\n\n{tag}".strip() if tag else q


def _candidate_photos() -> list[Path]:
    """Photos from the image asset folders, preferring on-strategy games."""
    qcfg = CONFIG.raw().get("quotes", {}) or {}
    base = ROOT / qcfg.get("image_dir", "assets/images")
    prefer = [str(g) for g in (qcfg.get("prefer", []) or
                               (CONFIG.reels.get("footage", {}) or {}).get("prefer", []))]
    exclude = {str(g).lower() for g in (qcfg.get("exclude", ["mlbb", "sports"]) or [])}
    photos: list[Path] = []
    if base.exists():
        dirs = [base / g for g in prefer if (base / g).is_dir()]
        # then any other non-excluded folder, for variety
        dirs += [d for d in base.iterdir()
                 if d.is_dir() and d.name.lower() not in exclude and d not in dirs]
        for d in dirs:
            photos += [p for p in d.iterdir()
                       if p.is_file() and p.suffix.lower() in IMG_EXTS]
    return photos


def pick_photo() -> Optional[Path]:
    """Pick a backdrop photo for a quote card (avoiding the most recent ones).

    Primary source: the image asset folders (per the user's request). If those
    are too sparse, the caller can fall back to a footage frame.
    """
    photos = _candidate_photos()
    if not photos:
        return None
    seen = _recent_photos()
    fresh = [p for p in photos if p.name not in seen] or photos
    return random.choice(fresh)


def _recent_photos() -> set[str]:
    """Names of recently-used quote photos (best-effort, from a tiny state file)."""
    f = ROOT / "output" / ".quote_photos_recent"
    try:
        return set(f.read_text(encoding="utf-8").split())
    except Exception:
        return set()


def _remember_photo(name: str, keep: int = 8) -> None:
    f = ROOT / "output" / ".quote_photos_recent"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        recent = (_recent_photos() | {name})
        names = list(recent)[-keep:]
        f.write_text(" ".join(names), encoding="utf-8")
    except Exception:
        pass


def render_card(
    quote: str,
    photo_path: Path,
    out_path: Path,
    logo: Optional[Path] = None,
    w: int = 1080,
    h: int = 1350,
) -> Path:
    """Render a designed quote card: the photo as a darkened backdrop with the
    quote in bold white centred text + KG branding. Returns the PNG path."""
    from PIL import Image, ImageDraw, ImageFilter

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg = Image.open(photo_path).convert("RGB")
    # cover-crop to w x h
    bw, bh = bg.size
    scale = max(w / bw, h / bh)
    bg = bg.resize((int(bw * scale + 1), int(bh * scale + 1)), Image.LANCZOS)
    bw, bh = bg.size
    bg = bg.crop(((bw - w) // 2, (bh - h) // 2, (bw - w) // 2 + w, (bh - h) // 2 + h))

    # Darken for legibility: blur a touch + a 55% black veil + stronger at the
    # centre band where the text sits.
    bg = bg.filter(ImageFilter.GaussianBlur(2))
    veil = Image.new("RGBA", (w, h), (0, 0, 0, 140))
    bg = Image.alpha_composite(bg.convert("RGBA"), veil)
    band = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(band).rectangle([0, int(h * 0.30), w, int(h * 0.74)], fill=(0, 0, 0, 90))
    bg = Image.alpha_composite(bg, band)

    draw = ImageDraw.Draw(bg)
    # Big opening quote mark accent (brand red).
    qfont = _font(180)
    draw.text((80, int(h * 0.18)), "“", font=qfont, fill=(229, 9, 20, 255))

    # Fit the quote: shrink font until it wraps within the margins + height.
    margin = 110
    max_w = w - 2 * margin
    for size in (96, 88, 80, 72, 64, 58, 52):
        font = _font(size)
        # wrap by measured width
        words, lines, cur = quote.split(), [], ""
        for wd in words:
            test = (cur + " " + wd).strip()
            if draw.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        line_h = int(size * 1.28)
        total_h = line_h * len(lines)
        if total_h <= int(h * 0.40) and len(lines) <= 7:
            break

    y = (h - total_h) // 2 + 10
    for ln in lines:
        tw = draw.textlength(ln, font=font)
        x = (w - tw) // 2
        # soft shadow + white text
        draw.text((x + 3, y + 3), ln, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += line_h

    # Branding: handle at the bottom, small circular logo above it if available.
    handle = str(CONFIG.brand.get("handle", "@kiwinoygamer"))
    hfont = _font(40)
    hw = draw.textlength(handle, font=hfont)
    draw.text(((w - hw) // 2, h - 90), handle, font=hfont, fill=(235, 235, 235, 255))
    if logo and Path(logo).exists():
        try:
            lg = Image.open(logo).convert("RGBA").resize((96, 96), Image.LANCZOS)
            bg.alpha_composite(lg, ((w - 96) // 2, h - 200))
        except Exception:
            pass

    bg.convert("RGB").save(out_path, "PNG")
    _remember_photo(Path(photo_path).name)
    return out_path
