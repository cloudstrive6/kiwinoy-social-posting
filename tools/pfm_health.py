"""Post for Me health check: Telegram alert when recent posts failed on a platform.

Post for Me accepts a post and publishes it in the background, so our runs report success
even when every Facebook/Instagram post is failing (2026-11-05 to 2026-11-06: the Meta
session was invalidated and nothing reached FB or IG for about 21 hours, unnoticed). This
reads the latest post results and pings Telegram once per failing platform, with the
reconnect instruction when the error is a dead token. Runs at the end of reels.yml.

Usage: python tools/pfm_health.py [--limit 30]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from core import notify, postforme as pfm  # noqa: E402


def check(limit: int = 30) -> dict[str, str]:
    """Return {platform: latest error} for platforms whose MOST RECENT result failed."""
    names = {a.get("id"): a.get("platform", "?") for a in pfm.list_accounts()}
    r = requests.get(f"{pfm.BASE_URL}/social-post-results", headers=pfm._headers(),
                     params={"limit": limit}, timeout=60)
    r.raise_for_status()
    d = r.json()
    items = d.get("data", d) if isinstance(d, dict) else d
    latest: dict[str, dict] = {}
    for x in items:                       # newest first: keep the first result per account
        acct = x.get("social_account_id")
        if acct and acct not in latest:
            latest[acct] = x
    return {names.get(a, a): str(x.get("error") or "unknown error")
            for a, x in latest.items() if x.get("success") is False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    a = ap.parse_args()
    try:
        bad = check(a.limit)
    except Exception as e:
        print(f"[pfm-health] check skipped ({e!r}).", flush=True)
        return 0
    if not bad:
        print("[pfm-health] latest post on every platform succeeded.", flush=True)
        return 0
    lines = []
    for plat, err in sorted(bad.items()):
        fix = (" -> reconnect it in app.postforme.dev (keep external id kg-"
               f"{'xtwitter' if plat == 'x' else plat})"
               if "reconnect" in err.lower() or "access token" in err.lower() else "")
        lines.append(f"- {plat}: {err[:180]}{fix}")
    msg = "🚨 KG posts are FAILING on Post for Me:\n" + "\n".join(lines)
    print(msg, flush=True)
    notify.telegram(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
