"""Clip map for a KG analysis long-form: data/analysis/<game>/clips.json (2026-11-14, Spider-Man 2).

The script's cues name clips two ways: an index from the footage map (the frames index the script
was cued against, output/inventory/frames/<game>/index.json at that time) or a B2 key. This tool
collects both from the script, keeps every index the script uses as it is (an index maps to a
stable B2 key), gives each key-only clip an index from 1000 up (existing assignments are kept, so
the EDL and edits.json stay valid), checks that every key is live on B2, and records each clip's
real duration and frame rate with ffprobe over a short-lived presigned URL. Extra keys (picture
upgrades used only in edits.json) can be added with --key. Read-only on B2.

    python tools/analysis_clips.py <script.md> spider-man2 [--index path] [--key "cutscenes/..."]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from analysis_edl import script_refs  # noqa: E402
from core import b2_store  # noqa: E402

KEY_BASE = 1000


def probe(key: str) -> dict:
    url = b2_store.presigned_url(key, valid_seconds=900) or ""
    if not url:
        return {}
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate:format=duration", "-of", "json", url],
                         capture_output=True, text=True, timeout=120).stdout
    try:
        j = json.loads(out)
        return {"seconds": round(float(j["format"]["duration"]), 2), "fps": j["streams"][0]["r_frame_rate"]}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("game")
    ap.add_argument("--index", default="", help="frames index the script's clip numbers refer to")
    ap.add_argument("--key", action="append", default=[], help="extra B2 key (picture upgrades)")
    a = ap.parse_args()
    d = ROOT / "data/analysis" / a.game
    d.mkdir(parents=True, exist_ok=True)
    path = d / "clips.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    clips: dict[str, dict] = old.get("clips", {})
    idx, keys = script_refs(Path(a.script).read_text(encoding="utf-8"))
    keys |= set(a.key)
    index_path = Path(a.index) if a.index else ROOT / "output/inventory/frames" / a.game / "index.json"
    inv = {int(e["idx"]): e for e in json.loads(index_path.read_text(encoding="utf-8"))} if idx else {}
    problems = []
    for i in sorted(idx):
        if str(i) in clips:
            continue
        if i not in inv:
            problems.append(f"index {i} is not in {index_path.name}")
            continue
        clips[str(i)] = {"key": inv[i]["key"]}
    have = {v["key"]: int(k) for k, v in clips.items()}
    nxt = max([KEY_BASE - 1] + [int(k) for k in clips if int(k) >= KEY_BASE]) + 1
    for k in sorted(keys):
        if k not in have:
            clips[str(nxt)] = {"key": k}
            have[k] = nxt
            nxt += 1
    # Every key must be live on B2.
    live: dict[str, int] = {}
    for prefix in sorted({v["key"].rsplit("/", 1)[0] + "/" for v in clips.values()}):
        for f in b2_store._list_names(prefix):
            live[f["fileName"]] = int(f.get("contentLength") or 0)
    todo = [k for k, v in clips.items() if "seconds" not in v or "fps" not in v]
    for k, v in clips.items():
        if v["key"] not in live:
            problems.append(f"clip {k} not on B2: {v['key']}")
    with ThreadPoolExecutor(8) as ex:
        for k, info in zip(todo, ex.map(lambda k: probe(clips[k]["key"]), todo)):
            if not info:
                problems.append(f"clip {k} could not be probed: {clips[k]['key']}")
            clips[k].update(info)
    # Every cue range must sit inside its clip (and end 2 s before it, playbook 2026-11-13).
    out = {"game": a.game,
           "note": old.get("note") or (
               f"Clip index as used in the script cues. Indices below {KEY_BASE} are the footage-map "
               f"numbers the script was cued against ({index_path.name} at the time); clips the script "
               f"names by B2 key get indices from {KEY_BASE} up. Seconds and fps from ffprobe on B2."),
           "clips": dict(sorted(clips.items(), key=lambda kv: int(kv[0])))}
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(clips)} clips ({len(idx)} by index, {len([k for k in clips if int(k) >= KEY_BASE])} by key) "
          f"-> {path.relative_to(ROOT)}")
    for p in problems:
        print("CHECK:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
