"""Append the Gear affiliate CTA line to EXISTING YouTube video descriptions.

Idempotent: skips any video whose description already contains the CTA, so it can be re-run
daily until the whole back-catalogue is done (YouTube's quota caps updates at ~200/day —
videos.update costs 50 units each of a 10,000/day budget). Stops cleanly on quotaExceeded.

  python tools/backfill_gear_cta.py --limit 150          # do up to 150 today
  python tools/backfill_gear_cta.py --limit 5 --dry      # preview, no writes
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

from core import youtube
from core.config import CONFIG

UPLOADS = "UUeHnkTv_uA_dUgryYUPa-Dg"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=150, help="max descriptions to update this run")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    cta = str((CONFIG.reels.get("gear_cta", "") or "")).strip()
    if not cta:
        print("[gear-cta] reels.gear_cta is empty — nothing to append.", flush=True)
        return 0
    # match on the URL so a reworded CTA still counts as 'already present'
    marker = cta.split("→")[-1].strip() or cta

    yt = youtube._service()
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=UPLOADS,
                                    maxResults=50, pageToken=tok).execute()
        ids += [it["contentDetails"]["videoId"] for it in r.get("items", [])]
        tok = r.get("nextPageToken")
        if not tok:
            break
    print(f"[gear-cta] {len(ids)} uploads; appending: {cta!r}", flush=True)

    updated = skipped = done_already = 0
    for i in range(0, len(ids), 50):
        if updated >= a.limit:
            break
        chunk = ids[i:i + 50]
        r = yt.videos().list(part="snippet", id=",".join(chunk), maxResults=50).execute()
        for it in r.get("items", []):
            if updated >= a.limit:
                break
            sn = it.get("snippet", {})
            desc = sn.get("description", "") or ""
            if marker in desc:
                done_already += 1
                continue
            new_desc = (desc.rstrip() + "\n\n" + cta).strip()[:5000]
            if a.dry:
                print(f"  would update {it['id']}: {sn.get('title','')[:50]}", flush=True)
                updated += 1
                continue
            body = {"id": it["id"], "snippet": {
                "title": sn.get("title", ""), "categoryId": sn.get("categoryId", "20"),
                "description": new_desc, "tags": sn.get("tags", [])}}
            if sn.get("defaultLanguage"):
                body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
            try:
                yt.videos().update(part="snippet", body=body).execute()
                updated += 1
                print(f"  + {it['id']}: {sn.get('title','')[:50]}", flush=True)
            except Exception as e:
                if "quota" in repr(e).lower():
                    print(f"  ⚠ DAILY QUOTA REACHED after {updated} updates — re-run tomorrow.", flush=True)
                    print(f"[gear-cta] updated {updated}, already-had {done_already}.", flush=True)
                    return 0
                print(f"  ! FAILED {it['id']}: {e!r}", flush=True)
                skipped += 1
    print(f"[gear-cta] {'DRY: would update' if a.dry else 'updated'} {updated}; "
          f"already-had {done_already}; failed {skipped}; "
          f"{'remaining ' + str(len(ids) - done_already - updated) if not a.dry else ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
