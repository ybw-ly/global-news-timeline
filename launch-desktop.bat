@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 1; if ($r.ok -eq $true -and $r.version) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  start "Meridian News Timeline" /d "%~dp0" /min cmd /c "python server\app.py"
)

powershell -NoProfile -Command "for ($i = 0; $i -lt 40; $i++) { try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 1; if ($r.ok -eq $true -and $r.version) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo.
  echo Service failed to start. Double-click run.bat to see the full error.
  pause
  exit /b 1
)

if /I "%MERIDIAN_NO_BROWSER%"=="1" exit /b 0
start "" "http://127.0.0.1:8765"
exit /b 0
