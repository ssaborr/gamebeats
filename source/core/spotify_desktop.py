"""
spotify_desktop.py — Spotify desktop control without Web API (free accounts).

Playlist search uses invisible HTTP (Jina). Playback never opens Edge or any
browser tab — only localhost API and direct Spotify.exe --uri (no cmd start).
"""

import json
import os
import re
import sys
import time
import random
import subprocess
import threading

# Allow running this script directly by adding the 'source' directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.playlist_search import (
    pick_random_playlist_uri,
    build_search_query,
    first_track_uri_from_playlist,
    block_playlist_uri,
    load_blocked_playlist_uris,
)
from core.spotify_local import SpotifyLocalClient


try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import pyvda
    HAS_PYVDA = True
except ImportError:
    HAS_PYVDA = False

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_APPCOMMAND = 0x319
    EVENT_SYSTEM_FOREGROUND = 0x0003
    WINEVENT_OUTOFCONTEXT   = 0x0000

    APPCOMMAND_MEDIA_PAUSE     = 47
    APPCOMMAND_MEDIA_PLAY      = 46
    APPCOMMAND_MEDIA_PLAYPAUSE = 14

    # SendInput structures for reliable media key injection
    VK_MEDIA_PLAY_PAUSE = 0xB3
    VK_MEDIA_STOP       = 0xB2
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    INPUT_KEYBOARD      = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP       = 0x0002

    # Win32 Option 2: Developer-level Input Control
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
    user32.SetCapture.argtypes = [wintypes.HWND]
    user32.ReleaseCapture.argtypes = []
    user32.ShowCursor.argtypes = [wintypes.BOOL]
    user32.ShowCursor.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]

    # SetWindowPos constants — used to demote Spotify or pin Game in Z-order
    # without activating it or moving/resizing it (no visual side-effects).
    HWND_BOTTOM    = 1
    HWND_TOPMOST   = -1
    SWP_NOSIZE     = 0x0001
    SWP_NOMOVE     = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040 # Ensure window is visible
    SWP_HIDEWINDOW = 0x0080
    SWP_FRAMECHANGED = 0x0020
    TOPMOST_FLAGS  = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE

    # Extended window style — the real nuclear option.
    GWL_EXSTYLE      = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW  = 0x00040000

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.c_ushort),
            ("wScan",       ctypes.c_ushort),
            ("dwFlags",     ctypes.c_ulong),
            ("time",        ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_ulonglong),
        ]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long), ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_ulonglong),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("_u", _INPUT_UNION)]

DETACHED = subprocess.DETACHED_PROCESS if IS_WINDOWS else 0
SW_HIDE = 0
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7

if IS_WINDOWS:
    shell32 = ctypes.windll.shell32


# Global variable to store the GameBeats main window HWND
_GAMEBEATS_HWND = 0

def set_gamebeats_hwnd(hwnd: int):
    """Update the global GameBeats HWND used for focus exclusion."""
    global _GAMEBEATS_HWND
    _GAMEBEATS_HWND = hwnd

def _playlists_path(data_dir: str) -> str:
    return os.path.join(data_dir, "saved_playlists.json")

def load_saved_playlists(data_dir: str) -> list:
    try:
        with open(_playlists_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_saved_playlists(data_dir: str, playlists: list):
    with open(_playlists_path(data_dir), "w", encoding="utf-8") as f:
        json.dump(playlists, f, indent=2)


def is_playlist_uri(uri: str) -> bool:
    if not uri or not uri.startswith("spotify:playlist:"):
        return False
    pid = uri.split(":")[-1]
    return 20 <= len(pid) <= 24 and pid.replace("_", "").isalnum()


def parse_spotify_uri(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("spotify:playlist:"):
        return text if is_playlist_uri(text) else ""
    if text.startswith("spotify:search:"):
        return ""
    m = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)", text)
    if m:
        uri = f"spotify:playlist:{m.group(1)}"
        return uri if is_playlist_uri(uri) else ""
    return ""


def _spotify_running() -> bool:
    if not HAS_PSUTIL:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info.get("name") or "").lower() == "spotify.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def _process_running_by_name(exe_name: str) -> bool:
    if not HAS_PSUTIL:
        return False
    target = (exe_name or "").lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info.get("name") or "").lower() == target:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def _spotify_processes() -> list:
    if not HAS_PSUTIL:
        return []
    procs = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() == "spotify.exe":
                procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return procs


def _move_to_virtual_desktop_2(hwnd: int, logger=None) -> bool:
    """
    Move *hwnd* to virtual desktop 2, creating it first if needed.

    Uses pyvda (Windows 10 1903+ / Windows 11).  Spotify windows land on
    desktop 2 so they are completely invisible to the user while gaming on
    desktop 1 — no minimise flash, no taskbar entry, no Alt-Tab clutter.

    Falls back silently if pyvda is not installed or the call fails.
    """
    if not IS_WINDOWS or not HAS_PYVDA or not hwnd:
        return False
    try:
        desktops = pyvda.get_virtual_desktops()
        if len(desktops) < 2:
            pyvda.create_virtual_desktop()
            desktops = pyvda.get_virtual_desktops()
        if len(desktops) >= 2:
            pyvda.AppView(hwnd).move_to_desktop(desktops[1])
            if logger:
                logger(f"Spotify HWND {hwnd:#x} moved to virtual desktop 2.")
            return True
    except Exception as exc:
        if logger:
            logger(f"Virtual desktop move skipped: {exc}")
    return False


def _send_spotify_to_desktop_2(logger=None) -> int:
    """
    Move ALL current Spotify HWNDs to virtual desktop 2.
    Returns the number of windows moved.
    """
    moved = 0
    for hwnd in _find_spotify_hwnds(logger):
        if _move_to_virtual_desktop_2(hwnd, logger):
            moved += 1
    return moved


def _find_spotify_hwnds(logger=None):
    """
    Return all top-level window handles belonging to Spotify.exe processes.

    Modern Spotify is an Electron app whose window title changes with the
    current track and whose class is 'Chrome_WidgetWin_0' or
    'Chrome_WidgetWin_1'.  Matching on the window title is unreliable.
    We match on PID instead: enumerate every top-level window, look up its
    owning PID, and include it if that PID belongs to a spotify.exe process.
    """
    if not IS_WINDOWS or not HAS_PSUTIL:
        return []

    # Collect all PIDs belonging to spotify.exe
    spotify_pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() == "spotify.exe":
                spotify_pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if logger:
        logger(f"Found {len(spotify_pids)} spotify.exe PIDs.")
    if not spotify_pids:
        return []

    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(n)
        user32.GetWindowTextW(hwnd, buf, n)
        title = buf.value or ""

        if "GameBeats" in title:
            return True

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in spotify_pids:
            # Only target windows with a title (main UI) to avoid hidden helpers
            if title:
                found.append(hwnd)
        return True

    user32.EnumWindows(_enum, 0)
    if logger:
        logger(f"Found {len(found)} Spotify HWNDs.")
    return found


def _foreground_hwnd():
    if not IS_WINDOWS:
        return 0
    try:
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0

def _restore_foreground(hwnd: int):
    """Restore game focus via topmost pin (no SetForegroundWindow thrashing)."""
    if hwnd == _GAMEBEATS_HWND:
        # Do not restore focus to GameBeats itself
        return
    if IS_WINDOWS and hwnd:
        try:
            _hide_spotify_windows()
            # Always on Top: Using SWP_SHOWWINDOW to ensure the game is visible and topmost
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            
            # Input capture and cursor clipping caused issues for some users
            # (trapping the mouse inside the game). Disable aggressive input
            # control here to avoid clipping the user's cursor. We keep only the
            # non-invasive Z-order change above.
            # user32.SetCapture(hwnd)
            # user32.ShowCursor(False)
            # rect = wintypes.RECT()
            # if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            #     user32.ClipCursor(ctypes.byref(rect))

        except Exception:
            pass

def _push_spotify_to_back(logger=None):
    """
    Silently demote every Spotify window to the bottom of the Z-order.

    SetWindowPos with HWND_BOTTOM + SWP_NOACTIVATE is the right tool here:
    - ShowWindow(SW_SHOWMINNOACTIVE) only *minimises* the window, which can
      itself cause a brief visual flash and doesn't guarantee Z-order when
      Spotify later un-minimises itself.
    - SetWindowPos with HWND_BOTTOM purely reorders the Z-stack with no
      size/position/activation side-effects, so the game window is never
      touched and no taskbar flash occurs.
    """
    if not IS_WINDOWS:
        return
    for hwnd in _find_spotify_hwnds(logger):
        try:
            user32.SetWindowPos(
                hwnd,
                HWND_BOTTOM,        # insert after: bottom of Z-order
                0, 0, 0, 0,         # x, y, cx, cy — ignored due to flags
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
            )
        except Exception:
            pass


def _hide_spotify_windows(logger=None):
    """Make every Spotify desktop window invisible and non-activating."""
    if not IS_WINDOWS:
        return
    for hwnd in _find_spotify_hwnds(logger):
        try:
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            target_style = (style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            if style != target_style:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, target_style)
            user32.ShowWindow(hwnd, SW_HIDE)
            user32.SetWindowPos(
                hwnd,
                HWND_BOTTOM,
                0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE |
                SWP_HIDEWINDOW | SWP_FRAMECHANGED,
            )
        except Exception:
            pass


def _noactivate_spotify_windows(logger=None):
    """
    Apply WS_EX_NOACTIVATE to every Spotify window — the true nuclear option.

    How it works:
    - LockSetForegroundWindow can ONLY be called by the foreground process.
      When a game has focus, GameBeats is not the foreground process, so those
      calls were silently failing. Spotify was getting focus because Windows
      automatically grants child processes foreground rights at spawn time.
    - WS_EX_NOACTIVATE is an extended window style that instructs Windows to
      refuse to activate that window no matter what the owning process requests.
      It is applied via SetWindowLongW, which ANY process can call on any HWND
      it holds — no foreground ownership required.
    - Once set, clicking or showing the window does NOT activate it or move the
      keyboard focus. Spotify can call SetForegroundWindow on itself all it
      wants — Windows will silently ignore it.
    """
    if not IS_WINDOWS:
        return
    for hwnd in _find_spotify_hwnds(logger):
        try:
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            target_style = style | WS_EX_NOACTIVATE
            if style != target_style:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, target_style)
        except Exception:
            pass

def _inject_hook_dll(pid, logger=None):
    """Inject spotify_hook.dll into the target process to suppress its UI."""
    if not IS_WINDOWS: return False

    # Try to find DLL in core/ or source/ root
    script_dir = os.path.dirname(__file__)
    dll_path = ""
    for candidate in ["spotify_hook.dll", "../spotify_hook.dll"]:
        path = os.path.abspath(os.path.join(script_dir, candidate))
        if os.path.exists(path):
            dll_path = path
            break
    else:
        if logger: logger("Injection failed: spotify_hook.dll not found. UI suppression inactive.")
        return False

    kernel32 = ctypes.windll.kernel32
    PROCESS_ALL_ACCESS = 0x1F0FFF
    
    h_process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
    if not h_process: return False

    try:
        path_bytes = dll_path.encode('utf-16-le') + b'\x00\x00'
        buf = kernel32.VirtualAllocEx(h_process, None, len(path_bytes), 0x1000, 0x04)
        kernel32.WriteProcessMemory(h_process, buf, path_bytes, len(path_bytes), None)
        
        h_kernel32 = kernel32.GetModuleHandleW("kernel32.dll")
        h_loadlib = kernel32.GetProcAddress(h_kernel32, b"LoadLibraryW")
        
        h_thread = kernel32.CreateRemoteThread(h_process, None, 0, h_loadlib, buf, 0, None)
        if h_thread:
            kernel32.WaitForSingleObject(h_thread, 1000)
            kernel32.CloseHandle(h_thread)
            if logger: logger(f"Injected hook into Spotify PID {pid}")
            return True
    except Exception as e:
        if logger: logger(f"Injection error: {e}")
    finally:
        kernel32.CloseHandle(h_process)
    return False

# A near-silent Spotify track used to make the desktop app register as an
# active device the moment it starts. Browser automation can then target
# this device for Spotify Connect without the user hearing anything.
SILENT_TRACK_URI = "spotify:track:2bNCdW4rLnCTzgqUXTTDO1"

def _track_cache_path(data_dir: str) -> str:
    return os.path.join(data_dir, "track_cache.json")

class SpotifyDesktopController:
    def __init__(self, data_dir: str, logger=None, gamebeats_hwnd: int = 0):
        self._log = logger if logger else (lambda msg: print(f"[SpotifyDesktopController] {msg}"))
        self.data_dir = data_dir
        global _GAMEBEATS_HWND; _GAMEBEATS_HWND = gamebeats_hwnd # Store GameBeats HWND globally
        self._last_error = ""
        self._last_play_method = ""
        self._is_playing = False
        self._playback_state_known = False
        self._last_uri = ""
        self._last_track_uri = ""
        self._last_query = ""
        self._last_pick = {}
        self._play_lock = threading.Lock()
        self._last_play_time = 0.0
        self._paused_by_game = False
        self._session_locked = False
        self._local = SpotifyLocalClient()
        self._local_disabled_until = 0.0
        self._track_cache = self._load_track_cache()
        self._start_noactivate_watcher()

    def _start_noactivate_watcher(self):
        """
        Launch spotify_focus_guard.exe if present (preferred — pure Win32 loop).
        Fall back to an in-process Python thread that re-applies WS_EX_NOACTIVATE
        every 2 seconds if the exe is missing.
        """
        guard_exe = self._find_focus_guard_exe()
        if IS_WINDOWS and guard_exe:
            try:
                if _process_running_by_name("spotify_focus_guard.exe"):
                    self._log("spotify_focus_guard.exe already running.")
                    return
                subprocess.Popen(
                    [guard_exe],
                    cwd=os.path.dirname(guard_exe) or None,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._log("spotify_focus_guard.exe launched.")
                return  # exe handles everything; no need for Python thread
            except Exception as ex:
                self._log(f"Could not launch focus guard exe: {ex} — using Python fallback.")

        # Python fallback: re-apply noactivate styles in a daemon thread
        def _watch():
            while True:
                try:
                    if _spotify_running():
                        _hide_spotify_windows()
                except Exception:
                    pass
                time.sleep(0.35)
        t = threading.Thread(target=_watch, daemon=True, name="spotify-noactivate-watcher")
        # Run one immediate pass to hide any already-running Spotify before thread starts
        try:
            if _spotify_running():
                _hide_spotify_windows()
        except Exception:
            pass
        t.start()

    def _find_focus_guard_exe(self) -> str:
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(os.path.dirname(sys.executable), "spotify_focus_guard.exe"))
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                candidates.append(os.path.join(meipass, "spotify_focus_guard.exe"))

        module_dir = os.path.dirname(__file__)
        candidates.extend([
            os.path.join(module_dir, "spotify_focus_guard.exe"),
            os.path.join(os.path.dirname(module_dir), "spotify_focus_guard.exe"),
        ])

        for path in candidates:
            path = os.path.abspath(path)
            if os.path.isfile(path):
                return path
        return ""

    def _load_track_cache(self) -> dict:
        try:
            with open(_track_cache_path(self.data_dir), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_track_cache(self):
        try:
            with open(_track_cache_path(self.data_dir), "w", encoding="utf-8") as f:
                json.dump(self._track_cache, f, indent=2)
        except Exception:
            pass

    def _cached_track(self, playlist_id: str) -> str:
        return self._track_cache.get(playlist_id, "")

    def _remember_track(self, playlist_id: str, track_uri: str):
        if playlist_id and track_uri:
            self._track_cache[playlist_id] = track_uri
            self._save_track_cache()

    def play_track_uri(self, uri: str, restart: bool = False) -> bool:
        """Play one concrete track/episode URI in Spotify desktop.

        This is the small behavior extracted from the old desktop script: send
        Spotify.exe a concrete playable URI, wait for the handoff, then send a
        play command. It intentionally does not go through playlist scraping.
        """
        uri = (uri or "").strip()
        if not re.match(r"^spotify:(track|episode):[A-Za-z0-9]{22}$", uri):
            self._last_error = "Expected a spotify:track:... or spotify:episode:... URI"
            return False

        if restart:
            self.close_spotify(timeout=4.0)
            self.reset_session()
            self._last_uri = ""
            self._last_track_uri = ""
            time.sleep(0.2)

        self._last_track_uri = uri
        self._last_uri = uri
        self._paused_by_game = False
        self._last_play_method = ""

        method = self._open_in_spotify(uri)
        if not method:
            return False

        self._last_play_method = method
        # Extra hide + settle: _open_in_spotify() already hides, but this
        # additional 3.5s wait gives Spotify time to re-show itself.
        _hide_spotify_windows()
        time.sleep(3.5)
        _hide_spotify_windows()

        played = False
        try:
            self._local_disabled_until = 0.0
            played = bool(self._local.play(uri, context_uri=uri))
        except Exception:
            played = False

        if not played:
            played = self._send_playback_command("play", use_toggle=False)

        if not played:
            played = self._send_input_media_key(VK_MEDIA_PLAY_PAUSE)

        self._remember_playback_state(True, paused_by_game=False)
        self._log(f"Spotify desktop track URI sent: {uri}")
        return bool(played or method)

    def _verify_playback(self, expected_playlist_uri: str = "", expected_track_uri: str = "", timeout: float = 6.0) -> bool:
        """Poll the local status and audio loopback to confirm playback.
        
        CRITICAL: Since we're desktop-only (no localhost API), rely primarily on:
        1. Audio loopback detection (most reliable)
        2. Local status as secondary check (if available)
        
        Returns True if verification succeeded within timeout, False otherwise.
        """
        if not expected_playlist_uri and not expected_track_uri:
            return False
        
        # DESKTOP-ONLY MODE: Prioritize audio detection over local status
        # Local status requires localhost:8888 which may not be available
        
        # Try BOTH methods in parallel for full timeout duration
        deadline = time.time() + timeout
        sustained_audio = 0
        required_sustain_checks = 2  # require ~1s of sustained audio (0.5s per check)
        
        try:
            from core.audio_monitor import get_spotify_loopback_peak, SPOTIFY_LOOPBACK_LOUD
            audio_available = True
        except Exception:
            audio_available = False
        
        while time.time() < deadline:
            # Method 1: Check audio loopback (most reliable for desktop-only)
            if audio_available:
                try:
                    peak, db, status = get_spotify_loopback_peak()
                    if logger := self._log:
                        if status != "ok":
                            logger(f"DEBUG: Audio loopback status: {status}")
                    
                    # Spotify audio detected above threshold
                    if status == "ok" and peak >= SPOTIFY_LOOPBACK_LOUD:
                        sustained_audio += 1
                        if sustained_audio >= required_sustain_checks:
                            self._log(f"DEBUG: Playback verified via audio loopback ({peak:.3f} peak, {db:.1f}dB)")
                            return True
                    else:
                        sustained_audio = 0
                except Exception as e:
                    self._log(f"DEBUG: Audio loopback error: {e}")
            
            # Method 2: Check local status (when available - no localhost required)
            # CRITICAL: ONLY verify TRACK URI match, NEVER playlist URI match
            # Playlist URI matching causes Spotify to resume from where it left off, not play track 1
            try:
                cur = self.get_current_track() or {}
                cur_uri = (cur.get("uri") or "")
                is_playing = cur.get("is_playing", False)
                
                # TRACK URI verification ONLY - this ensures we start at the correct track
                if is_playing and expected_track_uri and cur_uri == expected_track_uri:
                    self._log(f"DEBUG: Playback verified via track URI match (CORRECT track playing)")
                    return True
            except Exception:
                pass
            
            time.sleep(0.5)
        
        # Timeout: If we detected ANY audio, consider it a success (may have started late)
        if sustained_audio >= 1:
            self._log(f"DEBUG: Playback partially verified (audio detected but timeout)")
            return True
        
        self._log(f"DEBUG: Playback verification FAILED (no audio/URI match within {timeout}s)")
        return False

    def verify_access(self):
        if self._find_spotify_exe():
            return True, "Desktop mode — tag search playlists (no API)"
        return False, "Install Spotify desktop from spotify.com/download"

    def _find_spotify_exe(self):
        """Real install only — never WindowsApps stub (opens Edge / browser)."""
        if not IS_WINDOWS:
            return None
        candidates = []

        appdata = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")
        if os.path.isfile(appdata):
            candidates.append(appdata)

        try:
            import winreg
            for root, sub, name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Spotify", "Path"),
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "Spotify"),
            ):
                try:
                    key = winreg.OpenKey(root, sub)
                    val, _ = winreg.QueryValueEx(key, name)
                    winreg.CloseKey(key)
                    if sub.endswith("Run"):
                        parts = val.replace('"', " ").split()
                        for part in parts:
                            if part.lower().endswith("spotify.exe") and os.path.isfile(part):
                                candidates.append(part)
                    else:
                        exe = os.path.join(val, "Spotify.exe")
                        if os.path.isfile(exe):
                            candidates.append(exe)
                except OSError:
                    pass
        except ImportError:
            pass

        for path in candidates:
            norm = path.replace("\\", "/").lower()
            if "windowsapps" in norm or "msedge" in norm:
                continue
            self._log(f"Found Spotify executable at: {path}")
            return path
        return None

    def launch_spotify(self, uri: str = ""):
        if _spotify_running():
            if uri:
                # Need to restart Spotify with the URI so it opens with the
                # correct playback context (e.g. silent track for detection).
                self._log("Spotify already running — restarting with URI…")
                self.close_spotify(timeout=4.0)
                time.sleep(0.1)
            else:
                # No URI needed — just re-apply NOACTIVATE in case it reset
                # its own window styles (Spotify sometimes does this after updates).
                _hide_spotify_windows(self._log)
                return True
        exe = self._find_spotify_exe()
        if not exe:
            return False
        try:
            cmd = [exe]
            if uri:
                cmd.append(f"--uri={uri}")
            cmd.append("--minimized")
            if IS_WINDOWS:
                # Launch hidden and never steal the foreground window.
                si = subprocess.STARTUPINFO()
                si.dwFlags     = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = SW_HIDE
                subprocess.Popen(
                    cmd,
                    shell=False,
                    creationflags=DETACHED | subprocess.CREATE_NO_WINDOW,
                    startupinfo=si,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    cmd,
                    shell=False,
                    creationflags=DETACHED,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            # Poll for Spotify window then make it fully hidden/non-activating
            if IS_WINDOWS:
                for _ in range(300):
                    time.sleep(0.01)
                    hwnds = _find_spotify_hwnds()

                    if hwnds:
                        for hwnd in hwnds:
                            try:
                                # Nuclear anti-focus
                                user32.AllowSetForegroundWindow(0)
                                user32.LockSetForegroundWindow(1)

                                _hide_spotify_windows()
                            except Exception:
                                pass
                        break
            return True
        except Exception:
            return False

    def close_spotify(self, timeout=4.0) -> bool:
        procs = _spotify_processes()
        if not procs:
            return True
        self._log(f"Closing Spotify ({len(procs)} process(es)).")
        for proc in procs:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            gone, alive = psutil.wait_procs(procs, timeout=timeout)
        except Exception:
            alive = []
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(0.6)
        return not _spotify_running()

    def restart_spotify(self) -> bool:
        self.close_spotify()
        ok = self.launch_spotify()
        if ok:
            for _ in range(16):
                if _spotify_running():
                    # Reset controller session state so next pick fetches fresh playlist
                    try:
                        self.reset_session()
                        self._last_uri = ""
                        self._last_track_uri = ""
                        self._session_locked = False
                    except Exception:
                        pass
                    return True
                time.sleep(0.25)
        # Even on failure, clear session flags so caller treats next pick as fresh
        try:
            self.reset_session()
            self._last_uri = ""
            self._last_track_uri = ""
            self._session_locked = False
        except Exception:
            pass
        return ok

    def ensure_fresh_session(self, timeout: float = 10.0) -> bool:
        """Restart Spotify and wait until a fresh process appears (or timeout).

        Returns True if Spotify is running and controller session state was reset.
        """
        try:
            ok = self.restart_spotify()
        except Exception:
            ok = False

        if not ok:
            # Even if restart_spotify returned False, we attempted a reset above.
            # Wait briefly for any stray process to appear before giving up.
            deadline = time.time() + timeout
            while time.time() < deadline:
                if _spotify_running():
                    break
                time.sleep(0.25)

        # Final check
        running = _spotify_running()
        if running:
            try:
                # Re-apply hidden/non-activating state for any found windows
                _hide_spotify_windows(self._log)
            except Exception:
                pass
            return True
        return False

    def ensure_active_device(self, wait_seconds=8):
        if _spotify_running():
            return True

        # Launch Spotify plain — same as old code
        self.launch_spotify()
        deadline = time.time() + wait_seconds
        while not _spotify_running() and time.time() < deadline:
            time.sleep(0.3)

        # Old _begin_playback always paused first before sending a new URI
        # to clear any stuck playback state.
        self._media_pause()
        time.sleep(0.1)

        # VBScript sends the silent track URI — includes 3.5s settle wait inside.
        # For a silent track we CANNOT use audio loopback to verify (no sound = 0 peak).
        # So we skip the kickstart loop and just send play commands directly after the wait.
        method = self._open_in_spotify(SILENT_TRACK_URI)
        if not method:
            return _spotify_running()

        # Send play twice with a short gap — same individual commands as the old
        # kickstart loop, but without audio verification (track is silent by design).
        self._send_playback_command("play", use_toggle=False)
        time.sleep(0.5)
        self._send_input_media_key(VK_MEDIA_PLAY_PAUSE)
        time.sleep(0.3)
        self._send_playback_command("toggle", use_toggle=True)

        self._remember_playback_state(True, paused_by_game=False)
        return True


    def _clear_mixer_mute(self):
        try:
            from core.audio_monitor import _clear_spotify_mixer_mute
            _clear_spotify_mixer_mute()
        except Exception:
            pass

    def _send_input_media_key(self, vk: int) -> bool:
        """
        Inject a media key via SendInput — no window focus required.
        This is the most reliable way to send play/pause to Spotify
        because it goes through the system-wide media key pipeline,
        exactly as if the user pressed a keyboard media button.
        """
        if not IS_WINDOWS:
            return False
        try:
            inputs = (_INPUT * 2)()
            # Key-down
            inputs[0].type = INPUT_KEYBOARD
            inputs[0]._u.ki.wVk = vk
            inputs[0]._u.ki.dwFlags = KEYEVENTF_EXTENDEDKEY
            inputs[0]._u.ki.wScan = 0
            inputs[0]._u.ki.time = 0
            inputs[0]._u.ki.dwExtraInfo = ctypes.windll.user32.GetMessageExtraInfo()
            # Key-up
            inputs[1].type = INPUT_KEYBOARD
            inputs[1]._u.ki.wVk = vk
            inputs[1]._u.ki.dwFlags = KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP
            inputs[1]._u.ki.wScan = 0
            inputs[1]._u.ki.time = 0
            inputs[1]._u.ki.dwExtraInfo = ctypes.windll.user32.GetMessageExtraInfo()
            sent = ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(_INPUT))
            return sent == 2
        except Exception as ex:
            self._log(f"SendInput error: {ex}")
            return False

    def _powershell_sendkeys(self, char_code: int) -> bool:
        """Last-ditch media-key fallback through WScript SendKeys."""
        if not IS_WINDOWS:
            return False
        ps_cmd = f"$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys([char]{char_code})"
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                creationflags=DETACHED | subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as ex:
            self._log(f"PowerShell SendKeys error: {ex}")
            return False

    def _send_appcommand_to_spotify(self, appcommand: int, label: str) -> bool:
        if not IS_WINDOWS:
            return False

        hwnds = _find_spotify_hwnds(self._log)
        if not hwnds:
            return False

        sent = 0
        lparam = int(appcommand) << 16
        for hwnd in hwnds[:1]:
            try:
                if user32.PostMessageW(hwnd, WM_APPCOMMAND, hwnd, lparam):
                    sent += 1
            except Exception:
                pass

        if sent:
            self._log(f"Sent Spotify {label} command to {sent} window(s).")
            return True
        return False

    def _local_status(self) -> dict:
        if time.time() < self._local_disabled_until:
            return {}
        try:
            data = self._local.status()
            if not data:
                self._local_disabled_until = time.time() + 20.0
                return {}
            return data
        except Exception:
            self._local_disabled_until = time.time() + 20.0
        return {}

    def _local_is_playing(self):
        data = self._local_status()
        if data:
            for key in ("playing", "is_playing"):
                if key in data:
                    return bool(data.get(key))
            if "paused" in data:
                return not bool(data.get("paused"))
        return None

    def _remember_playback_state(self, is_playing: bool, paused_by_game=None):
        self._is_playing = bool(is_playing)
        self._playback_state_known = True
        if paused_by_game is not None:
            self._paused_by_game = bool(paused_by_game)
        elif is_playing:
            self._paused_by_game = False

    def _send_playback_command(self, command: str, use_toggle: bool = False) -> bool:
        """
        Send play/pause to Spotify.

        Local pause.json is idempotent when available. If Spotify's localhost
        API is disabled, target Spotify's own windows with WM_APPCOMMAND.
        For monitor-driven pause/resume, a toggle fallback is safe because the
        caller only reaches it when our own paused_by_game state says it is.

        Focus contract: we snapshot the foreground window before touching
        Spotify and restore it afterwards, so the game cursor/focus never
        moves regardless of which code path sends the command.
        """
        if not IS_WINDOWS:
            return False

        # Try to record the immediate caller for diagnostics (source of pause/resume)
        try:
            import inspect
            caller_frame = inspect.stack()[1]
            caller = f"{caller_frame.function} @ {os.path.basename(caller_frame.filename)}:{caller_frame.lineno}"
        except Exception:
            caller = "<unknown>"
        self._log(f"Sending Spotify media command '{command}' (source={caller})")
        fg = _foreground_hwnd()
        
        appcommand = {
            "pause": APPCOMMAND_MEDIA_PAUSE,
            "play": APPCOMMAND_MEDIA_PLAY,
            "toggle": APPCOMMAND_MEDIA_PLAYPAUSE,
        }.get(command, APPCOMMAND_MEDIA_PLAYPAUSE)

        if command == "pause" and self._send_appcommand_to_spotify(appcommand, command):
            _restore_foreground(fg)
            return True

        if self._send_appcommand_to_spotify(appcommand, command):
            _restore_foreground(fg)
            return True

        if command == "play" or use_toggle or command == "toggle":
            if self._send_appcommand_to_spotify(APPCOMMAND_MEDIA_PLAYPAUSE, "toggle"):
                _restore_foreground(fg)
                return True
            if self._send_input_media_key(VK_MEDIA_PLAY_PAUSE):
                self._log("Sent global media play/pause key.")
                _restore_foreground(fg)
                return True
            if self._powershell_sendkeys(179):
                self._log("Sent PowerShell play/pause fallback.")
                _restore_foreground(fg)
                return True

        self._last_error = "Could not send a Spotify media command."
        _restore_foreground(fg)
        return False

    def _media_pause(self) -> bool:
        """Pause Spotify. Spotify stays in the background."""
        self._clear_mixer_mute()
        return self._send_playback_command("pause", use_toggle=False)

    def _media_play(self) -> bool:
        """Resume Spotify. Spotify stays in the background."""
        self._clear_mixer_mute()
        return self._send_playback_command("play", use_toggle=False)

    def _set_playback_paused(self, paused: bool) -> bool:
        """
        Pause or resume Spotify using Space, but ONLY when the audio state
        confirms the toggle is needed — avoiding double-toggles.

        Rules (called from the audio monitor loop which already checks peaks):
          pause=True  → only send Space if _paused_by_game is False
                         (i.e. we haven't already paused it this session)
          pause=False → only send Space if _paused_by_game is True
                         (i.e. we were the ones who paused it)
        """
        self._clear_mixer_mute()

        if paused:
            if self._paused_by_game:
                return True  # already paused by us — [char]178 would be harmless but skip it
            # [char]178 = pause-only key, safe to send regardless of current state.
            if not self._send_playback_command("toggle", use_toggle=True):
                return False
            self._remember_playback_state(False, paused_by_game=True)
            return True
        else:
            if not self._paused_by_game:
                # We never paused it — don't send [char]179 (toggle) or we'd accidentally
                # pause a playlist that was already playing independently.
                return self._is_playing
            # _paused_by_game=True means WE sent [char]178, so Spotify is definitely
            # paused right now. Safe to send [char]179 (toggle) to resume it.
            if not self._send_playback_command("toggle", use_toggle=True):
                return False
            self._remember_playback_state(True, paused_by_game=False)
            return True

    def ensure_paused(self) -> bool:
        """Make Spotify paused, regardless of whether GameBeats paused it before."""
        self._clear_mixer_mute()
        if self._paused_by_game:
            self._remember_playback_state(False, paused_by_game=True)
            return True
        if self._playback_state_known and not self._is_playing:
            self._paused_by_game = True
            return True

        if self._send_playback_command("pause", use_toggle=False):
            self._remember_playback_state(False, paused_by_game=True)
            return True

        state = self._local_is_playing()
        if state is False:
            self._remember_playback_state(False, paused_by_game=True)
            return True

        if state is True or (self._playback_state_known and self._is_playing):
            if self._send_playback_command("toggle", use_toggle=True):
                self._remember_playback_state(False, paused_by_game=True)
                return True

        return False

    def ensure_playing(self) -> bool:
        """Make Spotify play using direct playback commands (media keys only)."""
        self._clear_mixer_mute()
        state = self._local_is_playing()
        if state is True:
            self._remember_playback_state(True, paused_by_game=False)
            return True
        if (
            state is None
            and self._playback_state_known
            and self._is_playing
            and not self._paused_by_game
        ):
            return True

        # Aggressive playback trigger: try direct play, then the global media key
        # Global media keys (SendInput) are the most reliable for Spotify Free.
        if (self._send_playback_command("play", use_toggle=False) or 
            self._send_input_media_key(VK_MEDIA_PLAY_PAUSE) or
            self._send_playback_command("toggle", use_toggle=True)):
            
            # Give it a moment to register before updating internal state
            time.sleep(0.2)
            self._remember_playback_state(True, paused_by_game=False)
            return True

        return False

    def _open_in_spotify(self, uri: str) -> str:
        """
        Open URI in the desktop Spotify app using Spotify.exe --uri.

        No browser, no shell, no cmd.  If Spotify.exe is not installed there
        is nothing to fall back to — we return "" and the caller reports an
        error to the user.
        
        CRITICAL FIX: Enhanced timing and verification to ensure picked playlist
        plays first, not recently played songs.
        """
        if not uri or not uri.startswith("spotify:"):
            return ""

        exe = self._find_spotify_exe()
        if not exe:
            self._last_error = (
                "Spotify desktop app not found. "
                "Install it from spotify.com/download and keep it running."
            )
            return ""

        if not _spotify_running():
            # Plain launch — the VBScript below will immediately hand off the
            # real URI, so no silent-track pre-warm needed here.
            self.launch_spotify()
            # Wait up to 10s for Spotify to fully start before sending --uri.
            # Sending --uri before Spotify is ready can cause Windows to hand
            # the spotify: protocol to the default browser (Edge), opening
            # unwanted tabs.
            for attempt in range(20):
                time.sleep(0.5)
                if _spotify_running():
                    # Extra settle time after process appears to ensure readiness
                    time.sleep(1.0)
                    break
            else:
                # Timeout: Spotify took too long to start
                self._log("Warning: Spotify startup timeout, proceeding anyway")
                time.sleep(0.5)

        fg = _foreground_hwnd()

        # Pin game window topmost (non-looping)
        if fg:
            if fg != _GAMEBEATS_HWND: # Do not pin GameBeats itself
                user32.SetWindowPos(fg, HWND_TOPMOST, 0, 0, 0, 0, TOPMOST_FLAGS)

        # VBScript wrapper for nuclear anti-focus launch. 
        # WshShell.Run(..., 0) attempts a fully hidden launch which is more 
        # reliable than Python's STARTUPINFO for Electron-based apps.
        vbs_script = f'''
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "{exe}" & chr(34) & " --uri={uri}", 0, False
'''
        # Use a unique filename for the VBS to avoid access collisions
        vbs_name = f"spotify_launch_{time.time_ns()}.vbs"
        vbs_path = os.path.join(self.data_dir, vbs_name)

        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_script)

        # Launch the VBS wrapper. We don't use .run() because we don't want to block.
        subprocess.Popen(
            ["wscript.exe", vbs_path],
            shell=False,
            creationflags=DETACHED | subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Clean up the script shortly after launch
        threading.Timer(5.0, lambda: os.remove(vbs_path) if os.path.exists(vbs_path) else None).start()

        launched = True

        if launched:
            # CRITICAL: Spotify takes time to "digest" the URI handoff.
            # The old code waited 3.5s here. Without this wait, any play
            # commands sent afterwards arrive before Spotify has loaded
            # the track, causing them to do nothing or resume recently played.

            # Hide Spotify windows IMMEDIATELY after launch to minimize the
            # visible flash. The focus guard polls every 150-350ms but we can
            # beat it by hiding right away. Then hide again after the settle
            # period in case Spotify re-showed itself while loading the URI.
            _hide_spotify_windows()
            time.sleep(3.5)
            _hide_spotify_windows()

            if fg and fg != _GAMEBEATS_HWND:
                user32.SetWindowPos(fg, HWND_TOPMOST, 0, 0, 0, 0, TOPMOST_FLAGS)
            return "spotify.exe"

        # Spotify.exe is running but --uri args failed; send a plain play command
        if _spotify_running():
            self._media_play()
            if fg:
                user32.SetWindowPos(fg, HWND_TOPMOST, 0, 0, 0, 0, TOPMOST_FLAGS)
            return "media_key"

        if fg:
            user32.SetWindowPos(fg, HWND_TOPMOST, 0, 0, 0, 0, TOPMOST_FLAGS)
        return ""

    def _begin_playback(self, playlist_uri: str, track_uri: str = "", force: bool = True) -> bool:
        if not is_playlist_uri(playlist_uri):
            self._last_error = "Invalid playlist URI"
            return False

        # Ensure Spotify is at least running. The full restart is now handled 
        # by the caller in app.py to avoid redundant cycles.
        if not _spotify_running():
            self.launch_spotify()
            time.sleep(1.5)

        self._last_uri = playlist_uri
        self._last_playlist_name = ""
        self._paused_by_game = False
        self._last_play_method = ""

        pid = playlist_uri.split(":")[-1]
        
        # Always fetch fresh from Jina (don't use cache) to ensure correct first track
        if not track_uri:
            self._log(f"Fetching first track for {pid[:8]}...")
            track_uri = first_track_uri_from_playlist(pid, logger=self._log) or ""
            if track_uri:
                self._remember_track(pid, track_uri)

        # CRITICAL: In desktop/tag-search mode, we MUST have a track URI.
        # Without it, Spotify won't reliably start playing or start at the first track.
        # NEVER use playlist URI as fallback - it causes no playback.
        # Skip this playlist and let caller try next one.
        if not track_uri:
            self._log(f"Cannot play {pid[:8]} — Jina extraction failed (track URI required). Skipping to next playlist.")
            self._last_error = "Jina extraction failed for this playlist"
            return False

        self._last_track_uri = track_uri
        # Use track URI to ensure reliable playback from the beginning
        play_uri = track_uri
        self._log(f"Final Playback URI: {play_uri}")

        fg = _foreground_hwnd()

        # Scraper-only flow: rely on the scraper-provided track URI and open that directly.
        method = self._open_in_spotify(play_uri)
        if method:
            self._last_play_method = method
            self._remember_playback_state(True, paused_by_game=False)
            self._session_locked = True
            _restore_foreground(fg)

            # CRITICAL: Wait for Spotify to digest the URI while window is visible.
            # Use longer wait for desktop-only mode since there's no localhost to check
            time.sleep(3.5)
            
            self._log(f"URI sent: {pid[:8]}... initiating playback.")
            
            # DESKTOP-ONLY MODE: ALWAYS send media keys to ensure playback starts
            # Don't rely solely on verification — aggressively trigger playback
            verified = self._verify_playback(expected_playlist_uri=playlist_uri, expected_track_uri=track_uri, timeout=2.0)
            
            if not verified:
                self._log(f"Initial verification failed, attempting aggressive kickstart...")
            else:
                self._log(f"Initial verification succeeded, sending confirm media keys...")
            
            # AGGRESSIVE KICKSTART: Even if verified, send media keys to ensure music REALLY plays
            # This handles the case where verification lied (Spotify loaded but didn't play)
            for i in range(5):  # Reduced from 8 to 5 since we're being more aggressive upfront
                self._log(f"Kickstart attempt {i + 1}/5...")
                
                # The "Nudge" trick: Next then Previous often wakes up a stuck player.
                if i == 1:
                    self._log(f"Sending Next/Prev nudge...")
                    self.media_next()
                    time.sleep(0.8)
                    self.media_prev()
                    time.sleep(0.8)

                # Global media keys are the most reliable way to play Spotify
                # Send both media key and play command for redundancy
                self._log(f"Sending media play/pause toggle...")
                self.media_play_pause()
                time.sleep(0.3)
                self._send_playback_command("play")
                
                # Wait and verify each attempt
                time.sleep(1.5)
                verified = self._verify_playback(expected_playlist_uri=playlist_uri, 
                                               expected_track_uri=track_uri, timeout=1.5)
                if verified:
                    self._log(f"✓ Playback confirmed on attempt {i + 1}")
                    break
                else:
                    self._log(f"✗ Playback not confirmed on attempt {i + 1}, continuing...")
            
            # FINAL SUPPRESSION: Now that music is playing (or we tried everything),
            # apply nuclear focus protection and hide the desktop window.
            _hide_spotify_windows(self._log)
            self.minimize_window()
            
            # Return the actual verification result so UI knows if it really started
            return verified

        _restore_foreground(fg)
        self._last_error = (
            "Could not open Spotify. Open the desktop app from spotify.com/download "
            "and keep it running in the background."
        )
        return False

    def _start_playback(
        self,
        playlist_uri: str,
        display_name: str,
        track_uri: str = "",
        force: bool = True,
    ):
        if self._begin_playback(playlist_uri, track_uri=track_uri, force=force):
            self._last_playlist_name = display_name
            return {"name": display_name, "uri": playlist_uri}
        return None

    def play_random_for_mood(
        self,
        mood: str = "",
        query_hint: str = "",
        game_name: str = "",
        tags: list = None,
        force_new: bool = True,
        max_results: int = 5,
        exclude_uris=None,
        one_shot: bool = False,
    ):
        pick = pick_random_playlist_uri(
            game_name=game_name,
            tags=tags or [],
            query_hint=query_hint,
            data_dir=self.data_dir,
            max_results=max_results,
            exclude_uris=exclude_uris,
        )
        if not pick or not pick.get("uri"):
            self._last_error = (pick or {}).get("error") or (
                f"No playlists found for: "
                f"{build_search_query(game_name, tags, query_hint)[:60]}"
            )
            return None

        with self._play_lock:
            # Vetted Pick Loop: Ensure we only pick playlists where Jina can read track metadata.
            # This prevents the 'stuck on recently played' issue by ensuring a track-first start.
            pool = list(pick.get("pool", []))
            if not pool:
                pool = [{"uri": pick["uri"], "name": pick.get("name", "")}]
            try:
                blocked_set = set(load_blocked_playlist_uris(self.data_dir) or [])
                blocked_set.update(exclude_uris or [])
                pool = [item for item in pool if item.get("uri") not in blocked_set]
            except Exception:
                pass
            if not pool:
                self._last_error = "All candidate playlists were blocked"
                return None
            # If one_shot is requested, only attempt the primary pick once
            if one_shot:
                item = pool[0]
                uri = item["uri"]
                pid = uri.split(":")[-1]
                item_name = item.get("name", "")[:60] or "Unknown"
                self._log(f"One-shot: attempting {item_name} ({pid[:8]}...) via desktop controller")
                self._log(f"DEBUG: Fetching first track for {pid[:8]} via Jina...")
                track_uri = first_track_uri_from_playlist(pid, logger=self._log)
                if not track_uri:
                    self._last_error = "One-shot failed: could not extract track URI"
                    return None
                self._remember_track(pid, track_uri)
                self._last_play_time = time.time()
                self._last_query = pick.get("query", "")
                self._last_pick = pick
                self._last_error = ""
                display_name = item.get("name")
                if not display_name or display_name == self._last_query or "#" in display_name:
                    display_name = "Spotify Playlist"
                result = self._start_playback(uri, display_name, track_uri=track_uri,
                                              force=force_new or not self._session_locked)
                if result:
                    self._session_locked = True
                    result.update({
                        "query": pick.get("query", ""),
                        "pick_rank": 1,
                        "top_count": 1,
                        "pool": pool,
                    })
                    return result
                self._last_error = "One-shot desktop playback attempt failed"
                return None

            # Shuffle the pool for variety across multiple vetting sessions
            random.shuffle(pool)

            # Iterate through the pool and find the first candidate that passes vetting.
            # Verification is both metadata (Jina) and audio (the controller's kickstart loop).
            for pool_index, item in enumerate(pool[:6]):
                uri = item["uri"]
                pid = uri.split(":")[-1]
                item_name = item.get("name", "")[:60] or "Unknown"

                self._log(f"DEBUG: Pool item #{pool_index + 1}: {item_name} ({pid[:8]}...)")

                # Always fetch fresh from Jina (don't use cache) to ensure correct first track
                self._log(f"DEBUG: Fetching first track for {pid[:8]} via Jina...")
                track_uri = first_track_uri_from_playlist(pid, logger=self._log)

                if track_uri:
                    self._remember_track(pid, track_uri)
                    self._log(f"DEBUG: Found valid track for pool item #{pool_index + 1}, attempting playback...")

                    self._last_play_time = time.time()
                    self._last_query = pick.get("query", "")
                    self._last_pick = pick
                    self._last_error = ""

                    display_name = item.get("name")
                    if not display_name or display_name == self._last_query or "#" in display_name:
                        display_name = "Spotify Playlist"

                    result = self._start_playback(uri, display_name, track_uri=track_uri,
                                                force=force_new or not self._session_locked)
                    if result:
                        self._session_locked = True
                        self._log(f"DEBUG: Successfully started playback for pool item #{pool_index + 1}")
                        result.update({
                            "query": pick.get("query", ""),
                            "pick_rank": pool.index(item) + 1,
                            "top_count": len(pool),
                            "pool": pool,
                        })
                        return result
                    else:
                        self._log(f"DEBUG: Playback failed for pool item #{pool_index + 1}, trying next...")
                else:
                    self._log(f"Skipping {pid[:8]}... - tracks not readable via Jina (Age/Geo restricted or scraper error)")

            self._last_error = "None of the found playlists have readable track metadata."
            return None

    def search_and_play(self, query, type_="playlist", mood="chill", tags=None, game_name=""):
        return self.play_random_for_mood(
            mood=mood,
            query_hint=query,
            game_name=game_name,
            tags=tags or [],
        )

    def play_playlist(self, uri):
        uri = parse_spotify_uri(uri) if not uri.startswith("spotify:") else uri
        if not is_playlist_uri(uri):
            return False
        try:
            if uri in set(load_blocked_playlist_uris(self.data_dir) or []):
                self._last_error = "Playlist is blocked and will not be played"
                self._log(f"Blocked playlist skipped: {uri}")
                return False
        except Exception:
            pass
        return self._start_playback(uri, "Playlist") is not None

    def block_current_playlist(self, name: str = "", query: str = "") -> bool:
        if not self._last_uri:
            return False
        return block_playlist_uri(
            self.data_dir,
            self._last_uri,
            name or self._last_playlist_name,
            query or self._last_query,
        )

    def resume(self):
        return self.ensure_playing()

    def reset_session(self):
        self._session_locked = False
        self._paused_by_game = False
        self._is_playing = False
        self._playback_state_known = False

    def play(self, context_uri=None, uris=None):
        if context_uri:
            return self.play_playlist(context_uri)
        return self.ensure_playing()

    def pause(self):
        """Pause Spotify using media keys. Spotify stays in background, game keeps focus."""
        return self.ensure_paused()

    def force_pause(self):
        """Force pause using media keys (same as pause())."""
        return self.pause()

    def minimize_window(self):
        """Instantly hide all Spotify windows (super refresh) - SYNCHRONOUS."""
        if not IS_WINDOWS:
            return True
        try:
            _hide_spotify_windows(self._log)
            return True
        except Exception as ex:
            self._log(f"Could not hide Spotify: {ex}")
            return False

    def media_play_pause(self) -> bool:
        """Send media play/pause key (179)."""
        # Try SendInput first (global system), then fallback to PowerShell
        if self._send_input_media_key(VK_MEDIA_PLAY_PAUSE):
            return True
        return self._powershell_sendkeys(179)

    def media_stop(self) -> bool:
        """Send media stop key (178)."""
        if self._send_input_media_key(VK_MEDIA_STOP):
            return True
        return self._powershell_sendkeys(178)

    def media_next(self) -> bool:
        """Send media next track key (176)."""
        if self._send_input_media_key(VK_MEDIA_NEXT_TRACK):
            return True
        return self._powershell_sendkeys(176)

    def media_prev(self) -> bool:
        """Send media previous track key (177)."""
        if self._send_input_media_key(VK_MEDIA_PREV_TRACK):
            return True
        return self._powershell_sendkeys(177)

    @property
    def paused_by_game(self) -> bool:
        return self._paused_by_game

    def next_track(self):
        return True

    def prev_track(self):
        return True

    def set_volume(self, percent):
        return True

    def get_playback_state(self):
        state = self._local_is_playing()
        if state is not None:
            self._remember_playback_state(
                state,
                paused_by_game=(self._paused_by_game and not state),
            )
            return {"is_playing": state}
        return {"is_playing": self._is_playing}

    def get_current_track(self):
        data = self._local_status()
        if data:
            playing = None
            for key in ("playing", "is_playing"):
                if key in data:
                    playing = bool(data.get(key))
                    break
            if playing is None and "paused" in data:
                playing = not bool(data.get("paused"))
            if playing is not None:
                self._remember_playback_state(
                    playing,
                    paused_by_game=(self._paused_by_game and not playing),
                )

            track = data.get("track") or {}
            track_resource = track.get("track_resource") or {}
            artist_resource = track.get("artist_resource") or {}
            name = (
                track.get("name")
                or track_resource.get("name")
                or "Spotify"
            )
            artist = (
                track.get("artist")
                or artist_resource.get("name")
                or self._last_query[:40]
                or "Tag search"
            )
            try:
                progress_ms = int(float(data.get("playing_position", 0) or 0) * 1000)
            except (TypeError, ValueError):
                progress_ms = 0
            try:
                duration_ms = int(float(track.get("length", 0) or 0) * 1000)
            except (TypeError, ValueError):
                duration_ms = 0

            if playing or name != "Spotify":
                return {
                    "name": name,
                    "artist": artist,
                    "album_art": None,
                    "is_playing": bool(playing),
                    "progress_ms": progress_ms,
                    "duration_ms": duration_ms,
                    "uri": track_resource.get("uri") or self._last_track_uri or self._last_uri,
                    "playlist_uri": self._last_uri,
                    "context_uri": self._last_uri,
                }

        if not self._is_playing:
            return None
        return {
            "name": "Spotify",
            "artist": self._last_query[:40] or "Tag search",
            "album_art": None,
            "is_playing": True,
            "progress_ms": 0,
            "duration_ms": 0,
            "uri": self._last_uri,
            "playlist_uri": self._last_uri,
            "context_uri": self._last_uri,
        }

    def get_user_playlists(self):
        return load_saved_playlists(self.data_dir), ""

    def add_playlist_link(self, name: str, link_or_uri: str) -> tuple:
        uri = parse_spotify_uri(link_or_uri)
        if not uri:
            return False, "Paste a Spotify playlist link"
        pls = load_saved_playlists(self.data_dir)
        if any(p.get("uri") == uri for p in pls):
            return False, "Playlist already added"
        pls.append({"name": name.strip() or "My playlist", "uri": uri, "tracks": "—"})
        save_saved_playlists(self.data_dir, pls)
        return True, ""

    def remove_playlist_link(self, uri: str):
        pls = [p for p in load_saved_playlists(self.data_dir) if p.get("uri") != uri]
        save_saved_playlists(self.data_dir, pls)

    def get_devices(self):
        return [{"id": "desktop", "name": "Spotify Desktop", "is_active": True}]

    def transfer_playback(self, device_id):
        return True

    def click_playlist_play_button(self, playlist_name: str = None) -> bool:
        """
        Attempt to locate and click the green Play button in the Spotify desktop UI.
        Uses UI Automation via pywinauto (UIA backend). Falls back to media keys.

        If `playlist_name` is provided, we try to narrow the search to a window
        or pane that contains that text; otherwise we search the whole Spotify
        window for a Button whose name/text contains 'play' or 'resume'.
        Returns True if an invoke/click was attempted, False otherwise.
        """
        try:
            from pywinauto import Application, Desktop
        except Exception:
            # pywinauto not available — fallback to media key
            self._log("pywinauto not installed; using media key fallback")
            return bool(self.media_play_pause())

        try:
            app = Application(backend="uia").connect(path="Spotify.exe", timeout=3)
        except Exception:
            # Could not connect to process
            self._log("Could not connect to Spotify.exe via pywinauto")
            return bool(self.media_play_pause())

        try:
            # Try to find the main Spotify window
            desktop = Desktop(backend="uia")
            # Prefer a top-level window whose title contains 'Spotify'
            try:
                win = desktop.window(title_re=".*Spotify.*")
            except Exception:
                # Fallback to the application's top window
                win = app.top_window()

            # Scope search to a container matching the playlist name when provided
            search_root = win
            if playlist_name:
                try:
                    candidate = win.child_window(title_re=f".*{playlist_name}.*", control_type="Text")
                    if candidate.exists():
                        # climb to parent pane
                        search_root = candidate.parent()
                except Exception:
                    pass

            # Safer window handling: if Desktop.window(title_re=...) failed earlier,
            # ensure `search_root` is a valid element; fallback to app.top_window()
            try:
                # some Spotify builds nest controls in non-Button groups; prefer scanning all descendants
                _ = getattr(search_root, 'children', None)
            except Exception:
                try:
                    search_root = app.top_window()
                except Exception:
                    search_root = win

            # Search for elements that likely represent the Play control. Spotify's
            # play control is often a Group with a class_name like
            # 'main-playButton-PlayButton' (not a Button). First search for
            # any descendant whose class_name contains 'playbutton' (case-insensitive)
            # and click its center.
            try:
                for el in search_root.descendants():
                    try:
                        ei = el.element_info
                        c_name_raw = getattr(ei, 'class_name', '') or ''
                        c_name = c_name_raw.strip()

                        # PRIORITY: exact match for the known play-button class
                        if c_name == 'main-playButton-PlayButton':
                            try:
                                r = el.rectangle()
                                cx = (r.left + r.right) // 2
                                cy = (r.top + r.bottom) // 2
                                try:
                                    el.click_input(coords=(cx, cy))
                                except Exception:
                                    try:
                                        el.invoke()
                                    except Exception:
                                        try:
                                            el.wrapper_object().click_input()
                                        except Exception:
                                            pass
                                self._log(f"Clicked Play element via exact class_name: '{c_name_raw}'")
                                return True
                            except Exception:
                                continue

                        # Secondary: loose matches for other playbutton-like classes
                        c_name_l = c_name.lower()
                        if 'playbutton' in c_name_l or 'play-button' in c_name_l or 'play_button' in c_name_l:
                            try:
                                r = el.rectangle()
                                cx = (r.left + r.right) // 2
                                cy = (r.top + r.bottom) // 2
                                try:
                                    el.click_input(coords=(cx, cy))
                                except Exception:
                                    try:
                                        el.invoke()
                                    except Exception:
                                        try:
                                            el.wrapper_object().click_input()
                                        except Exception:
                                            pass
                                self._log(f"Clicked Play element via class_name match: '{c_name_raw}'")
                                return True
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass

            # Search for buttons that likely represent the hover Play control
            buttons = search_root.descendants(control_type="Button")

            # Priority 1: exact hover-tooltip e.g. 'Play {playlist_name}' or startswith 'Play '
            if playlist_name:
                target_text = f"play {playlist_name.lower()}"
                for b in buttons:
                    try:
                        name = (getattr(b.element_info, 'name', None) or "" ).strip().lower()
                        help_text = (getattr(b.element_info, 'help_text', None) or "").strip().lower()
                        if name == target_text or help_text == target_text or name.startswith('play '):
                            try:
                                # click center of control for reliability
                                rect = b.rectangle()
                                x = (rect.left + rect.right) // 2
                                y = (rect.top + rect.bottom) // 2
                                b.click_input(coords=(x, y))
                            except Exception:
                                try:
                                    b.invoke()
                                except Exception:
                                    try:
                                        b.click_input()
                                    except Exception:
                                        continue
                            self._log(f"Clicked Play tooltip/button: '{name or help_text}'")
                            return True
                    except Exception:
                        continue

            # Priority 2: any button whose name contains 'play' or 'resume'
            for b in buttons:
                try:
                    name = (getattr(b.element_info, 'name', None) or "").strip().lower()
                    help_text = (getattr(b.element_info, 'help_text', None) or "").strip().lower()
                    if 'play' in name or 'resume' in name or 'play' in help_text:
                        try:
                            b.invoke()
                        except Exception:
                            try:
                                b.click_input()
                            except Exception:
                                continue
                        self._log(f"Clicked Play button via UIA: {name or help_text}")
                        return True
                except Exception:
                    continue

            # Last-resort: try clicking any button with no text (image-only) near the playlist area
            for b in buttons:
                try:
                    name = (getattr(b.element_info, 'name', None) or "").strip()
                    if not name:
                        try:
                            b.click_input()
                            self._log("Clicked anonymous button as fallback")
                            return True
                        except Exception:
                            continue
                except Exception:
                    continue

        except Exception as e:
            self._log(f"UI automation error: {e}")

        # Fallback to global media key toggle
        self._log("Play button not found via UIA; using media key fallback")
        return bool(self.media_play_pause())
