# KiwinoyGamer — Autonomous Social Posting Team

A 5-agent system that researches trending **gacha** (Genshin Impact / Honkai:
Star Rail / NTE) and **sports** (EPL / NFL / NBA / tennis) topics, writes
scroll-stopping captions, generates matching images with headlines baked in, and
auto-publishes **6 feed posts a day**, alternating Sports and Gacha. **Gacha**
posts go to **Facebook + Instagram** with an anime image; **Sports** posts are
**text-only on Facebook** (no image — AI can't show real players, so sports skips
Instagram). Separate **Reels** (gacha) and **Threads** (sports) tracks run on top
(see below).

Runs fully unattended in the cloud via **GitHub Actions** (no PC needed).

---

## The team

| Agent | File | Job |
|---|---|---|
| 1. Research & Trending | `agents/research.py` | Pulls real community buzz via the vendored **last30days** engine (Reddit/Polymarket/HN/GitHub), LLM-synthesizes a brief; web-search fallback |
| 2. Content Creation | `agents/content.py` | Writes the FB + IG caption with **Claude** |
| 3. Threads track | `agents/threads_research.py` + `threads_writer.py` | Separate sports-only Threads posts (text, <=500 chars) via your Claude subscription |
| 4. Image Generation | `agents/image.py` | `gpt-image-1` image w/ on-image headline (sports = photoreal, gacha = anime) |
| 5. Publisher | `agents/publisher.py` | Uploads the image + schedules to FB/IG/Threads via Post for Me |

`orchestrator.py` runs them in order for one slot; `run.py` is the CLI.

**Voice:** captions and Threads are written by **Claude**, with a strict
"human voice" filter (`core/style.py`) that bans em-dashes and the usual AI
tells, plus a mechanical cleanup pass as a backstop so nothing AI-sounding slips
through.

**Caption engagement:** captions use a story framework (hook → tension → payoff →
CTA). The first line is the **"See More" hook**, written and enforced to stay
**under 140 characters** (Facebook truncates around there) so people choose to
expand. Captions stay short by default; long-form is only used when the topic is
genuinely educational, entertaining, or high community value. Tune in
`config.yaml → caption`.

---

## Setup (one time)

### 1. Install Python deps
```powershell
pip install -r requirements.txt
```

### 2. Add your API keys
Copy `.env.example` to `.env` and paste your keys:
```
OPENAI_API_KEY=sk-...
POSTFORME_API_KEY=...
CLAUDE_CODE_OAUTH_TOKEN=...
ANTHROPIC_API_KEY=sk-ant-...   # optional (only if writer_provider: anthropic)
```
- **OpenAI** key → https://platform.openai.com/api-keys  *(trend research + images)*
- **Post for Me** key → https://www.postforme.dev (Dashboard → API Keys)  *(publishing)*
- **Claude Code OAuth token** → run `claude setup-token` (needs a Claude Pro/Max
  plan)  *(powers the Threads track on your subscription, no per-token billing)*
- **Anthropic API key** → optional; only needed if you switch the FB/IG caption
  writer to Claude (`writer_provider: anthropic`)

### 3. Connect your social accounts
In the **Post for Me dashboard**, connect KiwinoyGamer's **Facebook Page,
Instagram (Business/Creator), and Threads** accounts. Then pull their IDs:
```powershell
python tools/list_accounts.py --save
```
This writes the account IDs into `config.yaml` automatically.

### 4. Test without posting
```powershell
python run.py --slot 1 --dry-run     # gacha
python run.py --slot 2 --dry-run     # sports
```
Check the `output/<timestamp>_slotN_.../` folder — you'll see `brief.json`,
`caption.txt`, `threads.txt`, and `image.png`. When happy, drop `--dry-run`.

---

## Going live in the cloud (GitHub Actions)

1. Create a **private GitHub repo** and push this folder to it.
2. In the repo: **Settings → Secrets and variables → Actions → New repository
   secret**, add:
   - `OPENAI_API_KEY`
   - `POSTFORME_API_KEY`
   - `CLAUDE_CODE_OAUTH_TOKEN`
   - `ANTHROPIC_API_KEY` *(optional)*
3. That's it. The workflow in `.github/workflows/post.yml` fires **6×/day** and
   publishes automatically. You can also trigger a manual run from the
   **Actions** tab (with an optional dry-run toggle).

> ⚠️ Commit everything **except `.env`** (it's already in `.gitignore`). Keys
> live only in GitHub Secrets, never in the repo.

---

## Tuning it

Everything lives in **`config.yaml`** — no code changes needed:
- **Posting times** → `schedule.slots` (UTC). Keep them in sync with the cron
  lines in `.github/workflows/post.yml`.
- **Brand voice** → `brand.voice`
- **Games / leagues / angles** → `topics`
- **Hashtags** → `hashtags`
- **Image look & headline rules** → `image`
- **Models** → `models` (swap text/image models anytime)

### Posting schedule (default, UTC)
| Slot | UTC | Topic |
|---|---|---|
| 1 | 00:00 | ⚽ Sports |
| 2 | 04:00 | 🎮 Gacha |
| 3 | 08:00 | ⚽ Sports |
| 4 | 12:00 | 🎮 Gacha |
| 5 | 16:00 | ⚽ Sports |
| 6 | 20:00 | 🎮 Gacha |

---

## Reels track (short vertical videos)

A **separate** cadence from the image posts: **1 gacha reel/day** at 18:00 UTC.
(Sports reels were stopped — AI can't show the real players.) Each is a
**12-15s, 9:16 MP4** with **Ken Burns motion + animated storytelling captions**
and the **KIWINOY logo**, rendered free with **Remotion** in GitHub Actions, then
published to Instagram + Facebook **Reels** via Post for Me.

Pipeline per reel: research -> reel caption + on-screen beats -> background shots
(`gpt-image-1`, vertical, no baked text) -> Remotion render -> publish.

New pieces:
- `agents/reel_script.py` - storytelling on-screen beats (hook -> payoff -> CTA)
- `agents/reel_composer.py` - drives the Remotion render
- `reels/` - the Remotion project (`src/Reel.tsx` is the composition)
- `.github/workflows/reels.yml` - the 6x/day reels cron

Tune in `config.yaml -> reels` (duration, fps, shots, beats, schedule, styles).

### Music (optional but recommended)
Drop **royalty-free** `.mp3`/`.m4a` files in `reels/assets/music/`. The composer
picks one at random per reel; if the folder is empty, reels render silent. Never
use licensed songs - they get auto-flagged on IG/FB.

### Run a reel locally
```powershell
cd reels; npm install; cd ..        # one-time: install the renderer
python run.py --reel --slot 1 --dry-run   # render a reel, publish nothing
```
The MP4 lands in `output/<timestamp>_reel.../reel.mp4`.

## Research engine (last30days)

All research (image, reel, and Threads) is powered by the **vendored last30days
skill** (`vendor/last30days/`, MIT) running in direct-CLI mode: it pulls the
freshest, highest-engagement community stories from **free sources** (Reddit,
Hacker News, Polymarket, GitHub) for the chosen game/league, then an LLM
synthesizes our brief. A **topic guardrail** keeps the hype voice off tragic /
sensitive / unverified stories. If last30days returns nothing or errors, the
agents **fall back to web-search research**, so posts never stop. Tune in
`config.yaml -> research` (engine, sources, targets/subreddits).

## Threads track (text-only, sports)

A **separate** track from the image/reel posts. **Image posts and reels go to
Facebook + Instagram only** now — Threads is handled here:
- **Sports only**, **text only** (no images/reels), **<=500 characters**
- Storytelling with a scroll-stopping first-line "hook"
- Posts **every 2 hours** (`.github/workflows/threads.yml`)
- Researched + written by **Claude via your subscription**
  (`CLAUDE_CODE_OAUTH_TOKEN`), so the high frequency costs nothing per token

Each run independently web-searches a fresh trending sports story, so there are
no slots. Tune in `config.yaml -> threads_posts`.

Run one locally:
```powershell
python run.py --threads --dry-run   # research + write, publish nothing
```

## CLI reference
```
python run.py --slot N [--dry-run]   # run a specific slot
python run.py --auto                 # run the image slot closest to now
python run.py --reel --slot N        # render + publish a reel
python run.py --threads              # research + write + publish a Threads post
python run.py --all --dry-run        # test all image slots, no publish
python tools/list_accounts.py --save # discover + save account IDs
```
