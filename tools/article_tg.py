"""Telegram approval for BOSS KG draft articles: one card per draft with Approve / Reject
buttons, and replies to a card always resolve to THAT card's article.

Bryce, 2026-11-21: "improve how I can approve the blog drafts on Telegram, because it seems even
if I just reply "approved" to the bot's message, it still doesn't know. Perhaps put the box options
whether to approve or reject so it's easier? Also when I reply to that message, it should know that
that topic/message is the one I'm referring to."

How a draft is tied to its Telegram message (no extra state file):
  - each card is sent with buttons whose callback_data is "art:a:<id>" / "art:r:<id>", where <id> is
    a short hash of the article slug (Telegram allows 64 bytes; slugs can be longer);
  - the card's message_id is written into the article's frontmatter as `telegramMessageId`, which
    the drafting workflows commit with the draft (Astro's schema ignores the extra key).
A reply to a card is matched by (1) that message_id, (2) the card's button ids, (3) the "• <title>"
line of the card or of an older notice. Rejected drafts get `rejected: true` (the file stays in git,
draft stays true, so the site never shows it and it leaves the pending list).

Used by tools/site_article.py (sends cards), tools/telegram_poller.py (reads taps and replies) and
tools/publish_article.py (publishes or rejects, then edits the card to show the result).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ART_DIR = ROOT / "site" / "src" / "content" / "articles"
BASE_URL = "https://bosskg.com"
CB_PREFIX = "art"
CB_RE = re.compile(r"^art:([ar]):([0-9a-f]{6,16})$")

# Reply words (whole first word, case-insensitive). Only used for REPLIES to a draft card or
# notice, so short words like "yes" or "no" can't fire anything on their own.
APPROVE_WORDS = {"approve", "approved", "approves", "approving", "yes", "yep", "yeah", "yup", "y",
                 "ok", "okay", "sure", "go", "publish", "post", "lgtm", "accept", "accepted"}
REJECT_WORDS = {"reject", "rejected", "rejects", "no", "nope", "nah", "n", "skip", "drop", "delete",
                "discard", "decline", "declined", "cancel", "remove", "deny", "denied"}


# ---------------------------------------------------------------- articles on disk

def parse(path: Path) -> tuple[dict, str]:
    """(frontmatter dict, body) of an article markdown file."""
    import yaml
    text = path.read_text(encoding="utf-8")
    m = re.match(r"(?s)^---\n(.*?)\n---\n?(.*)$", text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), m.group(2).strip()


def status(fm: dict) -> str:
    """'rejected', 'pending' (a draft waiting for a decision) or 'live'."""
    if fm.get("rejected") is True:
        return "rejected"
    return "pending" if fm.get("draft") is True else "live"


def all_articles() -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(ART_DIR.glob("*.md")):
        fm, _ = parse(p)
        out.append((p, fm))
    return out


def short_id(slug: str) -> str:
    return hashlib.sha1(slug.encode("utf-8")).hexdigest()[:10]


def squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_by_id(sid: str, arts=None) -> Path | None:
    for p, _ in (arts if arts is not None else all_articles()):
        if short_id(p.stem) == sid:
            return p
    return None


def find_by_message(message_id: int, arts=None) -> Path | None:
    for p, fm in (arts if arts is not None else all_articles()):
        try:
            if int(fm.get("telegramMessageId") or 0) == int(message_id):
                return p
        except (TypeError, ValueError):
            continue
    return None


def find_by_title(title: str, arts=None) -> Path | None:
    t = squash(title)
    if not t:
        return None
    hits = [p for p, fm in (arts if arts is not None else all_articles())
            if t in (squash(str(fm.get("title", ""))), squash(p.stem))]
    return hits[0] if len(hits) == 1 else None


def set_frontmatter(path: Path, key: str, value) -> bool:
    """Set one scalar frontmatter key (replace its line, or add it before the closing ---)."""
    import json
    text = path.read_text(encoding="utf-8")
    m = re.match(r"(?s)^(---\n)(.*?)(\n---\n?)(.*)$", text)
    if not m:
        return False
    val = "true" if value is True else "false" if value is False else (
        str(value) if isinstance(value, int) else json.dumps(value, ensure_ascii=False))
    lines = m.group(2).split("\n")
    pat = re.compile(rf"^{re.escape(key)}:\s")
    for i, ln in enumerate(lines):
        if pat.match(ln + " "):
            lines[i] = f"{key}: {val}"
            break
    else:
        lines.append(f"{key}: {val}")
    path.write_text(m.group(1) + "\n".join(lines) + m.group(3) + m.group(4), encoding="utf-8")
    return True


# ---------------------------------------------------------------- cards and buttons

def buttons(slug: str) -> dict:
    sid = short_id(slug)
    return {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"{CB_PREFIX}:a:{sid}"},
                                 {"text": "❌ Reject", "callback_data": f"{CB_PREFIX}:r:{sid}"}]]}


def card_text(fm: dict, header: str = "📝 New BOSS KG draft article") -> str:
    title = str(fm.get("title", "")).strip()
    excerpt = str(fm.get("excerpt", "")).strip()
    src = str(fm.get("sourceName", "")).strip()
    parts = [f"{header}\n• {title}"]
    if excerpt:
        parts.append(excerpt)
    if src:
        parts.append(f"Source: {src}")
    parts.append("Tap ✅ Approve to publish it on bosskg.com and post it to Facebook, Threads and "
                 "IG Story, or ❌ Reject to drop it. Replying \"approved\" or \"reject\" to this "
                 "message works too.")
    return "\n\n".join(parts)


def send_card(path: Path, header: str = "📝 New BOSS KG draft article") -> int | None:
    """Send the draft's card with Approve / Reject buttons and remember its message id in the
    article's frontmatter. Returns the message id (None if Telegram is off or the send failed)."""
    from core import notify
    fm, _ = parse(path)
    mid = notify.send(card_text(fm, header), reply_markup=buttons(path.stem))
    if mid:
        set_frontmatter(path, "telegramMessageId", int(mid))
    return mid


def mark_card(path: Path, line: str) -> bool:
    """Show a decision on the article's own card (its text plus `line`) and remove the buttons."""
    from core import notify
    fm, _ = parse(path)
    mid = fm.get("telegramMessageId")
    if not mid:
        return False
    return notify.edit(int(mid), card_text(fm) + "\n\n" + line)


def picker(items: list[tuple[Path, dict]], head: str, limit: int = 8) -> int | None:
    """One message listing drafts, each with its own ✅ / ❌ buttons (newest first, max `limit`).
    Used when a message can't be matched to one article."""
    from core import notify
    items = items[:limit]
    if not items:
        return None
    lines, rows = [], []
    for i, (p, fm) in enumerate(items, 1):
        lines.append(f"{i}. {fm.get('title', p.stem)}")
        sid = short_id(p.stem)
        rows.append([{"text": f"✅ Approve {i}", "callback_data": f"{CB_PREFIX}:a:{sid}"},
                     {"text": f"❌ Reject {i}", "callback_data": f"{CB_PREFIX}:r:{sid}"}])
    return notify.send(head + "\n\n" + "\n".join(lines), reply_markup={"inline_keyboard": rows})


def drop_buttons_for(message: dict, sid: str, line: str) -> bool | None:
    """After a decision: on a single-draft card, add `line` and remove the buttons (returns True);
    on a picker, remove only that draft's row so the others stay tappable (returns False).
    None when there is no message to edit."""
    from core import notify
    mid = (message or {}).get("message_id")
    if not mid:
        return None
    rows = ((message.get("reply_markup") or {}).get("inline_keyboard") or [])
    keep = [r for r in rows if not any(str(b.get("callback_data", "")).endswith(":" + sid) for b in r)]
    other_ids = {CB_RE.match(str(b.get("callback_data", ""))).group(2)
                 for r in keep for b in r if CB_RE.match(str(b.get("callback_data", "")))}
    if other_ids:
        notify.edit_markup(int(mid), {"inline_keyboard": keep})
        return False
    notify.edit(int(mid), (message.get("text") or "").rstrip() + "\n\n" + line)
    return True


# ---------------------------------------------------------------- reading Bryce's replies

def classify(text: str) -> str:
    """'approve', 'reject' or '' for a reply's text."""
    t = (text or "").strip().lower()
    if not t:
        return ""
    if t[0] in "✅👍✔":
        return "approve"
    if t[0] in "❌👎🚫✖":
        return "reject"
    m = re.match(r"[a-z']+", t)
    w = m.group(0) if m else ""
    if w in APPROVE_WORDS:
        return "approve"
    if w in REJECT_WORDS:
        return "reject"
    return ""


def card_ids(message: dict) -> list[str]:
    """The draft ids on a message's ✅ / ❌ buttons, in order, without repeats."""
    ids = []
    for row in (((message or {}).get("reply_markup") or {}).get("inline_keyboard") or []):
        for b in row:
            m = CB_RE.match(str(b.get("callback_data", "")))
            if m and m.group(2) not in ids:
                ids.append(m.group(2))
    return ids


def resolve_reply(reply_to: dict, arts=None) -> tuple[Path | None, list[Path]]:
    """Which article a reply points at: (the one article, []) or (None, candidates). Candidates
    are the drafts named on a notice that lists several; ([], []) means not a draft message."""
    arts = arts if arts is not None else all_articles()
    if not reply_to:
        return None, []
    mid = reply_to.get("message_id")
    if mid:
        p = find_by_message(mid, arts)
        if p:
            return p, []
    ids = card_ids(reply_to)
    found = [p for p in (find_by_id(s, arts) for s in ids) if p]
    if len(found) == 1:
        return found[0], []
    text = reply_to.get("text") or ""
    titles = [ln.strip()[1:].strip() for ln in text.splitlines() if ln.strip().startswith("•")]
    # numbered picker lines ("1. Title") too
    titles += [re.sub(r"^\d+\.\s+", "", ln.strip()) for ln in text.splitlines()
               if re.match(r"^\s*\d+\.\s+\S", ln)]
    # older list formats: "• Title  —  reply: approve x" and "1. Title  (2026-11-20)"
    titles = [re.sub(r"\s+\(\d{4}-\d{2}-\d{2}\)\s*$", "", re.split(r"\s+—\s+reply:", t)[0]).strip()
              for t in titles]
    by_title = []
    for t in titles:
        p = find_by_title(t, arts)
        if p and p not in by_title:
            by_title.append(p)
    if len(by_title) == 1 and len(titles) == 1:
        return by_title[0], []
    cands = found or by_title
    return None, cands


def looks_like_draft_notice(reply_to: dict) -> bool:
    """True when the replied-to bot message is about draft articles (so an unmatched reply gets
    the picker instead of being ignored)."""
    t = (reply_to or {}).get("text") or ""
    if card_ids(reply_to):
        return True
    # only the article notices, never "rendering an IG draft" or "no fresh draft today" (review
    # 2026-11-21: an "ok" to a render message must not bring up the article picker)
    return bool(re.search(r"(?i)draft article|blog draft|drafted a boss kg blog|which article|"
                          r"which draft|pending draft|matches \d+ drafts", t))


def live_url(path: Path) -> str:
    return f"{BASE_URL}/news/{path.stem}"
