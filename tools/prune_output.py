"""Prune old rendered VIDEO files from output/ to reclaim disk.

output/ is gitignored scratch: every local render drops its MP4 there and NOTHING
auto-cleans it, so it grows unbounded (it reached 184 GB once). This deletes only
video files (mp4/mov/mkv/webm/m4v) older than the retention window, and KEEPS the
briefs/captions/results/logs/thumbnails so the run history stays intact.

Runs automatically at the start of every local run.py invocation (fail-open, quiet).
Also runnable by hand:
  python tools/prune_output.py              # use config output.video_retention_days (default 7)
  python tools/prune_output.py --days 3
  python tools/prune_output.py --dry-run    # report only, delete nothing
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import CONFIG, OUTPUT_DIR  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
DEFAULT_DAYS = 7


def retention_days() -> int:
    """Retention window from config output.video_retention_days (fail-open to 7)."""
    try:
        v = int((CONFIG.raw().get("output", {}) or {}).get(
            "video_retention_days", DEFAULT_DAYS))
        return max(0, v)
    except Exception:
        return DEFAULT_DAYS


def prune(days: int | None = None, dry_run: bool = False,
          quiet: bool = False) -> tuple[int, int]:
    """Delete video files under output/ older than `days` (by mtime).

    Returns (files_removed, bytes_freed). NEVER raises — cleanup must not block a
    render. days=0 prunes every video regardless of age.
    """
    if days is None:
        days = retention_days()
    n = freed = 0
    if not OUTPUT_DIR.is_dir():
        return (0, 0)
    cutoff = time.time() - days * 86400
    try:
        for p in OUTPUT_DIR.rglob("*"):
            try:
                if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
                    continue
                if p.stat().st_mtime >= cutoff:
                    continue
                sz = p.stat().st_size
                if not dry_run:
                    p.unlink()
                n += 1
                freed += sz
            except Exception:
                continue
    except Exception:
        pass
    if not quiet and n:
        verb = "would free" if dry_run else "freed"
        print(f"[prune] {'(dry-run) ' if dry_run else ''}{n} video file(s) older "
              f"than {days}d - {verb} {freed / 1024**3:.1f} GiB from output/",
              flush=True)
    return (n, freed)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prune old video renders from output/ (keeps metadata/logs).")
    ap.add_argument("--days", type=int, default=None,
                    help="retention window in days (default: config "
                         "output.video_retention_days, else 7)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only, delete nothing")
    args = ap.parse_args()
    n, _ = prune(days=args.days, dry_run=args.dry_run, quiet=False)
    if not n:
        print("[prune] nothing to prune.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
