"""On-demand THREADS DRAFT for MANUAL Threads posting — format-selectable.

Renders a gameplay reel in a chosen FORMAT, uploads it to B2 drafts/threads/, and Telegrams
a ping (filename + size + caption) so the user posts it by hand on Threads (the auto Threads
track is paused; this is deliberate hand-curation). FIRE ON DEMAND ONLY — posts nothing.

Formats:
  landscape  16:9 'as-is' graded clip + KG corner logo (Threads landscape video)
  fill       full-bleed 9:16 vertical (pure footage, scale-to-cover)
  triptych   3-panel 9:16 (needs game art)
  classic    9:16 footage band + on-screen hook + logos

Usage:
  python tools/threads_draft.py --format landscape [--game halo] [--seconds N]
  python tools/threads_draft.py --format fill --game spider-man2
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

FORMATS = ("landscape", "fill", "triptych", "classic")


def _default_game() -> str:
    try:
        pref = CONFIG.preferred_footage_games()
        if pref:
            return str(pref[0])
    except Exception:
        pass
    return str((CONFIG.reels.get("tiktok", {}) or {}).get("game", "spider-man2"))


def _threads_tag() -> str:
    return str((CONFIG.raw().get("threads_posts", {}) or {}).get("hashtag", "#GamingThreads")).strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render a gameplay reel in a chosen format + deliver it to Telegram for a "
                    "MANUAL Threads post.")
    ap.add_argument("--format", required=True, choices=sorted(FORMATS))
    ap.add_argument("--game", default=None, help="game key (default: current priority game)")
    ap.add_argument("--seconds", type=float, default=None, help="cap length (default: whole clip up to 5 min)")
    args = ap.parse_args()

    fmt = args.format
    game = args.game or _default_game()
    gcfg = CONFIG.reels.get("gameplay", {}) or {}
    vcfg = gcfg.get("vertical", {}) or {}
    fps = int(gcfg.get("fps", CONFIG.reels.get("fps", 60)))
    tag = _threads_tag()

    # Pool: fill draws from the vertical pool (fallback landscape); the rest use landscape footage.
    if fmt == "fill":
        clip_path, clip_id = reel_composer.pick_unused_clip(f"{game}-vertical")
        if not clip_path:
            clip_path, clip_id = reel_composer.pick_unused_clip(game)
    else:
        clip_path, clip_id = reel_composer.pick_unused_clip(game)
    if not clip_path:
        print(f"[threads-draft] No footage in the '{game}' pool. Add clips + sync to B2 first.", flush=True)
        return 2
    print(f"[threads-draft] format={fmt}  game={game}  clip={clip_id}", flush=True)

    dur = float(ffmpeg.duration(clip_path) or 0.0)
    cap = args.seconds or 300.0                              # Threads video ~5 min
    target = round(min(dur, cap), 1) if dur else cap
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "output" / f"threadsdraft_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"threads_{fmt}_{game}_{stamp}.mp4"

    # Caption: fill = relatable line; composited = the clip-grounded hook. Threads uses the
    # single #GamingThreads tag (per the Threads content rules), not the full hashtag set.
    if fmt == "fill":
        base = content.relatable_fill_caption(clip_path, game).split("\n\n#")[0].rstrip()
        caption = f"{base}\n\n{tag}".strip()
        print(f"[threads-draft] rendering full-bleed vertical ({int(target)}s)...", flush=True)
        reel_ffmpeg.build_gameplay_fill(clip_path, out, fps=fps, w=1080, h=1920,
                                        target_seconds=target, vol_db=float(vcfg.get("volume_db", 8.26)))
    else:
        hook, _ = content.hook_and_caption_from_video(clip_path, game, taglish=False)
        caption = f"{hook}\n\n{tag}".strip()
        if fmt == "landscape":
            print(f"[threads-draft] rendering landscape 1920x1080 ({int(target)}s)...", flush=True)
            reel_ffmpeg.build_threads_landscape(clip_path, out, logo=orch._reel_logo(), fps=fps,
                                                w=1920, h=1080, target_seconds=target, music=orch._reel_music())
        elif fmt == "triptych":
            art = orch._game_art(game)
            if not art:
                print(f"[threads-draft] no game art for '{game}' — try landscape/fill/classic.", flush=True)
                return 2
            print(f"[threads-draft] rendering triptych ({int(target)}s)...", flush=True)
            reel_ffmpeg.build_gameplay_triptych(clip_path, out, hook=hook, game_art=art,
                                                game_art_video=orch._game_art_footage(game),
                                                top_image=orch._game_screenshot(game), logo=orch._reel_logo(),
                                                fps=fps, w=1080, h=1920, target_seconds=target,
                                                music=orch._reel_music(), anim_logo=orch._anim_logo())
        else:  # classic
            print(f"[threads-draft] rendering classic ({int(target)}s)...", flush=True)
            reel_ffmpeg.build_gameplay(clip_path, out, hook=hook, logo=orch._reel_logo(), fps=fps,
                                       w=1080, h=1920, foot_h=int(gcfg.get("footage_height", 1320)),
                                       top_band=int(gcfg.get("top_band", 360)), target_seconds=target,
                                       music=orch._reel_music(), anim_logo=orch._anim_logo(),
                                       game_logo=orch._game_logo(game))

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"[threads-draft] rendered {out.name} ({size_mb:.0f} MB)", flush=True)

    # Upload to B2 drafts/threads/ + ping Telegram (filename + size + caption).
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    key = f"drafts/threads/{out.name}"
    print(f"[threads-draft] uploading to B2 -> {key}", flush=True)
    rc = subprocess.run(["rclone", "copyto", str(out), f"{remote}:{b2_store._bucket()}/{key}",
                         "--b2-chunk-size", "100M"], env=_b2_env(remote)).returncode
    if rc != 0:
        print(f"[threads-draft] B2 upload failed (rc={rc}); file is local: {out}", flush=True)
        notify.telegram(f"⚠️ Threads draft rendered but the B2 upload failed. File on the PC:\n"
                        f"{out}\n\n— caption —\n{caption}")
        print("\n[threads-draft] CAPTION:\n" + caption, flush=True)
        return 1
    msg = (f"\U0001F9F5 Threads draft ready — {fmt}, {game}, {int(target)}s\n"
           f"\U0001F4C1 Backblaze → drafts/threads/\n"
           f"• File: {out.name}\n"
           f"• Size: {size_mb:.0f} MB\n\n"
           f"— caption (copy below) —\n{caption}")
    print("[threads-draft] Telegram ping:", "sent" if notify.telegram(msg) else "NOT sent", flush=True)
    print("\n[threads-draft] CAPTION:\n" + caption, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
