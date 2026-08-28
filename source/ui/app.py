import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("dark-blue")
import threading
import time
import json
import os
import sys
import urllib.request
from io import BytesIO
import subprocess

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Windows-specific imports
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    try:
        import winreg
        HAS_WINREG = True
    except ImportError:
        HAS_WINREG = False
else:
    HAS_WINREG = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.detector import GameDetector, MOOD_TO_PLAYLIST, get_pid_for_proc
from core.spotify import SpotifyAuth, SpotifyController
from core.spotify_web import SpotifyWebController
from core.audio_monitor import (
    GameMusicDetector,
    HAS_PROCESS_LOOPBACK,
    HAS_PYAUDIO_WP,
    _clear_spotify_mixer_mute,
)
from ui.onboarding import OnboardingOverlay
from ui.games_page import GamesPage, get_game_square_icon_image, _generate_gradient_fallback
from ui.mascot_notifier import MascotNotifier, PuppySingingOverlay
from ui.runtime_overlay import RuntimeOverlay
from ui import theme as T

def _data_dir() -> str:
    """
    Return a writable directory for config/tokens.
    - Frozen (PyInstaller): use per-user AppData so installers can live in Program Files.
    - Dev: use the repo root
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "GameBeats")
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR    = _data_dir()
os.makedirs(BASE_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TOKENS_FILE = os.path.join(BASE_DIR, "tokens.json")
LOG_FILE    = os.path.join(BASE_DIR, "gamebeats.log")

def _repo_root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _puppy_logo_path() -> str:
    root = _repo_root_dir()
    candidates = [
        os.path.join(root, "puppies", "puppy logo.png"),
        os.path.join(root, "assets", "puppy", "puppy logo.png"),
        os.path.join(root, "assets", "puppy", "puppy_logo.png"),
        os.path.join(os.getcwd(), "puppies", "puppy logo.png"),
    ]
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        bundle_dir = getattr(sys, "_MEIPASS", "")
        candidates.extend([
            os.path.join(bundle_dir, "puppies", "puppy logo.png"),
            os.path.join(bundle_dir, "assets", "puppy", "puppy logo.png"),
            os.path.join(bundle_dir, "assets", "puppy", "puppy_logo.png"),
            os.path.join(exe_dir, "puppies", "puppy logo.png"),
            os.path.join(exe_dir, "assets", "puppy", "puppy logo.png"),
            os.path.join(exe_dir, "assets", "puppy", "puppy_logo.png"),
        ])
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def _load_puppy_logo_photo(max_size):
    if not HAS_PIL:
        return None
    path = _puppy_logo_path()
    if not path:
        return None
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail(max_size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

# ── DPI awareness (Windows) — must be set before any Tk window is created ───
def _load_puppy_window_icon(max_size=(64, 64)):
    path = _puppy_logo_path()
    if not path:
        return None
    try:
        if HAS_PIL:
            img = Image.open(path).convert("RGBA")
            img.thumbnail(max_size, Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        return tk.PhotoImage(file=path)
    except Exception:
        return None


# ── Palette (from theme.py) ──────────────────────────────────────────────────
BG         = T.BG
SIDEBAR    = T.SIDEBAR
SURFACE    = T.SURFACE
SURFACE2   = T.SURFACE2
SURFACE3   = T.SURFACE3
SURFACE4   = T.SURFACE4
ACCENT     = T.ACCENT
ACCENT2    = T.ACCENT2
ACCENT_DIM = T.ACCENT_DIM
ACCENT_BG  = T.ACCENT_BG
TEXT       = T.TEXT
TEXT_SEC   = T.TEXT_SEC
TEXT_MUTED = T.TEXT_MUTED
BORDER     = T.BORDER
BORDER2    = T.BORDER2
RED        = T.RED
AMBER      = T.AMBER
GREEN      = T.GREEN
PURPLE     = T.PURPLE
BLUE       = T.BLUE
SIDEBAR_W  = T.SIDEBAR_W
NAV_H      = T.NAV_H
WIN_W      = T.WIN_W
WIN_H      = T.WIN_H
RADIUS_LG  = T.RADIUS_LG
RADIUS_MD  = T.RADIUS_MD
RADIUS_SM  = T.RADIUS_SM

DEFAULT_PADX = T.DEFAULT_PADX
DEFAULT_PADY = T.DEFAULT_PADY
PLAYLIST_END_NORMAL_EXTRA_SEC = 4.0
PLAYLIST_END_RETRY_EXTRA_SEC = 10.0
SPOTIFY_UI_AUDIO_ON_THRESHOLD = 0.0001
SPOTIFY_UI_AUDIO_OFF_THRESHOLD = 0.0

F_FALLBACK = T.F_FALLBACK
F_TITLE    = T.F_TITLE
F_LABEL    = T.F_LABEL
F_SMALL    = T.F_SMALL
F_MICRO    = T.F_MICRO
F_MONO     = T.F_MONO
F_UI       = T.F_UI


# ── Reusable widgets ──────────────────────────────────────────────────────────

def pack_padded(widget, **kwargs):
    """Helper pour pack avec du padding par défaut pour uniformiser l'UI."""
    if 'padx' not in kwargs: kwargs['padx'] = DEFAULT_PADX
    if 'pady' not in kwargs: kwargs['pady'] = DEFAULT_PADY
    widget.pack(**kwargs)


def pill_label(parent, text, bg=None, fg=ACCENT, font_size=9):
    bg = bg or SURFACE3
    f = ctk.CTkFrame(parent, fg_color=bg, corner_radius=12)
    ctk.CTkLabel(f, text=text, fg_color="transparent", text_color=fg,
                 font=ctk.CTkFont(family=F_UI, size=font_size, weight="bold")).pack(padx=10, pady=3)
    return f


def _make_entry(parent, textvariable=None, show="", font_size=10, mono=False, **kwargs):
    border_wrap = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    ff = "Consolas" if mono else F_UI
    e = ctk.CTkEntry(
        border_wrap,
        textvariable=textvariable,
        show=show,
        fg_color=SURFACE3,
        text_color=TEXT,
        border_color=BORDER2,
        focused_border_color=ACCENT,
        insert_color=ACCENT,
        font=ctk.CTkFont(family=ff, size=font_size),
        corner_radius=8,
        height=38,
        **kwargs
    )
    e.pack(fill=tk.X)
    return border_wrap, e


class RoundedButton(ctk.CTkButton):
    def __init__(self, parent, text="", command=None, width=160, height=48,
                 bg=ACCENT, fg="#ffffff", radius=RADIUS_MD, font_size=11, canvas_bg=BG,
                 border_color="", **kwargs):
        import tkinter.font as tkfont
        try:
            f = tkfont.Font(font=(F_UI, font_size, "bold"))
            text_w = f.measure(text)
            width = max(width, text_w + 60)
        except Exception:
            pass

        super().__init__(parent, text=text, command=command, width=width, height=height,
                         fg_color=bg, text_color=fg, corner_radius=radius,
                         font=ctk.CTkFont(family=F_UI, size=font_size, weight="bold"),
                         border_color=border_color, border_width=1 if border_color else 0,
                         hover_color=T.ACCENT_HOV if bg == ACCENT else SURFACE4,
                         **kwargs)

    def update_text(self, text):
        self.configure(text=text)

    def set_bg(self, bg):
        self.configure(fg_color=bg)


class CircleBtn(ctk.CTkButton):
    def __init__(self, parent, text="", command=None, size=60,
                 bg=SURFACE3, fg=TEXT, font_size=16, canvas_bg=SURFACE,
                 accent=False, **kwargs):
        super().__init__(
            parent, text=text, command=command,
            width=size, height=size, corner_radius=size // 2,
            fg_color=bg, text_color=fg,
            font=ctk.CTkFont(family=F_UI, size=font_size, weight="bold"),
            border_width=0,
            hover_color=T.ACCENT_HOV if accent else SURFACE4,
            **kwargs,
        )
        self.size = size
        self.accent = accent

    def update_text(self, t):
        self.configure(text=t)

    def set_active(self, active: bool):
        if active:
            bg_n = ACCENT if self.accent else SURFACE3
            fg_n = "#ffffff" if self.accent else ACCENT
        else:
            bg_n = SURFACE3
            fg_n = TEXT
        self.configure(fg_color=bg_n, text_color=fg_n)


# ── Splash screen ────────────────────────────────────────────────────────────

class SplashScreen:
    def __init__(self, root):
        self.root = root
        self.win = ctk.CTkToplevel(root)
        self.win.overrideredirect(True)
        w, h = 360, 240
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.win.configure(fg_color=SURFACE)
        self.win.attributes("-topmost", True)
        
        if IS_WINDOWS:
            self.win.attributes("-alpha", 0.0)
            self._fade_in(0.0)

        # Accent top bar
        ctk.CTkFrame(self.win, fg_color=ACCENT, height=4, corner_radius=0).pack(fill=tk.X)

        # Logo area
        logo_frame = ctk.CTkFrame(self.win, fg_color="transparent", corner_radius=0)
        logo_frame.pack(pady=(36, 12))
        self._logo_photo = _load_puppy_logo_photo((156, 104))
        if self._logo_photo:
            tk.Label(
                logo_frame,
                image=self._logo_photo,
                bg=SURFACE,
                bd=0,
                highlightthickness=0,
            ).pack()
        else:
            lc = tk.Canvas(logo_frame, width=52, height=52, bg=SURFACE, highlightthickness=0)
            lc.pack()
            lc.create_oval(4, 4, 48, 48, fill=ACCENT_DIM, outline=ACCENT, width=1)
            lc.create_text(26, 26, text="\u266a", fill=ACCENT2, font=(F_UI, 20, "bold"))

        ctk.CTkLabel(self.win, text="GameBeats", fg_color="transparent", text_color=TEXT,
                     font=ctk.CTkFont(family=F_UI, size=22, weight="bold")).pack()
        ctk.CTkLabel(self.win, text="Starting up\u2026", fg_color="transparent", text_color=TEXT_MUTED,
                     font=ctk.CTkFont(family=F_UI, size=11)).pack(pady=(8, 24))

        # Progress bar
        self.progress = ctk.CTkProgressBar(self.win, width=260, height=5,
                                           fg_color=BORDER, progress_color=ACCENT,
                                           corner_radius=3)
        self.progress.pack(fill=tk.X, padx=44)
        self.progress.set(0.0)
        self._animate(0.0)

    def _fade_in(self, alpha):
        if alpha < 0.95 and self.win.winfo_exists():
            alpha += 0.08
            self.win.attributes("-alpha", alpha)
            self.win.after(15, self._fade_in, alpha)

    def _animate(self, progress_val):
        if progress_val > 1.0:
            return
        if self.win.winfo_exists():
            self.progress.set(progress_val)
            self.win.after(50, self._animate, progress_val + 0.03)

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass


# ── Main App ─────────────────────────────────────────────────────────────────

class GlowBackground(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, highlightthickness=0, **kwargs)
        self.blobs = []
        self.bind("<Configure>", self._on_resize)

    def _hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _on_resize(self, event):
        self._draw_gradient()

    def _draw_gradient(self):
        self.delete("bg_gradient")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        self.configure(scrollregion=(0, 0, w, h))
        self.xview_moveto(0)
        self.yview_moveto(0)
        c1 = (238, 240, 247)  # #eef0f7
        c2 = (248, 249, 252)  # #f8f9fc
        for y in range(0, h, 4):
            f = y / h
            r = int(c1[0] + (c2[0] - c1[0]) * f)
            g = int(c1[1] + (c2[1] - c1[1]) * f)
            b = int(c1[2] + (c2[2] - c1[2]) * f)
            self.create_rectangle(0, y, w, y+4, fill=f"#{r:02x}{g:02x}{b:02x}", outline="", tags="bg_gradient")
        self.tag_lower("bg_gradient")

    def _redraw_blobs(self):
        self.delete("blob")

    def _animate(self):
        return


class GameBeatsApp:
    def __init__(self):
        self.root = ctk.CTk()
        T.apply_ctk_scaling(self.root)

        # Thread-safe GUI queue
        import queue
        self._gui_queue = queue.Queue()
        original_after = self.root.after

        def safe_after(delay_ms, callback=None, *args):
            import threading
            if threading.current_thread() is threading.main_thread():
                return original_after(delay_ms, callback, *args)
            else:
                if callback is not None:
                    self._gui_queue.put(lambda: original_after(delay_ms, callback, *args))
                return None

        self.root.after = safe_after

        def check_gui_queue():
            try:
                while True:
                    task = self._gui_queue.get_nowait()
                    try:
                        task()
                    except Exception as e:
                        try:
                            self._log(f"Error in background GUI task: {e}")
                        except Exception:
                            pass
                    self._gui_queue.task_done()
            except queue.Empty:
                pass
            original_after(50, check_gui_queue)

        original_after(50, check_gui_queue)

        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.title("GameBeats")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        init_w = min(WIN_W, max(960, int(sw * 0.75)))
        init_h = min(WIN_H, max(700, int(sh * 0.80)))
        
        # Center window on screen for overrideredirect
        px = max(0, (sw - init_w) // 2)
        py = max(0, (sh - init_h) // 2)
        self.root.geometry(f"{init_w}x{init_h}+{px}+{py}")
        self.root.minsize(960, 700)
        self.root.resizable(True, True)
        
        self.root.configure(fg_color=BG)
        self._window_icon_photo = _load_puppy_window_icon()
        if self._window_icon_photo:
            try:
                # Set icon and schedule to stick on Windows/CustomTkinter window mappings
                self.root.iconphoto(True, self._window_icon_photo)
                self.root.after(200, lambda: self.root.iconphoto(True, self._window_icon_photo))
            except Exception:
                pass
        elif IS_WINDOWS:
            self.root.iconbitmap(default="")

                # Pulse control variables
        self._pulse_job = None
        self._pulse_active = False

        self._load_config()
        self.auth = None
        self.spotify = None
        self._closing = False
        self._spotify_login_prompt = None
        self._spotify_login_status_lbl = None
        self.detector = None
        self.current_game = None
        self._game_pid = None
        self._audio_monitor_running = False
        self._spotify_started_by_us = False
        self._play_in_progress = False
        self._game_audio = None
        self.auto_mode   = tk.BooleanVar(value=True)
        self.seamless_music_var = tk.BooleanVar(
            value=bool(self.configure.get("seamless_music", False))
        )
        self.startup_var = tk.BooleanVar(value=False)
        self.desktop_mode_var = tk.BooleanVar(
            value=self.configure.get("playback_mode", "desktop") == "desktop")
        self.cid_var = tk.StringVar(value=self.configure.get("client_id", ""))
        self.csec_var = tk.StringVar(value=self.configure.get("client_secret", ""))
        # auth_lbl is used for status updates during Spotify connection
        self.auth_lbl = ctk.CTkLabel(self.root, text="", fg_color="transparent", text_color=TEXT)
        self.volume_var  = tk.IntVar(value=50)
        self._track_job  = None
        self._album_photo = None
        self._game_icon_ctk = None
        self._is_playing  = False
        self._user_toggle_ts = 0.0  # timestamp of last user play/pause click
        self._play_pause_busy = False
        self._manual_paused = False
        self._current_page = "main"
        self._current_playlist_uri = ""
        self._current_playlist_name = ""
        self._current_playlist_query = ""
        self._playlist_end_pending = False
        self._mascot_notifier = None          # MascotNotifier shown at playlist end
        self._puppy_singing_overlay = None    # Small puppy animation while Spotify audio is active
        self._music_missing_since = 0.0
        self._last_music_seen_ts = 0.0
        self._last_game_loud_ts = 0.0
        self._last_spotify_loud_ts = 0.0  # Track when Spotify was last loud
        self._spotify_audio_active = False
        self._last_spotify_peak = 0.0
        self._audio_monitor_started_ts = 0.0
        self._playlist_end_prompt_not_before = 0.0
        self._playlist_end_extra_silence_sec = PLAYLIST_END_NORMAL_EXTRA_SEC
        self._playlist_end_extra_until_audio = False
        self._spotify_reset_done = False
        self._play_effect_phase = 0
        # Playlist-ended detection: both Spotify AND game silent much longer than resume delay
        self._gamebeats_hwnd = 0 # Will store the main window's HWND
        self._spotify_silence_since = 0.0  # when we first noticed Spotify silence
        self._tried_playlist_uris = []  # Track playlists we've tried in this session
        self._playlist_ended_closing = False  # True while closing/relaunching for next playlist
        self._paused_by_game_flag = False  # Local flag: True when GameBeats paused Spotify
        self._user_paused_flag = False  # True when user manually pauses via player tab
        # ┌─ PAUSE STACK STATE MANAGEMENT ─────────────────────────────────┐
        # │ Stack entries: [("auto" | "user", timestamp), ...]             │
        # │                                                                  │
        # │ AUTO pauses (game is loud):                                     │
        # │   - Added: when game audio loudness triggers auto-pause         │
        # │   - Removed: when game audio quiets down (auto-resume)          │
        # │                                                                  │
        # │ USER pauses (click pause on overlay):                           │
        # │   - Added: when user clicks pause button                        │
        # │   - Removed: when user clicks play button                       │
        # │                                                                  │
        # │ Overlay behavior:                                               │
        # │   - Shows: only when pause_stack is EMPTY                       │
        # │   - Suppressed: when ANY pause entry exists in stack            │
        # │                                                                  │
        # │ Stack cleared: when Spotify sound is detected playing           │
        # └──────────────────────────────────────────────────────────────────┘
        self._pause_stack = []

        self.playlist_limit_var = tk.IntVar(value=self._playlist_pick_count())
        self.end_behavior_var = tk.StringVar(value=self._end_behavior_label())
        self.resume_delay_var = tk.IntVar(value=self._resume_delay_seconds())

        splash = SplashScreen(self.root)
        self.root.after(1800, lambda: (splash.close(), self.root.deiconify(), self._post_splash()))

        # Get the main window's HWND after it's been created and deiconified
        if IS_WINDOWS:
            self.root.after(2000, lambda: self._set_gamebeats_hwnd())

        # Initialize control overlay (manual play/pause/prev/next)
        self._control_overlay = RuntimeOverlay(
            self.root,
            on_play=self._overlay_play,
            on_pause=self._overlay_pause,
            on_prev=self._overlay_prev,
            on_next=self._overlay_next,
            on_block=self._overlay_block,
            on_try_another=self._overlay_try_another
        )
        self._puppy_singing_overlay = PuppySingingOverlay(self.root)

        self._build_ui()
        # Make layout responsive to window resizes
        self.root.bind("<Configure>", lambda e: self._on_root_resize())

    def _post_splash(self):
        if HAS_WINREG:
            self.startup_var.set(self._check_startup())
        # Free mode: Spotify Web Player in browser (no Web API) unless user chose API
        mode = self.configure.get("playback_mode", "desktop")
        if mode in ("desktop", "web", ""):
            self.configure["playback_mode"] = "web"
            self._start_web_mode()
        elif mode == "api":
            if not self.configure.get("setup_done"):
                self._show_onboarding()
            else:
                self._try_auto_login()
        else:
            self.configure["playback_mode"] = "web"
            self._start_web_mode()

    def _is_web_mode(self):
        return isinstance(self.spotify, SpotifyWebController)

    def _is_desktop_mode(self):
        """Free playback via Spotify Web Player (kept name for existing call sites)."""
        return self._is_web_mode()

    def _start_web_mode(self):
        self.configure["playback_mode"] = "web"
        self.configure["setup_done"] = True
        self._save_config()
        play_xpath = self.configure.get("spotify_web_play_xpath", "")
        headless = bool(self.configure.get("spotify_web_headless", False))
        show_browser = self.configure.get("spotify_web_show_browser", False)
        self.configure["spotify_web_show_browser"] = bool(show_browser)
        self._save_config()
        cdp_url = self.configure.get("spotify_web_cdp_url", "")
        self.spotify = SpotifyWebController(
            BASE_DIR,
            logger=self._log,
            gamebeats_hwnd=self._gamebeats_hwnd,
            headless=headless,
            play_xpath=play_xpath or None,
            hide_window=not bool(show_browser),
            cdp_url=cdp_url or None,
        )
        if cdp_url:
            self._log("CDP mode: will attach to your own Chrome (most normal for Spotify).")
        if hasattr(self, "desktop_mode_var"):
            self.desktop_mode_var.set(True)

        self._spotify_reset_done = True
        self._log(
            "Web player mode — Spotify desktop + one automated Chrome (no extra Player Chrome). "
            "Log in once in spotify_web_profile."
        )
        if self._spotify_web_login_ready():
            self.root.after(0, self._on_spotify_ready)
            # Background verify: even though local cookies exist, the session
            # may have expired.  Fire a hidden browser check and show the
            # login prompt if the login button is found.
            threading.Thread(
                target=self._verify_spotify_login_background,
                daemon=True,
            ).start()
        else:
            self.root.after(0, self._show_spotify_browser_login_prompt)

    def _verify_spotify_login_background(self):
        """Background thread: open a hidden browser to Spotify and check
        whether the login button XPath is present. If it is, the session
        has expired and we need the user to log in again."""
        try:
            if not self.spotify or not hasattr(self.spotify, 'check_login_silently'):
                return
            logged_in = self.spotify.check_login_silently()
            if not logged_in:
                # Session expired — clear the cached flag and show login prompt
                self.configure["spotify_web_login_done"] = False
                self._save_config()
                self.root.after(0, lambda: (
                    self._log("⚠ Spotify session expired — please log in again."),
                    self._show_spotify_browser_login_prompt(),
                ))
        except Exception as ex:
            # Don't disrupt the app on background check failures
            self.root.after(0, lambda e=ex: self._log(
                f"Background login check skipped: {e}"))

    def _start_desktop_mode(self):
        """Legacy entry point — routes to web player mode."""
        self._start_web_mode()

    def _spotify_web_profile_has_saved_state(self) -> bool:
        profile = os.path.join(BASE_DIR, "spotify_web_profile")
        candidates = [
            os.path.join(profile, "Default", "Network", "Cookies"),
            os.path.join(profile, "Default", "Cookies"),
            os.path.join(profile, "Default", "Local Storage", "leveldb"),
            os.path.join(profile, "Default", "IndexedDB"),
        ]
        for path in candidates:
            try:
                if os.path.isfile(path) and os.path.getsize(path) > 2048:
                    return True
                if os.path.isdir(path):
                    for name in os.listdir(path):
                        full = os.path.join(path, name)
                        if os.path.isfile(full) and os.path.getsize(full) > 2048:
                            return True
            except Exception:
                pass
        return False

    def _spotify_web_login_ready(self) -> bool:
        return bool(self.configure.get("spotify_web_login_done")) or self._spotify_web_profile_has_saved_state()

    def _show_spotify_browser_login_prompt(self):
        if self._spotify_login_prompt is not None:
            try:
                self._spotify_login_prompt.lift()
                return
            except Exception:
                self._spotify_login_prompt = None

        win = ctk.CTkToplevel(self.root)
        self._spotify_login_prompt = win
        win.title("Spotify Login")
        win.configure(fg_color=BG)
        win.resizable(True, True)
        win.minsize(450, 350)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        try:
            w, h = 580, 420
            try:
                scale = win.tk.call('tk', 'scaling')
                if scale > 1.35:
                    mult = scale / 1.333333
                    w = int(w * mult)
                    h = int(h * mult)
            except Exception:
                pass
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - h) // 2)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        # Apply app icon to the login popup window
        try:
            if hasattr(self, '_window_icon_photo') and self._window_icon_photo:
                win.iconphoto(False, self._window_icon_photo)
        except Exception:
            pass

        card = ctk.CTkFrame(win, fg_color=SURFACE, corner_radius=12)
        card.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        # Header row: logo + title
        header_row = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        header_row.pack(anchor="w", fill=tk.X, padx=16, pady=(16, 4))
        try:
            if hasattr(self, '_window_icon_photo') and self._window_icon_photo:
                logo_lbl = ctk.CTkLabel(
                    header_row, image=self._window_icon_photo, text="",
                    fg_color="transparent", width=28, height=28
                )
                logo_lbl.pack(side=tk.LEFT, padx=(0, 8))
        except Exception:
            pass
        ctk.CTkLabel(
            header_row, text="Login to Spotify", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=18, weight="bold")
        ).pack(side=tk.LEFT)

        # Use a safe hardcoded wraplength so text wraps on first paint.
        # A deferred call also recalculates it once the window is actually rendered.
        _WRAP = 460

        lbl_info = ctk.CTkLabel(
            card,
            text=(
                "GameBeats needs you to log in once in the browser window it opens.\n"
                "Use the same Spotify account that is active on your Spotify desktop app.\n"
                "Your login is saved on this PC — you won't need to do this again."
            ),
            fg_color="transparent", text_color=TEXT_SEC, font=ctk.CTkFont(family=F_UI, size=11),
            justify=tk.LEFT, wraplength=_WRAP, anchor="w",
        )
        lbl_info.pack(anchor="w", fill=tk.X, padx=16, pady=(0, 14))

        lbl_warn = ctk.CTkLabel(
            card,
            text=(
                "⚠  If you use Google or another provider to log in to Spotify, choose that option here.\n"
                "Avoid typing your email/password directly unless that's how your account normally signs in."
            ),
            fg_color="transparent", text_color=AMBER, font=ctk.CTkFont(family=F_UI, size=11),
            justify=tk.LEFT, wraplength=_WRAP, anchor="w",
        )
        lbl_warn.pack(anchor="w", fill=tk.X, padx=16, pady=(0, 10))

        self._spotify_login_status_lbl = ctk.CTkLabel(
            card,
            text="Open the login window, sign in to Spotify, then come back here.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=11),
            justify=tk.LEFT, wraplength=_WRAP,
        )
        self._spotify_login_status_lbl.pack(anchor="w", fill=tk.X, padx=16, pady=(0, 14))

        def _apply_wrap(wrap):
            """Apply wraplength to all text labels in the dialog."""
            try:
                lbl_info.configure(wraplength=wrap)
                lbl_warn.configure(wraplength=wrap)
                if self._spotify_login_status_lbl:
                    self._spotify_login_status_lbl.configure(wraplength=wrap)
            except Exception:
                pass

        def _on_card_resize(e):
            _apply_wrap(max(200, e.width - 60))

        card.bind("<Configure>", _on_card_resize)

        # Re-apply wraplength after window is fully drawn so it's pixel-accurate
        def _deferred_wrap():
            try:
                cw = card.winfo_width()
                if cw > 100:
                    _apply_wrap(max(200, cw - 60))
            except Exception:
                pass
        win.after(50, _deferred_wrap)
        win.after(250, _deferred_wrap)

        row = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        row.pack(fill=tk.X, padx=16, pady=(4, 0))

        def _set_status(text, color=TEXT_MUTED):
            if self._spotify_login_status_lbl:
                self._spotify_login_status_lbl.configure(text=text, text_color=color)

        def _open_login():
            _set_status("Opening Spotify login...", ACCENT)

            def _go():
                ok = bool(self.spotify and self.spotify.open_login_window())
                self.root.after(
                    0,
                    lambda: _set_status(
                        "Sign in in the browser, then click I am logged in.",
                        TEXT_MUTED,
                    ) if ok else _set_status("Could not open Spotify login.", RED),
                )

            threading.Thread(target=_go, daemon=True).start()

        def _verify_login():
            _set_status("Checking Spotify login...", ACCENT)

            def _complete():
                try:
                    win.destroy()
                except Exception:
                    pass
                self._spotify_login_prompt = None
                self._spotify_login_status_lbl = None
                self._log("Music ready.")
                self._on_spotify_ready()

            def _go():
                ok = bool(self.spotify and self.spotify.browser_login_ready())
                if ok:
                    try:
                        self.configure["spotify_web_login_done"] = True
                        self.configure["spotify_web_show_browser"] = False
                        self.configure["setup_done"] = True
                        self._save_config()
                    except Exception:
                        pass
                    try:
                        if hasattr(self.spotify, "prepare_browser_background"):
                            self.spotify.prepare_browser_background()
                        else:
                            self.spotify.close_browser()
                    except Exception:
                        pass
                    self.root.after(0, _complete)
                else:
                    self.root.after(
                        0,
                        lambda: _set_status(
                            "Spotify still needs login. Finish signing in, then try again.",
                            AMBER,
                        ),
                    )

            threading.Thread(target=_go, daemon=True).start()

        ctk.CTkButton(
            row, text="Open Spotify Login", command=_open_login,
            fg_color=ACCENT, hover_color=ACCENT2, text_color="#000",
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"),
            corner_radius=8
        ).pack(side=tk.LEFT)
        
        ctk.CTkButton(
            row, text="I am logged in", command=_verify_login,
            fg_color=SURFACE3, hover_color=SURFACE4, text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"),
            corner_radius=8
        ).pack(side=tk.LEFT, padx=(12, 0))
        
        ctk.CTkButton(
            row, text="Exit", command=self._on_close,
            fg_color="transparent", hover_color=SURFACE2, text_color=TEXT_MUTED,
            font=ctk.CTkFont(family=F_UI, size=10),
            corner_radius=8
        ).pack(side=tk.RIGHT)

        try:
            win.parent = self.root
            win.lift()
            win.focus_force()
        except Exception:
            pass

    def _show_onboarding(self):
        OnboardingOverlay(
            self.root,
            SpotifyAuth=SpotifyAuth,
            SpotifyController=SpotifyController,
            on_complete=self._on_onboarding_complete,
            tokens_file=TOKENS_FILE,
            config_file=CONFIG_FILE,
        )

    def _on_onboarding_complete(self, auth, spotify):
        """Called when the user finishes (or skips) onboarding."""
        if auth and spotify:
            self.auth    = auth
            self.spotify = spotify
            self._reload_config()
            self.cid_var.set(self.configure.get("client_id", ""))
            self.csec_var.set(self.configure.get("client_secret", ""))
            self.auth_lbl.configure(text="✓ Connected to Spotify", text_color="#1DB954")
            self._log("Spotify connected via setup wizard ✓")
            self._on_spotify_ready()
        else:
            self._log("Using free web player mode (no Spotify API needed).")
            self._start_desktop_mode()

    def _mainwindow_hwnd(self):
        """HWND of the top-level window (needed for frameless minimize/taskbar)."""
        if not IS_WINDOWS:
            return None
        try:
            import ctypes
            wid = self.root.winfo_id()
            hwnd = ctypes.windll.user32.GetParent(wid)
            return hwnd or wid
        except Exception:
            return None

    def _minimize_window(self):
        """Minimize frameless window — iconify() does not work with overrideredirect."""
        if IS_WINDOWS:
            try:
                import ctypes
                hwnd = self._mainwindow_hwnd()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                    return
            except Exception:
                pass
        try:
            self.root.iconify()
        except Exception:
            pass

    def _set_gamebeats_hwnd(self):
        if IS_WINDOWS:
            try:
                import ctypes
                self._gamebeats_hwnd = self.root.winfo_id()
                hwnd = self._mainwindow_hwnd() or self._gamebeats_hwnd
                
                # Style modification:
                # GWL_EXSTYLE = -20
                # WS_EX_APPWINDOW = 0x00040000
                # WS_EX_TOOLWINDOW = 0x00000080 (remove this style so it shows in taskbar)
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                style = (style | 0x00040000) & ~0x00000080
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
                
                # Force update styles
                # SWP_NOMOVE = 2, SWP_NOSIZE = 1, SWP_NOZORDER = 4, SWP_FRAMECHANGED = 0x0020
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
                
                # Re-map the window so Windows taskbar notices the status change
                self.root.withdraw()
                self.root.deiconify()
                
                self._log(f"GameBeats main window HWND: {self._gamebeats_hwnd:#x} (Forced taskbar style)")
            except Exception as e:
                self._log(f"Failed to force taskbar style via ctypes: {e}")

    def _reload_config(self):
        try:
            with open(CONFIG_FILE) as f:
                self.configure = json.load(f)
        except:
            pass

    def _load_config(self):
        self.configure = {}
        try:
            with open(CONFIG_FILE) as f:
                self.configure = json.load(f)
        except: pass

    def _save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.configure, f, indent=2)

    def _playlist_pick_count(self) -> int:
        try:
            count = int(self.configure.get("playlist_pick_count", 5))
        except (TypeError, ValueError):
            count = 5
        return max(1, min(20, count))

    def _end_behavior_key(self) -> str:
        value = self.configure.get("playlist_end_behavior", "next_pool")
        return value if value in ("next_pool", "loop_current") else "next_pool"

    def _end_behavior_label(self) -> str:
        return {
            "next_pool": "Pick another playlist",
            "loop_current": "Loop current playlist",
        }.get(self._end_behavior_key(), "Pick another playlist")

    def _save_auto_playlist_settings(self, *_):
        try:
            count = int(self.playlist_limit_var.get())
        except (TypeError, ValueError, tk.TclError):
            count = 5
        count = max(1, min(20, count))
        self.playlist_limit_var.set(count)
        label = self.end_behavior_var.get()
        behavior = "loop_current" if label == "Loop current playlist" else "next_pool"
        self.configure["playlist_pick_count"] = count
        self.configure["playlist_end_behavior"] = behavior
        self._save_config()
        if self.spotify and hasattr(self.spotify, "set_repeat_mode"):
            repeat = "context" if behavior == "loop_current" else "off"
            threading.Thread(
                target=lambda: self.spotify.set_repeat_mode(repeat),
                daemon=True,
            ).start()

    def _resume_delay_seconds(self) -> int:
        try:
            delay = int(self.configure.get("resume_delay_sec", 4))
        except (TypeError, ValueError):
            delay = 4
        return max(1, min(30, delay))

    def _save_audio_settings(self, *_):
        try:
            delay = int(self.resume_delay_var.get())
        except (TypeError, ValueError, tk.TclError):
            delay = 4
        delay = max(1, min(30, delay))
        self.resume_delay_var.set(delay)
        self.configure["resume_delay_sec"] = delay
        self._save_config()

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _seamless_music_enabled(self) -> bool:
        try:
            return bool(self.seamless_music_var.get())
        except Exception:
            return bool(self.configure.get("seamless_music", False))

    def _save_player_settings(self, *_):
        enabled = self._seamless_music_enabled()
        self.configure["seamless_music"] = enabled
        self._save_config()
        if enabled and getattr(self, "_paused_by_game_flag", False):
            threading.Thread(
                target=self._resume_spotify_after_game_quiet,
                daemon=True,
            ).start()

    def _build_ui(self):
        # ── Root layout ───────────────────────────────────────────────────────
        container = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True)

        # ── Sidebar (native CTk — no canvas clipping) ─────────────────────────
        logo_photo = _load_puppy_logo_photo((40, 40))
        self._brand_logo_photo = logo_photo

        self.sidebar = T.SidebarPanel(
            container,
            on_nav=self._nav,
            logo_photo=logo_photo,
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self._sidebar_brand = self.sidebar.brand_frame

        self._current_page = "main"

        # ── Main content ──────────────────────────────────────────────────────
        main = ctk.CTkFrame(container, fg_color=BG, corner_radius=0)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        header = ctk.CTkFrame(main, fg_color=BG, height=40, corner_radius=0)
        header.pack(fill=tk.X)

        # Custom window controls (Minimize / Close) for frameless window
        win_controls = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
        win_controls.pack(side=tk.RIGHT, padx=(0, 12))

        # Close button (hover light red)
        close_btn = ctk.CTkButton(
            win_controls, text="\u2715", width=28, height=28, fg_color="transparent",
            text_color=TEXT_MUTED, hover_color="#fee2e2", corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=F_UI, size=11),
            command=self._on_close
        )
        close_btn.pack(side=tk.RIGHT, padx=2)

        min_btn = ctk.CTkButton(
            win_controls, text="\u2014", width=28, height=28, fg_color="transparent",
            text_color=TEXT_MUTED, hover_color=SURFACE3, corner_radius=RADIUS_SM,
            font=ctk.CTkFont(family=F_UI, size=11),
            command=self._minimize_window
        )
        min_btn.pack(side=tk.RIGHT, padx=2)

        status_cluster = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
        status_cluster.pack(side=tk.RIGHT, padx=(0, 10))

        self.status_dot = ctk.CTkLabel(
            status_cluster, text="\u25cf", fg_color="transparent", text_color=TEXT_MUTED,
            font=ctk.CTkFont(family=F_UI, size=8)
        )
        self.status_dot.pack(side=tk.RIGHT, padx=(4, 0), pady=8)

        self.status_pill = ctk.CTkLabel(
            status_cluster, text="Idle", fg_color="transparent", text_color=TEXT_MUTED,
            font=T.ctk_font(12),
        )
        self.status_pill.pack(side=tk.RIGHT, pady=8)

        self.content = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        self.content.pack(fill=tk.BOTH, expand=True, padx=(14, 14), pady=(6, 10))

        # Expose widgets
        self.header = header
        self.main = main
        self.player_frame = None
        self._build_pages()
        self._setup_window_dragging()

    def _setup_window_dragging(self):
        self._drag_x = 0
        self._drag_y = 0

        def _start_drag(event):
            self._drag_enabled = True
            self._drag_x = event.x
            self._drag_y = event.y

        def _drag_motion(event):
            if not getattr(self, "_drag_enabled", True):
                return
            deltax = event.x - self._drag_x
            deltay = event.y - self._drag_y
            x = self.root.winfo_x() + deltax
            y = self.root.winfo_y() + deltay
            self.root.geometry(f"+{x}+{y}")

        drag_targets = [self.header, self._sidebar_brand]
        for widget in drag_targets:
            if widget:
                widget.bind("<Button-1>", _start_drag)
                widget.bind("<B1-Motion>", _drag_motion)

        def _toggle_maximize(event):
            if self.root.state() == "zoomed":
                self.root.state("normal")
            else:
                self.root.state("zoomed")

        if self.header:
            self.header.bind("<Double-Button-1>", _toggle_maximize)
        if self._sidebar_brand:
            self._sidebar_brand.bind("<Double-Button-1>", _toggle_maximize)

    def _show_verifying(self, show: bool = True):
        """Show or hide the verifying playback indicator in the status bar."""
        def _update():
            try:
                if show:
                    self.status_pill.configure(text="Verifying…", text_color=PURPLE)
                    self.status_dot.configure(text_color=PURPLE)
                else:
                    self.status_pill.configure(text="Idle", text_color=TEXT_MUTED)
                    self.status_dot.configure(text_color=TEXT_MUTED)
            except Exception:
                pass
        try:
            self.root.after(0, _update)
        except Exception:
            _update()

    def _on_root_resize(self, event=None):
        """Update fonts, sidebar, wraplengths, and padding based on window size."""
        try:
            w = max(300, self.root.winfo_width())
            h = max(300, self.root.winfo_height())
        except Exception:
            w, h = WIN_W, WIN_H

        # Scale factor: 1.0 at 1280px wide, scales down/up proportionally
        scale = max(0.7, min(1.3, w / 1280))
        # Avoid redundant updates (only act on meaningful change)
        prev_scale = getattr(self, '_prev_scale', 0)
        if abs(scale - prev_scale) < 0.02 and prev_scale != 0:
            return
        self._prev_scale = scale

        def _sf(base_size):
            """Scale a font size. Disabled per user request so fonts don't grow huge on maximize."""
            return base_size

        # ── Sidebar ──────────────────────────────────────────────────────
        try:
            self.sidebar.configure(width=SIDEBAR_W)
        except Exception:
            pass

        # ── Content area wraplengths ─────────────────────────────────────
        wrap = max(240, w - SIDEBAR_W - 150)

        # Game banner + mood
        try:
            self.game_banner.configure(font=(F_UI, _sf(15), "bold"), wraplength=wrap)
        except Exception:
            pass
        try:
            self.mood_lbl.configure(font=(F_UI, _sf(11)), wraplength=wrap)
        except Exception:
            pass
        try:
            self.playlist_display_lbl.configure(font=(F_UI, _sf(10), "italic"), wraplength=wrap)
        except Exception:
            pass

        # Track title
        try:
            self.track_lbl.configure(font=(F_UI, _sf(17), "bold"), wraplength=wrap)
        except Exception:
            pass

        # Status log
        try:
            self.status_log_lbl.configure(font=(F_UI, _sf(10)), wraplength=wrap)
        except Exception:
            pass

        # Header status
        try:
            self.status_pill.configure(font=(F_UI, _sf(9)))
        except Exception:
            pass

        # Seamless music description
        try:
            self._seamless_desc_lbl.configure(
                font=(F_UI, _sf(9)), wraplength=max(200, wrap - 60))
        except Exception:
            pass

        # Playlists / blocked page labels
        for attr in ('pl_status_lbl', 'blocked_status_lbl'):
            try:
                lbl = getattr(self, attr, None)
                if lbl:
                    lbl.configure(font=(F_UI, _sf(10)), wraplength=wrap)
            except Exception:
                pass

        # Store for other code
        self._dynamic_wrap = wrap
        self._ui_scale = scale

    def _nav(self, page):
        self._current_page = page
        if hasattr(self, "sidebar") and self.sidebar:
            self.sidebar.set_active(page)

        # Hide all pages, show selected
        for f in [getattr(self, '_page_main', None),
                  getattr(self, '_page_playlists', None),
                  getattr(self, '_page_games', None),
                  getattr(self, '_page_blocked', None),
                  getattr(self, '_page_settings', None),
                  getattr(self, '_page_faq', None)]:
            try:
                if f: f.pack_forget()
            except Exception:
                pass

        page_map = {
            "main":      getattr(self, '_page_main', None),
            "playlists": getattr(self, '_page_playlists', None),
            "games":     getattr(self, '_page_games', None),
            "blocked":   getattr(self, '_page_blocked', None),
            "settings":  getattr(self, '_page_settings', None),
            "faq":       getattr(self, '_page_faq', None),
        }
        target = page_map.get(page)
        if target:
            target.pack(fill=tk.BOTH, expand=True)
        if page == "playlists" and self.spotify:
            self._load_playlists()
        if page == "blocked":
            self._refresh_blocked_page()

        return

    def _build_pages(self):
        page_bg = lambda: ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self._page_main = page_bg()
        self._page_playlists = page_bg()
        self._page_games = page_bg()
        self._page_blocked = page_bg()
        self._page_settings = page_bg()
        self._page_faq = page_bg()

        # Build page contents (each page isolated so one failure won't skip the rest)
        for build in (
            self._build_main_page,
            self._build_playlists_page,
            self._build_games_page,
            self._build_blocked_page,
            self._build_settings_page,
            self._build_faq_page,
        ):
            try:
                build()
            except Exception as e:
                try:
                    self._log(f"Failed to build page {build.__name__}: {e}")
                except Exception:
                    pass

        # Show default page
        self._nav('main')

    def _card(self, parent, pady=0):
        return T.elevated_card(parent, pady=pady)

    def _section_lbl(self, parent, text):
        T.section_header(parent, text)

    # ── MAIN PAGE ─────────────────────────────────────────────────────────────

    def _build_main_page(self):
        mp = self._page_main

        self._section_lbl(mp, "Console")
        console = self._card(mp, pady=0)

        # Game status + auto
        status_row = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        status_row.pack(fill=tk.X, pady=(0, 8))

        status_left = ctk.CTkFrame(status_row, fg_color="transparent", corner_radius=0)
        status_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))

        game_icon_sz = 40
        self._game_icon_holder = ctk.CTkFrame(
            status_left, fg_color=SURFACE3, width=game_icon_sz, height=game_icon_sz,
            corner_radius=RADIUS_SM, border_width=0,
        )
        self._game_icon_holder.pack(side=tk.LEFT, padx=(0, 10))
        self._game_icon_holder.pack_propagate(False)

        self._game_icon_label = ctk.CTkLabel(
            self._game_icon_holder, text="\U0001f3ae", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.ctk_font(16),
        )
        self._game_icon_label.pack(fill=tk.BOTH, expand=True)

        status_text = ctk.CTkFrame(status_left, fg_color="transparent", corner_radius=0)
        status_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.game_banner = ctk.CTkLabel(
            status_text, text="No saved game running",
            fg_color="transparent", text_color=TEXT,
            font=T.ctk_font(15, "bold"), anchor="w",
        )
        self.game_banner.pack(fill=tk.X)

        self.mood_lbl = ctk.CTkLabel(
            status_text,
            text="Add games in My Games \u2014 music starts when they run",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.ctk_font(12), anchor="w", justify=tk.LEFT,
        )
        self.mood_lbl.pack(fill=tk.X, pady=(2, 0))

        auto_frame = ctk.CTkFrame(status_row, fg_color="transparent", corner_radius=0)
        auto_frame.pack(side=tk.RIGHT)

        ctk.CTkLabel(
            auto_frame, text="Auto", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.ctk_font(13),
        ).pack(side=tk.LEFT, padx=(0, 6))

        ctk.CTkSwitch(
            auto_frame, variable=self.auto_mode, text="",
            fg_color=SURFACE4, progress_color=ACCENT,
            button_color="#ffffff", button_hover_color=SURFACE3,
            width=40, height=20,
        ).pack(side=tk.LEFT)

        self.playlist_display_lbl = ctk.CTkLabel(
            console, text="Playlist: \u2014", fg_color="transparent",
            text_color=ACCENT, font=T.ctk_font(13), anchor="w",
        )
        self.playlist_display_lbl.pack(fill=tk.X, pady=(0, 10))

        # Now playing — same surface, no inset box
        track_info_row = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        track_info_row.pack(fill=tk.X, pady=(0, 6))

        art_wrap = ctk.CTkFrame(
            track_info_row, fg_color=SURFACE3, width=56, height=56,
            corner_radius=RADIUS_SM, border_width=0,
        )
        art_wrap.pack(side=tk.LEFT, padx=(0, 12))
        art_wrap.pack_propagate(False)

        self.art_holder = art_wrap
        self.art_label = tk.Label(
            art_wrap, text="\u266a", bg=SURFACE3, fg=ACCENT,
            bd=0, highlightthickness=0, font=(F_UI, 22, "bold"),
        )
        self.art_label.pack(fill=tk.BOTH, expand=True)

        labels_col = ctk.CTkFrame(track_info_row, fg_color="transparent", corner_radius=0)
        labels_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.track_lbl = ctk.CTkLabel(
            labels_col, text="Nothing playing", fg_color="transparent",
            text_color=TEXT, font=T.ctk_font(16, "bold"),
            anchor="w", justify=tk.LEFT,
        )
        self.track_lbl.pack(fill=tk.X)

        self.artist_lbl = ctk.CTkLabel(
            labels_col, text="Connect Spotify in Settings",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.ctk_font(13), anchor="w", justify=tk.LEFT,
        )
        self.artist_lbl.pack(fill=tk.X, pady=(2, 0))

        self.status_log_lbl = T.info_banner(console, text="GameBeats ready.")
        self.status_log_lbl.pack(fill=tk.X, pady=(4, 10))

        # Transport — compact, no pill container
        ctrl_row = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        ctrl_row.pack(pady=(0, 10))

        self.prev_btn = CircleBtn(
            ctrl_row, "\u23ee", command=self._prev,
            size=38, font_size=13, canvas_bg=SURFACE,
        )
        self.prev_btn.pack(side=tk.LEFT, padx=8)

        self.play_btn = CircleBtn(
            ctrl_row, "\u25b6", command=self._play_pause_toggle,
            size=52, bg=ACCENT, fg="#ffffff", font_size=18,
            canvas_bg=SURFACE, accent=True,
        )
        self.play_btn.pack(side=tk.LEFT, padx=8)

        self.next_btn = CircleBtn(
            ctrl_row, "\u23ed", command=self._next,
            size=38, font_size=13, canvas_bg=SURFACE,
        )
        self.next_btn.pack(side=tk.LEFT, padx=8)

        # Keep music playing — inline row
        seamless_row = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        seamless_row.pack(fill=tk.X, pady=(0, 10))

        seamless_copy = ctk.CTkFrame(seamless_row, fg_color="transparent", corner_radius=0)
        seamless_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ctk.CTkLabel(
            seamless_copy, text="Keep music playing",
            fg_color="transparent", text_color=TEXT,
            font=T.ctk_font(13, "bold"), anchor="w",
        ).pack(fill=tk.X)

        self._seamless_desc_lbl = ctk.CTkLabel(
            seamless_copy,
            text="Do not auto-pause Spotify when game audio is detected.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.ctk_font(12), anchor="w", justify=tk.LEFT,
        )
        self._seamless_desc_lbl.pack(fill=tk.X, pady=(1, 0))

        ctk.CTkSwitch(
            seamless_row, variable=self.seamless_music_var,
            command=self._save_player_settings, text="",
            fg_color=SURFACE4, progress_color=ACCENT,
            button_color="#ffffff", button_hover_color=SURFACE3,
            width=40, height=20,
        ).pack(side=tk.RIGHT, padx=(12, 0))

        # Actions
        actions = ctk.CTkFrame(console, fg_color="transparent", corner_radius=0)
        actions.pack(fill=tk.X)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        self.block_pl_btn = RoundedButton(
            actions, text="\u2205  Block playlist",
            command=self._block_current_playlist,
            width=140, height=36, bg=SURFACE3, fg=AMBER,
            font_size=12, canvas_bg=SURFACE, border_color="",
            radius=RADIUS_SM,
        )
        self.block_pl_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        RoundedButton(
            actions, text="\u21ba  Try another",
            command=self._try_another_playlist,
            width=140, height=36, bg=ACCENT, fg="#ffffff",
            font_size=12, canvas_bg=SURFACE, border_color="",
            radius=RADIUS_SM,
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    # ── PLAYLISTS PAGE ────────────────────────────────────────────────────────

    def _build_playlists_page(self):
        p = self._page_playlists

        hdr = ctk.CTkFrame(p, fg_color="transparent", corner_radius=0)
        hdr.pack(fill=tk.X, pady=(4, 10))
        
        ctk.CTkLabel(
            hdr, text="Your Playlists", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=16, weight="bold")
        ).pack(side=tk.LEFT)
        
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent", corner_radius=0)
        btn_row.pack(side=tk.RIGHT, padx=(0, 4))
        
        self.pl_add_btn = RoundedButton(
            btn_row, text="+ Add link", command=self._add_playlist_link,
            width=120, height=36, bg=SURFACE2, fg=TEXT_SEC,
            font_size=10, canvas_bg=BG, border_color=BORDER2)
        self.pl_add_btn.pack(side=tk.RIGHT, padx=(6, 0))
        
        RoundedButton(btn_row, text="\u21ba Refresh", command=self._load_playlists,
                      width=120, height=36, bg=SURFACE2, fg=TEXT_SEC,
                      font_size=10, canvas_bg=BG, border_color=BORDER2).pack(side=tk.RIGHT)

        self.pl_status_lbl = ctk.CTkLabel(
            p, text="Connect Spotify in Settings to load playlists.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=ctk.CTkFont(family=F_UI, size=10),
            wraplength=400, justify=tk.LEFT
        )
        self.pl_status_lbl.pack(fill=tk.X, pady=(0, 14))

        self.pl_inner = ctk.CTkScrollableFrame(p, fg_color="transparent", corner_radius=0)
        self.pl_inner.pack(fill=tk.BOTH, expand=True)

    # ── GAMES PAGE ───────────────────────────────────────────────────────

    def _build_games_page(self):
        GamesPage(
            self._page_games,
            on_games_changed=lambda: self._log("Game list updated."),
        ).pack(fill=tk.BOTH, expand=True)

    # ── BLOCKED PAGE ──────────────────────────────────────────────────────────

    def _build_blocked_page(self):
        p = self._page_blocked

        hdr = ctk.CTkFrame(p, fg_color="transparent", corner_radius=0)
        hdr.pack(fill=tk.X, pady=(4, 16))
        
        ctk.CTkLabel(
            hdr, text="Blocked Playlists", fg_color="transparent", text_color=TEXT,
            font=T.ctk_font(22, "bold")
        ).pack(side=tk.LEFT)
        
        T.ghost_button(hdr, text="\u21ba  Refresh", command=self._refresh_blocked_page,
                       width=100, height=36).pack(side=tk.RIGHT, padx=(0, 4))

        self.blocked_status_lbl = ctk.CTkLabel(
            p, text="Playlists blocked from auto-play appear here.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=ctk.CTkFont(family=F_UI, size=10),
            wraplength=400, justify=tk.LEFT
        )
        self.blocked_status_lbl.pack(fill=tk.X, pady=(0, 14))

        self.blocked_inner = ctk.CTkScrollableFrame(p, fg_color="transparent", corner_radius=0)
        self.blocked_inner.pack(fill=tk.BOTH, expand=True)

    def _refresh_blocked_page(self):
        if not hasattr(self, "blocked_inner"):
            return
        for w in self.blocked_inner.winfo_children():
            w.destroy()

        blocked = self._blocked_playlists()
        if not blocked:
            self.blocked_status_lbl.configure(
                text="No blocked playlists \u2014 block one from the Player page.",
                text_color=TEXT_MUTED)
            return

        count = len(blocked)
        self.blocked_status_lbl.configure(
            text=f"{count} blocked playlist{'s' if count != 1 else ''}",
            text_color=TEXT_SEC)

        for item in blocked:
            uri  = item.get("uri", "")
            name = item.get("name") or uri.split(":")[-1] or "Blocked playlist"
            query = item.get("query", "")

            row = ctk.CTkFrame(self.blocked_inner, fg_color=SURFACE, corner_radius=RADIUS_MD,
                               border_width=1, border_color=BORDER)
            row.pack(fill=tk.X, pady=4, padx=(0, 4))

            badge = ctk.CTkFrame(row, fg_color=ACCENT_BG, width=44, height=44, corner_radius=22)
            badge.pack(side=tk.LEFT, padx=(12, 6), pady=12)
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text="\u2205", fg_color="transparent", text_color=AMBER,
                         font=T.ctk_font(14)).pack(expand=True)

            col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
            col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8), pady=12)

            ctk.CTkLabel(
                col, text=name, fg_color="transparent", text_color=TEXT,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"), anchor="w", justify=tk.LEFT,
                wraplength=350
            ).pack(anchor="w", fill=tk.X)

            detail = (query or uri)[:80]
            ctk.CTkLabel(
                col, text=detail, fg_color="transparent", text_color=TEXT_MUTED,
                font=ctk.CTkFont(family="Segoe UI", size=9), anchor="w", justify=tk.LEFT,
                wraplength=350
            ).pack(anchor="w", fill=tk.X)

            ctk.CTkButton(
                row, text="Unblock",
                fg_color="transparent", text_color=ACCENT, hover_color=SURFACE3,
                font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                width=72, height=32, corner_radius=RADIUS_SM,
                command=lambda u=uri: (
                    self._unblock_playlist(u),
                    self._refresh_blocked_page(),
                ),
            ).pack(side=tk.RIGHT, padx=(0, 12), pady=12)

    # ── SETTINGS PAGE ─────────────────────────────────────────────────────────

    def _build_settings_page(self):
        p = self._page_settings

        # ── Auto Playlists ────────────────────────────────────────────────────
        self._section_lbl(p, "Auto playlists")
        ap = self._card(p, pady=0)

        pick_row = ctk.CTkFrame(ap, fg_color="transparent", corner_radius=0)
        pick_row.pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            pick_row, text="Playlists to consider", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10)
        ).pack(side=tk.LEFT)
        
        pick_spin_frame = ctk.CTkFrame(pick_row, fg_color="transparent", corner_radius=0)
        pick_spin_frame.pack(side=tk.RIGHT)
        
        pick_spin_entry = ctk.CTkEntry(
            pick_spin_frame, width=40, height=28, textvariable=self.playlist_limit_var,
            fg_color=SURFACE3, border_color=BORDER2, corner_radius=6, justify="center"
        )
        pick_spin_entry.pack(side=tk.LEFT, padx=2)
        
        def _pick_dec():
            val = max(1, self.playlist_limit_var.get() - 1)
            self.playlist_limit_var.set(val)
            self._save_auto_playlist_settings()
            
        def _pick_inc():
            val = min(20, self.playlist_limit_var.get() + 1)
            self.playlist_limit_var.set(val)
            self._save_auto_playlist_settings()
            
        ctk.CTkButton(
            pick_spin_frame, text="-", width=20, height=28, fg_color=SURFACE3, hover_color=SURFACE4,
            text_color=TEXT, corner_radius=6, command=_pick_dec
        ).pack(side=tk.LEFT, padx=1)
        
        ctk.CTkButton(
            pick_spin_frame, text="+", width=20, height=28, fg_color=SURFACE3, hover_color=SURFACE4,
            text_color=TEXT, corner_radius=6, command=_pick_inc
        ).pack(side=tk.LEFT, padx=1)

        resume_row = ctk.CTkFrame(ap, fg_color="transparent", corner_radius=0)
        resume_row.pack(fill=tk.X)
        
        ctk.CTkLabel(
            resume_row, text="Resume / end-check delay", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10)
        ).pack(side=tk.LEFT)
        
        resume_spin_frame = ctk.CTkFrame(resume_row, fg_color="transparent", corner_radius=0)
        resume_spin_frame.pack(side=tk.RIGHT)
        
        resume_spin_entry = ctk.CTkEntry(
            resume_spin_frame, width=40, height=28, textvariable=self.resume_delay_var,
            fg_color=SURFACE3, border_color=BORDER2, corner_radius=6, justify="center"
        )
        resume_spin_entry.pack(side=tk.LEFT, padx=2)
        
        def _resume_dec():
            val = max(1, self.resume_delay_var.get() - 1)
            self.resume_delay_var.set(val)
            self._save_audio_settings()
            
        def _resume_inc():
            val = min(30, self.resume_delay_var.get() + 1)
            self.resume_delay_var.set(val)
            self._save_audio_settings()
            
        ctk.CTkButton(
            resume_spin_frame, text="-", width=20, height=28, fg_color=SURFACE3, hover_color=SURFACE4,
            text_color=TEXT, corner_radius=6, command=_resume_dec
        ).pack(side=tk.LEFT, padx=1)
        
        ctk.CTkButton(
            resume_spin_frame, text="+", width=20, height=28, fg_color=SURFACE3, hover_color=SURFACE4,
            text_color=TEXT, corner_radius=6, command=_resume_inc
        ).pack(side=tk.LEFT, padx=1)
        
        ctk.CTkLabel(
            resume_row, text="sec", fg_color="transparent", text_color=TEXT_MUTED,
            font=ctk.CTkFont(family=F_UI, size=9)
        ).pack(side=tk.RIGHT, padx=(0, 8))


    # ── LOGIC ─────────────────────────────────────────────────────────────────

    def _ui_log_message(self, msg):
        text = str(msg or "").strip()
        if not text:
            return None
        low = text.lower()

        if low.startswith("game running:"):
            return text
        if "game list updated" in low:
            return "Game list updated."
        if "watching your saved games" in low:
            return "Watching games."
        if "game closed" in low:
            return "Game closed - music paused."
        if "playlist unblocked" in low:
            return "Playlist unblocked."
        if "blocked playlist skipped" in low:
            return "Blocked playlist skipped."
        if "playlist removed" in low:
            return "Playlist removed."
        if low.startswith("playlist added:"):
            return "Playlist added."
        if low.startswith("playing:") or low.startswith("looping:"):
            return text.replace("\u25b6 ", "", 1)
        if "start a saved game first" in low:
            return "Start a saved game first."
        if "game audio detected" in low and "paused" in low:
            return "Game audio detected - music paused."
        if "game audio quiet" in low and "resumed" in low:
            return "Game audio quiet - music resumed."
        if "pause did not confirm" in low:
            return "Pause needs attention."
        if "resume did not confirm" in low:
            return "Resume needs attention."

        technical_tokens = (
            "[_", " js ", "xpath", "selector", "data-testid", "playwright",
            "chrom", "browser", "profile", "spotify_web_profile", "hwnd",
            "pid", "uri=", "spotify:playlist", "http://", "https://",
            "localhost", "loopback", "peak=", "db", "audio monitor",
            "controller", "connect", "fallback", "media key", "attempt",
            "exception", "debug", "bypass", "widevine", "drm", "jina",
            "scraper", "desktop.ensure", "verify", "verification",
            "focus_guard", "virtual desktop",
        )
        if any(token in low for token in technical_tokens):
            if any(token in low for token in ("failed", "error", "not found", "uncertain", "missed", "could not", "did not")):
                return "Music needs attention."
            if "pause" in low or "paused" in low:
                return "Music paused."
            if "resume" in low or "resumed" in low:
                return "Music resumed."
            if any(token in low for token in ("playing", "succeeded", "started", "clicked", "selected", "audio detected")):
                return "Music started."
            if any(token in low for token in ("search", "opening", "starting", "launch", "waiting")):
                return "Starting music..."
            return None

        if "searching playlists" in low or "picking another" in low:
            return "Finding music..."
        if "resuming cached playlist" in low:
            return "Resuming music..."
        if "playback stopped" in low:
            return "Finding music..."
        if "playlist ended" in low:
            return "Playlist finished."
        if "spotify connected" in low:
            return "Music ready."
        if low.startswith("spotify:"):
            return "Music setup needs attention."

        return text[:120]

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

        # Filter out technical noise and debug info from the UI label
        msg_s = str(msg)
        clean_msg = self._ui_log_message(msg_s)
        if not clean_msg:
            return
        noise_keywords = [
            "Restarting", "Closing", "Found", "Virtual desktop", "Sending", 
            "Sent", "Fetching", "Warning", "focus_guard", "Injected", 
            "Injection", "monitor on", "Spotify.exe (track)", "Ignored output"
        ]
        if False and any(keyword in msg_s for keyword in noise_keywords):
            return

        if hasattr(self, "status_log_lbl"):
            color = RED if msg_s.startswith("⚠") else ACCENT
            # Clean up the output message for the UI
            clean_msg = msg_s.replace("▶ ", "")
            clean_msg = self._ui_log_message(msg_s) or clean_msg
            color = RED if "attention" in clean_msg.lower() else color
            self.status_log_lbl.configure(text=clean_msg[:120], text_color=color)

    def _set_status(self, text, color=TEXT_SEC):
        self.status_pill.configure(text=text, text_color=color)
        self.status_dot.configure(text_color=color)

    def _animate_play_effect(self):
        # Animation removed - using cleaner UI without visualization
        pass

    def _on_spotify_ready(self):
        """After player is ready: verify, load playlists, start watchers."""
        ok, msg = self.spotify.verify_access()
        if ok:
            if hasattr(self, "auth_lbl"):
                self.auth_lbl.configure(text=f"✓ {msg}", text_color=ACCENT)
            self._log(msg)
        else:
            if hasattr(self, "auth_lbl"):
                self.auth_lbl.configure(text=f"⚠ {msg[:80]}", text_color=AMBER)
            self._log(f"Spotify: {msg}")
        self._update_playlist_ui_mode()
        self._load_playlists()
        self._start_track_poll()
        self._start_background_detection()

    def _update_playlist_ui_mode(self):
        if not hasattr(self, "pl_add_btn"):
            return
        if self._is_desktop_mode():
            self.pl_add_btn.pack(side=tk.RIGHT, padx=(0, 6))
            self.pl_status_lbl.configure(
                text="Add your playlists with + Add link (paste from Spotify Share).",
                text_color=TEXT_SEC)
        else:
            self.pl_add_btn.pack_forget()

    def _toggle_desktop_mode(self):
        if self.desktop_mode_var.get():
            if self.detector:
                self.detector.stop()
                self.detector = None
            self.spotify = None
            self._start_desktop_mode()
            self._log("Switched to free web player mode.")
        else:
            self.configure["playback_mode"] = "api"
            self._save_config()
            self.spotify = None
            if self.detector:
                self.detector.stop()
                self.detector = None
            self._log("Switched to API mode — connect credentials below.")
            if hasattr(self, "auth_lbl"):
                self.auth_lbl.configure(text="Enter credentials and Connect", text_color=TEXT_SEC)
            self._nav("settings")

    def _try_auto_login(self):
        cid = self.configure.get("client_id")
        sec = self.configure.get("client_secret")
        if cid and sec:
            self.auth = SpotifyAuth(cid, sec)
            if self.auth.load(TOKENS_FILE):
                self.spotify = SpotifyController(self.auth)
                self.root.after(400, self._on_spotify_ready)

    def _connect_spotify(self):
        cid  = self.cid_var.get().strip()
        csec = self.csec_var.get().strip()
        if not cid or not csec:
            self.auth_lbl.configure(text="⚠ Enter both credentials", text_color=AMBER)
            return
        self.configure["client_id"]     = cid
        self.configure["client_secret"] = csec
        self._save_config()
        self.auth = SpotifyAuth(cid, csec)
        self.auth_lbl.configure(text="⏳ Browser opening…", text_color=AMBER)
        self._log("Waiting for Spotify login…")

        def done(ok):
            if ok:
                self.configure["playback_mode"] = "api"
                self.desktop_mode_var.set(False)
                self._save_config()
                self.spotify = SpotifyController(self.auth)
                self.auth.save(TOKENS_FILE)
                self._log("Spotify API connected!")
                self._on_spotify_ready()
            else:
                self.auth_lbl.configure(text="✗ Auth failed — try again", text_color=RED)

        self.auth.start_auth_flow(on_complete=lambda s: self.root.after(0, lambda: done(s)))

    def _build_faq_page(self):
        p = self._page_faq

        hdr = ctk.CTkFrame(p, fg_color="transparent", corner_radius=0)
        hdr.pack(fill=tk.X, pady=(4, 10))
        
        ctk.CTkLabel(
            hdr, text="FAQ & Help", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=16, weight="bold")
        ).pack(side=tk.LEFT)

        inner = ctk.CTkScrollableFrame(p, fg_color="transparent", corner_radius=0)
        inner.pack(fill=tk.BOTH, expand=True)

        # Content Cards
        self._section_lbl(inner, "Important Information")
        c1 = self._card(inner)
        
        ctk.CTkLabel(
            c1, text="Not a Spotify Replacement", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=13, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c1, text="GameBeats is a companion tool designed to seamlessly integrate with your existing setup. It is not a standalone player; you must have the official Spotify client installed and running to use this application.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c1, text="Spotify Free Users", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=13, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c1, text="Supporting free Spotify accounts required overcoming significant technical limitations, but we made it happen. Please note that on first start, the free-tier desktop client might be a bit clunky to connect to. We apologize for any inconvenience, but it should work smoothly most of the time.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

        self._section_lbl(inner, "Important Setup Steps")
        c_web = self._card(inner)
        
        ctk.CTkLabel(
            c_web, text="1. One-Time Login Window", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c_web, text="On your first run, a secondary Spotify window will open. You MUST log in to Spotify here to establish the connection. Crucially, make sure you log in using the exact same Spotify account that is currently active on your main Spotify Desktop app.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c_web, text="2. Do Not Close the Helper Window", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c_web, text="While a game is running, you may notice this helper window remain open in the background. Please DO NOT close this window manually! It is required to maintain the connection. If you close it, your music will stop syncing.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c_web, text="3. Desktop App Required", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c_web, text="Even with the helper window open, you must always have the official Spotify Desktop application running on your PC for the app to route audio and detect playback correctly.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

        self._section_lbl(inner, "Best Practices")
        c2 = self._card(inner)
        
        ctk.CTkLabel(
            c2, text="1. Official Spotify Client Only", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="Please ensure you are using the Spotify Desktop client downloaded directly from the official Spotify website (.exe). GameBeats does not support the Microsoft Store version.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c2, text="2. Dedicated Playback Device", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="For the best experience, ensure your Spotify account is actively playing only on your local desktop client. Remote playback from other devices may interrupt the application's tracking.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c2, text="3. Adding Games Correctly", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="When adding games to your library, please select the actual game executable (.exe) from your installation folder. Avoid using desktop shortcuts or Steam URL links, as these cannot be properly tracked.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c2, text="4. Audio Capture & Muting", fg_color="transparent", text_color=TEXT,
            font=ctk.CTkFont(family=F_UI, size=10, weight="bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="GameBeats listens to your game's audio to automatically pause and resume music. Do not mute your games or Spotify in the Windows Volume Mixer, otherwise the detection will not work.",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family=F_UI, size=9),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

        self._section_lbl(inner, "Support & Contact")
        c3 = self._card(inner)
        
        ctk.CTkLabel(
            c3, text="If something isn't working... have you tried turning it off and on again? Restarting the app fixes most issues!\n\nJokes aside, if you need further assistance or have recommendations, feel free to contact me at amongkencod10@gmail.com.\n\nThank you for your purchase, and have fun!",
            fg_color="transparent", text_color=TEXT, font=ctk.CTkFont(family=F_UI, size=10, slant="italic"),
            wraplength=450, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

    def _start_background_detection(self):
        """Always watch saved games in the background."""
        if not self.spotify:
            return
        if self.detector and self.detector.running:
            return
        self.detector = GameDetector(
            on_game_found=self._on_game_found,
            on_game_lost=self._on_game_lost,
            user_only=True,
        )
        self.detector.start()
        self._set_status("Watching games", ACCENT)
        if not HAS_PROCESS_LOOPBACK:
            self._log("Tip: install process-audio-capture for game-audio detection.")
        self._log("Watching your saved games…")

    def _set_game_icon(self, info):
        """Show the running game's icon in the player tab."""
        if not info or not hasattr(self, "_game_icon_label"):
            return
        icon_sz = 40

        def _load():
            try:
                pil_img = get_game_square_icon_image(info, size=icon_sz)
            except Exception:
                pil_img = None

            def _apply():
                if pil_img and HAS_PIL:
                    try:
                        ctk_img = ctk.CTkImage(
                            light_image=pil_img, dark_image=pil_img, size=(icon_sz, icon_sz),
                        )
                        self._game_icon_ctk = ctk_img
                        self._game_icon_label.configure(image=ctk_img, text="")
                        return
                    except Exception:
                        pass
                try:
                    mood = info.get("mood", "chill")
                    color = MOOD_TO_PLAYLIST.get(mood, {}).get("color", ACCENT)
                    grad = _generate_gradient_fallback(color, size=(icon_sz, icon_sz), radius=8)
                    if grad and HAS_PIL:
                        ctk_img = ctk.CTkImage(
                            light_image=grad, dark_image=grad, size=(icon_sz, icon_sz),
                        )
                        self._game_icon_ctk = ctk_img
                        self._game_icon_label.configure(image=ctk_img, text="")
                        return
                except Exception:
                    pass
                self._game_icon_ctk = None
                self._game_icon_label.configure(image=None, text="\U0001f3ae")

            self.root.after(0, _apply)

        threading.Thread(target=_load, daemon=True).start()

    def _clear_game_icon(self):
        self._game_icon_ctk = None
        if hasattr(self, "_game_icon_label"):
            try:
                self._game_icon_label.configure(image=None, text="\U0001f3ae", text_color=TEXT_MUTED)
            except Exception:
                pass

    def _on_game_found(self, info):
        self.current_game = info
        self._game_pid = info.get("pid") or get_pid_for_proc(info.get("proc", ""))
        mood_info = MOOD_TO_PLAYLIST.get(info["mood"], {})
        color = mood_info.get("color", ACCENT)
        self.root.after(0, lambda: (
            self.game_banner.configure(text=info["name"], text_color=color),
            self.mood_lbl.configure(
                text=f"Mood → {mood_info.get('name', info['mood'])}  ·  loud game audio pauses music…"),
            self._set_status(info["name"], color),
            self._log(f"Game running: {info['name']}"),
            self._set_game_icon(info),
        ))
        if self.auto_mode.get() and self.spotify:
            # Check if game has a custom Spotify playlist assigned
            custom_uri = info.get("spotify_playlist_uri", "")
            if custom_uri:
                self.root.after(0, lambda: self._log(
                    f"Auto-play: playing assigned playlist for {info['name']}…"))
                def _play_custom_after_silent():
                    # Block auto-pause/resume for the entire automation window
                    # (silent track launch + browser open + playlist start).
                    # Silent track launch is needed for Spotify desktop detection.
                    # The playlist itself is NOT opened in the desktop client
                    # (it's hidden) — only the browser handles playback.
                    self._automation_in_progress = True
                    try:
                        self._launch_spotify_with_silent_track()
                        self._play_custom_playlist_for_game(info, custom_uri)
                    finally:
                        self._automation_in_progress = False

                threading.Thread(
                    target=_play_custom_after_silent,
                    daemon=True,
                ).start()
            else:
                self.root.after(0, lambda: self._log(
                    f"Auto-play: sending music to Spotify web player for {info['name']}…"))
                def _play_query_after_silent():
                    # Block auto-pause/resume for the entire automation window
                    # (silent track launch + browser open + playlist start).
                    # Silent track launch is needed for Spotify desktop detection.
                    # The playlist itself is NOT opened in the desktop client
                    # (it's hidden) — only the browser handles playback.
                    self._automation_in_progress = True
                    try:
                        self._launch_spotify_with_silent_track()
                        self._play_query_for_game(info, force_new=True)
                    finally:
                        self._automation_in_progress = False

                threading.Thread(
                    target=_play_query_after_silent,
                    daemon=True,
                ).start()

    SILENT_TRACK_URI = "spotify:track:2bNCdW4rLnCTzgqUXTTDO1"

    def _launch_spotify_with_silent_track_legacy_unused(self):
        """Restart Spotify desktop and start the silent URI before browser automation."""
        try:
            helper = None
            if hasattr(self, 'spotify') and self.spotify:
                if hasattr(self.spotify, '_desktop_helper'):
                    helper = self.spotify._desktop_helper()
                elif hasattr(self.spotify, 'launch_spotify'):
                    helper = self.spotify
            if helper and hasattr(helper, 'play_uri_direct'):
                ok = helper.play_uri_direct(self.SILENT_TRACK_URI, restart=True)
                if ok:
                    self.root.after(0, lambda: self._log(
                        "Spotify desktop started silent URI for device detection."))
                else:
                    err = getattr(helper, '_last_error', '') or "unknown error"
                    self.root.after(0, lambda e=err: self._log(
                        f"Silent URI playback was not confirmed: {e}"))
                return ok
            if helper and hasattr(helper, 'launch_spotify'):
                ok = bool(helper.launch_spotify(uri=self.SILENT_TRACK_URI))
                try:
                    if ok and hasattr(helper, 'ensure_playing'):
                        ok = bool(helper.ensure_playing())
                except Exception:
                    pass
                self.root.after(0, lambda: self._log(
                    "Spotify desktop launched with silent URI for device detection."))
                return ok
            else:
                self.root.after(0, lambda: self._log(
                    "Could not find Spotify launcher — silent track skipped."))
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(
                f"Silent track launch failed: {e}"))
            return False

    def _launch_spotify_with_silent_track(self):
        """Restart Spotify desktop and play the silent track URI for detection."""
        try:
            helper = None
            if hasattr(self, 'spotify') and self.spotify:
                if hasattr(self.spotify, '_desktop_helper'):
                    helper = self.spotify._desktop_helper()
                elif hasattr(self.spotify, 'launch_spotify'):
                    helper = self.spotify

            if helper and hasattr(helper, 'play_track_uri'):
                ok = helper.play_track_uri(self.SILENT_TRACK_URI, restart=True)
                self.root.after(0, lambda: self._log(
                    "Spotify desktop played silent track URI for device detection."))
                return ok

            if helper and hasattr(helper, 'launch_spotify'):
                helper.launch_spotify(uri=self.SILENT_TRACK_URI)
                self.root.after(0, lambda: self._log(
                    "Spotify desktop launched with silent track for device detection."))

            else:
                self.root.after(0, lambda: self._log(
                    "Could not find Spotify launcher â€” silent track skipped."))
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(
                f"Silent track launch failed: {e}"))

    def _play_custom_playlist_for_game(self, info, playlist_uri: str):
        """Play a specific Spotify playlist URI assigned to a game."""
        if self._play_in_progress:
            return
        self._play_in_progress = True
        try:
            if self._is_web_mode() and self.spotify:
                if not self.spotify.ensure_active_device():
                    err = getattr(self.spotify, "_last_error", "") or "browser failed"
                    self.root.after(0, lambda e=err: self._log(
                        f"⚠ Web player failed to start: {e}"))
                    self._play_in_progress = False
                    return
            elif self.spotify:
                self.spotify.ensure_active_device()

            ok = False
            try:
                ok = bool(self.spotify.play_playlist(playlist_uri))
            except Exception:
                ok = False

            if ok:
                self._spotify_started_by_us = True
                name = info.get("name", "Custom Playlist")
                self.root.after(0, lambda: (
                    self._remember_current_playlist(
                        playlist_uri, f"{name} playlist", "custom playlist"),
                    self._log(f"▶ Playing assigned playlist for {name}"),
                ))
                if self.current_game and not self._audio_monitor_running:
                    self._start_audio_monitor(self.current_game)
            else:
                err = getattr(self.spotify, "_last_error", "") or "Playback failed"
                self.root.after(0, lambda e=err: self._log(
                    f"⚠ Custom playlist failed: {e[:100]}"))
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(
                f"Custom playlist error: {e}"))
        finally:
            self._play_in_progress = False

    def _on_game_lost(self):
        self._stop_audio_monitor()
        self.current_game = None
        self._game_pid = None
        self._play_in_progress = False
        self._playlist_end_pending = False
        self._music_missing_since = 0.0
        if self.spotify and self._spotify_started_by_us:
            threading.Thread(target=self.spotify.media_stop, daemon=True).start()
        if self.spotify and hasattr(self.spotify, "reset_session"):
            self.spotify.reset_session()
        self._spotify_started_by_us = False
        self.root.after(0, lambda: (
            self.game_banner.configure(text="No saved game running", text_color=TEXT_MUTED),
            self.mood_lbl.configure(text="Add games in My Games — music starts when they run"),
            self.playlist_display_lbl.configure(text="Playlist: —"),
            self._set_status("Watching games", ACCENT),
            self._clear_game_icon(),
            self._log("Game closed — music paused."),
        ))

    def _play_query_for_game(self, info, force_new=False, exclude_uris=None, reason="Playing", one_shot: bool = False):
        if self._play_in_progress:
            return

        requested_excludes = set(exclude_uris or [])
        skip_uris = self._skip_playlist_uris(requested_excludes)
        current_blocked = bool(self._current_playlist_uri and self._current_playlist_uri in self._blocked_playlist_uris())
        tags = info.get("tags", [])
        mood = info.get("mood", "chill")
        game_name = info.get("name", "")
        mood_info = MOOD_TO_PLAYLIST.get(mood, {})
        # Search uses game name + saved tags; mood words only if tags are sparse
        from core.playlist_search import build_search_query
        search_q = build_search_query(
            game_name,
            tags,
            mood_info.get("query", "") if len([t for t in tags if not str(t).startswith("_")]) < 2 else "",
        )
        self._play_in_progress = True
        cached = (
            self._is_desktop_mode()
            and getattr(self.spotify, "_session_locked", False)
            and not force_new
            and not requested_excludes
            and not current_blocked
        )
        if cached:
            self.root.after(0, lambda: self._log("Loading connection…"))
        else:
            clean_reason = "Initiating next playlist…" if "playing" in str(reason).lower() else reason
            self.root.after(0, lambda r=clean_reason: self._log(f"{r}"))

        def _run():
            try:
                if self._is_web_mode():
                    self.root.after(0, lambda q=search_q: self._log(
                        f"Searching for a playlist to play…"))
                    if self.spotify:
                        if not self.spotify.ensure_active_device():
                            err = getattr(self.spotify, "_last_error", "") or "browser failed"
                            self.root.after(0, lambda e=err: self._log(
                                f"⚠ Web player failed to start: {e}"))
                            self.root.after(0, lambda: self._on_play_result(None, mood, search_q))
                            return
                elif self.spotify:
                    self.spotify.ensure_active_device()

                if self._is_web_mode() or self._is_desktop_mode():
                    result = self.spotify.play_random_for_mood(
                        mood=mood,
                        query_hint="",
                        game_name=game_name,
                        tags=tags,
                        force_new=force_new or bool(requested_excludes) or current_blocked,
                        max_results=self._playlist_pick_count(),
                        exclude_uris=skip_uris,
                        one_shot=one_shot,
                    )
                else:
                    result = self.spotify.search_and_play(
                        search_q,
                        max_results=self._playlist_pick_count(),
                        blocked_uris=self._blocked_playlist_uris(),
                        exclude_uris=skip_uris,
                    )
                    if result and hasattr(self.spotify, "set_repeat_mode"):
                        repeat = "context" if self._end_behavior_key() == "loop_current" else "off"
                        self.spotify.set_repeat_mode(repeat)
            except Exception as ex:
                result = None
                if self.spotify:
                    self.spotify._last_error = str(ex)
            self.root.after(0, lambda r=result, q=search_q: self._on_play_result(r, mood, q))

        threading.Thread(target=_run, daemon=True).start()

    def _on_play_result(self, result, mood, search_q):
        self._play_in_progress = False
        # If playback started successfully, clear the pending playlist-end
        # marker so the monitor can prompt again on future ends.
        try:
            if result:
                self._playlist_end_pending = False
        except Exception:
            pass
        if result:
            self._manual_paused = False
            picked_uri = result.get("uri", "")
            picked_name = result.get("name", "")
            picked_query = result.get("query", search_q)
            
            def _on_ok():
                try:
                    self._spotify_started_by_us = True
                    self._remember_current_playlist(picked_uri, picked_name, picked_query)
                    if self.current_game and not self._audio_monitor_running:
                        self._start_audio_monitor(self.current_game)
                    via = getattr(self.spotify, "_last_play_method", "") or "open"
                    rank = result.get("pick_rank", "?")
                    top_n = result.get("top_count", "?")
                    self._log(
                        f"▶ Web player playlist ({mood}) #{rank}/{top_n} via {via}: "
                        f"{picked_query[:42]}")
                    self.root.after(800, self._pause_started_playlist_if_game_loud)
                except Exception:
                    pass
            self.root.after(0, _on_ok)
            return
        else:
            # Playback did not start or verification failed.
            # In desktop mode, mark the attempted playlist as tried and automatically
            # try another playlist to avoid repeatedly starting the same (bad) URI.
            try:
                failed_uri = getattr(self.spotify, "_last_uri", "") if self.spotify else ""
                if self._is_desktop_mode() and failed_uri:
                    if failed_uri not in self._tried_playlist_uris:
                        self._tried_playlist_uris.append(failed_uri)
                    # Avoid infinite retry loops by bounding tries implicitly via tried list
                    self._log("⚠ Loading connection failed — trying another playlist...")
                    threading.Thread(
                        target=lambda: self._play_query_for_game(
                            self.current_game,
                            force_new=True,
                            exclude_uris=set(self._tried_playlist_uris),
                            reason="Verification failed - picking another",
                        ),
                        daemon=True,
                    ).start()
                    return
            except Exception:
                pass

            self._playlist_end_pending = False
            err = getattr(self.spotify, "_last_error", "") or "No playlist found"
            self._log(f"⚠ {err[:100]}  (log in to Spotify in the web player, then retry)")

    def _start_audio_monitor(self, info):
        self._stop_audio_monitor()
        if not HAS_PROCESS_LOOPBACK:
            self.root.after(0, lambda: self._log(
                "Install process-audio-capture for game-audio pause."))
            return
        self._audio_monitor_running = True
        self._game_audio = GameMusicDetector()
        self._broken_meter_logged = False
        self._audio_monitor_started_ts = time.time()
        self._last_game_loud_ts = 0.0
        self._last_spotify_loud_ts = 0.0  # Reset Spotify loud timestamp
        self._last_game_pause_attempt_ts = 0.0
        self._spotify_audio_active = False
        self._last_spotify_peak = 0.0
        self._tried_playlist_uris = []  # Reset tried playlists for this game session
        self._spotify_audio_status_logged = False
        # Clear stale pause state from the previous game session.
        self._paused_by_game_flag = False
        self._manual_paused = False
        self._user_paused_flag = False
        if getattr(self, "_pause_stack", None):
            self._pause_stack.clear()
        proc_name = info.get("proc", "")
        backend = "process-loopback" if HAS_PROCESS_LOOPBACK else (
            "loopback+pycaw" if HAS_PYAUDIO_WP else "pycaw only"
        )
        self.root.after(0, lambda: self._log("Audio monitor active"))
        # Force audio monitor to listen to Spotify desktop (not browser)
        try:
            from core.audio_monitor import set_browser_audio_only, register_music_player_pids
            try:
                set_browser_audio_only(False)
            except Exception:
                pass
            try:
                register_music_player_pids([])
            except Exception:
                pass
            self.root.after(0, lambda: self._log("Audio monitor: forced to Spotify desktop audio for game session"))
        except Exception:
            pass

        def _loop():
            TICK_SEC   = 0.5          # check twice per second

            _both_silent_since = 0.0   # timestamp when both first went quiet
            _prev_spotify_loud = True
            _prev_game_loud    = True
            _notifier_up       = False  # tracks whether the notifier overlay is visible

            try:
                while self._audio_monitor_running and self.current_game:
                    now = time.time()

                    # ── Update game audio detector ────────────────────────
                    if not self._game_pid:
                        self._game_pid = get_pid_for_proc(proc_name)
                    spotify_paused_for_meter = bool(
                        getattr(self, "_paused_by_game_flag", False)
                        or getattr(self, "_manual_paused", False)
                        or getattr(self, "_user_paused_flag", False)
                    )
                    self._game_audio.update(self._game_pid or 0, proc_name,
                                            spotify_paused=spotify_paused_for_meter)

                    # ── Sample audio ──────────────────────────────────────
                    try:
                        from core.audio_monitor import get_spotify_loopback_peak
                        spotify_peak, _spotify_db, spotify_status = get_spotify_loopback_peak()
                        if spotify_status == "ok":
                            if spotify_peak > SPOTIFY_UI_AUDIO_ON_THRESHOLD:
                                spotify_loud = True
                            elif spotify_peak <= SPOTIFY_UI_AUDIO_OFF_THRESHOLD:
                                spotify_loud = False
                            else:
                                spotify_loud = bool(getattr(self, "_spotify_audio_active", False))
                        else:
                            spotify_loud = False
                    except Exception:
                        spotify_peak = 0.0
                        spotify_loud = False

                    game_loud = self._game_audio.is_loud

                    # ── Update shared timestamps (used elsewhere in app) ──
                    if spotify_loud:
                        self._last_spotify_loud_ts = now
                        intentional_pause = bool(
                            getattr(self, "_manual_paused", False)
                            or getattr(self, "_user_paused_flag", False)
                            or getattr(self, "_paused_by_game_flag", False)
                        )
                        if not intentional_pause:
                            self._is_playing = True
                            self.root.after(0, lambda: self._set_play_btn_icon(True))
                            self._remove_pause_reason("user")
                            self._remove_pause_reason("auto")
                    if game_loud:
                        self._last_game_loud_ts = now
                    if spotify_loud or game_loud:
                        self._restore_playlist_end_prompt_delay_after_audio()

                    auto_pause_allowed = (
                        bool(self.spotify)
                        and bool(self.auto_mode.get())
                        and not self._seamless_music_enabled()
                        and bool(getattr(self, "_spotify_started_by_us", False))
                        and not bool(getattr(self, "_manual_paused", False))
                        and not bool(getattr(self, "_user_paused_flag", False))
                    )
                    if self._seamless_music_enabled() and self._paused_by_game_flag:
                        self._resume_spotify_after_game_quiet()
                    elif auto_pause_allowed and game_loud:
                        last_pause_try = float(getattr(self, "_last_game_pause_attempt_ts", 0.0) or 0.0)
                        if now - last_pause_try >= 1.0:
                            self._last_game_pause_attempt_ts = now
                            self._pause_spotify_for_game_audio(self._game_audio.current_peak)
                    elif self._paused_by_game_flag and not game_loud:
                        last_game_loud = self._last_game_loud_ts or now
                        if now - last_game_loud >= self._resume_delay_seconds():
                            self._resume_spotify_after_game_quiet()

                    # ── Transition logs ───────────────────────────────────
                    if spotify_loud and not _prev_spotify_loud:
                        self.root.after(0, lambda p=spotify_peak: self._log(
                            f"Spotify audio resumed (peak={p:.4f})"))
                    elif not spotify_loud and _prev_spotify_loud:
                        self.root.after(0, lambda: self._log(
                            "Spotify audio silent — watching for playlist end"))

                    if game_loud and not _prev_game_loud:
                        self.root.after(0, lambda: self._log("Game audio resumed"))
                    elif not game_loud and _prev_game_loud:
                        self.root.after(0, lambda: self._log("Game audio silent"))

                    _prev_spotify_loud = spotify_loud
                    _prev_game_loud    = game_loud

                    self.root.after(
                        0,
                        lambda active=spotify_loud, peak=spotify_peak:
                            self._sync_play_btn_to_spotify_audio(active, peak),
                    )
                    self.root.after(0, self._set_puppy_singing_visible, spotify_loud)
                    if spotify_loud and (
                        self._mascot_notifier is not None
                        or self._playlist_end_pending
                    ):
                        _both_silent_since = 0.0
                        _notifier_up = False
                        self.root.after(0, self._hide_mascot_notifier_for_spotify_audio)

                    # ── Core logic: both silent → notifier ────────────────
                    if self._intentional_pause_active():
                        _both_silent_since = 0.0
                        self._playlist_end_pending = False
                        mn = self._mascot_notifier
                        if mn is not None:
                            self._mascot_notifier = None
                            self.root.after(0, mn.close)
                        time.sleep(TICK_SEC)
                        continue

                    both_silent = not spotify_loud and not game_loud

                    if both_silent:
                        if not _both_silent_since:
                            _both_silent_since = now
                        silent_for = now - _both_silent_since

                        end_delay = self._playlist_end_delay_seconds()

                        if (
                            silent_for >= end_delay
                            and self._playlist_end_prompt_allowed(now)
                            and self._mascot_notifier is None
                            and not self._playlist_end_pending
                        ):
                            self._playlist_end_pending = True
                            _notifier_up = True
                            _sf = silent_for
                            self.root.after(0, lambda s=_sf: (
                                self._set_puppy_singing_visible(False),
                                self._log(f"Both silent {s:.1f}s >= {end_delay}s — showing notifier"),
                                self._show_mascot_prompt("Playlist ended — pick next?"),
                            ))
                    else:
                        # Sound detected — reset silence timer
                        _both_silent_since = 0.0
                        # If notifier was shown and sound came back, hide it
                        if _notifier_up:
                            _notifier_up = False
                            self._playlist_end_pending = False
                            mn = self._mascot_notifier
                            if mn is not None:
                                self._mascot_notifier = None
                                self.root.after(0, mn.close)

                    time.sleep(TICK_SEC)

            finally:
                # Restore audio monitor preference after game session ends
                try:
                    from core.audio_monitor import set_browser_audio_only
                    try:
                        if hasattr(self, "spotify") and getattr(self, "spotify", None) is not None:
                            set_browser_audio_only(self.spotify._uses_browser_player())
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    self.root.after(0, self._set_puppy_singing_visible, False)
                except Exception:
                    pass
                _clear_spotify_mixer_mute()

        threading.Thread(target=_loop, daemon=True).start()

    def _set_puppy_singing_visible(self, visible: bool):
        overlay = getattr(self, "_puppy_singing_overlay", None)
        if overlay is None:
            return
        try:
            if visible and self.current_game and self._mascot_notifier is None:
                overlay.show()
            else:
                overlay.hide()
        except Exception:
            pass

    def _hide_mascot_notifier_for_spotify_audio(self):
        mn = getattr(self, "_mascot_notifier", None)
        self._mascot_notifier = None
        self._playlist_end_pending = False
        self._music_missing_since = 0.0
        if mn is not None:
            try:
                mn.close()
            except Exception as ex:
                try:
                    self._log(f"Error hiding MascotNotifier after Spotify audio returned: {ex}")
                except Exception:
                    pass

    def _clear_spotify_game_pause_claim(self):
        try:
            if self.spotify and hasattr(self.spotify, "_paused_by_game"):
                self.spotify._paused_by_game = False
        except Exception:
            pass
        try:
            desktop = getattr(self.spotify, "_desktop_player", None) if self.spotify else None
            if desktop and hasattr(desktop, "_paused_by_game"):
                desktop._paused_by_game = False
        except Exception:
            pass

    def _pause_started_playlist_if_game_loud(self):
        if not self.spotify or not self.current_game:
            return
        if self._seamless_music_enabled():
            return
        if self._manual_paused or self._user_paused_flag:
            return
        game_audio = getattr(self, "_game_audio", None)
        game_loud = bool(game_audio and getattr(game_audio, "is_loud", False))
        if not game_loud:
            try:
                last_loud = float(getattr(self, "_last_game_loud_ts", 0.0) or 0.0)
                game_loud = last_loud > 0.0 and time.time() - last_loud <= 2.0
            except Exception:
                game_loud = False
        if not game_loud:
            return
        peak = float(getattr(game_audio, "current_peak", 0.0) or 0.0)
        threading.Thread(
            target=lambda: self._pause_spotify_for_game_audio(peak),
            daemon=True,
        ).start()

    def _pause_spotify_for_game_audio(self, peak: float = 0.0):
        if not self.spotify:
            return
        if self._seamless_music_enabled():
            return
        if self._manual_paused or self._user_paused_flag:
            return
        already_paused_by_game = bool(getattr(self, "_paused_by_game_flag", False))
        self._clear_spotify_game_pause_claim()

        ok = False
        try:
            if hasattr(self.spotify, "ensure_paused"):
                ok = bool(self.spotify.ensure_paused())
            else:
                ok = bool(self.spotify.media_stop())
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Game-audio pause failed: {e}"))

        if ok:
            self._paused_by_game_flag = True
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            self._add_pause_reason("auto")
            self._is_playing = False
            if already_paused_by_game:
                self.root.after(0, lambda: (
                    self._set_play_btn_icon(False, force_btn=True),
                    self._set_puppy_singing_visible(False),
                ))
            else:
                self.root.after(0, lambda p=peak: (
                    self._set_play_btn_icon(False, force_btn=True),
                    self._set_puppy_singing_visible(False),
                    self._log(f"Game audio detected - paused Spotify (peak={p:.4f})"),
                ))
        else:
            self._paused_by_game_flag = False
            self._clear_spotify_game_pause_claim()
            self._remove_pause_reason("auto")
            self.root.after(0, lambda: self._log("Game audio detected, but Spotify pause did not confirm."))

    def _resume_spotify_after_game_quiet(self):
        if not self.spotify or not self._paused_by_game_flag:
            return
        if self._manual_paused or self._user_paused_flag:
            return

        # Check if Spotify is ALREADY loud. If so, don't risk a toggle inversion.
        try:
            from core.audio_monitor import get_spotify_loopback_peak, SPOTIFY_LOOPBACK_LOUD
            s_peak, _, s_status = get_spotify_loopback_peak()
            if s_status == "ok" and s_peak >= SPOTIFY_LOOPBACK_LOUD:
                # Spotify is already playing. Mark it resumed and skip command.
                self._paused_by_game_flag = False
                self._remove_pause_reason("auto")
                self._is_playing = True
                self._music_missing_since = 0.0
                self._last_spotify_loud_ts = time.time()
                self.root.after(0, lambda: self._set_play_btn_icon(True, force_btn=True))
                return
        except Exception:
            pass

        ok = False
        try:
            if hasattr(self.spotify, "ensure_playing"):
                ok = bool(self.spotify.ensure_playing())
            elif hasattr(self.spotify, "resume"):
                ok = bool(self.spotify.resume())
            else:
                ok = bool(self.spotify.media_play_pause())
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Game-audio resume failed: {e}"))

        if ok:
            self._paused_by_game_flag = False
            self._remove_pause_reason("auto")
            self._is_playing = True
            self._music_missing_since = 0.0
            self._last_spotify_loud_ts = time.time()
            self.root.after(0, lambda: (
                self._set_play_btn_icon(True, force_btn=True),
                self._log("Game audio quiet - resumed Spotify"),
            ))

    def _stop_audio_monitor(self):
        self._audio_monitor_running = False
        if self._game_audio is not None:
            try:
                self._game_audio.shutdown()
            except Exception:
                pass
        # Restore audio monitor browser preference when monitor stops
        try:
            from core.audio_monitor import set_browser_audio_only
            try:
                if hasattr(self, "spotify") and getattr(self, "spotify", None) is not None:
                    set_browser_audio_only(self.spotify._uses_browser_player())
            except Exception:
                pass
        except Exception:
            pass
        _clear_spotify_mixer_mute()
        # Close the notifier if the game stopped while it was visible
        if self._mascot_notifier is not None:
            self._mascot_notifier.close()
            self._mascot_notifier = None
        self._set_puppy_singing_visible(False)

    # ── PLAYLISTS ─────────────────────────────────────────────────────────────

    def _remember_current_playlist(self, uri="", name="", query=""):
        if uri and str(uri).startswith("spotify:playlist:"):
            self._current_playlist_uri = uri
        if name:
            self._current_playlist_name = name
        if query:
            self._current_playlist_query = query
        self._manual_paused = False
        self._user_paused_flag = False
        if getattr(self, "_pause_stack", None):
            self._pause_stack.clear()
        self._playlist_end_pending = False
        # Only reset silence tracking if there's no active deferred cooldown
        # (block/try-another sets until_audio=True and we must preserve that)
        if not getattr(self, "_playlist_end_extra_until_audio", False):
            self._music_missing_since = 0.0
            self._last_spotify_loud_ts = time.time()  # Assume Spotify is loud when starting
        else:
            self._music_missing_since = 0.0
        self.root.after(0, lambda: (
            self.playlist_display_lbl.configure(text=f"Playlist: {self._current_playlist_name or '\u2014'}"),
            self.track_lbl.configure(text=self._current_playlist_name or "Spotify Playlist"),
        ))
        try:
            self._log(f"_remember_current_playlist: uri={uri}, name={name}, cleared pause flags: manual={self._manual_paused}, user_paused={self._user_paused_flag}, pause_stack_cleared={not bool(getattr(self,'_pause_stack',None))}")
        except Exception:
            pass
        try:
            old = bool(getattr(self, "_paused_by_game_flag", False))
            if old:
                self._paused_by_game_flag = False
                pass  # Starting new playlist
            else:
                self._paused_by_game_flag = False
        except Exception:
            pass

    def _blocked_playlist_uris(self):
        try:
            from core.playlist_search import load_blocked_playlist_uris
            return load_blocked_playlist_uris(BASE_DIR)
        except Exception:
            return set()

    def _skip_playlist_uris(self, extra_uris=None):
        uris = set(extra_uris or [])
        try:
            uris.update(self._blocked_playlist_uris())
        except Exception:
            pass
        return {u for u in uris if u}

    def _spotify_sound_detected_recently(self, seconds: float = 10.0) -> bool:
        try:
            last_loud = float(getattr(self, "_last_spotify_loud_ts", 0.0) or 0.0)
            return last_loud > 0 and (time.time() - last_loud) <= float(seconds)
        except Exception:
            return False

    def _playlist_end_extra_seconds(self) -> float:
        try:
            extra = float(getattr(self, "_playlist_end_extra_silence_sec", PLAYLIST_END_NORMAL_EXTRA_SEC) or PLAYLIST_END_NORMAL_EXTRA_SEC)
        except Exception:
            extra = PLAYLIST_END_NORMAL_EXTRA_SEC
        return max(0.0, extra)

    def _playlist_end_delay_seconds(self) -> float:
        return float(self._resume_delay_seconds()) + self._playlist_end_extra_seconds()

    def _playlist_end_prompt_allowed(self, now: float = None) -> bool:
        try:
            not_before = float(getattr(self, "_playlist_end_prompt_not_before", 0.0) or 0.0)
        except Exception:
            not_before = 0.0
        return not not_before or float(now if now is not None else time.time()) >= not_before

    def _defer_playlist_end_prompt(self, extra_seconds: float = None, until_audio: bool = False, reason: str = ""):
        extra = PLAYLIST_END_NORMAL_EXTRA_SEC if extra_seconds is None else float(extra_seconds)
        delay = float(self._resume_delay_seconds()) + max(0.0, extra)
        self._playlist_end_extra_silence_sec = max(0.0, extra)
        self._playlist_end_extra_until_audio = bool(until_audio)
        self._playlist_end_prompt_not_before = time.time() + delay
        self._playlist_end_pending = False
        self._music_missing_since = 0.0
        mn = getattr(self, "_mascot_notifier", None)
        if mn is not None:
            self._mascot_notifier = None
            try:
                self.root.after(0, mn.close)
            except Exception:
                pass
        try:
            label = reason or "Playlist-end notifier deferred"
            self._log(f"{label}: waiting {delay:.1f}s of silence before prompting.")
        except Exception:
            pass

    def _restore_playlist_end_prompt_delay_after_audio(self):
        if not bool(getattr(self, "_playlist_end_extra_until_audio", False)):
            return
        self._playlist_end_extra_until_audio = False
        self._playlist_end_extra_silence_sec = PLAYLIST_END_NORMAL_EXTRA_SEC
        # Do NOT reset _playlist_end_prompt_not_before here — the silence
        # timer (_both_silent_since) already restarts when audio is detected,
        # and clearing the timestamp guard would let the notifier fire
        # prematurely during playlist transitions (e.g. block → pick new).
        try:
            pass
        except Exception:
            pass

    def _clear_user_pause_for_resume(self):
        self._manual_paused = False
        self._user_paused_flag = False
        self._paused_by_game_flag = False
        self._remove_pause_reason("user")
        self._remove_pause_reason("auto")
        self._playlist_end_pending = False
        self._music_missing_since = 0.0
        self._playlist_end_extra_silence_sec = PLAYLIST_END_NORMAL_EXTRA_SEC
        self._playlist_end_extra_until_audio = False
        self._playlist_end_prompt_not_before = time.time() + self._playlist_end_delay_seconds()

    def _add_pause_reason(self, reason: str):
        try:
            stack = list(getattr(self, "_pause_stack", None) or [])
            if not any(item[0] == reason for item in stack):
                stack.append((reason, time.time()))
            self._pause_stack = stack
        except Exception:
            pass

    def _remove_pause_reason(self, reason: str):
        try:
            self._pause_stack = [
                item for item in (getattr(self, "_pause_stack", None) or [])
                if item[0] != reason
            ]
        except Exception:
            pass

    def _intentional_pause_active(self) -> bool:
        paused_by_game = bool(getattr(self, "_paused_by_game_flag", False))
        try:
            if self.spotify:
                paused_by_game = paused_by_game or bool(
                    getattr(self.spotify, "paused_by_game", getattr(self.spotify, "_paused_by_game", False))
                )
        except Exception:
            pass
        try:
            stack_active = bool(getattr(self, "_pause_stack", None))
        except Exception:
            stack_active = False
        return bool(
            paused_by_game
            or getattr(self, "_manual_paused", False)
            or getattr(self, "_user_paused_flag", False)
            or stack_active
        )

    def _blocked_playlists(self):
        try:
            from core.playlist_search import load_blocked_playlists
            return load_blocked_playlists(BASE_DIR)
        except Exception:
            return []

    def _block_current_playlist(self):
        # ── Capture state on the calling thread before any async work ────────
        uri   = self._current_playlist_uri
        name  = self._current_playlist_name or "Current playlist"
        query = self._current_playlist_query

        if not uri:
            self._log("No current playlist to block yet.")
            return

        # Defer notifier IMMEDIATELY (before background thread) so the monitor
        # loop cannot show the notifier during disk I/O.
        self._defer_playlist_end_prompt(
            extra_seconds=20.0, until_audio=True,
            reason="Blocked playlist — extending notifier cooldown",
        )

        def _go():
            # ── Step 1: Write to disk using app's reliable URI directly ──────
            # We bypass spotify.block_current_playlist() intentionally — it
            # relies on self._last_uri which can be stale.  The app always
            # maintains the authoritative URI in self._current_playlist_uri.
            try:
                from core.playlist_search import block_playlist_uri
                ok = block_playlist_uri(BASE_DIR, uri, name, query)
            except Exception as ex:
                ok = False
                self.root.after(0, lambda: self._log(f"Block write failed: {ex}"))

            if not ok:
                self.root.after(0, lambda: self._log("Could not save block — check file permissions."))
                return

            # ── Step 2: Sync desktop controller's internal state ─────────────
            # Keeps _last_uri consistent so block_current_playlist() on the
            # controller would also find the right URI if called elsewhere.
            if self._is_desktop_mode() and self.spotify:
                try:
                    self.spotify._last_uri = uri
                    # Clear session lock so next pick always fetches a fresh playlist
                    self.spotify._session_locked = False
                except Exception:
                    pass

            # ── Step 3: Bust the search cache for this query ─────────────────
            # Without this, the same blocked playlist can come back from the
            # cached result list on the next search.
            if query:
                try:
                    from core.playlist_search import clear_playlist_cache_for_query
                    clear_playlist_cache_for_query(BASE_DIR, query)
                except Exception:
                    pass

            # ── Step 4: Track as tried so session cycling also skips it ──────
            if uri not in self._tried_playlist_uris:
                self._tried_playlist_uris.append(uri)


            if self.current_game and self.auto_mode.get():
                # _play_query_for_game with force_new=True handles the Spotify restart internally
                # Reuse existing connection when possible; do not force a restart.
                self._play_query_for_game(
                    self.current_game,
                    force_new=False,
                    exclude_uris=set(self._tried_playlist_uris),
                    reason="Blocked \u2014 picking another",
                )
            elif self.spotify:
                # No game running — just stop
                threading.Thread(target=self.spotify.media_stop, daemon=True).start()

        threading.Thread(target=_go, daemon=True).start()

    def _try_another_playlist(self):
        if not self.current_game:
            self._log("Start a saved game first, then GameBeats can pick another playlist.")
            return
        
        # Track tried playlist
        if self._current_playlist_uri:
            if self._current_playlist_uri not in self._tried_playlist_uris:
                self._tried_playlist_uris.append(self._current_playlist_uri)
        
        # In desktop mode, restart Spotify to ensure a fresh session when picking another playlist.
        # Defer notifier: wait end_cycle + 10s before showing it again
        self._defer_playlist_end_prompt(
            extra_seconds=20.0, until_audio=True,
            reason="Try another — extending notifier cooldown",
        )

        def _pick():
            try:
                # Prefer reusing the established Spotify connection/device.
                self._play_query_for_game(
                    self.current_game,
                    force_new=False,
                    exclude_uris=set(self._tried_playlist_uris),  # Exclude all tried playlists
                    reason="Picking another playlist",
                )
            except Exception as ex:
                self._log(f"Try-another failed: {ex}")

        threading.Thread(target=_pick, daemon=True).start()

    def _unblock_playlist(self, uri):
        try:
            from core.playlist_search import unblock_playlist_uri
            ok = unblock_playlist_uri(BASE_DIR, uri)
        except Exception:
            ok = False
        if ok:
            self._load_playlists()
            self._log("Playlist unblocked.")
        else:
            self._log("Could not unblock playlist.")

    def _add_playlist_link(self):
        if not self._is_desktop_mode():
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Add playlist")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        w, h = 420, 220
        dlg.geometry(f"{w}x{h}+{(self.root.winfo_x() + 20)}+{(self.root.winfo_y() + 120)}")
        # Top accent bar
        tk.Frame(dlg, bg=ACCENT, height=2).pack(fill=tk.X)
        tk.Label(dlg, text="Add playlist link",
                 bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(pady=(18, 10))
        name_var = tk.StringVar(value="My playlist")
        link_var = tk.StringVar()
        for lbl, var, show in [("Name", name_var, ""), ("Link", link_var, "")]:
            row_f = tk.Frame(dlg, bg=BG)
            row_f.pack(fill=tk.X, padx=22, pady=(0, 4))
            tk.Label(row_f, text=lbl, bg=BG, fg=TEXT_MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor=tk.W)
            tk.Entry(row_f, textvariable=var, bg=SURFACE2, fg=TEXT,
                     insertbackground=ACCENT, relief=tk.FLAT,
                     font=("Segoe UI", 10)).pack(fill=tk.X, pady=(3, 0), ipady=6)
        tk.Label(dlg, text="Right-click playlist in Spotify \u2192 Share \u2192 Copy link",
                 bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 8)).pack(padx=22, anchor=tk.W)
        err_lbl = tk.Label(dlg, text="", bg=BG, fg=AMBER, font=("Segoe UI", 9))
        err_lbl.pack(pady=(4, 0))

        def save():
            ok, err = self.spotify.add_playlist_link(
                name_var.get(), link_var.get())
            if ok:
                dlg.destroy()
                self._load_playlists()
                self._log(f"Playlist added: {name_var.get()}")
            else:
                err_lbl.configure(text=err)

        brow = tk.Frame(dlg, bg=BG)
        brow.pack(pady=12)
        RoundedButton(brow, text="Cancel", command=dlg.destroy,
                       width=80, height=30, bg=SURFACE2, fg=TEXT_SEC,
                       font_size=10, canvas_bg=BG).pack(side=tk.LEFT, padx=4)
        RoundedButton(brow, text="Add", command=save,
                       width=80, height=30, bg=ACCENT, fg="#000",
                       font_size=10, canvas_bg=BG).pack(side=tk.LEFT, padx=4)

    def _load_playlists(self):
        if not self.spotify:
            self.pl_status_lbl.configure(
                text="Enable playback in Settings.", text_color=TEXT_MUTED)
            return
        if self._is_desktop_mode():
            self.pl_status_lbl.configure(
                text="Your saved playlist links:", text_color=TEXT_SEC)
        else:
            self.pl_status_lbl.configure(text="Loading playlists…", text_color=TEXT_SEC)
        def _fetch():
            pls, err = self.spotify.get_user_playlists()
            self.root.after(0, lambda: self._render_playlists(pls, err))
        threading.Thread(target=_fetch, daemon=True).start()

    def _render_playlists(self, pls, err=""):
        for w in self.pl_inner.winfo_children():
            w.destroy()
        blocked = self._blocked_playlists()
        if err:
            short = err if len(err) <= 120 else err[:117] + "\u2026"
            self.pl_status_lbl.configure(text=f"\u26a0  {short}", text_color=AMBER, wraplength=400)
            if "premium" in err.lower() and not self._is_desktop_mode():
                self._log("Tip: enable Free desktop mode in Settings (no Premium).")
            return
        if not pls:
            if self._is_desktop_mode():
                self.pl_status_lbl.configure(
                    text="No playlists yet \u2014 click + Add link above.", text_color=TEXT_MUTED)
            else:
                self.pl_status_lbl.configure(
                    text="No playlists found on this account.", text_color=TEXT_MUTED)
            self._render_blocked_playlists(blocked)
            return
        self.pl_status_lbl.configure(text=f"{len(pls)} playlist{'s' if len(pls) != 1 else ''}", text_color=TEXT_SEC)
        for pl in pls[:30]:
            row = ctk.CTkFrame(self.pl_inner, fg_color=SURFACE, corner_radius=8, cursor="hand2")
            row.pack(fill=tk.X, pady=2)

            # Music note icon — compact pill
            note_c = ctk.CTkFrame(row, width=40, height=40, fg_color=SURFACE3, corner_radius=20)
            note_c.pack(side=tk.LEFT, padx=(8, 4))
            note_c.pack_propagate(False)
            ctk.CTkLabel(note_c, text="\u266B", fg_color="transparent", text_color=ACCENT,
                         font=ctk.CTkFont(family="Segoe UI", size=12)).pack(expand=True)

            col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=12, padx=(4, 0))
            
            ctk.CTkLabel(col, text=pl["name"], fg_color="transparent", text_color=TEXT,
                         font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), anchor="w").pack(anchor="w")
            
            ctk.CTkLabel(col, text=f"{pl['tracks']} tracks", fg_color="transparent", text_color=TEXT_MUTED,
                         font=ctk.CTkFont(family="Segoe UI", size=8), anchor="w").pack(anchor="w", pady=(1, 0))

            arrow = ctk.CTkLabel(row, text="\u25B6", fg_color="transparent", text_color=TEXT_MUTED,
                                 font=ctk.CTkFont(family="Segoe UI", size=10), padx=16)
            arrow.pack(side=tk.RIGHT)

            def _set_row_bg(r, color):
                r.configure(fg_color=color)

            all_widgets = row.winfo_children() + [row]
            for widget in all_widgets:
                widget.bind("<Button-1>",
                    lambda e, u=pl["uri"], n=pl["name"]: self._play_pl(u, n))
                widget.bind("<Enter>", lambda e, r=row: _set_row_bg(r, SURFACE2))
                widget.bind("<Leave>", lambda e, r=row: _set_row_bg(r, SURFACE))

            if self._is_desktop_mode():
                del_l = ctk.CTkLabel(row, text="\u2715", fg_color="transparent", text_color=TEXT_MUTED,
                                     font=ctk.CTkFont(family="Segoe UI", size=11), padx=10, cursor="hand2")
                del_l.pack(side=tk.RIGHT)
                del_l.bind("<Button-1>",
                    lambda e, u=pl["uri"]: self._remove_saved_pl(u))

        self._render_blocked_playlists(blocked)

    def _render_blocked_playlists(self, blocked):
        if not blocked:
            return
        ctk.CTkLabel(
            self.pl_inner, text="BLOCKED PLAYLISTS",
            fg_color="transparent", text_color=TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=8, weight="bold"),
        ).pack(anchor=tk.W, padx=2, pady=(16, 4))
        for item in blocked:
            uri  = item.get("uri", "")
            name = item.get("name") or uri.split(":")[-1] or "Blocked playlist"
            query = item.get("query", "")
            row = ctk.CTkFrame(self.pl_inner, fg_color=SURFACE2, corner_radius=8)
            row.pack(fill=tk.X, pady=2)

            badge = ctk.CTkFrame(row, fg_color="#3A1A10", width=40, height=40, corner_radius=20)
            badge.pack(side=tk.LEFT, padx=(8, 4))
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text="\u2205", fg_color="transparent", text_color=AMBER,
                         font=ctk.CTkFont(family="Segoe UI", size=13)).pack(expand=True)

            col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=8)

            ctk.CTkLabel(col, text=name, fg_color="transparent", text_color=TEXT,
                         font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), anchor="w").pack(anchor="w")

            detail = (query or uri)[:52]
            ctk.CTkLabel(col, text=detail, fg_color="transparent", text_color=TEXT_MUTED,
                         font=ctk.CTkFont(family="Segoe UI", size=8), anchor="w").pack(anchor="w")

            ctk.CTkButton(
                row, text="Unblock",
                fg_color="transparent", text_color=ACCENT, hover_color=SURFACE3,
                font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                width=72, height=28, corner_radius=RADIUS_SM,
                command=lambda u=uri: self._unblock_playlist(u),
            ).pack(side=tk.RIGHT, padx=(0, 10), pady=8)

    def _remove_saved_pl(self, uri):
        if self._is_desktop_mode():
            self.spotify.remove_playlist_link(uri)
            self._load_playlists()
            self._log("Playlist removed.")

    def _play_pl(self, uri, name):
        if not self.spotify:
            return
        if uri in self._blocked_playlist_uris():
            self._log("Blocked playlist skipped.")
            return
        def _go():
            try:
                # Ensure fresh desktop session to avoid Spotify resuming old queue
                if self._is_web_mode() and self.spotify:
                    self._log("Web player: starting saved playlist…")
                    self.spotify.ensure_active_device()
                elif self.spotify:
                    self.spotify.ensure_active_device()

                ok = False
                try:
                    ok = bool(self.spotify.play_playlist(uri))
                except Exception:
                    ok = False

                if ok:
                    # Verify playback actually started (audio/local status)
                    verified = False
                    try:
                        self._show_verifying(True)
                    except Exception:
                        pass
                    try:
                        if self._is_desktop_mode() and self.spotify:
                            verified = self.spotify._verify_playback(expected_playlist_uri=uri, timeout=6.0)
                    except Exception:
                        verified = False

                    if verified:
                        self._manual_paused = False
                        self.root.after(0, lambda: (
                            self._remember_current_playlist(uri, name, "saved playlist"),
                            self._log(f"▶ Playing: {name}"),
                        ))
                        try:
                            self._show_verifying(False)
                        except Exception:
                            pass
                        return

                # Fallback / failure
                self.root.after(0, lambda: self._log(
                    "⚠ Playback failed or verification failed — open Spotify and retry."))
            except Exception as ex:
                self.root.after(0, lambda: self._log(f"Play failed: {ex}"))
        threading.Thread(target=_go, daemon=True).start()

    # ── CONTROLS ──────────────────────────────────────────────────────────────

    def _start_play_btn_pulse(self):
        if not hasattr(self, "_pulse_job") or self._pulse_job is None:
            self._pulse_active = True
            self._pulse_loop(0)

    def _pulse_loop(self, step):
        if not getattr(self, "_pulse_active", False) or self._closing:
            if hasattr(self, "play_btn"):
                self.play_btn.configure(fg_color=ACCENT)
            self._pulse_job = None
            return
        colors = [ACCENT, "#8b5cf6", ACCENT2, "#a78bfa"]
        col = colors[step % len(colors)]
        if hasattr(self, "play_btn"):
            self.play_btn.configure(fg_color=col)
        self._pulse_job = self.root.after(450, lambda: self._pulse_loop(step + 1))

    def _set_play_btn_icon(self, playing: bool, force_btn: bool = False):
        """Update internal playing state. Only updates the visible button
        icon when force_btn=True (i.e. user-initiated toggle)."""
        self._is_playing = bool(playing)
        if playing:
            self._start_play_btn_pulse()
        else:
            self._pulse_active = False
        if force_btn and hasattr(self, "play_btn"):
            self.play_btn.update_text("\u23F8" if playing else "\u25B6")
        try:
            overlay = getattr(self, "_control_overlay", None)
            if overlay and overlay.is_visible():
                overlay.update_status(playing=bool(playing))
        except Exception:
            pass

    def _sync_play_btn_to_spotify_audio(self, audio_active: bool, peak: float = 0.0):
        """Track Spotify audio state internally — does NOT touch the button icon."""
        self._spotify_audio_active = bool(audio_active)
        try:
            self._last_spotify_peak = float(peak)
        except Exception:
            self._last_spotify_peak = 0.0
        self._is_playing = bool(audio_active)
        if audio_active:
            self._start_play_btn_pulse()
        else:
            self._pulse_active = False

    def _read_spotify_is_playing(self):
        """Best-effort read of Spotify's real play state."""
        if not self.spotify:
            return None
        for method_name in ("get_playback_state", "get_current_track"):
            try:
                method = getattr(self.spotify, method_name, None)
                if not callable(method):
                    continue
                data = method()
                if not isinstance(data, dict):
                    continue
                if "is_playing" in data:
                    return bool(data.get("is_playing"))
                if "playing" in data:
                    return bool(data.get("playing"))
                if "paused" in data:
                    return not bool(data.get("paused"))
            except Exception:
                continue
        return None

    def _spotify_is_playing_for_toggle(self) -> bool:
        """Resolve clicks from Spotify/audio state instead of stale UI state."""
        if (
            getattr(self, "_manual_paused", False)
            or getattr(self, "_user_paused_flag", False)
            or getattr(self, "_paused_by_game_flag", False)
        ):
            return False
        if self._spotify_sound_detected_recently(1.5):
            return True
        state = self._read_spotify_is_playing()
        if state is not None:
            return bool(state)
        return bool(getattr(self, "_is_playing", False))

    def _send_spotify_pause_command(self) -> bool:
        if not self.spotify:
            return False
        if hasattr(self.spotify, "_media_pause"):
            return bool(self.spotify._media_pause())
        if hasattr(self.spotify, "ensure_paused"):
            return bool(self.spotify.ensure_paused())
        if hasattr(self.spotify, "pause"):
            return bool(self.spotify.pause())
        if hasattr(self.spotify, "media_stop"):
            return bool(self.spotify.media_stop())
        return False

    def _send_spotify_resume_command(self) -> bool:
        if not self.spotify:
            return False
        if hasattr(self.spotify, "_media_play"):
            return bool(self.spotify._media_play())
        if hasattr(self.spotify, "ensure_playing"):
            return bool(self.spotify.ensure_playing())
        if hasattr(self.spotify, "resume"):
            return bool(self.spotify.resume())
        if hasattr(self.spotify, "play"):
            return bool(self.spotify.play())
        if hasattr(self.spotify, "media_play_pause"):
            return bool(self.spotify.media_play_pause())
        return False

    def _apply_user_pause_state(self, paused: bool):
        self._user_toggle_ts = time.time()
        if paused:
            self._manual_paused = True
            self._user_paused_flag = True
            self._add_pause_reason("user")
        else:
            self._manual_paused = False
            self._user_paused_flag = False
            self._paused_by_game_flag = False
            self._remove_pause_reason("user")
            self._remove_pause_reason("auto")
            self._playlist_end_pending = False
            self._music_missing_since = 0.0

    def _pause(self):
        """Pause Spotify (called from overlay / keyboard shortcut)."""
        if not self.spotify:
            return
        self._apply_user_pause_state(True)
        def _do_pause():
            try:
                ok = self._send_spotify_pause_command()
            except Exception:
                ok = False
            if not ok:
                self.root.after(0, lambda: self._log("Spotify pause did not confirm."))
        threading.Thread(target=_do_pause, daemon=True).start()

    def _play(self):
        """Resume Spotify (called from overlay / keyboard shortcut)."""
        if not self.spotify:
            return
        self._apply_user_pause_state(False)
        def go():
            try:
                ok = self._send_spotify_resume_command()
            except Exception:
                ok = False
            if not ok:
                self.root.after(0, lambda: self._log("Spotify resume did not confirm."))
        threading.Thread(target=go, daemon=True).start()

    def _play_pause_toggle(self):
        """Single-button toggle: pause if playing, play if paused."""
        if not self.spotify or self._play_pause_busy:
            return
        self._play_pause_busy = True
        self._user_toggle_ts = time.time()

        def go():
            ok = False
            was_playing = self._spotify_is_playing_for_toggle()
            try:
                if was_playing:
                    self.root.after(0, lambda: self._apply_user_pause_state(True))
                    ok = self._send_spotify_pause_command()
                else:
                    self.root.after(0, lambda: self._apply_user_pause_state(False))
                    ok = self._send_spotify_resume_command()
            except Exception:
                ok = False

            def finish():
                self._play_pause_busy = False
                if ok:
                    # Only update the visible button icon on successful user toggle
                    self._set_play_btn_icon(not was_playing, force_btn=True)
                else:
                    self._log("Spotify play/pause command did not confirm.")

            self.root.after(0, finish)

        threading.Thread(target=go, daemon=True).start()
        return

    def _play_pause(self):
        """Legacy alias — routes to the toggle."""
        self._play_pause_toggle()

    def _next(self):
        if self.spotify:
            # If a game is running, prefer picking another playlist (overlay 'Next')
            if self.current_game:
                self._try_another_playlist()
                return
            threading.Thread(target=self.spotify.media_next, daemon=True).start()

    def _prev(self):
        if self.spotify:
            threading.Thread(target=self.spotify.media_prev, daemon=True).start()

    def _on_vol(self, val):
        v = int(float(val))
        self.vol_num.configure(text=f"{v}%")
        if self.spotify:
            threading.Thread(target=lambda: self.spotify.set_volume(v), daemon=True).start()

    # ── TRACK POLLING ─────────────────────────────────────────────────────────

    def _start_track_poll(self):
        self._poll()

    def _poll(self):
        if self.spotify:
            threading.Thread(target=self._fetch_track, daemon=True).start()
        self._track_job = self.root.after(4000, self._poll)

    def _fetch_track(self):
        try:
            track = self.spotify.get_current_track()
            if track:
                self.root.after(0, lambda: self._update_np(track))
            else:
                self.root.after(0, self._mark_music_missing)
        except:
            self.root.after(0, self._mark_music_missing)

    def _now_playing_playlist_title(self, track=None):
        track = track or {}
        for value in (
            getattr(self, "_current_playlist_name", ""),
            track.get("playlist_name", ""),
            track.get("context_name", ""),
        ):
            value = str(value or "").strip()
            if value:
                return value
        if getattr(self, "_current_playlist_uri", ""):
            return "Spotify Playlist"
        return str(track.get("name") or "Nothing playing")

    def _update_np(self, t):
        playlist_uri = t.get("playlist_uri") or t.get("context_uri")
        if (
            playlist_uri
            and str(playlist_uri).startswith("spotify:playlist:")
            and playlist_uri != self._current_playlist_uri
        ):
            # Only clear the name if this is a true manual switch (not during an app-triggered play)
            if not self._play_in_progress:
                self._remember_current_playlist(
                    playlist_uri,
                    "Spotify Playlist", # Fallback for manual switch
                    "" # Clear search query as it no longer applies
                )
            else:
                # Just sync the internal URI tracker without updating UI name
                self._current_playlist_uri = playlist_uri

        playlist_title = self._now_playing_playlist_title(t)
        self.track_lbl.configure(text=playlist_title)
        self.artist_lbl.configure(text="")
        self.artist_lbl.pack_forget()

        # Update the single toggle button: ⏸ when playing, ▶ when paused
        # But DON'T override the icon if the user just clicked the button
        # (give the Spotify command time to take effect before the poller
        # overwrites the state).
        user_toggle_age = time.time() - getattr(self, "_user_toggle_ts", 0.0)
        t_is_playing = bool(t.get("is_playing"))
        effective_is_playing = t_is_playing or bool(
            not self._intentional_pause_active()
            and self._spotify_sound_detected_recently(2.5)
        )
        if user_toggle_age > 3.0 and not getattr(self, "_audio_monitor_running", False):
            self._set_play_btn_icon(effective_is_playing)
            self._is_playing = effective_is_playing
        if effective_is_playing:
            self._last_music_seen_ts = time.time()
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
            if user_toggle_age > 3.0 or not (
                self._manual_paused or getattr(self, "_user_paused_flag", False)
            ):
                self._manual_paused = False  # Reset manual pause flag when music resumes
                self._user_paused_flag = False
                self._remove_pause_reason("user")
        else:
            self._mark_music_missing()

        if HAS_PIL and t.get("album_art"):
            threading.Thread(target=self._load_art, args=(t["album_art"],), daemon=True).start()

    def _should_handle_auto_stop(self):
        return (
            self._spotify_started_by_us
            and self.current_game
            and self.auto_mode.get()
            and not self._manual_paused
            and not self._play_in_progress
        )

    def _playback_paused_by_app_or_user(self) -> bool:
        """
        Return True if playback is currently paused by GameBeats or the user.
        This aggregates the controller state and the local flags we use for
        race-free decision making.
        
        CRITICAL: Only return True if we INTENTIONALLY paused playback.
        If Spotify is just naturally paused (track ended), return False so
        the playlist-ended overlay can appear.
        """
        paused_by_game = False
        try:
            if self.spotify:
                paused_by_game = bool(getattr(self.spotify, "paused_by_game", getattr(self.spotify, "_paused_by_game", False)))
        except Exception:
            paused_by_game = False
        paused_by_game = paused_by_game or bool(getattr(self, "_paused_by_game_flag", False))
        user_paused = bool(getattr(self, "_user_paused_flag", False))

        # IMPORTANT: Don't check Spotify's playback state here.
        # If Spotify is paused but paused_by_game is False, it means the track
        # ended naturally (not paused by us), so we should allow the overlay to show.
        # Only check intentional pause flags, not the actual playback state.

        # Check pause stack safely
        pause_stack_entries = False
        try:
            pause_stack_entries = bool(getattr(self, "_pause_stack", None) and len(self._pause_stack) > 0)
        except Exception:
            pause_stack_entries = False

        paused = bool(paused_by_game or self._manual_paused or user_paused or pause_stack_entries)
        if paused:
            try:
                self._log(
                    f"_playback_paused_by_app_or_user -> True: paused_by_game={paused_by_game}, manual={getattr(self,'_manual_paused',False)}, user_paused={user_paused}, pause_stack={pause_stack_entries}"
                )
            except Exception:
                pass
        return paused

    def _game_quiet_long_enough(self, delay):
        if not self._audio_monitor_running:
            return True
        now = time.time()
        last_loud = self._last_game_loud_ts or self._audio_monitor_started_ts or now
        return now - last_loud >= delay

    def _spotify_quiet_long_enough(self, delay):
        """Check if Spotify audio has been quiet for at least 'delay' seconds."""
        if not self._audio_monitor_running:
            return True
        now = time.time()
        # If we haven't detected Spotify being loud yet, treat it as quiet from start
        last_loud = self._last_spotify_loud_ts or self._audio_monitor_started_ts or now
        return now - last_loud >= delay

    def _mark_music_missing(self):
        now = time.time()
        user_toggle_age = now - getattr(self, "_user_toggle_ts", 0.0)
        if user_toggle_age <= 3.0:
            return
        if (
            not self._intentional_pause_active()
            and self._spotify_sound_detected_recently(2.5)
        ):
            self._music_missing_since = 0.0
            if not getattr(self, "_audio_monitor_running", False):
                self._set_play_btn_icon(True)
            return
        self._is_playing = False
        if not getattr(self, "_audio_monitor_running", False):
            self._set_play_btn_icon(False)


        if not self._should_handle_auto_stop():

            self._music_missing_since = 0.0
            return
        if not self._music_missing_since:
            self._music_missing_since = now
        delay = self._resume_delay_seconds()

        # Normal guard: wait at least `delay` seconds before acting.
        elapsed = now - self._music_missing_since

        # Playlist-ended heuristic:
        # The game is silent AND Spotify is also silent longer than
        # (resume_delay + 4 s).  GameBeats didn't pause Spotify, so the only
        # explanation is that the playlist finished on its own — pick a new one.
        game_quiet = self._game_quiet_long_enough(delay)
        spotify_quiet = self._spotify_quiet_long_enough(delay)
        playlist_ended_silence = (
            elapsed >= delay + 4.0
            and game_quiet
            and spotify_quiet
        )

        try:
            self._log(f"_mark_music_missing: elapsed={elapsed:.1f}s, game_quiet={game_quiet}, spotify_quiet={spotify_quiet}, playlist_ended_silence={playlist_ended_silence}")
        except Exception:
            pass

        if (
            elapsed < delay
            or not playlist_ended_silence
            or self._playlist_end_pending
        ):
            return

        # Do not treat silence as 'playlist ended' if GameBeats or the user
        # explicitly paused Spotify. This avoids race conditions where our
        # own pause/resume logic briefly pauses playback and the monitor
        # then believes the playlist finished.
        paused_by_game = False
        try:
            if self.spotify:
                paused_by_game = bool(getattr(self.spotify, "paused_by_game", getattr(self.spotify, "_paused_by_game", False)))
        except Exception:
            paused_by_game = False
        # Also consider the app-local flag in case the controller state was not updated
        paused_by_game = paused_by_game or bool(getattr(self, "_paused_by_game_flag", False))

        # Check pause stack: if ANY pause is in effect, don't treat silence as playlist end
        pause_stack_has_entries = bool(getattr(self, "_pause_stack", None) and len(self._pause_stack) > 0)

        if paused_by_game or self._manual_paused or bool(getattr(self, "_user_paused_flag", False)) or pause_stack_has_entries:
            return

        self._playlist_end_pending = True

        # Playlist-end now uses the puppy notifier only. Keeping the old
        # control overlay hidden avoids the stray titled white Tk window.
        try:
            if self._control_overlay:
                self._control_overlay.hide()
        except Exception:
            pass
        
        if self._end_behavior_key() == "loop_current" and not playlist_ended_silence:
            self._replay_current_playlist()
        else:
            uri = self._current_playlist_uri
            # Track this playlist as tried (for cycling through new ones)
            if uri and uri not in self._tried_playlist_uris:
                self._tried_playlist_uris.append(uri)

            reason = (
                "Playlist ended — picking another"
                if playlist_ended_silence
                else "Playback stopped — picking another playlist"
            )
            self._log(reason + ".")
            self._show_mascot_prompt(reason)

    # ── Mascot notifier ───────────────────────────────────────────────────────

    def _show_mascot_prompt(self, reason: str) -> None:
        """
        Show the game-safe 'playlist ended' notifier.

        Contract:
        • Window carries WS_EX_NOACTIVATE — game input is never interrupted
        • on_play_next fires on the Tk thread → safe to touch UI state
        • If user dismisses without clicking, _playlist_end_pending is cleared
          so the monitor loop can re-detect silence and prompt again
        """
        if self._spotify_sound_detected_recently(2.0):
            self._hide_mascot_notifier_for_spotify_audio()
            try:
                self._log("Playlist-end notifier suppressed because Spotify audio returned.")
            except Exception:
                pass
            return

        self._set_puppy_singing_visible(False)
        try:
            if self._control_overlay:
                self._control_overlay.hide()
        except Exception:
            pass

        if self._intentional_pause_active():
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            try:
                self._log("Playlist-end notifier suppressed because playback was intentionally paused.")
            except Exception:
                pass
            return

        # Entry log for debugging
        try:
            self._log(f"_show_mascot_prompt called: reason={reason}, playlist={self._current_playlist_name}, uri={self._current_playlist_uri}, playlist_end_pending={getattr(self,'_playlist_end_pending',None)}, is_playing={getattr(self,'_is_playing',False)}, play_in_progress={getattr(self,'_play_in_progress',False)}")
        except Exception:
            pass

        # Close any stale notifier (e.g. user ignored the last one).
        # Guard against exceptions in the notifier's callbacks so we
        # don't abort showing a fresh notifier.
        if self._mascot_notifier is not None:
            try:
                self._mascot_notifier.close()
            except Exception as ex:
                try:
                    self._log(f"Error closing stale MascotNotifier: {ex}")
                except Exception:
                    pass
            finally:
                self._mascot_notifier = None

        playlist_name = self._current_playlist_name or ""
        game_snapshot = self.current_game        # capture in case game changes

        def _on_play_next() -> None:
            """Fired (on Tk thread) when user clicks ▶ or countdown expires."""
            try:
                self._log(f"_on_play_next fired: game_snapshot={game_snapshot}, current_game={self.current_game}, current_playlist={self._current_playlist_uri}")
            except Exception:
                pass
            # User acted to pick next playlist — clear pending so monitor can
            # detect future playlist ends normally.
            try:
                self._playlist_end_pending = False
                self._music_missing_since = 0.0
            except Exception:
                pass
            if not (game_snapshot and game_snapshot == self.current_game):
                # Game switched while notifier was up — don't auto-play
                self._playlist_end_pending = False
                return

            # Explicitly track currently finished playlist so it isn't picked again
            if self._current_playlist_uri and self._current_playlist_uri not in self._tried_playlist_uris:
                self._tried_playlist_uris.append(self._current_playlist_uri)
            exclude_new = self._skip_playlist_uris(self._tried_playlist_uris)

            def _do_play():
                try:
                    # Do not restart Spotify here — prefer to reuse existing connection/device.

                    # If Spotify was audible recently, keep the automation
                    # browser alive so we do not interrupt active playback.
                    try:
                        if self._is_web_mode() and getattr(self, "spotify", None) is not None:
                            try:
                                if self._spotify_sound_detected_recently(10.0):
                                    self.root.after(0, lambda: self._log(
                                        "Spotify audio detected recently - keeping controller browser alive."))
                                elif hasattr(self.spotify, "close_browser"):
                                    self.root.after(0, lambda: self._log(
                                        "Closing controller browser for next playlist..."))
                                    self.spotify.close_browser()
                                    time.sleep(0.25)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # Trigger playlist pick on the Tk thread (one-shot: no pool retries)
                    # Do not force a new session; reuse the established connection if present.
                    self.root.after(0, lambda: self._play_query_for_game(
                        game_snapshot,
                        force_new=False,
                        exclude_uris=exclude_new,
                        reason=reason,
                        one_shot=True,
                    ))
                except Exception as ex:
                    self.root.after(0, lambda: self._log(f"Mascot play-next failed: {ex}"))

            threading.Thread(target=_do_play, daemon=True).start()

        def _on_dismiss() -> None:
            """Fired when user explicitly dismisses without playing."""
            try:
                self._log(f"_on_dismiss fired: current_game={self.current_game}, current_playlist={self._current_playlist_uri}")
            except Exception:
                pass
            self._mascot_notifier = None
            self._playlist_end_pending = False   # let monitor re-evaluate
            self._music_missing_since = 0.0

        def _on_play_another() -> None:
            """Fired when user clicks 'Another' button."""
            try:
                self._log(f"_on_play_another fired: current_game={self.current_game}, current_playlist={self._current_playlist_uri}")
            except Exception:
                pass
            self._mascot_notifier = None
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            if not (game_snapshot and game_snapshot == self.current_game):
                return
            
            # Track currently finished playlist so it isn't picked again
            if self._current_playlist_uri and self._current_playlist_uri not in self._tried_playlist_uris:
                self._tried_playlist_uris.append(self._current_playlist_uri)

            def _do_another():
                # Do not restart Spotify here — reuse existing device/connection.
                self.root.after(0, lambda: self._play_query_for_game(
                    game_snapshot,
                    force_new=False,
                    exclude_uris=set(self._tried_playlist_uris),
                    reason="User requested another playlist",
                    one_shot=True,
                ))

            threading.Thread(target=_do_another, daemon=True).start()

        def _on_quit() -> None:
            """Fired when user clicks the dismiss control and wants to quit the app.

            This closes Spotify desktop (if available) and exits the UI.
            """
            self._mascot_notifier = None
            self._playlist_end_pending = False

            def _do_quit():
                try:
                    if getattr(self, 'spotify', None):
                        try:
                            if hasattr(self.spotify, 'close_spotify'):
                                self.spotify.close_spotify()
                            elif hasattr(self.spotify, 'close_browser'):
                                self.spotify.close_browser()
                        except Exception:
                            pass
                finally:
                    try:
                        # Schedule UI shutdown on main thread
                        try:
                            self.root.after(0, self.root.quit)
                        except Exception:
                            pass
                        try:
                            self.root.after(50, self.root.destroy)
                        except Exception:
                            pass
                    except Exception:
                        pass

            threading.Thread(target=_do_quit, daemon=True).start()

        # auto_play_seconds=0 → no countdown, user MUST click to continue
        try:
            self._log("Creating MascotNotifier UI")
        except Exception:
            pass
        self._mascot_notifier = MascotNotifier(
            self.root,
            _on_play_next,
            on_play_another=_on_play_another,
            on_dismiss=_on_dismiss,
            on_quit=_on_quit,
            playlist_name=playlist_name,
            auto_play_seconds=0,
        )

    def _replay_current_playlist(self):
        uri = self._current_playlist_uri
        if not uri or not self.spotify:
            self._playlist_end_pending = False
            return
        name = self._current_playlist_name or "current playlist"
        self._log("Playback stopped - restarting playlist.")

        def _go():
            try:
                ok = bool(self.spotify.play_playlist(uri))
                if ok:
                    verified = False
                    try:
                        if self._is_desktop_mode() and self.spotify:
                            verified = self.spotify._verify_playback(expected_playlist_uri=uri, timeout=6.0)
                    except Exception:
                        verified = False

                    if not verified and self._is_web_mode() and self.spotify:
                        try:
                            self.spotify.ensure_active_device()
                            if self.spotify.play_playlist(uri):
                                verified = self.spotify._verify_playback(expected_playlist_uri=uri, timeout=6.0)
                        except Exception:
                            verified = False

                    if verified:
                        self._manual_paused = False
                        self.root.after(0, lambda: (
                            self._remember_current_playlist(uri, name, self._current_playlist_query),
                            self._log(f"Looping: {name}"),
                        ))
                        return

                self._playlist_end_pending = False
                self.root.after(0, lambda: self._log("Could not restart the playlist."))
            except Exception as ex:
                self._playlist_end_pending = False
                self.root.after(0, lambda: self._log(f"Replay failed: {ex}"))

        threading.Thread(target=_go, daemon=True).start()

    def _load_art(self, url):
        try:
            from io import BytesIO
            import urllib.request
            with urllib.request.urlopen(url, timeout=5) as r:
                data = r.read()
            img = Image.open(BytesIO(data)).convert("RGBA").resize((68, 68), Image.LANCZOS)
            
            # Round the corners of the album art to match the 8px radius holder
            from PIL import ImageDraw
            mask = Image.new("L", (68, 68), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle([(0, 0), (68, 68)], 8, fill=255)
            img.putalpha(mask)
            
            photo = ImageTk.PhotoImage(img)
            self._album_photo = photo
            self.root.after(0, lambda: self.art_label.configure(
                image=photo, text=""))
        except: pass

    # ── STARTUP ───────────────────────────────────────────────────────────────

    def _check_startup(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                  r"Software\Microsoft\Windows\CurrentVersion\Run",
                                  0, winreg.KEY_READ)
            winreg.QueryValueEx(key, "GameBeats")
            winreg.CloseKey(key)
            return True
        except: return False

    def _toggle_startup(self):
        if not HAS_WINREG: return
        exe = sys.executable if not getattr(sys, "frozen", False) else sys.executable
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                  r"Software\Microsoft\Windows\CurrentVersion\Run",
                                  0, winreg.KEY_SET_VALUE)
            if self.startup_var.get():
                winreg.SetValueEx(key, "GameBeats", 0, winreg.REG_SZ, f'"{exe}"')
                self._log("Added to Windows startup.")
            else:
                try: winreg.DeleteValue(key, "GameBeats")
                except: pass
                self._log("Removed from Windows startup.")
            winreg.CloseKey(key)
        except Exception as ex:
            self._log(f"Startup toggle failed: {ex}")

    def _open_url(self, url):
        """Copy link instead of opening Edge/default browser."""
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self._log("Link copied to clipboard (browser not opened).")
        except Exception as ex:
            self._log(f"Could not copy link: {ex}")

    # ── OVERLAY CONTROL CALLBACKS ─────────────────────────────────────────────

    def _overlay_play(self):
        """Play button from control overlay."""
        self._play()
        if self._control_overlay:
            self._control_overlay.update_status(playing=True)

    def _overlay_pause(self):
        """Pause button from control overlay."""
        self._pause()
        if self._control_overlay:
            self._control_overlay.update_status(playing=False)

    def _overlay_prev(self):
        """Previous button from control overlay."""
        self._prev()

    def _overlay_next(self):
        """Next button from control overlay."""
        self._next()

    def _overlay_block(self):
        """Block current playlist from control overlay."""
        self._block_current_playlist()

    def _overlay_try_another(self):
        """Try another playlist from control overlay."""
        self._try_another_playlist()

    def _show_control_overlay_for_playlist_end(self):
        """
        Show control overlay ONLY if playlist ended naturally.
        Don't show if we manually paused it or if Spotify paused it for other reasons.
        """
        # Only show if:
        # 1. We didn't manually pause it
        # 2. Spotify wasn't paused by us
        # 3. A playlist was actually playing
        # Use the centralized check so we don't show the overlay when paused
        if self.spotify and self._current_playlist_uri and not self._playback_paused_by_app_or_user():
            self._log("Playlist ended - showing control overlay")
            if self._control_overlay:
                self._control_overlay.show()
        else:
            # Log why overlay suppressed for easier debugging
            try:
                reason = []
                if self._manual_paused:
                    reason.append("manual_pause")
                if getattr(self, "_user_paused_flag", False):
                    reason.append("user_paused_flag")
                try:
                    if self.spotify and getattr(self.spotify, "paused_by_game", getattr(self.spotify, "_paused_by_game", False)):
                        reason.append("spotify_paused_by_game")
                except Exception:
                    pass
                if getattr(self, "_paused_by_game_flag", False):
                    reason.append("paused_by_game_flag")
                # Also log pause stack state for visibility
                try:
                    pause_stack_str = f"[{', '.join(e[0] for e in self._pause_stack)}]" if self._pause_stack else "[]"
                    reason.append(f"pause_stack={pause_stack_str}")
                except Exception:
                    pass
                if not reason:
                    reason.append("unknown")
                self._log(f"Playlist-ended overlay suppressed: {', '.join(reason)}")
            except Exception:
                pass

    # ── RUN ───────────────────────────────────────────────────────────────────

    def _shutdown_spotify_on_exit(self):
        spotify = getattr(self, "spotify", None)
        if not spotify:
            return
        try:
            if hasattr(spotify, "close_spotify"):
                spotify.close_spotify(timeout=4.0)
            elif hasattr(spotify, "close_browser"):
                spotify.close_browser()
        except Exception as ex:
            try:
                self._log(f"Could not close Spotify: {ex}")
            except Exception:
                pass

    def _on_close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        try:
            if self.detector:
                self.detector.stop()
        except Exception:
            pass
        try:
            if self._track_job:
                self.root.after_cancel(self._track_job)
                self._track_job = None
        except Exception:
            pass
        try:
            if self._mascot_notifier is not None:
                self._mascot_notifier.close()
                self._mascot_notifier = None
        except Exception:
            pass
        try:
            if self._spotify_login_prompt is not None:
                self._spotify_login_prompt.destroy()
                self._spotify_login_prompt = None
        except Exception:
            pass
        self._shutdown_spotify_on_exit()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()
