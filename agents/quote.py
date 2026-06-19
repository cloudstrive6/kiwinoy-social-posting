"""Motivational gaming quotes — text for Threads/X, and a designed quote CARD
(quote overlaid on a gameplay photo) for Facebook.

Quotes are ORIGINAL one-liners (no copyrighted lines from real games/people) so
they're always safe to post. The card is rendered with Pillow (no Remotion, so
it's safe to run locally too).
"""
from __future__ import annotations

import glob
import random
from pathlib import Path
from typing import Optional

from core import writer as ai
from core.config import CONFIG, ROOT
from core.dedup import avoid_block
from core.style import HUMAN_VOICE, sanitize

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Premium typeface for the quote cards: prefer Montserrat (geometric, high-end
# feel), then other clean fonts, then DejaVu (cloud default) / Windows (local).
# The cloud workflow apt-installs fonts-montserrat so production is consistent.
_FONT_GLOBS = [
    "/usr/share/fonts/**/Montserrat-{w}.ttf",
    "/usr/share/fonts/**/Poppins-{w}.ttf",
    "/usr/share/fonts/**/OpenSans-{w}.ttf",
    "/usr/share/fonts/**/Roboto-{w}.ttf",
    "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
]
_FONT_WIN = {
    "Bold": ["C:/Windows/Fonts/Bahnschrift.ttf", "C:/Windows/Fonts/seguisb.ttf",
             "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "SemiBold": ["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/Bahnschrift.ttf",
                 "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"],
}


def _font(size: int, weight: str = "Bold"):
    from PIL import ImageFont
    cands: list[str] = []
    for g in _FONT_GLOBS:
        cands += sorted(glob.glob(g.format(w=weight), recursive=True))
    cands += _FONT_WIN.get(weight, _FONT_WIN["Bold"])
    for p in cands:
        if p and Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _circular_logo(src, size: int):
    """The SAME circular logo treatment as the reels (centre-crop -> circle)."""
    from PIL import Image, ImageChops, ImageDraw
    im = Image.open(src).convert("RGBA")
    iw, ih = im.size
    s = min(iw, ih)
    im = im.crop(((iw - s) // 2, (ih - s) // 2, (iw - s) // 2 + s, (ih - s) // 2 + s))
    im = im.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    return im


def _vignette(img, strength: int = 150):
    """Darken the edges (cinematic focus) via a blurred radial mask."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse(
        [int(-w * 0.22), int(-h * 0.16), int(w * 1.22), int(h * 1.16)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(w, h) // 6))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.putalpha(mask.point(lambda v: int((255 - v) * strength / 255)))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _vgrad(img, top: int = 60, bottom: int = 200):
    """Vertical dark gradient (lighter top -> darker bottom) for depth + text."""
    from PIL import Image
    w, h = img.size
    grad = Image.new("L", (1, h))
    for y in range(h):
        grad.putpixel((0, y), int(top + (bottom - top) * (y / h)))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.putalpha(grad.resize((w, h)))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
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
    return lines


def _system() -> str:
    b = CONFIG.brand
    return (
        f"You are the motivational-content writer for {b['name']} ({b['handle']}), "
        f"a gaming channel. You write original, punchy, genuinely inspiring quotes "
        f"about gaming + life.\n\n{HUMAN_VOICE}"
    )


def generate(extra_avoid: Optional[list[str]] = None, theme: str = "gameplay") -> str:
    """Return ONE original English motivational quote (no attribution). theme
    'gameplay' uses a gaming metaphor; 'life' is general life motivation (no
    gaming references) so the page mixes both kinds of inspiration."""
    avoid = avoid_block()
    if theme == "life":
        prompt = f"""Write ONE original, scroll-stopping MOTIVATIONAL quote about LIFE in general.

Like a shareable quote-card line about growth, resilience, discipline, self-belief,
showing up, perseverance, purpose, or making the most of today. This one is NOT
about gaming — do NOT use any gaming words or metaphors.

Rules:
- Genuinely inspiring, not cheesy or corny. Confident, a little bold.
- ENGLISH. 6 to 18 words. One line (one sentence, or two very short ones).
- FULLY ORIGINAL: do NOT quote or paraphrase real people, books, movies, or any
  known quote. Invent it.
- No hashtags, no emojis, no quotation marks, no author/attribution. Just the line.

{avoid}

Return ONLY the quote line."""
        fallback = "Small steps taken daily still outrun standing still."
    else:
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
        fallback = "Every pro was once a beginner who refused to hit quit."
    raw = ai.write(prompt, system=_system())
    line = sanitize(raw).strip().strip('"').splitlines()[0].strip().strip('"')
    return line[:160] or fallback


def elaborate(quote_line: str, theme: str = "gameplay") -> str:
    """A SHORT (1-2 sentence) relatable elaboration of the quote, for the post
    caption. Does NOT repeat the quote — it expands on it. theme matches the quote
    ('gameplay' = gamer angle; 'life' = everyday-life angle, no gaming refs)."""
    if theme == "life":
        angle = ("a relatable, real-talk angle about everyday life (the early "
                 "mornings, the quiet setbacks, the showing-up again, the small "
                 "wins that add up) — NO gaming references")
        fallback = "Keep showing up - the small wins always add up."
    else:
        angle = ("a relatable, real-talk gamer angle (the late-night grind, the "
                 "boss that wrecked you, the clutch comeback, the squad that "
                 "carried you)")
        fallback = "Keep going - the grind always pays off eventually."
    prompt = f"""A motivational quote card shows this line: "{quote_line}"

Write the post CAPTION that goes under it. Do NOT repeat or rephrase the quote.
Instead expand on it in 1 to 2 short sentences with {angle} so it actually hits
home. Warm and motivating, a little personal.

No hashtags, no emojis, no quotation marks, no preamble. Return ONLY the caption."""
    raw = ai.write(prompt, system=_system())
    line = sanitize(raw).strip().strip('"').strip()
    return line[:400] or fallback


def threads_text(theme: Optional[str] = None) -> str:
    """A motivational quote for a Threads/X TEXT post — just the quote, NO hashtags
    (per user; Threads/X never get hashtags). theme defaults to a random mix of
    gameplay + life so the text track gets both kinds of inspiration too."""
    if theme is None:
        theme = random.choice(["gameplay", "life"])
    return generate(theme=theme)


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


def _vision_best(photos: list[Path], quote: str) -> Optional[Path]:
    """Use Claude vision to pick the most CINEMATIC/emotional backdrop for the
    quote, avoiding title/menu/UI/loading/copyright screens. None on failure."""
    import re
    cand = photos[:8]
    try:
        from core import claude_code
        listing = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(cand))
        prompt = (
            f"Use the Read tool to open these {len(cand)} candidate photos. Pick the "
            f"ONE that works best as the backdrop for a motivational gaming quote "
            f'card (quote: "{quote}"). Prefer a CINEMATIC, emotional, visually '
            f"striking in-game moment. STRONGLY AVOID title screens, main menus, "
            f"loading/pause screens, heavy HUD/UI, or anything with watermark or "
            f"copyright text. Reply with ONLY the number of your pick.\n\n{listing}"
        )
        raw = claude_code.run(prompt, allowed_tools="Read", timeout=150)
        m = re.search(r"\d+", raw or "")
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(cand):
                return cand[idx]
    except Exception:
        pass
    return None


def _cache_dir() -> Path:
    d = ROOT / "output" / ".quote_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pick_photo(quote: Optional[str] = None) -> Optional[Path]:
    """Pick a backdrop from the CLOUD quote-image pool (the Release manifest),
    cycling through ALL images before repeating, in random order. Claude vision
    picks the most cinematic of a few candidates. Falls back to local committed
    images if the cloud pool isn't available (dev / pre-sync)."""
    from core import gh_release
    qcfg = CONFIG.raw().get("quotes", {}) or {}
    pool = gh_release.quote_image_pool()
    if pool:
        chosen = _pick_release(pool, quote, qcfg)
        if chosen:
            return chosen
    photos = _candidate_photos()      # local fallback
    if not photos:
        return None
    fresh = [p for p in photos if p.name not in _recent_photos()] or photos
    if quote and len(fresh) > 1 and qcfg.get("vision_pick", True):
        best = _vision_best(fresh, quote)
        if best:
            _remember_photo(best.name)
            return best
    pick = random.choice(fresh)
    _remember_photo(pick.name)
    return pick


def _pick_release(pool: dict, quote, qcfg) -> Optional[Path]:
    from core import gh_release
    # Quotes are generic, so use ALL games' images (minus excluded), cycling
    # through every image before repeating (per user) — not just the prefer list.
    exclude = {str(g).lower() for g in (qcfg.get("exclude", []) or [])}
    games = [g for g in pool if g.lower() not in exclude] or list(pool)
    names = [n for g in games for n in (pool.get(g, []) or [])]
    if not names:
        return None
    used = gh_release.used_quote_images()
    fresh = [n for n in names if n not in used]
    if not fresh:                     # every backdrop shown -> restart the cycle
        gh_release.reset_quote_images()
        fresh = names[:]
    random.shuffle(fresh)
    cands: list[tuple[str, Path]] = []
    for name in fresh[:8]:
        p = gh_release.download(
            {"name": name, "url": gh_release.asset_download_url(name)}, _cache_dir())
        if p:
            cands.append((name, p))
    if not cands:
        return None
    chosen = None
    if quote and len(cands) > 1 and qcfg.get("vision_pick", True):
        best = _vision_best([p for _, p in cands], quote)
        chosen = next(((n, p) for n, p in cands if p == best), None)
    chosen = chosen or random.choice(cands)
    gh_release.mark_quote_image(chosen[0])
    return chosen[1]


def pick_music() -> "tuple[Optional[Path], float]":
    """A quote-music track from the Release (qmusic) + a randomised MID-TRACK
    start offset (the climax). Returns (local_path, start_seconds) or (None, 0)."""
    from core import gh_release, ffmpeg
    pool = gh_release.quote_music_pool()
    if not pool:
        return None, 0.0
    name = random.choice(pool)
    p = gh_release.download(
        {"name": name, "url": gh_release.asset_download_url(name)}, _cache_dir())
    if not p:
        return None, 0.0
    d = ffmpeg.duration(p) or 0.0
    qcfg = CONFIG.raw().get("quotes", {}) or {}
    lo = float(qcfg.get("music_start_min", 0.30))
    hi = float(qcfg.get("music_start_max", 0.65))
    start = random.uniform(lo, hi) * d if d > 0 else 0.0
    return p, max(0.0, start)


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
    """Render a PREMIUM quote card: the gameplay photo cinematically graded +
    vignetted as a backdrop, the quote in a high-quality typeface, a brand-red
    accent, and the CIRCULAR KG logo + @handle. Returns the PNG path."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg = Image.open(photo_path).convert("RGB")
    # cover-crop to w x h
    bw, bh = bg.size
    scale = max(w / bw, h / bh)
    bg = bg.resize((int(bw * scale + 1), int(bh * scale + 1)), Image.LANCZOS)
    bw, bh = bg.size
    bg = bg.crop(((bw - w) // 2, (bh - h) // 2, (bw - w) // 2 + w, (bh - h) // 2 + h))

    # CINEMATIC grade for emotion: richer colour + contrast, a touch darker, soft
    # focus, a vignette for the eye, and a top->bottom darkening gradient.
    bg = ImageEnhance.Color(bg).enhance(1.18)
    bg = ImageEnhance.Contrast(bg).enhance(1.12)
    bg = ImageEnhance.Brightness(bg).enhance(0.94)
    bg = bg.filter(ImageFilter.GaussianBlur(1.3))
    bg = _vignette(bg.convert("RGBA"), 150)
    bg = _vgrad(bg, 55, 195)
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))  # subtle legibility band
    ImageDraw.Draw(panel).rectangle([0, int(h * 0.30), w, int(h * 0.73)], fill=(0, 0, 0, 60))
    bg = Image.alpha_composite(bg, panel)

    _draw_quote_content(bg, quote, logo, w, h)
    bg.convert("RGB").save(out_path, "PNG")
    _remember_photo(Path(photo_path).name)
    return out_path


def _draw_quote_content(bg, quote: str, logo, w: int, h: int, strong_shadow: bool = False,
                        center_y: Optional[int] = None, sizes=None,
                        band_frac: float = 0.40, quote_mark_size: int = 170):
    """Draw the quote mark + quote + red accent + circular logo + @handle onto the
    given RGBA image (centred). Shared by the card and the YouTube-Short text layer.
    strong_shadow adds an outline for legibility over moving video. center_y / sizes
    let the Short use a smaller font placed higher (the card keeps the defaults)."""
    from PIL import ImageDraw
    draw = ImageDraw.Draw(bg)
    red = (229, 9, 20, 255)
    max_w = w - 2 * 108
    if center_y is None:
        center_y = h // 2
    if sizes is None:
        sizes = (104, 96, 88, 80, 72, 64, 58)

    # Fit the quote: shrink the premium font until it wraps within the text band.
    size, font, lines, line_h = sizes[0], _font(sizes[0], "Bold"), [], int(sizes[0] * 1.24)
    for size in sizes:
        font = _font(size, "Bold")
        lines = _wrap(draw, quote, font, max_w)
        line_h = int(size * 1.24)
        if line_h * len(lines) <= int(h * band_frac) and len(lines) <= 7:
            break
    total_h = line_h * len(lines)
    top = center_y - total_h // 2

    qf = _font(quote_mark_size, "Bold")
    qw = draw.textlength("“", font=qf)
    draw.text(((w - qw) // 2, top - int(quote_mark_size * 1.2)), "“", font=qf, fill=red)

    y = top + 8
    for ln in lines:
        x = (w - draw.textlength(ln, font=font)) // 2
        if strong_shadow:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                draw.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0, 190))
        draw.text((x + 3, y + 4), ln, font=font, fill=(0, 0, 0, 170))
        draw.text((x, y), ln, font=font, fill=(255, 255, 255, 255))
        y += line_h

    cx = w // 2
    draw.rectangle([cx - 64, y + 22, cx + 64, y + 29], fill=red)

    handle = str(CONFIG.brand.get("handle", "@kiwinoygaming"))
    hfont = _font(40, "SemiBold")
    hw = draw.textlength(handle, font=hfont)
    if logo and Path(logo).exists():
        try:
            bg.alpha_composite(_circular_logo(logo, 104), ((w - 104) // 2, h - 220))
        except Exception:
            pass
    draw.text(((w - hw) // 2, h - 98), handle, font=hfont, fill=(240, 240, 240, 255))


def render_text_layer(quote: str, out_path: Path, logo: Optional[Path] = None,
                      w: int = 1080, h: int = 1920) -> Path:
    """Transparent overlay PNG for the YouTube quote SHORT (9:16): a soft dark
    legibility veil + the SAME quote typography as the card. Overlaid on graded
    gameplay b-roll by reel_ffmpeg.build_quote_short."""
    from PIL import Image, ImageDraw
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # The quote sits HIGHER (upper-middle) and a touch SMALLER than the card, so it
    # reads as a tidy block in the top third rather than sprawling down the centre.
    center_y = int(h * 0.34)
    bg = _vignette(Image.new("RGBA", (w, h), (0, 0, 0, 0)), 120)
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rectangle([0, int(h * 0.12), w, int(h * 0.56)], fill=(0, 0, 0, 95))
    bg = Image.alpha_composite(bg, panel)
    _draw_quote_content(bg, quote, logo, w, h, strong_shadow=True,
                        center_y=center_y, sizes=(78, 70, 62, 56, 50, 46, 42),
                        band_frac=0.34, quote_mark_size=124)
    bg.save(out_path, "PNG")
    return out_path
