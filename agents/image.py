"""Agent 4 — Image Generation.

Builds a rich gpt-image-1 prompt from the brief + caption and generates a
scroll-stopping image WITH the headline baked in:
  - sports  -> hyper-realistic pro-camera photography
  - gacha   -> high-quality anime / splash-art aesthetic
Typography style is instructed to match the image style.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core import franchise
from core import openai_client as ai
from core.config import CONFIG


def _style_for(brief: dict[str, Any]) -> tuple[str, str]:
    """Return (visual style, likeness note) for the brief.

    Sports keeps its photoreal style. Otherwise, if the topic matches an AAA
    franchise (Final Fantasy / Resident Evil / Halo) use that franchise's real
    art style + a character-likeness push; else fall back to the anime/gacha style.
    """
    category = brief["category"]
    img = CONFIG.image
    if category != "sports":
        fr = franchise.match(brief)
        if fr:
            return fr["style"], franchise.LIKENESS
    return img["styles"][category], ""


def build_prompt(brief: dict[str, Any], caption: str) -> str:
    img = CONFIG.image
    style, likeness = _style_for(brief)
    headline_rules = img["headline"]
    fr = franchise.match(brief) if brief["category"] != "sports" else None
    if fr and fr.get("headline_style"):
        headline_rules = (
            f"{headline_rules}\nFRANCHISE TYPOGRAPHY (match the headline lettering to "
            f"this): {fr['headline_style']}"
        )
    headline_idea = brief.get("headline_idea") or brief.get("title", "")

    return f"""Create a single scroll-stopping social media image (square) for a
gaming channel post about: {brief.get('title')}.

SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}

VISUAL STYLE (follow exactly):
{style}
{likeness}

ON-IMAGE HEADLINE:
{headline_rules}
Use this as the headline (refine wording if it improves impact, keep it short):
"{headline_idea}"

COMPOSITION:
- Bold focal subject, strong contrast, designed to stop the thumb mid-scroll.
- Leave clean space so the headline is highly legible.
- Professional, premium finish. No watermarks, no logos, no UI, no borders.
- Spell every word correctly.

Context for tone (do not render this text on the image): {caption[:300]}"""


def run(brief: dict[str, Any], caption: str, save_path: Path | None = None) -> bytes:
    """Generate the post image; optionally save to disk. Returns PNG bytes."""
    prompt = build_prompt(brief, caption)
    data = ai.image(prompt)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(data)
    return data


def build_background_prompt(brief: dict[str, Any], shot_index: int, n_shots: int) -> str:
    """Vertical reel background art, NO baked text (Remotion overlays captions)."""
    style, likeness = _style_for(brief)
    reel = CONFIG.reels
    variety = (
        f"This is shot {shot_index + 1} of {n_shots}: vary the angle / framing / "
        f"moment from the other shots so the reel feels dynamic."
    )
    return f"""{reel.get('background_prompt', '')}

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}

VISUAL STYLE (follow exactly):
{style}
{likeness}

{variety}"""


def run_background(
    brief: dict[str, Any],
    shot_index: int,
    n_shots: int,
    save_path: Path | None = None,
) -> bytes:
    """Generate one vertical (9:16) background shot for a reel. Returns PNG bytes."""
    prompt = build_background_prompt(brief, shot_index, n_shots)
    size = CONFIG.reels.get("background_size", "1024x1536")
    data = ai.image(prompt, size=size)
    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(data)
    return data
