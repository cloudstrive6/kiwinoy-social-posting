"""Zernio unified-social API client — posts a video to **TikTok**.

Why: TikTok rejected our OWN Content Posting app for self-posting (TikTok only approves
multi-tenant products). Zernio is an approved posting platform (free tier: 2 connected
accounts, unlimited posts), so we route TikTok through it — the same shape as Post for Me
routes FB/IG/YT/Threads.

Setup (one-time, by the account owner):
  1. Sign up free at https://zernio.com/signup and connect the KiwinoyGamer TikTok account.
  2. Create an API key in the dashboard -> put it in `.env` as ZERNIO_API_KEY.
  3. `python -m core.zernio accounts`  -> copy the TikTok account id into
     config.yaml tiktok.zernio.account_id (or env ZERNIO_TIKTOK_ACCOUNT_ID).
Then: `python -m core.zernio post <public_video_url> "caption"` to smoke-test.

Docs: https://docs.zernio.com  |  API base: https://zernio.com/api/v1
"""
from __future__ import annotations

import os
from typing import Optional

from core.config import CONFIG

BASE = "https://zernio.com/api/v1"


def _cfg() -> dict:
    return (CONFIG.raw().get("tiktok", {}) or {}).get("zernio", {}) or {}


def _headers() -> dict:
    key = (CONFIG.zernio_api_key or "").strip()
    if not key:
        raise RuntimeError("ZERNIO_API_KEY is not set")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def enabled() -> bool:
    """True when TikTok is routed through Zernio and we have a key + an account id."""
    tk = CONFIG.raw().get("tiktok", {}) or {}
    return (str(tk.get("via", "")).lower() == "zernio"
            and bool((CONFIG.zernio_api_key or "").strip())
            and bool(_account_id()))


def _account_id() -> str:
    return str(_cfg().get("account_id") or os.environ.get("ZERNIO_TIKTOK_ACCOUNT_ID") or "").strip()


def upload_media(data: bytes, filename: str = "reel.mp4",
                 content_type: str = "video/mp4") -> str:
    """Upload bytes to Zernio storage via a presigned URL; returns the public HTTPS URL
    to reference in a post. Self-contained (no dependency on other hosts)."""
    import requests
    r = requests.post(f"{BASE}/media/presign",
                      json={"filename": filename, "contentType": content_type, "size": len(data)},
                      headers=_headers(), timeout=30)
    r.raise_for_status()
    j = r.json()
    put = requests.put(j["uploadUrl"], data=data,
                       headers={"Content-Type": content_type}, timeout=600)
    put.raise_for_status()
    return j["publicUrl"]


def list_accounts(platform: str = "tiktok") -> list:
    """Connected social accounts (to find the TikTok account id for config)."""
    import requests
    r = requests.get(f"{BASE}/accounts", params={"platform": platform, "limit": 50},
                     headers=_headers(), timeout=30)
    r.raise_for_status()
    d = r.json()
    return d.get("accounts") or d.get("data") or (d if isinstance(d, list) else [])


def post_video(video_url: str, caption: str, *, account_id: Optional[str] = None,
               scheduled_for: Optional[str] = None) -> dict:
    """Publish (or schedule) a video to TikTok via Zernio. `video_url` must be a public
    HTTPS URL (our Post-for-Me media_url works). Returns the Zernio post JSON."""
    import uuid

    import requests
    acc = (account_id or _account_id()).strip()
    if not acc:
        raise RuntimeError("No Zernio TikTok account id (config tiktok.zernio.account_id)")
    c = _cfg()
    tiktok_data = {
        "draft": bool(c.get("draft", False)),                 # False = direct auto-post
        "privacyLevel": str(c.get("privacy_level", "PUBLIC_TO_EVERYONE")),
        "allowComment": bool(c.get("allow_comment", True)),
        "allowDuet": bool(c.get("allow_duet", True)),
        "allowStitch": bool(c.get("allow_stitch", True)),
    }
    body: dict = {
        "content": caption or "",
        "mediaItems": [{"type": "video", "url": video_url}],
        "platforms": [{"platform": "tiktok", "accountId": acc,
                       "platformSpecificData": tiktok_data}],
    }
    if scheduled_for:
        body["scheduledFor"] = scheduled_for
    else:
        body["publishNow"] = True
    r = requests.post(f"{BASE}/posts", json=body,
                      headers={**_headers(), "x-request-id": str(uuid.uuid4())}, timeout=90)
    if r.status_code == 409:                                  # 24h content-hash dedup
        print("[zernio] duplicate (posted within 24h) — skipping.", flush=True)
        return r.json() if r.text else {"skipped": "duplicate"}
    r.raise_for_status()
    return r.json()


def publish_reel(video_bytes: bytes, caption: str) -> Optional[dict]:
    """Fire-and-forget TikTok post used by the reel pipeline: uploads the reel to Zernio
    and posts it to TikTok. No-op (returns None) when Zernio TikTok isn't configured;
    never raises into the caller."""
    if not enabled():
        print("[zernio] TikTok not configured (need ZERNIO_API_KEY + tiktok.zernio.account_id) "
              "— skipping TikTok.", flush=True)
        return None
    try:
        url = upload_media(video_bytes)
        res = post_video(url, caption)
        print("[zernio] TikTok post created.", flush=True)
        return res
    except Exception as e:
        print(f"[zernio] TikTok post failed ({e!r}) — continuing.", flush=True)
        return None


def _main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m core.zernio accounts | post <video_url> <caption>")
        return 0
    if argv[0] == "accounts":
        for a in list_accounts():
            print(f"{a.get('id') or a.get('_id')}  {a.get('platform')}  "
                  f"{a.get('username') or a.get('displayName')}")
        return 0
    if argv[0] == "post":
        print(post_video(argv[1], argv[2] if len(argv) > 2 else ""))
        return 0
    print("unknown command", argv[0])
    return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
