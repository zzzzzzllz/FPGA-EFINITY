@echo off
setlocal
call "%~dp0..\..\tools\efinity-env.cmd"
if errorlevel 1 exit /b %errorlevel%
set "PYTHONDONTWRITEBYTECODE=1"
set "QT_PLUGIN_PATH=%EFINITY_HOME%/python311"
"%EFINITY_HOME%\python311\bin\python.exe" -X utf8 "%~dp0control.py" %*
exit /b %errorlevel%
