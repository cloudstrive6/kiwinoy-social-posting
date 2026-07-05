"""FF7R YouTube gameplay SHORTS: auto-extract highlight clips from the full-game parts,
then render + SCHEDULE them 1-2/day (private + publishAt) across Jul 5-12. Auto-extract is
NOT hand-curated (user accepted this) — extraction points are varied to spread coverage.
Run DETACHED via run_ff7_shorts.bat so it survives the Claude session exiting."""
import sys
from pathlib import Path
sys.path.insert(0, ".")
from core import ffmpeg                       # noqa: E402
from orchestrator import run_youtube_short    # noqa: E402

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / "reels/assets/longform-fullgame/final-fantasy-7-remake"
POOL = ROOT / "reels/assets/4k-hdr-long-clips/ff7remake"
POOL.mkdir(parents=True, exist_ok=True)

# (part number, fraction-into-the-part) — 12 spread across the game (skip corrupt Part 13),
# varied % so we don't always land on the same beat.
EXTRACT = [(1, 0.35), (2, 0.55), (4, 0.45), (6, 0.60), (8, 0.40), (10, 0.55),
           (12, 0.35), (14, 0.65), (16, 0.50), (18, 0.40), (20, 0.60), (22, 0.45)]

# 12 publish slots, 1-2/day, Jul 5-12, ~PH afternoon/evening (UTC+8), evenly-ish varied.
SLOTS = ["2026-07-05T10:00:00Z", "2026-07-05T13:30:00Z", "2026-07-06T11:00:00Z",
         "2026-07-07T09:30:00Z", "2026-07-07T13:00:00Z", "2026-07-08T12:00:00Z",
         "2026-07-09T10:00:00Z", "2026-07-09T13:30:00Z", "2026-07-10T11:30:00Z",
         "2026-07-11T09:30:00Z", "2026-07-11T13:00:00Z", "2026-07-12T12:00:00Z"]


def extract():
    for n, pct in EXTRACT:
        out = POOL / f"ff7r-p{n:02d}.mp4"
        if out.exists():
            print(f"part {n}: already have {out.name}", flush=True)
            continue
        src = PARTS / f"Final Fantasy VII Remake - Part {n}.mp4"
        if not src.exists():
            print(f"part {n}: MISSING source", flush=True)
            continue
        ss = (ffmpeg.duration(src) or 1800) * pct
        rc, err = ffmpeg.run(["-ss", f"{ss:.1f}", "-i", str(src), "-t", "40", "-c", "copy",
                              "-movflags", "+faststart", str(out)], timeout=300)
        print(f"part {n}: {'OK' if rc == 0 else 'FAIL'} -> {out.name} (@{ss/60:.1f}min)", flush=True)


def _done_count():
    """How many Shorts already scheduled (ledger post counter) — so a restart RESUMES."""
    import json
    try:
        return int(json.loads((ROOT / "reels/assets/.shorts_ledgers/ff7remake.json")
                              .read_text(encoding="utf-8")).get("posts", 0))
    except Exception:
        return 0


print("=== extracting clips ===", flush=True)
extract()
done = _done_count()
print(f"=== scheduling Shorts (private + publishAt); {done} already done, resuming ===", flush=True)
for i, when in enumerate(SLOTS, 1):
    if i <= done:
        print(f"--- Short {i}/{len(SLOTS)} already scheduled — skip ---", flush=True)
        continue
    print(f"--- Short {i}/{len(SLOTS)} -> publish {when} ---", flush=True)
    try:
        r = run_youtube_short(game="ff7remake", privacy="private", publish_at=when)
        print(f"    {r.get('layout')} | clip={r.get('clip_id')} | {r.get('url') or r.get('skipped')}", flush=True)
    except Exception as e:
        print(f"    FAILED: {e!r}", flush=True)
print("=== FF7R Shorts scheduling done ===", flush=True)
