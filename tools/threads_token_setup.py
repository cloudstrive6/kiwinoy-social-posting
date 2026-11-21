"""One-time Threads token for the bosskg.com follower count (2026-11-21). Bryce runs this himself.

Before running: Meta for Developers, app "KG Publisher for Threads" (1004786802050130), Use cases,
Access the Threads API, Customize, Settings, User Token Generator, "Generate Access Token" next to
kiwinoygaming, approve in the Threads window, then copy the token it shows.

This script reads the token from the clipboard (then clears the clipboard), checks it can read
@kiwinoygaming's follower count (threads_manage_insights), and saves it as the GitHub secret
THREADS_ACCESS_TOKEN and on private B2 (secrets/threads-token.json), where tools/social_stats.py
renews it every 7 days. The token is never printed or written to a file in the repo.

    python tools/threads_token_setup.py
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:  # Avast intercepts TLS on this PC; use the Windows certificate store
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

REPO = "cloudstrive6/kiwinoy-social-posting"
KEY = "secrets/threads-token.json"


def clipboard_token() -> str:
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get().strip()
        if re.fullmatch(r"TH[A-Za-z0-9_\-]{40,}", text):
            root.clipboard_clear()
            root.clipboard_append(" ")
            root.update()
        else:
            text = ""
        root.destroy()
        return text
    except Exception:
        return ""


def get(path: str, params: dict) -> dict:
    url = f"https://graph.threads.net/v1.0/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    input("Copy the Threads access token from the User Token Generator, then press Enter here: ")
    tok = clipboard_token()
    if not tok:
        print("The clipboard does not hold a Threads token (it starts with TH). Copy it again and rerun.")
        return 1
    print(f"Token read ({len(tok)} characters).")
    me = get("me", {"fields": "username", "access_token": tok})
    print(f"Token is for @{me.get('username')}.")
    if me.get("username") != "kiwinoygaming":
        print("That is not @kiwinoygaming; nothing saved.")
        return 1
    ins = get("me/threads_insights", {"metric": "followers_count", "access_token": tok})
    n = next(((m.get("total_value") or {}).get("value") for m in ins.get("data", []) if m.get("name") == "followers_count"), None)
    print(f"Threads followers right now: {n}")
    r = subprocess.run(["gh", "secret", "set", "THREADS_ACCESS_TOKEN", "-R", REPO], input=tok, text=True, capture_output=True)
    print(f"GitHub secret THREADS_ACCESS_TOKEN: {'saved' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()[:200]}")
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from core import b2_store
        now = dt.datetime.now(dt.timezone.utc)
        rec = {"access_token": tok, "refreshed_at": now.isoformat(), "expires_at": (now + dt.timedelta(days=60)).isoformat()}
        print(f"Private B2 copy: {'saved' if b2_store.put_bytes(KEY, json.dumps(rec).encode()) else 'not saved (the daily job will save it)'}")
    except Exception as e:
        print(f"Private B2 copy: not saved ({type(e).__name__}); the daily job will save it")
    print("All done. Tell Claude it finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
