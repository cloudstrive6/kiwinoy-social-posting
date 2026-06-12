"""Render one designed Graphic PNG (for previews/tests).

Usage:
  python tools/render_graphic.py --headline "MVP" --sublabel "NBA FINALS"
  python tools/render_graphic.py --headline "ONIC SWEEP" --image assets/images/mlbb/x.jpg
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import graphic  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--headline", required=True)
p.add_argument("--sublabel", default="")
p.add_argument("--image", default=None)
p.add_argument("--accent", default=None)
p.add_argument("--size", default="1080x1350")
p.add_argument("--out", default="output/graphic_preview.png")
a = p.parse_args()

img = Path(a.image) if a.image else None
out = Path(a.out)
data = graphic.render(img, a.headline, out, sublabel=a.sublabel,
                      accent=a.accent, size=a.size)
print(f"rendered -> {out} ({len(data)//1024} KB)")
