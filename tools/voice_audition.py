"""Narrator auditions for the KG analysis long-form (2026-11-12).

Reads the same short script excerpt in several Google Cloud TTS Chirp 3 HD voices, normalises
each to -14 LUFS so they compare fairly, and reports seconds and words per minute. Needs
GOOGLE_TTS_API_KEY (KG Creative Publisher key, restricted to Cloud Text-to-Speech). Writes
output/inventory/auditions/<voice>.mp3 and auditions.md. Never uploads anywhere.

    python tools/voice_audition.py data/analysis/wolverine/audition.txt Orus Enceladus Algenib
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


RATE = float(os.environ.get("AUDITION_RATE") or 1.0)  # 0.85 = the analysis narration speed


def synth(text: str, voice: str, key: str) -> bytes:
    body = {"input": {"text": text},
            "voice": {"languageCode": "en-US", "name": f"en-US-Chirp3-HD-{voice}"},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 48000,
                            "speakingRate": RATE}}
    req = urllib.request.Request(
        f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return base64.b64decode(json.loads(r.read())["audioContent"])


def main() -> int:
    text_path, voices = Path(sys.argv[1]), sys.argv[2:] or ["Orus", "Enceladus", "Algenib"]
    key = os.environ.get("GOOGLE_TTS_API_KEY", "")
    if not key:
        print("GOOGLE_TTS_API_KEY is not set")
        return 1
    text = text_path.read_text(encoding="utf-8").strip()
    words = len(text.split())
    out = ROOT / "output" / "inventory" / "auditions"
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"# Narrator auditions ({words} words, Chirp 3 HD, rate {RATE}, -14 LUFS)", ""]
    for v in voices:
        wav = out / f"{v}.wav"
        mp3 = out / f"{v}.mp3"
        try:
            wav.write_bytes(synth(text, v, key))
        except Exception as e:
            lines.append(f"- {v}: failed ({e})")
            continue
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav),
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000",
                        "-b:a", "192k", str(mp3)], check=True)
        wav.unlink()
        secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=nw=1:nk=1", str(mp3)],
                                    capture_output=True, text=True).stdout.strip() or 0)
        wpm = words / (secs / 60) if secs else 0
        lines.append(f"- {v}: {secs:.1f} s, {wpm:.0f} wpm")
        print(lines[-1], flush=True)
    (out / "auditions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
