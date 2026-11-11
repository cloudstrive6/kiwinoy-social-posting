// Responsive image attributes for covers, game art and gear photos.
// integrations/image-variants.mjs writes /img/<width>/<folder>/<name>.webp after every build
// (sharp, already an Astro dependency), so cards get small WebP files and the article and home
// lead get a sharp one. The original JPG stays as `src`, and nothing in public/covers moves.
// Gear product photos also get /img/cut/<width>/gear/<name>.webp: the white studio background
// removed, so they sit on the dark product tile.
export const WIDTHS = [480, 800, 1200];
const VARIANT = /^\/(covers|game-art|gear)\/([^/]+)\.(jpe?g|png|webp)$/i;
const PRODUCT = /^\/gear\/(?!luxdrop)([^/]+)\.(jpe?g|png|webp)$/i;

export const isProductShot = (src) => !!src && PRODUCT.test(src);

export function imgAttrs(src, { width = 1200, height = 675, sizes = "100vw" } = {}) {
  if (!src) return null;
  const out = { src, width, height };
  const p = src.match(PRODUCT);
  if (p) {
    out.srcset = `/img/cut/480/gear/${p[1]}.webp 480w, /img/cut/800/gear/${p[1]}.webp 800w`;
    out.src = `/img/cut/800/gear/${p[1]}.webp`;
    out.sizes = sizes;
    out.product = true;
    return out;
  }
  const m = src.match(VARIANT);
  if (m) {
    out.srcset = WIDTHS.map((w) => `/img/${w}/${m[1]}/${m[2]}.webp ${w}w`).join(", ");
    out.sizes = sizes;
  }
  return out;
}

export const SIZES = {
  card: "(min-width: 1024px) 290px, (min-width: 641px) 46vw, 92vw",
  big: "(min-width: 1024px) 600px, (min-width: 641px) 92vw, 100vw",
  row: "160px",
  lead: "(min-width: 1024px) 760px, 100vw",
  cover: "(min-width: 1060px) 1000px, 100vw",
  tile: "(min-width: 1024px) 380px, (min-width: 641px) 46vw, 92vw",
  gear: "(min-width: 1024px) 280px, 46vw",
};
