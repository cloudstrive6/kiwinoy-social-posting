# 4K/60 HDR source intake — paste here

This is the **one place** to drop raw **4K/60 HDR** captures. Everything here feeds
**both** YouTube pillars:

- **Long-form** — `python run.py --youtube --parts reels/assets/4k-hdr/<game>`
- **Shorts** — curate reel clips from these files with `python tools/pool_4k.py`

## How to use it

1. **Paste** your 4K/60 HDR files into the folder named after the game, e.g.
   `reels/assets/4k-hdr/ff7remake/`. (No folder for your game yet? Just make one —
   name it the game key, like `thelastofus2`, `spider-man1`, `halo`.)
2. That's it. A scheduled job (`run_4k_sync.bat`, ~every 30 min) uploads each file to
   Backblaze B2, verifies it, then **deletes the local copy once it's safely on the
   cloud** (after a short grace window) so your drive stays lean.

## While you're still editing a game

Freshly pasted files stick around for `source_4k.free_after_hours` (default 12h) before
they're freed, so you have time to build the long-form / pull Shorts clips. Need longer?
**Pin** the game so its files are backed up but never auto-deleted until you're done:

```
python tools/archive_4k.py pin ff7remake      # pause auto-free (uploads still happen)
python tools/archive_4k.py unpin ff7remake    # resume auto-free
```

## Getting files back / manual control

```
python tools/archive_4k.py pull ff7remake                 # bring the whole game back
python tools/archive_4k.py pull ff7remake "Part 5.mp4"    # just one file
python tools/archive_4k.py list                           # what's archived on B2
python tools/archive_4k.py sync --dry-run                 # preview upload/free, do nothing
python tools/archive_4k.py free ff7remake                 # free now (skip the grace window)
```

Settings live in `config.yaml -> source_4k`. Files here are **git-ignored** (huge,
local-only). The cloud copy lives in your B2 bucket under `4k-hdr/<game>/`.

**The same scheduled sync also handles the FILL-format pools** (so pasted footage is
auto-clouded + freed everywhere):
- `reels/assets/footage/<game>-vertical/` (1080p feed fill) → the **GitHub footage
  release** via `tools/footage.py sync`, local deleted once uploaded.
- `reels/assets/footage-4k/<game>-vertical/` (4K HDR YouTube fill) → **B2** under
  `4k-vertical/<game>-vertical/` via `tools/archive_4k.py sync`, freed after the grace
  window; `run.py --youtube-short` pulls a clip back on demand to render.

> **If `pull` stalls at 0 B:** uploads work but a download that hangs at 0 bytes means
> your security suite (**Avast Web Shield**) is intercepting the B2 *download*
> connection — the same thing that once killed a YouTube upload. Add an exception for
> `%LOCALAPPDATA%\rclone\rclone.exe` (and the B2 hosts) in Avast, then `pull` works.
> Uploading + auto-freeing are unaffected, so your paste-and-archive flow still runs.
