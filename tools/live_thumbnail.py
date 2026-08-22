"""Generate a YouTube LIVE-session thumbnail (1280x720) from a game's committed key art.

Keeps it clean: the game's own key art (which already carries the game logo) is the
background; we overlay a bold red "LIVE" badge + the KG logo + a thin brand accent, so
every stream gets a consistent, on-brand cover without stamping a second title on top.

Output: assets/live-covers/<game>-live.png  (committed, ready to upload)
(Not "thumbnails/" — that folder name is globally gitignored for the auto-generated
per-upload thumbnail variants.)

  python tools/live_thumbnail.py --game halo
  python tools/live_thumbnail.py --game halo --title "CAMPAIGN EVOLVED"   # optional extra line
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
ART_DIR = ROOT / "reels" / "assets" / "game-art"
OUT_DIR = ROOT / "assets" / "live-covers"
LOGO = ROOT / "reels" / "assets" / "logo" / "KG Logo 2.PNG"
FONT_ANTON = ROOT / "assets" / "fonts" / "anton" / "Anton-Regular.ttf"

W, H = 1280, 720
RED = (255, 61, 70)

# site game slug -> game-art folder key (mirrors reels/assets/game-art/)
ART_KEY = {
    "halo": "halo",
    "spider-man-1": "spider-man1",
    "spider-man-miles": "spider-man-miles-morales",
    "spider-man-2": "spider-man2",
    "wolverine": "wolverine",
    "final-fantasy-7": "ff7remake",
}


def _first_art(key: str) -> Path:
    d = ART_DIR / key
    imgs: list[Path] = []
    for pat in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        imgs += sorted(d.glob(pat))
    if not imgs:
        raise SystemExit(f"[live-thumb] no key art found in {d}")
    # Prefer a designated hero image named "*main*" (e.g. ff7remake game-art-main.jpg).
    for im in imgs:
        if "main" in im.stem.lower():
            return im
    return imgs[0]


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    iw, ih = im.size
    scale = max(w / iw, h / ih)
    nim = im.resize((round(iw * scale), round(ih * scale)), Image.LANCZOS)
    x = (nim.width - w) // 2
    y = (nim.height - h) // 2
    return nim.crop((x, y, x + w, y + h))


def _grad(w: int, h: int, top_a: int, bot_a: int) -> Image.Image:
    """Vertical black gradient (alpha top_a -> bot_a)."""
    g = Image.new("L", (1, h))
    for y in range(h):
        g.putpixel((0, y), int(top_a + (bot_a - top_a) * y / max(1, h - 1)))
    a = g.resize((w, h))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.putalpha(a)
    return out


def build(game: str, title: str | None) -> Path:
    key = ART_KEY.get(game, game)
    art = Image.open(_first_art(key)).convert("RGB")
    canvas = _cover(art, W, H)
    canvas = ImageEnhance.Brightness(canvas).enhance(0.9)
    canvas = ImageEnhance.Contrast(canvas).enhance(1.05)
    canvas = canvas.convert("RGBA")

    # bottom scrim so logo/title read on bright art
    canvas.alpha_composite(_grad(W, H, 0, 150))

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # top brand accent hairline
    d.rectangle([0, 0, W, 7], fill=RED + (255,))

    # ---- LIVE badge (top-left) ----
    # Center on the TIGHT glyph bbox (not the em box) so the caps sit optically centred;
    # Anton reserves descender space that would otherwise push "LIVE" high.
    font_live = ImageFont.truetype(str(FONT_ANTON), 58)
    label = "LIVE"
    lb, tb, rb, bb = font_live.getbbox(label)
    text_w, text_h = rb - lb, bb - tb
    dot_r, gap, pad_x, pad_y = 13, 18, 34, 22
    content_w = dot_r * 2 + gap + text_w
    bx0, by0 = 44, 44
    badge_w = pad_x * 2 + content_w
    badge_h = pad_y * 2 + max(dot_r * 2, text_h)
    cy = by0 + badge_h // 2
    cx = bx0 + pad_x

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        [bx0, by0, bx0 + badge_w, by0 + badge_h], radius=20, fill=RED + (190,))
    overlay = Image.alpha_composite(overlay, glow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(overlay)

    d.rounded_rectangle([bx0, by0, bx0 + badge_w, by0 + badge_h], radius=20, fill=RED + (255,))
    d.ellipse([cx, cy - dot_r, cx + dot_r * 2, cy + dot_r], fill=(255, 255, 255, 255))
    # subtract the left/top bearings (lb, tb) so the glyphs are truly centred in the pill
    d.text((cx + dot_r * 2 + gap - lb, cy - (tb + bb) / 2), label,
           font=font_live, fill=(255, 255, 255, 255))

    # ---- optional extra title line (bottom-left) ----
    if title:
        ft = ImageFont.truetype(str(FONT_ANTON), 64)
        tx, ty = 48, H - 118
        # stroke for legibility
        d.text((tx, ty), title.upper(), font=ft, fill=(255, 255, 255, 255),
               stroke_width=5, stroke_fill=(0, 0, 0, 220))
        d.rectangle([tx, ty - 16, tx + 90, ty - 8], fill=RED + (255,))

    canvas = Image.alpha_composite(canvas, overlay)

    # ---- KG logo (bottom-right), circular-cropped (matches the reels watermark) ----
    d_size = 152
    logo = Image.open(LOGO).convert("RGBA")
    s = min(logo.size)                                   # center-crop to a square first
    logo = logo.crop(((logo.width - s) // 2, (logo.height - s) // 2,
                      (logo.width + s) // 2, (logo.height + s) // 2)).resize((d_size, d_size), Image.LANCZOS)
    mask = Image.new("L", (d_size * 4, d_size * 4), 0)   # supersample for a smooth edge
    ImageDraw.Draw(mask).ellipse([0, 0, d_size * 4, d_size * 4], fill=255)
    logo.putalpha(mask.resize((d_size, d_size), Image.LANCZOS))

    lx, ly = W - d_size - 44, H - d_size - 34
    # circular soft shadow
    sil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sil).ellipse([lx + 4, ly + 7, lx + 4 + d_size, ly + 7 + d_size], fill=(0, 0, 0, 170))
    sil.putalpha(sil.getchannel("A").filter(ImageFilter.GaussianBlur(12)))
    canvas = Image.alpha_composite(canvas, sil)
    canvas.alpha_composite(logo, (lx, ly))
    # thin white ring for definition on busy art
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([lx + 1, ly + 1, lx + d_size - 2, ly + d_size - 2],
                                 outline=(255, 255, 255, 235), width=4)
    canvas = Image.alpha_composite(canvas, ring)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{game}-live.png"
    canvas.convert("RGB").save(out, "PNG")
    print(f"[live-thumb] wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a YouTube LIVE thumbnail from game art.")
    ap.add_argument("--game", default="halo", help="game slug (default: halo)")
    ap.add_argument("--title", default=None, help="optional extra title line (e.g. a mode)")
    a = ap.parse_args()
    build(a.game, a.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
