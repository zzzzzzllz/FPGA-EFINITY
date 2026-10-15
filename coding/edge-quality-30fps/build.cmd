@echo off
setlocal
call "%~dp0..\..\tools\efinity-env.cmd"
if errorlevel 1 exit /b %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\tools\build-project.ps1" -Project "%~dp0."
exit /b %errorlevel%
