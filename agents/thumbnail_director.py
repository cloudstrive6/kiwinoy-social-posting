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
def _subject_side(base_path) -> tuple:
    """(fx, free_side): the subject's horizontal centroid (0..1) and which HALF is
    free for text ('left' or 'right')."""
    from PIL import Image
    from agents import thumbnail as T
    try:
        fx, _, _ = T._subject(Image.open(base_path).convert("RGB"))
    except Exception:
        fx = 0.6
    return fx, ("left" if fx >= 0.5 else "right")


def art_direct(base_path, title_text: str, *, free_side: str = "left",
               prior_issues: Optional[Sequence[str]] = None) -> dict:
    """Look at the composited render and decide the text/logo/badge layout per
    winning-CTR principles. The WORDS of `title_text` are fixed (may be split
    into <=2 lines); only placement/size/style are chosen. `free_side` is the
    empty half where text belongs; `prior_issues` are the previous QC failures to
    FIX this round (feedback loop)."""
    from core import openai_client as ai
    side_anchors = (["top-left", "mid-left", "bottom-left"] if free_side == "left"
                    else ["top-right", "mid-right", "bottom-right"])
    logo_corner = "top-left" if free_side == "left" else "top-right"
    badge_corner = "top-right" if free_side == "left" else "top-left"
    fix = ("\nThe PREVIOUS attempt FAILED QC for these reasons — FIX them all: "
           + "; ".join(prior_issues)) if prior_issues else ""
    prompt = (
        "You are an elite YouTube gaming-thumbnail ART DIRECTOR. The character is "
        f"already composited in this base image, occupying the {'RIGHT' if free_side=='left' else 'LEFT'} "
        f"side. ALL text/badge/logo must go on the FREE ({free_side.upper()}) side and in the "
        "corners — NEVER over the character's face or chest. Maximize CTR: fill the dead "
        "space with a big bold readable title, strong contrast, mobile-legible. "
        f"The title text is EXACTLY '{title_text}' — keep these words (you may split into at "
        "most 2 UPPERCASE lines). Return STRICT JSON: {title_lines:[1-2 UPPERCASE lines], "
        f"title_anchor:one of {side_anchors}, title_size:0.12-0.17, "
        "title_style:'box'|'outline', title_color:hex, box_color:hex|null, "
        f"logo_anchor:'{logo_corner}', logo_scale:0.24-0.32, badge_anchor:'{badge_corner}'}}"
        + fix)
    raw = ai.vision(prompt, [str(base_path)])
    m = re.search(r"\{.*\}", raw, re.S)
    spec = json.loads(m.group(0)) if m else {}
    spec.setdefault("title_lines", [title_text.upper()])
    # Safety net: force text furniture onto the free side regardless of the model.
    if spec.get("title_anchor") not in side_anchors:
        spec["title_anchor"] = side_anchors[1]
    spec["logo_anchor"] = logo_corner
    spec["badge_anchor"] = badge_corner
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
        r_, g_, b_, a_ = lg.split()
        a_ = a_.point(lambda v: 0 if v < 24 else v)      # kill faint matte box
        lg = Image.merge("RGBA", (r_, g_, b_, a_))
        mw = int(W * float(spec.get("logo_scale", 0.28)))
        if lg.width > mw:
            lg = lg.resize((mw, int(lg.height * mw / lg.width)), Image.LANCZOS)
        x, y = _anchor_xy(spec.get("logo_anchor", "top-left"), lg.width, lg.height)
        # White outline behind the logo so a DARK logo (e.g. FF7) stays legible on
        # a dark background — trace the logo's own shape, no visible backing box.
        m = lg.split()[-1].filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(3))
        outline = Image.new("RGBA", lg.size, (255, 255, 255, 0)); outline.putalpha(m)
        for _ in range(2):
            im.alpha_composite(outline, (x, y))
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
    def _rgb(c, default):
        try:
            return ImageColor.getrgb(c)[:3]
        except Exception:
            return default
    style = spec.get("title_style", "box"); box = spec.get("box_color")
    tcol = _rgb(spec.get("title_color", "#FFFFFF"), (255, 255, 255))
    if style == "box" and box:
        bx, by = _anchor_xy(spec.get("title_anchor", "mid-left"), lw + 64, blk + 48)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        od.rounded_rectangle([bx, by, bx + lw + 64, by + blk + 48], radius=20,
                             fill=_rgb(box, (0, 0, 0)) + (235,),
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
    """QC art-director: inspect EVERY element AND judge CTR quality. Mechanics
    alone aren't enough — a technically-clean thumbnail with a tiny face still
    fails (that gap let a 4/10 full-body shot through once). Returns
    {...,verdict:PASS|FAIL}."""
    from core import openai_client as ai
    prompt = (
        "You are a meticulous YouTube thumbnail QC ART DIRECTOR. FAIL unless the "
        "thumbnail is both mechanically clean AND high-CTR. Check: "
        "(1) game logo fully visible, not clipped; (2) 4K/HDR badge has comfortable "
        "padding, text not crowded; (3) title fully readable, not clipped, not "
        "covering the face; (4) nothing overlaps awkwardly; (5) balanced, no large "
        "dead space; (6) mobile-legible at small size; "
        "(7) FACE PROMINENCE — the character's face is LARGE and clearly readable "
        "(a tiny face in a full-body shot FAILS); "
        "(8) SUBJECT DOMINANCE — the character (not a prop/background) is the focal "
        "point; (9) not cluttered. "
        "Return STRICT JSON: {logo_ok,badge_ok,title_ok,overlap_ok,balance_ok,"
        "mobile_ok,face_prominent,subject_dominant,not_cluttered, "
        "issues:[concise], score:1-10, verdict:'PASS'|'FAIL'}. "
        "verdict PASS requires score>=7 AND face_prominent true.")
    raw = ai.vision(prompt, [str(path)])
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else {"verdict": "FAIL", "issues": ["no json"]}


def fidelity_ok(composite, reference) -> dict:
    """Confirm the composited character still matches the OFFICIAL source render
    (Gemini never touches the character, so this should always pass — it's the
    guardrail that catches an accidental swap/redraw)."""
    from core import openai_client as ai
    raw = ai.vision(
        "Image 1 is a YouTube thumbnail; image 2 is the OFFICIAL game character "
        "render. Does the character in image 1 match image 2 EXACTLY (same outfit, "
        "face, hair, design)? JSON {matches:bool, differences:[..]}.",
        [str(composite), str(reference)])
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m.group(0)) if m else {"matches": False}


# --------------------------------------------------------------------------- #
# CASTING — the art director picks the best render + framing (no human input)  #
# --------------------------------------------------------------------------- #
def select_render(candidates: Sequence[str], brief: str = "") -> dict:
    """The CASTING art director looks at every candidate official render and picks
    the ONE best for a high-CTR thumbnail, per the mined winning pattern, AND says
    how tightly to frame it so the FACE is prominent. Returns
    {best_index, framing:'full'|'upper'|'closeup', why}."""
    from core import openai_client as ai
    labels = ", ".join(f"{i}:{Path(c).name}" for i, c in enumerate(candidates))
    prompt = (
        "You are a CASTING ART DIRECTOR for high-CTR YouTube gaming thumbnails. "
        f"These candidate OFFICIAL character renders are provided in order [{labels}]. "
        f"Brief: {brief}. Pick the ONE best using proven high-CTR principles: the "
        "character's FACE should be clearly visible and ideally toward the viewer, "
        "high resolution/sharpness, an iconic/recognizable pose or signature weapon, "
        "and a strong expression. A full-body render is fine — we can crop it — so "
        "judge on face quality + recognizability, not just how much body is shown. "
        "Then recommend the FRAMING that makes the face prominent: 'full' (whole "
        "body), 'upper' (chest-up), or 'closeup' (face + shoulders). "
        "Return STRICT JSON {best_index:int, framing:'full'|'upper'|'closeup', why:str}.")
    raw = ai.vision(prompt, [str(c) for c in candidates])
    m = re.search(r"\{.*\}", raw, re.S)
    d = json.loads(m.group(0)) if m else {}
    d["best_index"] = max(0, min(len(candidates) - 1, int(d.get("best_index", 0))))
    d.setdefault("framing", "upper")
    return d


# --------------------------------------------------------------------------- #
# BACKGROUND — Gemini generates a dramatic scene ONLY (never the character)     #
# --------------------------------------------------------------------------- #
def generate_background(out_path, *, style_hint: str = "",
                        palette: Sequence[str] = _PALETTE, retries: int = 6) -> Path:
    """Gemini generates a dramatic 16:9 BACKGROUND with NO characters/text/logos,
    then we trim any letterbox bars so it fills the canvas edge-to-edge."""
    import io as _io
    import numpy as np
    from PIL import Image
    from core import gemini
    pal = " / ".join(palette)
    prompt = (
        "Create a 16:9 LANDSCAPE cinematic YouTube-thumbnail BACKGROUND for an epic "
        f"video game. {style_hint} Dark, moody, dramatic, with depth, glowing bokeh "
        "lights, drifting embers/particles, volumetric haze, high contrast, premium "
        "colour grade. ABSOLUTELY NO characters, NO people, NO text, NO logos, NO "
        "watermark. Keep one side calmer/darker for a title and the subject. Palette "
        f"{pal}. Full-bleed — fill the entire frame edge to edge, no black bars, no "
        "letterbox.")
    png = gemini.edit_image(prompt, [], aspect_ratio="16:9", retries=retries)
    im = Image.open(_io.BytesIO(png)).convert("RGB")
    a = np.asarray(im); Hh, Ww, _ = a.shape
    rows = np.where(a.reshape(Hh, -1).mean(1) > 14)[0]
    cols = np.where(a.transpose(1, 0, 2).reshape(Ww, -1).mean(1) > 14)[0]
    if len(rows) and len(cols):
        im = im.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path


# --------------------------------------------------------------------------- #
# FRAMING + HERO PLACEMENT — the real render composited onto the AI background  #
# --------------------------------------------------------------------------- #
_FRAMINGS = ["full", "upper", "closeup"]
# 'upper' = a VERTICAL top-crop (chest-up): keeps FULL WIDTH so a wide signature
# prop like the Buster Sword stays WHOLE, while the face still reads large once
# scaled. 'closeup' = a HEAD-CENTRED box (tight face + shoulders) for when a much
# bigger face is needed — this necessarily drops wide props.
_FRAME_VFRAC = {"upper": 0.56}
_FRAME_BOX = {"closeup": (0.40, 0.92)}


def crop_framing(render, framing: str, out_path) -> Path:
    """Cut out the render (rembg if needed) and crop for the framing. 'full' keeps
    the whole render; 'upper' vertically crops to chest-up (keeps wide props like a
    weapon WHOLE); 'closeup' crops a head-centred box (biggest face, drops props)."""
    import numpy as np
    from PIL import Image
    im = Image.open(render).convert("RGBA")
    if float((np.asarray(im)[:, :, 3] < 10).mean()) < 0.05:   # opaque -> rembg
        _inject_ssl()
        from rembg import remove
        im = remove(im)
    bb = im.split()[-1].getbbox()
    if bb:
        im = im.crop(bb)
    w, h = im.size
    if framing in _FRAME_VFRAC:                       # vertical crop, full width
        im = im.crop((0, 0, w, int(h * _FRAME_VFRAC[framing])))
    elif framing in _FRAME_BOX:                        # head-centred box crop
        a = np.asarray(im.split()[-1])
        ys, xs = np.where(a > 32)
        if len(ys):
            y0c, y1c = int(ys.min()), int(ys.max()); body = max(1, y1c - y0c)
            band = ys < y0c + body * 0.16                 # top band = the head
            hx = int(np.median(xs[band])) if band.any() else (w // 2)
            hfrac, agg = _FRAME_BOX[framing]
            boxh = int(body * hfrac); boxw = int(boxh * agg)
            x0 = max(0, hx - boxw // 2); y0 = max(0, y0c - int(boxh * 0.06))
            im = im.crop((x0, y0, min(w, x0 + boxw), min(h, y0 + boxh)))
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path


def place_hero(bg_path, render_cut, out_path) -> Path:
    """Composite the REAL character cutout onto the AI background with a GENTLE
    grade (keep the official render faithful) + rim light + drop shadow. The
    character is never sent through an image model — this is what guarantees an
    exact, official-looking character."""
    from PIL import Image
    from agents import thumbnail as T
    g = T._CFG()
    gm = dict(g, subject_target_lum=150, subject_brightness_max=1.12,
              subject_saturation=1.06, subject_contrast=1.06, subject_clarity=1.15)
    base = _cover(Image.open(bg_path).convert("RGB")).convert("RGBA")
    T._composite_character(base, str(render_cut), gm,
                           xc=float(g.get("character_x", 0.63)),
                           height_frac=1.15, max_w_frac=0.62, top=0.0)
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_path, "JPEG", quality=95)
    return out_path


def build(out_path, *, candidates: Sequence[str], title_text: str = "PART 1",
          game_logo=None, badge_lines: Sequence[str] = ("4K", "HDR"),
          title_box_fill: Sequence[int] = (214, 18, 18),
          palette: Sequence[str] = _PALETTE, bg_style_hint: str = "",
          brief: str = "", work_dir=None, qc_rounds: int = 3):
    """Fully autonomous, no human decisions. The agents do everything:

      1. CASTING art director picks the best render from `candidates` + a framing.
      2. Gemini generates a dramatic BACKGROUND (never the character).
      3. AUTO-FRAMING loop: composite the REAL render at the chosen framing; if the
         QC art director says the face isn't prominent, escalate the crop
         (full -> upper -> closeup) and re-composite until the face is big enough.
      4. Within each framing, the layout art director + QC feedback loop refine the
         text/logo/badge until QC PASSES (mechanics AND CTR/face-prominence).
      5. A fidelity critic confirms the character still matches the official render.

    Returns (path, report) where report carries the casting/framing/qc/fidelity."""
    work = Path(work_dir) if work_dir else Path(out_path).parent / "_tdir"
    work.mkdir(parents=True, exist_ok=True)
    candidates = [c for c in candidates if c and Path(str(c)).exists()]
    if not candidates:
        raise RuntimeError("no candidate renders exist")

    # 1) CASTING — the art director chooses the render + initial framing
    cast = select_render(candidates, brief or f"{title_text} hero thumbnail")
    render = str(candidates[cast["best_index"]])

    # 2) BACKGROUND — dramatic scene, no character
    bg = generate_background(work / "bg.png", style_hint=bg_style_hint, palette=palette)

    # 3) AUTO-FRAMING loop. GEOMETRY is deterministic — the composite uses the
    # proven fixed layout (logo top-left, badge top-right, CENTRED title box
    # bottom-left, guaranteed no overlaps / no clipping / centred text) via
    # agents.thumbnail.build_thumbnail. The vision agents are used ONLY for
    # JUDGMENT: casting (above), face-prominence (drives the crop escalation), and
    # fidelity. We do NOT trust a vision model for pixel geometry — that gap once
    # let a broken layout score 10/10.
    from agents import thumbnail as T
    box = tuple(title_box_fill)
    last = None
    start = _FRAMINGS.index(cast["framing"]) if cast.get("framing") in _FRAMINGS else 1
    for fi in range(start, len(_FRAMINGS)):
        framing = _FRAMINGS[fi]
        cut = crop_framing(render, framing, work / f"cut_{framing}.png")
        out = T.build_thumbnail(text=title_text, out_path=out_path, image=str(bg),
                                character=str(cut), game_logo=game_logo,
                                badge_lines=badge_lines, box_fill=box)
        report = qc(out)
        last = report
        # Accept once the face is prominent (geometry is already guaranteed). If the
        # face is still small, escalate to a TIGHTER crop and re-composite.
        if report.get("face_prominent", True) and int(report.get("score", 0) or 0) >= 7:
            report["fidelity"] = fidelity_ok(out, render)
            return Path(out), {"casting": cast, "framing": framing,
                               "render": render, "qc": report}
    return Path(out_path), {"casting": cast, "framing": _FRAMINGS[-1],
                            "render": render, "qc": last}
