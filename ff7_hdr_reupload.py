"""FF7 Remake HDR RE-UPLOAD — one of the 3 full-game parts (argv: 1 | 2 | 3).

The original 3 uploads went out as SDR because the source is FULL-range PQ with no mastering
metadata (YouTube ingests that as SDR). This job re-does them as canonical HDR10 via the NVENC
path (config youtube_longform.stream_copy:false + encoder:nvenc — auto-converts full->limited
range). It: keeps the PC awake, downloads the group's source parts from B2, concat + NVENC-HDR
re-encode + upload (PUBLIC), Telegrams status, frees the local temp on success, and reminds you
to delete the OLD SDR video once the new HDR one is confirmed.

Run one part at a time (disk + one-encode-at-a-time). The ENCODE stage is GPU-heavy (NVENC) —
don't stream while it's encoding. Launch detached via run_ff7_hdr_reupload.bat <N>.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

REPO = Path(r"Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting")
os.chdir(REPO)
sys.path.insert(0, str(REPO))

from core.config import CONFIG          # noqa: E402
from core import b2_store, notify       # noqa: E402
from tools.footage import _b2_env       # noqa: E402
import orchestrator as orch             # noqa: E402

# game-parts per YouTube part (part 13 is CORRUPT — skipped everywhere), + title/thumb/old id
_T = "FINAL FANTASY VII REMAKE Full Game HARD DIFFICULTY Walkthrough Part {n} [4K 60FPS HDR] No Commentary"
_D = ("Final Fantasy VII Remake full game walkthrough on HARD difficulty — Part {n}. "
      "4K 60fps HDR10, no commentary.")
GROUPS = {
    1: {"parts": [1, 2, 3, 4, 5, 6, 7, 8, 9],           "chars": ["cloud"],
        "old": "7Wib5mON-WA"},
    2: {"parts": [10, 11, 12, 14, 15, 16, 17],          "chars": ["aerith", "tifa"],
        "old": "EJBnLli6_V0"},
    3: {"parts": [18, 19, 20, 21, 22, 23, 24],          "chars": ["barret", "cloud", "aerith", "tifa", "red xiii"],
        "old": "Cb-BDK4ZAeo"},
}
DEST = REPO / "reels" / "assets" / "longform-fullgame" / "final-fantasy-7-remake"
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def _awake(on=True):
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED if on else ES_CONTINUOUS)
    except Exception:
        pass


def main() -> int:
    try:
        n = int(sys.argv[1])
        g = GROUPS[n]
    except (IndexError, ValueError, KeyError):
        print("usage: python ff7_hdr_reupload.py <1|2|3>", flush=True)
        return 2

    _awake(True)
    parts = g["parts"]
    notify.telegram(f"🎬 FF7R Part {n} HDR re-upload STARTED. Downloading {len(parts)} source "
                    "parts from B2 → NVENC HDR10 encode → upload (~a day). GPU-heavy while it "
                    "encodes — hold off streaming. I'll ping you when it's live.")
    DEST.mkdir(parents=True, exist_ok=True)
    remote = str((CONFIG.raw().get("longform_archive", {}) or {}).get("remote", "kgb2"))
    bucket = b2_store._bucket()

    # 1) download this group's parts from B2 (exact filenames so 'Part 2' != 'Part 20')
    inc = []
    for p in parts:
        inc += ["--include", f"Final Fantasy VII Remake - Part {p}.mp4"]
    print(f"[ff7-p{n}] downloading parts {parts} from B2 ...", flush=True)
    rc = subprocess.run(
        ["rclone", "copy", f"{remote}:{bucket}/final-fantasy-7-remake", str(DEST),
         "--transfers", "4", "--b2-chunk-size", "100M", "-v", "--stats", "120s",
         "--stats-one-line"] + inc, env=_b2_env(remote)).returncode
    files = [DEST / f"Final Fantasy VII Remake - Part {p}.mp4" for p in parts]
    missing = [f.name for f in files if not f.exists()]
    if rc != 0 or missing:
        notify.telegram(f"⚠️ FF7R Part {n} ABORTED: B2 download failed (rc={rc}, missing="
                        f"{len(missing)}). Source is safe on B2 — re-run when ready.")
        _awake(False)
        return 1

    # 2) concat + NVENC HDR10 re-encode + upload PUBLIC
    print(f"[ff7-p{n}] downloaded {len(files)} parts. NVENC HDR encode + upload ...", flush=True)
    _awake(True)
    ok, url = False, "(check YouTube Studio)"
    try:
        res = orch.run_youtube_longform(
            [str(f) for f in files], game="ff7remake",
            title=_T.format(n=n), description=_D.format(n=n),
            thumb_text=f"PART {n}", thumb_characters=g["chars"], privacy="public")
        url = (res or {}).get("url") or url
        ok = True
        notify.telegram(f"✅ FF7R Part {n} HDR re-upload DONE — public once YouTube processes.\n{url}\n"
                        f"Give it a day, confirm the HDR quality option shows, then DELETE the old "
                        f"SDR one: https://youtu.be/{g['old']}\nCleaning up local temp now.")
    except Exception as e:
        traceback.print_exc()
        notify.telegram(f"⚠️ FF7R Part {n} upload ERROR: {e!r}\nDownloaded parts kept for a quick "
                        "retry. Source is also safe on B2.")

    # 3) cleanup on SUCCESS (parts + concat are redundant — parts live on B2)
    if ok:
        for f in files:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        for d in REPO.glob("output/*_youtube_longform"):
            shutil.rmtree(d, ignore_errors=True)
    _awake(False)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
