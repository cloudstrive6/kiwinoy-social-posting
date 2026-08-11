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
        out.append({"title": title, "pub": _t("pubDate") or _t("published")})
    return out


def scout(*, news_per_feed: int = 8, yt_max: int = 15, geo: str = "US") -> list[dict]:
    """Return candidate topics as [{title, source, kind}] from all reachable sources.
    Fail-OPEN per source: one unreachable feed never sinks the scan."""
    _ssl()
    import requests
    cands: list[dict] = []

    # 1) gaming news RSS
    for name, url in _NEWS_FEEDS.items():
        try:
            r = requests.get(url, headers=_UA, timeout=15)
            for it in _feed_titles(r.text, news_per_feed):
                cands.append({"title": it["title"], "source": f"news:{name}", "kind": "news"})
        except Exception:
            continue

    # 2) YouTube trending gaming (our Data API)
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

    # 3) Google Trends daily RSS (mainstream breakouts; gaming filtered by the analyst)
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
            exclude: Optional[list[str]] = None, top_n: int = 5) -> list[dict]:
    """LLM Trend ANALYST: rank the candidates for a KG (gaming) Facebook page. Prefers
    RISING / pre-peak topics with high audience relevance + postability; returns the
    top_n each with {topic, why_rising, stage, relevance, angle, source}. `exclude` =
    topic keys already posted (skip them). Returns [] on parser failure (fail-safe)."""
    from agents.content import _text, extract_json
    if not candidates:
        return []
    games = games or []
    listing = "\n".join(
        f"{i+1}. [{c.get('source','?')}] {c.get('title','')}" for i, c in enumerate(candidates[:80]))
    excl = ("\nALREADY POSTED (do NOT pick these or close variants): "
            + "; ".join(exclude[:40])) if exclude else ""
    gline = (f"The channel's own games are: {', '.join(games)}. Lean toward these when "
             "relevant, but ANY hot gaming topic the audience cares about is fair game. "
             if games else "")
    prompt = (
        "You are a TREND ANALYST for a gaming Facebook page (KiwinoyGamer). Below are "
        "candidate topics scraped from gaming news, YouTube trending, and Google Trends. "
        f"{gline}Pick the BEST {top_n} to post about RIGHT NOW to maximize reach.\n\n"
        "Judge each on:\n"
        "- STAGE: is it RISING / about-to-explode (BEST), already PEAKING (ok, but late), "
        "or DECLINING (skip)? Prefer fresh announcements, new releases/DLC/updates, "
        "breaking news, and building hype over old news.\n"
        "- RELEVANCE to a mainstream gaming audience (console/PC/AAA/popular titles).\n"
        "- POSTABILITY: can we make an accurate, engaging, non-controversial FB post + "
        "image about it? Skip pure politics, tragedies, adult, or legally risky topics.\n"
        "Ignore non-gaming Google-Trends noise.\n\n"
        f"CANDIDATES:\n{listing}{excl}\n\n"
        'Return ONLY JSON: {"picks":[{"topic":"short clear topic","why_rising":"1 line",'
        '"stage":"rising|peaking|declining","relevance":1-10,"angle":"the specific post '
        'angle/hook for KG","game":"the game/franchise or \'gaming\'","source":"which '
        'candidate #/source"}]}. Order picks best-first; include only rising/peaking ones.')
    try:
        d = extract_json(_text(prompt, timeout=150))
        picks = d.get("picks", []) if isinstance(d, dict) else []
        return [p for p in picks if isinstance(p, dict) and p.get("topic")][:top_n]
    except Exception as e:
        print(f"[trends] analyst failed ({e!r}).", flush=True)
        return []
