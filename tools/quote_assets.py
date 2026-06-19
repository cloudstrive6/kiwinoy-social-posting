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
import re
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
    return _upload_to(up_url, token, name, data, ct) == "ok"


def _upload_to(up_url, token, name, data, ct) -> str:
    """Upload one asset. Returns 'ok', 'full' (release hit GitHub's 1000-asset
    cap -> caller should roll to the next shard), or 'fail'."""
    for attempt in range(4):
        try:
            r = requests.post(f"{up_url}?name={name}",
                              headers={**_api_headers(token), "Content-Type": ct},
                              data=data, timeout=300)
            if r.ok:
                return "ok"
            if r.status_code in (403, 422) and "already_exists" in r.text:
                return "ok"
            if r.status_code == 422 and "file_count" in r.text:
                return "full"
            if r.status_code in (403, 429):  # rate/secondary limit -> back off
                time.sleep(20 * (attempt + 1))
                continue
            print(f"  upload {name} -> {r.status_code} {r.text[:120]}", flush=True)
            return "fail"
        except Exception as e:
            print(f"  upload {name} err: {e!r}", flush=True)
            time.sleep(5)
    return "fail"


QIMG_CAP = 995  # leave headroom under GitHub's hard 1000-assets-per-release limit


def _asset_count(token, rid) -> int:
    """Total assets on a release (paginated)."""
    repo = footage._repo()
    n = 0
    for page in range(1, 400):
        r = requests.get(
            f"{footage.API}/repos/{repo}/releases/{rid}/assets?per_page=100&page={page}",
            headers=_api_headers(token), timeout=30)
        if r.status_code != 200:
            break
        chunk = r.json() or []
        n += len(chunk)
        if len(chunk) < 100:
            break
    return n


def _image_release_shards(token) -> list[dict]:
    """[{tag, id, up}] holding quote images: footage release first, then qimg-NN
    overflow shards ascending. Creates none here."""
    base = footage._tag()
    res = []
    for rel in footage._all_releases(token):
        t = str(rel.get("tag_name", ""))
        if t == base or re.match(r"^qimg-\d+$", t):
            res.append({"tag": t, "id": rel["id"],
                        "up": rel["upload_url"].split("{")[0]})
    res.sort(key=lambda r: (0 if r["tag"] == base else 1, r["tag"]))
    return res


def _next_qimg_tag(shards) -> str:
    nums = [int(s["tag"].split("-")[1]) for s in shards if s["tag"].startswith("qimg-")]
    return f"qimg-{(max(nums) + 1) if nums else 1:02d}"


def sync_images() -> None:
    token = footage._token()
    shards = _image_release_shards(token)
    if not shards:  # first ever run: fall back to creating/loading the footage release
        rel = footage._release(token)
        shards = [{"tag": footage._tag(), "id": rel["id"],
                   "up": rel["upload_url"].split("{")[0]}]
    # resume: every qimg name already uploaded across ALL shards
    done = set()
    for s in shards:
        done |= _existing_asset_names(token, s["id"], "qimg__")
    counts = {s["tag"]: _asset_count(token, s["id"]) for s in shards}

    def current_target():
        """The shard we're currently filling (first with room), creating a new
        qimg-NN overflow release when every existing shard is full."""
        for s in shards:
            if counts[s["tag"]] < QIMG_CAP:
                return s
        tag = _next_qimg_tag(shards)
        rel = footage._get_or_create_release(
            token, tag, f"Quote backdrops {tag}",
            "Overflow quote-card backdrops (GitHub caps releases at 1000 assets).")
        s = {"tag": tag, "id": rel["id"], "up": rel["upload_url"].split("{")[0]}
        shards.append(s)
        counts[tag] = _asset_count(token, rel["id"])
        return s

    base = ROOT / (CONFIG.raw().get("quotes", {}) or {}).get("image_dir", "assets/images")
    up_n = del_n = fail = 0
    tgt = shards[0]
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
            if not data:
                fail += 1
                continue
            ok = False
            for _ in range(len(shards) + 3):  # roll forward across shards as needed
                tgt = current_target()
                res = _upload_to(tgt["up"], token, name, data, "image/jpeg")
                if res == "ok":
                    counts[tgt["tag"]] += 1
                    ok = True
                    break
                if res == "full":
                    counts[tgt["tag"]] = QIMG_CAP + 1  # mark full -> pick/create next
                    continue
                break  # genuine failure
            if ok:
                done.add(name); up_n += 1
                try:
                    img.unlink(); del_n += 1
                except Exception:
                    pass
            else:
                fail += 1
            if up_n and up_n % 100 == 0:
                print(f"... uploaded {up_n} (on {tgt['tag']}), "
                      f"local-deleted {del_n}, failed {fail}", flush=True)
    print(f"DONE images: uploaded {up_n}, local-deleted {del_n}, failed {fail}; "
          f"shards: {[s['tag'] for s in shards]}")


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
    # Top-level files = universal/fallback (qmusic__<file>). Files inside a
    # per-game subfolder = tagged for that game (qmusic__<game>__<file>) so the
    # reel can match music to the footage's universe.
    for f in sorted(mdir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        rel = f.relative_to(mdir)
        tag = rel.parts[0] if len(rel.parts) > 1 else ""   # subfolder = game tag
        stem = f"{tag}__{f.name}" if tag else f.name
        name = footage._gh_name(MUSIC_PREFIX, stem)
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
