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
    run_gameplay_reel,
    run_quote_card,
    run_ready_reel,
    run_carousel_slot,
    run_reel_slot,
    run_slot,
    run_threads,
    run_threads_footage,
    run_threads_image,
    run_youtube_longform,
    run_youtube_short,
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
        "--threads-footage",
        dest="threads_footage",
        action="store_true",
        help="run a Threads FOOTAGE post (landscape graded gameplay + hook caption)",
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
    g.add_argument(
        "--youtube",
        action="store_true",
        help="LOCAL: concat the --parts 4K/60 HDR files into a full-game video + upload to YouTube",
    )
    g.add_argument(
        "--youtube-short",
        dest="youtube_short",
        action="store_true",
        help="LOCAL: render one 4K/60 HDR Short (classic<->triptych alternating) from the pool + upload via the Data API",
    )
    g.add_argument(
        "--tiktok",
        action="store_true",
        help="dedicated TikTok reel: one TLOU2 gameplay clip (classic<->triptych), posts ONLY to TikTok via Zernio",
    )
    p.add_argument("--reel", action="store_true", help="use the reels track")
    p.add_argument("--backup", action="store_true",
                   help="backup trigger: only post if the primary missed this slot "
                        "(self-heals a dropped cron->GitHub trigger; Telegrams if it covers a miss)")
    p.add_argument(
        "--carousel", action="store_true",
        help="use the carousel track (3-5 image multi-photo post)",
    )
    p.add_argument(
        "--type",
        choices=["update", "prediction", "poll"],
        help="Threads post type (with --threads); default = auto by UTC hour",
    )
    p.add_argument(
        "--quote-theme",
        choices=["auto", "story", "life", "gameplay"],
        default="auto",
        help="quote theme (with --quote): story=real attributed game quote, life=original; "
             "'auto' lets the daily ledger balance the mix",
    )
    p.add_argument("--dry-run", action="store_true", help="skip publishing")
    p.add_argument(
        "--schedule-at",
        default=None,
        help="ISO time to schedule the post (default: publish now)",
    )
    p.add_argument(
        "--parts",
        help="(with --youtube) folder of, or path to, the labelled 4K/60 HDR PART files",
    )
    p.add_argument("--game", help="(with --youtube/--youtube-short) game key")
    p.add_argument("--layout", default=None,
                   help="(with --youtube-short) force 'classic' or 'triptych' (else alternates)")
    p.add_argument("--clip", default=None,
                   help="(with --youtube-short) explicit 4K HDR clip file (else fresh-first from the pool)")
    p.add_argument("--title", help="(with --youtube) explicit video title (overrides the auto title)")
    p.add_argument("--description", help="(with --youtube) explicit description (overrides the auto one)")
    p.add_argument("--thumb-text", help="(with --youtube) thumbnail overlay words, e.g. 'SEPHIROTH BOSS' (default FULL GAME)")
    p.add_argument("--tags", help="(with --youtube) comma-separated tags")
    p.add_argument("--thumb-image", help="(with --youtube) explicit thumbnail base image (overrides the game pool)")
    p.add_argument(
        "--publish-at", default=None,
        help="(with --youtube) RFC3339 UTC time to schedule the video, e.g. 2026-07-01T12:00:00Z",
    )
    p.add_argument(
        "--public", action="store_true",
        help="(with --youtube) publish PUBLIC immediately (overrides the private default)",
    )
    p.add_argument(
        "--privacy", default=None,
        help="(with --youtube) explicit privacy: public | unlisted | private",
    )
    args = p.parse_args()

    # Auto-prune stale video renders from output/ so local scratch never balloons
    # (it once hit 184 GB). Fail-open + quiet — cleanup must never block a run.
    try:
        from tools.prune_output import prune as _prune_output
        _prune_output(quiet=False)
    except Exception:
        pass

    # Threads track has no slots — one independent run per invocation.
    if args.threads:
        try:
            # One Threads cron fires 8x/day; route by UTC hour -> footage on the
            # footage hours (default 3/9/15/21), caption otherwise (1/7/13/19).
            import datetime as _dt
            tf = CONFIG.raw().get("threads_footage", {}) or {}
            foot_hours = {int(h) for h in (tf.get("hours") or [3, 9, 15, 21])}
            if tf.get("enabled", True) and _dt.datetime.now(_dt.timezone.utc).hour in foot_hours:
                run_threads_footage(dry_run=args.dry_run, scheduled_at=args.schedule_at)
            else:
                run_threads(dry_run=args.dry_run, scheduled_at=args.schedule_at,
                            post_type=args.type)
            return 0
        except Exception as e:
            print(f"[threads] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    if args.threads_footage:
        try:
            run_threads_footage(dry_run=args.dry_run, scheduled_at=args.schedule_at)
            return 0
        except Exception as e:
            print(f"[threads-footage] ERROR: {e}", file=sys.stderr, flush=True)
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

    # Dedicated TikTok track: TLOU2-only gameplay reel, posts ONLY to TikTok (Zernio).
    if args.tiktok:
        try:
            from core.config import CONFIG as _C
            tk = (_C.reels.get("tiktok", {}) or {})
            run_gameplay_reel(args.slot or 1, dry_run=args.dry_run,
                              scheduled_at=args.schedule_at,
                              game=str(tk.get("game", "thelastofus2")), tiktok_only=True)
            return 0
        except Exception as e:
            print(f"[tiktok] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    # LOCAL long-form YouTube: --parts <folder/file> [--game <key>] [--publish-at <iso>]
    if args.youtube:
        if not args.parts:
            print("[youtube] --parts is required (folder of, or path to, the 4K HDR part files)",
                  file=sys.stderr)
            return 2
        try:
            tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None
            privacy = args.privacy or ("public" if args.public else None)
            run_youtube_longform(args.parts, game=args.game, title=args.title,
                                 description=args.description, thumb_text=args.thumb_text,
                                 tags=tags, thumb_image=args.thumb_image,
                                 publish_at=args.publish_at, privacy=privacy,
                                 dry_run=args.dry_run)
            return 0
        except Exception as e:
            print(f"[youtube] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    # LOCAL 4K/60 HDR YouTube Short (classic<->triptych alternating) via the Data API.
    if args.youtube_short:
        try:
            privacy = args.privacy or ("public" if args.public else None)
            run_youtube_short(game=args.game, clip=args.clip, layout=args.layout,
                              privacy=privacy, publish_at=args.publish_at,
                              dry_run=args.dry_run)
            return 0
        except Exception as e:
            print(f"[yt-short] ERROR: {e}", file=sys.stderr, flush=True)
            return 1

    # Motivational quote card -> Facebook.
    if args.quote:
        try:
            run_quote_card(dry_run=args.dry_run, scheduled_at=args.schedule_at,
                           theme=args.quote_theme)
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

    # Backup-trigger self-heal (reels only): a 2nd cron fires ~15 min after each slot
    # with --backup. If a reel already posted recently the primary trigger worked, so
    # skip; otherwise the primary was dropped (cron->GitHub 503) — post the make-up and
    # Telegram that a miss was covered. The marker is written on EVERY successful reel
    # post (below), so the guard always has fresh data.
    backup = bool(getattr(args, "backup", False)) and track == "reel" and not args.dry_run
    if backup:
        from core.config import CONFIG as _C
        from core import gh_release as _ghr
        window = int((_C.reels.get("backup", {}) or {}).get("window_minutes", 120))
        mins = _ghr.minutes_since_post("reels_feed")
        if mins is not None and mins < window:
            print(f"[backup] a reel already posted {mins:.0f} min ago (< {window}m) — "
                  f"primary trigger worked, backup skipping.", flush=True)
            return 0
        print(f"[backup] no recent reel post (last: "
              f"{'never' if mins is None else f'{mins:.0f}m ago'}) — posting the make-up.",
              flush=True)

    failures = 0
    posted_any = False
    for sid in slot_ids:
        try:
            res = runner(sid, dry_run=args.dry_run, scheduled_at=args.schedule_at)
            if isinstance(res, dict) and res.get("published"):
                posted_any = True
        except Exception as e:  # keep going on the other slots
            failures += 1
            print(f"[{label} {sid}] ERROR: {e}", file=sys.stderr, flush=True)

    # Stamp the reel-post marker (feeds the backup guard) + notify on a backup catch.
    if track == "reel" and posted_any and not args.dry_run:
        try:
            from core import gh_release as _ghr, notify as _notify
            _ghr.mark_posted("reels_feed")
            if backup:
                _notify.telegram(
                    "⚠️→✅ Backup trigger: the scheduled gameplay reel was "
                    "MISSED by the primary (a cron→GitHub hiccup). I've posted the make-up "
                    "reel just now — no post was lost, you're covered.")
        except Exception as _e:
            print(f"[backup] marker/notify step failed: {_e!r}", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
