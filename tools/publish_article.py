"""Approve a drafted BOSS KG article: publish it live AND cross-post to Facebook + Threads.

This is the second half of the news pipeline. tools/site_article.py drafts articles
(draft: true) and pings you on Telegram. When you reply "approved" (handled by
tools/telegram_poller.py -> ig-poller.yml), THIS tool runs and, for the chosen draft:

  1. flips `draft: true` -> `draft: false` in the markdown,
  2. commits + pushes and triggers a site deploy, then waits for the page to go live,
  3. writes a Facebook caption and a Threads caption (grounded in the article), each ending
     with a CTA + the live article link,
  4. posts them (Post-for-Me: FB feed + the Threads track),
  5. Telegrams you a confirmation with what went live + the captions used.

  python tools/publish_article.py --match doom      # publish the pending draft matching "doom"
  python tools/publish_article.py --all             # publish every pending draft
  python tools/publish_article.py --match doom --dry # show captions, don't publish/post/push
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import yaml  # noqa: E402

ART_DIR = ROOT / "site" / "src" / "content" / "articles"
BASE_URL = "https://bosskg.com"


def _parse(path: Path) -> tuple[dict, str]:
    """Return (frontmatter dict, body) for an article markdown file."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"(?s)^---\n(.*?)\n---\n?(.*)$", text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), m.group(2).strip()


def _pending() -> list[tuple[Path, dict, str]]:
    """All draft:true articles, newest file first."""
    out = []
    for p in sorted(ART_DIR.glob("*.md"), key=lambda q: q.stat().st_mtime, reverse=True):
        fm, body = _parse(p)
        if fm.get("draft") is True:
            out.append((p, fm, body))
    return out


def _select(pending, match: str, take_all: bool):
    if take_all:
        return pending
    if match:
        m = match.lower().strip()
        hit = [(p, fm, b) for (p, fm, b) in pending
               if m in p.stem.lower() or m in str(fm.get("title", "")).lower()]
        return hit
    return pending[:1] if len(pending) == 1 else []


def _flip_live(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^draft:\s*true\s*$", "draft: false", text, count=1)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def _captions(fm: dict, body: str, url: str) -> dict:
    """Write a Facebook + a Threads caption grounded in the article, each ending with a
    click-through CTA + the live link. One LLM call; falls back to a simple caption."""
    from agents.content import _text, extract_json
    title = str(fm.get("title", "")).strip()
    excerpt = str(fm.get("excerpt", "")).strip()
    category = str(fm.get("category", "")).strip()
    prompt = (
        "You write social captions for BOSS KG (a gaming & Marvel news brand) to drive clicks "
        "to a just-published article. Below is the article.\n\n"
        f"TITLE: {title}\nCATEGORY: {category}\nSUMMARY: {excerpt}\n\n"
        f"=== ARTICLE ===\n{body[:2600]}\n=== END ===\n\n"
        "Write TWO captions that tease the story and make people want to read it. RULES:\n"
        "- Use ONLY facts from the article — do not invent numbers, dates, or quotes.\n"
        "- Tone: hype but honest, never clickbait or fabricated. No spoilers of the payoff.\n"
        "- FACEBOOK: 2-4 short sentences, engaging hook first, may use 1-3 relevant hashtags.\n"
        "- THREADS: punchy, under 380 characters, NO hashtags.\n"
        "- Do NOT put the link inside your text — the CTA + link are appended automatically.\n\n"
        'Return ONLY JSON: {"facebook":"...","threads":"..."}'
    )
    fb = th = ""
    try:
        d = extract_json(_text(prompt, timeout=150))
        if isinstance(d, dict):
            fb = str(d.get("facebook", "")).strip()
            th = str(d.get("threads", "")).strip()
    except Exception as e:
        print(f"   caption LLM failed ({e!r}) — using fallback", flush=True)
    if not fb:
        fb = f"{title}\n\n{excerpt}".strip()
    if not th:
        th = (excerpt or title)[:360]
    # Strip any stray link/hashtags the model added to Threads, then append the CTA + link.
    from agents.post_director import fit_threads
    th = fit_threads(th, limit=380)
    fb_final = f"{fb}\n\n👉 Read the full story: {url}"
    th_final = f"{th}\n\n👉 Full story (link): {url}"
    return {"facebook": fb_final, "threads": th_final}


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
        return r.returncode, (r.stdout + r.stderr)
    except Exception as e:
        return 1, repr(e)


def _git_publish(paths: list[Path]) -> None:
    """Commit the flipped article(s) + their covers, push, and trigger a deploy. Best-effort."""
    rels = [str(p.relative_to(ROOT)).replace("\\", "/") for p in paths]
    _run(["git", "add", *rels, "site/public/covers"])
    code, out = _run(["git", "commit", "-m", "content: publish approved article(s)"])
    if code != 0 and "nothing to commit" not in out:
        print(f"   git commit: {out.strip()[:200]}", flush=True)
    code, out = _run(["git", "push"])
    if code != 0:
        print(f"   git push: {out.strip()[:200]}", flush=True)
    # github.token pushes don't fire the deploy's push trigger, so dispatch it explicitly.
    _run(["gh", "workflow", "run", "deploy-site.yml"])


def _wait_live(url: str, timeout: int = 300) -> bool:
    """Poll the article URL until it returns 200 (so FB/Threads scrape a live page)."""
    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(15)
    return False


def _build_card(title: str, game: str, slug: str):
    """Build the shared BOSS KG news card (headline + brand over the article cover), like the
    auto-posts. Returns (card_path, card_bytes) or (None, None) if no cover is available."""
    cover = ROOT / "site" / "public" / "covers" / f"{slug}.jpg"
    if not cover.exists():
        return None, None
    try:
        import tempfile
        from agents import post_director as pd
        out = Path(tempfile.gettempdir()) / f"bosskg_card_{slug}.jpg"
        if pd.build_card(title, game or "", title, out, bg_image=str(cover)):
            return out, out.read_bytes()
    except Exception as e:
        print(f"   card build failed: {e!r}", flush=True)
    return None, None


def _post(caps: dict, url: str, title: str, slug: str, game: str) -> list[str]:
    """Post the news CARD (graphic + headline) with the caption + link CTA to Facebook + Threads,
    and an Instagram STORY (same card on a 9:16 canvas + link-in-bio CTA) — like the auto-posts.
    Returns a list of human-readable results."""
    from agents import publisher
    card_path, card = _build_card(title, game, slug)
    tag = "" if card else " (text only — no cover)"
    try:
        publisher.run(caps["facebook"], card, platform_keys=["facebook"])
        results = ["✅ Facebook" + tag]
    except Exception as e:
        results = [f"⚠️ Facebook failed: {e}"]
        print(f"   FB post failed: {e!r}", flush=True)
    try:
        publisher.run(caps["threads"], card, platform_keys=["threads"])
        results.append("✅ Threads" + tag)
    except Exception as e:
        results.append(f"⚠️ Threads failed: {e}")
        print(f"   Threads post failed: {e!r}", flush=True)
    # Instagram STORY — the card on a 9:16 canvas with the "Read the full story / Tap the link in
    # bio" CTA (IG blocks API links, so the story drives to the bio link).
    try:
        from agents import post_director as pd
        img = str(card_path) if card_path else str(ROOT / "site" / "public" / "covers" / f"{slug}.jpg")
        if Path(img).exists():
            publisher.run_ig_story_image(title[:120], pd.story_canvas_bytes(img))
            results.append("✅ Instagram Story")
        else:
            results.append("⚠️ IG Story skipped (no cover)")
    except Exception as e:
        results.append(f"⚠️ IG Story failed: {e}")
        print(f"   IG Story failed: {e!r}", flush=True)
    return results


def _notify_pending(pending) -> None:
    from core import notify
    if not pending:
        notify.telegram("🤔 No draft articles are pending — nothing to publish.")
        return
    lst = "\n".join(f"• {fm.get('title','?')}  —  reply: approve {p.stem.split('-')[0]}"
                    for (p, fm, _) in pending[:8])
    notify.telegram("🤔 Which article? Reply e.g. \"approve <keyword>\" (a word from the title/slug), "
                    f"or \"approve all\". Pending:\n{lst}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="", help="keyword to pick the pending draft (slug or title)")
    ap.add_argument("--all", action="store_true", help="publish every pending draft")
    ap.add_argument("--dry", action="store_true", help="show captions; do not publish/post/push")
    a = ap.parse_args()

    pending = _pending()
    targets = _select(pending, a.match, a.all)
    if not targets:
        print(f"[publish] no matching draft (pending={len(pending)}, match={a.match!r}).", flush=True)
        if not a.dry:
            _notify_pending(pending)
        return 0

    for path, fm, body in targets:
        slug = path.stem
        url = f"{BASE_URL}/news/{slug}"
        title = str(fm.get("title", slug))
        print(f"\n[publish] {slug}\n  url: {url}", flush=True)
        caps = _captions(fm, body, url)
        print(f"  FACEBOOK:\n{caps['facebook']}\n\n  THREADS:\n{caps['threads']}", flush=True)
        if a.dry:
            continue

        if not _flip_live(path):
            print("  (already live — re-posting socials only)", flush=True)
        _git_publish([path])
        print("  deploying… waiting for the page to go live", flush=True)
        live = _wait_live(url)
        print(f"  live={live}", flush=True)
        results = _post(caps, url, title, slug, str(fm.get("game", "")))

        from core import notify
        notify.telegram(
            f"🚀 Published: {title}\n{url}\n\n" + "  ".join(results) +
            ("" if live else "\n(note: deploy still finishing — link goes live shortly)") +
            f"\n\n— Facebook —\n{caps['facebook']}\n\n— Threads —\n{caps['threads']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
