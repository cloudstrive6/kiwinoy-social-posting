"""Footage truth audit of a long-form script (Bryce, 2026-11-23, after the beginners guide narrated a robbery
Lucia had stopped: "You need to watch/analyze more the scenes and really know each of the videos/footage/
scenes/gameplay well").

For every narration paragraph of data/analysis/<game>/edl.json, every clip range it shows (plus --pad seconds
of context each side, overlapping ranges merged) goes through tools/footage_check.py: dialogue with times and
frame sheets every 2 s. Writes output/footage-audit/<game>/<beat>.md (the narration, the dialogue, the sheet
paths) for a reviewer who reads the sheets and marks every claim true, false or unclear. Local, read-only on
B2, CPU only.

    python tools/footage_audit.py gta6-guide [--only b011,b012] [--pad 30]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from analysis_edl import strip_tags  # noqa: E402


def merged(ranges: list[tuple[str, float, float]], pad: float, length: dict) -> list[tuple[str, float, float]]:
    by: dict[str, list[list[float]]] = {}
    for key, s, e in ranges:
        by.setdefault(key, []).append([max(0.0, s - pad), min(length.get(key, e + pad), e + pad)])
    out = []
    for key, rs in by.items():
        rs.sort()
        cur = rs[0]
        for r in rs[1:]:
            if r[0] <= cur[1] + 5:
                cur[1] = max(cur[1], r[1])
            else:
                out.append((key, *cur))
                cur = r
        out.append((key, *cur))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--only", default="")
    ap.add_argument("--pad", type=float, default=30.0)
    a = ap.parse_args()
    d = ROOT / "data/analysis" / a.game
    edl = json.loads((d / "edl.json").read_text(encoding="utf-8"))
    clips = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
    length = {c["key"]: float(c.get("seconds") or 0) or 1e9 for c in clips.values()}
    only = set(filter(None, a.only.split(",")))
    out = ROOT / "output/footage-audit" / a.game
    out.mkdir(parents=True, exist_ok=True)
    for b in edl["beats"]:
        if b["type"] != "narr" or (only and b["id"] not in only):
            continue
        rs = []
        for sh in b.get("shots") or []:
            c = clips[str(sh["clip"])]
            s = float(sh.get("in", sh.get("src", 0)) or 0)
            e = float(sh.get("out", s + float(sh.get("dur", 6)) if "dur" in sh else s + 6))
            rs.append((c["key"], s, e))
        parts = []
        for i, (key, s, e) in enumerate(merged(rs, a.pad, length)):
            name = f"{a.game}/{b['id']}-{i + 1}"
            done = ROOT / "output/footage-check" / name / "dialogue.txt"
            if not done.exists():
                subprocess.run([sys.executable, str(ROOT / "tools/footage_check.py"), key, f"{s:.1f}", f"{e:.1f}",
                                "--name", name], check=True, capture_output=True)
            sheets = sorted((ROOT / "output/footage-check" / name).glob("sheet*.jpg"))
            parts.append(f"### Range {i + 1}: `{key}` {s:.1f} to {e:.1f} s (shown range plus {a.pad:.0f} s context)\n\n"
                         f"Sheets: {', '.join(str(p) for p in sheets)}\n\n```\n{done.read_text(encoding='utf-8')}\n```\n")
        shown = "; ".join(f"{clips[str(sh['clip'])]['key'].split('/')[-1]} @ {sh.get('in', sh.get('src'))}"
                          for sh in b.get("shots") or [])
        (out / f"{b['id']}.md").write_text(
            f"# {b['id']}\n\n## Narration\n\n{strip_tags(b['tts'])}\n\n## Shots in the edit\n\n{shown}\n\n"
            f"## Footage\n\n" + "\n".join(parts), encoding="utf-8")
        print(f"{b['id']}: {len(parts)} ranges", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
