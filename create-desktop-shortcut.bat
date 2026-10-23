@echo off
setlocal
set "PROJECT_DIR=%~dp0"
powershell -NoProfile -Command "$project=$env:PROJECT_DIR.TrimEnd('\'); $desktop=[Environment]::GetFolderPath('Desktop'); $name=([char]0x7ECF)+([char]0x7EAC)+' Global News Timeline'; $shell=New-Object -ComObject WScript.Shell; $path=Join-Path $desktop ($name+'.lnk'); $sc=$shell.CreateShortcut($path); $sc.TargetPath=Join-Path $project 'launch-desktop.bat'; $sc.WorkingDirectory=$project; $sc.IconLocation=(Join-Path $project 'web\meridian.ico')+',0'; $sc.Description='Meridian Global News Timeline'; $sc.WindowStyle=7; $sc.Save(); Write-Output $path"
if errorlevel 1 (
  echo Failed to create the desktop shortcut.
  pause
  exit /b 1
)
echo Desktop shortcut created.
endlocal
