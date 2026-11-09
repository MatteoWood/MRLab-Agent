@echo off
rem Builds ..\MRLabHub.exe from MRLabHub.cs with the C# compiler that comes with Windows (.NET Framework 4).
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize /out:"%~dp0..\MRLabHub.exe" /reference:System.Windows.Forms.dll "%~dp0MRLabHub.cs"
