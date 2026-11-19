"""Release YouTube analysis Shorts at their slot, one per slot, games taking turns.

Bryce, 2026-11-16: "only upload them as they hit their timeslot and not upload > schedule them",
so other games can be fitted in without waiting for a whole series to finish (the 12 Wolverine
Shorts had booked every slot until 2026-11-21). Nothing is booked ahead any more:

  - At each slot (config reels.youtube_analysis_shorts.slots_utc) this job picks ONE Short.
  - Games take turns in the order of `games`: the game after the one that filled the last slot
    goes first; a game with nothing ready is skipped for that slot.
  - A pick is ready when it is HELD (uploaded earlier as private with no publish time; released
    by flipping it to public) or when it has a render on B2 and no YouTube id yet (downloaded
    from B2 and uploaded public there and then). New picks also need their long-form
    (shorts.json "full_video") to be public, because the description points to it.
  - A slot counts as filled when any pick in any pack has a YouTube time within 50 minutes of
    it (an old-style scheduled Short too), so a rerun or a backup cron never posts twice.
  - The workflow runs a few times after each slot; a run more than `window_hours` after the
    latest slot does nothing, so a dropped cron catches up but a stale one never fires late.

Usage: python tools/analysis_release.py [--dry-run] [--now ISO] [--hold game:id,id,...]
  --hold  migrate already-scheduled picks to HELD (private, publish time cleared) so their
          slots open up; they are then released by this job in turn.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UTC = dt.timezone.utc
FILLED_WITHIN = dt.timedelta(minutes=50)


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(t: Optional[str]) -> Optional[dt.datetime]:
    if not t:
        return None
    try:
        return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None


def settings() -> dict:
    from core.config import CONFIG
    s = dict(CONFIG.reels.get("youtube_analysis_shorts", {}) or {})
    s.setdefault("enabled", False)
    s.setdefault("slots_utc", ["15:00", "23:00"])
    s.setdefault("games", [])
    s.setdefault("window_hours", 3)
    return s


def pack_path(game: str) -> Path:
    return ROOT / "data" / "analysis" / game / "shorts.json"


def load_packs(games: list[str]) -> dict[str, dict]:
    from core.config import CONFIG
    out = {}
    for g in [x for x in games if CONFIG.game_allowed(x)]:  # reels.games_only lock (2026-11-19)
        f = pack_path(g)
        if f.exists():
            out[g] = json.loads(f.read_text(encoding="utf-8"))
    return out


def save_pack(game: str, cfg: dict) -> None:
    pack_path(game).write_text(json.dumps(cfg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def yt_time(s: dict) -> Optional[dt.datetime]:
    """When this pick went (or goes) public on YouTube: its release, or an old scheduled time."""
    y = s.get("youtube") or {}
    if y.get("held"):
        return None
    # the slot it filled, not the clock time: a run delayed past 50 min must still see its slot taken
    return parse(y.get("slot") or y.get("publish_at") or y.get("released_at"))


def current_slot(now: dt.datetime, slots_utc: list[str], window_h: float) -> Optional[dt.datetime]:
    """The latest slot at or before `now`, if it is still inside the catch-up window."""
    best = None
    for back in (0, 1):
        d = (now - dt.timedelta(days=back)).date()
        for hm in slots_utc:
            h, m = (int(x) for x in hm.split(":"))
            t = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)
            if t <= now and (best is None or t > best):
                best = t
    if best is None or now - best > dt.timedelta(hours=window_h):
        return None
    return best


def slot_filled(packs: dict[str, dict], slot: dt.datetime) -> Optional[str]:
    for g, cfg in packs.items():
        for s in cfg.get("shorts", []):
            t = yt_time(s)
            if t and abs(t - slot) < FILLED_WITHIN:
                return f"{g}/{s['id']}"
    return None


def last_game(packs: dict[str, dict], before: dt.datetime) -> Optional[str]:
    best = None
    for g, cfg in packs.items():
        for s in cfg.get("shorts", []):
            t = yt_time(s)
            if t and t < before and (best is None or t > best[0]):
                best = (t, g)
    return best[1] if best else None


def longform_public(cfg: dict, cache: dict) -> bool:
    url = (cfg.get("full_video") or "").strip()
    if not url:
        return False
    vid = url.rstrip("/").split("/")[-1].split("=")[-1]
    if vid not in cache:
        from core import youtube
        cache[vid] = (youtube.video_status([vid]).get(vid) or {}).get("privacy") == "public"
    return cache[vid]


def next_ready(cfg: dict, lf_cache: dict, offline: bool) -> Optional[tuple[dict, str]]:
    """(pick, action) for a game's next Short in order: 'release' a held one, 'upload' a new one."""
    for s in sorted(cfg.get("shorts", []), key=lambda x: x.get("order", 0)):
        y = s.get("youtube") or {}
        if y.get("held") and y.get("id"):
            return s, "release"
        if y.get("id"):
            continue                      # already public, or scheduled the old way
        if not s.get("b2_key"):
            return None                   # keep order: wait for this one's render
        if offline or longform_public(cfg, lf_cache):
            return s, "upload"
        return None
    return None


def choose(packs: dict[str, dict], games: list[str], slot: dt.datetime, offline: bool = False):
    order = [g for g in games if g in packs]
    if not order:
        return
    lg = last_game(packs, slot)
    if lg in order:                       # start with the game after the one that went last
        i = order.index(lg) + 1
        order = order[i:] + order[:i]
    cache: dict = {}
    for g in order:
        try:
            r = next_ready(packs[g], cache, offline)
        except Exception as e:
            print(f"{g}: cannot check readiness: {e!r}", flush=True)
            continue
        if r:
            yield g, r[0], r[1]


def known_ids(packs: dict[str, dict]) -> set[str]:
    """Every YouTube id a pack records (current and old versions such as youtube_v3)."""
    out = set()
    for cfg in packs.values():
        for s in cfg.get("shorts", []):
            for k, v in s.items():
                if k.startswith("youtube") and isinstance(v, dict) and v.get("id"):
                    out.add(v["id"])
    return out


def already_uploaded(title: str, known: set[str]) -> Optional[str]:
    """Id of a recent upload with this exact title that no pack records (a crash between the
    upload and the commit of its record). Old private versions share titles, hence `known`."""
    from core import youtube
    for u in youtube.list_uploads(max_items=40):
        if u["id"] not in known and (u.get("title") or "").strip() == title.strip()[:100]:
            return u["id"]
    return None


def release(game: str, cfg: dict, s: dict, action: str, slot: dt.datetime, known: set[str]) -> str:
    from core import youtube
    from core.config import CONFIG
    now = dt.datetime.now(UTC)
    if action == "release":
        vid = s["youtube"]["id"]
        youtube.set_privacy(vid, "public")
    elif (vid := already_uploaded(s["title"], known)):
        # an earlier run uploaded it but its record never got committed: adopt it, never upload twice
        print(f"{game}/{s['id']}: found earlier upload {vid}, adopting it", flush=True)
        s["youtube"] = {"id": vid, "uploaded_at": iso(now), "adopted": True}
        youtube.set_privacy(vid, "public")
    else:
        import requests

        from core import b2_store
        url = b2_store.presigned_url(s["b2_key"], valid_seconds=3600)
        if not url:
            raise RuntimeError(f"cannot sign {s['b2_key']}")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / f"{s['id']}.mp4"
            with requests.get(url, timeout=600, stream=True) as r:
                r.raise_for_status()
                with open(f, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            res = youtube.upload_video(f, s["title"], s["description"], s["tags"], privacy="public")
        vid = res.get("id")
        if not vid:
            raise RuntimeError(f"upload returned no id: {res!r}")
        s["youtube"] = {"id": vid, "uploaded_at": iso(now)}
        mark(s, now, slot)
        save_pack(game, cfg)              # id AND slot at once: a crash after this never posts twice
        playlist = (CONFIG.reels.get("youtube", {}) or {}).get("playlists", {}).get(game)
        if playlist:
            try:
                s["youtube"]["playlist"] = bool(youtube.add_to_playlist(vid, playlist))
            except Exception as e:
                print(f"{game}/{s['id']}: playlist add failed: {e!r}", flush=True)
                s["youtube"]["playlist"] = False
    mark(s, now, slot)
    save_pack(game, cfg)
    return vid


def mark(s: dict, now: dt.datetime, slot: dt.datetime) -> None:
    y = s["youtube"]
    y.pop("held", None)
    y.update({"released_at": iso(now), "publish_at": iso(now), "slot": iso(slot), "mode": "at-slot"})


def hold(spec: str, dry: bool) -> int:
    """game:id,id -> private with no publish time, marked held (their slots open up)."""
    from core import youtube
    game, ids = spec.split(":", 1)
    cfg = json.loads(pack_path(game).read_text(encoding="utf-8"))
    now = dt.datetime.now(UTC)
    for s in cfg["shorts"]:
        if s["id"] not in ids.split(","):
            continue
        y = s.get("youtube") or {}
        t = parse(y.get("publish_at"))
        if not y.get("id") or y.get("held") or not t or t <= now + dt.timedelta(minutes=30):
            print(f"{s['id']}: skipped (no id, already held, or publishes within 30 min)")
            continue
        print(f"{s['id']}: {y['id']} scheduled {y['publish_at']} -> held" + (" (dry run)" if dry else ""))
        if dry:
            continue
        youtube.set_privacy(y["id"], "private")   # clears publishAt
        y["was_scheduled"] = y.pop("publish_at")
        y["held"] = True
        y["held_at"] = iso(now)
        save_pack(game, cfg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", default="", help="pretend time, ISO UTC (for testing)")
    ap.add_argument("--offline", action="store_true", help="dry run without asking YouTube")
    ap.add_argument("--hold", default="", help="game:id,id,... move scheduled picks to held")
    a = ap.parse_args()
    if a.hold:
        return hold(a.hold, a.dry_run)
    st = settings()
    if not st["enabled"] and not a.dry_run:
        print("youtube_analysis_shorts disabled in config; nothing to do")
        return 0
    now = parse(a.now) if a.now else dt.datetime.now(UTC)
    slot = current_slot(now, st["slots_utc"], float(st["window_hours"]))
    if not slot:
        print(f"{iso(now)}: no slot in the last {st['window_hours']} h; nothing to do")
        return 0
    packs = load_packs(st["games"])
    got = slot_filled(packs, slot)
    if got:
        print(f"slot {iso(slot)} already filled by {got}")
        return 0
    errors = 0
    for game, s, action in choose(packs, st["games"], slot, offline=a.offline):
        print(f"slot {iso(slot)}: {action} {game}/{s['id']} \"{s['title']}\"")
        if a.dry_run:
            return 0
        try:
            vid = release(game, packs[game], s, action, slot, known_ids(packs))
        except Exception as e:
            print(f"{game}/{s['id']}: release FAILED: {e!r}", flush=True)
            errors += 1
            if (s.get("youtube") or {}).get("slot"):
                break                     # it did go up: the slot is filled, post nothing else
            continue                      # try the next game for this slot
        print(f"{game}/{s['id']} public https://youtu.be/{vid}")
        return 1 if errors else 0
    if not errors:
        print(f"slot {iso(slot)}: no Short ready in {st['games']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
