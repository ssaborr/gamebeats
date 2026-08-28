"""
playback_guard.py — simple guard to suppress other logic during Spotify
playback startup. Other modules should check `is_active()` before sending
pause/resume commands while a playlist is being started.
"""
import threading
import time
from typing import Optional

try:
    from core.audio_monitor import get_spotify_audio_peak, SPOTIFY_LOOPBACK_LOUD
except Exception:
    def get_spotify_audio_peak():
        return 0.0, -60.0, "unavailable"
    SPOTIFY_LOOPBACK_LOUD = 0.01

_lock = threading.Lock()
_active = False
_info = {}
_thread: Optional[threading.Thread] = None


def is_active() -> bool:
    with _lock:
        return bool(_active)


def info() -> dict:
    with _lock:
        return dict(_info)


def stop() -> None:
    """Deactivate the guard immediately."""
    global _active, _info
    with _lock:
        _active = False
        _info = {}


def start(playlist_uri: str = "", timeout: float = 12.0, poll: float = 0.25) -> None:
    """Activate the guard and spawn a watcher thread that clears it when
    Spotify audio is detected or when `timeout` elapses.
    """
    global _active, _info, _thread
    with _lock:
        _active = True
        _info = {"uri": playlist_uri, "start": time.time(), "timeout": float(timeout)}

    def _watch():
        deadline = time.time() + float(timeout)
        try:
            while True:
                with _lock:
                    if not _active:
                        break
                    if time.time() >= deadline:
                        break
                try:
                    peak, db, status = get_spotify_audio_peak()
                    if peak is not None and peak >= SPOTIFY_LOOPBACK_LOUD:
                        break
                except Exception:
                    pass
                time.sleep(poll)
        finally:
            stop()

    # Spawn watcher thread (daemon so it doesn't block shutdown)
    _thread = threading.Thread(target=_watch, daemon=True, name="playback-guard-watcher")
    _thread.start()
