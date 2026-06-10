"""Franchise matcher.

The Facebook/Instagram image rotation mixes anime gacha titles with AAA games
(Final Fantasy, Resident Evil, Halo). Each AAA title needs its own real art
style (and its own hashtags), not the default anime look. This scans a research
brief for a configured franchise keyword and returns that franchise's entry
(style + hashtags), or None for the default anime/gacha treatment.
"""
from __future__ import annotations

from typing import Any, Optional

from core.config import CONFIG

# Extra likeness push, appended to the image prompt whenever a franchise matches.
LIKENESS = (
    "CHARACTER LIKENESS (critical): depict the named character as accurately and "
    "recognizably as possible — correct hair, face, outfit or armor, signature "
    "weapon and colors, true to the official game design. Avoid a generic look."
)


def match(brief: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return the franchise_styles entry whose keyword appears in the brief, else None."""
    entries = CONFIG.image.get("franchise_styles") or []
    hay = " ".join(
        str(brief.get(k, "")) for k in ("title", "subject", "headline_idea", "angle")
    ).lower()
    for entry in entries:
        for kw in entry.get("match", []):
            if str(kw).lower() in hay:
                return entry
    return None
