import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// Articles are markdown files in src/content/articles/. The Python trend pipeline will
// write one file per published story (front-matter + body), then commit -> Netlify rebuilds.
const articles = defineCollection({
  loader: glob({ base: "./src/content/articles", pattern: "**/*.md" }),
  schema: z.object({
    title: z.string(),
    excerpt: z.string(),
    category: z.string().default("News"),      // Marvel Games | MCU | PlayStation | ...
    tag: z.string().default("News"),           // pill label: News | Preview | Rumor | Hot
    game: z.string().optional(),               // franchise/property for theming
    cover: z.string().optional(),              // /images/... hero image (our card / official still)
    coverAlt: z.string().default(""),
    date: z.coerce.date(),
    author: z.string().default("KiwinoyGamer"),
    sourceName: z.string().optional(),         // outlet we credit (e.g. "IGN")
    sourceUrl: z.string().url().optional(),    // link back to the original report
    featured: z.boolean().default(false),
    draft: z.boolean().default(false),
  }),
});

export const collections = { articles };
