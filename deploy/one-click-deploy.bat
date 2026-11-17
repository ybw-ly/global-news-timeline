@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."
set "PYTHONIOENCODING=utf-8"

set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo.
    echo Python 3.10+ was not found on PATH.
    echo Install it from https://www.python.org/downloads/ and try again.
    echo.
    pause
    exit /b 1
  )
  set "PY=py -3"
)

echo Starting Global News Timeline on http://127.0.0.1:8765 ...
start "Meridian News Timeline" /d "%CD%" /min cmd /c "%PY% server\app.py"

powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{$r=Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 1;if($r.ok){exit 0}}catch{};Start-Sleep -Milliseconds 500};exit 1"
if errorlevel 1 (
  echo.
  echo Service failed to start. Run run.bat to see the full error.
  echo.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:8765"
echo.
echo Global News Timeline is running at http://127.0.0.1:8765
echo Close the minimized "Meridian News Timeline" window to stop it.
echo.
timeout /t 4 >nul
endlocal
