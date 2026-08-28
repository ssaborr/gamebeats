@echo off
:: Run this once from the GameBeats_fixed folder to compile spotify_focus_guard.exe
:: Requires MSYS2 MinGW64 installed at C:\msys64

echo Compiling spotify_focus_guard.exe...

set G++=C:\msys64\mingw64\bin\g++.exe

if not exist "%G++%" (
    echo ERROR: g++.exe not found at %G++%
    echo Please install MSYS2 and run: pacman -S mingw-w64-x86_64-gcc
    pause
    exit /b 1
)

set PATH=C:\msys64\mingw64\bin;%PATH%

"%G++%" -o source\core\spotify_focus_guard.exe ^
    source\spotify_focus_guard.cpp ^
    -mwindows ^
    -static -static-libgcc -static-libstdc++

if exist source\core\spotify_focus_guard.exe (
    echo SUCCESS: source\core\spotify_focus_guard.exe created.
    if exist dist\GameBeats (
        copy /Y source\core\spotify_focus_guard.exe dist\GameBeats\spotify_focus_guard.exe >nul
        echo Copied to dist\GameBeats\spotify_focus_guard.exe.
    )
) else (
    echo FAILED: Check errors above.
)
pause
