r"""Auto-archive the unified 4K/60 HDR SOURCE intake to Backblaze B2, then free local
disk. This is the "paste and forget" companion to the 4K HDR source folders:

  reels/assets/4k-hdr/<game>/   <- paste raw 4K/60 HDR captures here (feeds BOTH the
                                   long-form pillar AND the YouTube Shorts source)

`sync` uploads every settled file to B2, VERIFIES it, then DELETES the local copy once
it's verified AND older than the grace window (config source_4k.free_after_hours), so
your drive stays lean. A game you're still editing can be PINNED (a .keep file in its
folder) to pause freeing until you're done.

Reuses the longform_archive B2 bucket + rclone remote + .env creds (B2_KEY_ID /
B2_APP_KEY). One-time setup is the same as tools/archive_longform.py.

Usage (run in the project folder):
  python tools/archive_4k.py sync                 # all games: upload new + free verified
  python tools/archive_4k.py sync <game>          # just one game
  python tools/archive_4k.py sync --dry-run       # show what would upload/free, do nothing
  python tools/archive_4k.py free <game>          # free verified files NOW (skip the grace)
  python tools/archive_4k.py pull <game> [file]   # bring a game's source (or one file) back
  python tools/archive_4k.py pin <game>           # pause auto-free while you edit
  python tools/archive_4k.py unpin <game>
  python tools/archive_4k.py list [game]          # what's archived on B2

Scheduled: run_4k_sync.bat is the runner; point a Windows Task Scheduler job at it
(e.g. every 30 min). Logs go to output\.archive_4k.log.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import CONFIG, ROOT  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".ts"}
PIN = ".keep"


def _scfg() -> dict:
    return CONFIG.source_4k or {}


def _acfg() -> dict:
    return CONFIG.raw().get("longform_archive", {}) or {}


def _rclone_env() -> tuple[dict, str]:
    """Configure a B2 rclone remote from .env via env vars (no interactive setup)."""
    kid, key = CONFIG.b2_key_id, CONFIG.b2_app_key
    if not kid or not key:
        sys.exit("B2_KEY_ID / B2_APP_KEY missing in .env (see tools/archive_longform.py).")
    remote = str(_acfg().get("remote", "kgb2"))
    env = dict(os.environ)
    env[f"RCLONE_CONFIG_{remote.upper()}_TYPE"] = "b2"
    env[f"RCLONE_CONFIG_{remote.upper()}_ACCOUNT"] = kid
    env[f"RCLONE_CONFIG_{remote.upper()}_KEY"] = key
    return env, remote


def _rclone(args: list[str], env: dict, capture: bool = False):
    if not shutil.which("rclone"):
        sys.exit("rclone not found. Install it: https://rclone.org/downloads/")
    if capture:
        return subprocess.run(["rclone", *args], env=env, capture_output=True, text=True)
    return subprocess.run(["rclone", *args], env=env).returncode


def _source_root() -> Path:
    return ROOT / str(_scfg().get("source_dir", "reels/assets/4k-hdr"))


def _dst(game: str, remote: str) -> str:
    bucket = _acfg().get("bucket")
    if not bucket:
        sys.exit("longform_archive.bucket is not set in config.yaml")
    prefix = str(_scfg().get("bucket_path", "4k-hdr")).strip("/")
    return f"{remote}:{bucket}/{prefix}/{game}"


def _games(one: str | None) -> list[str]:
    root = _source_root()
    if one:
        return [one]
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir())


def _pinned(game: str) -> bool:
    return (_source_root() / game / PIN).exists()


def _media(game_dir: Path) -> list[Path]:
    return sorted(p for p in game_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def sync(one: str | None, dry: bool = False) -> None:
    env, remote = _rclone_env()
    settle = float(_scfg().get("min_settle_minutes", 2))
    grace_h = float(_scfg().get("free_after_hours", 12))
    transfers = str(_scfg().get("transfers", 4))
    now = time.time()
    games = _games(one)
    if not games:
        print(f"No game folders under {_source_root()} — paste files into "
              f"{_source_root()}\\<game>\\ first.")
        return
    freed_total = 0
    for game in games:
        gdir = _source_root() / game
        files = _media(gdir)
        if not files:
            continue
        settled = [f for f in files if (now - f.stat().st_mtime) >= settle * 60]
        skipped = len(files) - len(settled)
        print(f"[{game}] {len(files)} file(s)"
              + (f", {skipped} still settling (skipped)" if skipped else "")
              + (" [PINNED: no auto-free]" if _pinned(game) else ""), flush=True)
        if not settled:
            continue
        dst = _dst(game, remote)
        if dry:
            print(f"  would upload {len(settled)} settled file(s) -> {dst}")
        else:
            # Upload settled files (copy = add/update, never deletes the remote).
            rc = _rclone(["copy", str(gdir), dst, "--min-age", f"{settle}m",
                          "--progress", "--transfers", transfers,
                          "--b2-hard-delete"], env)
            if rc != 0:
                print(f"  upload FAILED (rc={rc}) — nothing freed for {game}.")
                continue
        # Verify the settled files are all on B2 before freeing anything.
        chk = _rclone(["check", str(gdir), dst, "--one-way", "--min-age", f"{settle}m"], env)
        if chk != 0:
            print(f"  verify FAILED for {game} — NOT freeing (will retry next sync).")
            continue
        if _pinned(game):
            continue                                   # pinned: verified backup, keep local
        # Free files verified on B2 + older than the grace window.
        for f in settled:
            age_h = (now - f.stat().st_mtime) / 3600.0
            if age_h < grace_h:
                continue
            if dry:
                print(f"  would free {f.name} ({f.stat().st_size / 1024**3:.1f} GB, "
                      f"{age_h:.1f}h old)")
            else:
                sz = f.stat().st_size
                f.unlink()
                freed_total += sz
                print(f"  freed {f.name} ({sz / 1024**3:.1f} GB) — on B2, {age_h:.1f}h old",
                      flush=True)
    if not dry and freed_total:
        print(f"Done. Local disk freed this run: {freed_total / 1024**3:.1f} GB.")
    elif not dry:
        print("Done. (Nothing eligible to free yet — files still within the grace window "
              "or pinned.)")


def free(game: str) -> None:
    """Force-free a game's source NOW: verify each file is on B2, then delete local
    (ignores the grace window; still respects nothing else — this is deliberate)."""
    env, remote = _rclone_env()
    gdir = _source_root() / game
    if not gdir.is_dir():
        sys.exit(f"not a folder: {gdir}")
    dst = _dst(game, remote)
    print(f"Verifying {gdir} is fully on B2 before freeing...", flush=True)
    # Make sure everything is uploaded first, then verify.
    if _rclone(["copy", str(gdir), dst, "--progress", "--transfers",
                str(_scfg().get("transfers", 4))], env) != 0:
        sys.exit("upload failed — nothing freed.")
    if _rclone(["check", str(gdir), dst, "--one-way"], env) != 0:
        sys.exit("verify FAILED — nothing freed.")
    freed = 0
    for f in _media(gdir):
        sz = f.stat().st_size
        f.unlink()
        freed += sz
        print(f"  freed {f.name} ({sz / 1024**3:.1f} GB)")
    print(f"Freed {freed / 1024**3:.1f} GB from {game}.")


def pull(game: str, name: str | None) -> None:
    env, remote = _rclone_env()
    gdir = _source_root() / game
    gdir.mkdir(parents=True, exist_ok=True)
    dst = _dst(game, remote)
    args = ["copy", dst, str(gdir), "--progress", "--transfers",
            str(_scfg().get("transfers", 4))]
    if name:
        args += ["--include", f"/{name}"]
    print(f"Downloading {dst}{('/' + name) if name else ''}  ->  {gdir}", flush=True)
    if _rclone(args, env) != 0:
        sys.exit("download failed.")
    print("Done.")


def pin(game: str, on: bool) -> None:
    gdir = _source_root() / game
    gdir.mkdir(parents=True, exist_ok=True)
    marker = gdir / PIN
    if on:
        marker.write_text("auto-free paused while editing\n", encoding="utf-8")
        print(f"Pinned {game}: auto-free paused (uploads still happen). "
              f"Remove with: python tools/archive_4k.py unpin {game}")
    else:
        if marker.exists():
            marker.unlink()
        print(f"Unpinned {game}: auto-free resumes on the next sync.")


def lst(game: str | None) -> None:
    env, remote = _rclone_env()
    bucket = _acfg().get("bucket")
    prefix = str(_scfg().get("bucket_path", "4k-hdr")).strip("/")
    base = f"{remote}:{bucket}/{prefix}" + (f"/{game}" if game else "")
    _rclone((["ls"] if game else ["lsd"]) + [base], env)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    dry = "--dry-run" in rest
    rest = [a for a in rest if a != "--dry-run"]
    if cmd == "sync":
        sync(rest[0] if rest else None, dry=dry)
    elif cmd == "free" and rest:
        free(rest[0])
    elif cmd == "pull" and rest:
        pull(rest[0], rest[1] if len(rest) > 1 else None)
    elif cmd == "pin" and rest:
        pin(rest[0], on=True)
    elif cmd == "unpin" and rest:
        pin(rest[0], on=False)
    elif cmd == "list":
        lst(rest[0] if rest else None)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
