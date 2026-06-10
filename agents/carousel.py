"""Agent — Carousel Creation.

Turns a research brief + caption into a 3-5 slide image carousel for
Facebook + Instagram:
  1. The writer plans the slides (one idea per slide: cover hook -> content
     slides (a rank / stat / matchup / prediction each) -> CTA closer).
  2. Each slide is generated with gpt-image-1 in the same visual style as the
     single-image posts (franchise style + likeness + matching typography),
     with explicit set-consistency instructions across slides.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.image import _style_for
from core import franchise
from core import openai_client as ai
from core import writer
from core.config import CONFIG
from core.openai_client import extract_json
from core.style import HUMAN_VOICE, sanitize


def plan_slides(brief: dict[str, Any], caption: str) -> list[dict[str, str]]:
    """Ask the writer for a slide plan: [{headline, support, visual}, ...]."""
    cfg = CONFIG.carousels
    n_min = int(cfg.get("slides_min", 3))
    n_max = int(cfg.get("slides_max", 5))
    facts = "\n".join(f"- {f}" for f in brief.get("key_facts", []))

    prompt = f"""Plan an Instagram/Facebook image CAROUSEL ({n_min}-{n_max} slides) about:

TOPIC: {brief.get('title')}
SUBJECT: {brief.get('subject')}
ANGLE: {brief.get('angle')}
KEY FACTS (use accurately, never invent):
{facts}

CAPTION the carousel will run with (for tone, don't repeat it verbatim):
{caption[:400]}

CAROUSEL CRAFT:
- Slide 1 is the COVER: the single most scroll-stopping hook, big and bold.
- Each middle slide carries EXACTLY ONE idea (one rank, one stat, one matchup,
  one hero/champion, one prediction) so swiping feels rewarding.
- Final slide is the PAYOFF + CTA (the verdict/prediction + "save this" /
  "drop your take" energy).
- On-image text must be SHORT: a punchy headline (2-6 words) and at most one
  short support line (under 8 words). No paragraphs on images.

Return ONLY this JSON (no prose, no code fences):
{{
  "slides": [
    {{
      "headline": "2-6 word on-image headline",
      "support": "optional short support line, or empty string",
      "visual": "one sentence describing this slide's visual moment/subject"
    }}
  ]
}}
Use between {n_min} and {n_max} slides."""

    raw = writer.write(prompt, system=HUMAN_VOICE)
    slides: list[dict[str, str]] = []
    try:
        data = extract_json(raw)
        for s in data.get("slides", []):
            slides.append({
                "headline": sanitize(str(s.get("headline", "")).strip()),
                "support": sanitize(str(s.get("support", "")).strip()),
                "visual": str(s.get("visual", "")).strip(),
            })
    except Exception:
        pass
    slides = [s for s in slides if s["headline"]][:n_max]
    if len(slides) < n_min:
        # Fallback: minimal 3-slide plan straight from the brief.
        slides = [
            {"headline": brief.get("headline_idea") or brief.get("title", ""),
             "support": "", "visual": f"Hero cover for {brief.get('subject')}"},
            {"headline": "The key fact", "support": "",
             "visual": f"The core moment of {brief.get('title')}"},
            {"headline": "Your move", "support": "Drop your take below",
             "visual": f"Closing CTA visual for {brief.get('subject')}"},
        ]
    return slides


def _slide_prompt(
    brief: dict[str, Any],
    slide: dict[str, str],
    idx: int,
    total: int,
) -> str:
    style, likeness = _style_for(brief)
    headline_rules = CONFIG.image["headline"]
    fr = franchise.match(brief) if brief["category"] != "sports" else None
    if fr and fr.get("headline_style"):
        headline_rules = (
            f"{headline_rules}\nFRANCHISE TYPOGRAPHY (match the headline lettering to "
            f"this): {fr['headline_style']}"
        )
    role = "COVER slide" if idx == 0 else (
        "FINAL slide (payoff + call-to-action)" if idx == total - 1
        else f"content slide {idx + 1} of {total}"
    )
    support = f'\nSmaller support line below it: "{slide["support"]}"' if slide.get("support") else ""

    return f"""Create slide {idx + 1} of a {total}-slide social media CAROUSEL (square)
about: {brief.get('title')}.

This is the {role}.
SLIDE VISUAL: {slide.get('visual')}
SUBJECT: {brief.get('subject')}

VISUAL STYLE (follow exactly):
{style}
{likeness}

ON-IMAGE TEXT:
{headline_rules}
Render this exact headline (big, dominant): "{slide['headline']}"{support}
Spell every word exactly as given.

SET CONSISTENCY (critical): all {total} slides belong to ONE carousel — same art
style, same color palette and grade, same typography family and headline
placement zone on every slide, so swiping feels seamless.

COMPOSITION: bold focal subject, strong contrast, clean space for the text,
premium finish. No watermarks, no logos, no UI, no borders."""


def run(
    brief: dict[str, Any],
    caption: str,
    save_dir: Path | None = None,
) -> tuple[list[dict[str, str]], list[bytes]]:
    """Plan + generate the carousel. Returns (slide_plan, [png_bytes...])."""
    slides = plan_slides(brief, caption)
    size = CONFIG.carousels.get("size", "1024x1024")
    images: list[bytes] = []
    for i, slide in enumerate(slides):
        data = ai.image(_slide_prompt(brief, slide, i, len(slides)), size=size)
        images.append(data)
        if save_dir is not None:
            save_dir.mkdir(parents=True, exist_ok=True)
            (save_dir / f"slide{i + 1}.png").write_bytes(data)
    return slides, images
