# Your gameplay footage goes here

Drop your own gameplay clips into the matching game folder. The reel agent picks
a few short clips at random, trims each to ~4 seconds, splices 3-4 of them into a
12-16 second reel, and overlays the Taglish captions + voiceover + music.

## Where to put clips

Put each clip in the folder for its game (the reel topic decides which folder):

| Folder      | Game / topic |
|-------------|--------------|
| `mlbb/`     | Mobile Legends: Bang Bang (MPL PH) |
| `dota2/`    | Dota 2 |
| `cs2/`      | Counter-Strike 2 |
| `lol/`      | League of Legends / Wild Rift |
| `genshin/`  | Genshin Impact |
| `hsr/`      | Honkai: Star Rail |
| `nte/`      | NTE: Neverness to Everness |
| `ff7/`      | Final Fantasy VII |
| `re/`       | Resident Evil |
| `halo/`     | Halo |
| `general/`  | Any gameplay — used when a topic has no game-specific clips |

**Easiest start:** just dump everything into `general/` and it works. Organize
into game folders later for tighter topic matching.

## Clip tips

- **Format:** H.264 `.mp4` is safest (also ok: `.mov`, `.webm`, `.m4v`, `.mkv`).
- **Length:** make clips at least ~5 seconds (the agent trims to ~4s from the
  start, so put the best action up front).
- **Count:** add at least 3-4 clips per game so each reel can vary.
- **Orientation:** landscape gameplay is fine — it's shown centered over a
  blurred fill so it fits the 9:16 frame. Vertical clips work too.
- **Audio:** game audio is muted automatically so the voiceover stays clean.
- **Size:** keep the library modest. These clips ship in the repo so the cloud
  renderer (GitHub Actions) can use them, so smaller/compressed files are better.

## After adding clips

Commit and push them so the cloud reels can use them:

```
git add reels/assets/footage
git commit -m "Add gameplay footage"
git push
```

If no clips exist for a topic, the reel automatically falls back to AI-generated
background art, so nothing breaks while your library is still filling up.
