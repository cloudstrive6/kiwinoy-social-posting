"""EditTwin live-stream promo banner — a still JPG and a seamlessly looping MP4.

Both are 1920x320, so the MP4 is a drop-in replacement for the JPG in the same OBS
source. Brand values are taken from edittwin.bosskg.com itself (coral/ink/paper, the
CSS-drawn logo mark, Bricolage Grotesque display type) so the banner reads as the
product's own, not as a generic ad.

    python tools/edittwin_banner.py            # writes both into assets/promo/edittwin/
    python tools/edittwin_banner.py --still    # JPG only (fast)

The looping MP4 animates three things, each periodic over the full loop so the last
frame flows into the first: a coral light sweep, a rotating feature line, and a soft
pulse on the URL pill.
"""
from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets" / "fonts" / "bricolage" / "BricolageGrotesque.ttf"
OUT = ROOT / "assets" / "promo" / "edittwin"

W, H = 1920, 320
INK = (12, 12, 16)
CORAL = (255, 91, 58)
PAPER = (244, 239, 230)
MUTED = (163, 160, 174)
LINE = (46, 46, 56)

FEATURES = ["Cuts the dead air",
            "Writes your hook",
            "Burns in the captions",
            "Learns your style"]

# The message column sits between the divider and the URL pill. Text is auto-fitted to
# it, so editing FEATURES can never push a phrase under the pill.
MSG_X, MSG_RIGHT = 936, 1340

FPS, SECONDS = 30, 9.0


def font(size: int, weight: int = 800, width: int = 100):
    f = ImageFont.truetype(str(FONT), size)
    try:                       # variable axes: Optical size, Weight, Width
        f.set_variation_by_axes([min(96, max(12, size)), weight, width])
    except Exception:
        pass
    return f


def logo_mark(size: int) -> Image.Image:
    """EditTwin's logo, rebuilt from its own CSS: a coral tile with two 'twin' bars,
    one ink and one paper. Drawn at 4x and downsampled so the corners stay clean."""
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * .30), fill=CORAL)
    bw, bh = int(s * .333), int(s * .533)
    top, rad = int(s * .233), int(s * .133)
    d.rounded_rectangle([int(s * .167), top, int(s * .167) + bw, top + bh], radius=rad, fill=INK)
    d.rounded_rectangle([s - int(s * .167) - bw, top, s - int(s * .167), top + bh],
                        radius=rad, fill=PAPER)
    return im.resize((size, size), Image.LANCZOS)


def base_plate() -> Image.Image:
    """Everything that never moves."""
    im = Image.new("RGB", (W, H), INK)
    d = ImageDraw.Draw(im)

    # a very soft coral wash on the left so the lockup is not sitting on flat black
    glow = Image.new("RGB", (W, H), INK)
    ImageDraw.Draw(glow).ellipse([-260, -H, 760, H * 2], fill=(42, 20, 16))
    im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(90)), 0.85)
    d = ImageDraw.Draw(im)

    d.rectangle([0, 0, W, 5], fill=CORAL)                      # top rule
    d.rectangle([0, H - 2, W, H], fill=LINE)                   # hairline bottom

    mark = logo_mark(86)
    im.paste(mark, (84, 60), mark)

    d.text((196, 56), "EditTwin", font=font(78, 800), fill=PAPER)
    d.text((198, 146), "THE AI VIDEO EDITOR THAT EDITS LIKE YOU",
           font=font(26, 700, 95), fill=CORAL)
    d.line([(820, 86), (820, H - 86)], fill=LINE, width=2)     # lockup | message
    return im


def pill(d: ImageDraw.ImageDraw, text: str, cx: int, cy: int, glow: float = 0.0):
    f = font(34, 800)
    tw = d.textlength(text, font=f)
    pw, ph = int(tw) + 80, 76
    x0, y0 = cx - pw // 2, cy - ph // 2
    fill = tuple(min(255, int(c + (255 - c) * glow * .35)) for c in CORAL)
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=ph // 2, fill=fill)
    d.text((cx, cy - 2), text, font=f, fill=(12, 12, 16), anchor="mm")


def sweep_layer(phase: float) -> Image.Image:
    """A wide, soft highlight travelling left to right; wraps for a seamless loop."""
    lay = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(lay)
    band = 460
    x = phase * (W + band * 2) - band
    for i, a in ((0, 26), (1, 40), (2, 26)):          # three stacked bands = soft edges
        off = (i - 1) * band * .33
        d.polygon([(x + off - band / 2, 0), (x + off + band / 2, 0),
                   (x + off + band / 2 + 140, H), (x + off - band / 2 + 140, H)], fill=a)
    return lay.filter(ImageFilter.GaussianBlur(70))


def frame(t: float, still: bool = False) -> Image.Image:
    """t in [0,1) across the loop. still=True freezes the animated bits at their
    strongest: the JPG has no next frame to resolve a fade or a pulse."""
    im = base_plate().convert("RGB")

    sweep = sweep_layer(t)
    im = Image.composite(Image.new("RGB", (W, H), (255, 140, 110)), im, sweep.point(
        lambda v: int(v * .55)))

    d = ImageDraw.Draw(im)

    # rotating feature line — each phrase fades in and out inside its own slot
    n = len(FEATURES)
    pos = t * n
    idx = int(pos) % n
    local = pos - int(pos)
    fade = 1.0 if still else min(1.0, min(local, 1 - local) * 5.0)   # 0 at the seams
    txt = FEATURES[idx]
    col = tuple(int(INK[i] + (PAPER[i] - INK[i]) * fade) for i in range(3))
    dot = tuple(int(INK[i] + (CORAL[i] - INK[i]) * fade) for i in range(3))
    d.ellipse([890, H // 2 - 9, 908, H // 2 + 9], fill=dot)
    size = 40
    while size > 22 and d.textlength(txt, font=font(size, 600)) > MSG_RIGHT - MSG_X:
        size -= 2
    d.text((MSG_X, H // 2), txt, font=font(size, 600), fill=col, anchor="lm")

    # URL pill, breathing once per loop
    pill(d, "edittwin.bosskg.com", W - 330, H // 2,
         glow=0.0 if still else (math.sin(t * 2 * math.pi) + 1) / 2 * 0.6)
    d.text((W - 330, H // 2 + 62), "AI video editing on your own machine",
           font=font(22, 500), fill=MUTED, anchor="mm")
    return im


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--still", action="store_true", help="JPG only")
    a = ap.parse_args()
    if not FONT.exists():
        sys.exit(f"font missing: {FONT}")
    OUT.mkdir(parents=True, exist_ok=True)

    jpg = OUT / "edittwin-live-banner-1920x320.jpg"
    frame(0.0, still=True).save(jpg, quality=94, subsampling=0)     # mid-sweep reads best as a still
    print(f"[banner] {jpg}  ({jpg.stat().st_size // 1024} KB)")
    if a.still:
        return 0

    ff = shutil.which("ffmpeg") or "ffmpeg"
    total = int(FPS * SECONDS)
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(total):
            frame(i / total).save(Path(tmp) / f"f{i:04d}.png")
            if i % 45 == 0:
                print(f"  rendering {i}/{total}", flush=True)
        mp4 = OUT / "edittwin-live-banner-1920x320.mp4"
        subprocess.run([ff, "-y", "-v", "error", "-framerate", str(FPS),
                        "-i", str(Path(tmp) / "f%04d.png"),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        str(mp4)], check=True)
        print(f"[banner] {mp4}  ({mp4.stat().st_size // 1024} KB, {SECONDS:g}s loop)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
