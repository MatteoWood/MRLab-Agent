@echo off
rem Called by the numbered .bat files. For this window and every program started from it
rem (PowerShell, Python, Ollama): home, AppData and temp folders inside .\runtime, so nothing
rem is written outside this folder. These settings end when the window closes.
set "RT=%~dp0runtime"
for %%d in ("%RT%\home\AppData\Roaming" "%RT%\home\AppData\Local" "%RT%\temp") do if not exist %%d mkdir %%d
set "USERPROFILE=%RT%\home"
set "HOME=%RT%\home"
set "APPDATA=%RT%\home\AppData\Roaming"
set "LOCALAPPDATA=%RT%\home\AppData\Local"
set "TEMP=%RT%\temp"
set "TMP=%RT%\temp"
set "PSModuleAnalysisCachePath=%RT%\temp\ModuleAnalysisCache"
