@echo off
REM FF7R HDR RE-UPLOAD launcher (arg %1 = part group 1|2|3). Prepends rclone + ffmpeg
REM (user-local AppData) + Python to PATH so the job is self-contained when launched
REM detached / from a scheduled task (which don't inherit the interactive PATH).
cd /d "Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting"
set "PATH=C:\Users\Bryce Tantia\AppData\Local\rclone;C:\Users\Bryce Tantia\AppData\Local\Microsoft\WinGet\Links;C:\Python313;%PATH%"
echo ==== FF7R Part %1 HDR RE-UPLOAD started %DATE% %TIME% ==== >> "output\.ff7_hdr_p%1.log"
"C:\Python313\python.exe" ff7_hdr_reupload.py %1 >> "output\.ff7_hdr_p%1.log" 2>&1
echo ==== FF7R Part %1 HDR RE-UPLOAD ended   %DATE% %TIME% (exit %ERRORLEVEL%) ==== >> "output\.ff7_hdr_p%1.log"
