"""YouTube thumbnail generator (1280x720) — "FULL GAME" walkthrough style.

Matches the popular full-game-walkthrough look: a striking game image, a dark
4K/HDR badge (top-right), an optional game logo (top-left), and a bold red
"FULL GAME" box (bottom-left). Pillow-only; returns the JPEG path (<2 MB).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from core.config import ROOT

W, H = 1280, 720


def _font(size: int, font_path: Optional[str] = None):
    from PIL import ImageFont

    cands = ([font_path] if font_path else []) + [
        str(ROOT / (_CFG().get("headline_font") or "")) if _CFG().get("headline_font") else "",
        str(ROOT / "assets/fonts/tarrget-font/TarrgetRegular-WEOz.otf"),
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ]
    for c in cands:
        if not c:
            continue
        try:
            f = ImageFont.truetype(str(c), size)
            # variable fonts -> use the heaviest weight for thumbnail punch
            for setter in ("Black", "ExtraBold"):
                try:
                    f.set_variation_by_name(setter)
                    break
                except Exception:
                    continue
            return f
        except Exception:
            continue
    return ImageFont.load_default()


def _CFG() -> dict:
    from core.config import CONFIG
    return (CONFIG.reels.get("thumbnail", {}) or {}) if hasattr(CONFIG, "reels") else {}


def _tsize(draw, text: str, font) -> tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def build_thumbnail(
    text: str = "FULL GAME",
    out_path=None,
    image: Optional[str] = None,
    game_logo: Optional[str] = None,
    badge_lines: Sequence[str] = ("4K", "HDR"),
    box_fill: tuple = (214, 18, 18),     # YouTube-red "FULL GAME" box
    font_path: Optional[str] = None,     # override the headline font
) -> Path:
    """Render the 1280x720 thumbnail: cover-cropped + punchier game image, a dark
    4K/HDR badge top-right, the game logo top-left (if given), and a bold red box
    with `text` (default FULL GAME) bottom-left. Saves JPEG."""
    from PIL import Image, ImageDraw, ImageEnhance

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = (Image.open(image).convert("RGB") if image and Path(image).exists()
            else Image.new("RGB", (W, H), (15, 16, 32)))
    bw, bh = base.size
    s = max(W / bw, H / bh)
    base = base.resize((max(W, int(bw * s)), max(H, int(bh * s))), Image.LANCZOS)
    bw, bh = base.size
    base = base.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))
    base = ImageEnhance.Contrast(base).enhance(1.10)
    base = ImageEnhance.Color(base).enhance(1.25)
    draw = ImageDraw.Draw(base)

    # game logo, top-left
    if game_logo and Path(game_logo).exists():
        try:
            lg = Image.open(game_logo).convert("RGBA")
            lh = 150
            lg = lg.resize((max(1, int(lg.width * (lh / lg.height))), lh), Image.LANCZOS)
            base.alpha_composite(lg.convert("RGBA"), (44, 36)) if base.mode == "RGBA" \
                else base.paste(lg, (44, 36), lg)
        except Exception:
            pass

    # 4K / HDR badge, top-right (dark rounded box, white bold lines)
    blines = [str(x).upper() for x in (badge_lines or []) if str(x).strip()]
    if blines:
        bf = _font(60)
        line_w = max(_tsize(draw, l, bf)[0] for l in blines)
        line_h = int(60 * 1.18)
        padx, pady = 24, 14
        boxw, boxh = line_w + padx * 2, line_h * len(blines) + pady * 2
        x1, y0 = W - 32, 32
        x0, y1 = x1 - boxw, y0 + boxh
        draw.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=(0, 0, 0),
                               outline=(255, 255, 255), width=4)
        cy = y0 + pady + line_h // 2
        for l in blines:
            draw.text(((x0 + x1) // 2, cy), l, font=bf, fill=(255, 255, 255), anchor="mm")
            cy += line_h

    # "FULL GAME" red box, bottom-left (font shrinks if the text is long)
    txt = (text or "FULL GAME").upper().strip()
    # Headline font: caller override, else the config default (Montserrat Black),
    # auto-switching to a CONDENSED font (Anton) for long headlines so they stay big.
    hl = font_path
    if not hl:
        cfg = _CFG()
        lf, thr = cfg.get("long_font"), int(cfg.get("long_threshold", 14) or 14)
        if lf and len(txt) > thr:
            hl = str(ROOT / lf)
    fsize = 96
    while fsize > 44:
        f = _font(fsize, hl)
        tw, th = _tsize(draw, txt, f)
        if tw <= int(W * 0.74):
            break
        fsize -= 6
    f = _font(fsize, hl)
    tw, th = _tsize(draw, txt, f)
    padx, pady = 34, 20
    x0, y1 = 46, H - 46
    x1, y0 = x0 + tw + padx * 2, y1 - (th + pady * 2)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=box_fill,
                           outline=(255, 255, 255), width=8)
    draw.text(((x0 + x1) // 2, (y0 + y1) // 2), txt, font=f, fill=(255, 255, 255),
              anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))

    base.save(out_path, "JPEG", quality=92, optimize=True)
    return out_path
