// Follower/subscriber counts for the home "Follow the action" strip.
// Refreshed by tools/social_stats.py (see .github/workflows/social-stats.yml) into
// ../data/socials.json. `display` is the humanized string ("1.2K"); null when we've
// never gotten a real number for that platform (the card then hides the stat).
import data from "../data/socials.json";

export const socials = data;

export function followers(key) {
  const d = data && data[key];
  return d && d.display ? d.display : null;
}
