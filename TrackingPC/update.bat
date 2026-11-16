@echo off
rem Double-click: brings the code in this folder to the newest version from GitHub (GUIDE.md, section 1).
rem   update.bat b09109f   brings it to a given version instead.
rem Changes files only inside this folder: tools\update.py checks every path before writing, and the
rem programs started here get their home, AppData and temp folders inside .\runtime (env.bat).
rem Everything is in one block, which Windows reads whole before running it: the update may replace this
rem file itself while it runs.
(
  call "%~dp0env.bat"
  set "PYTHONDONTWRITEBYTECODE=1"
  echo Close MRLabHub first: its files cannot be replaced while it runs.
  echo Press a key to update, or close this window to stop.
  pause >nul
  if not exist "%~dp0tools\update.py" curl -sSL --create-dirs -o "%~dp0tools\update.py" https://raw.githubusercontent.com/MatteoWood/MRLab-Agent/main/TrackingPC/tools/update.py
  "%~dp0runtime\python\python.exe" "%~dp0tools\update.py" %*
  echo.
  pause
  exit /b
)
