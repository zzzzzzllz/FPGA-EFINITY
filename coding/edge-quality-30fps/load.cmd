@echo off
setlocal
call "%~dp0..\..\tools\efinity-env.cmd"
if errorlevel 1 exit /b %errorlevel%
"%EFINITY_HOME%\python311\bin\python.exe" -B "%~dp0..\..\tools\verify-project.py" "%~dp0." --runtime
if errorlevel 1 exit /b %errorlevel%
call "%EFINITY_HOME%\pgm\bin\ftdi_pgm.bat" -m jtag "%~dp0release\ti60f225_oob.bit"
if errorlevel 1 exit /b %errorlevel%
call "%~dp0control.cmd" --set 389 256 427 0 0 --algorithm sobel --low-ratio 1/2 --threshold 56 --median off --recognition off --view color --frame live --samples 3
if errorlevel 1 exit /b %errorlevel%
call "%~dp0control.cmd" --sensor-restore "%~dp0config\sensor.json" --samples 3
if errorlevel 1 exit /b %errorlevel%
exit /b 0
