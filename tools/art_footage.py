"""Sync game-art TITLE-SCREEN VIDEOS (the triptych bottom-panel loops) to B2.

Record ~5-min title-screen clips (showing the game logo), paste them into
reels/assets/game-art-footage/<game>/ (matched by the footage key, e.g. halo, spider-man2),
then run:
    python tools/art_footage.py sync              # push all games' art videos to B2, free local
    python tools/art_footage.py sync halo         # one game only
    python tools/art_footage.py sync --keep-local # upload but keep the local copies

They land on B2 under art-footage/<game>/ . At render time the triptych builder
(build_gameplay_triptych) loops one on the BOTTOM panel (MUTED), rotating when a game has
several, and falls back to the static game-art image when a game has none. Read via
core.b2_store.list_art_footage. Multiple videos per game => rotation (sorted by name).
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

SRC = ROOT / "reels" / "assets" / "game-art-footage"


def sync(delete_local: bool = True, only_game: str | None = None) -> None:
    """rclone move (verified) reels/assets/game-art-footage/<game>/ -> B2 art-footage/<game>/."""
    if not SRC.exists():
        sys.exit(f"art-footage dir not found: {SRC}")
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    bucket = b2_store._bucket()
    if not bucket:
        sys.exit("No B2 bucket set (longform_archive.bucket)")
    src = (SRC / only_game) if only_game else SRC
    dst = f"{remote}:{bucket}/art-footage" + (f"/{only_game}" if only_game else "")
    verb = "move" if delete_local else "copy"       # move = verified copy + free local
    args = ["rclone", verb, str(src), dst, "--min-age", "2m", "--transfers", "4",
            "--b2-chunk-size", "100M", "--exclude", ".cache/**", "--exclude", "*.part",
            "--exclude", "*.gitkeep", "-v", "--stats", "20s", "--stats-one-line"]
    print(f"[art sync] {verb} {src} -> {dst}", flush=True)
    rc = subprocess.run(args, env=_b2_env(remote)).returncode
    print(f"[art sync] rclone {verb} rc={rc}"
          + ("  (verified + local freed)" if delete_local and rc == 0 else ""), flush=True)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "sync":
        rest = argv[1:]
        keep = "--keep-local" in rest
        game = next((a for a in rest if not a.startswith("-")), None)
        sync(delete_local=not keep, only_game=game)
    else:
        print(__doc__)
