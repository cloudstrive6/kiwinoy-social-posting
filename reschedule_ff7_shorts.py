"""Reschedule the still-scheduled FF7 Remake YouTube SHORTS to start 2026-08-17,
2/day. Excludes the long-form parts (only touches '#Shorts' FF7R videos that are
private + have a future publishAt). Re-runnable: it re-derives the set live."""
import sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, ".")
from core import youtube  # noqa: E402

START = datetime(2026, 8, 17, tzinfo=timezone.utc)
TIMES = [(10, 0), (13, 30)]        # 2/day, UTC (PH evening)


def slots(n):
    out, day = [], 0
    while len(out) < n:
        for h, m in TIMES:
            out.append(START.replace(hour=h, minute=m) + timedelta(days=day))
            if len(out) >= n:
                break
        day += 1
    return out


def main():
    now = datetime.now(timezone.utc)
    vids = youtube.list_uploads(400)
    def fut(v):
        pa = v.get("publishAt")
        if not pa or v.get("privacy") != "private":
            return False
        try:
            return datetime.fromisoformat(pa.replace("Z", "+00:00")) > now
        except Exception:
            return False
    ff7 = [v for v in vids if fut(v) and "#shorts" in v["title"].lower()
           and ("final fantasy" in v["title"].lower() or "ff7" in v["title"].lower())]
    ff7.sort(key=lambda v: v["publishAt"])
    print(f"FF7R shorts to reschedule: {len(ff7)}", flush=True)
    new = slots(len(ff7))
    for v, when in zip(ff7, new):
        iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        t = v["title"][:45].encode("ascii", "replace").decode()
        print(f"  {v['publishAt']} -> {iso}  {v['id']}  {t}", flush=True)
        youtube.reschedule(v["id"], iso)
    print("=== done ===", flush=True)


if __name__ == "__main__":
    main()
