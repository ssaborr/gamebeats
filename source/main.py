import sys
import os
import traceback

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
        app = GameBeatsApp()
        app.run()
except Exception as e:
    with open(os.path.join(os.path.expanduser("~"), "Desktop", "gamebeats_crash.txt"), "w") as f:
        f.write(traceback.format_exc())
