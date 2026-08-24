@echo off
REM Verify the spike works locally before involving ChatGPT.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python probe.py %*
