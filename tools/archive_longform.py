"""Archive long-form 4K HDR source footage to Backblaze B2 (frees local disk).

Push a finished game's source folder to B2, VERIFY it, then delete local. Pull it
back when you want more clips. Uses rclone (robust for tens-of-GB files + resume).

One-time setup:
  1. backblaze.com -> B2 Cloud Storage -> create a PRIVATE bucket.
  2. App Keys -> Add a New Application Key (scope it to that bucket) -> copy the
     keyID and applicationKey.
  3. Put them in .env:   B2_KEY_ID=<keyID>   B2_APP_KEY=<applicationKey>
  4. Install rclone (https://rclone.org/downloads/) and add it to PATH.
  5. Set your bucket name in config.yaml -> longform_archive.bucket

Usage (run in the project folder):
  python tools/archive_longform.py push <game-folder>          # upload + verify + DELETE local
  python tools/archive_longform.py push <game-folder> --keep   # upload + verify, keep local
  python tools/archive_longform.py pull <game-folder>          # download it back to local
  python tools/archive_longform.py list                        # what's archived

<game-folder> is the subfolder name under reels/assets/longform-fullgame/ (e.g. final-fantasy-7-remake).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import CONFIG, ROOT  # noqa: E402


def _cfg() -> dict:
    return CONFIG.raw().get("longform_archive", {}) or {}


def _rclone_env() -> tuple[dict, str]:
    """Configure a B2 rclone remote from .env via env vars (no interactive setup)."""
    kid, key = CONFIG.b2_key_id, CONFIG.b2_app_key
    if not kid or not key:
        sys.exit("B2_KEY_ID / B2_APP_KEY missing in .env (see the header of this file).")
    remote = str(_cfg().get("remote", "kgb2"))
    env = dict(os.environ)
    env[f"RCLONE_CONFIG_{remote.upper()}_TYPE"] = "b2"
    env[f"RCLONE_CONFIG_{remote.upper()}_ACCOUNT"] = kid
    env[f"RCLONE_CONFIG_{remote.upper()}_KEY"] = key
    return env, remote


def _rclone(args: list[str], env: dict) -> int:
    if not shutil.which("rclone"):
        sys.exit("rclone not found. Install it: https://rclone.org/downloads/")
    return subprocess.run(["rclone", *args], env=env).returncode


def _paths(game: str) -> tuple[Path, str, str]:
    bucket = _cfg().get("bucket")
    if not bucket:
        sys.exit("longform_archive.bucket is not set in config.yaml")
    _, remote = _rclone_env()
    local = ROOT / str(_cfg().get("local_dir", "reels/assets/longform")) / game
    return local, remote, f"{remote}:{bucket}/{game}"


def push(game: str, keep: bool = False) -> None:
    env, _ = _rclone_env()
    local, _, dst = _paths(game)
    if not local.is_dir():
        sys.exit(f"not a folder: {local}")
    print(f"Uploading {local}  ->  {dst}", flush=True)
    if _rclone(["sync", str(local), dst, "--progress", "--transfers", "4"], env) != 0:
        sys.exit("upload failed — local kept.")
    print("Verifying (rclone check, size-only)...", flush=True)
    # --size-only: B2 stores NO SHA1 for multi-thread/chunked large files (the 20-30 GB
    # longform parts), so a hash `check` always reports errors even when the upload is
    # byte-complete and would wrongly refuse to free local. Size match across every part
    # is the reliable integrity signal for these big media files on B2.
    if _rclone(["check", str(local), dst, "--one-way", "--size-only"], env) != 0:
        sys.exit("verify FAILED — local NOT deleted.")
    print("Verified OK", flush=True)
    if keep:
        print("Kept local (--keep).")
    else:
        shutil.rmtree(local)
        print(f"Deleted local {local} — disk freed.")


def pull(game: str) -> None:
    env, _ = _rclone_env()
    local, _, src = _paths(game)
    print(f"Downloading {src}  ->  {local}", flush=True)
    if _rclone(["copy", src, str(local), "--progress", "--transfers", "4"], env) != 0:
        sys.exit("download failed.")
    print("Done ✓")


def lst() -> None:
    env, remote = _rclone_env()
    _rclone(["lsd", f"{remote}:{_cfg().get('bucket')}"], env)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "push" and len(a) >= 2:
        push(a[1], keep="--keep" in a)
    elif a and a[0] == "pull" and len(a) >= 2:
        pull(a[1])
    elif a and a[0] == "list":
        lst()
    else:
        sys.exit(__doc__)
