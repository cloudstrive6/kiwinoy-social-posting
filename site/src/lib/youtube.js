// Pulls the Boss KG channel's latest uploads from YouTube's PUBLIC Atom feed at build
// time — no API key, no auth. Fails open (returns []) so a YouTube hiccup never breaks
// the build. The site rebuilds on a schedule (see deploy-site.yml) to stay fresh.

export const CHANNEL_ID = "UCeHnkTv_uA_dUgryYUPa-Dg";
export const CHANNEL_HANDLE = "Kiwinoy";
export const CHANNEL_URL = "https://www.youtube.com/@Kiwinoy";

function decode(s = "") {
  return s
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&#39;/g, "'").replace(/&quot;/g, '"')
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n));
}

export async function latestVideos(limit = 12) {
  try {
    const res = await fetch(
      `https://www.youtube.com/feeds/videos.xml?channel_id=${CHANNEL_ID}`,
      { headers: { "User-Agent": "BossKG-site/1.0" } }
    );
    if (!res.ok) return [];
    const xml = await res.text();
    const out = [];
    for (const m of xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)) {
      const e = m[1];
      const id = (e.match(/<yt:videoId>(.*?)<\/yt:videoId>/) || [])[1];
      if (!id) continue;
      const title = decode((e.match(/<title>([\s\S]*?)<\/title>/) || [])[1] || "");
      const published = (e.match(/<published>(.*?)<\/published>/) || [])[1] || "";
      out.push({
        id, title, published,
        url: `https://www.youtube.com/watch?v=${id}`,
        thumb: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
      });
      if (out.length >= limit) break;
    }
    return out;
  } catch {
    return [];
  }
}
