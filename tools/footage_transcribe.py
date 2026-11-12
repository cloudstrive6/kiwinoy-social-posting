"""Timestamped dialogue transcripts of a game's analysis footage (read-only, 2026-11-12).

Approved by Bryce 2026-11-12 ("Yes, transcribe") for the first analysis video. Streams each
clip's audio from B2 over a short-lived presigned URL (ffmpeg, 16 kHz mono, nothing kept),
transcribes it with faster-whisper on the CPU (free, open source) and writes
output/inventory/transcripts/<game>/<idx>.json plus one transcript.md in clip order.
Sources: every B2 clip of the game under cutscenes/ and footage/ (rule: any footage of the
same game; automated runs use B2 only). Never uploads or deletes.

    python tools/footage_transcribe.py wolverine [--model small.en]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import b2_store  # noqa: E402

# Spelling hints only (names from core/lore.py), so Whisper writes them correctly.
NAMES = {
    "wolverine": "Logan, Wolverine, James Howlett, Jean Grey, Phoenix, Sabretooth, Victor Creed, "
                 "Mystique, Nathaniel Essex, Mister Sinister, Omega Red, Arkady Rossovich, "
                 "Apocalypse, Trask, Reavers, Sentinel, Helix Engine, Madripoor, Shiro Yoshida, "
                 "Sunfire, Lady Deathstrike, the Hand, Weapon X, Canada, Japan.",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game", nargs="?", default="wolverine")
    ap.add_argument("--model", default="small.en")
    a = ap.parse_args()
    game = a.game.lower()

    from faster_whisper import WhisperModel  # installed by the workflow step only

    clips = ([dict(c, pool="cutscenes") for c in b2_store.list_cutscenes(game)]
             + [dict(c, pool="footage") for c in b2_store.list_footage(game)])
    clips.sort(key=lambda c: (c["pool"], c["name"]))
    out = ROOT / "output" / "inventory" / "transcripts" / game
    out.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=4)
    prompt = NAMES.get(game, "")
    md = [f"# Dialogue transcripts: {game} ({len(clips)} clips, model {a.model})", ""]
    t0 = time.time()
    for i, c in enumerate(clips):
        url = b2_store.presigned_url(c["key"], valid_seconds=3600) or ""
        segs = []
        if url:
            with tempfile.TemporaryDirectory() as td:
                wav = Path(td) / "a.wav"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", url, "-vn", "-ac", "1",
                                "-ar", "16000", str(wav)], capture_output=True, timeout=600)
                if wav.exists():
                    parts, _ = model.transcribe(str(wav), language="en", beam_size=1,
                                                vad_filter=True, initial_prompt=prompt,
                                                condition_on_previous_text=False)
                    segs = [{"start": round(s.start, 1), "end": round(s.end, 1),
                             "text": s.text.strip()} for s in parts]
        (out / f"{i:03d}.json").write_text(json.dumps(
            {"idx": i, "pool": c["pool"], "name": c["name"], "key": c["key"], "segments": segs},
            indent=1), encoding="utf-8")
        md.append(f"## #{i} {c['pool']} | {c['name']}")
        md += [f"- [{s['start']:.0f}s] {s['text']}" for s in segs] or ["- (no speech)"]
        md.append("")
        print(f"{i + 1}/{len(clips)} {len(segs)} segs, {time.time() - t0:.0f}s", flush=True)
    (out / "transcript.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
