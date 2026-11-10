@echo off
title TranscribePH - Tagalog / English / Taglish Video Transcriber
cd /d "%~dp0"
echo ==============================================================
echo   TranscribePH - High-Accuracy Video Transcriber
echo   Engine: Faster-Whisper (Tagalog, English, Taglish)
echo ==============================================================
echo.
echo Starting web server on http://127.0.0.1:8000 ...
start http://127.0.0.1:8000
python server.py
pause
