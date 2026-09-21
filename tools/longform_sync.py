"""Move 4K 60FPS long-form source footage to B2 (per user 2026-09-21).

    reels/assets/4k60fps/<game>/parts/<file>     ->  B2 4k60fps/<game>/parts/<file>
    reels/assets/4k60fps/<game>/segments/<file>  ->  B2 4k60fps/<game>/segments/<file>

rclone MOVE = verified upload, then the local copy is freed. The .gitkeep placeholders are
never moved, so every folder survives for the next batch. Files touched in the last 2 min
are skipped (a copy still in progress is never uploaded half-done). rclone keeps each file's
modified time on B2, which the uploader uses to order recordings.

  python tools/longform_sync.py              # every game
  python tools/longform_sync.py wolverine    # one game folder
  python tools/longform_sync.py --keep-local # upload but keep the local files
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import CONFIG          # noqa: E402
from core import b2_store               # noqa: E402
from tools.footage import _b2_env       # noqa: E402

SRC = ROOT / "reels" / "assets" / "4k60fps"


def sync(delete_local: bool = True, only_game: str | None = None) -> int:
    if not SRC.exists():
        sys.exit(f"long-form folder not found: {SRC}")
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    bucket = b2_store._bucket()
    if not bucket:
        sys.exit("No B2 bucket set (longform_archive.bucket)")
    src = (SRC / only_game) if only_game else SRC
    dst = f"{remote}:{bucket}/{b2_store.LONGFORM_PREFIX}" + (f"/{only_game}" if only_game else "")
    verb = "move" if delete_local else "copy"
    args = ["rclone", verb, str(src), dst, "--min-age", "2m", "--transfers", "4",
            "--b2-chunk-size", "100M", "--exclude", ".gitkeep", "--exclude", ".cache/**",
            "--exclude", "*.part", "-v", "--stats", "30s", "--stats-one-line"]
    print(f"[longform sync] {verb} {src} -> {dst}", flush=True)
    rc = subprocess.run(args, env=_b2_env(remote)).returncode
    print(f"[longform sync] rclone {verb} rc={rc}"
          + ("  (verified + local freed)" if delete_local and rc == 0 else ""), flush=True)
    return rc


if __name__ == "__main__":
    argv = sys.argv[1:]
    game = next((a for a in argv if not a.startswith("-")), None)
    raise SystemExit(sync(delete_local="--keep-local" not in argv, only_game=game))
