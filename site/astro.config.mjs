// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import imageVariants from "./integrations/image-variants.mjs";

// `site` drives canonical URLs, the sitemap and RSS. Keep trailingSlash "ignore" and the default
// directory build format: bots post /news/<slug> without a slash and rely on the 301 to /news/<slug>/.
export default defineConfig({
  site: "https://bosskg.com",
  // The search results page is not a page to rank (it also sends X-Robots-Tag noindex, see netlify.toml).
  integrations: [sitemap({ filter: (page) => !/\/search\/?$/.test(page) }), imageVariants()],
  trailingSlash: "ignore",
  // Inline the one small stylesheet: saves a render-blocking round trip on a phone's first landing.
  build: { inlineStylesheets: "always" },
});
