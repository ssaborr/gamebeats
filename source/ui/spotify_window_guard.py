"""Keep Spotify's desktop window off-screen and never show it.

Spotify's Chromium build on this machine does not expose its renderer controls
through UI Automation, even when the window is visible.  Showing the window for
UIA therefore bought nothing and produced a visible flash.  This guard is now a
pure hider: it moves Spotify's windows off-screen and hides them, and the UI
layer drives playback with targeted WM_APPCOMMAND messages instead of UIA.

Original window positions are restored when the app closes.

The module is intentionally UI-side: it wraps the desktop controller instance
instead of changing core playback code.
"""
import ctypes
import threading
import time
from ctypes import wintypes

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a runtime dependency
    psutil = None

IS_WINDOWS = hasattr(ctypes, "windll")

OFFSCREEN_X = -32000
OFFSCREEN_Y = -32000
OFFSCREEN_GUARD_X = -30000

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SW_HIDE = 0


class _Win32WindowApi:
    """Small Win32 adapter kept injectable so the guard is unit-testable."""

    def __init__(self):
        self.user32 = ctypes.windll.user32 if IS_WINDOWS else None
        self._spotify_pids = set()
        self._pids_ts = 0.0
        self._pids_lock = threading.Lock()

    def _refresh_spotify_pids(self):
        now = time.time()
        with self._pids_lock:
            if now - self._pids_ts < 2.0:
                return set(self._spotify_pids)
            pids = set()
            if psutil is not None:
                for proc in psutil.process_iter(["name"]):
                    try:
                        if (proc.info.get("name") or "").lower() == "spotify.exe":
                            pids.add(int(proc.pid))
                    except Exception:
                        continue
            self._spotify_pids = pids
            self._pids_ts = now
            return set(pids)

    def is_visible(self, hwnd):
        if not self.user32:
            return False
        try:
            return bool(self.user32.IsWindowVisible(hwnd))
        except Exception:
            return False

    def get_rect(self, hwnd):
        if not self.user32:
            return None
        try:
            rect = wintypes.RECT()
            if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            width = int(rect.right) - int(rect.left)
            height = int(rect.bottom) - int(rect.top)
            if width <= 0 or height <= 0:
                return None
            return (int(rect.left), int(rect.top), width, height)
        except Exception:
            return None

    def move(self, hwnd, x, y, width=0, height=0, keep_size=True):
        if not self.user32:
            return False
        flags = SWP_NOZORDER | SWP_NOACTIVATE
        if keep_size:
            flags |= SWP_NOSIZE
        try:
            return bool(
                self.user32.SetWindowPos(
                    hwnd, 0, int(x), int(y), int(width), int(height), flags
                )
            )
        except Exception:
            return False

    def hide(self, hwnd):
        if not self.user32:
            return False
        try:
            return bool(self.user32.ShowWindow(hwnd, SW_HIDE))
        except Exception:
            return False

    def spotify_windows(self):
        if not self.user32:
            return []
        pids = self._refresh_spotify_pids()
        if not pids:
            return []
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd, _lparam):
            try:
                pid = wintypes.DWORD()
                self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) not in pids:
                    return True
                cls = ctypes.create_unicode_buffer(256)
                self.user32.GetClassNameW(hwnd, cls, 256)
                if cls.value != "Chrome_WidgetWin_1":
                    return True
                title = ctypes.create_unicode_buffer(512)
                self.user32.GetWindowTextW(hwnd, title, 512)
                if not title.value.strip():
                    return True
                found.append(int(hwnd))
            except Exception:
                pass
            return True

        try:
            self.user32.EnumWindows(_enum, 0)
        except Exception:
            return []
        return found


class SpotifyWindowGuard:
    """Keep Spotify's main windows off-screen and hidden."""

    def __init__(self, logger=None, window_api=None, start_watcher=True):
        self._log = logger if callable(logger) else (lambda _msg: None)
        self._api = window_api if window_api is not None else _Win32WindowApi()
        self._lock = threading.RLock()
        self._rects = {}
        self._desktops = []
        self._stop = threading.Event()
        self._thread = None
        if start_watcher and IS_WINDOWS:
            self._thread = threading.Thread(
                target=self._watch, name="SpotifyWindowGuard", daemon=True
            )
            self._thread.start()

    def _remember_rect(self, hwnd):
        rect = self._rects.get(hwnd)
        if rect is not None:
            return rect
        rect = self._api.get_rect(hwnd)
        if rect:
            self._rects[hwnd] = rect
        return rect

    def _move_offscreen_if_needed(self, hwnd):
        rect = self._api.get_rect(hwnd)
        if rect is None:
            return
        self._remember_rect(hwnd)
        # Already off-screen: leave the size alone.  Chromium can re-apply its
        # DPI-scaled size when it is moved, and repeatedly forcing the old
        # size causes needless churn.
        if rect[0] <= OFFSCREEN_GUARD_X or rect[1] <= OFFSCREEN_GUARD_X:
            return
        self._api.move(hwnd, OFFSCREEN_X, OFFSCREEN_Y, keep_size=True)

    def _watch(self):
        while not self._stop.wait(0.04):
            try:
                # Enumerate outside the lock; process/window enumeration can
                # take a few milliseconds and must not delay a hide.
                hwnds = self._api.spotify_windows()
                with self._lock:
                    for hwnd in hwnds:
                        self._move_offscreen_if_needed(hwnd)
                        self._api.hide(hwnd)
            except Exception:
                continue

    def install(self, desktop):
        """Wrap one desktop controller's UIA show/hide methods."""
        if desktop is None:
            return desktop
        with self._lock:
            if any(existing is desktop for existing in self._desktops):
                return desktop
            original_show = getattr(desktop, "_show_spotify_for_uia", None)
            original_hide = getattr(desktop, "_hide_spotify_after_uia", None)
            if not callable(original_show) or not callable(original_hide):
                return desktop
            self._desktops.append(desktop)

        def guarded_show(hwnd):
            # Never call ShowWindow.  Move the window off-screen and report it
            # as already visible so the core does not try a second show.
            try:
                with self._lock:
                    self._move_offscreen_if_needed(hwnd)
            except Exception:
                pass
            return True

        def guarded_hide(hwnd, was_visible):
            # Ignore was_visible: the window must stay hidden regardless of
            # what the core believed before the command.
            try:
                with self._lock:
                    if hwnd:
                        self._move_offscreen_if_needed(hwnd)
                        self._api.hide(hwnd)
            except Exception:
                pass

        desktop._show_spotify_for_uia = guarded_show
        desktop._hide_spotify_after_uia = guarded_hide
        desktop._gamebeats_window_guard = self
        return desktop

    def restore_all(self):
        """Restore original window positions and stop the watcher."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=1.0)
            except Exception:
                pass
        with self._lock:
            for hwnd, rect in list(self._rects.items()):
                try:
                    self._api.move(
                        hwnd, rect[0], rect[1], rect[2], rect[3], keep_size=False
                    )
                    self._api.hide(hwnd)
                except Exception:
                    pass
            self._rects.clear()

    def shutdown(self):
        self.restore_all()
