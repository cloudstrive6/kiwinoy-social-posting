# Character cutout library (thumbnail foreground)

Prominent character cutouts are the #1 click-through lever on gaming thumbnails
(MKIceAndFire / Shirrako style). Drop **transparent PNG** hero renders here and the
long-form thumbnail composites one big in the foreground, over the gameplay scene,
with the game logo (top-left), 4K/HDR badge (top-right) and the PART/FULL GAME box
(bottom-left) layered on top.

## How to use
Create a subfolder named with the game **key** (same key you pass to `--game`) and
put one or more transparent character PNGs in it:

```
reels/assets/game-character/
  ff7remake/        Cloud.png   Tifa.png   Sephiroth.png
  ff7/              Cloud (PS1).png
  halo/             Master Chief.png
  spider-man1/      Spider-Man.png
```

- **Must be transparent PNGs** (background removed) — a full-body or bust render.
  Official press renders / "character render transparent PNG" work great.
- Multiple per game = variety: each thumbnail variant picks one at random.
- The game's **universe** is also tried (e.g. a `spider-man` render is used for
  `spider-man1` / `spider-man-miles-morales` if no game-specific one exists).
- No PNG for a game? The thumbnail falls back to the subject-in-the-background look.

## Tuning (config.yaml → reels.thumbnail)
`character_scale` (height, 0.92), `character_side` (right/left), `character_max_w`
(width cap), `character_shadow` (contact shadow on/off).
