"""Central configuration loader.

Loads non-secret settings from config.yaml and secrets from the environment
(.env locally, or GitHub Actions Secrets in the cloud). Every agent imports
`CONFIG` from here so there is a single source of truth.
"""
from __future__ import annotations

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
    @property
    def anthropic_api_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "").strip()

    @property
    def openai_api_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "").strip()

    @property
    def postforme_api_key(self) -> str:
        return os.environ.get("POSTFORME_API_KEY", "").strip()

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

    def slot(self, slot_id: int) -> dict[str, Any]:
        for s in self.schedule["slots"]:
            if int(s["id"]) == int(slot_id):
                return s
        raise ValueError(f"No schedule slot with id={slot_id}")

    def account_ids(self) -> list[str]:
        """Return the connected account IDs we should publish to."""
        accts = self.platforms.get("accounts", {})
        wanted = self.platforms.get("publish_to", list(accts.keys()))
        ids = [str(accts.get(p, "")).strip() for p in wanted]
        return [i for i in ids if i]

    def raw(self) -> dict[str, Any]:
        return self._data

    def save(self) -> None:
        """Persist config.yaml (used by tools/list_accounts.py)."""
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            yaml.safe_dump(self._data, fh, sort_keys=False, allow_unicode=True)


CONFIG = _Config()
