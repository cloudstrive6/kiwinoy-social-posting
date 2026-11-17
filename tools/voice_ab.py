"""Blind narrator A/B for KG (Bryce approved 2026-11-17).

Voices one excerpt in up to four ways, a 2x2 of model (eleven_multilingual_v2, eleven_v4) by script (original,
rewritten for the ear, plus sparse audio tags on v4), from data/analysis/voice-ab/ab.json. Every take
gets the same processing as a real narration (silence trim, -16 LUFS, master preset C), and each v4
take is pace-matched to its v2 twin with atempo so speed does not decide the listen. Parselmouth
(Praat) measures pitch range and spread, loudness movement and pauses on each take. Output in
output/analysis/voice-ab/: blind/take-N.mp3 for the listen, key.json (which take is which), metrics.json and
report.md. Uses ELEVENLABS_API_KEY from the Actions secret (the Starter "KG Actions" key); stops before
recording if the month's credits would fall under the reserve. Never uploads anywhere.

    python tools/voice_ab.py
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from analysis_narrate import MASTERS, seconds  # noqa: E402

API = "https://api.elevenlabs.io"
TAG = re.compile(r"\[[^\]]*\]")
OUT = ROOT / "output" / "analysis" / "voice-ab"


def plain(t: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub("", t)).strip()


def words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", plain(t).lower())


def get(path: str, key: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(API + path, headers={"xi-api-key": key}), timeout=60) as r:
        return json.loads(r.read())


def credits_left(key: str) -> tuple[int, str]:
    s = get("/v1/user/subscription", key)
    return int(s["character_limit"]) - int(s["character_count"]), str(s.get("tier"))


def tts(text: str, voice_id: str, model: str, settings: dict, key: str, prev: str, nxt: str) -> tuple[bytes, bool]:
    """MP3 bytes, and whether the previous/next context was accepted."""
    def call(ctx: bool) -> bytes:
        body = {"text": text, "model_id": model, "voice_settings": dict(settings)}
        if model == "eleven_multilingual_v2":
            body["voice_settings"]["use_speaker_boost"] = True
        if ctx:
            body.update(previous_text=prev, next_text=nxt)
        req = urllib.request.Request(f"{API}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                                     data=json.dumps(body).encode(),
                                     headers={"xi-api-key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    try:
        return call(True), True
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:300]
        if e.code in (400, 422) and ("previous" in msg or "next" in msg or "context" in msg):
            print(f"  {model} refused previous/next context ({e.code}); voicing without it", flush=True)
            return call(False), False
        raise SystemExit(f"ElevenLabs refused the take ({e.code}): {msg}")


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def clean(src: Path, dst: Path, tempo: float = 1.0) -> None:
    pre = f"atempo={tempo:.4f}," if abs(tempo - 1) > 0.002 else ""
    ff("-i", str(src), "-af", pre + "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
       "silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-2:LRA=11",
       "-ar", "48000", "-ac", "1", str(dst))


def concat(parts: list[Path], dst: Path, gap_s: float = 0.6) -> None:
    gap = OUT / "gap.wav"
    if not gap.exists():
        ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(gap_s), str(gap))
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\nfile '{gap.as_posix()}'\n" for p in parts), encoding="utf-8")
    ff("-f", "concat", "-safe", "0", "-i", str(lst), *(["-b:a", "160k"] if dst.suffix == ".mp3" else []), str(dst))
    lst.unlink()


def measure(chunks: list[Path], n_words: int) -> dict:
    """Praat measures over the speech chunks (the inserted gaps between chunks are not counted)."""
    import numpy as np
    import parselmouth
    st_all, idb_all, pauses, speech = [], [], [], 0.0
    for c in chunks:
        snd = parselmouth.Sound(str(c))
        speech += snd.get_total_duration()
        f0 = snd.to_pitch(time_step=0.01, pitch_floor=60, pitch_ceiling=400).selected_array["frequency"]
        f0 = f0[f0 > 0]
        st_all.append(12 * np.log2(f0 / 100.0))
        it = snd.to_intensity(minimum_pitch=60, time_step=0.01).values[0]
        top = np.percentile(it, 95)
        idb_all.append(it[it > top - 25])
        quiet = it < top - 25
        run = 0
        for q in list(quiet) + [False]:  # silent stretches of 200 ms or more inside a chunk
            if q:
                run += 1
            else:
                if run >= 20:
                    pauses.append(run / 100)
                run = 0
    st, idb = np.concatenate(st_all), np.concatenate(idb_all)
    d = np.abs(np.diff(st))
    return {
        "speech_seconds": round(speech, 2),
        "wpm": round(n_words / (speech / 60), 1),
        "pitch_median_hz": round(float(100 * 2 ** (np.median(st) / 12)), 1),
        "pitch_range_st": round(float(np.percentile(st, 95) - np.percentile(st, 5)), 2),
        "pitch_sd_st": round(float(np.std(st)), 2),
        "pitch_movement_st_per_10ms": round(float(np.mean(d[d < 3])), 3),
        "loudness_sd_db": round(float(np.std(idb)), 2),
        "pauses_per_min": round(len(pauses) / (speech / 60), 1),
        "mean_pause_s": round(float(np.mean(pauses)), 3) if pauses else 0.0,
    }


def main() -> int:
    cfg = json.loads((ROOT / "data/analysis/voice-ab/ab.json").read_text(encoding="utf-8"))
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("ELEVENLABS_API_KEY is not set")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "blind").mkdir(exist_ok=True)

    # Word check: the tagged script must keep the rewritten script's words, in order (tags, case and
    # punctuation ignored), so the v4 take differs only in delivery cues.
    if words(" ".join(cfg["scripts"]["spoken"])) != words(" ".join(cfg["scripts"]["spoken_tagged"])):
        raise SystemExit("spoken_tagged changes words of spoken; fix the markup")
    for name, chunks in cfg["scripts"].items():
        if any(ch in "".join(chunks) for ch in "—–;"):
            raise SystemExit(f"script {name} has a dash or semicolon")

    need = sum(len(t) for tk in cfg["takes"].values() for t in cfg["scripts"][tk["script"]])
    left, tier = credits_left(key)
    print(f"ElevenLabs ({tier}): {need} characters to voice, {left} credits left; reserve {cfg['reserve_credits']}",
          flush=True)
    if left - need < cfg["reserve_credits"]:
        raise SystemExit("Not enough credits above the reserve; nothing was recorded.")
    vs = get("/v2/voices?page_size=100&search=" + urllib.request.quote(cfg["voice"]), key).get("voices", [])
    found = [v["voice_id"] for v in vs if v.get("name") == cfg["voice"]]
    if not found:
        raise SystemExit(f"Voice '{cfg['voice']}' is not on this account.")
    voice_id = found[0]

    results: dict = {}
    order = sorted(cfg["takes"], key=lambda k: "pace_match" in cfg["takes"][k])  # v2 twins first
    for name in order:
        tk = cfg["takes"][name]
        chunks = cfg["scripts"][tk["script"]]
        settings = cfg["v2_settings"] if tk["model"] == "eleven_multilingual_v2" else cfg["v4_settings"]
        before = credits_left(key)[0]
        raws, ctx_ok = [], True
        for i, text in enumerate(chunks):
            prev = plain(chunks[i - 1]) if i else cfg["context_before"]
            nxt = plain(chunks[i + 1]) if i + 1 < len(chunks) else cfg["context_after"]
            mp3, ok = tts(text, voice_id, tk["model"], settings, key, prev, nxt)
            ctx_ok &= ok
            raw = OUT / f"{name}-{i}.raw.mp3"
            raw.write_bytes(mp3)
            raws.append(raw)
        used = before - credits_left(key)[0]
        chars = sum(len(t) for t in chunks)
        tempo = 1.0
        if tk.get("pace_match"):  # make this take as long as its v2 twin, so pace is not the difference
            for i, raw in enumerate(raws):
                clean(raw, OUT / f"{name}-{i}.dry.wav")
            mine = sum(seconds(OUT / f"{name}-{i}.dry.wav") for i in range(len(raws)))
            target = len(words(" ".join(chunks))) / results[tk["pace_match"]]["metrics"]["wpm"] * 60
            tempo = max(0.85, min(1.15, mine / target))  # same words per minute as the twin
        dry = []
        for i, raw in enumerate(raws):
            p = OUT / f"{name}-{i}.dry.wav"
            clean(raw, p, tempo)
            dry.append(p)
        mastered = []
        for i, p in enumerate(dry):
            m = OUT / f"{name}-{i}.master.wav"
            ff("-i", str(p), "-af", MASTERS[cfg["master"]], "-ar", "48000", "-ac", "1", str(m))
            mastered.append(m)
        concat(mastered, OUT / f"take-{name}.mp3")
        n_words = len(words(" ".join(chunks)))
        results[name] = {**tk, "chars": chars, "credits_used": used,
                         "credits_per_char": round(used / chars, 3) if chars else None,
                         "context_accepted": ctx_ok, "atempo": round(tempo, 4),
                         "metrics": measure(dry, n_words)}
        print(name, json.dumps(results[name]), flush=True)

    labels = list(cfg["takes"])
    random.SystemRandom().shuffle(labels)
    key_map = {f"take-{i + 1}": lab for i, lab in enumerate(labels)}
    for blind, lab in key_map.items():
        (OUT / "blind" / f"{blind}.mp3").write_bytes((OUT / f"take-{lab}.mp3").read_bytes())
    (OUT / "key.json").write_text(json.dumps(key_map, indent=1), encoding="utf-8")
    (OUT / "metrics.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    rows = ["| Take | Model | Script | wpm | Pitch range (st) | Pitch SD (st) | Loudness SD (dB) | Pauses/min | "
            "Mean pause (s) | Credits/char |", "|---|---|---|---|---|---|---|---|---|---|"]
    for lab in cfg["takes"]:
        r, m = results[lab], results[lab]["metrics"]
        rows.append(f"| {lab} | {r['model']} | {r['script']} | {m['wpm']} | {m['pitch_range_st']} | {m['pitch_sd_st']} | "
                    f"{m['loudness_sd_db']} | {m['pauses_per_min']} | {m['mean_pause_s']} | {r['credits_per_char']} |")
    (OUT / "report.md").write_text("# Narrator A/B\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    print(f"ElevenLabs: {credits_left(key)[0]} credits left", flush=True)
    for f in OUT.glob("*.raw.mp3"):
        f.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
