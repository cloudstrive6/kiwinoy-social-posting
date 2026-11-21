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
    return send(text) is not None


def _call(method: str, payload: dict):
    """One Bot API call with a JSON body, to the configured chat's bot. Returns the `result`
    (a dict, True, ...) or None when unconfigured or on any error. Never raises."""
    tok, chat = _creds()
    if not (tok and chat):
        return None
    try:
        import requests
        r = requests.post(API.format(token=tok, method=method), json=payload, timeout=20)
        d = r.json() if r.content else {}
        if not d.get("ok"):
            print(f"[notify] Telegram {method} failed [{r.status_code}]: "
                  f"{str(d.get('description', ''))[:200]}", flush=True)
            return None
        return d.get("result")
    except Exception as e:
        print(f"[notify] Telegram {method} error ({e!r}) - continuing.", flush=True)
        return None


def send(text: str, reply_markup: dict | None = None, reply_to: int | None = None) -> int | None:
    """Send `text` (optionally with inline buttons, optionally as a reply to one of the chat's
    messages) and return the new message_id, or None. Never raises."""
    payload = {"chat_id": _creds()[1], "text": text[:4096], "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if reply_to:
        payload["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    res = _call("sendMessage", payload)
    return int(res["message_id"]) if isinstance(res, dict) and res.get("message_id") else None


def edit(message_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Replace a bot message's text. Without `reply_markup` its buttons are removed, so a
    decided draft can't be tapped again."""
    payload = {"chat_id": _creds()[1], "message_id": int(message_id), "text": text[:4096],
               "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("editMessageText", payload) is not None


def edit_markup(message_id: int, reply_markup: dict | None) -> bool:
    """Replace (or with None, remove) a bot message's inline buttons, keeping its text."""
    payload = {"chat_id": _creds()[1], "message_id": int(message_id),
               "reply_markup": reply_markup or {"inline_keyboard": []}}
    return _call("editMessageReplyMarkup", payload) is not None


def answer_callback(callback_query_id: str, text: str = "") -> bool:
    """Answer a button tap (stops the button's spinner, shows `text` as a small toast). The
    poller runs every few minutes, so Telegram may already call the tap too old; that's fine."""
    return _call("answerCallbackQuery", {"callback_query_id": callback_query_id,
                                         "text": text[:200]}) is not None


def telegram_photo(image_path, caption: str = "") -> bool:
    """Send a photo (with an optional caption) to the configured Telegram chat, so a
    draft is reviewable at a glance on the phone. Returns True on success; never raises.
    Caption is capped at Telegram's 1024-char photo-caption limit."""
    tok, chat = _creds()
    if not (tok and chat):
        return False
    try:
        import requests
        with open(image_path, "rb") as fh:
            r = requests.post(
                API.format(token=tok, method="sendPhoto"),
                data={"chat_id": chat, "caption": (caption or "")[:1024]},
                files={"photo": fh}, timeout=60)
        if r.status_code >= 400:
            print(f"[notify] Telegram photo failed [{r.status_code}]: {r.text[:200]}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[notify] Telegram photo error ({e!r}) — continuing.", flush=True)
        return False


def tiktok_draft_caption(caption: str, game: str = "") -> bool:
    """Send ONE message per TikTok draft = the caption + hashtags ONLY (no header/prefix),
    so long-press -> Copy grabs exactly what to paste into TikTok. One post = one message."""
    return telegram(caption)


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
