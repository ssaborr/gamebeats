"""spotify_python_guard.py

Pure-Python background guard to aggressively hide Spotify desktop windows
using Win32 APIs (ctypes). Starts a daemon thread that continuously
enumerates top-level windows owned by spotify.exe and applies NOACTIVATE,
TOOLWINDOW, removes APPWINDOW, hides the window and pushes it to the
bottom of the Z-order. Works without compiled helpers.

Run as a module for quick testing: `python -m core.spotify_python_guard`
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Constants
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_HIDEWINDOW = 0x0080

SW_HIDE = 0
SW_MINIMIZE = 6

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

try:
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
except Exception:
    pass


def _get_process_exe(pid: int) -> str | None:
    """Return full executable path for PID. Prefer psutil, fallback to QueryFullProcessImageNameW."""
    if HAS_PSUTIL:
        try:
            return psutil.Process(pid).exe()
        except Exception:
            return None

    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        buf_len = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(buf_len.value)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(buf_len))
        if ok:
            return buf.value
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(h)
    return None


def _is_spotify_exe_path(path: str | None) -> bool:
    if not path:
        return False
    try:
        bn = os.path.basename(path).lower()
        return bn == "spotify.exe" or "spotify" in bn
    except Exception:
        return False


def _find_spotify_hwnds(logger=None) -> list:
    """Enumerate top-level windows and return HWNDs owned by spotify.exe."""
    hwnds = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, lparam):
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return True
            exe = _get_process_exe(pid.value)
            if _is_spotify_exe_path(exe):
                hwnds.append(hwnd)
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        pass
    if logger:
        logger(f"spotify_python_guard: found {len(hwnds)} spotify HWND(s)")
    return hwnds


def _hide_hwnd(hwnd, logger=None):
    try:
        # 1. Apply NOACTIVATE + TOOLWINDOW and remove APPWINDOW
        try:
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        except Exception:
            style = 0
        target = (style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        try:
            if style != target:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, target)
        except Exception:
            pass

        # 2. Minimize then hide and push to bottom
        try:
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        except Exception:
            pass
        try:
            user32.ShowWindow(hwnd, SW_HIDE)
        except Exception:
            pass
        try:
            user32.SetWindowPos(hwnd, HWND_BOTTOM, -32000, -32000, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_HIDEWINDOW)
        except Exception:
            pass

        # 3. Try to block foreground stealing
        try:
            # AllowSetForegroundWindow(0) and LockSetForegroundWindow(1)
            try:
                user32.AllowSetForegroundWindow(0)
            except Exception:
                pass
            try:
                user32.LockSetForegroundWindow(1)
            except Exception:
                pass
        except Exception:
            pass

        if logger:
            logger(f"spotify_python_guard: hid HWND {hwnd:#x}")
    except Exception as exc:
        if logger:
            logger(f"spotify_python_guard: hide failed {exc}")


def _guard_loop(stop_event: threading.Event, poll_interval: float = 0.35, logger=None):
    """Continuously find and hide Spotify windows until stop_event is set."""
    while not stop_event.is_set():
        try:
            hwnds = _find_spotify_hwnds(logger)
            for hwnd in hwnds:
                _hide_hwnd(hwnd, logger=logger)
        except Exception:
            pass
        # Small sleep to avoid burning CPU but keep responsive to new windows
        stop_event.wait(poll_interval)


def start_guard_thread(logger=None, poll_interval: float = 0.35):
    """Start the guard in a daemon thread.

    Returns (thread, stop_event).
    """
    stop = threading.Event()
    thread = threading.Thread(target=_guard_loop, args=(stop, poll_interval, logger), daemon=True, name="spotify-python-guard")
    thread.start()
    if logger:
        logger("spotify_python_guard: started")
    return thread, stop


if __name__ == "__main__":
    import sys

    def _log(msg):
        print(msg)

    t, stop = start_guard_thread(logger=_log, poll_interval=0.25)
    _log("spotify_python_guard running — press Ctrl+C to exit")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        t.join(2)
        _log("exiting")
