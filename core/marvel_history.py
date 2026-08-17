"""Established Marvel facts the Trend Analyst must treat as ALREADY KNOWN.

The freshness filter in trends.scout() only checks an ARTICLE's publish date. That
misses the real trap: a *fresh* roundup article restating a fact that's been public for
months or years — e.g. "Robert Downey Jr. is Doctor Doom", revealed at SDCC in July 2024.
Posting that as breaking news makes the page look clueless.

This file is the page's institutional memory of what's ALREADY established. The analyst and
the novelty gate read history_brief() so they only post a GENUINELY NEW development on a
topic — never a restatement of a long-known fact.

LIVING FILE — keep it current. Add a fact the moment it becomes widely known, WITH the date
it broke, so future re-reports of it are correctly rejected as old news. Accuracy matters:
only add things you're confident are true and public; when unsure of an exact date use a
'YYYY-MM' month or a plain description.
"""
from __future__ import annotations

# fact:  the established claim (state it plainly).
# since: when it became public knowledge — ISO date "YYYY-MM-DD", month "YYYY-MM", or "".
# note:  optional — what WOULD count as genuinely new on this topic (helps the gate).
FACTS: list[dict] = [
    {"fact": "Robert Downey Jr. is playing Victor von Doom / Doctor Doom in the MCU",
     "since": "2024-07-27",
     "note": "Revealed at San Diego Comic-Con 2024. NOT news anymore. Only NEW Doom details "
             "(new footage, plot, costume reveal) are postable — the casting itself is not."},
    {"fact": "Joe & Anthony Russo are directing Avengers: Doomsday and Avengers: Secret Wars",
     "since": "2024-07-27", "note": ""},
    {"fact": "The main Avengers: Doomsday cast was revealed via the all-day 'director's chair' livestream",
     "since": "2025-03-26",
     "note": "The large cast list (returning X-Men actors, the new Fantastic Four, the "
             "Thunderbolts/New Avengers, etc.) is already public. Only cast ADDITIONS or "
             "changes announced AFTER this are new."},
    {"fact": "Marvel's Wolverine is an Insomniac single-player PS5 game, first announced at the September 2021 PlayStation Showcase",
     "since": "2021-09-09",
     "note": "The GAME's existence is old news. New TRAILERS, gameplay reveals, release "
             "dates/windows, or delays ARE postable."},
    {"fact": "Marvel's Spider-Man 2 (Insomniac, PS5) released on October 20, 2023",
     "since": "2023-10-20",
     "note": "The release itself is old. New updates/DLC, a PC port, sales milestones, or the "
             "next game ARE postable."},
    {"fact": "A next Insomniac Spider-Man game was teased in the ending of Marvel's Spider-Man 2",
     "since": "2023-10-20",
     "note": "Its existence is known; a concrete reveal (official title, trailer, platform, "
             "date) would be new."},
    # ─── ADD MORE AS THEY BECOME PUBLIC — with the date each one broke ───
]


def history_brief(limit: int = 60) -> str:
    """Compact 'already established' block for the analyst / novelty-gate prompt.
    Empty string if there are no facts (the prompt then simply omits the block)."""
    lines = []
    for f in FACTS[:limit]:
        note = (f.get("note") or "").strip()
        lines.append(f"- (public since {f.get('since') or '?'}) {f['fact']}"
                     + (f"  [new = {note}]" if note else ""))
    return "\n".join(lines)
