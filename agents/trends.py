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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional


def _age_days(pub: str):
    """Age of an article in days from its RSS pubDate / Atom published, or None if we
    can't parse it. Used to drop STALE 'news' (a week-old story isn't news)."""
    if not pub:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(pub)                       # RFC-822 (RSS pubDate)
    except Exception:
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))   # ISO-8601 (Atom)
        except Exception:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0

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
                                  "kind": "news", "link": it.get("link", ""),
                                  "pub": it.get("pub", "")})
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
                              "kind": "news", "link": it.get("link", ""),
                              "pub": it.get("pub", "")})
        except Exception:
            continue

    # 3) gaming news RSS (covers Insomniac/Marvel game news too; analyst filters to beat)
    for name, url in _NEWS_FEEDS.items():
        try:
            r = requests.get(url, headers=_UA, timeout=15)
            for it in _feed_titles(r.text, news_per_feed):
                cands.append({"title": it["title"], "source": f"news:{name}",
                              "kind": "news", "link": it.get("link", ""),
                              "pub": it.get("pub", "")})
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

    # FRESHNESS GUARDRAIL: a week-old story isn't "news". Stamp each candidate's age and
    # DROP news we can date as older than trends.max_age_days (default 7). Undatable items
    # are kept (the analyst still judges recency) so we never silently lose everything.
    try:
        from core.config import CONFIG
        max_age = float((CONFIG.raw().get("trends", {}) or {}).get("max_age_days", 7) or 7)
    except Exception:
        max_age = 7.0
    fresh: list[dict] = []
    for c in cands:
        age = _age_days(c.get("pub", ""))
        c["age_days"] = None if age is None else round(age, 1)
        if age is not None and age > max_age:
            continue                                          # too old to post as news
        fresh.append(c)

    # de-dup near-identical titles (keep the FRESHEST when the same story repeats)
    fresh.sort(key=lambda c: (c.get("age_days") is None, c.get("age_days") or 0.0))
    seen, uniq = set(), []
    for c in fresh:
        k = re.sub(r"[^a-z0-9 ]", "", c["title"].lower()).strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def _history_brief() -> str:
    try:
        from core.marvel_history import history_brief
        return history_brief()
    except Exception:
        return ""


def analyze(candidates: list[dict], *, games: Optional[list[str]] = None,
            exclude: Optional[list[str]] = None, top_n: int = 5,
            focus: str = "", posted_log: str = "", history: str = "") -> list[dict]:
    """LLM Trend ANALYST: rank the candidates for the KG Facebook page, filtered to the
    page's BEAT (config trends.focus — currently MCU + Insomniac's Marvel games). Prefers
    RISING / pre-peak topics with high relevance + postability; returns the top_n each with
    {topic, why_rising, stage, relevance, angle, game, source_index}.

    Awareness inputs (all optional):
      - `exclude`     — posted topic KEYS (hard de-dup fallback).
      - `posted_log`  — readable digest of what we've ALREADY posted (newest first).
      - `history`     — established Marvel facts + when they became public; a topic that just
                        restates one of these is NOT news even if a fresh article ran today.
                        Defaults to core.marvel_history.history_brief() when not passed.

    Returns [] on parser failure (fail-safe). Returning FEWER than top_n (or none) is fine."""
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
    if not history:
        history = _history_brief()
    def _age_tag(c):
        a = c.get("age_days")
        return f"[{a:g}d ago]" if isinstance(a, (int, float)) else "[age?]"
    listing = "\n".join(
        f"{i+1}. {_age_tag(c)} [{c.get('source','?')}] {c.get('title','')}"
        for i, c in enumerate(candidates[:80]))
    # Prefer the readable posted-log; fall back to the bare key list.
    if posted_log:
        excl = ("\n\nWE ALREADY POSTED THESE (newest first) — do NOT pick any of them or a "
                f"close variant:\n{posted_log}")
    elif exclude:
        excl = "\n\nALREADY POSTED (do NOT pick these or close variants): " + "; ".join(exclude[:40])
    else:
        excl = ""
    known = ("\n\nALREADY ESTABLISHED / PUBLIC KNOWLEDGE — do NOT post any of these as if it's "
             "news; they've been public since the dates shown. Only a GENUINELY NEW development "
             f"on the topic is postable:\n{history}") if history else ""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    beat = (f"THIS PAGE'S BEAT — pick ONLY topics that clearly fit it: {focus}\n\n"
            if focus else "")
    gline = (f"Our own Insomniac Marvel games are: {', '.join(games)}. " if games else "")
    prompt = (
        "You are a TREND ANALYST for a Marvel-focused fan Facebook page (KiwinoyGamer). "
        f"TODAY is {today}. Each candidate is tagged with how many days ago it was published "
        f"[Nd ago].\n\n{beat}{gline}Below are candidate topics scraped from news feeds. Pick "
        f"the BEST {top_n} ON-BEAT topics to post about RIGHT NOW to maximize reach.\n\n"
        "Judge each on:\n"
        "- FRESHNESS (HARD RULE): this is a NEWS page. Posting stale news makes us look late "
        "and hurts the page. REJECT anything that isn't genuinely current — if it broke more "
        "than ~7 days ago, or the underlying event/release already happened a while back and "
        "is no longer being actively discussed, SKIP it even if it's on-beat. Strongly prefer "
        "the last 48-72 hours. Do NOT phrase an old update as if it just happened.\n"
        "- OLD FACT IN A FRESH ARTICLE (CRITICAL): news sites constantly publish roundups, "
        "explainers and 'everything we know' pieces that RESTATE facts which have been public "
        "for months or years. Judge the underlying DEVELOPMENT, not the article's publish "
        "date. If the core fact is already in the ESTABLISHED list below, or is general "
        "knowledge you've long known (e.g. a casting or release date announced long ago), it "
        "is NOT news — SKIP it. Only a NEW twist on the topic (new trailer, new plot detail, "
        "a change/delay, a just-released product) counts.\n"
        "- FIT: does it clearly belong to the page's beat above? If NOT, DISCARD it — never "
        "pick an off-beat topic just to fill the list. Returning fewer (or zero) is correct.\n"
        "- STAGE: is it RISING / about-to-explode (BEST), already PEAKING (ok, but late), "
        "or DECLINING (skip)? Prefer fresh trailers, casting, release dates, new "
        "releases/DLC/updates, sales milestones, and building hype over old news.\n"
        "- POSTABILITY: can we make an ACCURATE, engaging, non-controversial FB post + image "
        "about it? Skip pure politics, tragedies, adult, leaks/legally risky, or rumors you "
        "can't state accurately.\n\n"
        f"CANDIDATES:\n{listing}{excl}{known}\n\n"
        'Return ONLY JSON: {"picks":[{"topic":"short clear topic","why_rising":"1 line",'
        '"stage":"rising|peaking|declining","relevance":1-10,"angle":"the specific post '
        'angle/hook for KG","game":"the MCU property or Insomniac game (or \'MCU\')",'
        '"source_index":the CANDIDATE NUMBER (integer) this pick is based on}]}. Order picks '
        "best-first; include only ON-BEAT, genuinely-new rising/peaking ones.")
    try:
        d = extract_json(_text(prompt, timeout=150))
        picks = d.get("picks", []) if isinstance(d, dict) else []
        return [p for p in picks if isinstance(p, dict) and p.get("topic")][:top_n]
    except Exception as e:
        print(f"[trends] analyst failed ({e!r}).", flush=True)
        return []


def novelty_check(topic: str, angle: str = "", history: str = "") -> dict:
    """Dedicated 'is this actually NEW?' gate, run before an autopost/draft goes out.

    Catches the case the age filter can't: a genuinely-recent article that merely RESTATES
    a long-known fact (e.g. "RDJ revealed as Doctor Doom" in 2026 — public since July 2024).
    Returns {"new": bool, "known_since": str, "reason": str}. FAILS OPEN (new=True) on any
    parser/LLM error so a flaky call never silently blocks the whole pipeline."""
    from agents.content import _text, extract_json
    if not history:
        history = _history_brief()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        f"TODAY is {today}. You are a gate that stops a Marvel news page from posting OLD news "
        "as if it just happened.\n\n"
        f"FACTS ALREADY PUBLIC (since the dates shown):\n{history or '(none provided)'}\n\n"
        f"PROPOSED POST TOPIC: {topic}\n"
        f"ANGLE: {angle or '(none)'}\n\n"
        "Decide whether this topic is a GENUINELY NEW development (a new trailer/footage, a "
        "newly announced casting, a new/changed release date, a delay, a just-released "
        "product) OR a RESTATEMENT of something already publicly known for weeks, months or "
        "years — whether it's in the list above or is general knowledge from your own training. "
        "If it merely re-reports a long-known casting, plot point or date, it is NOT new. When "
        "genuinely unsure and it smells like an old, oft-repeated fact, treat it as OLD.\n"
        'Return ONLY JSON: {"new": true|false, "known_since": "YYYY-MM or date or empty", '
        '"reason": "one short line"}.')
    try:
        d = extract_json(_text(prompt, timeout=90))
        if isinstance(d, dict) and "new" in d:
            return {"new": bool(d.get("new")), "known_since": str(d.get("known_since", "")),
                    "reason": str(d.get("reason", ""))}
    except Exception as e:
        print(f"[trends] novelty_check failed ({e!r}) — allowing.", flush=True)
    return {"new": True, "known_since": "", "reason": "novelty check unavailable"}
