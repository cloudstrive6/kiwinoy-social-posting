"""Upload a large curated image set to a GitHub Release.

For image sets too big for the repo (e.g. thousands of FF7 screenshots). Uploads
assets/images/<bucket>/ to a release tagged '<bucket>-images'. Resumable: images
already on the release are skipped, so you can re-run if it's interrupted.

Usage:
  python tools/upload_images.py ff7
  python tools/upload_images.py ff7 --batch 80
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import CONFIG, ROOT  # noqa: E402

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _repo() -> str:
    repo = (CONFIG.reels.get("footage", {}) or {}).get("release_repo")
    if not repo:
        sys.exit("config reels.footage.release_repo is not set.")
    return repo


def _existing(tag: str, repo: str) -> set[str]:
    r = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo, "--json", "assets"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return set()  # release doesn't exist yet
    try:
        return {a["name"] for a in json.loads(r.stdout).get("assets", [])}
    except Exception:
        return set()


CAP = 1000  # GitHub hard limit: 1000 assets per release


def _tag(bucket: str, n: int) -> str:
    return f"{bucket}-images" if n == 1 else f"{bucket}-images-{n}"


def _ensure(tag: str, bucket: str, repo: str) -> None:
    if subprocess.run(["gh", "release", "view", tag, "--repo", repo],
                      capture_output=True).returncode != 0:
        print(f"Creating release '{tag}'...")
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repo,
             "-t", f"{bucket.upper()} images {tag.split('-')[-1] if tag[-1].isdigit() else ''}",
             "-n", f"Curated {bucket} image set for KiwinoyGamer posts."],
            check=True,
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bucket")
    ap.add_argument("--batch", type=int, default=80)
    args = ap.parse_args()

    repo = _repo()
    folder = ROOT / "assets" / "images" / args.bucket
    if not folder.exists():
        sys.exit(f"No folder: {folder}")

    # Everything already on ANY of the bucket releases (so re-runs are resumable).
    existing_all: set[str] = set()
    n = 1
    while True:
        ex = _existing(_tag(args.bucket, n), repo)
        if not ex and n > 1:
            break
        existing_all |= {name.replace(".", "%") if "%" not in name else name
                         for name in ex}
        existing_all |= ex  # match both transformed + raw names
        if n > 20:
            break
        n += 1

    files = [p for p in sorted(folder.iterdir())
             if p.suffix.lower() in IMG_EXTS
             and p.name not in existing_all
             and p.name.replace("%", ".") not in existing_all]
    print(f"{len(files)} to upload.")

    done = 0
    rel = 1
    while files and done < len(files):
        tag = _tag(args.bucket, rel)
        _ensure(tag, args.bucket, repo)
        room = CAP - len(_existing(tag, repo))
        if room <= 0:
            rel += 1
            continue
        chunk = files[done:done + room]
        for i in range(0, len(chunk), args.batch):
            batch = chunk[i:i + args.batch]
            r = subprocess.run(
                ["gh", "release", "upload", tag, *[str(p) for p in batch],
                 "--repo", repo, "--clobber"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"  FAILED ({tag}): {r.stderr[-300:]}")
            else:
                done += len(batch)
                print(f"  uploaded {done}/{len(files)} (-> {tag})", flush=True)
        rel += 1
    print("done.")


if __name__ == "__main__":
    main()
