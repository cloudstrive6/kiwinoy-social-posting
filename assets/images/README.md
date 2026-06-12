# Your own photos for designed posts

Drop curated photos here and the system picks a relevant one for the topic and
renders a scroll-stopping, perfectly-spelled on-image headline over it (Bleacher-
Report / SportsCenter style, matching the samples in `samples/sports/`).

## Where to put images

| Folder      | Used for |
|-------------|----------|
| `sports/`   | **Threads** image posts (real curated sports photos — your call, so no "wrong AI player" problem) |
| `mlbb/`     | **Facebook + Instagram** MLBB posts (static + carousel) |
| `dota2/` `cs2/` `lol/` | other esports (FB+IG) |
| `genshin/` `hsr/` `nte/` `ff7/` `re/` `halo/` | games (FB+IG) |
| `general/`  | fallback if a topic has no matching folder |

## Tips
- **Format:** `.jpg` or `.png`. High-resolution, clean subject.
- **Headline space:** leave some room (top or bottom) for the headline. Single
  strong subject works best.
- **Size:** these are small (<1MB typically) and commit straight to the repo, so
  the cloud renderer can use them. No 100MB issue like video.
- **Real people are fine here** because you're curating them — the system just
  reuses your photo, it never invents a face.

## After adding images
Just tell me ("I added MLBB images") and I'll tag + commit them. The agents then
auto-match an image to each topic and design the headline on it in the cloud.
