"""Orchestrator — runs the pipeline for one scheduled slot, with a fact-check gate.

Each factual post is independently fact-checked before publishing. On a fail it
regenerates once; if it still fails, the post is skipped (nothing is published)
and the reason is logged. Polls are not fact-checked (pure opinion).

Every run writes an audit trail to output/<timestamp>_.../ (brief.json,
caption.txt / threads.txt, image.png / reel.mp4, result.json).
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

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
from core import elevenlabs, ffmpeg
from core.config import CONFIG, OUTPUT_DIR, ROOT


def _reel_logo() -> Optional[Any]:
    """Resolve the channel logo file path for ffmpeg overlays (or None)."""
    cfg = CONFIG.reels.get("brand_logo")
    if not cfg:
        return None
    p = ROOT / cfg
    return p if p.exists() else None


def _anim_logo() -> Optional[tuple]:
    """(rgb_mp4, alpha_mp4) paths for the animated lower-third logo, or None.
    Disabled globally per user (2026-06-27) — return None so no reel/video overlays
    it. Flip reels.logo_animated.enabled back to true to bring it back."""
    a = CONFIG.reels.get("logo_animated", {}) or {}
    if not a.get("enabled", True):
        return None
    rgb, alpha = a.get("rgb"), a.get("alpha")
    if rgb and alpha and (ROOT / rgb).exists() and (ROOT / alpha).exists():
        return (ROOT / rgb, ROOT / alpha)
    return None


def _game_logo(game: Optional[str]) -> Optional[Any]:
    """The game's logo PNG for the top-centre reel overlay, matched by filename
    keyword to the game's universe/key. Drop new PNGs in reels/assets/game-logo/
    named for the game (e.g. '...Spider-Man...'); returns None if none matches so
    the reel just renders without a game logo."""
    from core import game_quotes
    if not game:
        return None
    gcfg = CONFIG.reels.get("game_logo", {}) or {}
    folder = ROOT / gcfg.get("dir", "reels/assets/game-logo")
    if not folder.exists():
        return None
    # Explicit game-key -> filename map wins (unambiguous for FF7 original vs Remake).
    mapped = (gcfg.get("map", {}) or {}).get(game)
    if mapped and (folder / mapped).exists():
        return folder / mapped
    norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
    pngs = [(p, norm(p.stem)) for p in sorted(folder.iterdir())
            if p.suffix.lower() == ".png"]
    # Match most-specific first: the game KEY (e.g. 'spidermanmilesmorales'), then its
    # DISPLAY name (so a short key like 'ff7' still finds a 'Final Fantasy VII Remake'
    # logo), then the broader universe logo. Keys <3 chars are skipped so 're' doesn't
    # match everything with 're' in it (its 'Resident Evil' display name is used instead).
    gnames = CONFIG.reels.get("game_names", {}) or {}
    for key in (norm(game), norm(gnames.get(game, "")),
                norm(game_quotes.universe_for_game(game) or "")):
        if len(key) < 3:
            continue
        for p, nm in pngs:
            if key in nm:
                return p
    return None


def _game_art(game: Optional[str], alt: Optional[int] = None) -> Optional[Any]:
    """A key-art image for the 3-panel reel's bottom band. Drop image files in
    reels/assets/game-art/<game>/ (named by the footage folder key, e.g. spider-man1 /
    spider-man-miles-morales; the game's universe is also tried). Returns None if none
    exist so the reel falls back to the classic layout.

    `alt` = deterministically CYCLE the (sorted) art files instead of random — pass an
    incrementing index so successive triptychs ALTERNATE the art (e.g. main <-> art 1)."""
    from core import game_quotes
    if not game:
        return None
    base = ROOT / (CONFIG.reels.get("gameplay", {}) or {}).get(
        "art_dir", "reels/assets/game-art")
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    for key in (str(game), game_quotes.universe_for_game(game) or ""):
        d = base / key if key else None
        if d and d.is_dir():
            arts = [p for p in sorted(d.iterdir())
                    if p.is_file() and p.suffix.lower() in exts]
            if arts:
                return arts[alt % len(arts)] if alt is not None else random.choice(arts)
    return None


def _game_character(game: Optional[str]) -> Optional[Any]:
    """A random TRANSPARENT character cutout PNG for the thumbnail's prominent
    foreground subject. Drop hero renders (Cloud, Master Chief, ...) in
    reels/assets/game-character/<game>/ (matched by the footage key, then the game's
    universe). PNG only (they need transparency). None if none exist -> the thumbnail
    falls back to the subject-in-the-background look."""
    from core import game_quotes
    if not game:
        return None
    base = ROOT / (CONFIG.reels.get("thumbnail", {}) or {}).get(
        "character_dir", "reels/assets/game-character")
    for key in (str(game), game_quotes.universe_for_game(game) or ""):
        d = base / key if key else None
        if d and d.is_dir():
            pngs = [p for p in sorted(d.iterdir())
                    if p.is_file() and p.suffix.lower() in (".png", ".webp")]  # both carry alpha
            if pngs:
                return random.choice(pngs)
    return None


def _curated_renders(game: Optional[str]) -> list:
    from core import game_quotes
    if not game:
        return []
    base = ROOT / (CONFIG.reels.get("thumbnail", {}) or {}).get(
        "character_dir", "reels/assets/game-character")
    for key in (str(game), game_quotes.universe_for_game(game) or ""):
        d = base / key if key else None
        if d and d.is_dir():
            r = [p for p in sorted(d.iterdir())
                 if p.is_file() and p.suffix.lower() in (".png", ".webp")]
            if r:
                return r
    return []


def _best_curated_character(game: Optional[str]) -> Optional[Any]:
    """The BEST curated hero render (highest vision score), not a random one — rate each
    render in the game/universe folder for is-this-character / front-facing / quality /
    clean-cutout and return the top. Scores are cached by file mtime (one Haiku call per
    NEW render, then free). Fails open to the first render / random on any error."""
    renders = _curated_renders(game)
    if not renders:
        return None
    if len(renders) == 1:
        return renders[0]
    try:
        import json as _json

        from PIL import Image

        from core import vision
        cache_f = ROOT / "thumbnails" / ".render_scores.json"
        cache = {}
        if cache_f.exists():
            try:
                cache = _json.loads(cache_f.read_text())
            except Exception:
                cache = {}
        disp = str((CONFIG.reels.get("game_names", {}) or {}).get(str(game), game))
        subject = f"{disp} — the main playable character"
        tmp = ROOT / "output" / ".render_judge"
        tmp.mkdir(parents=True, exist_ok=True)
        best, best_sc = None, -1.0
        for p in renders:
            ckey = f"{game}/{p.name}:{int(p.stat().st_mtime)}"
            sc = cache.get(ckey)
            if sc is None:                         # flatten onto grey so the jpeg judge sees it
                im = Image.open(p).convert("RGBA")
                card = Image.new("RGBA", im.size, (128, 128, 128, 255))
                card.alpha_composite(im)
                jp = tmp / (p.stem + ".jpg")
                card.convert("RGB").save(jp, "JPEG", quality=90)
                r = vision.rate_character_render(jp, subject=subject)
                sc = r["score"] if r else 0.5      # no vision -> neutral, keep deterministic order
                cache[ckey] = sc
            if sc > best_sc:
                best, best_sc = p, sc
        try:
            cache_f.write_text(_json.dumps(cache))
        except Exception:
            pass
        if best:
            print(f"[youtube] best curated render: {best.name} (score {best_sc})", flush=True)
        return best or renders[0]
    except Exception as e:
        print(f"[youtube] render ranking failed ({e!r}) — random pick.", flush=True)
        return random.choice(renders)


def _pool_key(game: Optional[str]) -> Optional[str]:
    """Map a footage/game key to its cloud image-pool FOLDER key when they differ
    (the pool is keyed by the assets/images/<folder> name, which isn't always the
    game key — e.g. game 'thelastofus2' but images live under 'thelastofuspart2').
    Config: reels.image_pool_map. Falls back to the game key unchanged."""
    if not game:
        return None
    m = (CONFIG.reels.get("image_pool_map", {}) or {})
    return str(m.get(str(game), game))


def _game_screenshot(game: Optional[str]) -> Optional[Any]:
    """A real game screenshot for the triptych TOP panel, pulled from the cloud
    image library (the assets/images uploaded to the qimg pool), matched to THIS
    game (or its universe). Does NOT touch the quote-card image ledger. Returns None
    so the renderer falls back to a still frame from the clip — which is ALWAYS the
    right game — rather than ever showing a screenshot from a different game."""
    from core import gh_release, game_quotes
    if not game:
        return None
    key = _pool_key(game)
    # LOCAL curated images first (assets/images/<key>) — prioritized over the cloud pool,
    # e.g. the user's hand-picked FF7 Remake shots for the triptych top panel.
    ldir = ROOT / "assets" / "images" / key
    if ldir.is_dir():
        imgs = [p for p in sorted(ldir.iterdir())
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        if imgs:
            return random.choice(imgs)
    try:
        pool = gh_release.quote_image_pool()
        if not pool:
            return None
        universe = game_quotes.universe_for_game(game)
        if key in pool:                       # exact game folder first (SM1 -> SM1 shots)
            games = [key]
        elif universe and [g for g in pool if game_quotes.universe_for_game(g) == universe]:
            games = [g for g in pool if game_quotes.universe_for_game(g) == universe]
        else:
            return None                       # no match -> clip frame, NEVER a random other game
        names = [n for g in games for n in (pool.get(g, []) or [])]
        if not names:
            return None
        name = random.choice(names)
        return gh_release.download(
            {"name": name, "url": gh_release.asset_download_url(name)},
            ROOT / "output" / ".art_cache")
    except Exception as e:
        print(f"[reel] game screenshot fetch failed ({e!r})", flush=True)
        return None


def _pool_samples(game: Optional[str], n: int = 3) -> list[str]:
    """Download up to n curated stills from the cloud image pool for a game (exact
    game, else its universe) — the preferred, sharp thumbnail source."""
    if not game:
        return []
    try:
        from core import game_quotes, gh_release
        pool = gh_release.quote_image_pool() or {}
        names = list(pool.get(_pool_key(game), []) or [])
        if not names:
            uni = game_quotes.universe_for_game(game)
            if uni:
                names = [x for g in pool if game_quotes.universe_for_game(g) == uni
                         for x in (pool.get(g) or [])]
        if not names:
            return []
        out: list[str] = []
        for nm in random.sample(names, min(int(n), len(names))):
            p = gh_release.download({"name": nm, "url": gh_release.asset_download_url(nm)},
                                    ROOT / "output" / ".thumb_pool")
            if p:
                out.append(str(p))
        return out
    except Exception as e:
        print(f"[youtube] pool sample failed ({e!r})", flush=True)
        return []


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
    game: Optional[str] = None,        # force this game (dedicated track, e.g. TikTok TLOU2)
    tiktok_only: bool = False,         # publish ONLY to TikTok via Zernio (not the PfM platforms)
) -> dict[str, Any]:
    """Gameplay-only reel: one standalone clip + a static hook caption (no VO).

    Dedicated-track mode (game=<key>, tiktok_only=True): force the game, alternate
    classic<->triptych on THAT game's used-clip count, and post only to TikTok."""
    taglish = bool(CONFIG.reels.get("taglish", True))
    gcfg = CONFIG.reels.get("gameplay", {}) or {}
    run_dir = OUTPUT_DIR / f"{_stamp()}_reel{slot_id}_gameplay"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[reel {slot_id} | gameplay] {m}", flush=True)

    if game:                                   # dedicated track — this game only
        disp = str((CONFIG.reels.get("game_names", {}) or {}).get(game, game))
        brief = {"game": game, "subject": disp, "category": "gameplay"}
        log(f"Forced game (dedicated track): {disp}")
    else:
        games = reel_composer.list_games()
        if not games:
            log("No gameplay footage available — skipping.")
            return _skip(run_dir, {"slot_id": slot_id, "kind": "gameplay"}, "no_media")
        log(f"Footage available: {games}")
        # reel_topics only PICKS the game here (preferring e.g. Spider-Man); the hook
        # itself is written from the actual clip + lore below, so it fits the footage.
        brief = reel_topics.run("gameplay", games, taglish=False)
    # --- Decide the LAYOUT first: it selects the footage pool + caption style.
    # Format variety per reel (helps avoid platform spam-detection). Alternate the
    # NON-rotated layouts (classic <-> triptych <-> fill) on the persistent used-clip
    # counter; the sideways "rotated" look is INSTAGRAM-EXCLUSIVE (~every 3rd reel).
    layouts = [str(x) for x in (gcfg.get("layouts") or ["classic"])]
    try:
        from core import gh_release as _ghr
        used = _ghr.used_clips()
        # A dedicated (forced-game) track alternates on THAT game's own used count.
        n = len([u for u in used if str(u).startswith(f"{game}__")]) if game else len(used)
    except Exception:
        n = 0
    main_layouts = [l for l in layouts if l != "rotated"] or ["classic"]
    layout = main_layouts[n % len(main_layouts)]
    reel_path = run_dir / "reel.mp4"
    fps = int(gcfg.get("fps", CONFIG.reels.get("fps", 60)))
    rw, rh = int(gcfg.get("width", 1080)), int(gcfg.get("height", 1920))
    vcfg = gcfg.get("vertical", {}) or {}

    if layout == "fill":
        # FILL: full-bleed vertical from the DEDICATED vertical pool ('<game>-vertical'),
        # the raw landscape scaled to COVER 9:16. Falls back to classic if none exist.
        vkey = f"{brief['game']}{vcfg.get('key_suffix', '-vertical')}"
        clip_path, clip_id = reel_composer.pick_unused_clip(vkey)
        if not clip_path:
            log(f"No vertical footage ({vkey}) — using the classic layout this slot.")
            layout = "classic"
    if layout == "fill":
        # Generic GAME caption (the raw footage isn't reviewed); no on-screen hook.
        caption = content.generic_game_caption(brief["game"])
        hook = ""
        brief["hook"] = ""
        target = float(vcfg.get("max_seconds", 180))     # use the FULL clip (up to 3 min)
        log(f"Game: {brief.get('subject')} | FILL vertical | clip {clip_id}")
    else:
        # Landscape-composited layouts: pick from the normal pool + review the clip for
        # a lore-grounded on-screen hook + caption (ENGLISH per user).
        clip_path, clip_id = reel_composer.pick_unused_clip(brief["game"])
        if not clip_path:
            log("Could not resolve a clip — skipping.")
            return _skip(run_dir, {"slot_id": slot_id, "kind": "gameplay", "brief": brief}, "no_media")
        log(f"Clip (fresh-first): {clip_id}")
        log("Reviewing the clip to write the on-screen hook + caption...")
        hook, caption = content.hook_and_caption_from_video(
            clip_path, brief.get("game", ""), taglish=False)
        brief["hook"] = hook  # record the clip-grounded hook (replaces the generic one)
        choices = [float(x) for x in (gcfg.get("target_seconds_choices") or [])]
        target = random.choice(choices) if choices else float(gcfg.get("target_seconds", 75))
        log(f"Game: {brief.get('subject')} | Hook: {hook}")
    (run_dir / "brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")

    # IG-only rotated turn — never on the TikTok track or a fill turn (IG gets the fill).
    ig_rotated = ((not tiktok_only) and ("rotated" in layouts)
                  and (n % 3 == 2) and layout != "fill")
    art = _game_art(brief.get("game")) if layout == "triptych" else None
    # TikTok export: MATCH the FB/IG/Threads feed encode by default (per user 2026-07-07).
    # The 30 Mbps "hi" spec backfired on TikTok's PUBLIC API transcode (proven: high bitrate
    # degrades worse). Set reels.tiktok.hi_bitrate: true to restore the 30M browser-upload spec.
    tt_hi = tiktok_only and bool((CONFIG.reels.get("tiktok", {}) or {}).get("hi_bitrate", False))
    if layout == "fill":
        # Full-bleed: raw landscape scaled to COVER 9:16, pure footage (no overlay),
        # original game audio + the 1080p reels' +vol_db boost, FULL clip.
        log(f"Rendering FULL-BLEED vertical reel (full clip, <={int(target)}s)...")
        video_bytes = reel_ffmpeg.build_gameplay_fill(
            clip_path, reel_path, fps=fps, w=rw, h=rh, target_seconds=target,
            vol_db=float(vcfg.get("volume_db", 8.26)), hi_bitrate=tt_hi)
    elif layout == "triptych" and art:
        top = _game_screenshot(brief.get("game"))  # curated screenshot or None->clip frame
        log(f"Rendering 3-panel gameplay reel (art: {art.name}, "
            f"top: {'library' if top else 'clip-frame'}, <={int(target)}s)...")
        video_bytes = reel_ffmpeg.build_gameplay_triptych(
            clip_path, reel_path, hook=hook, game_art=art, top_image=top,
            logo=_reel_logo(), fps=fps, w=rw, h=rh, target_seconds=target,
            music=_reel_music(), anim_logo=_anim_logo(), hi_bitrate=tt_hi)
    else:
        if layout == "triptych":
            log("No game art for this game — using the classic layout this slot.")
        log(f"Rendering gameplay reel with ffmpeg (target <={int(target)}s)...")
        video_bytes = reel_ffmpeg.build_gameplay(
            clip_path, reel_path, hook=hook, logo=_reel_logo(),
            fps=fps, w=rw, h=rh,
            foot_h=int(gcfg.get("footage_height", 1320)),
            top_band=int(gcfg.get("top_band", 360)),
            target_seconds=target,
            music=_reel_music(), anim_logo=_anim_logo(),
            game_logo=_game_logo(brief.get("game")),
            hi_bitrate=tt_hi,
        )
    # Actual length = min(target, clip length). FB Reels caps ~90s, so anything
    # longer publishes as a Reel on IG + Short on YouTube but a feed video on FB.
    actual = ffmpeg.duration(reel_path) or target
    is_short = actual <= 90.0
    log(f"Reel rendered ({layout}) -> {reel_path} ({len(video_bytes)//1024} KB, "
        f"{actual:.0f}s, {'Reel/Short' if is_short else 'long video on FB'})")

    # Instagram-EXCLUSIVE rotated version — rendered only on IG's rotated turn. The
    # landscape gameplay ROTATED 90° CW into 9:16 (KG logo upright top-right, no hook
    # bar — the hook rides the caption). FB/Threads/YouTube never get this look.
    ig_rotated_bytes = None
    if ig_rotated:
        log(f"Rendering Instagram-only ROTATED (90° CW) reel (<={int(target)}s)...")
        try:
            ig_rotated_bytes = reel_ffmpeg.build_footage_rotated(
                clip_path, run_dir / "reel_ig_rotated.mp4", logo=_reel_logo(),
                fps=fps, target_seconds=target, music=_reel_music())
        except Exception as e:
            log(f"Rotated render failed ({e!r}) — IG will get the {layout} reel instead.")
            ig_rotated = False

    result: dict[str, Any] = {
        "slot_id": slot_id, "kind": "gameplay", "brief": brief, "clip_id": clip_id,
        "target_seconds": target, "actual_seconds": round(actual, 1),
        "caption": caption, "reel_path": str(reel_path), "dry_run": dry_run,
    }
    if dry_run:
        log("DRY RUN — skipping publish.")
        result["published"] = False
    elif tiktok_only:
        # Dedicated TikTok track. Route by top-level config `tiktok.via`:
        #   postforme -> PfM DRAFT (full-quality HD/60fps HDR, but you PUBLISH MANUALLY
        #                in-app + paste the caption — PfM's TikTok app is unaudited so
        #                public direct-post 403s; per user 2026-07-09), else
        #   zernio     -> auto-public (lower quality; Zernio re-compresses server-side).
        # TikTok-only extra hashtags (e.g. #gaming) are appended to the TikTok caption only.
        tt_caption = caption
        extra = [str(h).strip() for h in (CONFIG.reels.get("tiktok", {}) or {}).get("extra_hashtags", []) or []]
        add = [(h if h.startswith("#") else "#" + h) for h in extra
               if h and h.lower().lstrip("#") not in caption.lower()]
        if add:
            tt_caption = f"{caption.rstrip()} {' '.join(add)}".strip()
        via = str((CONFIG.raw().get("tiktok", {}) or {}).get("via", "zernio")).lower()
        if via == "postforme":
            from agents import publisher
            log("Publishing to TikTok via Post for Me (DRAFT — publish manually in-app; "
                "paste the caption from PfM)...")
            res = publisher.run_tiktok_draft(tt_caption, video_bytes)
        else:
            from core import zernio
            log("Publishing to TikTok via Zernio...")
            res = zernio.publish_reel(video_bytes, tt_caption)
        result["published"] = bool(res)
        result["tiktok_result"] = res
        result["tiktok_via"] = via
        if res and reel_composer.mark_clip_used(clip_id):
            log(f"Marked clip used: {clip_id}")
    else:
        # YouTube is gated separately (reels.youtube). RESUMED 2026-07-01: 3 reels/day
        # = 3 Shorts/day (the spam-safe cap), so when enabled EVERY gameplay reel also
        # posts to YouTube. (The old per-slot gate never matched — the reels cron
        # always sends slot 1.)
        targets = [t for t in CONFIG.platforms.get(
            "video_post_to", ["facebook", "instagram", "threads"]) if t != "x"]
        ycfg = CONFIG.reels.get("youtube", {}) or {}
        if ycfg.get("enabled", False):
            targets = targets + ["youtube"]
        # On THREADS only, use a single game hashtag (per user). FB/IG/YT keep the
        # full caption + their fuller hashtags. The FILL format follows the Threads
        # LANDSCAPE rule instead: caption body + #GamingThreads only (no game tags).
        if layout == "fill":
            body = caption.split("\n\n#")[0].rstrip()   # drop the trailing game-tag block
            threads_cap = publisher._with_threads_tag(body)
        else:
            gtags = content._reel_hashtags({"game": brief.get("game")}, 1)
            threads_cap = f"{hook}\n\n{gtags[0]}".strip() if gtags else hook
        # On IG's rotated turn, IG gets its OWN rotated reel (below) — so drop IG from
        # the main classic/triptych post; otherwise IG shares the main reel.
        main_targets = [t for t in targets if t != "instagram"] if ig_rotated else targets
        log(f"Publishing {layout} reel to {', '.join(main_targets)}...")
        api_result = (publisher.run_reel if is_short else publisher.run_video_post)(
            caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at,
            targets=main_targets, threads_caption=threads_cap)
        result["published"] = True
        result["postforme_result"] = api_result
        log(f"Published. Post id: {api_result.get('id', '(see result.json)')}")
        # NOTE: TikTok is NOT posted here — it's a SEPARATE dedicated track
        # (run_tiktok_reel: TLOU2-only, 4x/day) so the general multi-game reels don't
        # land on TikTok. See core/zernio.py.

        # Instagram-exclusive rotated reel: its own IG-only post with full hashtags.
        ig_video = video_bytes                      # the video IG received (for the Story)
        if ig_rotated and ig_rotated_bytes is not None:
            try:
                ig_tags = content._reel_hashtags({"game": brief.get("game")})
                ig_caption = f"{hook}\n\n{' '.join(ig_tags)}".strip() if ig_tags else hook
                log(f"Publishing Instagram-only rotated reel ({' '.join(ig_tags)})...")
                result["ig_rotated_result"] = publisher.run_reel(
                    caption=ig_caption, video_bytes=ig_rotated_bytes,
                    scheduled_at=scheduled_at, targets=["instagram"])
                ig_video = ig_rotated_bytes
                log("Instagram rotated reel published.")
            except Exception as e:  # IG rotated is a bonus — never sink the main post
                log(f"Instagram rotated reel skipped ({e!r})")
                result["ig_rotated_error"] = repr(e)

        # Remember this clip so the next gameplay reel uses fresh footage. The
        # clip itself stays on the release for future commentary reels.
        if reel_composer.mark_clip_used(clip_id):
            log(f"Marked clip used: {clip_id}")

        # Reach-booster: also repost the reel to the Instagram STORY (placement=
        # stories), using whichever video IG received. IG-only, best-effort.
        if gcfg.get("ig_stories", False) and "instagram" in targets:
            try:
                log("Reposting reel to Instagram Story...")
                story_cap = f"{hook}\n\n{gtags[0]}".strip() if gtags else hook
                result["ig_story_result"] = publisher.run_ig_story(
                    caption=story_cap, video_bytes=ig_video, scheduled_at=scheduled_at)
                log("IG Story reposted.")
            except Exception as e:  # Stories are ephemeral bonus reach — never fatal
                log(f"IG Story repost skipped ({e!r})")
                result["ig_story_error"] = repr(e)

        # Same reach-booster on the FACEBOOK Page Story (whatever FB received).
        if gcfg.get("fb_stories", False) and "facebook" in targets:
            try:
                log("Reposting reel to Facebook Story...")
                story_cap = f"{hook}\n\n{gtags[0]}".strip() if gtags else hook
                result["fb_story_result"] = publisher.run_fb_story(
                    caption=story_cap, media_bytes=video_bytes, is_video=True,
                    scheduled_at=scheduled_at)
                log("Facebook Story reposted.")
            except Exception as e:  # ephemeral bonus reach — never fatal
                log(f"Facebook Story repost skipped ({e!r})")
                result["fb_story_error"] = repr(e)
    _save(run_dir, result)
    return result


def run_commentary_reel(
    slot_id: int = 0,
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
    length: Optional[str] = None,
) -> dict[str, Any]:
    """Commentary reel: Taglish voiceover over gameplay b-roll, synced subtitles.
    Same visual treatment as the gameplay reels (3:4 band, circular + animated
    logos, Taglish on-screen hook). Posts to Facebook only (reels.commentary.post_to).

    length 'short'/'medium'/'long'. If not passed, taken from the reel slot, else
    a random choice from reels.commentary.length_choices ("vary it").
    """
    from core import ffmpeg as ff

    ccfg = CONFIG.reels.get("commentary", {}) or {}
    if not ccfg.get("enabled", True):
        print("[commentary] paused (reels.commentary.enabled=false) — skipping.", flush=True)
        return {"kind": "commentary", "published": False, "skipped": "disabled"}
    if length is None:
        try:
            length = str(CONFIG.reel_slot(slot_id).get("length", "")).lower() or None
        except Exception:
            length = None
    if length is None:
        length = random.choice([str(x) for x in (ccfg.get("length_choices") or ["short"])])
    length = str(length).lower()
    taglish = bool(CONFIG.reels.get("taglish", True))
    target = float({"long": ccfg.get("long_seconds", 360),
                    "medium": ccfg.get("medium_seconds", 150)}.get(
                       length, ccfg.get("short_seconds", 70)))
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
    gcfg = CONFIG.reels.get("gameplay", {}) or {}  # reuse the gameplay frame layout
    video_bytes = reel_ffmpeg.build_commentary(
        clips, reel_path, vo_path=vo_path, total_seconds=vo_seconds,
        subtitles=subtitles, title=brief.get("title"), logo=_reel_logo(),
        fps=int(ccfg.get("fps", 30)), music=_reel_music(),
        w=int(gcfg.get("width", 1080)), h=int(gcfg.get("height", 1920)),
        foot_h=int(gcfg.get("footage_height", 1440)),
        top_band=int(gcfg.get("top_band", 320)), anim_logo=_anim_logo(),
        game_logo=_game_logo(brief.get("game")),
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
        targets = list(ccfg.get("post_to", ["facebook"]))  # FB only (for now)
        is_short = length == "short"  # FB Reels for short, FB feed video for longer
        log(f"Publishing commentary ({length}) to {targets} "
            f"as {'Reel' if is_short else 'feed video'}...")
        api_result = publisher.publish_video(
            caption=caption, video_bytes=video_bytes, title=brief.get("title"),
            short=is_short, scheduled_at=scheduled_at, targets=targets)
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
    """Pick the Threads post type. ENGAGEMENT-FIRST (per user): mostly conversation-
    starters (this-or-that / hot-take / question / poll...) that drive REPLIES, plus
    ~update_ratio that ride a trending gaming moment ('update')."""
    tp = CONFIG.threads_posts
    if random.random() < float(tp.get("update_ratio", 0.2)):
        return "update"
    formats = list(tp.get("engagement_formats") or
                   ["this_or_that", "hot_take", "question", "rank",
                    "would_you_rather", "nostalgia", "poll"])
    return random.choice(formats)


def run_threads(
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
    post_type: Optional[str] = None,
) -> dict[str, Any]:
    """Threads track: research -> write -> FACT-CHECK -> publish (text only).

    post_type: "update", "prediction", or "poll" (polls skip fact-check).
    """
    if not (CONFIG.raw().get("threads_posts", {}) or {}).get("enabled", True):
        print("[threads] disabled (threads_posts.enabled=false) — skipping.", flush=True)
        return {"kind": "threads", "published": False, "skipped": "disabled"}
    post_type = post_type or _threads_type_for_now()
    run_dir = OUTPUT_DIR / f"{_stamp()}_threads_{post_type}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[threads | {post_type}] {m}", flush=True)

    brief: dict[str, Any] = {}
    text = ""
    passed = False

    tcfg = CONFIG.raw().get("threads_posts", {}) or {}
    if post_type == "poll":
        # Pure opinion — nothing to fact-check.
        log("Writing a gamer hot take + poll...")
        text = threads_writer.run_poll()
        passed = True
    elif post_type in threads_writer.ENGAGEMENT_FORMATS:
        # Conversation-starter about one of our franchises (evergreen). Still
        # fact-checked for lore accuracy (never reference a game that doesn't exist).
        subject = random.choice(tcfg.get("subjects") or ["Marvel's Spider-Man"])
        brief = {"subject": subject, "focus_game": subject, "key_facts": [],
                 "title": f"{post_type.replace('_', ' ')} - {subject}"}
        for attempt in range(2):
            if attempt:
                log("Regenerating after fact-check fail...")
            log(f"Writing a {post_type} conversation-starter about {subject}...")
            text = threads_writer.run_engagement(post_type, subject)
            if _factcheck_ok(text, brief, "claude", log):
                passed = True
                break
    else:
        # "update" — ride a trending gaming moment.
        for attempt in range(2):
            if attempt:
                log("Regenerating after fact-check fail...")
            log("Researching a trending topic (games)...")
            brief = threads_research.run(["games"])
            (run_dir / "brief.json").write_text(
                json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            log(f"Topic: {brief.get('title')}")
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


def _quote_footage_frame(run_dir, log) -> Optional[Any]:
    """Fallback backdrop: a striking frame from gameplay footage, used when the
    image asset folders are empty/sparse."""
    try:
        from core import frames
        games = reel_composer.list_games()
        prefer = [g for g in (CONFIG.reels.get("footage", {}) or {}).get("prefer", [])
                  if g in games] or list(games)
        if not prefer:
            return None
        clips = reel_composer.clips_for_game(random.choice(prefer), n=1)
        if not clips:
            return None
        cands = frames.extract_candidates(clips[0], run_dir, n=3)
        return random.choice(cands) if cands else None
    except Exception as e:
        log(f"footage-frame fallback failed ({e!r})")
        return None


def _quote_short_clips(n: int) -> list:
    """A few gameplay clips for the YouTube quote Short's b-roll (one game for
    now; the user will add more games/clips for cross-game splices)."""
    games = reel_composer.list_games()
    if not games:
        return []
    prefer = [g for g in (CONFIG.reels.get("footage", {}) or {}).get("prefer", [])
              if g in games] or list(games)
    return reel_composer.clips_for_game(random.choice(prefer), n=max(2, n))


def run_quote_card(
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
    theme: Optional[str] = None,
) -> dict[str, Any]:
    """Motivational quote CARD (quote overlaid on a gameplay photo) -> FB.

    Generates an original English quote, picks the best photo from the image
    asset folders (falls back to a footage frame), renders a designed card, and
    publishes to Facebook (quotes.post_to). theme is 'gameplay' or 'life'; when
    None/'auto' a daily ledger picks whichever is below its per-day target so the
    generic external triggers land the configured mix (default 2 gameplay + 2 life)."""
    from pathlib import Path
    from agents import quote
    from core import gh_release

    qcfg = CONFIG.raw().get("quotes", {}) or {}
    run_dir = OUTPUT_DIR / f"{_stamp()}_quote_card"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[quote-card] {m}", flush=True)

    if theme in (None, "auto"):
        theme = gh_release.pick_quote_theme(qcfg.get("daily_themes") or None)
    if theme == "gameplay":            # legacy alias for the game-story theme
        theme = "story"
    if not dry_run:
        gh_release.record_quote_theme(theme)  # claim the slot so runs self-balance

    universe = str(qcfg.get("story_universe", "spider-man"))
    attribution = None
    story = None
    if theme == "story":
        # A REAL, attributed quote from the footage's universe (e.g. Spider-Man).
        story = quote.story_quote(universe)
        if story:
            q = story["line"]
            attribution = story["author"]  # just WHO said it (no game/movie source)
        else:
            theme = "gameplay"         # no curated set yet -> game-themed fallback (no life)
    if theme != "story":
        q = quote.generate(theme="gameplay")
    log(f"Theme: {theme}" + (f" ({universe}: {attribution})" if attribution else ""))
    log(f"Quote: {q}")
    photo = quote.pick_photo(q, universe=(universe if story else None)) \
        or _quote_footage_frame(run_dir, log)
    if not photo:
        log("No photo (image assets empty + no footage frame) — skipping.")
        return _skip(run_dir, {"kind": "quote_card", "quote": q, "theme": theme}, "no_media")
    log(f"Photo: {Path(photo).name}")

    card_path = run_dir / "card.png"
    quote.render_card(q, Path(photo), card_path, logo=_reel_logo(), attribution=attribution)
    (run_dir / "quote.txt").write_text(q, encoding="utf-8")

    # Caption ELABORATES on the quote (relatable), it does NOT repeat it.
    caption = (quote.elaborate_story(story["line"], story["author"], story["source"])
               if story else quote.elaborate(q, theme="life"))
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
    log(f"Quote: {q}\n           Caption: {caption}")

    tags = " ".join(qcfg.get("hashtags", []))
    targets = list(qcfg.get("post_to", ["facebook"]))
    tag_plats = set(qcfg.get("hashtag_platforms", ["facebook", "instagram"]))
    # Instagram now gets the quote REEL (the same video as YouTube), NOT the static
    # card (per user) — handled in the reel section below. The card image still goes
    # to Facebook (with hashtags) + Threads/X (no hashtags).
    img_targets = [p for p in targets if p != "instagram"]
    with_tags = [p for p in img_targets if p in tag_plats]
    no_tags = [p for p in img_targets if p not in tag_plats]  # Threads/X: no hashtags

    result: dict[str, Any] = {
        "kind": "quote_card", "quote": q, "theme": theme, "attribution": attribution,
        "photo": str(photo), "caption": caption, "card_path": str(card_path),
        "dry_run": dry_run,
    }
    if dry_run:
        log(f"DRY RUN — card to {img_targets} (hashtags on {with_tags}); "
            f"reel to IG+YouTube.")
        result["published"] = False
    else:
        from core import postforme
        media_url = postforme.upload_image(card_path.read_bytes(), content_type="image/png")
        posts = []
        if with_tags:
            cap = f"{caption}\n\n{tags}".strip() if tags else caption
            log(f"Publishing to {with_tags} (with hashtags)...")
            posts.append(postforme.create_post(
                caption=cap, social_accounts=CONFIG.account_ids(with_tags),
                media_urls=[media_url], scheduled_at=scheduled_at))
        if no_tags:
            log(f"Publishing to {no_tags} (no hashtags)...")
            posts.append(postforme.create_post(
                caption=caption, social_accounts=CONFIG.account_ids(no_tags),
                media_urls=[media_url], scheduled_at=scheduled_at))
        result["published"] = True
        result["postforme_result"] = posts
        for p in posts:
            log(f"Published. Post id: {p.get('id', '(see result.json)')}")

        # Reach-booster: also share the card to the FACEBOOK Page Story (reuse the
        # already-uploaded image). Best-effort — never sinks the main post.
        if qcfg.get("fb_stories", False) and "facebook" in img_targets:
            try:
                log("Sharing quote card to Facebook Story...")
                cap = f"{caption}\n\n{tags}".strip() if tags else caption
                result["fb_story_result"] = postforme.create_post(
                    caption=cap, social_accounts=CONFIG.account_ids(["facebook"]),
                    media_urls=[media_url], scheduled_at=scheduled_at,
                    platform_configurations={"facebook": {"placement": "stories"}})
                log("Quote card shared to Facebook Story.")
            except Exception as e:
                log(f"Facebook Story (quote) skipped ({e!r})")
                result["fb_story_error"] = repr(e)

    # The quote also goes out as a short, loop-friendly REEL (quote over spliced
    # gameplay b-roll) to YouTube AND Instagram (IG gets the reel instead of the
    # static card, per user). IG Reels like hashtags, so the reel caption carries
    # them when IG is a target.
    if qcfg.get("youtube_short", True) or "instagram" in targets:
        try:
            from agents import reel_ffmpeg
            yt_clips = _quote_short_clips(int(qcfg.get("short_clips", 4)))
            if yt_clips:
                text_png = quote.render_text_layer(q, run_dir / "text_layer.png",
                                                   logo=_reel_logo(), attribution=attribution)
                music_path, music_start = quote.pick_music(universe if story else None)
                vid = reel_ffmpeg.build_quote_short(
                    yt_clips, run_dir / "short.mp4", text_png,
                    music=music_path or _reel_music(), music_start=music_start,
                    fps=int(qcfg.get("short_fps", 60)),
                    total_seconds=float(qcfg.get("short_seconds", 10)),
                    per_clip_seconds=float(qcfg.get("short_per_clip", 3)))
                result["short_path"] = str(run_dir / "short.mp4")
                reel_targets = ((["youtube"] if qcfg.get("youtube_short", True) else [])
                                + (["instagram"] if "instagram" in targets else []))
                reel_caption = (f"{caption}\n\n{tags}".strip()
                                if tags and "instagram" in reel_targets else caption)
                if dry_run:
                    log(f"DRY RUN — built quote reel ({len(vid)//1024} KB) for "
                        f"{reel_targets}, not posting.")
                else:
                    rv = publisher.publish_video(
                        caption=reel_caption, video_bytes=vid, title=q[:90], short=True,
                        scheduled_at=scheduled_at, targets=reel_targets)
                    result["reel_result"] = rv
                    log(f"Quote reel ({'+'.join(reel_targets)}) post id: "
                        f"{rv.get('id', '(see result.json)')}")
            else:
                log("No footage clips for the quote reel — skipping IG/YouTube video.")
        except Exception as e:
            log(f"Quote reel skipped ({e!r})")

    _save(run_dir, result)
    return result


def run_threads_footage(
    dry_run: bool = False,
    scheduled_at: Optional[str] = None,
) -> dict[str, Any]:
    """Threads FOOTAGE post: a graded landscape (1920x1080) gameplay clip 'as is' +
    the circular KG corner logo, with the clip's HOOK as the caption. CFR 60fps.
    Posts to Threads only. Separate cadence from the caption-only Threads track."""
    tf = CONFIG.raw().get("threads_footage", {}) or {}
    if not tf.get("enabled", True):
        print("[threads-footage] disabled — skipping.", flush=True)
        return {"kind": "threads_footage", "published": False, "skipped": "disabled"}
    run_dir = OUTPUT_DIR / f"{_stamp()}_threads_footage"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[threads-footage] {m}", flush=True)

    games = reel_composer.list_games()
    if not games:
        return _skip(run_dir, {"kind": "threads_footage"}, "no_media")
    prefer = CONFIG.preferred_footage_games()   # honors a time-boxed prefer_override
    preferred = {k: v for k, v in games.items() if k in prefer} or games
    game = random.choice(list(preferred))
    # a RANDOM clip — deliberately does NOT touch the gameplay-reel used-clip ledger.
    from core import gh_release
    cands = reel_composer._candidates(game)
    clip = None
    if cands:
        _name, item = random.choice(cands)
        clip = gh_release.download(item, ROOT / (CONFIG.reels.get("footage", {}) or {}).get(
            "cache_dir", "reels/assets/footage/.cache"))
    if not clip:
        return _skip(run_dir, {"kind": "threads_footage", "game": game}, "no_media")
    from pathlib import Path
    clip = Path(clip)
    log(f"Game: {game} | clip: {clip.name}")

    log("Reviewing the clip to write the hook caption...")
    hook, _cap = content.hook_and_caption_from_video(clip, game, taglish=False)
    caption = hook  # horizontal (as-is) footage -> hook + #GamingThreads (added by publisher)
    (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
    log(f"Hook: {hook}")

    log("Rendering landscape (1920x1080, graded, +logo, CFR 60)...")
    out = run_dir / "threads_footage.mp4"
    video_bytes = reel_ffmpeg.build_threads_landscape(
        clip, out, logo=_reel_logo(),
        fps=int(tf.get("fps", 60)),
        target_seconds=float(tf.get("seconds", 60)),
        music=_reel_music())

    result: dict[str, Any] = {
        "kind": "threads_footage", "game": game, "hook": hook,
        "caption": caption, "path": str(out), "dry_run": dry_run}
    if dry_run:
        log("DRY RUN — not posting.")
        result["published"] = False
    else:
        log("Publishing to Threads...")
        result["postforme_result"] = publisher.run_threads_video(
            caption=caption, video_bytes=video_bytes, scheduled_at=scheduled_at)
        result["published"] = True

        # Also post the SAME footage to INSTAGRAM, rotated 90° CW (bottom -> left),
        # with the FULL gameplay-reel hashtags (per user).
        if tf.get("instagram", True):
            try:
                log("Rendering rotated (90° CW) version for Instagram...")
                ig_out = run_dir / "ig_rotated.mp4"
                ig_bytes = reel_ffmpeg.build_footage_rotated(
                    clip, ig_out, logo=_reel_logo(),
                    fps=int(tf.get("fps", 60)),
                    target_seconds=float(tf.get("seconds", 60)),
                    music=_reel_music())
                ig_tags = content._reel_hashtags({"game": game})  # full reel hashtags
                ig_caption = f"{hook}\n\n{' '.join(ig_tags)}".strip() if ig_tags else hook
                (run_dir / "ig_caption.txt").write_text(ig_caption, encoding="utf-8")
                log(f"Publishing rotated footage to Instagram ({' '.join(ig_tags)})...")
                result["ig_result"] = publisher.publish_video(
                    ig_caption, ig_bytes, short=True, targets=["instagram"],
                    scheduled_at=scheduled_at)
            except Exception as e:  # IG is a bonus — never sink the Threads post
                log(f"Instagram rotated post skipped ({e!r})")
                result["ig_error"] = repr(e)

        # Reach-booster: also share the footage to the FACEBOOK Page Story (as-is
        # landscape -> letterboxed in the vertical Story). Best-effort.
        if tf.get("fb_stories", False) and "facebook" in (tf.get("post_to", []) or []):
            try:
                log("Reposting footage to Facebook Story...")
                result["fb_story_result"] = publisher.run_fb_story(
                    caption=caption, media_bytes=video_bytes, is_video=True,
                    scheduled_at=scheduled_at)
                log("Footage reposted to Facebook Story.")
            except Exception as e:  # ephemeral bonus reach — never fatal
                log(f"Facebook Story (footage) skipped ({e!r})")
                result["fb_story_error"] = repr(e)
    _save(run_dir, result)
    return result


def _video_bg_frames(video, n: int = 6) -> list:
    """Candidate BACKGROUND frames pulled from the actual video (so the thumbnail is
    relevant to the clip by construction). HDR->SDR tonemapped; returned best-first
    (well-exposed + high-detail; dark/flat/menu frames sink to the bottom)."""
    from core import ffmpeg as _ff
    dur = _ff.duration(video) or 60.0
    tmp = OUTPUT_DIR / f"{_stamp()}_bgframes"
    tmp.mkdir(parents=True, exist_ok=True)
    tm = ("zscale=t=linear:npl=100,tonemap=hable,"
          "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p")
    frames = []
    for i in range(max(1, n)):
        t = dur * (0.1 + 0.8 * (i / max(1, n - 1)))    # spread across the middle 80%
        p = tmp / f"f{i:02d}.jpg"
        rc, _ = _ff.run(["-ss", f"{t:.1f}", "-i", str(video), "-map", "0:v:0",
                         "-vf", tm, "-frames:v", "1", str(p)], timeout=120)
        if rc == 0 and p.exists():
            frames.append(p)
    try:
        import numpy as np
        from PIL import Image
        scored = []
        for p in frames:
            a = np.asarray(Image.open(p).convert("RGB").resize((160, 90)), dtype=np.float32)
            mean, std = float(a.mean()), float(a.std())
            sat = float((a.max(axis=2) - a.min(axis=2)).mean())
            expo = 1.0 - abs(mean - 120.0) / 120.0     # penalise too dark / blown out
            s = 0.5 * max(0.0, expo) + 0.3 * min(std, 70.0) / 70.0 + 0.2 * min(sat, 90.0) / 90.0
            scored.append((s, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored]
    except Exception:
        return frames


def _part_number(files) -> Optional[int]:
    """The Part number when this is a SINGLE-part upload (e.g. 'Halo - Part 1.mp4');
    None for a multi-part concat (= the full game)."""
    if len(files) != 1:
        return None
    import os
    import re as _r
    m = _r.search(r"part[\s_\-]*([0-9]+)", os.path.basename(str(files[0])), _r.IGNORECASE)
    return int(m.group(1)) if m else None


def _part_meta(gname: str, n: int, yl: dict) -> dict[str, Any]:
    """Deterministic YouTube metadata for a single-PART walkthrough upload — the
    proven 'Part N ... (FULL GAME)' format the big full-game channels use."""
    return {
        "title": (f"{gname} Gameplay Walkthrough Part {n} "
                  f"[4K 60FPS HDR] - No Commentary (FULL GAME)")[:100],
        "thumbnail": f"PART {n}",
        "description": (f"{gname} Gameplay Walkthrough Part {n} in 4K 60fps HDR, no "
                        f"commentary. This series will cover the full {gname} playthrough "
                        f"from start to finish — subscribe for the next parts!"),
        "tags": (list(yl.get("default_tags", [])) +
                 [gname.lower(), f"{gname.lower()} part {n}", "walkthrough",
                  "gameplay walkthrough", "no commentary", "playthrough", "4k", "hdr",
                  "60fps"])[:15],
    }


def _resolve_characters(game: Optional[str], names) -> list[str]:
    """Map requested character NAMES (e.g. ['aerith','tifa']) to their best transparent
    render file in reels/assets/game-character/<game>/. Prefers cutout renders
    (render > bust > promo), Remake over Rebirth, and PNG/WEBP (transparent) over AVIF."""
    if not game or not names:
        return []
    base = (ROOT / (CONFIG.reels.get("thumbnail", {}) or {}).get(
        "character_dir", "reels/assets/game-character") / game)
    if not base.is_dir():
        return []
    exts = {".png", ".webp", ".avif"}
    files = [f for f in base.iterdir() if f.is_file() and f.suffix.lower() in exts]

    def score(f):
        n = f.name.lower()
        return ((4 if "render" in n else 0) + (3 if "bust" in n else 0)
                + (2 if "promo" in n else 0) + (2 if "remake" in n else 0)
                + (1 if f.suffix.lower() in (".png", ".webp") else -1))
    out: list[str] = []
    for name in names:
        toks = [t for t in str(name).lower().replace("_", " ").split() if t]
        key = str(name).lower().replace(" ", "").replace("_", "")
        cands = [f for f in files
                 if all(t in f.name.lower() for t in toks)
                 or key in f.name.lower().replace(" ", "").replace("_", "")]
        cands.sort(key=score, reverse=True)
        if cands:
            out.append(str(cands[0]))
    return out


def run_youtube_longform(
    parts,
    game: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    thumb_text: Optional[str] = None,
    tags: Optional[list[str]] = None,
    thumb_image: Optional[str] = None,
    publish_at: Optional[str] = None,
    privacy: Optional[str] = None,
    reuse_concat: Optional[str] = None,
    thumb_characters: Optional[Sequence[str]] = None,  # names -> a cast-lineup thumbnail
    dry_run: bool = False,
) -> dict[str, Any]:
    """LOCAL long-form YouTube: concat the labelled 4K/60 HDR10 PART files into one
    full-game video (+ circular KG logo, HDR10 preserved to the Premiere preset),
    generate a clickbait thumbnail, and upload (scheduled if publish_at). `parts`
    is a folder OR a list of files. HEAVY — run on your own machine, not CI."""
    from pathlib import Path

    from agents import thumbnail

    yl = CONFIG.youtube_longform or {}
    if not yl.get("enabled", True):
        print("[youtube] disabled — skipping.", flush=True)
        return {"kind": "youtube_longform", "published": False, "skipped": "disabled"}

    src = Path(str(parts))
    if src.is_dir():
        files = sorted([f for f in src.iterdir()
                        if f.suffix.lower() in (".mp4", ".mov", ".mkv", ".m4v")])
    else:
        files = [Path(x) for x in (parts if isinstance(parts, (list, tuple)) else [parts])]
    files = [f for f in files if f.exists()]
    if not files:
        raise ValueError(f"no part files found at: {parts}")

    run_dir = OUTPUT_DIR / f"{_stamp()}_youtube_longform"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[youtube] {m}", flush=True)
    log(f"{len(files)} parts | game: {game or '(pass --game for the thumbnail image)'}")

    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or (game or "this game")
    # Metadata: explicit overrides win. For specific CLIPS the agent supplies all
    # of title/description/thumb_text (from reviewing the clip), so the generic
    # full-game AI writer is skipped entirely; otherwise it fills the gaps.
    part_n = _part_number(files)
    if title and description and thumb_text:
        meta = {"title": title, "description": description, "thumbnail": thumb_text,
                "tags": tags or list(yl.get("default_tags", []))}
    else:
        # Single PART upload -> 'Part N' title + 'PART N' thumbnail; else full-game.
        meta = (_part_meta(gname, part_n, yl) if part_n is not None
                else content.youtube_longform_meta(game or "", gname))
        if title:
            meta["title"] = title
        if description:
            meta["description"] = description
        if thumb_text:
            meta["thumbnail"] = thumb_text
        if tags:
            meta["tags"] = tags
    title = meta["title"]
    if part_n is not None:
        log(f"Single-part upload -> Part {part_n}")
    log(f"Title: {title}")

    # REUSE an already-built concat (e.g. a prior run whose upload failed) — skip the
    # multi-hour re-encode/stream-copy entirely and upload the existing file as-is.
    reuse = Path(reuse_concat) if reuse_concat else None
    out = reuse if (reuse and reuse.exists()) else run_dir / "fullgame.mp4"
    use_logo = bool(yl.get("logo", False))   # YouTube's own watermark covers it -> default off
    lt = yl.get("lower_third")
    lt_path = None
    if lt:
        lt_path = Path(lt) if Path(lt).is_absolute() else (ROOT / lt)
        lt_path = lt_path if lt_path.exists() else None
    if reuse and reuse.exists():
        log(f"Reusing existing concat: {out} ({out.stat().st_size / 1e9:.2f} GB) — skipping build.")
    else:
        log(f"Rendering full-game (concat + HDR10 encode"
            f"{' + logo' if use_logo else ''}"
            f"{' + lower-third' if lt_path else ''}) — this takes a while...")
        reel_ffmpeg.build_longform_hdr(
            files, out,
            logo=_reel_logo() if use_logo else None,
            lower_third=lt_path,
            lower_third_start=float(yl.get("lower_third_start", 7.0)),
            lower_third_fade=float(yl.get("lower_third_fade", 1.0)),
            lower_third_scale=float(yl.get("lower_third_scale", 1.0)),
            lower_third_pos=str(yl.get("lower_third_pos", "full")),
            graphics_pct=float(yl.get("graphics_pct", 0.58)),
            bitrate=str(yl.get("bitrate", "63M")),
            logo_size=int(yl.get("logo_size", 480)),
            audio_lufs=yl.get("audio_lufs", -14.0),
            copy=bool(yl.get("stream_copy", False)))

    log("Generating thumbnail variants...")
    import re as _re

    from core import ffmpeg as _ff
    slug = (_re.sub(r"[^a-z0-9]+", "-", (title or game or "video").lower()).strip("-") or "video")[:60]
    tdir = ROOT / "thumbnails" / (game or "misc") / slug
    tcfg = CONFIG.reels.get("thumbnail", {}) or {}
    pcrop = float(tcfg.get("pool_crop_bottom", 0.045))
    nvar = max(1, int(tcfg.get("variants", 3)))
    # All-RED box (MKIceAndFire) for walkthrough content — the Part N clips AND the
    # full-game concat. GOLD only for a single titled STORY-MOMENT clip (e.g. "The
    # Opening"): part-less single file.
    story = part_n is None and len(files) == 1
    box = (255, 196, 0) if story else (214, 18, 18)   # gold = story clip; red = part / full game
    txt = meta["thumbnail"]
    glogo = _game_logo(game) if game else None       # official game logo (top-left) if we have one
    gl = str(glogo) if glogo else None
    if glogo:
        log(f"Thumbnail game logo: {Path(glogo).name}")
    # Background candidates, priority: explicit --thumb-image > FRAMES FROM THE ACTUAL
    # VIDEO (relevant by construction — for Part clips + story-moment clips) > curated
    # cloud stills (full-game concat) > one tonemapped footage frame. (img, crop, sharpen)
    use_clip_bg = (part_n is not None or story) and bool(tcfg.get("clip_bg_from_video", True))
    bgs: list = []
    if thumb_image:
        bgs.append((str(thumb_image), 0.0, 0.0))
    if use_clip_bg:
        vf = _video_bg_frames(out, nvar + 2)
        if vf:
            log(f"Backgrounds from the clip's own frames ({len(vf)} candidates, relevant by construction).")
            bgs += [(str(f), 0.0, 0.5) for f in vf]
    if len(bgs) < nvar and game:
        bgs += [(pi, pcrop, 0.0) for pi in _pool_samples(game, nvar)]   # curated cloud stills
    if not bgs:                                       # fallback: one tonemapped footage frame
        ffimg = run_dir / "thumb_frame.jpg"
        _tm = ("zscale=t=linear:npl=100,tonemap=hable,"
               "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p")
        _ff.run(["-ss", f"{max(1.0, (_ff.duration(out) or 60) * 0.4):.1f}", "-i", str(out),
                 "-map", "0:v:0", "-vf", _tm, "-frames:v", "1", str(ffimg)], timeout=120)
        if ffimg.exists():
            bgs.append((str(ffimg), 0.0, 0.6))

    # PROMINENT FOREGROUND CHARACTER (#1 CTR lever). Priority: a hand-curated hero
    # render (cleanest) > else AUTO-CUT the best subject out of the candidate stills
    # with rembg (core/cutout.py) so every game gets a hero with no manual curation.
    # Explicit CAST LINEUP (thumb_characters=['aerith','tifa']) wins — resolves each name
    # to its best render + composites them side by side; else the single-hero logic below.
    multi_chars = _resolve_characters(game, thumb_characters) if thumb_characters else []
    if multi_chars:
        log(f"Cast lineup thumbnail: {[Path(c).name for c in multi_chars]}")
    curated = _best_curated_character(game) if (game and not multi_chars) else None
    char_png = str(curated) if curated else None
    cut_idx = None    # which bg frame the auto-cut came from (so we don't reuse it as its own backdrop)
    if multi_chars:
        pass                                          # explicit lineup; skip single-hero cutout
    elif char_png:
        log(f"Curated character render: {Path(char_png).name} — compositing in the foreground.")
    elif bool(tcfg.get("cutout_auto", True)) and bgs:
        from core import cutout as _cut
        if _cut.available():
            cp = _cut.best_cutout([b[0] for b in bgs], run_dir / "cutout",
                                  model=str(tcfg.get("cutout_model", "u2net_human_seg")),
                                  fallback_model=str(tcfg.get("cutout_fallback_model",
                                                              "isnet-general-use")),
                                  limit=nvar + 2)
            if cp:
                char_png = str(cp)
                try: cut_idx = int(Path(cp).stem.split("_")[1])
                except Exception: cut_idx = None
                log(f"Auto-cut hero from the pool ({Path(cp).name}) — no curated render needed.")
        if not char_png:
            log("No curated render + rembg not installed (pip install -r requirements-cutout.txt) "
                "— using the subject-in-the-background look.")
    else:
        log("No character render for this game — subject-in-the-background look.")

    # Don't sit the sharp cutout on top of its own (darkened) source frame — push that
    # frame to the back of the backdrop list so it's only used if needed to fill nvar.
    bg_order = list(bgs)
    if char_png and cut_idx is not None and 0 <= cut_idx < len(bgs) and len(bgs) > 1:
        bg_order = [b for k, b in enumerate(bgs) if k != cut_idx] + [bgs[cut_idx]]
    specs: list[dict] = [
        dict(text=txt, image=img, box_fill=box, crop_bottom=cb, sharpen=sh,
             game_logo=gl, character=char_png, characters=(multi_chars or None))
        for img, cb, sh in bg_order[:nvar]] or [
        dict(text=txt, image=None, box_fill=box, game_logo=gl, character=char_png,
             characters=(multi_chars or None))]

    thumb = None
    try:
        variants = thumbnail.build_variants(tdir, specs[:nvar])
        # INSPECTOR: prefer the Claude-Haiku VISION judge (relevance + scroll-stopping)
        # when enabled + the key is funded; else the free heuristic. Publish the best.
        vcfg = bool(tcfg.get("vision_judge", False))
        vmodel = str(tcfg.get("vision_model", "claude-haiku-4-5"))
        vopenai = str(tcfg.get("vision_openai_model", "gpt-4o-mini"))
        best, how = -1.0, "heuristic"
        for i, v in enumerate(variants):
            vj = None
            if vcfg:
                from core import vision
                vj = vision.judge_thumbnail(v, topic=title, model=vmodel, openai_model=vopenai)
            if vj is not None:
                how = "vision"
                log(f"  {v.name}: vision rel={vj['relevant']:.0f}/10 ss={vj['scroll_stopping']:.0f}/10 "
                    f"-> {vj['score']} | {vj['verdict']}"
                    + (" | " + "; ".join(vj["issues"]) if vj["issues"] else ""))
                score = vj["score"]
            else:
                q = thumbnail.inspect_thumbnail(
                    v, has_character=bool(specs[i].get("character")), game_logo=gl)
                log(f"  {v.name}: heuristic {q['score']} "
                    + ("OK" if q["ok"] else "— " + "; ".join(q["issues"])))
                score = q["score"]
            if score > best:
                best, thumb = score, v
        if thumb:
            log(f"{len(variants)} variant(s) -> {tdir} (live: {thumb.name}, {how} score {best})")
    except Exception as e:
        log(f"thumbnail variants failed ({e!r}) — no custom thumbnail")

    result: dict[str, Any] = {
        "kind": "youtube_longform", "game": game, "title": title,
        "video": str(out), "parts": [f.name for f in files], "dry_run": dry_run}
    if dry_run:
        log(f"DRY RUN — rendered {out.name} ({out.stat().st_size / 1e9:.2f} GB); not uploading.")
        result["published"] = False
        _save(run_dir, result)
        return result

    from core import youtube
    # privacy: CLI override (--public / --privacy) wins, else the config default.
    # NOTE: publish_at forces a scheduled (private-until-then) upload that then goes
    # PUBLIC at that time, so it takes precedence over an immediate privacy choice.
    priv = str(privacy or yl.get("privacy", "private")).lower()
    log(f"Uploading to YouTube (privacy={priv}"
        f"{', scheduled ' + publish_at if publish_at else ''})...")
    api = youtube.upload_video(
        out, title=title, description=meta["description"], tags=meta["tags"],
        privacy=priv, publish_at=publish_at,
        category_id=str(yl.get("category_id", "20")),
        made_for_kids=bool(yl.get("made_for_kids", False)),
        thumbnail=str(thumb) if thumb else None,
        chunk_mb=int(yl.get("upload_chunk_mb", 512)))   # big chunks -> fast upload on fast lines
    result["published"] = True
    result["video_id"] = api.get("id")
    result["url"] = f"https://youtu.be/{api.get('id', '')}"
    log(f"Done: {result['url']}")
    _save(run_dir, result)
    return result


# ---- 4K/60 HDR YouTube Shorts track -------------------------------------------------
# LOCAL, like the long-form pillar: nvenc (RTX GPU) + multi-GB HDR footage can't run in
# CI. A tiny per-game ledger tracks which 4K clips have been used for a Short (so we
# post fresh footage first) AND a monotonic post counter (so classic<->triptych keeps
# alternating even after the pool is exhausted and clips start getting reused).

_SHORT_VID_EXTS = {".mp4", ".mov", ".mkv", ".m4v"}


def _short_ledger_path(game: str):
    from pathlib import Path
    d = ROOT / "reels" / "assets" / ".shorts_ledgers"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{game}.json"


def _short_ledger(game: str) -> dict[str, Any]:
    """Read the per-GAME Shorts ledger: {"used": [names...], "posts": N}. One ledger per
    game, at a stable location (not inside the auto-archived footage folders), shared by
    every layout (classic/triptych/fill) so freshness + rotation hold across pools."""
    try:
        d = json.loads(_short_ledger_path(game).read_text(encoding="utf-8"))
        return {"used": list(d.get("used", [])), "posts": int(d.get("posts", 0))}
    except Exception:
        return {"used": [], "posts": 0}


def _short_post_count(game: str) -> int:
    """Monotonic count of Shorts posted for this game (drives layout alternation)."""
    return _short_ledger(game)["posts"]


def _short_write_ledger(game: str, d: dict) -> None:
    try:
        _short_ledger_path(game).write_text(
            json.dumps({"used": d["used"], "posts": d["posts"]}, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_short_used(game: str, clip_id: str) -> None:
    """Mark a clip used (freshness) AND bump the game's Short post counter."""
    d = _short_ledger(game)
    if clip_id and clip_id not in d["used"]:
        d["used"].append(clip_id)
    d["posts"] = int(d["posts"]) + 1
    _short_write_ledger(game, d)


def _pick_short_clip(dirs, game: str):
    """Fresh-first pick across an ORDERED list of pool dirs for `game`: return a clip not
    yet used for a Short, preferring earlier dirs (so long-clips win over the full-game
    fallback). When every clip has been used, reset + reuse the least-recently-used.
    Returns (path, name)."""
    from pathlib import Path
    dirs = [Path(d) for d in ([dirs] if isinstance(dirs, (str, Path)) else dirs)]
    all_clips: list = []
    for d in dirs:
        if d.exists():
            all_clips += sorted(p for p in d.iterdir()
                                if p.is_file() and p.suffix.lower() in _SHORT_VID_EXTS)
    if not all_clips:
        return None, None
    used = _short_ledger(game)["used"]
    for d in dirs:                                   # priority: earliest dir with a fresh clip
        fresh = [c for c in all_clips if c.parent == d and c.name not in used]
        if fresh:
            choice = random.choice(fresh)
            return choice, choice.name
    order = {name: i for i, name in enumerate(used)}  # all used -> least-recently-used
    choice = sorted(all_clips, key=lambda c: order.get(c.name, -1))[0]
    return choice, choice.name


def run_youtube_short(
    game: Optional[str] = None,
    clip: Optional[str] = None,
    layout: Optional[str] = None,
    privacy: Optional[str] = None,
    publish_at: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """LOCAL 4K/60 HDR YouTube Short: pick a fresh 4K HDR clip from the pool, render
    the CLASSIC or TRIPTYCH HDR reel (alternating per post) matching the long-form's
    HDR10 (Rec.2020 PQ) + loudnorm export, and upload as a Short via the Data API.
    HEAVY (nvenc + multi-GB HDR) — run on your own machine, not CI."""
    from pathlib import Path

    from core import youtube

    ys = CONFIG.youtube_shorts or {}
    if not ys.get("enabled", True):
        print("[yt-short] disabled (youtube_shorts.enabled=false) — skipping.", flush=True)
        return {"kind": "youtube_short", "published": False, "skipped": "disabled"}

    game = game or str(ys.get("game", "ff7remake"))
    fps = int(ys.get("fps", 60))
    rw, rh = int(ys.get("width", 2160)), int(ys.get("height", 3840))
    run_dir = OUTPUT_DIR / f"{_stamp()}_youtube_short"
    run_dir.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[yt-short] {m}", flush=True)

    # 1) layout first: classic <-> triptych <-> fill on the game's Short post counter.
    base = ROOT / str(ys.get("footage_dir", "reels/assets/footage-4k"))
    layouts = [str(x) for x in (ys.get("layouts") or ["classic", "triptych"])]
    n = _short_post_count(game)
    layout = (layout or layouts[n % len(layouts)]).lower()
    vcfg = (CONFIG.reels.get("gameplay", {}) or {}).get("vertical", {}) or {}
    # classic/triptych footage = discrete long-form shorter clips (each -> one Short),
    # with the full-game recordings as a local-only fallback (priority order in config).
    clip_dirs = [ROOT / str(d) / game for d in (ys.get("clip_source_dirs")
                 or ["reels/assets/4k-hdr-long-clips", "reels/assets/longform-fullgame"])]

    # 2) fresh-first clip from the layout's pool. FILL pulls raw 4K LANDSCAPE from the
    # dedicated '<game>-vertical' folder; classic/triptych use the long-clip pool(s).
    if layout == "fill":
        vkey = f"{game}{vcfg.get('key_suffix', '-vertical')}"
        pool_dirs = [base / vkey]
        if not clip:
            try:                                        # pull the fill pool back if freed
                from tools import archive_4k
                archive_4k.ensure_vertical_local(vkey)
            except Exception:
                pass
    else:
        pool_dirs = clip_dirs
        if not clip:
            try:                                        # pull the long-clip pool if freed
                from tools import archive_4k
                archive_4k.ensure_source_local(game)
            except Exception:
                pass
    if clip:
        clip_path, clip_id = Path(clip), Path(clip).name
    else:
        clip_path, clip_id = _pick_short_clip(pool_dirs, game)
    if layout == "fill" and (not clip_path or not Path(clip_path).exists()):
        log("No 4K vertical clip — falling back to the classic/long-clip pool.")
        layout, pool_dirs = "classic", clip_dirs
        clip_path, clip_id = _pick_short_clip(pool_dirs, game)
    if not clip_path or not Path(clip_path).exists():
        log(f"No 4K HDR clip available for {game} — skipping.")
        return _skip(run_dir, {"kind": "youtube_short", "game": game}, "no_media")
    log(f"Clip (fresh-first): {clip_id}")

    # Triptych: ALTERNATE the game-art files deterministically (main <-> art 1 <-> ...)
    # across successive triptychs, keyed off the post counter, per user.
    art = _game_art(game, alt=n // len(layouts)) if layout == "triptych" else None
    if layout == "triptych" and not art:
        log("No game art for this game — using the classic layout this post.")
        layout = "classic"

    # 3) caption. FILL = generic GAME caption (pure footage, no on-screen hook); the
    # composited layouts review the clip for a lore-grounded hook.
    reel_path = run_dir / "short.mp4"
    gcfg = CONFIG.reels.get("gameplay", {}) or {}
    if layout == "fill":
        caption = content.generic_game_caption(game)
        hook = (caption.splitlines()[0].strip() if caption else game)
        target = float(vcfg.get("max_seconds", 180))     # FULL clip up to 3 min
        (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
        log(f"Game: {game} | FILL vertical | clip {clip_id}")
        log(f"Rendering 4K HDR FULL-BLEED vertical (full clip, <={int(target)}s)...")
        reel_ffmpeg.build_gameplay_fill(clip_path, reel_path, fps=fps, w=rw, h=rh,
                                        target_seconds=target, hdr=True)
    else:
        log("Reviewing the clip to write the on-screen hook + caption...")
        hook, caption = content.hook_and_caption_from_video(clip_path, game, taglish=False)
        (run_dir / "caption.txt").write_text(caption, encoding="utf-8")
        choices = [float(x) for x in (ys.get("target_seconds_choices") or [])]
        target = random.choice(choices) if choices else float(ys.get("target_seconds", 35))
        log(f"Game: {game} | Layout: {layout} | Hook: {hook}")
        if layout == "triptych":
            top = _game_screenshot(game)
            log(f"Rendering 4K HDR triptych (art: {art.name}, "
                f"top: {'library' if top else 'clip-frame'}, <={int(target)}s)...")
            reel_ffmpeg.build_gameplay_triptych(
                clip_path, reel_path, hook=hook, game_art=art, top_image=top,
                logo=_reel_logo(), fps=fps, w=rw, h=rh, target_seconds=target,
                music=_reel_music(), anim_logo=_anim_logo(), hdr=True)
        else:
            log(f"Rendering 4K HDR classic (<={int(target)}s)...")
            reel_ffmpeg.build_gameplay(
                clip_path, reel_path, hook=hook, logo=_reel_logo(), fps=fps, w=rw, h=rh,
                foot_h=int(gcfg.get("footage_height", 1320)) * 2,
                top_band=int(gcfg.get("top_band", 360)) * 2,
                target_seconds=target, music=_reel_music(), anim_logo=_anim_logo(),
                game_logo=_game_logo(game), hdr=True)
    actual = ffmpeg.duration(reel_path) or target
    log(f"Rendered ({layout}) -> {reel_path} ({actual:.0f}s)")

    # 5) upload as a Short via the YouTube Data API (#Shorts in title + description).
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
    title = f"{hook} - {gname.upper()} [4K HDR] #Shorts"[:100]
    if layout == "fill":                         # caption already carries its hashtags
        desc = f"{caption}\n\n#Shorts".strip()
    else:
        gtags = " ".join(content._reel_hashtags({"game": game}))
        desc = f"{caption}\n\n#Shorts {gtags}".strip()
    result: dict[str, Any] = {
        "kind": "youtube_short", "game": game, "clip_id": clip_id, "layout": layout,
        "hook": hook, "caption": caption, "target_seconds": target,
        "actual_seconds": round(actual, 1), "reel_path": str(reel_path), "dry_run": dry_run}
    if dry_run:
        log("DRY RUN — skipping upload.")
        result["published"] = False
        _save(run_dir, result)
        return result

    # GAME-AWARE tags (don't tag e.g. SM2 with the static FF7 tag list). Derive from the
    # game's own hashtags (minus '#') + a generic gaming base; fall back to config tags.
    ghash = [str(h).lstrip("#") for h in
             (CONFIG.reels.get("game_hashtags", {}) or {}).get(game, []) if str(h).strip()]
    generic = ["gaming", "4K", "HDR", "60fps", "PS5"]
    if ghash:
        seen, yt_tags = set(), []
        for t in ghash + generic:
            if t.lower() not in seen:
                seen.add(t.lower()); yt_tags.append(t)
    else:
        yt_tags = [str(t) for t in (ys.get("tags") or [])]

    priv = str(privacy or ys.get("privacy", "public")).lower()
    log(f"Uploading Short via the YouTube Data API (privacy={priv}"
        f"{', scheduled ' + publish_at if publish_at else ''})...")
    api = youtube.upload_video(
        str(reel_path), title=title, description=desc,
        tags=yt_tags,
        privacy=priv, publish_at=publish_at,
        category_id=str(ys.get("category_id", "20")),
        made_for_kids=bool(ys.get("made_for_kids", False)))
    vid = api.get("id", "")
    result["published"] = bool(vid)
    result["video_id"] = vid
    result["url"] = f"https://youtu.be/{vid}" if vid else ""
    log(f"Done ({layout}): {result['url']}")
    if vid and not clip:                     # only advance the ledger for a real pool pick
        _mark_short_used(game, clip_id)      # one game ledger: freshness + rotation counter
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
