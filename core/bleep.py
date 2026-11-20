"""Beep out spoken swear words in a clip (Bryce, 2026-11-20, GTA 6 only for now): "when someone
says 'bitch' only the word when spoken 'bitch' is just beeped out".

ElevenLabs Scribe gives word timings for the clip's audio; every word that matches the swear list
in agents/content.py is muted and a tone plays over it. The video stream is copied untouched.
Fail-open: no key, no speech or any error returns the input clip unchanged (and says so)."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core.config import CONFIG


def _cfg() -> dict:
    return dict(CONFIG.reels.get("swear_rule", {}) or {})


def cfg_passes() -> list[str]:
    """MP3 bitrates for the Scribe passes ('' = ffmpeg's default, about 32 kbps at 16 kHz mono)."""
    p = _cfg().get("stt_bitrates")
    return [str(x) for x in p] if p else ["128k", ""]


def swear_spans(words: list[dict], pad: float = 0.06) -> list[tuple[float, float]]:
    """(start, end) of each spoken swear word, slurs included, padded and merged."""
    from agents.content import _UNSAFE_RE, _SLUR_RE
    spans = []
    for w in words:
        t = str(w.get("text", "")).strip(" .,!?;:\"'()[]")
        if t and (_UNSAFE_RE.fullmatch(t) or _SLUR_RE.fullmatch(t)):
            spans.append((max(0.0, float(w["start"]) - pad), float(w["end"]) + pad))
    spans.sort()
    out: list[tuple[float, float]] = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def bleep_swears(clip: Path, out: Path) -> tuple[Path, int]:
    """(clip to use, number of words beeped). Returns the input clip when nothing was beeped."""
    from core import elevenlabs, ffmpeg
    clip, out = Path(clip), Path(out)
    exe = ffmpeg.ffmpeg_bin()
    if not exe or not clip.exists():
        return clip, 0
    try:
        # TWO PASSES, two encodings (real GTA 6 test, 2026-11-20): over gunfire Scribe heard the
        # same line as "Holy shit, bitch!" from a 128 kbps copy and "Fuck this shit, bitch!" from
        # a ~32 kbps one. A word either pass hears as a swear gets beeped.
        words, any_ok = [], False
        with tempfile.TemporaryDirectory() as tmp:
            for i, br in enumerate(cfg_passes()):
                aud = Path(tmp) / f"a{i}.mp3"
                r = subprocess.run([exe, "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1",
                                    "-ar", "16000", *(["-b:a", br] if br else []), str(aud)],
                                   capture_output=True, timeout=300)
                if r.returncode != 0 or not aud.exists() or aud.stat().st_size < 1024:
                    return clip, 0                              # silent / no audio track
                w = elevenlabs.speech_to_text_words(aud)
                if w is not None:
                    any_ok = True
                    words += w
        if not any_ok:
            words = None
        if words is None:                            # STT down: say so, a swear may slip through
            print("[bleep] speech-to-text unavailable - clip NOT checked for swear words.",
                  flush=True)
            try:
                from core import notify
                notify.telegram(f"KG swear beep skipped: speech-to-text failed for {clip.name}, "
                                "so this GTA 6 reel posts without the word check.")
            except Exception:
                pass
            return clip, 0
        if not words:
            return clip, 0
        spans = swear_spans(words)
        if not spans:
            return clip, 0
        from agents.content import _UNSAFE_RE, _SLUR_RE
        hit = [f"{str(w['text']).strip()}@{float(w['start']):.1f}s" for w in words
               if (_UNSAFE_RE.fullmatch(str(w['text']).strip(" .,!?;:\"'()[]"))
                   or _SLUR_RE.fullmatch(str(w['text']).strip(" .,!?;:\"'()[]")))]
        hit = list(dict.fromkeys(hit))               # both passes usually hear the same word
        print(f"[bleep] beeping {len(hit)} word(s): {', '.join(hit)}", flush=True)
        cfg = _cfg()
        hz = float(cfg.get("beep_hz", 1000))
        vol = float(cfg.get("beep_volume", 0.35))
        on = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
        dur = float(ffmpeg.duration(clip) or (spans[-1][1] + 1))
        graph = (f"[0:a]volume='if({on},0,1)':eval=frame[m];"
                 f"aevalsrc='if({on},{vol:g}*sin(2*PI*{hz:g}*t),0)':s=48000:d={dur:.3f}[b];"
                 f"[m][b]amix=inputs=2:normalize=0:duration=first[a]")
        r = subprocess.run([exe, "-v", "error", "-y", "-i", str(clip), "-filter_complex", graph,
                            "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                            "-b:a", "192k", "-movflags", "+faststart", str(out)],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not out.exists():
            print(f"[bleep] ffmpeg failed - clip left as is: {(r.stderr or '')[-300:]}", flush=True)
            return clip, 0
        return out, len(spans)
    except Exception as e:
        print(f"[bleep] failed ({e!r}) - clip left as is.", flush=True)
        return clip, 0
