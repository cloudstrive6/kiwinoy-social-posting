"""Design new BOSS KG narrator candidates from a written brief only, on the ElevenLabs account
behind ELEVENLABS_API_KEY (Bryce's Starter workspace).

Why (2026-11-21): Bryce asked for a narrator in the style of a fast, upbeat UK gaming-guide
YouTuber he likes. The voice is designed from a description of the delivery (accent, age, pace,
energy, brightness); no recording of that creator is sent to ElevenLabs and no speaker-identity
score is used, so the result is a new voice in the same style, not a copy of a real person.

How:
  1. Voice Design (eleven_ttv_v3) for each brief in BRIEFS, 3 previews per call;
  2. measure every preview with the same numpy method used on the reference study
     (pitch median and spread, brightness, speaking pace) and rank by distance to TARGET;
  3. save the best KEEP previews as voices "BOSS KG Guide A/B/C", read the same guide excerpt
     with the production model (eleven_v4, the current NARRATOR settings), and read it once
     with today's narrator for comparison;
  4. write mp3s and scores.json to output/analysis/voices-guide/ (the run's artifact).
Stops before any call that would take the spend past CAP credits, and does nothing at all if the
account would be left under RESERVE credits (narration for the next long-form). Never prints the key.

    python tools/el_voice_brief.py
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io"
OUT = ROOT / "output/analysis/voices-guide"
CAP = int(os.environ.get("DESIGN_CREDIT_CAP") or 2000)
RESERVE = int(os.environ.get("DESIGN_RESERVE") or 3000)
KEEP = 3

# Delivery measured on 2026-11-21 from 200 s of the reference guide video (faster-whisper word
# timings, autocorrelation pitch on the loudest 40% of frames, FFT spectral centroid).
TARGET = {"f0_median_hz": 183.9, "f0_spread_st": 10.6, "centroid_hz": 1506.0, "wpm": 192.9}

BRIEFS = {
    "south": ("A British man in his late twenties with a light southern English accent, a gaming "
              "YouTuber talking straight to the viewer in a walkthrough guide. Fast, upbeat and "
              "confident, like a friend showing you a shortcut. Bright, forward voice with lively "
              "intonation and crisp consonants. Close studio microphone, no reverb."),
    "london": ("A UK gaming YouTuber around 28 with an everyday London-area accent, not posh and "
               "not cockney. Rapid conversational pace, punchy emphasis on key words and numbers, "
               "warm and bright tone, excited but always clear, with a grin in the voice. Clean "
               "close-mic studio recording."),
    "midlands": ("An energetic young English man in his mid twenties with a neutral modern English "
                 "accent, narrating a video game tips video at speed. Medium-high pitch, very "
                 "expressive and enthusiastic, quick breaths, no hesitation, clear diction. "
                 "Dry studio microphone sound."),
}

# Our own guide-style lines (written for this test, not taken from any video).
DESIGN_TEXT = ("Right, this is the fastest way to stack cash in GTA 6 right now, and you can start it "
               "the moment you finish the second mission. Grab a pickup truck first, because you are "
               "carrying a lot more than you think. Head north out of the city, take the second exit "
               "past the gas station, and look for the big red warehouse on your left.")
V4_TEXT = DESIGN_TEXT + (" Now, before you go inside, check the side door. Nine times out of ten "
                         "there is a cash bag sitting right there, and most people drive straight past it.")
NOW = {"name": "BOSS KG Narrator A", "voice_id": "Jn6g1Ws0FHFBiECPird2"}
V4 = {"model_id": "eleven_v4", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}


def call(method: str, path: str, key: str, body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    return data if raw else json.loads(data or b"{}")


def used(key: str) -> int:
    return int(call("GET", "/v1/user/subscription", key)["character_count"])


def measure(mp3: Path, words: int) -> dict:
    """Same measures as the reference study: pitch median and p10-p90 spread in semitones on the
    loudest 40% of 40 ms frames, median spectral centroid, words per minute over the whole clip."""
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    sr, fl, hop = 16000, 640, 160
    starts = range(0, max(0, len(x) - fl), hop)
    rms = np.array([np.sqrt(np.mean(x[i:i + fl] ** 2)) for i in starts])
    floor = np.percentile(rms, 60)
    f0, cents = [], []
    win, fq = np.hanning(fl), np.fft.rfftfreq(fl, 1 / sr)
    for k, i in enumerate(starts):
        if rms[k] < floor:
            continue
        fr = x[i:i + fl] * win
        ac = np.correlate(fr, fr, "full")[fl - 1:]
        lo, hi = sr // 400, sr // 70
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[0] > 0 and ac[lag] / ac[0] > 0.45:
            f0.append(sr / lag)
        sp = np.abs(np.fft.rfft(fr))
        cents.append(float((sp * fq).sum() / (sp.sum() + 1e-9)))
    f0 = np.array(f0) if f0 else np.array([1.0])
    st = 12 * np.log2(f0 / np.median(f0))
    return {"f0_median_hz": round(float(np.median(f0)), 1),
            "f0_spread_st": round(float(np.percentile(st, 90) - np.percentile(st, 10)), 1),
            "centroid_hz": round(float(np.median(cents)), 0),
            "wpm": round(words / (len(x) / sr / 60), 1),
            "seconds": round(len(x) / sr, 2)}


def distance(m: dict) -> float:
    """Lower is closer to the reference delivery. Pace counts least: tempo can be set later."""
    return round(abs(12 * np.log2(m["f0_median_hz"] / TARGET["f0_median_hz"])) / 2
                 + abs(m["f0_spread_st"] - TARGET["f0_spread_st"]) / 3
                 + abs(m["centroid_hz"] - TARGET["centroid_hz"]) / 300
                 + abs(m["wpm"] - TARGET["wpm"]) / 50, 3)


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("ELEVENLABS_API_KEY is not set")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    sub = call("GET", "/v1/user/subscription", key)
    start, limit = int(sub["character_count"]), int(sub["character_limit"])
    left = limit - start
    print(f"plan {sub.get('tier')}: {left} of {limit} credits left; cap {CAP}, reserve {RESERVE}")
    if left - CAP < RESERVE:
        print(f"stopped: this run could leave the account under the {RESERVE}-credit reserve")
        return 1
    dw, vw = len(DESIGN_TEXT.split()), len(V4_TEXT.split())
    print(f"design text {len(DESIGN_TEXT)} chars, v4 text {len(V4_TEXT)} chars")

    cands = []
    for tag, brief in BRIEFS.items():
        if used(key) - start + len(DESIGN_TEXT) > CAP:
            print(f"{tag}: skipped, would pass the {CAP}-credit cap")
            continue
        body = {"voice_description": brief, "text": DESIGN_TEXT, "model_id": "eleven_ttv_v3",
                "output_format": "mp3_44100_128"}
        try:
            res = call("POST", "/v1/text-to-voice/design", key, body)
        except urllib.error.HTTPError as e:
            print(f"{tag}: refused ({e.code}): {e.read().decode()[:600]}")
            continue
        for i, pv in enumerate(res.get("previews", []), 1):
            p = OUT / f"preview-{tag}-{i}.mp3"
            p.write_bytes(base64.b64decode(pv["audio_base_64"]))
            m = measure(p, dw)
            cands.append({"tag": f"{tag}-{i}", "brief": tag, "generated_voice_id": pv["generated_voice_id"],
                          "file": p.name, "preview": m, "distance": distance(m)})
            print(f"{tag}-{i}: {m} distance {distance(m)}")
    if not cands:
        print("no previews made")
        return 1

    cands.sort(key=lambda c: c["distance"])
    for letter, c in zip("ABC", cands[:KEEP]):
        if used(key) - start + len(V4_TEXT) > CAP:
            print(f"{c['tag']}: not rendered, would pass the {CAP}-credit cap")
            break
        name = f"BOSS KG Guide {letter}"
        try:
            v = call("POST", "/v1/text-to-voice", key, {"voice_name": name, "voice_description": BRIEFS[c["brief"]],
                                                         "generated_voice_id": c["generated_voice_id"]})
        except urllib.error.HTTPError as e:
            print(f"{name}: save refused ({e.code}): {e.read().decode()[:400]}")
            continue
        c.update(name=name, voice_id=v["voice_id"])
        audio = call("POST", f"/v1/text-to-speech/{v['voice_id']}?output_format=mp3_44100_128", key,
                     {"text": V4_TEXT, **V4}, raw=True)
        p = OUT / f"guide-{letter}-v4.mp3"
        p.write_bytes(audio)
        c.update(v4_file=p.name, v4=measure(p, vw))
        c["v4_distance"] = distance(c["v4"])
        print(f"{name} ({c['tag']}) = {v['voice_id']}: v4 {c['v4']} distance {c['v4_distance']}")

    now = {}
    if used(key) - start + len(V4_TEXT) <= CAP:
        audio = call("POST", f"/v1/text-to-speech/{NOW['voice_id']}?output_format=mp3_44100_128", key,
                     {"text": V4_TEXT, **V4}, raw=True)
        p = OUT / "current-narrator-v4.mp3"
        p.write_bytes(audio)
        now = {"name": NOW["name"], "file": p.name, "v4": measure(p, vw)}
        now["v4_distance"] = distance(now["v4"])
        print(f"current narrator: v4 {now['v4']} distance {now['v4_distance']}")

    spent = used(key) - start
    (OUT / "scores.json").write_text(json.dumps({"date": "2026-11-21", "target": TARGET, "credits_spent": spent,
                                                 "credits_left": left - spent, "design_text": DESIGN_TEXT,
                                                 "v4_text": V4_TEXT, "briefs": BRIEFS, "candidates": cands,
                                                 "current": now}, indent=2), encoding="utf-8")
    print(f"credits spent this run: {spent}; left about {left - spent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
