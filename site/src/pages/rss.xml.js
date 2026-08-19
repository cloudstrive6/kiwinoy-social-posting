// RSS feed powering MailerLite's weekly RSS auto-campaign (email subscribers when new
// content publishes) and general feed readers. Lives at /rss.xml.
// Includes BOTH news articles (/news/<id>) AND new YouTube longform/live video pages
// (/watch/<slug>), so the weekly digest surfaces videos as well as written posts.
import rss from "@astrojs/rss";
import { getCollection } from "astro:content";
import { longform } from "../lib/youtube.js";

const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

export async function GET(context) {
  const articleItems = (await getCollection("articles", ({ data }) => !data.draft)).map((a) => ({
    title: a.data.title,
    description: a.data.excerpt,
    pubDate: a.data.date,
    link: `/news/${a.id}/`,
    categories: a.data.tags,
  }));

  // Longform = 16:9 full-game + live videos (Shorts are excluded by design).
  const videoItems = longform.map((v) => ({
    title: v.title,
    description:
      clean((v.blurb || "").split(/\n\n+/)[0]).slice(0, 300) ||
      `${v.title} — full gameplay from Boss KG.`,
    pubDate: new Date(v.published),
    link: `/watch/${v.slug}/`,
    categories: ["Video"],
  }));

  const items = [...articleItems, ...videoItems]
    .sort((a, b) => b.pubDate.valueOf() - a.pubDate.valueOf())
    .slice(0, 30);

  return rss({
    title: "BOSS KG — Gaming & Marvel News",
    description:
      "The drop-first source for video games, the MCU, and the biggest moments in gaming.",
    site: context.site,
    items,
    customData: "<language>en-us</language>",
  });
}
