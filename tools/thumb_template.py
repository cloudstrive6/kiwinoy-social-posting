"""Long-form thumbnails in the reference template (2026-11-24, Bryce pointed at the MrDalekJD samples; vault
raw-sources/mrdalekjd-study/thumbnail-analysis.md): a big game logo in a corner, 1 to 2 stacked white words with a
heavy dark shadow and no outline, one big subject on the other side, a soft dark patch behind the text, no arrows,
boxes or coloured words. First used for the GTA 6 guide (data/analysis/gta6-guide/thumbs/), then Spider-Man 2 v11
and Wolverine v8.

    python tools/thumb_template.py <game>      # reads data/analysis/<game>/thumbs.json, writes data/analysis/<game>/thumbs/

thumbs.json: {"logo": "reels/assets/game-logo/<file>.png", "items": [{"name", "clip", "at", "crop": [x0, y0, x1, y1]
(fractions of the frame, 16:9 is kept by the height), "lines": ["HE KEPT", "IT"], "side": "left" | "right" | "center",
"logo_w": 420, "size": 140}]}
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import analysis_gfx as G  # noqa: E402

WHITE = (245, 243, 238)


def darken(im, box, a=0.5, blur=90):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rectangle(box, fill=int(255 * a))
    dark = Image.new("RGBA", im.size, (8, 8, 12, 255))
    dark.putalpha(m.filter(ImageFilter.GaussianBlur(blur)))
    im.alpha_composite(dark)


def shadowed(im, draw_fn, blur=18, strength=1.25, offset=(0, 10)):
    txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(txt))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(txt.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * strength * 1.6))))
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    layer.alpha_composite(sh, offset)
    im.alpha_composite(layer)
    im.alpha_composite(txt)


def logo(im, path, x, y, w):
    src = Image.open(path).convert("RGBA")
    lg = src.resize((w, int(src.height * w / src.width)), Image.LANCZOS)
    # 2026-11-24 review: logos that touch their file's edge (Spider-Man 2, Wolverine) got a shadow cut off
    # in a straight line, and the Wolverine file carries a faint haze. Clear the haze, pad before blurring.
    lg.putalpha(lg.getchannel("A").point(lambda v: 0 if v < 24 else v))
    pad = 40
    big = Image.new("RGBA", (lg.width + 2 * pad, lg.height + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(lg, (pad, pad))
    m = Image.new("RGBA", big.size, (0, 0, 0, 255))
    m.putalpha(big.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.6)))
    sh = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh.alpha_composite(m, (int(x), int(y) + 8))
    im.alpha_composite(sh.crop((pad, pad, pad + im.width, pad + im.height)))
    im.alpha_composite(lg, (int(x), int(y)))
    return lg.height


def frame(key: str, at: float, out: Path) -> Image.Image:
    from core import b2_store
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at}", "-i", b2_store.presigned_url(key, 600),
                    "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def build(img: Image.Image, it: dict, logo_path: Path, out: Path) -> None:
    W, H = img.size
    x0, y0, x1, y1 = it["crop"]
    ch = (y1 - y0) * H
    cw = ch * 16 / 9
    left = x0 * W if it.get("anchor", "x0") == "x0" else x1 * W - cw
    box = (int(left), int(y0 * H), int(left + cw), int(y0 * H + ch))
    im = img.crop(box).resize((1280, 720), Image.LANCZOS)
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.1)).enhance(1.05).convert("RGBA")
    side, lw, size = it.get("side", "right"), int(it.get("logo_w", 420)), int(it.get("size", 140))
    f = G.font("display", size)
    lines = it["lines"]
    if side == "right":
        darken(im, (int(1280 * 0.60), 0, 1280, 720), it.get("dark", 0.5))
        h = logo(im, logo_path, 1280 - lw - 30, 26, lw)
        xa, anchor = 1250, "rs"
    elif side == "left":
        darken(im, (0, 0, int(1280 * 0.40), 720), it.get("dark", 0.5))
        h = logo(im, logo_path, 30, 26, lw)
        xa, anchor = 34, "ls"
    else:
        darken(im, (380, 0, 900, 720), it.get("dark", 0.45))
        h = logo(im, logo_path, 640 - lw // 2, 22, lw)
        xa, anchor = 640, "ms"
    top = int(it.get("text_top", 26 + h + size + 10))
    # FACE KEEP-OUT (Bryce, 2026-11-24: "the words/logo are partly covering Jean's face"). Every item marks
    # its faces in output fractions; text or logo touching one is an error, never a saved thumbnail.
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    boxes = [probe.textbbox((xa, top + k * (size + 4)), ln, font=f, anchor=anchor) for k, ln in enumerate(lines)]
    lx = {"right": 1280 - lw - 30, "left": 30}.get(side, 640 - lw // 2)
    boxes.append((lx, 22, lx + lw, 26 + h))
    if "keep_clear" not in it:
        raise SystemExit(f"{it['name']}: mark the faces with keep_clear [x0, y0, x1, y1] (fractions) first")
    for kc in ([it["keep_clear"]] if isinstance(it["keep_clear"][0], (int, float)) else it["keep_clear"]):
        fx0, fy0, fx1, fy1 = kc[0] * 1280, kc[1] * 720, kc[2] * 1280, kc[3] * 720
        for bx0, by0, bx1, by1 in boxes:
            if bx0 < fx1 and bx1 > fx0 and by0 < fy1 and by1 > fy0:
                raise SystemExit(f"{it['name']}: text or logo covers a face area {kc}; move the crop or the text")
    shadowed(im, lambda d: [d.text((xa, top + k * (size + 4)), ln, font=f, fill=WHITE, anchor=anchor)
                            for k, ln in enumerate(lines)])
    im.convert("RGB").save(out, quality=92)


def main() -> int:
    game = sys.argv[1]
    d = ROOT / "data/analysis" / game
    spec = json.loads((d / "thumbs.json").read_text(encoding="utf-8"))
    clips = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
    outd = d / "thumbs"
    outd.mkdir(exist_ok=True)
    cache = outd / "_frames"
    cache.mkdir(exist_ok=True)
    for it in spec["items"]:
        key = clips[str(it["clip"])]["key"]
        fp = cache / f"{it['name']}.png"
        img = Image.open(fp).convert("RGB") if fp.exists() else frame(key, float(it["at"]), fp)
        build(img, it, ROOT / spec["logo"], outd / f"{it['name']}.jpg")
        print("built", outd / f"{it['name']}.jpg", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
