"""Read-only B2 footage inventory for the long-form analysis format (2026-11-12).

Lists every video object on B2 whose path names a game (any prefix: footage/, cutscenes/,
art-footage/, 4k60fps/), with size and, with --probe, duration and resolution read by
ffprobe over a short-lived presigned URL. Also writes a bucket-wide summary per prefix and
game. Writes output/inventory/<game>.md and .json. Never uploads, moves or deletes.

    python tools/footage_inventory.py wolverine --probe
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import b2_store  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm"}


def probe(key: str) -> dict:
    url = b2_store.presigned_url(key, valid_seconds=3600)
    if not url:
        return {}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
             "-of", "json", url],
            capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or "{}")
        s = (j.get("streams") or [{}])[0]
        return {"seconds": round(float((j.get("format") or {}).get("duration") or 0), 1),
                "width": s.get("width"), "height": s.get("height"), "fps": s.get("r_frame_rate")}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game", nargs="?", default="wolverine")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    game = a.game.lower()

    files = [f for f in b2_store._list_names("")
             if Path(str(f.get("fileName", ""))).suffix.lower() in VIDEO_EXTS]
    summary: dict = defaultdict(lambda: {"count": 0, "bytes": 0})
    rows = []
    for f in files:
        key = str(f["fileName"])
        bits = key.split("/")
        top = bits[0]
        sub = bits[1] if len(bits) > 2 else "(root)"
        summary[f"{top}/{sub}"]["count"] += 1
        summary[f"{top}/{sub}"]["bytes"] += int(f.get("contentLength") or 0)
        if game in key.lower():
            rows.append({"key": key, "folder": "/".join(bits[:-1]), "name": bits[-1],
                         "size_mb": round(int(f.get("contentLength") or 0) / 1e6, 1)})
    if a.probe:
        for i, r in enumerate(rows):
            r.update(probe(r["key"]))
            if i % 25 == 0:
                print(f"probed {i + 1}/{len(rows)}", flush=True)

    out = ROOT / "output" / "inventory"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{game}.json").write_text(json.dumps(
        {"game": game, "files": rows, "bucket_summary": summary}, indent=2), encoding="utf-8")

    by_folder: dict = defaultdict(list)
    for r in rows:
        by_folder[r["folder"]].append(r)
    lines = [f"# B2 inventory: {game}", ""]
    for folder, items in sorted(by_folder.items()):
        secs = sum(r.get("seconds") or 0 for r in items)
        lines.append(f"## {folder}: {len(items)} files, {sum(r['size_mb'] for r in items) / 1000:.1f} GB"
                     + (f", {secs / 60:.0f} min" if secs else ""))
        for r in sorted(items, key=lambda x: x["name"]):
            extra = f" | {r.get('seconds')} s | {r.get('width')}x{r.get('height')}" if r.get("seconds") else ""
            lines.append(f"- {r['name']} | {r['size_mb']} MB{extra}")
        lines.append("")
    lines.append("## Bucket summary (all games)")
    for k, v in sorted(summary.items()):
        lines.append(f"- {k}: {v['count']} files, {v['bytes'] / 1e9:.1f} GB")
    (out / f"{game}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:60]))
    print(f"... {len(rows)} {game} files; full list in output/inventory/{game}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
