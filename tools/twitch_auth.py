"""One-time Twitch login for the bosskg.com follower count (2026-11-21). Bryce runs this himself.

Twitch's follower endpoint (GET helix/channels/followers) needs a USER access token; with no scope it
returns only the total, which is all the site needs. This script:
  1. reads the app's Client Secret from the clipboard (hidden prompt as a fallback), then clears the
     clipboard; the secret is never printed or written to a file;
  2. opens Twitch's authorize page in the browser (no scopes) and catches the reply on
     http://localhost:3000/twitch (the redirect URL registered on the "BOSS KG Stats" app);
  3. trades the code for tokens, checks the login is kiwinoy, and checks that the refresh token can be
     used twice (confidential-client refresh tokens do not expire);
  4. stores TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET and TWITCH_REFRESH_TOKEN as GitHub Actions secrets
     with `gh secret set` (value on stdin), and prints only names and the follower total.

    python tools/twitch_auth.py <client id>
"""
from __future__ import annotations

import getpass
import http.server
import json
import secrets
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

try:  # Avast intercepts TLS on this PC; use the Windows certificate store
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

REPO = "cloudstrive6/kiwinoy-social-posting"
REDIRECT = "http://localhost:3000/twitch"
LOGIN = "kiwinoy"


def post(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(url: str, headers: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.loads(r.read())


def clipboard_secret() -> str:
    """The clipboard's text if it looks like a Twitch secret (30 lowercase letters and digits), then
    the clipboard is cleared. Never printed."""
    import re
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get().strip()
        if re.fullmatch(r"[a-z0-9]{20,64}", text):
            root.clipboard_clear()
            root.clipboard_append(" ")
            root.update()
        else:
            text = ""
        root.destroy()
        return text
    except Exception:
        return ""


def refresh(cid: str, secret: str, rt: str) -> dict | None:
    try:
        return post("https://id.twitch.tv/oauth2/token", {"client_id": cid, "client_secret": secret,
                                                          "grant_type": "refresh_token", "refresh_token": rt})
    except Exception:
        return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cid = sys.argv[1].strip()
    # From the clipboard (2026-11-21: a hidden prompt would not take a paste in the app's terminal).
    input("Copy the Client Secret (New Secret, then the copy button), then press Enter here: ")
    secret = clipboard_secret()
    if not secret:
        secret = getpass.getpass("Clipboard was empty or not a secret. Type or right-click paste it (hidden): ").strip()
    if not secret:
        print("No secret entered.")
        return 1
    print(f"Secret read ({len(secret)} characters).")
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and go back to the terminal.")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("localhost", 3000), H)
    th = threading.Thread(target=srv.handle_request, daemon=True)
    th.start()
    url = "https://id.twitch.tv/oauth2/authorize?" + urllib.parse.urlencode(
        {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": "",
         "state": state, "force_verify": "true"})
    print("Opening Twitch in your browser: sign in as kiwinoy if asked and click Authorize.")
    webbrowser.open(url)
    th.join(timeout=600)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        print("No authorization came back:", got.get("error_description") or got.get("error") or "timed out")
        return 1
    tok = post("https://id.twitch.tv/oauth2/token", {"client_id": cid, "client_secret": secret, "code": got["code"],
                                                     "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    h = {"Authorization": f"Bearer {tok['access_token']}", "Client-Id": cid}
    who = get("https://api.twitch.tv/helix/users", h)["data"][0]
    print(f"Signed in as {who['login']}.")
    if who["login"].lower() != LOGIN:
        print(f"That is not {LOGIN}; nothing saved. Sign out of Twitch and run this again.")
        return 1
    total = get(f"https://api.twitch.tv/helix/channels/followers?broadcaster_id={who['id']}", h).get("total")
    print(f"Twitch followers right now: {total}")
    rt = tok["refresh_token"]
    first, again = refresh(cid, secret, rt), refresh(cid, secret, rt)
    if not first:
        print("Refreshing the token failed; nothing saved.")
        return 1
    reusable = again is not None
    keep = rt if reusable else first["refresh_token"]
    print("Refresh token reusable:", "yes" if reusable else "NO (single use; tell Claude)")
    for name, value in (("TWITCH_CLIENT_ID", cid), ("TWITCH_CLIENT_SECRET", secret), ("TWITCH_REFRESH_TOKEN", keep)):
        r = subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=value, text=True, capture_output=True)
        print(f"GitHub secret {name}: {'saved' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()[:200]}")
    print("All done. Tell Claude it finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
