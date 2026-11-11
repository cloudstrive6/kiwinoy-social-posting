// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import imageVariants from "./integrations/image-variants.mjs";

// `site` drives canonical URLs, the sitemap and RSS. Keep trailingSlash "ignore" and the default
// directory build format: bots post /news/<slug> without a slash and rely on the 301 to /news/<slug>/.
export default defineConfig({
  site: "https://bosskg.com",
  integrations: [sitemap(), imageVariants()],
  trailingSlash: "ignore",
});
