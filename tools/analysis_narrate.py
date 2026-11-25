"""Narration for a KG analysis long-form, one take per paragraph (2026-11-12, ElevenLabs 2026-11-13).

Narrator: if edl.json has a "narrator" block, that voice is used (ElevenLabs; from 2026-11-13 the
BOSS KG voice is "BOSS KG Narrator A", designed for the channel and picked by Bryce, on
Multilingual v2, then Eleven v4 from 2026-11-17; new EDLs from 2026-11-21 use "BOSS KG Guide C"). Older EDLs carry "voice" and "speaking_rate" and keep their Chirp 3 HD voice
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
sys.path.insert(0, str(ROOT / "tools"))
from analysis_edl import reads_tags, strip_tags  # noqa: E402


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
    prev, nxt = strip_tags(prev), strip_tags(nxt)  # context is always plain text
    if reads_tags(nar):  # v3/v4 take only stability and similarity (2026-11-17); pace comes from "tempo"
        vs = {"stability": nar.get("stability", 0.5), "similarity_boost": nar.get("similarity_boost", 0.75)}
    else:  # a v2 or Flash model would read a tag aloud
        text = strip_tags(text)
        vs = {"stability": nar.get("stability", 0.5), "similarity_boost": nar.get("similarity_boost", 0.75),
              "style": nar.get("style", 0.0), "use_speaker_boost": True, "speed": nar.get("speed", 1.0)}
    body = {"text": text, "model_id": nar.get("model_id", "eleven_multilingual_v2"), "voice_settings": vs}
    if prev:
        body["previous_text"] = prev
    if nxt:
        body["next_text"] = nxt
    def call(b: dict) -> bytes:
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{nar['voice_id']}?output_format=mp3_44100_128",
            data=json.dumps(b).encode(), headers={"xi-api-key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    try:
        return call(body)
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:300]
        if e.code in (400, 422) and ("previous" in msg or "next" in msg) and ("previous_text" in body or "next_text" in body):
            print(f"ElevenLabs refused the previous/next context ({e.code}); voicing without it", flush=True)
            try:
                return call({k: v for k, v in body.items() if k not in ("previous_text", "next_text")})
            except urllib.error.HTTPError as e2:
                msg, e = e2.read().decode()[:300], e2
        raise SystemExit(f"ElevenLabs refused the take ({e.code}): {msg}")


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


# Narrator mastering (Bryce, 2026-11-15: "try mastering the audio of the narrator so that it is still
# pleasant to the ears"). Measured on Narrator A: heavy sibilance (about 12% of speech frames led by
# 5-9 kHz), some 200-500 Hz boxiness, rumble under 80 Hz, dynamics already tight. Presets chosen by ear
# from level-matched A/B samples (inbox/narrator-master-ab/ in the vault): C medium (Bryce's first pick),
# D hard, E harder. Each ends at -16 LUFS like the unmastered take; the mix then goes to -14 LUFS.
_LN = "loudnorm=I=-16:TP=-2:LRA=11"
MASTERS = {
    "C": ("highpass=f=80:poles=2,equalizer=f=280:width_type=q:w=1.0:g=-3,equalizer=f=3200:width_type=q:w=1.0:g=2,"
          "deesser=i=0.45:m=0.5:f=0.7:s=o,acompressor=threshold=-22dB:ratio=2:attack=10:release=150:makeup=1," + _LN),
    "D": ("highpass=f=85:poles=2,equalizer=f=120:width_type=q:w=0.9:g=1.5,equalizer=f=300:width_type=q:w=1.0:g=-4,"
          "acompressor=threshold=-30dB:ratio=3.5:attack=5:release=90:knee=4:makeup=6,"
          "acompressor=threshold=-18dB:ratio=2:attack=25:release=250:makeup=2,"
          "deesser=i=0.45:m=0.5:f=0.85:s=o,equalizer=f=3300:width_type=q:w=0.9:g=3,"
          "alimiter=limit=0.89:attack=2:release=40:level=false," + _LN),
    "E": ("highpass=f=90:poles=2,equalizer=f=120:width_type=q:w=0.9:g=2,equalizer=f=320:width_type=q:w=1.0:g=-5,"
          "acompressor=threshold=-34dB:ratio=5:attack=4:release=80:knee=4:makeup=9,"
          "acompressor=threshold=-18dB:ratio=2.5:attack=25:release=250:makeup=2,"
          "asoftclip=type=tanh:threshold=0.85:output=0.9,deesser=i=0.5:m=0.5:f=0.85:s=o,"
          "equalizer=f=3300:width_type=q:w=0.9:g=3.5,alimiter=limit=0.85:attack=2:release=40:level=false," + _LN),
}


def master_takes(narr: list, out: Path, timings: dict, preset: str, pace: float = 1.0, tail_fade: float = 0.0) -> None:
    """Master every paragraph from its kept dry take (<id>.dry.wav), so a preset can change later
    without re-recording or stacking processing. A re-recorded paragraph refreshes its dry take.
    "pace" (2026-11-18) slows or speeds the dry take before mastering, free: the first v4 video read
    at 220 wpm against the 199 wpm take Bryce picked, so its EDL carries pace 0.91."""
    import shutil
    chain = MASTERS.get(preset, preset)
    if abs(pace - 1) > 0.001:
        chain = f"atempo={pace}," + chain
    if tail_fade > 0:  # Eleven v4 takes can stop dead at speech level (bosses v3 review, 2026-11-18)
        chain += f",areverse,afade=t=in:d={tail_fade},areverse"
    for b in narr:
        wav, dry, t = out / f"{b['id']}.wav", out / f"{b['id']}.dry.wav", timings.get(b["id"], {})
        if not wav.exists():
            continue
        if (t.get("master") == preset and t.get("master_hash") == t.get("hash") and dry.exists()
                and float(t.get("pace", 1.0)) == pace and float(t.get("tail_fade", 0.0)) == tail_fade):
            continue
        if not dry.exists() or t.get("master_hash") != t.get("hash"):
            shutil.copyfile(wav, dry)  # the current take is unmastered (new, or never mastered)
        tmp = out / f"{b['id']}.mtmp.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(dry), "-af", chain, "-ar", "48000", "-ac", "1",
                        str(tmp)], check=True)
        tmp.replace(wav)
        t.update(master=preset, master_hash=t.get("hash"), seconds=round(seconds(wav), 3))
        t.pop("leveled2", None)  # a fresh master loses any short-take gain, so it is levelled again
        if abs(pace - 1) > 0.001 or "pace" in t:
            t["pace"] = pace
        if tail_fade > 0 or "tail_fade" in t:
            t["tail_fade"] = tail_fade
        timings[b["id"]] = t
    print(f"narration mastered with preset {preset}", flush=True)


def seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def used_file(game: str) -> Path:
    """Which narration folder the render reads (2026-11-23): narration/ for Guide C, narration-vox/
    for the VoxCPM2 backup. Written by every narrate run."""
    return ROOT / "output" / "analysis" / game / "narrator-used.json"


def el_take_hash(b: dict, nar: dict) -> str:
    """The cache hash of an ElevenLabs take (one definition, used by main and by the backup checks)."""
    tag = f"el|{nar['name']}|{nar.get('model_id')}|{nar.get('stability')}|{nar.get('style')}|{nar.get('speed')}"
    if nar.get("tempo"):  # only new EDLs carry it, so older videos keep their cached takes
        tag += f"|tempo{nar['tempo']}"
    said = b["tts"] if reads_tags(nar) else strip_tags(b["tts"])
    extra = f"|take{b['take']}" if b.get("take") else ""
    return hashlib.sha1(f"{tag}|{float(nar.get('speed', 1.0))}|{said}{extra}".encode()).hexdigest()[:12]


def guide_c_render_on_b2(game: str) -> bool | None:
    """True if B2 renders/analysis/<game>/ holds a draft voiced by ElevenLabs (a name without -vox),
    None if B2 cannot be read. A lasting record: the Actions cache of paid takes expires after 7 days
    unused, so "no Guide C take in the cache" alone could re-voice a finished video (review 2026-11-23)."""
    sys.path.insert(0, str(ROOT))
    from core import b2_store
    if not b2_store.enabled():
        return None
    names = [f.get("fileName", "") for f in b2_store._list_names(f"renders/analysis/{game}/")]
    return any(n.endswith(".mp4") and f"/{game}-analysis-" in n and "-vox" not in n for n in names)


def vox_folder(game: str, out: Path) -> Path:
    """narration-vox/ for this game. A folder restored from another video's cache is cleared first."""
    import shutil
    mark = out / "game.txt"
    if out.exists() and (not mark.exists() or mark.read_text(encoding="utf-8").strip() != game):
        print(f"{out} belongs to another video; clearing it", flush=True)
        shutil.rmtree(out)
    return out


def level_short_takes(narr: list, out: Path, timings: dict) -> None:
    """Raise short takes that came out quiet (independent review 2026-11-24 of the guide's v1-vox: the deadpan
    one-liners sat 3 to 6 dB under the narration, because a -16 LUFS loudnorm cannot measure a 2 s clip). A take
    under 6 s more than 1.5 dB below the median speech level is raised to it, at most 6 dB, with a limiter holding
    peaks at -2 dBFS (v2 render: a plain peak cap left under 1 dB of room, because master C already peaks near
    -2.8 dBFS, so nothing moved). Applied once per mastered take (backup narrator only, so published Guide C
    videos never change)."""
    import re as _re
    import statistics

    def levels(wav: Path) -> tuple[float, float]:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
                            "silenceremove=stop_periods=-1:stop_threshold=-45dB,volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
        mean = _re.search(r"mean_volume: (-?[\d.]+) dB", r)
        peak = _re.search(r"max_volume: (-?[\d.]+) dB", r)
        return (float(mean.group(1)) if mean else -99.0), (float(peak.group(1)) if peak else 0.0)

    lv = {}
    for b in narr:
        wav = out / f"{b['id']}.wav"
        if wav.exists():
            lv[b["id"]] = levels(wav)
    long_means = [lv[i][0] for i in lv if float(timings.get(i, {}).get("seconds", 0)) >= 6]
    if not long_means:
        return
    med = statistics.median(long_means)
    for b in narr:
        t, i = timings.get(b["id"], {}), b["id"]
        if i not in lv or float(t.get("seconds", 0)) >= 6 or t.get("leveled2") == t.get("master_hash"):
            continue
        mean, _peak = lv[i]
        gain = min(6.0, med - mean)
        if gain > 1.5:
            wav = out / f"{i}.wav"
            tmp = out / f"{i}.lvl.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af",
                            f"volume={gain:.2f}dB,alimiter=limit=0.79:attack=2:release=40:level=false",
                            "-ar", "48000", "-ac", "1", str(tmp)], check=True)
            tmp.replace(wav)
            print(f"{i}: short take raised {gain:.1f} dB to the narration median", flush=True)
        t.pop("leveled", None)
        t["leveled2"] = t.get("master_hash")
        timings[i] = t


def narrate_backup(game: str, edl: dict, narr: list, nar: dict, out: Path, reason: str) -> int:
    """Voice the whole video with the VoxCPM2 backup into narration-vox/ (tools/voice_backup.py),
    then the same tail trim and mastering as Guide C. Never writes to narration/."""
    import voice_backup
    if nar.get("name") != "BOSS KG Guide C":
        raise SystemExit("The VoxCPM2 backup clones BOSS KG Guide C only; this EDL uses another voice.")
    print(f"Narrator: VoxCPM2 backup (Guide C clone on Modal), because {reason}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "game.txt").write_text(game, encoding="utf-8")
    summary = voice_backup.narrate(narr, out)
    timings = json.loads((out / "timings.json").read_text(encoding="utf-8"))
    for b in narr:
        wav = out / f"{b['id']}.wav"
        if wav.exists() and not timings[b["id"]].get("tail_trimmed"):
            trim_tail(wav)
            timings[b["id"]].update(seconds=round(seconds(wav), 3), tail_trimmed=True)
    # Pace to take 1's 216 wpm (parity test, 2026-11-23: seed 11 on a Modal L4 read the test paragraph at
    # 241 wpm against 216 locally; same words, same pitch). Measured over the whole video on the
    # unmastered takes, then the free atempo slow-down that ElevenLabs EDLs use as "pace".
    said = sum(len(strip_tags(b["tts"]).split()) for b in narr)
    raw_s = sum(float(timings[b["id"]].get("qc", {}).get("seconds") or timings[b["id"]]["seconds"]) for b in narr)
    wpm = said / max(1e-6, raw_s / 60)
    pace = round(min(1.10, max(0.85, voice_backup.WPM / wpm)), 3) if abs(wpm / voice_backup.WPM - 1) > 0.03 else 1.0
    print(f"backup pace: {wpm:.0f} wpm measured, pace {pace} for {voice_backup.WPM:.0f} wpm", flush=True)
    if nar.get("master"):  # ElevenLabs "pace" and "tempo" are not applied: the backup gets its own pace
        master_takes(narr, out, timings, str(nar["master"]), pace, float(nar.get("tail_fade", 0.0)))
    level_short_takes(narr, out, timings)
    (out / "timings.json").write_text(json.dumps(timings, indent=1), encoding="utf-8")
    used_file(game).write_text(json.dumps({"dir": "narration-vox", "voice": "voxcpm2", "reason": reason}),
                               encoding="utf-8")
    words = sum(len(b["text"].split()) for b in narr)
    total = sum(timings[b["id"]]["seconds"] for b in narr)
    report = (f"# Narration: {game}, VoxCPM2 backup (Guide C clone)\n\n"
              f"- why: {reason}\n"
              f"- {len(narr)} paragraphs, {words} words, {total:.0f} s of speech ({total / 60:.1f} min), "
              f"{words / max(1e-6, total / 60):.0f} wpm\n"
              f"- this run: {summary['voiced']} voiced, {summary['rerolls']} re-rolls, {summary['gpu_s']:.0f} GPU s, "
              f"{summary['wall_s']:.0f} s wall, cold start {summary['cold_start_s']:.0f} s, "
              f"about ${summary['usd_est']:.2f} of Modal L4 time\n")
    (out / "narration.md").write_text(report, encoding="utf-8")
    print(report, flush=True)
    # One note per video, the first time its backup narration is complete (dry run 2026-11-23: the runs
    # that voiced paragraphs stopped on QC before this point, and the run that finished voiced none).
    mark = out / "notified.txt"
    if not mark.exists():
        try:
            sys.path.insert(0, str(ROOT))
            from core.notify import telegram
            if telegram(f"KG {game}: narrated with the VoxCPM2 backup ({reason}). {len(narr)} paragraphs, "
                        f"{total / 60:.1f} min of speech; this run {summary['voiced']} voiced, "
                        f"{summary['rerolls']} re-rolls, about ${summary['usd_est']:.2f} of Modal time. "
                        f"The draft name ends in -vox."):
                mark.write_text(reason, encoding="utf-8")
        except Exception as e:  # the note never stops a run
            print(f"Telegram note skipped: {e!r}", flush=True)
    return 0


def main() -> int:
    game = sys.argv[1] if len(sys.argv) > 1 else "wolverine"
    edl = json.loads((ROOT / "data" / "analysis" / game / "edl.json").read_text(encoding="utf-8"))
    from analysis_edl import tts_drift  # the voiced words must be the reviewed words (2026-11-25)
    drift = tts_drift(edl, game)
    if drift:
        raise SystemExit(f"tts differs from text in {', '.join(drift)}: change both (or rebuild the EDL), then narrate")
    import claims_check  # every footage claim checked against the footage before credits are spent (2026-11-23)
    claims_check.gate(game, edl)
    nar = edl.get("narrator")
    # Backup narrator (Bryce, 2026-11-23): auto is the default since he signed off the dry-run draft (2026-11-23);
    # elevenlabs stops when credits are short;
    # voxcpm2 forces the VoxCPM2 Guide C clone on Modal (tests); auto switches a whole video to it only
    # when credits are short and the video has no Guide C take yet, so a video never mixes voices.
    mode = (os.environ.get("KG_NARRATOR") or "auto").strip().lower()
    if mode not in ("elevenlabs", "voxcpm2", "auto"):
        raise SystemExit(f"KG_NARRATOR must be elevenlabs, voxcpm2 or auto, not {mode!r}")
    guide_c = bool(nar and nar.get("name") == "BOSS KG Guide C")
    if mode == "voxcpm2" and not guide_c:
        raise SystemExit("The VoxCPM2 backup clones BOSS KG Guide C only; this EDL uses another voice.")
    if mode == "auto" and not guide_c:
        mode = "elevenlabs"  # older voices (Narrator A, Chirp) have no backup: run as before
    out = ROOT / "output" / "analysis" / game / "narration"
    vox_out = vox_folder(game, out.parent / "narration-vox")
    narr = [b for b in edl["beats"] if b["type"] == "narr"]
    gc_timings = (json.loads((out / "timings.json").read_text(encoding="utf-8"))
                  if (out / "timings.json").exists() else {})
    # takes of THIS script only (hash match), so a cache restored from another video counts for nothing
    guide_c_takes = [b["id"] for b in narr if nar and (out / f"{b['id']}.wav").exists()
                     and gc_timings.get(b["id"], {}).get("hash") == el_take_hash(b, nar)]
    vox_takes = []
    if guide_c and (vox_out / "timings.json").exists():
        import voice_backup
        vt = json.loads((vox_out / "timings.json").read_text(encoding="utf-8"))
        vox_takes = [b["id"] for b in narr if (vox_out / f"{b['id']}.wav").exists()
                     and vt.get(b["id"], {}).get("hash") == voice_backup.take_hash(b)]
    backup, reason = False, ""
    if mode == "voxcpm2":
        backup, reason = True, "forced (narrator: voxcpm2)"
    elif mode == "auto" and not guide_c_takes and vox_takes:
        backup, reason = True, "this video was already voiced with the backup"  # sticky: one voice per video
    elif mode == "elevenlabs" and vox_takes and not guide_c_takes:
        raise SystemExit("This video was voiced with the VoxCPM2 backup. Run with narrator auto (keeps the "
                         "backup voice) or voxcpm2; to re-voice it with Guide C, delete its narration-vox "
                         "cache first. Nothing was recorded, so no credits were spent.")
    if backup and guide_c_takes:
        print(f"note: {len(guide_c_takes)} Guide C takes exist for this video; they are kept as they are",
              flush=True)
    if backup:
        return narrate_backup(game, edl, narr, nar, vox_out, reason)
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
        tag = ""  # the ElevenLabs take hash is el_take_hash()
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
    out.mkdir(parents=True, exist_ok=True)
    tpath = out / "timings.json"
    timings = gc_timings

    def said(b: dict) -> str:  # the text the model is sent (tags only for models that perform them)
        return b["tts"] if reads_tags(nar) else strip_tags(b["tts"])
    def take_hash(b: dict) -> str:  # "take": n on a beat re-rolls that paragraph alone (2026-11-18: the bosses
        # outro came out about 6 semitones above the paragraph before it; v4 takes vary, so a re-roll fixes it)
        if nar:
            return el_take_hash(b, nar)
        extra = f"|take{b['take']}" if b.get("take") else ""
        return hashlib.sha1(f"{tag}|{rate}|{said(b)}{extra}".encode()).hexdigest()[:12]
    words = 0
    todo = 0
    if nar:  # never start a video the month's ElevenLabs credits cannot finish (no half-voiced cuts)
        todo = 0
        for b in narr:
            h = take_hash(b)
            if not ((out / f"{b['id']}.wav").exists() and timings.get(b["id"], {}).get("hash") == h):
                todo += len(said(b))
        if todo:
            req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription",
                                         headers={"xi-api-key": key})
            with urllib.request.urlopen(req, timeout=60) as r:
                sub = json.loads(r.read())
            left = int(sub["character_limit"]) - int(sub["character_count"])
            print(f"ElevenLabs: {todo} characters to record, {left} credits left this month "
                  f"({sub.get('tier')})", flush=True)
            # Credits, not characters (2026-11-22): Eleven v4 on Starter measured about 0.4 credit per
            # character (Wolverine, the bosses video, the Guide C reel packs), so a character count
            # refused runs the balance could pay for. 0.5 keeps a safety margin.
            need = int(todo * 0.5) + 1
            if need > left and mode == "auto" and not guide_c_takes:
                on_b2 = guide_c_render_on_b2(game)
                if on_b2 is not False:
                    raise SystemExit(f"Not enough ElevenLabs credits (need about {need}, have {left}), and "
                                     + ("B2 already holds a Guide C draft of this video" if on_b2 else
                                        "B2 could not be checked for an earlier Guide C draft")
                                     + ", so the backup is not used (a video never mixes voices). Nothing was recorded.")
                return narrate_backup(game, edl, narr, nar, vox_out,
                                      f"ElevenLabs credits short: needed about {need}, had {left}")
            if need > left:
                if mode == "auto":
                    print(f"auto: not switching to the backup, because {len(guide_c_takes)} paragraphs "
                          f"already have Guide C takes (a video never mixes voices)", flush=True)
                raise SystemExit(f"Not enough ElevenLabs credits: need about {need} for {todo} characters, "
                                 f"have {left}. Nothing was recorded. Upgrade the plan or wait for the reset.")
            left_before = left
    for i, b in enumerate(narr):
        h = take_hash(b)
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
            raw.write_bytes(synth(strip_tags(b["tts"]), voice, rate, key))
        tempo = float(nar.get("tempo", 1.0)) if nar else 1.0
        pre = f"atempo={tempo}," if abs(tempo - 1) > 0.001 else ""  # v4 pace (2026-11-17)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", pre +
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
    if nar and nar.get("master"):
        master_takes(narr, out, timings, str(nar["master"]), float(nar.get("pace", 1.0)),
                     float(nar.get("tail_fade", 0.0)))
    tpath.write_text(json.dumps(timings, indent=1), encoding="utf-8")
    used_file(game).write_text(json.dumps({"dir": "narration", "voice": voice}), encoding="utf-8")
    if nar and todo:  # what this run really cost (about 0.4 credit per character on Starter)
        req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key})
        with urllib.request.urlopen(req, timeout=60) as r:
            sub = json.loads(r.read())
        left = int(sub["character_limit"]) - int(sub["character_count"])
        print(f"ElevenLabs: this run used {left_before - left} credits for {todo} characters; {left} left", flush=True)
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
    pace = f"tempo {nar['tempo']}" if nar and nar.get("tempo") else f"{'speed' if nar else 'rate'} {rate}"
    model = f" ({nar.get('model_id')})" if nar else ""
    report = (f"# Narration: {game}, {voice}{model} at {pace}\n\n"
              f"- {len(narr)} paragraphs, {words} words, {total:.0f} s of speech "
              f"({total / 60:.1f} min), {words / (total / 60):.0f} wpm\n")
    (out / "narration.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
