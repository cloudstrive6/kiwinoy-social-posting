"""Claims check: every narration claim about KG's footage is judged against that footage before any credits
are spent or anything renders (Bryce, 2026-11-23).

Why: the GTA 6 beginners guide said "I held up Tucker's farm stand" when Lucia had stopped a robbery in
progress and the clerk said "Just take whatever you came in for. It's on me." The script was written from 3
stills per clip. Bryce: "You need to watch/analyze more the scenes and really know each of the
videos/footage/scenes/gameplay well", and it must hold "during the automation/when the PC is off".

How: for each narration paragraph, every clip range it shows plus 30 s of context each side goes through
tools/footage_check.py (timed dialogue plus a labelled frame every 2 s), with the clip's footage log
(tools/footage_log.py) when there is one. Claude (subscription token only, never the paid API) reads the
sheets and marks every sentence:
  footage   says what happens, is shown, is said or is on screen in KG's own clips: true, false or unclear
  external  general game knowledge, guides, advice or opinion: not judged here
Results are cached per paragraph (text plus shots), so after a fix only the changed paragraphs are judged
again. A script passes when no footage claim is false or unclear, after Bryce's confirmations in
data/analysis/<game>/claims_override.json ([{"beat": "b011", "match": "words in the claim", "by":
"Bryce, 2026-11-23", "why": "..."}]).

The gate: tools/analysis_narrate.py and tools/analysis_render.py call gate() and stop, before any credits or
render time, when a gated script (every Guide C EDL, or "claims_gate": true) has no passing check for its
current text and shots. Older, already published videos are not gated.

    python tools/claims_check.py gta6-guide            # judge what is not cached, write the report
    python tools/claims_check.py gta6-guide --needs    # exit 0 if a check run is needed (CI uses this)
    python tools/claims_check.py gta6-guide --gate     # exit 1 and print the problems if the gate is shut
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from analysis_edl import strip_tags  # noqa: E402

VERSION = 3   # bump to re-judge every paragraph (prompt or packet change); 2: review fixes, 3: HUD sheets
PAD = 30.0
MODEL = "opus"

PROMPT = """You check a gaming channel's narration against the channel's own gameplay footage before it is
voiced. The narrator speaks as the player ("I held up ...", "I had $531 on me"). A false line misleads viewers
(2026-11-23: the script said the player robbed a farm stand; the footage shows the player STOPPED a robbery in
progress and the clerk offered the cash as a reward).

Open every contact sheet with the Read tool (frames are labelled with their time in the clip; hud sheets are the
top-right corner at full resolution, for the wallet and wanted stars), read the timed
dialogue and the footage log, then judge EVERY sentence of the narration.

kind "footage": the sentence says what happens, what is shown, what is said, what is on screen, or what the
player did, had, earned or saw in this footage. Verdict:
  "true"    the frames or dialogue clearly support it;
  "false"   the footage contradicts it (who did what, amounts, order of events, what a notice says);
  "unclear" the packet cannot show it either way (for example the amount is not legible, or the moment is
            outside these ranges and the log does not cover it).
If a range's dialogue says "(audio could not be read)", nothing about speech in that range is known: a claim
that depends on what was said there is "unclear", never "true" or "false" from silence.
kind "external": general game knowledge, what guides or the community say, mechanics not shown here, advice,
opinion, jokes, or channel talk. Verdict "external"; it is not judged.

Be strict on who did what: who starts a crime, who is the victim, who gives money to whom, and whether the
player was rewarded, paid, robbed or stole. Numbers must match what is legible.

Reply with JSON only:
{{"claims": [{{"text": "the sentence", "kind": "footage|external",
              "verdict": "true|false|unclear|external",
              "evidence": "time in the clip plus what is seen or heard (empty for external)",
              "fix": "for false or unclear: a corrected sentence true to the footage, in the same voice"}}]}}

Paragraph {beat} (a hyphenated spelling like "Loo-see-ah" is how a name is pronounced, here Lucia; judge it as the name):
{text}

Footage shown under it (each range includes {pad:.0f} s of context either side):
{ranges}

Footage log excerpts (whole-clip logs, may be missing):
{logs}

Verified footage facts for this game (who is who, whose home, whose car; data/footage_facts/). Use them to
settle names and ownership instead of calling a claim unclear:
{facts}

Contact sheets to open:
{sheets}
"""


# Guide C videos already published before the gate (2026-11-23): their reels are live in the rotation and
# were reviewed by Bryce, so a re-render must not wait on a fresh check. Every later Guide C video is gated.
EXEMPT = {"spider-man1-reels", "spider-man2-reels"}


def gated(edl: dict, game: str = "") -> bool:
    if edl.get("claims_gate") is False or game in EXEMPT:
        return False
    nar = edl.get("narrator") or {}
    return bool(edl.get("claims_gate")) or nar.get("name") == "BOSS KG Guide C"


def narr_beats(edl: dict) -> list[dict]:
    return [b for b in edl["beats"] if b["type"] == "narr"]


_CLIPS: dict = {}  # game -> clips.json map, so a signature names the clip FILE, not its index (review)


def beat_sig(b: dict, game: str) -> str:
    clips = _CLIPS.get(game) or load(game)[1]
    shots = [(clips.get(str(sh.get("clip")), {}).get("key", f"missing:{sh.get('clip')}"), sh.get("in"), sh.get("out"))
             for sh in b.get("shots") or []]
    return hashlib.sha1(json.dumps([VERSION, strip_tags(b.get("tts") or b.get("text") or ""), shots],
                                   default=str).encode()).hexdigest()[:16]


def script_hash(edl: dict, game: str) -> str:
    return hashlib.sha1("|".join(f"{b['id']}:{beat_sig(b, game)}" for b in narr_beats(edl)).encode()).hexdigest()[:16]


def load(game: str) -> tuple[dict, dict]:
    """The EDL with edits.json applied exactly as analysis_render applies it, so the check judges the shots
    that are rendered (review 2026-11-23: two reel EDLs override narration shots there)."""
    d = ROOT / "data/analysis" / game
    edl = json.loads((d / "edl.json").read_text(encoding="utf-8"))
    ep = d / "edits.json"
    if ep.exists():
        ed = json.loads(ep.read_text(encoding="utf-8"))
        over, bover = ed.get("shots", {}), ed.get("beats", {})
        for b in edl["beats"]:
            if b["id"] in over:
                b["shots"] = over[b["id"]]
            b.update(bover.get(b["id"], {}))
    clips = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
    _CLIPS[game] = clips
    return edl, clips


def overrides(game: str) -> list[dict]:
    p = ROOT / "data/analysis" / game / "claims_override.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def cache_key(game: str, sig: str) -> str:
    return f"claims/{game}/beats/{sig}.json"


def cached(game: str, sig: str) -> dict | None:
    local = ROOT / "output/analysis" / game / "claims" / f"{sig}.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    from core import b2_store
    data = b2_store.get_bytes(cache_key(game, sig))
    if data:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return json.loads(data)
    return None


def store(game: str, sig: str, res: dict) -> None:
    from core import b2_store
    local = ROOT / "output/analysis" / game / "claims" / f"{sig}.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(res, indent=1).encode()
    local.write_bytes(data)
    if not b2_store.put_bytes(cache_key(game, sig), data, "application/json"):
        print(f"warning: could not save {sig} to B2 (kept locally)", flush=True)


def log_excerpt(key: str, s: float, e: float) -> str:
    from core import b2_store
    data = b2_store.get_bytes(f"footage-log/{key}.json")
    if not data:
        return f"{key}: no log yet"
    log = json.loads(data)
    ev = [x for x in log.get("events", []) if float(x.get("end", 0)) >= s - 60 and float(x.get("start", 0)) <= e + 60]
    return f"{key}: {log.get('summary', '')}\n" + "\n".join(
        f"  {x.get('start')}-{x.get('end')} s [{x.get('certainty', '')}] {x.get('what', '')} | player: "
        f"{x.get('player_does', '')} | others: {x.get('others_do', '')} | text: {x.get('on_screen_text', '')} | "
        f"money: {x.get('money', '')} | quote: {x.get('quote', '')}" for x in ev)


def footage_facts(keys) -> str:
    """data/footage_facts/<game folder>.md for the games these clips come from (2026-11-23: agents, not Bryce,
    settle who is who; b054 was 'unclear' only because the judge could not tell whose house it was)."""
    out = []
    for g in sorted({k.split("/")[1] for k in keys if k.count("/") >= 2}):
        p = ROOT / "data" / "footage_facts" / f"{g}.md"
        if p.exists():
            out.append(p.read_text(encoding="utf-8"))
    return "\n\n".join(out) or "(none yet)"


def judge(game: str, b: dict, clips: dict) -> dict:
    from core import claude_code
    from footage_audit import merged
    from footage_check import run_check
    length = {c["key"]: float(c.get("seconds") or 0) or 1e9 for c in clips.values()}
    rs = [(clips[str(sh["clip"])]["key"], float(sh.get("in", 0)), float(sh.get("out", float(sh.get("in", 0)) + 6)))
          for sh in b.get("shots") or []]
    parts, logs, sheets = [], [], []
    for i, (key, s, e) in enumerate(merged(rs, PAD, length)):
        out = run_check(key, round(s, 1), round(e, 1), f"{game}/{b['id']}-{i + 1}")
        parts.append((out / "dialogue.txt").read_text(encoding="utf-8"))
        logs.append(log_excerpt(key, s, e))
        sheets += [str(p.resolve()) for p in sorted(out.glob("sheet*.jpg")) + sorted(out.glob("hud*.jpg"))]
    prompt = PROMPT.format(beat=b["id"], text=strip_tags(b.get("tts") or b.get("text") or ""), pad=PAD,
                           ranges="\n\n".join(parts) or "(no footage)", logs="\n\n".join(logs) or "(none)",
                           facts=footage_facts([k for k, _, _ in rs]), sheets="\n".join(sheets) or "(none)")
    reply = claude_code.run(prompt, model=MODEL, allowed_tools="Read", timeout=900)
    m = re.search(r"\{.*\}", reply, re.S)
    try:
        res = json.loads(m.group(0)) if m else {"claims": [], "error": reply[:500]}
    except Exception as e:
        res = {"claims": [], "error": f"unreadable reply ({e!r})"}
    if not res.get("error"):
        why = invalid(res, strip_tags(b.get("tts") or b.get("text") or ""))
        if why:
            res["error"] = why  # never cached, so the paragraph stays "not checked" and the gate stays shut
    res.update(beat=b["id"], sig=beat_sig(b, game), model=MODEL, version=VERSION,
               made=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    return res


def _toks(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9']+", s.lower()) if len(w) > 2}


def invalid(res: dict, text: str) -> str:
    """Why a judge reply cannot be trusted (review 2026-11-23: an empty list, a wrong kind or a skipped
    sentence used to pass), or "" when every sentence is judged with a known kind and verdict."""
    claims = res.get("claims")
    if not isinstance(claims, list) or not claims:
        return "the judge returned no claims"
    for c in claims:
        if not isinstance(c, dict) or c.get("kind") not in ("footage", "external"):
            return f"a claim has kind {c.get('kind') if isinstance(c, dict) else c!r}"
        ok = ("true", "false", "unclear") if c["kind"] == "footage" else ("external",)
        if c.get("verdict") not in ok:
            return f"a {c['kind']} claim has verdict {c.get('verdict')!r}"
    judged = [_toks(c.get("text", "")) for c in claims]
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        st = _toks(s)
        if st and not any(len(st & j) >= 0.6 * len(st) for j in judged):
            return f"sentence not judged: {s[:80]!r}"
    return ""


def problems(game: str, edl: dict) -> list[str]:
    """Footage claims that are false or unclear, after Bryce's confirmations; plus paragraphs never judged."""
    ov = overrides(game)
    out = []
    for b in narr_beats(edl):
        sig = beat_sig(b, game)
        res = cached(game, sig)
        if res is None:
            out.append(f"{b['id']}: not checked yet")
            continue
        if res.get("error"):
            out.append(f"{b['id']}: the check failed ({res['error'][:80]})")
        for c in res.get("claims", []):
            if c.get("kind") != "footage" or c.get("verdict") == "true":
                continue
            # Bryce's confirmation counts only for this exact paragraph version and a specific match
            # (review 2026-11-23: an empty match waived everything, and a confirmation outlived a rewrite)
            if any(o.get("beat") == b["id"] and o.get("sig") == sig and len(str(o.get("match", "")).strip()) >= 12
                   and str(o["match"]).lower() in c.get("text", "").lower() for o in ov):
                continue
            out.append(f"{b['id']} [{c.get('verdict')}] {c.get('text', '')} | footage: {c.get('evidence', '')} | "
                       f"fix: {c.get('fix', '')}")
    return out


def gate(game: str, edl: dict | None = None, notify: bool = True) -> None:
    """Stop (SystemExit) when a gated script has false, unclear or unchecked footage claims."""
    edl = load(game)[0]  # always the rendered version (edits.json applied), whatever the caller holds
    if not gated(edl, game):
        return
    bad = problems(game, edl)
    if not bad:
        print(f"claims check: passed for script {script_hash(edl, game)}", flush=True)
        return
    msg = (f"Claims check stopped {game}: {len(bad)} narration line(s) are false, unclear or not checked "
           f"against the footage. Nothing was voiced or rendered.\n" + "\n".join(f"- {x}" for x in bad[:12]))
    if notify:
        try:
            from core.notify import telegram
            telegram(msg[:3500])
        except Exception as e:
            print(f"Telegram note skipped: {e!r}", flush=True)
    raise SystemExit(msg)


def report(game: str, edl: dict) -> str:
    lines = [f"# Claims check: {game} (script {script_hash(edl, game)})", ""]
    counts = {"true": 0, "false": 0, "unclear": 0, "external": 0}
    for b in narr_beats(edl):
        res = cached(game, beat_sig(b, game)) or {}
        lines.append(f"## {b['id']}")
        for c in res.get("claims", []):
            v = c.get("verdict", "?")
            counts[v] = counts.get(v, 0) + 1
            lines.append(f"- [{v}] {c.get('text', '')}")
            if v in ("false", "unclear"):
                lines.append(f"  - footage: {c.get('evidence', '')}")
                lines.append(f"  - fix: {c.get('fix', '')}")
        lines.append("")
    bad = problems(game, edl)
    head = (f"Result: {'PASS' if not bad else 'FAIL'}; {counts.get('true', 0)} true, {counts.get('false', 0)} "
            f"false, {counts.get('unclear', 0)} unclear, {counts.get('external', 0)} external (not judged); "
            f"{len(bad)} open after confirmations.\n")
    return lines[0] + "\n\n" + head + "\n" + "\n".join(lines[2:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--needs", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    edl, clips = load(a.game)
    if a.needs:
        return 0 if gated(edl, a.game) and any(cached(a.game, beat_sig(b, a.game)) is None for b in narr_beats(edl)) else 1
    if a.gate:
        try:
            gate(a.game, edl, notify=False)
            return 0
        except SystemExit as e:
            print(e)
            return 1
    from core import claude_code
    claude_code._anthropic_key = lambda: ""  # subscription only: never fall back to the paid API
    if not claude_code.available_token():
        raise SystemExit("CLAUDE_CODE_OAUTH_TOKEN is not set (the check runs on the subscription, never the paid API)")
    only = set(filter(None, a.only.split(",")))
    todo = [b for b in narr_beats(edl) if (not only or b["id"] in only) and cached(a.game, beat_sig(b, a.game)) is None]
    print(f"claims check {a.game}: {len(todo)} paragraph(s) to judge", flush=True)

    def one(b):
        t0 = time.time()
        for attempt in range(2):
            try:
                res = judge(a.game, b, clips)
                if not res.get("error"):
                    break
            except Exception as e:
                res = {"claims": [], "error": repr(e)[:300]}
        if not res.get("error"):
            store(a.game, beat_sig(b, a.game), res)  # failures are not cached, so the next run tries again
        bad = [c for c in res.get("claims", []) if c.get("kind") == "footage" and c.get("verdict") != "true"]
        print(f"{b['id']}: {len(res.get('claims', []))} claims, {len(bad)} to fix"
              f"{' (check failed: ' + res['error'][:80] + ')' if res.get('error') else ''}, {time.time() - t0:.0f} s",
              flush=True)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        list(ex.map(one, todo))
    rep = report(a.game, edl)
    out = ROOT / "output/analysis" / a.game
    out.mkdir(parents=True, exist_ok=True)
    (out / "claims.md").write_text(rep, encoding="utf-8")
    print(rep[:4000], flush=True)
    return 0 if not problems(a.game, edl) else 2


if __name__ == "__main__":
    raise SystemExit(main())
