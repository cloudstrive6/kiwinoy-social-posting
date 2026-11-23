"""Backup narrator for KG long-forms: VoxCPM2 cloning "BOSS KG Guide C" on Modal (2026-11-23).

Bryce, 2026-11-23: "VoxCPM2 take 1 sounds best, plan it on Modal. We use this as a backup if
ElevenLabs Guide C runout of credits." Plan and checks: wiki/answers/kg-narrator-backup-voxcpm2-modal.md
in the Bryce-Brain vault. tools/analysis_narrate.py calls narrate() when KG_NARRATOR is voxcpm2, or
auto with too few credits and no Guide C take yet for the video. Takes go to their own folder
(output/analysis/<game>/narration-vox/), never next to the paid Guide C takes.

Every paragraph passes QC or is re-rolled with seed 22, then 33; still failing, the run stops and
names it. QC (faster-whisper small.en on the runner's CPU):
  - words wrong on normalised text: at most 5%, and at least 1 word is always allowed;
  - no flat-topped clipping in the raw take (CLIP_*);
  - length 0.6 to 1.6 times words / 216 wpm;
  - every "at" anchor passes the same test the render uses (analysis_render.beat_anchors);
  - paragraphs of 15 words or more: pace 185 to 245 wpm, pitch within 2 semitones of the video's median.

    python tools/voice_backup.py parity            # check 1: the 179-word test paragraph on Modal
Needs MODAL_TOKEN_ID and MODAL_TOKEN_SECRET (Modal reads them from the environment).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from analysis_edl import strip_tags  # noqa: E402

APP_NAME, CLS_NAME = "kg-voxcpm2-narrator", "Narrator"
SEEDS = (11, 22, 33)          # take 1 of the listening test, then two re-rolls
TAG = "vox|voxcpm2-2.0.3|cfg2.0|steps10|guideC-take1"
WPM = 216.0                   # take 1's pace on the test paragraph
# Cost estimate (USD, Modal list prices on 2026-11-23). The Modal dashboard is the real figure: this
# adds each container's load and its 120 s idle wait, plus about 15% for Modal's CPU and memory charge.
L4_PER_HOUR, IDLE_S, OVERHEAD, MAX_CONTAINERS = 0.80, 120.0, 1.15, 4
MAX_WER = 0.05
# Clipping (2026-11-23): take 1, the take Bryce picked by ear, peaks at -0.05 dBFS but has no
# flat-topped run at all, so loud is not clipped. The plan's "peak below -1 dBFS" would have refused
# it. A clipped take (VoxCPM issue #404) shows runs of 3+ identical samples at 0.98 of full scale.
CLIP_LEVEL, CLIP_RUNS_PER_MIN, CLIP_LONGEST = 0.98, 5.0, 8
# Pace is judged on the raw take, before the whole video is paced to WPM (dry run 2026-11-23: Modal takes
# run about 11% fast, so 185 to 245 wpm became 185 to 270 raw; 290 wpm still re-rolls).
LEN_RANGE, PACE_RANGE, PITCH_ST = (0.6, 1.6), (185.0, 270.0), 2.0
LONG = 15                     # words; shorter paragraphs skip the pace and pitch checks
# Whisper's spelling -> the script's, applied to what was heard before scoring (names Whisper
# writes differently whatever the voice). Add to it when a clean take fails on a spelling.
ALIASES = {"buck me": "buckme", "buck-me": "buckme", "a t m s": "atms", "atm's": "atms",
           "g t a": "gta", "okay": "ok", "'n'": " and "}
_NUMW = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_NUMW.update({w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1})

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
        "sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
        "nine": "ninth", "twelve": "twelfth"}


def num_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + num_words(n % 100))
    if n < 1_000_000:
        return num_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + num_words(n % 1000))
    if n < 1_000_000_000:
        return num_words(n // 1_000_000) + " million" + ("" if n % 1_000_000 == 0 else " " + num_words(n % 1_000_000))
    return str(n)


def ordinal(n: int) -> str:
    w = num_words(n).split()
    last = w[-1]
    w[-1] = _ORD.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return " ".join(w)


def year_words(n: int) -> str:
    """2026 -> twenty twenty six, 1998 -> nineteen ninety eight, 2005 -> two thousand five."""
    if 2000 <= n <= 2009:
        return num_words(n)
    hi, lo = divmod(n, 100)
    return num_words(hi) + (" hundred" if lo == 0 else " " + ("oh " if lo < 10 else "") + num_words(lo))


def tokens(text: str) -> list[str]:
    """Lower case, aliases applied, numbers as words, punctuation dropped, plurals folded."""
    t = text.lower().replace("’", "'").replace(",", "")
    for a, b in ALIASES.items():
        t = re.sub(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", b, t)
    t = re.sub(r"\$(\d+(?:\.\d+)?)\s*(million|thousand|k)?",
               lambda m: f" {m.group(1)} {(m.group(2) or '').replace('k', 'thousand')} dollars ", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%", r" \1 percent ", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: " " + ordinal(int(m.group(1))) + " ", t)
    t = re.sub(r"\b(\d+)\.(\d+)\b", lambda m: f" {m.group(1)} point {' '.join(m.group(2))} ", t)
    t = re.sub(r"(?<![\d.])(19\d\d|20\d\d)(?![\d.])(?!\s*dollars)", lambda m: " " + year_words(int(m.group())) + " ", t)
    t = re.sub(r"\d+", lambda m: " " + num_words(int(m.group())) + " ", t)
    out = []
    for w in t.replace("-", " ").split():
        w = re.sub(r"[^a-z0-9]", "", w)
        if not w or w in ("and", "n"):  # "five hundred and thirty-one" against Whisper's "531"
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return _hundreds(out)


def _hundreds(ws: list[str]) -> list[str]:
    """"eighteen hundred" (spoken) and "one thousand eight hundred" (Whisper's $1,800 expanded) read alike."""
    out, i = [], 0
    while i < len(ws):
        n = None
        if i + 1 < len(ws) and ws[i] in _NUMW and ws[i + 1] == "hundred" and _NUMW[ws[i]] >= 11:
            n, step = _NUMW[ws[i]], 2
        elif (i + 2 < len(ws) and ws[i] in _NUMW and ws[i + 1] in _NUMW and ws[i + 2] == "hundred"
              and _NUMW[ws[i]] >= 20 and 0 < _NUMW[ws[i + 1]] < 10):
            n, step = _NUMW[ws[i]] + _NUMW[ws[i + 1]], 3
        if n:
            out += num_words(n * 100).split()
            i += step
            continue
        out.append(ws[i])
        i += 1
    return out


def _merge_joined(ref: list[str], hyp: list[str]) -> list[str]:
    """"med kit" heard for "medkit": two heard tokens that make one script word count as that word."""
    want, out, i = set(ref), [], 0
    while i < len(hyp):
        if i + 1 < len(hyp) and hyp[i] + hyp[i + 1] in want and hyp[i] not in want:
            out.append(hyp[i] + hyp[i + 1])
            i += 2
            continue
        out.append(hyp[i])
        i += 1
    return out


def word_diff(ref: list[str], hyp: list[str], limit: int = 6) -> str:
    import difflib
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    bits = [f"{' '.join(ref[a:b]) or '-'} -> {' '.join(hyp[c:d]) or '-'}"
            for op, a, b, c, d in sm.get_opcodes() if op != "equal"]
    return "; ".join(bits[:limit])


def names_prompt(text: str) -> str:
    """Whisper hint: the paragraph's names only (capitalised words not starting a sentence). The whole
    paragraph as a prompt made Whisper skip speech (analysis_shorts, 2026-11-13)."""
    names, prev = [], "."
    for w in re.findall(r"[A-Za-z][\w'’]*|[.!?]", text):
        if w in ".!?":
            prev = w
            continue
        if w[0].isupper() and prev not in ".!?" and w not in ("I", "KG") and w not in names:
            names.append(w)
        prev = w
    return ", ".join(names) + "." if names else ""


def edits(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def wer(ref: list[str], hyp: list[str]) -> float:
    return edits(ref, hyp) / len(ref) if ref else 0.0


def seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def clipping(raw: Path) -> dict:
    """Peak in dBFS, flat-topped runs (3+ identical samples at CLIP_LEVEL or above) per minute, and the
    longest such run, measured on the raw float take."""
    import numpy as np
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(raw), "-f", "f32le", "-ac", "1", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.float32)
    if len(x) < 2:
        return {"peak_dbfs": -120.0, "clip_runs_per_min": 0.0, "clip_longest": 0}
    minutes = max(1e-6, seconds(raw) / 60)  # the model's own sample rate, not assumed
    hot = np.abs(x) >= CLIP_LEVEL
    same = np.concatenate([[False], (x[1:] == x[:-1]) & hot[1:] & hot[:-1]])
    d = np.diff(np.concatenate([[0], same.astype(np.int8), [0]]))
    runs = np.flatnonzero(d == -1) - np.flatnonzero(d == 1) + 1  # samples per flat run
    p = float(np.max(np.abs(x)))
    return {"peak_dbfs": round(20 * math.log10(p), 2) if p > 0 else -120.0,
            "clip_runs_per_min": round(float((runs >= 3).sum()) / minutes, 1),
            "clip_longest": int(runs.max()) if len(runs) else 0}


def pitch_median(wav: Path) -> float | None:
    """Median F0 in Hz, by the same measure that gave take 1's 175.8 Hz (el_voice_brief.measure,
    also used by the 2026-11-23 listening test), so parity compares like with like."""
    from el_voice_brief import measure
    f = measure(wav, 1)["f0_median_hz"]
    return float(f) if f and f > 1.0 else None


def heard_words(wav: Path, text: str = "") -> list[dict]:
    from analysis_shorts import whisper_words
    return whisper_words(wav, names_prompt(text), model="small.en")


def anchor_problems(b: dict, heard: list[dict], secs: float) -> list[str]:
    """The render's own anchor test (analysis_render.beat_anchors on snapped word times), so a take
    that passes here also passes there."""
    if not any(sh.get("at") for sh in b.get("shots") or []):
        return []
    from analysis_render import beat_anchors
    from analysis_shorts import snap
    words = snap(strip_tags(b.get("tts") or b.get("text") or ""), heard, 0.0, secs) if heard else []
    try:
        beat_anchors(b, {"words": words, "heard": heard})
        return []
    except SystemExit as e:
        return [f"anchor: {e}"]


def qc(b: dict, raw: Path, wav: Path) -> tuple[list[str], dict]:
    """Problems with one take (empty list = pass) and its measurements."""
    text = strip_tags(b["tts"])
    ref = tokens(text)
    heard = heard_words(wav, text)
    hyp = _merge_joined(ref, tokens(" ".join(w["w"] for w in heard)))
    secs = seconds(wav)
    n = len(text.split())
    errs = edits(ref, hyp)
    m = {"wer": round(errs / max(1, len(ref)), 4), "errors": errs, **clipping(raw), "seconds": round(secs, 3),
         "expected_s": round(n / WPM * 60, 2)}
    bad = []
    if errs > max(1, math.floor(MAX_WER * len(ref))):  # one Whisper slip never fails a short line
        bad.append(f"{errs} words wrong of {len(ref)} ({m['wer']:.1%}: {word_diff(ref, hyp)})")
    if m["clip_runs_per_min"] > CLIP_RUNS_PER_MIN or m["clip_longest"] >= CLIP_LONGEST:
        bad.append(f"clipping: {m['clip_runs_per_min']} flat runs a minute, longest {m['clip_longest']} samples")
    ratio = secs / max(0.5, m["expected_s"])
    if not LEN_RANGE[0] <= ratio <= LEN_RANGE[1]:
        bad.append(f"length {secs:.1f} s is {ratio:.2f}x the expected {m['expected_s']:.1f} s")
    bad += anchor_problems(b, heard, secs)
    if n >= LONG and secs > 0:
        m["wpm"] = round(n / (secs / 60), 1)
        if not PACE_RANGE[0] <= m["wpm"] <= PACE_RANGE[1]:
            bad.append(f"pace {m['wpm']} wpm")
        m["pitch_hz"] = pitch_median(wav)
    return bad, m


def take_hash(b: dict) -> str:
    extra = f"|take{b['take']}" if b.get("take") else ""
    return hashlib.sha1(f"{TAG}|{strip_tags(b['tts'])}{extra}".encode()).hexdigest()[:12]


def usd(gpu_s: float, containers: int, load_s: float) -> float:
    return round((gpu_s + containers * (load_s + IDLE_S)) / 3600 * L4_PER_HOUR * OVERHEAD, 3)


def _remote():
    import modal
    return modal.Cls.from_name(APP_NAME, CLS_NAME)()


def _clean(raw: Path, wav: Path) -> None:
    """The same first pass as a Guide C take: trim silence at both ends, -16 LUFS, 48 kHz mono."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                    "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                    "loudnorm=I=-16:TP=-2:LRA=11", "-ar", "48000", "-ac", "1", str(wav)], check=True)


def _seed_index(seed) -> int:
    return SEEDS.index(seed) if seed in SEEDS else len(SEEDS) - 1


def narrate(narr: list[dict], out: Path) -> dict:
    """Voice every paragraph without a current backup take into `out`. Writes timings.json after
    each paragraph, so a crash keeps what was done. Returns a summary for the log and Telegram."""
    out.mkdir(parents=True, exist_ok=True)
    tpath = out / "timings.json"
    timings = json.loads(tpath.read_text(encoding="utf-8")) if tpath.exists() else {}

    def save() -> None:
        tpath.write_text(json.dumps(timings, indent=1), encoding="utf-8")

    def current(b: dict) -> bool:
        return (out / f"{b['id']}.wav").exists() and timings.get(b["id"], {}).get("hash") == take_hash(b)

    pending = [b for b in narr if not current(b)]
    nxt_seed = {b["id"]: 0 for b in pending}   # index into SEEDS of the next try
    call_fails: dict[str, int] = {}             # a failed Modal call retries the same seed once
    fails: dict[str, list[str]] = {}
    gpu_s, rerolls, t0, load_s, voiced = 0.0, 0, time.time(), [], set()
    containers = min(MAX_CONTAINERS, len(pending))
    narrator = _remote() if pending else None
    print(f"VoxCPM2 backup: {len(pending)} of {len(narr)} paragraphs to voice", flush=True)

    def give_up(b: dict) -> None:
        raise SystemExit(f"VoxCPM2 backup: {b['id']} failed QC with seeds {list(SEEDS)}: "
                         f"{'; '.join(fails.get(b['id'], ['no reason recorded']))}. Stopped; "
                         f"the Guide C takes were not touched.")

    while pending:
        for b in pending:
            if nxt_seed[b["id"]] >= len(SEEDS):
                give_up(b)
        args = [(b["id"], strip_tags(b["tts"]), SEEDS[nxt_seed[b["id"]]]) for b in pending]
        rerolls += sum(1 for b in pending if nxt_seed[b["id"]] > 0)
        by_id = {b["id"]: b for b in pending}
        nxt = []
        for res in narrator.narrate_one.starmap(args, order_outputs=False, return_exceptions=True):
            if isinstance(res, BaseException):
                print(f"VoxCPM2 call failed: {res!r}", flush=True)
                continue  # its paragraph is picked up below as still pending
            b = by_id.pop(res["id"])
            nxt_seed[b["id"]] = _seed_index(res["seed"]) + 1
            gpu_s += float(res["render_s"])
            load_s.append(float(res.get("load_s") or 0))
            raw, wav, tmp = out / f"{b['id']}.raw.wav", out / f"{b['id']}.wav", out / f"{b['id']}.qc.wav"
            raw.write_bytes(res["wav"])
            _clean(raw, tmp)
            bad, m = qc(b, raw, tmp)
            raw.unlink()
            if bad:
                fails[b["id"]] = bad
                tmp.unlink()
                print(f"{b['id']}: seed {res['seed']} failed QC: {'; '.join(bad)}", flush=True)
                nxt.append(b)
                continue
            tmp.replace(wav)
            (out / f"{b['id']}.dry.wav").unlink(missing_ok=True)  # a new take is mastered fresh
            timings[b["id"]] = {"hash": take_hash(b), "seconds": round(seconds(wav), 3), "voice": "voxcpm2",
                                "seed": res["seed"], "qc": m}
            voiced.add(b["id"])
            save()
            print(f"{b['id']}: {m['seconds']:.1f} s, seed {res['seed']}, {m['errors']} words wrong", flush=True)
        for b in by_id.values():  # calls that raised: same seed once more, then the next seed
            call_fails[b["id"]] = call_fails.get(b["id"], 0) + 1
            if call_fails[b["id"]] > 1:
                nxt_seed[b["id"]] += 1
                call_fails[b["id"]] = 0
            fails.setdefault(b["id"], []).append("Modal call failed")
            nxt.append(b)
        pending = nxt
        if not pending:  # pitch is judged against the whole video, once every paragraph has a take
            hz = {b["id"]: timings[b["id"]]["qc"].get("pitch_hz") for b in narr
                  if timings.get(b["id"], {}).get("qc", {}).get("pitch_hz")}
            if hz:
                med = sorted(hz.values())[len(hz) // 2]
                for b in narr:
                    f = hz.get(b["id"])
                    if f and abs(12 * math.log2(f / med)) > PITCH_ST:
                        fails[b["id"]] = [f"pitch {f:.0f} Hz is over {PITCH_ST} semitones from the video's {med:.0f} Hz"]
                        nxt_seed[b["id"]] = _seed_index(timings[b["id"]].get("seed")) + 1
                        if nxt_seed[b["id"]] >= len(SEEDS):
                            give_up(b)  # before deleting anything: the take stays on disk for a listen
                        print(f"{b['id']}: {fails[b['id']][0]}; re-rolling", flush=True)
                        (out / f"{b['id']}.wav").unlink(missing_ok=True)
                        timings.pop(b["id"], None)
                        pending.append(b)
                if pending and narrator is None:
                    narrator = _remote()
                save()
    wall = time.time() - t0
    cold = max(load_s) if load_s else 0.0
    return {"paragraphs": len(narr), "voiced": len(voiced), "rerolls": rerolls, "gpu_s": round(gpu_s, 1),
            "wall_s": round(wall, 1), "cold_start_s": round(cold, 1),
            "usd_est": usd(gpu_s, containers, cold) if voiced else 0.0}


def parity() -> int:
    """Check 1: the 179-word test paragraph on Modal with take 1's settings, scored as the local test."""
    text = (ROOT / "data" / "voice" / "voxcpm2_parity.txt").read_text(encoding="utf-8").strip()
    out = ROOT / "output" / "voice-backup"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = _remote().narrate_one.remote("parity", text, SEEDS[0])
    wall = time.time() - t0
    raw = out / "parity_take1.wav"
    raw.write_bytes(res["wav"])
    wav = out / "parity_take1.clean.wav"
    _clean(raw, wav)
    bad, m = qc({"id": "parity", "tts": text}, raw, wav)
    spa = res["render_s"] / max(0.1, res["audio_s"])
    m.update(render_s=res["render_s"], audio_s=res["audio_s"], load_s=res["load_s"], wall_s=round(wall, 1),
             s_per_audio_s=round(spa, 2),
             # a 15-minute narration: 900 s of audio over up to 4 containers, each loading once and idling 120 s
             usd_per_15min_est=usd(spa * 900, MAX_CONTAINERS, res["load_s"]),
             wall_per_15min_min_est=round((spa * 900 / MAX_CONTAINERS + res["load_s"]) / 60, 1))
    target = {"wer_max": 0.02, "pitch_hz": 175.8, "pitch_st_max": 1.0, "wpm": 216.0, "wpm_pct_max": 5.0}
    p = m.get("pitch_hz")
    m["pitch_st_off"] = round(12 * math.log2(p / target["pitch_hz"]), 2) if p else None
    # a real run slows or speeds the whole video to WPM (analysis_narrate.narrate_backup), so parity
    # judges the pace after that step and keeps the raw pace for the record
    if m.get("wpm"):
        raw_dev = m["wpm"] / target["wpm"] - 1
        m["pace_applied"] = round(min(1.10, max(0.85, WPM / m["wpm"])), 3) if abs(raw_dev) > 0.03 else 1.0
        m["wpm_raw_pct_off"] = round(raw_dev * 100, 1)
        m["wpm"] = round(m["wpm"] * m["pace_applied"], 1)
    m["wpm_pct_off"] = round((m["wpm"] / target["wpm"] - 1) * 100, 1) if m.get("wpm") else None
    m["pass"] = (m["wer"] <= target["wer_max"] and m["pitch_st_off"] is not None
                 and abs(m["pitch_st_off"]) <= target["pitch_st_max"]
                 and m["wpm_pct_off"] is not None and abs(m["wpm_pct_off"]) <= target["wpm_pct_max"]
                 and m["usd_per_15min_est"] < 1.0 and m["wall_per_15min_min_est"] < 40 and not bad)
    m["qc_problems"] = bad
    (out / "parity.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    print(json.dumps(m, indent=1), flush=True)
    return 0 if m["pass"] else 2


if __name__ == "__main__":
    if sys.argv[1:2] == ["parity"]:
        raise SystemExit(parity())
    print(__doc__)
