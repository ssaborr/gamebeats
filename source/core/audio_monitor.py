"""
audio_monitor.py — detect game audio loudness (Windows).

Detection priority:
  1. Windows process loopback capture (game) — captures only the target game process
     tree when supported by the OS/native helper.
  2. Windows process loopback capture (Spotify) — captures Spotify audio separately.
  3. PyAudioWPatch WASAPI loopback — captures actual PCM frames from the
     default output device and computes RMS.
"""

import sys
import threading
import time
import struct
import math

HAS_PSUTIL     = False
HAS_PYAUDIO_WP = False
HAS_PROCESS_LOOPBACK = False

if sys.platform == "win32":
    try:
        import psutil
        HAS_PSUTIL = True
    except ImportError:
        pass
    try:
        import pyaudiowpatch as pyaudio
        HAS_PYAUDIO_WP = True
    except ImportError:
        pass
    try:
        from process_audio_capture import (
            PacCaptureMode,
            ProcessAudioCapture,
            ProcessAudioCaptureError,
        )
        HAS_PROCESS_LOOPBACK = ProcessAudioCapture.is_supported()
    except Exception:
        HAS_PROCESS_LOOPBACK = False
    try:
        from pycaw.pycaw import AudioUtilities
        from pycaw.api.endpointvolume import IAudioMeterInformation
        HAS_PYCAW = True
    except Exception:
        HAS_PYCAW = False

# ── Thresholds ────────────────────────────────────────────────────────────────
PROCESS_LOOPBACK_LOUD = 0.004  # Game audio detection threshold
SPOTIFY_LOOPBACK_LOUD = 0.005  # Spotify audio detection threshold (lowered for desktop-only mode)
OTHER_AUDIO_LOUD = 0.008       # Any non-Spotify app/browser audio (session meter)


# ── PyAudioWPatch loopback ────────────────────────────────────────────────────
# Captures total speaker output as PCM and computes RMS.
# This is the most reliable method when the WASAPI session peak meter is broken.

_loopback_lock   = threading.Lock()
_loopback_stream = None
_loopback_ch     = 2
_loopback_rate   = 44100
_pa_instance     = None


def _rms_from_frames(data: bytes) -> float:
    """Compute RMS peak from raw 16-bit PCM bytes, normalised 0-1."""
    if not data or len(data) < 2:
        return 0.0
    try:
        n = len(data) // 2
        samples = struct.unpack(f"<{n}h", data[:n * 2])
        if not samples:
            return 0.0
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        return min(1.0, rms / 32768.0)
    except Exception:
        return 0.0


def _open_loopback_stream():
    """
    Open a WASAPI loopback stream on the default output device using
    PyAudioWPatch's get_loopback_device_info_generator(), which is the
    correct API for loopback capture on Windows.
    """
    global _pa_instance, _loopback_ch, _loopback_rate
    try:
        if _pa_instance is None:
            _pa_instance = pyaudio.PyAudio()
        pa = _pa_instance

        # Get WASAPI host API info
        wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out_idx = wasapi_info.get("defaultOutputDevice", -1)
        if default_out_idx < 0:
            return None

        default_speakers = pa.get_device_info_by_index(default_out_idx)

        # PyAudioWPatch provides get_loopback_device_info_generator() which
        # yields loopback-capable input devices corresponding to output devices.
        loopback_device = None
        try:
            for loopback in pa.get_loopback_device_info_generator():
                # Match by name — the loopback device name contains the speaker name
                if default_speakers.get("name", "") in loopback.get("name", ""):
                    loopback_device = loopback
                    break
        except Exception:
            pass

        if loopback_device is None:
            return None

        ch   = min(int(loopback_device.get("maxInputChannels", 2) or 2), 2)
        rate = int(loopback_device.get("defaultSampleRate", 44100) or 44100)
        _loopback_ch   = ch
        _loopback_rate = rate

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=ch,
            rate=rate,
            input=True,
            input_device_index=int(loopback_device["index"]),
            frames_per_buffer=1024,
        )
        return stream
    except Exception:
        return None


def get_loopback_peak() -> float:
    """
    Capture one buffer from the loopback stream and return RMS peak (0-1).
    Reuses the open stream across calls; reopens on failure.
    """
    global _loopback_stream, _pa_instance

    if not HAS_PYAUDIO_WP:
        return 0.0

    with _loopback_lock:
        if _loopback_stream is None:
            _loopback_stream = _open_loopback_stream()

        if _loopback_stream is None:
            return 0.0

        try:
            data = _loopback_stream.read(1024, exception_on_overflow=False)
            return _rms_from_frames(data)
        except Exception:
            try:
                _loopback_stream.stop_stream()
                _loopback_stream.close()
            except Exception:
                pass
            _loopback_stream = None
            return 0.0


def close_loopback():
    """Release PyAudioWPatch resources — call on monitor shutdown."""
    global _loopback_stream, _pa_instance
    with _loopback_lock:
        if _loopback_stream is not None:
            try:
                _loopback_stream.stop_stream()
                _loopback_stream.close()
            except Exception:
                pass
            _loopback_stream = None
        if _pa_instance is not None:
            try:
                _pa_instance.terminate()
            except Exception:
                pass
            _pa_instance = None


# ── Windows process loopback ──────────────────────────────────────────────────
# Uses AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS through process-audio-capture's
# native DLL. This captures only the target PID/process tree.

_process_loopback_lock = threading.Lock()
_process_loopback_capture = None
_process_loopback_pid = 0
_process_loopback_disabled_until = 0.0
_process_loopback_error = ""


def _db_to_peak(level_db: float) -> float:
    try:
        level_db = float(level_db)
    except Exception:
        return 0.0
    if level_db <= -59.0:
        return 0.0
    return max(0.0, min(1.0, 10.0 ** (level_db / 20.0)))


def close_process_loopback():
    global _process_loopback_capture, _process_loopback_pid
    with _process_loopback_lock:
        if _process_loopback_capture is not None:
            try:
                _process_loopback_capture.stop()
            except Exception:
                pass
        _process_loopback_capture = None
        _process_loopback_pid = 0


def get_process_loopback_peak(pid: int) -> tuple:
    global _process_loopback_capture, _process_loopback_pid
    global _process_loopback_disabled_until, _process_loopback_error

    if not HAS_PROCESS_LOOPBACK:
        return 0.0, -60.0, "unavailable"
    if not pid:
        return 0.0, -60.0, "no-pid"

    now = time.time()
    with _process_loopback_lock:
        if now < _process_loopback_disabled_until:
            return 0.0, -60.0, _process_loopback_error or "disabled"

        if _process_loopback_capture is not None and _process_loopback_pid != pid:
            try:
                _process_loopback_capture.stop()
            except Exception:
                pass
            _process_loopback_capture = None
            _process_loopback_pid = 0

        if _process_loopback_capture is None:
            try:
                _process_loopback_capture = ProcessAudioCapture(
                    pid=int(pid),
                    output_path=None,
                    mode=PacCaptureMode.INCLUDE,
                )
                _process_loopback_capture.start()
                _process_loopback_pid = int(pid)
                _process_loopback_error = ""
            except Exception as ex:
                _process_loopback_capture = None
                _process_loopback_pid = 0
                _process_loopback_error = f"process-loopback-error: {ex}"
                _process_loopback_disabled_until = now + 10.0
                return 0.0, -60.0, "error"

        try:
            if not _process_loopback_capture.is_capturing:
                try:
                    _process_loopback_capture.stop()
                except Exception:
                    pass
                _process_loopback_capture = None
                _process_loopback_pid = 0
                _process_loopback_disabled_until = now + 2.0
                return 0.0, -60.0, "stopped"

            level_db = float(_process_loopback_capture.level_db)
            return _db_to_peak(level_db), level_db, "ok"
        except Exception as ex:
            try:
                _process_loopback_capture.stop()
            except Exception:
                pass
            _process_loopback_capture = None
            _process_loopback_pid = 0
            _process_loopback_error = f"process-loopback-read-error: {ex}"
            _process_loopback_disabled_until = now + 5.0
            return 0.0, -60.0, "error"


# ── Spotify process loopback ──────────────────────────────────────────────────

_spotify_loopback_lock = threading.Lock()
_spotify_loopback_capture = None
_spotify_loopback_captures = []  # List of capture instances for multiple processes
_spotify_loopback_pid = 0
_spotify_loopback_disabled_until = 0.0
_spotify_loopback_error = ""
_registered_music_pids: list = []
_registered_music_pid_lock = threading.Lock()
_browser_audio_only = False


def set_browser_audio_only(enabled: bool):
    """When True, loopback uses only registered browser PIDs (not spotify.exe)."""
    global _browser_audio_only, _spotify_loopback_pid
    _browser_audio_only = bool(enabled)
    close_spotify_loopback()


def _expand_process_tree(pids) -> list:
    """Include child processes so Chrome renderer audio is captured too.

    Chrome's browser process is the one carrying --user-data-dir, but audio is
    produced by renderer/utility children. Capturing only the browser PID
    yields silence, which previously made GameBeats think a playing web
    playlist had finished.
    """
    roots = sorted({int(p) for p in (pids or []) if int(p) > 0})
    if not HAS_PSUTIL:
        return roots
    expanded = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in expanded:
            continue
        expanded.add(pid)
        try:
            for child in psutil.Process(pid).children(recursive=False):
                if child.pid not in expanded:
                    stack.append(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return sorted(expanded)


def register_music_player_pids(pids: list):
    """Register browser (or other) PIDs used for Spotify Web Player audio loopback."""
    global _spotify_loopback_pid
    cleaned = _expand_process_tree(pids)
    with _registered_music_pid_lock:
        old = list(_registered_music_pids)
        _registered_music_pids[:] = cleaned
    if old != cleaned:
        close_spotify_loopback()


def close_spotify_loopback():
    global _spotify_loopback_capture, _spotify_loopback_pid, _spotify_loopback_captures
    with _spotify_loopback_lock:
        if _spotify_loopback_capture is not None:
            try:
                _spotify_loopback_capture.stop()
            except Exception:
                pass
        # Close all multi-process captures
        for cap in _spotify_loopback_captures:
            try:
                cap.stop()
            except Exception:
                pass
        _spotify_loopback_capture = None
        _spotify_loopback_captures = []
        _spotify_loopback_pid = 0


def _desktop_spotify_pids() -> list:
    """All spotify.exe process IDs (desktop app / silent sidecar)."""
    if not HAS_PSUTIL:
        return []
    try:
        spotify_pids = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name == "spotify.exe":
                    spotify_pids.append(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return sorted(spotify_pids)
    except Exception:
        pass
    return []


def get_all_spotify_pids() -> list:
    """Find Spotify desktop and/or registered web-player browser process IDs.

    In the simplified dual flow the browser is *supposed* to be the audio
    source, but Spotify can keep playback on the desktop sidecar when the
    output switch fails.  Monitoring only the browser then reads silence while
    music is clearly audible, so the UI shows "paused" and other-app audio
    never pauses the music.  Include both sources unless the caller explicitly
    requested browser-only monitoring.
    """
    with _registered_music_pid_lock:
        registered = list(_registered_music_pids)
    desktop = _desktop_spotify_pids()
    if registered:
        return sorted({int(pid) for pid in registered} | {int(pid) for pid in desktop})
    # Browser mode without a matched player PID yet: fall back to the desktop
    # client so audible music is never invisible.  _browser_audio_only still
    # suppresses the "other audio" meter until the browser is registered.
    return desktop


def _session_peak_for_pids(pids) -> float:
    """Max WASAPI session peak for the given process tree, without loopback.

    Used to tell the browser player and the desktop sidecar apart.  The global
    process-loopback meter intentionally unions both sources, but pause/resume
    decisions need to know which one is actually audible right now.
    """
    if not HAS_PYCAW:
        return 0.0
    targets = set(_expand_process_tree(pids))
    if not targets:
        return 0.0
    try:
        _ensure_com_initialized()
    except Exception:
        pass
    max_peak = 0.0
    with _other_audio_lock:
        try:
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc is None:
                    continue
                try:
                    if int(proc.pid) not in targets:
                        continue
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    peak = float(meter.GetPeakValue())
                except Exception:
                    continue
                if peak > max_peak:
                    max_peak = peak
        except Exception:
            return 0.0
    return max_peak


def get_browser_spotify_peak() -> tuple:
    """(peak, status) for the automated web-player browser only."""
    with _registered_music_pid_lock:
        pids = list(_registered_music_pids)
    if not pids:
        return 0.0, "no-browser-pids"
    return _session_peak_for_pids(pids), "ok"


def get_desktop_spotify_peak() -> tuple:
    """(peak, status) for spotify.exe (desktop client / silent sidecar)."""
    pids = _desktop_spotify_pids()
    if not pids:
        return 0.0, "no-spotify"
    return _session_peak_for_pids(pids), "ok"


def get_spotify_pid() -> int:
    """Find the main running Spotify process ID (finds all and returns the smallest PID)."""
    if not HAS_PSUTIL:
        return 0
    try:
        spotify_pids = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name == "spotify.exe":
                    spotify_pids.append(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        # Return the smallest PID (likely the parent/main process)
        return min(spotify_pids) if spotify_pids else 0
    except Exception:
        pass
    return 0


def get_spotify_loopback_peak() -> tuple:
    global _spotify_loopback_capture, _spotify_loopback_pid, _spotify_loopback_captures
    global _spotify_loopback_disabled_until, _spotify_loopback_error

    if not HAS_PROCESS_LOOPBACK:
        return 0.0, -60.0, "unavailable"

    all_spotify_pids = get_all_spotify_pids()
    main_spotify_pid = min(all_spotify_pids) if all_spotify_pids else 0
    
    if not main_spotify_pid:
        close_spotify_loopback()
        if _browser_audio_only:
            return 0.0, -60.0, "no-browser"
        return 0.0, -60.0, "no-spotify"

    now = time.time()
    with _spotify_loopback_lock:
        if now < _spotify_loopback_disabled_until:
            return 0.0, -60.0, _spotify_loopback_error or "disabled"

        # If Spotify PIDs changed, reset captures
        if _spotify_loopback_pid != main_spotify_pid:
            if _spotify_loopback_capture is not None:
                try:
                    _spotify_loopback_capture.stop()
                except Exception:
                    pass
            for cap in _spotify_loopback_captures:
                try:
                    cap.stop()
                except Exception:
                    pass
            _spotify_loopback_capture = None
            _spotify_loopback_captures = []
            _spotify_loopback_pid = 0

        # Try to create capture instances for all Spotify processes
        if _spotify_loopback_capture is None and not _spotify_loopback_captures:
            try:
                # First try: capture from all Spotify processes
                for pid in all_spotify_pids:
                    try:
                        cap = ProcessAudioCapture(
                            pid=int(pid),
                            output_path=None,
                            mode=PacCaptureMode.INCLUDE,
                        )
                        cap.start()
                        _spotify_loopback_captures.append(cap)
                    except Exception:
                        pass
                
                if _spotify_loopback_captures:
                    _spotify_loopback_pid = main_spotify_pid
                    _spotify_loopback_error = ""
                else:
                    # Fallback: try main process only
                    _spotify_loopback_capture = ProcessAudioCapture(
                        pid=int(main_spotify_pid),
                        output_path=None,
                        mode=PacCaptureMode.INCLUDE,
                    )
                    _spotify_loopback_capture.start()
                    _spotify_loopback_pid = main_spotify_pid
                    _spotify_loopback_error = ""
            except Exception as ex:
                _spotify_loopback_capture = None
                _spotify_loopback_captures = []
                _spotify_loopback_pid = 0
                _spotify_loopback_error = f"spotify-loopback-error: {ex}"
                _spotify_loopback_disabled_until = now + 10.0
                return 0.0, -60.0, "error"

        try:
            max_level_db = -60.0
            max_peak = 0.0
            
            # Check multi-process captures
            if _spotify_loopback_captures:
                active_caps = []
                for cap in _spotify_loopback_captures:
                    try:
                        if cap.is_capturing:
                            level_db = float(cap.level_db)
                            peak = _db_to_peak(level_db)
                            max_level_db = max(max_level_db, level_db)
                            max_peak = max(max_peak, peak)
                            active_caps.append(cap)
                        else:
                            try:
                                cap.stop()
                            except Exception:
                                pass
                    except Exception:
                        try:
                            cap.stop()
                        except Exception:
                            pass
                
                _spotify_loopback_captures = active_caps
                
                if _spotify_loopback_captures:
                    return max_peak, max_level_db, "ok"
                else:
                    # All multi-process captures failed, fall back to single process
                    _spotify_loopback_capture = None
                    _spotify_loopback_pid = 0
                    _spotify_loopback_disabled_until = now + 2.0
                    return 0.0, -60.0, "stopped"
            
            # Check single-process capture (fallback)
            elif _spotify_loopback_capture is not None:
                if not _spotify_loopback_capture.is_capturing:
                    try:
                        _spotify_loopback_capture.stop()
                    except Exception:
                        pass
                    _spotify_loopback_capture = None
                    _spotify_loopback_pid = 0
                    _spotify_loopback_disabled_until = now + 2.0
                    return 0.0, -60.0, "stopped"

                level_db = float(_spotify_loopback_capture.level_db)
                return _db_to_peak(level_db), level_db, "ok"
        except Exception as ex:
            if _spotify_loopback_capture is not None:
                try:
                    _spotify_loopback_capture.stop()
                except Exception:
                    pass
            for cap in _spotify_loopback_captures:
                try:
                    cap.stop()
                except Exception:
                    pass
            _spotify_loopback_capture = None
            _spotify_loopback_captures = []
            _spotify_loopback_pid = 0
            _spotify_loopback_error = f"spotify-loopback-read-error: {ex}"
            _spotify_loopback_disabled_until = now + 5.0
            return 0.0, -60.0, "error"


# ── Other application/browser audio ───────────────────────────────────────────
# Process loopback capture is not universal.  Microsoft Edge, for example,
# reports -60 dB through ProcessAudioCapture even while its WASAPI session
# meter reads 0.3+.  The per-session peak meter sees the audio, so it is used
# as a second, independent signal.  Our own Spotify browser and the desktop
# sidecar are excluded so the music can never pause itself.

_other_audio_lock = threading.Lock()
_com_initialized = threading.local()


def _ensure_com_initialized() -> None:
    if not HAS_PYCAW or getattr(_com_initialized, "done", False):
        return
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    _com_initialized.done = True


def _spotify_exclusion_pids() -> set:
    """PIDs whose audio belongs to GameBeats' own music, never 'other' audio."""
    excluded = set()
    try:
        # In web mode this is the automated browser's process tree; in
        # desktop mode get_all_spotify_pids() falls back to spotify.exe.
        for pid in _expand_process_tree(get_all_spotify_pids()):
            if pid:
                excluded.add(int(pid))
    except Exception:
        pass
    if HAS_PSUTIL:
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if (proc.info.get("name") or "").lower() == "spotify.exe":
                        excluded.add(int(proc.info["pid"]))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
    try:
        import os
        excluded.add(int(os.getpid()))
    except Exception:
        pass
    return excluded


def get_other_audio_peak() -> tuple:
    """Return (peak, status) for any non-Spotify app or browser audio.

    This intentionally includes the detected game, other browsers, media
    players and anything else the user is listening to.  It excludes the
    automated Spotify browser, the desktop sidecar and GameBeats itself.
    """
    if not HAS_PYCAW:
        return 0.0, "unavailable"
    if _browser_audio_only:
        with _registered_music_pid_lock:
            no_browser_pids = not _registered_music_pids
        if no_browser_pids:
            # Do not mistake the still-unregistered web player for "other"
            # audio during startup.  But if the desktop sidecar is audible,
            # the web player browser is silent, so other apps must still be
            # detected (otherwise a beep can never pause the desktop track).
            desktop_peak, desktop_status = get_desktop_spotify_peak()
            if not (desktop_status == "ok" and desktop_peak >= 0.0015):
                return 0.0, "no-music-pids"
    _ensure_com_initialized()
    excluded = _spotify_exclusion_pids()
    max_peak = 0.0
    with _other_audio_lock:
        try:
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc is None:
                    continue
                try:
                    pid = int(proc.pid)
                    name = (proc.name() or "").lower()
                except Exception:
                    continue
                if pid in excluded or name in (
                    "spotify.exe", "gamebeats.exe", "audiodg.exe"
                ):
                    continue
                try:
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    peak = float(meter.GetPeakValue())
                except Exception:
                    continue
                if peak > max_peak:
                    max_peak = peak
            return max_peak, "ok"
        except Exception as ex:
            return 0.0, f"error: {ex}"


def _pids_for_game(pid: int = 0, proc_name: str = "") -> set:
    pids = set()
    if pid:
        pids.add(int(pid))
        if HAS_PSUTIL:
            try:
                root = psutil.Process(pid)
                for child in root.children(recursive=True):
                    try:
                        pids.add(child.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    target = (proc_name or "").lower().strip()
    if target and HAS_PSUTIL:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower().strip()
                if name == target:
                    pids.add(proc.info["pid"])
                elif target.replace(".exe", "") and target.replace(".exe", "") in name:
                    pids.add(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return pids


def _game_is_foreground(game_pids: set) -> bool:
    if sys.platform != "win32" or not game_pids:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong()
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        fp = int(pid.value)
        if fp in game_pids:
            return True
        if HAS_PSUTIL:
            try:
                proc = psutil.Process(fp)
                while proc:
                    if proc.pid in game_pids:
                        return True
                    proc = proc.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass
    return False


# ── Main measurement ──────────────────────────────────────────────────────────

def measure_game_loud(
    pid: int = 0,
    proc_name: str = "",
    spotify_paused: bool = False,
) -> tuple:
    """
    Returns (is_loud, peak, mode, debug_dict).

    "Loud" means any audio that is not GameBeats' own music: the detected
    game, another browser, a media player, etc.  Process loopback is used for
    the game and a per-session WASAPI meter is combined with it because some
    apps (Edge, for example) are invisible to process capture.
    """
    if not HAS_PROCESS_LOOPBACK and not HAS_PYAUDIO_WP and not HAS_PYCAW:
        return False, 0.0, "none", {}

    game_pids = _pids_for_game(pid, proc_name)
    fg = _game_is_foreground(game_pids) if game_pids else False

    other_peak, other_status = get_other_audio_peak()
    other_loud = other_peak >= OTHER_AUDIO_LOUD

    dbg = {
        "pids":         len(game_pids),
        "game_peak":    0.0,
        "game_db":      -60.0,
        "game_status":  "",
        "spotify_peak": 0.0,
        "spotify_db":   -60.0,
        "spotify_status": "",
        "other_peak":   other_peak,
        "other_status": other_status,
        "other_loud":   other_loud,
        "lb_peak":      0.0,
        "fg":           fg,
    }

    if not game_pids:
        if other_status == "ok":
            return other_loud, other_peak, "other-session", dbg
        return False, 0.0, "none", dbg

    # Process-specific loopback for the game. When available it is
    # authoritative for that process, but other apps still come from the
    # session meter above.
    if HAS_PROCESS_LOOPBACK:
        target_pid = pid if pid in game_pids else next(iter(game_pids))
        game_peak, game_db, game_status = get_process_loopback_peak(target_pid)
        dbg["game_peak"] = game_peak
        dbg["game_db"] = game_db
        dbg["game_status"] = game_status

        # Also check Spotify audio
        spotify_peak, spotify_db, spotify_status = get_spotify_loopback_peak()
        dbg["spotify_peak"] = spotify_peak
        dbg["spotify_db"] = spotify_db
        dbg["spotify_status"] = spotify_status

        if game_status == "ok":
            game_loud = game_peak >= PROCESS_LOOPBACK_LOUD
            loud = game_loud or other_loud
            peak = max(game_peak, other_peak)
            mode = "process+other" if other_loud else "process"
            return loud, peak, mode, dbg

    # ── Fallback: PyAudioWPatch loopback ──────────────────────────────────────
    if HAS_PYAUDIO_WP:
        lb_peak = get_loopback_peak()
        dbg["lb_peak"] = lb_peak
        if other_loud:
            # The session meter already saw a non-Spotify app. Use total
            # loopback only to report the stronger of the two peaks.
            return True, max(other_peak, lb_peak), "other-session", dbg
        if lb_peak > 0.0:
            if not spotify_paused:
                spotify_peak = float(dbg.get("spotify_peak", 0.0) or 0.0)
                spotify_status = str(dbg.get("spotify_status", "") or "")
                spotify_is_loud = (
                    spotify_status == "ok"
                    and spotify_peak >= SPOTIFY_LOOPBACK_LOUD
                )
                mostly_spotify = lb_peak <= max(PROCESS_LOOPBACK_LOUD, spotify_peak * 1.35)
                if spotify_is_loud and mostly_spotify:
                    return False, 0.0, "loopback-spotify-filtered", dbg

            # When ProcessAudioCapture is not available, use loopback as fallback.
            # Only trust it while Spotify is paused/silent enough not to pollute
            # the game meter.
            return lb_peak >= PROCESS_LOOPBACK_LOUD, lb_peak, "loopback", dbg

    if other_status == "ok":
        return other_loud, other_peak, "other-session", dbg
    return False, 0.0, "none", dbg


def get_game_audio_peak(pid: int = 0, proc_name: str = "") -> float:
    """Get current game audio peak level."""
    _, peak, _, _ = measure_game_loud(pid, proc_name, spotify_paused=False)
    return peak


def get_spotify_audio_peak() -> float:
    """Get current Spotify audio peak level."""
    _, peak, _, _ = get_spotify_loopback_peak()
    return peak


def format_debug(dbg: dict, mode: str = "") -> str:
    fg = "fg" if dbg.get("fg") else "bg"
    game_peak = float(dbg.get("game_peak", 0))
    game_db = float(dbg.get("game_db", -60))
    game_stat = str(dbg.get("game_status", "") or "")
    spotify_peak = float(dbg.get("spotify_peak", 0))
    spotify_db = float(dbg.get("spotify_db", -60))
    spotify_stat = str(dbg.get("spotify_status", "") or "")
    other_peak = float(dbg.get("other_peak", 0))
    other_stat = str(dbg.get("other_status", "") or "")
    lb_peak = float(dbg.get("lb_peak", 0))
    
    extra = f" mode={mode}" if mode else ""
    lb_str = f" lb_peak={lb_peak:.4f}" if HAS_PYAUDIO_WP else ""
    game_str = f" game_peak={game_peak:.4f} game_db={game_db:.1f}"
    if game_stat and game_stat != "ok":
        game_str += f" game={game_stat}"
    spotify_str = f" spotify_peak={spotify_peak:.4f} spotify_db={spotify_db:.1f}"
    if spotify_stat and spotify_stat != "ok":
        spotify_str += f" spotify={spotify_stat}"
    other_str = f" other_peak={other_peak:.4f}"
    if other_stat and other_stat != "ok":
        other_str += f" other={other_stat}"
    
    return (
        f"{fg} pids={dbg.get('pids', 0)}{game_str}{spotify_str}{other_str}{lb_str} ok-meter{extra}"
    )


def debug_game_audio(pid: int = 0, proc_name: str = "", mode: str = "") -> str:
    if not HAS_PROCESS_LOOPBACK and not HAS_PYAUDIO_WP:
        return "no audio monitor backend installed"
    loud, peak, m, dbg = measure_game_loud(pid, proc_name, spotify_paused=False)
    if "lb_peak" not in dbg:
        dbg["lb_peak"] = peak
    return format_debug(dbg, mode or m)


def _clear_spotify_mixer_mute():
    """No-op stub for backward compatibility. Mute/unmute no longer needed with ProcessAudioCapture."""
    pass


class GameMusicDetector:
    def __init__(self, window_sec=6.0):
        self.window_sec    = window_sec
        self._samples      = []
        self._pid          = 0
        self._proc_name    = ""
        self._last_mode    = ""
        self._last_dbg     = {}
        self._last_loud    = False

    def update(self, pid: int = 0, proc_name: str = "", spotify_paused: bool = False):
        if pid:
            self._pid = pid
        if proc_name:
            self._proc_name = proc_name

        loud, peak, mode, dbg = measure_game_loud(
            self._pid,
            self._proc_name,
            spotify_paused=spotify_paused,
        )

        self._last_mode = mode
        self._last_loud = loud
        self._last_dbg  = dbg
        now = time.time()
        # Keep only samples marked as actual game audio
        self._samples.append((now, peak if loud else 0.0))
        cutoff = now - self.window_sec
        self._samples = [(t, p) for t, p in self._samples if t >= cutoff]

    def shutdown(self):
        close_process_loopback()
        close_spotify_loopback()
        close_loopback()

    @property
    def current_peak(self) -> float:
        if not self._samples:
            return 0.0
        return float(self._samples[-1][1])
    
    @property
    def is_loud(self) -> bool:
        return self._last_loud

    @property
    def other_peak(self) -> float:
        return float(self._last_dbg.get("other_peak", 0.0) or 0.0)

    @property
    def other_loud(self) -> bool:
        return bool(self._last_dbg.get("other_loud", False))

    @property
    def other_status(self) -> str:
        return str(self._last_dbg.get("other_status", "") or "")

    def debug_line(self) -> str:
        return format_debug(self._last_dbg, self._last_mode)

    @property
    def is_music_playing(self) -> bool:
        return self.is_loud

    @property
    def meter_broken(self) -> bool:
        return False
