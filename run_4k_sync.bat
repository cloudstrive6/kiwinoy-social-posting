@echo off
REM ============================================================================
REM  4K/60 HDR source auto-archive. Point a Windows Task Scheduler job at this
REM  (e.g. every 30 min): it uploads any new files pasted into
REM  reels\assets\4k-hdr\<game>\ to Backblaze B2, verifies them, then frees local
REM  disk (auto-delete once verified + past the grace window). See the intake
REM  README + config.yaml -> source_4k. Pinned games (a .keep file) are never freed.
REM
REM  Create the schedule (run once, in an elevated cmd if needed):
REM    schtasks /Create /TN "KG 4K source sync" /TR "\"Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting\run_4k_sync.bat\"" /SC MINUTE /MO 30
REM ============================================================================
cd /d "Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting"
echo ==== 4K sync started %DATE% %TIME% ==== >> "output\.archive_4k.log"
python tools\archive_4k.py sync >> "output\.archive_4k.log" 2>&1
echo ==== 4K sync ENDED   %DATE% %TIME% ==== >> "output\.archive_4k.log"
