"""Runner for the KG Facebook trend-jacking pipeline — delivers to FB DRAFTS.

Scout rising gaming trends -> Trend Analyst ranks them (prefers RISING/pre-peak) ->
Post Director writes an FB caption + builds a screened "trend card" -> deliver as a
DRAFT: the card + caption go to Telegram (review at a glance) and the image is stored
on B2 under drafts/fb-trends/. NOTHING is posted publicly — you review + post. A small
posted-topics ledger on B2 stops repeats.

Usage:
  python tools/trend_post.py                 # up to 1 fresh trend draft
  python tools/trend_post.py --count 2       # up to N drafts
  python tools/trend_post.py --dry-run       # scout+analyze+build only (no B2/Telegram)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:                                            # emoji captions vs Windows cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.config import CONFIG, ROOT          # noqa: E402
from core import b2_store, notify             # noqa: E402
from agents import trends, post_director as pd  # noqa: E402

_LEDGER_KEY = "drafts/fb-trends/_posted.json"


def _key(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (topic or "").lower()).strip("-")[:60]


def _tokens(s: str) -> set:
    return set(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def _best_link(title: str, chosen: str, cands: list[dict]) -> str:
    """Prefer a DIRECT publisher link over a Google-News redirect (whose og:image is just
    the Google-News logo). If `chosen` is a google-news URL, find a direct-link candidate
    covering the same story (title-word overlap) and use that link instead."""
    if chosen and "news.google.com" not in chosen:
        return chosen
    ct = _tokens(title)
    best, score = chosen, 0
    for c in cands:
        link = c.get("link", "")
        if not link or "news.google.com" in link:
            continue
        ov = len(ct & _tokens(c.get("title", "")))
        if ov >= 3 and ov > score:
            best, score = link, ov
    return best


def _rclone_env():
    from tools.footage import _b2_env
    la = CONFIG.raw().get("longform_archive", {}) or {}
    return _b2_env(str(la.get("remote", "kgb2"))), str(la.get("remote", "kgb2"))


def _load_posted() -> list[str]:
    try:
        env, remote = _rclone_env()
        r = subprocess.run(["rclone", "cat", f"{remote}:{b2_store._bucket()}/{_LEDGER_KEY}"],
                           env=env, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return list(json.loads(r.stdout))
    except Exception as e:
        print(f"[trend-post] posted-ledger read skipped ({e!r}).", flush=True)
    return []


def _save_posted(keys: list[str]) -> None:
    try:
        env, remote = _rclone_env()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_posted.json"
            p.write_text(json.dumps(keys[-300:]), encoding="utf-8")   # cap history
            subprocess.run(["rclone", "copyto", str(p),
                            f"{remote}:{b2_store._bucket()}/{_LEDGER_KEY}"],
                           env=env, capture_output=True, timeout=60)
    except Exception as e:
        print(f"[trend-post] posted-ledger write skipped ({e!r}).", flush=True)


def _deliver(res: dict, pick: dict) -> bool:
    """Send the draft to Telegram + store the card on B2. Returns True on Telegram send."""
    from agents.content import draft_stamp
    caption = res.get("caption", "")
    topic = res.get("topic", "")
    stage = pick.get("stage", "")
    game = _key(res.get("game", "") or "gaming")[:24] or "gaming"
    img = res.get("image")

    # store the card on B2 (self-describing name) — best-effort
    if img and Path(img).exists():
        try:
            env, remote = _rclone_env()
            fname = f"fb-trend_{game}_{_key(topic)[:32]}_{draft_stamp()}.jpg"
            subprocess.run(["rclone", "copyto", str(img),
                            f"{remote}:{b2_store._bucket()}/drafts/fb-trends/{fname}"],
                           env=env, capture_output=True, timeout=120)
        except Exception as e:
            print(f"[trend-post] B2 store skipped ({e!r}).", flush=True)

    # Telegram: the card as a photo + a header, then the caption as its OWN message so
    # long-press -> Copy grabs exactly what to paste into Facebook.
    header = (f"\U0001F4C8 TREND DRAFT ({stage}) — review + post to Facebook\n"
              f"Topic: {topic}\n(card stored on B2 → drafts/fb-trends/)")
    if img and Path(img).exists():
        notify.telegram_photo(img, header)
    else:
        notify.telegram(header)
    return notify.telegram(caption)   # caption alone = clean copy-paste


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate KG Facebook trend-jacking drafts.")
    ap.add_argument("--count", type=int, default=1, help="max drafts to produce this run")
    ap.add_argument("--dry-run", action="store_true", help="build only; no B2/Telegram")
    a = ap.parse_args()

    games = list((CONFIG.reels.get("game_names", {}) or {}).values())
    print("[trend-post] scouting rising gaming trends…", flush=True)
    cands = trends.scout()
    posted = [] if a.dry_run else _load_posted()
    picks = trends.analyze(cands, games=games, exclude=posted, top_n=6)
    for p in picks:                                        # map the pick to its source article
        try:
            si = int(p.get("source_index", 0))
            if 1 <= si <= len(cands):
                c = cands[si - 1]
                p["source_link"] = _best_link(c.get("title", ""), c.get("link", ""), cands)
                p["source_name"] = c.get("source", "")       # e.g. 'news:IGN'
        except Exception:
            pass
    print(f"[trend-post] {len(cands)} candidates -> {len(picks)} ranked picks "
          f"(excluding {len(posted)} already posted).", flush=True)
    if not picks:
        if not a.dry_run:
            notify.telegram("\U0001F4C8 No fresh trend worth posting this cycle — will re-check next run.")
        return 0

    out_dir = ROOT / "output" / "trend_posts"
    made = 0
    for pick in picks:
        if made >= max(1, a.count):
            break
        topic = pick.get("topic", "")
        print(f"[trend-post] directing: {topic!r} [{pick.get('stage')}]", flush=True)
        res = pd.direct(pick, out_dir)
        if not res.get("ok"):
            print(f"   skipped (screen: {res.get('screen') or res.get('error')})", flush=True)
            continue
        print(f"   caption:\n{res.get('caption')}", flush=True)
        print(f"   card: {res.get('image')} | screen {res.get('screen')}", flush=True)
        if a.dry_run:
            made += 1
            continue
        _deliver(res, pick)
        posted.append(_key(topic))
        _save_posted(posted)
        made += 1

    print(f"[trend-post] done — {made} draft(s).", flush=True)
    if not a.dry_run and made == 0:
        notify.telegram("\U0001F4C8 Trends found but none passed the post screening this cycle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
