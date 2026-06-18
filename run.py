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

Carousels (add --carousel for the 3-5 image multi-photo track):
  python run.py --carousel --slot 1            # build + publish carousel slot 1
  python run.py --carousel --slot 1 --dry-run  # build slides, do NOT publish

In GitHub Actions the cron passes --slot N (post.yml) or --reel --slot N
(reels.yml).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from core.config import CONFIG
from orchestrator import (
    run_commentary_reel,
    run_quote_card,
    run_ready_reel,
    run_carousel_slot,
    run_reel_slot,
    run_slot,
    run_threads,
    run_threads_image,
)


def _slots_for(track: str) -> list[dict]:
    if track == "reel":
        return CONFIG.reels.get("schedule", {}).get("slots", [])
    if track == "carousel":
        return CONFIG.carousels.get("schedule", {}).get("slots", [])
    return CONFIG.schedule["slots"]


def _closest_slot_now(track: str) -> int:
    """Return the slot id whose HH:MM is nearest to the current UTC time."""
    now = datetime.now(timezone.utc)
    now_min = now.hour * 60 + now.minute
    best_id, best_d = None, 10**9
    for s in _slots_for(track):
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
    g.add_argument(
        "--threads",
        action="store_true",
        help="run the dedicated Threads sports track (no slot needed)",
    )
    g.add_argument(
        "--threads-image",
        dest="threads_image",
        action="store_true",
        help="run a Threads IMAGE post (designed photo + headline)",
    )
    g.add_argument(
        "--photopost",
        metavar="BUCKET",
        help="run an image-set post for a bucket (e.g. ff7)",
    )
    g.add_argument(
        "--ready-reel",
        dest="ready_reel",
        action="store_true",
        help="post the next of YOUR queued finished reels (ready-reels Release)",
    )
    g.add_argument(
        "--commentary",
        action="store_true",
        help="render + publish a game commentary reel (Taglish VO over b-roll, FB only)",
    )
    g.add_argument(
        "--quote",
        action="store_true",
        help="render + publish a motivational gaming quote CARD (FB only)",
    )
    p.add_argument("--reel", action="store_true", help="use the reels track")
    p.add_argument(
        "--carousel", action="store_true",
        help="use the carousel track (3-5 image multi-photo post)",
    )
    p.add_argument(
        "--type",
        choices=["update", "prediction", "poll"],
        help="Threads post type (with --threads); default = auto by UTC hour",
    )
    p.add_argument("--dry-run", action="store_true", help="skip publishing")
    p.add_argument(
        "--schedule-at",
        default=None,
        help="ISO time to schedule the post (default: publish now)",
    )
    args = p.parse_args()

    # Threads track has no slots — one independent run per invocation.
    if args.threads:
        try:
            run_threads(dry_run=args.dry_run, scheduled_at=args.schedule_at,
                        post_type=args.type)
            return 0
        except Exception as e:
            print(f"[threads] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    if args.threads_image:
        try:
            run_threads_image(dry_run=args.dry_run, scheduled_at=args.schedule_at)
            return 0
        except Exception as e:
            print(f"[threads-image] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    if args.ready_reel:
        try:
            run_ready_reel(dry_run=args.dry_run, scheduled_at=args.schedule_at)
            return 0
        except Exception as e:
            print(f"[ready-reel] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    # Commentary track: no slot — one run, length auto-varied per config.
    if args.commentary:
        try:
            run_commentary_reel(dry_run=args.dry_run, scheduled_at=args.schedule_at)
            return 0
        except Exception as e:
            print(f"[commentary] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    # Motivational quote card -> Facebook.
    if args.quote:
        try:
            run_quote_card(dry_run=args.dry_run, scheduled_at=args.schedule_at)
            return 0
        except Exception as e:
            print(f"[quote] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    if args.photopost:
        from agents import photopost
        try:
            photopost.run(bucket=args.photopost, dry_run=args.dry_run,
                          scheduled_at=args.schedule_at)
            return 0
        except Exception as e:
            print(f"[photopost] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    track = "reel" if args.reel else ("carousel" if args.carousel else "post")
    if args.all:
        slot_ids = [int(s["id"]) for s in _slots_for(track)]
    elif args.auto:
        slot_ids = [_closest_slot_now(track)]
    else:
        slot_ids = [args.slot]

    runner = {"reel": run_reel_slot, "carousel": run_carousel_slot}.get(track, run_slot)
    label = track if track != "post" else "slot"

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
