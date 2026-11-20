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


def beep_word(text: str, slurs_only: bool = False) -> bool:
    """True when this spoken word gets beeped: a swear word or slur that is not on the rule's
    allow list (Bryce, 2026-11-20: 'the word shit is fine'). With `slurs_only` (Shorts and Reels
    since 2026-11-21, config swear_rule.beep_swears_in_reels) only slurs are beeped."""
    from agents.content import _UNSAFE_RE, _SLUR_RE, swear_allowed
    t = str(text or "").strip(" .,!?;:\"'()[]")
    if not t:
        return False
    if _SLUR_RE.fullmatch(t):
        return True
    if slurs_only:
        return False
    return bool(_UNSAFE_RE.fullmatch(t)) and not swear_allowed(t)


def _is_swearish(text: str) -> bool:
    """Any swear word or slur, allowed ones included (they mark where to listen again)."""
    from agents.content import _UNSAFE_RE, _SLUR_RE
    t = str(text or "").strip(" .,!?;:\"'()[]")
    return bool(t) and bool(_UNSAFE_RE.fullmatch(t) or _SLUR_RE.fullmatch(t))


def _listen(exe: str, clip: Path, a: float, b: float, tmp: Path, i: int):
    """Scribe on [a, b] of the clip, word times on the clip's clock; None if STT failed."""
    from core import elevenlabs
    aud = tmp / f"w{i}.flac"
    r = subprocess.run([exe, "-v", "error", "-y", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}",
                        "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(aud)],
                       capture_output=True, timeout=300)
    if r.returncode != 0 or not aud.exists():
        return None
    w = elevenlabs.speech_to_text_words(aud)
    if w is None:
        return None
    return [{"text": x["text"], "start": x["start"] + a, "end": x["end"] + a} for x in w]


def _vote(words: list[dict], listen, dur: float, win: float = 12.0, stride: float = 6.0,
          need: int = 2, max_windows: int = 40,
          slurs_only: bool = False) -> tuple[list[dict], list[str]]:
    """Majority vote across listens. Besides the full pass (`words`), the clip is heard again in
    overlapping `win`-second pieces `stride` seconds apart, so every moment is heard about three
    times. A banned word is beeped only when at least `need` of the listens covering that moment
    hear a banned word there (overlap within 0.25 s). Real GTA 6 test, 2026-11-20: the pieces
    caught a 'bitch' the full pass heard as 'shit', and kept a 'Fuck!' that only the full pass
    imagined in a clip with no swearing.
    WHEN UNSURE, DON'T BEEP (Bryce, 2026-11-20, on a chase shout 2 of 3 listens heard as 'Fuck!':
    "if you're unsure, then don't censor the word"). So a word is beeped only when EVERY listen
    covering that moment hears a swear there (an allowed one like 'shit' counts: someone clearly
    swore) and at least `need` of them hear a banned one. One listen that heard that moment and no
    swear in it means the word is uncertain and stays (the 45 s chase stretch: the full pass heard
    "Get down! Shots fired." and nothing where two pieces heard "Fuck!"). A piece that starts or
    ends within 1.5 s of the word and heard no words at all near it abstains: it was cut in with
    no context (the confirmed "Eat shit, bitch" in a 12 s cut). Returns (confirmed words, log)."""
    listens = [(0.0, dur or 1e9, words)]
    a, i = 0.0, 0
    while a < max(dur - 3.0, 0.01) and i < max_windows:
        b2 = min(dur, a + win) if dur else a + win
        i += 1
        listens.append((a, b2, listen(a, b2, i)))
        a += stride
    banned = [(a0, b0, [w for w in ws if beep_word(w.get("text", ""), slurs_only)])
              for a0, b0, ws in listens if ws is not None]     # a failed listen casts no vote
    heard_ok = [(a0, b0, ws) for a0, b0, ws in listens if ws is not None]  # failed = no evidence
    log, out, seen = [], [], []
    for _, _, ws in banned:
        for w in ws:
            if any(abs(w["start"] - s) < 0.25 for s in seen):
                continue
            seen.append(w["start"])
            cover = [(a0, b0, bw) for a0, b0, bw in banned
                     if a0 <= w["start"] - 0.3 and w["end"] + 0.3 <= b0]
            agree = [x for _, _, bw in cover for x in bw
                     if x["start"] < w["end"] + 0.25 and x["end"] > w["start"] - 0.25]
            votes = sum(1 for _, _, bw in cover
                        if any(x["start"] < w["end"] + 0.25 and x["end"] > w["start"] - 0.25
                               for x in bw))
            doubt = 0
            for a0, b0, ws in heard_ok:
                if not (a0 <= w["start"] - 0.3 and w["end"] + 0.3 <= b0):
                    continue
                if any(_is_swearish(x.get("text", "")) and x["start"] < w["end"] + 0.25
                       and x["end"] > w["start"] - 0.25 for x in ws):
                    continue                                        # heard a swear there
                at_edge = w["start"] - a0 < 1.5 or b0 - w["end"] < 1.5
                reach = 0.25 if at_edge else 2.0
                near = any(x["start"] < w["end"] + reach and x["end"] > w["start"] - reach
                           for x in ws)
                if near or not at_edge:     # it heard this moment and no swear in it: real doubt.
                    doubt += 1              # A piece cut in under 1.5 s from the word lacks
                                            # context: it doubts only if it heard another word on
                                            # the word itself, not a stray fragment beside it.
            if votes >= need and doubt:
                log.append(f"not beeped (unsure): '{w['text']}' at {w['start']:.1f}s, {votes}/"
                           f"{len(cover)} listens heard it but {doubt} heard no swear there")
            elif votes >= need:
                out.append({"text": w["text"], "start": min(x["start"] for x in agree),
                            "end": max(x["end"] for x in agree)})
                log.append(f"BEEP '{w['text']}' at {w['start']:.1f}s ({votes}/{len(cover)} listens)")
            else:
                log.append(f"not beeped: '{w['text']}' at {w['start']:.1f}s, only {votes}/"
                           f"{len(cover)} listens heard a swear there")
    return out, log


def swear_spans(words: list[dict], pad: float = 0.06, post: float = 0.12,
                min_len: float = 0.3, slurs_only: bool = False) -> list[tuple[float, float]]:
    """(start, end) of each spoken word to beep, padded, at least `min_len` long (Scribe sometimes
    ends a word too early, which left half of 'bitch' audible), merged."""
    spans = []
    for w in words:
        if beep_word(w.get("text", ""), slurs_only):
            a = max(0.0, float(w["start"]) - pad)
            spans.append((a, max(float(w["end"]) + post, a + min_len)))
    spans.sort()
    out: list[tuple[float, float]] = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def bleep_swears(clip: Path, out: Path, slurs_only: bool = False) -> tuple[Path, int]:
    """(clip to use, number of words beeped). Returns the input clip when nothing was beeped.
    `slurs_only`: beep slurs but leave ordinary swear words (Shorts and Reels, 2026-11-21)."""
    from core import elevenlabs, ffmpeg
    clip, out = Path(clip), Path(out)
    exe = ffmpeg.ffmpeg_bin()
    if not exe or not clip.exists():
        return clip, 0
    try:
        # MAJORITY VOTE (real GTA 6 test, 2026-11-20). Over gunfire Scribe heard one line as "Eat
        # shit, bitch!", "Holy shit, bitch!" and "Oh, shit, shit, shit!" depending on how much audio
        # it was given, and it imagined a "Fuck!" in a clip with no swearing. Bryce: never censor a
        # word that was not a swear. So one lossless FLAC pass over the whole clip plus overlapping
        # 12 s pieces (see _vote): a word is beeped only when 2 of the ~3 listens of that moment
        # hear a banned word there, and only when no listen of it heard no swear (unsure = keep).
        with tempfile.TemporaryDirectory() as tmp:
            aud = Path(tmp) / "a.flac"
            r = subprocess.run([exe, "-v", "error", "-y", "-i", str(clip), "-vn", "-ac", "1",
                                "-ar", "16000", "-c:a", "flac", str(aud)],
                               capture_output=True, timeout=300)
            if r.returncode != 0 or not aud.exists() or aud.stat().st_size < 1024:
                return clip, 0                                  # silent / no audio track
            words = elevenlabs.speech_to_text_words(aud)
            if words:
                dur0 = float(ffmpeg.duration(clip) or 0.0)
                voted, heard = _vote(words, lambda a, b, i: _listen(exe, clip, a, b, Path(tmp), i),
                                     dur0, slurs_only=slurs_only)  # full pass + overlapping 12 s pieces
                for line in heard:
                    print(f"[bleep] {line}", flush=True)
                words = voted
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
        spans = swear_spans(words, slurs_only=slurs_only)
        if not spans:
            return clip, 0
        hit = [f"{str(w['text']).strip()}@{float(w['start']):.1f}s" for w in words
               if beep_word(w.get("text", ""), slurs_only)]
        print(f"[bleep] beeping {len(hit)} word(s): {', '.join(hit)}", flush=True)
        cfg = _cfg()
        hz = float(cfg.get("beep_hz", 1000))
        vol = float(cfg.get("beep_volume", 0.32))
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
