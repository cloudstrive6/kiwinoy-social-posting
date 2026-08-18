// RSS feed of the latest BOSS KG articles — powers MailerLite's RSS auto-campaign (email
// subscribers when new articles publish) and general feed readers. Lives at /rss.xml.
import rss from "@astrojs/rss";
import { getCollection } from "astro:content";

export async function GET(context) {
  const articles = (await getCollection("articles", ({ data }) => !data.draft))
    .sort((a, b) => b.data.date.valueOf() - a.data.date.valueOf())
    .slice(0, 30);

  return rss({
    title: "BOSS KG — Gaming & Marvel News",
    description:
      "The drop-first source for video games, the MCU, and the biggest moments in gaming.",
    site: context.site,
    items: articles.map((a) => ({
      title: a.data.title,
      description: a.data.excerpt,
      pubDate: a.data.date,
      link: `/news/${a.id}/`,
      categories: a.data.tags,
    })),
    customData: "<language>en-us</language>",
  });
}
