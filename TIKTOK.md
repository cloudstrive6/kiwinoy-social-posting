# TikTok posting — how it works

> **Keep this file up to date.** Whenever the TikTok process changes (routing, encode,
> captions, cadence, cron status), update this doc in the same change.

_Last updated: 2026-07-09._

## TL;DR
TikTok posts are **full-quality 4K/60 HDR drafts** delivered via **Post for Me**, which
you **publish manually** in the TikTok app. Each draft's **caption + hashtags** are DMed to
you on **Telegram** to copy-paste (TikTok's draft API ignores captions). It's a **local**
workflow (4K HDR needs your GPU) — it does **not** run in CI.

## Why this design
| | Zernio (old) | Post for Me (current) |
|---|---|---|
| Quality on TikTok | ❌ re-compressed server-side (no HDR/60fps) | ✅ preserves **60fps HDR** |
| Public auto-post | ✅ | ❌ PfM's TikTok app is **unaudited** → public direct-post 403s |
| Only working path | direct public | **draft** (inbox), publish manually |
| Caption | ✅ auto | ❌ TikTok ignores caption on drafts → paste manually |

TikTok's Content Posting API only lets **unaudited** apps push **drafts** (or `SELF_ONLY`).
Public + captioned + automated needs the app to pass TikTok's **audit** — out of our hands
(PfM would have to get their TikTok app audited). Until then: HD drafts + manual publish.

## The pipeline (local, needs GPU)
```
python process_tiktok_hd.py <game> <count>      # e.g. spider-man2 6
```
1. **Reuse-first** — cross-posts the 4K HDR short renders already made for YouTube
   (`output/*_youtube_short/short.mp4`).
2. **Fallback** — if a game runs out of reusable renders, renders fresh 4K HDR reels from
   the **4K pool** (same as `run_youtube_short`).
3. **Dedupe** — per-game ledger `reels/assets/.tiktok_ledgers/<game>.json` (never posts the
   same render to TikTok twice).

Each render → **PfM draft** (`agents/publisher.run_tiktok_draft`) → TikTok inbox in full
60fps HDR. Alternatively, `run_youtube_short(game, tiktok=True)` sends one render to **both**
YouTube + TikTok in a single pass; `youtube=False, tiktok=True` = TikTok-only from the pool.

## Captions → Telegram
`core/notify.py` DMs the exact **caption + hashtags** (one clean message per draft) so you
long-press → Copy → paste when publishing. Setup (env-only, `.env`):
- `TELEGRAM_BOT_TOKEN` (from @BotFather), `TELEGRAM_CHAT_ID` (`python -m core.notify chatid`).
- Test: `python -m core.notify test`. Fail-open (no-op if unset).

Captions are lore-accurate: default to generic **"Spider-Man"** unless the black symbiote
suit / yellow bio-electric Venom makes it unmistakably Peter / Miles (`core/lore.py`).

## Config / toggles
- `tiktok.via` (config.yaml): `postforme` (current) | `zernio` (auto-public, degraded).
- `reels.tiktok.extra_hashtags`: appended to the TikTok caption only (e.g. `#gaming`).
- `reels.tiktok.hi_bitrate`: TikTok 1080p CI encode spec (Premiere 2-pass 15/20 Mbps) —
  only relevant to the `zernio`/CI path, which is superseded.

## Cron status
The old **CI 4×/day TikTok cron** (Zernio, 1080p, `tiktok.yml`) is **superseded and
DISABLED** on cron-job.org (all 4 KiwinoyGamer TikTok slots set Inactive, 2026-07-09). HD
TikTok is a **local, on-demand** step (`process_tiktok_hd.py`) — it can't run in CI (no GPU).

## Manual step per post
Open the TikTok draft → copy the caption from the Telegram DM → paste → publish.
```
