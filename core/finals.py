"""Finals archive: a permanent B2 copy of every video that goes out (2026-11-24).

Bryce, 2026-11-24: "for all the final/approved renders/versions of the video, be sure to save a copy in B2
Backblaze as we might be able to use them in the future".

Scope (Bryce, same day): "I just meant the long form ones". So this keeps the long-form voiceover
(analysis) videos that go out, not Shorts, reels or fact cards.

Layout: finals/longform/<YYYY-MM-DD>_<slug>_<sha8>.mp4 plus a .json sidecar (title, YouTube id, render key,
note). The same bytes are never stored twice (the sha1 prefix is checked first).

Automatic: core/youtube.upload_video calls save_longform_upload() for any file named
<slug>-analysis-v<N>[-vox].mp4, which copies renders/analysis/<slug>/<file> server side (no re-upload).
By hand: python -m core.finals --b2-key renders/analysis/<slug>/<file> --note "public since ...".
Nothing ever deletes under finals/ (b2_store.delete_file refuses it). Every call fails open: a backup
problem never blocks an upload. Off switch: config `finals.enabled: false`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Optional, Union

PREFIX = "finals/"


def _enabled() -> bool:
    try:
        from core.config import CONFIG
        return bool((getattr(CONFIG, "_data", None) or {}).get("finals", {}).get("enabled", True))
    except Exception:
        return True


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "video").lower()).strip("-")
    return (s or "video")[:60].rstrip("-")


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def already_saved(sha: str) -> Optional[str]:
    """The finals/ key that already holds these bytes, or None."""
    from core import b2_store
    tag = f"_{sha[:8]}."
    for f in b2_store._list_names(PREFIX):
        n = f.get("fileName", "")
        if tag in n and not n.endswith(".json"):
            return n
    return None


def save(video: Union[str, Path, bytes, None], kind: str, title: str = "", *, b2_key: str = "",
         meta: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Keep a permanent copy of one final video. `video` is a local path or the bytes; or pass
    b2_key= (a video already on B2) for a server-side copy. Returns the finals/ key, or None."""
    if not _enabled():
        return None
    try:
        from core import b2_store
        if not b2_store.enabled():
            return None
        tmp = None
        if isinstance(video, (bytes, bytearray)):
            tmp = Path(tempfile.mkdtemp()) / "final.mp4"
            tmp.write_bytes(video)
            path: Optional[Path] = tmp
        else:
            path = Path(video) if video else None
        try:
            if path is not None:
                if not path.is_file():
                    return None
                sha = _sha1_file(path)
            else:
                info = next((f for f in b2_store._list_names(b2_key) if f.get("fileName") == b2_key), None)
                if not info:
                    return None
                # Big rclone uploads have contentSha1 "none"; use their large_file_sha1, else a
                # fingerprint of key, size and file id (2026-11-24: "none" made every big file look kept).
                sha = (info.get("contentSha1") or "").replace("unverified:", "")
                if not re.fullmatch(r"[0-9a-f]{40}", sha):
                    sha = ((info.get("fileInfo") or {}).get("large_file_sha1") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{40}", sha):
                    sha = hashlib.sha1(f"{b2_key}:{info.get('contentLength')}:{info.get('fileId')}".encode()).hexdigest()
            have = already_saved(sha)
            if have:
                print(f"[finals] already kept as {have}", flush=True)
                return have
            day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
            ext = (Path(b2_key).suffix if b2_key else path.suffix) or ".mp4"
            key = f"{PREFIX}{_slug(kind)}/{day}_{_slug(title)}_{sha[:8]}{ext}"
            ok = b2_store.copy_file(b2_key, key) if path is None else b2_store.put_file(key, path)
            if not ok:
                print(f"[finals] could not save {key}", flush=True)
                return None
            side = {"title": title, "kind": kind, "sha1": sha, "saved": day,
                    "source": b2_key or (path.name if path else ""), **(meta or {})}
            b2_store.put_bytes(key.rsplit(".", 1)[0] + ".json", json.dumps(side, indent=1, default=str).encode())
            print(f"[finals] kept {key}", flush=True)
            return key
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                    tmp.parent.rmdir()
                except OSError:
                    pass
    except Exception as e:  # never block a post over the backup
        print(f"[finals] skipped ({e!r})"[:300], flush=True)
        return None


LONGFORM_RE = re.compile(r"^(?P<slug>.+)-analysis-v\d+(?:-vox)?\.mp4$")


def save_longform_upload(path, title: str, video_id: str = "", privacy: str = "") -> Optional[str]:
    """Called after a YouTube upload. Keeps the file only when it is a long-form analysis render."""
    name = Path(str(path)).name if path else ""
    m = LONGFORM_RE.match(name)
    if not m:
        return None
    from core import b2_store
    key = f"renders/analysis/{m.group('slug')}/{name}"
    meta = {"youtube_id": video_id, "privacy_at_upload": privacy, "render_key": key}
    if b2_store.file_id_of(key):
        return save(None, "longform", title or Path(name).stem, b2_key=key, meta=meta)
    return save(path, "longform", title or Path(name).stem, meta=meta)


def main() -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Keep a final video on B2 (finals/), or list what is kept.")
    ap.add_argument("--b2-key", action="append", default=[], help="a video already on B2 (server-side copy)")
    ap.add_argument("--file", default="", help="a local video file")
    ap.add_argument("--kind", default="longform")
    ap.add_argument("--title", default="")
    ap.add_argument("--note", default="", help="stored in the sidecar, e.g. 'public since 2026-11-15'")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    from core import b2_store
    if a.list:
        rows = [f for f in b2_store._list_names(PREFIX) if not f["fileName"].endswith(".json")]
        for f in rows:
            print(f"{int(f.get('contentLength') or 0) / 1e6:9.1f} MB  {f['fileName']}")
        print(f"{len(rows)} finals, {sum(int(f.get('contentLength') or 0) for f in rows) / 1e9:.2f} GB")
        return 0
    bad = 0
    for k in a.b2_key:
        bad += save(None, a.kind, a.title or Path(k).stem, b2_key=k, meta={"note": a.note}) is None
    if a.file:
        bad += save(a.file, a.kind, a.title or Path(a.file).stem, meta={"note": a.note}) is None
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
