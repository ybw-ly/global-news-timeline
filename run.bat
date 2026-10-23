@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ was not found on PATH.
  echo Install Python from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)
python server\app.py
pause
