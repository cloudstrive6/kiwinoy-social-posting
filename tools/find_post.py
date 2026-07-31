"""Look up past posts in the durable post log by caption / hook / clip-id / platform.

The auto-poster records every published reel (timestamp, platforms, clip_id, layout, hook,
caption, PfM result id) to a tiny GitHub-release asset, so any reel can be traced back to
its EXACT source clip forever — no 14-day CI-artifact race.

Usage:
  python tools/find_post.py "rooftop stakeout"     # search captions/hooks/clip-ids/platforms
  python tools/find_post.py --limit 5 "spider"
  python tools/find_post.py                          # newest 20 posts
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:                                   # captions have emojis; don't crash on a cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import gh_release  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Search the durable post log.")
    ap.add_argument("query", nargs="?", default="", help="text to match (caption/hook/clip-id/platform)")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    hits = gh_release.find_posts(args.query, limit=args.limit)
    if not hits:
        print(f"No posts match {args.query!r}." if args.query else "Post log is empty.")
        return 0
    print(f"{len(hits)} match(es){' for ' + repr(args.query) if args.query else ''} (newest first):\n")
    for p in hits:
        ts = p.get("ts")
        when = ""
        if ts:
            try:
                when = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                when = str(ts)
        print(f"• {when} | {'+'.join(p.get('platforms', []))} | {p.get('layout', '?')}")
        print(f"    clip_id : {p.get('clip_id', '')}")
        if p.get("hook"):
            print(f"    hook    : {p.get('hook')}")
        cap = (p.get("caption", "") or "").replace("\n", " ")
        print(f"    caption : {cap[:160]}")
        if p.get("result_id"):
            print(f"    result  : {p.get('result_id')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
