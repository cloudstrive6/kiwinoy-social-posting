"""Edit decision list for a KG analysis long-form, built from its approved script (2026-11-12).

Reads the script's cue sheet (the "## Script" section: [CLIPS idx@a-b (notes)], [GAME AUDIO idx,
a-b s: ...], [GFX ...] and plain narration paragraphs) and writes data/analysis/<game>/edl.json:
an ordered list of beats the renderer plays one after another.

  narr beat: one narration paragraph (TTS text plus the shots that cover it and its graphics)
  game beat: one game-audio burst (narration paused, the clip plays with its own sound)

Graphics specs come from data/analysis/<game>/gfx.json, keyed by the GFX cue id this tool prints
(G01, G02, ...), so the prose cue in the script and the drawn graphic stay linked. Plain code,
no AI, no network.

    python tools/analysis_edl.py <script.md> wolverine
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SEG = re.compile(r"(\d+)@(\d+)-(\d+)\s*(?:\(([^()]*)\))?")
BURST = re.compile(r"GAME AUDIO (\d+),\s*(\d+)-(\d+)\s*s")

# Spoken forms for the TTS input only (captions and the EDL text keep the written form).
TTS_SUBS = [
    (r"\b10,473\b", "ten thousand, four hundred and seventy-three"),
    (r"\b1830\b", "eighteen thirty"),
    (r"\b1800s\b", "eighteen hundreds"),
    (r"\bKG's\b", "K G's"),
    (r"\bKG\b", "K G"),
]


def tts_text(text: str) -> str:
    for pat, rep in TTS_SUBS:
        text = re.sub(pat, rep, text)
    return text


def shot_flags(note: str) -> dict:
    n = (note or "").lower()
    f = {}
    if "crop the subtitle" in n or "crop subtitle" in n:
        f["crop"] = "sub"
    if "crop hud" in n or "crop the hud" in n or "health bars" in n:
        f["crop"] = "hud"
    if "push in" in n:
        f["push"] = True
    if "desaturated" in n:
        f["gray"] = True
    if "blur the gore" in n:
        f["blur"] = True
    return f


def parse(script: str, banned: set[int], hud_clips: set[int] = frozenset()) -> dict:
    body = script.split("## Script", 1)[1].split("## Claims ledger", 1)[0]
    beats: list[dict] = []
    chapters: list[dict] = []
    gfx_cues: list[dict] = []
    shots: list[dict] = []
    gfx: list[str] = []
    pending_chapter = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("Cue key."):
            continue
        if line.startswith("### "):
            head = line[4:]
            m = re.match(r"([\d:]+)\s+(.*)", head)
            title = m.group(2) if m else head
            if title.lower().startswith("chapter"):
                pending_chapter = title.split(":", 1)[1].strip()
            elif m and m.group(1) == "0:00":
                pending_chapter = "Rescue or erasure?"
            continue
        if line.startswith("[CLIPS"):
            split = "split screen" in line.lower()
            segs = []
            for idx, a, b, note in SEG.findall(line):
                s = {"clip": int(idx), "in": float(a), "out": float(b), **shot_flags(note)}
                if int(idx) in hud_clips and "crop" not in s:
                    s["crop"] = "hud"  # editor notes: these clips carry HUD or boss bars
                segs.append(s)
            if split and len(segs) == 2:
                shots.append({"split": segs})
            else:
                shots.extend(segs)
            continue
        if line.startswith("[GFX"):
            gid = f"G{len(gfx_cues) + 1:02d}"
            gfx_cues.append({"id": gid, "cue": line[5:-1].strip()})
            gfx.append(gid)
            continue
        if line.startswith("[GAME AUDIO"):
            m = BURST.search(line)
            if not m:
                raise SystemExit(f"bad burst cue: {line}")
            beat = {"type": "game", "clip": int(m.group(1)), "in": float(m.group(2)),
                    "out": float(m.group(3)), "cue": line[1:-1], **shot_flags(line)}
            if gfx:
                beat["gfx"], gfx = gfx, []
            if pending_chapter:
                beat["chapter"], pending_chapter = pending_chapter, None
            beats.append(beat)
            continue
        if line.startswith("["):
            continue  # [ANALYSIS n: ...] notes for the editor, not rendered
        # Plain paragraph: narration.
        beat = {"type": "narr", "text": line, "tts": tts_text(line), "shots": shots, "gfx": gfx}
        shots, gfx = [], []
        if pending_chapter:
            beat["chapter"], pending_chapter = pending_chapter, None
        beats.append(beat)
    for i, b in enumerate(beats):
        b["id"] = f"b{i:03d}"
    problems = []
    for b in beats:
        used = [s["clip"] for s in b.get("shots", []) if "clip" in s]
        used += [x["clip"] for s in b.get("shots", []) for x in s.get("split", [])]
        if b["type"] == "game":
            used.append(b["clip"])
        bad = sorted(set(used) & banned)
        if bad:
            problems.append(f"{b['id']} uses banned clips {bad}")
        if b["type"] == "narr" and not b["shots"]:
            problems.append(f"{b['id']} has no shots (renderer carries the previous ones on)")
        if b["type"] == "game" and b["out"] - b["in"] > 15:
            problems.append(f"{b['id']} burst over 15 s")
    return {"beats": beats, "gfx_cues": gfx_cues, "problems": problems}


# The BOSS KG narrator (Bryce, 2026-11-13): an ElevenLabs voice designed for the channel ("KG
# Essayist", take 3), read on Multilingual v2. It reads about 176 wpm; speed barely moves that on v2.
NARRATOR = {"provider": "elevenlabs", "name": "BOSS KG Essayist take 3",
            "voice_id": "ms9Irzl0730aqqKYFuVm", "model_id": "eleven_multilingual_v2",
            "stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "speed": 0.9}


def main() -> int:
    script_path, game = Path(sys.argv[1]), sys.argv[2]
    d = ROOT / "data" / "analysis" / game
    # From the script's editor notes (Wolverine): music-risk clips, and clips with HUD or boss bars.
    banned = {88, 89, 90, 111, 112, 128}
    hud = {20, 21, 24, 26, 27, 166, 167}
    res = parse(script_path.read_text(encoding="utf-8"), banned, hud)
    edl = {"game": game, "narrator": NARRATOR, "under_narration_db": -24,
           "source": script_path.name, "beats": res["beats"], "gfx_cues": res["gfx_cues"]}
    (d / "edl.json").write_text(json.dumps(edl, indent=1, ensure_ascii=False), encoding="utf-8")
    narr = [b for b in res["beats"] if b["type"] == "narr"]
    words = sum(len(b["text"].split()) for b in narr)
    bursts = [b for b in res["beats"] if b["type"] == "game"]
    print(f"{len(res['beats'])} beats: {len(narr)} narration ({words} words), {len(bursts)} bursts "
          f"({sum(b['out'] - b['in'] for b in bursts):.0f} s), {len(res['gfx_cues'])} GFX cues")
    for p in res["problems"]:
        print("CHECK:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
