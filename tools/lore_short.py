"""LORE-CARD SHORTS — a short clip + a LONG text block people stop to read.

The format (researched 2026-10-06 from @moviemirrorbyavi + JeremyB's breakdown): the video
is ~8s but the text takes ~18s to read, so viewers loop it to finish. That records an average
view duration far longer than the video, which is what the Shorts algorithm rewards (their
numbers: ~80% stay-to-watch, ~300% watch time). The text is deliberately WORDY — a short
punchy line kills the mechanic.

Our version differs in the way that matters: THEY scrape movie clips (and bolt on a webcam
face to survive YouTube's reused-content policy); WE use our own capture, so there's nothing
to launder — and we have the game's subtitles + a lore bible, so the "fact" can be real.

    python tools/lore_short.py --clip "Wolverine (2026-09-16 01-43-07).mp4" --game wolverine
    python tools/lore_short.py --clip <path> --game wolverine --start 44 --dur 8
    python tools/lore_short.py ... --text "write my own card text"   # skip the writer

Output: output/lore-shorts/<stamp>_<game>/short.mp4 (1080x1920) + card.txt
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.content import (_observe_clip, _scan_subtitles, _strip_md, _text,  # noqa: E402
                            observe_frame_count, sanitize, unsafe_terms)
from core import b2_store, ffmpeg, frames  # noqa: E402
from core.config import CONFIG  # noqa: E402
from core.openai_client import extract_json  # noqa: E402

W, H = 1080, 1920
FONT_BODY = ROOT / "assets" / "fonts" / "montserrat" / "Montserrat.ttf"
FONT_HEAD = ROOT / "assets" / "fonts" / "anton" / "Anton-Regular.ttf"
LOGO = ROOT / "reels" / "assets" / "logo" / "KG Logo 2.PNG"
RED = (255, 61, 70)

# ~3.5 words/second is a comfortable silent-reading pace, so 55-70 words ~= 16-20s of reading
# against an 8s video: the viewer has to loop it, which is the whole point of the format.
# Bryce, 2026-11-22: keep cards at 60+ words, so viewers loop the clip to finish reading.
WORDS_MIN, WORDS_MAX = 40, 72  # Bryce, 2026-11-24: 40 to 72, a card ends when its facts do (was 60+)
# seconds of dialogue either side of the on-screen window, read for CONTEXT only
CTX_PAD = 10.0


def lore_seconds(lcfg: dict | None = None) -> float:
    """Target length of one lore clip. TRIAL from 2026-11-09 (user): a random 15-20s per post
    instead of a flat 8s, to test whether longer clips perform better. Config
    reels.gameplay.lore.seconds_min / seconds_max; without them the old flat `seconds` (8).
    build() trims this to the footage when the cutscene is shorter."""
    import random
    if lcfg is None:
        lcfg = (CONFIG.reels.get("gameplay", {}) or {}).get("lore", {}) or {}
    lo, hi = lcfg.get("seconds_min"), lcfg.get("seconds_max")
    if lo and hi and float(hi) >= float(lo):
        return round(random.uniform(float(lo), float(hi)), 1)
    return float(lcfg.get("seconds", 8))


class CardRefused(RuntimeError):
    """The card could not be supported by the evidence. A normal exception, NOT SystemExit:
    SystemExit skipped past every caller's `except Exception` and aborted the whole posting
    run, so one unsupported sentence cost the slot on every platform (bench 2026-10-08)."""


class NoFactFit(CardRefused):
    """No sourced fact is about this moment: skipped in seconds, and the slot's search does not count
    it as a costly try (orchestrator LORE loop)."""


def log(m: str) -> None:
    print(f"[lore-short] {m}", flush=True)


def research_scene(observation: str, subtitles: str, gname: str) -> str:
    """What the INTERNET says about THIS scene — Reddit threads, wikis, interviews, analysis.

    The card used to be limited to what the frames and subtitles show plus the lore bible,
    so the best it could do was explain the moment. The material that actually earns a
    'did you notice' short is the thing players argue about on r/SpidermanPS4, the cut
    content a wiki records, the line a developer explained in an interview (user's idea,
    2026-10-08). Returns a short evidence block, or '' when nothing specific turns up.
    """
    from core import claude_code
    prompt = (
        f"Research ONE specific scene from {gname} on the web and report what you find.\n\n"
        f"THE SCENE, as it appears on screen:\n{observation}\n\n"
        + (f"{subtitles}\n\n" if subtitles else "")
        + "Search Reddit (the game's subreddit and r/gaming), wikis, fandom pages, news "
        "articles, developer interviews and video essays for THIS scene specifically.\n"
        "Report only findings a casual player would NOT know from watching it once:\n"
        "- trivia, cut content, a detail the devs confirmed or explained\n"
        "- a popular fan reading, theory or argument about this moment\n"
        "- a connection to a later event, another game, or the comics the scene is setting up\n"
        "- voice acting, motion capture or writing notes about this specific scene\n\n"
        "RULES:\n"
        "- every line must be about THIS scene, not the game in general. A fact about the "
        "whole game is worthless here\n"
        "- say where each one comes from (subreddit, wiki, interview, article)\n"
        "- mark a fan theory as a fan theory. Never present speculation as confirmed\n"
        "- invent NOTHING. If the search turns up nothing specific, reply with exactly NONE\n\n"
        "Reply with up to 4 short bullet lines, or NONE."
    )
    try:
        out = (claude_code.run(prompt, web=True, timeout=300) or "").strip()
    except Exception as e:
        log(f"scene research unavailable ({e!r}) — writing from the clip alone.")
        return ""
    if not out or out.strip().upper().startswith("NONE"):
        log("scene research: nothing specific to this scene.")
        return ""
    out = "\n".join(_strip_md(l) for l in out.splitlines() if l.strip())[:1800]
    log(f"scene research:\n{out}")
    return out


FACTS_DIR = ROOT / "data" / "lore"
FACTS_SHOWN = 8


def fact_bank(game: str) -> list[dict]:
    """Sourced behind-the-scenes and did-you-know facts for a game (Bryce, 2026-11-19: the card
    may also carry "behind-the-scenes facts, the did-you-knows, anything about the game itself").
    data/lore/<game>-facts.json = {"facts": [{"id", "fact", "source", "wow" 1-5, "pairs_with"}]}."""
    f = FACTS_DIR / f"{game}-facts.json"
    try:
        return [x for x in json.loads(f.read_text(encoding="utf-8")).get("facts", []) if x.get("fact")]
    except Exception:
        return []


_STOP = set("that this with from your their there have what when where which while about into over them they "
             "then than were been will would could should just also only some more most very game player".split())


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in _STOP}


# Words that say nothing about WHAT a scene is about: a fact tagged 'Jason and Lucia' fits every clip.
_FIT_STOP = set("jason lucia both close ups scene clip cutscene moment story mission player character "
                "characters game vice city leonida playable controlled people person someone".split())
# Function words: never a topic, in any phrase.
_FIT_FUNC = set("and the for but not are was his her him she you its off out get got has had can any one two "
                "into onto from with this that".split())
# Everyday words: true of most clips, so a tag made only of these says nothing about the scene.
_FIT_WEAK = set("driving drive driven car view walking walk around town street life montage epic gameplay "
                "scenic cruising any crowd busy night day sunset cinematic skyline downtown with the radio on "
                "high speed highway road bridge".split())


def _tag_words(s: str, keep_names: bool = False) -> set:
    """Topic words for the fit check, singular ('cars' and 'car' match). keep_names keeps names and
    scene words ('switch Lucia' needs both), used for a fact's own fit phrases and for the scene."""
    out = set()
    for w in re.findall(r"[a-z]{3,}", (s or "").lower()):
        if len(w) > 5 and w.endswith(("sses", "shes", "ches", "xes")):
            w = w[:-2]                       # presses -> press, benches -> bench
        elif len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w in _FIT_FUNC or (w in _STOP and w not in ("player", "game")):
            continue
        if keep_names or w not in _FIT_STOP:
            out.add(w)
    return out


def _stem(w: str) -> str:
    if len(w) > 5 and w.endswith(("sses", "shes", "ches", "xes")):
        return w[:-2]                        # presses -> press, benches -> bench
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]                        # tops -> top, stars -> star
    return w


def _fit_tokens(s: str) -> set:
    """Every word and number, singular, nothing dropped: a fit phrase matches only when ALL its tokens
    are in the scene ('two heads' needs 'two', 'open 24 hours' needs '24'). Review 2026-11-26: dropping
    short words and digits turned 'two heads' into 'head' and matched any clip with a head in it."""
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", (s or "").lower().replace("'", ""))}


def _event_text(e: dict) -> str:
    """One footage-log event as plain text, from its own fields only (no 'money:' or 'quote:' labels,
    which matched 'money bag' on every moment in review)."""
    return " ".join(str(e.get(k, "") or "") for k in
                    ("what", "player_does", "others_do", "on_screen_text", "money", "quote"))


_USED_CACHE: dict = {}


def _used_facts() -> set:
    """Used fact ids, read once per 10 minutes (the picker checks many moments in a row)."""
    import time as _t
    if _USED_CACHE.get("at", 0) > _t.time() - 600:
        return _USED_CACHE["ids"]
    try:
        from core import gh_release
        ids = gh_release.used_story_quotes()
    except Exception:
        ids = set()
    _USED_CACHE.update(at=_t.time(), ids=ids)
    return ids


def fit_ranges(log_key: str, game: str) -> list[tuple[float, float]] | None:
    """The stretches (start, end seconds) of one recording whose footage log describes something a
    sourced fact is about. None when the clip has no log. Lets the picker skip a whole recording
    before downloading it, and pick windows that overlap a fitting stretch (2026-11-26)."""
    from core import b2_store
    if not fact_bank(game):
        return None                          # no fact bank for this game: no fit check (review 2026-11-26)
    memo = (log_key, game)
    if memo in _FIT_MEMO:
        return _FIT_MEMO[memo]
    key = f"footage-log/{log_key}.json"
    if key not in _LOG_CACHE:
        data = b2_store.get_bytes(key)
        _LOG_CACHE[key] = json.loads(data) if data else None
    log_ = _LOG_CACHE[key]
    if not log_:
        return None
    out = []
    for e in log_.get("events", []):
        if fact_fit(game, _event_text(e)):
            out.append((float(e.get("start", 0)), float(e.get("end", 0))))
    _FIT_MEMO[memo] = out
    return out


_FIT_MEMO: dict = {}


def fit_for_moment(name: str, game: str, start: float, dur: float) -> list[dict] | None:
    """The facts that fit the footage-log events inside the Short's own seconds, matched event by event
    (words from two events never combine). None when this game has no fact bank or the clip no log."""
    if not fact_bank(game):
        return None
    for key in (f"footage-log/cutscenes/{game}/{name}.json", f"footage-log/footage/{game}/{name}.json"):
        log_ = _LOG_CACHE.get(key)
        if not log_:
            continue
        best: dict = {}
        for e in log_.get("events", []):
            if float(e.get("end", 0)) > start + 0.5 and float(e.get("start", 0)) < start + dur - 0.5:
                for rank, x in enumerate(fact_fit(game, _event_text(e))):
                    k = str(x.get("id"))
                    if k not in best or rank < best[k][0]:
                        best[k] = (rank, x)
        return [x for _, x in sorted(best.values(), key=lambda t: (t[0], -float(t[1].get("wow", 3))))]
    return None


def fact_fit(game: str, scene: str, min_hits: int = 1) -> list[dict]:
    """The unused facts whose 'pairs with' tags name something in this scene (the footage log's
    account of the Short's own seconds), best fit first. No AI, a few milliseconds. On 2026-11-26
    the writer was offered police facts for 23 workout, wardrobe and garage moments in a row, stretched
    them onto the clip, and every card was refused; a moment no fact fits is now skipped in seconds."""
    sw = _tag_words(scene, keep_names=True)
    st = _fit_tokens(scene)
    if not st:
        return []
    bank = fact_bank(game)
    used = _used_facts()
    fresh = [x for x in bank if f"fact:{game}:{x.get('id')}" not in used] or bank
    scored = []
    for x in fresh:
        # A tag fits when EVERY topic word of that tag phrase is in the scene ('wanted level' needs
        # both words), and tags made only of everyday words ('driving', 'city view') never count:
        # they fit every clip, which is how a radio fact got offered for every drive.
        # A fact's own "fit" list (what must be visible for the fact to be about the moment, written
        # per fact on 2026-11-26) wins over the looser 'pairs with' tags. An empty list means the
        # fact is never about a moment on screen (sales, trailer views).
        hits = 0
        fit = x.get("fit")
        tags = [str(t) for t in fit] if isinstance(fit, list) else str(x.get("pairs_with", "") or "").split(",")
        for tag in tags:
            if isinstance(fit, list):
                tw = _fit_tokens(tag)
                ok = bool(tw) and tw <= st
            else:
                tw = _tag_words(tag) - _FIT_WEAK
                ok = bool(tw) and tw <= sw
            if ok:
                hits += len(tw)
        if hits >= min_hits:
            scored.append((hits, float(x.get("wow", 3)), x))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [x for _, _, x in scored]


def pick_facts(game: str, context: str = "", fitted: list[dict] | None = None) -> list[dict]:
    if fitted:
        # The fit check already chose the facts this scene is about; offer only those, so the writer
        # cannot reach for an unrelated high-wow fact and stretch the clip to fit it.
        return fitted[:FACTS_SHOWN]
    return _pick_facts(game, context)


def _pick_facts(game: str, context: str = "") -> list[dict]:
    """Up to FACTS_SHOWN unused facts. With a clip context (what is on screen plus the subtitles),
    the first slots go to the facts whose text and 'pairs with' tag share the most words with it,
    the rest to the highest wow (2026-11-24: the writer was offered trailer view counts for a robbery
    clip, found nothing relevant, and stretched the clip into invented claims). The bank starts over
    once every fact has been used."""
    bank = fact_bank(game)
    if not bank:
        return []
    try:
        from core import gh_release
        used = gh_release.used_story_quotes()
    except Exception:
        used = set()
    fresh = [x for x in bank if f"fact:{game}:{x.get('id')}" not in used] or bank
    random.shuffle(fresh)
    fresh.sort(key=lambda x: -float(x.get("wow", 3)))
    ctx = _words(context)
    if not ctx:
        return fresh[:FACTS_SHOWN]
    scored = sorted(fresh, key=lambda x: -(len(ctx & _words(f"{x.get('fact', '')} {x.get('pairs_with', '')}"))
                                            + 0.1 * float(x.get("wow", 3))))
    relevant = [x for x in scored if ctx & _words(f"{x.get('fact', '')} {x.get('pairs_with', '')}")][:5]
    rest = [x for x in fresh if x not in relevant]
    return (relevant + rest)[:FACTS_SHOWN]


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", str(url or "").strip())
    return m.group(1).lower() if m else str(url or "").strip()


OUTLETS = {"videogameschronicle": "VGC Video Games Chronicle", "kotaku": "Kotaku", "ign": "IGN",
           "gamespot": "GameSpot", "pcgamer": "PC Gamer", "rockstargames": "Rockstar Rockstar Games",
           "polygon": "Polygon", "eurogamer": "Eurogamer", "gamesradar": "GamesRadar", "thegamer": "TheGamer",
           "gamerant": "Game Rant", "dexerto": "Dexerto", "insider-gaming": "Insider Gaming", "theverge": "The Verge",
           "screenrant": "Screen Rant", "shacknews": "Shacknews", "pushsquare": "Push Square",
           "engadget": "Engadget", "vice": "Vice",
           # 2026-11-26, fact banks for every game: developers' own sites and more outlets.
           "insomniac": "Insomniac Insomniac Games", "playstation": "PlayStation PlayStation Blog",
           "naughtydog": "Naughty Dog", "halowaypoint": "Halo Waypoint Halo Studios", "xbox": "Xbox Xbox Wire",
           "gameinformer": "Game Informer", "techradar": "TechRadar", "mobilelegends": "Moonton Mobile Legends",
           "tarsier": "Tarsier Tarsier Studios", "bandainamco": "Bandai Namco"}
# How the card names each outlet (2026-11-26: a card wrote 'Videogameschronicle' from the bare domain).
OUTLET_SAY = {"videogameschronicle": "VGC", "rockstargames": "Rockstar", "insomniac": "Insomniac",
              "playstation": "the PlayStation Blog", "halowaypoint": "Halo Waypoint", "xbox": "Xbox Wire",
              "mobilelegends": "Moonton", "tarsier": "Tarsier"}


def outlet_names(text: str) -> str:
    """The names a card may credit for a fact, from its source domains (2026-11-25: a card crediting VGC
    for a videogameschronicle.com fact was refused because 'VGC' appeared in no evidence)."""
    # Domains only ('kotaku.com', 'blog.playstation.com'): a plain substring credited Vice for 'Vice City'
    # and IGN for 'design' (review 2026-11-26).
    low = (text or "").lower()
    return " ".join(v for k, v in OUTLETS.items() if re.search(rf"(^|[\s./,(]){re.escape(k)}\.", low))


def fact_source(x: dict) -> str:
    """Who reported a fact, as a domain ('kotaku.com'). The writer and the checker need it: a
    card turned a Kotaku preview into 'Rockstar confirmed...' because neither was ever told
    where the fact came from (Bryce, 2026-11-20)."""
    srcs = [x.get("source")] + list(x.get("sources") or [])
    return ", ".join(dict.fromkeys(_domain(s) for s in srcs if s)) or "unknown"


def outlet_say(x: dict) -> str:
    """The outlet names a card should write for a fact ('VGC and Kotaku'), from its source domains."""
    names = []
    for d in fact_source(x).split(", "):
        k = next((k for k in OUTLETS if re.search(rf"(^|\.){re.escape(k)}\.", d)), "")
        if k:
            names.append(OUTLET_SAY.get(k, OUTLETS[k]))
    return " and ".join(list(dict.fromkeys(names))[:2])


def facts_text(facts: list[dict]) -> str:
    return "\n".join(f"[{x.get('id')}] {x.get('fact')} (source: {fact_source(x)}"
                     + (f"; credit it as: {outlet_say(x)}" if outlet_say(x) else "")
                     + f"; pairs with: {x.get('pairs_with', 'any clip')})" for x in facts)


def mark_fact(game: str, fact_id: str) -> None:
    import os
    if not fact_id or os.environ.get("LORE_TEST"):  # LORE_TEST=1: a local test never uses up a fact
        return
    try:
        from core import gh_release
        gh_release.mark_story_quote(f"fact:{game}:{fact_id}")
        if "ids" in _USED_CACHE:             # so a second card in the same run cannot reuse it
            _USED_CACHE["ids"] = set(_USED_CACHE["ids"]) | {f"fact:{game}:{fact_id}"}
    except Exception as e:
        log(f"could not record used fact {fact_id} ({e!r})")


# AI-slop patterns (Bryce, 2026-11-24, after "AI generated garbage that doesn't even completely understand what
# it is talking about" on a GTA 6 card). Taken from the last fact cards: every one ended on a stock reaction and a
# stock comparison, and some narrated the HUD. A hit sends the card back to be rewritten.
SLOP = [
    (r"(?:^|[.!?]\s+)That(?:'s| is| was) (?!why\b|how\b|because\b|what\b|where\b|when\b|the reason\b|enough\b)(?:a |an |one |the )?(?:\w+ ){0,3}\w+[.!]", "a stock reaction line ('That is ...')"),
    (r"\bevery (?:gamer|player|streamer|fan|racing game player|souls player)\b", "an 'every gamer' comparison"),
    (r"\bclassic (?:gta|grand theft auto|drive|open.world)", "a 'classic GTA' comparison"),
    (r"\bthe kind of\b.*\b(?:dreams? about|knows?|loves?)\b", "a 'the kind of ... every X dreams about' line"),
    (r"\bnot included\b", "a quip ('... not included')"),
    (r"\b(?:ice cold|chef's kiss|hits different|peak gta|wild)\b", "a hype or reaction word"),
    (r"\b(?:spiral|long memory|with no door|in paperback form|closing time)\b", "a metaphor that restates the fact"),
    (r"\bit (?:plays|reads|feels) like\b", "an 'it plays like' comparison"),
    (r"\b(?:wishes|wished) (?:this|that) existed\b", "a 'wishes this existed' line"),
    (r"\b(?:ticks down|ticks up|on your minimap|the menu lands on|the camera (?:pans|cuts))\b", "screen play-by-play"),
    (r"\bthe lore\b|\blore bible\b|\bthe bible\b", "an uncheckable source ('the lore', 'the lore bible'); name the in-game or Rockstar source, or drop the claim"),
]


def slop_problems(text: str) -> list[str]:
    return [why for pat, why in SLOP if re.search(pat, text or "", re.I)]


def fan_critic(card: dict, observation: str, subtitles: str, gname: str) -> tuple[int, str, list]:
    """A real-fan read of the card (subscription only). (score 1 to 10, notes). 10 = a player learns
    something real and would share it; 1 = AI slop that misreads the game."""
    from core import claude_code
    prompt = (
        f"You are a hardcore {gname} player who comments on gaming Shorts and has no patience for AI "
        "slop. A channel wants to post this text card over a gameplay clip.\n\n"
        f"What the clip shows:\n{observation}\n\n" + (f"{subtitles}\n\n" if subtitles else "")
        + f"HEADLINE: {card.get('headline', '')}\nBODY: {card.get('body', '')}\n"
        f"COMMENT: {card.get('comment', '')}\n\n"
        "Score it 1 to 10. 10: you learned a real, specific thing about the game (a mechanic with "
        "its number, a cost, a hidden rule, a trick, a line that means more than it sounds) and "
        "would send it to a friend. 1: AI slop, meaning filler reactions, stock comparisons, "
        "metaphors that restate the obvious, describing what is already on screen, or getting the "
        "game wrong. House rules you must NOT mark down: a number that is not on screen has to "
        "name its source ('guides list', 'Kotaku reports'), so sourced attribution is correct, not "
        "hedging; the comment line may be a dry joke as long as it states nothing untrue. A claim about how "
        "the game works (what causes, clears, raises or lowers something, what you must do) that the clip "
        "does not show and no named source backs is WRONG even if it sounds plausible; so is anything "
        "the clip summary says happens outside the Short. A card that ends on a true, sourced fact "
        "with no tip is fine: never mark it down for lacking advice, and in 'better' never ask for a "
        "tip, rule, cause or number that neither the clip nor a source named in the card states. Name every "
        "sentence that is filler or wrong, and say what a real fan would want this card to say "
        "instead. Reply with JSON only: "
        '{"score": <1-10>, "filler": ["..."], "wrong": ["..."], "better": "..."}')
    try:
        d = extract_json(claude_code.run(prompt, timeout=200, paid_fallback=False))
        notes = "; ".join([f"filler: {x}" for x in d.get("filler", [])] + [f"wrong: {x}" for x in d.get("wrong", [])])
        if d.get("better"):
            notes += f"; a fan wants: {d['better']}"
        wrong = [str(x) for x in d.get("wrong", []) if str(x).strip()]
        return int(d.get("score") or 0), notes[:600], wrong
    except Exception as e:
        return 0, f"the fan critic could not run ({e!r})"[:200], []


FAN_MIN = 7   # a card under this is rewritten (twice, with the critic's notes), then refused


def _write_card(observation: str, subtitles: str, game: str, gname: str, avoid: str = "",
                research: str = "", facts: str = "") -> dict:
    """The card: a short EYEBROW line + the long body text, grounded in this clip."""
    from core import lore
    bible = lore.lore_for(game) or ""
    prompt = (
        f"You write 'did you notice' cards for {gname} gameplay shorts.\n\n"
        f"WHAT IS ON SCREEN:\n{observation}\n\n"
        + (f"{subtitles}\n\n" if subtitles else "")
        + (f"GAME LORE (for context — never contradict it):\n{bible}\n\n" if bible else "")
        + (f"WHAT PLAYERS AND WRITERS SAY ABOUT THIS SCENE (researched online — Reddit, "
           f"wikis, interviews):\n{research}\n\nTHIS RESEARCH IS CONTEXT ONLY (Bryce, 2026-11-24: "
           "cards must not invent or relay unchecked claims). Use it to understand who is who and "
           "what is happening. NEVER state a research finding in the card unless the same thing is "
           "in the VERIFIED GAME FACTS below or plainly on screen.\n"
           "BUT THE FOOTAGE OUTRANKS THE RESEARCH, ALWAYS. The research may have found a "
           "DIFFERENT scene that sounds like this one. If any finding disagrees with WHAT IS "
           "ON SCREEN above — who is doing what to whom, who is awake, where they are — the "
           "screen wins and you DROP that finding. Never import an event (a flashback, an "
           "object, a trigger) the frames do not show, and never reverse who is acting on "
           "whom to match a research note (user, 2026-10-09).\n"
           "A finding the research marks as unconfirmed, possible, rumoured or a fan theory is "
           "NEVER stated as fact, and a place name from it never goes in the card as where "
           "this happens.\n\n"
           if research else "")
        + (f"VERIFIED GAME FACTS (each one sourced; behind-the-scenes, development, records, "
           f"real-world inspirations, did-you-knows):\n{facts}\n\n"
           "You MAY build the card on ONE of these facts instead of on the scene, when it fits "
           "the KIND of moment on screen (its 'pairs with' note, or the place or activity you "
           "can see). This is the 'did you know' card, and viewers love a fact they never knew. "
           "Then beat 1 ties the fact to what is on screen in a few words, beat 2 IS the fact, "
           "told in your own words with every number and name exactly as given, and beat 3 (only "
           "when the fact itself states one) is what it means for a player (a cost, a risk, a use, "
           "a tip); when the fact states no consequence, the card ends on the fact. Never claim the clip itself shows the fact's "
           "subject unless the frames do (a fact about a trailer scene is not this clip). "
           "ADD NOTHING TO THE FACT: no claim the fact does not make, no superlative ('most', "
           "'first', 'only', 'biggest') unless the fact says it, no invented process or motive "
           "('Rockstar studied', 'documented', 'visited', 'on purpose'). The listed fact(s) you cite are the "
           "only true things you have; beats 1 and 2 must contain nothing else except what is visibly "
           "on screen (a test card invented 'Rockstar's most sourced region', 2026-11-19). "
           "WHO SAID IT: credit a fact only to its listed source ('Kotaku reports', 'previews "
           "say') or to nobody. Never write 'Rockstar confirmed', 'Rockstar revealed' or 'the "
           "developers said' unless the source is Rockstar or the fact itself says Rockstar "
           "said it. NO NEW NAMES OR LABELS: no place, district, building or 'his safehouse' "
           "unless the fact names it or it is readable on screen, and no label for the feature "
           "the fact does not use ('RPG-lite', 'physique system', 'connects to'). A card added "
           "'Rockstar confirmed' and 'his Key Lento safehouse' to a Kotaku fact (2026-11-20). "
           "Credit a fact with the outlet names its 'credit it as' note gives, and keep the credit in "
           "every sentence that states part of that fact ('Dexerto reports the level holds there, and "
           "that a cop who spots you restarts the chase'), never one credit followed by bare claims. "
           "Put the main fact's id in fact_id; a second listed fact must also be in your facts list by its id. If no fact fits, write a scene card and leave "
           "fact_id empty.\n\n"
           if facts else "")
        + "FIRST DECIDE THE MODE (Bryce, 2026-11-22: what YOU can do in the game is not the same "
        "thing as what the CHARACTER does in the story):\n"
        "- \"player\": the clip shows the player in control: HUD, minimap, button prompts, "
        "menus, tooltips, a toast or notice, free movement, an activity or system (gym, shops, "
        "food, wanted level, cars, money). The card is about what YOU can do or what the game "
        "does to you. Speak to the viewer: 'you', 'your'. Never tell it as a story event that "
        "happened to the character ('the gym shuts on Jason' is wrong; 'the gym locks you out "
        "after one session' is right).\n"
        "- \"story\": a scripted scene: cinematic framing, no HUD, mission dialogue, a cutscene. "
        "The card is about what the CHARACTER does or says in the story. Name the character. "
        "NEVER write 'you can' or 'you get to' about a scripted story beat, and never sell a "
        "mission moment as a feature the player chooses.\n"
        "If a fact from the list is used, its mode follows the fact: a mechanic is player, a "
        "story or production fact is story.\n\n"
        "WRITE FOR A PLAYER WHO KNOWS THE GAME (Bryce, 2026-11-24, after a viewer called a card "
        "'AI generated garbage that doesn't even completely understand what it is talking about'). "
        "The card is only worth posting if a GTA player learns something they would screenshot and "
        "send a friend: a real mechanic with its number, a cost, a hidden rule, a trick, a "
        "consequence, a line that means more than it sounds. Every sentence must carry a NEW piece "
        "of checkable information or a concrete use of it. NO FILLER SENTENCES: no reaction "
        "lines ('That is ice cold.', 'That is confident.', 'Dignity not included.'), no 'every "
        "gamer knows' or 'classic GTA' comparisons, no metaphors that restate the fact ('a vault "
        "with no door', 'a notification with a long memory'), no hype. If you only have one fact, "
        "add a second one from the listed facts or the lore, or stop short; never pad, and never "
        "invent a consequence or tip to fill space.\n\n"
        "Write a card about THIS moment, a HEADLINE then three beats, as ONE paragraph:\n"
        "  0. HEADLINE (Bryce, 2026-11-22: lead with the surprise): 6 to 8 words, shown big "
        "above the body. The single most surprising true thing in the card, said plainly "
        "('The gym locks you out after one session', 'Lucia pawns her necklace for a room'). "
        "No game name, no 'In GTA 6', no question unless the body answers it, no clickbait, "
        "no colon, nothing the body does not support.\n"
        f"  1. CONTEXT: straight into the situation in a few words. NEVER open with 'In {gname}' "
        "or 'In GTA 6' or any 'In <game>' phrase: the headline already did the job.\n"
        "  2. THE DETAIL: the specific thing worth knowing, with its number, name or rule, and "
        "what it MEANS as a listed fact, the subtitles or on-screen text says it (never a meaning "
        "you worked out yourself, 2026-11-26). This is the heart of the card.\n"
        "  3. WHAT TO DO WITH IT (OPTIONAL, 2026-11-26): a consequence or tip for a player (what "
        "it costs, what to do first, what to avoid) ONLY when a listed fact, the subtitles or "
        "on-screen text states it; for a story moment, what the line reveals ONLY when the "
        "subtitles or a fact say it. When nothing states one, leave beat 3 out and end on beat "
        "2: a card that ends on a true, sourced fact is a GOOD card. A tip, rule or consequence "
        "you worked out yourself gets the card refused (19 cards in a row on 2026-11-25 were "
        "refused for exactly this). Information, never a reaction.\n\n"
        "FUNNY CLIPS (Bryce, 2026-11-20): when WHAT IS ON SCREEN says the TONE is funny, the "
        "COMMENT line carries the joke. The body still teaches something true (from the "
        "subtitles, the lore bible or a listed fact). Never invent an engine, physics or AI "
        "reason for a gag.\n\n"
        f"- \"body\": beats 1 to 3 (beat 3 optional), {WORDS_MIN}-{WORDS_MAX} WORDS. The length IS the format: "
        "it must take ~15 seconds to read, about as long as the clip or longer, so the viewer "
        "stays to finish it. "
        "Plain spoken English, present tense, no hype words, no emojis, no hashtags.\n"
        "- \"highlight\": a SHORT phrase (2-6 words) copied EXACTLY from your body — the pivot "
        "of beat 2, coloured gold on screen.\n"
        "- \"comment\": one short funny/knowing reaction line, like a top YouTube comment on "
        "this moment (max 90 chars). Dry humour, no emojis, no hashtags.\n\n"
        "THE CARD EXPLAINS, IT NEVER NARRATES THE PICTURE. The viewer is watching the same "
        "footage, so telling them what is on screen is worthless — a card that reads like a "
        "scene description is a FAILED card. Give them what they CANNOT see: what the line "
        "means as the subtitles or a listed fact give it, what a listed fact says about it. "
        "NEVER make clothing, hair, "
        "lighting, colour, the camera, the UI, an on-screen caption or a character's face the "
        "POINT of the card. Never write 'the scene opens on', 'watch his face', 'a teen in a "
        "grey t-shirt', 'a man in a lab coat', 'in a green-lit lab'. If the only thing you can "
        "say about this moment is what it looks like, you have NO card — say that instead of "
        "padding the body with description.\n\n"
        "ACCURACY IS EVERYTHING — a gaming audience catches invented trivia instantly:\n"
        "- use ONLY what the screen and the subtitles above show, plus the lore bible\n"
        "- never invent a developer intention, a camera trick, a statistic or a hidden detail "
        "you cannot see in the evidence. Every beat must be literally true of this clip or "
        "stated by a listed fact or the lore bible\n"
        "- you MAY name a character whose subtitle speaker label appears, AND one the lore "
        "bible identifies unmistakably from what is on screen (its visual tells plus who is "
        "with whom in that part of the story). Vagueness is not safety: 'someone whose eyes "
        "stay shut' for a companion the bible plainly identifies reads as a mystery the "
        "scene does not have. If the bible does not settle it, describe the person plainly "
        "instead ('her partner', 'the man in the lab coat') and imply nothing more\n"
        "- NEVER imply a darker state than the evidence shows. Someone asleep or resting is "
        "ASLEEP — not unconscious, not dying, not gone. Do not write 'eyes stay shut', 'will "
        "not wake', 'motionless' about a sleeping character, and do not hint at injury or "
        "death that the clip and the bible do not support (user, 2026-10-09)\n"
        "- do not quote a line verbatim if it contains profanity; describe it instead\n"
        "- NEVER invent a NUMBER or a DURATION — no 'five years later', 'after three days', "
        "'the only time in the series' — unless that exact figure is in the lore bible or on "
        "screen. Fans check these. Say 'years later' or 'for a long time' instead\n"
        "- the COMMENT line is posted too and is held to the same standard; it may be funny, "
        "but it may not state anything untrue. It is OPTIONAL: leave it empty (\"\") unless it "
        "only restates what the clip shows. Most refused cards failed on a comment line\n"
        "WHAT GETS CARDS REFUSED (2026-11-25: every card of a whole slot was refused for these; "
        "the checker is right, so write so it has nothing to catch):\n"
        "- widening what the clip shows: 'every stop' when two are shown, 'the whole tab' when "
        "the line says 'pays the drinks', 'nothing else', 'always', 'never', 'across the city'. "
        "Say exactly as much as the screen or the line says, no more\n"
        "- a tip or rule ('change your look before the crime', 'trust the prompt over the "
        "distance') that is not written in a listed fact or on screen. Advice is allowed only "
        "when a listed fact states it\n"
        "- any number not on screen or in a fact (a distance, 'ten feet', a count)\n"
        "- naming who is played when WHAT REALLY HAPPENS says it is only likely; say 'the "
        "player' instead\n"
        "- a reaction or vibe line ('peak innocent-bystander energy'); end on the fact\n"
        "- a time into the clip ('from about 0:09', 'nine seconds in'): the log's times differ "
        "by a second, so say 'then' or 'a moment later' instead\n"
        "- a cause or link nobody states ('which is why the level follows you indoors', 'so a "
        "new look brings the stars down'): put the fact and the picture side by side and let "
        "the viewer connect them; never write 'so', 'which is why' or 'that is how' between them unless the fact itself "
        "states that link\n"
        "- saying the clip shows the fact happening when it does not (the fact is about "
        "swapping clothes and nobody swaps clothes): tell the fact as a fact about the game "
        "('Kotaku reports that ...'), not as what happens in this clip\n"
        "MATCH THE PICTURE (Bryce, 2026-11-22, after a card gave Danny's line to Lucia and "
        "described a shrug nobody could see):\n"
        "- give a spoken line ONLY to the speaker whose label shows with it in the subtitles; "
        "if no label, say 'someone' or leave the speaker out\n"
        "- never describe a gesture, look, shrug, smile or expression unless WHAT IS ON SCREEN "
        "states it\n"
        "- every number carries its unit and what it counts ('33 percent of the gym bar per "
        "day', never 'about 33 percent per day')\n"
        "- no story spoilers beyond what this clip itself shows: never reveal who dies, who "
        "betrays whom, a twist or an ending, and never NAME a later mission or chapter\n"
        "- quote or paraphrase only what the subtitles actually say; name a car, item or menu "
        "option only as it reads on screen or in the fact\n"
        "- the HEADLINE's subject must be visible in this clip (the notice, menu, action or "
        "moment itself), not something that only happens later; if the clip never shows it, "
        "headline what the clip DOES show. A fact card's headline may instead state its listed "
        "fact, adding nothing to it and keeping its hedges ('can', 'might'), with no number "
        "that is not on screen, when the clip shows the kind of moment the fact is about "
        "(a police fact on a wanted-level clip)\n"
        "- one consistent story: never say two things that contradict each other\n"
        "- a number or stat the clip does not show on screen must say where it comes from in "
        "the same sentence ('guides list pull-ups at +5% Strength'); never state an off-screen "
        "number as if the viewer can see it (test card, 2026-11-22)\n"
        "PAYOFF TIMING: the frames above carry times ('frame 4 at ~0:09'). Give \"payoff_at\": "
        "the seconds into the clip where the thing the headline is about is FIRST clearly on "
        "screen (0 if it is there from the start). Give \"text_evidence\": true only when that "
        "payoff is small in-game text the viewer must read (a toast, tooltip, menu line or "
        "notice), else false.\n"
        + "\nFACTS FIRST (2026-11-24, the fan critic's top complaints were screen description, "
        "sentences that restate the one before, and soft metaphors): before writing, list in "
        "\"facts\" the 2 to 4 specific, checkable things you have for this card. Each ends with its "
        "source tag in brackets, and ONLY these tags exist: (screen) for an on-screen number, notice, "
        "menu or tooltip, (subtitles) for a spoken line, (fact gta6-NN) for a VERIFIED GAME FACT by its "
        "id, (bible) for the lore bible. The bible is for YOUR checking only: the card itself never "
        "says 'the lore', 'the lore bible' or 'the bible' (a viewer cannot look it up, and fans call it "
        "out, 2026-11-24); a bible fact on the card must name where it comes from in the game or from "
        "Rockstar (a trailer, a mission, an in-game notice) as the bible entry says, or stay off the card. "
        "Nothing else is a source: not research, not 'guides', not "
        "your own knowledge of the game, not a website. Build the card on ONE verified game fact "
        "whenever the clip has fewer than two strong on-screen or spoken facts. A thing the viewer "
        "can plainly see is NOT a fact for this list unless a listed fact says what it means or costs. "
        "Then write the body so that EVERY sentence carries a different item from that list or a "
        "concrete use of one. The first sentence states a fact, never a description of the shot. "
        "No sentence may repeat the previous one in other words. If you run out of facts, STOP: "
        "40 words of real information beats 70 with padding (Bryce, 2026-11-24).\n"
        + (f"\nA PREVIOUS attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + ('\nReturn ONLY JSON: {"facts": ["fact (source)", "..."], "mode": "player or story", "headline": "6 to 8 words", '
           '"body": "the paragraph", "highlight": "exact phrase from the '
           'body", "comment": "the reaction line", "payoff_at": 0, "text_evidence": false'
           + (', "fact_id": "id of the fact used, or empty"' if facts else '') + '}')
    )
    try:
        d = extract_json(_text(prompt, timeout=240)) or {}
        try:
            payoff = max(0.0, float(d.get("payoff_at", 0) or 0))
        except (TypeError, ValueError):
            payoff = 0.0
        mode = str(d.get("mode", "") or "").strip().lower()
        return {"mode": mode if mode in ("player", "story") else "",
                "headline": re.sub(r"\s+", " ", sanitize(str(d.get("headline", "")))).strip()[:70],
                "highlight": sanitize(str(d.get("highlight", ""))).strip()[:60],
                "comment": sanitize(str(d.get("comment", ""))).strip()[:90],
                "body": re.sub(r"\s+", " ", sanitize(str(d.get("body", "")))).strip(),
                "payoff_at": payoff, "text_evidence": bool(d.get("text_evidence")),
                "fact_id": str(d.get("fact_id", "") or "").strip()[:40],
                "facts": [str(x)[:300] for x in (d.get("facts") or []) if str(x).strip()][:6]}
    except Exception as e:
        log(f"card writer failed ({e!r})")
        return {}


_SOURCE_TAG = re.compile(r"\((screen|subtitles?|bible|fact\s+([a-z0-9]+-\d+))\)\s*$", re.I)


def fact_source_problems(card: dict, fact_ids: set) -> list[str]:
    """Every listed fact must carry an allowed source tag; a (fact id) tag must be a real bank id
    (Bryce, 2026-11-24: no invented sources, prices or rules on a card)."""
    facts = card.get("facts") or []
    if len(facts) < 2:
        return ["the card lists fewer than 2 sourced facts"]
    bad = []
    for f in facts:
        m = _SOURCE_TAG.search(f.strip())
        if not m:
            bad.append(f"'{f[:70]}' has no allowed source (screen, subtitles, fact id, bible)")
        elif m.group(2) and m.group(2).lower() not in fact_ids:
            bad.append(f"'{f[:70]}' cites a fact id that is not in the bank")
    return bad


_QUOTE = re.compile("[“\"]([^”\"]{6,}?)[”\"]|(?<![A-Za-z0-9])[‘']([^\n]{6,}?)[’'](?![A-Za-z0-9])")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9$ ]+", " ", t.lower())).strip()


def quote_problems(text: str, heard: str) -> list[str]:
    """A line in quote marks must be word for word what is said or shown in the Short (2026-11-24:
    a card quoted 'take whatever you came for' for 'Just take whatever you came in for')."""
    hay = _norm(heard)
    bad = []
    for m in _QUOTE.finditer(text or ""):
        raw = (m.group(1) or m.group(2) or "").strip()
        q = _norm(raw)
        if len(q.split()) >= 3 and q not in hay:
            bad.append(raw)
    return bad


# Wording that only ever appears when the writer has narrated the footage instead of
# explaining it. A YouTube Short shipped "the scene opens on a caption reading TWO YEARS AGO,
# in a green-lit Oscorp lab. Harry, a teen in a grey-green t-shirt..." — the viewer can SEE
# all of that; the card's whole job is the part they cannot (user, 2026-10-08).
_DESCRIBES = (
    "the scene opens", "the camera", "the shot ", "this shot", "the frame", "on screen",
    "a caption reading", "the caption reads", "text on screen", "watch his face",
    "watch her face", "watch their face", "in the background", "we see ", "you can see",
    "wearing a", "in a grey", "in a green", "in a blue", "in a red", "in a black",
    "in a white", "t-shirt", "lab coat", "-lit ", "glances aside", "looks down,",
)


def card_shape_ok(body: str) -> tuple[bool, str]:
    """Reject a card that describes the picture instead of explaining the moment."""
    low = " " + re.sub(r"\s+", " ", body or "").lower() + " "
    hits = [p for p in _DESCRIBES if p in low]
    if hits:
        return False, f"describes the footage ({', '.join(hits[:3])})"
    return True, ""


# "Rockstar confirmed ..." on a fact whose only source was a Kotaku preview round-up, and the
# AI critic passed it (2026-11-20). Crediting the developer is a factual claim of its own, so
# code checks it: the card may credit the developer only when the support says the developer.
_DEV = (r"(?:rockstar(?:\s+games)?(?:['’]s?\s+(?:devs|developers|team|writers|director\w*))?|"
        r"the\s+(?:devs|developers|studio|writers)|(?:the\s+)?developers?|(?:the\s+)?devs|take-two)")
# Only verbs that claim the developer SAID something. 'showed', 'teased', 'told' are left out:
# a comparison like 'the grind the devs teased in San Andreas' is opinion, not a credit (review
# 2026-11-20). Up to two filler words may sit between ('Rockstar has since confirmed').
_SAID = r"(?:confirm\w*|reveal\w*|said|says|announc\w*|explain\w*|stat(?:ed|es)|admit\w*|verif\w*)"
_ATTRIB_RES = (
    re.compile(rf"\b{_DEV}(?:\s+(?!and\b|but\b|nor\b)\w+){{0,2}}?\s+{_SAID}\b", re.I),
    re.compile(rf"\b{_DEV}['’]s\s+{_SAID}\b", re.I),
    re.compile(rf"\b(?:confirmed|revealed|announced|explained|verified|stated)\s+by\s+{_DEV}\b", re.I),
    re.compile(rf"\b(?:according\s+to|per|straight\s+from|as)\s+{_DEV}(?:\s+put\s+it)?\b", re.I),
)
# Support that DOES come from the people who made the game: their site, or a line crediting
# a developer, director, writer or interview. No trailing \b on rockstar, so the
# rockstargames.com source domain counts.
_DEV_WORD = re.compile(r"(?:rockstar|\bdevelopers?\b|\bdevs\b|take-two|\bstudio\b|\bdirector\b|"
                       r"\bwriters?\b|\binterview\w*|\bproducer\b|\bnewswire\b|\bplaystation\.blog)", re.I)


def attribution_overreach(text: str, support: str) -> str:
    """A credit to the developer ('Rockstar confirmed') that the support never makes. A false
    hit costs one rewrite with the reason, not a lost post."""
    if _DEV_WORD.search(support or ""):
        return ""
    for rx in _ATTRIB_RES:
        m = rx.search(text or "")
        if m:
            return (f"'{m.group(0)}' credits the developer, but the source never says the "
                    "developer said it; credit the listed source or nobody")
    return ""


_HEDGE = re.compile(r"\b(?:unconfirmed|unverified|not\s+confirmed|rumou?r\w*|speculat\w*|fan\s+theor\w*|"
                    r"theor(?:y|ize|ise)\w*|possibl\w*|likely|may\s+be|might|appears?\s+to|seems?|"
                    r"unclear|unknown|reportedly|believ\w*|guess\w*|suggest\w*|could\s+be)\b", re.I)
_NAME_RUN = re.compile(r"[A-Z][\w-]*(?:\s+(?:of\s+|the\s+|de\s+)?[A-Z][\w-]*)*")
_NAME_SKIP = {"i", "in", "the", "a", "an", "and", "but", "so", "that", "this", "it", "its", "they",
              "he", "she", "his", "her", "their", "when", "then", "now", "keep", "watch", "yes",
              "no", "not", "one", "every", "after", "before", "while", "even", "if", "you", "your",
              "gta", "vi", "6", "ok"}


def confirmed_research(research: str) -> str:
    """The research SENTENCES that do not hedge; a hedged sentence supports nothing stated as
    fact. Sentence level, not line level: 'Nelson used pull-ups as his example (Dazed). It was
    likely chosen because...' keeps the sourced first half (rebuild test, 2026-11-20)."""
    keep = []
    for line in (research or "").splitlines():
        parts = [p for p in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", line.strip()) if p]
        hedged = [bool(_HEDGE.search(p)) for p in parts]
        # A short hedge or a tag ('Unconfirmed.', '(Fan theory, r/GTA6)') speaks for the whole
        # line, so the line goes (review, 2026-11-20).
        if any(h and (len(p.split()) <= 6 or p.lstrip().startswith(("(", "Source")))
               for p, h in zip(parts, hedged)):
            continue
        good = []
        for i, p in enumerate(parts):
            if hedged[i]:
                continue
            # 'Some fans believe A. It is a nod to Tommy.' carries the theory on
            if i and hedged[i - 1] and re.match(r"(?:it|this|that|they|he|she|which)\b", p, re.I):
                hedged[i] = True
                continue
            good.append(p)
        if good:
            keep.append(" ".join(good))
    return "\n".join(keep)


def unsupported_names(text: str, support: str, extra_ok: tuple = ()) -> list[str]:
    """Capitalised names in the card that appear nowhere in the support. Heuristic, so the
    list goes to the checker as suspects rather than rejecting on its own (a comparison beat
    may rightly name another game). A single capitalised word that opens a sentence is just
    the sentence start ('Imagine', 'Hit'), and a possessive splits a run ('CJ's San Andreas')."""
    sup = " " + re.sub(r"\s+", " ", (support or "")).lower() + " "
    ok = {w.lower() for w in extra_ok if w}
    out = []
    # split on possessives so "CJ's San Andreas" is two names
    flat = re.sub(r"['’]s\b", " ,", text or "")
    for m in _NAME_RUN.finditer(flat):
        words = m.group(0).split()
        before = flat[:m.start()].rstrip()
        at_start = not before or before[-1] in ".!?:;\"“"
        if at_start:
            if len(words) == 1:
                continue
            if words[0].lower() in _NAME_SKIP:
                words = words[1:]
        while words and words[0].lower() in _NAME_SKIP:
            words = words[1:]
        name = " ".join(words).strip(" -")
        if not name or name.lower() in ok:
            continue
        if all(w.lower() in ok or w.lower() in _NAME_SKIP for w in words):
            continue
        if name.lower() not in sup and name not in out:
            out.append(name)
    return out


def _write_caption(card: dict, gname: str, avoid: str = "") -> dict:
    """A SHORT caption that ELABORATES on the card — never a copy of it (user, 2026-10-08).
    Their own sample for a Harry/Norman card: 'The father who would do everything to save his
    son, even if it endangers everyone, including his own son.'"""
    prompt = (
        f"This {gname} short carries an on-screen card:\n\n{card.get('body', '')}\n\n"
        "Write the POST CAPTION for it. The caption does NOT repeat the card — the viewer is "
        "already reading that. It names the THEME underneath the moment in the writer's own "
        "words, so it rewards someone who just read the card.\n"
        "- ONE sentence, 12-28 words. Plain English. No emojis, no hashtags, no quotes.\n"
        "- stay CONCRETE about who this is about ('The father who...', 'A man who...'). Plain "
        "words beat literary ones — no 'indistinguishable from', no abstract nouns stacked up\n"
        "- never reuse a phrase from the card; never start with 'In " + gname + "'\n"
        "- state nothing the card does not support\n"
        "Example of the right register, for a card about a father promising never to let his "
        "dying son go: 'The father who would do everything to save his son, even if it "
        "endangers everyone, including his own son.'\n"
        + (f"\nA previous attempt was rejected: {avoid}\nFix exactly that.\n" if avoid else "")
        + "\nAlso write the YOUTUBE TITLE for the same short: 4-10 words, under 60 "
        "characters, a curiosity gap that makes someone tap. It is NOT the caption and NOT a "
        "full sentence with a full stop; no game name (it gets appended), no hashtags, no "
        "quotes, and no tease the card does not pay off. Good shape: 'The one word that costs "
        "Harry everything'.\n"
        + '\nReturn ONLY JSON: {"caption": "the sentence", "title": "the short title"}'
    )
    try:
        d = extract_json(_text(prompt, timeout=150)) or {}
        return {k: re.sub(r"\s+", " ", sanitize(str(d.get(k, "")))).strip().strip('"')
                for k in ("caption", "title")}
    except Exception as e:
        log(f"caption writer failed ({e!r})")
        return {}


def _caption_ok(caption: str, card: dict) -> tuple[bool, str]:
    """Short, and genuinely NOT a copy: no 6-word run shared with the card body."""
    words = caption.split()
    if not (8 <= len(words) <= 34):
        return False, f"{len(words)} words — needs one sentence of 12-28"
    body_words = [_norm_word(w) for w in card.get("body", "").split()]
    runs = {tuple(body_words[i:i + 6]) for i in range(max(0, len(body_words) - 5))}
    cw = [_norm_word(w) for w in words]
    for i in range(max(0, len(cw) - 5)):
        if tuple(cw[i:i + 6]) in runs:
            return False, "copies a phrase straight out of the card"
    if caption.strip().lower() == (card.get("comment", "") or "").strip().lower():
        return False, "same as the comment line"
    return True, ""


def _title_ok(title: str) -> bool:
    """A YouTube title must survive ' | <Game> #Shorts' inside 100 chars without being cut
    mid-sentence — a lore post has no on-screen hook, so this IS the title (user, 2026-10-08)."""
    n = len(title.split())
    return bool(title) and 3 <= n <= 12 and len(title) <= 62 and not title.endswith(".")


def lore_post_text(card: dict, gname: str) -> tuple[str, str]:
    """(caption, title) for a lore post: the caption elaborates, the title teases. Neither
    is ever a copy of the card."""
    cap_out, title_out, why = "", "", ""
    for _ in range(2):
        d = _write_caption(card, gname, avoid=why)
        cap, title = d.get("caption", ""), d.get("title", "")
        if title and _title_ok(title) and not unsafe_terms(title) and not title_out:
            title_out = title
        if cap and not cap_out:
            ok, why = _caption_ok(cap, card)
            if ok and not unsafe_terms(cap):
                cap_out = cap
            else:
                log(f"caption rejected ({why or 'unsafe wording'}); rewriting.")
        if cap_out and title_out:
            break
    # The comment line is already short, on-topic and fact-checked — better than shipping
    # the whole card body as the caption.
    cap_out = cap_out or (card.get("comment", "") or "").strip()
    if not title_out:      # trim the caption on a word boundary rather than mid-sentence
        words, title_out = cap_out.split(), ""
        for w in words:
            if len(f"{title_out} {w}".strip()) > 58:
                break
            title_out = f"{title_out} {w}".strip()
        title_out = title_out.rstrip(",;:.") or gname
    # Humanize pass (user, 2026-11-09). A rewrite that copies the card or trips the
    # advertiser-safety list is dropped for the original.
    from core import humanize
    h_cap, h_title = humanize.post_text(cap_out, title_out)
    if h_cap != cap_out and (not _caption_ok(h_cap, card)[0] or unsafe_terms(h_cap)):
        h_cap = cap_out
    if h_title != title_out and unsafe_terms(h_title):
        h_title = title_out
    return h_cap, h_title


def _check_card(card: dict, observation: str, subtitles: str, gname: str,
                game: str = "", research: str = "", facts: str = "",
                used_fact: str = "", suspects: list | None = None) -> tuple[bool, str]:
    """Adversarial check: every claim must come from the clip, the subtitles or the lore.
    The BIBLE is included (it was not, so a wrong 'five years' sailed through with no
    timeline to check it against — user, 2026-10-07). `used_fact` is the one fact the card
    says it is built on, with its source; `suspects` are names code found in no evidence."""
    from core import lore as _lore
    bible = (_lore.lore_for(game) if game else "") or ""
    prompt = (
        f"You are a strict fact-checker for a {gname} gameplay card. A gaming audience calls "
        "out invented trivia, so be rigorous.\n\n"
        + (f"GAME LORE BIBLE (authoritative — check any date, duration or who-did-what "
           f"against THIS):\n{bible}\n\n" if bible else "")
        + f"EVIDENCE — what is on screen:\n{observation}\n\n"
        + (f"RESEARCHED CONTEXT for this scene (Reddit, wikis, interviews). A claim that "
           f"matches this IS supported — but a fan theory must still be worded as one, and "
           f"anything here that is not about THIS scene supports nothing. The research may "
           f"describe a DIFFERENT, similar scene: it NEVER overrides the on-screen evidence, "
           f"so reject anything it imported that the frames contradict:\n{research}\n\n"
           if research else "")
        + (f"{subtitles}\n\n" if subtitles else "")
        + (f"VERIFIED GAME FACTS (sourced; a card built on one of these is SUPPORTED as long as "
           f"it keeps every number, date and name exactly as written here, and does not claim "
           f"the clip itself shows something only the fact describes):\n{facts}\n\n"
           "A FACT CARD may contain NOTHING beyond the fact, what is visibly on screen, and a "
           "consequence that the fact, the subtitles or on-screen text states. Flag as BAD any added claim around the fact: "
           "a superlative the fact does not make ('most', 'first', 'only', 'biggest'), an invented "
           "process or motive ('Rockstar documented', 'studied', 'visited', 'on purpose'), or a "
           "broader generalisation stated as fact. This is how an unsourced 'Rockstar's most "
           "sourced region' got through (2026-11-19).\n\n"
           if facts else "")
        + (f"THIS CARD IS BUILT ON THESE LISTED FACTS (one, or a main fact plus one more), and they "
           f"are ALL it may state as fact apart from what is visibly on screen or in the subtitles:\n{used_fact}\n\n"
           "Go through beats 1 and 2 claim by claim and hold each one against these facts and "
           "the on-screen evidence. Flag as BAD:\n"
           "- a credit the source does not give: 'Rockstar confirmed', 'Rockstar revealed', "
           "'the developers said' when the source is a news site or preview\n"
           "- a place, district, building, home or safehouse the fact does not name and the "
           "screen does not show in readable text\n"
           "- a label, mechanic name or link the fact does not make ('RPG-lite', 'connects "
           "to', 'physique system')\n"
           "- a research finding the research itself calls unconfirmed, possible or a theory, "
           "stated as fact\n"
           "A card that is true in spirit but adds any of these is still BAD. That is how "
           "'Rockstar confirmed' and 'his Key Lento safehouse' reached a card built on a "
           "Kotaku preview (2026-11-20).\n\n"
           if used_fact else "")
        + (f"NAMES IN THE CARD THAT APPEAR IN NONE OF THE EVIDENCE: {', '.join(suspects)}.\n"
           "Each one is BAD if it is used in beats 1 or 2 or stated as fact. It is fine only "
           "inside the closing comparison, naming another game or one of its characters.\n\n"
           if suspects else "")
        # The COMMENT ships on the video too, and it was NOT being checked — that is where an
        # invented 'five years' reached a live TikTok post (user, 2026-10-07). Check it all.
        + f"THE HEADLINE (shown big above the card, check it the same way):\n"
          f"{card.get('headline', '(none)')}\n\n"
        + f"THE CARD:\n{card.get('body', '')}\n\n"
        + f"THE COMMENT LINE (also posted, check it the same way):\n"
          f"{card.get('comment', '(none)')}\n\n"
        + f"THE CARD'S MODE: {card.get('mode') or '(not given)'}\n"
          "MODE CHECK (Bryce, 2026-11-22): 'player' means the clip shows the player in control "
          "(HUD, prompts, menus, a notice, an activity or system) and the card talks to the "
          "viewer about what YOU can do. 'story' means a scripted scene and the card names the "
          "character. Flag as BAD: a 'player' card on a scripted scene, a 'story' card that says "
          "'you can' or sells a story beat as a choice, or a player mechanic told as something "
          "that happened to the character.\n"
          "PICTURE CHECK (Bryce, 2026-11-22): flag as BAD a spoken line credited to anyone but "
          "the speaker labelled in the subtitles; a gesture, look, shrug or expression the "
          "on-screen evidence does not state; a number with no unit or no clear meaning ('about "
          "33 percent per day'); a story spoiler beyond this clip (who dies, betrayals, twists, "
          "endings); and a headline that claims more than the card supports or opens with "
          "'In <game>'.\n"
          "ROUND 2 (review 2026-11-22, slips that got past this check): flag as BAD any quoted or "
          "paraphrased speech ('calling it an investment') that the subtitles do not contain; "
          "any name, model or label (a car model, a menu option) that is neither readable in the "
          "evidence nor in the fact; a card that contradicts itself ('fires after X' and 'has no "
          "trigger'); a NAMED later mission, chapter or event that comes after this clip in the "
          "story (a spoiler, even when a walkthrough confirms it); a comparison that gets the "
          "mechanic backwards ('caps the damage you can take' for MORE health); and a headline "
          "whose subject the on-screen evidence never shows (except a fact card's headline that "
          "states its listed fact, adds nothing, keeps its hedges and has no off-screen number, on a clip of the kind of moment the fact is "
          "about); and a number or stat that is not "
          "on screen and is stated without saying where it comes from.\n\n"
        "CHECK THE DIRECTION OF THE ACTION FIRST. Who is doing what, TO WHOM, and who is "
        "awake, standing, holding or reaching — compare that against the on-screen evidence "
        "line by line. A card that swaps the two people round ('Dina holding her' when the "
        "evidence shows Ellie reaching for a sleeping Dina) is BAD even if it is beautifully "
        "written, and a card that imports an event the frames do not show (a flashback, a "
        "fallen object, a trigger) is BAD however confident the researched context sounds. "
        "This is the failure that shipped (user, 2026-10-09).\n"
        "NAMING: a character the BIBLE identifies unmistakably from what is on screen (its "
        "visual tells plus who is with whom at that point in the story) is CORRECTLY named — "
        "do NOT demand a subtitle label for them. Forcing the writer to say 'someone' about "
        "a companion the bible plainly identifies produced a card that read like a mystery "
        "the scene did not have, so do not reward vagueness (user, 2026-10-09).\n"
        "ALSO FLAG a place, scope or count narrower or wider than the fact says ('on the same street' "
        "for a fact that says 'in that area'; 'anything' for one rule), and any conclusion the card "
        "draws itself ('so clearing the circle does not reset anything') that no fact states "
        "(missed in a test card, 2026-11-26).\n"
        "ALSO FLAG a card that implies a DARKER STATE than the evidence shows: a sleeping or "
        "resting character written as unconscious, dying or dead ('eyes stay shut', 'won't "
        "wake'), or any hint of injury or loss the clip and bible do not support.\n"
        "Mark it BAD only for a FACTUAL claim the evidence does not support: an invented "
        "detail, a developer/design intention, a camera or animation claim you cannot verify, "
        "a character who is not shown or named, a misquoted or mis-attributed line, or an "
        "event outside this clip presented as happening in it.\n"
        "The card may end on its fact, or on a consequence or tip (2026-11-26: the tip is "
        "OPTIONAL). Never flag a card for having no tip, consequence or practical use. Flag as "
        "BAD a tip, consequence or cause the evidence does not support (a mechanic, cost, rule "
        "or 'which is why' link no source gives). "
        "Do not flag ordinary re-telling of what is shown, or established series lore. "
        "Flag only something stated as fact that is not true.\n"
        "ALWAYS flag an invented NUMBER or DURATION — a year, a count, 'five years later', "
        "'the only time in the series' — unless that exact figure is in the bible, on screen or in a listed fact "
        "(as written there). Check every span against the bible's TIMELINE.\n"
        "ALSO CHECK THE READING, NOT JUST THE FACTS. A sentence can be traceable to a line "
        "of dialogue and still be BACKWARDS about the story. Hold the card's interpretation "
        "against what the bible says these characters WANT and DO: if the card has someone "
        "acting against their established motive — a father who refuses to lose his son "
        "described as 'agreeing to let his son die', a character said to give up on "
        "something the story shows them never giving up on — that is a FACTUAL error about "
        "the game and you must flag it, however well the individual words match the "
        "subtitles (user, 2026-10-09).\n"
        'Return ONLY JSON: {"ok": true or false, "issues": "one short reason if BAD, else empty"}'
    )
    try:
        # Subscription only (Bryce, 2026-11-23: "yes subscription only"): never the paid Anthropic API or
        # OpenAI. If the subscription cannot run the check, the card is refused below, not posted unchecked.
        from core import claude_code
        d = extract_json(claude_code.run(prompt, timeout=200, paid_fallback=False))
        return d.get("ok") is True, str(d.get("issues", "")).strip()  # "false" as text is not a pass
    except Exception as e:
        # Fail CLOSED (2026-11-23, footage-truth review): a check that could not run used to pass the
        # card, so a crash or an unreadable reply let an unchecked card post. Now the card is rewritten
        # once and, if the check still cannot run, refused (CardRefused), never posted unchecked.
        return False, f"the fact check could not run ({e!r})"[:200]


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _font(size: int, weight: str = "Bold"):
    """Montserrat at a real weight (the file is variable and defaults to Thin)."""
    from PIL import ImageFont
    f = ImageFont.truetype(str(FONT_BODY), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def _norm_word(w: str) -> str:
    return re.sub(r"[^\w']", "", w).lower()


def _highlight_indices(body: str, highlight: str) -> set:
    """Indices of the body's words covered by the highlight PHRASE (contiguous match).
    Matching word-by-word lit up every stray 'a' and 'not' in the paragraph."""
    hw = [_norm_word(w) for w in (highlight or "").split() if _norm_word(w)]
    bw = [_norm_word(w) for w in body.split()]
    if not hw or len(hw) > len(bw):
        return set()
    for i in range(len(bw) - len(hw) + 1):
        if bw[i:i + len(hw)] == hw:
            return set(range(i, i + len(hw)))
    return set()


def _draw_highlighted(d, x: int, y: int, line: str, hl_idx: set, f_norm, f_hl,
                      start_word: int = 0) -> int:
    """Draw a line word by word, colouring only the words inside the highlight phrase.
    Returns the running word index after this line."""
    i = start_word
    for word in line.split(" "):
        hit = i in hl_idx
        font = f_hl if hit else f_norm
        d.text((x, y), word, font=font, fill=(255, 209, 102, 255) if hit else (255, 255, 255, 255))
        x += d.textlength(word + " ", font=font)
        i += 1
    return i


def _layout(card: dict, video_h: int, video_w: int) -> dict:
    """Vertical layout, imitating the proven format: TEXT CARD on top, video under it,
    a comment strip below that, and the PNGtuber reaction at the bottom."""
    from PIL import ImageDraw, Image
    d = ImageDraw.Draw(Image.new("RGB", (16, 16)))
    pad, inner = 36, 44
    # HEADLINE (Bryce, 2026-11-22: lead with the surprise): big Anton above the body, inside
    # the same card, at most two lines. Cards without one render exactly as before.
    from PIL import ImageFont
    f_head = ImageFont.truetype(str(FONT_HEAD), 72) if FONT_HEAD.exists() else _font(66, "ExtraBold")
    head_lines = (_wrap(d, card["headline"].upper(), f_head, W - pad * 2 - inner * 2)[:2]
                  if card.get("headline") else [])
    head_line_h, head_gap = 84, 26
    head_h = (len(head_lines) * head_line_h + head_gap) if head_lines else 0
    # FIT THE FRAME (2026-11-22: a 70-word card plus the headline pushed the comment strip off
    # the bottom). The body steps down from 46 px until card, video and comment fit; the layout
    # itself stays the same.
    cmt_est = 18 + 56 + 18 + 2 * 44 + 26
    for body_px, line_h in ((46, 58), (43, 54), (40, 50), (37, 46)):
        f_body = _font(body_px, "Bold")
        body_lines = _wrap(d, card["body"], f_body, W - pad * 2 - inner * 2)
        if 150 + inner * 2 + head_h + len(body_lines) * line_h + video_h + cmt_est <= H - 30:
            break
    text_h = inner * 2 + head_h + len(body_lines) * line_h
    # The comment strip is sized from the ACTUAL wrapped lines — a fixed height clipped the
    # second line outside the card (user, 2026-10-06).
    avatar, cmt_line_h = 56, 44
    comment_lines = (_wrap(d, card["comment"], _font(36, "Medium"), W - pad * 2 - inner * 2)[:3]
                     if card.get("comment") else [])
    comment_h = (18 + avatar + 18 + len(comment_lines) * cmt_line_h + 26) if comment_lines else 0
    top = 150                                       # leaves room for the Shorts UI
    return {"pad": pad, "inner": inner, "f_body": f_body, "body_lines": body_lines, "body_px": body_px,
            "f_head": f_head, "head_lines": head_lines, "head_line_h": head_line_h,
            "head_h": head_h,
            "video_h": video_h, "video_w": video_w, "avatar": avatar,
            "comment_lines": comment_lines, "cmt_line_h": cmt_line_h,
            "line_h": line_h, "top": top, "text_h": text_h, "video_y": top + text_h,
            "comment_y": top + text_h + video_h, "comment_h": comment_h}


def _card_png(card: dict, out: Path, video_h: int, lay: dict) -> Path:
    """One transparent overlay: the top text card, the comment strip and the reaction."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad, inner = lay["pad"], lay["inner"]
    panel_top, panel_bot = lay["top"], lay["comment_y"] + lay["comment_h"]
    # one dark rounded card behind text + video + comment, like the reference
    d.rounded_rectangle([pad, panel_top, W - pad, panel_bot], radius=44, fill=(10, 10, 12, 242))
    # clear the band where the video sits underneath, or the panel would hide it
    vy0, vy1 = lay["video_y"], lay["video_y"] + lay["video_h"]
    vx0 = round((W - lay["video_w"]) / 2)
    d.rectangle([vx0, vy0, vx0 + lay["video_w"], vy1], fill=(0, 0, 0, 0))

    hl_idx = _highlight_indices(card["body"], card.get("highlight", ""))
    f_body, f_hl = lay["f_body"], _font(lay.get("body_px", 46), "ExtraBold")
    y, wi = panel_top + inner, 0
    for ln in lay.get("head_lines", []):            # the headline, centred, white Anton
        w = d.textlength(ln, font=lay["f_head"])
        d.text((int((W - w) / 2), y), ln, font=lay["f_head"], fill=(255, 255, 255, 255))
        y += lay["head_line_h"]
    if lay.get("head_lines"):
        y += lay["head_h"] - len(lay["head_lines"]) * lay["head_line_h"]
    for ln in lay["body_lines"]:                    # centred, like the sample
        w = d.textlength(ln, font=f_body)
        wi = _draw_highlighted(d, int((W - w) / 2), y, ln, hl_idx, f_body, f_hl, wi)
        y += lay["line_h"]

    if lay["comment_lines"]:                        # avatar + handle + reaction line
        cy = lay["comment_y"] + 18
        s = lay["avatar"]
        if LOGO.exists():
            logo = Image.open(LOGO).convert("RGBA")
            c = min(logo.size)
            logo = logo.crop(((logo.width - c) // 2, (logo.height - c) // 2,
                              (logo.width + c) // 2, (logo.height + c) // 2)).resize(
                                  (s, s), Image.LANCZOS)
            mask = Image.new("L", (s * 4, s * 4), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, s * 4, s * 4], fill=255)
            logo.putalpha(mask.resize((s, s), Image.LANCZOS))
            img.alpha_composite(logo, (pad + inner, cy))
        f_handle, f_cmt = _font(34, "Bold"), _font(36, "Medium")
        d.text((pad + inner + s + 16, cy + 12), "@kiwinoygaming", font=f_handle,
               fill=(190, 190, 198, 255))
        for i, ln in enumerate(lay["comment_lines"]):   # same lines the height was sized from
            d.text((pad + inner, cy + s + 18 + i * lay["cmt_line_h"]), ln, font=f_cmt,
                   fill=(236, 236, 240, 255))

    react = ROOT / "assets" / "pngtuber" / "kg_idle.png"
    room = H - panel_bot - 60
    if react.exists() and room >= 140:              # our own reaction character, under the card
        r = Image.open(react).convert("RGBA")       # (skipped when a tall card leaves no room:
        rh = min(340, room)                         # it covered the comment line, 2026-11-22)
        r = r.resize((round(r.width * rh / r.height), rh), Image.LANCZOS)
        img.alpha_composite(r, (round((W - r.width) / 2), H - rh - 40))
    img.save(out)
    return out


def _payoff_scan(seg: Path, dur: float, card: dict) -> dict | None:
    """One frame per second of the clip on a labelled sheet, read by Claude vision: the first
    second the headline's subject is clearly on screen, whether it appears at all, and the
    broken-looking seconds (camera-mode blur or colour-split smear, black, loading, pause or
    map screen that is not the point of the card). None if the scan fails."""
    from PIL import Image, ImageDraw
    from core import claude_code
    ff = ffmpeg.ffmpeg_bin() or "ffmpeg"
    n = max(1, int(dur))
    with tempfile.TemporaryDirectory() as tmp:
        tiles = []
        for k in range(n):
            f = Path(tmp) / f"s{k:02d}.png"
            subprocess.run([ff, "-y", "-v", "error", "-ss", f"{k + 0.5:.2f}", "-i", str(seg),
                            "-frames:v", "1", "-vf", "scale=384:216", str(f)], check=False)
            tiles.append(Image.open(f).convert("RGB") if f.exists() else Image.new("RGB", (384, 216)))
        cols = 5
        sheet = Image.new("RGB", (384 * cols, 216 * ((n + cols - 1) // cols)))
        d = ImageDraw.Draw(sheet)
        for k, im in enumerate(tiles):
            x, y = (k % cols) * 384, (k // cols) * 216
            sheet.paste(im, (x, y))
            d.rectangle([x, y, x + 44, y + 22], fill=(0, 0, 0))
            d.text((x + 5, y + 4), f"{k}s", fill=(255, 255, 0))
        path = Path(tmp) / "sheet.jpg"
        sheet.save(path, quality=85)
        try:
            raw = claude_code.vision(
                f"This sheet shows one frame per second of a {n}-second gameplay clip; each tile is "
                "labelled with its second. A text card will sit above this clip:\n"
                f"HEADLINE: {card.get('headline', '')}\nCARD: {card.get('body', '')}\n\n"
                "1. payoff_s: the FIRST second where the thing the HEADLINE is about is clearly "
                "visible (the menu, notice, action or moment itself).\n"
                "2. shown: false if that thing never appears in any tile.\n"
                "3. bad_s: seconds that look broken or useless: camera-mode blur or a colour-split "
                "smear, black or near-black, a loading screen, or a pause/map screen that is not "
                "what the card is about.\n"
                'Reply ONLY JSON {"payoff_s": 0, "shown": true, "bad_s": []}.', [path], timeout=240)
            return extract_json(raw) or None
        except Exception as e:
            log(f"payoff scan skipped ({e!r})")
            return None


def _text_box(seg: Path, t: float, card: dict) -> tuple | None:
    """Where the evidence text sits in the frame at `t`, as a 16:9 crop (x0, y0, w, h in frame
    fractions, at least 45% wide so the zoom stays sharp at 1080p), or None if Claude cannot
    find it. One still, read with Claude vision on the subscription."""
    from core import claude_code
    ff = ffmpeg.ffmpeg_bin() or "ffmpeg"
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "payoff.png"
        subprocess.run([ff, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(seg), "-frames:v", "1",
                        str(png)], check=False)
        if not png.exists():
            return None
        try:
            raw = claude_code.vision(
                "This is a still from a gameplay clip. Find the in-game TEXT that this card line is "
                f"about: \"{card.get('headline', '')}\" / \"{card.get('highlight', '')}\". Reply ONLY "
                'JSON {"found": true, "box": [x0, y0, x1, y1]} with the text\'s box as fractions of '
                'the image width and height (0 to 1), or {"found": false}.', [png], timeout=180)
            d = extract_json(raw) or {}
        except Exception as e:
            log(f"text zoom skipped ({e!r})")
            return None
    if not d.get("found") or len(d.get("box") or []) != 4:
        return None
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in d["box"])
    # Conservative (test 2026-11-22: a loose box zoomed onto a car bonnet and a cut subtitle):
    # only a small, clear text box, and never tighter than 60% of the frame width.
    if not (0 < x1 - x0 <= 0.5 and 0 < y1 - y0 <= 0.3):
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = min(1.0, max(0.6, (x1 - x0) * 1.8))
    h = w                                 # same fraction of each side keeps the frame's 16:9
    x = min(1.0 - w, max(0.0, cx - w / 2))
    y = min(1.0 - h, max(0.0, cy - h / 2))
    return (x, y, w, h) if w < 0.95 else None


_LOG_CACHE: dict = {}


LOG_OUTSIDE = "BEFORE OR AFTER THE SHORT"


def footage_log_events(name: str, game: str, start: float, dur: float, pad: float = 45.0) -> str | None:
    """The footage log's account of this stretch (tools/footage_log.py; B2 footage-log/), or None if the
    clip has no log yet. Written from the timed dialogue and frames of the whole clip, so it knows who
    did what (2026-11-24: a test card said 'Lucia is robbing Tucker's' when she stopped the robber)."""
    from core import b2_store
    for key in (f"footage-log/cutscenes/{game}/{name}.json", f"footage-log/footage/{game}/{name}.json"):
        if key not in _LOG_CACHE:
            data = b2_store.get_bytes(key)
            _LOG_CACHE[key] = json.loads(data) if data else None
        log = _LOG_CACHE[key]
        if not log:
            continue
        lo, hi = start - pad, start + dur + pad
        ev = [x for x in log.get("events", []) if float(x.get("end", 0)) >= lo and float(x.get("start", 0)) <= hi]
        def line(x):
            return (f"- {float(x.get('start', 0)) - start:+.0f} to {float(x.get('end', 0)) - start:+.0f} s from the "
                    f"Short's start [{x.get('certainty', '')}]: {x.get('what', '')} | player: {x.get('player_does', '')} | "
                    f"others: {x.get('others_do', '')} | quote: {x.get('quote', '')} | on screen: "
                    f"{x.get('on_screen_text', '')} | money: {x.get('money', '')}")
        # 2026-11-24 independent review: a card quoted a line and a wallet total from AFTER the Short
        # ended. The viewer must see what the card claims, so the log is split in two.
        inside = [x for x in ev if float(x.get("end", 0)) > start + 0.5 and float(x.get("start", 0)) < start + dur - 0.5]
        outside = [x for x in ev if x not in inside]
        warn = "\n".join(f"- {w}" for w in (log.get("watch_outs") or []))
        return (f"Clip summary: {log.get('summary', '')}\n"
                f"INSIDE THE SHORT (0 to {dur:.0f} s; the card may only claim what happens here):\n"
                + ("\n".join(line(x) for x in inside) or "- (no logged event)")
                + "\n" + LOG_OUTSIDE + " (context only, to get who-did-what right; the viewer never sees it, "
                  "so never state it, quote it or use its numbers):\n"
                + ("\n".join(line(x) for x in outside) or "- (none)")
                + (f"\nWatch outs:\n{warn}" if warn else ""))
    return None


def build(clip: Path, game: str, start: float, dur: float, text: str | None, outdir: Path,
          card: dict | None = None, log_name: str | None = None, log_offset: float = 0.0) -> Path:
    gname = (CONFIG.reels.get("game_names", {}) or {}).get(game, "") or game
    outdir.mkdir(parents=True, exist_ok=True)
    # FOOTAGE LOG FIRST (Bryce, 2026-11-24): a card is only written about footage whose log says who
    # did what. A clip with no log yet is refused here, before any AI work, and the slot tries another.
    truth, fitted = None, None
    if not text and not card:
        truth = footage_log_events(log_name or Path(clip).name, game, start + log_offset, dur)
        lcfg0 = (CONFIG.reels.get("gameplay", {}) or {}).get("lore", {}) or {}
        if truth is None and bool(lcfg0.get("require_footage_log", True)):
            raise CardRefused(f"no footage log for {log_name or Path(clip).name} yet")
        # FACT FIT FIRST (Bryce, 2026-11-26, after 23 refused moments in one slot): a fact card needs a
        # sourced fact about what this moment shows. Checked from the log's account of the Short's own
        # seconds before any AI work, so a moment no fact fits costs seconds, not four minutes.
        if truth and bool(lcfg0.get("facts", True)) and bool(lcfg0.get("require_fact_fit", True)):
            fitted = fit_for_moment(log_name or Path(clip).name, game, start + log_offset, dur)
            if fitted is not None and not fitted:
                raise NoFactFit("no listed fact is about what this moment shows")
    seg = outdir / "segment.mp4"
    ff = ffmpeg.ffmpeg_bin() or "ffmpeg"
    # Never run past the footage: the final render LOOPS the segment to fill `dur`, so a
    # 10s cutscene asked for 17s would replay its start. A shorter cutscene is used whole
    # (user, 2026-11-09).
    _total = float(ffmpeg.duration(Path(clip)) or 0.0)
    if _total > 0:
        dur = max(1.0, min(dur, _total - max(0.0, start)))
    # keep the gameplay AUDIO (per user 2026-10-06) — it carries the moment
    subprocess.run([ff, "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
                    "-i", str(clip), "-c:v", "libx264", "-crf", "18",
                    "-preset", "medium", "-c:a", "aac", "-b:a", "192k", str(seg)], check=True)

    wrote = False
    if card:
        pass
    elif text:
        card = {"highlight": "", "comment": "", "body": re.sub(r"\s+", " ", text).strip()}
    else:
        # EVIDENCE MUST BE THE MOMENT ON SCREEN. Observing/scanning the whole source file
        # wrote a card about a part of the recording the viewer never sees: an 8s window of
        # the Sandman aftermath got a card about the Web Wings from minutes later in the same
        # file (bench 2026-10-08). Frames come from the rendered SEGMENT; subtitles come from
        # the segment plus a short lead-in/out, flagged as context only.
        with tempfile.TemporaryDirectory() as tmp:
            cands = frames.extract_candidates(seg, Path(tmp), n=max(6, observe_frame_count(dur)))
            observation = _observe_clip(cands, gname, dur)
            seen_text = observation + "\n" + (truth or "").split(LOG_OUTSIDE)[0]
            # The WRITER sees only the log's account of the Short's own seconds (2026-11-26: cards used
            # lines, menus and prices from after the Short ended, and were refused). The checker and fan
            # critic still see the whole log, to catch who-did-what mistakes.
            writer_obs = observation
            if truth:
                _wo = truth.split("\nWatch outs:\n", 1)[1] if "\nWatch outs:\n" in truth else ""
                writer_obs += ("\n\nWHAT REALLY HAPPENS IN THE SHORT (the footage log, written from the timed "
                               "dialogue and frames of the whole recording; it OUTRANKS any reading of these few "
                               "frames, above all on who does what to whom; nothing outside these seconds may go "
                               "on the card):\n" + re.sub(r"^Clip summary:[^\n]*\n", "",
                                                           truth.split(LOG_OUTSIDE)[0]).rstrip()
                               + (f"\nWatch outs:\n{_wo}" if _wo else ""))
            if truth:
                observation += ("\n\nWHAT REALLY HAPPENS AROUND THIS MOMENT (the footage log, written from the "
                                "timed dialogue and frames of the whole recording; it OUTRANKS any reading of "
                                f"these few frames, above all on who does what to whom):\n{truth}")
            from agents.content import adult_on_screen
            if adult_on_screen(observation):    # sexual activity or nudity: never post it
                raise CardRefused("sexual content or nudity on screen")
            ctx_start = max(0.0, start - CTX_PAD)
            ctx = Path(tmp) / "context.mp4"
            subprocess.run([ff, "-y", "-v", "error", "-ss", f"{ctx_start:.2f}",
                            "-t", f"{dur + CTX_PAD * 2:.2f}", "-i", str(clip),
                            "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                            "-an", str(ctx)], check=False)
            subs = _scan_subtitles(ctx if ctx.exists() else seg, gname)
        if subs:
            subs = (f"{subs}\n(These lines are from the {dur + CTX_PAD * 2:.0f}s AROUND the "
                    f"moment; only the middle {dur:.0f}s are ON SCREEN. Use the rest for "
                    "context only — never describe it as happening in the clip.)")
        # What the internet knows about THIS scene beats anything inferable from the frames,
        # so research it first and let the writer build the card on a finding (user's idea,
        # 2026-10-08). Off with reels.gameplay.lore.research: false.
        lcfg = (CONFIG.reels.get("gameplay", {}) or {}).get("lore", {}) or {}
        research = (research_scene(observation, subs, gname)
                    if bool(lcfg.get("research", True)) else "")
        _facts = (pick_facts(game, f"{observation} {subs}", fitted=fitted)
                  if bool(lcfg.get("facts", True)) else [])
        facts = facts_text(_facts)
        if _facts:
            log(f"fact bank: {len(_facts)} sourced facts offered "
                f"({', '.join(str(x.get('id')) for x in _facts)})")

        def _judge(c: dict) -> tuple[bool, str]:
            """The gates: no AI-slop patterns, it must EXPLAIN (not narrate the picture), be true,
            and pass a real-fan read (2026-11-24)."""
            slop = slop_problems(" ".join((c.get("headline", ""), c.get("body", ""))))
            if slop:
                return False, ("AI filler: " + ", ".join(slop) + ". Replace each with a real fact, "
                               "number or rule from the screen, the subtitles or a listed fact; never a reaction or a comparison")
            src_bad = fact_source_problems(c, {str(x.get("id", "")).lower() for x in _facts})
            if src_bad:
                return False, ("unsourced facts: " + "; ".join(src_bad[:3]) + ". Use only on-screen "
                               "text, the subtitles, a listed verified fact by its id, or the lore bible")
            q_bad = quote_problems(" ".join((c.get("headline", ""), c.get("body", ""))), f"{subs}\n{seen_text}")
            if q_bad:
                return False, ("a quote is not word for word what is said or shown in the Short: "
                               + "; ".join(f"'{q}'" for q in q_bad[:3]) + ". Quote it exactly from the subtitles "
                               "or on-screen text, or say it in your own words without quote marks")
            # A conclusion drawn with 'so' / 'which is why' is a claim of its own; the AI checker passed
            # "So clearing the circle does not reset anything" in a 2026-11-26 test. Allowed only when a
            # listed fact or the subtitles use that link word themselves.
            _links = re.findall(r"(?:^|[.!?]\s+|,\s+)(so|which is why|that is why|that's why|that is how|which means)\b",
                                c.get("body", ""), re.I)
            _have = " ".join([str(x.get("fact", "")) for x in _facts] + [subs]).lower()
            _bad_links = [w for w in _links if not re.search(rf"\b{re.escape(w.lower())}\b", _have)]
            if _bad_links:
                return False, (f"the card draws its own conclusion with '{_bad_links[0]}'. State the fact and "
                               "stop; never add a 'so' or 'which is why' conclusion that no listed fact states")
            shape_ok, shape_why = card_shape_ok(c.get("body", ""))
            if not shape_ok:
                return False, (f"{shape_why}: the viewer can already see that. Lead with the listed "
                               "fact instead and use the screen only to place it; never add a meaning "
                               "that no listed fact, subtitle or on-screen text states")
            head = c.get("headline", "")
            nh = len(head.split())
            if not (5 <= nh <= 9):
                return False, (f"the headline has {nh} words; write a 6 to 8 word headline with "
                               "the card's most surprising true point")
            _in_game = r"\s*in\s+(gta|grand theft auto|" + re.escape(gname.lower()) + r")\b"
            if any(re.match(_in_game, s.lower()) for s in (head, c.get("body", ""))):
                return False, "opens with 'In <game>'; lead with the surprise instead"
            if c.get("mode") not in ("player", "story"):
                return False, "no mode: say whether this is a player mechanic or a story moment"
            text = " ".join((head, c.get("body", ""), c.get("comment", "")))
            # The writer may return '[gta6-16]' for 'gta6-16'; an id that still matches
            # nothing would quietly skip the strict fact check, so it is a reject instead.
            fid = str(c.get("fact_id") or "").strip("[] ").lower()
            used = next((x for x in _facts if str(x.get("id")).lower() == fid), None)
            if fid and not used:
                return False, (f"fact_id '{c.get('fact_id')}' is not one of the listed facts; "
                               "use an exact id from the list, or leave it empty for a scene card")
            if used:
                c["fact_id"] = str(used.get("id"))
            # A fact card's facts come from the fact alone; a scene card's may also come from
            # research that does not hedge. Either way the screen and subtitles count.
            if used:
                # A second listed fact the card cites by id in its "facts" list counts too (2026-11-26:
                # the writer is told to add a second listed fact, and the checker refused it as unsourced).
                cited = set(re.findall(r"[a-z0-9]+-\d+", " ".join(map(str, c.get("facts") or [])).lower()))
                both = [used] + [x for x in _facts if str(x.get("id")).lower() in cited and x is not used][:1]
                fact_sup = " ".join(f"{x.get('fact', '')} {fact_source(x)}" for x in both)
                used_fact = "\n".join(f"[{x.get('id')}] {x.get('fact')} (source: {fact_source(x)}"
                                      + (f"; the card may credit it as: {outlet_say(x)}" if outlet_say(x) else "")
                                      + ")" for x in both)
            else:
                fact_sup, used_fact = confirmed_research(research), ""
            over = attribution_overreach(text, f"{fact_sup} {subs}")
            if over:
                return False, over
            from core import lore as _lore
            names_sup = " ".join((fact_sup, outlet_names(fact_sup), observation, subs, _lore.lore_for(game) or "",
                                  _lore.playable_note(game) or ""))
            suspects = unsupported_names(text, names_sup, extra_ok=(gname, *gname.split()))
            if suspects:
                log(f"names in no evidence, sent to the checker: {', '.join(suspects)}")
            ok, why = _check_card(c, observation, subs, gname, game, research, facts,
                                  used_fact=used_fact, suspects=suspects)
            if not ok:
                return ok, why
            score, notes, wrong = fan_critic(c, observation, subs, gname)
            log(f"fan critic: {score}/10 {notes}")
            if wrong:
                # 2026-11-24: a card scored 8/10 went through with a line the critic called wrong
                # ("permanent 'Irredeemable' status"). Any claim a fan reads as wrong is a rewrite,
                # whatever the score: one false line is what gets a card called AI garbage.
                return False, f"a real fan says it gets something wrong: {'; '.join(wrong)}"[:600]
            if score < FAN_MIN:
                return False, f"a real fan scored it {score}/10 ({notes})"
            return True, ""

        wrote = True
        # Humanize BEFORE the judges (user, 2026-11-09), so the fact-check runs on the exact
        # words that go on screen.
        from core import humanize
        card = humanize.card(_write_card(writer_obs, subs, game, gname, research=research,
                                         facts=facts),
                             gname, WORDS_MIN, WORDS_MAX)
        if card.get("body"):
            ok, why = _judge(card)
            if not ok:
                log(f"card rejected ({why}); rewriting.")
                # Two rewrites, each told exactly why the last one failed (2026-11-24: the fan critic's
                # notes say what a real fan wants, so a second rewrite usually lands).
                for attempt in (2, 3):
                    card2 = humanize.card(_write_card(writer_obs, subs, game, gname, avoid=why,
                                                      research=research, facts=facts),
                                          gname, WORDS_MIN, WORDS_MAX)
                    ok2, why2 = _judge(card2) if card2.get("body") else (False, "no card text")
                    if ok2:
                        card = card2
                        break
                    log(f"card {attempt} rejected ({why2})")
                    why = why2
                else:
                    raise CardRefused("three cards rejected (slop, facts or fan critic): not posting")
        if not card.get("body"):
            raise CardRefused("no card text was written")
        if card.get("fact_id") and any(str(x.get("id")) == card["fact_id"] for x in _facts):
            log(f"card is built on fact {card['fact_id']}")
            mark_fact(game, card["fact_id"])
        else:
            card.pop("fact_id", None)
        bad = unsafe_terms(" ".join((card["body"], card.get("comment", ""))))
        if bad:
            log(f"card contains advertiser-unsafe wording ({', '.join(bad)}) — rewriting body")
            card["body"] = re.sub(r"\b(?:%s)\b" % "|".join(map(re.escape, bad)), "", card["body"])
            card["body"] = re.sub(r"\s+", " ", card["body"]).strip()
        # The POST caption is written here, from the finished card, so every caller (the
        # reels track, the FB lore path, the CLI) posts the short elaboration instead of
        # re-posting the card text (user, 2026-10-08).
        card["caption"], card["title"] = lore_post_text(card, gname)
        log(f'caption: {card["caption"]}')
        log(f'title: {card["title"]}')

    # PAYOFF FIRST (Bryce, 2026-11-22: "show the payoff early"): start the clip about a second
    # before the moment the headline is about. Only the START moves later and the end stays,
    # so the clip never runs past the stretch that was observed and checked (adult content,
    # blocked ranges); at least 10 s are kept.
    zoom = None
    if not text:
        # Round 2 (review 2026-11-22: the writer's guess from 6 frames put a menu in the last
        # 2 s, and a camera-mode smear reached the end): find the payoff second and any broken
        # seconds on one frame per second, then trim. Only the start moves later and only the
        # end moves earlier, so nothing unchecked is added.
        scan = _payoff_scan(seg, dur, card)
        if scan and scan.get("shown") is False and wrote:
            # One rewrite about what the clip DOES show before giving up on this moment
            # (Bryce, 2026-11-23: a slot must always be filled, so do not waste a good moment).
            log("the headline's subject is not on screen; rewriting once about what the clip shows")
            c2 = humanize.card(_write_card(
                writer_obs, subs, game, gname, research=research, facts=facts,
                avoid="the HEADLINE's subject never appears in this clip; headline something the "
                      "clip clearly shows"), gname, WORDS_MIN, WORDS_MAX)
            if c2.get("body") and _judge(c2)[0]:
                scan2 = _payoff_scan(seg, dur, c2)
                if not (scan2 and scan2.get("shown") is False):
                    if c2.get("fact_id") and c2["fact_id"] != card.get("fact_id"):
                        mark_fact(game, c2["fact_id"])
                    c2["caption"], c2["title"] = lore_post_text(c2, gname)
                    card, scan = c2, scan2
        if scan and scan.get("shown") is False:
            raise CardRefused("the headline's subject never appears on screen in this clip")
        pay = float((scan or {}).get("payoff_s", card.get("payoff_at") or 0) or 0)
        bad = {int(b) for b in (scan or {}).get("bad_s", []) if str(b).lstrip("-").isdigit()}
        s0 = max(0.0, pay - 1.0)
        end = dur
        while int(end) - 1 in bad and end - s0 > 9:      # broken seconds at the tail
            end = float(int(end) - 1)
        while int(s0) in bad and end - s0 > 9 and s0 + 1 <= pay:   # and right after the new start
            s0 += 1.0
        if end - s0 < 8.0:                                # too short: keep more of the start
            s0 = max(0.0, end - 8.0) if end >= 8.0 else 0.0
        hold = (pay - s0) >= (end - s0) - 3.0             # payoff in the last 3 s: hold it
        if s0 >= 1.0 or end < dur or hold:
            vf_hold = ["-vf", "tpad=stop_mode=clone:stop_duration=2.5"] if hold else []
            start, dur = start + s0, end - s0
            subprocess.run([ff, "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
                            "-i", str(clip), *vf_hold, "-c:v", "libx264", "-crf", "18",
                            "-preset", "medium", "-c:a", "aac", "-b:a", "192k", str(seg)], check=True)
            if hold:
                dur += 2.5
            log(f"payoff first: clip {start:.1f}s for {dur:.1f}s (payoff at {pay:.0f}s of the old "
                f"window, cut {len(bad)} broken seconds" + (", payoff held 2.5 s)" if hold else ")"))
            pay = pay - s0
        # Small in-game text as the evidence (a toast, tooltip or menu line): zoom the picture
        # on it so it can be read on a phone. The layout stays the same.
        if card.get("text_evidence"):
            zoom = _text_box(seg, max(0.3, pay + 0.5), card)
    words = len(card["body"].split())
    log(f'headline: {card.get("headline", "")!r} | mode: {card.get("mode", "")!r}')
    log(f'highlight: {card.get("highlight", "")!r} | comment: {card.get("comment", "")!r}')
    log(f'body ({words} words, ~{words / 3.5:.0f}s to read vs a {dur:.0f}s video): {card["body"]}')
    (outdir / "card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    (outdir / "card.txt").write_text(
        f'{card["body"]}\n\n@kiwinoygaming: {card.get("comment", "")}\n', encoding="utf-8")

    # The video spans the card's FULL inner width. Any narrower and the hole punched in the
    # panel shows blurred background down each side of it (user spotted those strips).
    video_w = W - 36 * 2
    video_h = round(video_w * 9 / 16)
    lay = _layout(card, video_h, video_w)
    png = _card_png(card, outdir / "card.png", video_h, lay)
    out = outdir / "short.mp4"
    # blurred fill behind + the clip inset under the text + the overlay (text/comment/reaction)
    fg_crop = ""
    if zoom:   # fractions of the frame, already 16:9 and inside it
        x0, y0, zw, zh = zoom
        fg_crop = f"crop=iw*{zw:.4f}:ih*{zh:.4f}:iw*{x0:.4f}:ih*{y0:.4f},"
        log(f"zoomed on the on-screen text: {zw:.0%} of the frame width")
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"gblur=sigma=38,eq=brightness=-0.30[bg];"
          f"[0:v]{fg_crop}scale={video_w}:{video_h}[fg];"
          f"[bg][fg]overlay=(W-w)/2:{lay['video_y']}[v1];"
          f"[v1][1:v]overlay=0:0,format=yuv420p[v]")
    subprocess.run([ff, "-y", "-v", "error", "-stream_loop", "-1", "-i", str(seg),
                    "-i", str(png), "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
                    "-t", f"{dur:.2f}", "-r", "60", "-c:v", "libx264", "-crf", "20",
                    "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], check=True)
    log(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a lore-card short (clip + long read).")
    ap.add_argument("--clip", required=True, help="B2 footage name, or a local file path")
    ap.add_argument("--game", default="wolverine")
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the clip")
    ap.add_argument("--dur", type=float, default=8.0, help="short length (default 8s)")
    ap.add_argument("--text", default=None, help="use this card text instead of writing one")
    ap.add_argument("--log-name", default=None, help="footage-log file name when --clip is a local cut (tests)")
    ap.add_argument("--log-offset", type=float, default=0.0, help="where the local cut starts in that logged clip")
    ap.add_argument("--card-json", default=None,
                    help="re-render using a card.json from an earlier run (skips the writer)")
    a = ap.parse_args()

    clip = Path(a.clip)
    if not clip.exists():
        cache = ROOT / "output" / ".loreshort"
        cache.mkdir(parents=True, exist_ok=True)
        got = b2_store.download_footage(
            {"name": a.clip, "key": f"footage/{a.game}/{a.clip}"}, cache)
        if not got:
            raise SystemExit(f"[lore-short] clip not found locally or on B2: {a.clip}")
        clip = Path(got)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = ROOT / "output" / "lore-shorts" / f"{stamp}_{a.game}"
    card = json.loads(Path(a.card_json).read_text(encoding="utf-8")) if a.card_json else None
    try:
        build(clip, a.game, a.start, a.dur, a.text, outdir, card, log_name=a.log_name, log_offset=a.log_offset)
    except CardRefused as e:
        log(f"refused: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
