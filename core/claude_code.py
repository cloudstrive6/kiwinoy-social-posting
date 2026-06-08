"""Claude Code client — the brain for the Threads track.

Calls the `claude` CLI headlessly. PRIMARY auth is CLAUDE_CODE_OAUTH_TOKEN (a
Claude subscription token from `claude setup-token`), so the high-frequency
Threads posts run on your subscription instead of per-token API billing.

FALLBACK: if the OAuth token is missing/expired and an ANTHROPIC_API_KEY is set,
it retries with the API key. (The CLI would otherwise *prefer* the API key, so we
deliberately run the token alone first, then fall back to the key only on
failure.) On a dev machine with an existing `claude` login and no env creds, it
just uses that login.

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


def _base_env() -> dict:
    env = dict(os.environ)
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    return env


def _oauth_token() -> str:
    return CONFIG.claude_code_oauth_token or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")


def _anthropic_key() -> str:
    return CONFIG.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")


def available_token() -> bool:
    return bool(_oauth_token())


def _oauth_env() -> dict:
    """Env that forces the subscription OAuth token (strip higher-precedence keys)."""
    env = _base_env()
    env["CLAUDE_CODE_OAUTH_TOKEN"] = _oauth_token()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _apikey_env() -> dict:
    """Env that forces the Anthropic API key (fallback)."""
    env = _base_env()
    env["ANTHROPIC_API_KEY"] = _anthropic_key()
    env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _invoke(cmd: list[str], prompt: str, env: dict, timeout: int) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                cmd, cwd=tmp, env=env, input=prompt,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
        except FileNotFoundError as e:
            raise ClaudeCodeError(
                "`claude` CLI not found. Install it with "
                "`npm install -g @anthropic-ai/claude-code`."
            ) from e

    if proc.returncode != 0:
        raise ClaudeCodeError(
            f"claude CLI failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout)[-1500:]}"
        )

    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except Exception:
        return out
    if isinstance(data, list):
        data = data[-1] if data else {}
    if isinstance(data, dict) and data.get("is_error"):
        raise ClaudeCodeError(f"claude returned an error: {data.get('result') or data}")
    return str(data.get("result", "") if isinstance(data, dict) else out).strip()


def run(
    prompt: str,
    web: bool = False,
    model: Optional[str] = None,
    timeout: int = 300,
) -> str:
    """Run a one-shot headless Claude prompt and return the text result.

    Tries the subscription OAuth token first, then the Anthropic API key as a
    fallback. web=True allowlists WebSearch/WebFetch so Claude can research.
    """
    model = (
        model
        or CONFIG.models.get("claude_model")
        or CONFIG.threads_posts.get("model", "sonnet")
    )
    cmd = [_exe(), "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", str(model)]
    if web:
        cmd += ["--allowedTools", "WebSearch,WebFetch"]

    # Build the auth attempts in priority order.
    attempts: list[tuple[str, dict]] = []
    if _oauth_token():
        attempts.append(("subscription token", _oauth_env()))
    if _anthropic_key():
        attempts.append(("Anthropic API key (fallback)", _apikey_env()))
    if not attempts:
        # Dev convenience: rely on an existing local `claude` login.
        attempts.append(("local claude login", _base_env()))

    last_err: Optional[Exception] = None
    for i, (label, env) in enumerate(attempts):
        try:
            return _invoke(cmd, prompt, env, timeout)
        except ClaudeCodeError as e:
            last_err = e
            if i + 1 < len(attempts):
                print(
                    f"[claude_code] {label} failed, trying {attempts[i + 1][0]}...",
                    flush=True,
                )
            continue
    raise last_err  # type: ignore[misc]
