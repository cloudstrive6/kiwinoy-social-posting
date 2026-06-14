"""Agent 5 — Publisher.

Publishes via Post for Me:
  - run()        image post -> Facebook + Instagram (feed image)
  - run_reel()   reel MP4   -> Facebook + Instagram Reels
  - run_threads() text post  -> Threads (text only, no media)

Threads is handled ONLY by the dedicated Threads track now; image posts and
reels no longer go to Threads.
"""
from __future__ import annotations

from typing import Any, Optional

from core import postforme
from core.config import CONFIG

_IMAGE_PLATFORMS = ["facebook", "instagram"]
_THREADS_PLATFORMS = ["threads"]

_NO_ACCOUNTS = (
    "No connected account IDs in config.yaml. Run "
    "`python tools/list_accounts.py` after adding your Post for Me key."
)


def run(
    caption: str,
    image_bytes: Optional[bytes],
    platform_keys: Optional[list[str]] = None,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish (or schedule) a feed post.

    platform_keys selects which connected accounts to post to (default FB+IG).
    If image_bytes is None, it's a text-only post (Facebook supports this;
    Instagram does not, so text-only posts should target Facebook only).
    """
    account_ids = CONFIG.account_ids(platform_keys or _IMAGE_PLATFORMS)
    if not account_ids:
        raise postforme.PostForMeError(_NO_ACCOUNTS)

    media_urls: list[str] = []
    if image_bytes:
        media_urls = [postforme.upload_image(image_bytes, content_type="image/png")]

    return postforme.create_post(
        caption=caption,
        social_accounts=account_ids,
        media_urls=media_urls,
        scheduled_at=scheduled_at,
        is_draft=is_draft,
    )


def run_carousel(
    caption: str,
    images: list[bytes],
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish a multi-image carousel post to Facebook + Instagram."""
    account_ids = CONFIG.account_ids(_IMAGE_PLATFORMS)
    if not account_ids:
        raise postforme.PostForMeError(_NO_ACCOUNTS)
    media_urls = [
        postforme.upload_image(img, content_type="image/png") for img in images
    ]
    return postforme.create_post(
        caption=caption,
        social_accounts=account_ids,
        media_urls=media_urls,
        scheduled_at=scheduled_at,
        is_draft=is_draft,
    )


def run_reel(
    caption: str,
    video_bytes: bytes,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Upload an MP4 reel and publish it to Facebook + Instagram Reels."""
    account_ids = CONFIG.account_ids(_IMAGE_PLATFORMS)
    if not account_ids:
        raise postforme.PostForMeError(_NO_ACCOUNTS)

    media_url = postforme.upload_video(video_bytes)
    placements = {
        "instagram": {"placement": "reels"},
        "facebook": {"placement": "reels"},
    }
    try:
        return postforme.create_post(
            caption=caption,
            social_accounts=account_ids,
            media_urls=[media_url],
            scheduled_at=scheduled_at,
            platform_configurations=placements,
            is_draft=is_draft,
        )
    except postforme.PostForMeError:
        return postforme.create_post(
            caption=caption,
            social_accounts=account_ids,
            media_urls=[media_url],
            scheduled_at=scheduled_at,
            platform_configurations=None,
            is_draft=is_draft,
        )


def run_video_post(
    caption: str,
    video_bytes: bytes,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish a LONG video (commentary, > Reel length limits).

    Instagram publishes any API video as a Reel (max ~15 min), so IG keeps the
    reels placement. Facebook Reels cap at ~90s, so on Facebook a long video goes
    out as a normal video feed post (no reels placement).
    """
    account_ids = CONFIG.account_ids(_IMAGE_PLATFORMS)
    if not account_ids:
        raise postforme.PostForMeError(_NO_ACCOUNTS)
    media_url = postforme.upload_video(video_bytes)
    placements = {"instagram": {"placement": "reels"}}  # FB omitted = feed video
    try:
        return postforme.create_post(
            caption=caption,
            social_accounts=account_ids,
            media_urls=[media_url],
            scheduled_at=scheduled_at,
            platform_configurations=placements,
            is_draft=is_draft,
        )
    except postforme.PostForMeError:
        return postforme.create_post(
            caption=caption,
            social_accounts=account_ids,
            media_urls=[media_url],
            scheduled_at=scheduled_at,
            platform_configurations=None,
            is_draft=is_draft,
        )


def run_threads(
    text: str,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish a text-only post to the Threads track's platforms (Threads + X)."""
    targets = CONFIG.platforms.get("threads_post_to", _THREADS_PLATFORMS)
    account_ids = CONFIG.account_ids(targets)
    if not account_ids:
        raise postforme.PostForMeError(
            "No Threads/X account IDs in config.yaml. Connect them in Post for "
            "Me and run `python tools/list_accounts.py --save`."
        )
    return postforme.create_post(
        caption=text,
        social_accounts=account_ids,
        media_urls=None,
        scheduled_at=scheduled_at,
        is_draft=is_draft,
    )
