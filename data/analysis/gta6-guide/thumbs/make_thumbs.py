"""GTA 6 guide thumbnails in the reference template (MrDalekJD study, raw-sources/mrdalekjd-study/thumbnail-analysis.md):
huge logo, 1 to 2 stacked white condensed words with a dark drop shadow (no outline), one huge subject on the other
side, clean sunlit game frame, no arrows or boxes. Run from KG tools/."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

sys.path[:0] = [".", ".."]
import analysis_gfx as G  # noqa: E402

S = Path(sys.argv[1])
LOGO = Image.open("../reels/assets/game-logo/GTA 6 Logo.png").convert("RGBA")
WHITE, RED, GREEN = (245, 243, 238), (240, 64, 64), (76, 217, 100)


def base(img: Image.Image, box) -> Image.Image:
    im = img.convert("RGB").crop(box).resize((1280, 720), Image.LANCZOS)
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.12)).enhance(1.06)
    return im.convert("RGBA")


def darken(im, box, a=0.5, blur=60):
    """Soft dark patch behind text (review 2026-11-24: text on bright haze or a white bus)."""
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rectangle(box, fill=int(255 * a))
    m = m.filter(ImageFilter.GaussianBlur(blur))
    dark = Image.new("RGBA", im.size, (8, 8, 12, 255))
    dark.putalpha(m)
    im.alpha_composite(dark)


def shadowed(im: Image.Image, draw_fn, blur=18, strength=1.25, offset=(0, 10)):
    """Draw text via draw_fn(ImageDraw, fill) onto a layer, then a heavy soft dark shadow under it."""
    txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(txt))
    a = txt.getchannel("A")
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * strength * 1.6))))
    sh2 = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh2.alpha_composite(sh, offset)
    im.alpha_composite(sh2)
    im.alpha_composite(txt)


def logo(im, x, y, w):
    lg = LOGO.resize((w, int(LOGO.height * w / LOGO.width)), Image.LANCZOS)
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    m = Image.new("RGBA", lg.size, (0, 0, 0, 255))
    m.putalpha(lg.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.6)))
    sh.alpha_composite(m, (x, y + 8))
    im.alpha_composite(sh)
    im.alpha_composite(lg, (x, y))
    return lg.height


def grab(name):
    return Image.open(S / f"{name}.png")


# A. BEGINNERS GUIDE: Lucia from behind, head to waist, huge on the left; big logo top-right, two words under it
src = grab("bridge_21")
W, H = src.size
ch = int(H * 0.44); cw = int(ch * 16 / 9)
x0 = 545; y0 = int(H * 0.24)
im = base(src, (x0, y0, x0 + cw, y0 + ch))
darken(im, (760, 0, 1280, 720), 0.5, 140)
h = logo(im, 780, 14, 470)
f = G.font("display", 132)
shadowed(im, lambda d: (d.text((1250, 14 + h + 136), "BEGINNERS", font=f, fill=WHITE, anchor="rs"),
                        d.text((1250, 14 + h + 268), "GUIDE", font=f, fill=WHITE, anchor="rs")))
im.convert("RGB").save(S / "refA.jpg", quality=92)

# B. Money: Jason from behind on the left, cash pop top-right, logo bottom-right. The crocodile, the
# location banner and the game's own HUD figures are cropped out; the top-right is darkened under "$0".
src = grab("money_src")
W, H = src.size
x0, x1 = 538, int(W * 0.92); cw = x1 - x0; ch = int(cw * 9 / 16); y0 = int(H * 0.16)
im = base(src, (x0, y0, x1, y0 + ch))
darken(im, (900, 20, 1280, 320), 0.75, 70)
fb = G.font("display", 140); fs = G.font("display", 110)


def money(d):
    d.text((1240, 160), "$0", font=fb, fill=WHITE, anchor="rs")
    d.text((1240, 290), "- $531", font=fs, fill=RED, anchor="rs")


shadowed(im, money)
logo(im, 860, 380, 390)
im.convert("RGB").save(S / "refB.jpg", quality=92)

# C. BUSTED: the two being arrested fill the left; logo and one big word on the right
src = grab("arrest_1925").convert("RGB").crop((0, 60, 1920, 1020))  # cut the letterbox
W, H = src.size
cw = 1243; ch = int(cw * 9 / 16); x0 = 440; y0 = 63
im = base(src, (x0, y0, x0 + cw, y0 + ch))
darken(im, (820, 0, 1280, 720), 0.45)
h = logo(im, 870, 20, 380)
fc = G.font("display", 176)
shadowed(im, lambda d: d.text((1256, 20 + h + 186), "BUSTED", font=fc, fill=WHITE, anchor="rs"))
im.convert("RGB").save(S / "refC.jpg", quality=92)
print("ok")
