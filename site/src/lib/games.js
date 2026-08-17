// The franchises BOSS KG covers. Drives the Games hub, the per-game pages, and how
// articles + videos get filed. Add a game here and it appears everywhere automatically.
// `art` is a CSS gradient class from global.css (placeholder art until a cover is set).

export const GAMES = [
  { slug: "spider-man", title: "Marvel's Spider-Man", art: "g-spidey",
    blurb: "Insomniac's Spider-Man — Peter, Miles and Spider-Man 2.",
    match: ["spider-man", "spider man", "spiderman", "miles morales", "peter parker", "symbiote", "venom"] },
  { slug: "wolverine", title: "Marvel's Wolverine", art: "g-wolv",
    blurb: "Insomniac's brutal, first solo Wolverine game.",
    match: ["wolverine", "logan", "x-men", "weapon x"] },
  { slug: "final-fantasy-7", title: "Final Fantasy VII Remake", art: "g-marvel",
    blurb: "Cloud, Aerith, Tifa and the Remake saga in 4K HDR.",
    match: ["final fantasy vii", "final fantasy 7", "ffvii", "ff7", "cloud strife", "midgar"] },
  { slug: "halo", title: "Halo", art: "g-ps",
    blurb: "Master Chief and the fight for humanity.",
    match: ["halo", "master chief", "campaign evolved", "spartan", "covenant"] },
];

const norm = (s) => (s || "").toLowerCase();

// Best-matching game slug for a piece of text (video title, article game/category), or null.
export function gameForText(...parts) {
  const t = norm(parts.filter(Boolean).join(" "));
  for (const g of GAMES) {
    if (g.slug === norm(t)) return g.slug;
    if (g.match.some((k) => t.includes(k))) return g.slug;
  }
  return null;
}

export const gameBySlug = (slug) => GAMES.find((g) => g.slug === slug) || null;
