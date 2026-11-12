"""Motion-graphics layers for KG analysis long-forms (2026-11-12).

Every graphic is drawn with Pillow as one or more transparent 1920x1080 PNG layers, each with a
start and end time inside its beat; the renderer fades them over the footage with ffmpeg. A
graphic that "builds" (a counter ticking, a strip lighting up, a ring of memories whitening) is
a short run of layers. Specs live in data/analysis/<game>/gfx.json, keyed by the GFX cue id.

    layers(spec, beat_seconds, workdir, grab) -> [(png_path, start, end, fade_in, fade_out)]

`grab(clip, second)` returns a PIL image of a source frame (used by the memory ring).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080
ORANGE = (255, 112, 28, 255)
RED = (226, 38, 38, 255)
WHITE = (255, 255, 255, 255)
INK = (12, 12, 16, 255)
PAPER = (237, 227, 209, 255)
GREY = (120, 120, 128, 255)

_FONT_CACHE: dict = {}


def _first(paths: list[str]) -> str | None:
    for p in paths:
        if Path(p).exists():
            return p
    return None


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    if kind == "display":
        path = str(ROOT / "assets/fonts/anton/Anton-Regular.ttf")
    elif kind == "serif":
        path = _first(["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                       "C:/Windows/Fonts/georgia.ttf"])
    else:  # bold sans for labels
        path = _first(["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                       "C:/Windows/Fonts/arialbd.ttf"])
    f = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def text(d, xy, s, f, fill=WHITE, anchor="la", stroke=4):
    d.text(xy, s, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=(0, 0, 0, 220))


def tw(d, s, f) -> int:
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def gradient_bottom(im: Image.Image, top: int, alpha: int = 200) -> None:
    g = Image.new("RGBA", (W, H - top), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    for y in range(H - top):
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, int(alpha * y / (H - top))))
    im.alpha_composite(g, (0, top))


def dim(im: Image.Image, alpha: int) -> None:
    # Dark warm grey, not black: a black wash over a dark shot reads as black frames in QC
    # and on screen (Walter quote card, first full render 2026-11-12).
    im.alpha_composite(Image.new("RGBA", (W, H), (36, 32, 30, alpha)))


def save(im: Image.Image, workdir: Path, name: str) -> Path:
    p = workdir / f"{name}.png"
    im.save(p)
    return p


# ---------------------------------------------------------------- simple cards

def lower_third(s: str) -> Image.Image:
    im, d = canvas()
    gradient_bottom(im, 760, 170)
    f = font("display", 64)
    d.rectangle([110, 900, 118, 980], fill=ORANGE)
    text(d, (140, 940), s, f, anchor="lm")
    return im


def chapter(num: int, title: str) -> Image.Image:
    im, d = canvas()
    gradient_bottom(im, 640, 215)
    d.rectangle([110, 812, 118, 978], fill=ORANGE)
    text(d, (140, 832), f"CHAPTER {num}", font("label", 34), fill=ORANGE, anchor="lm", stroke=2)
    text(d, (138, 920), title, font("display", 92), anchor="lm")
    return im


def question(words: list[str], accent: int, strike: int | None = None) -> Image.Image:
    im, d = canvas()
    dim(im, 120)
    f = font("display", 150)
    gap = 40
    widths = [tw(d, w, f) for w in words]
    x = (W - sum(widths) - gap * (len(words) - 1)) // 2
    for i, w in enumerate(words):
        fill = ORANGE if i == accent else WHITE
        text(d, (x, H // 2), w, f, fill=fill, anchor="lm", stroke=6)
        if strike == i:
            d.line([(x - 10, H // 2 + 6), (x + widths[i] + 10, H // 2 - 6)], fill=RED, width=18)
        x += widths[i] + gap
    return im


def caption(s: str, pos: str = "top") -> Image.Image:
    im, d = canvas()
    f = font("label", 36)
    w = tw(d, s, f)
    y = 70 if pos == "top" else H - 130
    d.rounded_rectangle([(W - w) // 2 - 30, y - 14, (W + w) // 2 + 30, y + 58], 10,
                        fill=(0, 0, 0, 190))
    text(d, (W // 2, y + 22), s, f, anchor="mm", stroke=0)
    return im


def tag(s: str, slot: int) -> Image.Image:
    im, d = canvas()
    f = font("display", 70)
    w = tw(d, s, f)
    x, y = 120, 150 + slot * 130
    d.rectangle([x - 24, y - 50, x + w + 24, y + 54], fill=(0, 0, 0, 200))
    d.rectangle([x - 24, y - 50, x - 14, y + 54], fill=ORANGE)
    text(d, (x, y), s, f, anchor="lm", stroke=0)
    return im


def card(s: str) -> Image.Image:
    im, d = canvas()
    f = font("display", 76)
    lines = [ln.strip() + "." for ln in s.rstrip(".").split(". ")]
    h = 110 * len(lines)
    y0 = H // 2 - h // 2
    d.rectangle([0, y0 - 40, W, y0 + h + 30], fill=(0, 0, 0, 200))
    for i, ln in enumerate(lines):
        text(d, (W // 2, y0 + 50 + i * 110), ln, f, fill=WHITE if i else ORANGE, anchor="mm", stroke=0)
    return im


def quote(s: str, by: str) -> Image.Image:
    im, d = canvas()
    dim(im, 205)
    f = font("serif", 66)
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if tw(d, trial, f) > 1400 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    lines.append(cur)
    y = H // 2 - 60 * len(lines)
    for ln in lines:
        text(d, (W // 2, y), ln, f, anchor="mm", stroke=0)
        y += 110
    text(d, (W // 2, y + 30), by, font("label", 40), fill=ORANGE, anchor="mm", stroke=0)
    return im


def slam(s: str, scale: float = 1.0) -> Image.Image:
    im, d = canvas()
    dim(im, 110)
    text(d, (W // 2, H // 2), s, font("display", int(230 * scale)), fill=RED, anchor="mm", stroke=8)
    return im


# ---------------------------------------------------------------- builds

def strip(items: list[str], lit: int, shown: int) -> Image.Image:
    im, d = canvas()
    gradient_bottom(im, 760, 225)
    n = len(items)
    seg = (W - 240) // n
    y = 940
    d.line([(120, y), (W - 120, y)], fill=(255, 255, 255, 140), width=4)
    fh, fs = font("display", 44), font("label", 28)
    for i, it in enumerate(items[:shown]):
        x = 120 + i * seg
        on = i == lit
        head, _, sub = it.partition(": ")
        col = ORANGE if on else WHITE
        d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=col)
        text(d, (x - 6, y + 52), head.upper(), fh, fill=col, anchor="lm", stroke=3)
        if sub:
            text(d, (x - 4, y + 100), sub, fs, fill=(235, 235, 235, 255), anchor="lm", stroke=3)
    return im


def loop(stops: list[str], marker: int, cap: str) -> Image.Image:
    im, d = canvas()
    dim(im, 150)
    cx, cy, r = W // 2, 500, 280
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 200), width=6)
    f = font("display", 54)
    for i, s in enumerate(stops):
        a = math.radians(-90 + i * 360 / len(stops))
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        on = i == marker
        rr = 26 if on else 16
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=ORANGE if on else WHITE)
        lx = x + (70 if math.cos(a) > 0.2 else -70 if math.cos(a) < -0.2 else 0)
        ly = y + (-70 if math.sin(a) < -0.5 else 70)
        anchor = "lm" if math.cos(a) > 0.2 else "rm" if math.cos(a) < -0.2 else "mm"
        text(d, (lx, ly), s, f, fill=ORANGE if on else WHITE, anchor=anchor, stroke=4)
    text(d, (cx, cy + r + 130), cap, font("label", 36), fill=(255, 255, 255, 220), anchor="mm", stroke=0)
    return im


def counter(value: str, label: str) -> Image.Image:
    im, d = canvas()
    x, y = 1290, 330
    d.rectangle([x - 40, y - 40, x + 560, y + 250], fill=(0, 0, 0, 190))
    d.rectangle([x - 40, y - 40, x - 30, y + 250], fill=ORANGE)
    text(d, (x, y + 70), value, font("display", 150), anchor="lm", stroke=0)
    text(d, (x + 4, y + 200), label, font("label", 40), fill=ORANGE, anchor="lm", stroke=0)
    return im


def dossier(title: str, lines: list[str], stamps: int, stamp_list: list[str], foot: str | None) -> Image.Image:
    im, d = canvas()
    x0, y0, x1, y1 = 1100, 170, 1820, 900
    d.rectangle([x0, y0, x1, y1], fill=PAPER)
    d.rectangle([x0, y0, x1, y0 + 90], fill=INK)
    d.text((x0 + 40, y0 + 45), "DOSSIER", font=font("label", 40), fill=ORANGE, anchor="lm")
    d.text((x0 + 40, y0 + 170), title, font=font("display", 76), fill=INK, anchor="lm")
    for i, ln in enumerate(lines):
        d.text((x0 + 40, y0 + 270 + i * 70), ln, font=font("label", 44), fill=INK, anchor="lm")
    for i, s in enumerate(stamp_list[:stamps]):
        sx, sy = x0 + 90 + i * 210, y0 + 520
        d.rounded_rectangle([sx - 80, sy - 50, sx + 80, sy + 50], 8, outline=RED, width=7)
        d.text((sx, sy), s, font=font("display", 66), fill=RED, anchor="mm")
    if foot:
        d.text(((x0 + x1) // 2, y1 - 80), foot, font=font("display", 70), fill=RED, anchor="mm")
    return im


def split_labels(left: str, right: str, drop: str | None) -> Image.Image:
    im, d = canvas()
    f = font("display", 64)
    for cx, s, col in ((480, left, WHITE), (1440, right, ORANGE)):
        w = tw(d, s, f)
        d.rectangle([cx - w // 2 - 30, 150, cx + w // 2 + 30, 250], fill=(0, 0, 0, 210))
        text(d, (cx, 200), s, f, fill=col, anchor="mm", stroke=0)
    d.line([(W // 2, 280), (W // 2, 820)], fill=(255, 255, 255, 120), width=4)
    if drop:
        text(d, (W // 2, 930), drop, font("display", 150), fill=RED, anchor="mm", stroke=8)
    return im


def node(d, cx, cy, s, fill=(0, 0, 0, 220), col=WHITE, sub: str | None = None, edge=WHITE):
    f = font("display", 46)
    w = max(tw(d, s, f), tw(d, sub, font("label", 26)) if sub else 0)
    h = 84 if sub else 64
    d.rounded_rectangle([cx - w // 2 - 26, cy - h // 2, cx + w // 2 + 26, cy + h // 2], 12,
                        fill=fill, outline=edge, width=3)
    d.text((cx, cy - (14 if sub else 0)), s, font=f, fill=col, anchor="mm")
    if sub:
        d.text((cx, cy + 26), sub, font=font("label", 26), fill=(220, 220, 220, 255), anchor="mm")


def dashed(d, a, b, fill, width=4, dash=18):
    (x0, y0), (x1, y1) = a, b
    n = int(math.hypot(x1 - x0, y1 - y0) // dash)
    for i in range(0, n, 2):
        t0, t1 = i / n, min((i + 1) / n, 1)
        d.line([(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)],
               fill=fill, width=width)


def rel_map(stage: int) -> Image.Image:
    im, d = canvas()
    px0 = 1020
    panel = Image.new("RGBA", (W - px0, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    for x in range(W - px0):
        pd.line([(x, 0), (x, H)], fill=(0, 0, 0, min(225, int(225 * x / 160))))
    im.alpha_composite(panel, (px0, 0))
    cx = 1450
    # Essex and Team X
    node(d, cx, 200, "ESSEX", col=WHITE)
    d.line([(cx, 236), (cx, 330)], fill=WHITE, width=4)
    d.polygon([(cx - 12, 318), (cx + 12, 318), (cx, 340)], fill=WHITE)
    d.text((cx + 22, 285), "built Team X", font=font("label", 28), fill=(220, 220, 220, 255), anchor="lm")
    d.ellipse([cx - 330, 350, cx + 330, 540], outline=(255, 255, 255, 170), width=3)
    d.text((cx, 380), "TEAM X", font=font("label", 30), fill=ORANGE, anchor="mm")
    node(d, cx - 160, 465, "SABRETOOTH", sub="Victor Creed",
         col=ORANGE if stage == 3 else WHITE, edge=ORANGE if stage == 3 else WHITE)
    node(d, cx + 180, 465, "MYSTIQUE")
    if stage == 3:
        text(d, (cx - 325, 465), "NEXT?", font("display", 52), fill=ORANGE, anchor="rm", stroke=3)
    # Logan
    ly = 690
    dashed(d, (cx, 545), (cx, ly - 34), (255, 255, 255, 200))
    d.text((cx + 22, 615), "left 3 years ago", font=font("label", 28), fill=(220, 220, 220, 255), anchor="lm")
    node(d, cx, ly, "LOGAN", fill=(40, 40, 46, 235))
    if stage == 3:
        for i in range(5):
            fx, fy = cx - 200 + i * 100, ly + 90
            d.rectangle([fx - 40, fy - 23, fx + 40, fy + 23], fill=(250, 250, 250, 235))
        d.text((cx, ly + 145), "memories: blank", font=font("label", 26), fill=(230, 230, 230, 255), anchor="mm")
    if stage >= 2:
        node(d, cx + 300, ly, "JEAN", sub='"Red"', col=ORANGE, edge=ORANGE)
        d.line([(cx + 90, ly), (cx + 200, ly)], fill=ORANGE, width=5)
        node(d, cx, 900 if stage == 2 else 990, "TRASK + REAVERS", fill=(110, 10, 10, 235), edge=RED)
    return im


def memory_ring(frames: list[Image.Image], blank: int) -> Image.Image:
    im, d = canvas()
    pos = [(130, 90), (1370, 90), (130, 700), (1370, 700)]
    for i, (fr, (x, y)) in enumerate(zip(frames, pos)):
        t = fr.convert("RGBA").resize((420, 236))
        if i < blank:
            t = Image.blend(t, Image.new("RGBA", t.size, (250, 248, 240, 255)), 0.94)
        elif blank and i == blank:
            t = Image.blend(t, Image.new("RGBA", t.size, (255, 170, 90, 255)), 0.35)
        frame = Image.new("RGBA", (440, 256), (250, 248, 240, 255))
        frame.alpha_composite(t, (10, 10))
        im.alpha_composite(frame.rotate((-4, 3, 3, -3)[i], expand=True, resample=Image.BICUBIC), (x, y))
    return im


def storybook(shown: int, labels: list[str]) -> Image.Image:
    im, d = canvas()
    gradient_bottom(im, 520, 200)
    pw, ph, gap = 400, 300, 40
    x0 = (W - (4 * pw + 3 * gap)) // 2
    y0 = 650
    for i in range(shown):
        x = x0 + i * (pw + gap)
        d.rectangle([x, y0, x + pw, y0 + ph], fill=PAPER, outline=(60, 50, 40, 255), width=4)
        cx, cy = x + pw // 2, y0 + 130
        if i == 0:  # the girl, Red
            d.ellipse([cx - 36, cy - 96, cx + 36, cy - 24], fill=ORANGE)
            d.polygon([(cx, cy - 30), (cx - 70, cy + 90), (cx + 70, cy + 90)], fill=ORANGE)
        elif i == 1:  # the boy, strange and dirty
            d.ellipse([cx - 34, cy - 96, cx + 34, cy - 28], fill=GREY)
            d.rectangle([cx - 50, cy - 26, cx + 50, cy + 90], fill=GREY)
            for k in range(9):
                d.ellipse([cx - 40 + (k * 23) % 80, cy - 10 + (k * 37) % 90,
                           cx - 32 + (k * 23) % 80, cy - 2 + (k * 37) % 90], fill=(70, 60, 50, 255))
        elif i == 2:  # the dark cloud
            for ox, oy, r in ((-70, 0, 52), (0, -30, 66), (70, 0, 52), (0, 26, 58)):
                d.ellipse([cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r], fill=(55, 55, 62, 255))
        else:  # the sun
            for k in range(12):
                a = math.radians(k * 30)
                d.line([(cx + 70 * math.cos(a), cy + 70 * math.sin(a)),
                        (cx + 112 * math.cos(a), cy + 112 * math.sin(a))], fill=ORANGE, width=10)
            d.ellipse([cx - 58, cy - 58, cx + 58, cy + 58], fill=ORANGE)
        d.text((cx, y0 + ph - 38), labels[i], font=font("display", 40), fill=INK, anchor="mm")
    return im


def endscreen(nxt: str, sub: str) -> Image.Image:
    im, d = canvas()
    dim(im, 150)
    x0, y0, x1, y1 = 140, 300, 1040, 806  # 16:9 slot for YouTube's end-screen video element
    d.rectangle([x0, y0, x1, y1], outline=WHITE, width=4)
    d.text((x0, y0 - 50), "WATCH NEXT", font=font("label", 38), fill=ORANGE, anchor="lm")
    d.text(((x0 + x1) // 2, (y0 + y1) // 2 - 40), nxt, font=font("display", 52), fill=WHITE, anchor="mm")
    d.text(((x0 + x1) // 2, (y0 + y1) // 2 + 40), sub, font=font("display", 44), fill=ORANGE, anchor="mm")
    cx, cy = 1500, 553
    d.ellipse([cx - 170, cy - 170, cx + 170, cy + 170], outline=WHITE, width=4)
    d.rounded_rectangle([cx - 200, cy + 200, cx + 200, cy + 280], 40, fill=RED)
    d.text((cx, cy + 240), "SUBSCRIBE", font=font("display", 48), fill=WHITE, anchor="mm")
    d.text((cx, cy), "KG", font=font("display", 150), fill=WHITE, anchor="mm")
    return im


# ---------------------------------------------------------------- spec -> layers

def _t(spec: dict, key: str, frac_key: str, dur: float, default: float) -> float:
    if frac_key in spec:
        return float(spec[frac_key]) * dur
    v = spec.get(key, default)
    return dur + float(v) if v is not None and float(v) < 0 else float(v if v is not None else default)


def layers(spec: dict, dur: float, workdir: Path, name: str,
           grab: Callable[[int, float], Image.Image] | None = None) -> list[tuple]:
    k = spec["kind"]
    at = max(0.0, _t(spec, "at", "at_frac", dur, 0.0))
    end = min(dur, at + float(spec["dur"])) if spec.get("dur") else dur
    out: list[tuple] = []

    def one(im, s, e, fi=True, fo=True, suffix=""):
        out.append((save(im, workdir, f"{name}{suffix}"), s, e, fi, fo))

    def run(images: list[Image.Image], s: float, e: float, step: float | None = None, hold_last=True):
        n = len(images)
        step = step or (e - s) / n
        for i, im in enumerate(images):
            a = s + i * step
            b = e if (i == n - 1 and hold_last) else min(e, a + step)
            one(im, a, b, i == 0, i == n - 1, f"_{i}")

    if k == "lower":
        one(lower_third(spec["text"]), at, end)
    elif k == "chapter":
        one(chapter(spec["num"], spec["title"]), at, end)
    elif k == "question":
        one(question(spec["words"], spec.get("accent", -1), spec.get("strike")), at, end)
    elif k == "caption":
        one(caption(spec["text"], spec.get("pos", "top")), at, end)
    elif k == "tag":
        one(tag(spec["text"], spec.get("slot", 0)), at, end)
    elif k == "card":
        one(card(spec["text"]), at, end)
    elif k == "quote":
        one(quote(spec["text"], spec["by"]), at, end)
    elif k == "slam":
        run([slam(spec["text"], 1.25), slam(spec["text"])], at, end, step=0.12)
    elif k == "strip":
        items, lit = spec["items"], spec.get("lit")
        if spec.get("reveal"):
            ims = [strip(items, i, i + 1) for i in range(len(items))]
            run(ims, at, end)
        else:
            one(strip(items, lit if lit is not None else -1, len(items)), at, end)
    elif k == "loop":
        ims = [loop(spec["stops"], i, spec["caption"]) for i in range(len(spec["stops"]))]
        ims.append(loop(spec["stops"], 0, spec["caption"]))
        run(ims, at, end)
    elif k == "counter":
        target = spec["value"]
        n = int(target.replace(",", ""))
        steps = [0, 0.2, 0.45, 0.7, 0.88, 0.97, 1.0]
        ims = [counter(f"{int(n * s):,}" if s < 1 else target, spec["label"]) for s in steps]
        run(ims, at, end, step=0.16)
    elif k == "dossier":
        st = spec.get("stamps", [])
        ims = [dossier(spec["title"], spec["lines"], i, st, None) for i in range(len(st) + 1)]
        ims.append(dossier(spec["title"], spec["lines"], len(st), st, spec.get("foot")))
        run(ims, at, end)
    elif k == "split":
        drop_at = at + float(spec.get("drop_frac", 0.6)) * (end - at)
        one(split_labels(spec["left"], spec["right"], None), at, drop_at, True, False, "_0")
        one(split_labels(spec["left"], spec["right"], spec["drop"]), drop_at, end, False, True, "_1")
    elif k == "map":
        one(rel_map(int(spec["stage"])), at, end)
    elif k == "memory":
        frames = [grab(c, s) for c, s in spec["frames"]] if grab else []
        if frames:
            ims = [memory_ring(frames, b) for b in range(len(frames) + 1)]
            first = at + 0.35 * (end - at)
            one(ims[0], at, first, True, False, "_0")
            run(ims[1:], first, end)
    elif k == "storybook":
        labels = spec["labels"]
        marks = [at + float(f) * (end - at) for f in spec["panel_fracs"]]
        for i in range(len(labels)):
            s = marks[i]
            e = marks[i + 1] if i + 1 < len(labels) else end
            one(storybook(i + 1, labels), s, e, i == 0, i == len(labels) - 1, f"_{i}")
    elif k == "endscreen":
        s = max(0.0, end - float(spec.get("last", 20)))
        one(endscreen(spec["next"], spec["sub"]), s, end, True, False)
    else:
        raise ValueError(f"unknown gfx kind {k}")
    return out


def thumbnail(frame: Image.Image, words: str, out: Path) -> Path:
    im = frame.convert("RGB").resize((1280, 720))
    im = ImageEnhance.Color(im).enhance(1.2)
    im = ImageEnhance.Contrast(im).enhance(1.08).convert("RGBA")
    g = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    for y in range(300):
        gd.line([(0, 420 + y), (1280, 420 + y)], fill=(0, 0, 0, int(190 * y / 300)))
    im.alpha_composite(g)
    d = ImageDraw.Draw(im)
    f = font("display", 150)
    parts = words.split()
    x = 50
    for i, w in enumerate(parts):
        fill = ORANGE if i == len(parts) - 1 else WHITE
        d.text((x, 650), w, font=f, fill=fill, anchor="ls", stroke_width=8, stroke_fill=(0, 0, 0, 255))
        x += tw(d, w, f) + 26
    d.rectangle([0, 700, 1280, 720], fill=RED)
    im.convert("RGB").save(out, quality=92)
    return out
