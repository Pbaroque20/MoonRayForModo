@echo off
rem Compile XPU2's GPU shaders without opening Modo: the same as Compile XPU2 Shaders in
rem System > Preferences > MoonRay > XPU2, into the same shader cache, so Modo finds them compiled.
rem Double-click it, or run it from a command prompt. Closing Modo first leaves it more memory.
setlocal
cd /d "%~dp0runtime-xpu2" || goto missing
if not exist moonray_xpu2.exe goto missing
echo MoonRay for Modo: compiling XPU2 shaders. This takes about 15 minutes, or about 30 when
echo memory is short and it compiles one part at a time. Leave this window open until it says it is done.
echo.
moonray_xpu2.exe --compile-shaders
set result=%errorlevel%
echo.
if "%result%"=="0" (
  echo Done. XPU2's shaders are compiled; Modo will use them the next time it renders with XPU2.
) else if "%result%"=="3" (
  echo Not compiled: not enough free memory. Close other programs, Modo included, and run this again.
) else if "%result%"=="4" (
  echo Stopped: memory ran low. The parts already compiled are kept. Close other programs and run this again.
) else (
  echo Not compiled ^(error %result%^). See the lines above.
)
echo.
pause
exit /b %result%
:missing
echo This script belongs in the MoonRayForModo kit folder, beside runtime-xpu2, which was not found.
pause
exit /b 1
