"""Populate the BOSS KG website's News sections with fresh, accurate articles.

Scouts current on-beat news (agents.trends — MCU + Insomniac's Marvel games), writes an
original REWRITTEN article per topic (LLM), and drops a markdown file into
site/src/content/articles/. Grounded by the same guards as the FB trend pipeline:
  - freshness filter (no week-old news),
  - novelty gate (never present a long-known fact as new — see core/marvel_history),
  - accuracy rules in the writer prompt (no invented quotes/dates, attribute the source).
Run locally or on a cron (site-articles.yml). New files -> Netlify rebuild -> live.

  python tools/site_article.py --count 6        # up to 6 new articles
  python tools/site_article.py --count 3 --dry  # print, don't write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from agents import trends                       # noqa: E402
from agents.content import _text, extract_json  # noqa: E402

ART_DIR = Path(__file__).resolve().parents[1] / "site" / "src" / "content" / "articles"


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")[:70] or "story"


def _clean_source(name: str) -> str:
    return re.sub(r"^(news:|gnews)", "", name or "").strip() or "reports"


def _write_article(pick: dict, today: str) -> dict | None:
    """LLM writes an accurate rewritten article for the pick; returns the article dict or None."""
    src_name = _clean_source(pick.get("source_name", ""))
    src_url = pick.get("source_link", "")
    prompt = (
        "You are a news writer for BOSS KG, a gaming & Marvel site. Write an ORIGINAL, accurate "
        "news article rewriting this story for our readers (IGN-style: informative, engaging).\n\n"
        f"TODAY: {today}\nTOPIC: {pick.get('topic','')}\nANGLE: {pick.get('angle','')}\n"
        f"SOURCE OUTLET: {src_name}\n\n"
        "RULES:\n"
        "- Be ACCURATE. Do NOT invent quotes, numbers, release dates, or plot details you are "
        "not sure of. If a detail is a rumor or unconfirmed, say so and attribute it.\n"
        "- Credit the reporting to the source outlet where appropriate.\n"
        "- 4-6 short paragraphs, ~260-400 words. Plain paragraphs only — no markdown headings, "
        "no hashtags, no emojis.\n"
        "- Neutral-to-hype tone; never negative or clickbait-dishonest.\n\n"
        'Return ONLY JSON: {"title":"clear compelling headline","excerpt":"1-2 sentence summary",'
        '"category":"one of: Marvel Games | MCU | PlayStation | Gaming","game":"short property '
        'key like spider-man2, wolverine, mcu, final-fantasy-7, halo (or \'mcu\')","tag":"one of: '
        'News | Rumor | Preview | Hot","tags":["2-5 topical tags like \'Spider-Man 2\',\'PS5\'"],'
        '"body":"paragraph 1\\n\\nparagraph 2\\n\\n..."}')
    try:
        d = extract_json(_text(prompt, timeout=150))
    except Exception as e:
        print(f"   writer failed ({e!r})", flush=True)
        return None
    if not isinstance(d, dict) or not d.get("title") or not d.get("body"):
        return None
    d["sourceName"] = src_name
    d["sourceUrl"] = src_url
    return d


def _to_markdown(a: dict, today: str) -> str:
    def y(v):
        return json.dumps(v, ensure_ascii=False)          # JSON strings are valid YAML
    tags = a.get("tags") or []
    fm = [
        "---",
        f"title: {y(a['title'])}",
        f"excerpt: {y(a.get('excerpt',''))}",
        f"category: {y(a.get('category','News'))}",
        f'tag: {y(a.get("tag","News"))}',
        f"tags: {y(tags)}",
        f"game: {y(a.get('game',''))}",
        f"date: {today}",
        'author: "BOSS KG"',
    ]
    if a.get("sourceName"):
        fm.append(f"sourceName: {y(a['sourceName'])}")
    if a.get("sourceUrl"):
        fm.append(f"sourceUrl: {y(a['sourceUrl'])}")
    fm.append("---")
    return "\n".join(fm) + "\n\n" + a["body"].strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    ART_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in ART_DIR.glob("*.md")}
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    print("[site-article] scouting current news …", flush=True)
    cands = trends.scout()
    # Keep it light + robust: keyword-filter to the Marvel beat instead of one heavy ranking
    # LLM call (the scout already dates + de-dups; freshest come first).
    kw = trends._MARVEL_KW
    marvel_feeds = ("news:ScreenRant", "news:Collider", "news:CBR", "news:ComicBook")

    def _on_beat(c):
        t = (c.get("title") or "").lower()
        src = c.get("source") or ""
        return src == "gnews" or src.startswith(marvel_feeds) or any(k in t for k in kw)

    picks = [{"topic": c["title"], "angle": "", "source_link": c.get("link", ""),
              "source_name": c.get("source", "")}
             for c in cands if _on_beat(c)][: max(8, a.count * 2)]
    print(f"[site-article] {len(cands)} candidates -> {len(picks)} on-beat", flush=True)

    made = 0
    for pick in picks:
        if made >= a.count:
            break
        topic = pick.get("topic", "")
        nv = trends.novelty_check(topic, pick.get("angle", ""))
        if not nv.get("new", True):
            print(f"   skip (not new, {nv.get('known_since')}): {topic}", flush=True)
            continue
        art = _write_article(pick, today)
        if not art:
            continue
        slug = _slug(art["title"])
        if slug in existing:
            print(f"   skip (exists): {slug}", flush=True)
            continue
        md = _to_markdown(art, today)
        if a.dry:
            print(f"\n===== {slug}.md =====\n{md}", flush=True)
        else:
            (ART_DIR / f"{slug}.md").write_text(md, encoding="utf-8")
            print(f"   wrote {slug}.md  [{art.get('category')}]", flush=True)
        existing.add(slug)
        made += 1

    print(f"[site-article] done — {made} article(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
