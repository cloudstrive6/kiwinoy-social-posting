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

from agents.content import (_observe_clip, _scan_subtitles, _strip_md, _text,  # noqa: E402
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
# seconds of dialogue either side of the on-screen window, read for CONTEXT only
CTX_PAD = 10.0


class CardRefused(RuntimeError):
    """The card could not be supported by the evidence. A normal exception, NOT SystemExit:
    SystemExit skipped past every caller's `except Exception` and aborted the whole posting
    run, so one unsupported sentence cost the slot on every platform (bench 2026-10-08)."""


def log(m: str) -> None:
    print(f"[lore-short] {m}", flush=True)


def research_scene(observation: str, subtitles: str, gname: str) -> str:
    """What the INTERNET says about THIS scene — Reddit threads, wikis, interviews, analysis.

    The card used to be limited to what the frames and subtitles show plus the lore bible,
    so the best it could do was explain the moment. The material that actually earns a
    'did you notice' short is the thing players argue about on r/SpidermanPS4, the cut
    content a wiki records, the line a developer explained in an interview (user's idea,
    2026-10-08). Returns a short evidence block, or '' when nothing specific turns up.
    """
    from core import claude_code
    prompt = (
        f"Research ONE specific scene from {gname} on the web and report what you find.\n\n"
        f"THE SCENE, as it appears on screen:\n{observation}\n\n"
        + (f"{subtitles}\n\n" if subtitles else "")
        + "Search Reddit (the game's subreddit and r/gaming), wikis, fandom pages, news "
        "articles, developer interviews and video essays for THIS scene specifically.\n"
        "Report only findings a casual player would NOT know from watching it once:\n"
        "- trivia, cut content, a detail the devs confirmed or explained\n"
        "- a popular fan reading, theory or argument about this moment\n"
        "- a connection to a later event, another game, or the comics the scene is setting up\n"
        "- voice acting, motion capture or writing notes about this specific scene\n\n"
        "RULES:\n"
        "- every line must be about THIS scene, not the game in general. A fact about the "
        "whole game is worthless here\n"
        "- say where each one comes from (subreddit, wiki, interview, article)\n"
        "- mark a fan theory as a fan theory. Never present speculation as confirmed\n"
        "- invent NOTHING. If the search turns up nothing specific, reply with exactly NONE\n\n"
        "Reply with up to 4 short bullet lines, or NONE."
    )
    try:
        out = (claude_code.run(prompt, web=True, timeout=300) or "").strip()
    except Exception as e:
        log(f"scene research unavailable ({e!r}) — writing from the clip alone.")
        return ""
    if not out or out.strip().upper().startswith("NONE"):
        log("scene research: nothing specific to this scene.")
        return ""
    out = "\n".join(_strip_md(l) for l in out.splitlines() if l.strip())[:1800]
    log(f"scene research:\n{out}")
    return out


def _write_card(observation: str, subtitles: str, game: str, gname: str, avoid: str = "",
                research: str = "") -> dict:
    """The card: a short EYEBROW line + the long body text, grounded in this clip."""
    from core import lore
    bible = lore.lore_for(game) or ""
    prompt = (
        f"You write 'did you notice' cards for {gname} gameplay shorts.\n\n"
        f"WHAT IS ON SCREEN:\n{observation}\n\n"
        + (f"{subtitles}\n\n" if subtitles else "")
        + (f"GAME LORE (for context — never contradict it):\n{bible[:3000]}\n\n" if bible else "")
        + (f"WHAT PLAYERS AND WRITERS SAY ABOUT THIS SCENE (researched online — Reddit, "
           f"wikis, interviews):\n{research}\n\nIf one of these findings is genuinely "
           "surprising, MAKE IT THE CARD. A detail players argue about, cut content, a line "
           "the devs explained — that is far better than anything you can infer from the "
           "frames. Attribute a fan reading as one ('fans still argue', 'players noticed'), "
           "never as fact, and use a finding only if it fits THIS moment.\n\n"
           if research else "")
        + "Write a card about THIS moment. Follow the PROVEN SHAPE of this format exactly — "
        "four beats, in this order, as ONE paragraph:\n"
        f"  1. CONTEXT: open with 'In {gname}' and the situation, in a few words.\n"
        "  2. THE DETAIL: the specific thing worth noticing — what someone SAYS or DOES and "
        "what it MEANS. This is the heart of the card.\n"
        "  3. THE VERDICT: a short punchy reaction to that detail ('That is ice cold.').\n"
        "  4. THE COMPARISON: tie it to something the audience knows — another moment in THIS "
        "game's story, or a universal gamer experience ('the kind of parry every Souls player "
        "dreams about'). This beat is OPINION and is meant to be subjective. Name a DIFFERENT "
        "game only when the parallel is exact and you say what the parallel IS — a name-drop "
        "that only half-fits this moment reads as filler, so prefer this game.\n\n"
        f"- \"body\": all four beats, {WORDS_MIN}-{WORDS_MAX} WORDS. The length IS the format: "
        "it must take ~15 seconds to read against an 8-second video so the viewer loops it. "
        "Plain spoken English, present tense, no hype words, no emojis, no hashtags.\n"
        "- \"highlight\": a SHORT phrase (2-6 words) copied EXACTLY from your body — the pivot "
        "of beat 2, coloured gold on screen.\n"
        "- \"comment\": one short funny/knowing reaction line, like a top YouTube comment on "
        "this moment (max 90 chars). Dry humour, no emojis, no hashtags.\n\n"
        "THE CARD EXPLAINS, IT NEVER NARRATES THE PICTURE. The viewer is watching the same "
        "footage, so telling them what is on screen is worthless — a card that reads like a "
        "scene description is a FAILED card. Give them what they CANNOT see: what the line "
        "means, what it sets up, what it costs someone later. NEVER make clothing, hair, "
        "lighting, colour, the camera, the UI, an on-screen caption or a character's face the "
        "POINT of the card. Never write 'the scene opens on', 'watch his face', 'a teen in a "
        "grey t-shirt', 'a man in a lab coat', 'in a green-lit lab'. If the only thing you can "
        "say about this moment is what it looks like, you have NO card — say that instead of "
        "padding the body with description.\n\n"
        "ACCURACY IS EVERYTHING — a gaming audience catches invented trivia instantly:\n"
        "- use ONLY what the screen and the subtitles above show, plus the lore bible\n"
        "- never invent a developer intention, a camera trick, a statistic or a hidden detail "
        "you cannot see in the evidence. Beats 3 and 4 are opinion and comparison, which is "
        "fine — but beats 1 and 2 must be literally true of this clip\n"
        "- you MAY name a character whose subtitle speaker label appears\n"
        "- do not quote a line verbatim if it contains profanity; describe it instead\n"
        "- NEVER invent a NUMBER or a DURATION — no 'five years later', 'after three days', "
        "'the only time in the series' — unless that exact figure is in the lore bible or on "
        "screen. Fans check these. Say 'years later' or 'for a long time' instead\n"
        "- the COMMENT line is posted too and is held to the same standard; it may be funny, "
        "but it may not state anything untrue\n"
        + (f"\nA PREVIOUS attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + ('\nReturn ONLY JSON: {"body": "the paragraph", "highlight": "exact phrase from the '
           'body", "comment": "the reaction line"}')
    )
    try:
        d = extract_json(_text(prompt, timeout=240)) or {}
        return {"highlight": sanitize(str(d.get("highlight", ""))).strip()[:60],
                "comment": sanitize(str(d.get("comment", ""))).strip()[:90],
                "body": re.sub(r"\s+", " ", sanitize(str(d.get("body", "")))).strip()}
    except Exception as e:
        log(f"card writer failed ({e!r})")
        return {}


# Wording that only ever appears when the writer has narrated the footage instead of
# explaining it. A YouTube Short shipped "the scene opens on a caption reading TWO YEARS AGO,
# in a green-lit Oscorp lab. Harry, a teen in a grey-green t-shirt..." — the viewer can SEE
# all of that; the card's whole job is the part they cannot (user, 2026-10-08).
_DESCRIBES = (
    "the scene opens", "the camera", "the shot ", "this shot", "the frame", "on screen",
    "a caption reading", "the caption reads", "text on screen", "watch his face",
    "watch her face", "watch their face", "in the background", "we see ", "you can see",
    "wearing a", "in a grey", "in a green", "in a blue", "in a red", "in a black",
    "in a white", "t-shirt", "lab coat", "-lit ", "glances aside", "looks down,",
)


def card_shape_ok(body: str) -> tuple[bool, str]:
    """Reject a card that describes the picture instead of explaining the moment."""
    low = " " + re.sub(r"\s+", " ", body or "").lower() + " "
    hits = [p for p in _DESCRIBES if p in low]
    if hits:
        return False, f"describes the footage ({', '.join(hits[:3])})"
    return True, ""


def _write_caption(card: dict, gname: str, avoid: str = "") -> dict:
    """A SHORT caption that ELABORATES on the card — never a copy of it (user, 2026-10-08).
    Their own sample for a Harry/Norman card: 'The father who would do everything to save his
    son, even if it endangers everyone, including his own son.'"""
    prompt = (
        f"This {gname} short carries an on-screen card:\n\n{card.get('body', '')}\n\n"
        "Write the POST CAPTION for it. The caption does NOT repeat the card — the viewer is "
        "already reading that. It names the THEME underneath the moment in the writer's own "
        "words, so it rewards someone who just read the card.\n"
        "- ONE sentence, 12-28 words. Plain English. No emojis, no hashtags, no quotes.\n"
        "- stay CONCRETE about who this is about ('The father who...', 'A man who...'). Plain "
        "words beat literary ones — no 'indistinguishable from', no abstract nouns stacked up\n"
        "- never reuse a phrase from the card; never start with 'In " + gname + "'\n"
        "- state nothing the card does not support\n"
        "Example of the right register, for a card about a father promising never to let his "
        "dying son go: 'The father who would do everything to save his son, even if it "
        "endangers everyone, including his own son.'\n"
        + (f"\nA previous attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + "\nAlso write the YOUTUBE TITLE for the same short: 4-10 words, under 60 "
        "characters, a curiosity gap that makes someone tap. It is NOT the caption and NOT a "
        "full sentence with a full stop; no game name (it gets appended), no hashtags, no "
        "quotes, and no tease the card does not pay off. Good shape: 'The one word that costs "
        "Harry everything'.\n"
        + '\nReturn ONLY JSON: {"caption": "the sentence", "title": "the short title"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=150)) or {}
        return {k: re.sub(r"\s+", " ", sanitize(str(d.get(k, "")))).strip().strip('"')
                for k in ("caption", "title")}
    except Exception as e:
        log(f"caption writer failed ({e!r})")
        return {}


def _caption_ok(caption: str, card: dict) -> tuple[bool, str]:
    """Short, and genuinely NOT a copy: no 6-word run shared with the card body."""
    words = caption.split()
    if not (8 <= len(words) <= 34):
        return False, f"{len(words)} words — needs one sentence of 12-28"
    body_words = [_norm_word(w) for w in card.get("body", "").split()]
    runs = {tuple(body_words[i:i + 6]) for i in range(max(0, len(body_words) - 5))}
    cw = [_norm_word(w) for w in words]
    for i in range(max(0, len(cw) - 5)):
        if tuple(cw[i:i + 6]) in runs:
            return False, "copies a phrase straight out of the card"
    if caption.strip().lower() == (card.get("comment", "") or "").strip().lower():
        return False, "same as the comment line"
    return True, ""


def _title_ok(title: str) -> bool:
    """A YouTube title must survive ' | <Game> #Shorts' inside 100 chars without being cut
    mid-sentence — a lore post has no on-screen hook, so this IS the title (user, 2026-10-08)."""
    n = len(title.split())
    return bool(title) and 3 <= n <= 12 and len(title) <= 62 and not title.endswith(".")


def lore_post_text(card: dict, gname: str) -> tuple[str, str]:
    """(caption, title) for a lore post: the caption elaborates, the title teases. Neither
    is ever a copy of the card."""
    cap_out, title_out, why = "", "", ""
    for _ in range(2):
        d = _write_caption(card, gname, avoid=why)
        cap, title = d.get("caption", ""), d.get("title", "")
        if title and _title_ok(title) and not unsafe_terms(title) and not title_out:
            title_out = title
        if cap and not cap_out:
            ok, why = _caption_ok(cap, card)
            if ok and not unsafe_terms(cap):
                cap_out = cap
            else:
                log(f"caption rejected ({why or 'unsafe wording'}); rewriting.")
        if cap_out and title_out:
            break
    # The comment line is already short, on-topic and fact-checked — better than shipping
    # the whole card body as the caption.
    cap_out = cap_out or (card.get("comment", "") or "").strip()
    if not title_out:      # trim the caption on a word boundary rather than mid-sentence
        words, title_out = cap_out.split(), ""
        for w in words:
            if len(f"{title_out} {w}".strip()) > 58:
                break
            title_out = f"{title_out} {w}".strip()
        title_out = title_out.rstrip(",;:.") or gname
    return cap_out, title_out


def _check_card(card: dict, observation: str, subtitles: str, gname: str,
                game: str = "", research: str = "") -> tuple[bool, str]:
    """Adversarial check: every claim must come from the clip, the subtitles or the lore.
    The BIBLE is included (it was not, so a wrong 'five years' sailed through with no
    timeline to check it against — user, 2026-10-07)."""
    from core import lore as _lore
    bible = (_lore.lore_for(game) if game else "") or ""
    prompt = (
        f"You are a strict fact-checker for a {gname} gameplay card. A gaming audience calls "
        "out invented trivia, so be rigorous.\n\n"
        + (f"GAME LORE BIBLE (authoritative — check any date, duration or who-did-what "
           f"against THIS):\n{bible[:3500]}\n\n" if bible else "")
        + f"EVIDENCE — what is on screen:\n{observation}\n\n"
        + (f"RESEARCHED CONTEXT for this scene (Reddit, wikis, interviews). A claim that "
           f"matches this IS supported — but a fan theory must still be worded as one, and "
           f"anything here that is not about THIS scene supports nothing:\n{research}\n\n"
           if research else "")
        + (f"{subtitles}\n\n" if subtitles else "")
        # The COMMENT ships on the video too, and it was NOT being checked — that is where an
        # invented 'five years' reached a live TikTok post (user, 2026-10-07). Check it all.
        + f"THE CARD:\n{card.get('body', '')}\n\n"
        + f"THE COMMENT LINE (also posted, check it the same way):\n"
          f"{card.get('comment', '(none)')}\n\n"
        "Mark it BAD only for a FACTUAL claim the evidence does not support: an invented "
        "detail, a developer/design intention, a camera or animation claim you cannot verify, "
        "a character who is not shown or named, a misquoted or mis-attributed line, or an "
        "event outside this clip presented as happening in it.\n"
        "The card deliberately ENDS with a verdict and a comparison ('that is ice cold', 'the "
        "kind of parry every Souls player dreams about'). Those are OPINION — do NOT flag "
        "them for being subjective. DO flag a comparison that implies something untrue about "
        "this clip (likening it to a famous death when nobody dies here), or that name-drops "
        "another game's character without a parallel that actually holds. "
        "Do not flag ordinary re-telling of what is shown, or established series lore. "
        "Flag only something stated as fact that is not true.\n"
        "ALWAYS flag an invented NUMBER or DURATION — a year, a count, 'five years later', "
        "'the only time in the series' — unless that exact figure is in the bible or on "
        "screen. Check every span against the bible's TIMELINE.\n"
        "ALSO CHECK THE READING, NOT JUST THE FACTS. A sentence can be traceable to a line "
        "of dialogue and still be BACKWARDS about the story. Hold the card's interpretation "
        "against what the bible says these characters WANT and DO: if the card has someone "
        "acting against their established motive — a father who refuses to lose his son "
        "described as 'agreeing to let his son die', a character said to give up on "
        "something the story shows them never giving up on — that is a FACTUAL error about "
        "the game and you must flag it, however well the individual words match the "
        "subtitles (user, 2026-10-09).\n"
        'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=200))
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


def _norm_word(w: str) -> str:
    return re.sub(r"[^\w']", "", w).lower()


def _highlight_indices(body: str, highlight: str) -> set:
    """Indices of the body's words covered by the highlight PHRASE (contiguous match).
    Matching word-by-word lit up every stray 'a' and 'not' in the paragraph."""
    hw = [_norm_word(w) for w in (highlight or "").split() if _norm_word(w)]
    bw = [_norm_word(w) for w in body.split()]
    if not hw or len(hw) > len(bw):
        return set()
    for i in range(len(bw) - len(hw) + 1):
        if bw[i:i + len(hw)] == hw:
            return set(range(i, i + len(hw)))
    return set()


def _draw_highlighted(d, x: int, y: int, line: str, hl_idx: set, f_norm, f_hl,
                      start_word: int = 0) -> int:
    """Draw a line word by word, colouring only the words inside the highlight phrase.
    Returns the running word index after this line."""
    i = start_word
    for word in line.split(" "):
        hit = i in hl_idx
        font = f_hl if hit else f_norm
        d.text((x, y), word, font=font, fill=(255, 209, 102, 255) if hit else (255, 255, 255, 255))
        x += d.textlength(word + " ", font=font)
        i += 1
    return i


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

    hl_idx = _highlight_indices(card["body"], card.get("highlight", ""))
    f_body, f_hl = lay["f_body"], _font(46, "ExtraBold")
    y, wi = panel_top + inner, 0
    for ln in lay["body_lines"]:                    # centred, like the sample
        w = d.textlength(ln, font=f_body)
        wi = _draw_highlighted(d, int((W - w) / 2), y, ln, hl_idx, f_body, f_hl, wi)
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
        d.text((pad + inner + s + 16, cy + 12), "@kiwinoygaming", font=f_handle,
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
        # EVIDENCE MUST BE THE MOMENT ON SCREEN. Observing/scanning the whole source file
        # wrote a card about a part of the recording the viewer never sees: an 8s window of
        # the Sandman aftermath got a card about the Web Wings from minutes later in the same
        # file (bench 2026-10-08). Frames come from the rendered SEGMENT; subtitles come from
        # the segment plus a short lead-in/out, flagged as context only.
        with tempfile.TemporaryDirectory() as tmp:
            cands = frames.extract_candidates(seg, Path(tmp), n=max(6, observe_frame_count(dur)))
            observation = _observe_clip(cands, gname, dur)
            ctx_start = max(0.0, start - CTX_PAD)
            ctx = Path(tmp) / "context.mp4"
            subprocess.run([ff, "-y", "-v", "error", "-ss", f"{ctx_start:.2f}",
                            "-t", f"{dur + CTX_PAD * 2:.2f}", "-i", str(clip),
                            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                            "-an", str(ctx)], check=False)
            subs = _scan_subtitles(ctx if ctx.exists() else seg, gname)
        if subs:
            subs = (f"{subs}\n(These lines are from the {dur + CTX_PAD * 2:.0f}s AROUND the "
                    f"moment; only the middle {dur:.0f}s are ON SCREEN. Use the rest for "
                    "context only — never describe it as happening in the clip.)")
        # What the internet knows about THIS scene beats anything inferable from the frames,
        # so research it first and let the writer build the card on a finding (user's idea,
        # 2026-10-08). Off with reels.gameplay.lore.research: false.
        lcfg = (CONFIG.reels.get("gameplay", {}) or {}).get("lore", {}) or {}
        research = (research_scene(observation, subs, gname)
                    if bool(lcfg.get("research", True)) else "")

        def _judge(c: dict) -> tuple[bool, str]:
            """Both gates: it must EXPLAIN (not narrate the picture) and be true."""
            shape_ok, shape_why = card_shape_ok(c.get("body", ""))
            if not shape_ok:
                return False, (f"{shape_why} — the viewer can already see that. Explain what "
                               "the moment MEANS instead.")
            return _check_card(c, observation, subs, gname, game, research)

        card = _write_card(observation, subs, game, gname, research=research)
        if card.get("body"):
            ok, why = _judge(card)
            if not ok:
                log(f"card rejected ({why}); rewriting.")
                card2 = _write_card(observation, subs, game, gname, avoid=why,
                                    research=research)
                if card2.get("body") and _judge(card2)[0]:
                    card = card2
                else:
                    raise CardRefused("second card also rejected — not posting "
                                     "invented lore")
        if not card.get("body"):
            raise CardRefused("no card text was written")
        bad = unsafe_terms(" ".join((card["body"], card.get("comment", ""))))
        if bad:
            log(f"card contains advertiser-unsafe wording ({', '.join(bad)}) — rewriting body")
            card["body"] = re.sub(r"\b(?:%s)\b" % "|".join(map(re.escape, bad)), "", card["body"])
            card["body"] = re.sub(r"\s+", " ", card["body"]).strip()
        # The POST caption is written here, from the finished card, so every caller (the
        # reels track, the FB lore path, the CLI) posts the short elaboration instead of
        # re-posting the card text (user, 2026-10-08).
        card["caption"], card["title"] = lore_post_text(card, gname)
        log(f'caption: {card["caption"]}')
        log(f'title: {card["title"]}')

    words = len(card["body"].split())
    log(f'highlight: {card.get("highlight", "")!r} | comment: {card.get("comment", "")!r}')
    log(f'body ({words} words, ~{words / 3.5:.0f}s to read vs a {dur:.0f}s video): {card["body"]}')
    (outdir / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    (outdir / "card.txt").write_text(
        f'{card["body"]}\n\n@kiwinoygaming: {card.get("comment", "")}\n', encoding="utf-8")

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
                    "-t", f"{dur:.2f}", "-r", "60", "-c:v", "libx264", "-crf", "20",
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
    try:
        build(clip, a.game, a.start, a.dur, a.text, outdir, card)
    except CardRefused as e:
        log(f"refused: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
