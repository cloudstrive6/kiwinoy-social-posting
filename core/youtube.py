"""YouTube Data API v3 client — DIRECT long-form uploads (LOCAL only).

Our own Google Cloud OAuth app (Desktop client) in project kg-postforme. Used for
the 4K/60 HDR full-game uploads that Post for Me can't handle (it only sets a
title). Supports resumable upload (multi-GB files), scheduled publish, and a
custom thumbnail.

One-time auth (opens a browser; you approve; the refresh token is printed):
    python -m core.youtube login
Add the printed YOUTUBE_REFRESH_TOKEN to .env. After that, uploads run headless:
    from core import youtube
    youtube.upload_video("game.mp4", title=..., description=..., tags=[...],
                         privacy="private", publish_at="2026-07-01T12:00:00Z",
                         thumbnail="thumb.png")

Scopes: youtube.upload (videos.insert) + youtube.force-ssl (thumbnails.set).
Quota: insert ~1600 units, thumbnail ~50, of 10,000/day — trivial at 1-2/month.
Requires: google-api-python-client, google-auth, google-auth-oauthlib.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from core.config import CONFIG

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class YouTubeError(RuntimeError):
    pass


def _client_config() -> dict:
    cid, cs = CONFIG.youtube_client_id, CONFIG.youtube_client_secret
    if not cid or not cs:
        raise YouTubeError(
            "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET missing in .env "
            "(the Desktop OAuth client from the kg-postforme project)."
        )
    return {"installed": {
        "client_id": cid, "client_secret": cs,
        "auth_uri": AUTH_URI, "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}


def login() -> str:
    """One-time interactive auth -> prints + returns the refresh token to store as
    YOUTUBE_REFRESH_TOKEN. Opens a browser (loopback flow); approve the
    'unverified app' warning (it's your own channel)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    rt = getattr(creds, "refresh_token", None)
    if not rt:
        raise YouTubeError("No refresh_token returned — retry (ensure prompt=consent).")
    print("\n=== Add this line to your .env ===", flush=True)
    print(f"YOUTUBE_REFRESH_TOKEN={rt}\n", flush=True)
    return rt


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    rt = CONFIG.youtube_refresh_token
    if not rt:
        raise YouTubeError(
            "YOUTUBE_REFRESH_TOKEN missing — run:  python -m core.youtube login"
        )
    creds = Credentials(
        token=None, refresh_token=rt,
        client_id=CONFIG.youtube_client_id, client_secret=CONFIG.youtube_client_secret,
        token_uri=TOKEN_URI, scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def _service():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_creds(), cache_discovery=False)


def upload_video(
    path,
    title: str,
    description: str = "",
    tags: Optional[list[str]] = None,
    *,
    privacy: str = "private",
    publish_at: Optional[str] = None,
    category_id: str = "20",          # 20 = Gaming
    made_for_kids: bool = False,
    thumbnail: Optional[str] = None,
    # Resumable-upload chunk size. YouTube ACKs each chunk server-side before the next is
    # sent, so SMALL chunks pin throughput to (chunk / ack-latency) regardless of your line
    # speed — 50 MB chunks capped a 500 Mbps connection at ~19 Mbps. BIG chunks amortise the
    # per-chunk ACK wait: 512 MB is ~10x the data per ACK. Must be a multiple of 256 KB.
    chunk_mb: int = 512,
) -> dict[str, Any]:
    """Resumable-upload a video; optionally schedule it + set a custom thumbnail.

    publish_at (RFC3339 UTC, e.g. '2026-07-01T12:00:00Z') schedules the video —
    privacy is forced to 'private' until then. Returns the API response (incl.
    'id'); the watch URL is https://youtu.be/<id>.
    """
    import time

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    path = Path(path)
    if not path.exists():
        raise YouTubeError(f"video not found: {path}")

    status: dict[str, Any] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": bool(made_for_kids),
    }
    if publish_at:
        status["privacyStatus"] = "private"   # required for a scheduled publish
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": str(title)[:100],
            "description": str(description)[:5000],
            "tags": [str(t) for t in (tags or [])][:60],
            "categoryId": str(category_id),
        },
        "status": status,
    }

    yt = _service()
    media = MediaFileUpload(str(path), chunksize=max(1, chunk_mb) * 1024 * 1024,
                            resumable=True, mimetype="video/*")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    errs = 0
    while resp is None:
        try:
            # num_retries makes googleapiclient retry transient 5xx/socket errors on the
            # CURRENT chunk with backoff; the outer try adds a longer backoff on top so a
            # server hiccup mid-upload doesn't discard hours of progress. next_chunk() on a
            # resumable upload continues from the last CONFIRMED byte, so we resume, not restart.
            prog, resp = req.next_chunk(num_retries=6)
            if prog:
                print(f"[youtube] upload {int(prog.progress() * 100)}%", flush=True)
            errs = 0
        except HttpError as e:
            if getattr(e, "resp", None) is not None and e.resp.status in (500, 502, 503, 504) and errs < 12:
                errs += 1
                wait = min(120, 2 ** errs)
                print(f"[youtube] transient {e.resp.status} — retry {errs}/12 in {wait}s "
                      f"(resumes from last byte)", flush=True)
                time.sleep(wait)
                continue
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            if errs < 12:
                errs += 1
                wait = min(120, 2 ** errs)
                print(f"[youtube] connection error ({e!r}) — retry {errs}/12 in {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
    vid = resp.get("id", "")
    print(f"[youtube] uploaded id={vid}  https://youtu.be/{vid}", flush=True)

    if thumbnail and Path(thumbnail).exists():
        yt.thumbnails().set(
            videoId=vid, media_body=MediaFileUpload(str(thumbnail))
        ).execute()
        print("[youtube] custom thumbnail set", flush=True)
    return resp


def set_thumbnail(video_id: str, image) -> None:
    """Set/replace the custom thumbnail on an existing video."""
    from googleapiclient.http import MediaFileUpload

    _service().thumbnails().set(
        videoId=video_id, media_body=MediaFileUpload(str(image))
    ).execute()
    print(f"[youtube] thumbnail updated on {video_id}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        login()
    else:
        print("usage: python -m core.youtube login")
