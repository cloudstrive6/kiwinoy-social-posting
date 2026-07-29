"""On-demand FACEBOOK DRAFT for MANUAL FB posting — format-selectable.

Renders a gameplay reel in a chosen FORMAT, re-encodes it to FACEBOOK's Reels spec
(closed-GOP 60fps 15/20 — the same encode the auto FB feed uses so FB keeps 60fps
instead of downsampling to 30), uploads it to B2 drafts/fb/, and Telegrams a ping
(filename + size + caption) so the user posts it by hand on Facebook. This is separate
from the auto-posting pipeline and changes NOTHING about how the FB feed posts — it
NEVER posts anything itself. FIRE ON DEMAND ONLY.

Formats:
  classic    9:16 footage band + on-screen hook + logos (the canonical FB reel; DEFAULT)
  triptych   3-panel 9:16 (needs game art)
  fill       full-bleed 9:16 vertical (pure footage, scale-to-cover)
  landscape  16:9 'as-is' graded clip + KG corner logo (FB landscape video)

Usage:
  python tools/fb_draft.py [--format classic] [--game spider-man2] [--seconds N]
  python tools/fb_draft.py --format triptych --game halo
  python tools/fb_draft.py --format fill --keep-clip
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
import orchestrator as orch                                # noqa: E402

FORMATS = ("classic", "triptych", "fill", "landscape")


def _default_game() -> str:
    r = CONFIG.reels
    over = ((r.get("gameplay", {}) or {}).get("prefer_override", {}) or {}).get("games") or []
    if over:
        return str(over[0])
    return str((r.get("tiktok", {}) or {}).get("game", "spider-man2"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a gameplay reel in a chosen format, encode it to FB's Reels spec "
                    "(closed-GOP 60fps), and deliver it to Telegram for a MANUAL Facebook post.")
    ap.add_argument("--format", default="classic", choices=sorted(FORMATS),
                    help="render format (default: classic — the canonical branded FB reel)")
    ap.add_argument("--game", default=None, help="game key (default: current priority game)")
    ap.add_argument("--seconds", type=float, default=None,
                    help="cap length in seconds (default: the whole clip — FB has no duration cap)")
    ap.add_argument("--keep-clip", action="store_true",
                    help="do NOT mark the clip used (default marks it so the auto feed won't reuse it)")
    args = ap.parse_args()

    fmt = args.format
    game = args.game or _default_game()
    gcfg = CONFIG.reels.get("gameplay", {}) or {}
    vcfg = gcfg.get("vertical", {}) or {}
    fps = int(gcfg.get("fps", CONFIG.reels.get("fps", 60)))
    print(f"[fb-draft] format={fmt}  game={game}", flush=True)

    # Pool: fill draws from the vertical pool (fallback landscape); the rest use landscape footage.
    if fmt == "fill":
        vkey = f"{game}-vertical"
        clip_path, clip_id = reel_composer.pick_unused_clip(vkey, ["facebook"])
        if not clip_path:
            print(f"[fb-draft] no vertical clips in '{vkey}' — falling back to landscape footage.", flush=True)
            clip_path, clip_id = reel_composer.pick_unused_clip(game, ["facebook"])
    else:
        clip_path, clip_id = reel_composer.pick_unused_clip(game, ["facebook"])
    if not clip_path:
        print(f"[fb-draft] No footage in the '{game}' pool. Add clips + sync to B2 first.", flush=True)
        return 2
    print(f"[fb-draft] clip: {clip_id}", flush=True)

    dur = float(ffmpeg.duration(clip_path) or 0.0)
    target = round(min(dur, args.seconds), 1) if (args.seconds and dur) else (
        round(dur, 1) if dur else (args.seconds or 60.0))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "output" / f"fbdraft_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"fb_{fmt}_{game}_{stamp}_raw.mp4"     # pre-FB-encode render
    out = out_dir / f"fb_{fmt}_{game}_{stamp}.mp4"          # final FB-spec file (delivered)

    # Caption: fill = relatable moment line; composited = the clip-grounded caption. Both come
    # WITH the game hashtag set + brand tag already (<=5), matching the auto FB reel caption.
    if fmt == "fill":
        caption = content.relatable_fill_caption(clip_path, game)
        print(f"[fb-draft] rendering full-bleed vertical ({int(target)}s)...", flush=True)
        reel_ffmpeg.build_gameplay_fill(clip_path, raw, fps=fps, w=1080, h=1920,
                                        target_seconds=target, vol_db=float(vcfg.get("volume_db", 8.26)))
    else:
        hook, caption = content.hook_and_caption_from_video(clip_path, game, taglish=False)
        if fmt == "landscape":
            print(f"[fb-draft] rendering landscape 1920x1080 ({int(target)}s)...", flush=True)
            reel_ffmpeg.build_threads_landscape(clip_path, raw, logo=orch._reel_logo(), fps=fps,
                                                w=1920, h=1080, target_seconds=target, music=orch._reel_music())
        elif fmt == "triptych":
            art = orch._game_art(game)
            if not art:
                print(f"[fb-draft] no game art for '{game}' — try classic/fill/landscape.", flush=True)
                return 2
            print(f"[fb-draft] rendering triptych ({int(target)}s)...", flush=True)
            reel_ffmpeg.build_gameplay_triptych(clip_path, raw, hook=hook, game_art=art,
                                                game_art_video=orch._game_art_footage(game),
                                                top_image=orch._game_screenshot(game), logo=orch._reel_logo(),
                                                fps=fps, w=1080, h=1920, target_seconds=target,
                                                music=orch._reel_music(), anim_logo=orch._anim_logo())
        else:  # classic
            print(f"[fb-draft] rendering classic ({int(target)}s)...", flush=True)
            reel_ffmpeg.build_gameplay(clip_path, raw, hook=hook, logo=orch._reel_logo(), fps=fps,
                                       w=1080, h=1920, foot_h=int(gcfg.get("footage_height", 1320)),
                                       top_band=int(gcfg.get("top_band", 360)), target_seconds=target,
                                       music=orch._reel_music(), anim_logo=orch._anim_logo(),
                                       game_logo=orch._game_logo(game))

    # FB-SPEC RE-ENCODE: closed-GOP 60fps 15/20 (Rec.709 SDR, AAC 320k) so FB keeps 60fps on
    # the manual upload instead of downsampling the open-GOP CRF render to 30. This is what
    # makes an FB draft an FB draft. See reel_ffmpeg.reencode_facebook + [[facebook-reel-encode]].
    print("[fb-draft] re-encoding to FB Reels spec (closed-GOP 60fps 15/20)...", flush=True)
    reel_ffmpeg.reencode_facebook(raw, out, fps=fps)
    try:
        raw.unlink(missing_ok=True)
    except Exception:
        pass
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"[fb-draft] rendered {out.name} ({size_mb:.0f} MB)", flush=True)

    # Upload to B2 drafts/fb/ + ping Telegram (filename + size + caption).
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    key = f"drafts/fb/{out.name}"
    print(f"[fb-draft] uploading to B2 -> {key}", flush=True)
    rc = subprocess.run(["rclone", "copyto", str(out), f"{remote}:{b2_store._bucket()}/{key}",
                         "--b2-chunk-size", "100M"], env=_b2_env(remote)).returncode
    if rc != 0:
        print(f"[fb-draft] B2 upload failed (rc={rc}); file is local: {out}", flush=True)
        notify.telegram(f"⚠️ FB draft rendered but the B2 upload failed. File on the PC:\n"
                        f"{out}\n\n— caption —\n{caption}")
        print("\n[fb-draft] CAPTION:\n" + caption, flush=True)
        return 1
    msg = (f"\U0001F4D8 FB draft ready — {fmt}, {game}, {int(target)}s (60fps FB-spec)\n"
           f"\U0001F4C1 Backblaze → drafts/fb/\n"
           f"• File: {out.name}\n"
           f"• Size: {size_mb:.0f} MB\n\n"
           f"— caption (copy below) —\n{caption}")
    print("[fb-draft] Telegram ping:", "sent" if notify.telegram(msg) else "NOT sent", flush=True)

    # Mark the clip used so the auto feed won't post the same one (unless --keep-clip).
    if not args.keep_clip and clip_id:
        try:
            reel_composer.mark_clip_used(clip_id, ["facebook"])
            print(f"[fb-draft] marked clip used on FB (auto FB feed won't reuse it): {clip_id}", flush=True)
        except Exception:
            pass

    print("\n[fb-draft] DONE.\nCAPTION:\n" + caption, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
