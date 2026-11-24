"""Long-form thumbnails in the measured reference template (v2, 2026-11-24).

Bryce sent five top gaming thumbnails and asked for "all the elements, alignments, design, font design, font
size, font, graphics" and "position of the main subject" to be studied and used. The measured rules are in the
vault: raw-sources/kg-thumbnail-study-2026-11-24/analysis.md. In short:

- two columns: one big subject fills one half; a ~42% column holds the game logo and 1 to 2 words;
- the column fills the height: logo from the top edge, words down to about 0.95;
- every word line is sized to the column width (a short word is set bigger), Anton, white, soft dark shadow;
- the subject's head sits near the top, its body is cut by the bottom edge, centre at x 0.70 (column left)
  or x 0.28 (column right);
- text may overlap the subject's body, never a face (checked: the build stops if it does);
- the bottom-right corner stays free for the duration badge;
- money variant: HUD-style figure with a green wallet ring top-right, change lines right-aligned, logo
  bottom-left over the subject.

    python tools/thumb_template.py <game>   # data/analysis/<game>/thumbs.json -> data/analysis/<game>/thumbs/

thumbs.json: {"logo": "<path>", "items": [{"name", "clip", "at", "column": "left" | "right",
  "place": {"cx": src x of subject centre, "top": src y of crop top, "zoom": crop height / frame height,
            "target_cx": 0.70}, "faces": [[x0, y0, x1, y1] in SOURCE fractions], "lines": ["WORD", "WORD"],
  "letterbox": true (crop black bars first), "money": {"figure": "$0", "lines": ["- $531"], "color": "red"}}]}
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

W, H = 1280, 720
WHITE = (255, 255, 255)
GREEN = (60, 230, 60)
RED = (240, 52, 52)
ANTON = ROOT / "assets/fonts/anton/Anton-Regular.ttf"
HUD = ROOT / "assets/fonts/montserrat/Montserrat-ExtraBold.ttf"
COL_W = 0.42          # column width (fraction of W)
COL_PAD = 0.025       # column distance from the outer edge
BADGE = (int(W * 0.85), int(H * 0.86), W, H)   # duration badge: keep free


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def fit_line(text: str, width: int, max_h: int) -> tuple[ImageFont.FreeTypeFont, tuple]:
    """Largest Anton size whose ink width is <= width and cap height <= max_h."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lo, hi, best = 20, 400, None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(ANTON, mid)
        b = probe.textbbox((0, 0), text, font=f, anchor="ls")
        if b[2] - b[0] <= width and (b[3] - b[1]) <= max_h:
            best, lo = (f, b), mid + 1
        else:
            hi = mid - 1
    return best


def shadow_layer(alpha: Image.Image, blur=12, strength=2.2, offset=(3, 8)) -> Image.Image:
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = alpha.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * strength)))
    sh.putalpha(a)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(sh, offset)
    return out


def logo_sprite(path: Path, w: int) -> Image.Image:
    src = Image.open(path).convert("RGBA")
    a = np.asarray(src.getchannel("A"))
    ys, xs = np.where(a >= 24)                 # trim to the ink, clear the haze
    src = src.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    lg = src.resize((w, int(src.height * w / src.width)), Image.LANCZOS)
    lg.putalpha(lg.getchannel("A").point(lambda v: 0 if v < 24 else v))
    return lg


def place_sprite(canvas: Image.Image, spr: Image.Image, x: int, y: int) -> tuple:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.alpha_composite(spr, (x, y)) if x >= 0 and y >= 0 else layer.paste(spr, (x, y), spr)
    canvas.alpha_composite(shadow_layer(layer.getchannel("A"), blur=10, strength=1.0, offset=(3, 8)))
    canvas.alpha_composite(layer)
    return (x, y, x + spr.width, y + spr.height)


# Image targets measured on the reference thumbnails (study: brightness 111 to 130, contrast 65 to 87,
# saturation 88 to 106 with 6 to 15% strongly saturated pixels, darkest 5% lifted to 9 to 22, edge density
# 13 to 15%). Bryce, 2026-11-24: "study also the contrast of the main image, brightness, saturation".
TARGET = {"bright": 120, "sat": 100, "black": 15}


def grade(im: Image.Image, g: dict) -> Image.Image:
    """Grade a frame towards the reference measurements. Order matters: brightness, contrast, saturation and
    sharpening all move the shadows, so the black point is set last (review 2026-11-24: setting it first left
    the darkest 5% anywhere from 0 to 40)."""
    t = {**TARGET, **g}

    def lum_of(x):
        return 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]
    a = np.asarray(im.convert("RGB")).astype(np.float32) / 255
    # 1. brightness by gamma towards the target mean (night scenes may stay a little darker)
    m = float(lum_of(a).mean())
    a = np.clip(a, 0, 1) ** float(np.clip(np.log(t["bright"] / 255) / np.log(max(m, 1e-3)), 0.45, 1.6))
    # 2. contrast towards the references (65 to 87) around the mean
    L = lum_of(a)
    a = np.clip((a - L.mean()) * float(np.clip((t.get("contrast", 76) / 255) / max(float(L.std()), 1e-3), 0.85, 1.6))
                + L.mean(), 0, 1)
    im = Image.fromarray((a * 255).astype(np.uint8))
    # 3. saturation towards the target mean (fire and neon come down, grey sunlit concrete goes up)
    sat = float(np.asarray(im.convert("HSV"))[..., 1].mean())
    im = ImageEnhance.Color(im).enhance(float(np.clip(t["sat"] / max(sat, 1), 0.4, 1.7)))
    # 4. detail: local contrast, then crisp edges
    im = im.filter(ImageFilter.UnsharpMask(radius=24, percent=35, threshold=2))
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=int(t.get("sharpen", 130)), threshold=3))
    # 5. black point last: the darkest 5% land on t["black"] (lift crushed blacks, pull washed-out ones)
    a = np.asarray(im).astype(np.float32) / 255
    p5 = float(np.percentile(lum_of(a), 5))
    want = t["black"] / 255
    if p5 < want:
        a = (want - p5) + a * (1 - (want - p5))
    elif p5 > want:
        a = np.clip((a - (p5 - want)) / (1 - (p5 - want)), 0, 1)
    im = Image.fromarray((a * 255).clip(0, 255).astype(np.uint8))
    # 6. moving the black point shifts saturation again; one bounded correction pass
    sat = float(np.asarray(im.convert("HSV"))[..., 1].mean())
    return ImageEnhance.Color(im).enhance(float(np.clip(t["sat"] / max(sat, 1), 0.6, 1.5)))


def crop_subject(img: Image.Image, it: dict) -> tuple[Image.Image, tuple]:
    if it.get("letterbox"):
        a = np.asarray(img.convert("L")).mean(axis=1)
        rows = np.where(a > 12)[0]
        img = img.crop((0, int(rows[0]), img.width, int(rows[-1]) + 1))
    sw, sh = img.size
    p = it["place"]
    ch = p["zoom"] * sh
    cw = ch * 16 / 9
    left = p["cx"] * sw - p.get("target_cx", 0.70 if it.get("column", "left") == "left" else 0.28) * cw
    left = min(max(0.0, left), sw - cw)
    top = min(max(0.0, p["top"] * sh), sh - ch)
    box = (left, top, left + cw, top + ch)
    out = grade(img.crop(tuple(int(round(v)) for v in box)).resize((W, H), Image.LANCZOS), it.get("grade", {}))

    def to_out(fb):
        return (int((fb[0] * sw - left) / cw * W), int((fb[1] * sh - top) / ch * H),
                int((fb[2] * sw - left) / cw * W), int((fb[3] * sh - top) / ch * H))
    return out.convert("RGBA"), [to_out(f) for f in it.get("faces", [])]


def overlaps(a, b) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def build(img: Image.Image, it: dict, logo_path: Path, out: Path) -> None:
    im, faces = crop_subject(img, it)
    if not faces:
        raise SystemExit(f"{it['name']}: mark the subject's faces (\"faces\", source fractions) first")
    boxes = []
    if it.get("money"):
        boxes += money_column(im, it["money"])
        lg = logo_sprite(logo_path, int(W * 0.30))
        boxes.append(place_sprite(im, lg, int(W * 0.02), H - lg.height - int(H * 0.03)))
    else:
        col = it.get("column", "left")
        cw = int(W * COL_W * it.get("col_scale", 1.0))
        x0 = int(W * COL_PAD) if col == "left" else W - int(W * COL_PAD) - cw
        lg = logo_sprite(logo_path, int(cw * it.get("logo_scale", 0.9)))
        lines = it["lines"]
        gap = int(H * 0.018)
        top_y = int(H * 0.012)
        tw = min(int(cw * 1.08), W - int(W * COL_PAD) - (x0 if col == "left" else 0)) if col == "left" else int(cw * 1.08)
        tx0 = x0 if col == "left" else x0 + cw - tw          # words may run 8% wider than the logo, as in ref 1
        bottom = int(H * (0.95 if col == "left" else 0.85))      # right column clears the duration badge
        # Words sit straight under the logo (review 2026-11-24: wide Marvel logos left a 12 to 27% gap) and
        # each line grows to the column width; a short word may reach 30% of the height.
        room = bottom - top_y - lg.height - gap * len(lines)
        # Each line fills the column width (so a short word is set bigger, as "GUIDE" under "BEGINNERS"),
        # up to the cap; when the stack is too tall the cap comes down, so the biggest lines give first.
        max_cap = int(H * it.get("max_cap", 0.30))
        while True:
            fitted = [fit_line(t, tw, max_cap) for t in lines]
            text_h = sum(b[3] - b[1] for _, b in fitted) + gap * (len(lines) - 1)
            if text_h <= room + gap or max_cap <= int(H * 0.08):
                break
            max_cap -= 4
        if lg.height + gap + text_h > bottom - top_y:                 # logo shrinks before the words do
            lg = logo_sprite(logo_path, max(60, int(lg.width * (bottom - top_y - gap - text_h) / lg.height)))
        stack = lg.height + gap + text_h
        y0 = top_y + max(0, (bottom - top_y - stack) // 2) if it.get("centre", True) else top_y
        lx = x0 + (cw - lg.width) // 2
        boxes.append(place_sprite(im, lg, lx, y0))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        y = y0 + lg.height + gap
        for (f, b), t in zip(fitted, lines):
            y += b[3] - b[1]
            x = tx0 + (tw - (b[2] - b[0])) // 2 - b[0]
            d.text((x, y - b[3]), t, font=f, fill=WHITE + (255,), anchor="ls")
            boxes.append((x + b[0], y - (b[3] - b[1]), x + b[2], y))
            y += gap
        im.alpha_composite(shadow_layer(layer.getchannel("A")))
        im.alpha_composite(layer)
    for fb in faces:
        for bx in boxes:
            if overlaps(fb, bx):
                raise SystemExit(f"{it['name']}: text or logo {bx} covers a face {fb}; move the subject or the words")
    for bx in boxes:
        if overlaps(bx, BADGE):
            raise SystemExit(f"{it['name']}: {bx} runs into the duration badge corner {BADGE}")
    im.convert("RGB").save(out, quality=93)


def money_column(im: Image.Image, m: dict) -> list:
    """HUD-style money pop, top-right (reference 5)."""
    boxes = []
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    right = int(W * 0.975)
    ring_d = int(H * 0.17)
    rx0, ry0 = right - ring_d, int(H * 0.04)
    d.ellipse((rx0, ry0, rx0 + ring_d, ry0 + ring_d), fill=(18, 22, 20, 235), outline=GREEN + (255,), width=8)
    # wallet glyph (as on the GTA 6 HUD): green body, a darker flap across the top, a clasp tab on the right
    bw, bh = ring_d * 0.52, ring_d * 0.38
    wx0, wy0 = rx0 + (ring_d - bw) / 2, ry0 + (ring_d - bh) / 2 + ring_d * 0.03
    d.rounded_rectangle((wx0, wy0, wx0 + bw, wy0 + bh), radius=int(ring_d * 0.06), fill=GREEN + (255,))
    d.rectangle((wx0 + bw * 0.08, wy0 - ring_d * 0.07, wx0 + bw * 0.80, wy0 + ring_d * 0.015), fill=(40, 150, 40, 255))
    d.rounded_rectangle((wx0 + bw * 0.62, wy0 + bh * 0.32, wx0 + bw * 1.06, wy0 + bh * 0.68), radius=4,
                        fill=(30, 120, 30, 255), outline=(18, 22, 20, 255), width=2)
    boxes.append((rx0, ry0, rx0 + ring_d, ry0 + ring_d))
    fsz = int(H * 0.22)
    f = font(HUD, fsz)
    fig = m["figure"]
    b = d.textbbox((0, 0), fig, font=f, anchor="rs")
    fx = rx0 - int(W * 0.015)
    fy = ry0 + ring_d - int(ring_d * 0.12)
    d.text((fx, fy), fig, font=f, fill=WHITE + (255,), anchor="rs", stroke_width=6, stroke_fill=(10, 10, 10, 255))
    boxes.append((fx + b[0] - 6, fy + b[1] - 6, fx + 6, fy + b[3] + 6))
    col = RED if m.get("color") == "red" else GREEN
    f2 = font(HUD, int(H * 0.17))
    y = fy + int(H * 0.24)
    for t in m["lines"]:
        b2 = d.textbbox((0, 0), t, font=f2, anchor="rs")
        d.text((right, y), t, font=f2, fill=col + (255,), anchor="rs", stroke_width=6, stroke_fill=(10, 10, 10, 255))
        boxes.append((right + b2[0] - 6, y + b2[1] - 6, right + 6, y + b2[3] + 6))
        y += int(H * 0.15)
    im.alpha_composite(shadow_layer(layer.getchannel("A"), blur=8, strength=1.0, offset=(2, 5)))
    im.alpha_composite(layer)
    return boxes


def frame(key: str, at: float, out: Path) -> Image.Image:
    from core import b2_store
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at}", "-i", b2_store.presigned_url(key, 600),
                    "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def main() -> int:
    game = sys.argv[1]
    d = ROOT / "data/analysis" / game
    spec = json.loads((d / "thumbs.json").read_text(encoding="utf-8"))
    clips = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
    outd = d / "thumbs"
    cache = outd / "_frames"
    cache.mkdir(parents=True, exist_ok=True)
    for it in spec["items"]:
        fp = cache / f"{it['name']}.png"
        img = Image.open(fp).convert("RGB") if fp.exists() else frame(clips[str(it["clip"])]["key"], float(it["at"]), fp)
        build(img, it, ROOT / spec["logo"], outd / f"{it['name']}.jpg")
        print("built", outd / f"{it['name']}.jpg", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
