# CONTINUITY — KiwinoyGamer automation (current state & handoff)

> Read this first when picking the project up on a new PC or in a new session.
> The top-level `README.md` is OUTDATED (describes the old gacha/sports feed
> system from before the games-only pivot). **This file is the source of truth.**

## What the system is now (games-only)

KiwinoyGamer is a **fully autonomous, cloud-run** gaming social poster. Two tracks
are active:

1. **Gameplay reels** — 6/day. One Spider-Man gameplay clip, a psychology-driven
   on-screen hook + short caption (both lore-grounded), color-graded footage,
   animated KG logo (plays once), random length **60/90/120/170s**. Posts to
   **Facebook, Instagram, Threads, YouTube** (never X).
2. **Threads/X text track** — ~16/day. AAA-game text posts (≤280 chars), lore-
   accurate, hype/positive tone. Posts to **Threads + X**.
3. **Game commentary reels** — 4/day, **Facebook ONLY**. A Taglish voiceover
   (ElevenLabs) over gameplay b-roll with burned Taglish subtitles, the SAME 3:4
   band layout + circular/animated logos + Taglish on-screen hook as the gameplay
   reels. Length auto-varies short/medium per run (`reels.commentary.length_choices`).
   Funny/relatable barkada tone, lore-accurate (fact-checked). Run:
   `python run.py --commentary`. Workflow `commentary.yml`.

Everything else (image feed `post.yml`, carousel `carousels.yml`, FF7 photopost
`ff7.yml`, sports `threads-image.yml`) is **disabled** (schedules commented out;
still hand-runnable via `workflow_dispatch`). Sports/esports/gacha were dropped.

## It runs in the cloud — no PC required

| Piece | Where it lives |
|---|---|
| Code | GitHub repo `cloudstrive6/kiwinoy-social-posting` (public) |
| Secrets | GitHub **Actions Secrets** (not on any PC) |
| Schedules | **cron-job.org** (user's account) → triggers GitHub `workflow_dispatch` |
| Render + publish | **GitHub Actions** (ffmpeg in CI) |
| Footage storage | GitHub **Release** tag `footage` (assets `<game>__<file>`) |
| Account connections | **Post for Me** (api.postforme.dev) — user's account |

A new PC (or no PC) does NOT interrupt posting. The only thing needing a PC is
**uploading new gameplay clips** (repo + `gh` login).

## Schedules (all times :25 past, UTC)

- **Reels** — cron-job.org job *"KiwinoyGamer Reels (6/day, every 4h)"* POSTs to
  the `reels.yml` dispatch API every 4h (`25 */4 * * *`) with
  `{"ref":"main","inputs":{"slot":"1","dry_run":"false"}}`.
- **Threads** — cron-job.org job *"KiwinoyGamer Threads (16/day, ~90min)"* → the
  `threads.yml` dispatch API.
- **Commentary** — cron-job.org job *"KiwinoyGamer Commentary (4/day, PH prime)"* →
  the `commentary.yml` dispatch API, 4×/day at PH prime (00:00, 04:00, 11:00,
  13:30 UTC = 8 AM, 12 PM, 7 PM, 9:30 PM PHT). FB only.
- GitHub's native `schedule:` cron is **disabled** for reels (it silently
  dropped/delayed runs — 8h+ gaps). Do NOT re-enable it alongside cron-job.org or
  posts double up.
- `ready-reels.yml` (posts the user's own finished reels from the `ready-reels`
  Release queue) is still on GitHub native cron, 4×/day — only fires if the queue
  has reels.

## GitHub Actions secrets (already set)

`CLAUDE_CODE_OAUTH_TOKEN` (research/captions/lore via subscription),
`ANTHROPIC_API_KEY` (fallback), `OPENAI_API_KEY` (legacy image gen, mostly unused
now), `POSTFORME_API_KEY` (publishing), `ELEVENLABS_API_KEY` (optional VO).
`GH_TOKEN` is the workflow's `github.token` (reels.yml has `permissions: contents:
write` so it can update the used-clip ledger).

## Onboarding a NEW PC

1. Install **Claude Code**, log in.
2. `git clone https://github.com/cloudstrive6/kiwinoy-social-posting`
3. `gh auth login` as **cloudstrive6** (pushes 403 under other accounts — always
   `gh auth switch --user cloudstrive6` before pushing).
4. (Only for firing posts *manually*) set local env / `.env`: `POSTFORME_API_KEY`,
   `CLAUDE_CODE_OAUTH_TOKEN`, optionally `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`,
   `GH_TOKEN`. The cloud already has these — local is just for hand-runs.
5. Install **ffmpeg** (winget) for local renders. The agent's persistent memory
   lives under `~/.claude/projects/<project-key>/memory/` — copy that folder over
   as a backup of session context (this file covers the durable knowledge anyway).

## Running things by hand

```
python run.py --slot 1 --reel        # render + publish ONE gameplay reel
python run.py --threads              # research + write + factcheck + publish a Threads/X post
python run.py --ready-reel           # post the next queued finished reel
python run.py --slot 1 --reel --dry-run   # render only, no publish
python tools/footage.py sync         # upload new clips to the Release, delete local copies
python tools/list_accounts.py        # show connected Post for Me accounts + IDs
```

## Key policies / decisions baked in

- **No local Remotion / heavy renders** — the user's PC BSODs (bad RAM, 0x1A) under
  headless-Chrome render load. Reels are ffmpeg-only and render in CI. ffmpeg
  compression locally is OK but keep it bounded.
- **Lore-grounded content** (`core/lore.py`): reel captions use an observer +
  lore captioner; Threads posts inject the game's canon. Covers Spider-Man 1 /
  Miles / 2 and FF7. **FF7 Revelation is REAL** (the Remake Part 3 trilogy finale,
  Spring 2027, PS5/Xbox/Switch 2/PC) — post only confirmed news, never invented
  plot.
- **Threads tone**: hype/positive, never complaints/outrage-bait
  (`core/style.py:POSITIVE_TONE`). Fact-check (`agents/factcheck.py`) fails
  invented titles / wrong-canon claims.
- **Footage reuse**: gameplay reels never repeat a clip (ledger
  `_used_gameplay.json` on the footage Release; `reel_composer.pick_unused_clip`).
  Clips are **never deleted** — kept for future commentary reels. Once a clip is on
  the Release, the local copy is deleted to free disk.
- **Reel layout**: 1080×1920; top band 320 (hook), 3:4 footage 1440, bottom band
  160 (animated logo, plays once); subtle color grade (`reels.grade`); lengths
  random 60/90/120/170 — anything >90s auto-routes as a feed video on Facebook
  (FB Reels caps ~90s) while staying a Reel on IG and a Short/video on YouTube.
- **Token hygiene**: `core/postforme.py:_scrub` strips OAuth tokens from anything
  saved to artifacts (a public-repo leak happened once and was purged).

## Troubleshooting — Post for Me accounts (IMPORTANT, hit twice)

**Whenever the user reconnects an account in Post for Me, two things can break:**

1. **Account IDs rotate — NOW AUTO-HANDLED.** `account_ids()` resolves each
   platform to its live id via the STABLE external id (`platforms.external_ids`,
   e.g. `kg-facebook`), so a reconnect no longer needs any config edit. Only
   requirement: each account's **External ID** in Post for Me must match
   `platforms.external_ids` (`kg-facebook`, `kg-instagram`, `kg-threads`,
   `kg-xtwitter`, `kg-youtube`). The `accounts:` spc_ block is just an offline
   fallback now.
2. **Stored token gets invalidated** (esp. Facebook). FB/IG posts fail at publish
   with `OAuthException code 190, subcode 460` — *"session invalidated because the
   user changed their password / FB security."* **Instagram fails with it too**,
   because Post for Me publishes IG through the Facebook Graph session. Threads &
   YouTube use separate auth and are unaffected. Fix (user-only): **reconnect
   Facebook + Instagram in the Post for Me dashboard** to mint a fresh token, and
   don't change the FB password afterward. (No ID re-sync needed — see #1.)

Other gotchas: the GitHub `releases/tags` asset list is CDN-cached (use the
per-release `/releases/{id}/assets` endpoint); read Release JSON assets by asset
**id**, not the download URL (also CDN-cached); `gh_release` reads must be
authenticated or they hit the 60/hr anon rate limit.
