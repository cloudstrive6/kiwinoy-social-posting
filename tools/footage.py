"""Manage large reel footage on the GitHub 'footage' release (>100MB clips).

Big gameplay clips can't be committed (GitHub caps repo files at 100MB), so they
live as Release assets (up to 2GB each, free). The reel renderer auto-discovers
them by their "<game>__" name prefix and downloads what it needs at render time.

Usage:
  python tools/footage.py upload <game> <file> [<file> ...]
  python tools/footage.py list
  python tools/footage.py delete <asset-name>

<game> is one of the footage folders: mlbb, dota2, cs2, lol, genshin, hsr, nte,
ff7, re, halo, general.

Examples:
  python tools/footage.py upload mlbb "C:/clips/onic vs bren game5.mp4"
  python tools/footage.py list
"""
from __future__ import annotations

import mimetypes
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core.config import CONFIG  # noqa: E402

API = "https://api.github.com"


def _cfg() -> dict:
    return CONFIG.reels.get("footage", {}) or {}


def _repo() -> str:
    repo = _cfg().get("release_repo")
    if not repo:
        sys.exit("config reels.footage.release_repo is not set.")
    return repo


def _tag() -> str:
    return _cfg().get("release_tag", "footage")


def _token() -> str:
    import os
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except FileNotFoundError:
        pass
    sys.exit("No GitHub token. Run `gh auth login`, or set GH_TOKEN.")


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _release(token: str) -> dict:
    repo, tag = _repo(), _tag()
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=_h(token))
    if r.status_code == 200:
        return r.json()
    print(f"Creating release '{tag}' on {repo}...")
    r = requests.post(
        f"{API}/repos/{repo}/releases", headers=_h(token),
        json={"tag_name": tag, "name": "Reel footage",
              "body": "Large gameplay clips (>100MB) for KiwinoyGamer reels."},
    )
    r.raise_for_status()
    return r.json()


def upload(game: str, files: list[str]) -> None:
    token = _token()
    rel = _release(token)
    repo = _repo()
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload_url = rel["upload_url"].split("{")[0]
    for f in files:
        p = Path(f)
        if not p.exists():
            print(f"  SKIP (not found): {f}")
            continue
        name = f"{game}__{p.name}"
        if name in existing:  # replace
            requests.delete(
                f"{API}/repos/{repo}/releases/assets/{existing[name]}",
                headers=_h(token),
            )
        ct = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        size_mb = p.stat().st_size / 1024 / 1024
        print(f"  Uploading {name} ({size_mb:.0f} MB)...", flush=True)
        with open(p, "rb") as fh:
            r = requests.post(
                f"{upload_url}?name={name}",
                headers={**_h(token), "Content-Type": ct}, data=fh,
            )
        print(f"    {'OK' if r.ok else 'FAILED ' + str(r.status_code) + ': ' + r.text[:200]}")


def list_assets() -> None:
    rel = _release(_token())
    assets = rel.get("assets", [])
    if not assets:
        print("(no footage assets yet)")
        return
    for a in sorted(assets, key=lambda x: x["name"]):
        print(f'  {a["name"]:55s} {a["size"]//1024//1024:>5} MB')


def delete(name: str) -> None:
    token = _token()
    rel = _release(token)
    repo = _repo()
    for a in rel.get("assets", []):
        if a["name"] == name:
            requests.delete(
                f"{API}/repos/{repo}/releases/assets/{a['id']}", headers=_h(token)
            )
            print(f"Deleted {name}")
            return
    print(f"No asset named {name}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == "upload":
        upload(args[1], args[2:])
    elif len(args) == 1 and args[0] == "list":
        list_assets()
    elif len(args) == 2 and args[0] == "delete":
        delete(args[1])
    else:
        print(__doc__)
