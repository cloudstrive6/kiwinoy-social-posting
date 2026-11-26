"""Keep each live game's fact bank topped up, automatically (Bryce, 2026-11-20: "So what will the
process be when you are about to run of facts? There should be an automated process for that").

Fact cards (tools/lore_short.py) draw on data/lore/<game>-facts.json and mark each fact used once
posted (gh_release story-quote ledger, key "fact:<game>:<id>"). When every fact is used the bank
starts over and repeats. This job runs daily (.github/workflows/fact-topup.yml) and, for every game
in the games lock that has a fact bank:

  1. Counts the UNUSED facts. At or above `min_unused` (about 3 days of posts) it does nothing.
  2. RESEARCH: one Claude Code session (subscription, web search) finds `batch` NEW candidate facts,
     each with the source pages it opened, told every existing fact so it does not repeat them.
  3. CHECK: a SEPARATE Claude Code session (it never sees the researcher's reasoning) opens every
     source and gives each candidate PASS, FIX (a corrected wording the sources fully support) or
     FAIL. Same method as the 2026-11-19 manual check (gta6-facts-checkreport.md).
  4. CODE GATES on what passed: a working source URL, 45 words at most, no near-duplicate of an
     existing or earlier-in-batch fact, and no "Rockstar confirmed"-style credit the sources never
     make (lore_short.attribution_overreach).
  5. Appends the survivors to the bank (next ids, `checked` = today), appends a report section to
     data/lore/<game>-facts-checkreport.md, and tells Bryce on Telegram. The workflow commits both.

Fails safe: if research or the check fails, nothing is added, the bank keeps working (repeats at
worst) and Telegram says so; tomorrow's run tries again. Nothing unchecked ever reaches the bank.

Usage: python tools/fact_topup.py [--game gta6] [--force] [--dry-run] [--batch N]
  --force    top up even when the bank is not low (a test, or to stock up before a busy week)
  --dry-run  research and check, print the result, change nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core.config import CONFIG  # noqa: E402

FACTS_DIR = ROOT / "data" / "lore"
MAX_WORDS = 45
DUP_JACCARD = 0.5


def log(m: str) -> None:
    print(f"[fact-topup] {m}", flush=True)


def settings() -> dict:
    s = dict(CONFIG.reels.get("fact_topup", {}) or {})
    s.setdefault("enabled", True)
    s.setdefault("min_unused", 18)      # ~3 days at up to 6 fact cards a day (3 Facebook + 3 YouTube)
    s.setdefault("batch", 25)           # candidates researched per top-up; roughly 60-80% pass
    s.setdefault("model", "opus")
    s.setdefault("timeout", 1800)       # seconds per Claude session (web research is slow)
    return s


def bank_path(game: str) -> Path:
    return FACTS_DIR / f"{game}-facts.json"


def load_bank(game: str) -> dict:
    return json.loads(bank_path(game).read_text(encoding="utf-8"))


def used_keys() -> set[str]:
    from core import gh_release
    return gh_release.used_story_quotes()


def unused(game: str, facts: list[dict], used: set[str]) -> list[dict]:
    return [f for f in facts if f"fact:{game}:{f.get('id')}" not in used]


def _words(t: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "of", "in", "on", "to", "is", "was", "it", "its", "for",
            "with", "that", "this", "as", "at", "by", "from", "are", "be", "has", "have", "you", "your"}
    return {w for w in re.findall(r"[a-z0-9']+", str(t).lower()) if w not in stop and len(w) > 2}


def near_duplicate(fact: str, others: list[str]) -> str:
    """The existing fact this one repeats (word-set overlap >= DUP_JACCARD), else ''."""
    a = _words(fact)
    if not a:
        return ""
    for o in others:
        b = _words(o)
        if b and len(a & b) / len(a | b) >= DUP_JACCARD:
            return o
    return ""


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", str(url or "").strip())
    return m.group(1).lower() if m else ""


def _json(text: str) -> dict:
    from core.openai_client import extract_json
    d = extract_json(text or "")
    return d if isinstance(d, dict) else {}


def research(game: str, gname: str, existing: list[dict], n: int, st: dict) -> list[dict]:
    from core import claude_code
    today = dt.date.today().isoformat()
    have = "\n".join(f"- {f['fact']}" for f in existing)
    prompt = (
        f"You are restocking a bank of short, TRUE, surprising facts about {gname} for 15-20 second "
        f"YouTube and Facebook fact-card Shorts that play over gameplay footage. Today is {today}.\n\n"
        f"Find {n} NEW facts by searching the web and OPENING the pages. Each fact:\n"
        "- one or two plain sentences, at most 40 words, concrete (names, numbers, places, dates) "
        "and genuinely surprising to a player;\n"
        "- supported by a page you actually opened, from a reputable source: the developer or "
        "publisher, Wikipedia, or a major games outlet (IGN, Kotaku, VGC, Eurogamer, GamesRadar, "
        "Polygon, PC Gamer, The Verge, Gematsu, Push Square, Shacknews and similar);\n"
        "- WHO SAID IT: when a claim comes from a preview, review, interview or report, say who and "
        "when ('In August 2026, Rockstar North's Rob Nelson told IGN...', 'Reviews note...'). Never "
        "write 'Rockstar confirmed' or 'the developers revealed' unless the developer's own words "
        "or channel are the source;\n"
        "- about the game itself: its world, places, characters, systems, activities, vehicles, "
        "music, development history, real-world inspirations, records and numbers;\n"
        "- NOT a rumour, leak, datamine, fan theory, prediction or anything a source hedges; NOT a "
        "spoiler of the story's ending or a late twist; NOT about a real private person, a crime "
        "victim, or anyone's medical or legal situation;\n"
        "- NOT a repeat or rewording of any fact already in the bank below; new angles only.\n"
        "Prefer facts that pair with ordinary gameplay footage (driving, police and wanted level, "
        "the city and beaches, swamps and wildlife, characters, weapons, shops and activities).\n\n"
        f"FACTS ALREADY IN THE BANK (do not repeat):\n{have}\n\n"
        'Reply with JSON only: {"facts": [{"fact": "...", "sources": ["https://...", ...], '
        '"wow": 1-5, "pairs_with": "the kind of footage it suits, a few words"}]}'
    )
    out = claude_code.run(prompt, web=True, model=st["model"], timeout=int(st["timeout"]))
    facts = [f for f in (_json(out).get("facts") or []) if isinstance(f, dict) and f.get("fact")]
    log(f"research returned {len(facts)} candidate(s)")
    return facts


def check(gname: str, cands: list[dict], existing: list[dict], st: dict) -> list[dict]:
    """Independent check in a fresh session: [{'i', 'verdict', 'fact', 'sources', 'reason'}]."""
    from core import claude_code
    listing = "\n".join(f"{i}. {c['fact']}\n   sources: {', '.join(c.get('sources') or [])}"
                        for i, c in enumerate(cands, 1))
    have = "\n".join(f"- {f['fact']}" for f in existing)
    prompt = (
        f"You are an independent fact-checker for short {gname} fact cards that go on YouTube and "
        "Facebook. Someone else wrote the candidates below; do not trust them.\n\n"
        "For EACH candidate, open its source pages (WebFetch) and judge it:\n"
        "- PASS: every claim in it is stated by at least one opened, reputable page.\n"
        "- FIX: the gist is right but a detail is wrong, unsupported or overstated. Give a "
        "corrected wording that the opened pages FULLY support (drop the unsupported detail, add "
        "who said it and when for preview or interview claims). Same length or shorter.\n"
        "- FAIL: the sources do not support it, it is a rumour, leak, datamine or speculation, it "
        "is a story-ending spoiler, it is about a real private person or anyone's medical or legal "
        "situation, or it repeats a fact already in the bank listed further down.\n"
        "If a page is blocked or will not load, look for a second reputable source and use that "
        "instead; if none confirms the claim, FAIL it. Credit check: a fact that says 'Rockstar "
        "confirmed' (or similar) when the source is a news site reporting it is a FIX (credit the "
        "outlet or person) or a FAIL.\n\n"
        f"CANDIDATES:\n{listing}\n\n"
        f"ALREADY IN THE BANK (a candidate that repeats one of these FAILS):\n{have}\n\n"
        'Reply with JSON only: {"results": [{"i": 1, "verdict": "PASS|FIX|FAIL", "fact": "the '
        'final wording (the original for PASS, the corrected one for FIX)", "sources": ["only the '
        'URLs you opened that support it"], "reason": "one short line"}]}'
    )
    out = claude_code.run(prompt, web=True, model=st["model"], timeout=int(st["timeout"]))
    res = [r for r in (_json(out).get("results") or []) if isinstance(r, dict)]
    log(f"check returned {len(res)} verdict(s)")
    return res


def gate(cands: list[dict], results: list[dict], existing: list[dict]) -> tuple[list[dict], list[str]]:
    """Code gates after the check. Returns (accepted candidates, report lines)."""
    from lore_short import attribution_overreach
    ok, lines, done = [], [], set()
    seen = [f["fact"] for f in existing]
    for r in results:
        try:
            i = int(r.get("i"))
        except Exception:
            continue
        if not 1 <= i <= len(cands) or i in done:   # out of range, or a second verdict for one fact
            continue
        done.add(i)
        c = cands[i - 1]
        verdict = str(r.get("verdict", "")).upper().strip()
        fact = re.sub(r"\s+", " ", str(r.get("fact") or c.get("fact") or "")).strip()
        srcs = [s for s in (r.get("sources") or []) if _domain(s)]
        why = str(r.get("reason", "")).replace("|", "/").strip()
        drop = ""
        if verdict not in ("PASS", "FIX"):
            drop = f"check: {verdict or 'no verdict'}"
        elif not srcs:
            drop = "no opened source"
        elif len(fact.split()) > MAX_WORDS:
            drop = f"too long ({len(fact.split())} words)"
        else:
            dup = near_duplicate(fact, seen)
            # support = the source domains only: the checker's free-text reason ("not said by the
            # developer") would otherwise switch the credit check off (review, 2026-11-20)
            over = attribution_overreach(fact, " ".join(_domain(s) for s in srcs))
            a, b = _words(fact), _words(c.get("fact", ""))
            related = bool(a and b and len(a & b) / len(a | b) >= 0.2)
            if dup:
                drop = f"repeats: {dup[:60]}"
            elif over:
                drop = f"credit: {over}"
            elif not related:
                drop = "checker's wording is not about this candidate"
        status = "DROP" if drop else verdict
        lines.append(f"| {i} | {status} | {fact} | {'; '.join(_domain(s) for s in srcs)} | "
                     f"{drop or why} |")
        if drop:
            continue
        seen.append(fact)
        ok.append({"fact": fact, "sources": srcs, "wow": c.get("wow", 3),
                   "pairs_with": c.get("pairs_with", "any clip"), "verdict": verdict})
    return ok, lines


def next_ids(game: str, facts: list[dict], n: int, used: set | None = None) -> list[str]:
    """Next free ids, above every id in the bank AND in the used ledger: a removed fact's id stays
    marked used, so reusing it would hide the new fact until the bank cycles."""
    ids = [str(f.get("id", "")) for f in facts]
    ids += [k.split(":", 2)[2] for k in (used or set()) if k.startswith(f"fact:{game}:")]
    nums = [int(m.group(1)) for x in ids for m in [re.search(r"-(\d+)$", x)] if m]
    start = max(nums or [0]) + 1
    return [f"{game}-{k:02d}" for k in range(start, start + n)]


def topup(game: str, st: dict, force: bool = False, dry: bool = False, batch: int = 0) -> dict:
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
    data = load_bank(game)
    facts = [f for f in data.get("facts", []) if f.get("fact")]
    used = used_keys()
    if not used:
        # gh_release returns an empty set on ANY read failure, which would make every fact look
        # unused and hide a dry bank. The ledger always holds keys once anything has posted.
        raise RuntimeError("could not read the used-fact ledger (empty), so the bank level is unknown")
    left = unused(game, facts, used)
    log(f"{game}: {len(left)} unused of {len(facts)} (top up below {st['min_unused']})")
    if len(left) >= int(st["min_unused"]) and not force:
        return {"game": game, "action": "none", "unused": len(left)}
    n = int(batch or st["batch"])
    cands = research(game, gname, facts, n, st)
    if not cands:
        raise RuntimeError("research found no candidates")
    results = check(gname, cands, facts, st)
    if not results:
        raise RuntimeError("the independent check returned no verdicts")
    ok, lines = gate(cands, results, facts)
    today = dt.date.today().isoformat()
    ids = next_ids(game, facts, len(ok), used)
    new = [{"id": fid, "fact": f["fact"], "source": f["sources"][0], "sources": f["sources"],
            "wow": f["wow"], "pairs_with": f["pairs_with"], "flag": "", "checked": today,
            "fit": []}   # matched to no moment until a reviewed fit list is written (2026-11-26)
           for fid, f in zip(ids, ok)]
    passed = sum(1 for f in ok if f["verdict"] == "PASS")
    summary = (f"{len(cands)} researched, {len(results)} checked: {passed} PASS, "
               f"{len(ok) - passed} FIX, {len(cands) - len(ok)} dropped or failed")
    log(summary)
    for f in new:
        log(f"  + [{f['id']}] {f['fact']}  ({_domain(f['source'])})")
    if not dry and new:
        data["facts"] = facts + new
        data["updated"] = today
        bank_path(game).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        rep = FACTS_DIR / f"{game}-facts-checkreport.md"
        section = (f"\n\n## Automatic top-up {today} (tools/fact_topup.py)\n\n"
                   f"Unused before: {len(left)} of {len(facts)}. {summary}. Added: "
                   f"{', '.join(f['id'] for f in new) or 'none'}.\n\n"
                   "| # | verdict | final wording | sources | reason |\n|---|---|---|---|---|\n"
                   + "\n".join(lines) + "\n")
        with rep.open("a", encoding="utf-8") as fh:
            fh.write(section)
    return {"game": game, "action": "topped up" if new else "nothing passed", "unused": len(left),
            "added": len(new), "summary": summary, "total": len(facts) + len(new)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=0)
    a = ap.parse_args()
    st = settings()
    if not st["enabled"] and not a.force:
        log("reels.fact_topup.enabled is false; nothing to do")
        return 0
    games = [a.game] if a.game else [g for g in (CONFIG.games_lock() or [])
                                     if bank_path(g).exists()]
    if not games:
        log("no live game has a fact bank; nothing to do")
        return 0
    from core import notify
    rc = 0
    for g in games:
        try:
            r = topup(g, st, force=a.force, dry=a.dry_run, batch=a.batch)
        except Exception as e:
            rc = 1
            log(f"{g}: top-up FAILED: {e!r}")
            if not a.dry_run:
                notify.telegram(f"KG fact bank top-up for {g} failed ({str(e)[:200]}). Nothing was "
                                "added; the bank keeps working and tomorrow's run tries again.")
            continue
        if r["action"] == "none" or a.dry_run:
            continue
        left_after = r["unused"] + r["added"]
        msg = (f"KG fact bank ({g}): {r['unused']} unused facts left, so the daily top-up ran. "
               f"{r['summary']}. Added {r['added']}; {left_after} unused now, {r['total']} in the bank.")
        if r["added"] < 5:
            msg += " That is fewer than 5, so cards may start repeating facts soon; worth a look."
        notify.telegram(msg)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
