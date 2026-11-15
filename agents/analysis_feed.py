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

DEDICATED REELS (Bryce, 2026-11-15: "generate dedicated analysis format reels for these 3 social
media", then "Do only Spider-Man 2 and Spider-Man 1 games for now"). When config
reels.analysis_reels.games is set, the feed reads ONLY those games' reel packs,
data/analysis/<game>-reels/shorts.json: reels written and narrated for TikTok, Instagram and
Facebook (square layout, the payoff inside the reel, no YouTube end line). They need no YouTube
upload: a reel is ready once it has a b2_key and its optional "release_at" has passed. Games take
turns (first unused reel of each game in order), and a reel counts as used only when it is unused
on every platform the slot posts to.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent


def _reel_games() -> list[str]:
    try:
        from core.config import CONFIG
        return [str(g) for g in ((CONFIG.reels.get("analysis_reels", {}) or {}).get("games") or [])]
    except Exception:
        return []


def _reel_picks(games: list[str]) -> list[tuple[str, dict, dict]]:
    """Dedicated reel packs, games interleaved: R01 of each game, then R02 of each, ..."""
    per = []
    for g in games:
        f = ROOT / "data" / "analysis" / f"{g}-reels" / "shorts.json"
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        cfg["dedicated"] = True
        per.append([(g, cfg, s) for s in sorted(cfg.get("shorts", []), key=lambda x: x.get("order", 0))])
    out = []
    for i in range(max((len(x) for x in per), default=0)):
        out += [x[i] for x in per if i < len(x)]
    return out


def _picks() -> list[tuple[str, dict, dict]]:
    """(game, config, pick) for every pick, newest long-form first, then pick order."""
    games = _reel_games()
    if games:
        return _reel_picks(games)
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


def _live(pick: dict, now: dt.datetime, dedicated: bool = False) -> bool:
    t = pick.get("release_at") if dedicated else (pick.get("youtube") or {}).get("publish_at")
    if dedicated and not t:
        return True
    if not t:
        return False
    try:
        return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00")) <= now
    except ValueError:
        return False


def caption(cfg: dict, pick: dict, platform: str) -> str:
    tags = list(dict.fromkeys((cfg.get("hashtags_base") or []) + (pick.get("hashtags_extra") or [])))
    if cfg.get("dedicated"):   # the reel carries its own payoff: no pointer to YouTube
        body = (pick.get("caption") or pick.get("title") or "").strip()
        # the music bed's licences ask for a credit (CC BY for "Red"; Ross Bugden asks for one too)
        credits = pick.get("music_credits") or cfg.get("music_credits") or []   # per reel: only its own track
        music = ("Music: " + "; ".join(credits)) if credits else ""
        return "\n\n".join([x for x in (body, music) if x] + ([" ".join(tags[:5])] if tags else [])).strip()
    lines = [pick.get("title", "").strip()]
    if pick.get("spoilers"):
        lines.append("Spoilers for the ending.")
    lines.append("Full breakdown on YouTube: BOSS KG")
    return "\n\n".join([l for l in lines if l] + [" ".join(tags[:5])]).strip()


def next_short(platform: str, now: Optional[dt.datetime] = None,
               platforms: Optional[list[str]] = None) -> Optional[dict[str, Any]]:
    """The next ready pick unused on `platform` (and on every one of `platforms`, when given)."""
    from core import gh_release
    now = now or dt.datetime.now(dt.timezone.utc)
    used: set = set()
    for pl in dict.fromkeys([platform, *(platforms or [])]):
        try:
            used |= set(gh_release.used_clips(pl))
        except Exception:
            pass
    for game, cfg, s in _picks():
        ded = bool(cfg.get("dedicated"))
        cid = clip_id(f"{game}-reels" if ded else game, s)
        if cid in used or not s.get("b2_key") or not _live(s, now, ded):
            continue
        return {"game": game, "pick": s["id"], "clip_id": cid, "b2_key": s["b2_key"], "dedicated": ded,
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
