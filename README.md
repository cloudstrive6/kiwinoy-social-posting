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
| 1. Research & Trending | `agents/research.py` | Web-searches live trends (OpenAI for image/reel, Claude for Threads), verifies recency, writes a brief |
| 2. Content Creation | `agents/content.py` | Writes the FB + IG caption with **Claude** |
| 3. Threads track | `agents/threads_research.py` + `threads_writer.py` | Separate sports-only Threads posts (text, <=500 chars) via your Claude subscription |
| 4. Image Generation | `agents/image.py` | `gpt-image-1` image w/ on-image headline (sports = photoreal, gacha = anime) |
| 5. Fact-Check / Review | `agents/factcheck.py` | **Independently web-searches to verify every factual claim before publishing.** Fail → regenerate once → skip if still wrong. Polls skipped (opinion). |
| 6. Publisher | `agents/publisher.py` | Uploads the image + schedules to FB/IG/Threads via Post for Me |

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
ELEVENLABS_API_KEY=...         # optional (AI Taglish voiceover on reels)
```
- **OpenAI** key → https://platform.openai.com/api-keys  *(trend research + images)*
- **Post for Me** key → https://www.postforme.dev (Dashboard → API Keys)  *(publishing)*
- **Claude Code OAuth token** → run `claude setup-token` (needs a Claude Pro/Max
  plan)  *(powers the Threads track on your subscription, no per-token billing)*
- **Anthropic API key** → optional; only needed if you switch the FB/IG caption
  writer to Claude (`writer_provider: anthropic`)
- **ElevenLabs API key** → optional; adds an AI Taglish voiceover to reels. Get it
  at https://elevenlabs.io (Profile → API Keys), then set a voice in
  `config.yaml → reels.narration.voice_id`. Without it, reels render music-only.

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
   - `ELEVENLABS_API_KEY` *(optional — AI Taglish voiceover on reels)*
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

## Research engine (web search) + cost model

All research is **web-search based** with **recency + accuracy** guards (verify
it's current, never post speculation about something already decided) and a
**topic guardrail** (no tragic/sensitive/unverified stories).

**Everything LLM runs on your Claude subscription token (free):** research,
caption/beats writing, the Threads posts, and the fact-check all use
`CLAUDE_CODE_OAUTH_TOKEN` (with `ANTHROPIC_API_KEY` as fallback). **The only paid
piece is the image/video generator** (`gpt-image-1` on OpenAI). Flip
`models.writer_provider` back to `openai` in `config.yaml` if you ever want to.

*(An earlier "last30days" community-scraping engine was removed — it surfaced
stale, pre-announcement threads.)*

## Threads track (text-only, sports)

A **separate** track from the image/reel posts. **Image posts and reels go to
Facebook + Instagram only** now — Threads is handled here:
- **Sports only**, **text only** (no images/reels), **<=500 characters**
- Storytelling with a scroll-stopping first-line "hook"
- Posts **every 2 hours** (`.github/workflows/threads.yml`)
- Researched + written by **Claude via your subscription**
  (`CLAUDE_CODE_OAUTH_TOKEN`), so the high frequency costs nothing per token

**Three post types** (the every-2h cron fires the two mandatory ones daily):
- **update** (default) — fresh trending sports story
- **prediction** (09:00 UTC) — detailed esports/sports breakdown with bullets
  (stats, form, % odds)
- **poll** (15:00 UTC) — risk/probability hot take + a 2-option **reply-to-vote**
  poll (Post for Me can't post a native Threads poll, so it's a "reply A or B"
  text poll). Tune the themes/hours in `config.yaml -> threads_posts`.

Run one locally:
```powershell
python run.py --threads --dry-run                 # auto type (by UTC hour)
python run.py --threads --type poll --dry-run     # force a poll
python run.py --threads --type prediction --dry-run
```

## YouTube (4K/60 HDR) — LOCAL track

YouTube is an **HDR channel**: everything published there is native **4K/60 HDR10**
(Rec.2020 PQ). Because the source is multi-GB and encoding uses the local GPU
(`hevc_nvenc`), this track runs **on your PC, not in CI**.

**Long-form** (`run.py --youtube`) — concat the labelled 4K/60 HDR part files into a
full-game upload (stream-copy, HDR untouched) with an auto clickbait thumbnail. See
`config.yaml -> youtube_longform`.

**Shorts** (`run.py --youtube-short`) — the channel's Shorts are a dedicated 4K/60 HDR
track (the 1080p-via-Post-for-Me path was stopped 2026-07-03). Each Short is rendered
from the **4K HDR footage pool** and **alternates classic <-> triptych**, using the
**exact same edit/export as the long-form** (HDR10 + `loudnorm` audio + darkened HDR
text), then uploaded via the **YouTube Data API**. See `config.yaml -> youtube_shorts`.

Pipeline per Short: pick a fresh 4K HDR clip -> review it for a lore-grounded hook +
caption -> render `build_gameplay`/`build_gameplay_triptych` at 2160x3840 HDR -> upload
as a `#Shorts` via `core/youtube.py`. A tiny per-game ledger
(`footage-4k/<game>/.used_shorts.json`) tracks used clips + drives the alternation.

### Paste 4K HDR source once, use it for both
Drop raw **4K/60 HDR** captures into **`reels/assets/4k-hdr/<game>/`** — one intake that
feeds **both** the long-form pillar and the Shorts source. A scheduled job
(`run_4k_sync.bat`, ~every 30 min) uploads each file to Backblaze B2, verifies it, then
**frees the local copy** to save disk. Full guide: `reels/assets/4k-hdr/README.md`;
settings in `config.yaml -> source_4k`. Pin a game you're still editing:
```powershell
python tools/archive_4k.py sync            # upload new files + free verified (what the job runs)
python tools/archive_4k.py pull ff7remake  # bring a game's source back local
python tools/archive_4k.py pin ff7remake   # pause auto-free while you work on it
```

### Build the 4K HDR footage pool (Shorts)
Extract Short-length HDR clips from the source (keeps HDR10, unlike `hdr_to_reel.py`
which tonemaps to 1080p SDR for the feed reels):
```powershell
python tools/pool_4k.py "reels\assets\4k-hdr\ff7remake\<file>.mp4" ff7remake --at 00:12:30 --len 40 --name sephiroth-reveal
python tools/pool_4k.py --list ff7remake        # show the pool + used ledger
```
Clips land in `reels/assets/footage-4k/<game>/` (git-ignored — local only). These small
clips stay local (so Shorts render instantly) even after the big source is freed.

### Run / schedule a Short
```powershell
python run.py --youtube-short --dry-run         # render only, no upload
python run.py --youtube-short                   # render + upload (auto layout)
python run.py --youtube-short --layout triptych --privacy unlisted
```
**Cadence (Windows Task Scheduler):** YouTube throttled bulk Shorts, so keep it **low +
varied** — e.g. 2/day at different hours. `run_youtube_short.bat` is the runner; create
the schedule yourself (system-settings change) with, e.g.:
```cmd
schtasks /Create /TN "KG YouTube Short AM" /TR "\"Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting\run_youtube_short.bat\"" /SC DAILY /ST 09:30
schtasks /Create /TN "KG YouTube Short PM" /TR "\"Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting\run_youtube_short.bat\"" /SC DAILY /ST 20:00
```
The PC must be awake at those times; logs go to `output\.youtube_short.log`.

## CLI reference
```
python run.py --slot N [--dry-run]   # run a specific slot
python run.py --auto                 # run the image slot closest to now
python run.py --reel --slot N        # render + publish a reel
python run.py --threads              # research + write + publish a Threads post
python run.py --youtube --parts <dir> [--game K]   # LOCAL 4K HDR full-game upload
python run.py --youtube-short [--layout L] [--dry-run]  # LOCAL 4K HDR Short (auto classic/triptych)
python run.py --all --dry-run        # test all image slots, no publish
python tools/pool_4k.py --list <game># show the 4K HDR Shorts footage pool
python tools/list_accounts.py --save # discover + save account IDs
```
