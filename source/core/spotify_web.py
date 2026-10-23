"""
spotify_web.py — Spotify Web Player control without Web API (free accounts).

Dual mode (default):
  1. Spotify desktop app opens the playlist.
  2. One automated Google Chrome window plays the same playlist (no Player Chrome, no Connect).

Set spotify_use_connect=true to restore the old multi-window Connect flow.
Legacy playwright mode: one automated browser opens the playlist directly.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import random
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.playlist_search import (
    pick_random_playlist_uri,
    build_search_query,
    block_playlist_uri,
    load_blocked_playlist_uris,
)
from core.spotify_desktop import (
    SpotifyDesktopController,
    _spotify_running,
    is_playlist_uri,
    parse_spotify_uri,
    load_saved_playlists,
    save_saved_playlists,
)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    PlaywrightTimeoutError = Exception

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    VK_MEDIA_PLAY_PAUSE = 0xB3
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_EXTENDEDKEY = 0x0001
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_ulonglong),
        ]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_ulonglong),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("_u", _INPUT_UNION)]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Playlist page Play button (override in config / spotify_web.json).
DEFAULT_PLAYLIST_PLAY_XPATH = (
    '//*[@id="main-view"]/div/div[2]/div[1]/div/main/section/div[2]/div[2]/div[1]/div/div/div[1]/button'
)
PLAYLIST_PLAY_SPAN_XPATH = (
    '//*[@id="main-view"]/div/div[2]/div[1]/div/main/section/div[2]/div[2]/div[1]/div/div/div[1]/button/span'
)
PLAYER_PLAYPAUSE_SELECTOR = '[data-testid="control-button-playpause"]'
PLAYLIST_PLAY_FALLBACKS = (
    '[data-testid="play-button"]',
    'button[aria-label*="Play"]',
)

# Controller browser — Spotify Connect (sidebar + device list).
DEFAULT_CONNECT_DEVICE_XPATH = (
    '//*[@id="main"]/div/div[2]/div[5]/aside/div[1]/div[3]/div/span/button'
)
DEFAULT_CONNECT_DEVICE_ICON_XPATH = (
    '//*[@id="main"]/div/div[2]/div[5]/aside/div[1]/div[3]/div/span/button/span/svg/path'
)
DEFAULT_PLAYER_DEVICE_ROW_XPATH = (
    '//*[@id="Desktop_PanelContainer_Id"]/div/div[2]/div[1]/div/div/div[2]/div/div[1]/ul/li[1]/div/div[1]'
)
CONNECT_DEVICE_LABEL = re.compile(r"Web Player\s*\((Chrome|Chromium)\)", re.I)
CONNECT_DEVICE_SKIP = re.compile(
    r"web player|this web player|chrome|safari|firefox|edge|iphone|android|tablet|tv",
    re.I,
)
DEFAULT_BYPASS_MAIN_BUTTON_XPATH = '//*[@id="main"]/div/button/span'
GO_BACK_LABEL = re.compile(r"go back to previous site|back to previous", re.I)
BYPASS_CLICK_MS = 900
BYPASS_VISIBLE_MS = 1500

# Runs before any page script — hide common automation signals Spotify checks.
STEALTH_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
  } catch (e) {}
  try {
    if (!window.chrome) {
      window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {} };
    }
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  } catch (e) {}
  try {
    const q = window.navigator.permissions && window.navigator.permissions.query;
    if (q) {
      window.navigator.permissions.query = (parameters) => (
        parameters && parameters.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : q(parameters)
      );
    }
  } catch (e) {}
})();
"""


def playlist_uri_to_url(uri: str) -> str:
    """Build https://open.spotify.com/playlist/{id} from URI or web link."""
    text = (uri or "").strip()
    if not text:
        return ""
    parsed = parse_spotify_uri(text)
    if parsed:
        pid = parsed.split(":")[-1]
        return f"https://open.spotify.com/playlist/{pid}"
    m = re.search(
        r"(?:https?://)?open\.spotify\.com/playlist/([a-zA-Z0-9]+)|spotify:playlist:([a-zA-Z0-9]+)",
        text,
        re.I,
    )
    if m:
        pid = m.group(1) or m.group(2)
        return f"https://open.spotify.com/playlist/{pid}"
    return ""


def _send_global_media_play_pause() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        inputs = (
            _INPUT(type=INPUT_KEYBOARD, _u=_INPUT_UNION(ki=_KEYBDINPUT(VK_MEDIA_PLAY_PAUSE, 0, 0, 0, 0))),
            _INPUT(
                type=INPUT_KEYBOARD,
                _u=_INPUT_UNION(
                    ki=_KEYBDINPUT(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP | KEYEVENTF_EXTENDEDKEY, 0, 0)
                ),
            ),
        )
        arr = (_INPUT * len(inputs))(*inputs)
        sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
        return sent == len(inputs)
    except Exception:
        return False


def _hide_hwnd_from_taskbar(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        target = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if target != style:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, target)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception:
        return False


class SpotifyWebController:
    """Spotify Web Player via Playwright — drop-in for SpotifyDesktopController."""

    def __init__(
        self,
        data_dir: str,
        logger=None,
        gamebeats_hwnd: int = 0,
        headless: bool | None = None,
        play_xpath: str | None = None,
        hide_window: bool = True,
        cdp_url: str | None = None,
    ):
        self._log = logger if logger else (lambda msg: print(f"[SpotifyWeb] {msg}"))
        self.data_dir = data_dir
        self._gamebeats_hwnd = gamebeats_hwnd
        self._profile_dir = os.path.abspath(os.path.join(data_dir, "spotify_web_profile"))
        self._player_profile_dir = os.path.abspath(
            os.path.join(data_dir, "spotify_chrome_player_profile")
        )
        os.makedirs(self._profile_dir, exist_ok=True)
        os.makedirs(self._player_profile_dir, exist_ok=True)

        cfg = self._load_web_config()
        self._dual_chrome = str(cfg.get("spotify_web_mode", "dual_chrome")).lower() != "playwright"
        player = str(cfg.get("spotify_dual_player", "chrome")).lower().strip()
        if player in ("chrome", "web", "browser"):
            self._dual_player = "chrome"
        elif player == "desktop":
            self._dual_player = "desktop"
        else:
            self._dual_player = "chromium"
        self._also_launch_desktop = bool(cfg.get("spotify_also_launch_desktop", True))
        self._use_spotify_connect = bool(cfg.get("spotify_use_connect", False))
        self._connect_device_name = (cfg.get("spotify_connect_device_name") or "").strip()
        try:
            self._controller_delay_sec = float(cfg.get("spotify_controller_delay_sec", 3))
        except (TypeError, ValueError):
            self._controller_delay_sec = 3.0
        self._controller_delay_sec = max(1.0, min(15.0, self._controller_delay_sec))
        # Spotify needs Widevine DRM — bundled Playwright Chromium usually cannot play audio.
        self._use_system_chrome = bool(cfg.get("use_system_chrome", True))
        self._ui_bypass = bool(cfg.get("spotify_ui_bypass", True))
        self._cdp_url = (cdp_url or cfg.get("spotify_web_cdp_url") or cfg.get("cdp_url") or "").strip()
        self._headless = bool(headless) if headless is not None else bool(cfg.get("headless", False))
        # show_browser in config overrides hide_window (for testing)
        if "show_browser" in cfg:
            self._hide_window = not bool(cfg.get("show_browser"))
        else:
            self._hide_window = bool(cfg.get("hide_window", hide_window))
        self._play_xpath = (play_xpath or cfg.get("play_xpath") or DEFAULT_PLAYLIST_PLAY_XPATH).strip()
        self._connect_device_xpath = (
            cfg.get("spotify_connect_device_xpath") or DEFAULT_CONNECT_DEVICE_XPATH
        ).strip()
        self._connect_device_icon_xpath = (
            cfg.get("spotify_connect_device_icon_xpath") or DEFAULT_CONNECT_DEVICE_ICON_XPATH
        ).strip()
        self._player_device_row_xpath = (
            cfg.get("spotify_player_device_row_xpath") or DEFAULT_PLAYER_DEVICE_ROW_XPATH
        ).strip()
        self._bypass_main_button_xpath = (
            cfg.get("spotify_bypass_main_button_xpath") or DEFAULT_BYPASS_MAIN_BUTTON_XPATH
        ).strip()
        try:
            self._bypass_wait_sec = float(cfg.get("spotify_bypass_wait_sec", 2))
        except (TypeError, ValueError):
            self._bypass_wait_sec = 2.0
        try:
            self._bypass_before_connect_sec = float(
                cfg.get("spotify_bypass_before_connect_sec", 1)
            )
        except (TypeError, ValueError):
            self._bypass_before_connect_sec = 1.0
        try:
            self._play_followup_sec = float(cfg.get("spotify_play_followup_sec", 2))
        except (TypeError, ValueError):
            self._play_followup_sec = 2.0
        try:
            self._play_audio_check_sec = float(cfg.get("spotify_play_audio_check_sec", 6))
        except (TypeError, ValueError):
            self._play_audio_check_sec = 6.0

        self._desktop_player = None
        self._desktop_sidecar_active = False
        self._last_error = ""
        self._last_play_method = ""
        self._is_playing = False
        self._playback_state_known = False
        self._last_uri = ""
        self._last_track_uri = ""
        self._last_query = ""
        self._last_pick = {}
        self._last_playlist_name = ""
        self._play_lock = threading.RLock()
        self._browser_lock = threading.Lock()
        self._login_checked = False
        self._last_play_time = 0.0
        self._paused_by_game = False
        self._session_locked = False
        # "browser" or "desktop" — remembered so resume targets the source
        # that was actually audible before the game audio paused it.
        self._last_audio_source = "browser"

        self._pw = None
        self._context = None
        self._page = None
        self._player_context = None
        self._player_page = None
        self._browser_launched_at = 0.0

        # Audio routing is configured by _refresh_audio_pids() once the browser
        # and player mode are known. Do not force desktop audio here: in web
        # mode the actual music is produced by the automated browser, while the
        # desktop client may be a silent sidecar.

        # Playwright sync API must run on one thread only (not UI + game threads).
        self._browser_queue = queue.Queue()
        self._browser_thread_id = None
        self._browser_thread_ready = threading.Event()
        self._browser_thread = threading.Thread(
            target=self._browser_thread_loop,
            name="GameBeats-SpotifyWeb",
            daemon=True,
        )
        self._browser_thread.start()
        if not self._browser_thread_ready.wait(timeout=15):
            self._log("Warning: Spotify web browser thread did not start in time.")

    def _send_global_media_key(self, source: str) -> bool:
        """Send the global media Play/Pause key and log the source.

        Returns True on success.
        """
        ok = _send_global_media_play_pause()
        try:
            self._log(f"[{source}] global media Play/Pause key sent: {'OK' if ok else 'FAILED'}")
        except Exception:
            pass
        return ok

    def _uses_desktop_player(self) -> bool:
        return self._dual_chrome and self._dual_player == "desktop"

    def _uses_chromium_player(self) -> bool:
        return self._dual_chrome and self._dual_player == "chromium"

    def _uses_browser_player(self) -> bool:
        return self._dual_chrome and self._dual_player in ("chrome", "chromium")

    def _prefer_desktop_connect(self) -> bool:
        return self._uses_desktop_player() or (
            self._desktop_sidecar_active and self._use_spotify_connect
        )

    def _use_simplified_dual_flow(self) -> bool:
        """Spotify desktop + one automated browser; play playlist (no Connect)."""
        return self._dual_chrome and not self._use_spotify_connect

    def _desktop_helper(self) -> SpotifyDesktopController:
        if self._desktop_player is None:
            self._desktop_player = SpotifyDesktopController(
                self.data_dir,
                logger=self._log,
                gamebeats_hwnd=self._gamebeats_hwnd,
            )
        return self._desktop_player

    @staticmethod
    def _computer_device_name() -> str:
        return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "").strip()

    def _browser_thread_loop(self):
        self._browser_thread_id = threading.get_ident()
        self._browser_thread_ready.set()
        while True:
            job = self._browser_queue.get()
            if job is None:
                break
            fn, done_event, out, err_box = job
            try:
                out[0] = fn()
            except Exception as ex:
                err_box[0] = ex
            finally:
                done_event.set()

    def _browser_call(self, fn, timeout=120, default=None):
        """Run fn on the dedicated Playwright thread."""
        if self._browser_thread_id and threading.get_ident() == self._browser_thread_id:
            return fn()
        done = threading.Event()
        out = [None]
        err_box = [None]
        self._browser_queue.put((fn, done, out, err_box))
        if not done.wait(timeout):
            self._last_error = "Browser operation timed out"
            self._log(self._last_error)
            return default
        if err_box[0] is not None:
            self._last_error = str(err_box[0])
            self._log(f"Web player error: {err_box[0]}")
            return default
        return out[0]

    def _load_web_config(self) -> dict:
        path = os.path.join(self.data_dir, "spotify_web.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_web_config(self, **kwargs):
        data = self._load_web_config()
        data.update(kwargs)
        path = os.path.join(self.data_dir, "spotify_web.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if "play_xpath" in kwargs:
            self._play_xpath = str(kwargs["play_xpath"]).strip() or DEFAULT_PLAYLIST_PLAY_XPATH
        if "headless" in kwargs:
            self._headless = bool(kwargs["headless"])

    def set_play_xpath(self, xpath: str):
        self._play_xpath = (xpath or DEFAULT_PLAYLIST_PLAY_XPATH).strip()
        self.save_web_config(play_xpath=self._play_xpath)

    @staticmethod
    def normalize_playlist_uri(ref: str) -> str:
        text = (ref or "").strip()
        if not text:
            return ""
        parsed = parse_spotify_uri(text)
        if parsed:
            return parsed
        if text.startswith("spotify:playlist:") and is_playlist_uri(text):
            return text
        return ""

    def _browser_args(self) -> list:
        args = [
            "--disable-blink-features=AutomationControlled",
            "--autoplay-policy=no-user-gesture-required",
            "--exclude-switches=enable-automation",
            "--disable-infobars",
            # A previous run can leave Chrome showing the off-screen
            # "Restore pages?" bubble.  Playwright's first goto then waits
            # until it times out because the modal owns the browser UI.
            "--hide-crash-restore-bubble",
            "--disable-session-crashed-bubble",
        ]
        if not self._headless and self._hide_window:
            # Keep the window off-screen but prevent Chrome from throttling
            # background tabs (otherwise playlist UI loads slowly and clicks miss).
            args.extend([
                "--window-position=-32000,-32000",
                "--window-size=960,720",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ])
        return args

    def _automation_browser_pids(self) -> set[int]:
        if not (IS_WINDOWS and HAS_PSUTIL and self._hide_window):
            return set()
        return self._automation_browser_window_pids()

    def _automation_browser_window_pids(self) -> set[int]:
        """Chrome PIDs for this app's profile(s), even before hide_window is set."""
        if not (IS_WINDOWS and HAS_PSUTIL):
            return set()
        markers = {
            os.path.normcase(self._profile_dir),
            os.path.normcase(os.path.basename(self._profile_dir)),
            os.path.normcase(self._player_profile_dir),
            os.path.normcase(os.path.basename(self._player_profile_dir)),
        }
        pids = set()
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name not in ("chrome.exe", "chromium.exe", "msedge.exe"):
                        continue
                    cmd = os.path.normcase(" ".join(proc.info.get("cmdline") or []))
                    if any(marker and marker in cmd for marker in markers):
                        pids.add(int(proc.info["pid"]))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        return pids

    def _for_each_automation_browser_hwnd(self, fn) -> None:
        if not IS_WINDOWS:
            return
        pids = self._automation_browser_window_pids()
        if not pids:
            return

        @_WNDENUMPROC
        def _enum(hwnd, lparam):
            del lparam
            try:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) in pids:
                    fn(hwnd)
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(_enum, 0)
        except Exception:
            pass

    def _move_automation_browser_offscreen(self) -> None:
        if not IS_WINDOWS:
            return

        def _move(hwnd):
            try:
                user32.SetWindowPos(
                    hwnd,
                    0,
                    -32000,
                    -32000,
                    960,
                    720,
                    SWP_NOACTIVATE | SWP_FRAMECHANGED,
                )
            except Exception:
                pass

        self._for_each_automation_browser_hwnd(_move)

    def _hide_automation_browser_taskbar_icons(self) -> None:
        if not (IS_WINDOWS and self._hide_window):
            return

        def _hide(hwnd):
            _hide_hwnd_from_taskbar(hwnd)

        self._for_each_automation_browser_hwnd(_hide)

    def _start_taskbar_hide_watch(self, attempts: int = 8, delay: float = 0.35) -> None:
        if not (IS_WINDOWS and self._hide_window):
            return

        def _work():
            for _ in range(max(1, int(attempts))):
                self._hide_automation_browser_taskbar_icons()
                time.sleep(max(0.05, float(delay)))

        threading.Thread(
            target=_work,
            name="GameBeats-BrowserTaskbarHide",
            daemon=True,
        ).start()

    def _chromium_launch_kwargs(self) -> dict:
        kwargs = dict(
            headless=self._headless,
            args=self._browser_args(),
            locale="en-US",
            # Playwright adds --disable-component-update by default. Chrome
            # ships Widevine as a component, so leaving that switch in place
            # makes Spotify's web player report "Unsupported keySystem" and
            # play silently. Removing it lets Chrome load Widevine.
            ignore_default_args=["--enable-automation", "--disable-component-update"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        return kwargs

    def _apply_stealth(self, page=None) -> None:
        if self._context:
            try:
                self._context.add_init_script(STEALTH_INIT_SCRIPT)
            except Exception:
                pass
        targets = [page] if page else []
        if self._context:
            try:
                targets.extend([p for p in self._context.pages if not p.is_closed()])
            except Exception:
                pass
        for pg in targets:
            if not pg:
                continue
            try:
                session = self._context.new_cdp_session(pg)
                session.send(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": STEALTH_INIT_SCRIPT},
                )
            except Exception:
                pass

    def _connect_via_cdp(self) -> bool:
        url = self._cdp_url
        if not url:
            return False
        try:
            if not self._pw:
                self._pw = sync_playwright().start()
            browser = self._pw.chromium.connect_over_cdp(url)
            self._context = browser.contexts[0] if browser.contexts else browser.new_context()
            self._page = None
            for p in self._context.pages:
                if not p.is_closed():
                    self._page = p
                    break
            if not self._page:
                self._page = self._context.new_page()
            self._apply_stealth(self._page)
            self._grant_spotify_permissions()
            self._last_play_method = "cdp"
            self._browser_launched_at = time.time()
            self._refresh_audio_pids()
            self._log(
                f"Connected to your normal Chrome ({url}) — Spotify sees a regular browser."
            )
            return True
        except Exception as ex:
            self._last_error = f"CDP connect failed: {ex}"
            self._log(
                f"{self._last_error}  Start Chrome with remote debugging (see config spotify_web_cdp_url)."
            )
            return False

    def _grant_spotify_permissions(self):
        if not self._context:
            return
        try:
            self._context.grant_permissions(
                ["autoplay"],
                origin="https://open.spotify.com",
            )
        except Exception:
            pass

    def _browser_player_is_audio_source(self) -> bool:
        """True when the automated browser is the component producing audio.

        In the simplified dual flow a desktop Spotify process may still be
        running, but it only plays a silent track (device detection). Listening
        to spotify.exe in that situation makes the app believe playback ended
        while Chrome is actually playing.
        """
        try:
            if self._uses_desktop_player():
                return False
            if self._desktop_sidecar_active and self._use_spotify_connect:
                return False
            return True
        except Exception:
            return True

    def _find_browser_audio_pids(self) -> list:
        """Find Chrome/Edge processes hosting this app's Spotify web player."""
        if not HAS_PSUTIL:
            return []
        markers = {
            os.path.normcase(self._profile_dir),
            os.path.normcase(os.path.basename(self._profile_dir)),
            os.path.normcase(self._player_profile_dir),
            os.path.normcase(os.path.basename(self._player_profile_dir)),
        }
        pids = set()
        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name not in ("chrome.exe", "chromium.exe", "msedge.exe"):
                        continue
                    cmd = os.path.normcase(" ".join(proc.info.get("cmdline") or []))
                    if any(marker and marker in cmd for marker in markers):
                        pids.add(int(proc.info["pid"]))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        return sorted(pids)

    def refresh_audio_source(self):
        """Public hook so the app can re-point the audio monitor safely."""
        self._refresh_audio_pids()

    def _refresh_audio_pids(self):
        self._hide_automation_browser_taskbar_icons()
        try:
            from core.audio_monitor import (
                register_music_player_pids,
                set_browser_audio_only,
            )
        except Exception:
            return

        if self._browser_player_is_audio_source():
            pids = self._find_browser_audio_pids()
            set_browser_audio_only(True)
            register_music_player_pids(pids)
            if pids:
                self._log(
                    f"Audio monitor: listening to web-player browser PIDs {pids}"
                )
            else:
                self._log(
                    "Audio monitor: browser running but no player PIDs matched yet"
                )
            return

        # Desktop player (legacy Connect mode) — monitor spotify.exe.
        set_browser_audio_only(False)
        register_music_player_pids([])
        self._log("Audio monitor: listening to Spotify desktop (spotify.exe)")

    def _ensure_browser(self, check_login: bool = False) -> bool:
        return bool(
            self._browser_call(
                lambda: self._ensure_browser_impl(check_login),
                default=False,
            )
        )

    def _ensure_browser_impl(self, check_login: bool = False) -> bool:
        with self._browser_lock:
            if self._page and not self._page.is_closed():
                return True

            # Reuse open browser profile — do not close context (keeps Spotify login).
            if self._context:
                try:
                    for p in self._context.pages:
                        if not p.is_closed():
                            self._page = p
                            self._refresh_audio_pids()
                            return True
                    self._page = self._context.new_page()
                    self._refresh_audio_pids()
                    return True
                except Exception:
                    try:
                        self._context.close()
                    except Exception:
                        pass
                    self._context = None

            if not HAS_PLAYWRIGHT:
                self._last_error = "Playwright not installed. Run: pip install playwright && playwright install chromium"
                return False
            if self._cdp_url and self._connect_via_cdp():
                if check_login and not self._login_checked:
                    self._login_checked = True
                return True

            launch_kwargs = dict(
                headless=self._headless,
                args=self._browser_args(),
                locale="en-US",
                # Playwright adds --disable-component-update by default. Chrome
            # ships Widevine as a component, so leaving that switch in place
            # makes Spotify's web player report "Unsupported keySystem" and
            # play silently. Removing it lets Chrome load Widevine.
            ignore_default_args=["--enable-automation", "--disable-component-update"],
                no_viewport=not self._headless,
            )
            try:
                if not self._pw:
                    self._pw = sync_playwright().start()
                visible = not self._headless and not self._hide_window
                self._log(
                    f"Starting Spotify web player… profile: {self._profile_dir} "
                    + ("(visible)." if visible else "(hidden).")
                )
                self._log("Stealth mode on — browser should look like normal Chrome to sites.")
                self._log("Your Spotify login is stored in that profile folder between runs.")
                self._browser_launched_at = time.time()
                launched = False
                if self._use_system_chrome:
                    try:
                        self._context = self._pw.chromium.launch_persistent_context(
                            self._profile_dir,
                            channel="chrome",
                            **launch_kwargs,
                        )
                        self._log(
                            "Using installed Google Chrome (Widevine + less bot detection)."
                        )
                        launched = True
                    except Exception as ex:
                        self._log(
                            f"Google Chrome launch failed ({ex}) — falling back to bundled Chromium."
                        )
                if not launched:
                    launch_kwargs.pop("no_viewport", None)
                    chromium_kw = self._chromium_launch_kwargs()
                    chromium_kw["args"] = launch_kwargs.get("args", chromium_kw["args"])
                    self._context = self._pw.chromium.launch_persistent_context(
                        self._profile_dir,
                        **chromium_kw,
                    )
                    self._log(
                        "Using Playwright Chromium for controller (no menu/go-back bypass)."
                    )
                self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
                self._apply_stealth(self._page)
                self._grant_spotify_permissions()
                self._last_play_method = "playwright"
                self._start_taskbar_hide_watch()
                time.sleep(0.3)
                self._refresh_audio_pids()
                if visible and self._page:
                    try:
                        self._page.bring_to_front()
                    except Exception:
                        pass
                if check_login and not self._login_checked:
                    self._ensure_logged_in()
                    self._login_checked = True
                return True
            except Exception as ex:
                self._last_error = f"Could not start browser: {ex}"
                self._log(self._last_error)
                return False

    def _ensure_logged_in(self):
        if not self._page:
            return
        try:
            self._page.goto("https://open.spotify.com/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(1.5)
            if self._page.locator('button[data-testid="login-button"]').count() > 0:
                self._log(
                    "Log in to Spotify in the GameBeats browser window (one time). "
                    "Playback will work after that."
                )
        except Exception as ex:
            self._log(f"Login check: {ex}")

    def _page_has_login_prompt(self, page) -> bool:
        try:
            if page.locator('button[data-testid="login-button"]').count() > 0:
                return True
        except Exception:
            pass
        try:
            return page.get_by_role("button", name=re.compile(r"log in|login", re.I)).count() > 0
        except Exception:
            pass
        # Check the navbar login button via XPath (Spotify's top-right login)
        try:
            navbar_login_xpath = '//*[@id="global-nav-bar"]/div[3]/div/div[2]/button[2]/span'
            if page.locator(f"xpath={navbar_login_xpath}").count() > 0:
                return True
        except Exception:
            pass
        return False

    def _browser_login_ready_impl(self) -> bool:
        old_hide = self._hide_window
        try:
            if not self._ensure_browser_impl(False):
                return False
            page = self._page
            if not page:
                return False
            page.goto("https://open.spotify.com/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2.0)
            try:
                page.bring_to_front()
            except Exception:
                pass
            return not self._page_has_login_prompt(page)
        except Exception as ex:
            self._last_error = f"Spotify login check failed: {ex}"
            return False
        finally:
            self._hide_window = old_hide

    def open_login_window(self) -> bool:
        def _work():
            old_hide = self._hide_window
            self._hide_window = False
            try:
                # If the browser was previously running hidden, we must close it completely
                # so that a new, visible browser instance is created. Otherwise the login
                # window will open but remain completely hidden to the user.
                if old_hide:
                    self._close_browser_impl()

                if not self._ensure_browser_impl(False):
                    return False
                page = self._page
                if not page:
                    return False
                page.goto("https://open.spotify.com/", wait_until="domcontentloaded", timeout=60000)
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                self._log("Spotify login window opened.")
                return True
            finally:
                self._hide_window = old_hide

        return bool(self._browser_call(_work, timeout=90, default=False))

    def browser_login_ready(self) -> bool:
        return bool(self._browser_call(self._browser_login_ready_impl, timeout=90, default=False))

    def check_login_silently(self) -> bool:
        """Check Spotify login status in a hidden browser without showing any window.

        Returns True if the user IS logged in (no login button found).
        Returns False if the login button is detected (session expired / not logged in).
        The browser instance is closed after the check.
        """
        def _work():
            try:
                if not self._ensure_browser_impl(False):
                    return True
                page = self._page
                if not page:
                    return True
                page.goto(
                    "https://open.spotify.com/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                time.sleep(2.5)
                needs_login = self._page_has_login_prompt(page)
                if needs_login:
                    self._log("Silent login check: login button found — session expired.")
                else:
                    self._log("Silent login check: user is logged in.")
                return not needs_login
            except Exception as ex:
                self._log(f"Silent login check error: {ex}")
                return True
            finally:
                # Close only the tab used for the check, not the whole browser
                try:
                    if self._page and not self._page.is_closed():
                        self._page.close()
                        self._page = None
                except Exception:
                    pass

        return bool(self._browser_call(_work, timeout=60, default=True))

    def _run_on_page(self, fn, timeout: float = 60.0):
        def _inner():
            if not self._ensure_browser_impl(False):
                self._log(f"Web player: browser not available — {self._last_error}")
                return None
            try:
                return fn(self._page)
            except PlaywrightTimeoutError as ex:
                self._last_error = f"Browser timeout: {ex}"
                return None
            except Exception as ex:
                self._last_error = str(ex)
                self._log(f"Web player error: {ex}")
                return None

        return self._browser_call(_inner, timeout=timeout, default=None)

    @staticmethod
    def _is_xpath_selector(selector: str) -> bool:
        s = (selector or "").strip()
        return (
            s.startswith("//")
            or s.startswith("(/")
            or s.startswith("/html")
            or (s.startswith("/") and "[@" in s)
        )

    def _click_locator(self, page, selector: str, use_xpath: bool = False) -> bool:
        try:
            sel = (selector or "").strip()
            as_xpath = use_xpath or self._is_xpath_selector(sel)
            loc = page.locator(f"xpath={sel}" if as_xpath else sel).first
            loc.wait_for(state="visible", timeout=8000)
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
            return True
        except Exception as ex:
            self._last_error = f"Click failed ({selector[:40]}): {ex}"
            return False

    def _wait_for_playlist_ready(self, page, max_wait: float = 12.0) -> bool:
        """Wait until playlist shell or Play button is visible (no fixed 5s sleep)."""
        selectors = [
            f"xpath={self._play_xpath}",
            f"xpath={PLAYLIST_PLAY_SPAN_XPATH}",
            '#main-view button[data-testid="play-button"]',
            'button[data-testid="play-button"]',
            "#main-view",
            '[data-testid="playlist-page"]',
        ]
        deadline = time.time() + max_wait
        while time.time() < deadline:
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        self._log(f"Playlist page ready ({sel[:50]})")
                        return True
                except Exception:
                    pass
            time.sleep(0.1)
        self._log("Playlist page slow to load — will still try Play click")
        return False

    def _check_widevine(self, page) -> str:
        try:
            return page.evaluate(
                """async () => {
                if (!navigator.requestMediaKeySystemAccess) {
                    return 'no-widevine-api';
                }
                try {
                    await navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
                        initDataTypes: ['cenc'],
                        audioCapabilities: [{
                            contentType: 'audio/mp4; codecs="mp4a.40.2"',
                            robustness: 'SW_SECURE_CRYPTO',
                        }],
                    }]);
                    return 'widevine-ok';
                } catch (e) {
                    return 'widevine-blocked:' + (e && e.message ? e.message : String(e));
                }
            }"""
            ) or ""
        except Exception as ex:
            return f"widevine-check-error:{ex}"

    def _log_spotify_playback_issues(self, page) -> None:
        wv = self._check_widevine(page)
        if wv and wv != "widevine-ok":
            self._log(f"Spotify DRM check: {wv} — install Google Chrome if audio never plays.")
        try:
            body = (page.locator("body").inner_text(timeout=4000) or "").lower()
            for phrase in (
                "listening on another device",
                "listen on web player",
                "spotify premium",
                "can't play",
                "playback isn't supported",
                "enable playback in your browser",
                "use the spotify app",
            ):
                if phrase in body:
                    self._log(f"Spotify page says: «{phrase}»")
        except Exception:
            pass

    def _find_chrome_exe(self) -> str:
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in candidates:
            if path and os.path.isfile(path):
                return path
        return ""

    def _launch_player_desktop(self, playlist_uri: str) -> bool:
        """Open playlist in Spotify desktop app (shows reliably in Connect)."""
        uri = self.normalize_playlist_uri(playlist_uri)
        if not uri.startswith("spotify:playlist:"):
            self._last_error = "Invalid playlist URI"
            return False
        desktop = self._desktop_helper()
        if not desktop._find_spotify_exe():
            self._last_error = (
                "Spotify desktop app not found — install from spotify.com/download"
            )
            return False
        if not _spotify_running():
            desktop.launch_spotify()
        method = desktop._open_in_spotify(uri)
        if not method:
            self._last_error = desktop._last_error or "Could not open playlist in Spotify"
            return False
        self._last_play_method = "spotify-desktop"
        self._log(f"Spotify desktop → {uri}")
        return True

    def _nudge_player_desktop_playback(self) -> None:
        time.sleep(2.0)
        for i in range(3):
            self._send_global_media_key("_nudge_player_desktop_playback")
            time.sleep(0.4)
            if i == 0:
                self._log("Sent play to Spotify desktop (media key)…")

    def _ensure_desktop_playing_initial(self, attempts: int = 3, delay: float = 0.35) -> bool:
        """Quickly ensure the Spotify desktop client is producing audio.

        If no audio is detected, attempt to resume playback on the desktop client
        a few times (desktop command, then global media key) before returning.
        """
        try:
            from core.audio_monitor import get_spotify_loopback_peak
            threshold = 0.002
        except Exception:
            return False

        # Refresh audio PIDs so loopback targets spotify.exe
        try:
            self._refresh_audio_pids()
        except Exception:
            pass

        try:
            peak, db, status = get_spotify_loopback_peak()
            if status == "ok" and peak > threshold:
                self._log(f"Desktop audio already playing (peak={peak:.4f})")
                return True
        except Exception:
            pass

        # Try desktop controller resume first, fallback to global key
        for attempt in range(attempts):
            try:
                try:
                    desktop = self._desktop_helper()
                    self._log("Calling desktop.ensure_playing from _ensure_desktop_playing_initial")
                    if desktop.ensure_playing():
                        time.sleep(0.25)
                        peak, db, status = get_spotify_loopback_peak()
                        if status == "ok" and peak > threshold:
                            self._log(f"Desktop resumed via controller (peak={peak:.4f})")
                            return True
                except Exception:
                    pass
                # global media key fallback
                self._send_global_media_key("_ensure_desktop_playing_initial:global_fallback")
                time.sleep(delay)
                peak, db, status = get_spotify_loopback_peak()
                if status == "ok" and peak > threshold:
                    self._log(f"Desktop resumed via global media key (peak={peak:.4f})")
                    return True
            except Exception:
                pass

        self._log("Desktop initial play check: no audio detected after resume attempts")
        return False

    def _wait_for_player_desktop_audio(self, timeout: float = 12.0) -> bool:
        self._refresh_audio_pids()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                from core.audio_monitor import get_spotify_loopback_peak
                peak, _, status = get_spotify_loopback_peak()
                if status == "ok" and peak > 0.002:
                    self._log(f"Spotify desktop is playing music (peak={peak:.4f})")
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        self._log("Spotify desktop audio not detected — click Play in the app if needed.")
        return False

    def _ensure_player_chromium_context(self) -> bool:
        if not HAS_PLAYWRIGHT:
            self._last_error = "Playwright not installed"
            return False
        if self._player_context:
            try:
                if self._player_page and not self._player_page.is_closed():
                    return True
                for p in self._player_context.pages:
                    if not p.is_closed():
                        self._player_page = p
                        return True
                self._player_page = self._player_context.new_page()
                return True
            except Exception:
                try:
                    self._player_context.close()
                except Exception:
                    pass
                self._player_context = None
                self._player_page = None
        if not self._pw:
            self._pw = sync_playwright().start()
        try:
            self._player_context = self._pw.chromium.launch_persistent_context(
                self._player_profile_dir,
                **self._chromium_launch_kwargs(),
            )
            self._player_page = (
                self._player_context.pages[0]
                if self._player_context.pages
                else self._player_context.new_page()
            )
            self._apply_stealth(self._player_page)
            self._browser_launched_at = time.time()
            self._start_taskbar_hide_watch()
            self._log(
                f"Player Chromium → profile: spotify_chrome_player_profile"
            )
            return True
        except Exception as ex:
            self._last_error = f"Could not start Player Chromium: {ex}"
            return False

    def _launch_player_chromium_impl(self, url: str) -> bool:
        if not self._ensure_player_chromium_context():
            return False
        page = self._player_page
        if not page:
            return False
        page.goto(url, wait_until="commit", timeout=30000)
        self._wait_for_playlist_ready(page, max_wait=12.0)
        if not self._click_playlist_play_button(page):
            self._log("Player Chromium: Play button not found — trying media key…")
        self._last_play_method = "playwright-chromium-player"
        self._log(f"Player Chromium → {url}")
        return True

    def _launch_player_chromium(self, url: str) -> bool:
        return bool(
            self._browser_call(lambda: self._launch_player_chromium_impl(url), default=False)
        )

    def _launch_player_chrome(self, url: str) -> bool:
        """Launch normal Google Chrome (not Playwright) at a playlist URL."""
        exe = self._find_chrome_exe()
        if not exe:
            self._last_error = "Google Chrome not found — install Chrome for Spotify playback."
            return False
        try:
            flags = subprocess.DETACHED_PROCESS if IS_WINDOWS else 0
            cmd = [
                exe,
                f"--user-data-dir={self._player_profile_dir}",
                "--new-window",
                "--hide-crash-restore-bubble",
                "--disable-session-crashed-bubble",
            ]
            if self._hide_window:
                cmd.extend(["--window-position=-32000,-32000", "--window-size=960,720"])
            cmd.append(url)
            startupinfo = None
            if IS_WINDOWS and self._hide_window:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                startupinfo=startupinfo,
                close_fds=not IS_WINDOWS,
            )
            self._start_taskbar_hide_watch()
            self._last_play_method = "normal-chrome"
            self._log(f"Player Chrome → {url}")
            self._log(
                f"Log in once in Player Chrome (profile: spotify_chrome_player_profile) "
                "if Spotify asks."
            )
            return True
        except Exception as ex:
            self._last_error = f"Could not launch Player Chrome: {ex}"
            return False

    def _nudge_player_chrome_playback(self) -> None:
        """Give Player Chrome time to load, then nudge play (before controller opens)."""
        time.sleep(2.5)
        for i in range(3):
            self._send_global_media_key("_nudge_player_chrome_playback")
            time.sleep(0.5)
            if i == 0:
                self._log("Sent play to Player Chrome (media key)…")

    def _wait_for_dual_playback_audio(
        self, *, prefer_desktop: bool = False, timeout: float = 14.0
    ) -> bool:
        if prefer_desktop and self._wait_for_player_desktop_audio(timeout=timeout):
            return True
        if self._wait_for_player_chrome_audio(timeout=timeout):
            return True
        if prefer_desktop:
            return False
        return self._wait_for_player_desktop_audio(timeout=min(8.0, timeout))

    def _wait_for_player_chrome_audio(self, timeout: float = 14.0) -> bool:
        """Wait until loopback hears audio from Player Chrome (music actually playing)."""
        self._refresh_audio_pids()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                from core.audio_monitor import get_spotify_loopback_peak

                peak, _, status = get_spotify_loopback_peak()
                if status == "ok" and peak > 0.002:
                    self._log(f"Player Chrome is playing music (peak={peak:.4f})")
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        self._log("Player Chrome audio not detected — click Play in that window if needed.")
        return False

    def _ensure_desktop_audio_monitor(self) -> None:
        try:
            from core.audio_monitor import (
                close_spotify_loopback,
                register_music_player_pids,
                set_browser_audio_only,
            )
            set_browser_audio_only(False)
            register_music_player_pids([])
            close_spotify_loopback()
        except Exception:
            pass

    def _wait_for_desktop_audio(self, timeout: float = 6.0) -> bool:
        """Poll loopback on spotify.exe only."""
        self._ensure_desktop_audio_monitor()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                from core.audio_monitor import get_spotify_loopback_peak

                peak, _, status = get_spotify_loopback_peak()
                if status == "ok" and peak > 0.002:
                    self._log(f"Spotify desktop audio detected (peak={peak:.4f})")
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        self._log(f"No Spotify desktop audio detected in {timeout:.0f}s.")
        return False

    def _wait_before_controller(self) -> None:
        """Spotify Connect needs the player device playing before the controller attaches."""
        delay = self._controller_delay_sec
        self._log(f"Player active — controller browser starts in {delay:.0f}s…")
        time.sleep(delay)

    def _setup_controller_play_playlist(self, url: str) -> bool:
        """One controller browser: bypass page, open playlist, click Play (no Connect)."""
        if not self._ensure_browser_impl(False):
            return False
        page = self._page
        if not page:
            return False
        if not self._hide_window:
            try:
                page.bring_to_front()
            except Exception:
                pass
        page.goto("https://open.spotify.com/", wait_until="commit", timeout=30000)
        time.sleep(1.2)
        if self._ui_bypass:
            self._bypass_spotify_loaded_ui(page)
        self._log(f"Controller: opening playlist {url}")
        page.goto(url, wait_until="commit", timeout=30000)
        time.sleep(0.5)
        self._wait_for_playlist_ready(page, max_wait=14.0)
        time.sleep(0.4)
        self._refresh_audio_pids()
        self._log_spotify_playback_issues(page)
        self._unmute_web_player(page)
        # In the simplified flow there is no Connect panel to wait for. A
        # single click starts playback; repeated clicks would toggle it
        # pause/play and make the whole session unreliable.
        click_attempts = 1 if self._use_simplified_dual_flow() else 3
        # Prefer a real (trusted) click on the playlist Play button. Spotify
        # accepts the click, but a synthetic JS click does not count as a user
        # gesture; the UI then shows "Pause" while Chrome stays silent. That
        # looked like a finished playlist and broke pause/resume state.
        # The playlist shell can be "ready" before the big Play button is
        # painted. Clicking too early falls back to a synthetic JS click,
        # which Spotify does not treat as a user gesture (UI says Pause but
        # audio never starts). Wait for the real button first.
        try:
            page.locator(f"xpath={self._play_xpath}").first.wait_for(
                state="visible", timeout=6000
            )
        except Exception:
            pass
        clicked_label = ""
        try:
            clicked_label = self._try_click_play_selectors(
                page, self._playlist_play_selectors(), "Controller: clicked"
            )
        except Exception:
            clicked_label = ""
        if not clicked_label and not self._click_playlist_play_button(page, times=click_attempts):
            self._log("Playlist Play button missed — trying fallbacks…")
            if not self._kickstart_playback(page):
                self._last_error = self._last_error or "Could not start playlist playback"
                return False
        ui_playing = self._confirm_playback_started(page, timeout=10.0)
        if not ui_playing:
            ui_playing = self._playlist_header_is_playing(page)
        if ui_playing:
            if self._ensure_browser_playback_audio(page, timeout=8.0):
                self._log("Controller: playlist playing (browser audio confirmed).")
                return True
            self._log(
                "Controller: UI shows playing but Chrome has no audio - "
                "Spotify may still be using the desktop sidecar."
            )
            # The playlist *is* playing, just not through the automated
            # browser.  Switch pause/resume (and audio monitoring) to the
            # desktop client instead of reporting failure and leaving the UI
            # out of sync with the audible music.
            try:
                from core.audio_monitor import get_desktop_spotify_peak
                desktop_peak, _desktop_status = get_desktop_spotify_peak()
            except Exception:
                desktop_peak = 0.0
            if desktop_peak >= 0.0015:
                self._dual_player = "desktop"
                self._desktop_sidecar_active = True
                self._last_audio_source = "desktop"
                try:
                    self.refresh_audio_source()
                except Exception:
                    pass
                self._log(
                    "Controller: desktop Spotify is the audible source - "
                    "using desktop controls for pause/resume."
                )
                return True
        # Page-scoped retry only. Never send a global media key here: it can
        # reach the silent desktop sidecar and/or toggle the browser twice.
        state = self._player_is_playing(page)
        if state is None and self._browser_audio_is_loud():
            self._log("Controller: browser audio detected — playlist is playing.")
            return True
        if state is False:
            try:
                page.keyboard.press("Space")
            except Exception:
                pass
            time.sleep(0.4)
            if self._player_is_playing(page) is True:
                return True
        # Real browser audio is the strongest proof that playback started
        # (covers slow DRM/UI updates).
        if self._wait_for_browser_audio(timeout=6.0):
            self._log("Controller: browser audio detected — playlist is playing.")
            return True
        self._last_error = self._last_error or "Playback did not start"
        return False

    def _setup_controller_for_remote(self) -> bool:
        """Open controller Spotify and attach via Spotify Connect (legacy dual flow)."""
        if not self._ensure_browser_impl(False):
            return False
        page = self._page
        if not page:
            return False
        if not self._hide_window:
            try:
                page.bring_to_front()
            except Exception:
                pass
        page.goto("https://open.spotify.com/", wait_until="commit", timeout=30000)
        time.sleep(1.2)
        if self._ui_bypass and (self._use_system_chrome or self._dual_player == "chrome"):
            self._bypass_spotify_loaded_ui(page)
        if self._prefer_desktop_connect():
            target = "Spotify desktop"
        elif self._uses_chromium_player():
            target = "Player Chromium"
        else:
            target = "Player Chrome"
        self._log(f"Controller Spotify open — linking to {target} via Connect…")

        body = ""
        try:
            body = (page.locator("body").inner_text(timeout=5000) or "").lower()
        except Exception:
            pass

        if "listening on" in body:
            self._log("Controller sees remote playback (Spotify Connect active).")
        elif not self._connect_to_player_device(page):
            self._log("Connect XPath missed — trying fallback device picker…")
            self._select_player_device_in_connect_menu(page)

        if self._confirm_playback_started(page, timeout=8.0):
            self._log("Controller: playback active (remote).")
            return True

        self._log("Trying media key on controller…")
        self._send_global_media_key("_setup_controller_for_remote")
        time.sleep(0.5)
        return self._player_is_playing(page) is True

    def _browser_back(self, page) -> bool:
        """Use the browser back control (not the Spotify menu item)."""
        try:
            page.go_back(wait_until="domcontentloaded", timeout=8000)
            time.sleep(0.3)
            return True
        except Exception:
            pass
        try:
            page.evaluate("() => window.history.back()")
            time.sleep(0.5)
            return True
        except Exception:
            return False

    def _bypass_spotify_loaded_ui(self, page) -> None:
        """After controller loads: wait, optional sidebar click, browser back."""
        if self._bypass_wait_sec > 0:
            time.sleep(self._bypass_wait_sec)

        if not self._click_xpath_visible(
            page,
            self._bypass_main_button_xpath,
            "main sidebar button",
            wait_ms=BYPASS_VISIBLE_MS,
            click_ms=BYPASS_CLICK_MS,
        ):
            try:
                page.locator('//*[@id="main"]/div/button').first.click(timeout=BYPASS_CLICK_MS)
            except Exception:
                pass
        time.sleep(0.15)

        if self._browser_back(page):
            self._log("Controller: browser back to previous site")
        else:
            self._log("Controller: browser back skipped (no history)")

        if self._bypass_before_connect_sec > 0:
            time.sleep(self._bypass_before_connect_sec)

    def _click_connect_device_via_js(self, page) -> bool:
        """
        Click Connect/device button using robust JS selectors instead of XPath.
        Tries data-testid and button text matching.
        """
        try:
            result = page.evaluate(
                """
                (() => {
                  const btn = document.querySelector('[data-testid="devices-bar-button"]') ||
                    document.querySelector('button[data-testid="devices-bar-button"]') ||
                    Array.from(document.querySelectorAll('button')).find(b => 
                      /connect|device/i.test((b.innerText || b.getAttribute('aria-label') || '').trim())
                    );
                  if (!btn) return false;
                  
                  btn.scrollIntoView({block:'center'});
                  btn.click();
                  setTimeout(() => btn.click(), 300);
                  
                  return true;
                })();
                """
            )
            if result:
                self._log("Connect device button clicked via JS (data-testid/text matching)")
            return bool(result)
        except Exception as ex:
            self._log(f"JS-based connect device click failed: {ex}")
            return False

    def _click_xpath_visible(
        self,
        page,
        xpath: str,
        label: str,
        wait_ms: int = 8000,
        click_ms: int = 5000,
    ) -> bool:
        if not xpath:
            return False
        try:
            loc = page.locator(f"xpath={xpath}").first
            loc.wait_for(state="visible", timeout=wait_ms)
            loc.scroll_into_view_if_needed(timeout=min(2000, wait_ms))
            loc.click(timeout=click_ms)
            self._log(f"Controller: clicked {label}")
            return True
        except Exception as ex:
            self._last_error = f"{label}: {ex}"
            return False

    def _open_connect_panel(self, page) -> bool:
        for xp, label in (
            (self._connect_device_xpath, "Connect to a device"),
            (self._connect_device_icon_xpath, "Connect to a device (icon)"),
        ):
            if self._click_xpath_visible(
                page, xp, label, wait_ms=3500, click_ms=2500
            ):
                time.sleep(0.35)
                return True
        try:
            page.locator('[data-testid="devices-bar-button"]').first.click(timeout=2500)
            self._log("Controller: clicked Connect (data-testid fallback)")
            time.sleep(0.35)
            return True
        except Exception:
            return False

    def _select_desktop_connect_device(self, page) -> bool:
        """Pick this PC / Spotify desktop in the Connect device list."""
        if self._connect_device_name:
            try:
                page.get_by_text(
                    re.compile(re.escape(self._connect_device_name), re.I)
                ).first.click(timeout=2500)
                self._log(f"Controller: selected device «{self._connect_device_name}»")
                return True
            except Exception:
                pass

        for label in ("This computer", self._computer_device_name()):
            if not label:
                continue
            try:
                page.get_by_text(re.compile(re.escape(label), re.I)).first.click(
                    timeout=2500
                )
                self._log(f"Controller: selected desktop device «{label}»")
                return True
            except Exception:
                continue

        try:
            rows = page.locator(
                '[data-testid="device-picker-row"], '
                '[data-testid="connect-device-list"] button, '
                'xpath=//*[@id="Desktop_PanelContainer_Id"]//li'
            )
            for i in range(min(rows.count(), 12)):
                row = rows.nth(i)
                text = (row.inner_text(timeout=400) or "").strip()
                if not text or CONNECT_DEVICE_SKIP.search(text):
                    continue
                row.click(timeout=2000)
                self._log(f"Controller: selected device «{text[:48]}»")
                return True
        except Exception:
            pass
        return False

    def _select_chrome_connect_device(self, page) -> bool:
        try:
            target = page.get_by_text(CONNECT_DEVICE_LABEL).first
            target.click(timeout=2500)
            self._log("Controller: selected Web Player (Chrome)")
            return True
        except Exception:
            pass
        try:
            row = page.locator(
                'xpath=//*[@id="Desktop_PanelContainer_Id"]'
                '//span[contains(., "Web Player") and (contains(., "Chrome") or contains(., "Chromium"))]'
            ).first
            row.click(timeout=2500)
            self._log("Controller: selected Web Player (Chrome) in device list")
            return True
        except Exception:
            pass
        if self._click_xpath_visible(
            page, self._player_device_row_xpath, "Web Player device row", wait_ms=3000, click_ms=2000
        ):
            return True
        return False

    def _connect_to_player_device(self, page) -> bool:
        """Open Connect and select the active player (desktop app or Chrome)."""
        if not self._open_connect_panel(page):
            return False
        if self._prefer_desktop_connect():
            if self._select_desktop_connect_device(page):
                return True
        if self._uses_browser_player() and self._select_chrome_connect_device(page):
            return True
        if not self._prefer_desktop_connect() and self._select_desktop_connect_device(page):
            return True
        if self._prefer_desktop_connect() and self._select_chrome_connect_device(page):
            return True
        return False

    def _select_player_device_in_connect_menu(self, page) -> bool:
        """Fallback device picker if sidebar Connect XPaths fail."""
        if not self._open_connect_panel(page):
            return False
        if self._prefer_desktop_connect():
            if self._select_desktop_connect_device(page):
                return True
        if self._select_chrome_connect_device(page):
            return True
        return self._select_desktop_connect_device(page)

    def _maybe_launch_desktop_sidecar(self, playlist_uri: str) -> None:
        if not self._also_launch_desktop:
            return
        # Spotify desktop should already be running from the silent track
        # pre-launch. No need to open the playlist URI in the hidden desktop
        # client — the browser handles playback.
        if _spotify_running():
            self._desktop_sidecar_active = True
            self._log("Spotify desktop active (silent track) — skipping playlist open in desktop.")
        else:
            # Fallback: launch Spotify plain (no playlist URI) for audio detection
            desktop = self._desktop_helper()
            desktop.launch_spotify()
            if _spotify_running():
                self._desktop_sidecar_active = True
                self._log("Spotify desktop launched for audio detection.")
            else:
                self._log("Spotify desktop did not start — continuing without desktop.")

    def _open_playlist_dual_chrome(self, playlist_uri: str, url: str) -> bool:
        self._desktop_sidecar_active = False

        if self._use_simplified_dual_flow():
            # Spotify desktop is already running from the silent track
            # pre-launch. No need to open the playlist in the hidden desktop
            # client — only the automated Chrome browser handles playback.
            # Just mark desktop as active for pause/resume routing.
            if _spotify_running():
                self._desktop_sidecar_active = True
                self._log("Spotify desktop running (silent track) — browser will handle playlist.")
            else:
                # Fallback: if Spotify isn't running yet, launch it plain
                desktop = self._desktop_helper()
                desktop.launch_spotify()
                if _spotify_running():
                    self._desktop_sidecar_active = True
                self._log("Spotify desktop launched for audio detection.")
            self._wait_before_controller()
            self._log("Automated Chrome — open playlist and play (one browser, no Connect).")
            ok = bool(
                self._browser_call(
                    lambda: self._setup_controller_play_playlist(url),
                    default=False,
                )
            )
            if not ok:
                self._log(
                    "Playback uncertain — check the GameBeats browser window and click Play once."
                )
            self._refresh_audio_pids()
            return ok

        # Legacy: separate Player Chrome/Chromium + controller + Spotify Connect.
        if self._uses_desktop_player():
            if _spotify_running():
                self._log("Spotify desktop running — skipping playlist open in desktop (Connect will handle it).")
            else:
                if not self._launch_player_desktop(playlist_uri):
                    return False
                self._log("Step 1: Spotify desktop — load playlist and start music…")
            # Quick check: try to resume/listen to desktop immediately; if that
            # succeeds, skip the initial nudge to avoid double toggles.
            try:
                quick_ok = self._ensure_desktop_playing_initial(attempts=2, delay=0.25)
            except Exception:
                quick_ok = False
            if not quick_ok:
                self._nudge_player_desktop_playback()
            playing = self._wait_for_player_desktop_audio(timeout=12.0)
            if not playing:
                self._nudge_player_desktop_playback()
                playing = self._wait_for_player_desktop_audio(timeout=8.0)
            player_hint = "Spotify desktop app"
        elif self._uses_chromium_player():
            self._maybe_launch_desktop_sidecar(playlist_uri)
            if not self._launch_player_chromium(url) and not self._desktop_sidecar_active:
                return False
            self._refresh_audio_pids()
            self._nudge_player_chrome_playback()
            if self._desktop_sidecar_active:
                self._nudge_player_desktop_playback()
            playing = self._wait_for_dual_playback_audio(
                prefer_desktop=self._desktop_sidecar_active, timeout=14.0
            )
            player_hint = "Player Chromium or Spotify desktop"
        else:
            self._maybe_launch_desktop_sidecar(playlist_uri)
            if not self._launch_player_chrome(url) and not self._desktop_sidecar_active:
                return False
            self._browser_launched_at = time.time()
            self._refresh_audio_pids()
            self._nudge_player_chrome_playback()
            if self._desktop_sidecar_active:
                self._nudge_player_desktop_playback()
            playing = self._wait_for_dual_playback_audio(
                prefer_desktop=self._desktop_sidecar_active, timeout=14.0
            )
            player_hint = "Player Chrome or Spotify desktop"

        self._wait_before_controller()
        self._log("Step 2: Controller browser (Spotify Connect)…")
        if not self._browser_call(self._setup_controller_for_remote, default=False):
            self._log(f"Connect uncertain — click Play in {player_hint} if needed.")
            return bool(playing)
        self._refresh_audio_pids()
        return True

    def _activate_this_web_player(self, page) -> bool:
        """If Spotify is playing on another device, switch output to this browser.

        Spotify keeps a single active device.  When the desktop sidecar is
        playing its silent track, the web player shows a Pause button but no
        audio comes out of Chrome - the account is still sending sound to the
        desktop.  The device menu is the reliable way to move playback to the
        browser, but it renders asynchronously and the web-player row has no
        stable data-testid.  Click the row itself (not a loose text match) and
        wait for the list to appear first.
        """
        # Fast path: Spotify sometimes shows an explicit "listen on this
        # web player" banner/button.
        try:
            page.get_by_role(
                "button",
                name=re.compile(
                    r"listen on (this )?(web player|browser|computer)|play on this",
                    re.I,
                ),
            ).first.click(timeout=2000)
            self._log("Switched Spotify to this web player.")
            time.sleep(0.5)
            return True
        except Exception:
            pass

        # Open the Connect-to-a-device menu.  It renders only after the
        # bottom bar has painted, so poll for the trigger instead of giving
        # up on the first 0.4 s check.
        triggers = (
            'button[aria-label*="Connect to a device"]',
            'button[data-testid="devices-bar-button"]',
            '[data-testid="device-picker-trigger"]',
        )
        deadline = time.time() + 6.0
        while time.time() < deadline:
            for sel in triggers:
                try:
                    btn = page.locator(sel).first
                    if btn.count() == 0 or not btn.is_visible():
                        continue
                    btn.click(timeout=3000)
                    # The device list lives in a portal and takes a moment
                    # to paint.  The old fixed 0.4 s wait was too short on a
                    # cold profile, so the row search ran before it existed.
                    try:
                        page.locator('[data-testid="devices-list-"]').first.wait_for(
                            state="visible", timeout=5000
                        )
                    except Exception:
                        self._log("Device menu did not open; retrying...")
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass
                        time.sleep(0.3)
                        continue
                    rows = page.locator('[data-testid="device-picker-row-sidepanel"]')
                    target = rows.filter(
                        has_text=re.compile(
                            r"this web browser|this web player|web player|this computer",
                            re.I,
                        )
                    ).first
                    if target.count() == 0:
                        # Localized UIs may not use the English label.  The
                        # actionable row is the one whose hidden hint says
                        # "Connect to this device"; the current desktop row
                        # does not include that hint.
                        target = rows.filter(
                            has_text=re.compile(r"connect to this device", re.I)
                        ).first
                    if target.count() > 0:
                        target.click(timeout=3000)
                        self._log("Selected Web Player in device menu.")
                        time.sleep(0.5)
                        return True
                    self._log("Device menu opened but no web-player row was found.")
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                except Exception:
                    continue
            time.sleep(0.4)
        self._log("Could not switch Spotify output to the web player.")
        return False

    def _ensure_browser_playback_audio(self, page, timeout: float = 8.0) -> bool:
        """Make Chrome, not the desktop sidecar, the device producing audio.

        Spotify permits one active device.  A UI that says "Pause" only means
        the account is playing somewhere; it may still be the desktop app, in
        which case Chrome is completely silent.  Check real loopback audio,
        switch the device menu to "This web browser" when needed, and resume
        the page if the switch left it paused.
        """
        if self._wait_for_browser_audio(timeout=2.0):
            return True
        if self._activate_this_web_player(page):
            self._log("Web player: switched Spotify output to this browser.")
        else:
            self._log("Web player: could not switch Spotify output to this browser.")
        if self._wait_for_browser_audio(timeout=timeout):
            return True
        # A device switch can move playback to Chrome but leave the track
        # paused.  Use the real play/pause control (never a global media key).
        if self._player_is_playing(page) is False:
            self._click_player_control(page)
            if self._wait_for_browser_audio(timeout=timeout):
                return True
        return False

    def _unmute_web_player(self, page) -> None:
        try:
            page.evaluate(
                """() => {
                document.querySelectorAll('audio, video').forEach((m) => {
                    m.muted = false;
                    m.volume = 1.0;
                });
            }"""
            )
        except Exception:
            pass
        for sel in (
            '[data-testid="volume-bar-toggle-muted"]',
            'button[aria-label*="Unmute"]',
            '[aria-label="Unmute"]',
        ):
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    self._log("Unmuted web player volume")
                    break
            except Exception:
                pass

    def _playlist_header_is_playing(self, page) -> bool:
        """True when the large playlist Play control shows Pause."""
        for sel in (
            '#main-view button[data-testid="play-button"]',
            'main button[data-testid="play-button"]',
        ):
            try:
                btn = page.locator(sel).first
                if btn.count() == 0:
                    continue
                label = (btn.get_attribute("aria-label") or "").lower()
                if "pause" in label:
                    return True
                if "play" in label:
                    return False
            except Exception:
                pass
        return self._player_is_playing(page) is True

    def _click_play_button_via_js(self, page) -> bool:
                """Run a robust JS click routine in the page and return True on success."""
                try:
                        result = page.evaluate(
                                """
                                (() => {
                                    function clickEl(el) {
                                        if (!el) return false;
                                        try { el.scrollIntoView({block:'center'}); } catch (e) {}
                                        try { el.click(); return true; } catch (e) {}
                                        try {
                                            const ev = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
                                            el.dispatchEvent(ev);
                                            return true;
                                        } catch (e) {}
                                        try {
                                            el.focus && el.focus();
                                            el.dispatchEvent && el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                            el.dispatchEvent && el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                            el.dispatchEvent && el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                                            return true;
                                        } catch (e) {}
                                        return false;
                                    }

                                    const selectors = [
                                        'button[data-testid="play-button"]',
                                        'button[aria-label*="Play"]',
                                        '[data-testid="play-button"]',
                                        'button[data-testid="control-button-playpause"]',
                                        '[data-testid="control-button-playpause"]',
                                        'button[role="button"][aria-label*="Play"]'
                                    ];

                                    for (const sel of selectors) {
                                        try {
                                            const el = document.querySelector(sel);
                                            if (el && clickEl(el)) return true;
                                        } catch (e) {}
                                    }

                                    // Fallback: find any button-like element whose text or aria-label contains 'play' or 'start'
                                    const candidates = Array.from(document.querySelectorAll('button, [role="button"], a, div'));
                                    for (const node of candidates) {
                                        try {
                                            const txt = (node.innerText || node.getAttribute && node.getAttribute('aria-label') || node.title || '').trim();
                                            if (/\b(play|start)\b/i.test(txt)) {
                                                if (clickEl(node)) return true;
                                            }
                                        } catch (e) {}
                                    }

                                    return false;
                                })()
                                """
                        )
                        if result:
                                try:
                                        self._log("Play button clicked via robust JS")
                                except Exception:
                                        pass
                                return True
                        try:
                                self._log("Robust JS did not find a play button")
                        except Exception:
                                pass
                        return False
                except Exception as ex:
                        try:
                                self._log(f"JS click failed (exception): {ex}")
                        except Exception:
                                pass
                        return False

    def _click_play_locator(self, loc) -> bool:
        try:
            loc.wait_for(state="visible", timeout=8000)
            loc.scroll_into_view_if_needed(timeout=3000)
            try:
                loc.hover(timeout=2000)
            except Exception:
                pass
            time.sleep(0.15)
            loc.click(timeout=5000)
            return True
        except Exception:
            pass
        try:
            loc.click(force=True, timeout=3000)
            return True
        except Exception:
            pass
        try:
            loc.evaluate(
                """(el) => {
                el.focus();
                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            }"""
            )
            return True
        except Exception:
            return False

    def _playlist_play_selectors(self) -> list[tuple[str, str]]:
        selectors = [
            (f"xpath={self._play_xpath}", "play-button-xpath"),
            (f"xpath={PLAYLIST_PLAY_SPAN_XPATH}", "play-span-xpath"),
            ('#main-view button[data-testid="play-button"]', "main-play-button"),
            ('main button[data-testid="play-button"]', "main-section-play"),
            ('button[data-testid="play-button"][aria-label*="Play"]', "play-button-aria"),
            ('button[data-testid="play-button"]', "play-button"),
        ]
        seen = set()
        unique = []
        for sel, label in selectors:
            if sel in seen:
                continue
            seen.add(sel)
            unique.append((sel, label))
        return unique

    def _try_click_play_selectors(self, page, selectors, log_prefix: str = "Clicked") -> str:
        for sel, label in selectors:
            loc = page.locator(sel).first
            try:
                if loc.count() == 0 or not loc.is_visible():
                    continue
            except Exception:
                continue
            if self._click_play_locator(loc):
                self._log(f"{log_prefix} playlist Play ({label})")
                return label
        return ""

    def _click_playlist_play_button(
        self, page, times: int = 1, followup_sec: float | None = None
    ) -> bool:
        """Click Spotify's playlist Play button using JS only.

        Behavior:
        - If the Connect/device sidebar (xpath below) already exists, send
          a single JS click and return.
        - Otherwise, click the Play button and then continue clicking once
          per second until the Connect panel appears. When it does, send one
          additional JS click and stop. If `times` > 0, limit to that many
          click attempts (default 1). If `times` <= 0, treat as unlimited.
        """
        followup_sec = followup_sec if followup_sec is not None else getattr(self, "_play_followup_sec", 2.0)
        connect_panel_xpath = '//*[@id="main"]/div/div[2]/div[5]/aside/div[2]'

        existed_before = False
        try:
            loc = page.locator(f"xpath={connect_panel_xpath}").first
            if loc.count() > 0 and loc.is_visible():
                existed_before = True
        except Exception:
            existed_before = False

        def _panel_present() -> bool:
            try:
                loc = page.locator(f"xpath={connect_panel_xpath}").first
                return loc.count() > 0 and loc.is_visible()
            except Exception:
                return False

        clicked = False

        # If the Connect panel already exists, a single click is enough.
        if existed_before:
            try:
                if self._click_play_button_via_js(page):
                    clicked = True
                    try:
                        self._log("[_click_playlist_play_button] Clicked once (connect panel already present)")
                    except Exception:
                        pass
                else:
                    try:
                        self._log("[_click_playlist_play_button] Clicked once (connect panel already present) returned False")
                    except Exception:
                        pass
            except Exception:
                pass
            return clicked

        # Otherwise, click and keep clicking once per second until the panel appears.
        max_attempts = None if times is None or int(times) <= 0 else max(1, int(times))
        attempt = 0
        while True:
            attempt += 1
            try:
                res = self._click_play_button_via_js(page)
                if res:
                    clicked = True
                    try:
                        self._log(f"[_click_playlist_play_button] JS click attempt {attempt} succeeded")
                    except Exception:
                        pass
                else:
                    try:
                        self._log(f"[_click_playlist_play_button] JS click attempt {attempt} returned False")
                    except Exception:
                        pass
            except Exception as ex:
                try:
                    self._log(f"[_click_playlist_play_button] JS click attempt {attempt} exception: {ex}")
                except Exception:
                    pass

            # After clicking, watch up to 1s for the panel to appear (check frequently).
            deadline = time.time() + 1.0
            panel_seen = False
            while time.time() < deadline:
                if _panel_present():
                    panel_seen = True
                    break
                time.sleep(0.1)

            if panel_seen:
                # One additional click after the panel appears (unless it existed before).
                try:
                    self._click_play_button_via_js(page)
                    try:
                        self._log("[_click_playlist_play_button] Follow-up JS click sent after connect panel appeared")
                    except Exception:
                        pass
                except Exception:
                    pass
                break

            # Respect max attempts if provided.
            if max_attempts is not None and attempt >= max_attempts:
                break

            # Wait the remainder of the 1s interval if any (already slept in small increments).
            # Continue to next attempt.
            try:
                time.sleep(0.0)
            except Exception:
                pass

        return clicked

        return self._playlist_header_is_playing(page) or self._player_is_playing(page) is True

    def _confirm_playback_started(self, page, timeout: float = 6.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._player_is_playing(page) is True:
                return True
            time.sleep(0.15)
        return False

    def _nudge_playback(self, page) -> bool:
        """Extra play nudges, one page-scoped action at a time.

        The old version pressed Space *and* clicked the control *and* sent a
        global media key, which could toggle playback three times (ending in
        the wrong state). Only act again if the player is still paused.
        """
        if self._player_is_playing(page) is True:
            return True
        if self._player_is_playing(page) is None and self._browser_audio_is_loud():
            return True
        try:
            page.keyboard.press("Space")
            time.sleep(0.35)
        except Exception:
            pass
        for _ in range(20):
            time.sleep(0.15)
            if self._player_is_playing(page) is True:
                return True
        if self._player_is_playing(page) is False:
            self._click_player_control(page)
            return self._confirm_playback_started(page, timeout=4.0)
        return self._wait_for_browser_audio(timeout=3.0)

    def _browser_audio_is_loud(self, threshold: float = 0.0015) -> bool:
        """Ground-truth check: is the web player actually producing audio?

        The process-loopback meter now includes the desktop sidecar too, so it
        cannot answer this question.  Use the WASAPI session meter for the
        registered browser PIDs instead; otherwise a desktop track would make
        the app believe Chrome was playing and pause the wrong component.
        """
        try:
            from core.audio_monitor import (
                get_browser_spotify_peak,
                get_desktop_spotify_peak,
                get_spotify_loopback_peak,
            )
            peak, status = get_browser_spotify_peak()
            if status == "ok" and peak >= threshold:
                return True
            # Some Chrome audio sessions are invisible to the WASAPI session
            # meter.  If the desktop is silent, the combined loopback can
            # still prove the browser is the source.
            desktop_peak, desktop_status = get_desktop_spotify_peak()
            if desktop_status == "ok" and desktop_peak >= threshold:
                return False
            union_peak, _db, union_status = get_spotify_loopback_peak()
            return bool(union_status == "ok" and union_peak >= threshold)
        except Exception:
            return False

    def _wait_for_browser_audio(self, timeout: float = 6.0,
                                threshold: float = 0.0015) -> bool:
        self._refresh_audio_pids()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._browser_audio_is_loud(threshold):
                return True
            time.sleep(0.25)
        return False

    def _click_player_control(self, page) -> bool:
        """Click the page play/pause control, or send Space to the page.

        Never use a global media key here: in dual mode it reaches both the
        browser and the silent desktop sidecar, producing a net double toggle.
        """
        try:
            loc = page.locator(PLAYER_PLAYPAUSE_SELECTOR).first
            if loc.count() > 0:
                loc.click(timeout=4000)
                return True
        except Exception:
            pass
        try:
            page.keyboard.press("Space")
            return True
        except Exception:
            return False

    def _player_is_playing(self, page) -> bool | None:
        # Media Session state is language-independent and reflects real
        # playback (Spotify sets it in the web player).
        try:
            state = page.evaluate(
                "() => { try { return (navigator.mediaSession && "
                "navigator.mediaSession.playbackState) || ''; } "
                "catch (e) { return ''; } }"
            )
            state = str(state or "").strip().lower()
            if state == "playing":
                return True
            if state == "paused":
                return False
        except Exception:
            pass
        try:
            btn = page.locator(PLAYER_PLAYPAUSE_SELECTOR).first
            if btn.count() == 0:
                return None
            label = (btn.get_attribute("aria-label") or "").strip().lower()
            if "pause" in label or "pausa" in label or "pausieren" in label:
                return True
            if "play" in label or "lecture" in label or "abspielen" in label:
                return False
        except Exception:
            pass
        return None

    def _toggle_player(self, page) -> bool:
        ok = self._click_player_control(page)
        if ok:
            try:
                self._log("[_toggle_player] Clicked player play/pause control.")
            except Exception:
                pass
        return ok

    def _pause_player(self, page) -> bool:
        state = self._player_is_playing(page)
        if state is False:
            return True
        if state is None:
            # Avoid inverting an unknown state: audio is the tie-breaker.
            if not self._browser_audio_is_loud():
                return True  # already silent/paused
        if not self._click_player_control(page):
            return False
        # Confirm the pause actually happened (Spotify UI updates quickly).
        for _ in range(16):
            time.sleep(0.15)
            if self._player_is_playing(page) is False:
                return True
        # UI did not update but audio may have stopped; check it as fallback.
        time.sleep(0.25)
        return not self._browser_audio_is_loud()

    def _play_player(self, page) -> bool:
        state = self._player_is_playing(page)
        if state is True:
            return True
        if state is None and self._browser_audio_is_loud():
            return True  # already audibly playing
        if not self._click_player_control(page):
            return False
        for _ in range(16):
            time.sleep(0.15)
            if self._player_is_playing(page) is True:
                return True
        return self._wait_for_browser_audio(timeout=3.0)

    def _remember_playback_state(self, is_playing: bool, paused_by_game=None):
        self._is_playing = bool(is_playing)
        self._playback_state_known = True
        if paused_by_game is not None:
            self._paused_by_game = bool(paused_by_game)
        elif is_playing:
            self._paused_by_game = False

    def _kickstart_playback(self, page) -> bool:
        if self._player_is_playing(page) is True:
            return True
        if self._click_playlist_play_button(page):
            if self._confirm_playback_started(page, timeout=4.0):
                return True
        return self._nudge_playback(page)

    def _open_playlist_and_play(self, playlist_uri: str) -> bool:
        playlist_uri = self.normalize_playlist_uri(playlist_uri)
        url = playlist_uri_to_url(playlist_uri)
        if not playlist_uri or not url:
            self._last_error = f"Invalid playlist reference: {playlist_uri!r}"
            return False

        # Do not open blocked playlists in the browser.
        try:
            blocked = set(load_blocked_playlist_uris(self.data_dir) or [])
            if playlist_uri in blocked:
                self._last_error = "Playlist is blocked and will not be opened in browser"
                self._log(f"Blocked playlist prevented from opening: {playlist_uri}")
                return False
        except Exception:
            pass

        if self._dual_chrome:
            if self._use_simplified_dual_flow():
                self._log(
                    "Dual mode: Spotify desktop + one automated Chrome (playlist play, no Connect)."
                )
            else:
                self._log("Dual mode (Connect): desktop/player Chrome + controller browser.")
            ok = self._open_playlist_dual_chrome(playlist_uri, url)
            if ok:
                self._remember_playback_state(True, paused_by_game=False)
                self._last_play_method = "dual-chrome"
            return ok

        def _work(page):
            self._log(f"Web player: goto {url}")
            if not self._hide_window:
                try:
                    page.bring_to_front()
                except Exception:
                    pass
            page.goto(url, wait_until="commit", timeout=30000)
            self._wait_for_playlist_ready(page, max_wait=12.0)

            try:
                support_btn = page.locator("#main > div > button > span")
                if support_btn.is_visible(timeout=1000):
                    btn_text = support_btn.text_content() or ""
                    if "Spotify support" in btn_text:
                        self._log("Spotify support screen detected. Going back and retrying...")
                        page.go_back(wait_until="commit")
                        page.wait_for_timeout(1000)
                        page.goto(url, wait_until="commit", timeout=30000)
                        self._wait_for_playlist_ready(page, max_wait=12.0)
            except Exception:
                pass

            self._refresh_audio_pids()
            self._log_spotify_playback_issues(page)
            self._activate_this_web_player(page)
            self._unmute_web_player(page)

            if not self._click_playlist_play_button(page):
                self._log("Playlist Play XPath missed — trying fallbacks…")
                if not self._kickstart_playback(page):
                    self._last_error = self._last_error or "Could not click playlist Play"
                    return False
            elif not self._confirm_playback_started(page, timeout=5.0):
                self._log("Play clicked but bar still shows Play — nudging…")
                self._activate_this_web_player(page)
                if not self._nudge_playback(page):
                    self._last_error = "Play clicked but playback did not start"
                    self._log_spotify_playback_issues(page)
                    return False

            self._refresh_audio_pids()
            if self._player_is_playing(page) is True:
                self._log("Web player: playback started (Pause visible on bar)")
                wv = self._check_widevine(page)
                if wv != "widevine-ok":
                    self._log(
                        "UI shows playing but DRM may block real audio — use Google Chrome "
                        "(not bundled Chromium). YouTube can work without Widevine; Spotify cannot."
                    )
                return True
            return False

        ok = bool(self._run_on_page(_work))
        if ok:
            self._remember_playback_state(True, paused_by_game=False)
            self._last_play_method = "web-playlist"
        return ok

    # ── Public API (matches SpotifyDesktopController) ─────────────────────

    def verify_access(self):
        """Returns (ok, message) — matches Spotify API controller contract."""
        if not HAS_PLAYWRIGHT:
            return False, "Install Playwright: pip install playwright && playwright install chromium"
        if self._dual_chrome:
            if self._use_simplified_dual_flow():
                return True, (
                    "Spotify desktop + one automated Chrome. Log in once in "
                    "spotify_web_profile (no separate Player Chrome window)."
                )
            return True, (
                "Legacy dual mode with Spotify Connect — multiple browser windows."
            )
        return True, (
            "Web player ready — browser opens when a game plays; "
            "login is saved in spotify_web_profile"
        )

    def launch_spotify(self):
        if self._use_simplified_dual_flow():
            if self._desktop_helper()._find_spotify_exe():
                return True
            self._last_error = "Spotify desktop app not found"
            return False
        return self._ensure_browser(check_login=False)

    def close_spotify(self, timeout=4.0) -> bool:
        desktop_ok = True
        try:
            if self._desktop_player is not None or _spotify_running():
                desktop_ok = bool(self._desktop_helper().close_spotify(timeout=timeout))
                self._desktop_sidecar_active = False
        except Exception as ex:
            desktop_ok = False
            self._log(f"Could not close Spotify desktop: {ex}")

        browser_ok = True
        try:
            browser_ok = bool(
                self._browser_call(
                    self._close_browser_impl,
                    timeout=max(2.0, min(10.0, float(timeout))),
                    default=False,
                )
            )
        except Exception as ex:
            browser_ok = False
            self._log(f"Could not close Spotify browser: {ex}")
        return bool(desktop_ok and browser_ok)

    def close_browser(self, timeout: float = 8.0) -> bool:
        return bool(self._browser_call(self._close_browser_impl, timeout=timeout, default=False))

    def prepare_browser_background(self, timeout: float = 30.0) -> bool:
        """Keep Playwright alive after login — hide window instead of full teardown."""
        return bool(
            self._browser_call(
                self._prepare_browser_background_impl,
                timeout=timeout,
                default=False,
            )
        )

    def _prepare_browser_background_impl(self) -> bool:
        self._hide_window = True
        try:
            if self._page and not self._page.is_closed():
                self._page.goto(
                    "https://open.spotify.com/",
                    wait_until="commit",
                    timeout=30000,
                )
        except Exception:
            pass
        self._move_automation_browser_offscreen()
        self._start_taskbar_hide_watch()
        self._refresh_audio_pids()
        self._log("Spotify browser kept warm in background (faster next playlist).")
        return True

    def _close_browser_impl(self) -> bool:
        with self._browser_lock:
            try:
                if self._player_context:
                    self._player_context.close()
            except Exception:
                pass
            try:
                if self._context:
                    self._context.close()
            except Exception:
                pass
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass
            self._player_context = None
            self._player_page = None
            self._context = None
            self._page = None
            self._pw = None
            self._login_checked = False
            try:
                from core.audio_monitor import register_music_player_pids
                register_music_player_pids([])
            except Exception:
                pass
            time.sleep(0.3)
            return True

    def restart_spotify(self) -> bool:
        """Reset playback flags only — keep browser profile and login."""
        self.reset_session()
        return self._ensure_browser(check_login=False)

    def ensure_fresh_session(self, timeout: float = 10.0) -> bool:
        """Do not wipe browser data — only reset session flags and ensure browser is up."""
        del timeout
        self.reset_session()
        return self._ensure_browser(check_login=False)

    def ensure_active_device(self, wait_seconds=8):
        del wait_seconds
        if self._dual_chrome:
            if self._use_simplified_dual_flow():
                if not HAS_PLAYWRIGHT:
                    self._last_error = "Playwright not installed"
                    return False
                if not self._desktop_helper()._find_spotify_exe():
                    self._log("Warning: Spotify desktop not found.")
                if self._use_system_chrome and not self._find_chrome_exe():
                    self._log("Warning: Google Chrome not found for automated browser.")
                self._log(
                    "Ready: Spotify desktop + one automated Chrome when a playlist plays."
                )
                return True
            if self._uses_desktop_player():
                if self._desktop_helper()._find_spotify_exe():
                    self._log(
                        "Dual mode ready (Spotify desktop opens when a playlist plays)."
                    )
                    return True
                self._last_error = "Spotify desktop app not found"
                return False
            if not HAS_PLAYWRIGHT:
                self._last_error = "Playwright not installed"
                return False
            self._log("Dual mode (Connect) ready.")
            return True
        ok = self._ensure_browser(check_login=False)
        if ok:
            self._log("Spotify web player browser is ready.")
        else:
            self._log(f"Spotify web player not ready: {self._last_error}")
        return ok

    def _clear_mixer_mute(self):
        try:
            from core.audio_monitor import _clear_spotify_mixer_mute
            _clear_spotify_mixer_mute()
        except Exception:
            pass

    def _source_peaks(self) -> tuple:
        """Return (browser_peak, desktop_peak) from WASAPI session meters."""
        browser_peak = 0.0
        desktop_peak = 0.0
        try:
            from core.audio_monitor import (
                get_browser_spotify_peak,
                get_desktop_spotify_peak,
            )
            browser_peak, browser_status = get_browser_spotify_peak()
            desktop_peak, desktop_status = get_desktop_spotify_peak()
            if browser_status != "ok":
                browser_peak = 0.0
            if desktop_status != "ok":
                desktop_peak = 0.0
        except Exception:
            pass
        return float(browser_peak or 0.0), float(desktop_peak or 0.0)

    def _loopback_audible(self, threshold: float = 0.0015) -> bool:
        try:
            from core.audio_monitor import get_spotify_loopback_peak
            peak, _db, status = get_spotify_loopback_peak()
            return bool(status == "ok" and peak >= threshold)
        except Exception:
            return False

    def _note_audio_source(self, browser_peak: float, desktop_peak: float,
                           threshold: float = 0.0015):
        if desktop_peak >= threshold and desktop_peak > browser_peak:
            self._last_audio_source = "desktop"
        elif browser_peak >= threshold:
            self._last_audio_source = "browser"

    def _pause_desktop(self, paused_by_game: bool = False) -> bool:
        try:
            if not (
                _spotify_running()
                or self._desktop_sidecar_active
                or self._uses_desktop_player()
            ):
                return False
            desktop = self._desktop_helper()
            self._log("Calling desktop.ensure_paused from ensure_paused")
            return bool(desktop.ensure_paused(paused_by_game=paused_by_game))
        except Exception:
            return False

    def _resume_desktop(self) -> bool:
        try:
            if not (
                _spotify_running()
                or self._desktop_sidecar_active
                or self._uses_desktop_player()
            ):
                return False
            desktop = self._desktop_helper()
            self._log("Calling desktop.ensure_playing from ensure_playing")
            return bool(desktop.ensure_playing())
        except Exception:
            return False

    def _wait_for_silence(self, threshold: float = 0.0015,
                          timeout: float = 1.6) -> bool:
        """Wait until Spotify is actually inaudible after a pause command."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            browser_peak, desktop_peak = self._source_peaks()
            if browser_peak < threshold and desktop_peak < threshold:
                return True
            if not self._loopback_audible(threshold):
                return True
            time.sleep(0.15)
        return False

    def ensure_paused(self, paused_by_game: bool = False) -> bool:
        self._clear_mixer_mute()
        try:
            prefer_browser_pause = not self._uses_desktop_player()
        except Exception:
            prefer_browser_pause = False

        threshold = 0.0015
        browser_peak, desktop_peak = self._source_peaks()
        self._note_audio_source(browser_peak, desktop_peak, threshold)
        audible = (
            browser_peak >= threshold
            or desktop_peak >= threshold
            or self._loopback_audible(threshold)
        )

        if not audible:
            # Nothing is audible.  Still send one targeted idempotent pause so
            # a stale internal "playing" state gets cleared, but never launch
            # a browser just to pause silence.
            if prefer_browser_pause:
                if self._page or self._context or self._cdp_url:
                    try:
                        self._run_on_page(lambda page: self._pause_player(page))
                    except Exception:
                        pass
            else:
                self._pause_desktop(paused_by_game)
            self._remember_playback_state(False, paused_by_game=paused_by_game)
            return True

        # Pause the source that is actually audible first.  This is the key
        # fix: the old code paused the silent browser, claimed success, and
        # left the desktop track playing.  Every command here is targeted at
        # Spotify (browser page or Spotify window), never a global media key
        # that could hit the other app that just made the sound.
        browser_audible = browser_peak >= threshold
        desktop_audible = desktop_peak >= threshold
        if desktop_audible and desktop_peak >= browser_peak:
            order = ["desktop", "browser"]
        elif browser_audible:
            order = ["browser", "desktop"]
        elif not prefer_browser_pause:
            order = ["desktop", "browser"]
        else:
            order = ["browser", "desktop"]

        for source in order:
            if source == "desktop":
                # Never poke the silent desktop sidecar while the browser is
                # the known source.  That used to toggle the wrong component.
                if not desktop_audible and browser_audible:
                    continue
                if not desktop_audible and not self._loopback_audible(threshold):
                    continue
                if not self._pause_desktop(paused_by_game):
                    continue
            else:
                if not (self._page or self._context or self._cdp_url):
                    continue
                if not self._run_on_page(lambda page: self._pause_player(page)):
                    continue
            if self._wait_for_silence(threshold, timeout=1.6):
                self._remember_playback_state(False, paused_by_game=paused_by_game)
                return True
        self._last_error = self._last_error or "Could not confirm Spotify pause"
        return False

    def ensure_playing(self) -> bool:
        self._clear_mixer_mute()
        try:
            prefer_browser_play = not self._uses_desktop_player()
        except Exception:
            prefer_browser_play = False

        threshold = 0.0015
        browser_peak, desktop_peak = self._source_peaks()
        if browser_peak >= threshold or desktop_peak >= threshold:
            self._note_audio_source(browser_peak, desktop_peak, threshold)
            self._remember_playback_state(True, paused_by_game=False)
            return True
        # The source-specific meters can miss a session; if the combined
        # meter already hears Spotify, do not risk stealing playback by
        # sending another play command to the other component.
        if self._loopback_audible(threshold):
            self._remember_playback_state(True, paused_by_game=False)
            return True

        # Remember which source was audible before the game paused it.
        prefer_desktop = (
            not prefer_browser_play
            or getattr(self, "_last_audio_source", "browser") == "desktop"
        )

        def _resume_browser() -> bool:
            ok = bool(self._run_on_page(lambda page: self._play_player(page)))
            if ok:
                self._last_audio_source = "browser"
                self._remember_playback_state(True, paused_by_game=False)
            return ok

        def _resume_desktop_checked() -> bool:
            ok = self._resume_desktop()
            if ok:
                self._last_audio_source = "desktop"
                self._remember_playback_state(True, paused_by_game=False)
            return ok

        # Only targeted commands here.  A global media key can resume the
        # other app whose audio just stopped instead of Spotify.
        if prefer_desktop:
            if _resume_desktop_checked():
                return True
            if _resume_browser():
                return True
        else:
            if _resume_browser():
                return True
            if _resume_desktop_checked():
                return True
        return False

    def ensure_playing_any(self) -> bool:
        self._clear_mixer_mute()
        try:
            if not self._uses_desktop_player():
                ok = bool(self._run_on_page(lambda page: self._play_player(page)))
                if ok:
                    self._remember_playback_state(True, paused_by_game=False)
                return ok
        except Exception:
            pass
        # Prefer desktop client if present
        try:
            if _spotify_running() or self._desktop_sidecar_active or self._uses_desktop_player():
                try:
                    desktop = self._desktop_helper()
                    self._log("Calling desktop.ensure_playing from ensure_playing_any")
                    ok = desktop.ensure_playing()
                    if ok:
                        self._remember_playback_state(True, paused_by_game=False)
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # Targeted browser command only.  Never fall back to a global media
        # key here: it can target the other app that just stopped playing.
        def _work(page):
            return self._play_player(page)

        ok = bool(self._run_on_page(_work))
        if ok:
            self._remember_playback_state(True, paused_by_game=False)
        return ok

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
        return self.ensure_playing_any()

    def pause(self, paused_by_game: bool = False):
        return self.ensure_paused(paused_by_game=paused_by_game)

    def force_pause(self, paused_by_game: bool = False):
        return self.pause(paused_by_game=paused_by_game)

    def minimize_window(self):
        return True

    def media_play_pause(self) -> bool:
        self._clear_mixer_mute()
        try:
            if not self._uses_desktop_player():
                ok = bool(self._run_on_page(lambda page: self._toggle_player(page)))
                if ok:
                    state = self._run_on_page(
                        lambda page: self._player_is_playing(page)
                    )
                    if state is not None:
                        self._remember_playback_state(bool(state))
                    else:
                        self._is_playing = not self._is_playing
                return ok
        except Exception:
            pass

        def _work(page):
            return self._toggle_player(page)

        ok = bool(self._run_on_page(_work)) or self._send_global_media_key("media_play_pause")
        if ok:
            self._is_playing = not self._is_playing
        return ok

    def media_stop(self) -> bool:
        return self.ensure_paused(paused_by_game=False)

    def media_next(self) -> bool:
        def _work(page):
            return self._click_locator(page, '[data-testid="control-button-skip-forward"]')
        return bool(self._run_on_page(_work))

    def media_prev(self) -> bool:
        def _work(page):
            return self._click_locator(page, '[data-testid="control-button-skip-back"]')
        return bool(self._run_on_page(_work))

    @property
    def paused_by_game(self) -> bool:
        return self._paused_by_game

    def next_track(self):
        return self.media_next()

    def prev_track(self):
        return self.media_prev()

    def set_volume(self, percent):
        return True

    def get_playback_state(self):
        def _work(page):
            state = self._player_is_playing(page)
            if state is not None:
                self._remember_playback_state(state)
                return {"is_playing": state}
            return {"is_playing": self._is_playing}

        result = self._run_on_page(_work)
        return result if result else {"is_playing": self._is_playing}

    def get_current_track(self):
        def _work(page):
            title = ""
            artist = ""
            try:
                title_el = page.locator('[data-testid="context-item-link"]').first
                if title_el.count():
                    title = (title_el.inner_text() or "").strip()
            except Exception:
                pass
            try:
                artist_el = page.locator(
                    '[data-testid="context-item-info-artist"], a[href*="/artist/"]'
                ).first
                if artist_el.count():
                    artist = (artist_el.inner_text() or "").strip()
            except Exception:
                pass
            playing = self._player_is_playing(page)
            if playing is None:
                playing = self._is_playing
            if title or playing:
                return {
                    "name": title or "Spotify",
                    "artist": artist or self._last_query[:40] or "Web player",
                    "album_art": None,
                    "is_playing": bool(playing),
                    "progress_ms": 0,
                    "duration_ms": 0,
                    "uri": self._last_uri,
                    "playlist_uri": self._last_uri,
                    "context_uri": self._last_uri,
                }
            return None

        data = self._run_on_page(_work)
        if data:
            return data
        if not self._is_playing:
            return None
        return {
            "name": "Spotify",
            "artist": self._last_query[:40] or "Web player",
            "album_art": None,
            "is_playing": True,
            "progress_ms": 0,
            "duration_ms": 0,
            "uri": self._last_uri,
            "playlist_uri": self._last_uri,
            "context_uri": self._last_uri,
        }

    def _begin_playback(
        self,
        playlist_uri: str,
        display_name: str = "",
        track_uri: str = "",
    ) -> bool:
        del track_uri  # Always play full playlist context, not a single track URL
        playlist_uri = self.normalize_playlist_uri(playlist_uri)
        if not playlist_uri or not is_playlist_uri(playlist_uri):
            self._last_error = f"Invalid playlist URI: {playlist_uri!r}"
            return False
        play_url = playlist_uri_to_url(playlist_uri)
        self._last_uri = playlist_uri
        self._last_playlist_name = display_name or ""
        self._last_track_uri = ""
        self._paused_by_game = False

        if not self._ensure_browser():
            return False

        self._log(f"Web player: playlist {play_url}")
        ok = self._open_playlist_and_play(playlist_uri)

        if not ok and not self._last_error:
            self._last_error = "Could not start playlist in web player"
        if ok:
            self._session_locked = True
        return ok

    def _start_playback(self, playlist_uri: str, display_name: str, track_uri: str = "", force: bool = True):
        del track_uri, force
        if self._begin_playback(playlist_uri, display_name):
            self._last_playlist_name = display_name
            return {"name": display_name, "uri": playlist_uri}
        return None

    def play_playlist(self, uri):
        uri = self.normalize_playlist_uri(uri)
        if not uri or not is_playlist_uri(uri):
            return False
        try:
            if uri in set(load_blocked_playlist_uris(self.data_dir) or []):
                self._last_error = "Playlist is blocked and will not be played"
                self._log(f"Blocked playlist skipped: {uri}")
                return False
        except Exception:
            pass
        return self._start_playback(uri, "Playlist") is not None

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
        query = build_search_query(game_name, tags or [], query_hint)
        if not pick or not pick.get("uri"):
            self._last_error = (pick or {}).get("error") or (
                f"No playlists found for: {query[:60]}"
            )
            self._log(f"Playlist search failed for: {query[:80]}")
            return None

        self._log(
            f"Playlist search OK: {pick.get('name', 'playlist')[:50]} → "
            f"{playlist_uri_to_url(pick['uri'])}"
        )

        # If one_shot is requested, only attempt the primary pick once and do
        # not iterate the candidate pool. This avoids navigations between
        # multiple playlist pages in the controller browser.
        pool = list(pick.get("pool", []))
        if not pool:
            pool = [{"uri": pick["uri"], "name": pick.get("name", "")}]

        # Filter out any blocked playlists from the candidate pool as an
        # extra safety layer (blocked playlists shouldn't be opened in browser).
        try:
            blocked_set = set(load_blocked_playlist_uris(self.data_dir) or [])
            blocked_set.update(exclude_uris or [])
            filtered = []
            for it in pool:
                try:
                    u = self.normalize_playlist_uri(it.get("uri") or "")
                    if not u or u in blocked_set:
                        continue
                    filtered.append(it)
                except Exception:
                    continue
            pool = filtered
        except Exception:
            pass

        # If filtering removed all candidates, fail gracefully.
        if not pool:
            self._last_error = "All candidate playlists were blocked"
            self._log(f"Playlist pool empty after filtering blocked playlists for query: {query[:80]}")
            return None

        if one_shot:
            item = pool[0]
            uri = self.normalize_playlist_uri(item.get("uri") or "")
            if not uri:
                self._last_error = "Invalid playlist URI in one-shot pick"
                return None
            item_name = item.get("name", "")[:60] or "Spotify Playlist"
            self._log(f"Web player: one-shot try {item_name} → {playlist_uri_to_url(uri)}")
            self._last_play_time = time.time()
            self._last_query = pick.get("query", "")
            self._last_pick = pick
            self._last_error = ""
            display_name = item_name
            result = self._start_playback(uri, display_name)
            if result:
                self._session_locked = True
                result.update({
                    "query": pick.get("query", ""),
                    "pick_rank": 1,
                    "top_count": 1,
                    "pool": pool,
                })
                return result
            self._last_error = "One-shot playback attempt failed"
            return None

        # Start exactly one playlist per request.  Previously a failed or
        # uncertain start (slow buffering, DRM, UI lag) made this loop open the
        # next candidate, which users experienced as "it starts another
        # playlist" after pause/resume.  A definite failure is reported; the
        # user can press "Try another" when they actually want a new mix.
        random.shuffle(pool)
        item = None
        for candidate in pool[:6]:
            if self.normalize_playlist_uri(candidate.get("uri") or ""):
                item = candidate
                break
        if item is None:
            self._last_error = "No valid playlist URI in the candidate pool"
            return None

        uri = self.normalize_playlist_uri(item.get("uri") or "")
        item_name = item.get("name", "")[:60] or "Spotify Playlist"
        self._log(
            f"Web player: playing {item_name} → {playlist_uri_to_url(uri)}"
        )
        self._last_play_time = time.time()
        self._last_query = pick.get("query", "")
        self._last_pick = pick
        self._last_error = ""
        display_name = item_name
        result = self._start_playback(uri, display_name)
        if result:
            self._session_locked = True
            result.update({
                "query": pick.get("query", ""),
                "pick_rank": pool.index(item) + 1,
                "top_count": len(pool),
                "pool": pool,
            })
            return result

        self._last_error = self._last_error or (
            "Could not start the selected playlist in the web player."
        )
        return None

    def search_and_play(self, query, type_="playlist", mood="chill", tags=None, game_name=""):
        return self.play_random_for_mood(
            mood=mood,
            query_hint=query,
            game_name=game_name,
            tags=tags or [],
        )

    def block_current_playlist(self, name: str = "", query: str = "") -> bool:
        if not self._last_uri:
            return False
        return block_playlist_uri(
            self.data_dir,
            self._last_uri,
            name or self._last_playlist_name,
            query or self._last_query,
        )

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
        return [{"id": "web", "name": "Spotify Web Player", "is_active": True}]

    def transfer_playback(self, device_id):
        return True

    def click_playlist_play_button(self, playlist_name: str = None) -> bool:
        if self._last_uri:
            return self._open_playlist_and_play(self._last_uri)
        return False

    def _verify_playback(
        self,
        expected_playlist_uri: str = "",
        expected_track_uri: str = "",
        timeout: float = 6.0,
    ) -> bool:
        del expected_playlist_uri, expected_track_uri
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.get_playback_state() or {}
            if state.get("is_playing"):
                return True
            time.sleep(0.4)
        return False
