"""Trend Scout + Analyst — the front of the KG Facebook trend-jacking pipeline.

scout() gathers candidate GAMING topics from API-legal, reachable sources:
  - gaming news RSS (leading indicators: news breaks BEFORE a trend peaks)
  - YouTube trending gaming (chart=mostPopular, our Data API)
  - Google Trends daily RSS (mainstream breakouts)
Facebook/CrowdTangle has had NO public read API since Aug 2024, and Reddit needs
OAuth — both skipped. These leading indicators surface gaming trends EARLIER than
Facebook itself would show them, which is the point (catch the rise, not the peak).

analyze() asks an LLM to RANK the candidates: is each one RISING / pre-peak (not
already past its peak), how relevant is it to a gaming audience (lean to the KG
franchises), and how postable is it — returning the top topics each with a concrete
post ANGLE. A caller can dedupe against already-posted trends via `exclude`.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

_UA = {"User-Agent": "Mozilla/5.0 (compatible; KiwinoyGamerTrends/1.0)"}

# Gaming news RSS — leading indicators (announcements/patches/drama fire pre-peak).
_NEWS_FEEDS = {
    "IGN": "https://feeds.feedburner.com/ign/games-all",
    "GameSpot": "https://www.gamespot.com/feeds/mashup/",
    "Eurogamer": "https://www.eurogamer.net/feed",
    "PCGamer": "https://www.pcgamer.com/rss/",
    "Polygon": "https://www.polygon.com/rss/index.xml",
    "PushSquare": "https://www.pushsquare.com/feeds/latest",
    "VG247": "https://www.vg247.com/feed",
}
_GTRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"

# Entertainment RSS with DIRECT publisher links (real og:image stills, unlike Google-News
# redirect links) + heavy MCU coverage. Filtered to Marvel by keyword so non-Marvel
# movie/TV items don't crowd the beat.
_MARVEL_FEEDS = {
    "ScreenRant": "https://screenrant.com/feed/",
    "Collider": "https://collider.com/feed/",
    "CBR": "https://www.cbr.com/feed/",
    "ComicBook": "https://comicbook.com/feed/",
}
_MARVEL_KW = (
    "marvel", "mcu", "avengers", "spider-man", "spiderman", "spider man", "wolverine",
    "x-men", "x-force", "deadpool", "fantastic four", "thunderbolts", "daredevil", "loki",
    "doomsday", "kang", "mutant", "insomniac", "venom", "symbiote", "doctor doom", "doom",
    "captain america", "iron man", "thor", "hulk", "black panther", "blade", "fantastic 4",
    "miles morales", "peter parker", "secret wars", "vision", "wandavision", "ironheart",
)


def _ssl():
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass


def _feed_titles(xml: str, limit: int) -> list[dict]:
    """Parse RSS/Atom titles + links + pubDate from a feed body (stdlib only)."""
    out: list[dict] = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for it in items[:limit]:
        def _t(tag):
            # NB: `it.find(a) or it.find(b)` is BROKEN in ElementTree — a childless
            # element (e.g. a text-only <title>) is falsy, so `or` wrongly falls
            # through. Use explicit `is None` checks.
            e = it.find(tag)
            if e is None:
                e = it.find("{http://www.w3.org/2005/Atom}" + tag)
            return (e.text or "").strip() if e is not None and e.text else ""
        title = _t("title")
        if not title:
            continue
        link_e = it.find("link")
        link = ""
        if link_e is not None:
            link = (link_e.text or "").strip() or link_e.get("href", "")   # RSS text vs Atom href
        out.append({"title": title, "pub": _t("pubDate") or _t("published"), "link": link})
    return out


def _news_queries() -> list[str]:
    try:
        from core.config import CONFIG
        return list((CONFIG.raw().get("trends", {}) or {}).get("news_queries", []) or [])
    except Exception:
        return []


def scout(*, news_per_feed: int = 8, yt_max: int = 15, geo: str = "US") -> list[dict]:
    """Return candidate topics as [{title, source, kind}] from all reachable sources.
    Fail-OPEN per source: one unreachable feed never sinks the scan. When the page has a
    focused beat (config trends.news_queries), those on-topic Google-News searches lead and
    the broad mainstream sources (YouTube trending, Google Trends) are skipped as noise."""
    _ssl()
    from urllib.parse import quote_plus
    import requests
    cands: list[dict] = []
    queries = _news_queries()

    # 1) Marvel entertainment feeds FIRST — DIRECT publisher links = real og:image stills
    #    for the news card. Filtered to Marvel so the beat stays dense.
    for name, url in _MARVEL_FEEDS.items():
        try:
            r = requests.get(url, headers=_UA, timeout=15)
            for it in _feed_titles(r.text, 25):
                if any(k in it["title"].lower() for k in _MARVEL_KW):
                    cands.append({"title": it["title"], "source": f"news:{name}",
                                  "kind": "news", "link": it.get("link", "")})
        except Exception:
            continue

    # 2) FOCUSED Google-News RSS searches (great topic discovery; the card falls back to a
    #    web-image search when a google-news redirect link yields no usable hero image).
    for q in queries:
        try:
            url = ("https://news.google.com/rss/search?q=" + quote_plus(q)
                   + "&hl=en-US&gl=US&ceid=US:en")
            r = requests.get(url, headers=_UA, timeout=15)
            for it in _feed_titles(r.text, 5):
                cands.append({"title": it["title"], "source": "gnews",
                              "kind": "news", "link": it.get("link", "")})
        except Exception:
            continue

    # 3) gaming news RSS (covers Insomniac/Marvel game news too; analyst filters to beat)
    for name, url in _NEWS_FEEDS.items():
        try:
            r = requests.get(url, headers=_UA, timeout=15)
            for it in _feed_titles(r.text, news_per_feed):
                cands.append({"title": it["title"], "source": f"news:{name}",
                              "kind": "news", "link": it.get("link", "")})
        except Exception:
            continue

    # 4) broad sources — only when NO focused beat is set (else they're pure noise)
    if not queries:
        try:
            from core import youtube
            res = youtube._service().videos().list(
                part="snippet,statistics", chart="mostPopular", videoCategoryId="20",
                regionCode=geo, maxResults=yt_max).execute()
            for it in res.get("items", []):
                sn = it.get("snippet", {})
                cands.append({"title": sn.get("title", ""), "source": "youtube:trending",
                              "kind": "video", "channel": sn.get("channelTitle", "")})
        except Exception:
            pass
        try:
            r = requests.get(_GTRENDS_RSS.format(geo=geo), headers=_UA, timeout=15)
            for it in _feed_titles(r.text, 25):
                cands.append({"title": it["title"], "source": "gtrends:daily", "kind": "trend"})
        except Exception:
            pass

    # de-dup near-identical titles
    seen, uniq = set(), []
    for c in cands:
        k = re.sub(r"[^a-z0-9 ]", "", c["title"].lower()).strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def analyze(candidates: list[dict], *, games: Optional[list[str]] = None,
            exclude: Optional[list[str]] = None, top_n: int = 5,
            focus: str = "") -> list[dict]:
    """LLM Trend ANALYST: rank the candidates for the KG Facebook page, filtered to the
    page's BEAT (config trends.focus — currently MCU + Insomniac's Marvel games). Prefers
    RISING / pre-peak topics with high relevance + postability; returns the top_n each with
    {topic, why_rising, stage, relevance, angle, game, source_index}. `exclude` = topic keys
    already posted (skip them). Returns [] on parser failure (fail-safe). It is fine to
    return FEWER than top_n (or none) if nothing on-beat is worth posting."""
    from agents.content import _text, extract_json
    if not candidates:
        return []
    games = games or []
    if not focus:
        try:
            from core.config import CONFIG
            focus = str((CONFIG.raw().get("trends", {}) or {}).get("focus", "")).strip()
        except Exception:
            focus = ""
    listing = "\n".join(
        f"{i+1}. [{c.get('source','?')}] {c.get('title','')}" for i, c in enumerate(candidates[:80]))
    excl = ("\nALREADY POSTED (do NOT pick these or close variants): "
            + "; ".join(exclude[:40])) if exclude else ""
    beat = (f"THIS PAGE'S BEAT — pick ONLY topics that clearly fit it: {focus}\n\n"
            if focus else "")
    gline = (f"Our own Insomniac Marvel games are: {', '.join(games)}. " if games else "")
    prompt = (
        "You are a TREND ANALYST for a Marvel-focused fan Facebook page (KiwinoyGamer). "
        f"{beat}{gline}Below are candidate topics scraped from news feeds. Pick the BEST "
        f"{top_n} ON-BEAT topics to post about RIGHT NOW to maximize reach.\n\n"
        "Judge each on:\n"
        "- FIT: does it clearly belong to the page's beat above? If NOT, DISCARD it — never "
        "pick an off-beat topic just to fill the list. Returning fewer (or zero) is correct.\n"
        "- STAGE: is it RISING / about-to-explode (BEST), already PEAKING (ok, but late), "
        "or DECLINING (skip)? Prefer fresh trailers, casting, release dates, new "
        "releases/DLC/updates, sales milestones, and building hype over old news.\n"
        "- POSTABILITY: can we make an ACCURATE, engaging, non-controversial FB post + image "
        "about it? Skip pure politics, tragedies, adult, leaks/legally risky, or rumors you "
        "can't state accurately.\n\n"
        f"CANDIDATES:\n{listing}{excl}\n\n"
        'Return ONLY JSON: {"picks":[{"topic":"short clear topic","why_rising":"1 line",'
        '"stage":"rising|peaking|declining","relevance":1-10,"angle":"the specific post '
        'angle/hook for KG","game":"the MCU property or Insomniac game (or \'MCU\')",'
        '"source_index":the CANDIDATE NUMBER (integer) this pick is based on}]}. Order picks '
        "best-first; include only ON-BEAT rising/peaking ones.")
    try:
        d = extract_json(_text(prompt, timeout=150))
        picks = d.get("picks", []) if isinstance(d, dict) else []
        return [p for p in picks if isinstance(p, dict) and p.get("topic")][:top_n]
    except Exception as e:
        print(f"[trends] analyst failed ({e!r}).", flush=True)
        return []
