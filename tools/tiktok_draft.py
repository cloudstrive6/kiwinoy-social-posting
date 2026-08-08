"""Render a gameplay reel and push it straight to TikTok's IN-APP DRAFTS.

Triggered by the Telegram "tiktok draft [format] [game] [Ns]" command (or run
directly). Reuses run_gameplay_reel(tiktok_only=True), which: picks a FRESH clip
unused on TikTok (per-platform ledger), renders the format, and posts it via
Post-for-Me's TikTok INBOX/DRAFT flow — so the video lands in your TikTok app's
Drafts to finish + publish. TikTok's draft API ignores the caption, so the caption
is also sent to Telegram to paste in-app. The clip is marked used on TikTok.

Usage:
  python tools/tiktok_draft.py --format classic --game spider-man2
  python tools/tiktok_draft.py --format triptych --game halo
  formats: classic | triptych | fill   (landscape/other -> classic)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import CONFIG            # noqa: E402
from orchestrator import run_gameplay_reel  # noqa: E402

_VALID = {"classic", "triptych", "fill"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a reel to TikTok in-app drafts.")
    ap.add_argument("--format", default="classic", help="classic | triptych | fill")
    ap.add_argument("--game", default=None, help="game key (default: config tiktok.game)")
    ap.add_argument("--clip", default=None, help="force a specific clip filename")
    a = ap.parse_args()

    game = a.game or str((CONFIG.reels.get("tiktok", {}) or {}).get("game", "spider-man2"))
    fmt = (a.format or "classic").strip().lower()
    if fmt not in _VALID:                 # landscape/unknown -> the canonical branded reel
        fmt = "classic"
    print(f"[tiktok-draft] rendering {fmt} · {game} -> TikTok in-app drafts…", flush=True)

    r = run_gameplay_reel(1, dry_run=False, game=game, tiktok_only=True,
                          layout_override=fmt, clip_override=a.clip)
    ok = bool(r.get("published"))
    print(f"[tiktok-draft] published={ok} clip={r.get('clip_id')} skip={r.get('skipped')}",
          flush=True)
    if not ok:
        # e.g. ledger unreadable (fail-closed) or no fresh clip — tell the user so a
        # silent no-op doesn't look like success.
        try:
            from core import notify
            notify.telegram("⚠️ TikTok draft couldn't render (no fresh clip or a transient "
                            "read error). Text the command again to retry.")
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
