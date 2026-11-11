// Build step: write small WebP copies of every cover and game-art image so cards and the
// home lead do not download the full 1200px JPG on a phone. Runs after `astro build`
// (before pagefind) and only reads files already copied into dist/, so public/covers,
// which the cover bot writes, is never touched.
//
// Output: dist/img/<width>/<folder>/<name>.webp for widths 480, 800 and 1200.
// If sharp cannot load or an image fails, the original file is copied to the variant
// path instead (browsers sniff image formats), so no srcset entry ever 404s.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WIDTHS = [480, 800, 1200];
const FOLDERS = ["covers", "game-art"];
const IMG = /\.(jpe?g|png|webp)$/i;

export default function imageVariants() {
  return {
    name: "bosskg-image-variants",
    hooks: {
      "astro:build:done": async ({ dir, logger }) => {
        const out = fileURLToPath(dir);
        let sharp = null;
        try { sharp = (await import("sharp")).default; } catch { logger.warn("sharp not available: copying originals as variants"); }
        const jobs = [];
        for (const folder of FOLDERS) {
          const src = path.join(out, folder);
          let files = [];
          try { files = (await fs.readdir(src)).filter((f) => IMG.test(f)); } catch { continue; }
          for (const f of files) for (const w of WIDTHS) jobs.push({ folder, f, w, from: path.join(src, f) });
        }
        await Promise.all(WIDTHS.flatMap((w) => FOLDERS.map((folder) => fs.mkdir(path.join(out, "img", String(w), folder), { recursive: true }))));
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
        logger.info(`image variants: ${made} WebP written, ${copied} copied as fallback`);
      },
    },
  };
}
