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


def _auto_focus(base) -> tuple[float, float]:
    """Best-effort subject point (fx, fy in 0..1): where DETAIL + COLOUR is densest
    (characters have both; flat backgrounds don't), with a mild centre bias."""
    import numpy as np

    sm = np.asarray(base.convert("RGB").resize((160, 90)), dtype=np.float32)
    lum = sm.mean(axis=2)
    detail = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1])) + \
        np.abs(np.diff(lum, axis=0, prepend=lum[:1, :]))
    sat = sm.max(axis=2) - sm.min(axis=2)
    score = detail + 0.6 * sat
    h, w = score.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cbias = 1.0 - 0.5 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    score *= np.clip(cbias, 0.3, 1.0)
    # centroid of the top-scoring cells (robust vs a single hot pixel)
    thr = np.quantile(score, 0.90)
    m = score >= thr
    fx = float((xx[m]).mean()) / w
    fy = float((yy[m]).mean()) / h
    return (min(0.85, max(0.15, fx)), min(0.8, max(0.2, fy)))


def _bloom(base, strength: float):
    """Soft glow on the highlights -> cinematic/premium feel."""
    import numpy as np
    from PIL import Image, ImageChops, ImageFilter

    arr = np.asarray(base.convert("RGB"), dtype=np.float32)
    mask = np.clip((arr.mean(axis=2) - 175.0) / 80.0, 0, 1)[..., None]
    glow = Image.fromarray((arr * mask).astype("uint8")).filter(ImageFilter.GaussianBlur(18))
    return ImageChops.screen(base.convert("RGB"), glow.point(lambda v: int(v * strength)))


def _focus_grade(base, focus, vignette: float, spotlight: float):
    """Darken AWAY from the focus point (vignette) and brighten AT it (spotlight),
    so the viewer's eye is pulled straight to the subject."""
    import numpy as np
    from PIL import Image

    w, h = base.size
    fx = (focus[0] if focus else 0.5) * w
    fy = (focus[1] if focus else 0.45) * h
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - fx) ** 2 + (yy - fy) ** 2)
    d /= (d.max() + 1e-6)                       # 0 at focus -> 1 at the far corner
    arr = np.asarray(base.convert("RGB"), dtype=np.float32)
    if spotlight > 0:
        arr *= (1.0 + spotlight * (1.0 - d) ** 2)[..., None]
    if vignette > 0:
        arr *= (1.0 - vignette * (d ** 1.5))[..., None]
    return Image.fromarray(arr.clip(0, 255).astype("uint8"))


def build_thumbnail(
    text: str = "FULL GAME",
    out_path=None,
    image: Optional[str] = None,
    game_logo: Optional[str] = None,
    badge_lines: Sequence[str] = ("4K", "HDR"),
    box_fill: tuple = (214, 18, 18),     # YouTube-red "FULL GAME" box
    font_path: Optional[str] = None,     # override the headline font
    focus: Optional[tuple] = None,       # subject point (fx, fy in 0..1); None = auto
    zoom: float = 1.0,                   # >1 crops toward the subject (emotion face-zoom)
    sharpen: float = 0.0,                # extra crispening for soft footage frames (0..1)
    crop_bottom: float = 0.0,            # trim this fraction off the source bottom (copyright strip)
) -> Path:
    """Render the 1280x720 thumbnail: cover-cropped + punchier game image, a dark
    4K/HDR badge top-right, the game logo top-left (if given), and a bold red box
    with `text` (default FULL GAME) bottom-left. Saves JPEG."""
    from PIL import Image, ImageDraw, ImageEnhance

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = (Image.open(image).convert("RGB") if image and Path(image).exists()
            else Image.new("RGB", (W, H), (15, 16, 32)))
    if float(crop_bottom) > 0:            # trim the copyright strip off pool stills
        bw, bh = base.size
        base = base.crop((0, 0, bw, int(bh * (1 - min(0.15, float(crop_bottom))))))
    bw, bh = base.size
    s = max(W / bw, H / bh)
    base = base.resize((max(W, int(bw * s)), max(H, int(bh * s))), Image.LANCZOS)
    bw, bh = base.size
    base = base.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))

    # Emotion face-zoom: crop tighter TOWARD the subject, then scale back up.
    z = max(1.0, min(2.2, float(zoom)))
    if z > 1.01:
        fpt = focus or (0.5, 0.45)
        cw, ch = int(W / z), int(H / z)
        cx = int(min(W - cw, max(0, fpt[0] * W - cw / 2)))
        cy = int(min(H - ch, max(0, fpt[1] * H - ch / 2)))
        base = base.crop((cx, cy, cx + cw, cy + ch)).resize((W, H), Image.LANCZOS)

    # Crispen soft footage frames (curated stills don't need it; skip for them).
    if float(sharpen) > 0:
        from PIL import ImageFilter
        base = base.filter(ImageFilter.UnsharpMask(
            radius=2.2, percent=int(90 * float(sharpen)), threshold=2))

    # Attention grade (config-tunable via reels.thumbnail.*): pop the image so it
    # stops the scroll — vibrance + contrast + a touch brighter + clarity — then a
    # VIGNETTE (darken the edges) so the eye is pulled to the centre/subject.
    g = _CFG()
    base = ImageEnhance.Color(base).enhance(float(g.get("vibrance", 1.35)))
    base = ImageEnhance.Contrast(base).enhance(float(g.get("contrast", 1.16)))
    base = ImageEnhance.Brightness(base).enhance(float(g.get("brightness", 1.04)))
    base = ImageEnhance.Sharpness(base).enhance(float(g.get("clarity", 1.6)))
    if float(g.get("bloom", 0.45)) > 0:
        base = _bloom(base, float(g.get("bloom", 0.45)))
    try:
        if focus is None and float(g.get("auto_focus", 1)):
            focus = _auto_focus(base)
    except Exception:
        focus = None
    base = _focus_grade(base, focus,
                        max(0.0, min(0.9, float(g.get("vignette", 0.38)))),
                        max(0.0, float(g.get("spotlight", 0.18))))
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


def curated_candidates(game: str) -> list[Path]:
    """Curated still images available locally for a game (+ 'general') — sharper and
    cleaner than footage frames, so preferred for thumbnails when a suitable one
    exists. The cloud image pool is added separately by the caller."""
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    out: list[Path] = []
    for g in (game or "", "general"):
        d = ROOT / "assets/images" / g
        if g and d.is_dir():
            out += sorted(p for p in d.iterdir() if p.suffix.lower() in exts)
    return out


def build_variants(out_dir, specs: Sequence[dict]) -> list[Path]:
    """Render several thumbnail variants for YouTube's A/B 'Test & Compare'. Each
    spec is a dict of build_thumbnail kwargs (text/image/box_fill/focus/zoom/...).
    Returns the variant_N.jpg paths (upload 2-3 to Studio; it serves the CTR winner)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, spec in enumerate(specs, 1):
        p = out_dir / f"variant_{i}.jpg"
        build_thumbnail(out_path=p, **spec)
        paths.append(p)
    return paths
