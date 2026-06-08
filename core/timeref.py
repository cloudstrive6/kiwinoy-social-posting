"""Current date/time context for the writers and fact-checker.

Anchors 'today' / 'tonight' / 'tomorrow' to real calendar dates (UTC + US
Eastern) so posts never say a bare 'tomorrow 8:30 ET', and the fact-checker can
verify relative-day wording against the actual date.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_context() -> str:
    now = datetime.now(timezone.utc)
    out = [
        f"RIGHT NOW it is {now.strftime('%A')}, {now.strftime('%B')} {now.day}, "
        f"{now.year}, {now.strftime('%H:%M')} UTC."
    ]
    try:
        from zoneinfo import ZoneInfo

        et = now.astimezone(ZoneInfo("America/New_York"))
        tz = et.tzname() or "ET"
        tom = et + timedelta(days=1)
        t = et.strftime("%I:%M %p").lstrip("0")
        out.append(
            f"In US Eastern that is {et.strftime('%A')}, {et.strftime('%B')} "
            f"{et.day}, {t} {tz}."
        )
        out.append(
            f"So 'today'/'tonight' = {et.strftime('%A, %B')} {et.day}; "
            f"'tomorrow' = {tom.strftime('%A, %B')} {tom.day}."
        )
    except Exception:
        tom = now + timedelta(days=1)
        out.append(
            f"So 'today' = {now.strftime('%A, %B')} {now.day}; "
            f"'tomorrow' = {tom.strftime('%A, %B')} {tom.day} (UTC)."
        )
    return " ".join(out)
