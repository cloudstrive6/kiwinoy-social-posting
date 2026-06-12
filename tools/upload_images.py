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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bucket")
    ap.add_argument("--batch", type=int, default=80)
    args = ap.parse_args()

    repo = _repo()
    tag = f"{args.bucket}-images"
    folder = ROOT / "assets" / "images" / args.bucket
    if not folder.exists():
        sys.exit(f"No folder: {folder}")

    # Create the release if it doesn't exist.
    if subprocess.run(["gh", "release", "view", tag, "--repo", repo],
                      capture_output=True).returncode != 0:
        print(f"Creating release '{tag}'...")
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repo,
             "-t", f"{args.bucket.upper()} images",
             "-n", f"Curated {args.bucket} image set for KiwinoyGamer posts."],
            check=True,
        )

    existing = _existing(tag, repo)
    files = [p for p in sorted(folder.iterdir())
             if p.suffix.lower() in IMG_EXTS and p.name not in existing]
    print(f"{len(files)} to upload ({len(existing)} already on the release).")

    done = 0
    for i in range(0, len(files), args.batch):
        batch = files[i:i + args.batch]
        r = subprocess.run(
            ["gh", "release", "upload", tag, *[str(p) for p in batch],
             "--repo", repo, "--clobber"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  batch {i // args.batch + 1} FAILED: {r.stderr[-300:]}")
        else:
            done += len(batch)
            print(f"  uploaded {done}/{len(files)}", flush=True)
    print("done.")


if __name__ == "__main__":
    main()
