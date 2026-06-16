"""ffmpeg reel composer — gameplay-only + commentary reels (Gameranx-style).

Layout (9:16, black canvas):
  - gameplay footage letterboxed in the middle (scaled to fit, black bars),
  - a bold HOOK / TITLE caption in a black bar near the top,
  - (commentary only) time-synced SUBTITLE captions along the bottom,
  - the KG channel logo in the top-right corner.

Two builders:
  build_gameplay()  -> one standalone clip + static hook, KEEPS the game audio,
                       no voiceover. Short Reel (<=90s).
  build_commentary()-> several clips as b-roll under a Taglish voiceover with
                       burned subtitles. Game audio dropped; VO + ducked music.
                       Short Reel OR long video post (up to ~15 min).

Renders are ffmpeg-only (no headless Chrome) so they are fast at any length and
safe for CI. Fails by raising ReelFfmpegError; the orchestrator logs + skips.
"""
from __future__ import annotations

import random
import tempfile
from pathlib import Path
from typing import Any, Optional

from core import ffmpeg
from core.config import CONFIG, ROOT


class ReelFfmpegError(RuntimeError):
    pass


# ---------------------------------------------------------------- ASS captions

def _caption_cfg() -> dict[str, Any]:
    return (CONFIG.reels.get("caption", {}) or {})


def _grade_filter() -> str:
    """A tasteful colour/clarity grade for the gameplay footage so it looks its
    crisp best (subtle contrast + saturation + sharpening). Config-driven via
    reels.grade; returns a comma-terminated filter snippet, or '' when disabled.
    """
    g = CONFIG.reels.get("grade", {}) or {}
    if not g.get("enabled", True):
        return ""
    contrast = float(g.get("contrast", 1.06))
    brightness = float(g.get("brightness", 0.0))
    saturation = float(g.get("saturation", 1.12))
    gamma = float(g.get("gamma", 1.0))
    sharpen = float(g.get("sharpen", 0.8))
    parts = [
        f"eq=contrast={contrast}:brightness={brightness}:"
        f"saturation={saturation}:gamma={gamma}"
    ]
    if sharpen > 0:
        # luma-only unsharp: crisp edges without amplifying chroma noise.
        parts.append(f"unsharp=5:5:{sharpen}:5:5:0.0")
    if float(g.get("denoise", 0)) > 0:
        d = float(g.get("denoise"))
        parts.insert(0, f"hqdn3d={d}:{d}:6:6")
    return ",".join(parts) + ","


def _ass_header(w: int, h: int) -> str:
    cap = _caption_cfg()
    font = str(cap.get("font", "DejaVu Sans"))
    hook_size = int(cap.get("hook_size", 64))
    sub_size = int(cap.get("sub_size", 52))
    # Distance of the top hook bar from the top edge. ~250 sits a 2-line caption
    # centred in the top third of the 1920px frame.
    hook_mv = int(cap.get("hook_margin_v", 250))
    # Commentary subtitles sit in the footage lower-third but ABOVE the animated
    # logo lower-third (which plays at the bottom early on), so they never collide.
    sub_mv = int(cap.get("sub_margin_v", 430))
    # ASS colours are &HAABBGGRR. White text, black box/outline.
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        # Hook: top-centre white caps. Outline + drop-shadow (BorderStyle 1), NOT a
        # filled box — the black top band is already the backdrop, and a box would
        # bleed its shadow onto the footage below. Outline keeps it readable on the
        # rare line that dips a touch past the band onto the gameplay.
        f"Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H00000000,-1,0,0,0,100,100,0,0,1,7,4,8,90,90,{hook_mv},1\n"
        # Sub: bottom-centre, white text with a thick black outline (Gameranx).
        f"Style: Sub,{font},{sub_size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,120,120,{sub_mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )


def build_ass(
    out_path: Path,
    w: int,
    h: int,
    hook: Optional[str] = None,
    hook_end: float = 0.0,
    subtitles: Optional[list[dict[str, Any]]] = None,
) -> Path:
    """Write an ASS subtitle file: a persistent hook + timed subtitle events.

    hook        -> top caption text (shown 0 .. hook_end seconds).
    subtitles   -> [{start, end, text}, ...] bottom captions (seconds).
    """
    lines = [_ass_header(w, h)]
    if hook:
        lines.append(
            f"Dialogue: 0,{ffmpeg.ass_time(0)},{ffmpeg.ass_time(max(1.0, hook_end))},"
            f"Hook,,0,0,0,,{ffmpeg.ass_escape(hook.upper())}\n"
        )
    for s in subtitles or []:
        lines.append(
            f"Dialogue: 0,{ffmpeg.ass_time(s['start'])},{ffmpeg.ass_time(s['end'])},"
            f"Sub,,0,0,0,,{ffmpeg.ass_escape(str(s['text']))}\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def _ass_path_for_filter(p: Path) -> str:
    """Escape an ASS file path for use inside an ffmpeg filtergraph."""
    s = str(p).replace("\\", "/")
    # Escape the Windows drive colon for the filter parser (Linux paths unaffected).
    s = s.replace(":", "\\:")
    return s


# ------------------------------------------------------------------- builders

def _norm_chain(idx: int, w: int, h: int, fps: int, label: str) -> str:
    """Per-clip: scale to fit, letterbox-pad to WxH, square pixels, fixed fps."""
    return (
        f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}[{label}]"
    )


def _crop_chain(idx: int, w: int, h: int, fps: int, label: str) -> str:
    """Per-clip: scale to COVER WxH then centre-crop to fill (no black bars)."""
    return (
        f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,fps={fps}[{label}]"
    )


def _brand_logo(src: Optional[Path], out: Path) -> Optional[Path]:
    """Crop the brand logo to a CIRCLE + apply opacity (top-right overlay).

    Done in Pillow (robust) rather than an ffmpeg circle-mask. Returns the
    circular PNG path, or the raw src on failure, or None if no logo.
    """
    if not src or not Path(src).exists():
        return None
    try:
        from PIL import Image, ImageChops, ImageDraw
        size = int(CONFIG.reels.get("brand_logo_size", 140))
        opacity = max(0.0, min(1.0, float(CONFIG.reels.get("brand_logo_opacity", 0.6))))
        im = Image.open(src).convert("RGBA")
        w, h = im.size
        s = min(w, h)  # centre-crop to a square first (no distortion)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        im = im.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        a = ImageChops.multiply(im.getchannel("A"), mask)
        a = a.point(lambda v: int(v * opacity))
        im.putalpha(a)
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out)
        return out
    except Exception as e:
        print(f"[reel_ffmpeg] circular logo failed ({e!r}); using raw logo.", flush=True)
        return Path(src)


def build_gameplay(
    clip: Path,
    out_path: Path,
    hook: str,
    logo: Optional[Path] = None,
    fps: int = 60,
    w: int = 1080,
    h: int = 1920,
    foot_h: int = 1320,
    top_band: Optional[int] = None,
    target_seconds: float = 75.0,
    music: Optional[Path] = None,
    anim_logo: Optional[tuple] = None,
    fill: bool = True,
) -> bytes:
    """Single standalone gameplay clip in a w x h frame, with the footage
    crop-filled to a w x foot_h region CENTRED in it (black band above for the
    hook so it never covers the gameplay, band below for the animated logo).

    anim_logo=(rgb_mp4, alpha_mp4) overlays the animated KiwinoyGaming lower-third
    (bottom band) via alphamerge; the circular KG logo goes top-right. Trims to
    target_seconds. Returns the rendered MP4 bytes.
    """
    clip = Path(clip)
    if not clip.exists():
        raise ReelFfmpegError(f"gameplay clip missing: {clip}")
    dur = ffmpeg.duration(clip) or target_seconds
    show = min(float(target_seconds), dur) if dur else float(target_seconds)

    with tempfile.TemporaryDirectory() as tmp:
        ass = build_ass(Path(tmp) / "cap.ass", w, h, hook=hook, hook_end=show)
        logo = _brand_logo(logo, Path(tmp) / "kglogo.png")  # circular + opacity

        inputs: list[str] = ["-i", str(clip)]
        next_idx = 1
        logo_idx = None
        if logo and Path(logo).exists():
            inputs += ["-i", str(logo)]
            logo_idx = next_idx
            next_idx += 1

        anim_rgb_idx = None
        if anim_logo and all(p and Path(p).exists() for p in anim_logo):
            # NOT looped: the lower-third plays ONCE at the start, then disappears.
            inputs += ["-i", str(anim_logo[0]), "-i", str(anim_logo[1])]
            anim_rgb_idx, anim_alpha_idx = next_idx, next_idx + 1
            next_idx += 2

        keep_audio = ffmpeg.has_audio(clip)
        music_idx = None
        if not keep_audio and music and Path(music).exists():
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            music_idx = next_idx
            next_idx += 1

        # Crop-fill the footage to w x foot_h, then centre it in the w x h frame
        # (black band above for the hook, band below for the logo).
        foot_h = min(int(foot_h or h), h)
        pad_y = int(top_band) if top_band is not None else (h - foot_h) // 2
        pad_y = max(0, min(pad_y, h - foot_h))
        grade = _grade_filter()  # subtle contrast/saturation/sharpen on the footage
        fc = [
            f"[0:v]scale={w}:{foot_h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{foot_h},{grade}pad={w}:{h}:0:{pad_y}:color=black,"
            f"setsar=1,fps={fps}[base]"
        ]
        vlabel = "base"
        if logo_idx is not None:
            fc.append(f"[{logo_idx}:v]format=rgba[lg]")  # pre-sized circular logo
            # top-right of the FOOTAGE (just below the hook band), not the frame.
            fc.append(f"[{vlabel}][lg]overlay=W-w-30:{pad_y + 26}[ovk]")
            vlabel = "ovk"
        if anim_rgb_idx is not None:
            fc.append(f"[{anim_rgb_idx}:v][{anim_alpha_idx}:v]alphamerge,"
                      f"scale={w}:-1[anim]")
            # eof_action=pass -> after the logo finishes (once), the footage shows
            # clean (no freeze-frame, no loop).
            fc.append(f"[{vlabel}][anim]overlay=0:H-h:eof_action=pass[ova]")
            vlabel = "ova"
        fc.append(f"[{vlabel}]ass='{_ass_path_for_filter(ass)}'[v]")

        args = inputs + ["-t", f"{show:.2f}", "-filter_complex", ";".join(fc),
                         "-map", "[v]"]
        if keep_audio:
            args += ["-map", "0:a"]
        elif music_idx is not None:
            args += ["-map", f"{music_idx}:a"]
        args += _v_encode() + _a_encode(bool(keep_audio or music_idx is not None))
        args += ["-shortest", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=1800)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"gameplay render failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def build_commentary(
    clips: list[Path],
    out_path: Path,
    vo_path: Path,
    total_seconds: float,
    subtitles: Optional[list[dict[str, Any]]] = None,
    title: Optional[str] = None,
    title_seconds: float = 4.5,
    logo: Optional[Path] = None,
    fps: int = 30,
    w: int = 1080,
    h: int = 1920,
    foot_h: int = 1440,
    top_band: Optional[int] = None,
    anim_logo: Optional[tuple] = None,
    music: Optional[Path] = None,
    per_clip_seconds: float = 8.0,
    start_skip: float = 3.0,
) -> bytes:
    """Multi-clip b-roll under a voiceover, with burned subtitles. Two passes:
    (A) video-only letterboxed concat + ASS overlays + logo, trimmed to the VO
    length; (B) mux VO + ducked music. Returns the rendered MP4 bytes.

    start_skip -> seek at least this many seconds into each clip so the b-roll
    skips menu / loading / intro frames and lands on action; when a clip is long
    enough the in-point is randomised so repeats show different moments.
    """
    clips = [Path(c) for c in clips if Path(c).exists()]
    if not clips:
        raise ReelFfmpegError("commentary: no usable clips")
    vo_path = Path(vo_path)
    if not vo_path.exists():
        raise ReelFfmpegError(f"commentary: voiceover missing: {vo_path}")

    # Lay clips end-to-end (looping the pool) until they cover the VO length.
    # Each clip contributes at most `per_clip_seconds` of b-roll, so one long /
    # heavy source clip can never dominate (or blow up) the render. Each entry
    # also gets an in-point so we skip dead intro frames + vary repeated clips.
    per = max(2.0, float(per_clip_seconds))
    skip = max(0.0, float(start_skip))
    real = {c: (ffmpeg.duration(c) or per) for c in clips}

    def _in_point(c: Path) -> float:
        d = real[c]
        if d <= per:
            return 0.0                      # short clip: use the whole thing
        if d > per + skip:
            return random.uniform(skip, d - per)  # room to skip + randomise
        return max(0.0, d - per)            # just enough: take the tail (skip intro)

    order: list[tuple[Path, float]] = []
    covered = 0.0
    pool = clips[:]
    random.shuffle(pool)
    i = 0
    guard = 0
    while covered < total_seconds and guard < 4000:
        c = pool[i % len(pool)]
        order.append((c, _in_point(c)))
        covered += min(per, real[c])
        i += 1
        guard += 1

    with tempfile.TemporaryDirectory() as tmp:
        ass = build_ass(
            Path(tmp) / "cap.ass", w, h,
            hook=title, hook_end=title_seconds, subtitles=subtitles,
        )
        # ---- Pass A: video only -------------------------------------------
        # Same frame treatment as the gameplay reels: each b-roll clip is CROP-
        # FILLED into a w x foot_h band centred in the w x h frame (black top band
        # for the hook, bottom band for the animated logo), graded, with the
        # circular KG logo top-right and the animated lower-third (once).
        # `-ss in_point -t per` before each input seeks past dead frames + caps use.
        logo = _brand_logo(logo, Path(tmp) / "kglogo.png")  # circular + opacity
        inputs: list[str] = []
        for c, start in order:
            inputs += ["-ss", f"{start:.2f}", "-t", f"{per:.2f}", "-i", str(c)]
        next_idx = len(order)
        logo_idx = None
        if logo and Path(logo).exists():
            inputs += ["-i", str(logo)]
            logo_idx = next_idx
            next_idx += 1
        anim_rgb_idx = None
        if anim_logo and all(p and Path(p).exists() for p in anim_logo):
            inputs += ["-i", str(anim_logo[0]), "-i", str(anim_logo[1])]  # NOT looped
            anim_rgb_idx, anim_alpha_idx = next_idx, next_idx + 1
            next_idx += 2

        foot_h = min(int(foot_h or h), h)
        pad_y = int(top_band) if top_band is not None else (h - foot_h) // 2
        pad_y = max(0, min(pad_y, h - foot_h))
        grade = _grade_filter()
        fc = [
            f"[{k}:v]scale={w}:{foot_h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{foot_h},{grade}setsar=1,fps={fps}[v{k}]"
            for k in range(len(order))
        ]
        cat_in = "".join(f"[v{k}]" for k in range(len(order)))
        fc.append(f"{cat_in}concat=n={len(order)}:v=1:a=0[cat]")
        fc.append(f"[cat]pad={w}:{h}:0:{pad_y}:color=black[base]")
        vlabel = "base"
        if logo_idx is not None:
            fc.append(f"[{logo_idx}:v]format=rgba[lg]")
            fc.append(f"[{vlabel}][lg]overlay=W-w-30:{pad_y + 26}[ovk]")
            vlabel = "ovk"
        if anim_rgb_idx is not None:
            fc.append(f"[{anim_rgb_idx}:v][{anim_alpha_idx}:v]alphamerge,"
                      f"scale={w}:-1[anim]")
            fc.append(f"[{vlabel}][anim]overlay=0:H-h:eof_action=pass[ova]")
            vlabel = "ova"
        fc.append(f"[{vlabel}]ass='{_ass_path_for_filter(ass)}'[v]")

        video_only = Path(tmp) / "video.mp4"
        args_a = inputs + ["-t", f"{total_seconds:.2f}",
                           "-filter_complex", ";".join(fc), "-map", "[v]", "-an"]
        args_a += _v_encode() + [str(video_only)]
        rc, err = ffmpeg.run(args_a, timeout=3600)
        if rc != 0 or not video_only.exists():
            raise ReelFfmpegError(f"commentary pass A failed (rc={rc}):\n{err}")

        # ---- Pass B: mux VO (+ ducked, looped music) ----------------------
        out_path.parent.mkdir(parents=True, exist_ok=True)
        args_b = ["-i", str(video_only), "-i", str(vo_path)]
        if music and Path(music).exists():
            duck = float(_caption_cfg().get("music_duck", 0.14))
            args_b += ["-stream_loop", "-1", "-i", str(music),
                       "-filter_complex",
                       f"[2:a]volume={duck}[m];[1:a]volume=1[vo];"
                       f"[vo][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                       "-map", "0:v", "-map", "[a]"]
        else:
            args_b += ["-map", "0:v", "-map", "1:a"]
        args_b += ["-c:v", "copy"] + _a_encode(True) + ["-shortest", str(out_path)]
        rc, err = ffmpeg.run(args_b, timeout=600)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"commentary pass B failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def _v_encode() -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]


def _a_encode(has: bool) -> list[str]:
    if not has:
        return ["-an"]
    return ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
