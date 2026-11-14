"""Edit decision list for a KG analysis long-form, built from its approved script (2026-11-12).

Reads the script's cue sheet (the "## Script" section: [CLIPS idx@a-b (notes)], [GAME AUDIO idx,
a-b s: ...], [GFX ...] and plain narration paragraphs) and writes data/analysis/<game>/edl.json:
an ordered list of beats the renderer plays one after another.

  narr beat: one narration paragraph (TTS text plus the shots that cover it and its graphics)
  game beat: one game-audio burst (narration paused, the clip plays with its own sound)

Clip references come in two forms (2026-11-14, Spider-Man 2): a clip index from the footage map
(`488@150-159.4`) or a B2 key (`cutscenes/spider-man2/Spider-Man 2 (2026-11-13 22-21-27).mp4 @
18.5-20.75`). Seconds may be decimal. B2 keys are resolved to their index in
data/analysis/<game>/clips.json (tools/analysis_clips.py gives key-only clips indices from 1000
up). Graphics specs come from data/analysis/<game>/gfx.json, keyed by the GFX cue id this tool
prints (G01, G02, ...), so the prose cue in the script and the drawn graphic stay linked. Plain
code, no AI, no network.

    python tools/analysis_edl.py <script.md> wolverine
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NUM = r"\d+(?:\.\d+)?"
KEY = r"(?:cutscenes|footage|art-footage|4k60fps|4k-hdr|4k-vertical)/[^@\[\]]+?\.(?:mp4|mkv|mov)"
# One clip reference: a B2 key or a footage-map index, then "@ start-end".
REF = re.compile(rf"(?P<key>{KEY})\s*@\s*(?P<a>{NUM})-(?P<b>{NUM})"
                 rf"|(?<![\w./@-])(?P<idx>\d+)@(?P<ia>{NUM})-(?P<ib>{NUM})")
BURST = re.compile(rf"GAME AUDIO (?:(?P<idx>\d+),\s*|(?P<key>{KEY})\s*@\s*)(?P<a>{NUM})-(?P<b>{NUM})\s*s")

# Spoken forms for the TTS input only (captions and the EDL text keep the written form).
TTS_SUBS = [
    (r"\b10,473\b", "ten thousand, four hundred and seventy-three"),
    (r"\b1830\b", "eighteen thirty"),
    (r"\b1800s\b", "eighteen hundreds"),
    (r"\bKG's\b", "K G's"),
    (r"\bKG\b", "K G"),
]
# Per-game spoken forms (the script's pronunciation notes), applied after TTS_SUBS. Kept per game so
# regenerating an older game's EDL never changes its recorded narration.
TTS_GAME = {
    "spider-man2": [
        (r"\bF\.E\.A\.S\.T\.", "FEAST"),
        (r"\bDr\. ", "Doctor "),
        (r"\bLi\b", "Lee"),            # Martin Li: LEE
        (r"\bEmily-May\b", "Emily May"),
        (r"\bG-Serum\b", "G serum"),
    ],
}


def tts_text(text: str, game: str = "") -> str:
    for pat, rep in TTS_SUBS + TTS_GAME.get(game, []):
        text = re.sub(pat, rep, text)
    return text


def shot_flags(note: str, game_beat: bool = False) -> dict:
    n = (note or "").lower()
    f = {}
    if "crop the subtitle" in n or "crop subtitle" in n:
        f["crop"] = "sub"
    if "crop hud" in n or "crop the hud" in n or "health bars" in n:
        f["crop"] = "hud"
    if '"crop": "none"' in n:
        f["crop"] = "none"  # the narration points at on-screen text: show the whole frame
    elif game_beat and "crop" not in f and re.search(r"crop (?:the )?sides|crop top 10%", n):
        f["crop"] = "band"  # bursts keep the subtitle band, lose the HUD at the top and sides
    elif not game_beat and "crop" not in f and "hud" in n and re.search(r"\bcrop (?:it|hud)\b", n):
        f["crop"] = "hud"  # "free-roam HUD, crop it", "crop HUD and minimap"
    if "push in" in n:
        f["push"] = True
    if "desaturated" in n:
        f["gray"] = True
    if "blur the gore" in n:
        f["blur"] = True
    return f


def refs(text: str) -> list[tuple[dict, str]]:
    """Every clip reference in a cue line, each with its note (balanced brackets, so notes may hold
    their own parentheses, and B2 keys may too)."""
    out, i = [], 0
    while True:
        m = REF.search(text, i)
        if not m:
            return out
        j, note = m.end(), ""
        k = j
        while k < len(text) and text[k] == " ":
            k += 1
        if k < len(text) and text[k] == "(":
            depth, s = 0, k
            while k < len(text):
                depth += {"(": 1, ")": -1}.get(text[k], 0)
                if depth == 0:
                    break
                k += 1
            note, j = text[s + 1:k], k + 1
        if m.group("key"):
            r = {"key": m.group("key").strip(), "in": float(m.group("a")), "out": float(m.group("b"))}
        else:
            r = {"clip": int(m.group("idx")), "in": float(m.group("ia")), "out": float(m.group("ib"))}
        out.append((r, note))
        i = j


def script_body(script: str) -> str:
    """The cue sheet: from "## Script" to the next level-2 heading (Humor beats, Claims ledger...)."""
    return re.split(r"\n## ", script.split("## Script", 1)[1], maxsplit=1)[0]


def script_refs(script: str) -> tuple[set[int], set[str]]:
    """Clip indices and B2 keys the script's cues use (for tools/analysis_clips.py)."""
    idx, keys = set(), set()
    for raw in script_body(script).splitlines():
        line = raw.strip()
        if line.startswith("[CLIPS"):
            for r, _ in refs(line):
                (keys.add(r["key"]) if "key" in r else idx.add(r["clip"]))
        elif line.startswith("[GAME AUDIO"):
            m = BURST.search(line)
            if m:
                (keys.add(m.group("key").strip()) if m.group("key") else idx.add(int(m.group("idx"))))
    return idx, keys


def opening_chapter(script: str, default: str = "Rescue or erasure?") -> str:
    """The 0:00 chapter title from the script's YouTube chapters block (Wolverine kept its own)."""
    m = re.search(r"### YouTube chapters.*?```\s*\n0:00 ([^\n]+)", script, re.S)
    return m.group(1).strip() if m else default


def parse(script: str, banned: set[int], hud_clips: set[int] = frozenset(), game: str = "",
          key_index: dict[str, int] | None = None, clip_crops: dict | None = None) -> dict:
    body = script_body(script)
    key_index = key_index or {}
    beats: list[dict] = []
    gfx_cues: list[dict] = []
    shots: list[dict] = []
    gfx: list[str] = []
    problems: list[str] = []
    pending_chapter = None
    opening = opening_chapter(script)

    def clip_of(r: dict) -> int:
        if "key" not in r:
            return r["clip"]
        if r["key"] not in key_index:
            problems.append(f"B2 key not in clips.json: {r['key']}")
            return -1
        return key_index[r["key"]]

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
                pending_chapter = opening
            continue
        if line.startswith("[CLIPS"):
            low = line.lower()
            split = "split screen" in low or low.startswith("[clips split:")
            segs = []
            for r, note in refs(line):
                s = {"clip": clip_of(r), "in": r["in"], "out": r["out"], **shot_flags(note)}
                if s["clip"] in hud_clips and "crop" not in s:
                    s["crop"] = "hud"  # editor notes: these clips carry HUD or boss bars
                if s["clip"] in (clip_crops or {}) and s.get("crop") in (None, "hud"):
                    s["crop"] = clip_crops[s["clip"]]  # a tighter crop where the HUD reaches further in
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
            if m.group("key"):
                clip = clip_of({"key": m.group("key").strip()})
            else:
                clip = int(m.group("idx"))
            beat = {"type": "game", "clip": clip, "in": float(m.group("a")),
                    "out": float(m.group("b")), "cue": line[1:-1], **shot_flags(line, game_beat=True)}
            if gfx:
                beat["gfx"], gfx = gfx, []
            if pending_chapter:
                beat["chapter"], pending_chapter = pending_chapter, None
            beats.append(beat)
            continue
        if line.startswith("["):
            continue  # [ANALYSIS n: ...] notes for the editor, not rendered
        # Plain paragraph: narration.
        beat = {"type": "narr", "text": line, "tts": tts_text(line, game), "shots": shots, "gfx": gfx}
        shots, gfx = [], []
        if pending_chapter:
            beat["chapter"], pending_chapter = pending_chapter, None
        beats.append(beat)
    for i, b in enumerate(beats):
        b["id"] = f"b{i:03d}"
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
        if b["type"] == "narr" and re.search(r"\bKG\b|Kiwinoy", b["text"]):
            problems.append(f"{b['id']} names KG in the narration (the narrator is KG: first person)")
    return {"beats": beats, "gfx_cues": gfx_cues, "problems": problems}


# The BOSS KG narrator (Bryce, 2026-11-13): "BOSS KG Narrator A", designed on Bryce's Starter
# workspace to match his first pick ("KG Essayist" take 3, stuck in another workspace; voice-print
# match 0.945), read on Multilingual v2. Speed 0.95 is the speed Bryce heard take 3 at when he chose
# it (0.9 read 13 to 16% slower than take 3).
NARRATOR = {"provider": "elevenlabs", "name": "BOSS KG Narrator A",
            "voice_id": "Jn6g1Ws0FHFBiECPird2", "model_id": "eleven_multilingual_v2",
            "stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "speed": 0.95,
            "master": "C"}  # narrator mastering preset (tools/analysis_narrate.py MASTERS), Bryce 2026-11-15

# From each script's editor notes: music-risk or banned clips, and clips with HUD or boss bars.
GAME_NOTES = {
    "wolverine": {"banned": {88, 89, 90, 111, 112, 128}, "hud": {20, 21, 24, 26, 27, 166, 167}},
    # Spider-Man 2 script v1.2 "Notes for the editor": HUD and boss bars (old 619-clip index).
    # 2026-11-14 build: frame sheets of every shot added free-roam and fight clips whose cues do not say so.
    "spider-man2": {"banned": set(), "hud": {478, 483, 517, 520, 529, 532, 533, 534, 552, 611, 300, 526,
                                             159, 419, 492, 512, 560, 597},
                    # test render 1: the boss fights keep an objective box top right (inside the hud crop)
                    # and 492's traversal gauge sits at 15-19% of the width.
                    "crops": {529: "boss", 532: "boss", 533: "boss", 534: "boss", 492: [0.2, 0.12, 0.8, 0.72]}},
}


def main() -> int:
    script_path, game = Path(sys.argv[1]), sys.argv[2]
    d = ROOT / "data" / "analysis" / game
    notes = GAME_NOTES.get(game, {"banned": set(), "hud": set()})
    key_index = {}
    if (d / "clips.json").exists():
        cm = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
        for k, v in sorted(cm.items(), key=lambda kv: -int(kv[0])):  # lowest index wins
            key_index[v["key"]] = int(k)
    script = script_path.read_text(encoding="utf-8")
    res = parse(script, notes["banned"], notes["hud"], game, key_index, notes.get("crops"))
    edl = {"game": game, "narrator": NARRATOR, "under_narration_db": -24,
           "source": script_path.name, "beats": res["beats"], "gfx_cues": res["gfx_cues"]}
    (d / "edl.json").write_text(json.dumps(edl, indent=1, ensure_ascii=False), encoding="utf-8")
    narr = [b for b in res["beats"] if b["type"] == "narr"]
    words = sum(len(b["text"].split()) for b in narr)
    bursts = [b for b in res["beats"] if b["type"] == "game"]
    print(f"{len(res['beats'])} beats: {len(narr)} narration ({words} words, "
          f"{sum(len(b['tts']) for b in narr)} TTS characters), {len(bursts)} bursts "
          f"({sum(b['out'] - b['in'] for b in bursts):.0f} s), {len(res['gfx_cues'])} GFX cues")
    for p in res["problems"]:
        print("CHECK:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
