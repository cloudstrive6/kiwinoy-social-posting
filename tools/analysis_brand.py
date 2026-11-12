"""Animated "Subscribe To Boss KG" lower third for KG analysis long-forms (2026-11-13).

Bryce, 2026-11-13: a lower third reminding people to subscribe, appearing 5 seconds into the
video, with his profile photo on top of it; it doubles as a watermark for a few seconds.

The animation is drawn frame by frame with Pillow (no fonts from fontconfig, so it renders the
same locally and in Actions) and encoded once to a transparent QuickTime (qtrle, argb) clip that
the renderer overlays on whichever beats cover its time window. Timing follows the lower-thirds
skill: a staggered enter (photo, then bar, then name, then handle) of about 0.6 s, a readable
hold, and an exit about two thirds as long as the enter.

    python tools/analysis_brand.py --stills out_dir    # enter, hold and exit frames to check
    python tools/analysis_brand.py --mov out.mov        # the overlay clip
"""
from __future__ import annotations

import argparse
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_gfx as gfx  # noqa: E402

ROOT = gfx.ROOT
W, H = gfx.W, gfx.H
FPS = 60
AVATAR = ROOT / "assets/brand/kg-avatar.png"
BRAND_RED = (255, 61, 70, 255)  # KG red #FF3D46

DEFAULTS = {
    "at": 5.0,          # seconds into the video
    "hold": 4.4,        # fully on screen
    "line1": "SUBSCRIBE TO",
    "line1_accent": "BOSS KG",
    "line2": "@Kiwinoy",
    "side": "left",     # the renderer switches to "right" if a title lower third is on screen
}
ENTER, EXIT = 0.62, 0.42


def total_seconds(cfg: dict) -> float:
    return ENTER + float(cfg.get("hold", DEFAULTS["hold"])) + EXIT


def _ease_out_cubic(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _ease_in_cubic(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x ** 3


def _ease_out_back(x: float, s: float = 1.9) -> float:
    x = min(1.0, max(0.0, x))
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def _seg(t: float, a: float, b: float) -> float:
    return 0.0 if t <= a else 1.0 if t >= b else (t - a) / (b - a)


_AV: dict = {}


def _avatar(d: int) -> Image.Image:
    """Round photo with a KG-red ring, d px across (cached per size)."""
    if d in _AV:
        return _AV[d]
    src = Image.open(AVATAR).convert("RGBA")
    big = d * 4
    ph = src.resize((big, big), Image.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    ph.putalpha(Image.fromarray(np.minimum(np.array(ph.getchannel("A")), np.array(mask))))
    ring = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse([0, 0, big - 1, big - 1], outline=BRAND_RED, width=int(big * 0.045))
    out = Image.alpha_composite(ph, ring).resize((d, d), Image.LANCZOS)
    _AV[d] = out
    return out


def frame(t: float, cfg: dict) -> Image.Image:
    """The lower third at t seconds after it starts (0 .. total_seconds)."""
    hold = float(cfg.get("hold", DEFAULTS["hold"]))
    side = cfg.get("side", DEFAULTS["side"])
    l1, acc, l2 = cfg.get("line1", DEFAULTS["line1"]), cfg.get("line1_accent", DEFAULTS["line1_accent"]), \
        cfg.get("line2", DEFAULTS["line2"])
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f1, f2 = gfx.font("display", 58), gfx.font("label", 36)

    out_t = t - (ENTER + hold)  # >= 0 during the exit
    # Progress of each element: enter staggered photo -> bar -> name -> handle; exit reversed, faster.
    if out_t < 0:
        av = _ease_out_back(_seg(t, 0.0, 0.34))
        av_a = _seg(t, 0.0, 0.12)
        bar = _ease_out_cubic(_seg(t, 0.10, 0.48))
        n1 = _ease_out_cubic(_seg(t, 0.26, 0.56))
        n2 = _ease_out_cubic(_seg(t, 0.34, 0.62))
    else:
        n2 = 1 - _ease_in_cubic(_seg(out_t, 0.0, 0.16))
        n1 = 1 - _ease_in_cubic(_seg(out_t, 0.03, 0.20))
        bar = 1 - _ease_in_cubic(_seg(out_t, 0.08, 0.32))
        av = 1 - _ease_in_cubic(_seg(out_t, 0.20, 0.42))
        av_a = av

    margin = 96                        # 5% title-safe
    D = 184                            # photo diameter
    cy = 884                           # photo centre, about 82% down
    bar_h = 124
    pad = 30
    w1 = gfx.tw(d, l1 + " ", f1) + gfx.tw(d, acc, f1)
    w2 = gfx.tw(d, l2, f2)
    bar_w = D // 2 + pad + max(w1, w2) + 44      # from the photo centre to the bar's far end
    if side == "left":
        ax = margin + D // 2
        x0 = ax
        x1 = ax + int(bar_w * bar)
        tx = ax + D // 2 + pad
        sign = 1
    else:
        ax = W - margin - D // 2
        x1 = ax
        x0 = ax - int(bar_w * bar)
        tx = ax - D // 2 - pad - max(w1, w2)
        sign = -1

    if bar > 0.001:
        # Soft shadow, dark bar, KG-red edge at the far end.
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle([x0, cy - bar_h // 2 + 8, x1, cy + bar_h // 2 + 8], fill=(0, 0, 0, 110))
        im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(10)))
        d = ImageDraw.Draw(im)
        d.rectangle([x0, cy - bar_h // 2, x1, cy + bar_h // 2], fill=(14, 14, 18, 232))
        edge = [x1 - 8, cy - bar_h // 2, x1, cy + bar_h // 2] if side == "left" else \
            [x0, cy - bar_h // 2, x0 + 8, cy + bar_h // 2]
        d.rectangle(edge, fill=BRAND_RED)

    # Text sits inside the bar and is revealed with it (clipped to the bar), sliding 30 px.
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    y1, y2 = cy - 4, cy + 40
    if n1 > 0:
        off = int((1 - n1) * 30) * -sign
        a = int(255 * n1)
        td.text((tx + off, y1), l1 + " ", font=f1, fill=(255, 255, 255, a), anchor="ls")
        td.text((tx + off + gfx.tw(td, l1 + " ", f1), y1), acc, font=f1, fill=BRAND_RED[:3] + (a,), anchor="ls")
    if n2 > 0:
        off = int((1 - n2) * 30) * -sign
        td.text((tx + off, y2), l2, font=f2, fill=(200, 200, 208, int(255 * n2)), anchor="ls")
    clip = Image.new("L", (W, H), 0)
    if bar > 0.001:
        ImageDraw.Draw(clip).rectangle([min(x0, x1), cy - bar_h // 2, max(x0, x1), cy + bar_h // 2], fill=255)
    ta = np.minimum(np.array(txt.getchannel("A")), np.array(clip))
    txt.putalpha(Image.fromarray(ta))
    im = Image.alpha_composite(im, txt)

    # The photo sits on top of the bar's near end.
    if av > 0.01 and av_a > 0.01:
        dd = max(2, int(D * av))
        ph = _avatar(D).resize((dd, dd), Image.LANCZOS) if dd != D else _avatar(D)
        if av_a < 1:
            ph = ph.copy()
            ph.putalpha(Image.fromarray((np.array(ph.getchannel("A")) * av_a).astype("uint8")))
        im.alpha_composite(ph, (ax - dd // 2, cy - dd // 2))
    return im


def render_mov(out: Path, cfg: dict) -> tuple[Path, float]:
    """Encode the animation to a transparent qtrle .mov; returns (path, seconds)."""
    secs = total_seconds(cfg)
    n = int(round(secs * FPS))
    out.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "qtrle", "-pix_fmt", "argb", str(out)],
                         stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(frame(i / FPS, cfg).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("brand lower third encode failed")
    return out, secs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", default="")
    ap.add_argument("--mov", default="")
    ap.add_argument("--side", default="left")
    a = ap.parse_args()
    cfg = {**DEFAULTS, "side": a.side}
    if a.stills:
        o = Path(a.stills)
        o.mkdir(parents=True, exist_ok=True)
        for name, t in (("enter-a", 0.15), ("enter-b", 0.40), ("hold", 2.5),
                        ("exit", ENTER + cfg["hold"] + 0.18)):
            frame(t, cfg).save(o / f"lt-{a.side}-{name}.png")
    if a.mov:
        print(render_mov(Path(a.mov), cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
