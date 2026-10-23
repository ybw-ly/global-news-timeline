@echo off
chcp 65001 >nul
echo Stopping all loaded Ollama models (service stays running)...
for /f "skip=1 tokens=1" %%m in ('ollama ps') do (
  if not "%%m"=="" (
    echo   ollama stop %%m
    ollama stop %%m
  )
)
echo.
ollama ps
echo.
echo Done. Ollama service is still running; models will reload on the next request.
pause
