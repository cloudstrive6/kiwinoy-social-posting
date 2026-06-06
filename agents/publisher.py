"""Agent 5 — Publisher.

Uploads the generated image to Post for Me, then creates one post that fans out
to Facebook + Instagram + Threads. FB/IG get the long caption; Threads gets its
own punchier text via a platform override. scheduled_at=None publishes now.
"""
from __future__ import annotations

from typing import Any, Optional

from core import postforme
from core.config import CONFIG


def run(
    caption: str,
    threads_text: str,
    image_bytes: Optional[bytes],
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Publish (or schedule) the post. Returns the Post for Me response."""
    account_ids = CONFIG.account_ids()
    if not account_ids:
        raise postforme.PostForMeError(
            "No connected account IDs in config.yaml. Run "
            "`python tools/list_accounts.py` after adding your Post for Me key."
        )

    media_urls: list[str] = []
    if image_bytes:
        media_urls = [postforme.upload_image(image_bytes, content_type="image/png")]

    # Give Threads its own caption; FB/IG inherit the main caption.
    platform_configurations = {"threads": {"caption": threads_text}}

    try:
        return postforme.create_post(
            caption=caption,
            social_accounts=account_ids,
            media_urls=media_urls,
            scheduled_at=scheduled_at,
            platform_configurations=platform_configurations,
            is_draft=is_draft,
        )
    except postforme.PostForMeError:
        # If the per-platform override is rejected, fall back to one caption
        # everywhere so the post still goes out.
        return postforme.create_post(
            caption=caption,
            social_accounts=account_ids,
            media_urls=media_urls,
            scheduled_at=scheduled_at,
            platform_configurations=None,
            is_draft=is_draft,
        )


def run_reel(
    caption: str,
    video_bytes: bytes,
    scheduled_at: Optional[str] = None,
    is_draft: bool = False,
) -> dict[str, Any]:
    """Upload an MP4 reel and publish it to IG/FB Reels (+ Threads video)."""
    account_ids = CONFIG.account_ids()
    if not account_ids:
        raise postforme.PostForMeError(
            "No connected account IDs in config.yaml. Run "
            "`python tools/list_accounts.py` after adding your Post for Me key."
        )

    media_url = postforme.upload_video(video_bytes)
    # IG/FB get the Reels placement; Threads posts the video to its timeline.
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
