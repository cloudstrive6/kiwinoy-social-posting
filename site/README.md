# KiwinoyGamer — website

The public gaming & Marvel news site (Astro). Lives in this `site/` subfolder; Netlify
builds it in the cloud, so **you don't need Node installed locally** to ship it.

## Deploy (one-time)

1. **Netlify** → sign up (free) at netlify.com → *Add new site → Import from Git* → pick the
   `cloudstrive6/kiwinoy-social-posting` repo. Netlify reads `netlify.toml` at the repo root
   (base `site/`, build `npm run build`, publish `dist`). Click Deploy — you get a live
   `*.netlify.app` URL in ~2 minutes.
2. **Domain** → register `kiwinoygamer.com` (Namecheap / Cloudflare / Porkbun). In Netlify
   → *Domain settings → Add a domain* → follow the DNS steps. HTTPS is automatic.
3. Update `site` in `astro.config.mjs` to the real domain (canonical URLs / sitemap / RSS).

Every `git push` to `main` auto-rebuilds and redeploys. New articles appear automatically.

## Structure

- `src/pages/index.astro` — homepage (hero + Latest Drops + Follow + Newsletter).
- `src/pages/news/[...slug].astro` — article template.
- `src/content/articles/*.md` — one file per article (front-matter + body). **The Python
  trend pipeline writes these** and commits them; Netlify rebuilds.
- `src/layouts/Base.astro` — header, footer, theme toggle, SEO tags.
- `src/styles/global.css` — the design system (light + dark).

## Article front-matter

```yaml
title, excerpt, category, tag (News|Preview|Rumor|Hot), game, cover (/images/..),
coverAlt, date, author, sourceName, sourceUrl, featured (bool), draft (bool)
```

## Still to wire (next phases)

- Pipeline → auto-generate + commit an article per posted trend; caption links to it.
- MailerLite signup form + welcome/new-article automations.
- Follow page with live YouTube/TikTok/Instagram embeds.
- AdSense slots (apply once there's content + traffic).
- About / Privacy / Terms / Editorial-standards pages (required for ads).

## Run locally (optional, needs Node 20+)

```bash
cd site && npm install && npm run dev
```
