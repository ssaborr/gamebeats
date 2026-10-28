"""Targeted Spotify desktop transport without showing the window.

The desktop Spotify build used here does not expose its renderer controls to UI
Automation, and showing the window for UIA caused a visible flash.  This UI-side
adapter replaces the UIA transport with WM_APPCOMMAND messages sent directly to
Spotify's own main window.

WM_APPCOMMAND is not a global media key: Windows delivers it to the window that
receives the message, so it cannot pause/next the browser/YouTube player.  The
play and pause app-commands are idempotent; next/previous are sent exactly once
to exactly one Spotify window.
"""
import ctypes

try:
    from core.spotify_desktop import (
        APPCOMMAND_MEDIA_NEXTTRACK,
        APPCOMMAND_MEDIA_PAUSE,
        APPCOMMAND_MEDIA_PLAY,
        APPCOMMAND_MEDIA_PLAYPAUSE,
        APPCOMMAND_MEDIA_PREVIOUSTRACK,
        WM_APPCOMMAND,
        _find_spotify_hwnds,
    )
except Exception:  # pragma: no cover - core is present in the app
    APPCOMMAND_MEDIA_NEXTTRACK = 11
    APPCOMMAND_MEDIA_PAUSE = 47
    APPCOMMAND_MEDIA_PLAY = 46
    APPCOMMAND_MEDIA_PLAYPAUSE = 14
    APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
    WM_APPCOMMAND = 0x319

    def _find_spotify_hwnds(*_args, **_kwargs):
        return []


def _post_message(hwnd, appcommand):
    try:
        return bool(
            ctypes.windll.user32.PostMessageW(
                hwnd, WM_APPCOMMAND, hwnd, int(appcommand) << 16
            )
        )
    except Exception:
        return False


def _main_spotify_hwnd(desktop):
    """Return Spotify's main window, never a browser or another app."""
    try:
        hwnds = [int(h) for h in _find_spotify_hwnds()]
    except Exception:
        return 0
    for hwnd in hwnds:
        try:
            if desktop is None or desktop._is_spotify_main_window(hwnd):
                return hwnd
        except Exception:
            continue
    return hwnds[0] if hwnds else 0


def post_spotify_appcommand(desktop, appcommand):
    """Post one transport command to Spotify's own main window."""
    hwnd = _main_spotify_hwnd(desktop)
    if not hwnd:
        return False
    return _post_message(hwnd, appcommand)


def install_targeted_transport(desktop, logger=None):
    """Replace the desktop controller's UIA transport with targeted messages."""
    if desktop is None:
        return desktop
    if getattr(desktop, "_gamebeats_targeted_transport", False):
        return desktop
    if not hasattr(desktop, "ensure_paused") or not hasattr(desktop, "ensure_playing"):
        return desktop

    log = logger if callable(logger) else (lambda _msg: None)

    def _remember(is_playing, paused_by_game=None):
        try:
            desktop._remember_playback_state(
                bool(is_playing), paused_by_game=paused_by_game
            )
        except Exception:
            pass

    def _clear_mute():
        try:
            desktop._clear_mixer_mute()
        except Exception:
            pass

    def ensure_paused(paused_by_game=False):
        _clear_mute()
        if not post_spotify_appcommand(desktop, APPCOMMAND_MEDIA_PAUSE):
            log("Targeted Spotify pause failed: no Spotify window.")
            return False
        _remember(False, paused_by_game=paused_by_game)
        return True

    def ensure_playing():
        _clear_mute()
        if not post_spotify_appcommand(desktop, APPCOMMAND_MEDIA_PLAY):
            log("Targeted Spotify resume failed: no Spotify window.")
            return False
        _remember(True, paused_by_game=False)
        return True

    def media_play_pause():
        return post_spotify_appcommand(desktop, APPCOMMAND_MEDIA_PLAYPAUSE)

    def send_appcommand(appcommand, label):
        ok = post_spotify_appcommand(desktop, appcommand)
        if ok:
            log(f"Sent Spotify {label} command to its main window.")
        else:
            log(f"Could not send Spotify {label} command: no Spotify window.")
        return ok

    def uia_unavailable(*_args, **_kwargs):
        return False

    desktop.ensure_paused = ensure_paused
    desktop.ensure_playing = ensure_playing
    desktop.media_play_pause = media_play_pause
    desktop.media_stop = ensure_paused
    desktop._send_appcommand_to_spotify = send_appcommand
    desktop._uia_toggle_playback = uia_unavailable
    desktop._uia_invoke_transport = uia_unavailable
    desktop._uia_player_button = lambda: (None, None, True)
    desktop._gamebeats_targeted_transport = True
    return desktop
