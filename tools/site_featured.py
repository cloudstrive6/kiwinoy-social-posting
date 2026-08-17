"""Pick which live BOSS KG article headlines the home page (the big hero slot).

The hero is chosen by TREND BUZZ + RECENCY, not a static flag: this scans today's current
gaming/Marvel headlines (agents.trends.scout) and features the live article whose topic has the
most ongoing coverage right now, tie-broken by how recent it is. A story that keeps trending stays
in the hero for days; once the buzz cools, a fresher story takes over — so the "hot for 3 days vs a
week" lifespan is handled automatically. It sets `featured: true` on exactly one article and clears
the rest. Runs daily (site-articles.yml).

  python tools/site_featured.py            # re-pick + rewrite frontmatter
  python tools/site_featured.py --dry      # show the pick, change nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import yaml  # noqa: E402

ART_DIR = ROOT / "site" / "src" / "content" / "articles"
FRESH_DAYS = 10                                       # older news shouldn't headline the site


def _parse(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"(?s)^---\n(.*?)\n---\n?(.*)$", text)
    fm = {}
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
    return text, (fm if isinstance(fm, dict) else {})


def _live() -> list[dict]:
    out = []
    for p in ART_DIR.glob("*.md"):
        text, fm = _parse(p)
        if fm.get("draft") is True:
            continue
        d = fm.get("date")
        if isinstance(d, dt.datetime):
            d = d.date()
        elif isinstance(d, str):
            try:
                d = dt.date.fromisoformat(d[:10])
            except Exception:
                d = None
        out.append({"slug": p.stem, "path": p, "text": text,
                    "title": str(fm.get("title", p.stem)), "date": d,
                    "tags": fm.get("tags") or [], "featured": fm.get("featured") is True})
    return out


def _recent(arts, today: dt.date):
    fresh = [a for a in arts if a["date"] and (today - a["date"]).days <= FRESH_DAYS]
    return fresh or arts                              # fallback: consider all if none are fresh


def _newest(arts):
    return max(arts, key=lambda a: (a["date"] or dt.date.min))


def _pick_trending(arts, today: dt.date) -> str | None:
    """Ask the writer model which of OUR live articles is the biggest ongoing story right now,
    given today's trending headlines. Returns a slug, or None to fall back to newest."""
    try:
        from agents import trends
        from agents.content import _text, extract_json
        heads = [c.get("title", "") for c in trends.scout()][:34]
    except Exception as e:
        print(f"   scout/import failed ({e!r}) — recency only", flush=True)
        return None
    if not heads:
        return None
    ours = "\n".join(f"- [{a['slug']}] {a['title']}  ({a['date']})" for a in arts)
    trend = "\n".join(f"- {h}" for h in heads if h)
    prompt = (
        "You choose the single best story to feature in the big hero slot of a gaming & Marvel "
        f"news site. TODAY is {today}.\n\nOUR LIVE ARTICLES (pick one of THESE by slug):\n{ours}\n\n"
        f"TODAY'S TRENDING GAMING/MARVEL HEADLINES (buzz signal — more coverage = hotter):\n{trend}\n\n"
        "Pick the ONE of OUR articles that is the most trending / biggest story to headline right "
        "now. Weigh how much the topic still appears in today's headlines (ongoing buzz) first, then "
        "recency. Return ONLY JSON: {\"slug\":\"<one of our slugs>\",\"reason\":\"short\"}.")
    try:
        d = extract_json(_text(prompt, timeout=150))
        slug = str((d or {}).get("slug", "")).strip()
        reason = str((d or {}).get("reason", "")).strip()
        if any(a["slug"] == slug for a in arts):
            print(f"   trend pick: {slug} — {reason}", flush=True)
            return slug
        print(f"   model returned unknown slug {slug!r} — recency only", flush=True)
    except Exception as e:
        print(f"   featured LLM failed ({e!r}) — recency only", flush=True)
    return None


def _set_featured(text: str, value: bool) -> str:
    if re.search(r"(?m)^featured:\s*.*$", text):
        return re.sub(r"(?m)^featured:\s*.*$", f"featured: {str(value).lower()}", text, count=1)
    anchor = r"(?m)^(draft:.*)$" if re.search(r"(?m)^draft:", text) else r"(?m)^(date:.*)$"
    return re.sub(anchor, f"featured: {str(value).lower()}\n\\1", text, count=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    arts = _live()
    if not arts:
        print("[featured] no live articles.", flush=True)
        return 0
    today = dt.datetime.now(dt.timezone.utc).date()
    pool = _recent(arts, today)
    winner = _pick_trending(pool, today) or _newest(pool)["slug"]
    print(f"[featured] -> {winner}", flush=True)

    changed = 0
    for art in arts:
        want = art["slug"] == winner
        if art["featured"] == want:
            continue
        if not a.dry:
            art["path"].write_text(_set_featured(art["text"], want), encoding="utf-8")
        print(f"   {art['slug']}: featured {art['featured']} -> {want}", flush=True)
        changed += 1
    print(f"[featured] {'(dry) ' if a.dry else ''}updated {changed} file(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
