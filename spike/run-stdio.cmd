@echo off
REM stdio transport, for ChatGPT desktop / Codex CLI / Claude Code.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python m0_spike.py stdio %*
