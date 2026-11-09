@echo off
rem Step 1 (README.md): read-only report about this PC.
call "%~dp0env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tracking_pc.ps1" check
pause
