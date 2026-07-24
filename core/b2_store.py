"""Backblaze B2 footage store — native B2 API, requests-only.

Large gameplay clips live in the B2 media bucket under ``footage/<game>/<name>``.
This module lists a game's clips and downloads a chosen clip to a local cache at
render time, exposing the SAME shape as :mod:`core.gh_release` (``list_footage`` /
``download_footage``) so :mod:`agents.reel_composer` can treat B2 and the legacy
GitHub Release interchangeably.

Deliberately uses the B2 *native* API over ``requests`` — no boto3, no rclone —
so it runs in GitHub Actions with nothing but ``B2_KEY_ID`` / ``B2_APP_KEY`` in
the environment (no binary to install). Uploads/migrations use rclone locally;
this read path does not.

Every public call FAILS OPEN (returns ``[]`` / ``None``) so a network or auth
hiccup simply falls back to the GitHub Release, local clips, or AI stills.
"""
from __future__ import annotations

import base64
import os
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from core.config import CONFIG

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
_AUTH_URL = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"
_TIMEOUT = 30

_lock = threading.Lock()
_auth: Optional[dict[str, Any]] = None  # cached authorize response (valid ~24h)


# --------------------------------------------------------------- config / creds

def _fcfg() -> dict[str, Any]:
    return CONFIG.reels.get("footage", {}) or {}


def _creds() -> tuple[str, str]:
    """(key_id, app_key) from the environment (.env locally, Secrets in CI)."""
    return CONFIG._key("B2_KEY_ID"), CONFIG._key("B2_APP_KEY")


def _bucket() -> str:
    """The single B2 media bucket. Defined ONCE at longform_archive.bucket so a
    future rename is a one-line change (footage just reuses that bucket)."""
    la = CONFIG.raw().get("longform_archive", {}) or {}
    return str(_fcfg().get("b2_bucket") or la.get("bucket") or "")


def _prefix() -> str:
    p = str(_fcfg().get("b2_prefix", "footage")).strip("/")
    return f"{p}/" if p else ""


def enabled() -> bool:
    """True when B2 footage is turned on AND creds + bucket are available."""
    kid, key = _creds()
    return bool(_fcfg().get("use_b2") and kid and key and _bucket())


# ------------------------------------------------------------------- b2 native

def _authorize() -> Optional[dict[str, Any]]:
    """Authorize (cached). Returns {token, apiUrl, downloadUrl, bucketId,
    bucketName} or None. The app key is bucket-restricted, so authorize already
    hands back bucketId/bucketName — no b2_list_buckets needed."""
    global _auth
    with _lock:
        if _auth is not None:
            return _auth
        kid, key = _creds()
        if not (kid and key):
            return None
        try:
            basic = base64.b64encode(f"{kid}:{key}".encode()).decode()
            r = requests.get(_AUTH_URL, headers={"Authorization": f"Basic {basic}"},
                             timeout=_TIMEOUT)
            if r.status_code != 200:
                return None
            j = r.json()
            api = (j.get("apiInfo", {}) or {}).get("storageApi", {}) or {}
            _auth = {
                "token": j.get("authorizationToken", ""),
                "apiUrl": api.get("apiUrl", ""),
                "downloadUrl": api.get("downloadUrl", ""),
                "bucketId": api.get("bucketId", ""),
                "bucketName": api.get("bucketName", "") or _bucket(),
            }
            if not (_auth["token"] and _auth["apiUrl"] and _auth["downloadUrl"]):
                _auth = None
            return _auth
        except Exception:
            _auth = None
            return None


def _list_names(prefix: str) -> list[dict[str, Any]]:
    """Raw b2_list_file_names under a prefix (paginated). [] on any failure."""
    auth = _authorize()
    if not auth:
        return []
    bucket_id = auth.get("bucketId")
    if not bucket_id:
        return []
    url = f"{auth['apiUrl']}/b2api/v3/b2_list_file_names"
    headers = {"Authorization": auth["token"]}
    out: list[dict[str, Any]] = []
    start: Optional[str] = None
    try:
        for _ in range(200):  # up to 200 pages * 10k = plenty
            body = {"bucketId": bucket_id, "prefix": prefix, "maxFileCount": 10000}
            if start:
                body["startFileName"] = start
            r = requests.post(url, headers=headers, json=body, timeout=_TIMEOUT)
            if r.status_code != 200:
                break
            j = r.json()
            out += j.get("files", []) or []
            start = j.get("nextFileName")
            if not start:
                break
    except Exception:
        return out
    return out


# ------------------------------------------------------------------- public API

def list_footage(gamekey: str) -> list[dict[str, str]]:
    """Return [{name, key}] for a game's clips in B2 (``footage/<game>/*``).

    ``name`` is the bare filename (used for the no-repeat ledger id + cache
    filename); ``key`` is the full B2 object path (used to download).
    """
    if not enabled() or not gamekey:
        return []
    prefix = f"{_prefix()}{gamekey}/"
    out: list[dict[str, str]] = []
    for f in _list_names(prefix):
        key = str(f.get("fileName", ""))
        name = key[len(prefix):]
        if not name or "/" in name:          # skip anything nested
            continue
        if Path(name).suffix.lower() in VIDEO_EXTS:
            out.append({"name": name, "key": key})
    return out


def list_art_footage(gamekey: str) -> list[dict[str, str]]:
    """Return [{name, key}] for a game's TITLE-SCREEN art videos on B2
    (``art-footage/<game>/*``) — the looping bottom-panel clips for the triptych.
    Same shape as list_footage; download with ``download_footage``."""
    if not enabled() or not gamekey:
        return []
    prefix = f"art-footage/{gamekey}/"
    out: list[dict[str, str]] = []
    for f in _list_names(prefix):
        key = str(f.get("fileName", ""))
        name = key[len(prefix):]
        if not name or "/" in name:
            continue
        if Path(name).suffix.lower() in VIDEO_EXTS:
            out.append({"name": name, "key": key})
    return out


def list_games() -> dict[str, int]:
    """{game_key: clip_count} for every game with clips under the footage prefix."""
    if not enabled():
        return {}
    pre = _prefix()
    counts: dict[str, int] = {}
    for f in _list_names(pre):
        rel = str(f.get("fileName", ""))[len(pre):]
        if "/" not in rel:
            continue
        game, name = rel.split("/", 1)
        if "/" not in name and Path(name).suffix.lower() in VIDEO_EXTS:
            counts[game] = counts.get(game, 0) + 1
    return counts


def download_footage(item: dict[str, str], cache_dir: Path) -> Optional[Path]:
    """Download item['key'] into cache_dir/item['name'] (cached). Path or None."""
    auth = _authorize()
    if not auth or not item.get("key"):
        return None
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / item["name"]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    bucket = auth.get("bucketName") or _bucket()
    url = f"{auth['downloadUrl']}/file/{bucket}/{quote(item['key'], safe='/')}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, headers={"Authorization": auth["token"]},
                          stream=True, timeout=600) as r:
            if r.status_code != 200:
                return None
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
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


def presigned_url(key: str, valid_seconds: int = 7 * 24 * 3600) -> Optional[str]:
    """A time-limited, shareable download URL for a PRIVATE-bucket object, via
    b2_get_download_authorization (max 7 days). Returns the URL with the auth token
    appended, or None on failure. Used to hand a rendered draft to the user's phone."""
    auth = _authorize()
    if not auth or not key:
        return None
    try:
        valid = max(1, min(int(valid_seconds), 604800))   # B2 hard cap = 7 days
        url = f"{auth['apiUrl']}/b2api/v3/b2_get_download_authorization"
        r = requests.post(url, headers={"Authorization": auth["token"]},
                          json={"bucketId": auth["bucketId"], "fileNamePrefix": key,
                                "validDurationInSeconds": valid}, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        tok = r.json().get("authorizationToken", "")
        if not tok:
            return None
        bucket = auth.get("bucketName") or _bucket()
        return f"{auth['downloadUrl']}/file/{bucket}/{quote(key, safe='/')}?Authorization={tok}"
    except Exception:
        return None


if __name__ == "__main__":  # self-test against the real bucket
    import sys
    os.environ.setdefault("_B2_SELFTEST", "1")
    game = sys.argv[1] if len(sys.argv) > 1 else "spider-man2"
    print("enabled():", enabled(), "| bucket:", _bucket(), "| prefix:", _prefix())
    a = _authorize()
    print("authorize ok:", bool(a), "| bucketId:", (a or {}).get("bucketId", "")[:8],
          "| bucketName:", (a or {}).get("bucketName", ""))
    clips = list_footage(game)
    print(f"list_footage({game}): {len(clips)} clips")
    for c in clips[:3]:
        print("  -", c["name"])
    print("list_games():", list_games())
    if clips and "--dl" in sys.argv:
        p = download_footage(clips[0], Path("reels/assets/footage/.cache"))
        print("download ->", p, "| bytes:", p.stat().st_size if p else None)
