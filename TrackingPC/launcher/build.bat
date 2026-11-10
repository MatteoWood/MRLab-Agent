@echo off
rem Builds ..\MRLabHub.exe from MRLabHub.cs with the C# compiler that comes with Windows (.NET Framework 4).
rem MRLabHub.ico: the hub's icon (16 to 256 px, from the owner's design; hub\icon.png is the window's copy).
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize /out:"%~dp0..\MRLabHub.exe" /win32icon:"%~dp0MRLabHub.ico" /reference:System.Windows.Forms.dll "%~dp0MRLabHub.cs"
