# TikTok posting — how it works

> **Keep this file up to date.** Whenever the TikTok process changes (routing, encode,
> captions, cadence, cron status), update this doc in the same change.

_Last updated: 2026-07-10._

## TL;DR
Everything TikTok goes to **Post for Me DRAFTS** (PfM's TikTok app is unaudited → can't
auto-publish public), which you **publish manually** in the TikTok app. Each draft's
**caption + hashtags** are DMed to you on **Telegram** to copy-paste. There are **two paths**:

- **Automated 1080p (CI)** — the `tiktok.yml` cron renders a 1080p SDR gameplay reel 4×/day
  and posts it as a PfM draft. Runs in GitHub Actions (no GPU needed for 1080p).
- **Manual 4K/60 HDR (local)** — you ask for it; `process_tiktok_hd.py` renders 4K HDR on
  your GPU and posts as a PfM draft (preserves 60fps HDR). Kept open for on-demand use.

Both DM the caption to Telegram; both need manual publish in-app.

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

## Automated 1080p (CI)
`.github/workflows/tiktok.yml` runs `python run.py --tiktok` → `run_gameplay_reel(tiktok_only=True)`
→ renders a 1080p SDR reel (classic/triptych/fill rotation, game = `reels.tiktok.game`) →
`tiktok.via: postforme` → `publisher.run_tiktok_draft` (PfM draft) → Telegram caption.
Fired by 4 cron-job.org jobs (KiwinoyGamer TikTok slots 1-4). Needs GH Secrets:
`POSTFORME_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (+ the usual AI keys).

## Manual 4K/60 HDR (local, needs GPU)
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
- `reels.tiktok.hi_bitrate`: the CI 1080p encode. `true` = Premiere 2-pass VBR 15/20 Mbps
  (current); `false` = the lighter CRF21 feed encode. (PfM re-encodes the draft either way.)

## Cron status
The **CI TikTok cron** (`tiktok.yml`, **PfM drafts**) runs **2×/day** on cron-job.org —
**slots 2 (11:00 NZ) + 4 (23:00 NZ) ENABLED**; slots 1 & 3 disabled (2026-07-10). Lowered
from 4×/day because every draft is a **manual publish**: if drafts pile up unpublished,
TikTok blocks new ones with **`spam_risk_too_many_pending_share`** (400). Keep the draft
inbox reasonably clear. The **4K HDR** path is separate/**local/on-demand**
(`process_tiktok_hd.py`) — can't run in CI (no GPU); run it manually when you want HD.

## Gotcha: pending-draft cap
TikTok limits how many **unpublished drafts** can sit in the inbox. Too many →
`spam_risk_too_many_pending_share` on new drafts. Note the async gap: the Telegram DM +
"clip marked used" fire when PfM ACCEPTS the post, but TikTok's rejection is async after —
so a caption can DM even when the draft didn't actually land. Publish/clear drafts regularly.

## Manual step per post
Open the TikTok draft → copy the caption from the Telegram DM → paste → publish.
```
