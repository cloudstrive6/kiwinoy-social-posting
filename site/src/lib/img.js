// Responsive image attributes for covers and game art.
// integrations/image-variants.mjs writes /img/<width>/<folder>/<name>.webp after every build
// (sharp, already an Astro dependency), so cards get small WebP files and the article and home
// lead get a sharp one. The original JPG stays as `src`, and nothing in public/covers moves.
export const WIDTHS = [480, 800, 1200];
const VARIANT = /^\/(covers|game-art)\/([^/]+)\.(jpe?g|png|webp)$/i;

export function imgAttrs(src, { width = 1200, height = 675, sizes = "100vw" } = {}) {
  if (!src) return null;
  const m = src.match(VARIANT);
  const out = { src, width, height };
  if (m) {
    out.srcset = WIDTHS.map((w) => `/img/${w}/${m[1]}/${m[2]}.webp ${w}w`).join(", ");
    out.sizes = sizes;
  }
  return out;
}

export const SIZES = {
  card: "(min-width: 1024px) 290px, (min-width: 641px) 46vw, 92vw",
  row: "160px",
  lead: "(min-width: 1024px) 760px, 100vw",
  cover: "(min-width: 1060px) 1000px, 100vw",
  tile: "(min-width: 1024px) 380px, (min-width: 641px) 46vw, 92vw",
};
