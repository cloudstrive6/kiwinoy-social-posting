// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// Update `site` to your real domain once it's registered (used for canonical URLs,
// sitemap, RSS). Netlify serves a *.netlify.app URL until the custom domain is attached.
export default defineConfig({
  site: "https://bosskg.com",
  integrations: [sitemap()],
  trailingSlash: "ignore",
});
