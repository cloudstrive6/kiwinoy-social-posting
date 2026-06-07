"""Claude Code (OAuth-token) client — the brain for the Threads track.

Calls the `claude` CLI headlessly using CLAUDE_CODE_OAUTH_TOKEN (a Claude
subscription token from `claude setup-token`), so the high-frequency Threads
posts run on your subscription instead of per-token API billing. Supports web
search so the research agent can dig up current sports news.

Install the CLI with:  npm install -g @anthropic-ai/claude-code
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from core.config import CONFIG


class ClaudeCodeError(RuntimeError):
    pass


def _exe() -> str:
    for name in ("claude", "claude.cmd", "claude.exe"):
        found = shutil.which(name)
        if found:
            return found
    return "claude"


def _env() -> dict:
    env = dict(os.environ)
    token = CONFIG.claude_code_oauth_token
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    # Keep CI quiet/fast.
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    return env


def available_token() -> bool:
    return bool(CONFIG.claude_code_oauth_token or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


def run(
    prompt: str,
    web: bool = False,
    model: Optional[str] = None,
    timeout: int = 300,
) -> str:
    """Run a one-shot headless Claude prompt and return the text result.

    web=True allowlists the WebSearch/WebFetch tools so Claude can research
    current info. The prompt is piped via stdin (robust for long prompts).
    """
    # No hard token check: in CI the CLI uses CLAUDE_CODE_OAUTH_TOKEN; on a dev
    # machine it can use an existing `claude` login. If neither exists the CLI
    # itself errors and we surface a token hint below.
    model = model or CONFIG.threads_posts.get("model", "sonnet")
    cmd = [_exe(), "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", str(model)]
    if web:
        cmd += ["--allowedTools", "WebSearch,WebFetch"]

    # Run from an empty temp dir so no project/global .claude config is loaded.
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                env=_env(),
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise ClaudeCodeError(
                "`claude` CLI not found. Install it with "
                "`npm install -g @anthropic-ai/claude-code`."
            ) from e

    if proc.returncode != 0:
        hint = ""
        if not available_token():
            hint = (
                " (CLAUDE_CODE_OAUTH_TOKEN is not set — generate one with "
                "`claude setup-token` and add it to .env / GitHub secrets.)"
            )
        raise ClaudeCodeError(
            f"claude CLI failed (exit {proc.returncode}){hint}: "
            f"{(proc.stderr or proc.stdout)[-1500:]}"
        )

    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except Exception:
        return out  # plain-text fallback
    if isinstance(data, list):
        data = data[-1] if data else {}
    if isinstance(data, dict) and data.get("is_error"):
        raise ClaudeCodeError(f"claude returned an error: {data.get('result') or data}")
    return str(data.get("result", "") if isinstance(data, dict) else out).strip()
