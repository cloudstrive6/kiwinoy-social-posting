"""Narration for a KG analysis long-form: Chirp 3 HD, one take per paragraph (2026-11-12).

Voice and pace come from data/analysis/<game>/edl.json (Bryce picked Orus on 2026-11-12; Orus
reads about 188 wpm at rate 1.0, so 0.85 brings it to the script's 160 wpm plan). Each
narration beat is synthesised from its `tts` text (spoken forms for numbers and "KG"),
normalised to -16 LUFS and cached by a hash of text, voice and rate, so a rerun only re-records
changed paragraphs. Writes output/analysis/<game>/narration/<beat>.wav, timings.json and one
narration_full.mp3 for an ear check. Needs GOOGLE_TTS_API_KEY. Never uploads anywhere.

    python tools/analysis_narrate.py wolverine
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def synth(text: str, voice: str, rate: float, key: str) -> bytes:
    body = {"input": {"text": text},
            "voice": {"languageCode": "en-US", "name": f"en-US-Chirp3-HD-{voice}"},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 48000,
                            "speakingRate": rate}}
    req = urllib.request.Request(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return base64.b64decode(json.loads(r.read())["audioContent"])


def seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "wolverine"
    edl = json.loads((ROOT / "data" / "analysis" / game / "edl.json").read_text(encoding="utf-8"))
    voice, rate = edl["voice"], float(edl["speaking_rate"])
    key = os.environ.get("GOOGLE_TTS_API_KEY", "")
    if not key:
        print("GOOGLE_TTS_API_KEY is not set")
        return 1
    out = ROOT / "output" / "analysis" / game / "narration"
    out.mkdir(parents=True, exist_ok=True)
    tpath = out / "timings.json"
    timings = json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else {}
    narr = [b for b in edl["beats"] if b["type"] == "narr"]
    words = 0
    for b in narr:
        h = hashlib.sha1(f"{voice}|{rate}|{b['tts']}".encode()).hexdigest()[:12]
        wav = out / f"{b['id']}.wav"
        words += len(b["text"].split())
        if wav.exists() and timings.get(b["id"], {}).get("hash") == h:
            continue
        raw = out / f"{b['id']}.raw.wav"
        raw.write_bytes(synth(b["tts"], voice, rate, key))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "loudnorm=I=-16:TP=-2:LRA=11", "-ar", "48000", "-ac", "1",
                        str(wav)], check=True)
        raw.unlink()
        timings[b["id"]] = {"hash": h, "seconds": round(seconds(wav), 3)}
        print(f"{b['id']}: {timings[b['id']]['seconds']:.1f} s", flush=True)
    tpath.write_text(json.dumps(timings, indent=1), encoding="utf-8")
    total = sum(timings[b["id"]]["seconds"] for b in narr)
    # One file for the ear check: every paragraph with a short gap.
    lst = out / "concat.txt"
    gap = out / "gap.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=mono", "-t", "0.5", str(gap)], check=True)
    lst.write_text("".join(f"file '{(out / (b['id'] + '.wav')).as_posix()}'\nfile '{gap.as_posix()}'\n"
                           for b in narr), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-b:a", "160k", str(out / "narration_full.mp3")], check=True)
    report = (f"# Narration: {game}, {voice} at rate {rate}\n\n"
              f"- {len(narr)} paragraphs, {words} words, {total:.0f} s of speech "
              f"({total / 60:.1f} min), {words / (total / 60):.0f} wpm\n")
    (out / "narration.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
