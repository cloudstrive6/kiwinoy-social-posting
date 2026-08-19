"""Runner for the KG Marvel trend-jacking pipeline.

Scout rising Marvel trends (MCU + Insomniac's Marvel games) -> Trend Analyst ranks them
(prefers RISING/pre-peak) -> Post Director writes a caption + builds a screened "news
card" with a REAL image -> deliver.

Delivery is set by config `trends.autopost.enabled`:
  * AUTOPOST (default): after a caption accuracy fact-check + a higher screener bar, the
    card + caption publish DIRECTLY — Facebook + Threads get the post, Instagram gets the
    image as a STORY — and a "went live" ping (card + exact live caption) hits Telegram so
    a bad one can be deleted fast.
  * DRAFT (enabled:false, or --draft): card + caption go to Telegram for you to post by hand.
A posted-topics ledger on B2 stops repeats.

Usage:
  python tools/trend_post.py                 # 1 item, per config (autopost or draft)
  python tools/trend_post.py --count 2       # up to N items
  python tools/trend_post.py --draft         # force DRAFT-to-Telegram (safe test)
  python tools/trend_post.py --dry-run       # scout+analyze+build only (no publish/Telegram)
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
from agents import trends, publisher, post_director as pd  # noqa: E402

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


def _today() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _load_posted() -> list[dict]:
    """Rich posted-topics log from B2 (newest last). Back-compat: legacy files are a plain
    list of key strings — those are wrapped into minimal records so nothing is lost."""
    try:
        env, remote = _rclone_env()
        r = subprocess.run(["rclone", "cat", f"{remote}:{b2_store._bucket()}/{_LEDGER_KEY}"],
                           env=env, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            recs: list[dict] = []
            for x in data:
                if isinstance(x, str):
                    recs.append({"key": x, "topic": x, "date": ""})
                elif isinstance(x, dict) and x.get("key"):
                    recs.append(x)
            return recs
    except Exception as e:
        print(f"[trend-post] posted-ledger read skipped ({e!r}).", flush=True)
    return []


def _posted_keys(recs: list[dict]) -> list[str]:
    return [r.get("key", "") for r in recs if r.get("key")]


def _posted_digest(recs: list[dict], n: int = 40) -> str:
    """Readable 'already posted' block for the analyst — newest first, last n items."""
    lines = []
    for r in reversed(recs[-n:]):
        d = r.get("date") or "?"
        t = r.get("topic") or r.get("key") or ""
        src = r.get("source") or ""
        lines.append(f"- {d} · {t}" + (f" ({src})" if src else ""))
    return "\n".join(lines)


def _save_posted(recs: list[dict]) -> None:
    try:
        env, remote = _rclone_env()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "_posted.json"
            p.write_text(json.dumps(recs[-300:], ensure_ascii=False), encoding="utf-8")  # cap history
            subprocess.run(["rclone", "copyto", str(p),
                            f"{remote}:{b2_store._bucket()}/{_LEDGER_KEY}"],
                           env=env, capture_output=True, timeout=60)
    except Exception as e:
        print(f"[trend-post] posted-ledger write skipped ({e!r}).", flush=True)


def _autopost_cfg() -> dict:
    return (CONFIG.raw().get("trends", {}) or {}).get("autopost", {}) or {}


def _score(res: dict) -> int:
    try:
        return int((res.get("screen") or {}).get("score", 0) or 0)
    except Exception:
        return 0


def _png_bytes(path) -> bytes:
    from PIL import Image
    import io as _io
    b = _io.BytesIO()
    Image.open(path).convert("RGB").save(b, "PNG")
    return b.getvalue()


def _store_card(img, res: dict, pick: dict) -> None:
    """Archive the card on B2 (self-describing name) — best-effort."""
    from agents.content import draft_stamp
    if not (img and Path(img).exists()):
        return
    game = _key(res.get("game", "") or "marvel")[:24] or "marvel"
    try:
        env, remote = _rclone_env()
        fname = f"fb-trend_{game}_{_key(res.get('topic',''))[:32]}_{draft_stamp()}.jpg"
        subprocess.run(["rclone", "copyto", str(img),
                        f"{remote}:{b2_store._bucket()}/drafts/fb-trends/{fname}"],
                       env=env, capture_output=True, timeout=120)
    except Exception as e:
        print(f"[trend-post] B2 store skipped ({e!r}).", flush=True)


def _deliver(res: dict, pick: dict) -> bool:
    """DRAFT mode: send the card + caption to Telegram + archive on B2. Returns True."""
    caption = res.get("caption", "")
    topic = res.get("topic", "")
    stage = pick.get("stage", "")
    img = res.get("image")
    _store_card(img, res, pick)
    header = (f"\U0001F4C8 TREND DRAFT ({stage}) — review + post\n"
              f"Topic: {topic}\n(card stored on B2 → drafts/fb-trends/)")
    if img and Path(img).exists():
        notify.telegram_photo(img, header)
    else:
        notify.telegram(header)
    return notify.telegram(caption)   # caption alone = clean copy-paste


def _publish(res: dict, pick: dict) -> bool:
    """AUTOPOST mode: fact-check the caption, then publish DIRECTLY — FB + Threads get the
    card + caption, Instagram gets the image as a STORY. Sends a 'went live' Telegram ping
    (card + the exact live caption) so a bad one can be deleted fast. Returns True if it
    published to at least one platform; False if the accuracy gate blocked it."""
    ap = _autopost_cfg()
    topic = res.get("topic", "")
    img = res.get("image")

    # accuracy gate — no human review, so verify + de-specify before it goes public
    v = pd.verify_caption(topic, res.get("caption", ""), res.get("game", ""))
    if not v.get("ok"):
        print(f"   accuracy: NOT postable -> skipped ({v.get('issues')})", flush=True)
        notify.telegram(f"⚠️ Trend skipped (accuracy): {topic}\n{v.get('issues')}")
        return False
    caption = v.get("safe_caption") or res.get("caption", "")

    png = _png_bytes(img)
    done: list[str] = []
    if ap.get("facebook", True):
        try:
            publisher.run(caption, png, platform_keys=["facebook"], is_draft=False)
            done.append("Facebook")
        except Exception as e:
            done.append("FB-FAIL"); print(f"   FB post failed: {e!r}", flush=True)
    if ap.get("threads", True):
        try:
            # Threads has a ~500-char limit (it truncates longer posts mid-word) — send a
            # cleanly-trimmed caption; Facebook above keeps the full-length one.
            publisher.run(pd.fit_threads(caption), png, platform_keys=["threads"], is_draft=False)
            done.append("Threads")
        except Exception as e:
            done.append("Threads-FAIL"); print(f"   Threads post failed: {e!r}", flush=True)
    if ap.get("instagram_story", True):
        try:
            # Post-for-Me requires a non-empty caption even for a Story (it isn't shown on
            # the story itself); the visible CTA is rendered onto the canvas.
            publisher.run_ig_story_image(caption, pd.story_canvas_bytes(img))
            done.append("IG-Story")
        except Exception as e:
            done.append("IGStory-FAIL"); print(f"   IG story failed: {e!r}", flush=True)

    _store_card(img, res, pick)
    posted_any = any(d in ("Facebook", "Threads", "IG-Story") for d in done)
    header = (f"✅ AUTO-POSTED ({pick.get('stage','')}): {topic}\n"
              f"Targets: {', '.join(done) or 'none'}") if posted_any else (
              f"⚠️ Auto-post FAILED for: {topic}\nTargets: {', '.join(done)}")
    if img and Path(img).exists():
        notify.telegram_photo(img, header[:1000])
    else:
        notify.telegram(header)
    notify.telegram(caption)          # the exact live caption (review / delete if wrong)
    return posted_any


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate KG Facebook trend-jacking drafts.")
    ap.add_argument("--count", type=int, default=1, help="max posts/drafts to produce this run")
    ap.add_argument("--dry-run", action="store_true", help="build only; no publish/Telegram")
    ap.add_argument("--draft", action="store_true",
                    help="force DRAFT-to-Telegram even if trends.autopost.enabled is true")
    ap.add_argument("--show-log", action="store_true",
                    help="print the posted-topics log (what's already been posted) and exit")
    a = ap.parse_args()

    if a.show_log:
        recs = _load_posted()
        print(f"[trend-post] posted-topics log — {len(recs)} entries (newest first):\n"
              + (_posted_digest(recs, n=len(recs)) or "  (empty)"), flush=True)
        return 0

    try:
        from core.marvel_history import history_brief
        history = history_brief()
    except Exception:
        history = ""

    games = list((CONFIG.reels.get("game_names", {}) or {}).values())
    print("[trend-post] scouting rising gaming trends…", flush=True)
    cands = trends.scout()
    posted = [] if a.dry_run else _load_posted()           # rich records (newest last)
    picks = trends.analyze(cands, games=games, exclude=_posted_keys(posted),
                           posted_log=_posted_digest(posted), history=history, top_n=6)
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

    apc = _autopost_cfg()
    autopost = bool(apc.get("enabled")) and not a.draft and not a.dry_run
    min_score = int(apc.get("min_score", 8) or 8)
    mode = "AUTOPOST" if autopost else ("DRY-RUN" if a.dry_run else "DRAFT")
    print(f"[trend-post] mode = {mode}"
          + (f" (min screen score {min_score})" if autopost else ""), flush=True)

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

        # NOVELTY GATE: catch a genuinely-recent article that only RESTATES a long-known fact
        # (e.g. "RDJ is Doctor Doom" — public since 2024). The age filter can't see this.
        nv = trends.novelty_check(topic, pick.get("angle", ""), history)
        if not nv.get("new", True):
            since = nv.get("known_since") or "?"
            print(f"   NOT NEW (known since {since}): {nv.get('reason')} -> skip", flush=True)
            notify.telegram(f"🗞️ Trend skipped — not new (known since {since}): {topic}\n"
                            f"{nv.get('reason')}")
            continue

        if autopost:
            if _score(res) < min_score:            # higher bar: no human review
                print(f"   below autopost bar ({_score(res)} < {min_score}) -> next pick",
                      flush=True)
                continue
            if not _publish(res, pick):            # accuracy gate blocked it -> try next
                continue
        else:
            _deliver(res, pick)
        # TREND -> BLOG: a trend worth posting also becomes a reviewable blog DRAFT (grounded
        # on the same source, deduped vs existing articles), pinged to Telegram for "approved".
        try:
            from tools.site_article import draft_topic
            draft_topic(topic, pick.get("source_link", ""), pick.get("source_name", ""),
                        notify_tg=True)
        except Exception as e:
            print(f"   [blog] draft skipped ({e!r})", flush=True)
        posted.append({                            # rich record for the posted-topics log
            "key": _key(topic), "topic": topic, "date": _today(),
            "stage": pick.get("stage", ""), "game": res.get("game", "") or pick.get("game", ""),
            "source": pick.get("source_name", "") or "", "url": pick.get("source_link", "") or "",
            "angle": pick.get("angle", ""),
        })
        _save_posted(posted)
        made += 1

    verb = "post(s)" if autopost else "draft(s)"
    print(f"[trend-post] done — {made} {verb}.", flush=True)
    if not a.dry_run and made == 0:
        notify.telegram("\U0001F4C8 Trends found but none cleared this cycle's bar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
