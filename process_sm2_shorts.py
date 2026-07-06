"""Spider-Man 2 YouTube gameplay SHORTS: render + SCHEDULE 12 shorts, 2/day starting
today (private + publishAt). Uses the existing 4K HDR pools (no extraction needed):
  classic/triptych <- reels/assets/4k-hdr-long-clips/spider-man2 (8 clips)
  fill (full vertical bleed) <- reels/assets/footage-4k/spider-man2-vertical (16 clips)
Layout rotation [classic, triptych, fill] over 12 posts = 4 each -> exactly the 8 long
clips (classic+triptych) + 4 of 16 vertical, all UNIQUE (no duplicate scenes). The
spider-man2 shorts ledger drives freshness + resume. Run DETACHED via run_sm2_shorts.bat."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, ".")
from orchestrator import run_youtube_short, _short_post_count  # noqa: E402

ROOT = Path(__file__).resolve().parent
GAME = "spider-man2"
N = 12                              # duplicate-free max (see module docstring)
TIMES = [(10, 0), (13, 30)]        # 2/day, UTC (PH evening)


def slots(n):
    """n future slots, 2/day at TIMES, starting today; skip any already past."""
    now = datetime.now(timezone.utc)
    out, day = [], 0
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while len(out) < n:
        for h, m in TIMES:
            t = base.replace(hour=h, minute=m) + timedelta(days=day)
            if t > now + timedelta(minutes=5):
                out.append(t)
                if len(out) >= n:
                    break
        day += 1
    return out


done = _short_post_count(GAME)
SLOTS = slots(N)
print(f"=== SM2 Shorts: {N} target, {done} already done (resume), {len(SLOTS)} slots ===", flush=True)
for i, when in enumerate(SLOTS, 1):
    if i <= done:
        print(f"--- Short {i}/{N} already scheduled — skip ---", flush=True)
        continue
    iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"--- Short {i}/{N} -> publish {iso} ---", flush=True)
    try:
        r = run_youtube_short(game=GAME, privacy="private", publish_at=iso)
        print(f"    {r.get('layout')} | clip={r.get('clip_id')} | {r.get('url') or r.get('skipped')}", flush=True)
    except Exception as e:
        print(f"    FAILED: {e!r}", flush=True)
print("=== SM2 Shorts scheduling done ===", flush=True)
