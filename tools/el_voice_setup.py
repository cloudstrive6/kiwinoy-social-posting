"""Check the BOSS KG narrator voice on the ElevenLabs account behind ELEVENLABS_API_KEY, and delete
voices Bryce has ruled out.

History (2026-11-13): the first pick, "BOSS KG Essayist take 3", sits in another workspace (Lyntech)
and cannot be moved or cloned, so tools/el_voice_design.py made look-alikes on Bryce's Starter
workspace and Bryce picked "BOSS KG Narrator A". This step:
  1. prints the plan, credits used and left, and voice slots;
  2. deletes each voice named in EL_DELETE (comma list, exact names; only voices on this account);
  3. checks that the narrator voice NAME exists and prints its id (exit 1 if it does not).
Never prints the key.

    EL_DELETE="BOSS KG Narrator B,BOSS KG Narrator C" python tools/el_voice_setup.py
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

NAME = "BOSS KG Narrator A"
API = "https://api.elevenlabs.io"


def call(method: str, path: str, key: str) -> dict:
    req = urllib.request.Request(API + path, method=method, headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"{}")


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("ELEVENLABS_API_KEY is not set")
        return 1
    sub = call("GET", "/v1/user/subscription", key)
    used, limit = int(sub["character_count"]), int(sub["character_limit"])
    print(f"plan {sub.get('tier')}: {used} of {limit} credits used ({limit - used} left), "
          f"voice slots {sub.get('voice_slots_used')} of {sub.get('voice_limit')}")
    mine = call("GET", "/v2/voices?page_size=100&voice_type=personal", key).get("voices", [])
    by_name = {v.get("name"): v["voice_id"] for v in mine}
    print("own voices:", sorted(by_name) or "none")
    for name in [n.strip() for n in os.environ.get("EL_DELETE", "").split(",") if n.strip()]:
        if name == NAME:
            print(f"not deleting {name}: it is the narrator")
            continue
        if name not in by_name:
            print(f"{name}: not on this account, nothing to delete")
            continue
        try:
            call("DELETE", f"/v1/voices/{by_name[name]}", key)
            print(f"deleted {name} ({by_name[name]})")
        except urllib.error.HTTPError as e:
            print(f"could not delete {name} ({e.code}): {e.read().decode()[:300]}")
    if NAME in by_name:
        print(f"narrator voice on this account: {NAME} = {by_name[NAME]}")
        return 0
    print(f"narrator voice {NAME} is not on this account")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
