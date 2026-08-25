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
import re
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
CHANNEL_ID = "UCeHnkTv_uA_dUgryYUPa-Dg"
OUT = Path(__file__).resolve().parents[1] / "site" / "src" / "data" / "videos.json"
LONG_MAX, SHORT_MAX = 24, 300   # generous — the per-game pages need every game's videos;
#                                 the Videos landing slices to a display count of its own.


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


def _playlist_map() -> tuple[dict[str, list[str]], dict[str, dict]]:
    """Returns (pmap, meta):
      pmap  = videoId -> [playlist titles it belongs to]
      meta  = videoId -> {"title", "published"}  (so playlist videos OLDER than the recent
              uploads scan can still be pulled into the site's list).
    The site files each video into a game by its GAME PLAYLIST (authoritative, matched via
    lib/games.js), falling back to the video title — so clean per-game playlists on YouTube
    = correct, complete filing on the site regardless of how old the upload is."""
    yt = youtube._service()
    pls: list[tuple[str, str]] = []
    token = None
    while True:
        r = yt.playlists().list(part="snippet", channelId=CHANNEL_ID,
                                maxResults=50, pageToken=token).execute()
        pls += [(p["id"], p["snippet"]["title"]) for p in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    out: dict[str, list[str]] = {}
    meta: dict[str, dict] = {}
    for pid, ptitle in pls:
        tok = None
        while True:
            r = yt.playlistItems().list(part="snippet,contentDetails", playlistId=pid,
                                        maxResults=50, pageToken=tok).execute()
            for it in r.get("items", []):
                cd, sn = it.get("contentDetails", {}), it.get("snippet", {})
                vid = cd.get("videoId")
                if not vid:
                    continue
                out.setdefault(vid, []).append(ptitle)
                meta.setdefault(vid, {"title": sn.get("title", ""),
                                      "published": cd.get("videoPublishedAt")
                                      or sn.get("publishedAt", "")})
            tok = r.get("nextPageToken")
            if not tok:
                break
    print(f"[site-videos] mapped {len(pls)} playlists -> {len(out)} videos", flush=True)
    return out, meta


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


BLURBS = Path(__file__).resolve().parents[1] / "site" / "src" / "data" / "video_blurbs.json"


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:70].strip("-") or "video"


def _load_blurbs() -> dict:
    try:
        return json.loads(BLURBS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gen_blurb(title: str) -> str:
    """LLM SEO blurb for a long-form video; template fallback if no LLM is available."""
    prompt = (
        "Write a concise, engaging, SEO-friendly description (2 short paragraphs, ~70-100 words "
        "total) for a YouTube gameplay video by the channel Boss KG. The video is no-commentary "
        "gameplay, usually in 4K 60fps HDR. Describe what viewers will see and why it's worth "
        f"watching. Video title: \"{title}\". Be accurate to what the title implies; do NOT invent "
        "specific plot points you're unsure of. No hashtags, no emojis, no markdown.")
    try:
        from agents.content import _text
        t = (_text(prompt, timeout=90) or "").strip()
        if t and len(t) > 60 and "placeholder" not in t.lower():
            return t
    except Exception as e:
        print(f"[site-videos] blurb LLM failed ({e!r}) — using template.", flush=True)
    return (f"{title} — the full playthrough from Boss KG in 4K 60fps HDR, no commentary. "
            "Settle in and watch every moment in crisp detail, exactly as it happened.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--blurbs", action="store_true",
                    help="generate LLM SEO blurbs for long-form videos (run locally; needs LLM keys)")
    a = ap.parse_args()

    vids = _uploads(a.n)

    try:
        pmap, pmeta = _playlist_map()           # videoId -> [playlist titles] (game filing)
    except Exception as e:
        print(f"[site-videos] playlist map failed ({e!r}) — filing by title only.", flush=True)
        pmap, pmeta = {}, {}

    # Union: recent uploads + every playlist member (so a game's OLDER videos, which fall
    # outside the recent-uploads window, still appear on that game's page).
    have = {v["id"] for v in vids}
    for vid, m in pmeta.items():
        if vid not in have:
            vids.append({"id": vid, "title": m["title"], "published": m["published"]})
            have.add(vid)

    print(f"[site-videos] scanning {len(vids)} videos (uploads + playlists) ...", flush=True)
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
        pls = pmap.get(v["id"])
        if pls:
            rec["playlists"] = pls
        (shorts if v["is_short"] else longform).append(rec)

    longform.sort(key=lambda r: r.get("published") or "", reverse=True)
    shorts.sort(key=lambda r: r.get("published") or "", reverse=True)
    n_long, n_short = len(longform), len(shorts)
    # long-form videos each get their own SEO page (/watch/<slug>): stable slug + cached blurb
    longform = longform[:LONG_MAX]
    blurbs = _load_blurbs()
    seen = set()
    for rec in longform:
        base = _slug(rec["title"]); slug = base; i = 2
        while slug in seen:
            slug = f"{base}-{i}"; i += 1
        seen.add(slug); rec["slug"] = slug
        if a.blurbs and rec["id"] not in blurbs:
            blurbs[rec["id"]] = _gen_blurb(rec["title"])
            print(f"  blurb generated: {rec['title'][:48]}", flush=True)
        rec["blurb"] = blurbs.get(rec["id"], "")
    if a.blurbs:
        BLURBS.parent.mkdir(parents=True, exist_ok=True)
        BLURBS.write_text(json.dumps(blurbs, ensure_ascii=False, indent=2), encoding="utf-8")

    data = {"longform": longform, "shorts": shorts[:SHORT_MAX],
            "counts": {"longform": n_long, "shorts": n_short}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[site-videos] wrote {OUT.relative_to(OUT.parents[3])}: "
          f"{len(longform)} long, {len(shorts)} shorts ({skipped} skipped — not ready)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
