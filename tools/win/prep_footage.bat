@echo off
setlocal
rem ============================================================================
rem  KiwinoyGamer - PREP raw gameplay -> small, reel-ready b-roll clips
rem ----------------------------------------------------------------------------
rem  Drag a GAME FOLDER (e.g. ...\reels\assets\footage\spider-man1) onto this
rem  .bat. Each recording is compressed to 1080p AND split into ~25-second clips
rem  in a "_ready" subfolder. The real work is done by tools\prep_footage.py
rem  (Python handles spaces/parentheses in filenames reliably). Needs ffmpeg.
rem ============================================================================

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [x] Python was not found on your PATH.
  echo     Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^)
  echo     and retry, or tell Claude and it can run the prep for you.
  pause
  exit /b 1
)

"%PY%" "%~dp0..\prep_footage.py" %*

echo.
pause
