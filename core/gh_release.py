"""GitHub Release footage store.

Large gameplay clips (>100MB, up to 2GB) can't live in the repo, so they're
uploaded as assets on a GitHub Release (tag `footage`). Assets are named
"<game>__<whatever>.mp4"; this module lists the ones for a game and downloads a
chosen asset to a local cache at render time. All calls FAIL-OPEN (return [] or
None) so a network/API hiccup just falls back to local clips or AI stills.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import requests

from core.config import CONFIG

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}

# A tiny JSON asset on the footage release recording which clips have already
# been used for a GAMEPLAY reel, so the picker can prefer fresh footage. The
# clips themselves are NEVER deleted — they stay available for commentary reels.
USED_LEDGER_ASSET = "_used_gameplay.json"


def _cfg() -> dict[str, Any]:
    return CONFIG.reels.get("footage", {}) or {}


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    tok = _token()  # env token (CI) or the local gh login — authenticated reads
    if tok:          # get the 5000/hr limit instead of 60/hr unauthenticated
        h["Authorization"] = f"Bearer {tok}"
    return h


def list_assets(gamekey: str) -> list[dict[str, str]]:
    """Return [{name, url}] release assets whose name starts with '<gamekey>__'."""
    cfg = _cfg()
    if not cfg.get("use_releases"):
        return []
    repo = cfg.get("release_repo")
    tag = cfg.get("release_tag", "footage")
    if not repo:
        return []
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
            headers=_headers(), timeout=30,
        )
        if r.status_code != 200:
            return []
        assets = r.json().get("assets", []) or []
    except Exception:
        return []
    prefix = f"{gamekey}__"
    out = []
    for a in assets:
        name = a.get("name", "")
        if name.startswith(prefix) and Path(name).suffix.lower() in VIDEO_EXTS:
            out.append({"name": name, "url": a.get("browser_download_url", "")})
    return [a for a in out if a["url"]]


def list_release_assets(tag: str) -> list[dict[str, str]]:
    """Return [{name, url}] for ALL assets on the given release tag (any type)."""
    cfg = _cfg()
    repo = cfg.get("release_repo")
    if not repo or not tag:
        return []
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
            headers=_headers(), timeout=30,
        )
        if r.status_code != 200:
            return []
        assets = r.json().get("assets", []) or []
    except Exception:
        return []
    return [
        {"name": a.get("name", ""), "url": a.get("browser_download_url", ""),
         "id": a.get("id"), "created_at": a.get("created_at", "")}
        for a in assets if a.get("browser_download_url")
    ]


def delete_asset(asset_id: Any, repo: Optional[str] = None) -> bool:
    """Delete a release asset by id (used to advance the ready-reels queue)."""
    repo = repo or _cfg().get("release_repo")
    if not repo or asset_id is None:
        return False
    try:
        r = requests.delete(
            f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}",
            headers=_headers(), timeout=30,
        )
        return r.status_code in (204, 200)
    except Exception:
        return False


# --------------------------------------------------------- used-clip ledger

_TOKEN_CACHE: Optional[str] = None
_TOKEN_RESOLVED = False


def _token() -> Optional[str]:
    """A GitHub token: env first (CI), then the local gh login. Cached so we
    don't spawn `gh auth token` on every request."""
    global _TOKEN_CACHE, _TOKEN_RESOLVED
    if _TOKEN_RESOLVED:
        return _TOKEN_CACHE
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not tok:
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                tok = out.stdout.strip()
        except Exception:
            tok = None
    _TOKEN_CACHE = tok.strip() if tok else None
    _TOKEN_RESOLVED = True
    return _TOKEN_CACHE


def _release() -> Optional[dict[str, Any]]:
    """The footage release object (id + upload_url), or None. NOTE: the asset
    list on this (tags) endpoint is CDN-cached and can be stale — use
    _fresh_assets() for an up-to-date asset list."""
    cfg = _cfg()
    repo = cfg.get("release_repo")
    tag = cfg.get("release_tag", "footage")
    if not repo:
        return None
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
            headers=_headers(), timeout=30,
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


_ASSETS_CACHE: dict[Any, list[dict[str, Any]]] = {}


def _fresh_assets(repo: str, release_id: Any) -> list[dict[str, Any]]:
    """ALL current assets via the per-release endpoint (paginated — the release
    can have thousands of quote-image assets), cached per process. Consistent
    (unlike the tags endpoint, which is cached and lags newly written assets)."""
    if not repo or release_id is None:
        return []
    if release_id in _ASSETS_CACHE:
        return _ASSETS_CACHE[release_id]
    out: list[dict[str, Any]] = []
    try:
        for page in range(1, 300):
            r = requests.get(
                f"https://api.github.com/repos/{repo}/releases/{release_id}/assets"
                f"?per_page=100&page={page}", headers=_headers(), timeout=30)
            if r.status_code != 200:
                break
            chunk = r.json() or []
            out += chunk
            if len(chunk) < 100:
                break
    except Exception:
        pass
    _ASSETS_CACHE[release_id] = out
    return out


def _invalidate_assets_cache() -> None:
    _ASSETS_CACHE.clear()
    global _IMG_RELEASES, _QIMG_INDEX
    _IMG_RELEASES = None
    _QIMG_INDEX = None


# ---- quote-image releases (GitHub caps each release at 1000 assets, so the
#      7k+ quote backdrops are sharded across the footage release + overflow
#      releases tagged qimg-01, qimg-02, ...). Reads aggregate across all of them.

_IMG_RELEASES: Optional[list[dict[str, Any]]] = None
_QIMG_INDEX: Optional[dict[str, str]] = None


def _list_all_releases(repo: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        for page in range(1, 50):
            r = requests.get(
                f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
                headers=_headers(), timeout=30)
            if r.status_code != 200:
                break
            chunk = r.json() or []
            out += chunk
            if len(chunk) < 100:
                break
    except Exception:
        pass
    return out


def _image_releases() -> list[dict[str, Any]]:
    """[{tag, id}] of releases that hold quote images: the footage release first,
    then overflow releases tagged qimg-NN (ascending). Cached per process."""
    global _IMG_RELEASES
    if _IMG_RELEASES is not None:
        return _IMG_RELEASES
    repo = _cfg().get("release_repo")
    base = _cfg().get("release_tag", "footage")
    res: list[dict[str, Any]] = []
    if repo:
        for rel in _list_all_releases(repo):
            t = str(rel.get("tag_name", ""))
            if t == base or re.match(r"^qimg-\d+$", t):
                res.append({"tag": t, "id": rel.get("id")})
        res.sort(key=lambda r: (0 if r["tag"] == base else 1, r["tag"]))
    if not res:  # fail-open to just the footage release
        rel = _release()
        if rel:
            res = [{"tag": base, "id": rel.get("id")}]
    _IMG_RELEASES = res
    return res


def _quote_image_index() -> dict[str, str]:
    """{asset_name: release_tag} for every qimg__ asset across all image releases.
    Lets the pool list backdrops and build the right download URL per shard."""
    global _QIMG_INDEX
    if _QIMG_INDEX is not None:
        return _QIMG_INDEX
    repo = _cfg().get("release_repo")
    idx: dict[str, str] = {}
    for rel in _image_releases():
        for a in _fresh_assets(repo, rel.get("id")):
            n = str(a.get("name", ""))
            if n.startswith("qimg__"):
                idx[n] = rel["tag"]
    _QIMG_INDEX = idx
    return idx


def used_clips() -> set[str]:
    """Clip ids already used for a gameplay reel (fail-open to empty set)."""
    rel = _release()
    if not rel:
        return set()
    repo = _cfg().get("release_repo")
    for a in _fresh_assets(repo, rel.get("id")):
        if a.get("name") == USED_LEDGER_ASSET:
            try:
                # Read by unique asset ID, not browser_download_url: the latter is
                # CDN-cached by <tag>/<name> and serves STALE content after a
                # delete+reupload. The asset-id endpoint reflects the new upload.
                r = requests.get(
                    f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}",
                    headers={**_headers(), "Accept": "application/octet-stream"},
                    timeout=30)
                if r.status_code == 200:
                    return set((r.json() or {}).get("used", []) or [])
            except Exception:
                return set()
    return set()


def _write_ledger(used: set[str]) -> bool:
    """Replace the ledger asset with the given set. Needs a write token."""
    token = _token()
    cfg = _cfg()
    repo = cfg.get("release_repo")
    rel = _release()
    if not token or not repo or not rel:
        return False
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    for a in _fresh_assets(repo, rel.get("id")):  # delete old copy (no in-place)
        if a.get("name") == USED_LEDGER_ASSET:
            try:
                requests.delete(
                    f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}",
                    headers=h, timeout=30)
            except Exception:
                pass
    upload_url = (rel.get("upload_url", "") or "").split("{")[0]
    if not upload_url:
        return False
    body = json.dumps({"used": sorted(used)}, ensure_ascii=False).encode("utf-8")
    try:
        r = requests.post(f"{upload_url}?name={USED_LEDGER_ASSET}",
                          headers={**h, "Content-Type": "application/json"},
                          data=body, timeout=60)
        return r.ok
    except Exception:
        return False


# ---------------------------------------------------- quote assets (images/music)

QIMAGE_MANIFEST = "_quote_images.json"
QIMAGE_USED = "_quote_images_used.json"


def asset_download_url(name: str) -> str:
    """Public download URL for a release asset, by name. Quote backdrops can live
    on an overflow release (qimg-NN), so resolve those to the shard that holds
    them; everything else lives on the footage release."""
    cfg = _cfg()
    repo = cfg.get("release_repo")
    if not repo:
        return ""
    tag = cfg.get("release_tag", "footage")
    if str(name).startswith("qimg__"):
        tag = _quote_image_index().get(name, tag)
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


def _read_json_asset(name: str):
    """Read a small JSON release asset by name (by unique id, not the cached URL)."""
    rel = _release()
    if not rel:
        return None
    repo = _cfg().get("release_repo")
    for a in _fresh_assets(repo, rel.get("id")):
        if a.get("name") == name:
            try:
                r = requests.get(
                    f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}",
                    headers={**_headers(), "Accept": "application/octet-stream"},
                    timeout=30)
                return r.json() if r.status_code == 200 else None
            except Exception:
                return None
    return None


def _write_json_asset(name: str, obj) -> bool:
    token = _token()
    cfg = _cfg()
    repo = cfg.get("release_repo")
    rel = _release()
    if not token or not repo or not rel:
        return False
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    for a in _fresh_assets(repo, rel.get("id")):
        if a.get("name") == name:
            try:
                requests.delete(
                    f"https://api.github.com/repos/{repo}/releases/assets/{a['id']}",
                    headers=h, timeout=30)
            except Exception:
                pass
    upload_url = (rel.get("upload_url", "") or "").split("{")[0]
    if not upload_url:
        return False
    try:
        r = requests.post(
            f"{upload_url}?name={name}",
            headers={**h, "Content-Type": "application/json"},
            data=json.dumps(obj, ensure_ascii=False).encode("utf-8"), timeout=60)
        if r.ok:
            _invalidate_assets_cache()
        return r.ok
    except Exception:
        return False


def quote_image_pool() -> dict[str, Any]:
    """{game: [asset_name]} of synced quote backdrops, derived by listing the
    qimg__<game>.<file> assets across the footage release AND every qimg-NN
    overflow release (no fragile manifest)."""
    pool: dict[str, list[str]] = {}
    for name in _quote_image_index():
        game = name[len("qimg__"):].split(".", 1)[0]
        pool.setdefault(game, []).append(name)
    return pool


def used_quote_images() -> set[str]:
    return set((_read_json_asset(QIMAGE_USED) or {}).get("used", []) or [])


def mark_quote_image(name: str) -> bool:
    if not name:
        return False
    cur = used_quote_images()
    if name in cur:
        return True
    cur.add(name)
    return _write_json_asset(QIMAGE_USED, {"used": sorted(cur)})


def reset_quote_images() -> bool:
    return _write_json_asset(QIMAGE_USED, {"used": []})


QUOTE_THEMES_ASSET = "_quote_themes.json"


def _today_ph() -> str:
    """Today's date in PH time (UTC+8) — the quote schedule fires at PH primes."""
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))


def pick_quote_theme(targets: Optional[dict[str, int]] = None) -> str:
    """Pick the quote theme whose daily target is furthest from being met, so a
    set of generic (un-themed) external triggers still lands the desired per-day
    mix (e.g. 2 'gameplay' + 2 'life'). Ties broken randomly. Fail-open to random."""
    targets = targets or {"gameplay": 2, "life": 2}
    try:
        led = _read_json_asset(QUOTE_THEMES_ASSET) or {}
        counts = led.get("counts", {}) if led.get("date") == _today_ph() else {}
        deficits = {t: n - int(counts.get(t, 0)) for t, n in targets.items()}
        mx = max(deficits.values())
        pool = [t for t, d in deficits.items() if d == mx] if mx > 0 else list(targets)
        return random.choice(pool)
    except Exception:
        return random.choice(list(targets))


def record_quote_theme(theme: str) -> bool:
    """Increment today's count for `theme` in the daily ledger (resets on new day)."""
    if not theme:
        return False
    led = _read_json_asset(QUOTE_THEMES_ASSET) or {}
    today = _today_ph()
    counts = dict(led.get("counts", {})) if led.get("date") == today else {}
    counts[theme] = int(counts.get(theme, 0)) + 1
    return _write_json_asset(QUOTE_THEMES_ASSET, {"date": today, "counts": counts})


def quote_music_pool() -> list[str]:
    rel = _release()
    if not rel:
        return []
    repo = _cfg().get("release_repo")
    return [a["name"] for a in _fresh_assets(repo, rel.get("id"))
            if str(a.get("name", "")).startswith("qmusic")]


def add_used_clip(clip_id: str) -> bool:
    """Record clip_id as used for a gameplay reel."""
    if not clip_id:
        return False
    cur = used_clips()
    if clip_id in cur:
        return True
    cur.add(clip_id)
    return _write_ledger(cur)


def reset_used(prefix: Optional[str] = None) -> bool:
    """Clear the ledger; with prefix '<game>', clear only that game's entries
    (used to restart the cycle once every clip for a game has been shown)."""
    cur = used_clips()
    cur = {c for c in cur if not c.startswith(f"{prefix}__")} if prefix else set()
    return _write_ledger(cur)


def download(asset: dict[str, str], cache_dir: Path) -> Optional[Path]:
    """Download an asset into cache_dir (cached by name). Returns Path or None."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / asset["name"]
    if dest.exists() and dest.stat().st_size > 0:
        return dest  # already cached this run/job
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(
            asset["url"], headers=_headers(), stream=True, timeout=600
        ) as r:
            if r.status_code != 200:
                return None
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):  # 1 MB chunks
                    if chunk:
                        fh.write(chunk)
        tmp.replace(dest)
        return dest
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None
