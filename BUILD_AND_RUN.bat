@echo off
title GameBeats - Build

echo ============================================
echo  GameBeats Build Script
echo ============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.9+ and add it to PATH.
    pause
    exit /b 1
)

:: Install/upgrade dependencies
echo [1/3] Installing dependencies...
cd /d "%~dp0source"
py -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

:: Build the C++ Spotify focus guard when MSYS2 MinGW64 is available.
set MINGW_BIN=C:\msys64\mingw64\bin
set GPP=%MINGW_BIN%\g++.exe
if exist "%GPP%" (
    echo Compiling spotify_focus_guard.exe...
    set "PATH=%MINGW_BIN%;%PATH%"
    "%GPP%" -o core\spotify_focus_guard.exe spotify_focus_guard.cpp -mwindows -static -static-libgcc -static-libstdc++
    if errorlevel 1 (
        echo WARNING: focus guard compile failed. Existing helper will be used if present.
    )
) else (
    echo WARNING: MSYS2 g++.exe not found; skipping focus guard compile.
)

:: Preserve runtime data because PyInstaller recreates dist\GameBeats.
set DATA_DIR=%~dp0dist\GameBeats\data
set DATA_BACKUP=%TEMP%\GameBeats_data_%RANDOM%%RANDOM%
if exist "%DATA_DIR%" (
    mkdir "%DATA_BACKUP%" >nul 2>&1
    xcopy "%DATA_DIR%\*" "%DATA_BACKUP%\" /E /I /Y >nul
)

:: Build with PyInstaller - output goes to dist\GameBeats\
echo.
echo [2/3] Building GameBeats.exe...
py -m PyInstaller --noconfirm --onedir --windowed --name GameBeats ^
    --collect-binaries process_audio_capture ^
    --add-binary "core\spotify_focus_guard.exe;." ^
    --add-data "..\assets;assets" ^
    --distpath "..\dist" ^
    --workpath "..\build_tmp" ^
    main.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed. See output above.
    pause
    exit /b 1
)

if exist "%DATA_BACKUP%" (
    mkdir "%DATA_DIR%" >nul 2>&1
    xcopy "%DATA_BACKUP%\*" "%DATA_DIR%\" /E /I /Y >nul
    rmdir /s /q "%DATA_BACKUP%" >nul 2>&1
)

if exist "%~dp0source\core\spotify_focus_guard.exe" (
    copy /Y "%~dp0source\core\spotify_focus_guard.exe" "%~dp0dist\GameBeats\spotify_focus_guard.exe" >nul
)

if exist "%~dp0assets" (
    xcopy "%~dp0assets\*" "%~dp0dist\GameBeats\assets\" /E /I /Y >nul
)

:: Launch from the correct location (dist\GameBeats\)
echo.
echo [3/3] Launching GameBeats...
set EXE="%~dp0dist\GameBeats\GameBeats.exe"
if not exist %EXE% (
    echo ERROR: Built exe not found at %EXE%
    pause
    exit /b 1
)

start "" %EXE%

echo.
echo Done! GameBeats launched from dist\GameBeats\GameBeats.exe
echo.
echo NOTE: Always run GameBeats from  dist\GameBeats\GameBeats.exe
echo       NOT from build_tmp\ or source\build\  (those are broken intermediate files)
echo.
pause
