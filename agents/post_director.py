"""Post Director — turns a trend pick into a screened Facebook post (caption + image).

Given a pick {topic, angle, game, stage} from agents.trends.analyze(), it:
  1. COPYWRITER  -> an FB-native caption: hook + a value line + a question CTA + tags,
                    accurate to the topic (no fabricated stats), scroll-stopping.
  2. HEADLINE    -> a punchy <=8-word on-image headline.
  3. TREND CARD  -> a 1080x1080 image: a dramatic on-theme gaming background (Gemini),
                    a dark scrim, the bold headline, a red "TRENDING" pill, + the KG logo.
  4. SCREEN      -> a vision critic checks the post+image are accurate to the topic,
                    appealing, on-brand, mobile-legible, and not misleading.

direct(pick) runs all four and returns {caption, headline, image, screen, ok}. Never
raises to the runner — it fails soft so a bad topic just doesn't produce a draft.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from core.config import CONFIG, ROOT

CARD = 1080


def _kg_logo_circular(size: int):
    """Circular-cropped KG brand logo (RGBA) — same treatment as the reels."""
    from PIL import Image, ImageDraw
    src = ROOT / str(CONFIG.reels.get("brand_logo", "reels/assets/logo/KG Logo 2.PNG"))
    if not src.exists():
        return None
    lg = Image.open(src).convert("RGBA")
    s = min(lg.size)
    lg = lg.crop(((lg.width - s) // 2, (lg.height - s) // 2,
                  (lg.width - s) // 2 + s, (lg.height - s) // 2 + s)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    lg.putalpha(mask)
    return lg


def write_caption(topic: str, angle: str, game: str = "") -> str:
    """FB-native caption for the trend post."""
    from agents.content import _text, sanitize
    prompt = (
        "You write scroll-stopping Facebook posts for a gaming page (KiwinoyGamer). "
        f"Write ONE short post about this CURRENT gaming trend:\nTOPIC: {topic}\n"
        f"ANGLE: {angle}\nGAME/FRANCHISE: {game or 'gaming'}\n\n"
        "Rules:\n"
        "- Open with a punchy HOOK line.\n"
        "- 1 short line of value/context (accurate — do NOT invent specific stats, dates, "
        "or quotes; keep claims general if unsure).\n"
        "- End with a QUESTION that invites comments (engagement is the goal).\n"
        "- Warm, hype, community tone. 1-3 tasteful emojis. <= ~55 words total.\n"
        "- Then 3-5 relevant hashtags on the last line.\n"
        "- No clickbait lies, no preamble. Return ONLY the post text.")
    return sanitize(_text(prompt)).strip()


def _headline(topic: str, angle: str) -> str:
    from agents.content import _text, sanitize
    prompt = (
        f"Write a PUNCHY on-image headline (<=8 words, UPPERCASE ok) for a gaming trend "
        f"card about: {topic}. Angle: {angle}. It must be accurate + instantly readable. "
        "No hashtags, no quotes, no emoji. Return ONLY the headline.")
    h = sanitize(_text(prompt)).strip().strip('"').split("\n")[0]
    return h[:60] if h else (topic[:60])


def scrape_topic_images(query: str, out_dir, n: int = 4) -> list:
    """Download up to `n` REAL related images for a topic via Bing image search (no API
    key). Returns a list of saved Paths (best-effort, largest-ish first). The vision
    SCREENER then picks the RELEVANT one and rejects junk (e.g. a photo of a real spider
    for 'Spider-Man'). Press/promo imagery on a fan gaming page = standard practice."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    import html
    import re
    import requests
    from PIL import Image
    import io as _io
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
    try:
        r = requests.get("https://www.bing.com/images/search",
                         params={"q": query, "form": "HDRSC2", "first": "1"},
                         headers=ua, timeout=20)
        # Bing stores each full image URL in an HTML-ESCAPED `m="{...murl...}"` tile
        # attribute, so unescape the page before pulling murl.
        murls = re.findall(r'"murl":"(.*?)"', html.unescape(r.text))
    except Exception:
        return []
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    saved, seen = [], set()
    for m in murls[:30]:
        if len(saved) >= n:
            break
        u = m.encode("utf-8").decode("unicode_escape")
        if u in seen or not u.lower().startswith("http"):
            continue
        seen.add(u)
        try:
            ir = requests.get(u, headers=ua, timeout=25)
            if ir.status_code >= 400 or "image" not in ir.headers.get("Content-Type", ""):
                continue
            im = Image.open(_io.BytesIO(ir.content))
            if im.width < 700 or im.height < 450:          # skip icons/thumbnails
                continue
            p = out_dir / f"src_{len(saved)}.jpg"
            im.convert("RGB").save(p, "JPEG", quality=94)
            saved.append(p)
        except Exception:
            continue
    return saved


def _card_query(topic: str, game: str) -> str:
    """A search query biased toward GAME imagery (so 'Spider-Man' returns the game, not a
    real spider)."""
    g = (game or "").strip()
    if g and g.lower() not in ("gaming", "game"):
        return f"{g} video game"
    return topic


# KG-franchise -> (Fandom wiki host, a recognizable subject to scrape). For these the
# thumbnail_director scraper reliably pulls REAL, on-model official art.
_GAME_WIKI = [
    (("spider-man 2", "spider-man2"), "marvels-spider-man.fandom.com", "Symbiote Suit"),
    (("miles morales",), "marvels-spider-man.fandom.com", "Miles Morales"),
    (("spider-man", "spiderman"), "marvels-spider-man.fandom.com", "Advanced Suit"),
    (("final fantasy vii", "ffvii", "ff7"), "finalfantasy.fandom.com", "Cloud Strife from FFVII Remake"),
    (("final fantasy",), "finalfantasy.fandom.com", "Cloud Strife"),
    (("halo",), "halo.fandom.com", "Master Chief"),
    (("last of us",), "thelastofus.fandom.com", "Joel Miller"),
    (("resident evil",), "residentevil.fandom.com", "Leon Scott Kennedy"),
    (("god of war",), "godofwar.fandom.com", "Kratos"),
    (("elden ring",), "eldenring.fandom.com", "Malenia"),
    (("zelda",), "zelda.fandom.com", "Link"),
    (("grand theft auto", "gta"), "gta.fandom.com", "protagonist"),
]


def _game_art_images(game: str, out_dir, n: int = 3) -> list:
    """REAL, on-model official art for a KG-franchise game via the Fandom scraper
    (thumbnail_director). Reliable + relevant. Returns [] for non-mapped games."""
    g = (game or "").lower()
    for keys, host, subj in _GAME_WIKI:
        if any(k in g for k in keys):
            try:
                from agents import thumbnail_director as td
                return [Path(p) for p in td.scrape_candidates(
                    host, f"{subj} render", Path(out_dir), n=n,
                    prefer=("render", "promo", "key", "art"))]
            except Exception:
                return []
    return []


def _article_image(link: str, out_path):
    """The source news article's own hero image (og:image) — the most RELEVANT real image
    for a news-driven trend. Returns the saved Path or None."""
    if not link:
        return None
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    import re
    import requests
    from PIL import Image
    import io as _io
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126 Safari/537.36"}
    try:
        r = requests.get(link, headers=ua, timeout=20)
        m = (re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\'](.*?)["\']',
                       r.text, re.I) or
             re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\']og:image["\']',
                       r.text, re.I))
        if not m:
            return None
        ir = requests.get(m.group(1), headers=ua, timeout=25)
        if "image" not in ir.headers.get("Content-Type", ""):
            return None
        im = Image.open(_io.BytesIO(ir.content))
        if im.width < 600 or im.height < 350:
            return None
        out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
        im.convert("RGB").save(out_path, "JPEG", quality=94)
        return out_path
    except Exception:
        return None


def _gemini_bg(topic: str, game: str, palette: Optional[list]):
    from PIL import Image
    from core import gemini
    import io as _io
    pal = " / ".join(palette) if palette else "crimson red, deep blue, near-black"
    prompt = (
        f"Create a 1:1 SQUARE dramatic, cinematic GAMING-themed background for a news/trend "
        f"card about: {topic} ({game}). Moody, high-contrast, energetic, premium; glowing "
        f"light, depth, subtle particles. Palette: {pal}. Keep the LOWER HALF darker/simpler "
        "so a headline stays readable. ABSOLUTELY NO text, NO logos, NO watermark, NO real "
        "faces/characters.")
    png = gemini.edit_image(prompt, [], aspect_ratio="1:1", retries=5)
    return Image.open(_io.BytesIO(png)).convert("RGB")


def build_card(topic: str, game: str, headline: str, out_path,
               palette: Optional[list] = None, bg_image=None) -> Optional[Path]:
    """1080x1080 trend card. Background = the given `bg_image` (a real scraped image) if
    provided, else a generated Gemini scene; then a bottom scrim + bold headline +
    TRENDING pill + KG logo. Returns the JPEG path, or None on total failure."""
    from PIL import Image, ImageDraw
    from agents import thumbnail as T

    bg = None
    if bg_image and Path(bg_image).exists():
        try:
            bg = Image.open(bg_image).convert("RGB")
        except Exception:
            bg = None
    if bg is None:                                          # fall back to a generated scene
        try:
            bg = _gemini_bg(topic, game, palette)
        except Exception as e:
            print(f"[post_director] card bg failed ({e!r}).", flush=True)
            return None
    # cover-fit to square
    s = max(CARD / bg.width, CARD / bg.height)
    bg = bg.resize((int(bg.width * s), int(bg.height * s)), Image.LANCZOS)
    bg = bg.crop(((bg.width - CARD) // 2, (bg.height - CARD) // 2,
                  (bg.width - CARD) // 2 + CARD, (bg.height - CARD) // 2 + CARD)).convert("RGBA")
    # bottom scrim for headline legibility
    scrim = Image.new("RGBA", (CARD, CARD), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(CARD):
        a = int(235 * max(0.0, (y - CARD * 0.42) / (CARD * 0.58)) ** 1.3)
        sd.line([(0, y), (CARD, y)], fill=(8, 10, 20, min(235, a)))
    bg.alpha_composite(scrim)
    d = ImageDraw.Draw(bg)

    # KG circular logo, TOP-right (kept clear of the bottom headline)
    lg = _kg_logo_circular(120)
    if lg is not None:
        bg.alpha_composite(lg, (CARD - 120 - 48, 44))

    # red "TRENDING" pill, top-left — everything vertically CENTERED on the pill's mid
    # line (anchor='lm'), with a drawn dot (the base font has no emoji glyph).
    pf = T._font(40)
    pill = "TRENDING"
    tw = int(d.textlength(pill, font=pf))
    asc, desc = pf.getmetrics()
    dot = 22
    padx, pady = 32, 18
    inner = dot + 16 + tw
    bw, bh = inner + padx * 2, (asc + desc) + pady * 2
    x0, y0 = 48, 48
    cy = y0 + bh // 2
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=bh // 2, fill=(214, 18, 18))
    dx = x0 + padx
    d.ellipse([dx, cy - dot // 2, dx + dot, cy + dot // 2], fill=(255, 210, 60))
    d.text((dx + dot + 16, cy), pill, font=pf, fill=(255, 255, 255), anchor="lm")

    # headline, wrapped, bottom-left, big + bold
    words = headline.upper().split()
    fs = 92
    while fs > 46:
        f = T._font(fs)
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if d.textbbox((0, 0), test, font=f)[2] <= CARD - 96:
                cur = test
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= 3:
            break
        fs -= 6
    f = T._font(fs)
    lh = int(fs * 1.12)
    y = CARD - 70 - lh * len(lines)
    for ln in lines:
        d.text((48, y), ln, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        y += lh

    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
    return out_path


def screen(image, caption: str, topic: str) -> dict:
    """Vision critic: is the post+image accurate to the topic, appealing, on-brand,
    mobile-legible, non-misleading? Returns {ok, score, issues}."""
    import json
    from core import openai_client as ai
    from agents.content import extract_json
    prompt = (
        "You are the POST DIRECTOR screening a Facebook gaming post before it goes to "
        f"drafts. The intended TREND TOPIC is: {topic}\n\nThe CAPTION is:\n{caption}\n\n"
        "Look at the attached image (a trend card). Approve ONLY if: (1) the image + "
        "headline clearly relate to the topic; (2) nothing is misleading, fabricated, or "
        "off-brand for a positive gaming page; (3) the headline text is fully readable and "
        "not clipped; (4) it looks appealing/scroll-stopping on a phone. "
        'Return STRICT JSON {"ok":bool,"score":1-10,"issues":[concise]}.')
    try:
        d = extract_json(ai.vision(prompt, [str(image)]))
        return {"ok": bool(d.get("ok", False)), "score": int(d.get("score", 0) or 0),
                "issues": d.get("issues", [])}
    except Exception as e:
        return {"ok": False, "score": 0, "issues": [f"screen error: {e}"]}


def direct(pick: dict, out_dir, *, palette: Optional[list] = None) -> dict:
    """Orchestrate one trend post. Returns {topic, caption, headline, image, screen, ok}."""
    topic = str(pick.get("topic", "")).strip()
    angle = str(pick.get("angle", "")).strip()
    game = str(pick.get("game", "")).strip()
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    res: dict[str, Any] = {"topic": topic, "game": game, "ok": False}
    try:
        res["caption"] = write_caption(topic, angle, game)
        res["headline"] = _headline(topic, angle)
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40] or "trend"
        # Card geometry is deterministic, but the Gemini background varies — retry once
        # if the screener rejects the first roll (a fresh background usually fixes it).
        best = None
        # REAL images first, in reliability order, and let the SCREENER pick the relevant
        # one (rejecting junk). Fallback chain ending in a generated Gemini scene:
        #   1) official FANDOM game art (for KG franchises — reliable + on-model)
        #   2) the SOURCE ARTICLE's own image (news-driven topics)
        #   3) a best-effort web image search
        #   4) Gemini scene (None)
        srcs: list = []
        srcs += _game_art_images(game, out_dir / f"{slug}_art", n=3)
        ai = _article_image(str(pick.get("source_link", "")), out_dir / f"{slug}_article.jpg")
        if ai:
            srcs.append(ai)
        srcs += scrape_topic_images(_card_query(topic, game), out_dir / f"{slug}_src", n=3)
        for bg_src in srcs + [None]:
            img = build_card(topic, game, res["headline"], out_dir / f"{slug}.jpg",
                             palette=palette, bg_image=bg_src)
            if not img:
                continue
            sc = screen(img, res.get("caption", ""), topic)
            best = {"image": str(img), "screen": sc}
            if sc.get("ok"):
                break
        if best:
            res["image"] = best["image"]
            res["screen"] = best["screen"]
            res["ok"] = bool(best["screen"].get("ok"))
    except Exception as e:
        res["error"] = repr(e)
    return res
