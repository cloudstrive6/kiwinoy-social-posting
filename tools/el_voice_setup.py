"""Make sure the BOSS KG narrator voice exists on the ElevenLabs account behind ELEVENLABS_API_KEY.

Why (2026-11-13): the voice "BOSS KG Essayist take 3" was designed on a different ElevenLabs
account than the one in the GitHub secret (Bryce's Starter plan). This step, run in Actions,
recreates it on the secret's account without the key ever leaving GitHub:
  1. if a voice with that name already exists, report it and stop;
  2. else save it from the Voice Design id it was made with (works while the design is kept);
  3. else make an instant clone from the two take-3 samples kept on private B2
     (voices/boss-kg-essayist-3/), which needs a plan with instant cloning (Starter has it).
Prints the plan, the credits left and the voice id. Never prints the key.

    python tools/el_voice_setup.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NAME = "BOSS KG Essayist take 3"
DESIGN_ID = "ms9Irzl0730aqqKYFuVm"
BRIEF = ("A male narrator in his mid twenties with a neutral American accent. Friendly, clear and "
         "energetic but controlled, with crisp diction, like a passionate gaming YouTuber narrating "
         "a story analysis. Clean studio microphone recording with no reverb.")
SAMPLES = ["voices/boss-kg-essayist-3/sample-wolverine.mp3",
           "voices/boss-kg-essayist-3/sample-spiderman2.mp3"]
API = "https://api.elevenlabs.io"


def call(method: str, path: str, key: str, body: dict | None = None,
         data: bytes | None = None, ctype: str = "application/json") -> dict:
    payload = json.dumps(body).encode() if body is not None else data
    req = urllib.request.Request(API + path, method=method, data=payload,
                                 headers={"xi-api-key": key, "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read() or b"{}")


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("ELEVENLABS_API_KEY is not set")
        return 1
    sub = call("GET", "/v1/user/subscription", key)
    print(f"plan {sub.get('tier')}: {sub['character_count']} of {sub['character_limit']} credits used, "
          f"voice slots {sub.get('voice_slots_used')} of {sub.get('voice_limit')}, "
          f"instant cloning {'yes' if sub.get('can_use_instant_voice_cloning') else 'no'}")
    mine = call("GET", "/v2/voices?page_size=100&voice_type=non-default", key).get("voices", [])
    print("voices on this account:", [(v.get("name"), v.get("category")) for v in mine] or "none")
    voices = call("GET", "/v2/voices?page_size=100&search=" + urllib.request.quote(NAME), key)
    for v in voices.get("voices", []) + mine:
        if v.get("name") == NAME:
            print(f"voice already on this account: {NAME} = {v['voice_id']}")
            return 0
    try:
        v = call("POST", "/v1/text-to-voice", key, {"voice_name": NAME, "voice_description": BRIEF,
                                                      "generated_voice_id": DESIGN_ID})
        print(f"saved from the design: {NAME} = {v['voice_id']}")
        return 0
    except urllib.error.HTTPError as e:
        print(f"design not available on this account ({e.code}): {e.read().decode()[:200]}")
    from core import b2_store
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{NAME}\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\n{BRIEF}\r\n'.encode()]
    for i, k in enumerate(SAMPLES):
        url = b2_store.presigned_url(k, valid_seconds=600)
        with urllib.request.urlopen(url, timeout=120) as r:
            audio = r.read()
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                      f'filename="sample{i}.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n').encode()
                     + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    try:
        v = call("POST", "/v1/voices/add", key, data=b"".join(parts),
                 ctype=f"multipart/form-data; boundary={boundary}")
    except urllib.error.HTTPError as e:
        print(f"instant clone refused ({e.code}): {e.read().decode()[:1500]}")
        return 1
    print(f"cloned from the take-3 samples: {NAME} = {v['voice_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
