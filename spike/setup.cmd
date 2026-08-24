@echo off
REM One-time setup for the M0 spike.
cd /d "%~dp0"
py -3 -m venv .venv || goto :fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :fail
echo.
echo Setup done. Next: selftest.cmd
exit /b 0
:fail
echo Setup FAILED. Is Python 3.11+ installed and on PATH?
exit /b 1
