# Game art for the 3-panel ("triptych") gameplay reels

Drop **key-art / cover images** here, one folder per game, named by the game's
**footage-folder key** (the same key used under `reels/assets/footage/`):

```
reels/assets/game-art/
  spider-man1/                 <- Marvel's Spider-Man (Remastered)
  spider-man-miles-morales/    <- Marvel's Spider-Man: Miles Morales
  spider-man2/                 <- Marvel's Spider-Man 2 (when added)
```

These appear in the **bottom panel** of the new 3-panel reel layout (slots 2, 4, 6).

**Image guidance:**
- **Landscape 16:9** (e.g. 1920×1080) — it's scaled to the panel width; portrait art
  will leave black bars on the sides.
- `.png`, `.jpg`, `.jpeg`, or `.webp`.
- Put **several per game** if you like — one is picked at random each reel for variety.
- File names don't matter; any file in the game's folder is eligible.

If a game's folder is empty, that slot automatically falls back to the **classic**
layout — so it's always safe; nothing breaks if art is missing.

These are committed repo files (like the game logos), so CI renders from them — no
cloud upload needed. Keep them reasonably sized (a few hundred KB each is plenty).
