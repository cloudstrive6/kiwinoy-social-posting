"""Queue your OWN finished vertical reels for auto-posting.

Drop edited reels (1080x1920, from Premiere/AME) into:
    reels/assets/ready/<game>/<caption>.mp4    e.g. spider-man1/Fisk is caught.mp4
(or reels/assets/ready/<caption>.mp4). This re-encodes each to 1080x1920 CFR 60
at a sane bitrate (shrinks your ~40 Mbps export so it fits the cloud) and uploads
it to the 'ready-reels' GitHub Release, which acts as a queue. The ready-reels.yml
workflow then posts the oldest one to FB/IG/Threads/YouTube and removes it.

  python tools/ready_reels.py          # encode + upload everything in ready/
  python tools/ready_reels.py --dry    # show the plan, no encode/upload
"""
from __future__ import annotations

import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

from core import ffmpeg
from core.config import CONFIG, ROOT

API = "https://api.github.com"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _cfg() -> dict:
    return CONFIG.reels.get("ready_reels", {}) or {}


def _repo() -> str:
    return (CONFIG.reels.get("footage", {}) or {}).get("release_repo", "")


def _tag() -> str:
    return _cfg().get("release_tag", "ready-reels")


def _token() -> str:
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True,
                              text=True).stdout.strip()
    except Exception:
        return ""


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _release(token: str) -> dict:
    repo, tag = _repo(), _tag()
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=_h(token))
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{repo}/releases", headers=_h(token),
                      json={"tag_name": tag, "name": tag,
                            "body": "Queue of finished reels awaiting auto-post."})
    return r.json()


def _known_games() -> set:
    return set((CONFIG.reels.get("game_names", {}) or {}).keys())


def _sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


def _game_caption(path: Path) -> tuple[str, str]:
    """game = parent folder (if a known game) or a '<game>__' filename prefix;
    caption = the rest of the filename (underscores become spaces)."""
    game = path.parent.name if path.parent.name in _known_games() else ""
    stem = path.stem
    if not game and "__" in stem:
        game, stem = stem.split("__", 1)
    return game, stem.replace("_", " ").strip()


def _encode(src: Path, dst: Path, dry: bool) -> bool:
    c = _cfg()
    w, h = str(c.get("size", "1080x1920")).lower().split("x")
    args = [
        "-i", str(src),
        "-vf", (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"),
        "-r", str(c.get("fps", 60)),
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(c.get("bitrate", "12M")),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(dst),
    ]
    if dry:
        print("    ffmpeg " + " ".join(args))
        return True
    rc, err = ffmpeg.run(args, timeout=1800)
    if rc != 0:
        print(f"    encode failed: {err[-300:]}")
    return rc == 0 and Path(dst).exists()


def main() -> None:
    dry = "--dry" in sys.argv
    ready = ROOT / _cfg().get("dir", "reels/assets/ready")
    vids = [p for p in ready.rglob("*") if p.is_file()
            and p.suffix.lower() in VIDEO_EXTS and not p.stem.endswith("_enc")]
    if not vids:
        print(f"No reels found in {ready}.")
        print("Drop finished 1080x1920 reels there, named with the caption "
              "(e.g. spider-man1/Fisk is caught.mp4).")
        return
    if ffmpeg.ffmpeg_bin() is None:
        print("[x] ffmpeg not found.")
        return
    token = _token()
    if not token and not dry:
        print("[x] No GitHub token (set GH_TOKEN or run `gh auth login`).")
        return
    print(f"Found {len(vids)} reel(s) to queue.\n")
    for v in vids:
        game, caption = _game_caption(v)
        name = f"{_sanitize(game) or 'reel'}__{_sanitize(caption)}.mp4"
        print(f"- {v.name}\n    game={game or '(none)'}  caption='{caption}'  -> {name}")
        enc = v.with_name(v.stem + "_enc.mp4")
        if not _encode(v, enc, dry):
            continue
        if dry:
            continue
        rel = _release(token)
        existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
        if name in existing:
            requests.delete(f"{API}/repos/{_repo()}/releases/assets/{existing[name]}",
                            headers=_h(token))
        up = rel["upload_url"].split("{")[0]
        mb = enc.stat().st_size / 1024 / 1024
        print(f"    uploading ({mb:.0f} MB)...", flush=True)
        with open(enc, "rb") as fh:
            r = requests.post(f"{up}?name={name}",
                              headers={**_h(token), "Content-Type": "video/mp4"}, data=fh)
        print(f"    {'queued OK' if r.ok else 'UPLOAD FAILED ' + str(r.status_code)}")
        enc.unlink(missing_ok=True)
    print("\nDone. Queued reels post automatically on the ready-reels schedule.")


if __name__ == "__main__":
    main()
