@echo off
if not defined EFINITY_HOME set "EFINITY_HOME=D:\Efinity"
if not exist "%EFINITY_HOME%\bin\setup.bat" (
 echo Efinity not found: %EFINITY_HOME% 1>&2
 exit /b 1
)
call "%EFINITY_HOME%\bin\setup.bat"
exit /b %errorlevel%
