@echo off
setlocal enabledelayedexpansion

rem ============================================================================
rem  KiwinoyGamer - PREP raw gameplay -> small, reel-ready b-roll clips
rem ----------------------------------------------------------------------------
rem  Drag a GAME FOLDER (e.g. ...\reels\assets\footage\spider-man1) onto this
rem  .bat. Every video inside is compressed to 1080p AND split into ~SEG-second
rem  clips, written to a "_ready" subfolder. Those small clips are what get
rem  uploaded to the cloud (Claude uploads the _ready folder to the footage
rem  Release). A 3-minute recording becomes ~7 small clips of ~10-20 MB each.
rem    SEG     = seconds per output clip  (b-roll size)
rem    MAXH    = max height               (1080)
rem    QUALITY = NVENC cq / x264 crf      (higher = smaller file)
rem  Tries the GPU encoder (NVENC) first; falls back to the CPU automatically.
rem ============================================================================

set "SEG=25"
set "MAXH=1080"
set "QUALITY=26"

rem --- find ffmpeg: PATH, then the winget install location, then C:\ffmpeg ---
set "FFMPEG="
where ffmpeg >nul 2>nul && set "FFMPEG=ffmpeg"
if not defined FFMPEG if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" set "FFMPEG=%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"
if not defined FFMPEG if exist "C:\ffmpeg\bin\ffmpeg.exe" set "FFMPEG=C:\ffmpeg\bin\ffmpeg.exe"
if not defined FFMPEG (
  echo [!] ffmpeg not found. If you just installed it, RESTART YOUR PC once and retry.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo Drag a game FOLDER (or video files) onto this .bat.
  pause
  exit /b 0
)

:argloop
if "%~1"=="" goto :end
if exist "%~1\" (
  for %%F in ("%~1\*.mp4" "%~1\*.mov" "%~1\*.mkv" "%~1\*.avi" "%~1\*.m4v" "%~1\*.ts" "%~1\*.webm") do call :prep "%%~fF" "%~1"
) else (
  call :prep "%~1" "%~dp1"
)
shift
goto :argloop

:prep
rem %1 = source video, %2 = base folder (its "_ready" holds the output clips)
set "BASE=%~2"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"
set "OUTDIR=%BASE%\_ready"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
set "OUT=%OUTDIR%\%~n1_%%03d.mp4"
echo.
echo Prepping "%~nx1" -^> %SEG%s clips ...
rem --- try the GPU encoder (NVENC) first; hide its errors since we fall back ---
"%FFMPEG%" -hide_banner -loglevel error -y -i "%~1" -vf "scale=-2:min(%MAXH%\,ih)" -c:v h264_nvenc -preset p5 -rc vbr -cq %QUALITY% -b:v 0 -c:a aac -b:a 128k -f segment -segment_time %SEG% -reset_timestamps 1 "%OUT%" 2>nul
if exist "%OUTDIR%\%~n1_000.mp4" (
  echo   done ^(GPU^) -^> "%OUTDIR%"
  exit /b 0
)
rem --- GPU failed: use the CPU encoder (libx264) ---
echo   GPU encoder unavailable - using CPU ^(libx264, slower but reliable^)...
"%FFMPEG%" -hide_banner -loglevel error -y -i "%~1" -vf "scale=-2:min(%MAXH%\,ih)" -c:v libx264 -preset veryfast -crf 24 -pix_fmt yuv420p -c:a aac -b:a 128k -f segment -segment_time %SEG% -reset_timestamps 1 "%OUT%"
if exist "%OUTDIR%\%~n1_000.mp4" (echo   done ^(CPU^) -^> "%OUTDIR%") else (echo   [!] FAILED - see messages above)
exit /b 0

:end
echo.
echo All done. The small reel-ready clips are in the "_ready" folder next to your
echo videos. Tell Claude the prep is finished and it will upload them to the cloud.
pause
