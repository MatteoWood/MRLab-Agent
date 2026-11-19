@echo off
rem Double-click (LED wall PC): brings this project folder to the newest version from GitHub (README 4.1).
rem   update.bat c2f6a54   brings it to a given version instead.
rem Tools\update.py does the work with the engine's Python; no Git or Git LFS needed. It never writes the
rem locked NDC_Basic files, Saved, Plugins\MoversePlugin or CLAUDE.md, and keeps a copy of every file it replaces.
rem Everything is in one block, which Windows reads whole before running it: the update may replace this
rem file itself while it runs.
(
  echo Close Unreal first ^(the editor and the nDisplay window^): its files cannot be replaced while it runs.
  echo Press a key to update, or close this window to stop.
  pause >nul
  if not exist "%~dp0Tools\update.py" curl -fsSL --create-dirs -o "%~dp0Tools\update.py" https://raw.githubusercontent.com/MatteoWood/MRLab-Agent/main/Tools/update.py
  "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" -I "%~dp0Tools\update.py" %*
  echo.
  pause
  exit /b
)
