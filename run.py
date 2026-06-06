"""CLI entrypoint for the KiwinoyGamer social posting team.

Image posts:
  python run.py --slot 1            # run image slot 1, publish now
  python run.py --slot 2 --dry-run  # research+write+image, do NOT publish
  python run.py --auto              # pick the image slot closest to now
  python run.py --all --dry-run     # run all image slots without publishing

Reels (add --reel to use the reels schedule + reel pipeline):
  python run.py --reel --slot 1            # render + publish reel slot 1
  python run.py --reel --slot 1 --dry-run  # render reel, do NOT publish
  python run.py --reel --all --dry-run     # render all reels without publishing

In GitHub Actions the cron passes --slot N (post.yml) or --reel --slot N
(reels.yml).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from core.config import CONFIG
from orchestrator import run_reel_slot, run_slot


def _slots_for(reel: bool) -> list[dict]:
    if reel:
        return CONFIG.reels.get("schedule", {}).get("slots", [])
    return CONFIG.schedule["slots"]


def _closest_slot_now(reel: bool) -> int:
    """Return the slot id whose HH:MM is nearest to the current UTC time."""
    now = datetime.now(timezone.utc)
    now_min = now.hour * 60 + now.minute
    best_id, best_d = None, 10**9
    for s in _slots_for(reel):
        hh, mm = (int(x) for x in str(s["time"]).split(":"))
        smin = hh * 60 + mm
        d = min(abs(now_min - smin), 1440 - abs(now_min - smin))
        if d < best_d:
            best_id, best_d = int(s["id"]), d
    return best_id


def main() -> int:
    p = argparse.ArgumentParser(description="KiwinoyGamer social posting team")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--slot", type=int, help="schedule slot id (1-6)")
    g.add_argument("--auto", action="store_true", help="run the slot closest to now")
    g.add_argument("--all", action="store_true", help="run every slot (testing)")
    p.add_argument("--reel", action="store_true", help="use the reels track")
    p.add_argument("--dry-run", action="store_true", help="skip publishing")
    p.add_argument(
        "--schedule-at",
        default=None,
        help="ISO time to schedule the post (default: publish now)",
    )
    args = p.parse_args()

    if args.all:
        slot_ids = [int(s["id"]) for s in _slots_for(args.reel)]
    elif args.auto:
        slot_ids = [_closest_slot_now(args.reel)]
    else:
        slot_ids = [args.slot]

    runner = run_reel_slot if args.reel else run_slot
    label = "reel" if args.reel else "slot"

    failures = 0
    for sid in slot_ids:
        try:
            runner(sid, dry_run=args.dry_run, scheduled_at=args.schedule_at)
        except Exception as e:  # keep going on the other slots
            failures += 1
            print(f"[{label} {sid}] ERROR: {e}", file=sys.stderr, flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
