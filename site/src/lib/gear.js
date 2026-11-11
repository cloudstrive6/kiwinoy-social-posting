// BOSS KG "Gear we use": the affiliate catalogue, shared by /gear/ and the home Gear rail.
// Each item links out through an AFFILIATE link, so a purchase earns BOSS KG a small
// commission at no cost to the buyer. Every outbound link must keep rel="sponsored nofollow noopener".
//
// HOW TO EDIT
//   1) Replace an item's `url` with your affiliate link (Amazon SiteStripe short URL, brand referral link).
//   2) Swap names and notes to match the gear you actually use.
//   3) Delete any row you don't want; add rows freely.
// Until a real link is set, `url: "#"` renders a disabled "Link coming soon" button.
//
// LEGAL: the disclosure on /gear/ is required (FTC and platform rules). Keep it.

export const GEAR = [
  { cat: "Console", name: "PlayStation 5 Pro (2TB)", note: "The main rig. Every 4K/60 HDR playthrough runs here.", retailer: "Amazon", url: "https://amzn.to/4gBrxEo", img: "/gear/console.jpg" },
  { cat: "Controller", name: "DualSense in Chroma Pearl", note: "The everyday PS5 pad: haptics and adaptive triggers.", retailer: "Amazon", url: "https://amzn.to/45SI81t", img: "/gear/controller.jpg" },
  { cat: "Controller", name: "DualSense Edge", note: "The pro pad: back paddles, remappable inputs, tunable sticks.", retailer: "Amazon", url: "https://amzn.to/4qzh8xn", img: "/gear/controller-edge.jpg" },
  { cat: "Capture", name: "Elgato 4K Pro (internal)", note: "Internal PCIe card with 8K60 passthrough. The main capture.", retailer: "Amazon", url: "https://amzn.to/4qEPZcr", img: "/gear/capture-4kpro.jpg" },
  { cat: "Capture", name: "Elgato 4K X", note: "External HDMI 2.1, 4K144 ultra-low-latency capture.", retailer: "Amazon", url: "https://amzn.to/4izZJCG", img: "/gear/capture-4kx.jpg" },
  { cat: "Capture", name: "Elgato Cam Link 4K", note: "Turns a DSLR or camera into a clean facecam feed.", retailer: "Amazon", url: "https://amzn.to/3UhsqdS", img: "/gear/capture-camlink.jpg" },
  { cat: "Audio", name: "SteelSeries Arctis Nova 7P", note: "Wireless Gen 2: 2.4GHz plus Bluetooth, 50+ hour battery.", retailer: "Amazon", url: "https://amzn.to/4y84KXX", img: "/gear/headset.jpg" },
  { cat: "Display", name: 'LG C5 65" OLED evo 4K', note: "OLED, 4K/120Hz, Dolby Vision. How these games should look.", retailer: "Amazon", url: "https://amzn.to/4xp7lNc", img: "/gear/display.jpg" },
  { cat: "Storage", name: "WD_BLACK SN850P 4TB (PS5)", note: "Officially licensed PS5 expansion, up to 7,300MB/s, heatsink.", retailer: "Amazon", url: "https://amzn.to/4izZTdg", img: "/gear/storage.jpg" },
  { cat: "Fuel", name: "DUBBY Energy", note: "Jitterless clean energy. Use code BOSSKG for 10% off.", retailer: "Dubby", url: "https://www.dubby.gg/discount/BossKG?ref=ohipluqb", img: "/gear/dubby.jpg", code: "BOSSKG" },
  { cat: "Fuel", name: "GFUEL Energy", note: "The grind fuel. Code and link coming once approved.", retailer: "GFUEL", url: "#" },
];

// Partner offers (referral links). Shown on /gear/ and, one at a time, on the home page.
export const PARTNERS = {
  luxdrop: {
    name: "LuxDrop",
    label: "Partner, 18+",
    sub: "Spin the wheel for a free welcome bonus on sign-up: PS5s, skins and tech to win.",
    cta: "Claim the welcome bonus",
    url: "https://luxdrop.com/r/bosskg",
    img: "/gear/luxdrop-ps5.jpg",
  },
  trybe: {
    name: "Trybe",
    label: "Partner, for creators",
    sub: "The platform I use to land paid brand and UGC deals.",
    cta: "Join free",
    url: "https://jointrybe.com/r/HAGTVAG9",
  },
};
