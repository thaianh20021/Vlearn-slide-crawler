@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
set "exitCode=%errorlevel%"
if not "%exitCode%"=="0" pause
exit /b %exitCode%
