@echo off
REM Streamable HTTP on loopback. Pair with run-tunnel.cmd for ChatGPT web.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python m0_spike.py http --port 18765 %*
