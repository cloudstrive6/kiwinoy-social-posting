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
    narration,
    publisher,
    reel_composer,
    reel_script,
    research,
    threads_research,
    threads_writer,
)
from core import elevenlabs
from core.config import CONFIG, OUTPUT_DIR


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
        brief = research.run(category)
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

    # Image only after the post passes (gacha), to avoid spending on a skipped post.
    image_bytes = None
    image_path = None
    if not is_sports:
        log("Generating image...")
        image_path = run_dir / "image.png"
        image_bytes = image.run(brief, caption, save_path=image_path)
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
    """Reel slot: research -> caption + beats -> FACT-CHECK -> shots -> render -> publish."""
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

    # Generate shots + render only after the post passes.
    log(f"Generating {n_shots} background shot(s)...")
    image_paths = []
    for i in range(n_shots):
        p = run_dir / f"shot{i}.png"
        image.run_background(brief, i, n_shots, save_path=p)
        image_paths.append(p)

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
        brief, beats, image_paths, reel_path, narration_path=narration_path
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
        brief = research.run(category)
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
        log("Writing a risk/probability hot take + poll...")
        text = threads_writer.run_poll()
        passed = True
    else:
        categories = ["sports", "esports"] if post_type == "prediction" else ["sports"]
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
                log("Writing the prediction breakdown...")
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
