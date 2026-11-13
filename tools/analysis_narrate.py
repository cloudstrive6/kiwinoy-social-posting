"""Narration for a KG analysis long-form, one take per paragraph (2026-11-12, ElevenLabs 2026-11-13).

Narrator: if edl.json has a "narrator" block, that voice is used (ElevenLabs; from 2026-11-13 the
BOSS KG voice is "BOSS KG Narrator A", designed for the channel and picked by Bryce, on
Multilingual v2). Older EDLs carry "voice" and "speaking_rate" and keep their Chirp 3 HD voice
(Wolverine: Orus at 0.85), so a rerun never changes a published video's voice. A video never mixes
voices: if ElevenLabs fails (for example the monthly credit cap), the run stops with the reason.
ElevenLabs takes get the previous and next paragraph as context so the delivery flows. Each
narration beat is synthesised from its `tts` text (spoken forms for numbers and "KG"),
normalised to -16 LUFS and cached by a hash of text, voice and rate, so a rerun only re-records
changed paragraphs. Writes output/analysis/<game>/narration/<beat>.wav, timings.json and one
narration_full.mp3 for an ear check. Needs ELEVENLABS_API_KEY or GOOGLE_TTS_API_KEY. Never
uploads anywhere.

    python tools/analysis_narrate.py wolverine
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
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


def synth_el(text: str, nar: dict, key: str, prev: str = "", nxt: str = "") -> bytes:
    """ElevenLabs: MP3 bytes. Stops the run with ElevenLabs' own message (quota, auth) on failure."""
    body = {"text": text, "model_id": nar.get("model_id", "eleven_multilingual_v2"),
            "voice_settings": {"stability": nar.get("stability", 0.5),
                               "similarity_boost": nar.get("similarity_boost", 0.75),
                               "style": nar.get("style", 0.0), "use_speaker_boost": True,
                               "speed": nar.get("speed", 1.0)}}
    if prev:
        body["previous_text"] = prev
    if nxt:
        body["next_text"] = nxt
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{nar['voice_id']}?output_format=mp3_44100_128",
        data=json.dumps(body).encode(), headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ElevenLabs refused the take ({e.code}): {e.read().decode()[:300]}")


def trim_tail(wav: Path) -> bool:
    """Cut a paragraph 150 ms after its last word, with a 30 ms fade (2026-11-13, v6 review): ElevenLabs
    takes sometimes end with a 50-100 ms tick or thump 0.2-0.8 s after the last word, loud enough to
    survive the -50 dB silence trim. The last word is the last run of at least 120 ms within 32 dB of
    the paragraph's peak level; shorter blips after it are dropped. Returns True if the file changed."""
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    hop = 480  # 10 ms
    n = len(x) // hop
    if n < 30:
        return False
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    loud = db > db.max() - 32
    end, run = None, 0
    for i in range(n - 1, -1, -1):
        run = run + 1 if loud[i] else 0
        if run >= 12:  # 120 ms of voice
            j = i
            while j + 1 < n and loud[j + 1]:
                j += 1
            end = (j + 1) * hop
            break
    if end is None:
        return False
    cut = min(len(x), end + int(0.15 * 48000))
    if len(x) - cut < int(0.05 * 48000):
        return False
    y = x[:cut].copy()
    f = int(0.03 * 48000)
    y[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", "-", str(wav)],
                   input=(np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes(), check=True)
    return True


def seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "wolverine"
    edl = json.loads((ROOT / "data" / "analysis" / game / "edl.json").read_text(encoding="utf-8"))
    nar = edl.get("narrator")
    if nar:  # ElevenLabs; the voice is found by name, so the same EDL works on any KG account
        voice, rate = nar["name"], float(nar.get("speed", 1.0))
        key0 = os.environ.get("ELEVENLABS_API_KEY", "")
        if key0:
            q = urllib.request.Request(
                "https://api.elevenlabs.io/v2/voices?page_size=100&search=" + urllib.request.quote(voice),
                headers={"xi-api-key": key0})
            with urllib.request.urlopen(q, timeout=60) as r:
                found = [v["voice_id"] for v in json.loads(r.read()).get("voices", []) if v.get("name") == voice]
            if not found:
                raise SystemExit(f"ElevenLabs voice '{voice}' is not on this account; run step voice-setup first.")
            nar = dict(nar, voice_id=found[0])
        tag = f"el|{voice}|{nar.get('model_id')}|{nar.get('stability')}|{nar.get('style')}|{nar.get('speed')}"
        key = os.environ.get("ELEVENLABS_API_KEY", "")
        need = "ELEVENLABS_API_KEY"
    else:  # Chirp 3 HD (videos made before 2026-11-13)
        voice, rate = edl["voice"], float(edl["speaking_rate"])
        tag = voice
        key = os.environ.get("GOOGLE_TTS_API_KEY", "")
        need = "GOOGLE_TTS_API_KEY"
    if not key:
        print(f"{need} is not set")
        return 1
    out = ROOT / "output" / "analysis" / game / "narration"
    out.mkdir(parents=True, exist_ok=True)
    tpath = out / "timings.json"
    timings = json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else {}
    narr = [b for b in edl["beats"] if b["type"] == "narr"]
    words = 0
    if nar:  # never start a video the month's ElevenLabs credits cannot finish (no half-voiced cuts)
        todo = 0
        for b in narr:
            h = hashlib.sha1(f"{tag}|{rate}|{b['tts']}".encode()).hexdigest()[:12]
            if not ((out / f"{b['id']}.wav").exists() and timings.get(b["id"], {}).get("hash") == h):
                todo += len(b["tts"])
        if todo:
            req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription",
                                         headers={"xi-api-key": key})
            with urllib.request.urlopen(req, timeout=60) as r:
                sub = json.loads(r.read())
            left = int(sub["character_limit"]) - int(sub["character_count"])
            print(f"ElevenLabs: {todo} characters to record, {left} credits left this month "
                  f"({sub.get('tier')})", flush=True)
            if todo > left:
                raise SystemExit(f"Not enough ElevenLabs credits: need {todo}, have {left}. "
                                 "Nothing was recorded. Upgrade the plan or wait for the monthly reset.")
    for i, b in enumerate(narr):
        h = hashlib.sha1(f"{tag}|{rate}|{b['tts']}".encode()).hexdigest()[:12]
        wav = out / f"{b['id']}.wav"
        words += len(b["text"].split())
        if wav.exists() and timings.get(b["id"], {}).get("hash") == h:
            continue
        if nar:
            raw = out / f"{b['id']}.raw.mp3"
            raw.write_bytes(synth_el(b["tts"], nar, key,
                                     narr[i - 1]["tts"] if i else "",
                                     narr[i + 1]["tts"] if i + 1 < len(narr) else ""))
        else:
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
    for b in narr:  # also applies to cached takes, so older paragraphs lose their tail ticks too
        wav = out / f"{b['id']}.wav"
        if wav.exists() and not timings[b["id"]].get("tail_trimmed"):
            if trim_tail(wav):
                print(f"{b['id']}: tail trimmed {timings[b['id']]['seconds']:.2f} -> {seconds(wav):.2f} s", flush=True)
            timings[b["id"]].update(seconds=round(seconds(wav), 3), tail_trimmed=True)
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
    report = (f"# Narration: {game}, {voice} at {'speed' if nar else 'rate'} {rate}\n\n"
              f"- {len(narr)} paragraphs, {words} words, {total:.0f} s of speech "
              f"({total / 60:.1f} min), {words / (total / 60):.0f} wpm\n")
    (out / "narration.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
