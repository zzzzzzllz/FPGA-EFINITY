@echo off
setlocal
set "PYTHONDONTWRITEBYTECODE=1"
"D:\Python\python.exe" -B "%~dp0tests\test_camera.py" %*
exit /b %errorlevel%
