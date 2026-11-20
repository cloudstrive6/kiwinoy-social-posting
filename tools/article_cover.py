"""Give BOSS KG news articles a real cover image — the IGN way: use the press image from the
source we're citing.

For each article without a `cover:`, this scrapes the lead image (og:image / twitter:image) from
the article's `sourceUrl` — the official still/key art the outlet published for that story —
downloads it, crops to a 1200x675 (16:9) cover, writes it to site/public/covers/<slug>.jpg, and
sets the frontmatter `cover`. The site already credits the source outlet and notes that imagery
belongs to its respective owners (used for editorial coverage). If a source exposes no usable
image, a clean branded card (category gradient + topic + KG mark) is generated so a cover always
exists.

  python tools/article_cover.py --all-missing        # cover every article without one
  python tools/article_cover.py --slug wolverine-60fps-base-ps5 --force
"""
from __future__ import annotations

import argparse
import html as _html
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ART_DIR = ROOT / "site" / "src" / "content" / "articles"
COVERS = ROOT / "site" / "public" / "covers"
CW, CH = 1200, 675                                    # 16:9 cover
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_GRAD = {                                             # branded-fallback gradients (mirror site .g-*)
    "spider-man2": ("#e11d2a", "#1746b3"), "spider-man": ("#e11d2a", "#1746b3"),
    "wolverine": ("#f2b705", "#0d5c3b"), "mcu": ("#7a4de2", "#123a6b"),
    "marvel": ("#e23636", "#2b3f7a"), "playstation": ("#1f7ae0", "#0b1a3a"),
    "_default": ("#e23636", "#2b3f7a"),
}
FONTS = {
    "serif": "/c/Windows/Fonts/georgiab.ttf",
    "sans": "/c/Windows/Fonts/arialbd.ttf",
}


def _parse(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"(?s)^---\n(.*?)\n---\n?(.*)$", text)
    import yaml
    fm = {}
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
    return text, (fm if isinstance(fm, dict) else {})


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _fetch_html(page_url: str) -> str:
    """The source page's HTML. Some outlets (TweakTown, 2026-11-20) drop the `requests` connection
    but answer urllib, so a failed first try gets a second, plain urllib request."""
    import requests
    try:
        return requests.get(page_url, headers={"User-Agent": _UA}, timeout=25).text
    except Exception as e:
        print(f"      source fetch failed ({type(e).__name__}), retrying plainly", flush=True)
    try:
        import urllib.request
        req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    except Exception as e:
        print(f"      source fetch failed again: {e!r}", flush=True)
        return ""


def _og_image_url(page_url: str) -> str | None:
    """The social preview image the source outlet published for this story."""
    h = _fetch_html(page_url)
    if not h:
        return None
    for prop in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        m = (re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)', h, re.I)
             or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']', h, re.I))
        if m:
            return _html.unescape(m.group(1))
    return None


def _download(img_url: str) -> bytes | None:
    import requests
    try:
        r = requests.get(img_url, headers={"User-Agent": _UA}, timeout=25)
        if r.status_code == 200 and len(r.content) > 8000 and "image" in r.headers.get("content-type", "image"):
            return r.content
    except Exception as e:
        print(f"      image download failed ({type(e).__name__}), retrying plainly", flush=True)
    try:
        import urllib.request
        req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=25).read()
        return data if len(data) > 8000 else None
    except Exception as e:
        print(f"      image download failed again: {e!r}", flush=True)
    return None


GAME_ART = ROOT / "reels" / "assets" / "game-art"


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _game_art(fm: dict) -> tuple[Path | None, str]:
    """(an official key-art file for the article's game, the game's display name). Second fallback
    when the source has no usable image (Bryce, 2026-11-20: a GTA 6 article went up with a plain
    gradient card and 'Image: TweakTown' under it). Matches the article's `game` ('gta-6', 'gta6')
    or its tags against the game-art folders and the config game names."""
    import zlib
    try:
        from core.config import CONFIG
        names = CONFIG.reels.get("game_names", {}) or {}
    except Exception:
        names = {}
    folders = sorted(p for p in GAME_ART.iterdir() if p.is_dir()) if GAME_ART.exists() else []

    def keys(folder):
        k = {_squash(folder.name), _squash(names.get(folder.name, ""))}
        return k | {x.replace("grandtheftautovi", "gta6").replace("grandtheftauto6", "gta6") for x in k}

    # the article's own `game` first; tags only when it has none that matches (a GTA 6 article
    # tagged "Fortnite" must not get Fortnite art; review 2026-11-20)
    for wants in ([_squash(fm.get("game", ""))], [_squash(t) for t in (fm.get("tags") or [])]):
        wants = [w for w in wants if w]
        for folder in folders:
            if not any(w in keys(folder) for w in wants):
                continue
            imgs = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
            if imgs:                                   # same article -> same image on every rerun
                pick = imgs[zlib.crc32(str(fm.get("title", "")).encode()) % len(imgs)]
                return pick, str(names.get(folder.name) or folder.name)
    return None, ""


def _cover_from_bytes(data: bytes, out: Path) -> bool:
    """Scale + center-crop the press image to a 1200x675 cover, with a subtle bottom gradient so
    the site's overlaid card text stays readable."""
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        print(f"      image decode failed: {e!r}", flush=True)
        return False
    w, h = im.size
    if w < 480 or h < 270:                            # too small to be a real hero image
        return False
    scale = max(CW / w, CH / h)
    im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    nw, nh = im.size
    left, top = (nw - CW) // 2, (nh - CH) // 2
    im = im.crop((left, top, left + CW, top + CH))
    ov = Image.new("L", (CW, CH), 0)
    od = ImageDraw.Draw(ov)
    for y in range(CH):
        od.line([(0, y), (CW, y)], fill=int(120 * max(0, (y - CH * 0.45) / (CH * 0.55))))
    im = Image.composite(Image.new("RGB", (CW, CH), (0, 0, 0)), im, ov)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "JPEG", quality=84, optimize=True)
    return True


def _cover_branded(fm: dict, out: Path) -> None:
    """Fallback: a designed cover card (category gradient + topic + KG mark). No third-party art."""
    game = str(fm.get("game", "")).lower()
    cat = str(fm.get("category", "News"))
    tags = fm.get("tags") or []
    title = str(tags[0] if tags else fm.get("title", ""))
    g1, g2 = _GRAD.get(game) or _GRAD.get(cat.lower()) or _GRAD["_default"]
    c1, c2 = _hex(g1), _hex(g2)
    img = Image.new("RGB", (CW, CH), (15, 17, 22))
    d = ImageDraw.Draw(img)
    for y in range(CH):
        for band in range(0, CW, 8):
            t = (band / CW * 0.6 + y / CH * 0.4)
            c = tuple(int(c2[i] + (c1[i] - c2[i]) * t) for i in range(3))
            d.rectangle([band, y, band + 8, y + 1], fill=c)
    img = Image.blend(img, Image.new("RGB", (CW, CH), (10, 11, 15)), 0.34)
    d = ImageDraw.Draw(img)
    eyebrow = ImageFont.truetype(FONTS["sans"], 30)
    head = ImageFont.truetype(FONTS["serif"], 84 if len(title) <= 26 else 66)
    mark = ImageFont.truetype(FONTS["sans"], 26)
    d.rounded_rectangle([70, 92, 79, 128], radius=4, fill=(255, 61, 70))
    d.text((96, 95), cat.upper(), font=eyebrow, fill=(255, 255, 255))
    words, lines, cur = title.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=head) > CW - 140 and cur:
            lines.append(cur); cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > 3:
        last = lines[2]
        while last and d.textlength(last + "…", font=head) > CW - 140:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines = lines[:2] + [last + "…"]
    lh = head.size + 10
    y = CH - 88 - len(lines) * lh
    for ln in lines:
        d.text((70, y), ln, font=head, fill=(240, 242, 246)); y += lh
    d.text((CW - 40 - d.textlength("BOSS KG", font=mark), CH - 52), "BOSS KG",
           font=mark, fill=(210, 214, 222))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=88, optimize=True)


def _set_cover(text: str, cover_rel: str, credit: str = "") -> str:
    """Set `cover` and `coverCredit` (who the image belongs to; empty = the cited source's own
    image, which the page credits as 'Image: <sourceName>')."""
    if re.search(r"(?m)^cover:\s*.*$", text):
        text = re.sub(r"(?m)^cover:\s*.*$", f'cover: "{cover_rel}"', text, count=1)
    else:
        text = re.sub(r"(?m)^(date:.*)$", f'cover: "{cover_rel}"\n\\1', text, count=1)
    text = re.sub(r"(?m)^coverCredit:.*\n", "", text)
    if credit:
        text = re.sub(r"(?m)^(cover:.*)$", f'\\1\ncoverCredit: "{credit}"', text, count=1)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="")
    ap.add_argument("--all-missing", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    files = [ART_DIR / f"{a.slug}.md"] if a.slug else sorted(ART_DIR.glob("*.md"))
    made = 0
    for path in files:
        if not path.exists():
            print(f"   missing: {path.name}", flush=True); continue
        text, fm = _parse(path)
        if str(fm.get("cover", "")).strip() and not a.force:
            continue
        slug = path.stem
        out = COVERS / f"{slug}.jpg"
        src_url = str(fm.get("sourceUrl", "")).strip()
        how, credit = None, ""
        if src_url:
            img_url = _og_image_url(src_url)
            if img_url:
                data = _download(img_url)
                if data and _cover_from_bytes(data, out):
                    how = f"scraped {img_url.split('/')[2]}"
        if not how:                                   # no usable press image -> the game's key art
            art, gname = _game_art(fm)
            if art and _cover_from_bytes(art.read_bytes(), out):
                how, credit = f"game art {art.name}", f"{gname} official art"
        if not how:                                   # last resort: our branded card, credited to us
            _cover_branded(fm, out)
            how, credit = "branded card (no source image, no game art)", "BOSS KG"
            try:
                from core import notify
                notify.telegram(f"🖼 Article \"{fm.get('title', slug)}\" got a plain branded cover: "
                                "its source had no usable image and there is no game art for "
                                f"'{fm.get('game', '')}'. Add art to reels/assets/game-art/<game>/.")
            except Exception:
                pass
        path.write_text(_set_cover(text, f"/covers/{slug}.jpg", credit), encoding="utf-8")
        print(f"   {slug}: {how}", flush=True)
        made += 1
    print(f"[article-cover] set {made} cover(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
