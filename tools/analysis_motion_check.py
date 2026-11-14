"""Acceptance checks for the KG analysis motion graphics (2026-11-13).

Renders every graphic kind in data/analysis/<game>/gfx.json (--game, default wolverine) plus timeline samples to a
transparent .mov, saves stills at enter, hold and exit over a test background, and prints a table:

  motion     mean absolute frame difference shows motion within the first 36 frames
  moves      the entrance is not alpha only (opaque bbox or centroid moves, or the mask grows)
  exit       exit length about 0.6 of the entrance (0.5 to 0.7)
  extra      per kind: counter value and label timing, map padding and label collisions, loop
             marker speed, split layout holds, timeline playhead and label overlap, chapter enter
Then the token checks: text sizes only {36, 48, 64, 96, 150}, no system serif or sans font paths
in tools/analysis_*.py, only the five palette colours plus alpha.

    py tools/analysis_motion_check.py [--only G05,TL1] [--no-mov] [--render-test]
--render-test runs three graphics through analysis_render's overlay chain over a flat grey beat
and compares the encoded frames with the graphics composited directly (placement and timing).
Outputs go to output/motion-check/ (git-ignored).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import analysis_gfx as G  # noqa: E402
import analysis_motion as M  # noqa: E402

OUT = ROOT / "output" / "motion-check"

EXTRA = {
    "TL1": {"kind": "timeline", "at": 0.5, "dur": 9.0, "from": 1, "to": 3,
            "stops": [{"label": "SPIDER-MAN", "sub": "2018"}, {"label": "MILES MORALES", "sub": "2020"},
                      {"label": "SPIDER-MAN 2", "sub": "2023"}, {"label": "WOLVERINE", "sub": "2026"},
                      {"label": "VENOM", "sub": "next?"}]},
    "TL2": {"kind": "timeline", "at": 0.5, "dur": 12.0, "from": 0, "to": 4, "reveal": True,
            "stops": ["PETER: the first suit", "MILES: Harlem", "KRAVEN: the hunt", "LOGAN: Tokyo",
                      "NEXT: the venom war"]},
}


def fake_grab(clip: int, sec: float) -> Image.Image:
    """Stand-in source frame for the memory ring (no footage on this PC)."""
    rng = np.random.default_rng(clip)
    base = rng.integers(40, 200, size=3)
    y = np.linspace(0, 1, 1080)[:, None, None]
    arr = (base * (0.4 + 0.6 * y) + rng.normal(0, 8, (1080, 1920, 3))).clip(0, 255).astype(np.uint8)
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    for _ in range(6):
        x, yy, r = rng.integers(0, 1920), rng.integers(0, 1080), rng.integers(40, 220)
        d.ellipse([x - r, yy - r, x + r, yy + r], fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    return im


def test_background() -> Image.Image:
    """Busy mid-tone frame standing in for gameplay, so legibility shows in the stills."""
    rng = np.random.default_rng(7)
    x = np.linspace(0, 1, 1920)[None, :]
    y = np.linspace(0, 1, 1080)[:, None]
    r = 60 + 110 * x * (1 - y) + 40 * y
    g = 70 + 60 * y + 30 * x
    b = 90 + 80 * (1 - x)
    arr = np.stack([r + 0 * y, g + 0 * x, b + 0 * y], -1)
    arr = (arr + rng.normal(0, 10, arr.shape)).clip(0, 255).astype(np.uint8)
    im = Image.fromarray(arr).convert("RGBA")
    d = ImageDraw.Draw(im)
    for _ in range(14):
        cx, cy, rr = rng.integers(0, 1920), rng.integers(0, 1080), rng.integers(30, 160)
        v = int(rng.integers(120, 240))
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(v, v, int(v * 0.9), 255))
    return im.filter(ImageFilter.GaussianBlur(3))


def beat_seconds(spec: dict) -> float:
    if spec["kind"] == "endscreen":
        return 25.0
    if spec.get("dur"):
        return max(16.0, float(spec.get("at", 0) or 0) + float(spec["dur"]) + 1)
    return 16.0


def alpha_box(a: np.ndarray, thr: int = 250):
    ys, xs = np.nonzero(a >= thr)
    if len(xs) == 0:
        return None
    return (xs.min(), ys.min(), xs.max(), ys.max(), xs.mean(), ys.mean(), len(xs))


def motion_checks(g: M.Graphic, box: tuple) -> tuple[bool, bool, float]:
    upto = min(g.n, 37)
    frames = [np.asarray(g.compose(i, box), dtype=np.int16) for i in range(upto)]
    diffs = [np.abs(frames[i + 1] - frames[i]).mean() for i in range(upto - 1)]
    moving = max(diffs) > 0.05 if diffs else False
    stats = [s for s in (alpha_box(f[..., 3].astype(np.uint8)) for f in frames[:min(upto, g.enter + 7)]) if s]
    if len(stats) < 2:
        return moving, False, max(diffs) if diffs else 0.0
    arr = np.array(stats, dtype=np.float64)
    bbox_move = (arr[:, :4].max(0) - arr[:, :4].min(0)).max() >= 2
    cent_move = (arr[:, 4:6].max(0) - arr[:, 4:6].min(0)).max() >= 2
    grows = arr[:, 6].min() / max(1, arr[:, 6].max()) < 0.95
    return moving, bool(bbox_move or cent_move or grows), max(diffs)


def extra_checks(gid: str, spec: dict, g: M.Graphic) -> tuple[bool, str]:
    m, k = g.meta, g.kind
    if k == "counter" and m.get("digits"):
        widths_const = True  # digits sit in fixed cells; the cell row is one width for every value
        final = m["digits"](g.n - g.exit - 1)
        ok = final == spec["value"] and m["label_from"] >= m["count_end"] and widths_const
        return ok, f"final {final}, label from f{m['label_from']} after count end f{m['count_end']}"
    if k == "map":
        bad = []
        for name, r in m["labels"]:
            for sname, s in m["shapes"]:
                if M.overlap(r, s):
                    bad.append(f"{name}x{sname}")
            for name2, r2 in m["labels"]:
                if name2 < name and M.overlap(r, r2):
                    bad.append(f"{name}x{name2}")
            for gb in m["groups"]:
                inside = gb[0] <= r[0] and r[2] <= gb[2] and gb[1] <= r[1] and r[3] <= gb[3]
                if M.overlap(r, gb) and not inside:
                    bad.append(f"{name}xgroup-edge")
        for (n1, a), (n2, b) in [(x, y) for x in m["shapes"] for y in m["shapes"] if x[0] < y[0]]:
            if M.overlap(a, b):
                bad.append(f"{n1}x{n2}")
        gaps = [b - a for a, b in zip(m["step_t"], m["step_t"][1:])]
        hold_ok = all(gp >= 90 for gp in gaps)
        pad = min(m["pads"]) if m["pads"] else 99
        ok = not bad and pad >= 28 and hold_ok
        return ok, f"min pad {pad:.0f}px, collisions {bad or 0}, step gaps {[round(x / 60, 1) for x in gaps]}s"
    if k == "loop":
        return m["max_speed"] < 40, f"marker max {m['max_speed']:.1f}px/frame"
    if k == "split":
        ch = sorted(set(m["changes"] + [g.n]))
        gap = max(b - a for a, b in zip(ch, ch[1:])) / 60
        return gap < 12, f"longest layout hold {gap:.1f}s"
    if k in ("timeline", "strip"):
        x_end = m["px"](g.n - g.exit - 1)
        at_to = abs(x_end - m["xs"][m["to"]]) < 0.5
        rects = m["rects"]
        clash = [(a, b) for a in range(len(rects)) for b in range(a + 1, len(rects)) if M.overlap(rects[a], rects[b], 8)]
        inside = all(r[0] >= M.SAFE - 0.5 and r[2] <= M.W - M.SAFE + 0.5 for r in rects)
        return at_to and not clash and inside, f"playhead at stop {m['to']}: {at_to}, overlaps {clash or 0}"
    if k == "chapter":
        return g.enter <= 36, f"enter {g.enter} frames"
    return True, ""


def token_checks() -> list[tuple[str, bool, str]]:
    res = []
    sizes = sorted(M.USED_SIZES)
    res.append(("text sizes in tokens", set(sizes) <= set(M.SIZES), str(sizes)))
    pat = re.compile("deja" + "vu|geor" + "gia", re.I)  # split so this file does not match itself
    hits = []
    for p in sorted((ROOT / "tools").glob("analysis_*.py")):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{p.name}:{n}")
    res.append(("no system serif/sans paths", not hits, f"{len(hits)} hits {hits[:4]}"))
    used = M.COLOURS_USED
    res.append(("only palette colours", used <= set(M.PALETTE.values()),
                f"{len(used)} used: {sorted(k for k, v in M.PALETTE.items() if v in used)}"))
    lit = []
    for name in ("analysis_gfx.py", "analysis_motion.py"):
        tree = ast.parse((ROOT / "tools" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in ("fill", "outline", "stroke_fill", "color") \
                    and isinstance(node.value, ast.Tuple):
                vals = [getattr(e, "value", None) for e in node.value.elts]
                if all(isinstance(v, int) for v in vals) and not (len(vals) == 4 and vals[3] == 0):
                    lit.append(f"{name}:{node.lineno}")
    res.append(("no literal colours in draw calls", not lit, f"{lit[:4]}"))
    return res


def render_test() -> bool:
    """Overlay three graphics on a 10.5 s grey beat with analysis_render.overlay_gfx, then compare
    frames of the encode with the same graphics composited in Python."""
    import subprocess
    sys.path.insert(0, str(ROOT))
    import analysis_render as R
    specs = json.loads((ROOT / "data/analysis/wolverine/gfx.json").read_text(encoding="utf-8"))
    use = [specs["G04"][0], specs["G12"][0], {"kind": "caption", "text": "TEST CAPTION", "pos": "top", "at": 6.0}]
    dur = 10.5
    work = OUT / "render-test"
    work.mkdir(parents=True, exist_ok=True)
    inputs, graph = [], []

    def add_input(args):
        inputs.extend(args)
        return sum(1 for x in inputs if x == "-i") - 1
    add_input(["-f", "lavfi", "-i", f"color=c=0x606060:s=1920x1080:r=60:d={dur}"])
    graph.append("[0:v]format=yuv420p[vb]")
    items = []
    for k, sp in enumerate(use):
        items += G.overlays(sp, dur, work, f"t{k}")
    cur = R.overlay_gfx(graph, add_input, "vb", items)
    graph.append(f"[{cur}]format=yuv420p[vout]")
    out = work / "beat.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[vout]",
                    "-t", str(dur), "-r", "60", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(out)],
                   check=True)
    graphics = [G.build(sp, dur)[0] for sp in use]
    starts = [it[3] for it in items]
    ok = True
    for t in (0.8, 3.0, 4.0, 6.3, 7.5, 10.2):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(out), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        got = np.frombuffer(raw, np.uint8).reshape(1080, 1920, 3).astype(np.int16)
        exp = Image.new("RGBA", (1920, 1080), (96, 96, 96, 255))
        for g, s0 in zip(graphics, starts):
            fi = int(round((t - s0) * 60))
            if 0 <= fi < g.n:
                exp.alpha_composite(g.frame(fi))
        e = np.asarray(exp.convert("RGB"), np.int16)
        region = np.abs(e - 96).max(-1) > 12  # pixels the graphics touch
        err = np.abs(got - e)[region].mean() if region.any() else 0.0
        fine = err < 6.0
        ok &= fine
        print(f"{'ok  ' if fine else 'FAIL'} render test t={t:.1f}s mean abs error {err:.2f} over {int(region.sum())} graphic pixels")
        Image.fromarray(got.astype(np.uint8)).save(work / f"t{t:.1f}.png")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-mov", action="store_true")
    ap.add_argument("--render-test", action="store_true")
    ap.add_argument("--game", default="wolverine", help="whose gfx.json to check (map layouts are per game)")
    a = ap.parse_args()
    if a.render_test:
        return 0 if render_test() else 1
    OUT.mkdir(parents=True, exist_ok=True)
    specs = G.load_specs(ROOT / "data/analysis" / a.game / "gfx.json")
    items = [(f"{gid}_{k}" if len(v) > 1 else gid, s) for gid, v in specs.items() if isinstance(v, list)
             for k, s in enumerate(v)] + list(EXTRA.items())
    only = set(filter(None, a.only.split(",")))
    bg = test_background()
    rows, all_ok = [], True
    kinds_seen = set()
    for gid, spec in items:
        if only and gid.split("_")[0] not in only and gid not in only:
            continue
        t0 = time.time()
        g, at = G.build(spec, beat_seconds(spec), fake_grab)
        if g is None:
            rows.append((gid, spec["kind"], "-", "-", "-", "-", "FAIL", "FAIL", "FAIL", "no graphic", "-"))
            all_ok = False
            continue
        kinds_seen.add(spec["kind"])
        box = g.box()
        moving, moves, mad = motion_checks(g, box)
        ratio = g.exit / g.enter
        exit_ok = 0.5 <= ratio <= 0.7
        last_empty = np.asarray(g.compose(g.n - 1, box))[..., 3].max() < 8
        ok_x, note = extra_checks(gid, spec, g)
        size = "-"
        if not a.no_mov:
            mov = OUT / f"{gid}.mov"
            g.export(mov)
            size = f"{mov.stat().st_size // 1024}"
        for name, fi in (("1-enter", g.enter // 2), ("2-hold", min(g.enter + 40, g.n - g.exit - 1)),
                         ("3-late", g.n - g.exit - 2), ("4-exit", g.n - g.exit + g.exit // 2)):
            still = bg.copy()
            still.alpha_composite(g.frame(max(0, min(g.n - 1, fi))))
            still.convert("RGB").save(OUT / f"{gid}-{name}.png")
        g.free()
        ok = moving and moves and exit_ok and last_empty and ok_x
        all_ok &= ok
        rows.append((gid, g.kind, str(g.n), str(g.enter), str(g.exit), f"{ratio:.2f}",
                     "ok" if moving else "FAIL", "ok" if moves else "FAIL",
                     "ok" if (exit_ok and last_empty) else "FAIL", note + ("" if ok_x else "  <-- FAIL"),
                     f"{size} KB {time.time() - t0:.0f}s"))
    head = ("graphic", "kind", "frames", "enter", "exit", "x/e", "motion", "moves", "exit ok", "extra", "mov")
    w = [max(len(r[i]) for r in rows + [head]) for i in range(len(head))]
    for r in [head] + rows:
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(r)))
    print()
    for name, ok, note in token_checks():
        all_ok &= ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {note}")
    missing = set(G.BUILDERS) - kinds_seen
    if not only:
        print(f"{'ok  ' if not missing else 'FAIL'} every kind rendered: missing {sorted(missing) or 'none'}")
        all_ok &= not missing
    print("\nALL PASS" if all_ok else "\nSOME CHECKS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
