# Video helpers (Windows + NVIDIA NVENC)

Fast, GPU-accelerated ways to shrink and splice your gameplay videos. Needs
**ffmpeg** installed (download `ffmpeg-release-essentials.zip` from
https://www.gyan.dev/ffmpeg/builds/ and unzip to `C:\ffmpeg`, or add it to PATH).

## Compress (shrink file size) — `compress_videos.bat`
Drag one or more videos (or a folder) onto `compress_videos.bat`. It re-encodes
each with NVENC, downscales to 1080p, and writes results to a `compressed`
subfolder. Edit the top of the file to change:
- `QUALITY` — lower = better/bigger, higher = smaller (18-28 sensible; 24 default)
- `MAXH` — max height in pixels (1080 = 1080p; set 720 for even smaller)

A multi-GB recording typically drops to a few hundred MB with no visible quality
loss for social.

## Splice / trim (cut out the good moments)
The script above only compresses. To grab short clips, two options:

**LosslessCut (fastest, no quality loss):** https://github.com/mifi/lossless-cut
Drag in a long recording, mark in/out points, export segments instantly. Best
for "pull a few 8-15s highlights out of a 30-min recording."

**ffmpeg one-liners** (run in a terminal in the video's folder):

Trim, lossless + instant (cuts at nearest keyframe, ~1s precision):
```
ffmpeg -ss 00:01:30 -i input.mp4 -t 12 -c copy clip.mp4
```

Trim with exact cut + downscale + compress (NVENC):
```
ffmpeg -ss 00:01:30 -i input.mp4 -t 12 -vf "scale=-2:min(1080\,ih)" -c:v h264_nvenc -preset p5 -rc vbr -cq 24 -b:v 0 -c:a aac -b:a 128k out.mp4
```
(`-ss` = start time, `-t` = duration in seconds.)

## After you have clips
- Reels footage (any size): drop into `reels/assets/footage/<game>/`. Small clips
  (<100MB) get committed; bigger ones go on the Release via `tools/footage.py`.
- Reels only use ~4s per clip, so short highlights are ideal.

## If Avast flags ffmpeg
Heavy encoding can trip the behavior shield (false positive). If so, add an Avast
exclusion for your `C:\ffmpeg` folder (Avast > Menu > Settings > General >
Exceptions). Don't quarantine system files.
