"""Find a great foreground CHARACTER render on the web and add it to the thumbnail
library (reels/assets/game-character/<game>/), so the long-form thumbnail pipeline has
a clean, front-facing hero to composite — better than a murky gameplay cutout.

Pipeline: web image-search (or explicit --url) -> download candidates -> rembg-clean any
that aren't already transparent -> vision-rate each for "clearly THIS character, front-
facing, high-res, clean cutout" (core.vision.rate_character_render) -> keep the best.

    python tools/find_character.py --game ff7remake --character "Cloud Strife"
    python tools/find_character.py --game ff7remake --character "Cloud Strife" --save
    python tools/find_character.py --game re4 --character "Leon Kennedy" --url https://.../leon.png --save

Downloads copyrighted character art — intended for the user's own thumbnails, run on
demand. Fails open: no network / rembg / vision key -> it just reports what it could.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import cutout, vision  # noqa: E402

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36"}


# Behind an intercepting HTTPS proxy (e.g. Avast Web Shield) Python's default certifi
# bundle doesn't trust the proxy's cert. truststore makes Python use the OS trust store
# (where that cert legitimately lives), so verification stays ON and requests succeed.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    _truststore = None


def _get(url, **kw):
    """Verified GET (TLS verification stays on). Returns a requests.Response."""
    import requests
    kw.setdefault("headers", _UA)
    kw.setdefault("timeout", 25)
    return requests.get(url, **kw)


def _game_display(game: str) -> str:
    try:
        from core.config import CONFIG
        return str((CONFIG.reels.get("game_names", {}) or {}).get(game, game))
    except Exception:
        return game


def search_image_urls(query: str, n: int = 10) -> list:
    """Best-effort DuckDuckGo image search -> direct image URLs (no API key), Bing as a
    fallback. Fails open to []."""
    out: list = []
    try:                                             # --- DuckDuckGo i.js (returns JSON) ---
        html = _get("https://duckduckgo.com/", params={"q": query, "iax": "images",
                                                       "ia": "images"}).text
        m = (re.search(r'vqd=["\']([\d-]+)["\']', html) or re.search(r'vqd=([\d-]+)\&', html)
             or re.search(r'"vqd":"([\d-]+)"', html))
        if m:
            r = _get("https://duckduckgo.com/i.js",
                     params={"l": "us-en", "o": "json", "q": query, "vqd": m.group(1),
                             "f": ",,,", "p": "1"},
                     headers={**_UA, "Referer": "https://duckduckgo.com/"})
            for it in (r.json().get("results") or []):
                u = it.get("image") or ""
                if u.startswith("http") and u not in out and not u.lower().endswith(".gif"):
                    out.append(u)
    except Exception as e:
        print(f"[find] DDG image search failed ({e!r})", flush=True)
    if len(out) < n:                                 # --- Bing async fallback ---
        try:
            html = _get("https://www.bing.com/images/async?q="
                        + urllib.parse.quote(query) + f"&count={n * 3}&first=1").text
            for u in (re.findall(r'murl&quot;:&quot;(.*?)&quot;', html)
                      or re.findall(r'"murl":"(.*?)"', html)):
                u = u.replace("\\/", "/").replace("&amp;", "&")
                if u.startswith("http") and u not in out and not u.lower().endswith(".gif"):
                    out.append(u)
        except Exception as e:
            print(f"[find] Bing image search failed ({e!r})", flush=True)
    if not out:
        print("[find] no search results — pass --url <direct image url> instead.", flush=True)
    return out[:n]


def _download(url: str, dest: Path):
    try:
        import requests
        from PIL import Image
        r = requests.get(url, headers=_UA, timeout=30)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")
        if img.width < 300 or img.height < 300:      # too small to be a hero render
            return None, None
        dest.write_bytes(r.content)
        return dest, img
    except Exception as e:
        print(f"[find] download failed {url[:70]} ({e!r})", flush=True)
        return None, None


def _prep_candidate(raw_path: Path, img, work: Path, i: int):
    """Return a clean transparent RGBA (rembg-cut if the source isn't already cut out)."""
    from PIL import Image
    from agents.thumbnail import _autocrop_alpha
    alpha = img.split()[-1]
    opaque = alpha.getextrema()[0] >= 250          # no transparency -> needs bg removal
    if opaque:
        cut = cutout.cutout(raw_path, work / f"cut_{i}.png", model="u2net_human_seg") \
            or cutout.cutout(raw_path, work / f"cut_{i}.png", model="isnet-general-use")
        if not cut:
            return None
        img = Image.open(cut).convert("RGBA")
    return _autocrop_alpha(img)


def _judge_jpeg(rgba, work: Path, i: int) -> Path:
    """Flatten onto neutral grey + save JPEG so the vision judge (media_type jpeg) sees it."""
    from PIL import Image
    card = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
    card.alpha_composite(rgba)
    p = work / f"judge_{i}.jpg"
    card.convert("RGB").save(p, "JPEG", quality=90)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", required=True)
    ap.add_argument("--character", required=True)
    ap.add_argument("--url", action="append", default=[], help="explicit image URL(s)")
    ap.add_argument("--dir", default=None, help="rank LOCAL image files in this folder (no web)")
    ap.add_argument("--search", default=None, help="override the search query")
    ap.add_argument("--max", type=int, default=8)
    ap.add_argument("--save", action="store_true", help="copy the winner into the library")
    args = ap.parse_args()

    work = ROOT / "output" / ".charfind" / args.game
    work.mkdir(parents=True, exist_ok=True)

    # Candidate sources: LOCAL folder (--dir, no web) > explicit --url(s) > web search.
    from PIL import Image
    local: list = []
    if args.dir:
        exts = {".png", ".jpg", ".jpeg", ".webp"}
        local = [p for p in sorted(Path(args.dir).iterdir())
                 if p.suffix.lower() in exts] if Path(args.dir).is_dir() else []
        print(f"[find] {args.character} — {len(local)} local file(s) in {args.dir}")
    else:
        query = args.search or f"{_game_display(args.game)} {args.character} transparent png render"
        urls = list(args.url) or search_image_urls(query, args.max)
        print(f"[find] {args.character} — {len(urls)} candidate URL(s)")
        if not urls:
            print("[find] nothing to try. Pass --url <direct image url> or --dir <folder>.")
            return 1

    ranked = []
    items = local or urls[: args.max]
    for i, item in enumerate(items):
        if local:
            try:
                img = Image.open(item).convert("RGBA")
                raw = work / f"raw_{i}{Path(item).suffix}"
                raw.write_bytes(Path(item).read_bytes())
            except Exception as e:
                print(f"[find] skip {item} ({e!r})", flush=True)
                continue
            u = str(item)
        else:
            raw, img = _download(item, work / f"raw_{i}")
            u = item
            if raw is None:
                continue
        clean = _prep_candidate(raw, img, work, i)
        if clean is None:
            continue
        clean_path = work / f"cand_{i}.png"
        clean.save(clean_path)
        r = vision.rate_character_render(_judge_jpeg(clean, work, i), subject=args.character)
        score = r["score"] if r else 0.0
        tag = (f"subj={r['is_subject']:.0f} front={r['front_facing']:.0f} q={r['quality']:.0f} "
               f"frame={r['thumbnail_framing']:.0f}" if r else "no-vision")
        print(f"  cand_{i} {score} {tag} | {r['verdict'] if r else ''} | {u[:60]}")
        ranked.append((score, clean_path, u, r))

    if not ranked:
        print("[find] no usable candidates.")
        return 1
    ranked.sort(key=lambda t: t[0], reverse=True)
    best = ranked[0]
    print(f"\n[find] BEST {best[1].name} score {best[0]} <- {best[2][:70]}")

    if args.save:
        dest_dir = ROOT / "reels/assets/game-character" / args.game
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.character} - web.png"
        import shutil
        shutil.copy(best[1], dest)
        print(f"[find] saved -> {dest}")
    else:
        print("[find] dry run — re-run with --save to add the winner to the library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
