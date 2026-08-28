@echo off
:: Quick launcher — just runs the already-built exe from the correct location.
:: If not built yet, run BUILD_AND_RUN.bat first.

set EXE="%~dp0dist\GameBeats\GameBeats.exe"

if not exist %EXE% (
    echo GameBeats has not been built yet.
    echo Please run BUILD_AND_RUN.bat first.
    echo.
    pause
    exit /b 1
)

start "" %EXE%
