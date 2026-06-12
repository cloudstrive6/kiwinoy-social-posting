@echo off
setlocal enabledelayedexpansion

rem ============================================================================
rem  KiwinoyGamer - compress gameplay videos with NVIDIA NVENC (GPU, fast)
rem ----------------------------------------------------------------------------
rem  Drag one or more video files (or a folder) onto this .bat, or run:
rem    compress_videos.bat "C:\clips\game.mp4" [more...]
rem  Output goes to a "compressed" subfolder next to each source video.
rem  QUALITY: lower = better+bigger, higher = smaller (18-28 ok). MAXH = max height.
rem ============================================================================

set "QUALITY=24"
set "MAXH=1080"

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
  echo Drag video files onto this .bat, or pass files / a folder as arguments.
  pause
  exit /b 0
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
if errorlevel 1 (echo   [!] FAILED ^(see message above^)) else (echo   done -^> "%OUT%")
exit /b 0

:end
echo.
echo All done. Compressed files are in the "compressed" folder next to each source.
pause
