import requests
import threading
import time
import json
import base64
import socket
import urllib.parse
import os
import subprocess
import sys
import random
from http.server import HTTPServer, BaseHTTPRequestHandler


def _open_url_hidden(url: str) -> None:
    """
    No-op — browser opening is disabled.
    All Spotify control goes through the desktop app; no browser is ever opened.
    """
    pass

# Spotify officially allows http:// for localhost redirect URIs (RFC 8252).
_REDIRECT_HOST = "127.0.0.1"
_REDIRECT_PATH = "/callback"

SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "playlist-read-private "
    "playlist-read-collaborative "
    "streaming"
)

_SUCCESS_HTML = b"""
<html>
<head><title>GameBeats</title></head>
<body style="background:#0a0a0a;color:#1DB954;font-family:monospace;
             display:flex;align-items:center;justify-content:center;
             height:100vh;margin:0;flex-direction:column;gap:16px;">
  <div style="font-size:48px;">&#127918;</div>
  <div style="font-size:24px;">GameBeats connected!</div>
  <div style="font-size:14px;color:#888;">You can close this tab.</div>
</body>
</html>
"""

_ERROR_HTML = b"""
<html>
<head><title>GameBeats</title></head>
<body style="background:#0a0a0a;color:#FF4455;font-family:monospace;
             display:flex;align-items:center;justify-content:center;
             height:100vh;margin:0;flex-direction:column;gap:16px;">
  <div style="font-size:48px;">&#10060;</div>
  <div style="font-size:24px;">Authorization cancelled or failed.</div>
  <div style="font-size:14px;color:#888;">Go back to GameBeats and try again.</div>
</body>
</html>
"""

_PREFERRED_PORT = 8888


def _find_free_port(preferred=_PREFERRED_PORT):
    """Prefer port 8888 (must match Spotify Dashboard redirect URI)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((_REDIRECT_HOST, preferred))
            return preferred
    except OSError:
        raise RuntimeError(
            f"Port {preferred} is in use. Close other apps using it, "
            "or free the port — Spotify redirect must be "
            f"http://127.0.0.1:{preferred}/callback"
        )


class SpotifyAuth:
    def __init__(self, client_id, client_secret):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.access_token  = None
        self.refresh_token = None
        self.token_expiry  = 0
        self._port         = None
        self._auth_code    = None
        self._auth_event   = threading.Event()

    def _redirect_uri(self):
        return f"http://{_REDIRECT_HOST}:{self._port}{_REDIRECT_PATH}"

    def get_auth_url(self):
        params = {
            "client_id":     self.client_id,
            "response_type": "code",
            "redirect_uri":  self._redirect_uri(),
            "scope":         SCOPES,
            "show_dialog":   "true",
        }
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    def start_auth_flow(self, on_complete=None):
        self._port = _find_free_port()
        auth = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != _REDIRECT_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = urllib.parse.parse_qs(parsed.query)
                code  = params.get("code",  [None])[0]

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()

                if code:
                    self.wfile.write(_SUCCESS_HTML)
                    auth._auth_code = code
                else:
                    self.wfile.write(_ERROR_HTML)

                auth._auth_event.set()

            def log_message(self, *args):
                pass

        def _run():
            try:
                server = HTTPServer((_REDIRECT_HOST, auth._port), _Handler)
                server.timeout = 120
                server.handle_request()
                server.server_close()
            except Exception:
                pass

            if auth._auth_code:
                try:
                    auth._exchange_code(auth._auth_code)
                    if on_complete:
                        on_complete(True)
                except Exception:
                    if on_complete:
                        on_complete(False)
            else:
                if on_complete:
                    on_complete(False)

        threading.Thread(target=_run, daemon=True).start()
        _open_url_hidden(self.get_auth_url())

    def _exchange_code(self, code):
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": self._redirect_uri(),
            },
            headers={"Authorization": f"Basic {creds}"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        self.access_token  = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.token_expiry  = time.time() + data["expires_in"] - 60

    def refresh(self):
        if not self.refresh_token:
            return False
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type":    "refresh_token",
                "refresh_token": self.refresh_token,
            },
            headers={"Authorization": f"Basic {creds}"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            self.access_token = data["access_token"]
            self.token_expiry = time.time() + data["expires_in"] - 60
            if "refresh_token" in data:
                self.refresh_token = data["refresh_token"]
            return True
        return False

    def get_token(self):
        if not self.access_token:
            return None
        if time.time() > self.token_expiry and self.refresh_token:
            self.refresh()
        return self.access_token

    def is_authenticated(self):
        return bool(self.get_token())

    def save(self, path="tokens.json"):
        with open(path, "w") as f:
            json.dump({
                "access_token":  self.access_token,
                "refresh_token": self.refresh_token,
                "token_expiry":  self.token_expiry,
            }, f)

    def load(self, path="tokens.json"):
        try:
            with open(path) as f:
                data = json.load(f)
            self.access_token  = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.token_expiry  = data.get("token_expiry", 0)
            return bool(self.access_token)
        except Exception:
            return False


class SpotifyController:
    BASE = "https://api.spotify.com/v1"

    def __init__(self, auth: SpotifyAuth):
        self.auth = auth
        self._last_error = ""

    def _headers(self):
        token = self.auth.get_token()
        if not token:
            return None
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _format_api_error(response) -> str:
        try:
            body = response.json()
            msg = body.get("error", {}).get("message") or body.get("message")
            if msg:
                if "premium" in msg.lower():
                    return (
                        "Spotify requires Premium on your developer account. "
                        "Add Premium to the Spotify account that owns this app "
                        "at developer.spotify.com, then reconnect."
                    )
                return msg
        except Exception:
            pass
        text = (response.text or "").strip()
        if text and len(text) < 300:
            return text
        return f"Spotify API error {response.status_code}"

    def verify_access(self):
        """Returns (ok, message). Checks that the token can call the API."""
        data, code = self._request("get", "/me")
        if code == 200 and data:
            return True, f"Connected as {data.get('display_name', 'user')}"
        return False, self._last_error or "Could not reach Spotify"

    def _request(self, method, path, retry=True, **kwargs):
        headers = self._headers()
        if not headers:
            self._last_error = "Not connected to Spotify"
            return None, 401
        url = f"{self.BASE}{path}"
        try:
            fn = getattr(requests, method)
            r = fn(url, headers=headers, timeout=12, **kwargs)
            if r.status_code == 401 and retry:
                if self.auth.refresh():
                    return self._request(method, path, retry=False, **kwargs)
                self._last_error = "Session expired — reconnect in Settings"
                return None, 401
            if r.status_code == 204:
                return None, 204
            if r.status_code == 200:
                try:
                    return r.json(), 200
                except Exception:
                    return {}, 200
            self._last_error = self._format_api_error(r)
            return None, r.status_code
        except Exception as ex:
            self._last_error = str(ex)
            return None, 0

    def _get(self, path, **kwargs):
        data, _ = self._request("get", path, **kwargs)
        return data

    def _put(self, path, **kwargs):
        data, code = self._request("put", path, **kwargs)
        return code in (200, 204)

    def _post(self, path, **kwargs):
        data, code = self._request("post", path, **kwargs)
        return code in (200, 204)

    def launch_spotify(self):
        """Start the Spotify desktop client if it is not running."""
        if sys.platform != "win32":
            try:
                subprocess.Popen(["spotify"], shell=False)
            except Exception:
                pass
            return
        candidates = [
            os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""),
                "Microsoft", "WindowsApps", "Spotify.exe",
            ),
        ]
        for exe in candidates:
            if exe and os.path.isfile(exe):
                try:
                    subprocess.Popen(
                        [exe], shell=False,
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except Exception:
                    pass

    def ensure_active_device(self, wait_seconds=25):
        """Return an active device id, launching Spotify if needed."""
        for _ in range(wait_seconds):
            devices = self.get_devices()
            if devices:
                active = next((d for d in devices if d.get("is_active")), None)
                dev = active or devices[0]
                if not dev.get("is_active"):
                    self.transfer_playback(dev["id"])
                    time.sleep(0.5)
                return dev["id"]
            time.sleep(1)

        self.launch_spotify()
        for _ in range(wait_seconds):
            time.sleep(1)
            devices = self.get_devices()
            if devices:
                dev = devices[0]
                self.transfer_playback(dev["id"])
                time.sleep(0.5)
                return dev["id"]
        return None

    def get_current_track(self):
        data = self._get("/me/player/currently-playing")
        if data and data.get("item"):
            item = data["item"]
            context = data.get("context") or {}
            context_uri = context.get("uri", "")
            return {
                "name":        item["name"],
                "artist":      ", ".join(a["name"] for a in item["artists"]),
                "album_art":   item["album"]["images"][0]["url"] if item["album"]["images"] else None,
                "is_playing":  data.get("is_playing", False),
                "progress_ms": data.get("progress_ms", 0),
                "duration_ms": item["duration_ms"],
                "uri":         item["uri"],
                "context_uri": context_uri,
                "playlist_uri": context_uri if context.get("type") == "playlist" else "",
            }
        return None

    def get_playback_state(self):
        return self._get("/me/player")

    def play(self, context_uri=None, uris=None):
        if not self.ensure_active_device():
            return False
        body = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        return self._put("/me/player/play", json=body if body else None)

    def pause(self):
        return self._put("/me/player/pause")

    def ensure_paused(self, paused_by_game=False):
        return self.pause()

    def ensure_playing(self):
        return self.play()

    def next_track(self):
        return self._post("/me/player/next")

    def prev_track(self):
        return self._post("/me/player/previous")

    def set_volume(self, percent):
        return self._put(f"/me/player/volume?volume_percent={int(percent)}")

    def set_repeat_mode(self, state="context"):
        if state not in ("track", "context", "off"):
            state = "context"
        return self._put(f"/me/player/repeat?state={state}")

    def get_volume(self):
        state = self.get_playback_state()
        if state and state.get("device"):
            return state["device"].get("volume_percent", 50)
        return 50

    def search_and_play(
        self,
        query,
        type_="playlist",
        max_results=5,
        blocked_uris=None,
        exclude_uris=None,
    ):
        if not self.ensure_active_device():
            return None
        try:
            max_results = max(1, min(20, int(max_results)))
        except (TypeError, ValueError):
            max_results = 5
        data = self._get("/search", params={"q": query, "type": type_, "limit": max_results})
        if data:
            items = data.get(f"{type_}s", {}).get("items", [])
            items = [i for i in items if i]
            blocked = set(blocked_uris or [])
            blocked.update(exclude_uris or [])
            if blocked:
                items = [i for i in items if i.get("uri") not in blocked]
            if items:
                pool = items[:max_results]
                item = random.choice(pool)
                uri = item["uri"]
                if self.play(context_uri=uri):
                    item = dict(item)
                    item["query"] = query
                    item["pick_rank"] = pool.index(next(i for i in pool if i["uri"] == uri)) + 1
                    item["top_count"] = len(pool)
                    item["pool"] = [{"uri": i.get("uri"), "name": i.get("name", "")} for i in pool]
                    return item
        return None

    def get_user_playlists(self):
        """Returns (playlists, error_message). error_message is '' on success."""
        playlists = []
        offset = 0
        while True:
            data, code = self._request(
                "get", "/me/playlists",
                params={"limit": 50, "offset": offset},
            )
            if code != 200 or not data:
                if playlists:
                    return playlists, ""
                return [], self._last_error or "Could not load playlists"
            items = data.get("items", [])
            for p in items:
                if p:
                    playlists.append({
                        "name":   p["name"],
                        "uri":    p["uri"],
                        "id":     p["id"],
                        "tracks": p["tracks"]["total"],
                    })
            if not data.get("next"):
                break
            offset += 50
            if offset >= 200:
                break
        return playlists, ""

    def play_playlist(self, uri):
        return self.play(context_uri=uri)

    def get_devices(self):
        data = self._get("/me/player/devices")
        return data.get("devices", []) if data else []

    def transfer_playback(self, device_id):
        return self._put("/me/player", json={"device_ids": [device_id], "play": False})
