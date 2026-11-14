"""The "analysis" format for the Instagram and TikTok reel rotation (Bryce, 2026-11-14: "Add the
analysis format to the rotation for TikTok and Instagram").

An analysis Short is a vertical Short cut from a finished KG analysis long-form by
tools/analysis_shorts.py (one question and its answer, word-by-word captions). They are rendered
once, kept on private B2 (shorts/analysis/<game>/<id>.mp4, written to the pick as "b2_key") and
listed in data/analysis/<game>/shorts.json. On an "analysis" rotation slot the reel track posts
the next one that

  - has a file on B2,
  - is already live on YouTube (its YouTube publish time has passed), so the full video it points
    to is public too, and
  - has not been posted on this platform yet (the same used-clip ledger as every other reel,
    clip id "analysis__<game>__<pick id>").

Picks run in each game's own order, newest long-form first. None left -> the caller falls back to
the next format in the rotation, so a slot is never empty.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent


def _picks() -> list[tuple[str, dict, dict]]:
    """(game, config, pick) for every pick, newest long-form first, then pick order."""
    out = []
    files = sorted((ROOT / "data" / "analysis").glob("*/shorts.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        game = f.parent.name
        for s in sorted(cfg.get("shorts", []), key=lambda x: x.get("order", 0)):
            out.append((game, cfg, s))
    return out


def clip_id(game: str, pick: dict) -> str:
    return f"analysis__{game}__{pick['id']}"


def _live(pick: dict, now: dt.datetime) -> bool:
    t = (pick.get("youtube") or {}).get("publish_at")
    if not t:
        return False
    try:
        return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00")) <= now
    except ValueError:
        return False


def caption(cfg: dict, pick: dict, platform: str) -> str:
    tags = list(dict.fromkeys((cfg.get("hashtags_base") or []) + (pick.get("hashtags_extra") or [])))
    lines = [pick.get("title", "").strip()]
    if pick.get("spoilers"):
        lines.append("Spoilers for the ending.")
    lines.append("Full breakdown on YouTube: BOSS KG")
    return "\n\n".join([l for l in lines if l] + [" ".join(tags[:5])]).strip()


def next_short(platform: str, now: Optional[dt.datetime] = None) -> Optional[dict[str, Any]]:
    from core import gh_release
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        used = gh_release.used_clips(platform)
    except Exception:
        used = set()
    for game, cfg, s in _picks():
        cid = clip_id(game, s)
        if cid in used or not s.get("b2_key") or not _live(s, now):
            continue
        return {"game": game, "pick": s["id"], "clip_id": cid, "b2_key": s["b2_key"],
                "title": s.get("title", ""), "caption": caption(cfg, s, platform)}
    return None


def fetch(item: dict) -> bytes:
    import requests

    from core import b2_store
    url = b2_store.presigned_url(item["b2_key"], valid_seconds=3600)
    if not url:
        raise RuntimeError(f"cannot sign {item['b2_key']}")
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    return r.content
