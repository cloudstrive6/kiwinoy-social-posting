"""Orchestrator — runs the pipeline for one scheduled slot, with a fact-check gate.

Each factual post is independently fact-checked before publishing. On a fail it
regenerates once; if it still fails, the post is skipped (nothing is published)
and the reason is logged. Polls are not fact-checked (pure opinion).

Every run writes an audit trail to output/<timestamp>_.../ (brief.json,
caption.txt / threads.txt, image.png / reel.mp4, result.json).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from agents import (
    carousel,
    content,
    factcheck,
    image,
    media,
    narration,
    publisher,
    reel_composer,
    reel_ffmpeg,
    reel_script,
    reel_topics,
    research,
    threads_research,
    threads_writer,
)
from core import elevenlabs
from core.config import CONFIG, OUTPUT_DIR, ROOT


def _reel_logo() -> Optional[Any]:
    """Resolve the channel logo file path for ffmpeg overlays (or None)."""
    cfg = CONFIG.reels.get("brand_logo")
    if not cfg:
        return None
    p = ROOT / cfg
    return p if p.exists() else None


def _anim_logo() -> Optional[tuple]:
    """(rgb_mp4, alpha_mp4) paths for the animated lower-third logo, or None."""
    a = CONFIG.reels.get("logo_animated", {}) or {}
    rgb, alpha = a.get("rgb"), a.get("alpha")
    if rgb and alpha and (ROOT / rgb).exists() and (ROOT / alpha).exists():
        return (ROOT / rgb, ROOT / alpha)
    return None


def _reel_music() -> Optional[Any]:
    """Pick a random royalty-free music track path (or None)."""
    import random
    from pathlib import Path
    mdir = ROOT / CONFIG.reels.get("music_dir", "reels/assets/music")
    if not mdir.exists():
        return None
    tracks = [p for p in mdir.iterdir()
              if p.suffix.lower() in {".mp3", ".m4a", ".aac", ".wav", ".ogg"}]
    return random.choice(tracks) if tracks else None


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _save(run_dir, result: dict[str, Any]) -> None:
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _factcheck_ok(text: str, brief: dict[str, Any], provider: str, log) -> bool:
    """True if the post passes fact-check (or the checker couldn't run)."""
    v = factcheck.review(text, brief, provider=provider)
    verdict = v.get("verdict")
    issues = "; ".join(v.get("issues", []) or [])
    if verdict == "pass":
        log("Fact-check: PASS")
        return True
    if verdict == "error":
        log(f"Fact-check could not run ({issues}); publishing anyway")
        return True  # fail-open on checker error so infra issues don't halt posting
    log(f"Fact-check: FAIL -> {issues or 'unspecified'}")
    return False


def run_slot(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Image/sports feed slot: research -> caption -> FACT-CHECK -> image -> publish.

    Sports = text-only on Facebook; Gacha = anime image on Facebook + Instagram.
    """
    slot = CONFIG.slot(slot_id)
    category = slot["category"]
    is_sports = category == "sports"
    run_dir = OUTPUT_DIR / f"{_stamp()}_slot{slot_id}_{category}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[slot {slot_id} | {category}] {m}", flush=True)

    brief: dict[str, Any] = {}
    caption = ""
    passed = False
    for attempt in range(2):
        if attempt:
            log("Regenerating after fact-check fail...")
        log("Researching trending topic...")
        brief = research.run(category, focus=slot.get("focus"))
        (run_dir / "brief.json").write_text(
            json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"Topic: {brief.get('title')}")
        log("Writing caption...")
        caption = content.run(brief)
        (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
        if _factcheck_ok(caption, brief, "claude", log):
            passed = True
            break

    targets = (
        CONFIG.platforms.get("sports_post_to", ["facebook"]) if is_sports
        else CONFIG.platforms.get("image_post_to", ["facebook", "instagram"])
    )
    result: dict[str, Any] = {
        "slot_id": slot_id, "category": category, "brief": brief,
        "caption": caption, "targets": targets, "dry_run": dry_run,
    }

    if not passed:
        log("Fact-check failed twice — skipping publish (nothing posted).")
        result["published"] = False
        result["skipped"] = "factcheck_failed"
        _save(run_dir, result)
        return result

    # Image only after the post passes, to avoid spending on a skipped post.
    # Prefer YOUR media (curated photo / footage frame, designed with the KG
    # headline); fall back to a generated AI image only if you have none.
    image_bytes = None
    image_path = None
    if not is_sports:
        image_path = run_dir / "image.png"
        log("Designing image from your photos/footage...")
        image_bytes = media.design(brief, image_path, work_dir=run_dir)
        if image_bytes:
            log(f"Designed from your media -> {image_path}")
        elif CONFIG.image.get("ai_fallback", True):
            log("No curated photo/footage for this topic; generating AI image...")
            image_bytes = image.run(brief, caption, save_path=image_path)
        else:
            log("No curated photo/footage and AI fallback is off — skipping post.")
            result["published"] = False
            result["skipped"] = "no_media"
            _save(run_dir, result)
            return result
        log(f"Image saved -> {image_path}")
    result["image_path"] = str(image_path) if image_path else None

    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log(f"Publishing ({'text-only' if image_bytes is None else 'image'}) to "
            f"{', '.join(targets)}...")
        api_result = publisher.run(
            caption=caption, image_bytes=image_bytes,
            platform_keys=targets, scheduled_at=scheduled_at,
        )
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    _save(run_dir, result)
    return result


def run_reel_slot(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Dispatch a reel slot by its `kind`.

    hype (default) -> animated Remotion hype reel (news-driven, MLBB).
    gameplay       -> standalone gameplay clip + a static hook caption (ffmpeg).
    commentary     -> Taglish voiceover over gameplay b-roll w/ subtitles (ffmpeg).
    """
    slot = CONFIG.reel_slot(slot_id)
    kind = str(slot.get("kind", "hype")).lower()
    if kind == "gameplay":
        return run_gameplay_reel(slot_id, dry_run=dry_run, scheduled_at=scheduled_at)
    if kind == "commentary":
        return run_commentary_reel(slot_id, dry_run=dry_run, scheduled_at=scheduled_at)
    return _run_hype_reel(slot_id, dry_run=dry_run, scheduled_at=scheduled_at)


def _run_hype_reel(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Hype reel: research -> caption + beats -> FACT-CHECK -> shots -> render -> publish."""
    slot = CONFIG.reel_slot(slot_id)
    category = slot["category"]
    focus = slot.get("focus")  # e.g. pin esports reels to MLBB
    n_shots = int(CONFIG.reels.get("shots", 3))
    taglish = bool(CONFIG.reels.get("taglish", False))
    # Rotate the recurring series formats by slot id so the feed feels familiar.
    formats = CONFIG.reels.get("formats", []) or []
    reel_format = formats[(slot_id - 1) % len(formats)] if formats else None
    run_dir = OUTPUT_DIR / f"{_stamp()}_reel{slot_id}_{category}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[reel {slot_id} | {category}] {m}", flush=True)

    brief: dict[str, Any] = {}
    caption = ""
    beats: list = []
    passed = False
    for attempt in range(2):
        if attempt:
            log("Regenerating after fact-check fail...")
        log(f"Researching trending topic{' (focus: ' + focus + ')' if focus else ''}...")
        brief = research.run(category, focus=focus)
        (run_dir / "brief.json").write_text(
            json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"Topic: {brief.get('title')}")
        log("Writing reel caption + on-screen beats...")
        caption = content.run(brief, taglish=taglish)
        (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
        beats = reel_script.run(brief, taglish=taglish, reel_format=reel_format)
        (run_dir / "beats.json").write_text(
            json.dumps(beats, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if _factcheck_ok(caption, brief, "claude", log):
            passed = True
            break

    result: dict[str, Any] = {
        "slot_id": slot_id, "category": category, "brief": brief,
        "caption": caption, "beats": beats, "dry_run": dry_run,
    }
    if not passed:
        log("Fact-check failed twice — skipping reel (nothing rendered/posted).")
        result["published"] = False
        result["skipped"] = "factcheck_failed"
        _save(run_dir, result)
        return result

    # Prefer the user's own gameplay footage; fall back to AI stills if none.
    clips = reel_composer.resolve_clips(brief)
    image_paths: list = []
    if clips:
        log(f"Using {len(clips)} of your gameplay clip(s): "
            f"{', '.join(p.name for p in clips)}")
    elif CONFIG.image.get("ai_fallback", True):
        log(f"No matching footage — generating {n_shots} AI background shot(s)...")
        for i in range(n_shots):
            p = run_dir / f"shot{i}.png"
            image.run_background(brief, i, n_shots, save_path=p)
            image_paths.append(p)
    else:
        log("No matching footage and AI fallback is off — skipping reel.")
        result["published"] = False
        result["skipped"] = "no_media"
        _save(run_dir, result)
        return result

    # Optional AI Taglish voiceover (fail-open: music-only if unavailable).
    narration_path = None
    if (CONFIG.reels.get("narration", {}) or {}).get("enabled", False):
        log("Writing + synthesizing Taglish voiceover...")
        vo_script = narration.write_script(brief, caption)
        (run_dir / "narration.txt").write_text(vo_script, encoding="utf-8")
        audio = elevenlabs.tts(vo_script)
        if audio:
            narration_path = run_dir / "narration.mp3"
            narration_path.write_bytes(audio)
            log(f"Voiceover ready ({len(audio)//1024} KB).")
        else:
            log("Voiceover unavailable (no key / disabled) — rendering music-only.")
        result["narration"] = vo_script

    log("Rendering reel with Remotion...")
    reel_path = run_dir / "reel.mp4"
    video_bytes = reel_composer.run(
        brief, beats, image_paths, reel_path,
        narration_path=narration_path, clips=clips,
    )
    log(f"Reel rendered -> {reel_path} ({len(video_bytes)//1024} KB)")
    result["reel_path"] = str(reel_path)

    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing reel to Instagram + Facebook Reels...")
        api_result = publisher.run_reel(
            caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at
        )
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    _save(run_dir, result)
    return result


def run_gameplay_reel(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Gameplay-only reel: one standalone clip + a static hook caption (no VO)."""
    taglish = bool(CONFIG.reels.get("taglish", True))
    gcfg = CONFIG.reels.get("gameplay", {}) or {}
    run_dir = OUTPUT_DIR / f"{_stamp()}_reel{slot_id}_gameplay"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[reel {slot_id} | gameplay] {m}", flush=True)

    games = reel_composer.list_games()
    if not games:
        log("No gameplay footage available — skipping.")
        return _skip(run_dir, {"slot_id": slot_id, "kind": "gameplay"}, "no_media")
    log(f"Footage available: {games}")
    # On-screen hook is ENGLISH (per user); the post caption (vision) may be Taglish.
    brief = reel_topics.run("gameplay", games, taglish=False)
    (run_dir / "brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Game: {brief.get('subject')} | Hook: {brief.get('hook')}")

    clips = reel_composer.clips_for_game(brief["game"], n=1)
    if not clips:
        log("Could not resolve a clip — skipping.")
        return _skip(run_dir, {"slot_id": slot_id, "kind": "gameplay", "brief": brief}, "no_media")

    log("Reviewing the clip to write a caption...")
    # Captions are ENGLISH for all gameplay reels (per user); the on-screen hook
    # is English too. Only reel narration/threads can be Taglish.
    caption = content.caption_from_video(clips[0], brief.get("game", ""), taglish=False)
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")

    log("Rendering gameplay reel with ffmpeg...")
    reel_path = run_dir / "reel.mp4"
    video_bytes = reel_ffmpeg.build_gameplay(
        clips[0], reel_path, hook=brief["hook"], logo=_reel_logo(),
        fps=int(gcfg.get("fps", CONFIG.reels.get("fps", 60))),
        w=int(gcfg.get("width", 1080)), h=int(gcfg.get("height", 1920)),
        foot_h=int(gcfg.get("footage_height", 1320)),
        top_band=int(gcfg.get("top_band", 360)),
        target_seconds=float(gcfg.get("target_seconds", 75)),
        music=_reel_music(), anim_logo=_anim_logo(),
    )
    log(f"Reel rendered -> {reel_path} ({len(video_bytes)//1024} KB)")

    result: dict[str, Any] = {
        "slot_id": slot_id, "kind": "gameplay", "brief": brief,
        "caption": caption, "reel_path": str(reel_path), "dry_run": dry_run,
    }
    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing gameplay reel to Instagram + Facebook Reels...")
        api_result = publisher.run_reel(
            caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at)
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")
    _save(run_dir, result)
    return result


def run_commentary_reel(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Commentary reel: Taglish voiceover over gameplay b-roll, synced subtitles.

    length 'short' -> a Reel; 'long' -> a video feed post (over Reel limits).
    """
    from core import ffmpeg as ff

    slot = CONFIG.reel_slot(slot_id)
    length = str(slot.get("length", "short")).lower()
    taglish = bool(CONFIG.reels.get("taglish", True))
    ccfg = CONFIG.reels.get("commentary", {}) or {}
    target = float(ccfg.get("long_seconds", 360) if length == "long"
                   else ccfg.get("short_seconds", 70))
    run_dir = OUTPUT_DIR / f"{_stamp()}_reel{slot_id}_commentary_{length}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[reel {slot_id} | commentary/{length}] {m}", flush=True)

    games = reel_composer.list_games()
    if not games:
        log("No gameplay footage available — skipping.")
        return _skip(run_dir, {"slot_id": slot_id, "kind": "commentary"}, "no_media")
    log(f"Footage available: {games}")
    brief = reel_topics.run("commentary", games, length=length, taglish=taglish)
    (run_dir / "brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Topic: {brief.get('title')} ({brief.get('subject')})")

    # Voiceover script -> fact-check -> timestamped TTS (subtitles).
    vo_text = reel_script.run_commentary(brief, target_seconds=target, taglish=taglish)
    (run_dir / "narration.txt").write_text(vo_text, encoding="utf-8")
    if not _factcheck_ok(vo_text, brief, "claude", log):
        log("Fact-check failed — skipping commentary reel.")
        return _skip(run_dir, {"slot_id": slot_id, "kind": "commentary", "brief": brief}, "factcheck_failed")

    log("Synthesizing Taglish voiceover + subtitles...")
    vo_path, subtitles = elevenlabs.tts_timed(vo_text, run_dir / "vo.mp3")
    if not vo_path:
        log("Voiceover unavailable (no key / TTS error) — skipping (commentary needs VO).")
        return _skip(run_dir, {"slot_id": slot_id, "kind": "commentary", "brief": brief}, "no_voiceover")
    vo_seconds = ff.duration(vo_path) or target
    log(f"Voiceover ready ({vo_seconds:.0f}s, {len(subtitles)} subtitle lines).")

    # Only resolve as many clips as the runtime needs (so we don't download a
    # whole big-clip library for a short reel), capped by max_clips.
    broll = float(ccfg.get("broll_seconds", 8)) or 8.0
    needed = min(int(ccfg.get("max_clips", 30)), int(vo_seconds // broll) + 4)
    clips = reel_composer.clips_for_game(brief["game"], n=max(3, needed))
    if not clips:
        log("Could not resolve clips — skipping.")
        return _skip(run_dir, {"slot_id": slot_id, "kind": "commentary", "brief": brief}, "no_media")

    caption = content.run_short(brief, taglish=taglish)
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")

    log(f"Rendering commentary reel with ffmpeg ({len(clips)} clips, ~{vo_seconds:.0f}s)...")
    reel_path = run_dir / "reel.mp4"
    video_bytes = reel_ffmpeg.build_commentary(
        clips, reel_path, vo_path=vo_path, total_seconds=vo_seconds,
        subtitles=subtitles, title=brief.get("title"), logo=_reel_logo(),
        fps=int(ccfg.get("fps", 30)), music=_reel_music(),
        per_clip_seconds=float(ccfg.get("broll_seconds", 8)),
        start_skip=float(ccfg.get("broll_start_min", 3)),
    )
    log(f"Reel rendered -> {reel_path} ({len(video_bytes)//1024} KB)")

    result: dict[str, Any] = {
        "slot_id": slot_id, "kind": "commentary", "length": length, "brief": brief,
        "caption": caption, "narration": vo_text, "reel_path": str(reel_path),
        "vo_seconds": vo_seconds, "dry_run": dry_run,
    }
    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        if length == "long":
            log("Publishing long commentary as a video post (IG Reel + FB video)...")
            api_result = publisher.run_video_post(
                caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at)
        else:
            log("Publishing commentary reel to Instagram + Facebook Reels...")
            api_result = publisher.run_reel(
                caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at)
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")
    _save(run_dir, result)
    return result


def _skip(run_dir, result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["published"] = False
    result["skipped"] = reason
    _save(run_dir, result)
    return result


def run_ready_reel(
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Post the oldest of YOUR OWN finished reels from the 'ready-reels' Release
    queue to FB/IG/Threads/YouTube, then remove it from the queue. Caption +
    hashtags come from the filename you queued it with (not regenerated)."""
    from core import ffmpeg as ff
    from core import gh_release
    from agents import content

    rcfg = CONFIG.reels.get("ready_reels", {}) or {}
    tag = rcfg.get("release_tag", "ready-reels")
    run_dir = OUTPUT_DIR / f"{_stamp()}_readyreel"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[ready-reel] {m}", flush=True)

    if not rcfg.get("enabled", True):
        return _skip(run_dir, {"kind": "ready_reel"}, "disabled")
    assets = gh_release.list_release_assets(tag)
    if not assets:
        log("Queue empty — drop reels in reels/assets/ready/ + run tools/ready_reels.py.")
        return _skip(run_dir, {"kind": "ready_reel"}, "queue_empty")
    assets.sort(key=lambda a: a.get("created_at", ""))  # oldest first (FIFO)
    asset = assets[0]
    log(f"Next of {len(assets)} queued: {asset['name']}")

    path = gh_release.download(asset, run_dir)
    if not path:
        return _skip(run_dir, {"kind": "ready_reel", "asset": asset["name"]}, "download_failed")

    # Decode "<game>__<caption>.mp4". Use a descriptive filename as the caption;
    # otherwise REVIEW the video and write one (the agent captions it).
    game, _, cap = Path(asset["name"]).stem.partition("__")
    line = cap.replace("_", " ").strip()
    generic = {"", "reel", "clip", "video", game.replace("-", " ").strip().lower()}
    if len(line.split()) < 2 or line.lower() in generic:
        log("Reviewing the reel to write a caption...")
        caption = content.caption_from_video(path, game, taglish=False)
    else:
        tags = content._reel_hashtags({"game": game, "subject": line})
        caption = f"{line}\n\n{' '.join(tags)}".strip()
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
    secs = ff.duration(path)

    result: dict[str, Any] = {
        "kind": "ready_reel", "asset": asset["name"], "caption": caption,
        "seconds": secs, "dry_run": dry_run,
    }
    if dry_run:
        log(f"DRY RUN — would post '{line}' ({secs:.0f}s) to "
            f"{CONFIG.platforms.get('video_post_to')}.")
        result["published"] = False
        _save(run_dir, result)
        return result

    # Long videos (> ~3 min) go out as feed video; short ones as Reels/Shorts.
    short = not (secs and secs > 185)
    log(f"Publishing to {', '.join(CONFIG.platforms.get('video_post_to', []))}...")
    api_result = publisher.publish_video(
        caption, path.read_bytes(), title=line, short=short, scheduled_at=scheduled_at)
    result["published"] = True
    result["postforme_result"] = api_result
    log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")
    if gh_release.delete_asset(asset.get("id")):
        log("Removed from the queue.")
    _save(run_dir, result)
    return result


def run_carousel_slot(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Carousel slot: research -> caption -> FACT-CHECK -> 3-5 slides -> publish."""
    slot = CONFIG.carousel_slot(slot_id)
    category = slot["category"]
    run_dir = OUTPUT_DIR / f"{_stamp()}_carousel{slot_id}_{category}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[carousel {slot_id} | {category}] {m}", flush=True)

    brief: dict[str, Any] = {}
    caption = ""
    passed = False
    for attempt in range(2):
        if attempt:
            log("Regenerating after fact-check fail...")
        log("Researching trending topic...")
        brief = research.run(category, focus=slot.get("focus"))
        (run_dir / "brief.json").write_text(
            json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"Topic: {brief.get('title')}")
        log("Writing caption...")
        caption = content.run(brief)
        (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
        if _factcheck_ok(caption, brief, "claude", log):
            passed = True
            break

    result: dict[str, Any] = {
        "slot_id": slot_id, "category": category, "brief": brief,
        "caption": caption, "dry_run": dry_run, "kind": "carousel",
    }
    if not passed:
        log("Fact-check failed twice — skipping carousel (nothing posted).")
        result["published"] = False
        result["skipped"] = "factcheck_failed"
        _save(run_dir, result)
        return result

    # Slides only after the caption passes, to avoid spending on a skipped post.
    log("Planning + generating slides...")
    slides, images = carousel.run(brief, caption, save_dir=run_dir)
    if not images:
        log("No curated photo/footage and AI fallback is off — skipping carousel.")
        result["published"] = False
        result["skipped"] = "no_media"
        _save(run_dir, result)
        return result
    (run_dir / "slides.json").write_text(
        json.dumps(slides, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log(f"{len(images)} slides generated -> {run_dir}")
    result["slides"] = slides
    result["n_slides"] = len(images)

    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing carousel to Facebook + Instagram...")
        api_result = publisher.run_carousel(
            caption=caption, images=images, scheduled_at=scheduled_at
        )
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    _save(run_dir, result)
    return result


def _threads_type_for_now() -> str:
    """Pick the Threads post type for this run by UTC hour."""
    tp = CONFIG.threads_posts
    h = datetime.now(timezone.utc).hour
    if h == int(tp.get("prediction_hour", 9)):
        return "prediction"
    if h == int(tp.get("poll_hour", 15)):
        return "poll"
    return "update"


def run_threads(
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
    post_type: Optional[str] = None,
) -> dict[str, Any]:
    """Threads track: research -> write -> FACT-CHECK -> publish (text only).

    post_type: "update", "prediction", or "poll" (polls skip fact-check).
    """
    post_type = post_type or _threads_type_for_now()
    run_dir = OUTPUT_DIR / f"{_stamp()}_threads_{post_type}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[threads | {post_type}] {m}", flush=True)

    brief: dict[str, Any] = {}
    text = ""
    passed = False

    if post_type == "poll":
        # Pure opinion — nothing to fact-check.
        log("Writing a gamer hot take + poll...")
        text = threads_writer.run_poll()
        passed = True
    else:
        categories = ["games", "verdict"] if post_type == "prediction" else ["games"]
        for attempt in range(2):
            if attempt:
                log("Regenerating after fact-check fail...")
            log(f"Researching a trending topic ({'+'.join(categories)})...")
            brief = threads_research.run(categories)
            (run_dir / "brief.json").write_text(
                json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            log(f"Topic: {brief.get('title')}")
            if post_type == "prediction":
                log("Writing the game verdict/breakdown...")
                text = threads_writer.run_prediction(brief)
            else:
                log("Writing the Threads post...")
                text = threads_writer.run(brief)
            if _factcheck_ok(text, brief, "claude", log):
                passed = True
                break

    (run_dir / "threads.txt").write_text(text, encoding="utf-8")
    log(f"Post ({len(text)} chars): {text[:90]}")

    result: dict[str, Any] = {
        "post_type": post_type, "brief": brief, "text": text,
        "chars": len(text), "dry_run": dry_run,
    }

    if not passed:
        log("Fact-check failed twice — skipping publish (nothing posted).")
        result["published"] = False
        result["skipped"] = "factcheck_failed"
        _save(run_dir, result)
        return result

    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing to Threads...")
        api_result = publisher.run_threads(text=text, scheduled_at=scheduled_at)
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    _save(run_dir, result)
    return result


def run_threads_image(
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Threads IMAGE post: research the hottest sport -> design a KG graphic on
    YOUR sports photo/footage -> publish to Threads (image + caption). Skips if
    you have no sports media for the topic (the text track still covers it)."""
    run_dir = OUTPUT_DIR / f"{_stamp()}_threadsimg"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[threads-image] {m}", flush=True)

    brief: dict[str, Any] = {}
    text = ""
    passed = False
    for attempt in range(2):
        if attempt:
            log("Regenerating after fact-check fail...")
        log("Researching the hottest sport...")
        brief = threads_research.run(["sports"])
        (run_dir / "brief.json").write_text(
            json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"Topic: {brief.get('title')}")
        text = threads_writer.run(brief)
        (run_dir / "threads.txt").write_text(text, encoding="utf-8")
        if _factcheck_ok(text, brief, "claude", log):
            passed = True
            break

    result: dict[str, Any] = {
        "post_type": "threads_image", "brief": brief, "text": text, "dry_run": dry_run,
    }
    if not passed:
        log("Fact-check failed twice — skipping.")
        result["published"] = False
        result["skipped"] = "factcheck_failed"
        _save(run_dir, result)
        return result

    log("Designing image from your sports media...")
    img = media.design(brief, run_dir / "image.png", work_dir=run_dir)
    if not img:
        log("No sports photo/footage for this topic — skipping (text track covers it).")
        result["published"] = False
        result["skipped"] = "no_media"
        _save(run_dir, result)
        return result

    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing image post to Threads...")
        api_result = publisher.run(
            caption=text, image_bytes=img,
            platform_keys=["threads"], scheduled_at=scheduled_at,
        )
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    _save(run_dir, result)
    return result
