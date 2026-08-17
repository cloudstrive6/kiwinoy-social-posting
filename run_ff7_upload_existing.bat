@echo off
REM Upload an ALREADY-ENCODED FF7R part (arg %1 = 1|2|3) — no re-encode. PATH-safe + detached.
cd /d "Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting"
set "PATH=C:\Users\Bryce Tantia\AppData\Local\rclone;C:\Users\Bryce Tantia\AppData\Local\Microsoft\WinGet\Links;C:\Python313;%PATH%"
echo ==== FF7R Part %1 UPLOAD-EXISTING started %DATE% %TIME% ==== >> "output\.ff7_uploadonly_p%1.log"
"C:\Python313\python.exe" ff7_upload_existing.py %1 >> "output\.ff7_uploadonly_p%1.log" 2>&1
echo ==== FF7R Part %1 UPLOAD-EXISTING ended   %DATE% %TIME% (exit %ERRORLEVEL%) ==== >> "output\.ff7_uploadonly_p%1.log"
