@echo off
setlocal
title GameBeats - Release Build

echo ============================================
echo  GameBeats Release Build
echo ============================================
echo.

echo [0/4] Cleaning GameBeats AppData for fresh test...
if exist "%APPDATA%\GameBeats" rmdir /s /q "%APPDATA%\GameBeats"
echo.

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher not found. Install Python 3.10+ and try again.
    exit /b 1
)

echo [1/4] Installing Python dependencies...
pushd "%~dp0source"
py -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    popd
    echo ERROR: dependency install failed.
    exit /b 1
)

echo.
echo [2/4] Building clean app folder...
popd
if exist "%~dp0dist_release" rmdir /s /q "%~dp0dist_release"
if exist "%~dp0build_release" rmdir /s /q "%~dp0build_release"

pushd "%~dp0source"
py -m pip install nuitka
py -m nuitka ^
    --standalone ^
    --windows-console-mode=disable ^
    --enable-plugin=tk-inter ^
    --windows-icon-from-ico=..\assets\icon.ico ^
    --include-data-dir=..\assets=assets ^
    --include-data-file=core\spotify_focus_guard.exe=core\spotify_focus_guard.exe ^
    --include-package-data=playwright ^
    --include-package=process_audio_capture ^
    --include-data-files=%APPDATA%\Python\Python313\site-packages\process_audio_capture\ProcessAudioCapture.dll=process_audio_capture\ProcessAudioCapture.dll ^
    --include-package=core ^
    --output-dir=..\dist_release ^
    --output-filename=GameBeats.exe ^
    --assume-yes-for-downloads ^
    main.py
set BUILD_ERR=%ERRORLEVEL%
popd

if not "%BUILD_ERR%"=="0" (
    echo ERROR: Nuitka build failed.
    exit /b %BUILD_ERR%
)

if exist "%~dp0dist_release\GameBeats" rmdir /s /q "%~dp0dist_release\GameBeats"
if exist "%~dp0dist_release\main.dist" rename "%~dp0dist_release\main.dist" GameBeats

if not exist "%~dp0dist_release\GameBeats\GameBeats.exe" (
    echo ERROR: release exe was not created.
    exit /b 1
)

echo.
echo [3/4] Removing local runtime data from release folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%~dp0dist_release\GameBeats\data','%~dp0dist_release\GameBeats\spotify_web_profile','%~dp0dist_release\GameBeats\spotify_chrome_player_profile' -Recurse -Force -ErrorAction SilentlyContinue"

echo.
echo [4/4] Creating installer when Inno Setup is available...
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not "%ISCC%"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%~dp0dist_release\GameBeats\data','%~dp0dist_release\GameBeats\spotify_web_profile','%~dp0dist_release\GameBeats\spotify_chrome_player_profile' -Recurse -Force -ErrorAction SilentlyContinue"
    "%ISCC%" "%~dp0installer\GameBeats.iss"
    if errorlevel 1 exit /b 1
) else (
    echo Inno Setup not found. Run this after installing Inno Setup:
    echo "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%~dp0installer\GameBeats.iss"
)

echo.
echo Release folder: %~dp0dist_release\GameBeats
if exist "%~dp0installer_output\GameBeatsSetup.exe" echo Installer: %~dp0installer_output\GameBeatsSetup.exe
echo Done.
