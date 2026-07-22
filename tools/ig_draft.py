"""On-demand IG DRAFT for full-bleed vertical gameplay reels.

The goal is to add a TRENDING INSTAGRAM SONG to a full-bleed gameplay reel. Instagram's
licensed music can ONLY be added inside the IG app (there is no API for it), so this tool
does NOT post anything. It renders ONE full-bleed vertical reel (FULL game audio), uploads
it to B2 under drafts/ig/, and Telegrams a download link + the caption. On the phone: tap
the link, save the video, open Instagram, add your trending song, and post.

FIRE ON DEMAND ONLY (per user 2026-07-21). This is completely separate from the auto-posting
pipeline — it changes NOTHING about how FB/IG feed reels post automatically.

Usage:
  python tools/ig_draft.py                 # default game, a fresh unused vertical clip
  python tools/ig_draft.py --game halo     # a specific game's vertical pool
  python tools/ig_draft.py --seconds 30    # cap the reel length
  python tools/ig_draft.py --keep-clip     # don't mark the clip used (allow the auto feed to reuse it)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import CONFIG                              # noqa: E402
from core import b2_store, ffmpeg, notify                  # noqa: E402
from agents import content, reel_composer, reel_ffmpeg     # noqa: E402
from tools.footage import _b2_env                          # noqa: E402


def _default_game() -> str:
    r = CONFIG.reels
    over = ((r.get("gameplay", {}) or {}).get("prefer_override", {}) or {}).get("games") or []
    if over:
        return str(over[0])
    return str((r.get("tiktok", {}) or {}).get("game", "spider-man2"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a full-bleed vertical gameplay reel and deliver it to Telegram "
                    "for a MANUAL Instagram post (add your own trending song in-app).")
    ap.add_argument("--game", default=None,
                    help="game key (default: the current prefer_override / tiktok game)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="cap the reel length in seconds (default: whole clip up to IG's 15-min max)")
    ap.add_argument("--keep-clip", action="store_true",
                    help="do NOT mark the clip used (default marks it so the auto feed won't reuse it)")
    args = ap.parse_args()

    game = args.game or _default_game()
    vkey = f"{game}-vertical"
    print(f"[ig-draft] game={game}  pool={vkey}", flush=True)

    # 1) pick a fresh, unused vertical clip (the picker retries on download hiccups)
    clip_path, clip_id = reel_composer.pick_unused_clip(vkey)
    if not clip_path:
        print(f"[ig-draft] No footage in '{vkey}'. Add vertical clips to "
              f"reels/assets/footage/{vkey}/ (then sync to B2) first.", flush=True)
        return 2
    print(f"[ig-draft] clip: {clip_id}", flush=True)

    # 2) render the full-bleed vertical reel — FULL game audio (same as the feed FILL)
    gcfg = CONFIG.reels.get("gameplay", {}) or {}
    vcfg = gcfg.get("vertical", {}) or {}
    fps = int(gcfg.get("fps", CONFIG.reels.get("fps", 60)))
    w, h = int(gcfg.get("width", 1080)), int(gcfg.get("height", 1920))
    dur = float(ffmpeg.duration(clip_path) or 0.0)
    cap = args.seconds or 900.0                                   # IG reels max = 15 min
    target = round(min(dur, cap), 1) if dur else cap
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "output" / f"igdraft_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    reel_path = out_dir / f"ig_{game}_{stamp}.mp4"
    print(f"[ig-draft] rendering full-bleed vertical ({int(target)}s, full game audio)...", flush=True)
    reel_ffmpeg.build_gameplay_fill(
        clip_path, reel_path, fps=fps, w=w, h=h, target_seconds=target,
        vol_db=float(vcfg.get("volume_db", 8.26)))
    size_mb = reel_path.stat().st_size / (1024 * 1024)
    print(f"[ig-draft] rendered {reel_path.name} ({size_mb:.0f} MB)", flush=True)

    # 3) relatable, clip-grounded caption (<=5 hashtags, brand-tagged)
    caption = content.relatable_fill_caption(clip_path, game)

    # 4) upload to B2 drafts/ig/ + presign a 7-day download link
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    bucket = b2_store._bucket()
    key = f"drafts/ig/{reel_path.name}"
    print(f"[ig-draft] uploading to B2 -> {key}", flush=True)
    rc = subprocess.run(["rclone", "copyto", str(reel_path), f"{remote}:{bucket}/{key}",
                         "--b2-chunk-size", "100M"], env=_b2_env(remote)).returncode
    link = b2_store.presigned_url(key) if rc == 0 else None

    # 5) deliver to Telegram (link + caption). Fail-soft to the local path.
    if link:
        msg = (f"\U0001F3AC IG DRAFT ready — {game}, {int(target)}s\n"
               "Open on your phone, save the video, then post to Instagram and add your "
               "trending song in-app.\n\n"
               f"⬇️ Download (valid 7 days):\n{link}\n\n"
               f"— caption (copy below) —\n{caption}")
        print("[ig-draft] Telegram:", "sent" if notify.telegram(msg) else
              "NOT sent (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)", flush=True)
    else:
        print(f"[ig-draft] B2 upload/presign failed (rc={rc}); file is local: {reel_path}", flush=True)
        notify.telegram(f"⚠️ IG draft rendered but the upload failed. File on the PC:\n"
                        f"{reel_path}\n\n— caption —\n{caption}")
        print("\n[ig-draft] CAPTION:\n" + caption, flush=True)
        return 1

    # 6) mark the clip used so the auto feed won't post the same one (unless --keep-clip)
    if not args.keep_clip:
        reel_composer.mark_clip_used(clip_id)
        print(f"[ig-draft] marked clip used (auto feed won't reuse it): {clip_id}", flush=True)

    print("\n[ig-draft] DONE.\nCAPTION:\n" + caption, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
