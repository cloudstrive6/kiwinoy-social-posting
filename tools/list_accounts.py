"""Discover your connected Post for Me accounts and save their IDs.

Run this once after you've (1) added POSTFORME_API_KEY to .env and
(2) connected your Facebook, Instagram, and Threads accounts in the Post for Me
dashboard.

  python tools/list_accounts.py            # list accounts
  python tools/list_accounts.py --save     # also write IDs into config.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import postforme  # noqa: E402
from core.config import CONFIG  # noqa: E402

# Map common Post for Me platform/provider labels onto our 3 target slots.
PLATFORM_ALIASES = {
    "facebook": "facebook",
    "facebook_page": "facebook",
    "instagram": "instagram",
    "instagram_business": "instagram",
    "threads": "threads",
}


def _platform_of(acct: dict) -> str:
    for k in ("platform", "provider", "type", "channel"):
        v = str(acct.get(k, "")).lower()
        if v in PLATFORM_ALIASES:
            return PLATFORM_ALIASES[v]
    return ""


def main() -> int:
    save = "--save" in sys.argv
    accounts = postforme.list_accounts()
    if not accounts:
        print("No connected accounts found. Connect FB / IG / Threads in the "
              "Post for Me dashboard first.")
        return 1

    print(f"Found {len(accounts)} connected account(s):\n")
    found: dict[str, str] = {}
    for a in accounts:
        plat = _platform_of(a)
        aid = a.get("id", "")
        name = a.get("username") or a.get("name") or a.get("display_name") or "?"
        raw_plat = a.get("platform") or a.get("provider") or a.get("type") or "?"
        print(f"  - {raw_plat:18} {name:24} id={aid}")
        if plat and plat not in found:
            found[plat] = aid

    if save:
        accts = CONFIG.platforms.setdefault("accounts", {})
        for plat in ("facebook", "instagram", "threads"):
            if plat in found:
                accts[plat] = found[plat]
        CONFIG.save()
        print("\nSaved account IDs into config.yaml:")
        for plat in ("facebook", "instagram", "threads"):
            print(f"  {plat}: {accts.get(plat, '(not found)')}")
    else:
        print("\nRe-run with --save to write these IDs into config.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
