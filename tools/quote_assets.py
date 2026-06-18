"""Sync quote-card backdrops + quote music to the GitHub Release, then delete the
local originals (per the user's "bring to cloud, delete local" rule).

Images are DOWNSCALED + re-encoded to JPEG (they're only darkened backdrops, so
this is visually identical but ~10x smaller, making 49GB of PNGs practical to
host + download in CI). A manifest (`_quote_images.json`, {game: [asset_names]})
lets the cloud pick a backdrop without listing thousands of assets. Resumable:
anything already in the manifest is skipped (and its local copy deleted).

  python tools/quote_assets.py images   # sync + delete local images
  python tools/quote_assets.py music    # sync + delete local quote music
  python tools/quote_assets.py all
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core.config import CONFIG, ROOT  # noqa: E402
from tools import footage  # reuse _token/_release/_h/_repo/_tag/_gh_name  # noqa: E402

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
MANIFEST = "_quote_images.json"
IMG_PREFIX = "qimg"
MUSIC_PREFIX = "qmusic"
MAX_DIM = 1620          # downscale backdrops to this long edge (card is 1080 wide)
JPEG_Q = 90


def _api_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _existing_asset_names(token, rid, prefix) -> set:
    """ALL release asset names with `prefix` (paginated), for resume-skip."""
    repo = footage._repo()
    names = set()
    for page in range(1, 300):
        r = requests.get(
            f"{footage.API}/repos/{repo}/releases/{rid}/assets?per_page=100&page={page}",
            headers=_api_headers(token), timeout=30)
        if r.status_code != 200:
            break
        chunk = r.json() or []
        names |= {a["name"] for a in chunk if str(a.get("name", "")).startswith(prefix)}
        if len(chunk) < 100:
            break
    return names


def _jpeg_bytes(path: Path) -> bytes | None:
    """Downscale to <=MAX_DIM long edge + JPEG. None on failure."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        w, h = im.size
        if max(w, h) > MAX_DIM:
            s = MAX_DIM / max(w, h)
            im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=JPEG_Q, optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"  jpeg failed {path.name}: {e!r}", flush=True)
        return None


def _upload_bytes(up_url, token, name, data, ct) -> bool:
    for attempt in range(4):
        try:
            r = requests.post(f"{up_url}?name={name}",
                              headers={**_api_headers(token), "Content-Type": ct},
                              data=data, timeout=300)
            if r.ok:
                return True
            if r.status_code in (403, 422) and "already_exists" in r.text:
                return True
            if r.status_code in (403, 429):  # rate/secondary limit -> back off
                time.sleep(20 * (attempt + 1))
                continue
            print(f"  upload {name} -> {r.status_code} {r.text[:120]}", flush=True)
            return False
        except Exception as e:
            print(f"  upload {name} err: {e!r}", flush=True)
            time.sleep(5)
    return False


def sync_images() -> None:
    token = footage._token()
    rel = footage._release(token)
    up = rel["upload_url"].split("{")[0]
    done = _existing_asset_names(token, rel["id"], "qimg__")  # resume: skip uploaded
    base = ROOT / (CONFIG.raw().get("quotes", {}) or {}).get("image_dir", "assets/images")
    up_n = del_n = fail = 0
    for gd in sorted(p for p in base.iterdir() if p.is_dir()):
        game = gd.name
        for img in sorted(gd.iterdir()):
            if not img.is_file() or img.suffix.lower() not in IMG_EXTS:
                continue
            name = footage._gh_name(IMG_PREFIX, f"{game}.{img.stem}.jpg")
            if name in done:
                try:
                    img.unlink(); del_n += 1
                except Exception:
                    pass
                continue
            data = _jpeg_bytes(img)
            if data and _upload_bytes(up, token, name, data, "image/jpeg"):
                done.add(name); up_n += 1
                try:
                    img.unlink(); del_n += 1
                except Exception:
                    pass
            else:
                fail += 1
            if up_n and up_n % 100 == 0:
                print(f"... uploaded {up_n}, local-deleted {del_n}, failed {fail}", flush=True)
    print(f"DONE images: uploaded {up_n}, local-deleted {del_n}, failed {fail}")


def sync_music() -> None:
    token = footage._token()
    rel = footage._release(token)
    up = rel["upload_url"].split("{")[0]
    existing = {a["name"] for a in rel.get("assets", [])}
    mdir = ROOT / (CONFIG.raw().get("quotes", {}) or {}).get(
        "music_dir", "assets/background-music-for-quotes-videos")
    if not mdir.exists():
        print("no quote-music dir"); return
    up_n = del_n = 0
    for f in sorted(mdir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        name = footage._gh_name(MUSIC_PREFIX, f.name)
        ok = name in existing or _upload_bytes(up, token, name, f.read_bytes(),
                                               "audio/mpeg")
        if ok:
            up_n += 1
            try:
                f.unlink(); del_n += 1
            except Exception:
                pass
    print(f"DONE music: uploaded {up_n}, local-deleted {del_n}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("music", "all"):
        sync_music()
    if what in ("images", "all"):
        sync_images()
