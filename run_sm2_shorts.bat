@echo off
REM Spider-Man 2 YouTube Shorts: render + schedule 12 Shorts (private + publishAt, 2/day
REM from today) incl. the full vertical-bleed FILL format. Detached so it survives the
REM Claude session exiting. 4K HDR NVENC renders (GPU, no bandwidth) + small uploads.
REM Resumable: the spider-man2 shorts ledger skips already-scheduled ones on a re-run.
cd /d "Z:\Video Production Files\Kiwinoy Gaming\kiwinoy-social-posting"
echo ==== SM2 Shorts started %DATE% %TIME% ==== >> "output\.sm2_shorts.log"
python process_sm2_shorts.py >> "output\.sm2_shorts.log" 2>&1
echo ==== SM2 Shorts ENDED   %DATE% %TIME% ==== >> "output\.sm2_shorts.log"
