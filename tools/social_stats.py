"""Refresh the follower/subscriber counts shown on the BOSS KG home "Follow the action" strip.

Writes site/src/data/socials.json, which the site reads at build time. Fetches:
  - YouTube    subscriberCount via the Data API (official, reliable)
  - TikTok     followerCount scraped from the public profile page's rehydration JSON
  - Instagram  follower count via the public web_profile_info endpoint (best-effort)

There is NO official follower API for TikTok or Instagram, so those two are scraped and can
occasionally fail (bot-check / rate-limit from a cloud IP). To make that invisible on the site,
we keep a LAST-KNOWN-GOOD cache: a platform's number is only overwritten when a fresh fetch
succeeds, so a failed scrape leaves the previously-shown real number in place — never a dash.

  python tools/social_stats.py            # refresh all, merge, write socials.json
  python tools/social_stats.py --dry      # print what it fetched, don't write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

OUT = ROOT / "site" / "src" / "data" / "socials.json"
CHANNEL_ID = "UCeHnkTv_uA_dUgryYUPa-Dg"          # Boss KG
TIKTOK_USER = "kiwinoygamer"
IG_USER = "kiwinoygaming"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _humanize(n: int) -> str:
    """1234 -> '1.2K', 394 -> '394', 2_500_000 -> '2.5M' (drop a trailing .0)."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        s = f"{n/1000:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    s = f"{n/1_000_000:.1f}".rstrip("0").rstrip(".")
    return f"{s}M"


def _youtube_subs() -> int | None:
    try:
        from core import youtube
        yt = youtube._service()
        r = yt.channels().list(part="statistics", id=CHANNEL_ID).execute()
        items = r.get("items") or []
        if not items:
            return None
        c = int(items[0]["statistics"].get("subscriberCount", 0))
        return c or None
    except Exception as e:
        print(f"   youtube: {e!r}", flush=True)
        return None


def _tiktok_followers() -> int | None:
    """Scrape the public TikTok profile page's rehydration JSON for followerCount."""
    import requests
    try:
        url = f"https://www.tiktok.com/@{TIKTOK_USER}"
        html = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
                            timeout=25).text
        m = re.search(r'id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            data = json.loads(m.group(1))
            stats = (((data.get("__DEFAULT_SCOPE__", {}) or {})
                      .get("webapp.user-detail", {}) or {})
                     .get("userInfo", {}) or {}).get("stats", {}) or {}
            c = int(stats.get("followerCount", 0))
            if c:
                return c
        m2 = re.search(r'"followerCount":(\d+)', html)          # fallback
        return int(m2.group(1)) if m2 else None
    except Exception as e:
        print(f"   tiktok: {e!r}", flush=True)
        return None


def _instagram_followers() -> int | None:
    """Best-effort: the public web_profile_info endpoint (needs the web app-id header)."""
    import requests
    try:
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={IG_USER}"
        r = requests.get(url, headers={
            "User-Agent": _UA, "x-ig-app-id": "936619743392459",
            "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
        }, timeout=25)
        if r.status_code != 200:
            print(f"   instagram: HTTP {r.status_code}", flush=True)
            return None
        c = int((((r.json().get("data", {}) or {}).get("user", {}) or {})
                 .get("edge_followed_by", {}) or {}).get("count", 0))
        return c or None
    except Exception as e:
        print(f"   instagram: {e!r}", flush=True)
        return None


def _load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    prev = _load()
    print("[social-stats] fetching follower/subscriber counts …", flush=True)
    fetched = {
        "youtube": _youtube_subs(),
        "tiktok": _tiktok_followers(),
        "instagram": _instagram_followers(),
    }

    out = dict(prev)
    out.setdefault("youtube", {}); out.setdefault("tiktok", {}); out.setdefault("instagram", {})
    changed = False
    for key, n in fetched.items():
        if n and n > 0:                                   # only overwrite on a good fetch
            disp = _humanize(n)
            if out[key].get("count") != n:
                changed = True
            out[key] = {"count": n, "display": disp}
            print(f"   {key}: {n} ({disp})", flush=True)
        else:
            kept = out.get(key, {}).get("display", "—")
            print(f"   {key}: fetch failed — keeping last-known {kept}", flush=True)
    out["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    if a.dry:
        print(json.dumps(out, indent=2), flush=True)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"[social-stats] wrote {OUT.relative_to(ROOT)} (changed={changed}).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
