"""Generate site/src/data/videos.json for the BOSS KG website's Videos page.

Pulls the channel's recent uploads (YouTube Data API), classifies each as a SHORT
(vertical 9:16) vs LONGFORM (16:9) via the /shorts/<id> redirect trick, and writes a
split JSON the Astro site reads at build time. Run locally or from a cron workflow
(refresh-videos.yml) with the YouTube creds already used by the reels tracks.

  python tools/site_videos.py            # writes site/src/data/videos.json
  python tools/site_videos.py --n 60     # scan more uploads
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests                       # noqa: E402
from core import youtube              # noqa: E402

UPLOADS = "UUeHnkTv_uA_dUgryYUPa-Dg"   # Boss KG uploads playlist (UU + channel id tail)
OUT = Path(__file__).resolve().parents[1] / "site" / "src" / "data" / "videos.json"
LONG_MAX, SHORT_MAX = 12, 18


def _uploads(n: int) -> list[dict]:
    yt = youtube._service()
    items, token = [], None
    while len(items) < n:
        r = yt.playlistItems().list(part="snippet,contentDetails", playlistId=UPLOADS,
                                    maxResults=min(50, n - len(items)), pageToken=token).execute()
        for it in r.get("items", []):
            sn = it["snippet"]
            vid = it["contentDetails"]["videoId"]
            items.append({"id": vid, "title": sn.get("title", ""),
                          "published": it["contentDetails"].get("videoPublishedAt")
                          or sn.get("publishedAt", "")})
        token = r.get("nextPageToken")
        if not token:
            break
    return items


_UA = {"User-Agent": "Mozilla/5.0"}


def _is_short(vid: str):
    """True if /shorts/<id> serves a Short (200); False if it redirects to /watch (long)."""
    try:
        r = requests.head(f"https://www.youtube.com/shorts/{vid}", allow_redirects=False,
                          timeout=12, headers=_UA)
        return r.status_code == 200
    except Exception:
        return None                    # unknown -> treat as longform (safer 16:9)


def _thumb_ready(vid: str) -> bool:
    """False if hqdefault is YouTube's tiny grey placeholder (video still processing / no
    thumbnail yet) — real thumbnails are ~15KB+, the placeholder is ~1.5KB."""
    try:
        r = requests.get(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", timeout=12, headers=_UA)
        return r.status_code == 200 and len(r.content) > 3000
    except Exception:
        return True                    # unknown -> keep it (fail open)


def _classify(v: dict) -> dict:
    return {**v, "is_short": _is_short(v["id"]), "ready": _thumb_ready(v["id"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()

    vids = _uploads(a.n)
    print(f"[site-videos] scanning {len(vids)} uploads ...", flush=True)
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        vids = list(ex.map(_classify, vids))
    skipped = sum(1 for v in vids if not v["ready"])

    longform, shorts = [], []
    for v in vids:
        if not v["ready"]:                      # still processing / no thumbnail -> skip
            continue
        rec = {"id": v["id"], "title": v["title"], "published": (v["published"] or "")[:10],
               "url": f"https://www.youtube.com/watch?v={v['id']}",
               "thumb": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg"}
        (shorts if v["is_short"] else longform).append(rec)

    data = {"longform": longform[:LONG_MAX], "shorts": shorts[:SHORT_MAX],
            "counts": {"longform": len(longform), "shorts": len(shorts)}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[site-videos] wrote {OUT.relative_to(OUT.parents[3])}: "
          f"{len(longform)} long, {len(shorts)} shorts ({skipped} skipped — not ready)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
