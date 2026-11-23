"""Store the Modal token for the VoxCPM2 backup narrator as GitHub secrets (2026-11-23). Bryce runs this.

On modal.com, Settings, API Tokens, New Token: Modal shows one command,
`modal token set --token-id ak-... --token-secret as-...`, with a copy button. Press copy, then run
this script and press Enter. It reads the ID and secret from the clipboard, clears the clipboard,
and saves MODAL_TOKEN_ID and MODAL_TOKEN_SECRET on the KG repo with `gh secret set` (value on stdin).
Neither value is printed or written to a file.

    python tools/modal_token_setup.py
"""
from __future__ import annotations

import getpass
import re
import subprocess

REPO = "cloudstrive6/kiwinoy-social-posting"


def from_clipboard() -> tuple[str, str]:
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get()
        tid = re.search(r"\bak-[A-Za-z0-9]{8,}\b", text)
        sec = re.search(r"\bas-[A-Za-z0-9]{8,}\b", text)
        if tid and sec:
            root.clipboard_clear()
            root.clipboard_append(" ")
            root.update()
        root.destroy()
        return (tid.group(), sec.group()) if tid and sec else ("", "")
    except Exception:
        return "", ""


def main() -> int:
    # getpass, not input: anything pasted here by mistake does not show on screen
    getpass.getpass("Copy the 'modal token set ...' command on Modal (copy button), then press Enter here (do not paste): ")
    tid, sec = from_clipboard()
    if not (tid and sec):
        print("The clipboard did not hold a Modal token (ak-... and as-...). Copy it again and rerun.")
        return 1
    print(f"Token read (ID {len(tid)} characters, secret {len(sec)} characters).")
    for name, value in (("MODAL_TOKEN_ID", tid), ("MODAL_TOKEN_SECRET", sec)):
        r = subprocess.run(["gh", "secret", "set", name, "-R", REPO], input=value, text=True, capture_output=True)
        print(f"GitHub secret {name}: {'saved' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()[:200]}")
    print("All done. Tell Claude it finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
