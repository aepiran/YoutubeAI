@echo off
setlocal
cd /d "%~dp0"
call "%~dp0build-scripts\build_windows.bat" %*
exit /b %ERRORLEVEL%
