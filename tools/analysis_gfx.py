"""Motion graphics for KG analysis long-forms (rebuilt on tools/analysis_motion.py, 2026-11-13).

Every graphic is an animation drawn frame by frame with Pillow and encoded once to a transparent
qtrle .mov cropped to its bounding box; the renderer overlays it at x,y from its start time inside
the beat (the old path faded static PNG layers in and out, which read as a stepping slideshow).
Specs live in data/analysis/<game>/gfx.json, keyed by the GFX cue id. Style and motion rules:
Bryce-Brain wiki answer kg-analysis-motion-upgrade-plan; tokens live in analysis_motion.

    build(spec, beat_seconds, grab) -> (Graphic | None, start_seconds)
    overlays(spec, beat_seconds, workdir, name, grab) -> [(mov, x, y, start, seconds)]

`grab(clip, second)` returns a PIL image of a source frame (used by the memory ring).

Kinds: lower, chapter, question, caption, tag, card, quote, slam, counter, dossier, split, map,
memory, loop, storybook, endscreen, timeline (the scrubber), and strip (drawn as a timeline).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageEnhance

import analysis_motion as M
from analysis_motion import FPS, H, W, put, seg, tin

ROOT = M.ROOT
font = M.font
# RGBA names kept for analysis_render thumbnails and analysis_brand.
WHITE = M.rgba(M.OFF)
ORANGE = M.rgba(M.ORANGE)
RED = M.rgba(M.RED)


def tw(d, s, f) -> int:
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


CAP = {"display": 0.86, "heavy": 0.72, "label": 0.72, "quote": 0.72}  # cap height per em


def cap(size: int, kind: str = "display") -> int:
    return int(round(size * CAP[kind]))


class Clock:
    """Entrance cascade length e, exit length x (about 0.6 e, ending on the last frame)."""

    def __init__(self, n: int, enter: int):
        e = int(enter)
        x = int(round(0.6 * e))
        if n < e + x + 30:  # very short graphic: squeeze both, keep the ratio
            k = max(0.3, n / (e + x + 30))
            e = max(8, int(e * k))
            x = max(5, int(round(0.6 * e)))
        self.n, self.e, self.x, self.x0 = n, e, x, n - x

    def out(self, i: int, delay: int = 0) -> float:
        return M.ease_in_cubic(seg(i, self.x0 + delay, max(1, self.x - 1 - delay)))  # 1 on the last frame


def _g(kind: str, n: int, c: Clock, draw: Callable, **meta) -> M.Graphic:
    return M.Graphic(kind, n, c.e, c.x, draw, meta)


def _centre_x(spr: M.Sprite, cx: float) -> float:
    return cx - spr.w / 2 - spr.ink[0]


def _shake(i: int, t0: int, length: int = 6, px: int = 2) -> int:
    return (px if i % 2 else -px) if t0 <= i < t0 + length else 0


# ---------------------------------------------------------------- simple cards

def g_lower(spec: dict, n: int, grab=None) -> M.Graphic:
    c = Clock(n, 30)
    s = M.text(spec["text"], M.NAME)
    x, base = 120, 950
    line = M.hline(x, base + 28, x + s.w, M.RED, M.LINK)
    band = M.band(700, 0.8)

    def draw(i):
        o = c.out(i)
        out = put(band, 0, 0, a=tin(i, 0, 24, M.ease_out_cubic) * (1 - o))
        out += put(line, 0, 0, mask=("lr", tin(i, 0, 22) * (1 - o)))
        out += put(s, x, base, mask=("rise", tin(i, 6, 24) * (1 - o)))
        return out
    return _g("lower", n, c, draw)


def g_chapter(spec: dict, n: int, grab=None) -> M.Graphic:
    num, title = spec["num"], str(spec["title"]).upper()
    lines = M.wrap_balanced(title, M.STATEMENT, "display", 1400)
    x, lh, last = 120, 104, 930
    bases = [last - lh * (len(lines) - 1 - k) for k in range(len(lines))]
    ts = [M.text(ln, M.STATEMENT) for ln in lines]
    lab = M.text(f"CHAPTER {num}", M.MIN_LABEL, "heavy", M.GREY)
    lab_base = bases[0] - cap(M.STATEMENT) - 30
    hair = M.hline(x, last + 34, x + 200, M.RED, M.LINK)
    # Ghost number: a texture rendered at the 150 token and scaled up, 8% off-white.
    ghost = M.scaled(M.text(str(num), M.SLAM, "display", M.OFF, 0.08, shadow=False), 3.6)
    gx = W - ghost.w * 0.72 - ghost.ink[0]
    band = M.band(520, 0.85)
    stg = 6
    c = Clock(n, max(34, 4 + stg * (len(lines) - 1) + 24))

    def draw(i):
        o = c.out(i)
        out = put(band, 0, 0, a=tin(i, 0, 24, M.ease_out_cubic) * (1 - o))
        g = tin(i, 0, 30)
        out += put(ghost, gx, 1040, dx=(1 - g) * 140 + o * 140, a=min(1, g * 2) * (1 - o))
        out += put(lab, x, lab_base, mask=("rise", tin(i, 0, 18) * (1 - o)))
        for k, (t, b) in enumerate(zip(ts, bases)):
            out += put(t, x, b, mask=("rise", tin(i, 4 + stg * k, 24) * (1 - o)))
        out += put(hair, 0, 0, mask=("lr", tin(i, 14, 20) * (1 - o)))
        return out
    return _g("chapter", n, c, draw)


def g_question(spec: dict, n: int, grab=None) -> M.Graphic:
    words, acc, strike = spec["words"], spec.get("accent", -1), spec.get("strike")
    small = [w.islower() and len(w) <= 3 for w in words]
    sprs = [M.text(w, M.STATEMENT if sm else M.SLAM, "display",
                   M.RED if k == acc else M.GREY if sm else M.OFF) for k, (w, sm) in enumerate(zip(words, small))]
    gap = 40
    total = sum(s.w for s in sprs) + gap * (len(sprs) - 1)
    xs, x = [], (W - total) / 2
    for s in sprs:
        xs.append(x - s.ink[0])
        x += s.w + gap
    base = 540 + cap(M.SLAM) // 2
    stg, L = 4, 22
    c = Clock(n, stg * (len(words) - 1) + L)
    dim = M.dim(0.72)
    st = None
    if strike is not None and 0 <= strike < len(sprs):
        sx0, sx1 = xs[strike] + sprs[strike].ink[0] - 12, xs[strike] + sprs[strike].ink[2] + 12
        mid = base - cap(M.SLAM) / 2
        st = M.Shape(sx0, mid - 14, sx1, mid + 14).line([(sx0, mid + 10), (sx1, mid - 10)], M.RED,
                                                        M.HIGHLIGHT).done(shadow=True)
    t_strike = c.e + 12

    def draw(i):
        o = c.out(i)
        out = put(dim, 0, 0, a=tin(i, 0, 18, M.ease_out_cubic) * (1 - o))
        for k, (s, xk) in enumerate(zip(sprs, xs)):
            p = tin(i, k * stg, L)
            carry = max(12.0, 300 * 0.3 ** k)  # the first word carries the motion, later ones settle
            out += put(s, xk, base, a=min(1, p * 3) * (1 - o), dx=-(1 - p) * carry - o * 60)
        if st is not None:
            out += put(st, 0, 0, a=1 - o, dx=-o * 60, mask=("lr", tin(i, t_strike, 10, M.ease_out_cubic)))
        return out
    return _g("question", n, c, draw)


def g_caption(spec: dict, n: int, grab=None) -> M.Graphic:
    s = M.text(spec["text"], M.MIN_LABEL, "label")
    pad = 28
    w, h = s.w + 2 * pad, (s.ink[3] - s.ink[1]) + 2 * pad
    y0 = 64 if spec.get("pos", "top") == "top" else H - 64 - h
    x0 = (W - w) / 2
    pl = M.plate(x0, y0, x0 + w, y0 + h, r=10)
    tx, base = x0 + pad - s.ink[0], y0 + pad - s.ink[1]
    c = Clock(n, 26)

    def draw(i):
        o = c.out(i)
        out = put(pl, 0, 0, mask=("cx", tin(i, 0, 20) * (1 - o)))
        out += put(s, tx, base, mask=("rise", tin(i, 6, 20) * (1 - o)))
        return out
    return _g("caption", n, c, draw)


def g_tag(spec: dict, n: int, grab=None) -> M.Graphic:
    s = M.text(spec["text"], M.NAME)
    pad = 28
    x = 120
    h = cap(M.NAME) + 2 * pad
    yc = 150 + int(spec.get("slot", 0)) * 130
    y0 = yc - h / 2
    pl = M.plate(x - pad, y0, x + s.w + pad, y0 + h)
    base = y0 + pad + cap(M.NAME)
    c = Clock(n, 26)

    def draw(i):
        o = c.out(i)
        out = put(pl, 0, 0, mask=("lr", tin(i, 0, 18) * (1 - o)))
        out += put(s, x - s.ink[0], base, mask=("rise", tin(i, 4, 22) * (1 - o)))
        return out
    return _g("tag", n, c, draw)


def g_card(spec: dict, n: int, grab=None) -> M.Graphic:
    lines = [ln.strip() + "." for ln in spec["text"].rstrip(".").split(". ")]
    lh, pad = 120, 56
    ts = [M.text(ln, M.STATEMENT, "display", M.RED if (k == len(lines) - 1 and k) else M.OFF)
          for k, ln in enumerate(lines)]
    hgt = lh * (len(lines) - 1) + cap(M.STATEMENT)
    y0 = 540 - hgt / 2 - pad
    bases = [540 - hgt / 2 + cap(M.STATEMENT) + lh * k for k in range(len(lines))]
    bandp = M.plate(0, y0, W, y0 + hgt + 2 * pad)
    c = Clock(n, 6 + 8 * (len(lines) - 1) + 22)

    def draw(i):
        o = c.out(i)
        out = put(bandp, 0, 0, mask=("cy", tin(i, 0, 20) * (1 - o)))
        for k, (t, b) in enumerate(zip(ts, bases)):
            out += put(t, _centre_x(t, W / 2), b, mask=("rise", tin(i, 6 + 8 * k, 22) * (1 - o)))
        return out
    return _g("card", n, c, draw)


def g_quote(spec: dict, n: int, grab=None) -> M.Graphic:
    text = spec["text"].replace("'", "’")  # typographic apostrophes in the serif
    lines = M.wrap_balanced(text, M.NAME, "quote", 1400)  # balanced lines, no one-word widow
    lh = 92
    ts = [M.text(ln, M.NAME, "quote") for ln in lines]
    first = 540 - (len(lines) - 1) * lh / 2 - 40 + cap(M.NAME, "quote") / 2
    bases = [first + k * lh for k in range(len(lines))]
    xs = [_centre_x(t, W / 2) for t in ts]
    name = M.text(spec["by"], M.LABEL, "heavy", M.ORANGE)
    rule_w, gap = 48, 18
    nx = W / 2 - (rule_w + gap + name.w) / 2
    nbase = bases[-1] + 100
    rule = M.hline(nx, nbase - cap(M.LABEL, "heavy") / 2, nx + rule_w, M.OFF, M.HAIR, 0.8)
    stg = 8
    sp0 = stg * (len(lines) - 1) + 18
    c = Clock(n, sp0 + 22)
    key = None
    kw = str(spec.get("key", "")).strip().lower().replace("'", "’")
    if kw:
        for k, ln in enumerate(lines):
            m = re.search(r"\b" + re.escape(kw) + r"\b", ln, re.I)
            if m:
                ksp = M.text(ln[m.start():m.end()], M.NAME, "quote", M.RED, shadow=False)
                key = (k, ksp, xs[k] + M.adv(ln[:m.start()], M.NAME, "quote"))
                break
    dim = M.dim(0.78)

    def draw(i):
        o = c.out(i)
        out = put(dim, 0, 0, a=tin(i, 0, 18, M.ease_out_cubic) * (1 - o))
        for k, (t, x, b) in enumerate(zip(ts, xs, bases)):
            out += put(t, x, b, mask=("rise", tin(i, stg * k, 24) * (1 - o)))
        p = tin(i, sp0, 22)
        out += put(rule, 0, 0, a=min(1, p * 2) * (1 - o), mask=("lr", p))
        out += put(name, nx + rule_w + gap - name.ink[0], nbase, dx=-(1 - p) * 40, a=min(1, p * 2) * (1 - o))
        if key:
            k, ksp, kx = key
            out += put(ksp, kx, bases[k], a=tin(i, c.e + 6, 14, M.ease_in_out_cubic) * (1 - o))
        return out
    return _g("quote", n, c, draw)


def g_slam(spec: dict, n: int, grab=None) -> M.Graphic:
    s = M.text(spec["text"], M.SLAM, "display", M.RED)
    x, base = _centre_x(s, W / 2), 540 + cap(M.SLAM) // 2
    c = Clock(n, 18)
    dim = M.dim(0.62)

    def draw(i):
        o = c.out(i)
        out = put(dim, 0, 0, a=tin(i, 0, 18, M.ease_out_cubic) * (1 - o))
        p = tin(i, 0, 10)
        out += put(s, x, base, a=min(1, p * 3) * (1 - o), s=1.35 - 0.35 * p - 0.06 * o, dx=_shake(i, 10))
        return out
    return _g("slam", n, c, draw)


# ---------------------------------------------------------------- data

def g_counter(spec: dict, n: int, grab=None) -> M.Graphic:
    value, label = str(spec["value"]), spec["label"]
    countable = bool(re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", value))
    cell = max(M.adv(d, M.SLAM) for d in "0123456789")
    widths = [cell if ch.isdigit() else M.adv(ch, M.SLAM) for ch in value]
    num_w = sum(widths)
    lab = M.text(label, M.LABEL, "heavy")
    pad = 44
    w = max(num_w, lab.w) + 2 * pad
    x1, y0 = W - M.SAFE, 300
    x0 = x1 - w
    nx = x0 + pad
    nbase = y0 + pad + cap(M.SLAM)
    bar_y = nbase + 40
    lbase = bar_y + 30 + cap(M.LABEL, "heavy")
    y1 = lbase + pad
    pl = M.plate(x0, y0, x1, y1)
    track = M.hline(nx, bar_y, nx + num_w, M.GREY, M.HAIR, 0.7)
    fill = M.hline(nx, bar_y, nx + num_w, M.RED, M.HIGHLIGHT)
    target = int(value.replace(",", "")) if countable else 0
    nd = sum(ch.isdigit() for ch in value)
    cs, cl = 10, 54
    lab_t = cs + cl + 4
    c = Clock(n, 24)
    whole = M.text(value, M.SLAM) if not countable else None

    def digits(i: int) -> str:
        v = int(round(target * M.ease_out_cubic(seg(i, cs, cl))))
        z = iter(str(v).zfill(nd)[-nd:])
        return "".join(next(z) if ch.isdigit() else ch for ch in value)

    def draw(i):
        o = c.out(i)
        p = tin(i, 0, 24)
        dx = (1 - p) * 90 + o * 90
        a = min(1, p * 2) * (1 - o)
        out = put(pl, 0, 0, a=a, dx=dx)
        if countable:
            s = digits(i)
            sig = next((k for k, ch in enumerate(s) if ch.isdigit() and ch != "0"), len(s) - 1)
            x = nx
            for k, (ch, cw) in enumerate(zip(s, widths)):
                lead = k < sig
                spr = M.text(ch, M.SLAM, "display", M.GREY if lead else M.OFF, 0.5 if lead else 1.0)
                out += put(spr, x + (cw - M.adv(ch, M.SLAM)) / 2, nbase, a=a, dx=dx)
                x += cw
        else:
            out += put(whole, nx - whole.ink[0], nbase, a=a, dx=dx, mask=("rise", tin(i, cs, 24)))
        out += put(track, 0, 0, a=a, dx=dx)
        out += put(fill, 0, 0, a=a, dx=dx, mask=("lr", M.ease_out_cubic(seg(i, cs, cl))))
        out += put(lab, nx - lab.ink[0], lbase, a=1 - o, dx=dx, mask=("rise", tin(i, lab_t, 20)))
        return out
    meta = {"digits": digits if countable else None, "label_from": lab_t, "count_end": cs + cl,
            "num_box": (nx, nx + num_w), "value": value}
    return _g("counter", n, c, draw, **meta)


def _stamp(s: str, cx: float, cy: float, size: int = M.NAME) -> M.Sprite:
    t = M.text(s, size, "display", M.RED, shadow=False)
    pad = 28
    w, h = t.w + 2 * pad, cap(size) + 2 * pad
    sh = M.Shape(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, pad=12)
    sh.rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, outline=M.RED, width=M.LINK, r=10)
    spr = sh.done()
    spr.img.alpha_composite(t.img, (int(round(cx - w / 2 + pad - t.ink[0] - t.ax + spr.ax)),
                                     int(round(cy + cap(size) / 2 - t.ay + spr.ay))))
    return spr


def g_dossier(spec: dict, n: int, grab=None) -> M.Graphic:
    x0, y0, x1, y1 = 1100, 170, 1820, 900
    card = M.plate(x0, y0, x1, y1, col=M.OFF, a=1.0)
    head = M.plate(x0, y0, x1, y0 + 90, col=M.INK, a=1.0, shadow=False)
    lbl = M.text("DOSSIER", M.MIN_LABEL, "heavy", M.OFF, shadow=False)
    title = M.text(spec["title"], M.NAME, "display", M.INK, shadow=False)
    lines = [M.text(ln, M.LABEL, "label", M.INK, shadow=False) for ln in spec["lines"]]
    stamps_s = spec.get("stamps", [])
    widths = [M.adv(s, M.NAME) + 56 for s in stamps_s]
    gap = 34
    sx = (x0 + x1) / 2 - (sum(widths) + gap * max(0, len(widths) - 1)) / 2
    stamps = []
    for s, w in zip(stamps_s, widths):
        stamps.append(_stamp(s, sx + w / 2, y0 + 520))
        sx += w + gap
    foot = M.text(spec["foot"], M.NAME, "display", M.RED, shadow=False) if spec.get("foot") else None
    c = Clock(n, 32)
    k_all = len(stamps) + (1 if foot else 0)
    times = [max(c.e + 30, int(round(n * (k + 1) / (k_all + 2)))) for k in range(k_all)]

    def draw(i):
        o = c.out(i)
        p = tin(i, 0, 24)
        dx = (1 - p) * 140 + o * 160
        a = min(1, p * 2) * (1 - o)
        out = put(card, 0, 0, a=a, dx=dx) + put(head, 0, 0, a=a, dx=dx)
        out += put(lbl, x0 + 40, y0 + 45 + cap(M.MIN_LABEL, "heavy") / 2, a=a, dx=dx)
        out += put(title, x0 + 40 - title.ink[0], y0 + 170 + cap(M.NAME) / 2, a=a, dx=dx,
                   mask=("rise", tin(i, 6, 22)))
        for k, ln in enumerate(lines):
            out += put(ln, x0 + 40, y0 + 270 + k * 70 + cap(M.LABEL, "label") / 2, a=a, dx=dx,
                       mask=("rise", tin(i, 10 + 6 * k, 22)))
        for k, st in enumerate(stamps):
            t0 = times[k]
            if i >= t0:
                q = seg(i, t0, 4)
                out += put(st, 0, 0, a=min(1, q * 3) * a, s=1.4 - 0.4 * M.ease_out_cubic(q),
                           dx=dx + _shake(i, t0 + 4))
        if foot is not None:
            out += put(foot, _centre_x(foot, (x0 + x1) / 2), y1 - 80 + cap(M.NAME) / 2, a=a, dx=dx,
                       mask=("rise", tin(i, times[-1], 22)))
        return out
    return _g("dossier", n, c, draw)


def _split_states(spec: dict, n: int, c: Clock, td: int) -> list[tuple]:
    """Focus changes for the split screen: (frame, 'both' | 'left' | 'right'), every 7 s or so."""
    if spec.get("focus"):
        return [(0, "both")] + [(int(float(f) * n), s) for f, s in spec["focus"]]
    every = 7 * FPS
    out, side = [(0, "both")], "left"
    t = c.e + 60
    while t < td - 3 * FPS:
        out.append((t, side))
        side = "right" if side == "left" else "left"
        t += every
    out.append((td, "both"))
    t = td + 6 * FPS
    while t < c.x0 - 3 * FPS:
        out.append((t, side))
        side = "right" if side == "left" else "left"
        t += every
    return out


def g_split(spec: dict, n: int, grab=None) -> M.Graphic:
    c = Clock(n, 30)
    pad = 28

    def label(s: str) -> M.Sprite:
        head, sep, rest = s.partition(": ")
        parts = [(head + ":", M.ORANGE, 1.0), (" " + rest, M.OFF, 1.0)] if sep else [(s, M.OFF, 1.0)]
        return M.runs(parts, M.NAME)

    labs = [(480, label(spec["left"])), (1440, label(spec["right"]))]
    plates, h = [], cap(M.NAME) + 2 * pad
    for cx, s in labs:
        plates.append(M.plate(cx - s.w / 2 - pad, 150, cx + s.w / 2 + pad, 150 + h))
    base = 150 + pad + cap(M.NAME)
    divider = M.Shape(958, 290, 962, 840).line([(960, 290), (960, 840)], M.OFF, M.HAIR, 0.6).done()
    veils = [M.plate(12, 300, 956, 831, a=0.55, shadow=False), M.plate(964, 300, 1908, 831, a=0.55, shadow=False)]
    drop = M.text(spec["drop"], M.SLAM, "display", M.RED) if spec.get("drop") else None
    td = int(round(float(spec.get("drop_frac", 0.6)) * n)) if drop else n
    states = _split_states(spec, n, c, td)

    def veil(i: int, side: int) -> float:
        v = 0.0
        for t, s in states:
            if i < t:
                break
            tgt = 1.0 if (s == "left" and side == 1) or (s == "right" and side == 0) else 0.0
            v = v + (tgt - v) * M.ease_in_out_cubic(seg(i, t, 24))
        return v

    def draw(i):
        o = c.out(i)
        out = put(divider, 0, 0, mask=("cy", tin(i, 0, 24) * (1 - o)))
        for side in (0, 1):
            vl = veil(i, side)
            out += put(veils[side], 0, 0, a=vl * (1 - o))
            p = tin(i, 6, 24)
            sgn = -1 if side == 0 else 1
            dx = sgn * ((1 - p) * 140 + o * 140)
            a = min(1, p * 2) * (1 - o) * (1 - 0.5 * vl)
            cx, s = labs[side]
            out += put(plates[side], 0, 0, a=min(1, p * 2) * (1 - o), dx=dx)
            out += put(s, cx - s.w / 2 - s.ink[0], base, a=a, dx=dx)
        if drop is not None and i >= td:
            q = seg(i, td, 8)
            out += put(drop, _centre_x(drop, W / 2), 930 + cap(M.SLAM) // 2, a=min(1, q * 3) * (1 - o),
                       s=1.3 - 0.3 * M.ease_out_cubic(q), dx=_shake(i, td + 8))
        return out
    return _g("split", n, c, draw, changes=[t for t, _ in states])


# ---------------------------------------------------------------- relationship map

WOLVERINE_MAP = {
    "nodes": {"essex": ["ESSEX", None, "name"], "mystique": ["MYSTIQUE", None, "name"],
              "sabretooth": ["SABRETOOTH", "Victor Creed", "name"], "logan": ["LOGAN", None, "name"],
              "jean": ["JEAN", "“Red”", "name"], "trask": ["TRASK + REAVERS", None, "threat"]},
    "steps": {1: [["essex"], ["e_built", "teamx"], ["mystique", "sabretooth"], ["e_left", "logan"]],
              2: [["e_red", "jean"], ["trask"]],
              3: [["memories"], ["next"]]},
    "lit": {3: {1: ["sabretooth", "next"]}},
}


def _map_layout() -> dict:
    """Positions for the Wolverine map (boxes auto-size from text with 28 px padding)."""
    cx, pad = 1430, 28
    capn, caps = cap(M.LABEL), cap(M.MIN_LABEL, "label")
    els: dict = {}

    def node(i: str, top: float, centre: float | None = None, left: float | None = None) -> dict:
        lab, sub, tone = WOLVERINE_MAP["nodes"][i]
        w = max(M.adv(lab, M.LABEL), M.adv(sub, M.MIN_LABEL, "label") if sub else 0) + 2 * pad
        h = capn + 2 * pad + (14 + caps if sub else 0)
        x0 = left if left is not None else (centre if centre is not None else cx) - w / 2
        e = {"type": "node", "label": lab, "sub": sub, "tone": tone, "box": (x0, top, x0 + w, top + h)}
        els[i] = e
        return e

    essex = node("essex", 96)
    myst = node("mystique", 0)
    sab = node("sabretooth", 0)
    gy0 = essex["box"][3] + 110
    row_top = gy0 + pad + capn + 20
    row_h = max(sab["box"][3], myst["box"][3])
    row_w = (myst["box"][2] - myst["box"][0]) + 40 + (sab["box"][2] - sab["box"][0])
    gx0 = cx - row_w / 2 - pad
    gx1 = gx0 + row_w + 2 * pad
    for e, x in ((myst, gx0 + pad), (sab, gx0 + pad + (myst["box"][2] - myst["box"][0]) + 40)):
        w, h = e["box"][2] - e["box"][0], e["box"][3] - e["box"][1]
        y = row_top + (row_h - h) / 2
        e["box"] = (x, y, x + w, y + h)
    gy1 = row_top + row_h + pad
    els["teamx"] = {"type": "group", "label": "TEAM X", "box": (gx0, gy0, gx1, gy1),
                    "label_at": (gx0 + pad, gy0 + pad + caps)}
    els["next"] = {"type": "next", "at": (gx1 - pad, gy0 + pad + capn)}
    logan = node("logan", gy1 + 104)
    lb = logan["box"]
    jw = max(M.adv("JEAN", M.LABEL), M.adv("“Red”", M.MIN_LABEL, "label")) + 2 * pad
    jean = node("jean", 0, left=lb[2] + 90)
    jh = jean["box"][3] - jean["box"][1]
    jy = (lb[1] + lb[3]) / 2 - jh / 2
    jean["box"] = (lb[2] + 90, jy, lb[2] + 90 + jw, jy + jh)
    els["e_built"] = {"type": "edge", "pts": [(cx, essex["box"][3]), (cx, gy0)], "label": "built Team X",
                      "arrow": True, "dashed": False, "tone": "plain"}
    els["e_left"] = {"type": "edge", "pts": [(cx, gy1), (cx, lb[1])], "label": "left 3 years ago",
                     "arrow": False, "dashed": True, "tone": "plain"}
    els["e_red"] = {"type": "edge", "pts": [(lb[2], (lb[1] + lb[3]) / 2), (jean["box"][0], (lb[1] + lb[3]) / 2)],
                    "label": None, "arrow": False, "dashed": False, "tone": "name"}
    bw, bh, bg = 72, 42, 18
    bx = cx - (5 * bw + 4 * bg) / 2
    by = lb[3] + 28
    blocks = [(bx + k * (bw + bg), by, bx + k * (bw + bg) + bw, by + bh) for k in range(5)]
    els["memories"] = {"type": "memories", "blocks": blocks, "label": "memories: blank",
                       "label_at": (cx, by + bh + 22 + caps)}
    trask = node("trask", lb[3] + 60)
    th = trask["box"][3] - trask["box"][1]
    trask["move"] = {3: by + bh + 22 + caps + 34 - trask["box"][1]}  # stage 3 drops it under the memories
    for e in els.values():
        if e["type"] == "edge" and e["label"]:
            (ax, ay), (bx2, by2) = e["pts"]
            e["label_at"] = (ax + 22, (ay + by2) / 2 + caps / 2)
    return els


def _node_face(e: dict, state: str) -> M.Sprite:
    x0, y0, x1, y1 = e["box"]
    threat = e.get("tone") == "threat"
    if state == "act":
        col, width = (M.RED if threat else M.ORANGE), M.LINK
        lc, la, sc, sa = (M.RED if threat else M.ORANGE), 1.0, M.OFF, 0.9
    else:
        col, width = (M.RED if threat else M.GREY), M.HAIR
        lc, la, sc, sa = M.OFF, 0.72, M.GREY, 1.0
    sh = M.Shape(x0, y0, x1, y1, pad=8)
    sh.rect(x0 + width / 2, y0 + width / 2, x1 - width / 2, y1 - width / 2, outline=col, width=width, r=10)
    spr = sh.done()
    d = ImageDraw.Draw(spr.img)
    cxm = (x0 + x1) / 2
    base = y0 + 28 + cap(M.LABEL)
    d.text((cxm - M.adv(e["label"], M.LABEL) / 2 + spr.ax, base + spr.ay), e["label"],
           font=M.font("display", M.LABEL), fill=M.rgba(lc, la), anchor="ls")
    if e.get("sub"):
        d.text((cxm - M.adv(e["sub"], M.MIN_LABEL, "label") / 2 + spr.ax, base + 14 + cap(M.MIN_LABEL, "label") + spr.ay),
               e["sub"], font=M.font("label", M.MIN_LABEL), fill=M.rgba(sc, sa), anchor="ls")
    return spr


def _edge_sprite(e: dict, frac: float, col: tuple, dot: bool = True) -> M.Sprite:
    pts = e["pts"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    sh = M.Shape(min(xs) - 16, min(ys) - 16, max(xs) + 16, max(ys) + 16)
    part = M.partial(pts, frac)
    if e["dashed"]:
        sh.dashed(part, col, M.HAIR) if len(part) > 1 else None
    else:
        sh.line(part, col, M.LINK)
    if dot and frac < 1:
        hx, hy = part[-1]
        sh.circle(hx, hy, 7, fill=col)
    if frac >= 1 and e["arrow"]:
        (ax, ay), (bx, by) = pts[-2], pts[-1]
        ang = math.atan2(by - ay, bx - ax)
        tip = (bx, by)
        l, wd = 18, 11
        sh.polygon([tip, (bx - l * math.cos(ang) + wd * math.sin(ang), by - l * math.sin(ang) - wd * math.cos(ang)),
                    (bx - l * math.cos(ang) - wd * math.sin(ang), by - l * math.sin(ang) + wd * math.cos(ang))], col)
    return sh.done()


def g_map(spec: dict, n: int, grab=None) -> M.Graphic:
    """Relationship map. The layout comes from the game's gfx.json "map" key, which the renderer
    copies into each map spec as "layout" (load_specs); without one it is the Wolverine map."""
    lay = spec.get("layout")
    if isinstance(lay, dict):
        return _g_map_data(spec, n, lay)
    return _g_map_wolverine(spec, n, grab)


def _g_map_wolverine(spec: dict, n: int, grab=None) -> M.Graphic:
    stage = int(spec["stage"])
    els = _map_layout()
    steps_all = WOLVERINE_MAP["steps"]
    lit_over = WOLVERINE_MAP["lit"].get(stage, {})
    base_ids = [x for s in range(1, stage) for step in steps_all.get(s, []) for x in step]
    steps = steps_all[stage]
    # Schedule: earlier stages arrive first as context, then this stage's steps every few seconds.
    show: dict = {}
    t = 0
    for x in base_ids:
        show[x] = t
        t += 6 if els[x]["type"] == "edge" else 2
    base_end = t + 18 if base_ids else 0
    c = Clock(n, max(30, base_end))
    t1 = base_end + 12 if base_ids else 0
    internal = 60
    gap_steps = ((c.x0 - 90 - internal) - t1) / max(1, len(steps) - 1)
    gap_steps = M.clamp(gap_steps, 90, 360)
    step_t = [int(t1 + k * gap_steps) for k in range(len(steps))]
    lit_win: dict = {}
    for k, step in enumerate(steps):
        t = step_t[k]
        for x in step:
            show[x] = t
            t += 24 if els[x]["type"] == "edge" else 8
        end = step_t[k + 1] if k + 1 < len(steps) else 10 ** 9
        for x in lit_over.get(k, step):
            lit_win[x] = (step_t[k], end)
    move_t = step_t[0] if stage == 3 else None
    panel = M.side_panel(1000)

    def act(x: str, i: int) -> float:
        if x not in lit_win:
            return 0.0
        a0, a1 = lit_win[x]
        return M.ease_in_out_cubic(seg(i, a0, 18)) * (1 - M.ease_in_out_cubic(seg(i, a1, 20)))

    faces = {x: (_node_face(e, "ctx"), _node_face(e, "act")) for x, e in els.items() if e["type"] == "node"}
    fills = {x: M.plate(*e["box"], r=10) for x, e in els.items() if e["type"] == "node"}
    g = els["teamx"]
    gfill = M.plate(*g["box"], a=0.35, r=10, shadow=False)
    gfaces = []
    for col in (M.GREY, M.ORANGE):
        gfaces.append(M.Shape(*g["box"], pad=6).rect(*g["box"], outline=col, width=M.HAIR, r=10).done())
    glabs = (M.text("TEAM X", M.MIN_LABEL, "heavy", M.GREY), M.text("TEAM X", M.MIN_LABEL, "heavy", M.ORANGE))
    edge_full = {x: (_edge_sprite(e, 1, M.GREY), _edge_sprite(e, 1, M.ORANGE if e["tone"] == "name" else M.OFF))
                 for x, e in els.items() if e["type"] == "edge"}
    edge_lab = {x: (M.text(e["label"], M.MIN_LABEL, "label", M.GREY), M.text(e["label"], M.MIN_LABEL, "label", M.OFF))
                for x, e in els.items() if e["type"] == "edge" and e["label"]}
    mem = els["memories"]
    blocks = [M.plate(*b, col=M.OFF, a=0.92, shadow=False) for b in mem["blocks"]]
    memlab = M.text(mem["label"], M.MIN_LABEL, "label", M.OFF)
    nxt = M.text("NEXT?", M.LABEL, "display", M.RED)

    def ypos(x: str, i: int) -> float:
        mv = els[x].get("move", {}).get(stage)
        if mv is None or move_t is None:
            return 0.0
        return mv * M.ease_in_out_cubic(seg(i, move_t, 24))

    def draw(i):
        o = c.out(i)
        ox = o * 80
        fade = 1 - o
        p = tin(i, 0, 24)
        out = put(panel, 0, 0, dx=(1 - p) * 120 + ox, a=min(1, p * 2) * fade)
        order = [x for x in show if els[x]["type"] in ("group",)] + [x for x in show if els[x]["type"] != "group"]
        for x in order:
            t0 = show[x]
            if i < t0:
                continue
            e, w = els[x], act(x, i)
            base = x in base_ids
            if e["type"] in ("node", "group"):
                q = tin(i, t0, 18)
                sc = 0.92 + 0.08 * q
                a = min(1, q * 2) * fade
                dy = ypos(x, i)
                if e["type"] == "node":
                    out += put(fills[x], 0, 0, a=a, s=sc, dx=ox, dy=dy)
                    out += put(faces[x][0], 0, 0, a=a * (1 - w), s=sc, dx=ox, dy=dy)
                    out += put(faces[x][1], 0, 0, a=a * w, s=sc, dx=ox, dy=dy)
                else:
                    out += put(gfill, 0, 0, a=a, s=sc, dx=ox)
                    out += put(gfaces[0], 0, 0, a=a * (1 - w), s=sc, dx=ox)
                    out += put(gfaces[1], 0, 0, a=a * w, s=sc, dx=ox)
                    lx, ly = e["label_at"]
                    for k, sp in enumerate(glabs):
                        out += put(sp, lx, ly, a=a * (w if k else 1 - w), dx=ox, mask=("rise", tin(i, t0 + 6, 18)))
            elif e["type"] == "edge":
                L = 12 if base else 24
                f = M.ease_in_out_cubic(seg(i, t0, L))
                if f < 1:
                    out += put(_edge_sprite(e, f, M.OFF if e["tone"] != "name" else M.ORANGE), 0, 0, a=fade, dx=ox)
                else:
                    ctx, on = edge_full[x]
                    out += put(ctx, 0, 0, a=fade * (1 - w), dx=ox) + put(on, 0, 0, a=fade * w, dx=ox)
                if x in edge_lab:
                    q = tin(i, t0 + L, 14)
                    lx, ly = e["label_at"]
                    for k, sp in enumerate(edge_lab[x]):
                        out += put(sp, lx, ly, a=min(1, q * 2) * fade * (w if k else 1 - w), dx=ox - (1 - q) * 12)
            elif e["type"] == "memories":
                for k, b in enumerate(blocks):
                    q = tin(i, t0 + 4 * k, 16)
                    out += put(b, 0, 0, a=min(1, q * 2) * fade, s=0.6 + 0.4 * q, dx=ox)
                lx, ly = e["label_at"]
                out += put(memlab, _centre_x(memlab, lx), ly, a=fade, dx=ox, mask=("rise", tin(i, t0 + 24, 18)))
            elif e["type"] == "next":
                q = seg(i, t0, 4)
                ax, ay = e["at"]
                out += put(nxt, ax - nxt.ink[2], ay, a=min(1, q * 3) * fade, s=1.4 - 0.4 * M.ease_out_cubic(q),
                           dx=ox + _shake(i, t0 + 4))
        return out

    # Layout facts for the checks: shapes on screen at this stage and every label box.
    visible = set(show)
    shapes, labels, pads = [], [], []
    for x in visible:
        e = els[x]
        if e["type"] == "node":
            b = list(e["box"])
            mv = e.get("move", {}).get(stage, 0)
            b[1] += mv
            b[3] += mv
            shapes.append((x, tuple(b)))
            iw = max(M.adv(e["label"], M.LABEL), M.adv(e["sub"], M.MIN_LABEL, "label") if e["sub"] else 0)
            pads.append((b[2] - b[0] - iw) / 2)
        elif e["type"] == "edge" and e["label"]:
            lx, ly = e["label_at"]
            bb = M.ink(e["label"], M.MIN_LABEL, "label")
            labels.append((x, (lx + bb[0], ly + bb[1], lx + bb[2], ly + bb[3])))
        elif e["type"] == "group":
            lx, ly = e["label_at"]
            bb = M.ink("TEAM X", M.MIN_LABEL, "heavy")
            labels.append((x + ":label", (lx + bb[0], ly + bb[1], lx + bb[2], ly + bb[3])))
        elif e["type"] == "memories":
            lx, ly = e["label_at"]
            bb = M.ink(e["label"], M.MIN_LABEL, "label")
            w = bb[2] - bb[0]
            labels.append((x + ":label", (lx - w / 2, ly + bb[1], lx + w / 2, ly + bb[3])))
            for k, b in enumerate(e["blocks"]):
                shapes.append((f"block{k}", b))
        elif e["type"] == "next":
            ax, ay = e["at"]
            bb = M.ink("NEXT?", M.LABEL)
            labels.append((x, (ax - bb[2] + bb[0], ay + bb[1], ax, ay + bb[3])))
    groups = [els["teamx"]["box"]] if "teamx" in visible else []
    return _g("map", n, c, draw, shapes=shapes, labels=labels, groups=groups, pads=pads,
              step_t=step_t)


# A map described as data (gfx.json "map", 2026-11-14, Spider-Man 2). Each stage is a snapshot:
#   "nodes": {id: [cx, top] | {"at": [cx, top], "from": [cx, top], "sub": s, "sub_from": s}}
#   "edges": {id: {"from": node, "to": node, "label": s, "label_from": s, "tone": plain|name|threat,
#             "arrow": bool, "dashed": bool, "pts": [[x, y], ...], "label_side": above|below|left|right}}
#   "steps": [[id | "move:id", ...], ...]  ids not in any step are context and arrive first;
#             "move:id" slides a node from "from" to "at" and swaps sub_from / label_from for the new text.
#   "caption": text under the map (red), "lit": {step: [ids]} overrides which ids light up in a step.
# Shared "nodes" give each node its label, optional sub and tone (name, threat, ghost).

def _data_box(label: str, sub: str | None, cx: float, top: float) -> tuple:
    pad = 28
    w = max(M.adv(label, M.LABEL), M.adv(sub, M.MIN_LABEL, "label") if sub else 0) + 2 * pad
    h = cap(M.LABEL) + 2 * pad + (14 + cap(M.MIN_LABEL, "label") if sub else 0)
    return (cx - w / 2, top, cx + w / 2, top + h)


def _data_edge_pts(e: dict, boxes: dict) -> list[tuple]:
    if e.get("pts"):
        return [tuple(p) for p in e["pts"]]
    a, b = boxes[e["from"]], boxes[e["to"]]
    acx, acy, bcx, bcy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    if a[2] <= b[0] or b[2] <= a[0]:  # side by side: right edge to left edge at the shared middle
        y = (max(a[1], b[1]) + min(a[3], b[3])) / 2 if min(a[3], b[3]) > max(a[1], b[1]) else acy
        return [(a[2], y), (b[0], y)] if acx < bcx else [(a[0], y), (b[2], y)]
    x = (max(a[0], b[0]) + min(a[2], b[2])) / 2
    return [(x, a[3]), (x, b[1])] if acy < bcy else [(x, a[1]), (x, b[3])]


def _data_label_at(pts: list[tuple], text: str, side: str | None) -> tuple:
    """Baseline-left position of an edge label beside its longest segment."""
    segs = list(zip(pts, pts[1:]))
    (ax, ay), (bx, by) = max(segs, key=lambda s: math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
    bb = M.ink(text, M.MIN_LABEL, "label")
    mx, my = (ax + bx) / 2, (ay + by) / 2
    horiz = abs(bx - ax) >= abs(by - ay)
    side = side or ("above" if horiz else "right")
    if side == "above":
        return (mx - (bb[2] - bb[0]) / 2 - bb[0], my - 16 - bb[3])
    if side == "below":
        return (mx - (bb[2] - bb[0]) / 2 - bb[0], my + 16 - bb[1])
    if side == "left":
        return (mx - 22 - bb[2], my + (bb[3] - bb[1]) / 2 - bb[3])
    return (mx + 22 - bb[0], my + (bb[3] - bb[1]) / 2 - bb[3])


def _g_map_data(spec: dict, n: int, lay: dict) -> M.Graphic:
    stage = str(spec["stage"])
    st = lay["stages"][stage]
    defs = lay.get("nodes", {})
    nodes: dict = {}
    for i, v in st.get("nodes", {}).items():
        v = {"at": v} if isinstance(v, list) else dict(v)
        d = defs.get(i, {})
        lab, tone = d.get("label", i.upper()), v.get("tone", d.get("tone", "name"))
        sub = v.get("sub", d.get("sub"))
        box = _data_box(lab, sub, *v["at"])
        e = {"type": "node", "label": lab, "sub": sub, "tone": tone, "box": box}
        if "sub_from" in v:
            e["old"] = {"type": "node", "label": lab, "sub": v["sub_from"], "tone": tone,
                        "box": _data_box(lab, v["sub_from"], *v["at"])}
        if "from" in v:
            fb = _data_box(lab, v.get("sub_from", sub), *v["from"])
            e["shift"] = (fb[0] - box[0] + (fb[2] - fb[0] - (box[2] - box[0])) / 2, fb[1] - box[1])
        nodes[i] = e
    boxes = {i: e["box"] for i, e in nodes.items()}
    edges: dict = {}
    for i, v in st.get("edges", {}).items():
        pts = _data_edge_pts(v, boxes)
        tone = v.get("tone", "plain")
        e = {"type": "edge", "pts": pts, "label": v.get("label"), "arrow": bool(v.get("arrow")),
             "dashed": bool(v.get("dashed")), "tone": tone}
        if e["label"]:
            e["label_at"] = _data_label_at(pts, e["label"], v.get("label_side"))
        if v.get("label_from"):
            e["label_from"] = v["label_from"]
            e["label_from_at"] = _data_label_at(pts, v["label_from"], v.get("label_side"))
        edges[i] = e
    els = {**nodes, **edges}
    steps = [[str(x) for x in step] for step in st["steps"]]
    stepped = {x.split(":", 1)[-1] for step in steps for x in step if not x.startswith("move:")}
    context = [x for x in els if x not in stepped]
    show: dict = {}
    t = 0
    for x in context:  # context first, quickly, as in the Wolverine map
        show[x] = t
        t += 6 if els[x]["type"] == "edge" else 2
    base_end = t + 18 if context else 0
    c = Clock(n, max(30, base_end))
    t1 = base_end + 12 if context else 0
    gap_steps = M.clamp(((c.x0 - 90 - 60) - t1) / max(1, len(steps) - 1), 90, 360)
    step_t = [int(t1 + k * gap_steps) for k in range(len(steps))]
    moves: dict = {}
    lit_win: dict = {}
    lit_over = {int(k): v for k, v in lay.get("lit", {}).get(stage, {}).items()} if lay.get("lit") else {}
    for k, step in enumerate(steps):
        t = step_t[k]
        for x in step:
            if x.startswith("move:"):
                moves[x[5:]] = t
                continue
            show[x] = t
            t += 24 if els[x]["type"] == "edge" else 8
        end = step_t[k + 1] if k + 1 < len(steps) else 10 ** 9
        for x in lit_over.get(k, [s.split(":", 1)[-1] for s in step]):
            lit_win[x] = (step_t[k], end)
    panel = M.side_panel(int(lay.get("panel", 1000)))

    def act(x: str, i: int) -> float:
        if x not in lit_win:
            return 0.0
        a0, a1 = lit_win[x]
        return M.ease_in_out_cubic(seg(i, a0, 18)) * (1 - M.ease_in_out_cubic(seg(i, a1, 20)))

    def mv(x: str, i: int) -> float:  # 0 before the move, 1 after
        return M.ease_in_out_cubic(seg(i, moves[x], 24)) if x in moves else 1.0

    faces = {x: (_node_face(e, "ctx"), _node_face(e, "act"), M.plate(*e["box"], r=10)) for x, e in nodes.items()}
    old_faces = {x: (_node_face(e["old"], "ctx"), _node_face(e["old"], "act"), M.plate(*e["old"]["box"], r=10))
                 for x, e in nodes.items() if "old" in e}

    def edge_cols(e: dict) -> tuple:
        if e["tone"] == "threat":
            return M.RED, M.RED
        return M.GREY, (M.ORANGE if e["tone"] == "name" else M.OFF)

    def edge_spr(e: dict, f: float, col: tuple, a: float = 1.0) -> M.Sprite:
        spr = _edge_sprite(e, f, col)
        if a < 1:
            spr.img.putalpha(spr.img.getchannel("A").point(lambda v: int(v * a)))
        return spr

    edge_full = {x: (edge_spr(e, 1, edge_cols(e)[0], 0.55 if e["tone"] == "threat" else 1.0),
                     edge_spr(e, 1, edge_cols(e)[1])) for x, e in edges.items()}
    edge_lab = {x: (M.text(e["label"], M.MIN_LABEL, "label", M.GREY), M.text(e["label"], M.MIN_LABEL, "label", M.OFF))
                for x, e in edges.items() if e["label"]}
    edge_lab_old = {x: (M.text(e["label_from"], M.MIN_LABEL, "label", M.GREY),
                        M.text(e["label_from"], M.MIN_LABEL, "label", M.OFF))
                    for x, e in edges.items() if e.get("label_from")}
    capt = st.get("caption")
    capt_s = M.text(capt, M.LABEL, "heavy", M.RED) if capt else None
    pl = int(lay.get("panel", 1000))
    capt_at = (pl + 180 + (W - M.SAFE - pl - 180) / 2, float(st.get("caption_y", 1000))) if capt else None
    capt_t = (step_t[0] + 12) if capt else 0

    def draw(i):
        o = c.out(i)
        ox = o * 80
        fade = 1 - o
        p = tin(i, 0, 24)
        out = put(panel, 0, 0, dx=(1 - p) * 120 + ox, a=min(1, p * 2) * fade)
        for x in [x for x in show if els[x]["type"] == "edge"] + [x for x in show if els[x]["type"] == "node"]:
            t0 = show[x]
            if i < t0:
                continue
            e, w = els[x], act(x, i)
            if e["type"] == "node":
                q = tin(i, t0, 18)
                sc = 0.92 + 0.08 * q
                ghost = e["tone"] == "ghost"  # someone gone: always grey, never lit
                a = min(1, q * 2) * fade * (0.5 if ghost else 1.0)
                w = 0.0 if ghost else w
                m = mv(x, i)
                sx, sy = e.get("shift", (0.0, 0.0))
                dx, dy = ox + sx * (1 - m), sy * (1 - m)
                layers = [(faces[x], m if x in old_faces else 1.0)]
                if x in old_faces:
                    layers.append((old_faces[x], 1 - m))
                for (ctx, on, fill), k in layers:
                    if k <= 0.004:
                        continue
                    out += put(fill, 0, 0, a=a * k, s=sc, dx=dx, dy=dy)
                    out += put(ctx, 0, 0, a=a * k * (1 - w), s=sc, dx=dx, dy=dy)
                    out += put(on, 0, 0, a=a * k * w, s=sc, dx=dx, dy=dy)
            else:
                L = 12 if x in context else 24
                f = M.ease_in_out_cubic(seg(i, t0, L))
                ctx_col, on_col = edge_cols(e)
                if f < 1:
                    out += put(_edge_sprite(e, f, on_col), 0, 0, a=fade, dx=ox)
                else:
                    ctx, on = edge_full[x]
                    out += put(ctx, 0, 0, a=fade * (1 - w), dx=ox) + put(on, 0, 0, a=fade * w, dx=ox)
                q = tin(i, t0 + L, 14)
                m = mv(x, i)
                labs = [(edge_lab.get(x), e.get("label_at"), m if x in edge_lab_old else 1.0)]
                if x in edge_lab_old:
                    labs.append((edge_lab_old[x], e["label_from_at"], 1 - m))
                for pair, at, k in labs:
                    if not pair or k <= 0.004:
                        continue
                    lx, ly = at
                    for j, sp in enumerate(pair):
                        out += put(sp, lx, ly, a=min(1, q * 2) * fade * k * (w if j else 1 - w), dx=ox - (1 - q) * 12)
        if capt_s is not None and i >= capt_t:
            out += put(capt_s, _centre_x(capt_s, capt_at[0]), capt_at[1], a=fade, dx=ox,
                       mask=("rise", tin(i, capt_t, 18)))
        return out

    # Layout facts for the checks (analysis_motion_check): boxes in every state, every label box.
    shapes, labels, pads = [], [], []
    for x, e in nodes.items():
        for tag, ee in (("", e), (":old", e.get("old"))):
            if not ee:
                continue
            if not tag:  # the old face shares the node's place, so only its padding is checked
                shapes.append((x, ee["box"]))
            iw = max(M.adv(ee["label"], M.LABEL), M.adv(ee["sub"], M.MIN_LABEL, "label") if ee["sub"] else 0)
            pads.append((ee["box"][2] - ee["box"][0] - iw) / 2)
        if "shift" in e:
            b, (sx, sy) = e["box"], e["shift"]
            shapes.append((x + ":from", (b[0] + sx, b[1] + sy, b[2] + sx, b[3] + sy)))
    for x, e in edges.items():
        for tag, key, at in (("", "label", "label_at"),):  # an old label crossfades in the same place
            if e.get(key):
                lx, ly = e[at]
                bb = M.ink(e[key], M.MIN_LABEL, "label")
                labels.append((x + tag, (lx + bb[0], ly + bb[1], lx + bb[2], ly + bb[3])))
    if capt_s is not None:
        bb = M.ink(capt, M.LABEL, "heavy")
        w = bb[2] - bb[0]
        labels.append(("caption", (capt_at[0] - w / 2, capt_at[1] + bb[1], capt_at[0] + w / 2, capt_at[1] + bb[3])))
    return _g("map", n, c, draw, shapes=shapes, labels=labels, groups=[], pads=pads, step_t=step_t)


# ---------------------------------------------------------------- memory ring and loop

def g_memory(spec: dict, n: int, grab=None) -> M.Graphic | None:
    frames = [grab(cl, s) for cl, s in spec["frames"]] if grab else []
    if not frames:
        return None
    pos = [(130, 90), (1370, 90), (130, 700), (1370, 700)]
    rots = (-4, 3, 3, -3)
    dirs = [(-1, -1), (1, -1), (-1, 1), (1, 1)]
    cards = []
    for k, (fr, (x, y)) in enumerate(zip(frames, pos)):
        th = fr.convert("RGBA").resize((420, 236), Image.LANCZOS)
        var = []
        for tint, amt in ((None, 0), (M.RED, 0.3), (M.OFF, 0.94)):
            t = th if tint is None else Image.blend(th, Image.new("RGBA", th.size, M.rgba(tint)), amt)
            cd = Image.new("RGBA", (440, 256), M.rgba(M.OFF))
            cd.alpha_composite(t, (10, 10))
            r = cd.rotate(rots[k % 4], expand=True, resample=Image.BICUBIC)
            padded = Image.new("RGBA", (r.width + 72, r.height + 72), (0, 0, 0, 0))
            padded.alpha_composite(r, (36, 36))
            var.append(M.Sprite(M.shadow_stack(padded, 0.8), -(x - 36), -(y - 36)))
        cards.append(var)
    c = Clock(n, 4 * (len(cards) - 1) + 24)
    kb = len(cards)
    first = 0.35 * n
    steps = [int(first + b * (c.x0 - 30 - first) / kb) for b in range(kb)]

    def draw(i):
        o = c.out(i)
        out = []
        for k, (norm, red, white) in enumerate(cards):
            p = tin(i, 4 * k, 24)
            dxs, dys = dirs[k % 4]
            dx = dxs * ((1 - p) * 90 + o * 90)
            dy = dys * ((1 - p) * 70 + o * 70)
            a = min(1, p * 2) * (1 - o)
            out += put(norm, 0, 0, a=a, dx=dx, dy=dy)
            if k >= 1:  # tinted red while it is the next memory to go
                out += put(red, 0, 0, a=a * M.ease_in_out_cubic(seg(i, steps[k - 1], 18)), dx=dx, dy=dy)
            out += put(white, 0, 0, a=a, dx=dx, dy=dy,
                       mask=("lr", M.ease_in_out_cubic(seg(i, steps[k], 24))))
        return out
    return _g("memory", n, c, draw, steps=steps)


def g_loop(spec: dict, n: int, grab=None) -> M.Graphic:
    stops, capt = spec["stops"], spec["caption"]
    ns = len(stops)
    cx, cy, r = 960, 500, 280
    ring_pts = M.arc_points(cx, cy, r, -math.pi / 2, 1.5 * math.pi, 240)
    ring = M.Shape(cx - r, cy - r, cx + r, cy + r).line(ring_pts, M.OFF, M.LINK, 0.8).done(shadow=True, k=0.6)
    ang = [-math.pi / 2 + k * 2 * math.pi / ns for k in range(ns)]
    pts = [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in ang]
    dot = [M.Shape(x - 12, y - 12, x + 12, y + 12).circle(x, y, 12, fill=M.OFF).done(shadow=True) for x, y in pts]
    labs, lpos = [], []
    for k, (a, (x, y)) in enumerate(zip(ang, pts)):
        g = M.text(stops[k], M.NAME, "display", M.GREY)
        on = M.text(stops[k], M.NAME, "display", M.OFF)
        lx = x + (70 if math.cos(a) > 0.2 else -70 if math.cos(a) < -0.2 else 0)
        ly = y + (-70 if math.sin(a) < -0.5 else 70)
        if math.cos(a) > 0.2:
            bx = lx - g.ink[0]
        elif math.cos(a) < -0.2:
            bx = lx - g.ink[2]
        else:
            bx = lx - g.w / 2 - g.ink[0]
        labs.append((g, on))
        lpos.append((bx, ly + cap(M.NAME) / 2))
    capt_s = M.text(capt, M.LABEL, "heavy", M.OFF, 0.9)
    marker = M.Shape(-24, -24, 24, 24).circle(0, 0, 20, fill=M.RED, outline=M.OFF, width=M.HAIR).done(shadow=True)
    RING = 30
    t_dot = []
    for k in range(ns):
        f = k / ns
        t_dot.append(next(j for j in range(RING + 1) if M.ease_in_out_cubic(j / RING) >= f - 1e-6))
    E = max(t_dot[-1] + 4 + 18, 30 + 18, RING + 18)
    c = Clock(n, E)
    arc = 2 * math.pi * r / ns
    T = max(36, math.ceil(3 * arc / 38))
    seq = list(range(ns)) + [0]
    S = (c.x0 - c.e - 30) / len(seq)
    hops = [int(c.e + 18 + (k + 1) * S - T) for k in range(len(seq) - 1)]
    dim = M.dim(0.7)

    def marker_at(i: int) -> tuple:
        k_done, frac = 0, 0.0
        for k, h0 in enumerate(hops):
            if i >= h0:
                k_done, frac = k, M.ease_in_out_cubic(seg(i, h0, T))
        if i < (hops[0] if hops else 10 ** 9):
            return ang[0], 0
        a0 = ang[seq[k_done]]
        a = a0 + frac * 2 * math.pi / ns
        return a, (seq[k_done + 1] if frac >= 0.5 else seq[k_done])

    def draw(i):
        o = c.out(i)
        fade = 1 - o
        dy = o * 40
        out = put(dim, 0, 0, a=tin(i, 0, 18, M.ease_out_cubic) * fade)
        f = M.ease_in_out_cubic(seg(i, 0, RING))
        if f >= 1:
            out += put(ring, 0, 0, a=fade, dy=dy)
        elif f > 0:
            part = M.partial(ring_pts, f)
            sh = M.Shape(cx - r, cy - r, cx + r, cy + r).line(part, M.OFF, M.LINK, 0.8)
            sh.circle(part[-1][0], part[-1][1], 7, fill=M.OFF)
            out += put(sh.done(), 0, 0, dy=dy)
        a_m, cur = marker_at(i)
        for k in range(ns):
            q = tin(i, t_dot[k], 10)
            out += put(dot[k], 0, 0, a=min(1, q * 2) * fade, s=0.5 + 0.5 * q, dy=dy)
            w = 1.0 if (cur == k and i >= c.e) else 0.0
            g, on = labs[k]
            bx, by = lpos[k]
            m = tin(i, t_dot[k] + 4, 18)
            out += put(g, bx, by, a=fade * (1 - w), dy=dy, mask=("rise", m))
            out += put(on, bx, by, a=fade * w, dy=dy, mask=("rise", m))
        out += put(capt_s, _centre_x(capt_s, cx), cy + r + 130, a=fade, dy=dy, mask=("rise", tin(i, 30, 18)))
        q = tin(i, c.e, 18, M.ease_out_cubic)
        if i >= c.e:
            out += put(marker, cx + r * math.cos(a_m), cy + r * math.sin(a_m), a=min(1, q * 2) * fade,
                       s=0.6 + 0.4 * q, dy=dy)
        return out

    speeds = []
    prev = None
    for i in range(c.e, c.x0):
        a_m, _ = marker_at(i)
        p = (cx + r * math.cos(a_m), cy + r * math.sin(a_m))
        if prev:
            speeds.append(math.hypot(p[0] - prev[0], p[1] - prev[1]))
        prev = p
    return _g("loop", n, c, draw, max_speed=max(speeds) if speeds else 0.0, hops=hops)


# ---------------------------------------------------------------- storybook and end screen

def _panel_art(k: int, x: int, y0: int, pw: int, ph: int, label: str) -> M.Sprite:
    sh = M.Shape(x, y0, x + pw, y0 + ph, pad=40)
    sh.rect(x, y0, x + pw, y0 + ph, fill=M.OFF, outline=M.INK, width=M.HAIR)
    cx, cy = x + pw // 2, y0 + 130
    if k == 0:  # the girl, Red
        sh.circle(cx, cy - 60, 36, fill=M.ORANGE)
        sh.polygon([(cx, cy - 30), (cx - 70, cy + 90), (cx + 70, cy + 90)], M.ORANGE)
    elif k == 1:  # the boy, strange and dirty
        sh.circle(cx, cy - 62, 34, fill=M.GREY)
        sh.rect(cx - 50, cy - 26, cx + 50, cy + 90, fill=M.GREY)
        for j in range(9):
            sh.circle(cx - 36 + (j * 23) % 80, cy - 6 + (j * 37) % 90, 4, fill=M.INK, a=0.7)
    elif k == 2:  # the dark cloud
        for ox, oy, r in ((-70, 0, 52), (0, -30, 66), (70, 0, 52), (0, 26, 58)):
            sh.circle(cx + ox, cy + oy, r, fill=M.INK, a=0.75)
    else:  # the sun
        for j in range(12):
            a = math.radians(j * 30)
            sh.line([(cx + 62 * math.cos(a), cy + 62 * math.sin(a)), (cx + 94 * math.cos(a), cy + 94 * math.sin(a))],
                    M.ORANGE, M.HIGHLIGHT)
        sh.circle(cx, cy, 50, fill=M.ORANGE)
    spr = sh.done(shadow=True, k=0.7)
    t = M.text(label, M.LABEL, "display", M.INK, shadow=False)
    spr.img.alpha_composite(t.img, (int(round(cx - t.w / 2 - t.ink[0] - t.ax + spr.ax)),
                                     int(round(y0 + ph - 38 + cap(M.LABEL) / 2 - t.ay + spr.ay))))
    return spr


def g_storybook(spec: dict, n: int, grab=None) -> M.Graphic:
    labels = spec["labels"]
    pw, ph, gap = 400, 300, 40
    x0 = (W - (len(labels) * pw + (len(labels) - 1) * gap)) // 2
    y0 = 650
    panels = [_panel_art(k % 4, x0 + k * (pw + gap), y0, pw, ph, lab) for k, lab in enumerate(labels)]
    marks = [int(M.clamp(float(f)) * n) for f in spec["panel_fracs"]]
    c = Clock(n, 24)
    bnd = M.band(480, 0.8)

    def draw(i):
        o = c.out(i)
        out = put(bnd, 0, 0, a=tin(i, 0, 20, M.ease_out_cubic) * (1 - o))
        for k, sp in enumerate(panels):
            p = tin(i, marks[k], 24)
            out += put(sp, 0, 0, a=min(1, p * 2) * (1 - o), dy=(1 - p) * 90 + o * 120, s=0.92 + 0.08 * p)
        return out
    return _g("storybook", n, c, draw)


def g_endscreen(spec: dict, n: int, grab=None) -> M.Graphic:
    x0, y0, x1, y1 = 140, 300, 1040, 806  # 16:9 slot for YouTube's end-screen video element
    perim = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    head = M.text("WATCH NEXT", M.MIN_LABEL, "heavy", M.OFF)
    nl = M.wrap(spec["next"], M.LABEL, "display", x1 - x0 - 56)
    nts = [M.text(s, M.LABEL) for s in nl]
    sub = M.text(spec["sub"], M.LABEL, "display", M.ORANGE)
    mid = (y0 + y1) / 2
    lines = nts + [sub]
    bases = [mid - (len(lines) - 1) * 32 + k * 64 + cap(M.LABEL) / 2 for k in range(len(lines))]
    ccx, ccy, cr = 1500, 553, 170
    circ = M.arc_points(ccx, ccy, cr, -math.pi / 2, 1.5 * math.pi, 200)
    kg = M.text("KG", M.SLAM)
    bx0, by0, bx1, by1 = ccx - 200, ccy + 200, ccx + 200, ccy + 280
    btn = M.Shape(bx0, by0, bx1, by1, pad=40).rect(bx0, by0, bx1, by1, fill=M.RED, r=10).done(shadow=True, k=0.8)
    bl = M.text("SUBSCRIBE", M.LABEL, "display", M.OFF, shadow=False)
    btn.img.alpha_composite(bl.img, (int(round(ccx - bl.w / 2 - bl.ink[0] - bl.ax + btn.ax)),
                                     int(round(ccy + 240 + cap(M.LABEL) / 2 - bl.ay + btn.ay))))
    c = Clock(n, 46)
    dim = M.dim(0.66)

    def outline(pts, f):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return M.Shape(min(xs), min(ys), max(xs), max(ys)).line(M.partial(pts, f), M.OFF, M.HAIR).done()

    full_slot, full_circ = outline(perim, 1), outline(circ, 1)

    def draw(i):
        o = c.out(i)
        fade = 1 - o
        out = put(dim, 0, 0, a=tin(i, 0, 18, M.ease_out_cubic) * fade)
        f = M.ease_in_out_cubic(seg(i, 0, 30))
        out += put(full_slot if f >= 1 else outline(perim, f), 0, 0, a=fade) if f > 0 else []
        f2 = M.ease_in_out_cubic(seg(i, 6, 30))
        out += put(full_circ if f2 >= 1 else outline(circ, f2), 0, 0, a=fade) if f2 > 0 else []
        out += put(head, x0, y0 - 40, a=fade, mask=("rise", tin(i, 6, 18)))
        for k, (t, b) in enumerate(zip(lines, bases)):
            out += put(t, _centre_x(t, (x0 + x1) / 2), b, a=fade, mask=("rise", tin(i, 12 + 6 * k, 20)))
        q = tin(i, 16, 20)
        out += put(kg, _centre_x(kg, ccx), ccy + cap(M.SLAM) / 2, a=min(1, q * 2) * fade, s=0.92 + 0.08 * q)
        q2 = M.ease_out_back(seg(i, 22, 24))  # the one overshoot of the closing chapter
        out += put(btn, 0, 0, a=min(1, seg(i, 22, 8)) * fade, s=max(0.02, 0.92 + 0.08 * q2), dy=o * 40)
        return out
    return _g("endscreen", n, c, draw)


# ---------------------------------------------------------------- timeline scrubber

def _stops(raw: list) -> list[dict]:
    out = []
    for s in raw:
        if isinstance(s, dict):
            out.append({"label": str(s["label"]), "sub": s.get("sub")})
        else:
            head, sep, sub = str(s).partition(": ")
            out.append({"label": head, "sub": sub if sep else None})
    return out


def g_timeline(spec: dict, n: int, grab=None) -> M.Graphic:
    """The scrubber: a rail with a stop per game or era, a KG-red playhead that travels eased from
    `from` to `to`, past segments grey, labels alternating below and above the rail.
    spec: {"kind": "timeline", "stops": [{"label", "sub"} | "LABEL: sub", ...], "from": 0, "to": 2,
           "reveal": false}  (reveal hides stops until the playhead reaches them)."""
    stops = _stops(spec["stops"])
    ns = len(stops)
    frm = int(spec.get("from", 0))
    to = int(spec.get("to", frm))
    reveal = bool(spec.get("reveal", False))
    y = 905
    xL, xR = (260, 1660) if ns > 1 else (960, 960)
    xs = [xL + k * (xR - xL) / (ns - 1) for k in range(ns)] if ns > 1 else [960.0]
    r0, r1 = 160, 1760
    maxw = (2 * (xs[1] - xs[0]) - 48) if ns > 2 else 860
    caph, caps = cap(M.LABEL), cap(M.MIN_LABEL, "label")
    blocks = []
    for k, st in enumerate(stops):
        subs = M.wrap(st["sub"], M.MIN_LABEL, "label", maxw) if st.get("sub") else []
        bw = max([M.adv(st["label"], M.LABEL)] + [M.adv(s, M.MIN_LABEL, "label") for s in subs])
        below = k % 2 == 0
        if below:
            hb = y + 30 + caph
            sbs = [hb + 16 + caps + 40 * j for j in range(len(subs))]
        else:
            last = y - 30
            sbs = [last - 40 * (len(subs) - 1 - j) for j in range(len(subs))]
            hb = (sbs[0] - caps - 16) if subs else last
        left = M.clamp(xs[k] - bw / 2, M.SAFE, W - M.SAFE - bw)
        top = hb - caph
        bot = (sbs[-1] if sbs else hb) + (10 if subs else 0)
        states = {}
        for name, hc, ha, sc, sa in (("future", M.OFF, 0.7, M.OFF, 0.55), ("current", M.OFF, 1.0, M.OFF, 0.9),
                                     ("past", M.GREY, 1.0, M.GREY, 1.0)):
            states[name] = ([M.text(st["label"], M.LABEL, "display", hc, ha)],
                            [M.text(s, M.MIN_LABEL, "label", sc, sa) for s in subs])
        blocks.append({"left": left, "w": bw, "hb": hb, "sbs": sbs, "subs": subs, "states": states,
                       "rect": (left, top, left + bw, bot)})
    rail_f = M.Shape(r0, y - 4, r1, y + 4).line([(r0, y), (r1, y)], M.OFF, M.HAIR, 0.6).done(shadow=True, k=0.5)
    rail_p = M.Shape(r0, y - 6, r1, y + 6).line([(r0, y), (r1, y)], M.GREY, M.LINK).done()
    dots = {nm: [M.Shape(x - 10, y - 10, x + 10, y + 10).circle(x, y, 9, fill=col, a=al).done(shadow=True, k=0.5)
                 for x in xs] for nm, col, al in (("future", M.OFF, 0.6), ("past", M.GREY, 1.0), ("current", M.RED, 1.0))}
    head = M.Shape(-22, -22, 22, 22).circle(0, 0, 16, fill=M.RED, outline=M.OFF, width=M.HAIR).done(shadow=True)
    bnd = M.band(560, 0.9)
    RAIL = 24
    t_dot = [next(j for j in range(RAIL + 1) if M.ease_out_cubic(j / RAIL) >= (x - r0) / (r1 - r0) - 1e-6) for x in xs]
    t_ph = 26
    E = max(t_dot[-1] + 2 + 18, t_ph + 18)
    c = Clock(n, E)
    # Playhead moves: one hop (or one per stop in reveal mode) from frm to to.
    path = list(range(frm, to + 1)) if to >= frm else list(range(frm, to - 1, -1))
    legs = list(zip(path, path[1:]))
    start = c.e + 36
    avail = max(60, c.x0 - 60 - start)
    hops = []
    if legs:
        span = avail / len(legs) if reveal else avail
        for k, (a, b) in enumerate(legs if reveal else [(frm, to)]):
            dist = abs(xs[b] - xs[a])
            T = int(M.clamp(24 + dist / 25 if reveal else 30 + dist / 20, 36, 96))
            T = int(min(T, max(24, span - 30)))
            hops.append((int(start + k * span), T, a, b))
    reach = {frm: t_ph}
    for h0, T, a, b in hops:
        lo, hi = sorted((a, b))
        for k in range(lo, hi + 1):
            if k not in reach:
                frac = abs(xs[k] - xs[a]) / max(1, abs(xs[b] - xs[a]))
                reach[k] = h0 + next(j for j in range(T + 1) if M.ease_in_out_cubic(j / T) >= frac - 1e-6)

    def px(i: int) -> float:
        x = xs[frm]
        for h0, T, a, b in hops:
            if i >= h0:
                x = xs[a] + (xs[b] - xs[a]) * M.ease_in_out_cubic(seg(i, h0, T))
        return x

    def draw(i):
        o = c.out(i)
        fade = 1 - o
        dy = o * 40
        out = put(bnd, 0, 0, a=tin(i, 0, 20, M.ease_out_cubic) * fade)
        out += put(rail_f, 0, 0, a=fade, dy=dy, mask=("lr", M.ease_out_cubic(seg(i, 0, RAIL))))
        x = px(i)
        if i >= t_ph:
            out += put(rail_p, 0, 0, a=fade * min(1, seg(i, t_ph, 10)), dy=dy, mask=("lr", (x - r0 + 4) / (r1 - r0)))
        cur = max((k for k in reach if reach[k] <= i and (xs[k] <= x + 0.5 if to >= frm else xs[k] >= x - 0.5)),
                  default=None, key=lambda k: reach[k])
        for k, b in enumerate(blocks):
            seen = k in reach and i >= reach[k]
            if reveal and k > frm and not seen:
                continue
            past_side = k < frm if to >= frm else k > frm
            state = "current" if k == cur else "past" if (seen or past_side) else "future"
            t_in = reach[k] if (reveal and k > frm) else t_dot[k]
            q = tin(i, t_in, 10)
            out += put(dots[state][k], 0, 0, a=min(1, q * 2) * fade, s=0.5 + 0.5 * q, dy=dy)
            m = tin(i, t_in + 2, 18)
            heads, subs = b["states"][state]
            for sp in heads:
                out += put(sp, b["left"] + (b["w"] - sp.w) / 2 - sp.ink[0], b["hb"], a=fade, dy=dy, mask=("rise", m))
            for sp, sb in zip(subs, b["sbs"]):
                out += put(sp, b["left"] + (b["w"] - sp.w) / 2 - sp.ink[0], sb, a=fade, dy=dy,
                           mask=("rise", tin(i, t_in + 6, 18)))
        if i >= t_ph:
            q = seg(i, t_ph, 18)
            out += put(head, x, y, a=min(1, q * 3) * fade, s=max(0.05, M.ease_out_back(q)), dy=dy)
        return out
    return _g("timeline", n, c, draw, xs=xs, to=to, px=px, rects=[b["rect"] for b in blocks],
              hops=hops)


def g_strip(spec: dict, n: int, grab=None) -> M.Graphic:
    """The Wolverine strip, drawn by the timeline scrubber: reveal walks every stop in turn;
    lit k moves the playhead from the stop before it to k."""
    items = spec["items"]
    if spec.get("reveal"):
        tl = {"stops": items, "from": 0, "to": len(items) - 1, "reveal": True}
    else:
        lit = spec.get("lit")
        lit = len(items) - 1 if lit is None else int(lit)
        tl = {"stops": items, "from": max(0, lit - 1), "to": lit}
    g = g_timeline(tl, n)
    g.kind = "strip"
    return g


# ---------------------------------------------------------------- spec -> overlays

BUILDERS = {"lower": g_lower, "chapter": g_chapter, "question": g_question, "caption": g_caption,
            "tag": g_tag, "card": g_card, "quote": g_quote, "slam": g_slam, "counter": g_counter,
            "dossier": g_dossier, "split": g_split, "map": g_map, "memory": g_memory, "loop": g_loop,
            "storybook": g_storybook, "endscreen": g_endscreen, "timeline": g_timeline, "strip": g_strip}

_SRC = [Path(__file__), Path(M.__file__)] + sorted(set(M.FONT_FILES.values()))
CODE_HASH = hashlib.sha1(b"".join(p.read_bytes() for p in _SRC)).hexdigest()[:10]


def load_specs(path: Path) -> dict:
    """A game's gfx.json with its map layout (the "map" key, when it is a dict) copied into every
    map spec, so a spec carries everything that draws it (and the beat cache sees layout changes)."""
    specs = json.loads(Path(path).read_text(encoding="utf-8"))
    lay = specs.get("map")
    if isinstance(lay, dict):
        for v in specs.values():
            if isinstance(v, list):
                for s in v:
                    if isinstance(s, dict) and s.get("kind") == "map":
                        s.setdefault("layout", lay)
    return specs


def _t(spec: dict, key: str, frac_key: str, dur: float, default: float) -> float:
    if frac_key in spec:
        return float(spec[frac_key]) * dur
    v = spec.get(key, default)
    return dur + float(v) if v is not None and float(v) < 0 else float(v if v is not None else default)


def timing(spec: dict, dur: float) -> tuple[float, float]:
    """(start, seconds) inside the beat. Nothing starts on the cut's exact frame (6 frames in)."""
    at = max(0.1, _t(spec, "at", "at_frac", dur, 0.0))
    end = min(dur, at + float(spec["dur"])) if spec.get("dur") else dur
    if spec["kind"] == "endscreen":
        at = max(0.1, end - float(spec.get("last", 20)))
    return at, max(0.0, end - at)


def build(spec: dict, dur: float, grab: Callable | None = None) -> tuple[M.Graphic | None, float]:
    k = spec["kind"]
    if k not in BUILDERS:
        raise ValueError(f"unknown gfx kind {k}")
    at, secs = timing(spec, dur)
    n = max(2, int(round(secs * FPS)))
    return BUILDERS[k](spec, n, grab), at


def overlays(spec: dict, dur: float, workdir: Path, name: str, grab: Callable | None = None) -> list[tuple]:
    """[(mov, x, y, start, seconds)] for one spec; encoded once and cached by spec, timing and code."""
    at, secs = timing(spec, dur)
    if secs < 0.05:
        return []
    key = hashlib.sha1(json.dumps([spec, round(dur, 3), CODE_HASH], sort_keys=True).encode()).hexdigest()[:12]
    mov = Path(workdir) / "gfx" / f"{name}-{key}.mov"
    side = mov.with_suffix(".json")
    if mov.exists() and side.exists():
        info = json.loads(side.read_text(encoding="utf-8"))
    else:
        g, _ = build(spec, dur, grab)
        if g is None:
            return []
        info = g.export(mov)
        g.free()
        side.write_text(json.dumps(info), encoding="utf-8")
    return [(mov, info["x"], info["y"], at, info["secs"])]


def thumbnail(frame: Image.Image, words: str, out: Path, bright: float = 1.0, contrast: float = 1.08,
              accent=ORANGE) -> Path:
    im = frame.convert("RGB").resize((1280, 720))
    im = ImageEnhance.Color(im).enhance(1.2)
    im = ImageEnhance.Brightness(im).enhance(bright)
    im = ImageEnhance.Contrast(im).enhance(contrast).convert("RGBA")
    g = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    for y in range(300):
        gd.line([(0, 420 + y), (1280, 420 + y)], fill=M.rgba(M.INK, 0.75 * y / 300))
    im.alpha_composite(g)
    d = ImageDraw.Draw(im)
    f = font("display", M.SLAM)
    parts = words.split()
    x = 50
    for i, w in enumerate(parts):
        fill = accent if i == len(parts) - 1 else WHITE
        # Thumbnails keep a hard outline: they are read at 200 px wide, not over motion.
        d.text((x, 650), w, font=f, fill=fill, anchor="ls", stroke_width=M.HIGHLIGHT, stroke_fill=M.rgba(M.INK))
        x += tw(d, w, f) + 26
    im.convert("RGB").save(out, quality=92)
    return out
