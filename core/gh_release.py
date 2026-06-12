"""GitHub Release footage store.

Large gameplay clips (>100MB, up to 2GB) can't live in the repo, so they're
uploaded as assets on a GitHub Release (tag `footage`). Assets are named
"<game>__<whatever>.mp4"; this module lists the ones for a game and downloads a
chosen asset to a local cache at render time. All calls FAIL-OPEN (return [] or
None) so a network/API hiccup just falls back to local clips or AI stills.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import requests

from core.config import CONFIG

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def _cfg() -> dict[str, Any]:
    return CONFIG.reels.get("footage", {}) or {}


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def list_assets(gamekey: str) -> list[dict[str, str]]:
    """Return [{name, url}] release assets whose name starts with '<gamekey>__'."""
    cfg = _cfg()
    if not cfg.get("use_releases"):
        return []
    repo = cfg.get("release_repo")
    tag = cfg.get("release_tag", "footage")
    if not repo:
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
    prefix = f"{gamekey}__"
    out = []
    for a in assets:
        name = a.get("name", "")
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
        {"name": a.get("name", ""), "url": a.get("browser_download_url", "")}
        for a in assets if a.get("browser_download_url")
    ]


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
