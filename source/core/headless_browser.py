"""
headless_browser.py — Stub: no headless browser is used.

GameBeats controls Spotify exclusively through the desktop app (Spotify.exe --uri
and WM_APPCOMMAND media keys). Opening browser tabs — headless or otherwise — is
never needed and caused phantom browser processes to appear in all app states.
"""


class HeadlessBrowserController:
    """No-op stub — always reports failure so callers fall back gracefully."""

    def open_uri(self, uri: str) -> bool:
        return False

    def open_headless_url(self, url: str) -> bool:
        return False


_headless_browser = None


def get_headless_browser() -> HeadlessBrowserController:
    """Get or create the (no-op) headless browser controller."""
    global _headless_browser
    if _headless_browser is None:
        _headless_browser = HeadlessBrowserController()
    return _headless_browser
