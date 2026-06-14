"""Post for Me REST client.

Wraps the three calls we need:
  1. list connected social accounts (to discover FB / IG / Threads IDs)
  2. create an upload URL + PUT image bytes (returns a public media URL)
  3. create a (optionally scheduled) post to one or more accounts

API surface verified against https://api.postforme.dev/docs (OpenAPI):
  GET  /v1/social-accounts
  POST /v1/media/create-upload-url   -> { upload_url, media_url }
  POST /v1/social-posts              -> caption, social_accounts[], media[{url}],
                                        scheduled_at (ISO, null = post now)
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from .config import CONFIG

BASE_URL = "https://api.postforme.dev/v1"
TIMEOUT = 60


class PostForMeError(RuntimeError):
    pass


def _headers(json: bool = True) -> dict[str, str]:
    key = CONFIG.postforme_api_key
    if not key:
        raise PostForMeError(
            "POSTFORME_API_KEY is not set. Add it to .env (local) or to your "
            "GitHub Actions secrets (cloud)."
        )
    h = {"Authorization": f"Bearer {key}"}
    if json:
        h["Content-Type"] = "application/json"
    return h


def list_accounts() -> list[dict[str, Any]]:
    """Return all connected social accounts (paginated -> flattened)."""
    out: list[dict[str, Any]] = []
    offset, limit = 0, 100
    while True:
        r = requests.get(
            f"{BASE_URL}/social-accounts",
            headers=_headers(json=False),
            params={"offset": offset, "limit": limit},
            timeout=TIMEOUT,
        )
        if r.status_code >= 400:
            raise PostForMeError(f"list_accounts failed [{r.status_code}]: {r.text}")
        payload = r.json()
        items = payload.get("data", payload if isinstance(payload, list) else [])
        out.extend(items)
        if len(items) < limit:
            break
        offset += limit
    return out


def upload_image(image_bytes: bytes, content_type: str = "image/png") -> str:
    """Upload raw image bytes and return the public media URL to attach to a post."""
    # Step 1: ask Post for Me for a one-time upload URL.
    r = requests.post(
        f"{BASE_URL}/media/create-upload-url",
        headers=_headers(),
        json={},
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise PostForMeError(f"create-upload-url failed [{r.status_code}]: {r.text}")
    data = r.json()
    upload_url = data["upload_url"]
    media_url = data["media_url"]

    # Step 2: PUT the bytes straight to storage.
    put = requests.put(
        upload_url,
        data=image_bytes,
        headers={"Content-Type": content_type},
        timeout=TIMEOUT,
    )
    if put.status_code >= 400:
        raise PostForMeError(f"media upload PUT failed [{put.status_code}]: {put.text}")

    return media_url


def recent_captions(limit: int = 15) -> list[str]:
    """Best-effort: recent published post captions (newest first), for dedup.

    Never raises — dedup is a nice-to-have and must not block posting.
    """
    try:
        r = requests.get(
            f"{BASE_URL}/social-posts",
            headers=_headers(json=False),
            params={"offset": 0, "limit": limit},
            timeout=TIMEOUT,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
        items = data.get("data", data if isinstance(data, list) else [])
        out: list[str] = []
        for it in items:
            c = (it.get("caption") or "").strip()
            if c:
                out.append(c)
        return out
    except Exception:
        return []


def upload_video(video_bytes: bytes, content_type: str = "video/mp4") -> str:
    """Upload an MP4 reel and return its public media URL (same flow as images)."""
    return upload_image(video_bytes, content_type=content_type)


def create_post(
    caption: str,
    social_accounts: list[str],
    media_urls: Optional[list[str]] = None,
    scheduled_at: Optional[str] = None,
    platform_configurations: Optional[dict[str, Any]] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Create a post. scheduled_at=None publishes immediately."""
    if not social_accounts:
        raise PostForMeError(
            "No social_accounts to post to. Run tools/list_accounts.py to "
            "populate account IDs in config.yaml."
        )
    body: dict[str, Any] = {
        "caption": caption,
        "social_accounts": social_accounts,
        "isDraft": is_draft,
    }
    if media_urls:
        body["media"] = [{"url": u} for u in media_urls]
    if scheduled_at:
        body["scheduled_at"] = scheduled_at
    if platform_configurations:
        body["platform_configurations"] = platform_configurations

    r = requests.post(
        f"{BASE_URL}/social-posts",
        headers=_headers(),
        json=body,
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise PostForMeError(f"create_post failed [{r.status_code}]: {r.text}")
    return _scrub(r.json())


# Post for Me echoes the connected accounts' live OAuth tokens in the create_post
# response. We persist the response to result.json (uploaded as a public-repo
# Actions artifact), so strip every credential field before returning it.
_SENSITIVE = {
    "access_token", "refresh_token",
    "access_token_expires_at", "refresh_token_expires_at",
}


def _scrub(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if k in _SENSITIVE else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(x) for x in obj]
    return obj
