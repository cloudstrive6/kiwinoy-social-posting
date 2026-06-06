# KiwinoyGamer — Autonomous Social Posting Team

A 5-agent system that researches trending **gacha** (Genshin Impact / Honkai:
Star Rail / NTE) and **sports** (EPL / NFL / NBA / tennis) topics, writes
scroll-stopping captions, generates matching images with headlines baked in, and
auto-publishes to **Facebook + Instagram + Threads** — **4 posts a day**,
alternating Gacha → Sports → Gacha → Sports.

Runs fully unattended in the cloud via **GitHub Actions** (no PC needed).

---

## The team

| Agent | File | Job |
|---|---|---|
| 1. Research & Trending | `agents/research.py` | Web-searches live trends, picks the day's topic, writes a brief |
| 2. Content Creation | `agents/content.py` | Writes the FB + IG caption with **Claude** |
| 3. Threads Creator | `agents/threads.py` | Writes a punchier native Threads post with **Claude** |
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
Copy `.env.example` to `.env` and paste your three keys:
```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
POSTFORME_API_KEY=...
```
- **Anthropic (Claude)** key → https://console.anthropic.com/settings/keys  *(writes captions + Threads)*
- **OpenAI** key → https://platform.openai.com/api-keys  *(trend research + images)*
- **Post for Me** key → https://www.postforme.dev (Dashboard → API Keys)  *(publishing)*

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
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
   - `POSTFORME_API_KEY`
3. That's it. The workflow in `.github/workflows/post.yml` fires **4×/day** and
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
| 1 | 12:00 | 🎮 Gacha |
| 2 | 16:00 | ⚽ Sports |
| 3 | 20:00 | 🎮 Gacha |
| 4 | 00:00 | 🏈 Sports |

---

## CLI reference
```
python run.py --slot N [--dry-run]   # run a specific slot
python run.py --auto                 # run the slot closest to now
python run.py --all --dry-run        # test all 4 slots, no publish
python tools/list_accounts.py --save # discover + save account IDs
```
