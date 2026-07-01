"""Convert 4K/60 HDR gameplay clips -> 1080p CFR60 SDR H.264 reel footage.

Record once in 4K/60 HDR, use it for BOTH the YouTube long-form (HDR, untouched)
AND the reels (this tool). The key step is HDR10 (Rec.2020 PQ) / HLG -> SDR
(Rec.709) TONE-MAPPING: skip it and the footage looks washed-out/grey on phones
(IG/FB/Threads/YouTube reels are SDR). It also downscales 4K->1080p (a quality WIN
— 1080p from 4K supersamples crisper than native 1080p) and forces CFR 60. Output
lands in reels/assets/footage/<game>/, so the normal reel pipeline
(classic/triptych/rotated) picks it up.

Runs on YOUR machine (HDR source is multi-GB; not in CI). Tone-mapping 4K is
CPU-heavy — expect a while per long clip; --segment turns a long part into several
short reel clips (better for the reel picker AND under GitHub's 2GB/file cap).

Usage:
  python tools/hdr_to_reel.py <src> <game>                 # convert a file, or every clip in a folder
  python tools/hdr_to_reel.py <src> <game> --segment 90    # also split into ~90s reel clips
  python tools/hdr_to_reel.py <src> <game> --upload         # push results to the footage Release (CI reels)
  python tools/hdr_to_reel.py <src> <game> --mute           # drop audio (reels add their own VO/music)
  python tools/hdr_to_reel.py <src> <game> --sdr            # source is already SDR: just downscale+CFR
  python tools/hdr_to_reel.py <src> <game> --crf 20 --out D:/x

<game> = the footage subfolder key (halo, spider-man1, thelastofus2, ff7, ...).
See config reels.footage.map / reels.game_names.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ffmpeg  # noqa: E402
from core.config import CONFIG, ROOT  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".ts"}
RELEASE_MAX_GB = 2.0

# Downscale FIRST (in the source HDR space — fast) then linearize + Hable tone-map +
# convert to Rec.709 SDR. Same tone-map the thumbnails use, proven in this ffmpeg.
_HDR_TONEMAP = (
    "zscale=w=1920:h=1080:filter=lanczos,"
    "zscale=t=linear:npl=100,tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p"
)
_SDR_DOWNSCALE = "scale=1920:1080:flags=lanczos,format=yuv420p"


def _is_hdr(path: Path) -> bool:
    """True if the video's transfer curve is PQ (smpte2084) or HLG (arib-std-b67)."""
    fp = ffmpeg.ffprobe_bin()
    if not fp:
        return False
    try:
        out = subprocess.run(
            [fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=color_transfer,color_primaries", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60)
        s = (out.stdout or "").lower()
        return "smpte2084" in s or "arib-std-b67" in s
    except Exception:
        return False


def _inputs(src: Path) -> list[Path]:
    if src.is_dir():
        return sorted(p for p in src.iterdir()
                      if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    if src.is_file():
        return [src]
    sys.exit(f"not found: {src}")


def _convert(src: Path, out_dir: Path, *, hdr: bool, segment: float,
             crf: int, mute: bool, timeout: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    vf = _HDR_TONEMAP if hdr else _SDR_DOWNSCALE
    keep_audio = (not mute) and ffmpeg.has_audio(src)
    args = ["-i", str(src), "-vf", vf, "-r", "60", "-fps_mode", "cfr",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    args += (["-c:a", "aac", "-b:a", "160k", "-ar", "48000"] if keep_audio else ["-an"])
    stem = src.stem
    if segment > 0:
        pattern = str(out_dir / f"{stem}_%03d.mp4")
        args += ["-f", "segment", "-segment_time", f"{segment:g}",
                 "-reset_timestamps", "1", "-segment_start_number", "1", pattern]
    else:
        args += ["-movflags", "+faststart", str(out_dir / f"{stem}.mp4")]
    print(f"  [{'HDR->SDR' if hdr else 'SDR'}] {src.name}"
          + (f"  (split ~{segment:g}s)" if segment > 0 else "") + " ...", flush=True)
    rc, err = ffmpeg.run(args, timeout=timeout)
    if rc != 0:
        print(f"    FAILED: {err[-400:]}", flush=True)
        return []
    if segment > 0:
        made = sorted(out_dir.glob(f"{stem}_[0-9][0-9][0-9].mp4"))
    else:
        made = [out_dir / f"{stem}.mp4"]
        made = [m for m in made if m.exists()]
    for m in made:
        gb = m.stat().st_size / 1024 ** 3
        flag = "  ⚠ >2GB (Release won't take it — use --segment)" if gb > RELEASE_MAX_GB else ""
        print(f"    -> {m.name}  ({gb * 1024:.0f} MB){flag}", flush=True)
    return made


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    src = Path(argv[0])
    game = argv[1]
    opt = argv[2:]

    def _val(flag, default):
        return opt[opt.index(flag) + 1] if flag in opt and opt.index(flag) + 1 < len(opt) else default

    segment = float(_val("--segment", 0) or 0)
    crf = int(_val("--crf", 18))
    mute = "--mute" in opt
    force_sdr = "--sdr" in opt
    do_upload = "--upload" in opt
    timeout = int(_val("--timeout", 14400))  # 4h headroom for long 4K tone-maps
    out_dir = Path(_val("--out", "")) if "--out" in opt else \
        ROOT / (CONFIG.reels.get("footage", {}).get("dir", "reels/assets/footage")) / game

    files = _inputs(src)
    if not files:
        sys.exit(f"no video files in {src}")
    print(f"Converting {len(files)} file(s) -> {out_dir}", flush=True)
    made: list[Path] = []
    for f in files:
        hdr = (not force_sdr) and _is_hdr(f)
        made += _convert(f, out_dir, hdr=hdr, segment=segment, crf=crf,
                         mute=mute, timeout=timeout)
    print(f"\nDone: {len(made)} reel clip(s) in {out_dir}", flush=True)

    if do_upload and made:
        small = [m for m in made if m.stat().st_size / 1024 ** 3 <= RELEASE_MAX_GB]
        skipped = len(made) - len(small)
        if skipped:
            print(f"(skipping {skipped} clip(s) over 2GB — re-run with --segment)", flush=True)
        if small:
            print(f"Uploading {len(small)} clip(s) to the footage Release...", flush=True)
            from tools import footage
            footage.upload(game, [str(m) for m in small])
    elif made:
        print("Next: push these to the footage Release for the CI reels:", flush=True)
        print(f"  python tools/footage.py sync {game}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
