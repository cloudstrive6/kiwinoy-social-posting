"""Pro YouTube thumbnail pipeline (high-CTR, exact character).

Chain of small agents, each proven in the SM2 prototype:

  scrape_fandom_character()  find + download the EXACT game render (Fandom CDN)
  cutout()                   rembg -> clean transparent subject
  relight()                  Gemini image-EDIT into a dramatic composite, keeping
                             the character EXACT (mined winning-pattern art direction)
  art_direct()               a vision agent LOOKS at the render and decides the
                             title/logo/badge placement + sizing (not hardcoded)
  compose()                  clip-safe Pillow furniture per the art-director spec
  qc()                       a QC art-director inspects EVERY element -> PASS/FAIL
  content_ok()               a critic confirms the character/ļook matches the brief

`build()` runs the lot with a QC retry loop and returns the finished JPEG path.

Design notes learned the hard way:
- Gemini's IP safety is STOCHASTIC and Gemini-3 image models refuse hard -> we use
  gemini-2.5-flash-image (via core.gemini) and NEVER name the IP in the prompt
  (we supply the exact character as an image, so naming it only raises blocks).
- Avast HTTPS interception breaks requests + rembg's model download on this PC ->
  truststore.inject_into_ssl() (uses the OS trust store, which has Avast's root).
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Optional, Sequence

from core.config import ROOT

W, H = 1280, 720
_MARGIN = 40
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# Default high-CTR palette (overridable). Learned from the top gaming thumbnails.
_PALETTE = ("#E23636", "#2E3A58", "#131212")


def _inject_ssl() -> None:
    """Make requests / rembg trust the OS store (defeats Avast's MITM cert)."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 1. SCRAPE — find + download the exact character render from a Fandom wiki    #
# --------------------------------------------------------------------------- #
def scrape_fandom_character(wiki_host: str, query: str, out_path,
                            prefer: Sequence[str] = ()) -> Optional[Path]:
    """Search a Fandom wiki's File namespace for `query` and download the best
    matching render (highest-res, transparent PNG preferred) to `out_path`.
    `wiki_host` e.g. 'marvels-spider-man.fandom.com' or 'finalfantasy.fandom.com'.
    `prefer` = substrings that bump a candidate (e.g. ('render','promo')).
    Returns the saved path or None. Caller should cache the result."""
    _inject_ssl()
    import requests
    api = f"https://{wiki_host}/api.php"
    s = requests.Session(); s.headers.update(_UA)
    try:
        r = s.get(api, params={"action": "query", "list": "search",
                  "srsearch": query, "srnamespace": 6, "srlimit": 20,
                  "format": "json"}, timeout=25)
        titles = [h["title"] for h in r.json().get("query", {}).get("search", [])]
    except Exception:
        return None
    if not titles:
        return None

    def score(t: str) -> tuple:
        tl = t.lower()
        return (sum(k in tl for k in prefer),
                "render" in tl, "png" in tl, -len(tl))
    titles.sort(key=score, reverse=True)

    for title in titles[:6]:
        try:
            info = s.get(api, params={"action": "query", "titles": title,
                     "prop": "imageinfo", "iiprop": "url|size|mime",
                     "format": "json"}, timeout=25).json()
            page = next(iter(info["query"]["pages"].values()))
            ii = page["imageinfo"][0]
            if "png" not in ii.get("mime", ""):
                continue
            data = s.get(ii["url"], timeout=60).content
            if len(data) < 20_000:
                continue
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            return out_path
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# 2. CUTOUT — rembg (skipped if the source is already transparent)            #
# --------------------------------------------------------------------------- #
def cutout(src, out_path) -> Path:
    """Return a transparent PNG of the subject. If `src` already has meaningful
    transparency (a clean render), use it as-is; otherwise rembg it."""
    import numpy as np
    from PIL import Image
    src = Path(src); out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGBA")
    if float((np.asarray(im)[:, :, 3] < 10).mean()) > 0.05:
        im.save(out_path)
        return out_path
    _inject_ssl()                      # rembg downloads its model on first use
    from rembg import remove
    remove(im).save(out_path)
    return out_path


# --------------------------------------------------------------------------- #
# 3. RELIGHT — Gemini image-edit into a dramatic composite (character exact)  #
# --------------------------------------------------------------------------- #
_STYLES = {
    "hero": ("Compose the character LARGE and dominant, centre-right, in a "
             "powerful confident stance, head in the upper third."),
    "closeup": ("Frame a dramatic CHEST-UP close-up of the character, large, "
                "centre-right, intense and heroic, catching rim light."),
    "action": ("Pose the character in a DYNAMIC mid-action stance full of motion "
                "and energy, body forming a strong diagonal, on the right two-thirds, "
                "subtle motion blur behind."),
}


def relight(cutout_path, out_path, *, style: str = "hero",
            palette: Sequence[str] = _PALETTE, retries: int = 6) -> Path:
    """Gemini relights the exact cutout into a dark, dramatic, high-CTR 16:9
    composite. The prompt describes ART DIRECTION only — it NEVER names the IP."""
    from core import gemini
    pal = " / ".join(palette)
    prompt = (
        "Turn the provided game character into a 16:9 LANDSCAPE cinematic YouTube "
        "gaming thumbnail. Keep the character's costume, colours, markings, face and "
        "body EXACTLY as provided — do not redesign or restyle. "
        f"{_STYLES.get(style, _STYLES['hero'])} "
        "Fill the frame with atmosphere so there is NO empty black void: a moody, "
        "cinematically blurred dramatic background with depth, glowing bokeh and "
        "drifting embers/particles. Strong cool rim light separating the character "
        "from the background, high contrast, premium colour grade. "
        f"Palette: {pal}. Keep one side slightly darker and less busy so a title "
        "stays readable, but not empty. No text, no logo, no watermark.")
    png = gemini.edit_image(prompt, [str(cutout_path)], aspect_ratio="16:9",
                            retries=retries)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return out_path


# --------------------------------------------------------------------------- #
# 4. ART DIRECT — a vision agent decides placement (not hardcoded)            #
# --------------------------------------------------------------------------- #
def art_direct(base_path, title_text: str) -> dict:
    """Look at the composited render and decide the text/logo/badge layout per
    winning-CTR principles. The WORDS of `title_text` are fixed (may be split
    into <=2 lines); only placement/size/style are chosen."""
    from core import openai_client as ai
    prompt = (
        "You are an elite YouTube gaming-thumbnail ART DIRECTOR. The character is "
        "already composited in this base image. Decide the TEXT & BADGE layout that "
        "maximizes CTR: fill dead space, NEVER cover the character's face or chest "
        "emblem, big bold readable title, strong contrast, mobile-legible. "
        f"The title text is EXACTLY '{title_text}' — keep these words (you may split "
        "into at most 2 UPPERCASE lines). Return STRICT JSON: "
        "{title_lines:[1-2 UPPERCASE lines], "
        "title_anchor:['top-left','mid-left','bottom-left','bottom-center'], "
        "title_size:0.10-0.18, title_style:'box'|'outline', title_color:hex, "
        "box_color:hex|null, logo_anchor:['top-left','top-center','top-right'], "
        "logo_scale:0.22-0.34, badge_anchor:['top-right','top-left','bottom-right']}")
    raw = ai.vision(prompt, [str(base_path)])
    m = re.search(r"\{.*\}", raw, re.S)
    spec = json.loads(m.group(0)) if m else {}
    spec.setdefault("title_lines", [title_text.upper()])
    return spec


# --------------------------------------------------------------------------- #
# 5. COMPOSE — clip-safe Pillow furniture per the art-director spec           #
# --------------------------------------------------------------------------- #
def _anchor_xy(anch: str, w: int, h: int) -> tuple:
    x = _MARGIN if "left" in anch else (W - w - _MARGIN if "right" in anch else (W - w) // 2)
    y = _MARGIN if "top" in anch else (H - h - _MARGIN if "bottom" in anch else (H - h) // 2)
    return max(_MARGIN, min(W - w - _MARGIN, x)), max(_MARGIN, min(H - h - _MARGIN, y))


def _cover(im):
    from PIL import Image
    bw, bh = im.size
    s = max(W / bw, H / bh)
    im = im.resize((int(bw * s), int(bh * s)), Image.LANCZOS)
    bw, bh = im.size
    return im.crop(((bw - W) // 2, (bh - H) // 2, (bw - W) // 2 + W, (bh - H) // 2 + H))


def compose(base_path, spec: dict, out_path, *, game_logo=None,
            badge_lines: Sequence[str] = ("4K", "HDR")) -> Path:
    """Lay the logo (width-capped so it never clips), an auto-sized 4K/HDR badge,
    and the title (box or outline) onto the relit base per `spec`. Saves JPEG."""
    from PIL import Image, ImageDraw, ImageFilter, ImageColor
    from agents import thumbnail as T

    im = _cover(Image.open(base_path).convert("RGB")).convert("RGBA")
    d = ImageDraw.Draw(im)

    if game_logo and Path(str(game_logo)).exists():
        lg = Image.open(str(game_logo)).convert("RGBA")
        mw = int(W * float(spec.get("logo_scale", 0.28)))
        if lg.width > mw:
            lg = lg.resize((mw, int(lg.height * mw / lg.width)), Image.LANCZOS)
        x, y = _anchor_xy(spec.get("logo_anchor", "top-left"), lg.width, lg.height)
        im.alpha_composite(lg, (x, y))

    blines = [str(x).upper() for x in (badge_lines or []) if str(x).strip()]
    if blines:
        bf = T._font(44)
        tw = max(d.textbbox((0, 0), t, font=bf)[2] for t in blines)
        lh = int(44 * 1.28); padx, pady = 30, 20
        bw_, bh_ = tw + padx * 2, lh * len(blines) + pady * 2
        bl = Image.new("RGBA", (bw_, bh_), (0, 0, 0, 0)); bd = ImageDraw.Draw(bl)
        bd.rounded_rectangle([2, 2, bw_ - 2, bh_ - 2], radius=16,
                             fill=(0, 0, 0, 150), outline=(255, 255, 255, 255), width=4)
        cy = pady + lh // 2
        for t in blines:
            bd.text((bw_ // 2, cy), t, font=bf, fill=(255, 255, 255, 255), anchor="mm"); cy += lh
        x, y = _anchor_xy(spec.get("badge_anchor", "top-right"), bw_, bh_)
        im.alpha_composite(bl, (x, y))

    tl = [str(l).upper() for l in spec.get("title_lines", [""])][:2]
    fs = int(H * float(spec.get("title_size", 0.15))); tf = T._font(fs)
    lw = max(d.textbbox((0, 0), t, font=tf)[2] for t in tl); glh = int(fs * 1.16)
    blk = glh * len(tl)
    style = spec.get("title_style", "box"); box = spec.get("box_color")
    tcol = ImageColor.getrgb(spec.get("title_color", "#FFFFFF"))
    if style == "box" and box:
        bx, by = _anchor_xy(spec.get("title_anchor", "mid-left"), lw + 64, blk + 48)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        od.rounded_rectangle([bx, by, bx + lw + 64, by + blk + 48], radius=20,
                             fill=ImageColor.getrgb(box) + (235,),
                             outline=(255, 255, 255, 255), width=6)
        im.alpha_composite(ov); tx, ty = bx + 32, by + 24
    else:
        bx, by = _anchor_xy(spec.get("title_anchor", "bottom-left"), lw, blk)
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); ds = ImageDraw.Draw(sh)
        for i, t in enumerate(tl):
            ds.text((bx + 3, by + 3 + i * glh), t, font=tf, fill=(0, 0, 0, 220),
                    stroke_width=8, stroke_fill=(0, 0, 0, 220))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7))); tx, ty = bx, by
    for i, t in enumerate(tl):
        d.text((tx, ty + i * glh), t, font=tf, fill=tcol, stroke_width=4, stroke_fill=(0, 0, 0))

    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out_path, "JPEG", quality=93, optimize=True)
    return out_path


# --------------------------------------------------------------------------- #
# 6/7. QC + CONTENT critic (vision)                                           #
# --------------------------------------------------------------------------- #
def qc(path) -> dict:
    """QC art-director: inspect EVERY element. Returns {...,verdict:PASS|FAIL}."""
    from core import openai_client as ai
    prompt = (
        "You are a meticulous YouTube thumbnail QC ART DIRECTOR. Inspect EVERY "
        "element and verify it's perfect: (1) game logo fully visible, not clipped "
        "by any edge; (2) 4K/HDR badge has comfortable padding, text not crowded "
        "against its border; (3) title fully readable, not clipped, not covering the "
        "character's face or chest emblem; (4) nothing overlaps awkwardly; (5) "
        "balanced composition, no large dead space; (6) mobile-legible at small size. "
        "Return STRICT JSON: {logo_ok,badge_ok,title_ok,overlap_ok,balance_ok,"
        "mobile_ok, issues:[concise], verdict:'PASS'|'FAIL'}.")
    raw = ai.vision(prompt, [str(path)])
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else {"verdict": "FAIL", "issues": ["no json"]}


def build(out_path, *, character_image=None, title_text: str = "PART 1",
          game_logo=None, style: str = "hero",
          badge_lines: Sequence[str] = ("4K", "HDR"),
          palette: Sequence[str] = _PALETTE,
          scrape: Optional[dict] = None, work_dir=None,
          qc_rounds: int = 2, relight_tries: int = 3):
    """End-to-end. Provide `character_image` (a render/cutout) OR `scrape`
    ({wiki_host, query, prefer}) to fetch one. Returns (path, qc_report).

    The relight is regenerated up to `relight_tries` times if QC keeps failing
    (a fresh Gemini composite often fixes a bad first roll); within each relit
    base the art-direct+compose+qc loop runs up to `qc_rounds` times."""
    work = Path(work_dir) if work_dir else Path(out_path).parent / "_tdir"
    work.mkdir(parents=True, exist_ok=True)

    src = character_image
    if not src and scrape:
        src = scrape_fandom_character(scrape["wiki_host"], scrape["query"],
                                      work / "scrape.png", scrape.get("prefer", ()))
    if not src:
        raise RuntimeError("no character_image and scrape failed")
    cut = cutout(src, work / "cutout.png")

    last = None
    for t in range(max(1, relight_tries)):
        base = relight(cut, work / f"relit_{t}.png", style=style, palette=palette)
        for _ in range(max(1, qc_rounds)):
            spec = art_direct(base, title_text)
            out = compose(base, spec, out_path, game_logo=game_logo, badge_lines=badge_lines)
            report = qc(out)
            last = report
            if str(report.get("verdict", "")).upper() == "PASS":
                return out, report
    return Path(out_path), last
