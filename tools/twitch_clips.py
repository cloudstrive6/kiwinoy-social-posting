"""Twitch clips from every past broadcast, no markers needed (Bryce, 2026-11-21: "Do these as automated").

After each stream, for every saved broadcast (Twitch "archive" VOD) not clipped yet:
  1. download a small 360p copy to this machine's temp folder with yt-dlp (Bryce chose this on
     2026-11-21; Twitch's official API has no download). The copy is only used to find moments and
     is deleted with the runner; it is never uploaded anywhere;
  2. find candidate moments with plain code: loudness peaks, how much is said, excited words and
     how often the picture cuts, in 40 s windows (muted copyright stretches and the first/last
     minutes are skipped);
  3. Claude (subscription, core.claude_code.vision) looks at a frame sheet and the words of each
     candidate and picks the 5 to 8 best, with a title, rejecting menus, loading screens, dead air,
     sexual content and slurs;
  4. each pick becomes a real Twitch clip through the official API (POST helix/videos/clips, scope
     channel:manage:clips), cut by Twitch from its own full-quality copy. Clips made by the
     broadcaster go into the channel's Stream Recap automatically (dashboard setting, on);
  5. data/twitch/clips_state.json records what was clipped; Telegram gets the links.

    python tools/twitch_clips.py                 # every new broadcast (at most MAX_PER_RUN)
    python tools/twitch_clips.py --vod 123 --dry # one broadcast, print picks, create nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests  # noqa: E402

STATE = ROOT / "data" / "twitch" / "clips_state.json"
LOGIN = "kiwinoy"
MAX_PER_RUN = 2           # broadcasts per run (a 5 h one takes about an hour to analyse)
PICKS = (5, 8)            # clips per broadcast
WIN = 40                  # candidate window, seconds
CANDIDATES = 18           # windows shown to Claude
GAP = 150                 # seconds between candidates
LEAD_PAD, TAIL_PAD = 3, 4  # Twitch places VOD clips 2 to 9 s off; widen each clip a little
EXCITED = re.compile(r"\b(oh my god|omg|no way|let'?s go|what the|wtf|holy|bro|dude|yes+|nooo*|crazy|insane|"
                     r"run|go go|haha+|hahaha|wow|damn|sheesh|clutch|gg)\b", re.I)


def log(msg: str) -> None:
    print(f"[twitch-clips] {msg}", flush=True)


# ------------------------------------------------------------------------------- Twitch API

def token() -> tuple[str, str]:
    cid, sec, rt = (os.environ.get(k, "").strip() for k in
                    ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "TWITCH_REFRESH_TOKEN"))
    if not (cid and sec and rt):
        raise SystemExit("no TWITCH_* secrets (run tools/twitch_auth.py)")
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30,
                      data={"client_id": cid, "client_secret": sec, "grant_type": "refresh_token", "refresh_token": rt})
    if r.status_code != 200:
        raise SystemExit(f"token refresh HTTP {r.status_code} (rerun tools/twitch_auth.py)")
    tok = r.json()["access_token"]
    scopes = requests.get("https://id.twitch.tv/oauth2/validate", timeout=30,
                          headers={"Authorization": f"OAuth {tok}"}).json().get("scopes", [])
    if "channel:manage:clips" not in scopes:
        raise SystemExit("the Twitch login lacks channel:manage:clips: rerun tools/twitch_auth.py (it now asks for it)")
    return cid, tok


def api(method: str, path: str, cid: str, tok: str, **params) -> dict:
    r = requests.request(method, f"https://api.twitch.tv/helix/{path}", params=params, timeout=60,
                         headers={"Authorization": f"Bearer {tok}", "Client-Id": cid})
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


def secs(d: str) -> int:
    """Twitch duration '3h21m5s' -> seconds."""
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in re.findall(r"(\d+)([hms])", d))


# ------------------------------------------------------------------------------- analysis

def download(vod_id: str, work: Path) -> Path:
    out = work / f"vod_{vod_id}.mp4"
    cmd = [sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "-N", "8",
           "-f", "360p30/360p/480p30/480p/worst[height>=240]/worst", "-o", str(out),
           f"https://www.twitch.tv/videos/{vod_id}"]
    subprocess.run(cmd, check=True, timeout=3 * 3600)
    return out


def audio_features(video: Path, work: Path) -> tuple[list[float], Path]:
    """Per-second loudness (dB) and a 16 kHz mono wav for whisper."""
    import numpy as np
    wav = work / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                   check=True)
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // 16000
    rms = np.sqrt((x[: n * 16000].reshape(n, 16000) ** 2).mean(axis=1) + 1e-9)
    return list(20 * np.log10(rms)), wav


def transcript(wav: Path) -> list[dict]:
    import numpy as np
    from faster_whisper import WhisperModel
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(x, vad_filter=True, beam_size=1, condition_on_previous_text=False)
    return [{"s": s.start, "e": s.end, "t": s.text.strip()} for s in segs]


def cut_times(video: Path) -> list[float]:
    log_ = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
                           "fps=4,scale=160:-2,select='gt(scene,0.3)',showinfo", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", log_)]


def candidates(dur: int, loud: list[float], segs: list[dict], cuts: list[float], muted: list[tuple[int, int]]) -> list[dict]:
    import numpy as np
    L = np.array(loud)
    wins = []
    for st in range(120, max(121, dur - 120 - WIN), 10):
        en = st + WIN
        if any(st < m1 and en > m0 for m0, m1 in muted):
            continue
        words = [g for g in segs if g["s"] < en and g["e"] > st]
        text = " ".join(g["t"] for g in words)
        wins.append({"start": st, "end": en, "text": text,
                     "loud": float(np.percentile(L[st:en], 90)) if en <= len(L) else -90.0,
                     "words": len(text.split()), "excited": len(EXCITED.findall(text)),
                     "cuts": sum(1 for c in cuts if st <= c < en)})
    if not wins:
        return []

    def z(key):
        v = np.array([w[key] for w in wins], dtype=float)
        return (v - v.mean()) / (v.std() + 1e-6)
    score = 1.2 * z("loud") + 0.8 * z("words") + 1.0 * z("excited") + 0.6 * z("cuts")
    for w, sc in zip(wins, score):
        w["score"] = float(sc)
    picked = []
    for w in sorted(wins, key=lambda w: -w["score"]):
        if all(abs(w["start"] - p["start"]) >= GAP for p in picked):
            picked.append(w)
        if len(picked) >= CANDIDATES:
            break
    return sorted(picked, key=lambda w: w["start"])


def sheet(video: Path, c: dict, path: Path) -> None:
    """Six frames across the window in a 3x2 grid with the time on each."""
    step = WIN / 6
    inputs = []
    for k in range(6):
        inputs += ["-ss", f"{c['start'] + step * (k + 0.5):.1f}", "-i", str(video)]
    tiles = "".join(f"[{k}:v]scale=426:-2,trim=end_frame=1,setpts=PTS-STARTPTS[t{k}];" for k in range(6))
    layout = "0_0|w0_0|w0+w1_0|0_h0|w0_h0|w0+w1_h0"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
                    tiles + "".join(f"[t{k}]" for k in range(6)) + f"xstack=inputs=6:layout={layout}[v]",
                    "-map", "[v]", "-frames:v", "1", str(path)], check=True)


def choose(video: Path, game: str, title: str, cands: list[dict], work: Path) -> list[dict]:
    from core import claude_code
    imgs = []
    lines = []
    for i, c in enumerate(cands):
        p = work / f"cand_{i:02d}.jpg"
        sheet(video, c, p)
        imgs.append(p)
        lines.append(f"Candidate {i + 1} (image {i + 1}): {c['start'] // 60}:{c['start'] % 60:02d} to "
                     f"{c['end'] // 60}:{c['end'] % 60:02d} into the stream. Streamer's words: "
                     f"\"{c['text'][:400] or '(no speech)'}\"")
    prompt = f"""You pick Twitch clips for the gaming streamer BOSS KG (twitch.tv/kiwinoy).
Stream: "{title}", game: {game}. Each image is a 3x2 sheet of six frames from one 40-second
window of the stream, in order; its text is what the streamer said then (automatic transcript, may
have errors; the streamer also speaks Tagalog).

Pick the {PICKS[0]} to {PICKS[1]} candidates a new viewer would most want to watch: action, chases,
crashes, funny or surprising moments, big reactions, story reveals. Reject: menus, map screens,
loading or black screens, the streamer idle or talking with nothing happening, anything sexual or
nude, any racial or homophobic slur. If fewer than {PICKS[0]} are good, pick fewer.

For each pick give the best part of the window: "from" and "to" in seconds inside the window
(0 to 40, at least 12 s long), and a clip title of at most 70 characters, specific to what happens
(no clickbait, no emojis, no hashtags, no em-dashes, never "KG" or the streamer's name).

{chr(10).join(lines)}

Answer with JSON only: {{"picks": [{{"candidate": 3, "from": 4, "to": 32, "title": "..."}}]}}"""
    raw = claude_code.vision(prompt, imgs, timeout=600)
    m = re.search(r"\{.*\}", raw, re.S)
    picks = json.loads(m.group(0)).get("picks", []) if m else []
    out = []
    for p in picks[: PICKS[1]]:
        i = int(p.get("candidate", 0)) - 1
        if not 0 <= i < len(cands):
            continue
        a = max(0.0, min(float(p.get("from", 0)), WIN - 12))
        b = max(a + 12, min(float(p.get("to", WIN)), WIN))
        title = re.sub(r"[—–#]", "", str(p.get("title", "")).strip())[:70] or f"{game} moment"
        out.append({"start": cands[i]["start"] + a, "end": cands[i]["start"] + b, "title": title})
    return out


# ------------------------------------------------------------------------------- main

def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vod", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    cid, tok = token()
    uid = api("GET", "users", cid, tok, login=LOGIN)["data"][0]["id"]
    live = api("GET", "streams", cid, tok, user_id=uid).get("data", [])
    live_stream = live[0]["id"] if live else None
    if a.vod:
        vods = api("GET", "videos", cid, tok, id=a.vod).get("data", [])
    else:
        vods = api("GET", "videos", cid, tok, user_id=uid, type="archive", first=20).get("data", [])
    state = load_state()
    now = dt.datetime.now(dt.timezone.utc)
    todo = []
    for v in sorted(vods, key=lambda v: v["created_at"]):  # oldest first: they expire first
        age = now - dt.datetime.fromisoformat(v["created_at"].replace("Z", "+00:00"))
        if not a.vod and (v["id"] in state or v.get("stream_id") == live_stream or secs(v["duration"]) < 300
                          or age > dt.timedelta(days=6, hours=20)):
            continue
        todo.append(v)
    log(f"{len(vods)} broadcasts listed, {len(todo)} to clip" + (f" (live now: {live_stream})" if live_stream else ""))
    made_all = []
    for v in todo[:MAX_PER_RUN]:
        dur = secs(v["duration"])
        game = v.get("title") or "gameplay"
        muted = [(m["offset"], m["offset"] + m["duration"]) for m in (v.get("muted_segments") or [])]
        log(f"broadcast {v['id']} \"{v['title']}\" {v['duration']} from {v['created_at']}, {len(muted)} muted stretches")
        work = Path(tempfile.mkdtemp(prefix="twclip_"))
        try:
            video = download(v["id"], work)
            loud, wav = audio_features(video, work)
            segs = transcript(wav)
            cuts = cut_times(video)
            cands = candidates(dur, loud, segs, cuts, muted)
            log(f"{len(segs)} speech segments, {len(cuts)} picture cuts, {len(cands)} candidates")
            picks = choose(video, game, v["title"], cands, work) if cands else []
            made = []
            for p in picks:
                start, end = max(0, p["start"] - LEAD_PAD), min(dur, p["end"] + TAIL_PAD)
                length = round(min(60.0, max(5.0, end - start)), 1)
                if a.dry:
                    log(f"DRY {int(start) // 60}:{int(start) % 60:02d} +{length}s  {p['title']}")
                    continue
                try:
                    r = api("POST", "videos/clips", cid, tok, editor_id=uid, broadcaster_id=uid, vod_id=v["id"],
                            vod_offset=int(round(start + length)), duration=length, title=p["title"])
                    cl = r["data"][0]
                    made.append({"id": cl["id"], "title": p["title"], "offset": int(start), "seconds": length,
                                 "url": f"https://clips.twitch.tv/{cl['id']}"})
                    log(f"clip {cl['id']} at {int(start) // 60}:{int(start) % 60:02d} +{length}s  {p['title']}")
                except Exception as e:
                    log(f"clip failed at {int(start)} s: {e}")
            if not a.dry:
                state[v["id"]] = {"title": v["title"], "created_at": v["created_at"], "done": now.isoformat(),
                                  "clips": made}
                STATE.parent.mkdir(parents=True, exist_ok=True)
                STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                made_all.append((v, made))
        except Exception as e:
            log(f"broadcast {v['id']} failed: {type(e).__name__}: {str(e)[:300]}")
        finally:
            shutil.rmtree(work, ignore_errors=True)   # the downloaded copy never leaves this machine
    if made_all:
        from core import notify
        lines = ["Twitch clips made (they also go into the Stream Recap):"]
        for v, made in made_all:
            lines.append(f"\n{v['title']} ({v['created_at'][:10]}): {len(made)} clips")
            lines += [f"- {c['title']}: {c['url']}" for c in made]
        notify.telegram("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
