"""Orchestrator — runs the full 5-agent pipeline for one scheduled slot.

Flow for a slot:
  Research -> Content (FB/IG caption) + Threads (post) -> Image -> Publish

Everything for a run is also written to output/<timestamp>_<category>/ so you
have a full audit trail (brief.json, caption.txt, threads.txt, image.png,
result.json).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agents import (
    content,
    image,
    publisher,
    reel_composer,
    reel_script,
    research,
    threads,
)
from core.config import CONFIG, OUTPUT_DIR


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def run_slot(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Execute the pipeline for a schedule slot.

    dry_run=True does research/writing/images but skips publishing.
    scheduled_at: ISO time to schedule the post; None = publish immediately.
    """
    slot = CONFIG.slot(slot_id)
    category = slot["category"]
    run_dir = OUTPUT_DIR / f"{_stamp()}_slot{slot_id}_{category}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log = lambda m: print(f"[slot {slot_id} | {category}] {m}", flush=True)

    # 1) Research & Trending --------------------------------------------
    log("Researching trending topic...")
    brief = research.run(category)
    (run_dir / "brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log(f"Topic: {brief.get('title')}")

    # 2) Content (FB/IG caption) ----------------------------------------
    log("Writing FB/IG caption...")
    caption = content.run(brief)
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")

    # 3) Threads post ----------------------------------------------------
    log("Writing Threads post...")
    threads_text = threads.run(brief)
    (run_dir / "threads.txt").write_text(threads_text, encoding="utf-8")

    # 4) Image -----------------------------------------------------------
    log("Generating image...")
    image_path = run_dir / "image.png"
    image_bytes = image.run(brief, caption, save_path=image_path)
    log(f"Image saved -> {image_path}")

    result: dict[str, Any] = {
        "slot_id": slot_id,
        "category": category,
        "brief": brief,
        "caption": caption,
        "threads": threads_text,
        "image_path": str(image_path),
        "dry_run": dry_run,
    }

    # 5) Publish ---------------------------------------------------------
    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing to Facebook + Instagram + Threads...")
        api_result = publisher.run(
            caption=caption,
            threads_text=threads_text,
            image_bytes=image_bytes,
            scheduled_at=scheduled_at,
        )
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return result


def run_reel_slot(
    slot_id: int,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Execute the reel pipeline for a reels schedule slot.

    Research -> reel post caption + on-screen beats -> background shots ->
    Remotion render -> publish video to IG/FB Reels (+ Threads).
    """
    slot = CONFIG.reel_slot(slot_id)
    category = slot["category"]
    n_shots = int(CONFIG.reels.get("shots", 3))
    run_dir = OUTPUT_DIR / f"{_stamp()}_reel{slot_id}_{category}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log = lambda m: print(f"[reel {slot_id} | {category}] {m}", flush=True)

    # 1) Research --------------------------------------------------------
    log("Researching trending topic...")
    brief = research.run(category)
    (run_dir / "brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log(f"Topic: {brief.get('title')}")

    # 2) Post caption + on-screen beats ---------------------------------
    log("Writing reel caption + on-screen beats...")
    caption = content.run(brief)
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
    beats = reel_script.run(brief)
    (run_dir / "beats.json").write_text(
        json.dumps(beats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3) Background shots -----------------------------------------------
    log(f"Generating {n_shots} background shot(s)...")
    image_paths = []
    for i in range(n_shots):
        p = run_dir / f"shot{i}.png"
        image.run_background(brief, i, n_shots, save_path=p)
        image_paths.append(p)

    # 4) Render the reel -------------------------------------------------
    log("Rendering reel with Remotion...")
    reel_path = run_dir / "reel.mp4"
    video_bytes = reel_composer.run(brief, beats, image_paths, reel_path)
    log(f"Reel rendered -> {reel_path} ({len(video_bytes)//1024} KB)")

    result: dict[str, Any] = {
        "slot_id": slot_id,
        "category": category,
        "brief": brief,
        "caption": caption,
        "beats": beats,
        "reel_path": str(reel_path),
        "dry_run": dry_run,
    }

    # 5) Publish ---------------------------------------------------------
    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    else:
        log("Publishing reel to Instagram + Facebook Reels (+ Threads)...")
        api_result = publisher.run_reel(
            caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at
        )
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")

    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return result
