"""Weekly newsletter digest — the FREE, self-hosted stand-in for MailerLite's
(premium) RSS campaign.

Reads the site feed at https://bosskg.com/rss.xml (which now carries BOTH news
articles AND YouTube longform/live video pages), and if >=1 item was published in
the last N days, builds a branded digest and sends it as a MailerLite *regular*
campaign to the newsletter group via the API. Runs on a GitHub Actions cron
(Sunday 10:00 Manila = 02:00 UTC).

Only sends when there's fresh content (never an empty digest). Idempotent: the
campaign is NAMED by ISO week and we skip if that week's digest already exists, so
a re-run / double-fire never double-sends — MailerLite itself is the state store.

Env (GitHub Actions Secrets / local .env):
  MAILERLITE_API_KEY   (required)  MailerLite -> Integrations -> API -> token
  MAILERLITE_GROUP_ID  (optional)  defaults to the public "The KG Drop" group id

One-time setup: add MAILERLITE_API_KEY to the repo's Actions secrets (it currently
lives only in the Netlify site env).

Usage:
  python -m tools.rss_digest --dry-run     # build + preview, NO API calls, no send
  python -m tools.rss_digest               # send this week's digest if there's new content
  python -m tools.rss_digest --days 7 --force   # ignore the "already sent this week" guard
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from core.config import CONFIG
from core.notify import telegram

# Emoji in subjects/logs must not crash a non-UTF-8 console (Windows cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FEED_URL = "https://bosskg.com/rss.xml"
API = "https://connect.mailerlite.com/api"
SITE = "https://bosskg.com"
FROM_NAME = "Boss KG"
FROM_EMAIL = "hello@bosskg.com"


# ---- feed -------------------------------------------------------------------
def fetch_items() -> list[dict]:
    """Return the feed items as dicts: {title, link, description, dt, is_video}."""
    import requests

    r = requests.get(FEED_URL, timeout=30, headers={"User-Agent": "kg-rss-digest/1.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items: list[dict] = []
    for it in root.iterfind(".//item"):
        link = (it.findtext("link") or "").strip()
        raw_date = (it.findtext("pubDate") or "").strip()
        try:
            dt = parsedate_to_datetime(raw_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": link,
            "description": (it.findtext("description") or "").strip(),
            "dt": dt,
            "is_video": "/watch/" in link,
        })
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items


def recent(items: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [i for i in items if i["dt"] >= cutoff]


# ---- email ------------------------------------------------------------------
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def subject_for(items: list[dict]) -> str:
    vids = sum(1 for i in items if i["is_video"])
    arts = len(items) - vids
    if len(items) == 1:
        t = items[0]["title"]
        return (t[:77] + "…") if len(t) > 78 else t
    bits = []
    if arts:
        bits.append(f"{arts} new {'read' if arts == 1 else 'reads'}")
    if vids:
        bits.append(f"{vids} new {'video' if vids == 1 else 'videos'}")
    return "This week on Boss KG: " + " + ".join(bits) + " \U0001F3AE"


def build_html(items: list[dict]) -> str:
    rows = []
    for i in items:
        label = ("▶ VIDEO" if i["is_video"] else "NEWS")
        url = i["link"] if i["link"].startswith("http") else f"{SITE}{i['link']}"
        desc = _esc(i["description"])[:180]
        rows.append(f"""
        <tr><td style="padding:0 34px 22px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="background-color:#171b24;border:1px solid #242932;border-radius:12px;">
            <tr><td style="padding:16px 18px;">
              <div style="font-size:10px;font-weight:800;letter-spacing:.14em;color:#FF3D46;margin-bottom:7px;">{label}</div>
              <a href="{url}" target="_blank" style="font-size:17px;font-weight:800;line-height:1.25;color:#ffffff;text-decoration:none;">{_esc(i['title'])}</a>
              <p style="margin:8px 0 0;font-size:13px;line-height:1.55;color:#9AA0AC;">{desc}</p>
            </td></tr>
          </table>
        </td></tr>""")

    return f"""<div style="display:none;max-height:0;overflow:hidden;opacity:0;">Here's everything new from Boss KG this week. \U0001F3AE</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0b0e14;margin:0;padding:0;">
  <tr><td align="center" style="padding:26px 14px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;background-color:#12151d;border:1px solid #242932;border-radius:16px;overflow:hidden;font-family:'Helvetica Neue',Arial,sans-serif;">
      <tr><td style="height:4px;background-color:#FF3D46;line-height:4px;font-size:0;">&nbsp;</td></tr>
      <tr><td align="center" style="padding:26px 30px 4px;">
        <div style="font-size:24px;font-weight:800;letter-spacing:.02em;color:#ffffff;">Boss<span style="color:#FF3D46;"> KG</span></div>
        <div style="font-size:11px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#9AA0AC;margin-top:6px;">◆ The KG Drop · This week</div>
      </td></tr>
      <tr><td align="center" style="padding:14px 34px 22px;">
        <h1 style="margin:0;font-size:24px;line-height:1.2;font-weight:800;color:#ffffff;">Here's what's new this week. \U0001F3AE</h1>
      </td></tr>
      {''.join(rows)}
      <tr><td align="center" style="padding:16px 34px 4px;">
        <p style="margin:0;font-size:14px;line-height:1.6;color:#c7cede;">Catch everything anytime at <a href="{SITE}/" target="_blank" style="color:#FF3D46;font-weight:700;text-decoration:none;">bosskg.com</a>.</p>
      </td></tr>
      <tr><td style="padding:20px 34px 0;"><div style="border-top:1px solid #242932;"></div></td></tr>
      <tr><td align="center" style="padding:16px 34px 28px;">
        <p style="margin:0 0 6px;font-size:13px;color:#8b95a9;">See you next week,<br><strong style="color:#c7cede;">— KG</strong> <span style="font-size:12px;color:#8b95a9;">(a fellow gamer &amp; Marvel fan)</span></p>
        <p style="margin:12px 0 0;font-size:11px;line-height:1.6;color:#6C727E;">You're getting this because you subscribed at <a href="{SITE}/" style="color:#8b95a9;">bosskg.com</a>.<br>Not for you? <a href="{{$unsubscribe}}" style="color:#8b95a9;text-decoration:underline;">Unsubscribe here</a>.</p>
      </td></tr>
    </table>
  </td></tr>
</table>"""


# ---- MailerLite API ---------------------------------------------------------
def _headers(key: str) -> dict:
    return {"Content-Type": "application/json", "Accept": "application/json",
            "Authorization": f"Bearer {key}"}


def already_sent(key: str, name: str) -> bool:
    """True if a campaign with this exact name already exists (any status), so a
    re-run this same ISO week is a no-op."""
    import requests

    try:
        r = requests.get(f"{API}/campaigns", headers=_headers(key),
                          params={"limit": 50}, timeout=30)
        if r.status_code >= 400:
            print(f"[digest] campaigns list failed [{r.status_code}]: {r.text[:200]}", flush=True)
            return False
        for c in (r.json().get("data") or []):
            if (c.get("name") or "").strip() == name:
                return True
    except Exception as e:
        print(f"[digest] campaigns list error ({e!r})", flush=True)
    return False


def send_campaign(key: str, group: str, name: str, subject: str, html: str) -> bool:
    import requests

    create = {
        "name": name,
        "type": "regular",
        "emails": [{"subject": subject, "from_name": FROM_NAME, "from": FROM_EMAIL, "content": html}],
        "groups": [group],
    }
    r = requests.post(f"{API}/campaigns", headers=_headers(key), json=create, timeout=45)
    if r.status_code not in (200, 201):
        print(f"[digest] create failed [{r.status_code}]: {r.text[:400]}", flush=True)
        return False
    cid = (r.json().get("data") or {}).get("id")
    if not cid:
        print(f"[digest] no campaign id in response: {r.text[:300]}", flush=True)
        return False
    s = requests.post(f"{API}/campaigns/{cid}/schedule", headers=_headers(key),
                      json={"delivery": "instant"}, timeout=45)
    if s.status_code not in (200, 201):
        print(f"[digest] schedule failed [{s.status_code}]: {s.text[:400]}", flush=True)
        return False
    print(f"[digest] campaign {cid} sent ✓", flush=True)
    return True


# ---- main -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Send the weekly Boss KG newsletter digest.")
    ap.add_argument("--days", type=int, default=7, help="look-back window in days (default 7)")
    ap.add_argument("--dry-run", action="store_true", help="build + preview only; no API calls, no send")
    ap.add_argument("--force", action="store_true", help="ignore the 'already sent this week' guard")
    ap.add_argument("--test", action="store_true",
                    help="send a one-off TEST campaign (unique name + [TEST] subject) — a real "
                         "end-to-end send that does NOT consume the weekly guard")
    args = ap.parse_args(argv)

    try:
        items = recent(fetch_items(), args.days)
    except Exception as e:
        print(f"[digest] feed fetch/parse failed: {e!r}", flush=True)
        return 1

    if not items:
        print(f"[digest] no new items in the last {args.days} days — nothing to send.", flush=True)
        return 0

    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    name = f"KG Drop — Weekly Digest {iso.year}-W{iso.week:02d}"
    subject = subject_for(items)
    if args.test:
        # Unique name so it never collides with the real weekly guard; flagged subject.
        name += f" · test {now.strftime('%m%d-%H%M')}"
        subject = "[TEST] " + subject
    html = build_html(items)
    vids = sum(1 for i in items if i["is_video"])
    print(f"[digest] {len(items)} item(s) this week ({len(items) - vids} article(s), {vids} video(s)) "
          f"| subject: {subject!r}", flush=True)

    if args.dry_run:
        from pathlib import Path
        out = Path("output") / "rss_digest_preview.html"
        try:
            out.parent.mkdir(exist_ok=True)
            out.write_text(html, encoding="utf-8")
            print(f"[digest] DRY RUN — preview written to {out}", flush=True)
        except Exception:
            print("[digest] DRY RUN — (preview not written)", flush=True)
        for i in items:
            print(f"   - [{'VIDEO' if i['is_video'] else 'NEWS '}] {i['title']}", flush=True)
        return 0

    key = CONFIG.mailerlite_api_key
    if not key:
        print("[digest] MAILERLITE_API_KEY not set — cannot send. Add it to the repo's "
              "Actions secrets (Settings -> Secrets and variables -> Actions).", flush=True)
        return 1

    if not (args.force or args.test) and already_sent(key, name):
        print(f"[digest] '{name}' already exists — skipping (no double-send).", flush=True)
        return 0

    ok = send_campaign(key, CONFIG.mailerlite_group_id, name, subject, html)
    if ok:
        telegram(f"\U0001F4E7 KG weekly digest sent — {len(items)} item(s): {subject}")
        return 0
    telegram("⚠️ KG weekly digest FAILED to send — check the newsletter-digest workflow log.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
