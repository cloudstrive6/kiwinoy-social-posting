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
    """Return [{name, url}] clip assets named '<gamekey>__*', aggregated across the
    footage release AND every footage-NN overflow shard (GitHub caps a release at
    1000 assets, so clips spill into footage-02, footage-03, ...)."""
    cfg = _cfg()
    if not cfg.get("use_releases"):
        return []
    repo = cfg.get("release_repo")
    if not repo:
        return []
    prefix = f"{gamekey}__"
    out = []
    for rel in _footage_releases():
        for a in _fresh_assets(repo, rel.get("id")):
            name = str(a.get("name", ""))
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
         "id": a.get("id"), "created_at": a.get("created_at", ""),
         "size": a.get("size", 0)}
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
    global _IMG_RELEASES, _QIMG_INDEX, _FOOTAGE_RELEASES
    _IMG_RELEASES = None
    _QIMG_INDEX = None
    _FOOTAGE_RELEASES = None


_FOOTAGE_RELEASES: Optional[list[dict[str, Any]]] = None


def _footage_releases() -> list[dict[str, Any]]:
    """[{tag, id}] of releases that hold gameplay CLIPS: the footage release first,
    then overflow shards tagged footage-NN (ascending). Cached per process."""
    global _FOOTAGE_RELEASES
    if _FOOTAGE_RELEASES is not None:
        return _FOOTAGE_RELEASES
    repo = _cfg().get("release_repo")
    base = _cfg().get("release_tag", "footage")
    res: list[dict[str, Any]] = []
    if repo:
        for rel in _list_all_releases(repo):
            t = str(rel.get("tag_name", ""))
            if t == base or re.match(r"^footage-\d+$", t):
                res.append({"tag": t, "id": rel.get("id")})
        res.sort(key=lambda r: (0 if r["tag"] == base else 1, r["tag"]))
    if not res:
        rel = _release()
        if rel:
            res = [{"tag": base, "id": rel.get("id")}]
    _FOOTAGE_RELEASES = res
    return res


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


# PER-PLATFORM used-clip ledger (per user 2026-07-30): each platform tracks its own
# used clips so a clip can appear ONCE on each platform independently — a clip used on
# TikTok is still fresh for the feed/YouTube, and a paused YouTube doesn't have its
# slate consumed by IG/TikTok. (FB+IG+YouTube still share ONE feed render, so a feed
# clip is marked on all its actual targets together — see orchestrator.)
LEDGER_PLATFORMS = ("facebook", "instagram", "youtube", "tiktok", "threads")
# Migration: the OLD ledger was a flat list (global). Those clips were posted across
# the feed (FB/IG) + TikTok (+ Threads before it paused) while YouTube was paused, so
# seed them as used on those platforms and leave YOUTUBE fresh (its whole point).
_LEGACY_SEED_PLATFORMS = ("facebook", "instagram", "tiktok", "threads")


def _parse_ledger(payload: dict) -> dict[str, set[str]]:
    """Normalize a ledger payload into {platform: set(ids)}. Accepts the NEW per-platform
    dict form and the OLD flat-list form (migrated by seeding the legacy platforms)."""
    used = (payload or {}).get("used", {})
    out: dict[str, set[str]] = {p: set() for p in LEDGER_PLATFORMS}
    if isinstance(used, list):                       # OLD flat global list -> seed
        base = set(used)
        for p in _LEGACY_SEED_PLATFORMS:
            out[p] = set(base)                       # youtube stays empty (fresh)
    elif isinstance(used, dict):
        for p, ids in used.items():
            out[str(p)] = set(ids or [])
    return out


def read_ledger(retries: int = 4) -> Optional[dict[str, set[str]]]:
    """Fetch the per-platform used-clip ledger. Distinguishes states:
      * {platform: set(...)} -> the recorded ids (empty sets if nothing yet)
      * None                 -> UNREADABLE after retries (transient GitHub error).
                                Callers MUST NOT treat this as empty, or dedup silently
                                vanishes and clips repeat; the picker fails CLOSED on None.
    Retries transient 403/429/5xx so a blip doesn't wipe the anti-repeat guarantee."""
    rel = _release()
    if not rel:
        return None
    repo = _cfg().get("release_repo")
    asset_id = None
    try:
        for a in _fresh_assets(repo, rel.get("id")):
            if a.get("name") == USED_LEDGER_ASSET:
                asset_id = a.get("id")
                break
    except Exception:
        return None
    if asset_id is None:
        return {p: set() for p in LEDGER_PLATFORMS}   # no ledger yet == all empty (known)
    for attempt in range(retries):
        try:
            # Read by unique asset ID, not browser_download_url: the latter is
            # CDN-cached by <tag>/<name> and serves STALE content after a
            # delete+reupload. The asset-id endpoint reflects the new upload.
            r = requests.get(
                f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}",
                headers={**_headers(), "Accept": "application/octet-stream"},
                timeout=30)
            if r.status_code == 200:
                return _parse_ledger(r.json() or {})
            if r.status_code in (403, 429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None
    return None


def used_clips(platform: Optional[str] = None) -> set[str]:
    """Used clip ids: for one `platform`, or the UNION across platforms if None.
    Fail-open to empty for non-critical callers (stats/counters); the PICKER uses
    read_ledger() so it can fail CLOSED on None."""
    led = read_ledger()
    if led is None:
        return set()
    if platform:
        return led.get(platform, set())
    u: set[str] = set()
    for s in led.values():
        u |= s
    return u


def _write_ledger(used: dict[str, set[str]]) -> bool:
    """Replace the ledger asset with the given per-platform mapping. Needs a write token."""
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
    payload = {"used": {p: sorted(ids) for p, ids in used.items() if ids}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(3):
        try:
            r = requests.post(f"{upload_url}?name={USED_LEDGER_ASSET}",
                              headers={**h, "Content-Type": "application/json"},
                              data=body, timeout=60)
            if r.ok:
                return True
            if r.status_code in (403, 429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            return False
        except Exception:
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            return False
    return False


# ------------------------------------------------ last-posted markers (backup guard)
# A tiny JSON asset recording, per track, when a post last succeeded. The BACKUP
# cron trigger reads this to decide whether the primary already posted (skip) or a
# slot was missed (post the make-up). Reuses the small-JSON-asset plumbing above.
POST_MARKER_ASSET = "_post_markers.json"


def mark_posted(track: str) -> bool:
    """Record that `track` just posted successfully (epoch seconds)."""
    cur = _read_json_asset(POST_MARKER_ASSET) or {}
    cur[str(track)] = time.time()
    return _write_json_asset(POST_MARKER_ASSET, cur)


def minutes_since_post(track: str) -> Optional[float]:
    """Minutes since `track` last posted, or None if never recorded / unknown."""
    cur = _read_json_asset(POST_MARKER_ASSET) or {}
    ts = cur.get(str(track))
    if not ts:
        return None
    try:
        return max(0.0, (time.time() - float(ts)) / 60.0)
    except Exception:
        return None


# ---- low-footage-pool alert throttle (per user 2026-07-30) --------------------------
# When a game's fresh clips for a platform drop to <=20, Telegram-alert the user to add
# footage — but at most once per COOLDOWN per (pool,platform) so it isn't spammy.
LOW_POOL_ASSET = "_low_pool_alerts.json"


def low_pool_should_alert(alert_key: str, cooldown_hours: float = 24.0) -> bool:
    """True if we should send a low-pool alert for `alert_key` now (records the time).
    Fail-open to True on read/write trouble is WRONG (would spam); fail to False."""
    try:
        cur = _read_json_asset(LOW_POOL_ASSET) or {}
        ts = cur.get(alert_key)
        now = time.time()
        if ts and (now - float(ts)) / 3600.0 < cooldown_hours:
            return False
        cur[alert_key] = now
        _write_json_asset(LOW_POOL_ASSET, cur)
        return True
    except Exception:
        return False


# ---- durable POST LOG (per user 2026-07-30) ----------------------------------------
# One appended record per published post so any reel can be traced back to its exact clip
# forever (no 14-day CI-artifact race). Fields: ts, kind, game, clip_id, layout, hook,
# caption, platforms, result_id. Read/searched by tools/find_post.py + re-render flows.
POST_LOG_ASSET = "_post_log.json"
POST_LOG_MAX = 4000        # keep the most-recent N records (tiny JSON; bounds growth)


def log_post(entry: dict, retries: int = 3) -> bool:
    """Append a post record. EXISTENCE-AWARE read so a transient GitHub read error can't
    clobber the whole history (skip this append instead). Best-effort — never raises."""
    if not entry:
        return False
    repo = _cfg().get("release_repo")
    rel = _release()
    if not repo or not rel:
        return False
    for attempt in range(retries):
        posts = None
        try:
            aid = None
            for a in _fresh_assets(repo, rel.get("id")):
                if a.get("name") == POST_LOG_ASSET:
                    aid = a.get("id")
                    break
            if aid is None:
                posts = []                        # no log yet -> start fresh (safe)
            else:
                r = requests.get(
                    f"https://api.github.com/repos/{repo}/releases/assets/{aid}",
                    headers={**_headers(), "Accept": "application/octet-stream"}, timeout=30)
                if r.status_code == 200:
                    d = r.json() or {}
                    posts = list(d.get("posts", [])) if isinstance(d, dict) else []
        except Exception:
            posts = None
        if posts is None:                         # read error -> do NOT clobber; retry
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return False
        posts.append(entry)
        if len(posts) > POST_LOG_MAX:
            posts = posts[-POST_LOG_MAX:]
        if _write_json_asset(POST_LOG_ASSET, {"posts": posts}):
            return True
        if attempt < retries - 1:
            time.sleep(1.0 * (attempt + 1))
    return False


def read_post_log() -> list:
    """All post records (oldest first). Fail-open to [] for read errors."""
    cur = _read_json_asset(POST_LOG_ASSET) or {}
    return list(cur.get("posts", [])) if isinstance(cur, dict) else []


# ---- PINNED next clip (per user 2026-07-30) ----------------------------------------
# Force the NEXT scheduled run of a track to use a SPECIFIC clip (+ optional layout),
# consumed once. Lets us re-post a particular clip at the next slot without an extra
# off-cadence post. e.g. re-post a reel that YouTube mis-classified as long-form.
NEXT_CLIP_ASSET = "_next_clip.json"


def set_next_clip(track: str, clip: str, layout: Optional[str] = None) -> bool:
    """Pin `clip` (+ optional `layout`) as the next post for `track`."""
    if not track or not clip:
        return False
    cur = _read_json_asset(NEXT_CLIP_ASSET) or {}
    cur[str(track)] = {"clip": clip, "layout": layout}
    return _write_json_asset(NEXT_CLIP_ASSET, cur)


def take_next_clip(track: str) -> Optional[dict]:
    """Pop the pinned clip for `track` ({'clip':..,'layout':..}) or None. CONSUMES it —
    returns the entry ONLY if the clear write succeeds, so a run can't re-post it twice."""
    cur = _read_json_asset(NEXT_CLIP_ASSET)
    if not isinstance(cur, dict):
        return None
    entry = cur.get(str(track))
    if not entry:
        return None
    cur.pop(str(track), None)
    if not _write_json_asset(NEXT_CLIP_ASSET, cur):
        return None                     # couldn't clear -> don't consume (avoid a repeat)
    return entry


def find_posts(query: str = "", limit: int = 20) -> list:
    """Posts whose record contains `query` (caption/hook/clip_id/platform), NEWEST first."""
    import json as _json
    q = (query or "").lower().strip()
    hits = [p for p in read_post_log() if not q or q in _json.dumps(p, ensure_ascii=False).lower()]
    return list(reversed(hits))[: max(1, int(limit))]


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


STORY_QUOTES_ASSET = "_quote_story_used.json"


def used_story_quotes() -> set[str]:
    """Keys of game-story quotes already posted (cycle-all-before-repeat)."""
    return set((_read_json_asset(STORY_QUOTES_ASSET) or {}).get("used", []) or [])


def mark_story_quote(key: str) -> bool:
    if not key:
        return False
    cur = used_story_quotes()
    if key in cur:
        return True
    cur.add(key)
    return _write_json_asset(STORY_QUOTES_ASSET, {"used": sorted(cur)})


def reset_story_quotes() -> bool:
    return _write_json_asset(STORY_QUOTES_ASSET, {"used": []})


QUOTE_THEMES_ASSET = "_quote_themes.json"


def _today_ph() -> str:
    """Today's date in PH time (UTC+8) — the quote schedule fires at PH primes."""
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))


def pick_quote_theme(targets: Optional[dict[str, int]] = None) -> str:
    """Pick the quote theme whose daily target is furthest from being met, so a
    set of generic (un-themed) external triggers still lands the desired per-day
    mix (e.g. 2 'gameplay' + 2 'life'). Ties broken randomly. Fail-open to random."""
    targets = targets or {"story": 3}
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


def add_used_clip(clip_id: str, platforms, retries: int = 4) -> bool:
    """Record clip_id as used ON EACH of `platforms` for a gameplay reel. Re-reads the
    FRESHEST ledger immediately before each write and unions in the new id — this shrinks
    the read-modify-write lost-update window when tracks run concurrently (feed + TikTok +
    the draft poller + backups all mutate this one asset). Retries the whole cycle so a
    transient GitHub error doesn't drop the mark (an unrecorded post is exactly what causes
    a same-platform repeat)."""
    plats = [str(p) for p in (platforms or []) if p]
    if not clip_id or not plats:
        return False
    for attempt in range(retries):
        led = read_ledger()
        if led is None:                   # couldn't read -> can't safely merge; retry
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return False
        changed = False
        for p in plats:
            s = led.setdefault(p, set())
            if clip_id not in s:
                s.add(clip_id)
                changed = True
        if not changed:
            return True                   # already recorded on every target platform
        if _write_ledger(led):
            return True
        if attempt < retries - 1:
            time.sleep(1.0 * (attempt + 1))
    return False


def reset_used(prefix: Optional[str] = None, platforms=None) -> bool:
    """Restart a cycle: clear this game's (`prefix`) entries on the given `platforms`
    (all platforms if None). Used when every clip for a game has been shown on a platform."""
    led = read_ledger()
    if led is None:
        return False
    plats = [str(p) for p in platforms] if platforms else list(led.keys())
    for p in plats:
        s = led.get(p, set())
        led[p] = {c for c in s if not c.startswith(f"{prefix}__")} if prefix else set()
    return _write_ledger(led)


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
