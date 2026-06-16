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


def _video_targets() -> list[str]:
    """Platforms for video posts: config video_post_to, else FB+IG. Never X."""
    targets = CONFIG.platforms.get("video_post_to", _IMAGE_PLATFORMS)
    return [t for t in targets if t != "x"]


def _video_placements(targets: list[str], title: str, short: bool) -> dict[str, Any]:
    """Per-platform config for a video post across FB/IG/Threads/YouTube.

    short=True -> Reels/Shorts placement; short=False (long video) -> FB feed
    video (no reels placement, which caps ~90s). Threads needs no special config.
    YouTube requires a title.
    """
    cfg: dict[str, Any] = {}
    if "instagram" in targets:
        cfg["instagram"] = {"placement": "reels"}
    if "facebook" in targets and short:
        cfg["facebook"] = {"placement": "reels"}  # long video -> omit = FB feed
    if "youtube" in targets:
        cfg["youtube"] = {"title": (title or "KiwinoyGamer").strip()[:95]}
    return cfg


def publish_video(
    caption: str,
    video_bytes: bytes,
    title: Optional[str] = None,
    short: bool = True,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
    targets: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Upload + publish a video. Defaults to every video platform (FB/IG/Threads/
    YouTube); pass `targets` to restrict (e.g. ["facebook"] for commentary). X is
    always excluded. short=True for Reels/Shorts; False for a long video. Falls
    back to a no-placement post if the placement config is rejected, so one
    platform's quirk can't sink the whole post."""
    targets = [t for t in (targets if targets is not None else _video_targets()) if t != "x"]
    account_ids = CONFIG.account_ids(targets)
    if not account_ids:
        raise postforme.PostForMeError(_NO_ACCOUNTS)
    media_url = postforme.upload_video(video_bytes)
    placements = _video_placements(targets, title or caption.splitlines()[0] if caption else "", short)
    try:
        return postforme.create_post(
            caption=caption, social_accounts=account_ids, media_urls=[media_url],
            scheduled_at=scheduled_at, platform_configurations=placements or None,
            is_draft=is_draft,
        )
    except postforme.PostForMeError:
        return postforme.create_post(
            caption=caption, social_accounts=account_ids, media_urls=[media_url],
            scheduled_at=scheduled_at, platform_configurations=None, is_draft=is_draft,
        )


def run_reel(
    caption: str,
    video_bytes: bytes,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish a short reel to FB/IG/Threads/YouTube (Reels/Shorts)."""
    return publish_video(caption, video_bytes, short=True,
                         scheduled_at=scheduled_at, is_draft=is_draft)


def run_video_post(
    caption: str,
    video_bytes: bytes,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish a LONG video (commentary) to FB/IG/Threads/YouTube (feed video on FB)."""
    return publish_video(caption, video_bytes, short=False,
                         scheduled_at=scheduled_at, is_draft=is_draft)


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
