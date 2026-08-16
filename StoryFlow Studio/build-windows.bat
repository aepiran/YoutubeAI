@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1" %*
set "STORYFLOW_EXIT=%ERRORLEVEL%"
if not "%STORYFLOW_EXIT%"=="0" pause
exit /b %STORYFLOW_EXIT%
