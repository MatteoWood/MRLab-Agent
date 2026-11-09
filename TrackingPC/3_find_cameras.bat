@echo off
rem Step 3 (README.md): lists the OAK cameras and shows one picture of each.
rem Moverse must be closed. Camera addresses can be given if the search finds none:
rem   3_find_cameras.bat <address> <address> ...
call "%~dp0env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tracking_pc.ps1" cameras %*
pause
