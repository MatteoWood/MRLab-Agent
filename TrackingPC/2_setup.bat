@echo off
rem Step 2 (README.md): downloads Python, its packages, Ollama and the vision model into .\runtime.
call "%~dp0env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tracking_pc.ps1" setup
pause
