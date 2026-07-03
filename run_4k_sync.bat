@echo off
REM ============================================================================
REM  "Paste and forget" cloud sync for ALL pasted footage. Point a Windows Task
REM  Scheduler job at this (e.g. every 30 min). Two clouds, both delete-local:
REM
REM   1) tools\footage.py sync  -> GitHub footage RELEASE (the 1080p FEED clips,
REM      incl. the fill pool reels\assets\footage\<game>-vertical\). CI reads these.
REM   2) tools\archive_4k.py sync -> Backblaze B2 (the 4K HDR source reels\assets\
REM      4k-hdr\<game>\ AND the YouTube fill pool reels\assets\footage-4k\<game>-vertical\).
REM
REM  Each verified upload frees its local copy (B2 side respects source_4k.free_after_hours
REM  + .keep pins). Create the schedule (run once):
REM    schtasks /Create /TN "KG cloud sync" /TR "\"Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting\run_4k_sync.bat\"" /SC MINUTE /MO 30
REM ============================================================================
cd /d "Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting"
echo ==== cloud sync started %DATE% %TIME% ==== >> "output\.archive_4k.log"
python tools\footage.py sync   >> "output\.archive_4k.log" 2>&1
python tools\archive_4k.py sync >> "output\.archive_4k.log" 2>&1
echo ==== cloud sync ENDED   %DATE% %TIME% ==== >> "output\.archive_4k.log"
