"""Sync CUTSCENE clips to B2 — the source pool for the LORE short format.

Cutscenes live apart from gameplay footage (per user 2026-10-06) so the talky clips only
ever feed the lore cards, and a normal gameplay reel can never pick one.

    reels/assets/cutscenes/<game>/<file>  ->  B2 cutscenes/<game>/<file>

  python tools/cutscenes.py sync                # every game, then free the local copies
  python tools/cutscenes.py sync wolverine      # one game
  python tools/cutscenes.py sync --keep-local   # upload but keep the local files
  python tools/cutscenes.py list                # what is on B2 per game
  python tools/cutscenes.py log [game]          # which SCENES/windows are already used
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

SRC = ROOT / "reels" / "assets" / "cutscenes"


def sync(delete_local: bool = True, only_game: str | None = None) -> None:
    """rclone move (verified upload, then frees the local file) -> B2 cutscenes/<game>/."""
    if not SRC.exists():
        sys.exit(f"cutscenes dir not found: {SRC}")
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    bucket = b2_store._bucket()
    if not bucket:
        sys.exit("No B2 bucket set (longform_archive.bucket)")
    src = (SRC / only_game) if only_game else SRC
    dst = f"{remote}:{bucket}/cutscenes" + (f"/{only_game}" if only_game else "")
    verb = "move" if delete_local else "copy"
    args = ["rclone", verb, str(src), dst, "--min-age", "2m", "--transfers", "4",
            "--b2-chunk-size", "100M", "--exclude", ".cache/**", "--exclude", "*.part",
            "--exclude", "*.gitkeep", "-v", "--stats", "20s", "--stats-one-line"]
    print(f"[cutscenes] {verb} {src} -> {dst}", flush=True)
    rc = subprocess.run(args, env=_b2_env(remote)).returncode
    print(f"[cutscenes] rclone {verb} rc={rc}"
          + ("  (verified + local freed)" if delete_local and rc == 0 else ""), flush=True)


def used_log(only_game: str | None = None) -> None:
    """WHICH SCENES ARE SPENT. Every lore short records '<game>-cutscene__<file>@<start>'
    in the per-platform used-clip ledger, so the same MOMENT is never posted twice on a
    platform even though the file is reused for other moments (per user 2026-10-07)."""
    from core import gh_release
    led = gh_release.read_ledger()
    if led is None:
        sys.exit("[cutscenes] used-clip ledger unreadable (transient GitHub error) — try again")
    rows: dict[str, dict[float, list[str]]] = {}
    for plat, ids in (led or {}).items():
        for cid in ids:
            if "-cutscene__" not in str(cid):
                continue
            head, _, start = str(cid).partition("@")
            game = head.split("-cutscene__")[0]
            if only_game and game != only_game:
                continue
            try:
                t = float(start)
            except ValueError:
                t = -1.0
            rows.setdefault(head, {}).setdefault(t, []).append(plat)
    if not rows:
        print("[cutscenes] no lore windows posted yet"
              + (f" for {only_game}" if only_game else ""))
        return
    for head in sorted(rows):
        file = head.split("-cutscene__", 1)[-1]
        print(f"\n  {file}")
        for t in sorted(rows[head]):
            mm, ss = divmod(int(t), 60)
            where = ", ".join(sorted(set(rows[head][t])))
            print(f"    used @ {mm}:{ss:02d}  ->  {where}")


def listing() -> None:
    games = sorted({p.name for p in SRC.iterdir() if p.is_dir()} if SRC.exists() else set())
    for g in games:
        n = len(b2_store.list_cutscenes(g))
        local = len([p for p in (SRC / g).iterdir()
                     if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".mkv")])
        print(f"  {g:28} B2: {n:3}   local (not yet synced): {local}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "sync":
        rest = argv[1:]
        keep = "--keep-local" in rest
        game = next((a for a in rest if not a.startswith("-")), None)
        sync(delete_local=not keep, only_game=game)
    elif argv and argv[0] == "list":
        listing()
    elif argv and argv[0] in ("log", "used"):
        used_log(next((a for a in argv[1:] if not a.startswith("-")), None))
    else:
        print(__doc__)
