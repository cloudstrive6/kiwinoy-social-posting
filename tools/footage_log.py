"""Footage log: what really happens in every KG clip, written once, in the cloud (2026-11-23).

Bryce, 2026-11-23, after the beginners guide narrated a robbery Lucia had stopped: "You need to
watch/analyze more the scenes and really know each of the videos/footage/scenes/gameplay well", and asked
for it to hold "during the automation/when the PC is off".

For each clip in B2 cutscenes/<game>/ and footage/<game>/ without a log, this builds the frames every 2 s and
the timed dialogue (tools/footage_check.py, CPU), then Claude (subscription token, Read tool for the sheets)
writes a scene-by-scene log: who does what, who starts any crime, what NPCs say and offer, on-screen notices
word for word, and wallet changes. Saved to B2 footage-log/<clip key>.json and .md, where writers and the
claims check (tools/claims_check.py) read it. Never posts anything. Runs from .github/workflows/footage-log.yml.

    python tools/footage_log.py gta6 [--max 6] [--model opus]
    python tools/footage_log.py --show "cutscenes/gta6/GTA 6 (2026-11-21 23-37-28) p05.mp4"
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

PROMPT = """You are logging gameplay footage for a gaming channel so its writers never misdescribe it. The
player recorded this clip; the channel narrates it in the first person ("I did ..."). A wrong log line becomes
a false claim in a video (2026-11-23: a store robbery the player STOPPED was written up as one the player
COMMITTED, because nobody listened to the clerk).

Open every contact sheet with the Read tool (each frame is labelled with its time, mm:ss.s from the clip
start; hud sheets show the top-right corner at full resolution, for the wallet and wanted stars), then read the timed dialogue below. Write the log as JSON only, no other text:

{{"summary": "two or three sentences: where, who is played, what happens",
  "events": [{{"start": seconds, "end": seconds,
              "what": "what happens, plainly: who does what to whom, and why if the scene says so",
              "player_does": "what the player character does",
              "others_do": "what other characters do or say, including offers, threats, rewards",
              "on_screen_text": "notices, tooltips, objectives, word for word if legible, else empty",
              "money": "wallet or bank changes you can read, e.g. 149 to 247, else empty",
              "quote": "the key spoken line, word for word from the dialogue, else empty",
              "certainty": "sure | likely | unclear"}}],
  "watch_outs": ["anything a writer could easily get wrong about this clip"]}}

Rules: an event every time the situation changes (about every 10 to 40 s). Who starts a crime, who is the
victim, and who gives money to whom must come from the frames AND the dialogue; if they disagree or you cannot
tell, say so and mark it unclear. Never guess numbers: write only what is legible. Times are seconds from the
clip start (a frame labelled 01m04.0s is 64).

Clip: {key} ({seconds:.0f} s)

Verified footage facts for this game (who is who, whose home, whose car); use them to name people and places:
{facts}

Timed dialogue (faster-whisper; names and numbers may be misspelled):
{dialogue}

Contact sheets:
{sheets}
"""


def log_key(key: str) -> str:
    return f"footage-log/{key}.json"


def seconds_of(url: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", url], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in the reply")
    return json.loads(m.group(0))


def to_md(key: str, log: dict) -> str:
    def ts(s):
        s = float(s or 0)
        return f"{int(s // 60)}:{s % 60:04.1f}"
    lines = [f"# Footage log: {key}", "", log.get("summary", ""), ""]
    for e in log.get("events", []):
        lines.append(f"- **{ts(e.get('start'))} to {ts(e.get('end'))}** ({e.get('certainty', '')}): {e.get('what', '')}")
        for k in ("player_does", "others_do", "on_screen_text", "money", "quote"):
            if e.get(k):
                lines.append(f"  - {k.replace('_', ' ')}: {e[k]}")
    if log.get("watch_outs"):
        lines += ["", "Watch outs:"] + [f"- {w}" for w in log["watch_outs"]]
    return "\n".join(lines) + "\n"


def build(key: str, model: str) -> dict:
    from core import b2_store, claude_code
    from footage_check import run_check
    url = b2_store.presigned_url(key, valid_seconds=3600)
    secs = seconds_of(url)
    if secs <= 0:
        raise RuntimeError(f"cannot read the length of {key}")
    name = "log/" + re.sub(r"[^A-Za-z0-9._-]+", "_", key)
    out = run_check(key, 0.0, secs, name)
    dialogue = (out / "dialogue.txt").read_text(encoding="utf-8").split("\n", 2)[-1].strip()
    sheets = sorted(out.glob("sheet*.jpg")) + sorted(out.glob("hud*.jpg"))
    listing = "\n".join(str(p.resolve()) for p in sheets)
    from claims_check import footage_facts
    prompt = PROMPT.format(key=key, seconds=secs, dialogue=dialogue or "(no speech heard)", sheets=listing,
                           facts=footage_facts([key]))
    reply = claude_code.run(prompt, model=model, allowed_tools="Read", timeout=900)
    log = parse_json(reply)
    log.update(key=key, seconds=round(secs, 2), dialogue=dialogue, model=model,
               made=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), version=1)
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("games", nargs="*", help="game keys (cutscenes/<game> and footage/<game> on B2)")
    ap.add_argument("--max", type=int, default=6, help="clips per run (each takes a few minutes)")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--show", default="", help="print the log of one clip key")
    ap.add_argument("--redo", action="store_true", help="rebuild logs that exist")
    ap.add_argument("--keys", default="", help="log exactly these B2 keys, separated by |")
    a = ap.parse_args()
    from core import b2_store
    if a.show:
        data = b2_store.get_bytes(log_key(a.show))
        print(to_md(a.show, json.loads(data)) if data else "no log yet")
        return 0
    from core import claude_code
    claude_code._anthropic_key = lambda: ""  # subscription only: never fall back to the paid API
    if not claude_code.available_token():
        raise SystemExit("CLAUDE_CODE_OAUTH_TOKEN is not set (the log runs on the subscription, never the paid API)")
    have = {f.get("fileName", "") for f in b2_store._list_names("footage-log/")}
    failed = json.loads(b2_store.get_bytes("footage-log/_failed.json") or b"{}")
    todo = [k.strip() for k in a.keys.split("|") if k.strip()]
    for g in ([] if todo else a.games):
        for c in b2_store.list_cutscenes(g) + b2_store.list_footage(g):
            if (a.redo or log_key(c["key"]) not in have) and failed.get(c["key"], 0) < 2:
                todo.append(c["key"])
    skipped = [k for k, n in failed.items() if n >= 2]
    if skipped:
        print(f"skipping {len(skipped)} clip(s) that failed twice (footage-log/_failed.json)", flush=True)
    print(f"{len(todo)} clips without a log; doing up to {a.max}", flush=True)
    done = 0
    for key in todo[:a.max]:
        t0 = time.time()
        try:
            log = build(key, a.model)
        except Exception as e:  # one bad clip never blocks the rest; after 2 fails it stops using the slot
            print(f"FAILED {key}: {e!r}"[:400], flush=True)
            failed[key] = failed.get(key, 0) + 1
            b2_store.put_bytes("footage-log/_failed.json", json.dumps(failed, indent=1).encode())
            continue
        ok = b2_store.put_bytes(log_key(key), json.dumps(log, indent=1).encode(), "application/json")
        b2_store.put_bytes(log_key(key)[:-5] + ".md", to_md(key, log).encode(), "text/markdown")
        print(f"{'logged' if ok else 'UPLOAD FAILED'} {key}: {len(log.get('events', []))} events, "
              f"{time.time() - t0:.0f} s", flush=True)
        done += ok
    print(f"done: {done} logged, {max(0, len(todo) - a.max)} left for the next run", flush=True)
    return 1 if todo and not done else 0  # a run with work and no logs shows red, never a silent green


if __name__ == "__main__":
    raise SystemExit(main())
