@echo off
setlocal
rem Enter task 8 on the loaded program. This does not reload SRAM or the sensor.
call "%~dp0control.cmd" --frame demo-home --samples 1
if errorlevel 1 exit /b %errorlevel%
for /l %%i in (1,1,7) do (
 call "%~dp0control.cmd" --frame demo-next --samples 1
 if errorlevel 1 exit /b 1
)
echo Task 08: KEY2 threshold -4, KEY3 threshold +4. Hold to repeat.
exit /b 0
