# GameBeats

GameBeats is a non-intrusive background music automation and overlay system designed for Windows gamers. It detects active game processes, automatically manages context-aware Spotify soundtrack playback, and monitors audio activity in real time. When silent periods or playlist ends occur, GameBeats offers seamless playlist transitions via a non-activating overlay or customizable global hotkeys—ensuring game input focus is never interrupted.

---

## Download

Get the standalone Windows installer:

- **Itch.io**: [Download GameBeats on itch.io](https://ssaborr.itch.io/gamebeats)
- **GitHub Releases**: Download `GameBeatsSetup.exe` from the repository releases page.

---

## Features

- **Automatic Game Detection**: Actively identifies running games across Steam, Epic Games Launcher, and custom executables.
- **Context-Aware Spotify Playback**: Maps games to specific genres, moods, or curated Spotify playlists with automatic switching upon game launch.
- **Passive WASAPI Audio Monitoring**: Analyzes game audio loopback and Spotify output amplitudes to detect gameplay transitions and track completion.
- **Zero-Focus-Stealing Overlay**: Built with Win32 extended window styles (`WS_EX_NOACTIVATE`, `WS_EX_TOOLWINDOW`, `HWND_TOPMOST`) allowing players to interact with notifications without losing keyboard or mouse focus in borderless and windowed games.
- **Customizable Mascot Prompt**: Configurable notification widget with automatic countdown timers, click-to-play triggers, and animations.
- **Global Hotkey Integration**: Asynchronous keyboard listener (`Ctrl+Alt+N`) enabling instant playlist progression without alt-tabbing.
- **Native C++ Focus Guard**: Specialized helper process that prevents Spotify desktop clients from forcing foreground focus during track transitions.

---

## Architecture Overview

```
+-----------------------------------------------------------------------+
|                             GAME WINDOW                               |
|                         (Maintains 100% Focus)                        |
|                                                                       |
|  - Active user input captured uninterrupted                           |
|  - WASAPI loopback audio monitored passively                          |
+-----------------------------------------------------------------------+
                                   |
                                   v (Async Audio Amplitude Stream)
+-----------------------------------------------------------------------+
|                     GAMEBEATS MONITORING ENGINE                       |
|                                                                       |
|  - Audio Monitor Thread: Evaluates game vs. media output silence     |
|  - Process Detector: Scans for running game executables               |
|  - State Dispatcher: Triggers playlist transition events              |
+-----------------------------------------------------------------------+
                                   |
                     +-------------+-------------+
                     |                           |
                     v                           v
+------------------------------------+  +-------------------------------+
|       NON-INTRUSIVE OVERLAY        |  |      SPOTIFY CONTROLLER       |
|                                    |  |                               |
| - Topmost floating widget          |  | - Web API (OAuth PKCE)        |
| - Zero focus steal (Win32 flags)   |  | - Desktop Focus Guard Bridge  |
| - Visual countdown & prompt        |  | - Headless / Web fallback     |
+------------------------------------+  +-------------------------------+
```

---

## Prerequisites

- **Operating System**: Windows 10 or Windows 11 (64-bit)
- **Python**: Version 3.9 or higher
- **Spotify Account**: Free or Premium account. GameBeats plays through its own Spotify web-player browser; the desktop client is optional.
- **C++ Compiler (Optional)**: MinGW-w64 (`g++`) if recompiling the native focus guard binary

---

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/GameBeats.git
cd GameBeats
```

### 2. Set Up a Virtual Environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Dependencies

```bash
cd source
pip install -r requirements.txt
```

### 4. Sign in to Spotify

GameBeats plays Spotify through a helper Chrome window, so no developer app or desktop client is required:

1. Launch GameBeats.
2. On first run, a Spotify login window opens.
3. Sign in with the Spotify account you want GameBeats to control.
4. The login is saved locally and reused on future launches.

The helper browser is the audio source; Spotify Desktop is optional and is not controlled by GameBeats.

---

## Running the Application

### Running from Source

```bash
cd source
python main.py
```

### Quick Launch Batch Script

From the repository root:

```bash
LAUNCH.bat
```

---

## Building Executables and Installers

GameBeats provides preconfigured build scripts for PyInstaller and Inno Setup.

### 1. Build and Run Executable

Run the automated build script from the repository root:

```bash
BUILD_AND_RUN.bat
```

This script will:
- Validate Python dependencies.
- Compile the C++ focus guard helper (if MinGW is installed).
- Package the project using PyInstaller into `dist/GameBeats/`.
- Launch `GameBeats.exe` from the correct distribution folder.

### 2. Build Release Installer

To create a standalone setup wizard installer (requires [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```bash
BUILD_RELEASE.bat
```

The compiled installer package will be output to `installer_output/GameBeatsSetup.exe`.

---

## Project Structure

```
GameBeats/
├── assets/                  # Application icons, mascots, and UI graphics
├── data/                    # User configurations and game database (generated)
├── include/                 # C/C++ header dependencies (e.g. MinHook)
├── installer/               # Inno Setup compilation script (GameBeats.iss)
├── lib/                     # Static C/C++ library binaries
├── source/                  # Core application source code
│   ├── core/                # Detection, audio monitoring, hotkeys, and Spotify backend
│   │   ├── audio_monitor.py
│   │   ├── detector.py
│   │   ├── global_hotkey.py
│   │   ├── spotify.py
│   │   ├── spotify_desktop.py
│   │   └── spotify_web.py
│   ├── ui/                  # CustomTkinter GUI, mascot overlay, and configuration views
│   │   ├── app.py
│   │   ├── games_page.py
│   │   ├── mascot_notifier.py
│   │   └── onboarding.py
│   ├── main.py              # Application entry point
│   ├── requirements.txt     # Python package dependencies
│   └── spotify_focus_guard.cpp # Native focus prevention helper source
├── BUILD.md                 # Technical build details and PyInstaller specifications
├── BUILD_AND_RUN.bat        # Automated build and execution script
├── BUILD_RELEASE.bat        # Release packaging and installer script
├── COMPLETE_ARCHITECTURE.md # Exhaustive system architecture documentation
├── LAUNCH.bat               # Executable launcher script
└── README.md
```

---

## Configuration

Settings are stored in the `data/` directory:

| File | Purpose |
|---|---|
| `data/config.json` | General application settings, API client credentials, hotkey configurations, and sound thresholds |
| `data/games.json` | Detected game mappings and associated Spotify playlist IDs / search queries |
| `data/tokens.json` | Cached OAuth authentication tokens (automatically refreshed) |

---

## Troubleshooting

- **Audio Capture Initialization**: Ensure the Windows WASAPI loopback audio device is active and not disabled in the Windows Sound Control Panel.
- **Focus Issues with Spotify Desktop**: Run `COMPILE_FOCUS_GUARD.bat` to compile `spotify_focus_guard.exe` if using a custom build of the desktop client hooks.
- **Spotify Authentication Callback**: Verify that `http://127.0.0.1:8888/callback` matches the Redirect URI entered in your Spotify Developer App configuration exactly.

---

## License

This project is open source and available under the [MIT License](LICENSE).
