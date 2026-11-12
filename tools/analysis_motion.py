"""Shared motion engine and design tokens for KG analysis graphics (2026-11-13).

Plan: Bryce-Brain wiki answer "kg-analysis-motion-upgrade-plan" (style guide and motion rules).
Every graphic is drawn frame by frame with Pillow from small cached sprites (text with a soft
shadow stack, plates, shapes), then encoded to a transparent qtrle (argb) .mov cropped to the
union of everything it ever draws, so the renderer overlays it at x,y inside the beat. Identical
consecutive frames are composed once, so long holds cost almost nothing.

Tokens (one place, nothing else allowed in tools/analysis_gfx.py):
  colours  KG red #FF3D46 (finding, verdict, threat), orange #FF701C (names, factions),
           ink #0E0C10 (plates), off-white #F2EEE8 (type), grey #8A8690 (context)
  sizes    36 (minimum label), 48 (label), 64 (name, quote), 96 (statement), 150 (slam)
  strokes  3 (hairline), 5 (connector), 8 (highlight); corner radius 0 or 10
Motion at 60 fps: entrances ease-out expo over 18 to 30 frames and always move (slide, wipe,
scale 0.92 to 1, draw-on); exits ease-in cubic, about 0.6 of the entrance.

    py tools/analysis_motion.py --make-fonts    # rebuild the static Montserrat files (fontTools)
"""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080
FPS = 60
SAFE = 96  # 5% title-safe margin at 1920

# ---------------------------------------------------------------- tokens

RED = (255, 61, 70)
ORANGE = (255, 112, 28)
INK = (14, 12, 16)
OFF = (242, 238, 232)
GREY = (138, 134, 144)
PALETTE = {"red": RED, "orange": ORANGE, "ink": INK, "off": OFF, "grey": GREY}
_PAL_SET = set(PALETTE.values())

SIZES = (36, 48, 64, 96, 150)
MIN_LABEL, LABEL, NAME, STATEMENT, SLAM = SIZES
HAIR, LINK, HIGHLIGHT = 3, 5, 8
STROKES = (HAIR, LINK, HIGHLIGHT)
RADII = (0, 10)
PLATE_A = 0.86  # ink plates sit at 82 to 88% alpha

COLOURS_USED: set = set()


def rgba(col: tuple, a: float = 1.0) -> tuple:
    """A palette colour with alpha 0..1. Raises on any colour outside the five tokens."""
    col = tuple(col[:3])
    if col not in _PAL_SET:
        raise ValueError(f"colour {col} is not a palette token")
    COLOURS_USED.add(col)
    return (col[0], col[1], col[2], max(0, min(255, int(round(255 * a)))))


# ---------------------------------------------------------------- fonts

FONT_FILES = {
    "display": ROOT / "assets/fonts/anton/Anton-Regular.ttf",
    "heavy": ROOT / "assets/fonts/montserrat/Montserrat-ExtraBold.ttf",
    "label": ROOT / "assets/fonts/montserrat/Montserrat-SemiBold.ttf",
}
# Quotes: Source Serif 4 Italic (SIL OFL, Adobe), a static Medium instance (wght 500, opsz 36)
# made with fontTools from Google Fonts' variable file; Bryce approved the download 2026-11-13.
FONT_FILES["quote"] = ROOT / "assets/fonts/source-serif-4/SourceSerif4-MediumItalic.ttf"
FONT_FILES["serif"] = FONT_FILES["quote"]

USED_SIZES: set = set()
_FONTS: dict = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """The shipped font file for this role. Raises if the file is missing: a render never falls back."""
    key = (kind, size)
    if key not in _FONTS:
        path = FONT_FILES[kind]
        if not path.exists():
            raise FileNotFoundError(f"font file missing: {path}")
        _FONTS[key] = ImageFont.truetype(str(path), size)
    USED_SIZES.add(size)
    return _FONTS[key]


def make_static_fonts() -> None:
    """Instance the repo's variable Montserrat into static ExtraBold (800) and SemiBold (600)."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    src = ROOT / "assets/fonts/montserrat/Montserrat.ttf"
    for name, wght in (("ExtraBold", 800), ("SemiBold", 600)):
        vf = TTFont(str(src))
        inst = instancer.instantiateVariableFont(vf, {"wght": wght}, updateFontNames=True)
        out = src.parent / f"Montserrat-{name}.ttf"
        inst.save(str(out))
        print(out, out.stat().st_size)


def adv(s: str, size: int, kind: str = "display") -> float:
    return font(kind, size).getlength(s)


def ink(s: str, size: int, kind: str = "display") -> tuple:
    """Ink box of s relative to its baseline-left point (x0, y0, x1, y1)."""
    return font(kind, size).getbbox(s, anchor="ls")


def wrap(s: str, size: int, kind: str, maxw: float) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and adv(trial, size, kind) > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def wrap_balanced(s: str, size: int, kind: str, maxw: float) -> list[str]:
    """Like wrap, but evens out the line lengths (no one-word last line)."""
    lines = wrap(s, size, kind, maxw)
    if len(lines) < 2:
        return lines
    words = s.split()
    n = len(lines)
    best, best_w = lines, max(adv(x, size, kind) for x in lines)
    if n == 2:
        for k in range(1, len(words)):
            a, b = " ".join(words[:k]), " ".join(words[k:])
            w = max(adv(a, size, kind), adv(b, size, kind))
            if w <= maxw and w < best_w:
                best, best_w = [a, b], w
    return best


# ---------------------------------------------------------------- easing

def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def ease_out_expo(x: float) -> float:
    x = clamp(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def ease_in_cubic(x: float) -> float:
    return clamp(x) ** 3


def ease_out_cubic(x: float) -> float:
    return 1 - (1 - clamp(x)) ** 3


def ease_in_out_cubic(x: float) -> float:
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out_back(x: float, s: float = 1.70158) -> float:
    x = clamp(x) - 1
    return x * x * ((s + 1) * x + s) + 1


def seg(i: float, start: float, length: float) -> float:
    """Linear 0..1 progress of frame i through [start, start + length)."""
    if length <= 0:
        return 1.0 if i >= start else 0.0
    return clamp((i - start) / length)


def tin(i: float, start: float, length: float = 24, ease: Callable = ease_out_expo) -> float:
    return ease(seg(i, start, length))


def stagger(n: int, each: float = 5, cap: float = 30, length: float = 24) -> list[float]:
    """Start offsets for n items, each frames apart, squeezed so the cascade ends by cap + length."""
    if n <= 1:
        return [0.0]
    step = min(each, max(1.0, cap / (n - 1)))
    return [k * step for k in range(n)]


# ---------------------------------------------------------------- geometry

def partial(pts: list[tuple], frac: float) -> list[tuple]:
    """The first frac of a polyline by arc length (draw-on)."""
    if frac >= 1:
        return list(pts)
    if frac <= 0 or len(pts) < 2:
        return [pts[0]]
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    target = frac * sum(lens)
    out = [pts[0]]
    for (a, b), L in zip(zip(pts, pts[1:]), lens):
        if target <= L:
            t = target / L if L else 0
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            return out
        out.append(b)
        target -= L
    return out


def arc_points(cx: float, cy: float, r: float, a0: float, a1: float, n: int = 0) -> list[tuple]:
    """Points on a circle from angle a0 to a1 (radians, screen y down)."""
    n = n or max(8, int(abs(a1 - a0) * r / 6))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


def dashes(pts: list[tuple], dash: float = 18, gap: float = 14) -> list[list[tuple]]:
    """Split a polyline into dash pieces by arc length."""
    out, cur, pos, on = [], [pts[0]], 0.0, True
    for a, b in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        t = 0.0
        while L > 0 and t < L:
            left = (dash if on else gap) - pos
            step = min(left, L - t)
            t += step
            pos += step
            p = (a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L)
            if on:
                cur.append(p)
            if pos >= (dash if on else gap) - 1e-6:
                if on and len(cur) > 1:
                    out.append(cur)
                on, pos, cur = not on, 0.0, [p]
    if on and len(cur) > 1:
        out.append(cur)
    return out


def overlap(a: tuple, b: tuple, gap: float = 0) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


# ---------------------------------------------------------------- sprites

class Sprite:
    """An RGBA image plus the point inside it that put() lines up with the given x, y.
    Text sprites anchor at the baseline-left point; shape sprites anchor at screen 0,0."""
    __slots__ = ("img", "ax", "ay", "ink")

    def __init__(self, img: Image.Image, ax: float = 0, ay: float = 0, ink_box: tuple | None = None):
        self.img, self.ax, self.ay = img, ax, ay
        self.ink = ink_box or (-ax, -ay, img.width - ax, img.height - ay)

    @property
    def w(self) -> float:
        return self.ink[2] - self.ink[0]

    @property
    def h(self) -> float:
        return self.ink[3] - self.ink[1]


def _shift(a: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(a)
    h, w = a.shape
    out[dy:, dx:] = a[:h - dy, :w - dx]
    return out


def shadow_stack(layer: Image.Image, k: float = 1.0) -> Image.Image:
    """Soft legibility shadow instead of an outline: a 2 px contact shadow plus a 12 px blurred
    key at 60% ink, both dropped a little."""
    al = layer.getchannel("A")
    key = np.asarray(al.filter(ImageFilter.GaussianBlur(12)), np.float32) / 255 * 0.6 * k
    con = np.asarray(al.filter(ImageFilter.GaussianBlur(2)), np.float32) / 255 * 0.8 * k
    sh = 1 - (1 - _shift(key, 0, 6)) * (1 - _shift(con, 0, 2))
    out = Image.new("RGBA", layer.size, rgba(INK, 0))
    out.putalpha(Image.fromarray((sh * 255).clip(0, 255).astype(np.uint8)))
    out.alpha_composite(layer)
    return out


_TEXT: dict = {}


def text(s: str, size: int, kind: str = "display", col: tuple = OFF, a: float = 1.0,
         shadow: bool = True) -> Sprite:
    """One line of text (anchor: baseline-left), with the shadow stack unless shadow=False."""
    return runs([(s, col, a)], size, kind, shadow)


def runs(parts: list[tuple], size: int, kind: str = "display", shadow: bool = True) -> Sprite:
    """Several coloured runs on one line: [(text, colour, alpha), ...]."""
    key = (tuple(parts), size, kind, shadow)
    if key in _TEXT:
        return _TEXT[key]
    f = font(kind, size)
    s = "".join(p[0] for p in parts)
    bb = f.getbbox(s, anchor="ls")
    pad = 36 if shadow else 6
    x0, top, bot = min(0, bb[0]), min(bb[1], -1), max(bb[3], 1)
    w, h = int(bb[2] - x0) + 2 * pad, int(bot - top) + 2 * pad
    ax, ay = pad - x0, pad - top
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = ax
    for t, col, al in parts:
        d.text((x, ay), t, font=f, fill=rgba(col, al), anchor="ls")
        x += f.getlength(t)
    img = shadow_stack(layer) if shadow else layer
    spr = Sprite(img, ax, ay, bb)
    _TEXT[key] = spr
    return spr


def scaled(spr: Sprite, k: float) -> Sprite:
    """A sprite resized by k (used for the ghost chapter number, a texture rendered at 150)."""
    img = spr.img.resize((max(1, int(spr.img.width * k)), max(1, int(spr.img.height * k))), Image.LANCZOS)
    return Sprite(img, spr.ax * k, spr.ay * k, tuple(v * k for v in spr.ink))


class Shape:
    """Supersampled vector drawing in screen coordinates, finished into a screen-anchored sprite."""

    def __init__(self, x0: float, y0: float, x1: float, y1: float, pad: int = 10, ss: int = 3):
        self.x0, self.y0 = int(math.floor(x0)) - pad, int(math.floor(y0)) - pad
        self.w = int(math.ceil(x1)) + pad - self.x0
        self.h = int(math.ceil(y1)) + pad - self.y0
        self.ss = ss
        self.img = Image.new("RGBA", (self.w * ss, self.h * ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def p(self, x: float, y: float) -> tuple:
        return ((x - self.x0) * self.ss, (y - self.y0) * self.ss)

    def line(self, pts: list[tuple], col: tuple, width: int, a: float = 1.0, caps: bool = True) -> "Shape":
        if len(pts) < 2:
            return self
        fill = rgba(col, a)
        self.d.line([self.p(*q) for q in pts], fill=fill, width=width * self.ss, joint="curve")
        if caps:
            r = width * self.ss / 2
            for q in (pts[0], pts[-1]):
                x, y = self.p(*q)
                self.d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
        return self

    def dashed(self, pts: list[tuple], col: tuple, width: int, a: float = 1.0) -> "Shape":
        for piece in dashes(pts):
            self.line(piece, col, width, a, caps=False)
        return self

    def circle(self, cx: float, cy: float, r: float, fill: tuple | None = None, outline: tuple | None = None,
               width: int = 0, a: float = 1.0) -> "Shape":
        x, y = self.p(cx, cy)
        R = r * self.ss
        self.d.ellipse([x - R, y - R, x + R, y + R], fill=rgba(fill, a) if fill else None,
                       outline=rgba(outline, a) if outline else None, width=width * self.ss)
        return self

    def rect(self, x0: float, y0: float, x1: float, y1: float, fill: tuple | None = None,
             outline: tuple | None = None, width: int = 0, r: int = 0, a: float = 1.0,
             fill_a: float | None = None) -> "Shape":
        assert r in RADII, f"radius {r} is not a token"
        box = [*self.p(x0, y0), *self.p(x1, y1)]
        fa = a if fill_a is None else fill_a
        self.d.rounded_rectangle(box, r * self.ss, fill=rgba(fill, fa) if fill else None,
                                 outline=rgba(outline, a) if outline else None, width=width * self.ss)
        return self

    def polygon(self, pts: list[tuple], fill: tuple, a: float = 1.0) -> "Shape":
        self.d.polygon([self.p(*q) for q in pts], fill=rgba(fill, a))
        return self

    def done(self, shadow: bool = False, k: float = 1.0) -> Sprite:
        img = self.img.resize((self.w, self.h), Image.LANCZOS) if self.ss > 1 else self.img
        if shadow:
            img = shadow_stack(img, k)
        return Sprite(img, -self.x0, -self.y0)


def plate(x0: float, y0: float, x1: float, y1: float, col: tuple = INK, a: float = PLATE_A,
          r: int = 0, shadow: bool = True) -> Sprite:
    return Shape(x0, y0, x1, y1, pad=40 if shadow else 4, ss=2 if r else 1).rect(
        x0, y0, x1, y1, fill=col, r=r, a=a).done(shadow, 0.7)


def hline(x0: float, y: float, x1: float, col: tuple, width: int = LINK, a: float = 1.0) -> Sprite:
    return Shape(x0, y - width, x1, y + width).line([(x0, y), (x1, y)], col, width, a, caps=False).done()


_FULL: dict = {}


def dim(a: float = 0.72) -> Sprite:
    """Full-frame ink wash with a little grey on top, so a dark shot never reads as black in QC."""
    key = ("dim", a)
    if key not in _FULL:
        im = Image.new("RGBA", (W, H), rgba(INK, a))
        im.alpha_composite(Image.new("RGBA", (W, H), rgba(GREY, 0.17)))
        _FULL[key] = Sprite(im)
    return _FULL[key]


def band(top: int, a: float = 0.85, bottom: int = H) -> Sprite:
    """Ink gradient from transparent at `top` to a at `bottom` (eased)."""
    key = ("band", top, a, bottom)
    if key not in _FULL:
        h = bottom - top
        t = np.linspace(0, 1, h, dtype=np.float32)
        al = (a * (1 - (1 - t) ** 2) * 255).astype(np.uint8)
        im = Image.new("RGBA", (W, h), rgba(INK, 0))
        im.putalpha(Image.fromarray(np.repeat(al[:, None], W, axis=1)))
        _FULL[key] = Sprite(im, 0, -top)
    return _FULL[key]


def side_panel(left: int, ramp: int = 180, a: float = 0.88) -> Sprite:
    key = ("panel", left, ramp, a)
    if key not in _FULL:
        w = W - left
        x = np.arange(w, dtype=np.float32)
        al = (np.clip(x / ramp, 0, 1) * a * 255).astype(np.uint8)
        im = Image.new("RGBA", (w, H), rgba(INK, 0))
        im.putalpha(Image.fromarray(np.repeat(al[None, :], H, axis=0)))
        _FULL[key] = Sprite(im, -left, 0)
    return _FULL[key]


# ---------------------------------------------------------------- placements

class P:
    __slots__ = ("img", "x", "y", "a")

    def __init__(self, img: Image.Image, x: int, y: int, a: float):
        self.img, self.x, self.y, self.a = img, x, y, a


_SCALE: dict = {}
_ALPHA: dict = {}


def _scaled_img(img: Image.Image, s: float) -> Image.Image:
    k = (id(img), round(s, 3))
    hit = _SCALE.get(k)
    if hit is None or hit[0] is not img:  # keep the source alive and check identity: ids get reused
        hit = (img, img.resize((max(1, int(round(img.width * s))), max(1, int(round(img.height * s)))),
                               Image.BICUBIC))
        _SCALE[k] = hit
    return hit[1]


def put(spr: Sprite, x: float, y: float, a: float = 1.0, dx: float = 0.0, dy: float = 0.0,
        s: float = 1.0, mask: tuple | None = None, rot: float = 0.0) -> list[P]:
    """Place a sprite. mask = (mode, f) with f 0..1:
      rise  the content slides up into its own window from below (f 1 = at rest); falling f sinks it
      lr/rl a wipe from the left / right edge;  cx/cy  grows from the centre outwards."""
    if a <= 0.004 or s <= 0.01:
        return []
    img = spr.img
    ox, oy = x - spr.ax + dx, y - spr.ay + dy
    if rot:
        big = img.rotate(rot, resample=Image.BICUBIC, expand=True)
        ox -= (big.width - img.width) / 2
        oy -= (big.height - img.height) / 2
        img = big
    if abs(s - 1) > 0.001:
        sm = _scaled_img(img, s)
        ox += (img.width - sm.width) / 2
        oy += (img.height - sm.height) / 2
        img = sm
    if mask:
        mode, f = mask
        f = clamp(f)
        if f <= 0.002:
            return []
        if f < 0.999:
            img, ox, oy = _masked(img, mode, f, ox, oy)
    return [P(img, int(round(ox)), int(round(oy)), clamp(a))]


_CROP: dict = {}


def _masked(img: Image.Image, mode: str, f: float, ox: float, oy: float) -> tuple:
    """Crop for a mask, cached by source and pixel extent so a held mask reuses one image."""
    w, h = img.size
    k = (id(img), mode, int(round(f * 4096)))
    hit = _CROP.get(k)
    if hit is not None and hit[0] is img:
        return hit[1], ox + hit[2], oy + hit[3]
    x0 = y0 = 0
    src = img
    if mode == "rise":
        off = int(round((1 - f) * h))
        img = img.crop((0, 0, w, max(1, h - off)))
        y0 = off
    elif mode == "lr":
        img = img.crop((0, 0, max(1, int(w * f)), h))
    elif mode == "rl":
        c = max(1, int(w * f))
        img = img.crop((w - c, 0, w, h))
        x0 = w - c
    elif mode == "cy":
        hh = max(1, int(h * f / 2))
        img = img.crop((0, h // 2 - hh, w, h // 2 + hh))
        y0 = h // 2 - hh
    elif mode == "cx":
        hw = max(1, int(w * f / 2))
        img = img.crop((w // 2 - hw, 0, w // 2 + hw, h))
        x0 = w // 2 - hw
    else:
        raise ValueError(mode)
    _CROP[k] = (src, img, x0, y0)
    return img, ox + x0, oy + y0


def _faded(img: Image.Image, a: float) -> Image.Image:
    q = int(round(a * 255))
    if q >= 255:
        return img
    k = (id(img), q)
    hit = _ALPHA.get(k)
    if hit is None or hit[0] is not img:
        out = img.copy()
        out.putalpha(img.getchannel("A").point([v * q // 255 for v in range(256)]))
        hit = (img, out)
        _ALPHA[k] = hit
    return hit[1]


def _blit(dst: Image.Image, img: Image.Image, x: int, y: int) -> None:
    w, h = img.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.width, x + w), min(dst.height, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + w, y + h):
        img = img.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    dst.alpha_composite(img, (x0, y0))


# ---------------------------------------------------------------- graphic

class Graphic:
    """n frames at 60 fps; draw(i) returns the frame's placements. enter/exit are frame counts of
    the entrance cascade and of the exit (exit ends on the last frame). meta carries per-kind
    facts for the checks (tools/analysis_motion_check.py)."""

    def __init__(self, kind: str, n: int, enter: int, exit: int, draw: Callable[[int], list[P]],
                 meta: dict | None = None):
        self.kind, self.n, self.enter, self.exit, self.draw = kind, n, enter, exit, draw
        self.meta = meta or {}
        self._pl: list[list[P]] | None = None

    @property
    def secs(self) -> float:
        return self.n / FPS

    def placements(self) -> list[list[P]]:
        if self._pl is None:
            self._pl = [self.draw(i) for i in range(self.n)]
        return self._pl

    def box(self) -> tuple:
        x0 = y0 = 10 ** 9
        x1 = y1 = -10 ** 9
        for pl in self.placements():
            for p in pl:
                x0, y0 = min(x0, p.x), min(y0, p.y)
                x1, y1 = max(x1, p.x + p.img.width), max(y1, p.y + p.img.height)
        if x1 <= x0:
            return (0, 0, 2, 2)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if (x1 - x0) % 2:
            x1 = x1 + 1 if x1 < W else x1
            x0 = x0 - 1 if (x1 - x0) % 2 else x0
        if (y1 - y0) % 2:
            y1 = y1 + 1 if y1 < H else y1
            y0 = y0 - 1 if (y1 - y0) % 2 else y0
        return (x0, y0, x1, y1)

    def compose(self, i: int, box: tuple | None = None) -> Image.Image:
        x0, y0, x1, y1 = box or (0, 0, W, H)
        im = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for p in self.placements()[i]:
            _blit(im, _faded(p.img, p.a), p.x - x0, p.y - y0)
        return im

    def frame(self, i: int) -> Image.Image:
        return self.compose(i)

    def signature(self, i: int) -> tuple:
        return tuple((id(p.img), p.x, p.y, int(round(p.a * 255))) for p in self.placements()[i])

    def export(self, out: Path) -> dict:
        """Encode to a transparent qtrle .mov cropped to the graphic's box; returns x, y, w, h, secs."""
        out.parent.mkdir(parents=True, exist_ok=True)
        box = self.box()
        x0, y0, x1, y1 = box
        tmp = out.with_suffix(".part.mov")
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
                              "-s", f"{x1 - x0}x{y1 - y0}", "-r", str(FPS), "-i", "-",
                              "-c:v", "qtrle", "-pix_fmt", "argb", "-g", "600", str(tmp)],
                             stdin=subprocess.PIPE)  # long GOP: held frames cost almost nothing
        prev, buf = None, b""
        try:
            for i in range(self.n):
                sig = self.signature(i)
                if sig != prev:
                    buf = self.compose(i, box).tobytes()
                    prev = sig
                p.stdin.write(buf)
        finally:
            p.stdin.close()
            rc = p.wait()
            release()
        if rc != 0:
            raise RuntimeError(f"{self.kind} graphic encode failed")
        tmp.replace(out)
        return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "secs": self.secs}

    def free(self) -> None:
        self._pl = None
        release()


def release() -> None:
    """Drop per-frame caches keyed by image id (ids can be reused once those images are freed)."""
    _SCALE.clear()
    _ALPHA.clear()
    _CROP.clear()


if __name__ == "__main__":
    if "--make-fonts" in sys.argv:
        make_static_fonts()
