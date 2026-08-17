"""Upload an ALREADY-ENCODED FF7R part (argv: 1|2|3) — no re-encode.

Used when the NVENC HDR encode succeeded but the UPLOAD died (e.g. an Avast reset on the
token endpoint). Finds the cached output/*_youtube_longform/fullgame.mp4, uploads it PUBLIC
with the token-refresh retry now in core.youtube, sets the approved OLD thumbnail, cleans up
on success, and Telegrams status. Keeps the PC awake. Launch detached via
run_ff7_upload_existing.bat <N>.
"""
import ctypes
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(r"Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting")
os.chdir(REPO)
sys.path.insert(0, str(REPO))
try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests                              # noqa: E402
from core import youtube, notify            # noqa: E402
from ff7_hdr_reupload import GROUPS, DEST    # reuse part -> parts/old-id mapping  # noqa: E402

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def main() -> int:
    try:
        n = int(sys.argv[1]); g = GROUPS[n]
    except (IndexError, ValueError, KeyError):
        print("usage: python ff7_upload_existing.py <1|2|3>", flush=True)
        return 2

    mp4s = sorted(REPO.glob("output/*_youtube_longform/fullgame.mp4"),
                  key=lambda p: p.stat().st_size, reverse=True)
    if not mp4s:
        notify.telegram(f"⚠️ FF7R Part {n}: no cached encode found — run the full re-upload instead.")
        return 1
    mp4 = mp4s[0]
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

    # approved OLD thumbnail (avoids the pipeline's regenerated one)
    thumb = None
    try:
        yt = youtube._service()
        it = yt.videos().list(part="snippet", id=g["old"]).execute()["items"][0]
        th = it["snippet"]["thumbnails"]
        u = (th.get("maxres") or th.get("standard") or th.get("high"))["url"]
        thumb = Path(tempfile.gettempdir()) / f"ff7_old_{g['old']}.jpg"
        thumb.write_bytes(requests.get(u, timeout=30).content)
    except Exception as e:
        print(f"[ff7] old-thumb fetch failed ({e!r})", flush=True)

    title = (f"FINAL FANTASY VII REMAKE Full Game HARD DIFFICULTY Walkthrough Part {n} "
             "[4K 60FPS HDR] No Commentary")
    desc = (f"Final Fantasy VII Remake full game walkthrough on HARD difficulty — Part {n}. "
            "4K 60fps HDR10, no commentary.")
    notify.telegram(f"🎬 FF7R Part {n} — uploading the ALREADY-ENCODED file (no re-encode) with "
                    "the token-refresh fix. ~a day. I'll ping when it's live.")
    ok = False
    try:
        res = youtube.upload_video(
            str(mp4), title=title, description=desc,
            tags=["gaming", "walkthrough", "playthrough", "4K", "HDR", "60fps",
                  "final fantasy vii remake"],
            privacy="public", thumbnail=str(thumb) if thumb else None)
        vid = (res or {}).get("id", "")
        ok = True
        notify.telegram(f"✅ FF7R Part {n} HDR DONE (from cached encode).\nhttps://youtu.be/{vid}\n"
                        f"Confirm the HDR option shows, then delete the old SDR: "
                        f"https://youtu.be/{g['old']}")
    except Exception as e:
        traceback.print_exc()
        notify.telegram(f"⚠️ FF7R Part {n} upload ERROR: {e!r}\nEncoded file kept for another retry.")

    if ok:
        for p in g["parts"]:
            (DEST / f"Final Fantasy VII Remake - Part {p}.mp4").unlink(missing_ok=True)
        shutil.rmtree(mp4.parent, ignore_errors=True)
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
