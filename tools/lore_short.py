"""LORE-CARD SHORTS — a short clip + a LONG text block people stop to read.

The format (researched 2026-10-06 from @moviemirrorbyavi + JeremyB's breakdown): the video
is ~8s but the text takes ~18s to read, so viewers loop it to finish. That records an average
view duration far longer than the video, which is what the Shorts algorithm rewards (their
numbers: ~80% stay-to-watch, ~300% watch time). The text is deliberately WORDY — a short
punchy line kills the mechanic.

Our version differs in the way that matters: THEY scrape movie clips (and bolt on a webcam
face to survive YouTube's reused-content policy); WE use our own capture, so there's nothing
to launder — and we have the game's subtitles + a lore bible, so the "fact" can be real.

    python tools/lore_short.py --clip "Wolverine (2026-09-16 01-43-07).mp4" --game wolverine
    python tools/lore_short.py --clip <path> --game wolverine --start 44 --dur 8
    python tools/lore_short.py ... --text "write my own card text"   # skip the writer

Output: output/lore-shorts/<stamp>_<game>/short.mp4 (1080x1920) + card.txt
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.content import (_observe_clip, _scan_subtitles, _text,  # noqa: E402
                            observe_frame_count, sanitize, unsafe_terms)
from core import b2_store, ffmpeg, frames  # noqa: E402
from core.config import CONFIG  # noqa: E402
from core.openai_client import extract_json  # noqa: E402

W, H = 1080, 1920
FONT_BODY = ROOT / "assets" / "fonts" / "montserrat" / "Montserrat.ttf"
FONT_HEAD = ROOT / "assets" / "fonts" / "anton" / "Anton-Regular.ttf"
LOGO = ROOT / "reels" / "assets" / "logo" / "KG Logo 2.PNG"
RED = (255, 61, 70)

# ~3.5 words/second is a comfortable silent-reading pace, so 55-70 words ~= 16-20s of reading
# against an 8s video: the viewer has to loop it, which is the whole point of the format.
WORDS_MIN, WORDS_MAX = 55, 75


def log(m: str) -> None:
    print(f"[lore-short] {m}", flush=True)


def _write_card(observation: str, subtitles: str, game: str, gname: str, avoid: str = "") -> dict:
    """The card: a short EYEBROW line + the long body text, grounded in this clip."""
    from core import lore
    bible = lore.lore_for(game) or ""
    prompt = (
        f"You write 'did you notice' cards for {gname} gameplay shorts.\n\n"
        f"WHAT IS ON SCREEN:\n{observation}\n\n"
        + (f"{subtitles}\n\n" if subtitles else "")
        + (f"GAME LORE (for context — never contradict it):\n{bible[:3000]}\n\n" if bible else "")
        + "Write a card about THIS moment with two parts:\n"
        f"- \"eyebrow\": 2-5 words, uppercase, like a label — 'DID YOU NOTICE', 'ABOUT THAT "
        "LINE', 'THE DETAIL EVERYONE MISSES'.\n"
        f"- \"body\": {WORDS_MIN}-{WORDS_MAX} WORDS. This is the whole point of the format: it "
        "must take about 18 SECONDS TO READ, so it is a short paragraph, NOT a punchy line. "
        "Explain one specific thing in this moment and why it lands — what a character says "
        "and what it reveals, what the scene sets up, how it pays off a relationship. Build "
        "it like: the setup, the specific detail, then the turn that makes the reader go 'oh'. "
        "Plain spoken English, present tense, no hype words, no emojis, no hashtags.\n\n"
        "ACCURACY IS EVERYTHING — a gaming audience catches invented trivia instantly:\n"
        "- use ONLY what the screen and the subtitles above show, plus the lore bible\n"
        "- never invent a developer intention, a camera trick, a statistic or a hidden detail "
        "you cannot see in the evidence\n"
        "- you MAY name a character whose subtitle speaker label appears\n"
        "- do not quote a line verbatim if it contains profanity; describe it instead\n"
        + (f"\nA PREVIOUS attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + '\nReturn ONLY JSON: {"eyebrow": "...", "body": "..."}'
    )
    try:
        d = extract_json(_text(prompt, timeout=180)) or {}
        return {"eyebrow": sanitize(str(d.get("eyebrow", ""))).strip().upper()[:40],
                "body": re.sub(r"\s+", " ", sanitize(str(d.get("body", "")))).strip()}
    except Exception as e:
        log(f"card writer failed ({e!r})")
        return {}


def _check_card(card: dict, observation: str, subtitles: str, gname: str) -> tuple[bool, str]:
    """Adversarial check: every claim must come from the clip, the subtitles or the lore."""
    prompt = (
        f"You are a strict fact-checker for a {gname} gameplay card. A gaming audience calls "
        "out invented trivia, so be rigorous.\n\n"
        f"EVIDENCE — what is on screen:\n{observation}\n\n"
        + (f"{subtitles}\n\n" if subtitles else "")
        + f"THE CARD:\n{card.get('eyebrow', '')}\n{card.get('body', '')}\n\n"
        "Mark it BAD if it states anything the evidence does not support: an invented detail, "
        "a developer/design intention, a camera or animation claim you cannot verify, a "
        "character who is not shown or named, a misquoted or mis-attributed line, or an event "
        "outside this clip presented as happening in it. Re-telling what IS shown or said, and "
        "established series lore, are fine.\n"
        'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=150))
        return bool(d.get("ok", True)), str(d.get("issues", "")).strip()
    except Exception:
        return True, ""


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _card_png(card: dict, out: Path, video_h: int) -> Path:
    """The text panel + eyebrow + logo, drawn once as a transparent overlay."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 72
    top = 300 + video_h + 56                      # just under the video card

    f_eye = ImageFont.truetype(str(FONT_HEAD), 52)
    f_body = ImageFont.truetype(str(FONT_BODY), 46)
    body_lines = _wrap(d, card["body"], f_body, W - pad * 2)
    line_h = 64
    panel_h = 44 + 52 + 30 + len(body_lines) * line_h + 52
    d.rounded_rectangle([pad - 32, top, W - pad + 32, top + panel_h], radius=36,
                        fill=(12, 12, 16, 232))
    y = top + 44
    d.text((pad, y), card["eyebrow"], font=f_eye, fill=RED + (255,))
    y += 52 + 30
    for ln in body_lines:
        d.text((pad, y), ln, font=f_body, fill=(238, 238, 242, 255))
        y += line_h

    if LOGO.exists():                              # small circular watermark, bottom-right
        s = 108
        logo = Image.open(LOGO).convert("RGBA")
        c = min(logo.size)
        logo = logo.crop(((logo.width - c) // 2, (logo.height - c) // 2,
                          (logo.width + c) // 2, (logo.height + c) // 2)).resize((s, s),
                                                                                Image.LANCZOS)
        mask = Image.new("L", (s * 4, s * 4), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, s * 4, s * 4], fill=255)
        logo.putalpha(mask.resize((s, s), Image.LANCZOS))
        img.alpha_composite(logo, (W - s - 48, H - s - 64))
    img.save(out)
    return out


def build(clip: Path, game: str, start: float, dur: float, text: str | None, outdir: Path) -> Path:
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
    outdir.mkdir(parents=True, exist_ok=True)
    seg = outdir / "segment.mp4"
    ff = ffmpeg.ffmpeg_bin() or "ffmpeg"
    subprocess.run([ff, "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
                    "-i", str(clip), "-an", "-c:v", "libx264", "-crf", "18",
                    "-preset", "medium", str(seg)], check=True)

    if text:
        card = {"eyebrow": "DID YOU NOTICE", "body": re.sub(r"\s+", " ", text).strip()}
    else:
        with tempfile.TemporaryDirectory() as tmp:
            cands = frames.extract_candidates(clip, Path(tmp), n=observe_frame_count(dur * 3))
            observation = _observe_clip(cands, gname, dur * 3)
        subs = _scan_subtitles(clip, gname)
        card = _write_card(observation, subs, game, gname)
        if card.get("body"):
            ok, why = _check_card(card, observation, subs, gname)
            if not ok:
                log(f"card rejected ({why}); rewriting.")
                card2 = _write_card(observation, subs, game, gname, avoid=why)
                if card2.get("body") and _check_card(card2, observation, subs, gname)[0]:
                    card = card2
                else:
                    log("second card also rejected — stopping rather than posting invented lore")
                    raise SystemExit(1)
        if not card.get("body"):
            raise SystemExit("[lore-short] no card text was written")
        bad = unsafe_terms(card["eyebrow"] + " " + card["body"])
        if bad:
            log(f"card contains advertiser-unsafe wording ({', '.join(bad)}) — rewriting body")
            card["body"] = re.sub(r"\b(?:%s)\b" % "|".join(map(re.escape, bad)), "", card["body"])
            card["body"] = re.sub(r"\s+", " ", card["body"]).strip()

    words = len(card["body"].split())
    log(f'eyebrow: {card["eyebrow"]}')
    log(f'body ({words} words, ~{words / 3.5:.0f}s to read vs a {dur:.0f}s video): {card["body"]}')
    (outdir / "card.txt").write_text(f'{card["eyebrow"]}\n\n{card["body"]}\n', encoding="utf-8")

    video_w = W - 96                               # 16:9 card, full width minus a margin
    video_h = round(video_w * 9 / 16)
    png = _card_png(card, outdir / "card.png", video_h)
    out = outdir / "short.mp4"
    # blurred fill of the clip behind + the clip as a card + the text overlay
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"gblur=sigma=38,eq=brightness=-0.22[bg];"
          f"[0:v]scale={video_w}:{video_h}[fg];"
          f"[bg][fg]overlay=(W-w)/2:300[v1];[v1][1:v]overlay=0:0,format=yuv420p[v]")
    subprocess.run([ff, "-y", "-v", "error", "-stream_loop", "-1", "-i", str(seg),
                    "-i", str(png), "-filter_complex", vf, "-map", "[v]",
                    "-t", f"{dur:.2f}", "-r", "30", "-c:v", "libx264", "-crf", "20",
                    "-preset", "medium", "-pix_fmt", "yuv420p", str(out)], check=True)
    log(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a lore-card short (clip + long read).")
    ap.add_argument("--clip", required=True, help="B2 footage name, or a local file path")
    ap.add_argument("--game", default="wolverine")
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the clip")
    ap.add_argument("--dur", type=float, default=8.0, help="short length (default 8s)")
    ap.add_argument("--text", default=None, help="use this card text instead of writing one")
    a = ap.parse_args()

    clip = Path(a.clip)
    if not clip.exists():
        cache = ROOT / "output" / ".loreshort"
        cache.mkdir(parents=True, exist_ok=True)
        got = b2_store.download_footage(
            {"name": a.clip, "key": f"footage/{a.game}/{a.clip}"}, cache)
        if not got:
            raise SystemExit(f"[lore-short] clip not found locally or on B2: {a.clip}")
        clip = Path(got)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = ROOT / "output" / "lore-shorts" / f"{stamp}_{a.game}"
    build(clip, a.game, a.start, a.dur, a.text, outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
