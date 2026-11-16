import sys
import os
import traceback

# Keep these handles alive for the lifetime of the first instance.  The mutex
# makes Windows reject a second copy, and the event is how that second copy
# asks the already-running window to come back to the front.
_SINGLE_INSTANCE_MUTEX = None
_SINGLE_INSTANCE_EVENT = None


def _single_instance_guard():
    """Return True for the first GameBeats instance, False for a relaunch."""
    global _SINGLE_INSTANCE_MUTEX, _SINGLE_INSTANCE_EVENT
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateEventW.restype = wintypes.HANDLE

        mutex = kernel32.CreateMutexW(
            None, False, ctypes.c_wchar_p("Local\\GameBeatsSingleInstance"))
        already_running = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        event = kernel32.CreateEventW(
            None, False, False,
            ctypes.c_wchar_p("Local\\GameBeatsShowWindow"),
        )

        if already_running:
            # Tell the first instance to restore its window, then leave.
            if event:
                kernel32.SetEvent(event)
                kernel32.CloseHandle(event)
            if mutex:
                kernel32.CloseHandle(mutex)
            return False

        _SINGLE_INSTANCE_MUTEX = mutex
        _SINGLE_INSTANCE_EVENT = event
        return True
    except Exception:
        # If the guard itself fails, don't block the user from opening the app.
        return True


try:
    # Nuitka polyfill and Playwright path configuration
    if "__compiled__" in globals():
        sys.frozen = True
        sys._MEIPASS = os.path.dirname(sys.executable)
        driver_dir = os.path.join(sys._MEIPASS, "playwright", "driver")
        if os.path.isdir(driver_dir):
            os.environ.setdefault("PLAYWRIGHT_DRIVER_PATH", driver_dir)
        browsers_dir = os.path.join(driver_dir, "package", ".local-browsers")
        if os.path.isdir(browsers_dir):
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers_dir)

    sys.path.insert(0, os.path.dirname(__file__))
    from ui.app import GameBeatsApp

    if __name__ == "__main__":
        if not _single_instance_guard():
            sys.exit(0)
        app = GameBeatsApp()
        if _SINGLE_INSTANCE_EVENT:
            app.listen_for_second_instance(_SINGLE_INSTANCE_EVENT)
        app.run()
except Exception as e:
    with open(os.path.join(os.path.expanduser("~"), "Desktop", "gamebeats_crash.txt"), "w") as f:
        f.write(traceback.format_exc())
