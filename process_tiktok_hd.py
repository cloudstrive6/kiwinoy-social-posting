"""Post N 4K/60 HDR TikTok DRAFTS for a game via Post for Me (preserves 60fps HDR).
REUSE-FIRST: cross-post the HD short renders we ALREADY made for YouTube; if there aren't
enough for the game, FALL BACK to rendering fresh 4K HDR reels from the 4K pool. Each lands
as a TikTok DRAFT — publish manually in-app + paste the caption (PfM stores it; TikTok's
draft API ignores captions). LOCAL only (nvenc + multi-GB HDR) — run on your machine.

  python process_tiktok_hd.py [game] [count]      # default: spider-man2 6
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, ".")
from orchestrator import run_youtube_short, ROOT   # noqa: E402
from agents import publisher                        # noqa: E402
from core.config import CONFIG                       # noqa: E402

GAME = sys.argv[1] if len(sys.argv) > 1 else "spider-man2"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 6

LEDGER = ROOT / "reels/assets/.tiktok_ledgers" / f"{GAME}.json"
LEDGER.parent.mkdir(parents=True, exist_ok=True)
posted = set(json.loads(LEDGER.read_text()).get("posted", [])) if LEDGER.exists() else set()


def save_ledger():
    LEDGER.write_text(json.dumps({"posted": sorted(posted)}, indent=2), encoding="utf-8")


def tt_caption(cap: str) -> str:
    extra = [str(h).strip() for h in (CONFIG.reels.get("tiktok", {}) or {}).get("extra_hashtags", []) or []]
    add = [(h if h.startswith("#") else "#" + h) for h in extra
           if h and h.lower().lstrip("#") not in cap.lower()]
    return f"{cap.rstrip()} {' '.join(add)}".strip() if add else cap


# 1) REUSE: existing local short renders for this game, not yet sent to TikTok.
existing = []
for d in sorted((ROOT / "output").glob("*_youtube_short")):
    rj, mp4 = d / "result.json", d / "short.mp4"
    if not (rj.exists() and mp4.exists()) or str(mp4) in posted:
        continue
    try:
        if json.loads(rj.read_text()).get("game") == GAME:
            existing.append((mp4, d / "caption.txt"))
    except Exception:
        pass

count = 0
print(f"=== TikTok HD drafts for {GAME}: target {N}, {len(existing)} reusable renders ===", flush=True)
for mp4, capf in existing:
    if count >= N:
        break
    cap = capf.read_text(encoding="utf-8").strip() if capf.exists() else GAME
    print(f"--- REUSE {mp4.parent.name} ({round(mp4.stat().st_size/1048576,1)} MB) ---", flush=True)
    try:
        res = publisher.run_tiktok_draft(tt_caption(cap), mp4.read_bytes())
        if res:
            posted.add(str(mp4)); save_ledger(); count += 1
            print(f"    TikTok draft: {res.get('id')}", flush=True)
        else:
            print("    no result (TikTok not connected?) — stopping.", flush=True); break
    except Exception as e:
        print(f"    FAILED: {e!r}", flush=True)

# 2) FALLBACK: render fresh 4K HDR from the 4K pool for the remainder.
while count < N:
    print(f"--- RENDER fresh from 4K pool ({count + 1}/{N}) ---", flush=True)
    try:
        r = run_youtube_short(game=GAME, youtube=False, tiktok=True)
        if r.get("tiktok_result"):
            count += 1
            print(f"    {r.get('layout')} | clip={r.get('clip_id')} | "
                  f"{r.get('tiktok_result', {}).get('id')}", flush=True)
        else:
            print(f"    no tiktok result ({r.get('skipped') or 'unknown'}) — stopping.", flush=True); break
    except Exception as e:
        print(f"    FAILED: {e!r}", flush=True); break

print(f"=== done: {count} TikTok drafts ({GAME}) ===", flush=True)
