"""Which promo line goes in a post description: our own product for that game, else the Gear page.

Bryce, 2026-11-24: "replace the gear promotion with our GTA 6 product/s - if the game is gta 6 then
promote our gta 6 products", and "if we have another guide/product for sale related to another game,
then that product/s should automatically replace the gear line".

So the rule is general: ANY game listed under reels.product_ctas in config.yaml promotes its own
product(s) instead of the gear page. Adding a product for a new game needs no code change:

    reels:
      product_ctas:
        gta6:                 # the game key used by the pipeline (footage/<game>, reels.games_only)
          link: "..."         # descriptions that allow a clickable link (YouTube Shorts, long-form)
          social: "..."       # Instagram and TikTok captions, which say "link in bio" instead
        wolverine:            # a second product for one game? make it a list; they take turns daily
          - {link: "...", social: "..."}
          - {link: "...", social: "..."}

A game matches its own key or any key that starts with it plus "-" (so the "gta6-guide" analysis
Shorts count as gta6). Games with no product keep the gear CTA (reels.gear_cta /
reels.gear_cta_social), so nothing changes for them.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional


def _ctas() -> dict:
    try:
        from core.config import CONFIG
        return dict(CONFIG.reels.get("product_ctas", {}) or {})
    except Exception:
        return {}


def _gear(kind: str) -> str:
    try:
        from core.config import CONFIG
        key = "gear_cta_social" if kind == "social" else "gear_cta"
        return str(CONFIG.reels.get(key, "") or "").strip()
    except Exception:
        return ""


def product_for(game: Optional[str]) -> Optional[str]:
    """The product key for a game key, or None. 'gta6' and 'gta6-guide' both give 'gta6'.
    The longest matching key wins, so a more specific entry can override a general one."""
    g = str(game or "").strip().lower()
    if not g:
        return None
    best = None
    for key in _ctas():
        k = str(key).strip().lower()
        if (g == k or g.startswith(k + "-")) and (best is None or len(k) > len(str(best))):
            best = key
    return best


def _pick(entry, day: Optional[int] = None) -> dict:
    """One product from an entry: a dict, or a list of dicts that take turns by UTC day."""
    if isinstance(entry, dict):
        return entry
    items = [e for e in (entry or []) if isinstance(e, dict)]
    if not items:
        return {}
    if day is None:
        day = _dt.datetime.now(_dt.timezone.utc).date().toordinal()
    return items[day % len(items)]


def promo_cta(game: Optional[str], kind: str = "link", day: Optional[int] = None) -> str:
    """The promo line for a post about `game`. kind='link' for descriptions with clickable
    links, kind='social' for Instagram/TikTok captions. Falls back to the gear CTA."""
    key = product_for(game)
    if key:
        line = str(_pick(_ctas().get(key), day).get(kind, "") or "").strip()
        if line:
            return line
    return _gear(kind)
