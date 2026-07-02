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
import re
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
    hook_center: Optional[tuple[int, int]] = None,
) -> Path:
    """Write an ASS subtitle file: a persistent hook + timed subtitle events.

    hook        -> top caption text (shown 0 .. hook_end seconds).
    subtitles   -> [{start, end, text}, ...] bottom captions (seconds).
    hook_center -> if set, the hook is centred (\\an5) on this (x, y) point instead
                   of the default top-anchored Hook style — used to centre the hook
                   in the top 1/3 band of the triptych regardless of line count.
    """
    lines = [_ass_header(w, h)]
    if hook:
        htext = ffmpeg.ass_escape(hook.upper())
        if hook_center:
            htext = f"{{\\an5\\pos({int(hook_center[0])},{int(hook_center[1])})}}" + htext
        lines.append(
            f"Dialogue: 0,{ffmpeg.ass_time(0)},{ffmpeg.ass_time(max(1.0, hook_end))},"
            f"Hook,,0,0,0,,{htext}\n"
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


def _anim_overlay(rgb_idx: int, alpha_idx: int, vlabel: str, w: int,
                  out_label: str, cfg: Optional[dict] = None) -> list[str]:
    """Filter lines for the animated lower-third: bottom-CENTRED + a fade-out
    after a few seconds (viewer feedback: it was covering subtitles). Plays once
    (eof_action=pass) then the footage shows clean. `cfg` lets each reel type set
    its own placement (gameplay sits higher for YouTube; commentary stays low)."""
    a = cfg if cfg is not None else (CONFIG.reels.get("logo_animated", {}) or {})
    scale = float(a.get("scale", 0.78))
    fstart = float(a.get("fade_start", 4.0))
    fdur = float(a.get("fade_dur", 1.5))
    margin = int(a.get("bottom_margin", 20))
    start = float(a.get("start", 0.0))  # delay: reveal only AFTER N s of the reel
    lw = int(w * scale)
    # When start>0, shift the animation's timeline so it begins at reel t=start, and
    # gate the overlay so nothing shows before then (clean for a logo-reveal intro).
    delay = f",setpts=PTS+{start}/TB" if start > 0 else ""
    gate = f":enable='gte(t,{start})'" if start > 0 else ""
    return [
        f"[{rgb_idx}:v][{alpha_idx}:v]alphamerge,scale={lw}:-1,"
        f"fade=t=out:st={fstart}:d={fdur}:alpha=1{delay}[animl]",
        f"[{vlabel}][animl]overlay=(W-w)/2:H-h-{margin}:eof_action=pass{gate}[{out_label}]",
    ]


def _brand_logo(src: Optional[Path], out: Path, size: Optional[int] = None) -> Optional[Path]:
    """Crop the brand logo to a CIRCLE + apply opacity (top-right overlay).

    Done in Pillow (robust) rather than an ffmpeg circle-mask. Returns the
    circular PNG path, or the raw src on failure, or None if no logo. `size`
    overrides the rendered diameter (e.g. larger for a 4K long-form frame).
    """
    if not src or not Path(src).exists():
        return None
    try:
        from PIL import Image, ImageChops, ImageDraw
        size = int(size or CONFIG.reels.get("brand_logo_size", 140))
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


def _prep_game_logo(src: Path, out: Path) -> Optional[Path]:
    """Trim the transparent padding off a game-logo PNG (e.g. a 2200x2200 canvas
    around a wide wordmark) so it scales tight + sharp. Returns the trimmed PNG."""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGBA")
        bbox = im.getbbox()
        if bbox:
            im = im.crop(bbox)
        im.save(out, "PNG")
        return out
    except Exception:
        return Path(src) if Path(src).exists() else None


def _game_logo_overlay(idx: int, vlabel: str, w: int, out_label: str) -> list[str]:
    """Overlay the (trimmed) game logo at TOP-CENTRE, scaled to fit ABOVE the hook
    so it never overlaps the on-screen caption (which starts at hook_margin_v)."""
    g = CONFIG.reels.get("game_logo", {}) or {}
    cap = CONFIG.reels.get("caption", {}) or {}
    hook_mv = int(cap.get("hook_margin_v", 250))
    top = int(g.get("top_margin", 36))
    bw = int(w * float(g.get("scale_w", 0.5)))
    max_h = min(int(g.get("max_h", 160)), max(60, hook_mv - top - 24))  # keep above hook
    return [
        f"[{idx}:v]format=rgba,scale={bw}:{max_h}:force_original_aspect_ratio=decrease[glogo]",
        f"[{vlabel}][glogo]overlay=(W-w)/2:{top}[{out_label}]",
    ]


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
    game_logo: Optional[Path] = None,
    fill: bool = True,
    hi_bitrate: bool = False,
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

        game_logo_idx = None
        if game_logo and Path(game_logo).exists():
            gl = _prep_game_logo(Path(game_logo), Path(tmp) / "glogo.png")
            if gl:
                inputs += ["-i", str(gl)]
                game_logo_idx = next_idx
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
        if game_logo_idx is not None:                    # game logo: top-centre, above the hook
            fc += _game_logo_overlay(game_logo_idx, vlabel, w, "ovg")
            vlabel = "ovg"
        if anim_rgb_idx is not None:
            fc += _anim_overlay(anim_rgb_idx, anim_alpha_idx, vlabel, w, "ova")
            vlabel = "ova"
        fc.append(f"[{vlabel}]ass='{_ass_path_for_filter(ass)}'[v]")

        args = inputs + ["-t", f"{show:.2f}", "-filter_complex", ";".join(fc),
                         "-map", "[v]"]
        if keep_audio:
            args += ["-map", "0:a"]
        elif music_idx is not None:
            args += ["-map", f"{music_idx}:a"]
        args += _v_encode(hi_bitrate) + _a_encode(bool(keep_audio or music_idx is not None), hi_bitrate)
        args += ["-shortest", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=1800)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"gameplay render failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def build_threads_landscape(
    clip: Path,
    out_path: Path,
    logo: Optional[Path] = None,
    fps: int = 60,
    w: int = 1920,
    h: int = 1080,
    target_seconds: float = 60.0,
    music: Optional[Path] = None,
) -> bytes:
    """Landscape (1920x1080) gameplay clip for a Threads VIDEO post: the footage
    'as is' (16:9, not reframed), GRADED like the reels, with the circular KG logo
    in the top-right corner. No burned text — the hook is the post caption. CFR fps.
    Keeps the game audio (or loops music). Returns the rendered MP4 bytes."""
    clip = Path(clip)
    if not clip.exists():
        raise ReelFfmpegError(f"clip missing: {clip}")
    dur = ffmpeg.duration(clip) or target_seconds
    show = min(float(target_seconds), dur) if dur else float(target_seconds)

    with tempfile.TemporaryDirectory() as tmp:
        logo = _brand_logo(logo, Path(tmp) / "kglogo.png")  # same circular corner mark
        inputs: list[str] = ["-i", str(clip)]
        next_idx, logo_idx = 1, None
        if logo and Path(logo).exists():
            inputs += ["-loop", "1", "-i", str(logo)]
            logo_idx = next_idx
            next_idx += 1
        keep_audio = ffmpeg.has_audio(clip)
        music_idx = None
        if not keep_audio and music and Path(music).exists():
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            music_idx = next_idx
            next_idx += 1

        grade = _grade_filter()
        fc = [f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},{grade}setsar=1,fps={fps}[base]"]
        vlabel = "base"
        if logo_idx is not None:
            fc.append(f"[{logo_idx}:v]format=rgba[lg]")
            fc.append(f"[{vlabel}][lg]overlay=W-w-{int(w*0.02)}:{int(h*0.04)}[v]")
            vlabel = "v"

        args = inputs + ["-t", f"{show:.2f}", "-filter_complex", ";".join(fc),
                         "-map", f"[{vlabel}]"]
        if keep_audio:
            args += ["-map", "0:a"]
        elif music_idx is not None:
            args += ["-map", f"{music_idx}:a"]
        args += _v_encode() + ["-fps_mode", "cfr", "-r", str(fps)]
        args += _a_encode(bool(keep_audio or music_idx is not None))
        args += ["-shortest", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=1800)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"threads landscape render failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def build_footage_rotated(
    clip: Path,
    out_path: Path,
    logo: Optional[Path] = None,
    fps: int = 60,
    target_seconds: float = 60.0,
    music: Optional[Path] = None,
) -> bytes:
    """The landscape gameplay ROTATED 90° CLOCKWISE into a 1080x1920 portrait (so the
    footage's bottom edge ends up on the LEFT). Graded; the KG corner logo stays
    UPRIGHT top-right; CFR fps. For an Instagram reel. Returns the MP4 bytes."""
    clip = Path(clip)
    if not clip.exists():
        raise ReelFfmpegError(f"clip missing: {clip}")
    dur = ffmpeg.duration(clip) or target_seconds
    show = min(float(target_seconds), dur) if dur else float(target_seconds)

    with tempfile.TemporaryDirectory() as tmp:
        logo = _brand_logo(logo, Path(tmp) / "kglogo.png")
        inputs: list[str] = ["-i", str(clip)]
        next_idx, logo_idx = 1, None
        if logo and Path(logo).exists():
            inputs += ["-loop", "1", "-i", str(logo)]
            logo_idx = next_idx
            next_idx += 1
        keep_audio = ffmpeg.has_audio(clip)
        music_idx = None
        if not keep_audio and music and Path(music).exists():
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            music_idx = next_idx
            next_idx += 1

        grade = _grade_filter()
        # Build the graded LANDSCAPE first, overlay the logo at the landscape top-right,
        # THEN rotate the whole frame 90° CW -> 1080x1920. This way the logo rotates
        # WITH the footage, so when the viewer tilts their phone to watch the gameplay
        # right-side-up, footage + logo are both upright (and the logo lands top-right).
        fc = [f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
              f"crop=1920:1080,{grade}setsar=1[land]"]
        comp = "land"
        if logo_idx is not None:
            fc.append(f"[{logo_idx}:v]format=rgba[lg]")
            fc.append(f"[land][lg]overlay=W-w-38:38[comp]")  # landscape top-right
            comp = "comp"
        fc.append(f"[{comp}]transpose=1,fps={fps}[v]")  # rotate footage + logo together
        vlabel = "v"

        args = inputs + ["-t", f"{show:.2f}", "-filter_complex", ";".join(fc),
                         "-map", f"[{vlabel}]"]
        if keep_audio:
            args += ["-map", "0:a"]
        elif music_idx is not None:
            args += ["-map", f"{music_idx}:a"]
        args += _v_encode() + ["-fps_mode", "cfr", "-r", str(fps)]
        args += _a_encode(bool(keep_audio or music_idx is not None))
        args += ["-shortest", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=1800)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"rotated footage render failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def _part_order_key(p: Path):
    """Order gameplay parts by the number after 'part' (handles 'Part 2',
    'part 5.1', 'Part_10'); files without a part number sort last by name."""
    m = re.search(r"part[\s_\-]*([0-9]+(?:\.[0-9]+)?)", p.name, re.IGNORECASE)
    return (float(m.group(1)) if m else float("inf"), p.name.lower())


def _measure_loudness(parts: list[Path], target_i: float = -14.0,
                      tp: float = -1.5, lra: float = 11.0) -> Optional[dict]:
    """Pass 1 of two-pass loudnorm: measure the CONCATENATED audio's loudness
    (audio-only, no video decode). Returns loudnorm's JSON stats (input_i/tp/lra/
    thresh + target_offset) for the correction pass, or None if parsing fails."""
    import json

    n = len(parts)
    inputs: list[str] = []
    for p in parts:
        inputs += ["-i", str(p)]
    ain = "".join(f"[{i}:a:0]" for i in range(n))
    fc = (f"{ain}concat=n={n}:v=0:a=1[a];"
          f"[a]loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=json")
    _, err = ffmpeg.run(inputs + ["-filter_complex", fc, "-vn", "-f", "null", "-"],
                        timeout=7200)
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err or "", re.DOTALL)
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except Exception:
        return None


def build_longform_hdr(
    parts: list[Path],
    out_path: Path,
    logo: Optional[Path] = None,
    lower_third: Optional[Path] = None,
    lower_third_start: float = 7.0,
    lower_third_fade: float = 1.0,
    lower_third_scale: float = 1.0,
    lower_third_pos: str = "full",
    graphics_pct: float = 0.58,
    bitrate: str = "63M",
    keyint: int = 72,
    fps: str = "60000/1001",   # 59.94
    logo_size: int = 480,
    audio_lufs: Optional[float] = -14.0,
    copy: bool = False,
    timeout: int = 36000,
) -> Path:
    """Concatenate the ordered 4K/60 HDR10 PART files into one full-game video and
    re-encode PRESERVING HDR10 to match the user's Premiere preset: H.264 High10
    (10-bit), Rec.2100 PQ / Rec2020, HDR10 metadata (MaxCLL 1000 / MaxFALL 200,
    MasterDisplay L 0.01-1000), ~63 Mbps.

    Optional overlays (both SDR graphics scaled toward HDR graphics-white via
    graphics_pct — calibrate on an HDR display):
      logo         -> circular KG mark, top-right (persists). Usually omitted now
                      because YouTube's own channel watermark covers it.
      lower_third  -> a transparent (alpha) .mov that plays ONCE at lower_third_start
                      seconds (e.g. the Gaming Social lower-thirds at 0:07).

    Parts MUST share the same codec/res/fps/colour (same export preset). Returns
    out_path (does NOT load bytes — the full-game file can be tens of GB)."""
    parts = sorted([Path(p) for p in parts], key=_part_order_key)
    missing = [str(p) for p in parts if not p.exists()]
    if not parts or missing:
        raise ReelFfmpegError(f"longform parts missing: {missing or 'none provided'}")

    if copy:
        # STREAM-COPY concat (no re-encode): near-instant + byte-perfect HDR preserved.
        # Requires identical codec/res/fps/colour across parts (same capture export).
        # Overlays + loudnorm are skipped (they'd force a decode+re-encode). No
        # +faststart — it would rewrite the whole (tens-of-GB) file; YouTube doesn't
        # need it.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            lst = Path(tmp) / "concat.txt"
            # ABSOLUTE paths — the concat demuxer resolves relative paths against the
            # list file's own dir (the temp dir), not the CWD.
            lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts),
                           encoding="utf-8")
            rc, err = ffmpeg.run(["-f", "concat", "-safe", "0", "-i", str(lst),
                                  "-c", "copy", str(out_path)], timeout=timeout)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"longform stream-copy concat failed (rc={rc}):\n{err[-2000:]}")
        return out_path

    with tempfile.TemporaryDirectory() as tmp:
        n = len(parts)
        gp = max(0.05, min(1.0, float(graphics_pct)))
        inputs: list[str] = []
        for p in parts:
            inputs += ["-i", str(p)]
        idx = n
        # optional circular KG logo — a SINGLE frame (overlay repeats it for the whole
        # video, so no -loop + no -shortest, which would truncate to the lower-third).
        logo_png = (_brand_logo(logo, Path(tmp) / "kglogo.png", size=logo_size)
                    if logo else None)
        logo_idx = None
        if logo_png and Path(logo_png).exists():
            inputs += ["-i", str(logo_png)]
            logo_idx = idx
            idx += 1
        # optional animated lower-third (transparent-alpha .mov) — plays ONCE.
        lt_idx = None
        if lower_third and Path(lower_third).exists():
            inputs += ["-i", str(lower_third)]
            lt_idx = idx
            idx += 1

        # concat all parts (video + audio) in order
        concat_in = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
        fc = [f"{concat_in}concat=n={n}:v=1:a=1[cv][ca]"]
        vlabel = "cv"
        # SDR graphics are scaled toward HDR graphics-white (PQ ~58% = 203 nits) before
        # overlaying onto the PQ/Rec2020 signal. graphics_pct is the calibration knob.
        if logo_idx is not None:
            margin = int(3840 * 0.02)
            fc += [
                f"[{logo_idx}:v]colorchannelmixer=rr={gp}:gg={gp}:bb={gp},format=rgba[lg]",
                f"[{vlabel}][lg]overlay=W-w-{margin}:{margin}:format=auto[vl]",
            ]
            vlabel = "vl"
        if lt_idx is not None:
            st = max(0.0, float(lower_third_start))
            # delay the lower-third to t=start, gate it, play once (eof_action=pass).
            # Fade its ALPHA out over the last lower_third_fade seconds so it doesn't
            # cut abruptly (fade is in the clip's OWN time, before the setpts delay).
            ltdur = ffmpeg.duration(Path(lower_third)) or 10.0
            fdur = max(0.0, min(float(lower_third_fade), ltdur))
            fade = (f"fade=t=out:st={max(0.0, ltdur - fdur):.2f}:d={fdur:.2f}:alpha=1,"
                    if fdur > 0 else "")
            s = max(0.05, min(1.0, float(lower_third_scale)))
            scl = f"scale=trunc(iw*{s}/2)*2:trunc(ih*{s}/2)*2," if s < 1.0 else ""
            pos = {"full": "0:0",
                   "bottom": "(W-w)/2:H-h-60",
                   "bottom-left": "60:H-h-60",
                   "bottom-right": "W-w-60:H-h-60"}.get(str(lower_third_pos), "0:0")
            fc += [
                f"[{lt_idx}:v]{scl}colorchannelmixer=rr={gp}:gg={gp}:bb={gp},"
                f"format=rgba,{fade}setpts=PTS+{st}/TB[lt]",
                f"[{vlabel}][lt]overlay={pos}:enable='gte(t,{st})':"
                f"eof_action=pass:format=auto[vlt]",
            ]
            vlabel = "vlt"

        # Loudness-normalize the (concatenated) audio to a consistent target — parts
        # can be exported at different levels, so this evens the whole game out.
        # -14 LUFS = YouTube's playback target; TP -1.5 dBTP, LRA 11.
        alabel = "ca"
        if audio_lufs is not None:
            # Two-pass loudnorm: measure the concatenated audio, then correct to the
            # target accurately (single-pass under/overshoots on dynamic content).
            I = float(audio_lufs)
            m = _measure_loudness(parts, I)
            if m:
                fc.append(
                    f"[ca]loudnorm=I={I:.1f}:TP=-1.5:LRA=11:"
                    f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                    f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
                    f"offset={m['target_offset']}:linear=true[aout]")
            else:
                fc.append(f"[ca]loudnorm=I={I:.1f}:TP=-1.5:LRA=11[aout]")  # fallback
            alabel = "aout"

        # HDR10 static metadata in x264 units: chromaticity in 0.00002 steps,
        # luminance in 0.0001 cd/m^2 steps. Rec2020 primaries + D65; L max 1000, min 0.01.
        master = ("G(8500,39850)B(6550,2300)R(35400,14600)"
                  "WP(15635,16450)L(10000000,100)")
        x264p = (f"keyint={keyint}:min-keyint={keyint}:colorprim=bt2020:"
                 f"transfer=smpte2084:colormatrix=bt2020nc:"
                 f"mastering-display={master}:cll=1000,200")

        args = inputs + [
            "-filter_complex", ";".join(fc),
            "-map", f"[{vlabel}]", "-map", f"[{alabel}]",
            "-c:v", "libx264", "-profile:v", "high10", "-level", "5.2",
            "-pix_fmt", "yuv420p10le", "-r", fps,
            "-color_primaries", "bt2020", "-color_trc", "smpte2084",
            "-colorspace", "bt2020nc", "-color_range", "tv",
            "-b:v", bitrate, "-maxrate", bitrate, "-minrate", bitrate, "-bufsize", "126M",
            "-x264-params", x264p,
            "-c:a", "aac", "-b:a", "384k",
            "-movflags", "+faststart", str(out_path),   # NO -shortest (keep full length)
        ]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=timeout)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"longform HDR render failed (rc={rc}):\n{err[-2000:]}")
    return out_path


def build_gameplay_triptych(
    clip: Path,
    out_path: Path,
    hook: str,
    game_art: Path,
    top_image: Optional[Path] = None,
    logo: Optional[Path] = None,
    fps: int = 60,
    w: int = 1080,
    h: int = 1920,
    target_seconds: float = 75.0,
    music: Optional[Path] = None,
    anim_logo: Optional[tuple] = None,
    hi_bitrate: bool = False,
) -> bytes:
    """3-PANEL gameplay reel (the meme/TikTok layout). The w x h frame is split into
    three equal horizontal bands; a 16:9 element is centred in each:
      - TOP    : a still frame grabbed from the clip + the HOOK caption on it.
      - MIDDLE : the gameplay video UNCROPPED (16:9 fits the band edge-to-edge).
      - BOTTOM : the game's key art (from reels/assets/game-art/<game>/).
    Returns the rendered MP4 bytes. Raises if the clip or art is missing (the
    orchestrator then falls back to the classic layout)."""
    clip, game_art = Path(clip), Path(game_art)
    if not clip.exists():
        raise ReelFfmpegError(f"gameplay clip missing: {clip}")
    if not game_art.exists():
        raise ReelFfmpegError(f"game art missing: {game_art}")
    dur = ffmpeg.duration(clip) or target_seconds
    show = min(float(target_seconds), dur) if dur else float(target_seconds)
    band = h // 3

    with tempfile.TemporaryDirectory() as tmp:
        # Top panel: prefer a curated game screenshot (from the cloud image library);
        # otherwise grab a representative still from the clip itself.
        if top_image and Path(top_image).exists():
            shot = Path(top_image)
        else:
            shot = Path(tmp) / "shot.png"
            ss = min(2.0, max(0.5, (dur or 2.0) * 0.3))
            ffmpeg.run(["-ss", f"{ss:.2f}", "-i", str(clip), "-frames:v", "1",
                        "-q:v", "2", str(shot)], timeout=120)
            if not shot.exists():
                ffmpeg.run(["-i", str(clip), "-frames:v", "1", "-q:v", "2", str(shot)],
                           timeout=120)

        # Hook centred in the top 1/3 band (per user) — vertical centre of band 0.
        # No circle KG logo on the triptych anymore (per user).
        ass = build_ass(Path(tmp) / "cap.ass", w, h, hook=hook, hook_end=show,
                        hook_center=(w // 2, band // 2))

        inputs: list[str] = ["-i", str(clip),
                             "-loop", "1", "-i", str(shot),
                             "-loop", "1", "-i", str(game_art)]
        next_idx = 3
        # Moving glow for the bottom game-art panel: a big SOFT round light that
        # WANDERS (sin-based, non-repeating path) so the art's own highlights/edges/
        # text/subject shimmer as it passes — a moving reflection, not a band. The
        # light is a soft radial blob; the glow only lifts the art where the light is.
        arth = round(w * 9 / 16)
        gl = (CONFIG.reels.get("gameplay", {}) or {}).get("triptych_glow", {}) or {}
        glow_on, blob_idx = bool(gl.get("enabled", True)), None
        bd = int(gl.get("size", 640))               # soft light diameter (px)
        if glow_on:
            # feather: higher -> the gaussian fades fully to 0 well inside the tile,
            # so there's NO hard ring/edge (the moving shape stays invisible).
            feather = max(2.5, float(gl.get("feather", 6.0)))
            sr = max(1.0, bd / feather)              # gaussian radius (soft edges)
            a_peak = int(max(0.0, min(1.0, float(gl.get("intensity", 0.5)))) * 255)
            blob = Path(tmp) / "glow.png"
            ffmpeg.run(["-f", "lavfi", "-i", f"color=c=white:s={bd}x{bd}", "-vf",
                        ("format=rgba,geq=r=255:g=255:b=255:"
                         f"a='{a_peak}*exp(-(pow((X-{bd}/2)/{sr:.1f},2)"
                         f"+pow((Y-{bd}/2)/{sr:.1f},2)))'"),
                        "-frames:v", "1", str(blob)], timeout=60)
            if blob.exists():
                inputs += ["-loop", "1", "-i", str(blob)]
                blob_idx = next_idx
                next_idx += 1
            else:
                glow_on = False
        anim_rgb_idx = None
        if anim_logo and all(p and Path(p).exists() for p in anim_logo):
            # animated KiwinoyGaming lower-third — plays ONCE at the start, same spot
            # as the classic layout (bottom-centre), then fades out.
            inputs += ["-i", str(anim_logo[0]), "-i", str(anim_logo[1])]
            anim_rgb_idx, anim_alpha_idx = next_idx, next_idx + 1
            next_idx += 2
        keep_audio = ffmpeg.has_audio(clip)
        music_idx = None
        if not keep_audio and music and Path(music).exists():
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            music_idx = next_idx
            next_idx += 1

        grade = _grade_filter()  # enhance the gameplay AND the game art (like classic)
        # Darken the top still (like the quote cards) so the white hook stays the
        # dominant element. rr/gg/bb<1 multiplies brightness -> 0.55 ~= a 45% black
        # overlay. Tunable via reels.gameplay.triptych_top_dim (lower = darker).
        dim = float((CONFIG.reels.get("gameplay", {}) or {}).get("triptych_top_dim", 0.55))
        # Bottom panel: fill the art to the 16:9 panel, GRADE it, then sweep a glow.
        if glow_on and blob_idx is not None:
            sway = float(gl.get("sway", 0.42))           # how far the light wanders
            spd = max(0.1, float(gl.get("speed", 1.0)))  # <1 = slower wander
            dual = bool(gl.get("dual", True))            # a 2nd light on the opposite side
            ax, bx = w * sway, w * sway * 0.4
            ay, by = arth * sway, arth * sway * 0.45
            p1, p2, p3, p4 = 6.3 / spd, 9.7 / spd, 5.1 / spd, 8.3 / spd
            # wandering offset (non-commensurate periods -> the path never repeats)
            dx = f"{ax:.0f}*sin(2*PI*t/{p1:.2f})+{bx:.0f}*sin(2*PI*t/{p2:.2f})"
            dy = f"{ay:.0f}*sin(2*PI*t/{p3:.2f})+{by:.0f}*sin(2*PI*t/{p4:.2f})"
            bot_lines = [
                f"[2:v]scale={w}:{arth}:force_original_aspect_ratio=increase,"
                f"crop={w}:{arth},{grade}setsar=1,format=gbrp[artg]",
                f"[artg]split[artA][artB]",
                f"color=c=black:s={w}x{arth}:r={fps},format=gbrp[lblk]",
            ]
            if dual:
                bot_lines += [
                    f"[{blob_idx}:v]split[bl1][bl2]",
                    f"[lblk][bl1]overlay=x='(W-w)/2+{dx}':y='(H-h)/2+{dy}':"
                    f"eof_action=pass[lg1]",
                    # 2nd light mirrored through centre -> always on the opposite side
                    f"[lg1][bl2]overlay=x='(W-w)/2-({dx})':y='(H-h)/2-({dy})':"
                    f"eof_action=pass[light]",
                ]
            else:
                bot_lines += [
                    f"[lblk][{blob_idx}:v]overlay=x='(W-w)/2+{dx}':y='(H-h)/2+{dy}':"
                    f"eof_action=pass[light]",
                ]
            # art x light -> only the lit regions survive; screen it back onto the
            # art so highlights/edges/text glow where each light is.
            bot_lines += [
                f"[artB][light]blend=all_mode=multiply[lit]",
                f"[artA][lit]blend=all_mode=screen,format=yuv420p[bot]",
            ]
        else:
            bot_lines = [f"[2:v]scale={w}:{arth}:force_original_aspect_ratio=increase,"
                         f"crop={w}:{arth},{grade}setsar=1[bot]"]
        fc = [
            f"color=c=black:s={w}x{h}:r={fps}[bg]",
            f"[0:v]scale={w}:-2,{grade}setsar=1,fps={fps}[mid]",
            f"[1:v]scale={w}:-2,colorchannelmixer=rr={dim}:gg={dim}:bb={dim},"
            f"setsar=1[top]",
            *bot_lines,
            f"[bg][top]overlay=(W-w)/2:({band}-h)/2[b1]",
            f"[b1][mid]overlay=(W-w)/2:{band}+({band}-h)/2[b2]",
            f"[b2][bot]overlay=(W-w)/2:{2 * band}+({band}-h)/2[b3]",
        ]
        vlabel = "b3"
        # NOTE: no circle KG logo (removed per user) and no game logo on the triptych.
        if anim_rgb_idx is not None:
            fc += _anim_overlay(anim_rgb_idx, anim_alpha_idx, vlabel, w, "ova")
            vlabel = "ova"
        # Lowkey "KIWINOYGAMING" wordmark at the bottom-centre of the TOP panel.
        wm = (CONFIG.reels.get("gameplay", {}) or {}).get("triptych_wordmark", {}) or {}
        if wm.get("enabled", True) and wm.get("text"):
            font = str(wm.get("font", "assets/fonts/tarrget-font/TarrgetRegular-WEOz.otf"))
            txt = str(wm.get("text", "KIWINOYGAMING"))
            size = int(wm.get("size", 42))
            opac = float(wm.get("opacity", 0.85))
            off = int(wm.get("bottom_offset", 22))
            fc.append(
                f"[{vlabel}]drawtext=fontfile={font}:text={txt}:fontcolor=white@{opac}:"
                f"fontsize={size}:x=(w-text_w)/2:y={band}-text_h-{off}:"
                f"shadowcolor=black@0.5:shadowx=2:shadowy=2[ovw]")
            vlabel = "ovw"
        fc.append(f"[{vlabel}]ass='{_ass_path_for_filter(ass)}'[v]")

        args = inputs + ["-t", f"{show:.2f}", "-filter_complex", ";".join(fc),
                         "-map", "[v]"]
        if keep_audio:
            args += ["-map", "0:a"]
        elif music_idx is not None:
            args += ["-map", f"{music_idx}:a"]
        args += _v_encode(hi_bitrate) + ["-fps_mode", "cfr", "-r", str(fps)]
        args += _a_encode(bool(keep_audio or music_idx is not None), hi_bitrate)
        args += ["-shortest", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=1800)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"triptych render failed (rc={rc}):\n{err}")
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
    game_logo: Optional[Path] = None,
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
        game_logo_idx = None
        if game_logo and Path(game_logo).exists():
            gl = _prep_game_logo(Path(game_logo), Path(tmp) / "glogo.png")
            if gl:
                inputs += ["-i", str(gl)]
                game_logo_idx = next_idx
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
        if game_logo_idx is not None:                    # game logo: top-centre, above the hook
            fc += _game_logo_overlay(game_logo_idx, vlabel, w, "ovg")
            vlabel = "ovg"
        if anim_rgb_idx is not None:
            # Commentary keeps the ORIGINAL low lower-third (FB-only; the raised
            # gameplay placement is a YouTube-Shorts fix and shouldn't apply here).
            base = CONFIG.reels.get("logo_animated", {}) or {}
            cmt = (CONFIG.reels.get("commentary", {}) or {}).get("logo_animated") or {}
            anim_cfg = {**base, "scale": 0.78, "bottom_margin": 20, **cmt}
            fc += _anim_overlay(anim_rgb_idx, anim_alpha_idx, vlabel, w, "ova",
                                cfg=anim_cfg)
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
            cap = _caption_cfg()
            music_vol = float(cap.get("music_duck", 0.08))  # base bed level under VO
            vo_gain = float(cap.get("vo_gain", 1.0))         # narrator at full
            # SIDECHAIN DUCKING: the music is compressed by the VOICE itself, so it
            # drops whenever the narrator speaks and comes back in the gaps — the
            # music never competes with the narration. normalize=0 keeps the voice
            # at full level (amix's default 1/n would otherwise halve it); alimiter
            # guards against clipping.
            args_b += ["-stream_loop", "-1", "-i", str(music),
                       "-filter_complex",
                       f"[1:a]volume={vo_gain},asplit=2[vo][sc];"
                       f"[2:a]volume={music_vol}[m0];"
                       f"[m0][sc]sidechaincompress=threshold=0.02:ratio=12:"
                       f"attack=15:release=320[mduck];"
                       f"[vo][mduck]amix=inputs=2:duration=first:dropout_transition=0:"
                       f"normalize=0,alimiter=limit=0.95[a]",
                       "-map", "0:v", "-map", "[a]"]
        else:
            args_b += ["-map", "0:v", "-map", "1:a"]
        args_b += ["-c:v", "copy"] + _a_encode(True) + ["-shortest", str(out_path)]
        rc, err = ffmpeg.run(args_b, timeout=600)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"commentary pass B failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def build_quote_short(
    clips: list[Path],
    out_path: Path,
    text_png: Path,
    music: Optional[Path] = None,
    music_start: float = 0.0,
    total_seconds: float = 10.0,
    per_clip_seconds: float = 3.0,
    start_skip: float = 3.0,
    fps: int = 60,
    w: int = 1080,
    h: int = 1920,
) -> bytes:
    """A short, loop-friendly motivational quote SHORT for YouTube: gameplay
    b-roll spliced FULL-SCREEN (9:16) + graded at CFR `fps`, the quote text
    overlaid (the transparent text_png), with a music bed that starts at
    `music_start` seconds (mid-track climax). No voiceover. Returns the MP4 bytes."""
    clips = [Path(c) for c in clips if Path(c).exists()]
    if not clips:
        raise ReelFfmpegError("quote short: no clips")
    text_png = Path(text_png)
    per = max(1.5, float(per_clip_seconds))
    skip = max(0.0, float(start_skip))
    real = {c: (ffmpeg.duration(c) or per) for c in clips}

    def _in(c: Path) -> float:
        d = real[c]
        if d <= per:
            return 0.0
        if d > per + skip:
            return random.uniform(skip, d - per)
        return max(0.0, d - per)

    order: list[tuple[Path, float]] = []
    pool = clips[:]
    random.shuffle(pool)
    i = guard = 0
    covered = 0.0
    while covered < total_seconds and guard < 200:
        c = pool[i % len(pool)]
        order.append((c, _in(c)))
        covered += per
        i += 1
        guard += 1

    with tempfile.TemporaryDirectory():
        inputs: list[str] = []
        for c, start in order:
            inputs += ["-ss", f"{start:.2f}", "-t", f"{per:.2f}", "-i", str(c)]
        # LOOP the still quote PNG into a real timed stream (at the output fps) so
        # the fade-in actually animates across frames. A single-frame input would
        # be frozen at t=0 — where fade-in alpha is 0 — leaving the quote invisible.
        inputs += ["-loop", "1", "-framerate", str(fps), "-t",
                   f"{total_seconds:.2f}", "-i", str(text_png)]
        text_idx = len(order)
        music_idx = None
        if music and Path(music).exists():
            # seek mid-track (climax) + loop so a short track still fills the video
            inputs += ["-stream_loop", "-1", "-ss", f"{max(0.0, music_start):.2f}",
                       "-i", str(music)]
            music_idx = len(order) + 1

        grade = _grade_filter()
        fc = [
            f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},{grade}setsar=1,fps={fps}[v{k}]"
            for k in range(len(order))
        ]
        fc.append("".join(f"[v{k}]" for k in range(len(order))) +
                  f"concat=n={len(order)}:v=1:a=0[bgv]")
        # Opening transition: the quote fades in while easing up a few px (~0.7s).
        fc.append(f"[{text_idx}:v]format=rgba,fade=t=in:st=0:d=0.7:alpha=1[txt]")
        fc.append("[bgv][txt]overlay=x=0:y='if(lt(t,0.7),(0.7-t)/0.7*55,0)'[v]")

        args = inputs + ["-t", f"{total_seconds:.2f}",
                         "-filter_complex", ";".join(fc), "-map", "[v]"]
        if music_idx is not None:
            args += ["-map", f"{music_idx}:a"]
        # explicit CFR at the target fps (per user)
        args += _v_encode() + ["-fps_mode", "cfr", "-r", str(fps)]
        args += _a_encode(music_idx is not None) + ["-shortest", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        rc, err = ffmpeg.run(args, timeout=900)
        if rc != 0 or not out_path.exists():
            raise ReelFfmpegError(f"quote short failed (rc={rc}):\n{err}")
        return out_path.read_bytes()


def _v_encode(hi: bool = False) -> list[str]:
    """Reel video encoder. Default = the original proven feed encode (IG/YT/FB, smooth
    60fps). hi=True = a high-bitrate source for the TikTok track ONLY: ~40 Mbps (TikTok's
    20-50 spec). Proven necessary because TikTok's PUBLIC transcode crushes low-bitrate
    sources (a private 10 Mbps reel looked great, degraded the instant it went public);
    handing TikTok ~40 Mbps leaves far more detail for its public re-encode to preserve."""
    if not hi:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart"]
    return ["-c:v", "libx264", "-preset", "fast",
            "-b:v", "40M", "-maxrate", "55M", "-bufsize", "110M",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-color_range", "tv",
            "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709",
            "-movflags", "+faststart"]


def _a_encode(has: bool, hi: bool = False) -> list[str]:
    if not has:
        return ["-an"]
    if hi:
        return ["-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2"]  # TikTok spec
    return ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
