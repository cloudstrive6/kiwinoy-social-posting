"""Manage large reel footage on the GitHub 'footage' release (>100MB clips).

Big gameplay clips can't be committed (GitHub caps repo files at 100MB), so they
live as Release assets (up to 2GB each, free). The reel renderer auto-discovers
them by their "<game>__" name prefix and downloads what it needs at render time.

Usage:
  python tools/footage.py sync                 # auto-upload every >100MB clip
  python tools/footage.py upload <game> <file> [<file> ...]
  python tools/footage.py list
  python tools/footage.py delete <asset-name>

`sync` scans the footage folders and uploads any clip over ~95MB to the release
(named "<folder>__<file>"), skipping ones already there. Smaller clips are left
for a normal git commit. Just paste clips into reels/assets/footage/<game>/ and
run sync (or commit the small ones).

<game> is one of the footage folders: mlbb, dota2, cs2, lol, genshin, hsr, nte,
ff7, re, halo, general.

Examples:
  python tools/footage.py upload mlbb "C:/clips/onic vs bren game5.mp4"
  python tools/footage.py list
"""
from __future__ import annotations

import mimetypes
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core.config import CONFIG, ROOT  # noqa: E402

API = "https://api.github.com"
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
SIZE_LIMIT = 95 * 1024 * 1024       # ~just under GitHub's 100MB repo file limit
RELEASE_MAX = 1990 * 1024 * 1024    # GitHub Release assets cap at 2GB/file


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


def _gh_name(game: str, filename: str) -> str:
    """The asset name GitHub will store (non [A-Za-z0-9._-] become '.')."""
    return re.sub(r"[^A-Za-z0-9._-]", ".", f"{game}__{filename}")


def upload(game: str, files: list[str]) -> bool:
    """Upload clips to the footage Release. Returns True if all succeeded."""
    token = _token()
    rel = _release(token)
    repo = _repo()
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload_url = rel["upload_url"].split("{")[0]
    ok_all = True
    for f in files:
        p = Path(f)
        if not p.exists():
            print(f"  SKIP (not found): {f}")
            ok_all = False
            continue
        if p.stat().st_size > RELEASE_MAX:
            gb = p.stat().st_size / 1024 / 1024 / 1024
            print(f"  SKIP ({gb:.1f} GB, over GitHub's 2GB Release limit): {p.name}")
            print("       Trim it to a short highlight first (reels use only ~4s).")
            ok_all = False
            continue
        name = _gh_name(game, p.name)
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
        ok_all = ok_all and r.ok
    return ok_all


def sync(delete_local: bool = True, only_game: str | None = None) -> None:
    """Proactively scan footage folders and push UNUSED clips to the cloud.

    Any clip not already on the 'footage' Release is uploaded; once a clip is
    confirmed on the cloud, the LOCAL file is deleted (per the user's rule) to
    free disk. Pass only_game to limit to one game, delete_local=False to keep.
    """
    base = ROOT / (_cfg().get("dir", "reels/assets/footage"))
    if not base.exists():
        sys.exit(f"Footage dir not found: {base}")
    existing = {a["name"] for a in _release(_token()).get("assets", [])}
    uploaded = already = deleted = failed = toobig = 0
    for sub in sorted(p for p in base.iterdir()
                      if p.is_dir() and not p.name.startswith(".")):
        game = sub.name
        if only_game and game != only_game:
            continue
        for f in sorted(sub.iterdir()):
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXTS:
                continue
            if f.stat().st_size > RELEASE_MAX:
                print(f"  TOO BIG ({f.stat().st_size/1024**3:.1f} GB > 2GB), skipped: "
                      f"{f.name} -- trim it first.")
                toobig += 1
                continue
            on_cloud = _gh_name(game, f.name) in existing
            if not on_cloud:
                print(f"[{game}] {f.name}")
                if upload(game, [str(f)]):
                    uploaded += 1
                    on_cloud = True
                else:
                    print("    upload failed -- keeping local.")
                    failed += 1
            else:
                print(f"[{game}] already on cloud: {f.name}")
                already += 1
            if on_cloud and delete_local:
                try:
                    f.unlink()
                    deleted += 1
                    print("    deleted local copy.")
                except Exception as e:
                    print(f"    could not delete local ({e!r}).")
    print(f"\nsync done: uploaded {uploaded}, already-present {already}, "
          f"local-deleted {deleted}, failed {failed}, too-big {toobig}")


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
    if args and args[0] == "sync":
        game = next((a for a in args[1:] if not a.startswith("-")), None)
        sync(delete_local="--keep-local" not in args, only_game=game)
    elif len(args) >= 3 and args[0] == "upload":
        upload(args[1], args[2:])
    elif len(args) == 1 and args[0] == "list":
        list_assets()
    elif len(args) == 2 and args[0] == "delete":
        delete(args[1])
    else:
        print(__doc__)
