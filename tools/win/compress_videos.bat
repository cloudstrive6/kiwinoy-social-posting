@echo off
setlocal enabledelayedexpansion

rem ============================================================================
rem  KiwinoyGamer - compress gameplay videos with NVIDIA NVENC (GPU, fast)
rem ----------------------------------------------------------------------------
rem  USAGE: drag one or more video files (or a folder) onto this .bat,
rem         or run:  compress_videos.bat "C:\clips\game.mp4" [more...]
rem  Output goes to a "compressed" subfolder next to each source video.
rem
rem  QUALITY: lower = better + bigger, higher = smaller. 18-28 is sensible.
rem  MAXH:    downscale so height is at most this many pixels (1080 = 1080p).
rem ============================================================================

set "QUALITY=24"
set "MAXH=1080"

rem --- locate ffmpeg: PATH first, then C:\ffmpeg\bin\ffmpeg.exe ---
set "FFMPEG=ffmpeg"
where ffmpeg >nul 2>nul || set "FFMPEG=C:\ffmpeg\bin\ffmpeg.exe"
if not exist "%FFMPEG%" if /i "%FFMPEG%"=="C:\ffmpeg\bin\ffmpeg.exe" (
  echo [!] ffmpeg not found. Unzip the gyan.dev build to C:\ffmpeg
  echo     ^(so C:\ffmpeg\bin\ffmpeg.exe exists^), or add ffmpeg to your PATH.
  pause & exit /b 1
)

if "%~1"=="" (
  echo Drag video files onto this .bat, or pass files / a folder as arguments.
  pause & exit /b 0
)

:argloop
if "%~1"=="" goto :end
if exist "%~1\" (
  for %%F in ("%~1\*.mp4" "%~1\*.mov" "%~1\*.mkv" "%~1\*.avi" "%~1\*.m4v" "%~1\*.ts" "%~1\*.webm") do call :enc "%%~fF"
) else (
  call :enc "%~1"
)
shift
goto :argloop

:enc
set "OUTDIR=%~dp1compressed"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
set "OUT=%OUTDIR%\%~n1.mp4"
echo.
echo Compressing "%~nx1" ...
"%FFMPEG%" -hide_banner -loglevel error -y -i "%~1" -vf "scale=-2:min(%MAXH%\,ih)" -c:v h264_nvenc -preset p5 -rc vbr -cq %QUALITY% -b:v 0 -c:a aac -b:a 128k -movflags +faststart "%OUT%"
if errorlevel 1 (echo   [!] FAILED) else (echo   -^> "%OUT%")
exit /b 0

:end
echo.
echo All done. Compressed files are in the "compressed" folder next to each source.
pause
