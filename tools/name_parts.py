"""Number raw long-form recordings in a game folder as '<Game> - Part N' by capture time.

Point Elgato (4K Capture Utility) at reels/assets/longform-fullgame/<game>/ so recordings land
there, then run this. It sorts the video files by CREATION time (earliest = Part 1 — on
Windows os.stat().st_ctime IS the true file birth time), strips any timestamp/old part
suffix, and renames them '<Game> - Part N' so build_longform_hdr concats them in play
order (its part parser reads the number after 'Part').

The game name is taken from each filename (Elgato prepends the app name), so
'Halo Infinite 2026-07-23 20-15-01.mp4' -> 'Halo Infinite - Part 1.mp4'. Override with
--name if the auto name is wrong. Idempotent: re-running renumbers cleanly.

Usage:
  python tools/name_parts.py <folder>                       # PREVIEW the plan (no changes)
  python tools/name_parts.py <folder> --apply               # do the renames
  python tools/name_parts.py <folder> --apply --name "Halo Infinite"
  python tools/name_parts.py <folder> --apply --by mtime    # order by modified time instead

<folder> = a path, or a folder key under reels/assets/longform-fullgame/ (e.g. tlou-part2).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ROOT  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".ts"}

# A trailing capture timestamp Elgato/OBS append, e.g. "2026-07-23 20-15-01",
# "2026-07-23_20-15", or "(2026-06-15 17-46-07)". Roman/sequel numbers ("Part II",
# "Spider-Man 2") are left alone — the date pattern needs \d{4}-\d\d-\d\d.
_TS = re.compile(
    r"[\s_\-]*[\(\[]?\s*\d{4}[-_.]\d{1,2}[-_.]\d{1,2}"
    r"(?:[\s_T\-]*\d{1,2}[-_.:]\d{2}(?:[-_.:]\d{2})?)?\s*[\)\]]?\s*$")
# An existing " - Part 3" / "Part_3" / "part 5.1" suffix (so re-running is idempotent).
_PART = re.compile(r"\s*[-_]?\s*part[\s_\-]*\d+(?:\.\d+)?\s*$", re.IGNORECASE)


def _clean(stem: str) -> str:
    prev = None
    while prev != stem:            # peel a part suffix then a timestamp, repeatedly
        prev = stem
        stem = _PART.sub("", stem)
        stem = _TS.sub("", stem)
    return stem.strip(" _-")


def _resolve(folder: str) -> Path:
    p = Path(folder)
    if p.is_dir():
        return p
    cand = ROOT / "reels/assets/longform" / folder
    if cand.is_dir():
        return cand
    sys.exit(f"folder not found: {folder} (nor {cand})")


def plan(folder: Path, name: str | None, by: str) -> list[tuple[Path, Path]]:
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not files:
        sys.exit(f"no video files in {folder}")
    key = (lambda p: (p.stat().st_mtime, p.name.lower())) if by == "mtime" \
        else (lambda p: (p.stat().st_ctime, p.name.lower()))
    files.sort(key=key)
    moves: list[tuple[Path, Path]] = []
    for i, p in enumerate(files, 1):
        base = name or _clean(p.stem) or "Clip"
        moves.append((p, p.with_name(f"{base} - Part {i}{p.suffix.lower()}")))
    return moves


def apply(moves: list[tuple[Path, Path]]) -> None:
    # Two-phase (via temp names) so a target that equals another file's current name
    # can't clobber it.
    finals = {dst.name for _, dst in moves}
    for src, dst in moves:
        if dst.exists() and dst.name != src.name and dst.name not in finals:
            sys.exit(f"target already exists (not ours): {dst.name}")
    tmp = []
    for i, (src, dst) in enumerate(moves):
        if src.name == dst.name:
            tmp.append((src, dst))
            continue
        t = src.with_name(f".__rename_{i}{src.suffix.lower()}")
        src.rename(t)
        tmp.append((t, dst))
    for t, dst in tmp:
        if t.name != dst.name:
            t.rename(dst)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    folder = _resolve(argv[0])
    name = argv[argv.index("--name") + 1] if "--name" in argv and \
        argv.index("--name") + 1 < len(argv) else None
    by = "mtime" if "--by" in argv and argv[argv.index("--by") + 1:] and \
        argv[argv.index("--by") + 1] == "mtime" else "ctime"
    moves = plan(folder, name, by)

    print(f"{folder}  ({'modified' if by == 'mtime' else 'created'}-time order):\n")
    changed = 0
    for src, dst in moves:
        mark = "  (unchanged)" if src.name == dst.name else ""
        if not mark:
            changed += 1
        print(f"  {src.name}\n    -> {dst.name}{mark}")
    if "--apply" in argv:
        if changed:
            apply(moves)
            print(f"\nRenamed {changed} file(s).")
        else:
            print("\nNothing to rename — already numbered.")
        print("\nNext: upload the long-form with"
              f"\n  python run.py --youtube --parts \"{folder}\" --game <key>")
    else:
        print(f"\nPREVIEW only ({changed} would change). Add --apply to rename.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
