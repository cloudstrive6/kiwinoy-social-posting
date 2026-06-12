@echo off
setlocal enabledelayedexpansion

rem ============================================================================
rem  KiwinoyGamer - compress gameplay videos (NVIDIA NVENC, with CPU fallback)
rem ----------------------------------------------------------------------------
rem  Drag one or more video files (or a folder) onto this .bat, or run:
rem    compress_videos.bat "C:\clips\game.mp4" [more...]
rem  Output goes to a "compressed" subfolder next to each source video.
rem  QUALITY: lower = better+bigger, higher = smaller (18-28 ok). MAXH = max height.
rem  FPS:     blank = keep source frame rate (60fps stays 60fps). Set to force it.
rem  Tries the GPU encoder first; if the GPU is busy/unavailable it uses the CPU.
rem ============================================================================

set "QUALITY=24"
set "MAXH=1080"
set "FPS="

set "FPSARG="
if defined FPS set "FPSARG=-r %FPS%"

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
del "%OUT%" >nul 2>nul
echo.
echo Compressing "%~nx1" ...
rem --- try the GPU encoder (NVENC) first; hide its errors since we fall back ---
"%FFMPEG%" -hide_banner -loglevel error -y -i "%~1" -vf "scale=-2:min(%MAXH%\,ih)" %FPSARG% -c:v h264_nvenc -preset p5 -rc vbr -cq %QUALITY% -b:v 0 -c:a aac -b:a 128k -movflags +faststart "%OUT%" 2>nul
call :ok "%OUT%" && (
  echo   done ^(GPU^) -^> "%OUT%"
  exit /b 0
)
rem --- GPU failed: use the CPU encoder (libx264) ---
del "%OUT%" >nul 2>nul
echo   GPU encoder unavailable - using CPU ^(libx264, slower but reliable^)...
"%FFMPEG%" -hide_banner -loglevel error -y -i "%~1" -vf "scale=-2:min(%MAXH%\,ih)" %FPSARG% -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart "%OUT%"
call :ok "%OUT%" && (echo   done ^(CPU^) -^> "%OUT%") || (echo   [!] FAILED - see messages above)
exit /b 0

:ok
if not exist "%~1" exit /b 1
for %%A in ("%~1") do if %%~zA LSS 100000 exit /b 1
exit /b 0

:end
echo.
echo All done. Compressed files are in the "compressed" folder next to each source.
pause
