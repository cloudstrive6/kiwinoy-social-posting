// Structured data helpers (JSON-LD). Author and publisher are always the brand, never a person.
export const SITE = "https://bosskg.com";
export const abs = (p) => new URL(p, SITE).href;

export const ORG = {
  "@type": "NewsMediaOrganization",
  "@id": `${SITE}/#org`,
  name: "BOSS KG",
  url: `${SITE}/`,
  logo: { "@type": "ImageObject", url: `${SITE}/brand/bosskg-logo-512.png`, width: 512, height: 512 },
  sameAs: [
    "https://www.youtube.com/@Kiwinoy",
    "https://www.tiktok.com/@kiwinoygamer",
    "https://www.instagram.com/kiwinoygaming",
    "https://www.facebook.com/KiwinoyGaming",
  ],
};

export const crumbsLd = (items) => ({
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: items.map((c, i) => ({
    "@type": "ListItem",
    position: i + 1,
    name: c.label,
    ...(c.href ? { item: abs(c.href) } : {}),
  })),
});

// Meta description: 155 characters at most, cut on a word boundary.
export const trimDesc = (s = "", max = 155) => {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  return cut.slice(0, cut.lastIndexOf(" ")).replace(/[,;:.]$/, "") + "…";
};
