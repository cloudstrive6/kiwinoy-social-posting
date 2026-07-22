"""Poll Telegram for on-demand commands (currently: "ig draft") and hand them to the
ig-poller.yml workflow so the user can fire a reel from their phone with the PC off.

SECURITY: only messages from TELEGRAM_CHAT_ID are honoured — a chat-id gate so nobody
else who finds the bot can trigger a render. The only command runs `tools/ig_draft.py`,
which renders a full-bleed reel + uploads it to the PRIVATE B2 `drafts/ig/` + pings the
user; it NEVER posts anything publicly. Commands understood:
    "ig draft"              -> default game, whole clip
    "ig draft halo"         -> a specific game
    "ig draft 30s"          -> cap the length

Modes:
    python tools/telegram_poller.py --check   # CI: confirm updates, ack, emit GITHUB_OUTPUT (fire/game/seconds)
    python tools/telegram_poller.py           # local: print what it WOULD do (reads only; no ack, no confirm)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import CONFIG          # noqa: E402
from core import notify                 # noqa: E402

API = "https://api.telegram.org/bot{token}/{method}"
CMD_RE = re.compile(r"\big[\s_-]?draft\b", re.I)     # "ig draft" / "ig-draft" / "igdraft"
_ALIASES = {
    "spiderman": "spider-man2", "spider man": "spider-man2", "spidey": "spider-man2",
    "sm2": "spider-man2", "tlou": "thelastofus2", "last of us": "thelastofus2",
    "ff7": "ff7remake", "final fantasy": "ff7remake",
}


def _tg(method: str, **params):
    import requests
    tok = CONFIG.telegram_bot_token
    try:
        r = requests.get(API.format(token=tok, method=method), params=params, timeout=30)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def _resolve_game(text: str) -> str:
    """A valid game KEY parsed from the text, else the default track game. Always returns
    a KNOWN key (kebab-case) — safe to pass to the shell in the workflow."""
    t = text.lower()
    names = CONFIG.reels.get("game_names", {}) or {}
    for key, disp in names.items():
        if re.search(rf"\b{re.escape(str(key).lower())}\b", t) or (disp and str(disp).lower() in t):
            return str(key)
    for alias, key in _ALIASES.items():
        if alias in t:
            return key
    over = ((CONFIG.reels.get("gameplay", {}) or {}).get("prefer_override", {}) or {}).get("games") or []
    return str(over[0]) if over else str((CONFIG.reels.get("tiktok", {}) or {}).get("game", "spider-man2"))


def _seconds(text: str) -> int:
    m = re.search(r"\b(\d{1,3})\s*s(ec(onds)?)?\b", text.lower())
    return int(m.group(1)) if m else 0


def _emit(fire: int, game: str = "", seconds: int = 0) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"fire={fire}\ngame={game}\nseconds={seconds}\n")


def main() -> int:
    check = "--check" in sys.argv
    if not notify.enabled():
        print("[poller] Telegram not configured — nothing to do.", flush=True)
        _emit(0)
        return 0
    chat_id = str(CONFIG.telegram_chat_id)
    updates = (_tg("getUpdates") or {}).get("result", []) or []
    if not updates:
        print("[poller] no updates.", flush=True)
        _emit(0)
        return 0
    max_uid = max(int(u.get("update_id", 0)) for u in updates)
    cmd = ""
    for u in updates:                                    # keep the LATEST matching command
        msg = u.get("message") or u.get("edited_message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat_id:
            continue                                     # chat-id gate: ignore everyone else
        text = (msg.get("text") or "").strip()
        if CMD_RE.search(text):
            cmd = text
    if check:                                            # mark ALL updates seen (before firing)
        _tg("getUpdates", offset=max_uid + 1)
    if not cmd:
        print("[poller] no ig-draft command in this batch.", flush=True)
        _emit(0)
        return 0
    game, secs = _resolve_game(cmd), _seconds(cmd)
    print(f"[poller] command: {cmd!r} -> game={game} seconds={secs}", flush=True)
    if check:
        notify.telegram(f"\U0001F3AC Got it — rendering an IG draft ({game}"
                        + (f", {secs}s" if secs else "") + "). It'll land in drafts/ig in a couple minutes…")
        _emit(1, game, secs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
