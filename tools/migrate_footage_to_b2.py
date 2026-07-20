"""One-off migration: move gameplay clips off the GitHub 'footage' Release(s) into
Backblaze B2 (footage/<game>/<name>), then delete the Release copy.

Two phases (safe overlap: clips can live on BOTH sources meanwhile because their
render ledger clip-id -- '<game>__<name>' -- is IDENTICAL on B2 and GitHub, so the
no-repeat picker de-dups them):

  COPY (default): download each clip from GitHub -> rclone copyto B2 -> verify size.
                  Leaves the GitHub copy intact. Nothing in CI needs B2 creds yet.
  PURGE (--purge): for every clip already verified on B2 (size matches the GitHub
                  asset), delete the GitHub copy. Run this only AFTER CI is
                  confirmed reading B2. No downloads.

B2 filename = the asset name with its '<game>__' prefix stripped.
Resumable (re-run to continue).

Usage:
  python tools/migrate_footage_to_b2.py             # COPY all games (spider-man2 first)
  python tools/migrate_footage_to_b2.py spider-man2   # COPY one game
  python tools/migrate_footage_to_b2.py --purge      # delete GitHub copies already on B2
  python tools/migrate_footage_to_b2.py --dry        # list what WOULD move, no changes
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core.config import CONFIG, ROOT  # noqa: E402
from core import gh_release  # noqa: E402

try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

API = "https://api.github.com"
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


def _fcfg() -> dict:
    return CONFIG.reels.get("footage", {}) or {}


def _b2() -> tuple[dict, str, str, str]:
    """(rclone_env, remote, bucket, prefix)."""
    la = CONFIG.raw().get("longform_archive", {}) or {}
    bucket = str(_fcfg().get("b2_bucket") or la.get("bucket") or "")
    remote = str(la.get("remote", "kgb2"))
    prefix = str(_fcfg().get("b2_prefix", "footage")).strip("/")
    kid, key = CONFIG._key("B2_KEY_ID"), CONFIG._key("B2_APP_KEY")
    if not (kid and key and bucket):
        sys.exit("Missing B2_KEY_ID / B2_APP_KEY / bucket")
    env = dict(os.environ)
    env[f"RCLONE_CONFIG_{remote.upper()}_TYPE"] = "b2"
    env[f"RCLONE_CONFIG_{remote.upper()}_ACCOUNT"] = kid
    env[f"RCLONE_CONFIG_{remote.upper()}_KEY"] = key
    return env, remote, bucket, prefix


def _b2_size(env, remote, bucket, prefix, game, name) -> int:
    """Size of footage/<game>/<name> on B2, or -1 if absent."""
    r = subprocess.run(
        ["rclone", "lsf", "--format", "s",
         f"{remote}:{bucket}/{prefix}/{game}/{name}"],
        env=env, capture_output=True, text=True)
    out = (r.stdout or "").strip()
    try:
        return int(out) if out else -1
    except ValueError:
        return -1


def _headers() -> dict:
    tok = gh_release._token()
    h = {"Accept": "application/vnd.github+json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _footage_shard_tags() -> list[str]:
    return [str(s["tag"]) for s in gh_release._footage_releases()]


def _game_of(asset_name: str) -> str | None:
    m = re.match(r"^(.+?)__", asset_name)
    return m.group(1) if m else None


def main() -> None:
    args = sys.argv[1:]
    dry = "--dry" in args
    purge = "--purge" in args
    only = next((a for a in args if not a.startswith("-")), None)
    env, remote, bucket, prefix = _b2()
    repo = _fcfg().get("release_repo")

    # gather every '<game>__*.<video>' asset across the footage shard releases
    items: list[dict] = []
    for tag in _footage_shard_tags():
        for a in gh_release.list_release_assets(tag):
            name = a.get("name", "")
            game = _game_of(name)
            if not game or Path(name).suffix.lower() not in VIDEO_EXTS:
                continue
            if only and game != only:
                continue
            items.append({"tag": tag, "id": a.get("id"), "name": name, "game": game,
                          "size": int(a.get("size", 0) or 0),
                          "b2name": name[len(game) + 2:]})  # strip '<game>__'

    # spider-man2 first (the active game), then the rest
    items.sort(key=lambda x: (x["game"] != "spider-man2", x["game"], x["name"]))
    by_game: dict[str, int] = {}
    for it in items:
        by_game[it["game"]] = by_game.get(it["game"], 0) + 1
    mode = "PURGE (delete GitHub copies already on B2)" if purge else "COPY (GitHub -> B2, keep GitHub)"
    print(f"[migrate] {len(items)} clips across {len(by_game)} games: {by_game}", flush=True)
    print(f"[migrate] mode: {mode}", flush=True)
    if dry:
        print("[migrate] --dry: no changes made."); return

    if purge:
        purged = kept = 0
        for i, it in enumerate(items, 1):
            game, b2name, gsz = it["game"], it["b2name"], it["size"]
            b2sz = _b2_size(env, remote, bucket, prefix, game, b2name)
            if b2sz > 0 and (gsz == 0 or b2sz == gsz):   # verified on B2
                gh_release.delete_asset(it["id"], repo)
                purged += 1
                if purged % 25 == 0:
                    print(f"  purged {purged}...", flush=True)
            else:
                kept += 1
                print(f"[{i}/{len(items)}] {game}/{b2name}: NOT verified on B2 "
                      f"(b2={b2sz} gh={gsz}) -- kept on GitHub", flush=True)
        print(f"\n[migrate] purge done: deleted {purged} GitHub copies, kept {kept}", flush=True)
        return

    # COPY phase
    moved = already = failed = 0
    tmpdir = Path(tempfile.gettempdir()) / "kg_migrate"
    tmpdir.mkdir(exist_ok=True)
    for i, it in enumerate(items, 1):
        game, name, b2name, gsz = it["game"], it["name"], it["b2name"], it["size"]
        tag = f"{i}/{len(items)}"
        # already on B2 with matching size? -> skip (resume)
        b2sz = _b2_size(env, remote, bucket, prefix, game, b2name)
        if b2sz > 0 and (gsz == 0 or b2sz == gsz):
            already += 1
            continue
        # download from GitHub (by asset id, octet-stream)
        local = tmpdir / name
        try:
            with requests.get(f"{API}/repos/{repo}/releases/assets/{it['id']}",
                              headers={**_headers(), "Accept": "application/octet-stream"},
                              stream=True, timeout=1800) as r:
                if r.status_code != 200:
                    print(f"[{tag}] {name}: GH download {r.status_code} -- skip", flush=True)
                    failed += 1
                    continue
                with open(local, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            fh.write(chunk)
        except Exception as e:
            print(f"[{tag}] {name}: download err {e!r} -- skip", flush=True)
            failed += 1
            continue
        lsz = local.stat().st_size
        # upload to B2 (rclone-verified), confirm size. Leave GitHub intact.
        up = subprocess.run(
            ["rclone", "copyto", str(local),
             f"{remote}:{bucket}/{prefix}/{game}/{b2name}",
             "--b2-chunk-size", "100M"], env=env).returncode
        if up == 0 and _b2_size(env, remote, bucket, prefix, game, b2name) == lsz:
            moved += 1
            print(f"[{tag}] {game}/{b2name} ({lsz/1024/1024:.0f} MB) -> B2 (GitHub kept)", flush=True)
        else:
            failed += 1
            print(f"[{tag}] {game}/{b2name}: B2 verify FAILED (up rc={up}) -- retry later", flush=True)
        try:
            local.unlink(missing_ok=True)
        except Exception:
            pass

    print(f"\n[migrate] copy done: copied {moved}, already-on-B2 {already}, failed {failed}."
          f"\n[migrate] GitHub copies still in place. After CI reads B2, run: "
          f"python tools/migrate_footage_to_b2.py --purge", flush=True)


if __name__ == "__main__":
    main()
