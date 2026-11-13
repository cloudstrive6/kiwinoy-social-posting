"""Design BOSS KG narrator voices as close as possible to "BOSS KG Essayist take 3", on the
ElevenLabs account behind ELEVENLABS_API_KEY (Bryce's Starter workspace).

Why (2026-11-13): take 3 lives in another workspace and cannot be copied or cloned (it matches a
library voice). Bryce: "Design something as similar as much as possible to Take 3".

How:
  1. pull the two take-3 recordings from private B2 (voices/boss-kg-essayist-3/);
  2. Voice Design (eleven_ttv_v3) with the take-3 brief, steered by take-3 audio as reference
     where the API accepts it, plus brief-only rounds with different seeds; 3 previews per call;
  3. score every preview against take 3 by speaker-embedding cosine (resemblyzer);
  4. save the best KEEP previews as voices "BOSS KG Narrator A/B/C", render the same excerpt with
     the production model (eleven_multilingual_v2) and score those against take 3 again;
  5. write mp3s and scores.json to output/analysis/voices/ (kept as the run's artifact).
Stops before any call that would take the spend past CAP credits. Never prints the key.

    python tools/el_voice_design.py
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
sys.path.insert(0, str(ROOT))

API = "https://api.elevenlabs.io"
BRIEF = ("A male narrator in his mid twenties with a neutral American accent. Friendly, clear and "
         "energetic but controlled, with crisp diction, like a passionate gaming YouTuber narrating "
         "a story analysis. Clean studio microphone recording with no reverb.")
TAKE3 = {"wolverine": "voices/boss-kg-essayist-3/sample-wolverine.mp3",
         "spiderman2": "voices/boss-kg-essayist-3/sample-spiderman2.mp3"}
CAP = int(os.environ.get("DESIGN_CREDIT_CAP") or 4000)
KEEP = 3
OUT = ROOT / "output/analysis/voices"
FULL = (ROOT / "data/analysis/wolverine/audition.txt").read_text(encoding="utf-8").strip()


def excerpt(text: str, limit: int) -> str:
    """Whole sentences up to about limit characters."""
    out = ""
    for s in text.replace("\n", " ").split(". "):
        nxt = (out + ". " if out else "") + s.strip().rstrip(".")
        if len(nxt) + 1 > limit and len(out) >= 100:
            break
        out = nxt
    return out + "."


DESIGN_TEXT = excerpt(FULL, 300)
V2_TEXT = excerpt(FULL, 420)


def call(method: str, path: str, key: str, body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    return data if raw else json.loads(data or b"{}")


def used(key: str) -> int:
    return int(call("GET", "/v1/user/subscription", key)["character_count"])


def to_wav16(mp3: Path) -> np.ndarray:
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("ELEVENLABS_API_KEY is not set")
        return 1
    from core import b2_store
    from resemblyzer import VoiceEncoder, preprocess_wav

    OUT.mkdir(parents=True, exist_ok=True)
    sub = call("GET", "/v1/user/subscription", key)
    start = int(sub["character_count"])
    print(f"plan {sub.get('tier')}: {start} of {sub['character_limit']} credits used; cap for this run {CAP}")
    print(f"design text {len(DESIGN_TEXT)} chars, v2 text {len(V2_TEXT)} chars")

    enc = VoiceEncoder()
    refs = {}
    for name, k in TAKE3.items():
        p = OUT / f"take3-{name}.mp3"
        with urllib.request.urlopen(b2_store.presigned_url(k, valid_seconds=600), timeout=120) as r:
            p.write_bytes(r.read())
        refs[name] = enc.embed_utterance(preprocess_wav(to_wav16(p), source_sr=16000))
    target = refs["wolverine"] / np.linalg.norm(refs["wolverine"])
    print(f"take-3 self check (wolverine vs spiderman2 sample): {float(np.dot(target, refs['spiderman2'])):.3f}")

    def score(path: Path) -> float:
        e = enc.embed_utterance(preprocess_wav(to_wav16(path), source_sr=16000))
        return round(float(np.dot(target, e / np.linalg.norm(e))), 4)

    ref_b64 = base64.b64encode((OUT / "take3-spiderman2.mp3").read_bytes()).decode()
    rounds = [
        ("ref-p0.2", {"reference_audio_base64": ref_b64, "prompt_strength": 0.2}),
        ("ref-p0.5", {"reference_audio_base64": ref_b64, "prompt_strength": 0.5}),
        ("brief-s11", {"seed": 11}),
        ("brief-s29", {"seed": 29}),
    ]
    cands = []
    for tag, extra in rounds:
        if used(key) - start + len(DESIGN_TEXT) > CAP:
            print(f"{tag}: skipped, would pass the {CAP}-credit cap")
            continue
        body = {"voice_description": BRIEF, "text": DESIGN_TEXT, "model_id": "eleven_ttv_v3",
                "output_format": "mp3_44100_128", **extra}
        try:
            res = call("POST", "/v1/text-to-voice/design", key, body)
        except urllib.error.HTTPError as e:
            print(f"{tag}: refused ({e.code}): {e.read().decode()[:600]}")
            continue
        for i, pv in enumerate(res.get("previews", []), 1):
            p = OUT / f"design-{tag}-{i}.mp3"
            p.write_bytes(base64.b64decode(pv["audio_base_64"]))
            s = score(p)
            cands.append({"tag": f"{tag}-{i}", "generated_voice_id": pv["generated_voice_id"],
                          "file": p.name, "preview_similarity": s})
            print(f"{tag}-{i}: similarity to take 3 {s}")
    if not cands:
        print("no previews made")
        return 1

    cands.sort(key=lambda c: -c["preview_similarity"])
    for letter, c in zip("ABC", cands[:KEEP]):
        if used(key) - start + len(V2_TEXT) > CAP:
            print(f"{c['tag']}: not rendered, would pass the {CAP}-credit cap")
            break
        name = f"BOSS KG Narrator {letter}"
        try:
            v = call("POST", "/v1/text-to-voice", key, {"voice_name": name, "voice_description": BRIEF,
                                                         "generated_voice_id": c["generated_voice_id"]})
        except urllib.error.HTTPError as e:
            print(f"{name}: save refused ({e.code}): {e.read().decode()[:400]}")
            continue
        c.update(name=name, voice_id=v["voice_id"])
        audio = call("POST", f"/v1/text-to-speech/{v['voice_id']}?output_format=mp3_44100_128", key,
                     {"text": V2_TEXT, "model_id": "eleven_multilingual_v2",
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0,
                                         "use_speaker_boost": True, "speed": 0.9}}, raw=True)
        p = OUT / f"narrator-{letter}-v2.mp3"
        p.write_bytes(audio)
        c.update(v2_file=p.name, v2_similarity=score(p))
        print(f"{name} ({c['tag']}) = {v['voice_id']}: v2 similarity to take 3 {c['v2_similarity']}")

    spent = used(key) - start
    (OUT / "scores.json").write_text(json.dumps({"credits_spent": spent, "design_text": DESIGN_TEXT,
                                                 "v2_text": V2_TEXT, "candidates": cands}, indent=2),
                                     encoding="utf-8")
    print(f"credits spent this run: {spent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
