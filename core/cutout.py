"""Local subject cutout (rembg / U2-Net) — cuts the hero out of a game still into a
transparent PNG for the thumbnail foreground, so EVERY game gets a prominent character
even without a hand-curated render.

Fail-open by design: if rembg isn't installed (it's a heavy, local-only dep — see
requirements-cutout.txt), everything returns None and the thumbnail pipeline falls back
to curated PNGs or the subject-in-the-background look. Nothing is ever blocked.

Install locally (the machine that runs `run.py --youtube`):
    pip install -r requirements-cutout.txt
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

_SESSIONS: dict = {}


def available() -> bool:
    try:
        import rembg  # noqa: F401
        return True
    except Exception:
        return False


def _session(model: str):
    if model not in _SESSIONS:
        from rembg import new_session
        _SESSIONS[model] = new_session(model)
    return _SESSIONS[model]


def _score_alpha(res) -> tuple:
    """Rate a cutout by its alpha mask: prefer ONE tall, solid, roughly-centred subject
    that fills a sensible slice of the frame (a good bust/upper-body cutout), and reject
    an empty mask or one that kept nearly the whole image (bad segmentation)."""
    import numpy as np
    a = np.asarray(res.convert("RGBA"))[:, :, 3]
    h, w = a.shape
    m = a > 24
    frac = float(m.mean())
    if frac < 0.03 or frac > 0.9:
        return -1.0, {}
    ys, xs = np.where(m)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    bh, bw = (y1 - y0 + 1) / h, (x1 - x0 + 1) / w
    solidity = float(m.sum()) / max(1, (y1 - y0 + 1) * (x1 - x0 + 1))
    cx = (x0 + x1) / 2 / w
    aspect = bh / max(1e-3, bw)
    score = (min(bh, 1.0) * 1.0            # taller = better (head-to-torso reads big)
             + min(frac * 3, 1.0) * 0.6    # reasonable coverage, not a speck
             + min(aspect, 2.0) / 2 * 0.8  # portrait orientation (a person, not scenery)
             + solidity * 0.6              # one clean solid subject, not scattered bits
             - abs(cx - 0.5) * 0.4)        # roughly centred horizontally
    return round(score, 3), {"bh": round(bh, 2), "bw": round(bw, 2),
                             "frac": round(frac, 2), "solidity": round(solidity, 2)}


def cutout(image_path, out_path, *, model: str = "isnet-general-use") -> Optional[Path]:
    """Cut the subject out of one still. Returns the transparent PNG path, or None if
    rembg is missing / the mask looks like garbage."""
    try:
        from PIL import Image
        from rembg import remove
        res = remove(Image.open(image_path).convert("RGB"), session=_session(model))
        sc, _ = _score_alpha(res)
        if sc < 0:
            return None
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        res.convert("RGBA").save(out_path)
        return out_path
    except Exception as e:
        print(f"[cutout] failed ({e!r})", flush=True)
        return None


def _best_with_model(image_paths, out_dir, model: str, limit: int):
    from PIL import Image
    from rembg import remove
    best, best_sc, best_meta = None, -1.0, {}
    for i, p in enumerate(list(image_paths)[: max(1, int(limit))]):
        try:
            res = remove(Image.open(p).convert("RGB"), session=_session(model))
        except Exception as e:
            print(f"[cutout] {Path(p).name}: {e!r}", flush=True)
            continue
        sc, meta = _score_alpha(res)
        if sc > best_sc:
            dest = Path(out_dir) / f"cut_{i}.png"
            res.convert("RGBA").save(dest)
            best, best_sc, best_meta = dest, sc, meta
    return best, best_sc, best_meta


def best_cutout(image_paths: Sequence, out_dir, *, model: str = "u2net_human_seg",
                fallback_model: Optional[str] = "isnet-general-use",
                floor: float = 1.2, limit: int = 6) -> Optional[Path]:
    """Cut the subject from several candidate stills and keep the cleanest one (best
    alpha-mask score). Tries `model` first (default u2net_human_seg — isolates the
    PERSON and ignores HUD/scenery, ideal for game heroes); if the best result is
    still weak (< floor, e.g. a non-human subject the human model can't find) it
    retries with `fallback_model` (general segmentation). Free + local, no vision call.
    Returns the winning transparent PNG, or None if rembg is missing / nothing clean."""
    if not available():
        return None
    try:
        import rembg  # noqa: F401
    except Exception:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    best, best_sc, best_meta = _best_with_model(image_paths, out_dir, model, limit)
    if (best is None or best_sc < floor) and fallback_model and fallback_model != model:
        print(f"[cutout] {model} weak (score {best_sc}); retrying with {fallback_model}", flush=True)
        fb, fb_sc, fb_meta = _best_with_model(image_paths, out_dir, fallback_model, limit)
        if fb is not None and fb_sc > best_sc:
            best, best_sc, best_meta = fb, fb_sc, fb_meta
    if best is not None:
        print(f"[cutout] best subject: {best.name} score={best_sc} {best_meta}", flush=True)
    return best
