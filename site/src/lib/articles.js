// One place for reading and shaping articles. Every list on the site goes through
// liveArticles(), so a draft (draft: true) can never leak into a page, a rail or "Up next".
// Reads only fields the bots already write; no schema change.
import { getCollection } from "astro:content";

const byDateDesc = (a, b) => b.data.date.valueOf() - a.data.date.valueOf();

export async function liveArticles() {
  return (await getCollection("articles", ({ data }) => !data.draft)).sort(byDateDesc);
}

// The four section pages that exist under /category/. tools/site_qa.py hardcodes these slugs.
export const SECTIONS = {
  "marvel-games": {
    title: "Marvel games",
    blurb: "Insomniac's Spider-Man, Wolverine and the rest of Marvel's game slate.",
    match: (d) =>
      ["spider-man2", "spider-man", "spider-man1", "miles", "wolverine"].includes((d.game || "").toLowerCase()) ||
      /wolverine|spider|marvel games/i.test(d.category || ""),
  },
  mcu: {
    title: "MCU",
    blurb: "Movies, shows and the wider Marvel Cinematic Universe.",
    match: (d) => (d.game || "").toLowerCase() === "mcu" || /mcu/i.test(d.category || ""),
  },
  playstation: {
    title: "PlayStation",
    blurb: "PS5 news, updates and performance deep dives.",
    match: (d) => /playstation|ps5|pssr/i.test(d.category || ""),
  },
  news: {
    title: "Latest news",
    blurb: "Everything from BOSS KG, newest first.",
    match: () => true,
  },
};

// Where a story's category label should link. Categories without a section page
// ("Gaming", "Hardware") map to an existing page, never to a 404.
export function sectionFor(d) {
  if (/hardware/i.test(d.category || "")) return { slug: null, label: "Gear", href: "/gear/" };
  for (const slug of ["marvel-games", "mcu", "playstation"]) {
    if (SECTIONS[slug].match(d)) return { slug, label: SECTIONS[slug].title, href: `/category/${slug}/` };
  }
  return { slug: "news", label: "News", href: "/category/news/" };
}

// "Marvel Games | PlayStation" shows as "Marvel Games".
// One casing everywhere (crumbs, chips, cards): sentence case, names and acronyms kept.
const LABEL_CASE = { "marvel games": "Marvel games" };
export const catLabel = (c) => {
  const l = (c || "News").split("|")[0].trim();
  return LABEL_CASE[l.toLowerCase()] || l;
};

const GMAP = {
  wolverine: "g-wolv", "spider-man2": "g-spidey", "spider-man": "g-spidey",
  mcu: "g-mcu", playstation: "g-ps", marvel: "g-marvel",
};
export const gclass = (game, fallback = "g-marvel") => GMAP[(game || "").toLowerCase()] || fallback;

// Absolute dates everywhere ("Nov 2, 2026"). UTC so the build machine's zone never shifts a day.
export const fmtDate = (date, long = false) =>
  new Date(date).toLocaleDateString("en-US", {
    month: long ? "long" : "short", day: "numeric", year: "numeric", timeZone: "UTC",
  });

export const readMinutes = (body = "") => {
  const words = body.replace(/[#*_>`\[\]()!-]/g, " ").split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 230));
};

export const slugify = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// Plain, serialisable shape used by every card (safe to pass through getStaticPaths props).
export function toStory(entry) {
  const d = entry.data;
  return {
    id: entry.id,
    href: `/news/${entry.id}/`,
    title: d.title,
    excerpt: d.excerpt,
    cat: catLabel(d.category),
    tag: d.tag || "News",
    cover: d.cover ?? null,
    coverAlt: d.coverAlt || d.title,
    gclass: gclass(d.game),
    date: d.date.toISOString(),
    dateLabel: fmtDate(d.date),
  };
}

// Tags that match almost everything, so they say nothing about relatedness.
const GENERIC_TAGS = new Set([
  "marvel", "gaming", "games", "video-games", "news", "playstation", "ps5", "ps4", "sony",
  "mcu", "marvel-studios", "disney", "xbox", "pc", "nintendo", "trailer", "update", "rumor",
]);

// Relatedness score: same `game` first, then same category, then shared specific tags.
export function relatedScore(d, o) {
  const game = (d.game || "").toLowerCase();
  let score = 0;
  if (game && (o.game || "").toLowerCase() === game) score += 6;
  if (catLabel(o.category).toLowerCase() === catLabel(d.category).toLowerCase()) score += 3;
  const mine = new Set((d.tags || []).map(slugify).filter((t) => !GENERIC_TAGS.has(t)));
  for (const t of o.tags || []) if (mine.has(slugify(t))) score += 2;
  return score;
}

// Stories ranked by relatedness (ties: newest first). `all` is already draft-free and newest first.
// Never the story itself. Falls back to the newest other stories so there is always somewhere to go.
export function rankRelated(entry, all) {
  const others = all.filter((a) => a.id !== entry.id);
  const scored = others
    .map((a, i) => ({ a, i, s: relatedScore(entry.data, a.data) }))
    .sort((x, y) => y.s - x.s || x.i - y.i);
  return scored.map((x) => x.a);
}

// "Up next": the n most related stories.
export function related(entry, all, n = 2) {
  return rankRelated(entry, all).slice(0, n);
}
