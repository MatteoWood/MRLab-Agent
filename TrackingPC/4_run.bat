@echo off
rem Step 4 (README.md): starts the vision model and the camera service. Ctrl+C stops both.
rem Moverse must be closed.
call "%~dp0env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tracking_pc.ps1" run
pause
