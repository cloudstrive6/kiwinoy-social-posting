"""Recent-post dedup helper.

CI runs are stateless, so to stop the research agent from picking the same hot
story over and over (e.g. five near-identical 'Wemby Game 3' posts), we pull the
channel's most recent published captions from Post for Me and feed them to the
research prompt as a 'do not repeat these' list. Best-effort: returns "" on any
error so it can never block posting.
"""
from __future__ import annotations

from core import postforme


def avoid_block(limit: int = 12, max_chars: int = 110) -> str:
    """Return a prompt block listing recent posts to avoid repeating, or ""."""
    try:
        caps = postforme.recent_captions(limit)
    except Exception:
        caps = []
    if not caps:
        return ""
    lines = []
    for c in caps:
        first = (c.splitlines()[0] if c.splitlines() else c).strip()
        if first:
            lines.append(f"- {first[:max_chars]}")
    if not lines:
        return ""
    return (
        "AVOID REPETITION (important): below are KiwinoyGamer's most recent posts. "
        "Do NOT pick the same story or a near-duplicate angle. Choose a clearly "
        "DIFFERENT, fresh topic (a different match, player, team, or storyline) that "
        "is not already covered here:\n" + "\n".join(lines)
    )
