"""Central configuration loader.

Loads non-secret settings from config.yaml and secrets from the environment
(.env locally, or GitHub Actions Secrets in the cloud). Every agent imports
`CONFIG` from here so there is a single source of truth.
"""
from __future__ import annotations

# Make Python's HTTPS use the OS certificate store. This keeps requests/httpx
# (Post for Me, OpenAI, Anthropic) working behind antivirus or corporate proxy
# SSL inspection, which is common on Windows. Best-effort: a no-op if missing.
try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:
    pass

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
OUTPUT_DIR = ROOT / "output"

# Load .env if present (local dev). In CI the vars come from the environment.
load_dotenv(ROOT / ".env")


class _Config:
    """Thin wrapper over the parsed config.yaml + environment secrets."""

    def __init__(self) -> None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            self._data: dict[str, Any] = yaml.safe_load(fh)
        OUTPUT_DIR.mkdir(exist_ok=True)

    # ---- secrets -------------------------------------------------------
    @staticmethod
    def _key(name: str) -> str:
        # Strip whitespace AND any stray BOM/zero-width chars. A BOM can sneak
        # into a secret value (e.g. set via a PowerShell pipe) and would corrupt
        # the Authorization header, so we remove it defensively.
        v = os.environ.get(name, "")
        for _ch in ("\ufeff", "\u200b", "\u200c", "\u200d"):
            v = v.replace(_ch, "")
        return v.strip()

    @property
    def anthropic_api_key(self) -> str:
        return self._key("ANTHROPIC_API_KEY")

    @property
    def openai_api_key(self) -> str:
        return self._key("OPENAI_API_KEY")

    @property
    def postforme_api_key(self) -> str:
        return self._key("POSTFORME_API_KEY")

    @property
    def claude_code_oauth_token(self) -> str:
        return self._key("CLAUDE_CODE_OAUTH_TOKEN")

    @property
    def elevenlabs_api_key(self) -> str:
        return self._key("ELEVENLABS_API_KEY")

    # TikTok Content Posting API (direct, no middleman). client_key/secret identify
    # our TikTok app; the long-lived refresh_token mints a short-lived access_token
    # each run. All three are env-only (public repo).
    @property
    def tiktok_client_key(self) -> str:
        return self._key("TIKTOK_CLIENT_KEY")

    @property
    def tiktok_client_secret(self) -> str:
        return self._key("TIKTOK_CLIENT_SECRET")

    @property
    def tiktok_refresh_token(self) -> str:
        return self._key("TIKTOK_REFRESH_TOKEN")

    # ---- convenience accessors ----------------------------------------
    @property
    def brand(self) -> dict[str, Any]:
        return self._data["brand"]

    @property
    def models(self) -> dict[str, Any]:
        return self._data["models"]

    @property
    def schedule(self) -> dict[str, Any]:
        return self._data["schedule"]

    @property
    def topics(self) -> dict[str, Any]:
        return self._data["topics"]

    @property
    def caption(self) -> dict[str, Any]:
        return self._data["caption"]

    @property
    def hashtags(self) -> dict[str, Any]:
        return self._data["hashtags"]

    @property
    def image(self) -> dict[str, Any]:
        return self._data["image"]

    @property
    def platforms(self) -> dict[str, Any]:
        return self._data["platforms"]

    @property
    def reels(self) -> dict[str, Any]:
        return self._data.get("reels", {})

    @property
    def carousels(self) -> dict[str, Any]:
        return self._data.get("carousels", {})

    @property
    def photoposts(self) -> dict[str, Any]:
        return self._data.get("photoposts", {})

    @property
    def threads_posts(self) -> dict[str, Any]:
        return self._data.get("threads_posts", {})

    def slot(self, slot_id: int) -> dict[str, Any]:
        for s in self.schedule["slots"]:
            if int(s["id"]) == int(slot_id):
                return s
        raise ValueError(f"No schedule slot with id={slot_id}")

    def reel_slot(self, slot_id: int) -> dict[str, Any]:
        for s in self.reels.get("schedule", {}).get("slots", []):
            if int(s["id"]) == int(slot_id):
                return s
        raise ValueError(f"No reels slot with id={slot_id}")

    def carousel_slot(self, slot_id: int) -> dict[str, Any]:
        for s in self.carousels.get("schedule", {}).get("slots", []):
            if int(s["id"]) == int(slot_id):
                return s
        raise ValueError(f"No carousel slot with id={slot_id}")

    def _live_accounts(self) -> list[dict[str, Any]]:
        """Connected Post for Me accounts, fetched once per process and cached.

        Lazy import avoids a circular import (postforme imports CONFIG). Fail-open
        to [] so an API hiccup just falls back to the cached IDs in config.
        """
        if getattr(self, "_acct_cache", None) is not None:
            return self._acct_cache
        accounts: list[dict[str, Any]] = []
        try:
            from core import postforme
            accounts = postforme.list_accounts() or []
        except Exception:
            accounts = []
        self._acct_cache = accounts
        return accounts

    def account_ids(self, platform_keys: list[str] | None = None) -> list[str]:
        """Return the CURRENT connected account IDs for the given platforms.

        Resolves each platform to its live Post for Me id via the STABLE external
        id (e.g. "kg-facebook" in platforms.external_ids), so reconnecting an
        account — which rotates its spc_ id — never needs a config edit. Falls
        back to a live platform match, then to the cached `accounts:` id in config
        if Post for Me is unreachable.

        Defaults to the image/reel platforms. Pass an explicit list (e.g.
        ["threads"]) for the Threads track.
        """
        accts = self.platforms.get("accounts", {})          # cached spc_ ids (offline fallback)
        ext = self.platforms.get("external_ids", {})         # platform -> stable external id
        if platform_keys is None:
            platform_keys = self.platforms.get("image_post_to", list(accts.keys()))
        live = self._live_accounts()
        by_ext = {a.get("external_id"): a.get("id")
                  for a in live if a.get("external_id") and a.get("id")}
        by_plat = {a.get("platform"): a.get("id")
                   for a in live if a.get("platform") and a.get("id")}
        out: list[str] = []
        for p in platform_keys:
            eid = str(ext.get(p, "")).strip()
            rid = ((by_ext.get(eid) if eid else None)        # 1) stable external id (preferred)
                   or by_plat.get(p)                         # 2) live platform match
                   or str(accts.get(p, "")).strip())         # 3) cached config id (offline)
            if rid:
                out.append(str(rid).strip())
        return out

    def raw(self) -> dict[str, Any]:
        return self._data

    def save(self) -> None:
        """Persist config.yaml (used by tools/list_accounts.py)."""
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self._data, fh, sort_keys=False, allow_unicode=True)


CONFIG = _Config()
