"""Push a short message to the user's phone — used to send TikTok DRAFT captions so they
can copy-paste when publishing (TikTok's draft API ignores captions; see
[[tiktok-direct-integration]]).

TELEGRAM is the backend: free, instant, no approval (SMS needs a paid Twilio number;
WhatsApp needs Meta Business API review + message templates). Fail-open: a no-op if
unconfigured, and never raises into the caller.

One-time setup (both values are env-only — .env locally, GitHub Secrets in CI):
  1. In Telegram, message @BotFather -> /newbot -> name it -> copy the token  => TELEGRAM_BOT_TOKEN
  2. Message your new bot anything (say "hi") so it can DM you.
  3. Get your chat id:  python -m core.notify chatid   (prints the id from your "hi")  => TELEGRAM_CHAT_ID
  4. Test:  python -m core.notify test
"""
from __future__ import annotations

import sys

from core.config import CONFIG

API = "https://api.telegram.org/bot{token}/{method}"


def _creds() -> tuple[str, str]:
    return CONFIG.telegram_bot_token, CONFIG.telegram_chat_id


def enabled() -> bool:
    tok, chat = _creds()
    return bool(tok and chat)


def telegram(text: str) -> bool:
    """Send `text` to the configured Telegram chat. Returns True on success, False if
    unconfigured or on any error (never raises)."""
    tok, chat = _creds()
    if not (tok and chat):
        print("[notify] Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) "
              "— skipping.", flush=True)
        return False
    try:
        import requests
        r = requests.post(
            API.format(token=tok, method="sendMessage"),
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=20)
        if r.status_code >= 400:
            print(f"[notify] Telegram send failed [{r.status_code}]: {r.text[:200]}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[notify] Telegram error ({e!r}) — continuing.", flush=True)
        return False


def tiktok_draft_caption(caption: str, game: str = "") -> bool:
    """Notify that a TikTok DRAFT is ready, with the exact caption to paste."""
    head = "🎬 TikTok draft ready — copy-paste this caption:"
    if game:
        head = f"🎬 TikTok draft ready ({game}) — copy-paste this caption:"
    return telegram(f"{head}\n\n{caption}")


def _get_chat_id() -> None:
    """Print the chat id of whoever last messaged the bot (getUpdates)."""
    import requests
    tok = CONFIG.telegram_bot_token
    if not tok:
        sys.exit("Set TELEGRAM_BOT_TOKEN first (from @BotFather).")
    r = requests.get(API.format(token=tok, method="getUpdates"), timeout=20)
    r.raise_for_status()
    updates = r.json().get("result", [])
    if not updates:
        sys.exit("No messages yet — open Telegram, message your bot 'hi', then retry.")
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat", {})
        if chat.get("id"):
            print(f"chat id: {chat['id']}  ({chat.get('username') or chat.get('first_name')})")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "test"
    if arg == "chatid":
        _get_chat_id()
    else:
        print("sent" if telegram("✅ KiwinoyGamer notifier test — this is working.") else "not sent")
