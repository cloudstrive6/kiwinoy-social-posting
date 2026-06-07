"""last30days research engine (vendored, direct-CLI mode).

Calls the vendored `last30days.py --emit json` to pull engagement-ranked,
last-30-days community signal (Reddit, Hacker News, Polymarket, GitHub, YouTube)
for a topic, scoped to the subreddits we choose. Free sources only, deterministic
plan, preflight skipped. Returns a compact list of trending stories that our
LLM then synthesizes into a brief.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Optional

from core.config import CONFIG, ROOT, OUTPUT_DIR

CLI = ROOT / "vendor" / "last30days" / "last30days.py"


class Last30Error(RuntimeError):
    pass


def available() -> bool:
    return CLI.exists()


def _run_cli(
    topic: str,
    sources: list[str],
    subreddits: Optional[list[str]] = None,
    quick: bool = True,
    timeout: int = 150,
) -> dict[str, Any]:
    if not CLI.exists():
        raise Last30Error(f"vendored last30days CLI not found at {CLI}")
    cmd = [sys.executable, str(CLI), topic, "--emit", "json",
           "--search", ",".join(sources)]
    if subreddits:
        cmd += ["--subreddits", ",".join(subreddits)]
    if quick:
        cmd += ["--quick"]

    env = dict(os.environ)
    env["LAST30DAYS_SKIP_PREFLIGHT"] = "1"
    mem = OUTPUT_DIR / "last30days"
    mem.mkdir(parents=True, exist_ok=True)
    env.setdefault("LAST30DAYS_MEMORY_DIR", str(mem))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise Last30Error(f"last30days timed out after {timeout}s") from e

    if proc.returncode != 0:
        raise Last30Error(
            f"last30days CLI failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout)[-800:]}"
        )
    out = (proc.stdout or "").strip()
    start = out.find("{")
    if start == -1:
        raise Last30Error("no JSON found in last30days output")
    return json.loads(out[start:])


def gather(
    topic: str,
    subreddits: Optional[list[str]] = None,
    sources: Optional[list[str]] = None,
    limit: int = 12,
    quick: Optional[bool] = None,
    timeout: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return up to `limit` trending stories for `topic` (engagement-ranked)."""
    cfg = CONFIG.research
    sources = sources or cfg.get("sources", ["reddit", "hackernews", "polymarket"])
    quick = cfg.get("quick", True) if quick is None else quick
    timeout = int(cfg.get("timeout_seconds", 150)) if timeout is None else timeout

    data = _run_cli(topic, sources, subreddits, quick=quick, timeout=timeout)

    # Index raw items by url so we can attach a snippet to each ranked cluster.
    idx: dict[str, tuple[str, dict]] = {}
    for src, items in (data.get("items_by_source") or {}).items():
        for it in items:
            url = it.get("url") or it.get("permalink") or ""
            if url:
                idx[url] = (src, it)

    stories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in data.get("clusters", []):
        title = (c.get("title") or "").strip()
        if not title:
            continue
        key = title.lower()[:70]
        if key in seen:
            continue
        seen.add(key)
        rep = (c.get("representative_ids") or c.get("candidate_ids") or [""])[0]
        src, it = idx.get(rep, (",".join(c.get("sources", [])), {}))
        snippet = (it.get("body") or it.get("text") or "")[:280]
        stories.append({
            "title": title,
            "score": round(float(c.get("score", 0)), 1),
            "source": src,
            "url": rep or it.get("url", ""),
            "snippet": snippet,
        })
        if len(stories) >= limit:
            break

    # If clustering produced nothing, fall back to raw ranked items.
    if not stories:
        for src, items in (data.get("items_by_source") or {}).items():
            for it in items:
                t = (it.get("title") or it.get("body", "")[:90]).strip()
                if not t:
                    continue
                stories.append({
                    "title": t,
                    "score": round(float(it.get("score", 0) or 0), 1),
                    "source": src,
                    "url": it.get("url", ""),
                    "snippet": (it.get("body") or "")[:280],
                })
                if len(stories) >= limit:
                    break
            if len(stories) >= limit:
                break
    return stories


def format_stories(stories: list[dict[str, Any]]) -> str:
    """Render stories as a compact text block for an LLM synthesis prompt."""
    lines = []
    for s in stories:
        head = f"- [{s['source']} | engagement {s['score']}] {s['title']}"
        lines.append(head)
        if s.get("snippet"):
            lines.append(f"    {s['snippet']}")
    return "\n".join(lines)
