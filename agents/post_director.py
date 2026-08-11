"""Post Director — turns a trend pick into a screened Facebook post (caption + image).

Given a pick {topic, angle, game, stage} from agents.trends.analyze(), it:
  1. COPYWRITER  -> an FB-native caption: hook + a value line + a question CTA + tags,
                    accurate to the topic (no fabricated stats), scroll-stopping.
  2. HEADLINE    -> a punchy <=8-word on-image headline.
  3. NEWS CARD   -> a 1080x1350 (4:5) card: a REAL, topic-related scraped image (the source
                    article's hero image, a web image search, or on-model official character
                    art) under a top scrim, a NEWS kicker, the bold headline, a "VIA:
                    <source>" attribution, + the KG logo. NO AI-generated background — an
                    unrelated picture makes the post useless, so a topic with no usable real
                    image is SKIPPED, not filled with a generic scene.
  4. SCREEN      -> a vision critic checks the image genuinely depicts the topic, the post is
                    accurate + on-brand, and the headline is mobile-legible + unclipped.

direct(pick) runs all four and returns {caption, headline, image, screen, ok}. Never
raises to the runner — it fails soft so a bad topic just doesn't produce a draft.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from core.config import CONFIG, ROOT

CARD = 1080          # card width
CARDH = 1350         # card height (4:5 portrait — matches the news-card reference)
BRAND_CREDIT = "BOSS KG"   # our signature under the headline (in place of a news 'VIA:' line)


def _source_label(raw: str) -> str:
    """Human source name for the 'VIA:' attribution line. 'news:IGN' -> 'IGN'."""
    raw = (raw or "").strip()
    if ":" in raw:
        pre, name = raw.split(":", 1)
        if pre == "news":
            return name.strip()
        if pre == "youtube":
            return "YouTube"
        if pre == "gtrends":
            return "Google Trends"
    return name.strip() if raw else ""


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
    """FB-native caption for the trend post — Marvel beat (MCU + Insomniac's Marvel games),
    a little longer so it gives real CONTEXT, not just a hook."""
    from agents.content import _text, sanitize
    prompt = (
        "You write scroll-stopping Facebook posts for a MARVEL fan page (KiwinoyGamer) that "
        "covers the Marvel Cinematic Universe and Insomniac's Marvel games. Write ONE post "
        f"about this CURRENT trending topic:\nTOPIC: {topic}\nANGLE: {angle}\n"
        f"PROPERTY: {game or 'Marvel'}\n\n"
        "Structure:\n"
        "- Open with a punchy HOOK line that stops the scroll.\n"
        "- Then 2-3 sentences of real CONTEXT: what happened, why it matters, and why fans "
        "should care — enough that someone who only skims still gets the story. Be ACCURATE: "
        "do NOT invent specific stats, dates, quotes, or plot details; if unsure, keep the "
        "claim general rather than fabricating a specific.\n"
        "- End with a QUESTION that invites comments (engagement is the goal).\n"
        "- Warm, hype, in-the-know community tone. 2-4 tasteful emojis. ~70-110 words for the "
        "body (longer than a one-liner, but still tight).\n"
        "- Then 4-6 relevant hashtags on the last line. Each hashtag is ONE word with NO "
        "spaces or apostrophes (write #MarvelsSpiderMan2, never #Marvel's SpiderMan2).\n"
        "- No clickbait lies, no preamble, no markdown. Return ONLY the post text.")
    return _fix_hashtags(sanitize(_text(prompt)).strip())


def _fix_hashtags(text: str) -> str:
    """Repair hashtags mangled by apostrophe/space stripping: '#Marvels SpiderMan2' ->
    '#MarvelsSpiderMan2'. Joins a '#Word' immediately followed by CamelCase/Digit words on
    the SAME line into one tag (a real next word starting lowercase is left alone)."""
    import re

    def _join(m):
        tag = "#" + m.group(1)
        for w in re.findall(r"[A-Z0-9]\w*", m.group(2)):
            tag += w
        return tag

    out = []
    for line in text.split("\n"):
        if line.count("#") >= 2:            # the hashtag line only (avoid body '#1' etc.)
            # a hashtag word, then one or more following Capitalised/Number words
            line = re.sub(r"#(\w+)((?:\s+[A-Z0-9]\w*)+)", _join, line)
        out.append(line)
    return "\n".join(out)


def verify_caption(topic: str, caption: str, game: str = "") -> dict:
    """Accuracy gate for AUTOPOST (no human review). An adversarial critic checks the
    caption for FABRICATED specifics — invented stats, dates, quotes, cast names, plot
    details, or rumors stated as fact — that we can't stand behind. Returns
    {ok, safe_caption, issues}: if it finds a fixable specific it returns a corrected
    caption with the claim removed/generalised (hook + hashtags kept); if the post is
    fundamentally unsupportable it returns ok=False. Fail-OPEN on critic error (the writer
    is already anti-fabrication and the image screener is a second gate)."""
    from agents.content import _text, extract_json, sanitize
    prompt = (
        "You are a strict FACT-CHECK editor for a Marvel fan page. A caption is about to "
        f"AUTO-POST (no human will review it). TOPIC: {topic}\nPROPERTY: {game or 'Marvel'}\n\n"
        f"CAPTION:\n{caption}\n\n"
        "Flag any statement the page can't stand behind: invented or precise stats/numbers, "
        "specific dates, direct quotes, specific casting/actor names, or plot/story details, "
        "and rumors phrased as confirmed fact. General hype and clearly-attributed 'rumor'/"
        "'reportedly' framing are fine.\n"
        "ALWAYS produce `safe_caption`: an ACCURATE version — remove or generalise ONLY the "
        "unsupported parts, keep the hook, the question, the emojis, and a hashtag line, keep "
        "it natural. Set ok=TRUE when safe_caption is accurate and postable (this is the "
        "normal case, even if you had to edit). Set ok=FALSE ONLY if the topic itself cannot "
        "be posted accurately at all (pure leak/fabrication with nothing true to say).\n"
        'Return STRICT JSON {"ok":bool,"issues":[concise what you changed],"safe_caption":'
        '"the corrected caption (or the original if already fine)"}.')
    try:
        d = extract_json(_text(prompt))
        safe = sanitize(str(d.get("safe_caption") or caption)).strip()
        safe = _fix_hashtags(safe) if safe else caption
        return {"ok": bool(d.get("ok", True)), "issues": d.get("issues", []),
                "safe_caption": safe or caption}
    except Exception as e:
        return {"ok": True, "issues": [f"verify skipped: {e}"], "safe_caption": caption}


def story_canvas_bytes(card_path) -> bytes:
    """Fit the 4:5 trend card onto a 1080x1920 (9:16) Instagram STORY canvas — the card
    centred over a blurred, darkened blow-up of itself. Returns PNG bytes."""
    import io as _io
    from PIL import Image, ImageFilter, ImageEnhance
    W, H = 1080, 1920
    card = Image.open(card_path).convert("RGB")
    # background: cover-fill the story frame with a heavily blurred, dimmed card
    s = max(W / card.width, H / card.height)
    bg = card.resize((int(card.width * s), int(card.height * s)), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2,
                  (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    # foreground: the card at full width, vertically centred
    fw = W
    fh = int(card.height * fw / card.width)
    fg = card.resize((fw, fh), Image.LANCZOS)
    bg.paste(fg, (0, (H - fh) // 2))
    out = _io.BytesIO()
    bg.save(out, "PNG")
    return out.getvalue()


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


# Insomniac's Marvel GAME titles (vs MCU films/shows) — decides whether an image search
# should bias to game art or to a real film/show still.
_GAME_TITLES = ("marvel's spider-man", "spider-man 2", "spider-man: miles", "miles morales",
                "marvel's wolverine")


def _card_query(topic: str, game: str) -> str:
    """Web-image-search fallback query = the SUBJECT, not the full headline sentence (a
    sentence is a terrible image query — it returned a real spider / stock photos). Bias an
    Insomniac GAME title to game art; use an MCU film/show property as-is for real stills."""
    g = (game or "").strip()
    gl = g.lower()
    if not g or gl in ("gaming", "game", "marvel", "mcu"):
        return topic
    return f"{g} video game" if any(k in gl for k in _GAME_TITLES) else g


# KG-franchise -> (Fandom wiki host, a recognizable subject to scrape). For these the
# thumbnail_director scraper reliably pulls REAL, on-model official art.
_GAME_WIKI = [
    (("spider-man 2", "spider-man2"), "marvels-spider-man.fandom.com", "Advanced Suit 2.0"),
    (("miles morales",), "marvels-spider-man.fandom.com", "Advanced Tech Suit"),
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
        img_url = m.group(1)
        # Google-News article pages expose the hero image as a googleusercontent thumbnail;
        # request a large render (strip any trailing =wNN-hNN size directive first).
        is_gthumb = "googleusercontent.com" in img_url or "gstatic.com" in img_url
        if is_gthumb:
            img_url = re.sub(r"=[-\w]+$", "", img_url) + "=w1280"
        ir = requests.get(img_url, headers=ua, timeout=25)
        if "image" not in ir.headers.get("Content-Type", ""):
            return None
        im = Image.open(_io.BytesIO(ir.content))
        min_w, min_h = (500, 280) if is_gthumb else (600, 350)   # thumbs render a bit smaller
        if im.width < min_w or im.height < min_h:
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


def _trim_black(img):
    """Trim near-black letterbox borders (Gemini sometimes returns them)."""
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("RGB")); H, W, _ = a.shape
    rows = np.where(a.reshape(H, -1).mean(1) > 14)[0]
    cols = np.where(a.transpose(1, 0, 2).reshape(W, -1).mean(1) > 14)[0]
    if len(rows) and len(cols):
        img = img.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))
    return img


def _cover(img, w: int, h: int, top_bias: bool = False):
    """Cover-fit an RGB image to w×h. For a portrait source a top_bias keeps the HEAD
    (faces sit near the top) instead of a blind centre crop that decapitates it."""
    from PIL import Image
    img = _trim_black(img)
    s = max(w / img.width, h / img.height)
    img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    ox = (img.width - w) // 2
    oy = (int((img.height - h) * 0.10) if (top_bias and img.height > img.width)
          else (img.height - h) // 2)
    return img.crop((ox, oy, ox + w, oy + h))


def _render_on_dark(render_rgba, palette: Optional[list] = None):
    """Compose a TRANSPARENT character render onto a dark themed portrait canvas,
    FACE-FORWARD: head near the top, body filling the frame. Used only for on-model
    official CHARACTER art (a real render, not an AI scene)."""
    from PIL import Image, ImageColor, ImageDraw, ImageFilter
    from agents.thumbnail import _autocrop_alpha
    r = _autocrop_alpha(render_rgba)
    col = (226, 54, 54)
    try:
        if palette:
            col = ImageColor.getrgb(palette[0])[:3]
    except Exception:
        pass
    canvas = Image.new("RGBA", (CARD, CARDH), (10, 12, 22, 255))
    glow = Image.new("RGBA", (CARD, CARDH), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([CARD * 0.06, CARDH * 0.02, CARD * 0.94, CARDH * 0.66],
                                 fill=col + (70,))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(150)))
    th = int(CARDH * 0.96)                                  # near-full height, head up top
    rr = r.resize((max(1, int(r.width * th / r.height)), th), Image.LANCZOS)
    if rr.width > int(CARD * 0.98):
        rr = rr.resize((int(CARD * 0.98), max(1, int(rr.height * CARD * 0.98 / rr.width))),
                       Image.LANCZOS)
    canvas.alpha_composite(rr, ((CARD - rr.width) // 2, int(CARDH * 0.06)))
    return canvas.convert("RGB")


def _draw_centered_spaced(d, cx: int, y: int, text: str, font, fill, spacing: int = 6):
    """Draw letter-spaced text horizontally centred on cx (Pillow has no tracking)."""
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = cx - total / 2
    for ch, wc in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += wc + spacing


def build_card(topic: str, game: str, headline: str, out_path,
               palette: Optional[list] = None, bg_image=None) -> Optional[Path]:
    """News-card (1080x1350, 4:5). REAL scraped `bg_image` REQUIRED — a transparent
    character render is composed face-forward on a dark canvas, a photo/scene is
    cover-cropped keeping the head. NO AI-scene fallback: without a usable real image this
    returns None (the post is skipped rather than shipped with an unrelated picture). Adds a
    top scrim + centred NEWS kicker + bold headline + BOSS KG brand credit.
    """
    from PIL import Image, ImageDraw
    from agents import thumbnail as T

    if not (bg_image and Path(bg_image).exists()):
        return None
    try:
        raw = Image.open(bg_image)
        rgba = raw.convert("RGBA")
        is_render = rgba.getchannel("A").getextrema()[0] < 245   # true transparency = a cutout
        bg = (_render_on_dark(rgba, palette) if is_render
              else _cover(raw.convert("RGB"), CARD, CARDH, top_bias=True))
    except Exception as e:
        print(f"[post_director] card bg failed ({e!r}).", flush=True)
        return None
    bg = bg.convert("RGBA")
    cx = CARD // 2

    # top scrim (headline zone) + a soft bottom scrim (logo/attribution legibility)
    scrim = Image.new("RGBA", (CARD, CARDH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(CARDH):
        top = int(232 * max(0.0, 1.0 - y / (CARDH * 0.52)) ** 1.15)
        bot = int(150 * max(0.0, (y - CARDH * 0.82) / (CARDH * 0.18)) ** 1.4)
        sd.line([(0, y), (CARD, y)], fill=(6, 8, 16, min(240, max(top, bot))))
    bg.alpha_composite(scrim)
    d = ImageDraw.Draw(bg)

    YEL = (255, 209, 41)
    # NEWS kicker (centred, letter-spaced)
    kf = T._font(34)
    _draw_centered_spaced(d, cx, 58, "NEWS", kf, YEL, spacing=10)

    # headline — centred, wrapped, big + bold (UPPERCASE), stroked for legibility
    words = headline.upper().split()
    fs = 96
    while fs > 46:
        f = T._font(fs)
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if d.textbbox((0, 0), test, font=f)[2] <= CARD - 120:
                cur = test
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= 4:
            break
        fs -= 6
    f = T._font(fs)
    lh = int(fs * 1.06)
    y = 120
    for ln in lines:
        d.text((cx, y), ln, font=f, fill=(255, 255, 255), anchor="ma",
               stroke_width=3, stroke_fill=(0, 0, 0))
        y += lh

    # KG brand credit under the headline (centred, yellow, letter-spaced) — this is our
    # page, so our signature sits where a news outlet's 'VIA:' source line would; no
    # separate logo badge (removed per brand preference).
    y += 16
    _draw_centered_spaced(d, cx, y, BRAND_CREDIT.upper(), T._font(34), YEL, spacing=10)

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
        "You are the POST DIRECTOR screening a Facebook gaming NEWS card before it goes to "
        f"drafts. The intended TREND TOPIC is: {topic}\n\nThe CAPTION is:\n{caption}\n\n"
        "Look at the attached image. The photo/artwork is what stops the scroll, so it MUST "
        "genuinely depict THIS topic. Approve ONLY if ALL hold: (1) the background image is "
        "a REAL, on-topic photo/still/character clearly about the topic (the RIGHT game, "
        "character, person, or franchise) — REJECT a generic/abstract/AI-looking background, "
        "a wrong or unrelated subject, or a real-world look-alike (e.g. a real spider for "
        "'Spider-Man'); (2) nothing misleading, fabricated, or off-brand for a positive "
        "gaming page; (3) OUR white headline is fully readable, not clipped, and not colliding "
        "with any text already baked into the photo; (4) it looks appealing on a phone. "
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
        # REAL, topic-related images ONLY — the image is what stops the scroll, so an
        # unrelated picture makes the post useless. Sourced in relevance order and the
        # vision SCREENER keeps the one that truly matches the topic (rejecting junk):
        #   1) the SOURCE ARTICLE's own hero image (most on-topic for a news-driven trend)
        #   2) a web image search for the topic/game
        #   3) official FANDOM character art (on-model render, for our franchises)
        # NO AI-generated fallback: if nothing real passes, we SKIP (ok stays False) so a
        # useless/irrelevant card never ships.
        srcs: list = []
        art = _article_image(str(pick.get("source_link", "")), out_dir / f"{slug}_article.jpg")
        if art:
            srcs.append(art)
        srcs += scrape_topic_images(_card_query(topic, game), out_dir / f"{slug}_src", n=4)
        srcs += _game_art_images(game, out_dir / f"{slug}_art", n=3)
        best = None
        for i, bg_src in enumerate(srcs):
            img = build_card(topic, game, res["headline"], out_dir / f"{slug}_c{i}.jpg",
                             palette=palette, bg_image=bg_src)
            if not img:
                continue
            sc = screen(img, res.get("caption", ""), topic)
            if best is None or sc.get("score", 0) > best["screen"].get("score", 0):
                best = {"image": str(img), "screen": sc}
            if sc.get("ok"):
                break
        if best:
            res["image"] = best["image"]
            res["screen"] = best["screen"]
            res["ok"] = bool(best["screen"].get("ok"))
        else:
            res["screen"] = {"ok": False, "score": 0, "issues": ["no real related image found"]}
    except Exception as e:
        res["error"] = repr(e)
    return res
