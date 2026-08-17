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


def _fetch_text(url: str) -> str:
    """Fetch the real source article and extract its paragraph text, so the writer rewrites
    from FACTS rather than inventing them from a headline. Empty for unusable URLs."""
    import html as _html
    import urllib.request
    if not url or "news.google.com" in url:
        return ""                                  # google-news redirects give no article text
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except Exception:
        return ""
    page = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", page)
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", page)
    text = " ".join(re.sub(r"(?s)<[^>]+>", " ", p) for p in paras)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()[:4800]


def _write_article(pick: dict, today: str) -> dict | None:
    """Fetch the real source article and have the LLM rewrite ONLY from its facts — so we never
    invent details from a headline. Returns the article dict, or None if the source can't be read."""
    src_url = pick.get("source_link", "")
    source_text = _fetch_text(src_url)
    if len(source_text) < 350:
        print(f"   skip (no readable source): {pick.get('topic','')[:50]}", flush=True)
        return None
    src_name = _clean_source(pick.get("source_name", ""))
    prompt = (
        "You are a news writer for BOSS KG (a gaming & Marvel site). Rewrite the SOURCE ARTICLE "
        "below into an original, accurate article for our readers (IGN-style: informative, "
        f"engaging).\n\nTODAY: {today}\nSOURCE OUTLET: {src_name}\n\n"
        f"=== SOURCE ARTICLE ===\n{source_text}\n=== END SOURCE ===\n\n"
        "STRICT RULES:\n"
        "- Use ONLY facts that appear in the SOURCE ARTICLE above. Do NOT add numbers, dates, "
        "box-office figures, quotes, or plot details that are not in the source. If it isn't in "
        "the source, do not state it.\n"
        "- Get the medium right: a movie is a movie, a game is a game, a LEGO set is a toy — never "
        "mislabel them.\n"
        "- Attribute the reporting to the source outlet. Label rumors/leaks as unconfirmed.\n"
        "- 4-6 short paragraphs, ~260-380 words. Plain paragraphs only — no markdown, hashtags or "
        "emojis. Engaging but honest; never clickbait or invented hype.\n\n"
        'Return ONLY JSON: {"title":"accurate headline","excerpt":"1-2 sentence summary",'
        '"category":"one of: Marvel Games | MCU | PlayStation | Gaming","game":"short key like '
        'spider-man2, wolverine, mcu, final-fantasy-7, halo (or \'mcu\')","tag":"News | Rumor | '
        'Preview | Hot","tags":["2-5 topical tags"],"body":"para 1\\n\\npara 2\\n\\n..."}')
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


def _to_markdown(a: dict, today: str, draft: bool = True) -> str:
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
    if draft:
        fm.append("draft: true")                          # draft-first: review before it goes live
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
    ap.add_argument("--publish", action="store_true",
                    help="write articles live (draft:false). Default is draft-first (review before publish).")
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

    picks = [{"topic": c["title"], "source_link": c.get("link", ""), "source_name": c.get("source", "")}
             for c in cands
             if _on_beat(c) and c.get("link") and "news.google.com" not in c.get("link", "")][: max(8, a.count * 2)]
    print(f"[site-article] {len(cands)} candidates -> {len(picks)} on-beat (with direct source)", flush=True)

    made, written = 0, []
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
        md = _to_markdown(art, today, draft=not a.publish)
        if a.dry:
            print(f"\n===== {slug}.md =====\n{md}", flush=True)
        else:
            (ART_DIR / f"{slug}.md").write_text(md, encoding="utf-8")
            # give it a cover scraped from the cited source (IGN-style press image)
            try:
                import subprocess
                subprocess.run([sys.executable, str(Path(__file__).with_name("article_cover.py")),
                                "--slug", slug], cwd=str(Path(__file__).resolve().parents[1]),
                               timeout=90)
            except Exception as e:
                print(f"   cover step skipped ({e!r})", flush=True)
            print(f"   wrote {slug}.md  [{art.get('category')}]", flush=True)
            written.append(art["title"])
        existing.add(slug)
        made += 1

    print(f"[site-article] done — {made} article(s).", flush=True)
    if written and not a.publish:
        try:
            from core import notify
            lst = "\n".join(f"• {t}" for t in written)
            notify.telegram(
                f"📝 {len(written)} new BOSS KG DRAFT article(s):\n{lst}\n\n"
                "Reply \"approved\" to publish + auto-post it to Facebook & Threads (with a link "
                "CTA). If more than one is pending, reply \"approve <keyword>\" (a word from the "
                "title) or \"approve all\".")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
