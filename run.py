"""CLI entrypoint for the KiwinoyGamer social posting team.

Examples:
  python run.py --slot 1            # run slot 1 (gacha), publish now
  python run.py --slot 2 --dry-run  # research+write+image, do NOT publish
  python run.py --auto              # pick the slot whose time is closest now
  python run.py --all --dry-run     # run all 4 slots without publishing (test)

In GitHub Actions, the cron passes --slot N (see .github/workflows/post.yml).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from core.config import CONFIG
from orchestrator import run_slot


def _closest_slot_now() -> int:
    """Return the slot id whose HH:MM is nearest to the current UTC time."""
    now = datetime.now(timezone.utc)
    now_min = now.hour * 60 + now.minute
    best_id, best_d = None, 10**9
    for s in CONFIG.schedule["slots"]:
        hh, mm = (int(x) for x in s["time"].split(":"))
        smin = hh * 60 + mm
        d = min(abs(now_min - smin), 1440 - abs(now_min - smin))
        if d < best_d:
            best_id, best_d = int(s["id"]), d
    return best_id


def main() -> int:
    p = argparse.ArgumentParser(description="KiwinoyGamer social posting team")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--slot", type=int, help="schedule slot id (1-4)")
    g.add_argument("--auto", action="store_true", help="run the slot closest to now")
    g.add_argument("--all", action="store_true", help="run every slot (testing)")
    p.add_argument("--dry-run", action="store_true", help="skip publishing")
    p.add_argument(
        "--schedule-at",
        default=None,
        help="ISO time to schedule the post (default: publish now)",
    )
    args = p.parse_args()

    if args.all:
        slot_ids = [int(s["id"]) for s in CONFIG.schedule["slots"]]
    elif args.auto:
        slot_ids = [_closest_slot_now()]
    else:
        slot_ids = [args.slot]

    failures = 0
    for sid in slot_ids:
        try:
            run_slot(sid, dry_run=args.dry_run, scheduled_at=args.schedule_at)
        except Exception as e:  # keep going on the other slots
            failures += 1
            print(f"[slot {sid}] ERROR: {e}", file=sys.stderr, flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
