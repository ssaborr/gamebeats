import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
import threading
import time
import math
import json
import os
import sys
import urllib.request
from io import BytesIO
import subprocess

try:
    from PIL import Image, ImageTk, ImageOps
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
    HAS_PYCAW,
    _clear_spotify_mixer_mute,
)
from ui.onboarding import OnboardingOverlay
from ui.games_page import GamesPage, get_game_square_icon_image, _generate_gradient_fallback
from ui.mascot_notifier import MascotNotifier, PuppySingingOverlay
from ui.puppy_anim import PuppyAnimator
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


def _design_asset_path(*parts) -> str:
    """Find a file under the bundled assets directory."""
    path = os.path.join(str(T.assets_dir()), *parts)
    return path if os.path.exists(path) else ""


def _load_design_room(name="den_room.png"):
    path = _design_asset_path("room", name)
    if not path or not HAS_PIL:
        return None
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def _load_design_sprite(name):
    path = _design_asset_path("puppy_design", f"{name}.png")
    if not path or not HAS_PIL:
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _load_design_json(name):
    path = _design_asset_path("puppy_design", name)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


# ── Palette (from theme.py) ──────────────────────────────────────────────────
BG         = T.BG
NIGHT      = T.NIGHT
CREAM      = T.CREAM
GOLD       = T.GOLD
ORANGE     = T.ORANGE
MINT       = T.MINT
WOOD       = T.WOOD
DECK       = T.DECK
DECK_TOP   = T.DECK_TOP
ROSE       = T.ROSE
DUST       = T.DUST
MAGENTA    = T.MAGENTA
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

# The room plate is authored at 400x250 logical pixels and scaled by four
# before it reaches the app. All ambient overlays use these logical
# coordinates, so they stay locked to the same grid as the art.
ROOM_SOURCE_W = 400
ROOM_SOURCE_H = 250
ROOM_WINDOW_PANES = (
    (135, 42, 172, 81),
    (179, 42, 218, 81),
    (225, 42, 263, 81),
    (135, 88, 172, 124),
    (179, 88, 218, 124),
    (225, 88, 263, 124),
)
ROOM_HOTSPOTS = {
    # x0, y0, x1, y1 in room-logical pixels.
    "shelf": (285, 60, 380, 103),
    "panel": (290, 109, 376, 161),
    "crate": (308, 164, 384, 188),
    "crt": (32, 86, 108, 146),
}
ROOM_SHELF_CASES = (
    (292, 72, 298, 90),
    (300, 84, 316, 90),
    (318, 79, 324, 90),
    (326, 85, 344, 90),
    (348, 77, 354, 90),
    (356, 80, 372, 90),
)
ROOM_RECORD_SLEEVES = (
    (312, 164, 319, 176, MINT),
    (320, 165, 327, 177, GOLD),
    (328, 166, 335, 178, ORANGE),
)
ROOM_KNOBS = ((303, 136), (315, 136), (341, 136), (353, 136))
MASTER_TICK_MS = 33

F_FALLBACK = T.F_FALLBACK
F_TITLE    = T.F_TITLE
F_LABEL    = T.F_LABEL
F_SMALL    = T.F_SMALL
F_MICRO    = T.F_MICRO
F_MONO     = T.F_MONO
F_UI       = T.F_UI
F_PIXEL    = T.F_PIXEL
F_RETRO    = T.F_RETRO
F_SERIF    = T.F_SERIF


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
                 bg=ACCENT, fg=BG, radius=RADIUS_MD, font_size=11, canvas_bg=BG,
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
                         font=T.pixel_font(max(8, font_size), "bold"),
                         border_color=border_color, border_width=1 if border_color else 0,
                         hover_color=T.ACCENT_HOV if bg in (ACCENT, GOLD) else SURFACE4,
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
            font=T.retro_font(font_size, "bold"),
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
            fg_n = BG if self.accent else ACCENT
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
            lc.create_text(26, 26, text="\u266a", fill=ACCENT2, font=(F_UI, -20, "bold"))

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

        # Tk scales geometry sizes by the display DPI but screen dimensions are
        # physical pixels, so centering with the raw numbers pushes the window
        # off-screen on 150%+ displays. Center using the physical window size.
        try:
            ui_scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            ui_scale = 1.0
        px = max(0, (sw - int(init_w * ui_scale)) // 2)
        py = max(0, (sh - int(init_h * ui_scale)) // 2)
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
        self._autoplay_pending = False
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
        self._play_pause_watchdog = None
        self._manual_paused = False
        self._current_page = "main"
        self._current_playlist_uri = ""
        self._current_playlist_name = ""
        self._current_playlist_query = ""
        self._playlist_end_pending = False
        self._mascot_notifier = None          # MascotNotifier shown at playlist end
        self._puppy_singing_overlay = None    # Small desktop puppy while music plays
        self._puppy_hide_job = None           # Delayed hide so short audio dips don't blink it
        self._puppy_last_loud_ts = 0.0
        self._puppy_audio_active = False      # Drives the in-room mascot pose
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
            on_try_another=self._overlay_try_another,
            get_playing=lambda: (
                (not self._intentional_pause_active())
                and (
                    self._spotify_sound_detected_recently(3.0)
                    or bool(getattr(self, "_is_playing", False))
                )
            ),
        )
        self._puppy_singing_overlay = PuppySingingOverlay(
            self.root, corner="bottom-left"
        )
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
        # ── Room assets ───────────────────────────────────────────────────────
        self._room_pil = _load_design_room("den_room.png")
        self._room_dim_pil = _load_design_room("den_room_dim.png")
        self._puppy_anim_spec = _load_design_json("puppy_anim.json")
        self._puppy_anim = None
        if self._puppy_anim_spec:
            try:
                self._puppy_anim = PuppyAnimator(self._puppy_anim_spec)
            except Exception:
                self._puppy_anim = None
        if self._puppy_anim is not None:
            frame_names = set()
            for state in self._puppy_anim_spec.get("states", {}).values():
                frame_names.update(state.get("frames", ()))
                if state.get("static"):
                    frame_names.add(state["static"])
            self._puppy_sprites = {
                name: _load_design_sprite(f"anim/{name}")
                for name in sorted(frame_names)
            }
            self._puppy_sprites = {
                name: sprite for name, sprite in self._puppy_sprites.items()
                if sprite is not None
            }
        else:
            self._puppy_sprites = {
                name: _load_design_sprite(name)
                for name in ("idle", "mic", "sing", "encore")
            }
        self._puppy_photo_cache = {}
        self._puppy_mood_until = 0.0
        self._puppy_reaction_until = 0.0
        self._last_np_key = None
        self._room_image_item = None
        self._room_photo = None
        self._room_base_cache = None
        self._room_base_key = None
        self._room_redraw_job = None
        self._puppy_job = None
        self._puppy_frame = 0
        self._vu_job = None
        self._clock_job = None
        self._anim_tick = 0
        self._ambient = {}
        self._room_layout_info = None
        self._room_hotspots = {}
        self._room_hover = None
        self._crt_boost_until = 0.0
        self._vu_items = []
        self._vu_key = None
        self._vu_colors = []
        self._vu_heights = []
        self._cart_items = None
        self._cart_key = None
        self._heart_until = 0.0
        self._footer_buttons = {}
        self._footer_tools = {}
        self._is_maximized = False
        self._restore_geometry = ""
        self._brand_widgets = []

        self._room_dim_photo = None
        if self._room_dim_pil is not None:
            try:
                self._room_dim_photo = ImageTk.PhotoImage(self._room_dim_pil)
            except Exception:
                self._room_dim_photo = None

        # ── Root layout ───────────────────────────────────────────────────────
        container = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True)
        self._container = container

        # ── Window bar ────────────────────────────────────────────────────────
        header = ctk.CTkFrame(container, fg_color=NIGHT, height=48, corner_radius=0)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        self.header = header

        brand = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0, cursor="hand2")
        brand.pack(side=tk.LEFT, padx=(18, 0))

        brand_logo = None
        self._brand_puppy_photo = None
        try:
            sprite = (
                self._puppy_sprites.get("idle_0")
                or self._puppy_sprites.get("idle")
                or _load_design_sprite("idle")
            )
            if sprite is not None:
                resampling = getattr(Image, "Resampling", Image)
                logo = sprite.resize((32, 36), resampling.NEAREST)
                self._brand_puppy_photo = ImageTk.PhotoImage(logo)
                brand_logo = tk.Label(
                    brand, image=self._brand_puppy_photo, bg=NIGHT,
                    bd=0, highlightthickness=0, cursor="hand2",
                )
        except Exception:
            brand_logo = None

        if brand_logo is not None:
            brand_logo.pack(side=tk.LEFT, padx=(0, 9))
            paw = brand_logo
        else:
            paw = ctk.CTkLabel(
                brand, text="\u266a", fg_color="transparent", text_color=GOLD,
                font=T.retro_font(28, "bold"),
            )
            paw.pack(side=tk.LEFT, padx=(0, 9))

        brand_title = ctk.CTkLabel(
            brand, text="GAMEBEATS", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(17, "bold"),
        )
        brand_title.pack(side=tk.LEFT)

        brand_sub = ctk.CTkLabel(
            brand, text="THE DEN / VOL. 01", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        )
        brand_sub.pack(side=tk.LEFT, padx=(12, 0))

        self._brand_frame = brand
        self._brand_widgets = [brand, paw, brand_title, brand_sub]

        # Window buttons (far right first)
        win_controls = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
        win_controls.pack(side=tk.RIGHT, padx=(0, 10))

        close_btn = ctk.CTkButton(
            win_controls, text="\u2715", width=30, height=30, fg_color="transparent",
            text_color=TEXT_MUTED, hover_color="#4A1A1A", corner_radius=RADIUS_SM,
            font=T.retro_font(19, "bold"), command=self._on_close,
        )
        close_btn.pack(side=tk.RIGHT, padx=1)

        max_btn = ctk.CTkButton(
            win_controls, text="\u25a1", width=30, height=30, fg_color="transparent",
            text_color=TEXT_MUTED, hover_color=SURFACE3, corner_radius=RADIUS_SM,
            font=T.retro_font(18), command=self._toggle_maximize_window,
        )
        max_btn.pack(side=tk.RIGHT, padx=1)

        min_btn = ctk.CTkButton(
            win_controls, text="\u2014", width=30, height=30, fg_color="transparent",
            text_color=TEXT_MUTED, hover_color=SURFACE3, corner_radius=RADIUS_SM,
            font=T.retro_font(17), command=self._minimize_window,
        )
        min_btn.pack(side=tk.RIGHT, padx=1)

        ctk.CTkFrame(header, fg_color=BORDER, width=1, height=18).pack(
            side=tk.RIGHT, padx=(0, 14), pady=15,
        )

        # Live status pill (Watching games, game name, verifying…)
        status_cluster = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0)
        status_cluster.pack(side=tk.RIGHT, padx=(0, 16))

        self.status_dot = ctk.CTkLabel(
            status_cluster, text="\u25cf", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(13),
        )
        self.status_dot.pack(side=tk.RIGHT, padx=(5, 0))

        self.status_pill = ctk.CTkLabel(
            status_cluster, text="STARTING UP", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        )
        self.status_pill.pack(side=tk.RIGHT)

        ctk.CTkFrame(header, fg_color=BORDER, width=1, height=18).pack(
            side=tk.RIGHT, padx=(0, 14), pady=15,
        )

        # Spotify connection LED
        conn = ctk.CTkFrame(header, fg_color="transparent", corner_radius=0, cursor="hand2")
        conn.pack(side=tk.RIGHT, padx=(0, 6))

        self.connection_dot = ctk.CTkLabel(
            conn, text="\u25cf", fg_color="transparent", text_color=MAGENTA,
            font=T.retro_font(13),
        )
        self.connection_dot.pack(side=tk.LEFT, padx=(0, 6))

        self.connection_lbl = ctk.CTkLabel(
            conn, text="SPOTIFY OFFLINE", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        )
        self.connection_lbl.pack(side=tk.LEFT)

        for widget in (conn, self.connection_dot, self.connection_lbl):
            widget.bind("<Button-1>", lambda e: self._nav("settings"))
            widget.bind("<Enter>", lambda e: conn.configure(cursor="hand2"))

        # ── Topline ───────────────────────────────────────────────────────────
        topline = ctk.CTkFrame(container, fg_color=BG, height=44, corner_radius=0)
        topline.pack(fill=tk.X)
        topline.pack_propagate(False)
        self.topline = topline

        room_line = ctk.CTkFrame(topline, fg_color="transparent", corner_radius=0)
        room_line.pack(side=tk.LEFT, padx=(30, 0))
        ctk.CTkLabel(
            room_line, text="\u25aa", fg_color="transparent",
            text_color=ACCENT, font=T.retro_font(16),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkLabel(
            room_line, text="PLAYER 1'S ROOM", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        ).pack(side=tk.LEFT)
        ctk.CTkLabel(
            room_line, text="/", fg_color="transparent",
            text_color=WOOD, font=T.pixel_font(9),
        ).pack(side=tk.LEFT, padx=8)

        self._clock_lbl = ctk.CTkLabel(
            room_line, text="08:42 PM \u00b7 GOLDEN HOUR", fg_color="transparent",
            text_color=ROSE, font=T.pixel_font(9),
        )
        self._clock_lbl.pack(side=tk.LEFT)

        ctk.CTkButton(
            topline, text="\u2726  THE LITTLE DETAILS", command=lambda: self._nav("faq"),
            fg_color="transparent", text_color=ROSE, hover_color=SURFACE3,
            width=194, height=28, corner_radius=0,
            font=T.pixel_font(9),
        ).pack(side=tk.RIGHT, padx=(0, 28))

        # ── Content ──────────────────────────────────────────────────────────
        self.content = ctk.CTkFrame(container, fg_color=BG, corner_radius=0)
        self.content.pack(fill=tk.BOTH, expand=True)

        # ── Footer nav ───────────────────────────────────────────────────────
        footer = ctk.CTkFrame(container, fg_color=NIGHT, height=62, corner_radius=0)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)
        self.footer = footer

        nav = ctk.CTkFrame(footer, fg_color="transparent", corner_radius=0)
        nav.pack(side=tk.LEFT, padx=(26, 0), fill=tk.Y)

        nav_items = [
            ("main", "\u2302", "01 / THE DEN"),
            ("games", "\u25a5", "02 / GAME SHELF"),
            ("playlists", "\u25c9", "03 / RECORD CRATE"),
            ("settings", "\u2692", "04 / CONTROL PANEL"),
        ]
        for page, icon, label in nav_items:
            btn = ctk.CTkButton(
                nav, text=f"{icon}  {label}", command=lambda p=page: self._nav(p),
                fg_color="transparent", text_color=TEXT_MUTED, hover_color=SURFACE2,
                width=148, height=34, corner_radius=0,
                font=T.pixel_font(9), anchor="w",
            )
            btn.pack(side=tk.LEFT, padx=(0, 4), pady=14)
            self._footer_buttons[page] = btn

        tools = ctk.CTkFrame(footer, fg_color="transparent", corner_radius=0)
        tools.pack(side=tk.RIGHT, padx=(0, 26), fill=tk.Y)

        self._footer_version_lbl = ctk.CTkLabel(
            tools, text="V.01  \u25aa  MADE FOR YOUR SIDE QUESTS", fg_color="transparent",
            text_color=WOOD, font=T.pixel_font(8),
        )
        self._footer_version_lbl.pack(side=tk.RIGHT, padx=(14, 0))

        overlay_btn = ctk.CTkButton(
            tools, text="\u2723  OVERLAY", command=self._show_control_overlay,
            fg_color="transparent", text_color=TEXT_MUTED, hover_color=SURFACE2,
            width=94, height=34, corner_radius=0, font=T.pixel_font(9),
        )
        overlay_btn.pack(side=tk.RIGHT, padx=2, pady=14)
        self._footer_tools["overlay"] = overlay_btn

        faq_btn = ctk.CTkButton(
            tools, text="\u2726  FAQ", command=lambda: self._nav("faq"),
            fg_color="transparent", text_color=TEXT_MUTED, hover_color=SURFACE2,
            width=74, height=34, corner_radius=0, font=T.pixel_font(9),
        )
        faq_btn.pack(side=tk.RIGHT, padx=2, pady=14)
        self._footer_tools["faq"] = faq_btn

        blocked_btn = ctk.CTkButton(
            tools, text="\u2298  BLOCKED", command=lambda: self._nav("blocked"),
            fg_color="transparent", text_color=TEXT_MUTED, hover_color=SURFACE2,
            width=102, height=34, corner_radius=0, font=T.pixel_font(9),
        )
        blocked_btn.pack(side=tk.RIGHT, padx=2, pady=14)
        self._footer_tools["blocked"] = blocked_btn

        # ── Build pages + wiring ─────────────────────────────────────────────
        self._current_page = "main"
        self.main = container
        self.player_frame = None
        self._build_pages()
        self._setup_window_dragging()
        self._tick_clock()
        self._refresh_connection_ui()

    def _toggle_maximize_window(self):
        """Maximize/restore the frameless window without relying on WM chrome."""
        try:
            if getattr(self, "_is_maximized", False):
                if self._restore_geometry:
                    self.root.geometry(self._restore_geometry)
                self._is_maximized = False
            else:
                self._restore_geometry = self.root.geometry()
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                self.root.geometry(f"{sw}x{sh}+0+0")
                self._is_maximized = True
        except Exception:
            pass

    def _setup_window_dragging(self):
        self._drag_x = 0
        self._drag_y = 0
        self._drag_moved = False

        def _start_drag(event):
            self._drag_enabled = True
            self._drag_moved = False
            self._drag_x = event.x_root
            self._drag_y = event.y_root

        def _drag_motion(event):
            if not getattr(self, "_drag_enabled", True):
                return
            dx = event.x_root - self._drag_x
            dy = event.y_root - self._drag_y
            if abs(dx) + abs(dy) > 2:
                self._drag_moved = True
            x = self.root.winfo_x() + dx
            y = self.root.winfo_y() + dy
            self.root.geometry(f"+{x}+{y}")
            self._drag_x = event.x_root
            self._drag_y = event.y_root

        def _brand_release(_event):
            if not getattr(self, "_drag_moved", False):
                self._nav("main")

        drag_targets = [self.header] + list(getattr(self, "_brand_widgets", []))
        for widget in drag_targets:
            if widget:
                widget.bind("<Button-1>", _start_drag, add="+")
                widget.bind("<B1-Motion>", _drag_motion, add="+")

        for widget in getattr(self, "_brand_widgets", []) or []:
            widget.bind("<ButtonRelease-1>", _brand_release, add="+")

        if self.header:
            self.header.bind("<Double-Button-1>",
                             lambda e: self._toggle_maximize_window(), add="+")

    def _tick_clock(self):
        try:
            stamp = time.strftime("%I:%M %p").lstrip("0")
            if hasattr(self, "_clock_lbl"):
                self._clock_lbl.configure(text=f"{stamp} \u00b7 GOLDEN HOUR")
            self._clock_job = self.root.after(30000, self._tick_clock)
        except Exception:
            pass

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
        """Keep the den proportional and update wraplengths without rescaling fonts."""
        try:
            w = max(300, self.root.winfo_width())
            h = max(300, self.root.winfo_height())
        except Exception:
            w, h = WIN_W, WIN_H

        if getattr(self, "_last_resize", None) == (w, h):
            return
        self._last_resize = (w, h)

        room_h = max(260, h - 48 - 44 - 62)
        self._deck_height = 420
        try:
            if getattr(self, "_deck_wrap", None) is not None:
                self._deck_wrap.configure(height=self._deck_height)
        except Exception:
            pass

        wrap = max(300, w - 120)
        deck_wrap = max(240, int(w * 0.584) - 230)
        cart_w = max(190, int(w * 0.145))
        try:
            self._deck_body.grid_columnconfigure(0, minsize=cart_w)
            self._deck_cart.configure(width=cart_w)
        except Exception:
            pass

        for attr in ("game_banner", "mood_lbl"):
            try:
                getattr(self, attr).configure(wraplength=max(110, cart_w - 70))
            except Exception:
                pass
        try:
            self.playlist_display_lbl.configure(wraplength=max(150, cart_w - 40))
        except Exception:
            pass
        try:
            self.track_lbl.configure(wraplength=deck_wrap)
        except Exception:
            pass
        try:
            self.status_log_lbl.configure(wraplength=deck_wrap)
        except Exception:
            pass
        try:
            self.deck_artist_lbl.configure(wraplength=deck_wrap)
        except Exception:
            pass

        for attr in ("pl_status_lbl", "blocked_status_lbl"):
            try:
                lbl = getattr(self, attr, None)
                if lbl:
                    lbl.configure(wraplength=wrap)
            except Exception:
                pass

        try:
            if hasattr(self, "_footer_version_lbl"):
                if w < 1120:
                    self._footer_version_lbl.pack_forget()
                else:
                    self._footer_version_lbl.pack(side=tk.RIGHT, padx=(14, 0))
        except Exception:
            pass

        self._dynamic_wrap = wrap
        self._ui_scale = 1.0

    def _nav(self, page):
        if page == "overlay":
            self._show_control_overlay()
            return

        self._current_page = page

        for f in [
            getattr(self, "_page_main", None),
            getattr(self, "_page_playlists", None),
            getattr(self, "_page_games", None),
            getattr(self, "_page_blocked", None),
            getattr(self, "_page_settings", None),
            getattr(self, "_page_faq", None),
        ]:
            try:
                if f:
                    f.pack_forget()
            except Exception:
                pass

        page_map = {
            "main": getattr(self, "_page_main", None),
            "playlists": getattr(self, "_page_playlists", None),
            "games": getattr(self, "_page_games", None),
            "blocked": getattr(self, "_page_blocked", None),
            "settings": getattr(self, "_page_settings", None),
            "faq": getattr(self, "_page_faq", None),
        }
        target = page_map.get(page)
        if target:
            target.pack(fill=tk.BOTH, expand=True)

        self._paint_footer(page)

        if page == "main":
            self._redraw_room()
            self._start_puppy_animation()
        else:
            self._stop_puppy_animation()

        if page == "playlists" and getattr(self, "spotify", None):
            self._load_playlists()
        if page == "blocked":
            self._refresh_blocked_page()

    def _paint_footer(self, page):
        for key, btn in getattr(self, "_footer_buttons", {}).items():
            try:
                if key == page:
                    btn.configure(fg_color=SURFACE2, text_color=ACCENT)
                else:
                    btn.configure(fg_color="transparent", text_color=TEXT_MUTED)
            except Exception:
                pass
        for key, btn in getattr(self, "_footer_tools", {}).items():
            try:
                if key == page:
                    btn.configure(fg_color=SURFACE2, text_color=ACCENT)
                else:
                    btn.configure(fg_color="transparent", text_color=TEXT_MUTED)
            except Exception:
                pass

    def _show_control_overlay(self):
        try:
            if getattr(self, "_control_overlay", None):
                self._control_overlay.show()
        except Exception as e:
            try:
                self._log(f"Could not open overlay: {e}")
            except Exception:
                pass

    def _refresh_connection_ui(self):
        connected = bool(getattr(self, "spotify", None))
        try:
            if connected:
                self.connection_lbl.configure(text="SPOTIFY CONNECTED", text_color=MINT)
                self.connection_dot.configure(text_color=GREEN)
                if hasattr(self, "deck_led"):
                    self.deck_led.configure(text="\u25cf  SPOTIFY IN", text_color=MINT)
            else:
                self.connection_lbl.configure(text="SPOTIFY OFFLINE", text_color=TEXT_MUTED)
                self.connection_dot.configure(text_color=MAGENTA)
                if hasattr(self, "deck_led"):
                    self.deck_led.configure(text="\u25cb  SPOTIFY OUT", text_color=TEXT_MUTED)
        except Exception:
            pass

    def _new_page(self):
        page = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        if getattr(self, "_room_dim_photo", None) is not None:
            try:
                bg = tk.Label(
                    page, image=self._room_dim_photo, bg=BG, bd=0,
                    highlightthickness=0, anchor="nw",
                )
                bg.place(x=0, y=0, relwidth=1, relheight=1)
                bg.lower()
            except Exception:
                pass
        return page

    def _make_page_body(self, page, padx=26, pady=(14, 8)):
        body = ctk.CTkFrame(page, fg_color=BG, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True, padx=padx, pady=pady)
        return body

    def _build_pages(self):
        self._page_main = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self._page_playlists = self._new_page()
        self._page_games = self._new_page()
        self._page_blocked = self._new_page()
        self._page_settings = self._new_page()
        self._page_faq = self._new_page()

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

        self._nav("main")

    def _card(self, parent, pady=0):
        return T.elevated_card(parent, pady=pady)

    def _section_lbl(self, parent, text):
        T.section_header(parent, text)

    # ── MAIN PAGE ─────────────────────────────────────────────────────────────

    def _build_main_page(self):
        mp = self._page_main

        self._room_canvas = tk.Canvas(mp, bg=BG, highlightthickness=0, bd=0)
        mp.grid_rowconfigure(0, weight=1)
        mp.grid_columnconfigure(0, weight=1)
        self._room_canvas.grid(row=0, column=0, sticky="nsew")
        self._room_canvas.bind("<Configure>", self._on_room_canvas_configure)
        self._room_canvas.bind("<Button-1>", self._on_room_canvas_click)
        self._room_canvas.bind("<Motion>", self._on_room_canvas_motion)
        self._room_canvas.bind("<Leave>", self._on_room_canvas_leave)
        self._room_image_item = None
        self._puppy_bbox = (0, 0, 0, 0)
        self._room_puppy_item = None
        self._room_puppy_photo = None
        self._room_puppy_base = (0, 0, 0, 0)
        self._room_puppy_sprite_key = None
        self._vu_level = 0.0
        self._deck_height = 420

        # The deck is a real dock now, not a floating window placed over the
        # canvas. That keeps it visible on every DPI/window-size combination.
        self._deck_shadow = None
        self._deck_wrap = tk.Frame(
            mp, bg=DECK, bd=0, highlightthickness=0, height=420,
        )
        self._deck_wrap.grid(
            row=1, column=0, sticky="ew", padx=(24, 24), pady=(0, 12),
        )
        self._deck_wrap.pack_propagate(False)

        self._deck = ctk.CTkFrame(
            self._deck_wrap, fg_color=DECK, corner_radius=0,
            border_width=3, border_color=NIGHT,
        )
        self._deck.pack(fill=tk.BOTH, expand=True)
        # Crisp 3D bevel: lit top edge, deep bottom edge.
        try:
            tk.Frame(self._deck, bg="#8E5560", height=2).place(
                x=0, y=0, relwidth=1,
            )
            tk.Frame(self._deck, bg=NIGHT, height=3).place(
                x=0, rely=1.0, y=-3, relwidth=1,
            )
        except Exception:
            pass

        top = ctk.CTkFrame(self._deck, fg_color=DECK_TOP, height=25, corner_radius=0)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        ctk.CTkLabel(
            top, text="GB\u201401 / AUTO-SOUND SYSTEM", fg_color="transparent",
            text_color=GOLD, font=T.pixel_font(9, "bold"),
        ).pack(side=tk.LEFT, padx=10)

        self.deck_led = ctk.CTkLabel(
            top, text="\u25cb  SPOTIFY OUT", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9), cursor="hand2",
        )
        self.deck_led.pack(side=tk.RIGHT, padx=10)
        self.deck_led.bind("<Button-1>", lambda e: self._nav("settings"))

        body = ctk.CTkFrame(self._deck, fg_color=DECK, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True, padx=9, pady=(7, 4))
        body.grid_columnconfigure(0, weight=0, minsize=230)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self._deck_body = body

        # ── Cartridge ────────────────────────────────────────────────────────
        cart = ctk.CTkFrame(
            body, fg_color=SURFACE2, corner_radius=0,
            border_width=2, border_color=NIGHT, width=230,
        )
        cart.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        cart.grid_propagate(False)
        self._deck_cart = cart

        ridges = tk.Canvas(cart, height=9, bg=NIGHT, highlightthickness=0)
        ridges.pack(fill=tk.X)
        for i in range(18):
            ridges.create_line(8 + i * 9, 2, 8 + i * 9, 7, fill=DECK)

        cart_label = ctk.CTkFrame(cart, fg_color=NIGHT, corner_radius=0)
        cart_label.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        head = ctk.CTkFrame(cart_label, fg_color="transparent", corner_radius=0)
        head.pack(fill=tk.X, padx=7, pady=(7, 2))

        self._game_icon_holder = ctk.CTkFrame(
            head, fg_color=SURFACE3, width=40, height=40, corner_radius=0,
            border_width=1, border_color=WOOD,
        )
        self._game_icon_holder.pack(side=tk.LEFT, padx=(0, 7))
        self._game_icon_holder.pack_propagate(False)

        self._game_icon_label = ctk.CTkLabel(
            self._game_icon_holder, text="\U0001f3ae", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(18),
        )
        self._game_icon_label.pack(fill=tk.BOTH, expand=True)

        name_col = ctk.CTkFrame(head, fg_color="transparent", corner_radius=0)
        name_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.game_banner = ctk.CTkLabel(
            name_col, text="NO SAVED GAME RUNNING", fg_color="transparent",
            text_color=TEXT, font=T.pixel_font(11, "bold"),
            anchor="w", justify=tk.LEFT, wraplength=160,
        )
        self.game_banner.pack(fill=tk.X)

        self.mood_lbl = ctk.CTkLabel(
            name_col, text="Waiting for a game", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(13),
            anchor="w", justify=tk.LEFT, wraplength=160,
        )
        self.mood_lbl.pack(fill=tk.X, pady=(1, 0))

        self.playlist_display_lbl = ctk.CTkLabel(
            cart_label, text="PLAYLIST: \u2014", fg_color="transparent",
            text_color=GOLD, font=T.retro_font(13),
            anchor="w", justify=tk.LEFT, wraplength=190,
        )
        self.playlist_display_lbl.pack(fill=tk.X, padx=7, pady=(4, 0))

        cassette = tk.Canvas(
            cart_label, height=28, width=1, bg=NIGHT, highlightthickness=0,
        )
        cassette.pack(fill=tk.X, padx=7, pady=(6, 6))
        cassette.bind(
            "<Configure>",
            lambda e: self._draw_cart_cassette(cassette),
        )
        self._cart_canvas = cassette

        # ── Display ──────────────────────────────────────────────────────────
        disp = ctk.CTkFrame(
            body, fg_color=NIGHT, corner_radius=0,
            border_width=2, border_color=WOOD,
        )
        disp.grid(row=0, column=1, sticky="nsew")

        inner = ctk.CTkFrame(disp, fg_color=NIGHT, corner_radius=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=7)

        status_row = ctk.CTkFrame(inner, fg_color="transparent", corner_radius=0)
        status_row.pack(fill=tk.X)

        self.deck_status_lbl = ctk.CTkLabel(
            status_row, text="\u25cb  STANDING BY", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9, "bold"),
        )
        self.deck_status_lbl.pack(side=tk.LEFT)

        ctk.CTkLabel(
            status_row, text="SIDE A / AUTO", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(8),
        ).pack(side=tk.RIGHT)

        self.track_lbl = ctk.CTkLabel(
            inner, text="Nothing playing", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(24),
            anchor="w", justify=tk.LEFT,
        )
        self.track_lbl.pack(fill=tk.X, pady=(2, 0))

        self.deck_artist_lbl = ctk.CTkLabel(
            inner, text="Connect Spotify in Control Panel", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(15),
            anchor="w", justify=tk.LEFT,
        )
        self.deck_artist_lbl.pack(fill=tk.X, pady=(0, 1))

        # Hidden compatibility labels used by _update_np / _load_art.
        self.artist_lbl = ctk.CTkLabel(inner, text="", fg_color="transparent")
        self.art_holder = ctk.CTkFrame(mp, width=1, height=1)
        self.art_holder.place(x=-40, y=-40)
        self.art_label = tk.Label(self.art_holder, text="", bg=NIGHT)

        vu_row = ctk.CTkFrame(inner, fg_color="transparent", corner_radius=0)
        vu_row.pack(fill=tk.X, pady=(3, 0))

        ctrl = ctk.CTkFrame(vu_row, fg_color="transparent", corner_radius=0)
        ctrl.pack(side=tk.RIGHT)

        self._vu_canvas = tk.Canvas(
            vu_row, height=18, bg=NIGHT, highlightthickness=0, bd=0,
        )
        self._vu_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self._vu_canvas.bind("<Configure>", lambda e: self._draw_vu())

        self.prev_btn = CircleBtn(
            ctrl, "\u23ee", command=self._prev, size=30, font_size=13,
            bg=SURFACE2, fg=TEXT, canvas_bg=NIGHT,
        )
        self.prev_btn.pack(side=tk.LEFT, padx=3)

        self.play_btn = CircleBtn(
            ctrl, "\u25b6", command=self._play_pause_toggle,
            size=40, bg=GOLD, fg=BG, font_size=17,
            canvas_bg=NIGHT, accent=True,
        )
        self.play_btn.pack(side=tk.LEFT, padx=3)

        self.next_btn = CircleBtn(
            ctrl, "\u23ed", command=self._next, size=30, font_size=13,
            bg=SURFACE2, fg=TEXT, canvas_bg=NIGHT,
        )
        self.next_btn.pack(side=tk.LEFT, padx=3)

        self.status_log_lbl = ctk.CTkLabel(
            inner, text="GameBeats ready.", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(13),
            anchor="w", justify=tk.LEFT,
        )
        self.status_log_lbl.pack(fill=tk.X, pady=(3, 0))

        # ── Deck bottom ─────────────────────────────────────────────────────
        bottom = ctk.CTkFrame(self._deck, fg_color=DECK, height=34, corner_radius=0)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, padx=9, pady=(0, 7))
        bottom.pack_propagate(False)

        auto = ctk.CTkFrame(bottom, fg_color="transparent", corner_radius=0)
        auto.pack(side=tk.LEFT)
        ctk.CTkLabel(
            auto, text="AUTO", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(8),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ctk.CTkSwitch(
            auto, variable=self.auto_mode, text="", width=34, height=17,
            fg_color=SURFACE4, progress_color=MINT,
            button_color=CREAM, button_hover_color=GOLD,
            border_width=0, corner_radius=9,
            command=lambda: self._log(
                "Auto-play " + ("on" if self.auto_mode.get() else "off")
            ),
        ).pack(side=tk.LEFT)

        seamless = ctk.CTkFrame(bottom, fg_color="transparent", corner_radius=0)
        seamless.pack(side=tk.LEFT, padx=(14, 0))
        ctk.CTkLabel(
            seamless, text="KEEP MUSIC", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(8),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ctk.CTkSwitch(
            seamless, variable=self.seamless_music_var,
            command=self._save_player_settings, text="", width=34, height=17,
            fg_color=SURFACE4, progress_color=MINT,
            button_color=CREAM, button_hover_color=GOLD,
            border_width=0, corner_radius=9,
        ).pack(side=tk.LEFT)

        self.block_pl_btn = T.pixel_button(
            bottom, text="\u2298  BLOCK", command=self._block_current_playlist,
            width=82, height=27,
        )
        self.block_pl_btn.pack(side=tk.RIGHT, padx=(5, 0))

        T.pixel_button(
            bottom, text="\u21ba  TRY ANOTHER", command=self._try_another_playlist,
            width=128, height=27,
        ).pack(side=tk.RIGHT)

        # Keep the bottom rail reserved before the flexible body claims space.
        body.pack_forget()
        body.pack(fill=tk.BOTH, expand=True, padx=9, pady=(7, 4))

        self.root.after(80, self._redraw_room)
        # The room canvas fills the page. Force the player deck above it and
        # re-assert once the window has its final geometry.
        self._raise_deck()
        self.root.after(250, self._raise_deck)
        self.root.after(900, self._raise_deck)

    def _raise_deck(self):
        try:
            if getattr(self, "_deck_shadow", None) is not None:
                self._deck_shadow.lift()
            if getattr(self, "_deck_wrap", None) is not None:
                self._deck_wrap.lift()
        except Exception:
            pass

    # ── DEN CANVAS ────────────────────────────────────────────────────────────

    def _time_of_day(self):
        try:
            hour = time.localtime().tm_hour
        except Exception:
            return "evening"
        if hour < 12:
            return "morning"
        if hour < 18:
            return "afternoon"
        return "evening"

    def _schedule_room_redraw(self, delay_ms: int = 0):
        """Coalesce room repaints so rapid state changes stay cheap."""
        try:
            if self._room_redraw_job:
                self.root.after_cancel(self._room_redraw_job)
        except Exception:
            pass
        try:
            self._room_redraw_job = self.root.after(
                max(0, int(delay_ms)), self._redraw_room
            )
        except Exception:
            self._room_redraw_job = None

    def _on_room_canvas_configure(self, _event=None):
        self._schedule_room_redraw(55)

    def _puppy_image_for(self, name, size):
        sprite = getattr(self, "_puppy_sprites", {}).get(name)
        if sprite is None:
            return None
        key = (name, int(size[0]), int(size[1]))
        cached = self._puppy_photo_cache.get(key)
        if cached is not None:
            return cached
        try:
            resampling = getattr(Image, "Resampling", Image)
            scaled = sprite.resize((int(size[0]), int(size[1])), resampling.NEAREST)
            self._puppy_photo_cache[key] = scaled
            return scaled
        except Exception:
            return None

    def _draw_room_puppy(self, canvas, sprite_name, geometry):
        px, py, pw, ph = geometry
        sprite = self._puppy_image_for(sprite_name, (pw, ph))
        if sprite is None:
            return
        try:
            photo = ImageTk.PhotoImage(sprite)
            self._room_puppy_photo = photo
            if self._room_puppy_item is None or not canvas.type(self._room_puppy_item):
                self._room_puppy_item = canvas.create_image(
                    px, py, anchor="nw", image=photo, tags=("puppy",)
                )
            else:
                canvas.itemconfigure(self._room_puppy_item, image=photo)
                canvas.coords(self._room_puppy_item, px, py)
            self._room_puppy_sprite_key = (sprite_name, int(pw), int(ph))
            canvas.tag_raise("puppy")
        except Exception:
            pass

    def _reduce_motion_enabled(self):
        try:
            return bool(self.configure.get("reduce_motion", False))
        except Exception:
            return False

    def _puppy_audio_level(self):
        try:
            peak = float(getattr(self, "_last_spotify_peak", 0.0) or 0.0)
        except Exception:
            peak = 0.0
        return max(0.0, min(1.0, peak / 0.18))

    def _puppy_animation_mode(self, now=None):
        now = time.time() if now is None else now
        if now < getattr(self, "_puppy_mood_until", 0.0):
            return "happy"
        if now < getattr(self, "_puppy_reaction_until", 0.0):
            return "reaction"
        try:
            playing = bool(
                getattr(self, "_is_playing", False)
                or getattr(self, "_spotify_audio_active", False)
            ) and not self._intentional_pause_active()
        except Exception:
            playing = bool(getattr(self, "_is_playing", False))
        if playing:
            return "singing"
        if getattr(self, "current_game", None):
            return "alert"
        try:
            if self._intentional_pause_active():
                return "paused"
        except Exception:
            pass
        return "idle"

    def _puppy_frame_name(self, now=None):
        now = time.time() if now is None else now
        mode = self._puppy_animation_mode(now)
        animator = getattr(self, "_puppy_anim", None)
        if animator is not None:
            return animator.frame(
                int(now * 30), mode, self._puppy_audio_level(),
                self._reduce_motion_enabled(),
            )
        # Legacy fallback if the animation spec was not packaged.
        if mode == "singing":
            return "sing" if int(now * 6.0) % 4 < 2 else "mic"
        if mode in ("alert", "reaction"):
            return "mic"
        return "idle"

    def _animate_room_puppy(self, now=None):
        """Swap in-place frames; the mascot never moves on the canvas."""
        canvas = getattr(self, "_room_canvas", None)
        if canvas is None or self._room_puppy_item is None:
            return
        try:
            if not canvas.winfo_exists():
                return
            px, py, pw, ph = getattr(self, "_room_puppy_base", (0, 0, 0, 0))
            if pw <= 0 or ph <= 0:
                return

            now = time.time() if now is None else now
            sprite_name = self._puppy_frame_name(now)
            key = (sprite_name, int(pw), int(ph))
            if key != self._room_puppy_sprite_key:
                sprite = self._puppy_image_for(sprite_name, (pw, ph))
                if sprite is not None:
                    photo = ImageTk.PhotoImage(sprite)
                    self._room_puppy_photo = photo
                    canvas.itemconfigure(self._room_puppy_item, image=photo)
                    self._room_puppy_sprite_key = key
            # Feet are locked: coordinates and bbox never change after layout.
            self._puppy_bbox = (px, py, px + pw, py + ph)
            canvas.tag_raise("puppy")
        except Exception:
            pass

    @staticmethod
    def _room_layout(w, h):
        """Map the 400x250 authored room plate onto a canvas rectangle.

        ImageOps.fit scales by the larger axis and centres the crop, so the
        same transform is needed for every ambient overlay.
        """
        w = max(1, int(w))
        h = max(1, int(h))
        scale = max(w / float(ROOM_SOURCE_W), h / float(ROOM_SOURCE_H))
        visible_w = w / scale
        visible_h = h / scale
        left = (ROOM_SOURCE_W - visible_w) / 2.0
        top = (ROOM_SOURCE_H - visible_h) / 2.0
        return scale, left, top

    @staticmethod
    def _room_rect(layout, x0, y0, x1, y1, min_w=1, min_h=1):
        scale, left, top = layout
        cx0 = int(round((x0 - left) * scale))
        cy0 = int(round((y0 - top) * scale))
        cx1 = int(round((x1 - left) * scale))
        cy1 = int(round((y1 - top) * scale))
        if cx1 <= cx0:
            cx1 = cx0 + max(1, int(min_w))
        if cy1 <= cy0:
            cy1 = cy0 + max(1, int(min_h))
        return cx0, cy0, cx1, cy1

    def _build_room_ambient(self, canvas, w, h):
        """Create the pooled ambient canvas items once per room layout.

        Nothing here runs on the animation tick. The master clock only moves
        and recolours these existing items.
        """
        try:
            canvas.delete("ambient")
        except Exception:
            pass

        layout = self._room_layout(w, h)
        self._room_layout_info = layout
        reduce_motion = self._reduce_motion_enabled()
        self._room_hotspots = {
            name: self._room_rect(layout, *zone)
            for name, zone in ROOM_HOTSPOTS.items()
        }

        outlines = {}
        outline_width = max(1, int(round(layout[0] * 0.32)))
        for name, zone in ROOM_HOTSPOTS.items():
            rect = self._room_rect(layout, *zone)
            outlines[name] = canvas.create_rectangle(
                *rect, fill="", outline=ACCENT, width=outline_width,
                state="hidden", tags=("ambient", "hotspot_outline", f"hotspot_{name}"),
            )

        dust = []
        for i in range(14):
            bx = 20.0 + ((i * 53) % 360)
            by = 66.0 + ((i * 29) % 112)
            size = 1.35 if i % 4 == 0 else 1.0
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=(GOLD, MINT, ROSE, DUST)[i % 4],
                outline="", tags=("ambient", "ambient_motion", "dust"),
            )
            dust.append({
                "id": item, "bx": bx, "by": by, "phase": i * 0.83,
                "speed": 0.45 + (i % 4) * 0.12, "size": size,
            })

        rain = []
        for i in range(10):
            pane = ROOM_WINDOW_PANES[i % len(ROOM_WINDOW_PANES)]
            pane_w = max(1, pane[2] - pane[0] - 1)
            pane_h = max(1, pane[3] - pane[1] - 3)
            bx = pane[0] + (i * 7) % pane_w
            by = pane[1] + (i * 11) % pane_h
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=(ROSE, CREAM, MINT)[i % 3],
                outline="", tags=("ambient", "ambient_motion", "rain"),
            )
            rain.append({
                "id": item, "pane": pane, "bx": bx, "by": by,
                "speed": 18.0 + (i % 4) * 3.5, "length": 2.0 + (i % 3),
            })

        crt_scan = []
        for i in range(2):
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=ACCENT_DIM, outline="",
                tags=("ambient", "ambient_motion", "crt_scan"),
            )
            crt_scan.append({"id": item, "offset": i * 19})
        crt_glitch = canvas.create_rectangle(
            0, 0, 1, 1, fill=GOLD, outline="", state="hidden",
            tags=("ambient", "ambient_motion", "crt_glitch"),
        )

        lamp = canvas.create_rectangle(
            0, 0, 1, 1, fill=GOLD, outline="",
            tags=("ambient", "ambient_motion", "lamp"),
        )

        plant = []
        for i, (px, py) in enumerate(((104, 109), (127, 110), (123, 103))):
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=MINT, outline="",
                tags=("ambient", "ambient_motion", "plant"),
            )
            plant.append({"id": item, "x": px, "y": py, "phase": i * 1.7})

        mug = []
        for i in range(3):
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=(CREAM, DUST, ROSE)[i % 3], outline="",
                tags=("ambient", "ambient_motion", "mug_steam"),
            )
            mug.append({"id": item, "x": 114 + i * 2, "phase": i * 1.6})

        shelf = []
        for x0, y0, x1, _y1 in ROOM_SHELF_CASES:
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=CREAM, outline="", state="hidden",
                tags=("ambient", "hover_fx", "shelf_case"),
            )
            shelf.append({"id": item, "rect": (x0, y0, x1)})

        records = []
        for x0, y0, x1, y1, color in ROOM_RECORD_SLEEVES:
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=color, outline="", state="hidden",
                tags=("ambient", "hover_fx", "record_sleeve"),
            )
            records.append({"id": item, "rect": (x0, y0, x1, y1)})

        knobs = []
        for cx, cy in ROOM_KNOBS:
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=NIGHT, outline="", state="hidden",
                tags=("ambient", "hover_fx", "panel_knob"),
            )
            knobs.append({"id": item, "cx": cx, "cy": cy})

        self._ambient = {
            "layout": layout,
            "reduce": reduce_motion,
            "outlines": outlines,
            "dust": dust,
            "rain": rain,
            "crt_scan": crt_scan,
            "crt_glitch": crt_glitch,
            "lamp": lamp,
            "plant": plant,
            "mug": mug,
            "shelf": shelf,
            "records": records,
            "knobs": knobs,
        }

        # Outlines sit above the rest of the ambient layer but still below
        # the puppy and the UI copy.
        for item in outlines.values():
            canvas.tag_raise(item)

        # Seed every pooled item with a real position. The clock will move
        # them from here without creating or deleting anything.
        self._animate_room_ambient(time.time(), 0)
        if reduce_motion:
            for entry in rain:
                canvas.itemconfigure(entry["id"], state="hidden")
            for entry in mug:
                canvas.itemconfigure(entry["id"], state="hidden")
        self._apply_room_hover()

    def _animate_room_ambient(self, now, tick=None):
        ambient = getattr(self, "_ambient", None)
        canvas = getattr(self, "_room_canvas", None)
        if not ambient or canvas is None:
            return
        layout = ambient.get("layout")
        if not layout:
            return
        tick = int(self._anim_tick if tick is None else tick)

        if ambient.get("reduce"):
            self._update_hover_overlays(tick, static=True)
            return

        try:
            if tick % 2 == 0:
                for mote in ambient["dust"]:
                    x = 12.0 + (
                        (mote["bx"] - 12.0 + tick * mote["speed"] * 0.055) % 376.0
                    )
                    y = mote["by"] + math.sin(tick * 0.03 + mote["phase"]) * 2.4
                    rect = self._room_rect(
                        layout, x, y, x + mote["size"], y + mote["size"]
                    )
                    canvas.coords(mote["id"], *rect)

            for drop in ambient["rain"]:
                pane_x0, pane_y0, pane_x1, pane_y1 = drop["pane"]
                travel = max(1.0, pane_y1 - pane_y0 - drop["length"])
                y = pane_y0 + (
                    (drop["by"] - pane_y0 + tick * drop["speed"] / 30.0) % travel
                )
                x = drop["bx"]
                rect = self._room_rect(
                    layout, x - 0.35, y, x + 0.35, y + drop["length"]
                )
                canvas.coords(drop["id"], *rect)

            hot_crt = self._room_hover == "crt"
            crt_boost = now < getattr(self, "_crt_boost_until", 0.0)
            scan_speed = 5.2 if (hot_crt or crt_boost) else 2.2
            scan_color = MINT if (hot_crt or crt_boost) else ACCENT_DIM
            for scan in ambient["crt_scan"]:
                y = 94.0 + ((tick * scan_speed + scan["offset"]) % 38.0)
                rect = self._room_rect(layout, 40.5, y, 99.5, y + 0.55)
                canvas.coords(scan["id"], *rect)
                canvas.itemconfigure(scan["id"], fill=scan_color)

            show_glitch = (
                hot_crt or crt_boost or (tick % 37 in (0, 1, 2))
            )
            glitch = ambient["crt_glitch"]
            if show_glitch:
                gx = 42.0 + ((tick * 13) % 54)
                gy = 95.0 + ((tick * 7) % 34)
                rect = self._room_rect(layout, gx, gy, gx + 3.0, gy + 0.55)
                canvas.coords(glitch, *rect)
                canvas.itemconfigure(
                    glitch, state="normal",
                    fill=GOLD if (tick // 3) % 2 else MINT,
                )
            else:
                canvas.itemconfigure(glitch, state="hidden")

            if tick % 6 == 0:
                lamp_color = CREAM if (tick // 6) % 9 < 2 else GOLD
                rect = self._room_rect(layout, 272, 70, 280, 72)
                canvas.coords(ambient["lamp"], *rect)
                canvas.itemconfigure(ambient["lamp"], fill=lamp_color)

            if tick % 3 == 0:
                for leaf in ambient["plant"]:
                    dx = int(round(math.sin(tick * 0.06 + leaf["phase"])))
                    dy = int(round(math.cos(tick * 0.045 + leaf["phase"]) * 0.5))
                    rect = self._room_rect(
                        layout, leaf["x"] + dx, leaf["y"] + dy,
                        leaf["x"] + dx + 1, leaf["y"] + dy + 1,
                    )
                    canvas.coords(leaf["id"], *rect)

            if tick % 2 == 0:
                for steam in ambient["mug"]:
                    phase = (tick * 0.08 + steam["phase"]) % 7.0
                    sy = 175.0 - phase
                    sx = steam["x"] + math.sin(tick * 0.05 + steam["phase"]) * 0.45
                    rect = self._room_rect(layout, sx, sy, sx + 1, sy + 1)
                    canvas.coords(steam["id"], *rect)

            self._update_hover_overlays(tick, static=False)
        except Exception:
            pass

    def _update_hover_overlays(self, tick, static=False):
        ambient = getattr(self, "_ambient", None)
        canvas = getattr(self, "_room_canvas", None)
        if not ambient or canvas is None:
            return
        layout = ambient.get("layout")
        if not layout:
            return
        hover = self._room_hover

        for idx, entry in enumerate(ambient.get("shelf", ())):
            if hover == "shelf":
                dy = 0 if static else (-1 if ((tick // 4) + idx) % 2 else 0)
                x0, y0, x1 = entry["rect"]
                rect = self._room_rect(layout, x0, y0 - 1 + dy, x1, y0 + 0.45 + dy)
                canvas.coords(entry["id"], *rect)
                canvas.itemconfigure(entry["id"], state="normal")
            else:
                canvas.itemconfigure(entry["id"], state="hidden")

        for idx, entry in enumerate(ambient.get("records", ())):
            if hover == "crate":
                dy = 0 if static else (-1 if ((tick // 5) + idx) % 2 else 0)
                x0, y0, x1, y1 = entry["rect"]
                rect = self._room_rect(layout, x0, y0 + dy, x1, y1 + dy)
                canvas.coords(entry["id"], *rect)
                canvas.itemconfigure(entry["id"], state="normal")
            else:
                canvas.itemconfigure(entry["id"], state="hidden")

        knob_steps = ((0, -2), (2, 0), (0, 2), (-2, 0))
        for idx, entry in enumerate(ambient.get("knobs", ())):
            if hover == "panel":
                step = 0 if static else (tick // 6 + idx) % 4
                dx, dy = knob_steps[step]
                cx, cy = entry["cx"], entry["cy"]
                rect = self._room_rect(
                    layout, cx + dx, cy + dy, cx + dx + 1, cy + dy + 1
                )
                canvas.coords(entry["id"], *rect)
                canvas.itemconfigure(entry["id"], state="normal")
            else:
                canvas.itemconfigure(entry["id"], state="hidden")

    def _apply_room_hover(self):
        ambient = getattr(self, "_ambient", None)
        canvas = getattr(self, "_room_canvas", None)
        if not ambient or canvas is None:
            return
        hover = self._room_hover
        for name, item in ambient.get("outlines", {}).items():
            try:
                if name == hover:
                    canvas.itemconfigure(
                        item, state="normal",
                        outline=CREAM if name != "crt" else GOLD,
                        width=max(1, int(round(ambient["layout"][0] * 0.42))),
                    )
                else:
                    canvas.itemconfigure(item, state="hidden")
            except Exception:
                pass

    def _set_room_hover(self, zone):
        if zone == self._room_hover:
            return
        self._room_hover = zone
        self._apply_room_hover()
        canvas = getattr(self, "_room_canvas", None)
        if canvas is not None:
            try:
                if zone in ("shelf", "panel", "crate"):
                    canvas.configure(cursor="hand2")
                elif zone == "crt":
                    canvas.configure(cursor="crosshair")
                else:
                    canvas.configure(cursor="")
            except Exception:
                pass
        try:
            self._update_hover_overlays(
                self._anim_tick, static=self._reduce_motion_enabled()
            )
        except Exception:
            pass

    def _on_room_canvas_motion(self, event):
        zone = None
        for name, bbox in getattr(self, "_room_hotspots", {}).items():
            if bbox[0] <= event.x <= bbox[2] and bbox[1] <= event.y <= bbox[3]:
                zone = name
                break
        self._set_room_hover(zone)

    def _on_room_canvas_leave(self, _event=None):
        self._set_room_hover(None)

    @staticmethod
    def _game_label(game):
        """Return a clean display name for a detector record or plain string."""
        if isinstance(game, dict):
            return str(
                game.get("name")
                or game.get("display_name")
                or game.get("proc")
                or game.get("exe")
                or "GAME"
            )
        return str(game or "GAME")

    def _redraw_room(self):
        canvas = getattr(self, "_room_canvas", None)
        self._raise_deck()
        self._room_redraw_job = None
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists():
                return
        except Exception:
            return

        w = max(1, canvas.winfo_width())
        h = max(1, canvas.winfo_height())
        if w < 80 or h < 80:
            return

        if self._room_pil is None or not HAS_PIL:
            try:
                canvas.delete("all")
                canvas.configure(bg=BG)
                canvas.create_text(
                    w // 2, h // 2, text="GAMEBEATS / THE DEN",
                    font=(F_PIXEL, -18, "bold"), fill=CREAM,
                )
            except Exception:
                pass
            return

        try:
            resampling = getattr(Image, "Resampling", Image)
            key = (w, h)
            if self._room_base_cache is None or self._room_base_key != key:
                self._room_base_cache = ImageOps.fit(
                    self._room_pil, (w, h), method=resampling.NEAREST,
                    centering=(0.5, 0.5),
                ).convert("RGBA")
                self._room_base_key = key
            base = self._room_base_cache.copy()
        except Exception:
            return

        now = time.time()
        sprite_name = self._puppy_frame_name(now)

        # The mascot is the big in-room puppy, centred over the player deck.
        # 64x72 authored pixels at 3x keeps the character on the same pixel
        # grid as the 400x250 room plate. The feet baseline is fixed.
        pw = max(96, int(round(w * 0.15)))
        ph = int(round(pw * 72 / 64))
        px = (w - pw) // 2
        paw_margin = int(round(ph * 2.0 / 72.0))
        perch_y = h - ph + paw_margin - 1
        py = max(0, perch_y)
        px = max(0, min(px, w - pw - 4))
        self._puppy_bbox = (px, py, px + pw, py + ph)
        self._room_puppy_base = (px, py, pw, ph)

        try:
            photo = ImageTk.PhotoImage(base.convert("RGB"))
            self._room_photo = photo
            if self._room_image_item is None:
                self._room_image_item = canvas.create_image(
                    0, 0, anchor="nw", image=photo, tags=("room_bg",)
                )
            else:
                canvas.itemconfigure(self._room_image_item, image=photo)
            canvas.tag_lower("room_bg")
            canvas.delete("overlay")
        except Exception:
            return

        # Pooled ambient layer: dust, rain, CRT scanlines, lamp pulse,
        # plant highlights, mug steam, and hover reactions. It is created
        # here (layout changes only) and moved by the master clock.
        self._build_room_ambient(canvas, w, h)

        # The puppy lives on its own canvas image item, so the animation loop
        # can swap frames without re-rendering the entire room. The item's
        # coordinates are written once here and never touched by the loop.
        self._draw_room_puppy(canvas, sprite_name, (px, py, pw, ph))

        # Small, dark contact shadow under the paws. The old gold/mint oval
        # read as an orange circle behind the mascot, so the glow is gone.
        try:
            sy = min(h - 1, py + ph - paw_margin)
            shadow_w = int(pw * 0.62)
            sx = px + (pw - shadow_w) // 2
            layers = (
                (0.00, 1.00, 5, 4),
                (0.10, 0.90, 3, 3),
                (0.22, 0.78, 2, 2),
            )
            shadow = None
            for inset, right, height, _ in layers:
                x0 = sx + int(shadow_w * inset)
                x1 = sx + int(shadow_w * right)
                shadow = canvas.create_rectangle(
                    x0, sy - height, x1, sy,
                    fill="#160C1A", outline="", stipple="gray50",
                    tags=("overlay", "puppy_shadow"),
                )
            if shadow is not None and self._room_puppy_item is not None:
                canvas.tag_lower(shadow, self._room_puppy_item)
                canvas.tag_lower("puppy_shadow", self._room_puppy_item)
        except Exception:
            pass

        # Greeting
        gx = int(w * 0.068)
        gy = int(h * 0.062)
        headline_size = max(25, int(w * 0.028))
        eyebrow_size = max(8, int(w * 0.0058))
        sub_size = max(14, int(w * 0.0110))
        headline = f"Good {self._time_of_day()}, Player 1 \u266a"
        try:
            canvas.create_rectangle(
                gx - eyebrow_size - 4, gy + 3,
                gx - eyebrow_size + 1, gy + 8,
                fill=MINT, outline="", tags=("overlay",),
            )
            canvas.create_text(
                gx + 1, gy + 1, text="A SOUNDTRACK FOR YOUR SIDE QUESTS",
                anchor="nw", font=(F_PIXEL, -eyebrow_size),
                fill=NIGHT, tags=("overlay",),
            )
            canvas.create_text(
                gx, gy, text="A SOUNDTRACK FOR YOUR SIDE QUESTS",
                anchor="nw", font=(F_PIXEL, -eyebrow_size),
                fill=ROSE, tags=("overlay",),
            )
            headline_y = gy + 18
            canvas.create_text(
                gx + 2, headline_y + 2, text=headline, anchor="nw",
                font=(F_SERIF, -headline_size, "italic"), fill=NIGHT,
                tags=("overlay",),
            )
            canvas.create_text(
                gx, headline_y, text=headline, anchor="nw",
                font=(F_SERIF, -headline_size, "italic"), fill=CREAM,
                tags=("overlay",),
            )
            sub_y = headline_y + headline_size + 11
            canvas.create_text(
                gx + 1, sub_y + 1,
                text="The world can wait. Stay for one more song.",
                anchor="nw", font=(F_RETRO, -sub_size),
                fill=NIGHT, tags=("overlay",),
            )
            canvas.create_text(
                gx, sub_y, text="The world can wait. Stay for one more song.",
                anchor="nw", font=(F_RETRO, -sub_size),
                fill=ROSE, tags=("overlay",),
            )
        except Exception:
            pass

        # Room object labels
        label_x = int(w * 0.79)
        self._draw_room_label(canvas, label_x, int(h * 0.36),
                              "THE GAME SHELF", "lbl_shelf",
                              lambda: self._nav("games"))
        self._draw_room_label(canvas, label_x, int(h * 0.60),
                              "TWEAK A LITTLE", "lbl_board",
                              lambda: self._nav("settings"))
        self._draw_room_label(canvas, int(w * 0.78), int(h * 0.845),
                              "DIG FOR A VIBE", "lbl_crate",
                              lambda: self._nav("playlists"))

        # Pet heart (tap feedback only; the mascot itself never floats).
        try:
            if time.time() < getattr(self, "_heart_until", 0.0):
                canvas.create_text(
                    px + pw // 2, py - 26, text="\u2665",
                    anchor="s", font=(F_RETRO, -max(20, int(w * 0.015))),
                    fill=ORANGE, tags=("overlay",),
                )
        except Exception:
            pass

        # Game status caption (real detector state)
        try:
            cap_x = int(w * 0.665)
            cap_y = int(h * 0.935)
            game = getattr(self, "current_game", None)
            if game:
                line, color = f"\u25cf {self._game_label(game).upper()} DETECTED", MINT
            else:
                line, color = "\u25cb NO GAME RUNNING", TEXT_MUTED
            cap_size = max(8, int(w * 0.0052))
            canvas.create_text(
                cap_x, cap_y, text=line, anchor="nw",
                font=(F_PIXEL, -cap_size), fill=color, tags=("overlay",),
            )
            canvas.create_text(
                cap_x, cap_y + int(cap_size * 1.7),
                text="YOU PLAY. WE PRESS PLAY.",
                anchor="nw", font=(F_PIXEL, -max(7, cap_size - 1)),
                fill=WOOD, tags=("overlay",),
            )
        except Exception:
            pass

    def _draw_room_label(self, canvas, x, y, text, tag, command):
        try:
            fs = max(8, int(canvas.winfo_width() * 0.0056))
            pad = max(8, int(fs * 1.1))
            box_h = max(24, int(fs * 2.6))
            txt = canvas.create_text(
                x + pad, y + (box_h - fs) // 2 - 1, text=text, anchor="nw",
                font=(F_PIXEL, -fs), fill=GOLD, tags=("overlay", f"{tag}_txt"),
            )
            bbox = canvas.bbox(txt)
            if not bbox:
                return
            box_w = (bbox[2] - bbox[0]) + pad * 2 + int(fs * 1.8)
            box = canvas.create_rectangle(
                x, y, x + box_w, y + box_h, fill=NIGHT, outline=WOOD,
                width=max(2, int(fs * 0.22)), tags=("overlay", f"{tag}_box"),
            )
            canvas.tag_raise(txt, box)
            canvas.create_text(
                x + box_w - pad, y + box_h // 2, text="\u2197", anchor="e",
                font=(F_RETRO, -max(12, int(fs * 1.5))), fill=CREAM,
                tags=("overlay", f"{tag}_arrow"),
            )
            for part in (f"{tag}_txt", f"{tag}_box", f"{tag}_arrow"):
                canvas.tag_bind(part, "<Button-1>", lambda e, c=command: c())
                canvas.tag_bind(
                    part, "<Enter>",
                    lambda e, t=tag: self._label_hover(canvas, t, True),
                )
                canvas.tag_bind(
                    part, "<Leave>",
                    lambda e, t=tag: self._label_hover(canvas, t, False),
                )
        except Exception:
            pass

    def _label_hover(self, canvas, tag, entering):
        try:
            if entering:
                canvas.itemconfigure(f"{tag}_box", fill=ACCENT, outline=T.ACCENT_HOV)
                canvas.itemconfigure(f"{tag}_txt", fill=BG)
                canvas.itemconfigure(f"{tag}_arrow", fill=BG)
                canvas.configure(cursor="hand2")
            else:
                canvas.itemconfigure(f"{tag}_box", fill=NIGHT, outline=WOOD)
                canvas.itemconfigure(f"{tag}_txt", fill=GOLD)
                canvas.itemconfigure(f"{tag}_arrow", fill=CREAM)
                canvas.configure(cursor="")
        except Exception:
            pass
        zone = {"lbl_shelf": "shelf", "lbl_board": "panel",
                "lbl_crate": "crate"}.get(tag)
        if zone:
            self._set_room_hover(zone if entering else None)

    def _on_room_canvas_click(self, event):
        try:
            x0, y0, x1, y1 = self._puppy_bbox
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._pet_puppy()
                return
        except Exception:
            pass
        try:
            if self._room_hover == "crt":
                self._crt_boost_until = time.time() + 0.9
                self._on_room_canvas_motion(event)
        except Exception:
            pass

    def _pet_puppy(self):
        now = time.time()
        self._heart_until = now + 1.2
        self._puppy_mood_until = now + 1.2
        if hasattr(self, "status_log_lbl"):
            self.status_log_lbl.configure(text="Puppy says hi.", text_color=GOLD)
        self._redraw_room()
        try:
            self.root.after(1250, self._redraw_room)
        except Exception:
            pass

    def _draw_cart_cassette(self, canvas):
        """Build the cassette once; the master clock only turns its spokes."""
        if canvas is None:
            return
        try:
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 20 or h < 10:
                return
            key = (int(w), int(h))
            if self._cart_key != key or self._cart_items is None:
                canvas.delete("cart")
                cy = h // 2
                items = {"cy": cy, "reels": []}
                canvas.create_rectangle(
                    0, 0, w, h, fill=NIGHT, outline="", tags=("cart",),
                )
                canvas.create_line(4, 4, w - 4, 4, fill=WOOD, tags=("cart",))
                canvas.create_line(4, h - 4, w - 4, h - 4, fill=WOOD, tags=("cart",))
                for idx, cx in enumerate((int(w * 0.30), int(w * 0.70))):
                    canvas.create_oval(
                        cx - 7, cy - 7, cx + 7, cy + 7,
                        fill=GOLD, outline=WOOD, tags=("cart",),
                    )
                    spokes = []
                    for _k in range(3):
                        spokes.append(canvas.create_line(
                            cx, cy, cx, cy, fill=WOOD, width=1, tags=("cart",)
                        ))
                    canvas.create_oval(
                        cx - 2, cy - 2, cx + 2, cy + 2,
                        fill=NIGHT, outline="", tags=("cart",),
                    )
                    items["reels"].append({"cx": cx, "spokes": spokes})
                canvas.create_line(6, cy, w - 6, cy, fill=WOOD, tags=("cart",))
                self._cart_items = items
                self._cart_key = key
            self._update_cart_cassette(time.time())
        except Exception:
            pass

    def _update_cart_cassette(self, now):
        items = getattr(self, "_cart_items", None)
        canvas = getattr(self, "_cart_canvas", None)
        if not items or canvas is None:
            return
        playing = bool(
            getattr(self, "_is_playing", False)
            or getattr(self, "_spotify_audio_active", False)
        )
        phase = now * 5.2 if playing else 0.0
        cy = items["cy"]
        try:
            for idx, reel in enumerate(items["reels"]):
                cx = reel["cx"]
                for k, spoke in enumerate(reel["spokes"]):
                    angle = phase + idx * 0.7 + k * (2 * math.pi / 3)
                    canvas.coords(
                        spoke,
                        cx, cy,
                        cx + 5 * math.cos(angle),
                        cy + 5 * math.sin(angle),
                    )
        except Exception:
            pass

    # ── Puppy + VU animation ─────────────────────────────────────────────────

    def _start_puppy_animation(self):
        if getattr(self, "_puppy_job", None) is not None:
            return
        try:
            # One 30 Hz clock for every animated element in the room.
            self._puppy_job = self.root.after(380, self._master_clock)
        except Exception:
            self._puppy_job = None

    def _stop_puppy_animation(self):
        try:
            if getattr(self, "_puppy_job", None):
                self.root.after_cancel(self._puppy_job)
        except Exception:
            pass
        self._puppy_job = None

    def _master_clock(self):
        self._puppy_job = None
        if getattr(self, "_closing", False):
            return
        if getattr(self, "_current_page", "") != "main":
            return

        now = time.time()
        self._anim_tick = getattr(self, "_anim_tick", 0) + 1
        tick = self._anim_tick

        try:
            if self._room_puppy_item is None:
                self._redraw_room()
            else:
                self._animate_room_puppy(now)
        except Exception:
            pass

        try:
            self._animate_vu_tick(now)
        except Exception:
            pass

        try:
            self._update_cart_cassette(now)
        except Exception:
            pass

        try:
            self._animate_room_ambient(now, tick)
        except Exception:
            pass

        try:
            self._puppy_job = self.root.after(MASTER_TICK_MS, self._master_clock)
        except Exception:
            self._puppy_job = None

    def _animate_puppy(self):
        """Backwards-compatible entry point for the single master clock."""
        self._master_clock()

    def _stop_vu_animation(self):
        # The VU rides the master clock now; keep this hook for old callers.
        try:
            if getattr(self, "_vu_job", None):
                self.root.after_cancel(self._vu_job)
        except Exception:
            pass
        self._vu_job = None

    def _animate_vu_tick(self, now):
        playing = bool(
            getattr(self, "_is_playing", False)
            or getattr(self, "_spotify_audio_active", False)
        )
        peak = float(getattr(self, "_last_spotify_peak", 0.0) or 0.0)
        target = min(1.0, peak / 0.18) if playing else 0.0
        if self._reduce_motion_enabled():
            level = target
        else:
            level = getattr(self, "_vu_level", 0.0) * 0.55 + target * 0.45
        if target <= 0.0 and level < 0.005:
            level = 0.0
        self._vu_level = max(0.0, min(1.0, level))
        self._draw_vu()

    def _draw_vu(self):
        canvas = getattr(self, "_vu_canvas", None)
        if canvas is None:
            return
        try:
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 20 or h < 6:
                return
            bars = 21
            gap = 2
            bw = max(2, (w - (bars - 1) * gap) // bars)
            key = (int(w), int(h), bars, gap, bw)
            if self._vu_key != key:
                canvas.delete("vu_bars")
                self._vu_items = []
                self._vu_colors = []
                self._vu_heights = []
                for i in range(bars):
                    x = i * (bw + gap)
                    item = canvas.create_rectangle(
                        x, h - 3, x + bw, h, fill=SURFACE4, outline="",
                        tags=("vu_bars",),
                    )
                    self._vu_items.append(item)
                    self._vu_colors.append(SURFACE4)
                    self._vu_heights.append(3)
                self._vu_key = key

            level = max(0.0, min(1.0, getattr(self, "_vu_level", 0.0)))
            for i, item in enumerate(self._vu_items):
                frac = i / max(1, bars - 1)
                lit = frac <= level
                bh = 3 + int((h - 4) * (0.35 + 0.65 * frac)) if lit else 3
                if not lit:
                    color = SURFACE4
                elif frac < 0.60:
                    color = MINT
                elif frac < 0.85:
                    color = GOLD
                else:
                    color = ORANGE
                if self._vu_colors[i] != color:
                    canvas.itemconfigure(item, fill=color)
                    self._vu_colors[i] = color
                if self._vu_heights[i] != bh:
                    x = i * (bw + gap)
                    canvas.coords(item, x, h - bh, x + bw, h)
                    self._vu_heights[i] = bh
        except Exception:
            pass

    def _update_deck_status(self):
        try:
            if getattr(self, "_is_playing", False):
                text, color = "\u25b6  NOW PLAYING", MINT
            elif getattr(self, "current_game", None):
                text, color = "\u2161  LISTENING TO YOUR GAME", GOLD
            else:
                text, color = "\u25cb  STANDING BY", TEXT_MUTED
            self.deck_status_lbl.configure(text=text, text_color=color)
        except Exception:
            pass

    # ── PLAYLISTS PAGE ────────────────────────────────────────────────────────

    def _build_playlists_page(self):
        p = self._make_page_body(self._page_playlists)

        hdr = T.object_header(
            p, "THE DEN / A LITTLE DISCOVERY", "Go on. Dig a little.",
            "Pick a playlist for the next side quest.",
            on_back=lambda: self._nav("main"),
        )

        btn_row = ctk.CTkFrame(hdr, fg_color="transparent", corner_radius=0)
        btn_row.pack(side=tk.RIGHT, anchor="n", padx=(10, 0))

        self.pl_add_btn = T.primary_button(
            btn_row, "+ ADD LINK", command=self._add_playlist_link,
            width=116, height=34,
        )
        self.pl_add_btn.pack(side=tk.RIGHT, padx=(6, 0))

        T.ghost_button(
            btn_row, "\u21ba REFRESH", command=self._load_playlists,
            width=108, height=34,
        ).pack(side=tk.RIGHT)

        self.pl_status_lbl = ctk.CTkLabel(
            p, text="Connect Spotify in Control Panel to load playlists.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), wraplength=620, justify=tk.LEFT, anchor="w",
        )
        self.pl_status_lbl.pack(fill=tk.X, pady=(0, 10))

        self.pl_inner = ctk.CTkScrollableFrame(
            p, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=DECK, scrollbar_button_hover_color=WOOD,
        )
        self.pl_inner.pack(fill=tk.BOTH, expand=True)

    # ── GAMES PAGE ───────────────────────────────────────────────────────

    def _build_games_page(self):
        p = self._make_page_body(self._page_games)
        GamesPage(
            p,
            on_games_changed=lambda: self._log("Game list updated."),
            on_back=lambda: self._nav("main"),
        ).pack(fill=tk.BOTH, expand=True)

    # ── BLOCKED PAGE ──────────────────────────────────────────────────────────

    def _build_blocked_page(self):
        p = self._make_page_body(self._page_blocked)

        hdr = T.object_header(
            p, "THE DEN / NOT TODAY", "Tapes on the naughty shelf.",
            "Blocked playlists stay here until you give them another chance.",
            on_back=lambda: self._nav("main"),
        )
        T.ghost_button(
            hdr, "\u21ba  REFRESH", command=self._refresh_blocked_page,
            width=108, height=34,
        ).pack(side=tk.RIGHT, anchor="n", padx=(10, 0))

        self.blocked_status_lbl = ctk.CTkLabel(
            p, text="Playlists blocked from auto-play appear here.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), wraplength=620, justify=tk.LEFT, anchor="w",
        )
        self.blocked_status_lbl.pack(fill=tk.X, pady=(0, 10))

        self.blocked_inner = ctk.CTkScrollableFrame(
            p, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=DECK, scrollbar_button_hover_color=WOOD,
        )
        self.blocked_inner.pack(fill=tk.BOTH, expand=True)

    def _refresh_blocked_page(self):
        if not hasattr(self, "blocked_inner"):
            return
        for w in self.blocked_inner.winfo_children():
            w.destroy()

        blocked = self._blocked_playlists()
        if not blocked:
            self.blocked_status_lbl.configure(
                text="No blocked playlists \u2014 your crate is clear.",
                text_color=TEXT_MUTED)
            empty = ctk.CTkFrame(
                self.blocked_inner, fg_color=SURFACE2, corner_radius=0,
                border_width=2, border_color=WOOD,
            )
            empty.pack(fill=tk.X, pady=(6, 4), padx=(0, 4))
            ctk.CTkLabel(
                empty, text="\u2205", fg_color="transparent", text_color=GOLD,
                font=T.retro_font(44),
            ).pack(pady=(22, 4))
            ctk.CTkLabel(
                empty, text="Nothing blocked. Yet.", fg_color="transparent",
                text_color=TEXT, font=T.serif_font(24, "italic"),
            ).pack()
            ctk.CTkLabel(
                empty,
                text="Use BLOCK on the deck when a mix is not the vibe. It will wait here.",
                fg_color="transparent", text_color=TEXT_MUTED,
                font=T.retro_font(16),
            ).pack(pady=(4, 24))
            return

        count = len(blocked)
        self.blocked_status_lbl.configure(
            text=f"{count} blocked playlist{'s' if count != 1 else ''} \u00b7 unblock to give it another chance",
            text_color=TEXT_SEC)

        for item in blocked:
            uri  = item.get("uri", "")
            name = item.get("name") or uri.split(":")[-1] or "Blocked playlist"
            query = item.get("query", "")

            row = ctk.CTkFrame(
                self.blocked_inner, fg_color=SURFACE2, corner_radius=0,
                border_width=2, border_color=NIGHT,
            )
            row.pack(fill=tk.X, pady=5, padx=(0, 4))

            badge = ctk.CTkFrame(row, fg_color="#3A1A10", width=52, height=52, corner_radius=0)
            badge.pack(side=tk.LEFT, padx=(12, 12), pady=12)
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text="\u2205", fg_color="transparent", text_color=AMBER,
                         font=T.retro_font(24)).pack(expand=True)

            col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
            col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8), pady=14)

            ctk.CTkLabel(
                col, text=name, fg_color="transparent", text_color=TEXT,
                font=T.retro_font(20, "bold"), anchor="w", justify=tk.LEFT,
                wraplength=620,
            ).pack(anchor="w", fill=tk.X)

            detail = (query or uri)[:100]
            ctk.CTkLabel(
                col, text=detail, fg_color="transparent", text_color=TEXT_MUTED,
                font=T.retro_font(16), anchor="w", justify=tk.LEFT,
                wraplength=620,
            ).pack(anchor="w", fill=tk.X, pady=(2, 0))

            T.pixel_button(
                row, text="UNBLOCK",
                command=lambda u=uri: (
                    self._unblock_playlist(u),
                    self._refresh_blocked_page(),
                ),
                width=104, height=32,
            ).pack(side=tk.RIGHT, padx=(0, 12), pady=12)

    # ── SETTINGS PAGE ─────────────────────────────────────────────────────────

    def _build_settings_page(self):
        p = self._make_page_body(self._page_settings)

        T.object_header(
            p, "THE DEN / MAKE IT YOURS", "Fine-tune your corner.",
            "The real knobs behind your side quests.",
            on_back=lambda: self._nav("main"),
        )

        inner = ctk.CTkScrollableFrame(
            p, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=DECK, scrollbar_button_hover_color=WOOD,
        )
        inner.pack(fill=tk.BOTH, expand=True)

        board = ctk.CTkFrame(
            inner, fg_color=SURFACE2, corner_radius=0,
            border_width=3, border_color=WOOD,
        )
        board.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        board_head = ctk.CTkFrame(board, fg_color="transparent", corner_radius=0)
        board_head.pack(fill=tk.X, padx=18, pady=(14, 0))
        ctk.CTkLabel(
            board_head, text="CONTROL PANEL  /  EVERYTHING SAVES INSTANTLY",
            fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(10, "bold"), anchor="w",
        ).pack(side=tk.LEFT)
        ctk.CTkLabel(
            board_head, text="\u25cf  LIVE", fg_color="transparent",
            text_color=MINT, font=T.pixel_font(11, "bold"), anchor="e",
        ).pack(side=tk.RIGHT)

        content = ctk.CTkFrame(board, fg_color="transparent", corner_radius=0)
        content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 16))

        # ── Auto Playlists ────────────────────────────────────────────────────
        T.section_header(content, "01 / AUTO PLAYLISTS")
        ap = self._card(content)

        ctk.CTkLabel(
            ap,
            text="How many of your Spotify playlists GameBeats can choose from when a game starts.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(16), anchor="w", justify=tk.LEFT,
            wraplength=760,
        ).pack(fill=tk.X, pady=(0, 8))

        pick_row = ctk.CTkFrame(ap, fg_color="transparent", corner_radius=0)
        pick_row.pack(fill=tk.X, pady=(0, 8))

        ctk.CTkLabel(
            pick_row, text="Playlists to consider", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(16),
        ).pack(side=tk.LEFT)

        pick_spin = ctk.CTkFrame(pick_row, fg_color="transparent", corner_radius=0)
        pick_spin.pack(side=tk.RIGHT)

        ctk.CTkEntry(
            pick_spin, width=42, height=28, textvariable=self.playlist_limit_var,
            fg_color=NIGHT, border_color=WOOD, corner_radius=0, justify="center",
            text_color=TEXT, font=T.retro_font(16),
        ).pack(side=tk.LEFT, padx=2)

        def _pick_dec():
            val = max(1, self.playlist_limit_var.get() - 1)
            self.playlist_limit_var.set(val)
            self._save_auto_playlist_settings()

        def _pick_inc():
            val = min(20, self.playlist_limit_var.get() + 1)
            self.playlist_limit_var.set(val)
            self._save_auto_playlist_settings()

        T.pixel_button(pick_spin, "-", command=_pick_dec, width=26, height=28).pack(
            side=tk.LEFT, padx=1)
        T.pixel_button(pick_spin, "+", command=_pick_inc, width=26, height=28).pack(
            side=tk.LEFT, padx=1)

        T.rule(ap, color=BORDER, pady=(2, 8))

        ctk.CTkLabel(
            ap,
            text="How long to wait before pausing or resuming after the game gets loud or quiet.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(16), anchor="w", justify=tk.LEFT,
            wraplength=760,
        ).pack(fill=tk.X, pady=(0, 6))

        resume_row = ctk.CTkFrame(ap, fg_color="transparent", corner_radius=0)
        resume_row.pack(fill=tk.X)

        ctk.CTkLabel(
            resume_row, text="Pause / resume delay", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(17),
        ).pack(side=tk.LEFT)

        resume_spin = ctk.CTkFrame(resume_row, fg_color="transparent", corner_radius=0)
        resume_spin.pack(side=tk.RIGHT)

        ctk.CTkEntry(
            resume_spin, width=42, height=28, textvariable=self.resume_delay_var,
            fg_color=NIGHT, border_color=WOOD, corner_radius=0, justify="center",
            text_color=TEXT, font=T.retro_font(16),
        ).pack(side=tk.LEFT, padx=2)

        def _resume_dec():
            val = max(1, self.resume_delay_var.get() - 1)
            self.resume_delay_var.set(val)
            self._save_audio_settings()

        def _resume_inc():
            val = min(30, self.resume_delay_var.get() + 1)
            self.resume_delay_var.set(val)
            self._save_audio_settings()

        T.pixel_button(resume_spin, "-", command=_resume_dec, width=26, height=28).pack(
            side=tk.LEFT, padx=1)
        T.pixel_button(resume_spin, "+", command=_resume_inc, width=26, height=28).pack(
            side=tk.LEFT, padx=1)

        ctk.CTkLabel(
            resume_row, text="sec", fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(13),
        ).pack(side=tk.RIGHT, padx=(0, 6))

        if HAS_WINREG:
            T.rule(ap, color=BORDER, pady=(10, 8))
            startup_row = ctk.CTkFrame(ap, fg_color="transparent", corner_radius=0)
            startup_row.pack(fill=tk.X)
            ctk.CTkLabel(
                startup_row, text="Start GameBeats with Windows", fg_color="transparent",
                text_color=TEXT, font=T.retro_font(17),
            ).pack(side=tk.LEFT)
            ctk.CTkSwitch(
                startup_row, variable=self.startup_var, text="",
                command=self._toggle_startup, width=38, height=19,
                fg_color=SURFACE4, progress_color=MINT,
                button_color=CREAM, button_hover_color=GOLD,
                border_width=0, corner_radius=10,
            ).pack(side=tk.RIGHT, padx=2)

        # ── Puppy Overlay ─────────────────────────────────────────────────────
        T.section_header(content, "02 / PUPPY OVERLAY", pady=(14, 6))
        ov = self._card(content)

        ov_row = ctk.CTkFrame(ov, fg_color="transparent", corner_radius=0)
        ov_row.pack(fill=tk.X)

        puppy_path = _design_asset_path("puppy_design", "encore.png")
        if puppy_path and HAS_PIL:
            try:
                pil = Image.open(puppy_path).convert("RGBA")
                photo = ctk.CTkImage(light_image=pil, dark_image=pil, size=(88, 99))
                self._settings_puppy_img = photo
                ctk.CTkLabel(ov_row, image=photo, text="").pack(
                    side=tk.LEFT, padx=(0, 16))
            except Exception:
                pass

        ov_copy = ctk.CTkFrame(ov_row, fg_color="transparent", corner_radius=0)
        ov_copy.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ctk.CTkLabel(
            ov_copy, text="Your player two, always on your side.", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(19), anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            ov_copy,
            text="A small controller appears during games for manual pause, resume, skip, and playlist rescue. Drag it anywhere.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(16), anchor="w", justify=tk.LEFT, wraplength=600,
        ).pack(fill=tk.X, pady=(3, 8))

        T.primary_button(
            ov_copy, "\u25a3  OPEN OVERLAY", command=self._show_control_overlay,
            width=160, height=32,
        ).pack(anchor="w")

        # ── Keep Music Playing ────────────────────────────────────────────────
        T.section_header(content, "03 / KEEP MUSIC PLAYING", pady=(14, 6))
        km = self._card(content)

        km_row = ctk.CTkFrame(km, fg_color="transparent", corner_radius=0)
        km_row.pack(fill=tk.X)

        km_copy = ctk.CTkFrame(km_row, fg_color="transparent", corner_radius=0)
        km_copy.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ctk.CTkLabel(
            km_copy, text="Don't pause for game audio", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(19), anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            km_copy,
            text="Keep Spotify playing even when the game gets loud. Calls, videos, and other PC audio still pause it.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(16), anchor="w", justify=tk.LEFT, wraplength=600,
        ).pack(fill=tk.X, pady=(3, 0))

        ctk.CTkSwitch(
            km_row, variable=self.seamless_music_var,
            command=self._save_player_settings, text="",
            fg_color=SURFACE4, progress_color=MINT,
            button_color=CREAM, button_hover_color=GOLD,
            width=38, height=19, border_width=0, corner_radius=10,
        ).pack(side=tk.RIGHT, padx=(14, 2))

        T.info_banner(
            content,
            "Your settings and Spotify login live in AppData and are kept across updates.",
            fg=ROSE,
        ).pack(fill=tk.X, pady=(12, 4))


    # ── LOGIC ─────────────────────────────────────────────────────────────────

    def _ui_log_message(self, msg):
        text = str(msg or "").strip()
        if not text:
            return None
        low = text.lower()

        if any(k in low for k in (
            "audio monitor", "stealth mode", "using installed",
            "spotify_web_profile", "login window opened",
        )):
            return None
        if "silent login check" in low and "logged in" in low:
            return "Spotify ready."
        if "session expired" in low:
            return "Spotify session expired \u2014 log in again."
        if "browser kept warm" in low:
            return "Web player ready."
        if "spotify connected" in low:
            return "Music ready."

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
        if "other audio detected" in low and "paused" in low:
            return "Other audio detected - music paused."
        if "other audio quiet" in low and "resumed" in low:
            return "Other audio quiet - music resumed."
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
        self._refresh_connection_ui()

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
        self._refresh_connection_ui()
        try:
            if hasattr(self, "deck_artist_lbl"):
                self.deck_artist_lbl.configure(text="Spotify ready \u00b7 waiting for a track")
        except Exception:
            pass
        # If the game detector already found a game before the web player
        # finished starting, the first auto-play attempt was skipped. Retry
        # once the player is ready.
        game = getattr(self, "current_game", None)
        if game:
            self.root.after(800, lambda g=game: self._autoplay_for_game(g))
            # The detector may have fired before the player existed. Make
            # sure other-app audio monitoring is running now that it does.
            self.root.after(900, lambda g=game: self._ensure_audio_monitor(g))

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
        p = self._make_page_body(self._page_faq)

        T.object_header(
            p, "THE DEN / FIELD NOTES", "A little help for the side quest.",
            "Everything you need to keep the music playing.",
            on_back=lambda: self._nav("main"),
        )

        inner = ctk.CTkScrollableFrame(
            p, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=DECK, scrollbar_button_hover_color=WOOD,
        )
        inner.pack(fill=tk.BOTH, expand=True)

        # Content Cards
        self._section_lbl(inner, "Important Information")
        c1 = self._card(inner)
        
        ctk.CTkLabel(
            c1, text="Not a Spotify Replacement", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(10, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c1, text="GameBeats is a companion tool designed to seamlessly integrate with your existing setup. It is not a standalone player; you must have the official Spotify client installed and running to use this application.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c1, text="Spotify Free Users", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(10, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c1, text="Supporting free Spotify accounts required overcoming significant technical limitations, but we made it happen. Please note that on first start, the free-tier desktop client might be a bit clunky to connect to. We apologize for any inconvenience, but it should work smoothly most of the time.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

        self._section_lbl(inner, "Important Setup Steps")
        c_web = self._card(inner)
        
        ctk.CTkLabel(
            c_web, text="1. One-Time Login Window", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c_web, text="On your first run, a secondary Spotify window will open. You MUST log in to Spotify here to establish the connection. Crucially, make sure you log in using the exact same Spotify account that is currently active on your main Spotify Desktop app.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c_web, text="2. Do Not Close the Helper Window", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c_web, text="While a game is running, you may notice this helper window remain open in the background. Please DO NOT close this window manually! It is required to maintain the connection. If you close it, your music will stop syncing.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c_web, text="3. Desktop App Required", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c_web, text="Even with the helper window open, you must always have the official Spotify Desktop application running on your PC for the app to route audio and detect playback correctly.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

        self._section_lbl(inner, "Best Practices")
        c2 = self._card(inner)
        
        ctk.CTkLabel(
            c2, text="1. Official Spotify Client Only", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="Please ensure you are using the Spotify Desktop client downloaded directly from the official Spotify website (.exe). GameBeats does not support the Microsoft Store version.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))
        
        ctk.CTkLabel(
            c2, text="2. Dedicated Playback Device", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="For the best experience, ensure your Spotify account is actively playing only on your local desktop client. Remote playback from other devices may interrupt the application's tracking.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c2, text="3. Adding Games Correctly", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="When adding games to your library, please select the actual game executable (.exe) from your installation folder. Avoid using desktop shortcuts or Steam URL links, as these cannot be properly tracked.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        ctk.CTkLabel(
            c2, text="4. Audio Capture & Muting", fg_color="transparent", text_color=TEXT,
            font=T.pixel_font(11, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 4))
        
        ctk.CTkLabel(
            c2, text="GameBeats listens to your game's audio to automatically pause and resume music. Do not mute your games or Spotify in the Windows Volume Mixer, otherwise the detection will not work.",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(16),
            wraplength=820, justify=tk.LEFT, anchor="w"
        ).pack(fill=tk.X)

        self._section_lbl(inner, "Support & Contact")
        c3 = self._card(inner)
        
        ctk.CTkLabel(
            c3, text="If something isn't working... have you tried turning it off and on again? Restarting the app fixes most issues!\n\nJokes aside, if you need further assistance or have recommendations, feel free to contact me at amongkencod10@gmail.com.\n\nThank you for your purchase, and have fun!",
            fg_color="transparent", text_color=TEXT, font=T.retro_font(16, slant="italic"),
            wraplength=820, justify=tk.LEFT, anchor="w"
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
        # Start the audio monitor for *every* detected game, even if music is
        # already playing. Previously this only happened inside the auto-play
        # success path, so if the app had already started a playlist (or the
        # user pressed Play first), other-app audio was never watched and
        # music no longer paused. This is the core auto-pause regression.
        self.root.after(0, lambda g=info: self._ensure_audio_monitor(g))
        mood_info = MOOD_TO_PLAYLIST.get(info["mood"], {})
        color = mood_info.get("color", ACCENT)
        self.root.after(0, lambda: (
            self.game_banner.configure(text=str(info["name"]).upper(), text_color=color),
            self.mood_lbl.configure(
                text=f"Mood: {mood_info.get('name', info['mood'])}  \u00b7  loud game audio pauses music\u2026"),
            self._set_status(info["name"], color),
            self._log(f"Game running: {info['name']}"),
            self._set_game_icon(info),
            self._update_deck_status(),
            self._redraw_room(),
        ))
        # The detector runs in its own thread.  Do the auto-play decision on
        # the Tk thread: reading Tk variables (auto_mode) from the detector
        # thread can fail before the main loop starts, leaving startup with a
        # detected game but no music.
        self.root.after(0, lambda: self._autoplay_for_game(info))

    def _autoplay_for_game(self, info):
        """Start music for a detected game on the Tk thread."""
        if not info or not self.spotify:
            return
        if getattr(self, "_autoplay_pending", False):
            return
        if getattr(self, "_spotify_started_by_us", False):
            return
        if getattr(self, "_play_in_progress", False):
            return
        try:
            if not self.auto_mode.get():
                return
        except Exception:
            return

        self._autoplay_pending = True
        custom_uri = info.get("spotify_playlist_uri", "")
        if custom_uri:
            self._log(f"Auto-play: playing assigned playlist for {info['name']}…")

            def _play_custom_after_silent():
                # Block auto-pause/resume for the entire automation window
                # (silent track launch + browser open + playlist start).
                self._automation_in_progress = True
                try:
                    self._launch_spotify_with_silent_track()
                    self._play_custom_playlist_for_game(info, custom_uri)
                finally:
                    self._automation_in_progress = False
                    self._autoplay_pending = False

            threading.Thread(target=_play_custom_after_silent, daemon=True).start()
            return

        self._log(f"Auto-play: sending music to Spotify web player for {info['name']}…")

        def _play_query_after_silent():
            # Block auto-pause/resume for the entire automation window
            # (silent track launch + browser open + playlist start).
            self._automation_in_progress = True
            try:
                self._launch_spotify_with_silent_track()
                self._play_query_for_game(info, force_new=True)
            finally:
                self._automation_in_progress = False
                self._autoplay_pending = False

        threading.Thread(target=_play_query_after_silent, daemon=True).start()

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
            self.game_banner.configure(text="NO SAVED GAME RUNNING", text_color=TEXT_MUTED),
            self.mood_lbl.configure(text="Waiting for a game"),
            self.playlist_display_lbl.configure(text="PLAYLIST: \u2014"),
            self.track_lbl.configure(text="Nothing playing"),
            self.deck_artist_lbl.configure(text="Connect Spotify in Control Panel"),
            self._set_status("Watching games", ACCENT),
            self._clear_game_icon(),
            self._log("Game closed \u2014 music paused."),
            self._update_deck_status(),
            self._redraw_room(),
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
                    # Explicit successful start: show the pause icon. Audio
                    # meter ticks must never do this on their own.
                    self._set_play_btn_icon(True, force_btn=True)
                    self._remember_current_playlist(picked_uri, picked_name, picked_query, reset_pause_flags=True)
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
            # Do NOT auto-start a different playlist here. A slow web player,
            # DRM hiccup, or a single failed verification used to make the app
            # jump to another mix, which users experienced as "it starts
            # another playlist" after pause/resume. Report the failure and let
            # the user press "Try another" explicitly.
            try:
                failed_uri = getattr(self.spotify, "_last_uri", "") if self.spotify else ""
                if failed_uri and failed_uri not in self._tried_playlist_uris:
                    self._tried_playlist_uris.append(failed_uri)
            except Exception:
                pass

            self._playlist_end_pending = False
            err = getattr(self.spotify, "_last_error", "") or "No playlist found"
            self._log(f"⚠ Playlist did not start: {err[:100]}")
            self._log("No playlist was switched automatically — use Try another if needed.")

    def _auto_pause_allowed(self, spotify_loud: bool = False) -> bool:
        """True when game/other audio should pause Spotify.

        Requires that music is actually playing, but deliberately does *not*
        require that GameBeats started the playlist. Otherwise music that was
        already playing (or whose autoplay failed) would never pause for a
        game or another app's audio.
        """
        music_active = bool(
            getattr(self, "_is_playing", False)
            or getattr(self, "_spotify_audio_active", False)
            or spotify_loud
            # If we started the playlist, trust that over a temporarily blind
            # audio meter (e.g. the desktop sidecar is the audible source).
            or getattr(self, "_spotify_started_by_us", False)
        )
        return bool(
            self.spotify
            and self.auto_mode.get()
            and not self._seamless_music_enabled()
            and music_active
            and not getattr(self, "_manual_paused", False)
            and not getattr(self, "_user_paused_flag", False)
        )

    def _ensure_audio_monitor(self, info=None):
        """Make sure game/other-audio monitoring is running for this game."""
        info = info or getattr(self, "current_game", None)
        if not info or not self.spotify:
            return
        if getattr(self, "_audio_monitor_running", False):
            return
        try:
            self._start_audio_monitor(info)
        except Exception as ex:
            try:
                self._log(f"Could not start audio monitor: {ex}")
            except Exception:
                pass

    def _start_audio_monitor(self, info):
        self._stop_audio_monitor()
        if not HAS_PROCESS_LOOPBACK and not HAS_PYCAW:
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
        self._audio_source_refresh_ts = time.time()
        self._audio_source_warmup_until = time.time() + 30.0
        self._playlist_audio_armed = False
        self._spotify_loud_streak = 0
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
        self.root.after(0, lambda b=backend: self._log(
            f"Audio monitor: {b}; other-audio meter "
            f"{'ready' if HAS_PYCAW else 'unavailable'}"))
        # Point the monitor at the component that actually produces music.
        # In web mode that is the automated browser, not spotify.exe (which may
        # only be a silent sidecar). Listening to the sidecar made GameBeats
        # believe a playing playlist had finished after a few seconds.
        try:
            if self._is_web_mode() and hasattr(self.spotify, "refresh_audio_source"):
                self.spotify.refresh_audio_source()
                self.root.after(0, lambda: self._log(
                    "Audio monitor: listening to web-player browser"))
            else:
                from core.audio_monitor import set_browser_audio_only, register_music_player_pids
                set_browser_audio_only(False)
                register_music_player_pids([])
                self.root.after(0, lambda: self._log(
                    "Audio monitor: listening to Spotify desktop"))
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

                    # Browsers spawn/replace renderer processes; re-scan the
                    # web-player PIDs periodically so loopback keeps working.
                    # During the first seconds after startup (while the
                    # automated browser is still coming up) poll quickly, so
                    # other-app audio can pause Spotify right away instead of
                    # waiting for the 10s steady-state refresh.
                    refresh_interval = (
                        1.5
                        if now < getattr(self, "_audio_source_warmup_until", 0.0)
                        else 10.0
                    )
                    if (self._is_web_mode()
                            and now - getattr(self, "_audio_source_refresh_ts", 0.0) >= refresh_interval):
                        self._audio_source_refresh_ts = now
                        try:
                            if self.spotify and hasattr(self.spotify, "refresh_audio_source"):
                                self.spotify.refresh_audio_source()
                                try:
                                    from core.audio_monitor import has_registered_music_pids
                                    if has_registered_music_pids():
                                        self._audio_source_warmup_until = 0.0
                                except Exception:
                                    pass
                        except Exception:
                            pass

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
                    other_loud = bool(getattr(self._game_audio, "other_loud", False))
                    other_peak = float(getattr(self._game_audio, "other_peak", 0.0) or 0.0)

                    # ── Update shared timestamps (used elsewhere in app) ──
                    if spotify_loud:
                        self._last_spotify_loud_ts = now
                        self._spotify_loud_streak = int(
                            getattr(self, "_spotify_loud_streak", 0)
                        ) + 1
                        # Require ~1.5s of sustained audio before re-arming
                        # the end-of-playlist check. A single residual blip
                        # after an auto-resume must not count as a playlist.
                        if self._spotify_loud_streak >= 3:
                            self._playlist_audio_armed = True
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
                    else:
                        self._spotify_loud_streak = 0
                    if game_loud:
                        self._last_game_loud_ts = now
                    if spotify_loud or game_loud:
                        self._restore_playlist_end_prompt_delay_after_audio()

                    auto_pause_allowed = self._auto_pause_allowed(spotify_loud)
                    if self._seamless_music_enabled() and self._paused_by_game_flag:
                        self._resume_spotify_after_game_quiet()
                    elif auto_pause_allowed and game_loud:
                        last_pause_try = float(getattr(self, "_last_game_pause_attempt_ts", 0.0) or 0.0)
                        if now - last_pause_try >= 1.0:
                            self._last_game_pause_attempt_ts = now
                            self._pause_spotify_for_game_audio(self._game_audio.current_peak)
                    elif self._paused_by_game_flag and not game_loud:
                        last_game_loud = self._last_game_loud_ts or now
                        last_resume_try = float(getattr(self, "_last_game_resume_attempt_ts", 0.0) or 0.0)
                        if (now - last_game_loud >= self._resume_delay_seconds()) and (now - last_resume_try >= 1.5):
                            self._last_game_resume_attempt_ts = now
                            self._resume_spotify_after_game_quiet()

                    # ── Transition logs ───────────────────────────────────
                    if spotify_loud and not _prev_spotify_loud:
                        self.root.after(0, lambda p=spotify_peak: self._log(
                            f"Spotify audio resumed (peak={p:.4f})"))
                    elif not spotify_loud and _prev_spotify_loud:
                        self.root.after(0, lambda: self._log(
                            "Spotify audio silent — watching for playlist end"))

                    if game_loud and not _prev_game_loud:
                        if other_loud:
                            self.root.after(0, lambda p=other_peak: self._log(
                                f"Other audio detected (peak={p:.4f})"))
                        else:
                            self.root.after(0, lambda: self._log("Game audio resumed"))
                    elif not game_loud and _prev_game_loud:
                        self.root.after(0, lambda: self._log("Game/other audio silent"))

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
                            and not self._intentional_pause_active()
                            and not self._player_is_playing_cached()
                            and (
                                not getattr(self, "_audio_monitor_running", False)
                                or getattr(self, "_playlist_audio_armed", False)
                            )
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
                # Restore the audio source preference after the game session.
                try:
                    if hasattr(self, "spotify") and getattr(self, "spotify", None) is not None:
                        if hasattr(self.spotify, "refresh_audio_source"):
                            self.spotify.refresh_audio_source()
                        else:
                            from core.audio_monitor import set_browser_audio_only
                            set_browser_audio_only(
                                not self.spotify._uses_desktop_player()
                            )
                except Exception:
                    pass
                try:
                    self.root.after(0, self._set_puppy_singing_visible, False)
                except Exception:
                    pass
                _clear_spotify_mixer_mute()

        threading.Thread(target=_loop, daemon=True).start()

    def _set_puppy_singing_visible(self, visible: bool):
        """Show the small desktop puppy and update the in-room mascot.

        The desktop puppy is a transparent, always-on-top Toplevel in the
        lower-left corner. Audio meters dip briefly between beats, so a short
        quiet run keeps it on screen; a real pause or playlist end hides it
        immediately. The big den mascot follows the same state.
        """
        overlay = getattr(self, "_puppy_singing_overlay", None)
        try:
            intentionally_stopped = self._intentional_pause_active()
            notifier_up = getattr(self, "_mascot_notifier", None) is not None
            active = bool(visible) and not intentionally_stopped and not notifier_up
            changed = bool(getattr(self, "_puppy_audio_active", False)) != active
            self._puppy_audio_active = active
            if changed:
                self._schedule_room_redraw(0)

            if overlay is None:
                return

            hide_job = getattr(self, "_puppy_hide_job", None)
            if active:
                self._puppy_last_loud_ts = time.time()
                if hide_job is not None:
                    try:
                        self.root.after_cancel(hide_job)
                    except Exception:
                        pass
                    self._puppy_hide_job = None
                overlay.show()
                return

            if intentionally_stopped or notifier_up:
                if hide_job is not None:
                    try:
                        self.root.after_cancel(hide_job)
                    except Exception:
                        pass
                    self._puppy_hide_job = None
                overlay.hide(immediate=True)
                return

            # Transient quiet: hold the puppy briefly so it doesn't blink.
            try:
                is_visible = bool(overlay.is_visible())
            except Exception:
                is_visible = True
            if not is_visible:
                return
            if hide_job is None:
                self._puppy_hide_job = self.root.after(
                    2600, self._hide_puppy_after_quiet
                )
        except Exception:
            pass

    def _hide_puppy_after_quiet(self):
        self._puppy_hide_job = None
        overlay = getattr(self, "_puppy_singing_overlay", None)
        if overlay is None:
            return
        try:
            if time.time() - float(getattr(self, "_puppy_last_loud_ts", 0.0) or 0.0) < 1.0:
                return
            if (
                self._intentional_pause_active()
                or getattr(self, "_mascot_notifier", None) is not None
            ):
                overlay.hide(immediate=True)
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
                try:
                    ok = bool(self.spotify.ensure_paused(paused_by_game=True))
                except TypeError:
                    ok = bool(self.spotify.ensure_paused())
            else:
                ok = bool(self.spotify.media_stop())
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Other-audio pause failed: {e}"))

        if ok:
            self._paused_by_game_flag = True
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            self._playlist_audio_armed = False
            self._spotify_loud_streak = 0
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
                    self._log(f"Other audio detected - paused Spotify (peak={p:.4f})"),
                ))
        else:
            self._paused_by_game_flag = False
            self._clear_spotify_game_pause_claim()
            self._remove_pause_reason("auto")
            self.root.after(0, lambda: self._log("Other audio detected, but Spotify pause did not confirm."))

    def _resume_spotify_after_game_quiet(self):
        if not self.spotify or not self._paused_by_game_flag:
            return
        if self._manual_paused or self._user_paused_flag:
            return
        # Wait for real audio before re-arming the end-of-playlist prompt.
        self._playlist_audio_armed = False
        self._spotify_loud_streak = 0

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
            self.root.after(0, lambda e=ex: self._log(f"Other-audio resume failed: {e}"))

        if ok:
            self._paused_by_game_flag = False
            self._remove_pause_reason("auto")
            self._is_playing = True
            self._music_missing_since = 0.0
            self._last_spotify_loud_ts = time.time()
            self.root.after(0, lambda: (
                self._set_play_btn_icon(True, force_btn=True),
                self._log("Other audio quiet - resumed Spotify"),
            ))

    def _stop_audio_monitor(self):
        self._audio_monitor_running = False
        if self._game_audio is not None:
            try:
                self._game_audio.shutdown()
            except Exception:
                pass
        # Restore the audio source preference when the monitor stops.
        try:
            if hasattr(self, "spotify") and getattr(self, "spotify", None) is not None:
                if hasattr(self.spotify, "refresh_audio_source"):
                    self.spotify.refresh_audio_source()
                else:
                    from core.audio_monitor import set_browser_audio_only
                    set_browser_audio_only(not self.spotify._uses_desktop_player())
        except Exception:
            pass
        _clear_spotify_mixer_mute()
        # Close the notifier if the game stopped while it was visible
        if self._mascot_notifier is not None:
            self._mascot_notifier.close()
            self._mascot_notifier = None
        # Keep the puppy visible if music is still playing after the game
        # session ends; only hide it when playback actually stopped.
        if not getattr(self, "_is_playing", False):
            self._set_puppy_singing_visible(False)

    # ── PLAYLISTS ─────────────────────────────────────────────────────────────

    def _remember_current_playlist(self, uri="", name="", query="", reset_pause_flags: bool = False):
        new_playlist = False
        if uri and str(uri).startswith("spotify:playlist:"):
            new_playlist = uri != getattr(self, "_current_playlist_uri", "")
            self._current_playlist_uri = uri
        if name:
            self._current_playlist_name = name
        if query:
            self._current_playlist_query = query
        if reset_pause_flags:
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
        # A brand-new playlist has not produced audio yet. Do not let the
        # silence timer reach the end-of-playlist threshold while the web
        # player is still loading (this caused a false "Playlist finished"
        # popup right after playback started).
        if new_playlist or reset_pause_flags:
            self._playlist_audio_armed = False
            self._spotify_loud_streak = 0
        self.root.after(0, lambda: (
            self.playlist_display_lbl.configure(text=f"PLAYLIST: {self._current_playlist_name or '\u2014'}"),
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
        """True only when GameBeats or the user explicitly paused playback.

        This used to guess from window titles / track progress. Those guesses
        were unreliable and caused the "Playlist finished" overlay to appear
        after a manual pause (or to suppress it at a real playlist end).
        """
        if getattr(self, "_manual_paused", False) or getattr(self, "_user_paused_flag", False):
            return True
        if getattr(self, "_paused_by_game_flag", False):
            return True
        try:
            if self.spotify and getattr(
                self.spotify,
                "paused_by_game",
                getattr(self.spotify, "_paused_by_game", False),
            ):
                return True
        except Exception:
            pass
        try:
            if getattr(self, "_pause_stack", None):
                return True
        except Exception:
            pass
        return False

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
        self.pl_status_lbl.configure(
            text=f"{len(pls)} record{'s' if len(pls) != 1 else ''} in the crate \u00b7 click a sleeve to spin it",
            text_color=TEXT_SEC,
        )
        palette = [MINT, GOLD, ORANGE, CREAM, "#C084FC", "#00E5FF"]
        for index, pl in enumerate(pls[:30]):
            color = palette[index % len(palette)]
            row = ctk.CTkFrame(
                self.pl_inner, fg_color=SURFACE2, corner_radius=0,
                border_width=2, border_color=WOOD, height=94, cursor="hand2",
            )
            row.pack(fill=tk.X, pady=4, padx=(0, 4))
            row.pack_propagate(False)

            sleeve = self._record_sleeve(row, color, index, size=68)
            sleeve.pack(side=tk.LEFT, padx=(10, 12), pady=10)

            col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
            col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=10)

            title = ctk.CTkLabel(
                col, text=pl["name"], fg_color="transparent", text_color=TEXT,
                font=T.retro_font(21, "bold"), anchor="w", justify=tk.LEFT,
            )
            title.pack(anchor="w", fill=tk.X)

            ctk.CTkLabel(
                col, text=f"{pl['tracks']} tracks  \u00b7  READY TO SPIN",
                fg_color="transparent", text_color=TEXT_MUTED,
                font=T.pixel_font(9), anchor="w",
            ).pack(anchor="w", pady=(3, 0))

            spin = T.pixel_button(
                row, text="\u25b6  SPIN", command=lambda u=pl["uri"], n=pl["name"]: self._play_pl(u, n),
                width=90, height=32,
            )
            spin.pack(side=tk.RIGHT, padx=(8, 10))

            if self._is_desktop_mode():
                del_l = ctk.CTkButton(
                    row, text="\u2715", fg_color="transparent", text_color=TEXT_MUTED,
                    hover_color=SURFACE4, font=T.pixel_font(10, "bold"),
                    width=30, height=30, corner_radius=0,
                    command=lambda u=pl["uri"]: self._remove_saved_pl(u),
                )
                del_l.pack(side=tk.RIGHT, padx=(0, 2))

            def _set_row_bg(r, color):
                try:
                    r.configure(fg_color=color)
                except Exception:
                    pass

            for widget in (row, sleeve, col, title):
                widget.bind(
                    "<Button-1>",
                    lambda e, u=pl["uri"], n=pl["name"]: self._play_pl(u, n),
                )
                widget.bind("<Enter>", lambda e, r=row: _set_row_bg(r, SURFACE3))
                widget.bind("<Leave>", lambda e, r=row: _set_row_bg(r, SURFACE2))

        self._render_blocked_playlists(blocked)

    def _record_sleeve(self, parent, color, index, size=68):
        canvas = tk.Canvas(
            parent, width=size, height=size, bg=color,
            highlightthickness=2, highlightbackground=NIGHT, bd=0,
            cursor="hand2",
        )
        try:
            canvas.create_text(
                size * 0.5, size * 0.12, text=f"0{index + 1}",
                fill=T.NIGHT, font=(T.F_PIXEL, -7, "bold"),
            )
            canvas.create_oval(
                size * 0.17, size * 0.17, size * 0.83, size * 0.83,
                fill=NIGHT, outline=CREAM, width=2,
            )
            canvas.create_oval(
                size * 0.37, size * 0.37, size * 0.63, size * 0.63,
                fill=color, outline=NIGHT, width=2,
            )
            canvas.create_text(
                size * 0.5, size * 0.5, text="GB",
                fill=NIGHT, font=(T.F_PIXEL, -6, "bold"),
            )
        except Exception:
            pass
        return canvas

    def _render_blocked_playlists(self, blocked):
        if not blocked:
            return
        ctk.CTkLabel(
            self.pl_inner, text="BLOCKED FROM AUTO-PLAY",
            fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(10, "bold"),
        ).pack(anchor=tk.W, padx=2, pady=(18, 6))
        for item in blocked:
            uri  = item.get("uri", "")
            name = item.get("name") or uri.split(":")[-1] or "Blocked playlist"
            query = item.get("query", "")
            row = ctk.CTkFrame(
                self.pl_inner, fg_color=SURFACE2, corner_radius=0,
                border_width=2, border_color=NIGHT,
            )
            row.pack(fill=tk.X, pady=4, padx=(0, 4))

            badge = ctk.CTkFrame(row, fg_color="#3A1A10", width=46, height=46, corner_radius=0)
            badge.pack(side=tk.LEFT, padx=(10, 10), pady=10)
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text="\u2205", fg_color="transparent", text_color=AMBER,
                         font=T.retro_font(22)).pack(expand=True)

            col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), pady=10)

            ctk.CTkLabel(col, text=name, fg_color="transparent", text_color=TEXT,
                         font=T.retro_font(19, "bold"), anchor="w", justify=tk.LEFT).pack(anchor="w")

            detail = (query or uri)[:80]
            ctk.CTkLabel(col, text=detail, fg_color="transparent", text_color=TEXT_MUTED,
                         font=T.retro_font(14), anchor="w", justify=tk.LEFT).pack(anchor="w", pady=(2,0))

            T.pixel_button(
                row, text="UNBLOCK",
                command=lambda u=uri: (
                    self._unblock_playlist(u),
                    self._load_playlists(),
                ),
                width=96, height=30,
            ).pack(side=tk.RIGHT, padx=(0, 10), pady=10)

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
                self.play_btn.configure(fg_color=GOLD)
            self._pulse_job = None
            return
        colors = [GOLD, "#FFD89A", ORANGE, "#FFC06A"]
        col = colors[step % len(colors)]
        if hasattr(self, "play_btn"):
            self.play_btn.configure(fg_color=col)
        self._pulse_job = self.root.after(450, lambda: self._pulse_loop(step + 1))

    def _set_play_btn_icon(self, playing: bool, force_btn: bool = False):
        """Update internal playing state and control button icons.

        This is called from the audio monitor as often as twice per second.
        Keep it *cheap*: the room canvas has its own animation loop, so never
        force a full room repaint here unless the play state actually changed.
        A full repaint on every audio tick made the whole UI feel frozen and
        caused pause/resume clicks to appear ignored.
        """
        playing = bool(playing)
        previous = bool(getattr(self, "_is_playing", False))
        changed = (playing != previous) or bool(force_btn)
        self._is_playing = playing
        if playing:
            self._start_play_btn_pulse()
        else:
            self._pulse_active = False
        # Only an explicit user/auto action may change the visible icon.
        # Audio-meter ticks call this method too, and letting them overwrite
        # the icon is what made the UI show "paused" while music was audible.
        if force_btn and hasattr(self, "play_btn"):
            try:
                self.play_btn.update_text("\u23F8" if playing else "\u25B6")
            except Exception:
                pass
        try:
            overlay = getattr(self, "_control_overlay", None)
            if overlay and overlay.is_visible():
                overlay.update_status(playing=playing)
        except Exception:
            pass
        try:
            self._update_deck_status()
        except Exception:
            pass
        if changed:
            # One coalesced repaint per actual state change (not per tick).
            try:
                self._schedule_room_redraw(0)
            except Exception:
                pass
            try:
                if playing and not self._intentional_pause_active():
                    self._set_puppy_singing_visible(True)
                elif not playing and self._intentional_pause_active():
                    self._set_puppy_singing_visible(False)
            except Exception:
                pass

    def _sync_play_btn_to_spotify_audio(self, audio_active: bool, peak: float = 0.0):
        """Track Spotify audio state internally (never the visible button icon).

        The audio meter is a hint for auto-pause and animation; it is not a
        reliable source of truth for play/pause state (the browser can be
        silent while the desktop sidecar is audible).  Explicit actions pass
        force_btn=True to _set_play_btn_icon().
        """
        self._spotify_audio_active = bool(audio_active)
        try:
            self._last_spotify_peak = float(peak)
        except Exception:
            self._last_spotify_peak = 0.0

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
        """Resolve clicks from explicit/audio state instead of stale UI state."""
        # Explicit pause state wins. Residual loopback audio for ~1s after a
        # pause used to make the next click send *pause* again instead of play.
        if self._intentional_pause_active():
            return False
        if self._spotify_sound_detected_recently(2.0):
            return True
        # In web mode get_playback_state() goes through the Playwright queue
        # and can block the Tk thread. The poller/monitor keeps these caches
        # up to date instead.
        if self._is_web_mode():
            info = getattr(self, "_last_track_info", None) or {}
            ts = float(getattr(self, "_last_track_info_ts", 0.0) or 0.0)
            if "is_playing" in info and ts > 0 and (time.time() - ts) <= 10.0:
                return bool(info.get("is_playing"))
            return bool(getattr(self, "_is_playing", False))
        state = self._read_spotify_is_playing()
        if state is not None:
            return bool(state)
        return bool(getattr(self, "_is_playing", False))

    def _send_spotify_pause_command(self) -> bool:
        if not self.spotify:
            return False
        ok = False
        try:
            if hasattr(self.spotify, "ensure_paused"):
                try:
                    ok = bool(self.spotify.ensure_paused(paused_by_game=False))
                except TypeError:
                    ok = bool(self.spotify.ensure_paused())
            elif hasattr(self.spotify, "pause"):
                ok = bool(self.spotify.pause())
            elif hasattr(self.spotify, "media_stop"):
                ok = bool(self.spotify.media_stop())
            elif hasattr(self.spotify, "media_play_pause"):
                ok = bool(self.spotify.media_play_pause())
        except Exception:
            ok = False
        return ok

    def _send_spotify_resume_command(self) -> bool:
        if not self.spotify:
            return False

        def _attempt() -> bool:
            try:
                if hasattr(self.spotify, "ensure_playing"):
                    return bool(self.spotify.ensure_playing())
                if hasattr(self.spotify, "resume"):
                    return bool(self.spotify.resume())
                if hasattr(self.spotify, "play"):
                    return bool(self.spotify.play())
                if hasattr(self.spotify, "media_play_pause"):
                    return bool(self.spotify.media_play_pause())
            except Exception:
                return False
            return False

        ok = _attempt()
        if not ok:
            # One bounded retry. NEVER fall back to play_playlist() here:
            # that navigates to the playlist and restarts it, which users
            # experienced as "pausing/resuming starts another playlist".
            time.sleep(0.35)
            ok = _attempt()
        return ok

    def _apply_user_pause_state(self, paused: bool):
        self._user_toggle_ts = time.time()
        # The next end-of-playlist check must wait until this playlist's
        # audio is actually heard again.  Silence during a pause/resume
        # transition is not a finished playlist.
        self._playlist_audio_armed = False
        self._spotify_loud_streak = 0
        if paused:
            self._manual_paused = True
            self._user_paused_flag = True
            self._paused_by_game_flag = False
            self._add_pause_reason("user")
            self._remove_pause_reason("auto")
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            # Keep the playlist-end prompt from firing immediately after a
            # resume (audio may need a moment to come back).
            self._playlist_end_prompt_not_before = (
                time.time() + max(3.0, self._playlist_end_delay_seconds())
            )
            self._set_play_btn_icon(False, force_btn=True)
            if getattr(self, "_mascot_notifier", None) is not None:
                try:
                    self._mascot_notifier.close()
                except Exception:
                    pass
                self._mascot_notifier = None
        else:
            self._manual_paused = False
            self._user_paused_flag = False
            self._paused_by_game_flag = False
            self._spotify_started_by_us = True
            self._remove_pause_reason("user")
            self._remove_pause_reason("auto")
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            self._playlist_end_prompt_not_before = (
                time.time() + max(3.0, self._playlist_end_delay_seconds())
            )
            if self.spotify:
                # Clear the *private* flag: paused_by_game is a read-only
                # property. Assigning to it raised AttributeError before the
                # private flag could be cleared, leaving the app stuck in an
                # "intentionally paused" state after a manual resume.
                try:
                    self.spotify._paused_by_game = False
                except Exception:
                    pass
                try:
                    desktop = getattr(self.spotify, "_desktop_player", None)
                    if desktop:
                        desktop._paused_by_game = False
                except Exception:
                    pass

    def _begin_play_pause(self) -> bool:
        """Take the play/pause lock, with a watchdog so it can never stick."""
        if getattr(self, "_play_pause_busy", False):
            return False
        self._play_pause_busy = True
        try:
            if getattr(self, "_play_pause_watchdog", None):
                self.root.after_cancel(self._play_pause_watchdog)
        except Exception:
            pass
        try:
            self._play_pause_watchdog = self.root.after(
                8000, self._finish_play_pause
            )
        except Exception:
            self._play_pause_watchdog = None
        return True

    def _finish_play_pause(self):
        self._play_pause_busy = False
        try:
            if getattr(self, "_play_pause_watchdog", None):
                self.root.after_cancel(self._play_pause_watchdog)
        except Exception:
            pass
        self._play_pause_watchdog = None

    def _pause(self):
        """Pause Spotify (called from overlay / keyboard shortcut)."""
        if not self.spotify or not self._begin_play_pause():
            return False
        self._apply_user_pause_state(True)
        def _do_pause():
            try:
                ok = self._send_spotify_pause_command()
            except Exception:
                ok = False
            def finish():
                self._finish_play_pause()
                if ok:
                    self._set_play_btn_icon(False, force_btn=True)
                else:
                    # The player is still audibly playing; reflect reality so
                    # the next click is a pause rather than a stuck toggle.
                    self._apply_user_pause_state(False)
                    self._set_play_btn_icon(True, force_btn=True)
                    self._log("Spotify pause did not confirm — still playing.")
            self.root.after(0, finish)
        try:
            threading.Thread(target=_do_pause, daemon=True).start()
        except Exception as ex:
            self._finish_play_pause()
            self._apply_user_pause_state(False)
            self._log(f"Could not start pause command: {ex}")
            return False
        return True

    def _play(self):
        """Resume Spotify (called from overlay / keyboard shortcut)."""
        if not self.spotify or not self._begin_play_pause():
            return False
        self._apply_user_pause_state(False)
        def go():
            try:
                ok = self._send_spotify_resume_command()
            except Exception:
                ok = False
            def finish():
                self._finish_play_pause()
                if ok:
                    self._set_play_btn_icon(True, force_btn=True)
                else:
                    self._set_play_btn_icon(False, force_btn=True)
                    self._log("Spotify resume did not confirm — click Play again.")
            self.root.after(0, finish)
        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception as ex:
            self._finish_play_pause()
            self._set_play_btn_icon(False, force_btn=True)
            self._log(f"Could not start resume command: {ex}")
            return False
        return True

    def _play_pause_toggle(self):
        """Single-button toggle: pause if playing, play if paused."""
        if not self.spotify or not self._begin_play_pause():
            return
        self._user_toggle_ts = time.time()

        was_playing = self._spotify_is_playing_for_toggle()
        target_playing = not was_playing
        self._apply_user_pause_state(not target_playing)

        def go():
            ok = False
            try:
                if was_playing:
                    ok = self._send_spotify_pause_command()
                else:
                    ok = self._send_spotify_resume_command()
            except Exception:
                ok = False

            def finish():
                self._finish_play_pause()
                if ok:
                    self._set_play_btn_icon(target_playing, force_btn=True)
                else:
                    self._log("Spotify play/pause command did not confirm.")
                    if not target_playing:
                        # Pause failed: revert the optimistic manual-pause flags
                        # so the next click still means "pause", not "play".
                        self._apply_user_pause_state(False)
                    actual = self._spotify_is_playing_for_toggle()
                    self._set_play_btn_icon(actual, force_btn=True)

            self.root.after(0, finish)

        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception as ex:
            self._finish_play_pause()
            self._log(f"Could not start play/pause command: {ex}")
        return

    def _play_pause(self):
        """Legacy alias — routes to the toggle."""
        self._play_pause_toggle()

    def _next(self):
        if self.spotify:
            threading.Thread(target=self._media_next, daemon=True).start()

    def _media_next(self):
        try:
            if hasattr(self.spotify, "media_next"):
                self.spotify.media_next()
            elif hasattr(self.spotify, "next_track"):
                self.spotify.next_track()
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Next track error: {e}"))

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
                if not self._intentional_pause_active():
                    self.root.after(0, self._mark_music_missing)
        except Exception:
            if not self._intentional_pause_active():
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
        return ""

    def _update_np(self, t):
        self._last_track_info = t
        self._last_track_info_ts = time.time()
        try:
            key = (
                str(t.get("uri") or ""),
                str(t.get("name") or "").strip(),
                str(t.get("artist") or "").strip(),
            )
            if self._last_np_key is not None and key != self._last_np_key:
                # In-place track-change reaction: head turn + ear perk.
                self._puppy_reaction_until = time.time() + 1.15
            self._last_np_key = key
        except Exception:
            pass
        if not hasattr(self, "track_lbl"):
            return
        playlist_uri = t.get("playlist_uri") or t.get("context_uri")
        if (
            playlist_uri
            and str(playlist_uri).startswith("spotify:playlist:")
            and playlist_uri != self._current_playlist_uri
        ):
            self._current_playlist_uri = playlist_uri
            # New playlist detected from the player itself: wait for it to
            # produce audio before allowing an end-of-playlist prompt.
            try:
                self._playlist_audio_armed = False
                self._spotify_loud_streak = 0
            except Exception:
                pass
            if not self._play_in_progress:
                self._current_playlist_name = "Spotify Playlist"
                self.root.after(0, lambda: self.playlist_display_lbl.configure(
                    text=f"PLAYLIST: {self._current_playlist_name}"
                ))

        playlist_title = self._now_playing_playlist_title(t)
        song_title = str(t.get("name") or "").strip()
        lowered_song = song_title.lower()
        if (
            not song_title
            or lowered_song == "spotify"
            or "gdi+ window" in lowered_song
            or "spotify.exe" in lowered_song
            or str(t.get("uri") or "") == getattr(self, "SILENT_TRACK_URI", "")
        ):
            song_title = playlist_title or "Spotify"
        self.track_lbl.configure(text=song_title)

        # Keep the deck's playlist line in sync even when the track poller is
        # recovering from a desktop/web hand-off (previously it stayed "—").
        if playlist_title and playlist_title.lower() != "nothing playing":
            try:
                self.playlist_display_lbl.configure(
                    text=f"PLAYLIST: {playlist_title}"
                )
            except Exception:
                pass

        artist = str(t.get("artist") or "").strip()
        if not artist or artist.lower() in ("web player", "spotify"):
            artist = "Spotify web player"
        try:
            self.deck_artist_lbl.configure(text=artist)
        except Exception:
            pass

        self.artist_lbl.configure(text="")
        self.artist_lbl.pack_forget()

        # Update the single toggle button: ⏸ when playing, ▶ when paused
        # But DON'T override the icon if the user just clicked the button
        # (give the Spotify command time to take effect before the poller
        # overwrites the state).
        user_toggle_age = time.time() - getattr(self, "_user_toggle_ts", 0.0)
        t_is_playing = bool(t.get("is_playing"))
        spotify_sound = self._spotify_sound_detected_recently(2.5)
        intentional = self._intentional_pause_active()
        # While paused (by the user or by game-audio logic), never let a stale
        # window title / media-session value flip the UI back to playing.
        effective_is_playing = (not intentional) and (t_is_playing or spotify_sound)
        if user_toggle_age > 3.0 and not getattr(self, "_audio_monitor_running", False):
            self._set_play_btn_icon(effective_is_playing)
            self._is_playing = effective_is_playing
            # Poll-only mode (no detected game) still needs the in-room
            # mascot to follow playback, since the audio monitor isn't running.
            self._set_puppy_singing_visible(effective_is_playing)
        if effective_is_playing:
            self._last_music_seen_ts = time.time()
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
            # IMPORTANT: never clear _manual_paused/_user_paused_flag here.
            # Only an explicit user resume or starting a new playlist may
            # clear a manual pause. The old auto-clear after 5s was what made
            # the "Playlist finished" overlay appear right after pausing.
        else:
            if not intentional:
                self._mark_music_missing()

        if HAS_PIL and t.get("album_art"):
            threading.Thread(target=self._load_art, args=(t["album_art"],), daemon=True).start()

    def _should_handle_auto_stop(self):
        return (
            self._spotify_started_by_us
            and self.current_game
            and self.auto_mode.get()
            and not self._intentional_pause_active()
            and not self._play_in_progress
        )

    def _playback_paused_by_app_or_user(self) -> bool:
        """
        Return True if playback is currently paused by GameBeats or the user.
        Delegates directly to _intentional_pause_active() so all pause states
        are checked consistently.
        """
        return self._intentional_pause_active()

    def _player_is_playing_cached(self) -> bool:
        """True when the last polled player state explicitly says 'playing'.

        Only used for the web player: in desktop mode silence is the reliable
        end-of-playlist signal and the window title is not trustworthy.
        """
        if not self._is_web_mode():
            return False
        try:
            info = getattr(self, "_last_track_info", None) or {}
            if not info.get("is_playing"):
                return False
            # Never trust a very old poll; a stalled browser/tab can leave a
            # stale "playing" snapshot forever and suppress a real end prompt.
            ts = float(getattr(self, "_last_track_info_ts", 0.0) or 0.0)
            return ts > 0 and (time.time() - ts) <= 10.0
        except Exception:
            return False

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
        if self._intentional_pause_active():
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
            return
        if self._player_is_playing_cached():
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
            return
        if not self._playlist_end_prompt_allowed(now):
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
        # A brand-new playlist (or a pause/resume transition) has not
        # produced audio yet. Never call that "playlist ended" until this
        # playlist has actually been heard at least once.
        if (
            getattr(self, "_audio_monitor_running", False)
            and not getattr(self, "_playlist_audio_armed", False)
        ):
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
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

        if self._intentional_pause_active():
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
            return
        if self._player_is_playing_cached():
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
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
        if self._player_is_playing_cached():
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            try:
                self._log("Playlist-end notifier suppressed because the player is still playing.")
            except Exception:
                pass
            return
        if (
            getattr(self, "_audio_monitor_running", False)
            and not getattr(self, "_playlist_audio_armed", False)
        ):
            # This playlist has never produced audio in this session. It is
            # most likely still loading (or failed to start), not finished.
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            try:
                self._log(
                    "Playlist-end notifier suppressed: no audio heard from this playlist yet."
                )
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
            self._defer_playlist_end_prompt(
                extra_seconds=60.0, until_audio=True, reason="User dismissed notifier"
            )

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
        if self._play() and self._control_overlay:
            self._control_overlay.update_status(playing=True)

    def _overlay_pause(self):
        """Pause button from control overlay."""
        if self._pause() and self._control_overlay:
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
