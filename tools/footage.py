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
import time
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core.config import CONFIG, ROOT  # noqa: E402

# Use the OS trust store so HTTPS verifies behind Avast's TLS interception on the
# local machine (no-op / skipped in CI where truststore isn't installed).
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    _truststore = None

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


def _all_releases(token: str) -> list[dict]:
    """Every release on the repo (paginated)."""
    repo = _repo()
    out: list[dict] = []
    for page in range(1, 50):
        r = requests.get(f"{API}/repos/{repo}/releases?per_page=100&page={page}",
                         headers=_h(token))
        if r.status_code != 200:
            break
        chunk = r.json() or []
        out += chunk
        if len(chunk) < 100:
            break
    return out


def _get_or_create_release(token: str, tag: str, name: str, body: str) -> dict:
    """Fetch the release for `tag`, creating it (as a prerelease, not 'latest')
    if it doesn't exist. Used for the qimg-NN quote-image overflow shards."""
    repo = _repo()
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=_h(token))
    if r.status_code == 200:
        return r.json()
    print(f"Creating overflow release '{tag}' on {repo}...", flush=True)
    r = requests.post(
        f"{API}/repos/{repo}/releases", headers=_h(token),
        json={"tag_name": tag, "name": name, "body": body,
              "prerelease": True, "make_latest": "false"})
    r.raise_for_status()
    return r.json()


def _gh_name(game: str, filename: str) -> str:
    """The asset name GitHub will store: each RUN of non [A-Za-z0-9._-] chars
    becomes a single '.', and consecutive dots collapse (matches GitHub)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", ".", f"{game}__{filename}")
    return re.sub(r"\.+", ".", s)


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


FOOTAGE_CAP = 995  # leave headroom under GitHub's 1000-assets-per-release cap


def _footage_shards(token: str) -> list[dict]:
    """[{tag,id,up}] holding clips: footage release first, then footage-NN asc."""
    base = _tag()
    res = []
    for rel in _all_releases(token):
        t = str(rel.get("tag_name", ""))
        if t == base or re.match(r"^footage-\d+$", t):
            res.append({"tag": t, "id": rel["id"], "up": rel["upload_url"].split("{")[0]})
    res.sort(key=lambda r: (0 if r["tag"] == base else 1, r["tag"]))
    return res


def _shard_assets(token: str, rid):
    """(count, set-of-names) for a release, paginated."""
    repo = _repo(); names = set()
    for page in range(1, 400):
        r = requests.get(f"{API}/repos/{repo}/releases/{rid}/assets?per_page=100&page={page}",
                         headers=_h(token))
        if r.status_code != 200:
            break
        ch = r.json() or []
        names |= {a["name"] for a in ch}
        if len(ch) < 100:
            break
    return len(names), names


def _next_footage_tag(shards) -> str:
    nums = [int(s["tag"].split("-")[1]) for s in shards if s["tag"].startswith("footage-")]
    return f"footage-{(max(nums) + 1) if nums else 2:02d}"


def _upload_clip(up_url: str, token: str, name: str, path: Path, ct: str) -> str:
    """Stream-upload one clip. Returns 'ok' | 'full' | 'fail'."""
    for attempt in range(3):
        try:
            with open(path, "rb") as fh:
                r = requests.post(f"{up_url}?name={name}",
                                  headers={**_h(token), "Content-Type": ct},
                                  data=fh, timeout=3600)
            if r.ok:
                return "ok"
            if r.status_code in (403, 422) and "already_exists" in r.text:
                return "ok"
            if r.status_code == 422 and "file_count" in r.text:
                return "full"
            if r.status_code in (403, 429):
                time.sleep(20 * (attempt + 1)); continue
            print(f"    upload {name} -> {r.status_code} {r.text[:160]}", flush=True)
            return "fail"
        except Exception as e:
            print(f"    upload {name} err: {e!r}", flush=True)
            time.sleep(5)
    return "fail"


def sync(delete_local: bool = True, only_game: str | None = None) -> None:
    """Scan footage folders and push clips to the cloud, SHARDING across the
    footage release + footage-NN overflow releases (GitHub caps a release at 1000
    assets). Each clip confirmed on the cloud has its LOCAL copy deleted to free
    disk. Pass only_game to limit to one game, delete_local=False to keep."""
    base = ROOT / (_cfg().get("dir", "reels/assets/footage"))
    if not base.exists():
        sys.exit(f"Footage dir not found: {base}")
    token = _token()
    shards = _footage_shards(token)
    if not shards:
        rel = _release(token)
        shards = [{"tag": _tag(), "id": rel["id"], "up": rel["upload_url"].split("{")[0]}]
    done = set(); counts = {}
    for s in shards:
        counts[s["tag"]], names = _shard_assets(token, s["id"])
        done |= names

    def current_target():
        for s in shards:
            if counts[s["tag"]] < FOOTAGE_CAP:
                return s
        tag = _next_footage_tag(shards)
        rel = _get_or_create_release(token, tag, f"Reel footage {tag}",
                                     "Overflow gameplay clips (GitHub caps releases at 1000 assets).")
        s = {"tag": tag, "id": rel["id"], "up": rel["upload_url"].split("{")[0]}
        shards.append(s); counts[tag] = 0; return s

    uploaded = already = deleted = failed = toobig = 0
    for sub in sorted(p for p in base.iterdir()
                      if p.is_dir() and not p.name.startswith(".")):
        game = sub.name
        if only_game and game != only_game:
            continue
        for f in sorted(sub.iterdir()):
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXTS:
                continue
            # Skip files changed in the last ~2 min — they may still be copying, and a
            # scheduled sync could otherwise upload a partial clip then delete it locally.
            if delete_local and (time.time() - f.stat().st_mtime) < 120:
                continue
            name = _gh_name(game, f.name)
            if name in done:
                already += 1
                if delete_local:
                    try: f.unlink(); deleted += 1
                    except Exception: pass
                continue
            if f.stat().st_size > RELEASE_MAX:
                print(f"  TOO BIG ({f.stat().st_size/1024**3:.1f} GB > 2GB), skipped: {f.name}")
                toobig += 1
                continue
            ct = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            print(f"[{game}] {f.name} ({f.stat().st_size/1024/1024:.0f} MB)", flush=True)
            ok = False
            for _ in range(len(shards) + 3):
                tgt = current_target()
                res = _upload_clip(tgt["up"], token, name, f, ct)
                if res == "ok":
                    counts[tgt["tag"]] += 1; ok = True
                    print(f"    -> {tgt['tag']}", flush=True)
                    break
                if res == "full":
                    counts[tgt["tag"]] = FOOTAGE_CAP + 1; continue
                break
            if ok:
                done.add(name); uploaded += 1
                if delete_local:
                    try: f.unlink(); deleted += 1
                    except Exception as e: print(f"    could not delete local ({e!r}).")
            else:
                failed += 1; print("    upload failed -- keeping local.")
    print(f"\nsync done: uploaded {uploaded}, already {already}, local-deleted {deleted}, "
          f"failed {failed}, too-big {toobig}; shards: {[s['tag'] for s in shards]}")


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
