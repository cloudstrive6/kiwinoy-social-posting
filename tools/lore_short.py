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
import json
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
WORDS_MIN, WORDS_MAX = 45, 65


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
        + "Write a card about THIS moment. Follow the PROVEN SHAPE of this format exactly — "
        "four beats, in this order, as ONE paragraph:\n"
        f"  1. CONTEXT: open with 'In {gname}' and the situation, in a few words.\n"
        "  2. THE DETAIL: the specific thing worth noticing — what someone says or does, and "
        "the part most viewers skim past. This is the heart of the card.\n"
        "  3. THE VERDICT: a short punchy reaction to that detail ('That is ice cold.').\n"
        "  4. THE COMPARISON: tie it to something the audience knows — another moment in this "
        "game, another game, or a gamer experience ('the kind of parry every Souls player "
        "dreams about'). This beat is OPINION and is meant to be subjective.\n\n"
        f"- \"body\": all four beats, {WORDS_MIN}-{WORDS_MAX} WORDS. The length IS the format: "
        "it must take ~15 seconds to read against an 8-second video so the viewer loops it. "
        "Plain spoken English, present tense, no hype words, no emojis, no hashtags.\n"
        "- \"highlight\": a SHORT phrase (2-6 words) copied EXACTLY from your body — the pivot "
        "of beat 2, coloured gold on screen.\n"
        "- \"comment\": one short funny/knowing reaction line, like a top YouTube comment on "
        "this moment (max 90 chars). Dry humour, no emojis, no hashtags.\n\n"
        "ACCURACY IS EVERYTHING — a gaming audience catches invented trivia instantly:\n"
        "- use ONLY what the screen and the subtitles above show, plus the lore bible\n"
        "- never invent a developer intention, a camera trick, a statistic or a hidden detail "
        "you cannot see in the evidence. Beats 3 and 4 are opinion and comparison, which is "
        "fine — but beats 1 and 2 must be literally true of this clip\n"
        "- you MAY name a character whose subtitle speaker label appears\n"
        "- do not quote a line verbatim if it contains profanity; describe it instead\n"
        + (f"\nA PREVIOUS attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + ('\nReturn ONLY JSON: {"body": "the paragraph", "highlight": "exact phrase from the '
           'body", "comment": "the reaction line"}')
    )
    try:
        d = extract_json(_text(prompt, timeout=180)) or {}
        return {"highlight": sanitize(str(d.get("highlight", ""))).strip()[:60],
                "comment": sanitize(str(d.get("comment", ""))).strip()[:90],
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
        + f"THE CARD:\n{card.get('body', '')}\n\n"
        "Mark it BAD only for a FACTUAL claim the evidence does not support: an invented "
        "detail, a developer/design intention, a camera or animation claim you cannot verify, "
        "a character who is not shown or named, a misquoted or mis-attributed line, or an "
        "event outside this clip presented as happening in it.\n"
        "The card deliberately ENDS with a verdict and a comparison ('that is ice cold', 'the "
        "kind of parry every Souls player dreams about'). Those are OPINION — do NOT flag "
        "them. Do not flag ordinary re-telling of what is shown, or established series lore. "
        "Flag only something stated as fact about this clip that is not true of it.\n"
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


def _font(size: int, weight: str = "Bold"):
    """Montserrat at a real weight (the file is variable and defaults to Thin)."""
    from PIL import ImageFont
    f = ImageFont.truetype(str(FONT_BODY), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def _draw_highlighted(d, x: int, y: int, line: str, hl_words: set, f_norm, f_hl) -> None:
    """Draw a line word by word, colouring the highlight phrase gold (reference format)."""
    for word in line.split(" "):
        key = re.sub(r"[^\w']", "", word).lower()
        hit = key in hl_words
        font = f_hl if hit else f_norm
        d.text((x, y), word, font=font, fill=(255, 209, 102, 255) if hit else (255, 255, 255, 255))
        x += d.textlength(word + " ", font=font)


def _layout(card: dict, video_h: int, video_w: int) -> dict:
    """Vertical layout, imitating the proven format: TEXT CARD on top, video under it,
    a comment strip below that, and the PNGtuber reaction at the bottom."""
    from PIL import ImageDraw, Image
    d = ImageDraw.Draw(Image.new("RGB", (16, 16)))
    pad, inner = 36, 44
    f_body = _font(46, "Bold")
    body_lines = _wrap(d, card["body"], f_body, W - pad * 2 - inner * 2)
    line_h = 58
    text_h = inner * 2 + len(body_lines) * line_h
    # The comment strip is sized from the ACTUAL wrapped lines — a fixed height clipped the
    # second line outside the card (user, 2026-10-06).
    avatar, cmt_line_h = 56, 44
    comment_lines = (_wrap(d, card["comment"], _font(36, "Medium"), W - pad * 2 - inner * 2)[:3]
                     if card.get("comment") else [])
    comment_h = (18 + avatar + 18 + len(comment_lines) * cmt_line_h + 26) if comment_lines else 0
    top = 150                                       # leaves room for the Shorts UI
    return {"pad": pad, "inner": inner, "f_body": f_body, "body_lines": body_lines,
            "video_h": video_h, "video_w": video_w, "avatar": avatar,
            "comment_lines": comment_lines, "cmt_line_h": cmt_line_h,
            "line_h": line_h, "top": top, "text_h": text_h, "video_y": top + text_h,
            "comment_y": top + text_h + video_h, "comment_h": comment_h}


def _card_png(card: dict, out: Path, video_h: int, lay: dict) -> Path:
    """One transparent overlay: the top text card, the comment strip and the reaction."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad, inner = lay["pad"], lay["inner"]
    panel_top, panel_bot = lay["top"], lay["comment_y"] + lay["comment_h"]
    # one dark rounded card behind text + video + comment, like the reference
    d.rounded_rectangle([pad, panel_top, W - pad, panel_bot], radius=44, fill=(10, 10, 12, 242))
    # clear the band where the video sits underneath, or the panel would hide it
    vy0, vy1 = lay["video_y"], lay["video_y"] + lay["video_h"]
    vx0 = round((W - lay["video_w"]) / 2)
    d.rectangle([vx0, vy0, vx0 + lay["video_w"], vy1], fill=(0, 0, 0, 0))

    hl_words = {re.sub(r"[^\w']", "", w).lower()
                for w in (card.get("highlight") or "").split() if w}
    f_body, f_hl = lay["f_body"], _font(46, "ExtraBold")
    y = panel_top + inner
    for ln in lay["body_lines"]:                    # centred, like the sample
        w = d.textlength(ln, font=f_body)
        _draw_highlighted(d, int((W - w) / 2), y, ln, hl_words, f_body, f_hl)
        y += lay["line_h"]

    if lay["comment_lines"]:                        # avatar + handle + reaction line
        cy = lay["comment_y"] + 18
        s = lay["avatar"]
        if LOGO.exists():
            logo = Image.open(LOGO).convert("RGBA")
            c = min(logo.size)
            logo = logo.crop(((logo.width - c) // 2, (logo.height - c) // 2,
                              (logo.width + c) // 2, (logo.height + c) // 2)).resize(
                                  (s, s), Image.LANCZOS)
            mask = Image.new("L", (s * 4, s * 4), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, s * 4, s * 4], fill=255)
            logo.putalpha(mask.resize((s, s), Image.LANCZOS))
            img.alpha_composite(logo, (pad + inner, cy))
        f_handle, f_cmt = _font(34, "Bold"), _font(36, "Medium")
        d.text((pad + inner + s + 16, cy + 12), "@bosskg", font=f_handle,
               fill=(190, 190, 198, 255))
        for i, ln in enumerate(lay["comment_lines"]):   # same lines the height was sized from
            d.text((pad + inner, cy + s + 18 + i * lay["cmt_line_h"]), ln, font=f_cmt,
                   fill=(236, 236, 240, 255))

    react = ROOT / "assets" / "pngtuber" / "kg_idle.png"
    if react.exists():                              # our own reaction character, under the card
        r = Image.open(react).convert("RGBA")
        rh = min(340, max(160, H - panel_bot - 60))
        r = r.resize((round(r.width * rh / r.height), rh), Image.LANCZOS)
        img.alpha_composite(r, (round((W - r.width) / 2), H - rh - 40))
    img.save(out)
    return out


def build(clip: Path, game: str, start: float, dur: float, text: str | None, outdir: Path,
          card: dict | None = None) -> Path:
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
    outdir.mkdir(parents=True, exist_ok=True)
    seg = outdir / "segment.mp4"
    ff = ffmpeg.ffmpeg_bin() or "ffmpeg"
    # keep the gameplay AUDIO (per user 2026-10-06) — it carries the moment
    subprocess.run([ff, "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
                    "-i", str(clip), "-c:v", "libx264", "-crf", "18",
                    "-preset", "medium", "-c:a", "aac", "-b:a", "192k", str(seg)], check=True)

    if card:
        pass
    elif text:
        card = {"highlight": "", "comment": "", "body": re.sub(r"\s+", " ", text).strip()}
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
        bad = unsafe_terms(" ".join((card["body"], card.get("comment", ""))))
        if bad:
            log(f"card contains advertiser-unsafe wording ({', '.join(bad)}) — rewriting body")
            card["body"] = re.sub(r"\b(?:%s)\b" % "|".join(map(re.escape, bad)), "", card["body"])
            card["body"] = re.sub(r"\s+", " ", card["body"]).strip()

    words = len(card["body"].split())
    log(f'highlight: {card.get("highlight", "")!r} | comment: {card.get("comment", "")!r}')
    log(f'body ({words} words, ~{words / 3.5:.0f}s to read vs a {dur:.0f}s video): {card["body"]}')
    (outdir / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    (outdir / "card.txt").write_text(
        f'{card["body"]}\n\n@bosskg: {card.get("comment", "")}\n', encoding="utf-8")

    # The video spans the card's FULL inner width. Any narrower and the hole punched in the
    # panel shows blurred background down each side of it (user spotted those strips).
    video_w = W - 36 * 2
    video_h = round(video_w * 9 / 16)
    lay = _layout(card, video_h, video_w)
    png = _card_png(card, outdir / "card.png", video_h, lay)
    out = outdir / "short.mp4"
    # blurred fill behind + the clip inset under the text + the overlay (text/comment/reaction)
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"gblur=sigma=38,eq=brightness=-0.30[bg];"
          f"[0:v]scale={video_w}:{video_h}[fg];"
          f"[bg][fg]overlay=(W-w)/2:{lay['video_y']}[v1];"
          f"[v1][1:v]overlay=0:0,format=yuv420p[v]")
    subprocess.run([ff, "-y", "-v", "error", "-stream_loop", "-1", "-i", str(seg),
                    "-i", str(png), "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
                    "-t", f"{dur:.2f}", "-r", "30", "-c:v", "libx264", "-crf", "20",
                    "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], check=True)
    log(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a lore-card short (clip + long read).")
    ap.add_argument("--clip", required=True, help="B2 footage name, or a local file path")
    ap.add_argument("--game", default="wolverine")
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the clip")
    ap.add_argument("--dur", type=float, default=8.0, help="short length (default 8s)")
    ap.add_argument("--text", default=None, help="use this card text instead of writing one")
    ap.add_argument("--card-json", default=None,
                    help="re-render using a card.json from an earlier run (skips the writer)")
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
    card = json.loads(Path(a.card_json).read_text(encoding="utf-8")) if a.card_json else None
    build(clip, a.game, a.start, a.dur, a.text, outdir, card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
