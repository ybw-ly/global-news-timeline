@echo off
chcp 65001 >nul
set MODEL=qwen3-vl:8b
echo Warming up %MODEL% and keeping it loaded for 30 minutes...
ollama run %MODEL% "warmup" --keepalive 30m
echo.
ollama ps
echo.
echo Done. Model should be listed above with a 30 minute keep-alive.
pause
