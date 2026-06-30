"""Clickbait YouTube thumbnail generator (1280x720).

Composes a striking game image (chosen by the caller — usually the vision-picked
curated shot) + big bold high-contrast text into a scroll-stopping thumbnail.
Pillow-only. Returns the output path (JPEG, well under YouTube's 2 MB limit).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.config import ROOT

W, H = 1280, 720


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        ROOT / "assets/fonts/tarrget-font/TarrgetRegular-WEOz.otf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(str(c), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def build_thumbnail(
    text: str,
    out_path,
    image: Optional[str] = None,
    accent: tuple = (255, 209, 0),     # brand pop (gold)
    text_color: tuple = (255, 255, 255),
) -> Path:
    """Render a 1280x720 clickbait thumbnail: cover-cropped + punchier game image,
    a darkening gradient for legibility, BIG bold caps text with a heavy stroke +
    shadow (reads on any background), and a brand accent bar. Saves JPEG."""
    from PIL import Image, ImageDraw, ImageEnhance

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if image and Path(image).exists():
        base = Image.open(image).convert("RGB")
    else:
        base = Image.new("RGB", (W, H), (15, 16, 32))

    # cover-fill to 1280x720 (no bars), then pop contrast + saturation
    bw, bh = base.size
    scale = max(W / bw, H / bh)
    base = base.resize((max(W, int(bw * scale)), max(H, int(bh * scale))), Image.LANCZOS)
    bw, bh = base.size
    base = base.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
    base = ImageEnhance.Contrast(base).enhance(1.12)
    base = ImageEnhance.Color(base).enhance(1.28)

    # darken toward the bottom so the headline always reads
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        grad.putpixel((0, y), int(225 * (y / H) ** 1.5))
    grad = grad.resize((W, H))
    base = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), base, grad)

    draw = ImageDraw.Draw(base)
    txt = (text or "").upper().strip()

    # shrink the font until the headline fits in <= 3 lines
    size = 132
    while size > 46:
        f = _font(size)
        lines = _wrap(draw, txt, f, int(W * 0.90))
        if len(lines) <= 3:
            break
        size -= 6
    font = _font(size)
    lines = _wrap(draw, txt, font, int(W * 0.90))

    line_h = int(size * 1.12)
    y = H - line_h * len(lines) - 54
    stroke = max(6, size // 9)
    for ln in lines:
        draw.text((52, y), ln, font=font, fill=text_color,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h

    draw.rectangle([0, H - 12, W, H], fill=accent)   # brand accent strip

    base.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path
