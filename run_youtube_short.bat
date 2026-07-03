@echo off
REM ============================================================================
REM  4K/60 HDR YouTube SHORTS track (classic <-> triptych alternating).
REM  LOCAL only: nvenc (RTX GPU) + multi-GB HDR footage can't run in CI, so this
REM  is driven by Windows Task Scheduler on this PC (see README "YouTube Shorts").
REM
REM  Renders ONE Short from reels\assets\footage-4k\<game>\ (fresh clip first) and
REM  uploads it via the YouTube Data API. The layout alternates automatically.
REM
REM  Any extra args are passed through, e.g:
REM    run_youtube_short.bat --dry-run
REM    run_youtube_short.bat --layout triptych
REM    run_youtube_short.bat --privacy unlisted
REM ============================================================================
cd /d "Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting"
echo ==== YT Short started %DATE% %TIME% ==== >> "output\.youtube_short.log"
python run.py --youtube-short %* >> "output\.youtube_short.log" 2>&1
echo ==== YT Short ENDED   %DATE% %TIME% ==== >> "output\.youtube_short.log"
