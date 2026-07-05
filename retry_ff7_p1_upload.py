"""Retry the FF7 Remake Full Game Part 1 upload REUSING the existing 213 GB concat
(output/20260702-052911_youtube_longform/fullgame.mp4) — the prior run built the
concat fine but the upload died on Avast Web Shield (now excepted). No re-encode:
reuse_concat skips build_longform_hdr; only the thumbnail + upload run. Public now.
Deletes the concat after a successful upload. Run DETACHED (survives session exit)
via run_ff7_p1_retry.bat.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from orchestrator import run_youtube_longform  # noqa: E402

D = ROOT / "reels/assets/longform-fullgame/final-fantasy-7-remake"
CONCAT = ROOT / "output/20260702-052911_youtube_longform/fullgame.mp4"
files = [str(D / f"Final Fantasy VII Remake - Part {n}.mp4") for n in range(1, 10)]

if not CONCAT.exists():
    print(f"MISSING concat: {CONCAT}", flush=True)
    sys.exit(1)

title = ("FINAL FANTASY VII REMAKE Full Game Walkthrough Part 1 "
         "[4K 60FPS HDR] No Commentary")
print(f"=== Full Game Part 1 RETRY (reuse {CONCAT.stat().st_size/1e9:.1f} GB concat) ===",
      flush=True)
res = run_youtube_longform(files, game="ff7remake", title=title, thumb_text="PART 1",
                           privacy="public", reuse_concat=str(CONCAT))
print(f"=== Part 1 DONE -> {res.get('url') or res} ===", flush=True)

if res.get("published") and CONCAT.exists():
    try:
        CONCAT.unlink()
        print(f"cleaned up local concat: {CONCAT}", flush=True)
    except Exception as e:
        print(f"cleanup failed ({e!r})", flush=True)
