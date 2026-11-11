// Build step: write small WebP copies of every cover, game-art and gear image so cards and the
// home lead do not download a full-size JPG on a phone. Runs after `astro build` (before pagefind)
// and only reads files already copied into dist/, so public/covers, which the cover bot writes,
// is never touched.
//
// Output:
//   dist/img/<width>/<folder>/<name>.webp       widths 480, 800, 1200 (covers, game-art, gear)
//   dist/img/cut/<width>/gear/<name>.webp        widths 480, 800: product photos with the white
//                                                studio background removed (flood fill from the
//                                                edges), so they sit on the dark product tile.
// If sharp cannot load or an image fails, the original file is copied to the variant path instead
// (browsers sniff image formats), so no srcset entry ever 404s.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WIDTHS = [480, 800, 1200];
const CUT_WIDTHS = [480, 800];
const FOLDERS = ["covers", "game-art", "gear"];
const IMG = /\.(jpe?g|png|webp)$/i;
const NOT_PRODUCT = /^luxdrop/i; // real photos, not studio shots

// Remove a near-white background connected to the image edge. Returns a PNG buffer with alpha.
async function cutout(sharp, file) {
  const { data, info } = await sharp(file).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h } = info;
  const px = (i) => i * 4;
  const bgLike = (i) => {
    const o = px(i), r = data[o], g = data[o + 1], b = data[o + 2];
    const mn = Math.min(r, g, b), mx = Math.max(r, g, b);
    return mn >= 247 && mx - mn <= 8;
  };
  const seen = new Uint8Array(w * h);
  const stack = [];
  const push = (i) => { if (!seen[i] && bgLike(i)) { seen[i] = 1; stack.push(i); } };
  for (let x = 0; x < w; x++) { push(x); push((h - 1) * w + x); }
  for (let y = 0; y < h; y++) { push(y * w); push(y * w + w - 1); }
  while (stack.length) {
    const i = stack.pop(), x = i % w, y = (i / w) | 0;
    if (x > 0) push(i - 1);
    if (x < w - 1) push(i + 1);
    if (y > 0) push(i - w);
    if (y < h - 1) push(i + w);
  }
  for (let i = 0; i < w * h; i++) {
    if (seen[i]) { data[px(i) + 3] = 0; continue; }
    // soften the 1px rim next to the removed background
    const x = i % w, y = (i / w) | 0;
    const nb = (x > 0 && seen[i - 1]) || (x < w - 1 && seen[i + 1]) || (y > 0 && seen[i - w]) || (y < h - 1 && seen[i + w]);
    if (nb) {
      const o = px(i), mn = Math.min(data[o], data[o + 1], data[o + 2]);
      const wht = Math.max(0, Math.min(1, (mn - 190) / 60));
      data[o + 3] = Math.round(255 * (1 - wht * 0.8));
    }
  }
  return sharp(data, { raw: { width: w, height: h, channels: 4 } }).png().toBuffer();
}

export default function imageVariants() {
  return {
    name: "bosskg-image-variants",
    hooks: {
      "astro:build:done": async ({ dir, logger }) => {
        const out = fileURLToPath(dir);
        let sharp = null;
        try { sharp = (await import("sharp")).default; } catch { logger.warn("sharp not available: copying originals as variants"); }
        const jobs = [];
        const cuts = [];
        for (const folder of FOLDERS) {
          const src = path.join(out, folder);
          let files = [];
          try { files = (await fs.readdir(src)).filter((f) => IMG.test(f)); } catch { continue; }
          for (const f of files) {
            for (const w of WIDTHS) jobs.push({ folder, f, w, from: path.join(src, f) });
            if (folder === "gear" && !NOT_PRODUCT.test(f)) cuts.push({ f, from: path.join(src, f) });
          }
        }
        await Promise.all([
          ...WIDTHS.flatMap((w) => FOLDERS.map((folder) => fs.mkdir(path.join(out, "img", String(w), folder), { recursive: true }))),
          ...CUT_WIDTHS.map((w) => fs.mkdir(path.join(out, "img", "cut", String(w), "gear"), { recursive: true })),
        ]);
        let made = 0, copied = 0, i = 0;
        const worker = async () => {
          while (i < jobs.length) {
            const j = jobs[i++];
            const to = path.join(out, "img", String(j.w), j.folder, j.f.replace(IMG, ".webp"));
            try {
              if (!sharp) throw new Error("no sharp");
              await sharp(j.from).resize({ width: j.w, withoutEnlargement: true }).webp({ quality: 74 }).toFile(to);
              made++;
            } catch {
              await fs.copyFile(j.from, to);
              copied++;
            }
          }
        };
        await Promise.all(Array.from({ length: 6 }, worker));
        let cutMade = 0;
        for (const c of cuts) {
          let png = null;
          try { if (sharp) png = await cutout(sharp, c.from); } catch { png = null; }
          for (const w of CUT_WIDTHS) {
            const to = path.join(out, "img", "cut", String(w), "gear", c.f.replace(IMG, ".webp"));
            try {
              if (!png) throw new Error("no cutout");
              await sharp(png).resize({ width: w, withoutEnlargement: true }).webp({ quality: 80, alphaQuality: 90 }).toFile(to);
              cutMade++;
            } catch {
              await fs.copyFile(c.from, to);
              copied++;
            }
          }
        }
        logger.info(`image variants: ${made} WebP written, ${cutMade} product cut-outs, ${copied} copied as fallback`);

        // The /videos/ feature still (the page's LCP image): fetched once from YouTube at build time
        // and served same-origin as WebP, so a phone does not open a third-party connection first.
        // On any failure nothing is written and the page's onerror falls back to the YouTube URL.
        try {
          const data = JSON.parse(await fs.readFile(path.join(process.cwd(), "src", "data", "videos.json"), "utf8"));
          const id = data.longform && data.longform[0] && data.longform[0].id;
          if (id && sharp && /^[\w-]{6,20}$/.test(id)) {
            const r = await fetch(`https://i.ytimg.com/vi/${id}/hq720.jpg`, { signal: AbortSignal.timeout(15000) });
            if (!r.ok) throw new Error("status " + r.status);
            const buf = Buffer.from(await r.arrayBuffer());
            await fs.mkdir(path.join(out, "img", "yt"), { recursive: true });
            for (const w of [480, 800, 1280]) {
              await sharp(buf).resize({ width: w, withoutEnlargement: true }).webp({ quality: 76 }).toFile(path.join(out, "img", "yt", `${id}-${w}.webp`));
            }
            logger.info(`video feature still: /img/yt/${id}-{480,800,1280}.webp`);
          }
        } catch (e) {
          logger.warn(`video feature still not cached (${String(e).slice(0, 80)}): /videos/ uses the YouTube URL`);
        }
      },
    },
  };
}
