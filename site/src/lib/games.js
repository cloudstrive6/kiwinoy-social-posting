// The franchises BOSS KG covers. Drives the Games hub, the per-game pages, and how
// articles + videos get filed. Add a game here and it appears everywhere automatically.
// `art` is a CSS gradient class (global.css) used as the fallback; `cover` is the real
// key-art image under site/public/game-art/ (copied from reels/assets/game-art/).
//
// `exclude` lets a broad game (e.g. base Spider-Man) bow out when a more specific
// title cue is present, so "Spider-Man 2" / "Miles Morales" win over the generic match.

export const GAMES = [
  { slug: "spider-man-1", title: "Marvel's Spider-Man", art: "g-spidey", cover: "/game-art/spider-man-1.webp",
    blurb: "Insomniac's original — Peter Parker's Spider-Man.",
    match: ["mister negative", "martin li", "sinister six", "doctor octopus", "otto octavius",
            "spider-man remastered", "peter parker", "spider-man", "spider man", "spiderman"],
    exclude: ["spider-man 2", "spider man 2", "spider-man2", "spiderman 2", "spiderman2",
              "miles morales", "symbiote", "venom", "kraven", "sandman", "lizard", "harry", "anti-venom"] },
  { slug: "spider-man-miles", title: "Marvel's Spider-Man: Miles Morales", art: "g-spidey", cover: "/game-art/spider-man-miles.jpg",
    blurb: "Miles Morales steps up as Harlem's Spider-Man.",
    match: ["miles morales"] },
  { slug: "spider-man-2", title: "Marvel's Spider-Man 2", art: "g-spidey", cover: "/game-art/spider-man-2.webp",
    blurb: "Peter and Miles vs. Venom and the symbiote invasion.",
    match: ["spider-man 2", "spider man 2", "spider-man2", "spiderman 2", "spiderman2",
            "symbiote", "venom", "kraven", "sandman", "lizard", "harry osborn", "harry", "anti-venom"] },
  { slug: "wolverine", title: "Marvel's Wolverine", art: "g-wolv", cover: "/game-art/wolverine.jpg",
    blurb: "Insomniac's brutal, first solo Wolverine game.",
    match: ["wolverine", "logan", "x-men", "weapon x"] },
  { slug: "final-fantasy-7", title: "Final Fantasy VII Remake", art: "g-marvel", cover: "/game-art/final-fantasy-7.jpg",
    blurb: "Cloud, Aerith, Tifa and the Remake saga in 4K HDR.",
    match: ["final fantasy vii", "final fantasy 7", "ffvii", "ff7", "cloud strife", "midgar"] },
  { slug: "halo", title: "Halo", art: "g-ps", cover: "/game-art/halo.jpg",
    blurb: "Master Chief and the fight for humanity.",
    match: ["halo", "master chief", "campaign evolved", "spartan", "covenant"] },
];

const norm = (s) => (s || "").toLowerCase();

// Best-matching game slug for a piece of text (video title, article game/category), or null.
// A game with an `exclude` cue present bows out, so more-specific franchises win.
export function gameForText(...parts) {
  const t = norm(parts.filter(Boolean).join(" "));
  for (const g of GAMES) {
    if (g.exclude && g.exclude.some((k) => t.includes(k))) continue;
    if (g.slug === t) return g.slug;
    if (g.match.some((k) => t.includes(k))) return g.slug;
  }
  return null;
}

export const gameBySlug = (slug) => GAMES.find((g) => g.slug === slug) || null;
