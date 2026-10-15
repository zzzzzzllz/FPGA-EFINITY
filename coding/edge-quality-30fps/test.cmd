@echo off
setlocal
set "PYTHONDONTWRITEBYTECODE=1"
if "%~1"=="" (
 "D:\Python\python.exe" -B "%~dp0tests\regression.py" small
) else (
 "D:\Python\python.exe" -B "%~dp0tests\regression.py" %*
)
exit /b %errorlevel%
