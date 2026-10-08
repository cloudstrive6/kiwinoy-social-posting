"""AUDIT THE LORE BIBLES — every game must carry MOTIVE depth, not just who-is-who.

A bible that only identifies characters lets a card be written that quotes the subtitles
correctly and still inverts the story: "Norman just agreed to let his son die" shipped on a
live Short, when Norman's whole arc is refusing to let Harry go (user, 2026-10-09). The
critics check a card's READING against these bibles, so a thin bible means no check at all.

Every bible must have:
  - WHAT EACH ONE WANTS   : what the main characters want and do, in their own arc
  - BACKWARDS READINGS    : the specific inversions to reject for this game

    python tools/lore_audit.py            # table of every game
    python tools/lore_audit.py --strict   # exit 1 if any game is thin (for CI)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import lore  # noqa: E402

REQUIRED = (("WHAT EACH ONE WANTS", "motives"), ("BACKWARDS READINGS", "inversions"))
MIN_CHARS = 1500


def audit() -> list[tuple[str, int, list[str]]]:
    rows = []
    for game in sorted(lore.GAME_LORE):
        bible = lore.lore_for(game) or ""
        missing = [label for marker, label in REQUIRED if marker not in bible.upper()]
        if len(bible) < MIN_CHARS:
            missing.append(f"short ({len(bible)} chars)")
        rows.append((game, len(bible), missing))
    return rows


def main() -> int:
    rows = audit()
    width = max(len(g) for g, _, _ in rows)
    thin = 0
    print(f"{'GAME':<{width}}  {'CHARS':>6}  STATUS")
    for game, size, missing in rows:
        if missing:
            thin += 1
            print(f"{game:<{width}}  {size:>6}  THIN - missing: {', '.join(missing)}")
        else:
            print(f"{game:<{width}}  {size:>6}  ok")
    print(f"\n{len(rows) - thin}/{len(rows)} bibles carry motive depth.")
    if thin:
        print("\nAdd a 'WHAT EACH ONE WANTS' block (what each character wants and does) and a\n"
              "'BACKWARDS READINGS TO REJECT' list to each THIN game before it joins the\n"
              "rotation - the hook and card critics check a reading against these.")
    return 1 if (thin and "--strict" in sys.argv) else 0


if __name__ == "__main__":
    raise SystemExit(main())
