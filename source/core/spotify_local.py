"""
spotify_local.py — control Spotify desktop via its localhost HTTP server (4370+).

Many recent Spotify builds disable this API; callers should fall back to Spotify.exe --uri.
"""

import requests

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

ORIGIN_HEADER = {
    "Origin": "https://open.spotify.com",
    "Referer": "https://open.spotify.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
LOCAL_PORTS = list(range(4370, 4376)) + [7768, 7769, 7770]


class SpotifyLocalClient:
    def __init__(self):
        self.port = None
        self._oauth = ""
        self._csrf = ""
        self._last_error = ""

    def _base(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    def _fetch_token(self) -> bool:
        urls = (
            "https://open.spotify.com/token",
            "https://open.spotify.com/get_access_token?reason=transport&product=embed",
        )
        for url in urls:
            try:
                r = requests.get(url, headers=ORIGIN_HEADER, timeout=8)
                if r.status_code != 200:
                    continue
                data = r.json() if r.text else {}
                token = data.get("t") or data.get("accessToken") or ""
                if token:
                    self._oauth = token
                    return True
            except Exception:
                continue
        return False

    def _probe_port(self, port: int) -> bool:
        for scheme in ("https", "http"):
            try:
                r = requests.get(
                    f"{scheme}://127.0.0.1:{port}/service/version.json",
                    params={"service": "remote"},
                    headers=ORIGIN_HEADER,
                    timeout=0.25,
                    verify=False,
                )
                if r.status_code == 200:
                    self.port = port
                    return True
            except Exception:
                continue
        return False

    def connect(self) -> bool:
        if self.port and self._oauth and self._csrf:
            return True

        self.port = None
        for port in LOCAL_PORTS:
            if self._probe_port(port):
                break

        if not self.port:
            self._oauth = ""
            self._csrf = ""
            self._last_error = "Spotify localhost API not running (open Spotify desktop app)."
            return False

        if not self._fetch_token():
            self._last_error = "Could not get Spotify web token."
            return False

        try:
            r = requests.get(
                f"{self._base()}/simplecsrf/token.json",
                headers=ORIGIN_HEADER,
                timeout=5,
                verify=False,
            )
            if r.status_code == 200:
                self._csrf = (r.json() or {}).get("token", "")
        except Exception as ex:
            self._last_error = str(ex)

        if not self._csrf:
            self._last_error = "Could not get Spotify CSRF token."
        return bool(self._oauth and self._csrf)

    def play(self, uri: str, context_uri: str = "") -> bool:
        if not uri or not self.connect():
            return False
        ctx = context_uri or uri
        params = {
            "oauth": self._oauth,
            "csrf": self._csrf,
            "uri": uri,
            "context": ctx,
        }
        try:
            r = requests.get(
                f"{self._base()}/remote/play.json",
                params=params,
                headers=ORIGIN_HEADER,
                timeout=12,
                verify=False,
            )
            if r.status_code == 200:
                return True
            self._last_error = f"play.json status {r.status_code}"
        except Exception as ex:
            self._last_error = str(ex)
        return False

    def pause(self, paused: bool = True) -> bool:
        if not self.connect():
            return False
        try:
            r = requests.get(
                f"{self._base()}/remote/pause.json",
                params={
                    "oauth": self._oauth,
                    "csrf": self._csrf,
                    "pause": "true" if paused else "false",
                },
                headers=ORIGIN_HEADER,
                timeout=8,
                verify=False,
            )
            return r.status_code == 200
        except Exception:
            return False

    def status(self) -> dict:
        if not self.connect():
            return {}
        try:
            r = requests.get(
                f"{self._base()}/remote/status.json",
                params={
                    "oauth": self._oauth,
                    "csrf": self._csrf,
                    "returnafter": 1,
                },
                headers=ORIGIN_HEADER,
                timeout=6,
                verify=False,
            )
            if r.status_code == 200:
                return r.json() or {}
        except Exception:
            pass
        return {}

    def is_available(self) -> bool:
        self.port = None
        self._oauth = ""
        self._csrf = ""
        return self.connect()
