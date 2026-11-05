"""Official trailer tracker: which Marvel trailers are NEW and which are OLD.

A film or game gets many trailers (teaser, trailer 2, character trailers, TV spots, launch
trailer), and news sites keep writing about each one for days. The article date alone can't
tell us whether the trailer itself just dropped. The official YouTube upload date can.

Every trend run reads the public RSS feeds of the official channels (free, no API quota),
keeps the Marvel trailer-type uploads, and merges them into a history file on B2
(drafts/fb-trends/_trailers.json). Each feed only shows its latest 15 uploads, so the saved
history is what remembers older trailers. brief() turns it into a NEW / OLDER list that the
Trend Analyst and the novelty gate read: a trailer story is only news while the trailer is
fresh. No hand upkeep needed; add a channel to FEEDS if a new official source matters.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LEDGER_KEY = "drafts/fb-trends/_trailers.json"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; KiwinoyGamerTrends/1.0)"}
FRESH_DAYS = 3          # a trailer counts as NEW news for this many days after upload

# (display name, YouTube channel id, only keep Marvel titles?)
# Channel ids checked 2026-11-06. Note: the "@MarvelStudios" handle is NOT Marvel's channel.
FEEDS = [
    ("Marvel Entertainment", "UCvC4D8onUfXzvjTOM-dBfEA", False),
    ("Insomniac Games", "UCbBuGaZMd6bN1mxW886u1Gg", False),
    ("PlayStation", "UC-2Y8dQb0S6DtpxNgAKoJKA", True),
    ("Sony Pictures", "UCz97F7dMxBNOfGYu3rx8aCw", True),
]

# Marvel often titles trailers with no "trailer" in them, e.g. "Avengers: Doomsday | In
# Theaters December 18" (the 2026-10-25 trailer) or "Special Look".
TRAILER_RE = re.compile(r"trailer|teaser|\bspot\b|first look|special look|sneak peek|"
                        r"preview|official clip|footage|\bpromo\b|reveal|gameplay|"
                        r"release date|announce|in theaters|in cinemas", re.I)
SKIP_RE = re.compile(r"podcast|#|full episode|compilation|react|explains|livestream|"
                     r"\blive\b|soundtrack|audio only", re.I)
MARVEL_RE = re.compile(r"marvel|spider-?man|wolverine|venom|x-?men|avengers|doomsday|"
                       r"insomniac|marvel's blade|fantastic four|deadpool|daredevil|thunderbolts|"
                       r"black panther|iron man|captain america|thor\b|hulk|loki|"
                       r"visionquest|wonder man|ironheart|midnight sons|ghost rider", re.I)


def _feed_url(cid: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"


def _unescape(s: str) -> str:
    import html
    return html.unescape(s or "").strip()


def _keep(channel: str, need_marvel: bool, vid: str, title: str, published: str):
    """Trailer-type upload worth tracking, or None. On the non-Marvel channels any Marvel
    title counts (Sony names Spider-Man trailers creatively, e.g. 'The World Is Grey')."""
    if not vid or SKIP_RE.search(title):
        return None
    if need_marvel:
        if not MARVEL_RE.search(title):
            return None
    elif not TRAILER_RE.search(title):
        return None
    return {"id": vid, "title": title, "channel": channel, "published": published}


def fetch() -> list[dict]:
    """Current Marvel trailer-type uploads from the official feeds. Fail-open per feed."""
    import requests
    out: list[dict] = []
    for name, cid, need_marvel in FEEDS:
        try:
            r = requests.get(_feed_url(cid), headers=_UA, timeout=15)
            if r.status_code != 200:
                continue
            for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
                vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", e)
                title = re.search(r"<title>(.*?)</title>", e, re.S)
                pub = re.search(r"<published>(.*?)</published>", e)
                if not (vid and title and pub):
                    continue
                rec = _keep(name, need_marvel, vid.group(1), _unescape(title.group(1)),
                            pub.group(1)[:10])
                if rec:
                    out.append(rec)
        except Exception as ex:
            print(f"[trailers] {name} feed skipped ({ex!r}).", flush=True)
    return out


def _rclone():
    from core.config import CONFIG
    from core import b2_store
    from tools.footage import _b2_env
    la = CONFIG.raw().get("longform_archive", {}) or {}
    remote = str(la.get("remote", "kgb2"))
    return _b2_env(remote), f"{remote}:{b2_store._bucket()}/{_LEDGER_KEY}"


def load() -> list[dict]:
    try:
        env, path = _rclone()
        r = subprocess.run(["rclone", "cat", path], env=env, capture_output=True,
                           encoding="utf-8", timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            return [x for x in data if isinstance(x, dict) and x.get("id")]
    except Exception as ex:
        print(f"[trailers] history read skipped ({ex!r}).", flush=True)
    return []


def save(recs: list[dict]) -> None:
    try:
        env, path = _rclone()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_trailers.json"
            p.write_text(json.dumps(recs[-500:], ensure_ascii=False), encoding="utf-8")
            subprocess.run(["rclone", "copyto", str(p), path], env=env,
                           capture_output=True, timeout=60)
    except Exception as ex:
        print(f"[trailers] history write skipped ({ex!r}).", flush=True)


def update(*, persist: bool = True) -> list[dict]:
    """Merge the live feeds into the saved history (keyed by video id, first upload date
    wins), save it, and return it oldest first."""
    hist = load()
    known = {r["id"] for r in hist}
    new = [t for t in fetch() if t["id"] not in known]
    if new:
        hist.extend(new)
        hist.sort(key=lambda r: r.get("published", ""))
        if persist:
            save(hist)
    print(f"[trailers] {len(hist)} official trailers tracked ({len(new)} new this run).",
          flush=True)
    return hist


def brief(recs: list[dict], *, fresh_days: int = FRESH_DAYS, older_limit: int = 60) -> str:
    """NEW / OLDER trailer block for the analyst and novelty-gate prompts."""
    if not recs:
        return ""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=fresh_days)).strftime("%Y-%m-%d")
    newest_first = sorted(recs, key=lambda r: r.get("published", ""), reverse=True)
    fresh = [r for r in newest_first if r.get("published", "") >= cutoff]
    older = [r for r in newest_first if r.get("published", "") < cutoff][:older_limit]
    line = lambda r: f"- {r['published']} · {r['title']} ({r['channel']})"
    parts = [
        "OFFICIAL TRAILERS, with their YouTube upload dates. RULE: a story about a trailer, "
        f"teaser, TV spot or clip is NEW only if that trailer was uploaded in the last "
        f"{fresh_days} days (NEW list) and we have not posted it. A story about a trailer in "
        "the OLDER list is OLD news, even if the article is from today (reactions, breakdowns, "
        "'fans spot' pieces), unless it reveals something genuinely new. A trailer story whose "
        "trailer is in neither list: judge by the posted list and the article age."]
    parts.append("NEW TRAILERS:\n" + ("\n".join(map(line, fresh)) if fresh else "(none)"))
    if older:
        parts.append("OLDER TRAILERS (already out):\n" + "\n".join(map(line, older)))
    return "\n".join(parts)


def backfill(max_per_channel: int = 400) -> int:
    """One-off: page through each channel's full uploads list with the YouTube Data API
    (playlistItems, 1 quota unit per 50 videos) so trailers older than the RSS window are
    known too. Run by hand: py -c "from core import trailer_watch as t; t.backfill()"."""
    from core.youtube import _service
    yt = _service()
    hist = load()
    known = {r["id"] for r in hist}
    added = 0
    for name, cid, need_marvel in FEEDS:
        token, seen = None, 0
        while seen < max_per_channel:
            resp = yt.playlistItems().list(part="snippet", playlistId="UU" + cid[2:],
                                           maxResults=50, pageToken=token).execute()
            for it in resp.get("items", []):
                sn = it.get("snippet", {})
                vid = (sn.get("resourceId") or {}).get("videoId", "")
                rec = _keep(name, need_marvel, vid, sn.get("title", ""),
                            str(sn.get("publishedAt", ""))[:10])
                if rec and vid not in known:
                    hist.append(rec)
                    known.add(vid)
                    added += 1
            seen += len(resp.get("items", []))
            token = resp.get("nextPageToken")
            if not token:
                break
    hist.sort(key=lambda r: r.get("published", ""))
    save(hist)
    print(f"[trailers] backfill added {added}; {len(hist)} tracked.", flush=True)
    return added
