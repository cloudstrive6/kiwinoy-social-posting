"""TikTok Content Posting API client — direct, no middleman.

Post for Me / Metricool are NOT used for TikTok; we own a TikTok developer app and
post straight to TikTok's API (free, no subscription, no third-party outage). The
gameplay reels cross-post here; Post for Me still handles IG / YouTube / FB / Threads.

Contract (verified against developers.tiktok.com, base https://open.tiktokapis.com):
  OAuth:
    authorize  GET  https://www.tiktok.com/v2/auth/authorize/   (browser consent)
    token      POST /v2/oauth/token/   (code->tokens, or refresh_token->access_token)
  Posting (scope video.publish):
    POST /v2/post/publish/creator_info/query/   -> allowed privacy levels (call first)
    POST /v2/post/publish/video/init/           -> publish_id + upload_url (FILE_UPLOAD)
    PUT  <upload_url>                            -> the video bytes, in 5-64MB chunks
    POST /v2/post/publish/status/fetch/          -> publish status by publish_id

We use FILE_UPLOAD (not PULL_FROM_URL) so we don't have to verify a public domain
with TikTok — the rendered reel is uploaded straight from disk.

IMPORTANT — audit gate: an UNAUDITED app can ONLY post privacy_level SELF_ONLY
(private). Public posting (PUBLIC_TO_EVERYONE) needs TikTok to audit the app
(~1-2 weeks). So config.tiktok.privacy stays SELF_ONLY until the audit clears.

Secrets (env only — public repo): TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET /
TIKTOK_REFRESH_TOKEN. The access_token is minted from the refresh_token each run.

One-time auth (run locally after creating the app + setting redirect_uri):
  python -m core.tiktok auth                 # prints the consent URL to open
  python -m core.tiktok token "<redirect_url_or_code>"   # -> prints refresh_token
Then store the refresh_token as TIKTOK_REFRESH_TOKEN. After that:
  python -m core.tiktok creator              # sanity-check auth
  python -m core.tiktok publish <file.mp4> "caption"     # SELF_ONLY test post
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from .config import CONFIG

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com"
SCOPE = "user.info.basic,video.publish"
TIMEOUT = 300
CHUNK = 10 * 1024 * 1024            # 10MB working chunk (TikTok allows 5-64MB)
SINGLE_MAX = 64 * 1024 * 1024       # <=64MB may upload as one chunk


class TikTokError(RuntimeError):
    pass


def _cfg() -> dict[str, Any]:
    return CONFIG.raw().get("tiktok", {}) or {}


# ----------------------------------------------------------------- OAuth
def auth_url(state: str = "kg") -> str:
    """The browser consent URL. The user opens it, authorizes, and is redirected to
    our registered redirect_uri with ?code=... (then call `token`)."""
    redirect = _cfg().get("redirect_uri", "")
    if not CONFIG.tiktok_client_key or not redirect:
        raise TikTokError("Set TIKTOK_CLIENT_KEY and config.tiktok.redirect_uri first.")
    q = {
        "client_key": CONFIG.tiktok_client_key,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": redirect,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(q)}"


def exchange_code(code_or_url: str) -> dict[str, Any]:
    """Swap the OAuth `code` (or the full redirected URL containing it) for tokens.
    Prints + returns the refresh_token to store as TIKTOK_REFRESH_TOKEN."""
    code = code_or_url
    if code_or_url.startswith("http"):
        qs = parse_qs(urlparse(code_or_url).query)
        code = (qs.get("code") or [""])[0]
    if not code:
        raise TikTokError("No authorization code found.")
    r = requests.post(
        f"{API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": CONFIG.tiktok_client_key,
            "client_secret": CONFIG.tiktok_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _cfg().get("redirect_uri", ""),
        },
        timeout=TIMEOUT,
    )
    data = r.json()
    if r.status_code >= 400 or "access_token" not in data:
        raise TikTokError(f"token exchange failed [{r.status_code}]: {r.text[:300]}")
    return data


def access_token() -> str:
    """Mint a fresh access_token from the stored refresh_token.

    TikTok rotates the refresh_token on refresh — if a new one comes back, we warn
    so it gets persisted (CI updates the TIKTOK_REFRESH_TOKEN secret)."""
    rt = CONFIG.tiktok_refresh_token
    if not rt:
        raise TikTokError("TIKTOK_REFRESH_TOKEN not set — run the one-time `auth`/`token` flow.")
    r = requests.post(
        f"{API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": CONFIG.tiktok_client_key,
            "client_secret": CONFIG.tiktok_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": rt,
        },
        timeout=TIMEOUT,
    )
    data = r.json()
    if r.status_code >= 400 or "access_token" not in data:
        raise TikTokError(f"refresh failed [{r.status_code}]: {r.text[:300]}")
    new_rt = data.get("refresh_token")
    if new_rt and new_rt != rt:
        # Surface for persistence; the orchestrator writes it back to the secret.
        print(f"::tiktok-refresh-token::{new_rt}", flush=True)
    return data["access_token"]


def _auth_headers(token: Optional[str] = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or access_token()}",
            "Content-Type": "application/json; charset=UTF-8"}


# ----------------------------------------------------------------- posting
def creator_info(token: Optional[str] = None) -> dict[str, Any]:
    """Query the creator's allowed privacy levels etc. TikTok requires this before
    an init call; also a clean auth sanity-check."""
    r = requests.post(f"{API}/v2/post/publish/creator_info/query/",
                      headers=_auth_headers(token), timeout=TIMEOUT)
    data = r.json()
    if r.status_code >= 400:
        raise TikTokError(f"creator_info failed [{r.status_code}]: {r.text[:300]}")
    return data


def _chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) per TikTok's rules: <=64MB -> single chunk;
    larger -> fixed CHUNK chunks with the final chunk absorbing the remainder."""
    if size <= SINGLE_MAX:
        return size, 1
    total = size // CHUNK            # floor; last PUT carries chunk_size + remainder
    return CHUNK, total


def publish_video(path: str, caption: str, *, privacy: Optional[str] = None,
                  token: Optional[str] = None) -> str:
    """Upload + publish a local MP4 to TikTok via FILE_UPLOAD. Returns the
    publish_id. privacy defaults to config (SELF_ONLY until the app is audited)."""
    cfg = _cfg()
    privacy = privacy or cfg.get("privacy", "SELF_ONLY")
    token = token or access_token()
    size = os.path.getsize(path)
    if size <= 0:
        raise TikTokError(f"empty video: {path}")
    chunk_size, total = _chunk_plan(size)

    init = requests.post(
        f"{API}/v2/post/publish/video/init/",
        headers=_auth_headers(token),
        json={
            "post_info": {
                "title": " ".join(str(caption).split())[:2200],
                "privacy_level": privacy,
                "disable_comment": bool(cfg.get("disable_comment", False)),
                "disable_duet": bool(cfg.get("disable_duet", False)),
                "disable_stitch": bool(cfg.get("disable_stitch", False)),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": total,
            },
        },
        timeout=TIMEOUT,
    )
    j = init.json()
    if init.status_code >= 400 or j.get("error", {}).get("code") not in (None, "ok"):
        raise TikTokError(f"init failed [{init.status_code}]: {init.text[:400]}")
    data = j.get("data", {})
    publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
    if not publish_id or not upload_url:
        raise TikTokError(f"init missing publish_id/upload_url: {init.text[:300]}")

    with open(path, "rb") as fh:
        blob = fh.read()
    for i in range(total):
        start = i * chunk_size
        end = size - 1 if i == total - 1 else start + chunk_size - 1
        part = blob[start:end + 1]
        put = requests.put(
            upload_url,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(part)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            },
            data=part,
            timeout=TIMEOUT,
        )
        if put.status_code not in (200, 201, 206):
            raise TikTokError(f"chunk {i+1}/{total} PUT failed [{put.status_code}]: {put.text[:200]}")
    return publish_id


def status(publish_id: str, token: Optional[str] = None) -> dict[str, Any]:
    r = requests.post(f"{API}/v2/post/publish/status/fetch/",
                      headers=_auth_headers(token),
                      json={"publish_id": publish_id}, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise TikTokError(f"status failed [{r.status_code}]: {r.text[:300]}")
    return r.json()


# ----------------------------------------------------------------- CLI
def _cli() -> None:
    import json
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auth"
    if cmd == "auth":
        print(auth_url())
    elif cmd == "token" and len(sys.argv) >= 3:
        d = exchange_code(sys.argv[2])
        print("refresh_token (store as TIKTOK_REFRESH_TOKEN):\n", d.get("refresh_token"))
        print("open_id:", d.get("open_id"), "| scopes:", d.get("scope"))
    elif cmd == "creator":
        print(json.dumps(creator_info(), indent=2)[:1000])
    elif cmd == "publish" and len(sys.argv) >= 3:
        cap = sys.argv[3] if len(sys.argv) >= 4 else "KiwinoyGamer"
        pid = publish_video(sys.argv[2], cap)
        print("publish_id:", pid)
        print(json.dumps(status(pid), indent=2)[:600])
    elif cmd == "status" and len(sys.argv) >= 3:
        print(json.dumps(status(sys.argv[2]), indent=2)[:600])
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
