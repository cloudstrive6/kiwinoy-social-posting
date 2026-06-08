"""Fact-Check / Reviewer agent — independent publish gate.

Before a factual post goes out, this re-verifies its claims with a FRESH web
search (separate from the research agent that wrote it) and returns a pass/fail
verdict. Opinions / predictions / hot takes / polls are NOT fact-checked (only
factual errors are flagged).

Provider: "openai" (OpenAI web search, for image/reel) or "claude" (Claude web
search via CLAUDE_CODE_OAUTH_TOKEN, for Threads).

On a checker error the verdict is "error" (the orchestrator treats that as
publishable so an infra hiccup never halts the whole pipeline).
"""
from __future__ import annotations

from typing import Any, Optional

from core import claude_code, openai_client
from core.timeref import now_context

_SYSTEM = (
    "You are a meticulous, skeptical fact-checker for a social media channel. You "
    "independently verify factual claims using web search and you never approve a "
    "claim you cannot confirm is currently true."
)


def _prompt(text: str, brief: dict[str, Any]) -> str:
    facts = "\n".join(f"- {f}" for f in (brief.get("key_facts") or []))
    return f"""A social media post is about to be published. Use web search to
INDEPENDENTLY verify every factual claim in it (names, scores, dates, results,
events, "X happened", "Y is the Z"). Confirm each is TRUE and CURRENT as of today.

{now_context()}

POST:
\"\"\"{text}\"\"\"

Facts the author cited (verify these too):
{facts or '- (none listed)'}

Rules:
- Flag anything FALSE, OUTDATED, already decided/announced differently, or that you
  cannot verify from a credible, current source.
- Do NOT flag opinions, predictions, hot takes, hype, or subjective phrasing — only
  concrete factual errors.

TIME / DATE checks (using the current date/time above) — BE STRICT:
- A relative word alone ("today", "tonight", "tomorrow", "this weekend") is NOT a
  date. If the post states a specific time (e.g. "8:30 ET", "18:00", a kickoff or
  tip-off time) WITHOUT an explicit calendar date right next to it (a month + day,
  e.g. "June 9" or "Mon Jun 9"), that is an automatic FAIL — a reader seeing it a
  day later would not know which day it means.
- The explicit date, its weekday, and the timezone must all be correct, and any
  "today"/"tonight"/"tomorrow" wording must match the actual date relative to right
  now. FAIL on any mismatch (wrong day, wrong weekday, wrong timezone conversion).
- The event time itself must be accurate.

If even ONE material factual claim (including a time/date problem) is wrong,
missing, or unverifiable, the verdict is "fail".

Return ONLY this JSON (no prose, no code fences):
{{"verdict": "pass" or "fail", "issues": ["specific problem", "..."]}}"""


def review(
    text: str,
    brief: Optional[dict[str, Any]] = None,
    provider: str = "openai",
) -> dict[str, Any]:
    """Return {"verdict": "pass"|"fail"|"error", "issues": [...]}."""
    brief = brief or {}
    prompt = _prompt(text, brief)
    try:
        if provider == "claude":
            raw = claude_code.run(prompt, web=True)
        else:
            raw = openai_client.research(prompt, system=_SYSTEM)
        data = openai_client.extract_json(raw)
        verdict = str(data.get("verdict", "")).lower().strip()
        issues = data.get("issues", []) or []
        if verdict not in ("pass", "fail"):
            verdict = "fail" if issues else "pass"
        return {"verdict": verdict, "issues": issues}
    except Exception as e:  # fail-open on checker error, but surface it
        return {"verdict": "error", "issues": [f"fact-check could not run: {e}"]}
