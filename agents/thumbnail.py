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


def _saliency(base):
    """Low-res saliency map (DETAIL + COLOUR, mild centre bias): characters/effects
    score high, flat backgrounds low. Returned as a 90x160 float array."""
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
    return score * np.clip(cbias, 0.3, 1.0)


def _subject(base) -> tuple[float, float, float]:
    """(fx, fy, span): subject centroid (0..1) + how much of the frame the salient
    subject spans (0..1, the larger of its width/height). A small span = a compact or
    far subject a thumbnail should zoom into; a large span = it already fills the
    frame, so leave it. Robust to a few hot pixels (10-90 pct bbox)."""
    import numpy as np

    score = _saliency(base)
    h, w = score.shape
    yy, xx = np.mgrid[0:h, 0:w]
    thr = np.quantile(score, 0.90)
    m = score >= thr
    fx = float(xx[m].mean()) / w
    fy = float(yy[m].mean()) / h
    strong = score >= max(float(thr), 0.5 * float(score.max()))
    if int(strong.sum()) >= 3:
        xs, ys = xx[strong], yy[strong]
        wf = (np.percentile(xs, 90) - np.percentile(xs, 10)) / w
        hf = (np.percentile(ys, 90) - np.percentile(ys, 10)) / h
        span = max(0.2, min(1.0, float(max(wf, hf))))
    else:
        span = 1.0
    return (min(0.85, max(0.15, fx)), min(0.8, max(0.2, fy)), span)


def _auto_focus(base) -> tuple[float, float]:
    """Best-effort subject point (fx, fy in 0..1) for the spotlight/vignette grade."""
    fx, fy, _ = _subject(base)
    return (fx, fy)


def _auto_compose(base) -> tuple[tuple[float, float], float]:
    """Analyze an (already cover-cropped 1280x720) image and DECIDE the CTR crop: the
    subject point + how hard to zoom toward it. A small/far subject is zoomed so it
    fills ~`auto_fill` of the frame; a subject that already fills gets ~no zoom. Focus
    is nudged slightly up so faces (usually upper) stay in frame."""
    g = _CFG()
    fx, fy, span = _subject(base)
    fy = max(0.2, fy - 0.04)
    fill = float(g.get("auto_fill", 0.82))
    zmin = float(g.get("auto_zoom_min", 1.0))
    zmax = float(g.get("auto_zoom_max", 1.7))
    zoom = max(zmin, min(zmax, fill / max(0.2, span)))
    return (fx, fy), zoom


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


def _place_shadowed(base, layer, xy, *, blur: float = 14.0, dark: float = 0.6,
                    offset: tuple = (0, 7)):
    """Composite an RGBA `layer` onto RGB `base` at xy over a soft drop shadow (a
    blurred dark silhouette from the layer's alpha) so it lifts off any background —
    the premium 'logo/box pops' look. Returns a new RGB image."""
    from PIL import Image, ImageFilter

    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.putalpha(layer.split()[-1].point(lambda v: int(v * dark)))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    canvas = base.convert("RGBA")
    canvas.alpha_composite(sh, (int(xy[0] + offset[0]), int(xy[1] + offset[1])))
    canvas.alpha_composite(layer, (int(xy[0]), int(xy[1])))
    return canvas.convert("RGB")


def _autocrop_alpha(img):
    """Trim fully-transparent borders so a character PNG scales by its real bounds."""
    bbox = img.split()[-1].getbbox()
    return img.crop(bbox) if bbox else img


def inspect_thumbnail(path, *, has_character: bool = False,
                      game_logo: Optional[str] = None) -> dict:
    """Heuristic QC (no AI, free): does the thumbnail meet the scroll-stopping bar?
    Returns {ok, score 0-1, issues[]}. Used to PICK the best variant + flag problems
    (the vision-based judge comes in Phase 2 when AI billing is back)."""
    import numpy as np
    from PIL import Image

    issues: list[str] = []
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im, dtype=np.float32)
    # 1) subject prominence: a composited character guarantees it; else measure span
    if not has_character:
        try:
            _, _, span = _subject(im)
            if span < 0.45:
                issues.append("subject not prominent (no character; small saliency)")
        except Exception:
            pass
    # 2) exposure + punch
    mean, std = float(arr.mean()), float(arr.std())
    if mean < 38:
        issues.append("too dark")
    elif mean > 226:
        issues.append("washed out / too bright")
    if std < 26:
        issues.append("low contrast (flat, not scroll-stopping)")
    # 3) logo transparency — a solid-background logo shows as an ugly box
    if game_logo and Path(str(game_logo)).exists():
        try:
            a = np.asarray(Image.open(str(game_logo)).convert("RGBA"))[:, :, 3]
            if float((a < 10).mean()) < 0.05:
                issues.append("game logo has no transparent background (shows a box)")
        except Exception:
            pass
    return {"ok": not issues, "score": round(max(0.0, 1.0 - 0.25 * len(issues)), 2),
            "issues": issues}


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
    auto_compose: Optional[bool] = None,  # analyze + auto-crop toward the subject (None = config default, on)
    character: Optional[str] = None,     # transparent character PNG composited big in the foreground
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
    auto = _CFG().get("auto_compose", True) if auto_compose is None else bool(auto_compose)
    if character and Path(str(character)).exists():
        auto = False   # the composited character is the subject; keep the bg a full scene
    bw, bh = base.size
    s = max(W / bw, H / bh)
    base = base.resize((max(W, int(bw * s)), max(H, int(bh * s))), Image.LANCZOS)
    bw, bh = base.size
    # Cover-crop to 1280x720. Normally centre; when auto-composing, slide the crop
    # window toward the subject so an off-centre character isn't chopped off.
    if auto and (bw > W or bh > H):
        sfx, sfy, _ = _subject(base)
        ox = int(min(bw - W, max(0, sfx * bw - W / 2)))
        oy = int(min(bh - H, max(0, sfy * bh - H / 2)))
    else:
        ox, oy = (bw - W) // 2, (bh - H) // 2
    base = base.crop((ox, oy, ox + W, oy + H))

    # Decide the crop: when auto-composing and the caller didn't force a zoom/focus,
    # analyze THIS frame and zoom toward the subject so it fills the thumbnail (small
    # or far subjects get pulled in; an already-full shot is left alone).
    if auto and focus is None and abs(float(zoom) - 1.0) < 1e-6:
        focus, zoom = _auto_compose(base)
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

    # PROMINENT foreground CHARACTER cutout (transparent PNG) — the #1 CTR lever.
    # Large, bottom-anchored on one side, so the other side stays clear for the logo
    # + headline box. Rendered UNDER the logo/badge/text (added below) so those stay
    # readable. Sits over the graded scene with a soft contact shadow to separate it.
    if character and Path(str(character)).exists():
        try:
            ch = _autocrop_alpha(Image.open(str(character)).convert("RGBA"))
            th = int(H * max(0.5, min(1.0, float(g.get("character_scale", 0.92)))))
            ch = ch.resize((max(1, int(ch.width * th / ch.height)), th), Image.LANCZOS)
            maxw = int(W * float(g.get("character_max_w", 0.72)))
            if ch.width > maxw:
                ch = ch.resize((maxw, max(1, int(ch.height * maxw / ch.width))), Image.LANCZOS)
            side = str(g.get("character_side", "right"))
            cx = (W - ch.width - 20) if side == "right" else 20
            cy = H - ch.height + int(H * 0.02)             # feet just past the bottom edge
            if float(g.get("character_shadow", 1)):
                base = _place_shadowed(base, ch, (cx, cy), blur=24, dark=0.5, offset=(0, 0))
            else:
                c = base.convert("RGBA"); c.alpha_composite(ch, (cx, cy)); base = c.convert("RGB")
            draw = ImageDraw.Draw(base)
        except Exception:
            pass

    # game logo, top-left (with a SUBTLE drop shadow so it reads on any background —
    # kept light so it never looks like a box behind a transparent logo)
    if game_logo and Path(game_logo).exists():
        try:
            lg = Image.open(game_logo).convert("RGBA")
            lh = int(g.get("logo_height", 168))
            lg = lg.resize((max(1, int(lg.width * (lh / lg.height))), lh), Image.LANCZOS)
            if float(g.get("logo_glow", 1)):
                base = _place_shadowed(base, lg, (44, 34),
                                       blur=float(g.get("logo_shadow_blur", 10)),
                                       dark=float(g.get("logo_shadow_dark", 0.42)), offset=(0, 4))
                draw = ImageDraw.Draw(base)   # base replaced -> refresh the draw handle
            else:
                base.paste(lg, (44, 34), lg)
        except Exception:
            pass

    # 4K / HDR badge, top-right: a SEMI-TRANSPARENT dark rounded box (image shows
    # through) with a crisp white outline + white lines — the MKIceAndFire look.
    blines = [str(x).upper() for x in (badge_lines or []) if str(x).strip()]
    if blines:
        bf = _font(60)
        line_w = max(_tsize(draw, l, bf)[0] for l in blines)
        line_h = int(60 * 1.18)
        padx, pady = 24, 14
        boxw, boxh = line_w + padx * 2, line_h * len(blines) + pady * 2
        x1, y0 = W - 32, 32
        x0 = x1 - boxw
        op = max(0.0, min(1.0, float(g.get("badge_opacity", 0.6))))
        blayer = Image.new("RGBA", (boxw + 8, boxh + 8), (0, 0, 0, 0))
        bd = ImageDraw.Draw(blayer)
        bd.rounded_rectangle([4, 4, 4 + boxw, 4 + boxh], radius=16,
                             fill=(0, 0, 0, int(255 * op)),
                             outline=(255, 255, 255, 255), width=4)
        cy = 4 + pady + line_h // 2
        for l in blines:
            bd.text((4 + boxw // 2, cy), l, font=bf, fill=(255, 255, 255, 255), anchor="mm")
            cy += line_h
        c = base.convert("RGBA")
        c.alpha_composite(blayer, (x0 - 4, y0 - 4))
        base = c.convert("RGB")
        draw = ImageDraw.Draw(base)   # base replaced -> refresh for the headline below

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
    bw2, bh2 = tw + padx * 2, th + pady * 2
    x0, y1 = 46, H - 46
    y0 = y1 - bh2
    # Render the box+text on its own transparent layer (pad 10px for the outline),
    # then drop it onto the image with a soft glow/shadow behind it (pop).
    layer = Image.new("RGBA", (bw2 + 20, bh2 + 20), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([10, 10, 10 + bw2, 10 + bh2], radius=16, fill=box_fill,
                         outline=(255, 255, 255), width=8)
    ld.text((10 + bw2 // 2, 10 + bh2 // 2), txt, font=f, fill=(255, 255, 255),
            anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
    if float(g.get("text_glow", 1)):
        base = _place_shadowed(base, layer, (x0 - 10, y0 - 10), blur=18, dark=0.75, offset=(0, 8))
    else:
        c = base.convert("RGBA")
        c.alpha_composite(layer, (x0 - 10, y0 - 10))
        base = c.convert("RGB")

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
