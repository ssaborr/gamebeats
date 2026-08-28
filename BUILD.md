# Building GameBeats.exe with PyInstaller

## Requirements
```
pip install pyinstaller psutil requests Pillow
```

## One-folder build (recommended — gives you the exact layout below)

Run from the `source/` directory:

```
cd source
pyinstaller --noconfirm --onedir --windowed --name GameBeats \
    --collect-binaries process_audio_capture \
    --add-binary "core/spotify_focus_guard.exe;." \
    --distpath ../dist \
    --workpath ../build_tmp \
    --specpath ../ \
    main.py
```

After build, your **runnable** distribution is at:

```
GameBeats/
  dist/
    GameBeats/             ← THIS is the folder you run GameBeats.exe from
      GameBeats.exe        ← launcher
      _internal/           ← Python runtime + bundled DLLs (PyInstaller ≥6)
  build_tmp/               ← intermediate build artifacts — DO NOT run the .exe here!
  data/                    ← auto-created at first run (config.json, tokens.json, games.json)
  assets/                  ← drop icon.ico here
```

> ⚠️  **IMPORTANT:** Always run `GameBeats.exe` from `dist/GameBeats/`, **never** from
> `build_tmp/` or any intermediate folder.  The `build_tmp/` directory contains
> partial build artefacts and is missing the `_internal/python3xx.dll` that the
> launcher needs.  Running from there produces the error:
>
> *"Failed to load Python DLL … _internal\python313.dll …
>  LoadLibrary: The specified module could not be found."*

## To add a custom icon

1. Put `icon.ico` in the `assets/` folder
2. Add `--icon ../assets/icon.ico` to the pyinstaller command

## Rebuild using the spec file

```
cd source
pyinstaller --noconfirm --distpath ../dist --workpath ../build_tmp ../gamebeats.spec
```

## Distribution

To share or deploy, copy only the `dist/GameBeats/` folder (including `_internal/`).
The `build_tmp/` folder is never needed by end-users.

## Notes

- `data/` is writable at runtime — all user settings live there
- Do NOT delete `_internal/` — it contains the Python interpreter and all DLLs
- The app targets Python 3.9+ (no 3.10+ type hint syntax used)
- Redirect URI for Spotify must be `http://127.0.0.1:8888/callback` (not `localhost`)
