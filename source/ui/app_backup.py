import tkinter as tk
from tkinter import ttk, messagebox
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
from ui.games_page import GamesPage
from ui.mascot_notifier import MascotNotifier, PuppySingingOverlay
from ui.runtime_overlay import RuntimeOverlay

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


if sys.platform == "win32":
    try:
        import ctypes as _ctypes
        _ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes as _ctypes
            _ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ── Palette ──────────────────────────────────────────────────────────────────
BG        = "#08080c"      # Deep zinc-black
SIDEBAR   = "#0b0b0f"      # Sidebar — slightly distinct
SURFACE   = "#111116"      # Card / elevated surface
SURFACE2  = "#17171e"      # Secondary surface
SURFACE3  = "#202028"      # Input / button fill
SURFACE3  = "#202028"      # Input / button fill
SURFACE4  = "#2a2a35"      # Hover state
ACCENT    = "#a78bfa"      # Violet 400 — primary accent
ACCENT2   = "#c4b5fd"      # Violet 300 — lighter accent
ACCENT_DIM= "#6d28d9"      # Violet 700 — subdued
ACCENT_BG = "#1e1730"      # Accent tinted bg
TEXT      = "#f0f0f2"      # Near-white body
TEXT_SEC  = "#9898a6"      # Secondary text
TEXT_MUTED= "#4a4a58"      # Muted / placeholder
BORDER    = "#1c1c24"      # Card border
BORDER2   = "#242430"      # Stronger separator
RED       = "#f43f5e"      # Rose 500
AMBER     = "#fbbf24"      # Amber 400
GREEN     = "#22c55e"      # Green 500
PURPLE    = "#8b5cf6"      # Violet 500
BLUE      = "#4a90e2"
WIN_W     = 1280           # Largeur confortable pour éviter les coupures
WIN_H     =  1280        # Hauteur fixe stable pour tous les éléments

DEFAULT_PADX = 12          # Padding standard global
DEFAULT_PADY = 10
PLAYLIST_END_NORMAL_EXTRA_SEC = 4.0
PLAYLIST_END_RETRY_EXTRA_SEC = 10.0
SPOTIFY_UI_AUDIO_ON_THRESHOLD = 0.0001
SPOTIFY_UI_AUDIO_OFF_THRESHOLD = 0.0

# Font shortcuts — prefer Inter / Segoe UI Variable for crispness
F_FALLBACK = ("Segoe UI Variable Display", "Segoe UI", "Inter", "Arial")
F_TITLE  = (F_FALLBACK[0], 20, "bold")
F_LABEL  = (F_FALLBACK[0], 13)
F_SMALL  = (F_FALLBACK[0], 12)
F_MICRO  = (F_FALLBACK[0], 8, "bold")
F_MONO   = ("Consolas", 9)
F_UI     = F_FALLBACK[0]


# ── Reusable widgets ──────────────────────────────────────────────────────────

def pack_padded(widget, **kwargs):
    """Helper pour pack avec du padding par défaut pour uniformiser l'UI."""
    if 'padx' not in kwargs: kwargs['padx'] = DEFAULT_PADX
    if 'pady' not in kwargs: kwargs['pady'] = DEFAULT_PADY
    widget.pack(**kwargs)


def pill_label(parent, text, bg=None, fg=ACCENT, font_size=9):
    bg = bg or SURFACE3
    f = tk.Frame(parent, bg=bg, padx=10, pady=3)
    tk.Label(f, text=text, bg=bg, fg=fg,
             font=(F_UI, font_size, "bold")).pack()
    return f


def _make_entry(parent, textvariable=None, show="", font_size=10, mono=False, **kwargs):
    """Styled entry with focus-highlight border effect."""
    border_wrap = tk.Frame(parent, bg=BORDER2, padx=1, pady=1)
    inner = tk.Frame(border_wrap, bg=SURFACE3)
    inner.pack(fill=tk.X)
    ff = "Consolas" if mono else F_UI
    e = tk.Entry(inner, textvariable=textvariable, show=show,
                 bg=SURFACE3, fg=TEXT, insertbackground=ACCENT,
                 relief=tk.FLAT, font=(ff, font_size), bd=0, **kwargs)
    e.pack(fill=tk.X, ipady=9, padx=10)
    e.bind("<FocusIn>",  lambda _: border_wrap.config(bg=ACCENT))
    e.bind("<FocusOut>", lambda _: border_wrap.config(bg=BORDER2))
    return border_wrap, e


class RoundedButton(tk.Canvas):
    """Pill-shaped button with smooth hover and click feedback."""
    def __init__(self, parent, text="", command=None, width=160, height=48,
                 bg=ACCENT, fg="#000000", radius=8, font_size=9, canvas_bg=BG,
                 border_color="", **kwargs):
        # Auto-calculate width to prevent text clipping on high DPI
        import tkinter.font as tkfont
        try:
            f = tkfont.Font(font=(F_UI, font_size, "bold"))
            text_w = f.measure(text)
            # Use max to ensure it doesn't shrink below the requested width
            # Add 60px base padding to accommodate icons and generous margins
            width = max(width, text_w + 60)
        except Exception:
            pass

        super().__init__(parent, width=width, height=height,
                         bg=canvas_bg, highlightthickness=0, cursor="hand2", **kwargs)
        self.command  = command
        self.bg_n     = bg
        self.bg_h     = self._adjust(bg, 22)
        self.bg_p     = self._adjust(bg, -18)
        self.fg       = fg
        self.radius   = radius
        self.text     = text
        self.w, self.h = width, height
        self.font_size = font_size
        self.border_color = border_color
        self._pressed = False
        self.after_idle(lambda: self._draw(self.bg_n))
        self.bind("<Enter>",          lambda e: self._draw(self.bg_h))
        self.bind("<Leave>",          lambda e: self._draw(self.bg_n))
        self.bind("<ButtonPress-1>",  lambda e: self._press())
        self.bind("<ButtonRelease-1>",lambda e: self._release())

    def _adjust(self, h, amt):
        try:
            r = max(0, min(255, int(h[1:3], 16) + amt))
            g = max(0, min(255, int(h[3:5], 16) + amt))
            b = max(0, min(255, int(h[5:7], 16) + amt))
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return h

    def _press(self):
        self._pressed = True
        self._draw(self.bg_p)

    def _release(self):
        self._pressed = False
        self._draw(self.bg_n)
        if self.command:
            self.command()

    def _draw(self, color):
        self.delete("all")
        r, w, h = self.radius, self.w, self.h
        # Rounded rectangle fill
        for x, y, s, e in [(0, 0, 90, 90), (w-2*r, 0, 0, 90),
                            (0, h-2*r, 180, 90), (w-2*r, h-2*r, 270, 90)]:
            self.create_arc(x, y, x+2*r, y+2*r, start=s, extent=e,
                            fill=color, outline="")
        self.create_rectangle(r, 0, w-r, h, fill=color, outline="")
        self.create_rectangle(0, r, w, h-r, fill=color, outline="")
        # Optional border
        if self.border_color:
            bc = self.border_color
            for x, y, s, e in [(0, 0, 90, 90), (w-2*r, 0, 0, 90),
                                (0, h-2*r, 180, 90), (w-2*r, h-2*r, 270, 90)]:
                self.create_arc(x, y, x+2*r, y+2*r, start=s, extent=e,
                                fill="", outline=bc, width=1)
            self.create_line(r, 0, w-r, 0, fill=bc)
            self.create_line(r, h-1, w-r, h-1, fill=bc)
            self.create_line(0, r, 0, h-r, fill=bc)
            self.create_line(w-1, r, w-1, h-r, fill=bc)
        # Label
        self.create_text(w//2, h//2, text=self.text, fill=self.fg,
                         font=(F_UI, self.font_size, "bold"))

    def update_text(self, text):
        self.text = text
        self._draw(self.bg_n)

    def set_bg(self, bg):
        self.bg_n = bg
        self.bg_h = self._adjust(bg, 22)
        self._draw(self.bg_n)


class CircleBtn(tk.Canvas):
    """Circular icon button with smooth hover feedback."""
    def __init__(self, parent, text="", command=None, size=60,
                 bg=SURFACE3, fg=TEXT, font_size=16, canvas_bg=SURFACE,
                 accent=False, **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg=canvas_bg, highlightthickness=0, cursor="hand2", **kwargs)
        self.command  = command
        self.bg_n     = bg
        self.bg_h     = self._adjust(bg, 18)
        self.fg       = fg
        self.size     = size
        self.text     = text
        self.font_size = font_size
        self.accent   = accent
        self.after_idle(lambda: self._draw(self.bg_n))
        self.bind("<Enter>",          lambda e: self._draw(self.bg_h))
        self.bind("<Leave>",          lambda e: self._draw(self.bg_n))
        self.bind("<ButtonPress-1>",  lambda e: self._draw(self.bg_n))
        self.bind("<ButtonRelease-1>",lambda e: (self._draw(self.bg_n),
                                                  self.command() if self.command else None))

    def _adjust(self, h, amt):
        try:
            r = max(0, min(255, int(h[1:3], 16) + amt))
            g = max(0, min(255, int(h[3:5], 16) + amt))
            b = max(0, min(255, int(h[5:7], 16) + amt))
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return h

    def _draw(self, color):
        self.delete("all")
        s = self.size
        pad = 2
        self.create_oval(pad, pad, s - pad, s - pad,
                         fill=color, outline=BORDER2, width=1)

        cx, cy = s // 2, s // 2

        if self.text == "\u25b6":  # ▶ Play triangle — draw as polygon
            # Equilateral-ish triangle, slightly shifted right to look centred
            r = int(s * 0.26)  # radius of the triangle
            off = int(s * 0.04)  # optical centering nudge
            self.create_polygon(
                cx - int(r * 0.75) + off, cy - r,
                cx - int(r * 0.75) + off, cy + r,
                cx + r + off, cy,
                fill=self.fg, outline="",
            )
        elif self.text == "\u23F8":  # ⏸ Pause bars — draw as two rectangles
            bar_w = max(3, int(s * 0.08))
            bar_h = int(s * 0.34)
            gap = max(3, int(s * 0.10))
            x1 = cx - gap // 2 - bar_w
            x2 = cx + gap // 2
            y1 = cy - bar_h // 2
            y2 = cy + bar_h // 2
            self.create_rectangle(x1, y1, x1 + bar_w, y2,
                                  fill=self.fg, outline="")
            self.create_rectangle(x2, y1, x2 + bar_w, y2,
                                  fill=self.fg, outline="")
        else:
            # Fallback: other icons (prev/next) use text
            self.create_text(cx, cy, text=self.text, fill=self.fg,
                             font=(F_UI, self.font_size, "bold"))

    def update_text(self, t):
        self.text = t
        self._draw(self.bg_n)

    def set_active(self, active: bool):
        if active:
            self.bg_n = ACCENT if self.accent else SURFACE3
            self.fg   = "#000" if self.accent else ACCENT
        else:
            self.bg_n = SURFACE3
            self.fg   = TEXT
        self.bg_h = self._adjust(self.bg_n, 18)
        self._draw(self.bg_n)


# ── Splash screen ────────────────────────────────────────────────────────────

class SplashScreen:
    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        w, h = 360, 240
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.win.configure(bg=SURFACE)
        self.win.attributes("-topmost", True)

        # Accent top bar
        tk.Frame(self.win, bg=ACCENT, height=3).pack(fill=tk.X)

        # Logo area
        logo_frame = tk.Frame(self.win, bg=SURFACE)
        logo_frame.pack(pady=(32, 10))
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

        tk.Label(self.win, text="GameBeats", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 20, "bold")).pack()
        tk.Label(self.win, text="Starting up\u2026", bg=SURFACE, fg=TEXT_MUTED,
                 font=(F_UI, 9)).pack(pady=(6, 20))

        # Progress bar
        bar_bg = tk.Frame(self.win, bg=BORDER2, height=2)
        bar_bg.pack(fill=tk.X, padx=44)
        self.bar = tk.Frame(bar_bg, bg=ACCENT, height=2, width=0)
        self.bar.place(x=0, y=0, height=2)
        self._animate(0)

    def _animate(self, pct):
        if pct > 100:
            return
        total_w = self.bar.master.winfo_width() or 260
        self.bar.place(width=int(total_w * pct / 100))
        self.win.after(18, self._animate, pct + 3)

    def close(self):
        self.win.destroy()


# ── Main App ─────────────────────────────────────────────────────────────────

class GameBeatsApp:
    def __init__(self):
        self.root = tk.Tk()
        # Configure global ttk styles
        style = ttk.Style()
        style.theme_use('clam')
        # Combobox
        style.configure("TCombobox",
                         fieldbackground=SURFACE3, background=SURFACE3,
                         foreground=TEXT, bordercolor=BORDER2,
                         arrowcolor=TEXT_SEC, lightcolor=SURFACE3,
                         darkcolor=SURFACE3, insertcolor=ACCENT,
                         padding=(10, 6))
        style.map("TCombobox",
                  fieldbackground=[("readonly", SURFACE3)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", ACCENT_DIM)],
                  selectforeground=[("readonly", TEXT)])
        # Scrollbar — ultra thin, minimal
        style.configure("Vertical.TScrollbar",
                         gripcount=0, relief=tk.FLAT,
                         background=SURFACE3, darkcolor=SURFACE2,
                         lightcolor=SURFACE2, bordercolor=BG,
                         troughcolor=BG, arrowcolor=SURFACE3,
                         arrowsize=0, width=4)
        style.map("Vertical.TScrollbar",
                  background=[("active", ACCENT_DIM), ("!active", SURFACE4)])

        self.root.withdraw()
        self.root.title("GameBeats")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        init_w = min(WIN_W, max(960, int(sw * 0.75)))
        init_h = min(WIN_H, max(700, int(sh * 0.80)))
        self.root.geometry(f"{init_w}x{init_h}")
        self.root.minsize(960, 700)
        self.root.resizable(True, True)
        
        self.root.configure(bg=BG)
        self._window_icon_photo = _load_puppy_window_icon()
        if self._window_icon_photo:
            try:
                self.root.iconphoto(True, self._window_icon_photo)
            except Exception:
                pass
        elif IS_WINDOWS:
            self.root.iconbitmap(default="")

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
            value=bool(self.config.get("seamless_music", False))
        )
        self.startup_var = tk.BooleanVar(value=False)
        self.desktop_mode_var = tk.BooleanVar(
            value=self.config.get("playback_mode", "desktop") == "desktop")
        self.cid_var = tk.StringVar(value=self.config.get("client_id", ""))
        self.csec_var = tk.StringVar(value=self.config.get("client_secret", ""))
        # auth_lbl is used for status updates during Spotify connection
        self.auth_lbl = ctk.CTkLabel(self.root, text="", fg_color="transparent", text_color=TEXT)
        self.volume_var  = tk.IntVar(value=50)
        self._track_job  = None
        self._album_photo = None
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
        mode = self.config.get("playback_mode", "desktop")
        if mode in ("desktop", "web", ""):
            self.config["playback_mode"] = "web"
            self._start_web_mode()
        elif mode == "api":
            if not self.config.get("setup_done"):
                self._show_onboarding()
            else:
                self._try_auto_login()
        else:
            self.config["playback_mode"] = "web"
            self._start_web_mode()

    def _is_web_mode(self):
        return isinstance(self.spotify, SpotifyWebController)

    def _is_desktop_mode(self):
        """Free playback via Spotify Web Player (kept name for existing call sites)."""
        return self._is_web_mode()

    def _start_web_mode(self):
        self.config["playback_mode"] = "web"
        self.config["setup_done"] = True
        self._save_config()
        play_xpath = self.config.get("spotify_web_play_xpath", "")
        headless = bool(self.config.get("spotify_web_headless", False))
        show_browser = self.config.get("spotify_web_show_browser", False)
        self.config["spotify_web_show_browser"] = bool(show_browser)
        self._save_config()
        cdp_url = self.config.get("spotify_web_cdp_url", "")
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
                self.config["spotify_web_login_done"] = False
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
        return bool(self.config.get("spotify_web_login_done")) or self._spotify_web_profile_has_saved_state()

    def _show_spotify_browser_login_prompt(self):
        if self._spotify_login_prompt is not None:
            try:
                self._spotify_login_prompt.lift()
                return
            except Exception:
                self._spotify_login_prompt = None

        win = tk.Toplevel(self.root)
        self._spotify_login_prompt = win
        win.title("Spotify Login")
        win.configure(bg=BG)
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

        card = tk.Frame(win, bg=SURFACE, padx=30, pady=26)
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(card, text="Login to Spotify", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 18, "bold")).pack(anchor=tk.W)
        
        lbl_info = tk.Label(
            card,
            text=(
                "GameBeats needs you to log in once in the browser window it opens. "
                "Use the same Spotify account in the desktop app and this browser. "
                "After that, your login is saved on this PC and you should not need "
                "to log in again next time."
            ),
            bg=SURFACE, fg=TEXT_SEC, font=(F_UI, 10),
            justify=tk.LEFT,
        )
        lbl_info.pack(anchor=tk.W, fill=tk.X, pady=(10, 18))
        
        lbl_warn = tk.Label(
            card,
            text=(
                "For login, choose Google or another provider option if you use one. "
                "Avoid typing direct email/password unless that is how your Spotify "
                "account normally signs in."
            ),
            bg=SURFACE, fg=AMBER, font=(F_UI, 9),
            justify=tk.LEFT,
        )
        lbl_warn.pack(anchor=tk.W, fill=tk.X, pady=(0, 14))

        self._spotify_login_status_lbl = tk.Label(
            card,
            text="Open the login window, sign in to Spotify, then come back here.",
            bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9),
            justify=tk.LEFT,
        )
        self._spotify_login_status_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 18))

        def _on_card_resize(e):
            wrap = max(200, e.width - 60)
            lbl_info.config(wraplength=wrap)
            lbl_warn.config(wraplength=wrap)
            if self._spotify_login_status_lbl:
                try:
                    self._spotify_login_status_lbl.config(wraplength=wrap)
                except Exception:
                    pass

        card.bind("<Configure>", _on_card_resize)

        row = tk.Frame(card, bg=SURFACE)
        row.pack(fill=tk.X, pady=(4, 0))

        def _set_status(text, color=TEXT_MUTED):
            if self._spotify_login_status_lbl:
                self._spotify_login_status_lbl.config(text=text, fg=color)

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
                        self.config["spotify_web_login_done"] = True
                        self.config["spotify_web_show_browser"] = False
                        self.config["setup_done"] = True
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

        tk.Button(
            row, text="Open Spotify Login", command=_open_login,
            bg=ACCENT, fg="#000", font=(F_UI, 10, "bold"),
            relief=tk.FLAT, padx=18, pady=10, cursor="hand2",
        ).pack(side=tk.LEFT)
        tk.Button(
            row, text="I am logged in", command=_verify_login,
            bg=SURFACE3, fg=TEXT, font=(F_UI, 10, "bold"),
            relief=tk.FLAT, padx=18, pady=10, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(12, 0))
        tk.Button(
            row, text="Exit", command=self._on_close,
            bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 10),
            relief=tk.FLAT, padx=14, pady=10, cursor="hand2",
        ).pack(side=tk.RIGHT)

        try:
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
            self.cid_var.set(self.config.get("client_id", ""))
            self.csec_var.set(self.config.get("client_secret", ""))
            self.auth_lbl.configure(text="✓ Connected to Spotify", text_color="#1DB954")
            self._log("Spotify connected via setup wizard ✓")
            self._on_spotify_ready()
        else:
            self._log("Using free web player mode (no Spotify API needed).")
            self._start_desktop_mode()

    def _set_gamebeats_hwnd(self):
        if IS_WINDOWS:
            self._gamebeats_hwnd = self.root.winfo_id()
            pass  # Web player mode does not need Win32 focus guard HWND
            self._log(f"GameBeats main window HWND: {self._gamebeats_hwnd:#x}")

    def _reload_config(self):
        try:
            with open(CONFIG_FILE) as f:
                self.config = json.load(f)
        except:
            pass

    def _load_config(self):
        self.config = {}
        try:
            with open(CONFIG_FILE) as f:
                self.config = json.load(f)
        except: pass

    def _save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    def _playlist_pick_count(self) -> int:
        try:
            count = int(self.config.get("playlist_pick_count", 5))
        except (TypeError, ValueError):
            count = 5
        return max(1, min(20, count))

    def _end_behavior_key(self) -> str:
        value = self.config.get("playlist_end_behavior", "next_pool")
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
        self.config["playlist_pick_count"] = count
        self.config["playlist_end_behavior"] = behavior
        self._save_config()
        if self.spotify and hasattr(self.spotify, "set_repeat_mode"):
            repeat = "context" if behavior == "loop_current" else "off"
            threading.Thread(
                target=lambda: self.spotify.set_repeat_mode(repeat),
                daemon=True,
            ).start()

    def _resume_delay_seconds(self) -> int:
        try:
            delay = int(self.config.get("resume_delay_sec", 4))
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
        self.config["resume_delay_sec"] = delay
        self._save_config()

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _seamless_music_enabled(self) -> bool:
        try:
            return bool(self.seamless_music_var.get())
        except Exception:
            return bool(self.config.get("seamless_music", False))

    def _save_player_settings(self, *_):
        enabled = self._seamless_music_enabled()
        self.config["seamless_music"] = enabled
        self._save_config()
        if enabled and getattr(self, "_paused_by_game_flag", False):
            threading.Thread(
                target=self._resume_spotify_after_game_quiet,
                daemon=True,
            ).start()

    def _build_ui(self):
        # ── Root layout ───────────────────────────────────────────────────────
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill=tk.BOTH, expand=True)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = tk.Frame(container, bg=SIDEBAR)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        
        # Invisible spacer to enforce an absolute minimum width
        tk.Frame(sidebar, bg=SIDEBAR, width=240, height=1).pack()

        # Thin right border on sidebar
        tk.Frame(container, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        # Logo area — side-by-side layout
        logo_area = tk.Frame(sidebar, bg=SIDEBAR)
        logo_area.pack(fill=tk.X, padx=(18, 18), pady=(30, 24))

        self._brand_logo_photo = _load_puppy_logo_photo((64, 48))
        if self._brand_logo_photo:
            tk.Label(
                logo_area,
                image=self._brand_logo_photo,
                bg=SIDEBAR,
                bd=0,
                highlightthickness=0,
            ).pack(side=tk.LEFT, padx=(0, 10))
        else:
            lc = tk.Canvas(logo_area, width=36, height=36, bg=SIDEBAR, highlightthickness=0)
            lc.pack(side=tk.LEFT, padx=(0, 10))
            lc.create_oval(3, 3, 33, 33, fill=ACCENT_DIM, outline=ACCENT, width=1)
            lc.create_text(18, 18, text="\u266a", fill=ACCENT2, font=(F_UI, 14, "bold"))

        brand = tk.Frame(logo_area, bg=SIDEBAR)
        # Added 10px left margin to the title area as requested
        brand.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        self._brand_title_lbl = tk.Label(brand, text="GameBeats", bg=SIDEBAR, fg=TEXT,
                 font=(F_UI, 14, "bold"), anchor="w")
        self._brand_title_lbl.pack(fill=tk.X)
        self._brand_sub_lbl = tk.Label(brand, text="Music for your game", bg=SIDEBAR, fg=TEXT_MUTED,
                 font=(F_UI, 8), anchor="w")
        self._brand_sub_lbl.pack(fill=tk.X, pady=(1, 0))

        # Section divider + Nav label
        tk.Frame(sidebar, bg=BORDER2, height=1).pack(fill=tk.X, padx=18, pady=(0, 12))
        tk.Label(sidebar, text="NAVIGATION", bg=SIDEBAR, fg=TEXT_MUTED,
                 font=(F_UI, 7, "bold")).pack(anchor="w", padx=22, pady=(0, 4))

        nav_frame = tk.Frame(sidebar, bg=SIDEBAR)
        nav_frame.pack(fill=tk.X, padx=(12, 16))
        self._nav_btns = {}
        self._nav_indicators = {}
        self._nav_rows = {}

        nav_items = [
            ("main",      "Home",      "\u2302"),
            ("games",     "My Games",  "\u2b21"),
            ("blocked",   "Blocked",   "\u2298"),
            ("settings",  "Settings",  "\u2699"),
            ("faq",       "FAQ & Help","\u2139"),
        ]

        for page, label, icon in nav_items:
            row = tk.Frame(nav_frame, bg=SIDEBAR, cursor="hand2")
            row.pack(fill=tk.X, pady=1)

            indicator = tk.Canvas(row, width=3, height=40, bg=SIDEBAR,
                                  highlightthickness=0)
            indicator.pack(side=tk.LEFT)
            indicator.create_rectangle(0, 0, 3, 40, fill=SIDEBAR, outline="")
            self._nav_indicators[page] = indicator

            icon_lbl = tk.Label(row, text=icon, bg=SIDEBAR, fg=TEXT_MUTED,
                                font=(F_UI, 13), width=2, pady=10)
            icon_lbl.pack(side=tk.LEFT, padx=(12, 10))

            lbl = tk.Label(row, text=label, anchor="w", bg=SIDEBAR, fg=TEXT_SEC,
                           font=(F_UI, 11), pady=12)
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))

            self._nav_btns[page] = lbl
            self._nav_rows[page] = (row, icon_lbl)

            def _enter(e, r=row, ind=indicator, il=icon_lbl, l=lbl):
                for w in [r, ind, il, l]:
                    try: w.config(bg=SURFACE2)
                    except: pass

            def _leave(e, r=row, ind=indicator, il=icon_lbl, l=lbl, p=page):
                is_active = (p == getattr(self, "_current_page", "main"))
                c = SURFACE3 if is_active else SIDEBAR
                for w in [r, ind, il, l]:
                    try: w.config(bg=c)
                    except: pass

            def _click(e, p=page):
                self._nav(p)

            for w in [row, lbl, icon_lbl]:
                w.bind("<Enter>",    _enter)
                w.bind("<Leave>",    _leave)
                w.bind("<Button-1>", _click)

        tk.Frame(sidebar, bg=SIDEBAR).pack(fill=tk.BOTH, expand=True)

        # Sidebar footer — version / mode badge
        sf = tk.Frame(sidebar, bg=SIDEBAR)
        sf.pack(fill=tk.X, padx=18, pady=(0, 18))
        tk.Frame(sf, bg=BORDER2, height=1).pack(fill=tk.X, pady=(0, 10))
        mode_row = tk.Frame(sf, bg=SIDEBAR)
        mode_row.pack(anchor="center")
        # Dot + label
        tk.Label(mode_row, text="\u25cf", bg=SIDEBAR, fg=GREEN,
                 font=(F_UI, 7)).pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(mode_row, text="Ready", bg=SIDEBAR, fg=TEXT_MUTED,
                 font=(F_UI, 8)).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(mode_row, text="by @ssaborr", bg=SIDEBAR, fg=TEXT_MUTED,
                 font=(F_UI, 7)).pack(side=tk.LEFT)

        # ── Main content ──────────────────────────────────────────────────────
        main = tk.Frame(container, bg=BG)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Header bar — slim, clean
        header = tk.Frame(main, bg=BG)
        header.pack(fill=tk.X)

        # Subtle bottom border on header
        tk.Frame(header, bg=BORDER, height=1).place(relx=0, rely=1.0, relwidth=1.0,
                                                      anchor="sw")

        status_cluster = tk.Frame(header, bg=BG)
        status_cluster.pack(side=tk.RIGHT, padx=(0, 14))
        self.status_dot = tk.Label(status_cluster, text="\u25cf", bg=BG,
                                   fg=TEXT_MUTED, font=(F_UI, 8))
        self.status_dot.pack(side=tk.RIGHT, padx=(5, 0), pady=12)
        self.status_pill = tk.Label(status_cluster, text="Idle", bg=BG,
                                    fg=TEXT_MUTED, font=(F_UI, 9))
        self.status_pill.pack(side=tk.RIGHT, pady=12)

        # Content area — responsive side padding
        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill=tk.BOTH, expand=True, padx=(28, 24), pady=(20, 24))

        # Expose widgets (no player_frame — footer removed)
        self.header = header
        self.sidebar = sidebar
        self.main = main
        self.player_frame = None
        self._build_pages()

    def _show_verifying(self, show: bool = True):
        """Show or hide the verifying playback indicator in the status bar."""
        def _update():
            try:
                if show:
                    self.status_pill.config(text="Verifying…", fg=PURPLE)
                    self.status_dot.config(fg=PURPLE)
                else:
                    self.status_pill.config(text="Idle", fg=TEXT_MUTED)
                    self.status_dot.config(fg=TEXT_MUTED)
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
        # Fixed width to 260px so it comfortably fits the brand title
        sidebar_w = 260
        try:
            self.sidebar.config(width=sidebar_w)
        except Exception:
            pass

        # Sidebar brand text
        try:
            self._brand_title_lbl.config(
                font=(F_UI, _sf(14), "bold"))
        except Exception:
            pass
        try:
            self._brand_sub_lbl.config(
                font=(F_UI, _sf(8)))
        except Exception:
            pass

        # Nav buttons
        for _p, lbl in getattr(self, '_nav_btns', {}).items():
            try:
                active = (_p == getattr(self, '_current_page', 'main'))
                lbl.config(font=(F_UI, _sf(10), "bold") if active else (F_UI, _sf(10)))
            except Exception:
                pass
        for _p, (row, icon_lbl) in getattr(self, '_nav_rows', {}).items():
            try:
                icon_lbl.config(font=(F_UI, _sf(13)))
            except Exception:
                pass

        # ── Content area wraplengths ─────────────────────────────────────
        wrap = max(200, w - sidebar_w - 140)

        # Game banner + mood
        try:
            self.game_banner.config(font=(F_UI, _sf(14), "bold"), wraplength=wrap)
        except Exception:
            pass
        try:
            self.mood_lbl.config(font=(F_UI, _sf(11)), wraplength=wrap)
        except Exception:
            pass
        try:
            self.playlist_display_lbl.config(font=(F_UI, _sf(10), "italic"), wraplength=wrap)
        except Exception:
            pass

        # Track title
        try:
            self.track_lbl.config(font=(F_UI, _sf(22), "bold"), wraplength=wrap)
        except Exception:
            pass

        # Status log
        try:
            self.status_log_lbl.config(font=(F_UI, _sf(10)), wraplength=wrap)
        except Exception:
            pass

        # Header status
        try:
            self.status_pill.config(font=(F_UI, _sf(9)))
        except Exception:
            pass

        # Seamless music description
        try:
            self._seamless_desc_lbl.config(
                font=(F_UI, _sf(9)), wraplength=max(200, wrap - 60))
        except Exception:
            pass

        # Playlists / blocked page labels
        for attr in ('pl_status_lbl', 'blocked_status_lbl'):
            try:
                lbl = getattr(self, attr, None)
                if lbl:
                    lbl.config(font=(F_UI, _sf(10)), wraplength=wrap)
            except Exception:
                pass

        # Store for other code
        self._dynamic_wrap = wrap
        self._ui_scale = scale

    def _nav(self, page):
        self._current_page = page

        # Update nav button styles: active indicator + bg
        for p, lbl in self._nav_btns.items():
            active = (p == page)
            row, icon_lbl = self._nav_rows.get(p, (None, None))
            ind = self._nav_indicators.get(p)
            bg_c  = SURFACE3 if active else SIDEBAR
            fg_c  = TEXT    if active else TEXT_SEC
            ind_c = ACCENT  if active else SIDEBAR
            try:
                lbl.config(fg=fg_c, font=(F_UI, 10, "bold") if active else (F_UI, 10),
                            bg=bg_c)
            except Exception:
                pass
            if row:
                try: row.config(bg=bg_c)
                except: pass
            if icon_lbl:
                try: icon_lbl.config(bg=bg_c, fg=ACCENT if active else TEXT_MUTED)
                except: pass
            if ind:
                try:
                    ind.config(bg=bg_c)
                    ind.delete("all")
                    ind.create_rectangle(0, 6, 3, 32, fill=ind_c, outline="")
                except: pass

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
        # Create page frames inside self.content
        self._page_main = tk.Frame(self.content, bg=BG)
        self._page_playlists = tk.Frame(self.content, bg=BG)
        self._page_games = tk.Frame(self.content, bg=BG)
        self._page_blocked = tk.Frame(self.content, bg=BG)
        self._page_settings = tk.Frame(self.content, bg=BG)
        self._page_faq = tk.Frame(self.content, bg=BG)

        # Build page contents
        try:
            self._build_main_page()
            self._build_playlists_page()
            self._build_games_page()
            self._build_blocked_page()
            self._build_settings_page()
            self._build_faq_page()
        except Exception:
            pass

        # Show default page
        self._nav('main')

    def _card(self, parent, pady=16):
        """Elevated card with border and inner padding."""
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        outer.pack(fill=tk.X, pady=pady)
        inner = tk.Frame(outer, bg=SURFACE)
        inner.pack(fill=tk.X)
        content = tk.Frame(inner, bg=SURFACE, padx=32, pady=28)
        pack_padded(content, fill=tk.X)
        return content

    def _section_lbl(self, parent, text):
        """Section label with horizontal rule — minimal and elegant."""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill=tk.X, padx=2, pady=(24, 12))
        tk.Label(row, text=text.upper(), bg=BG, fg=TEXT_MUTED,
                 font=(F_UI, 8, "bold")).pack(side=tk.LEFT, padx=(2, 0))
        tk.Frame(row, bg=BORDER2, height=1).pack(side=tk.LEFT, fill=tk.X,
                                                  expand=True, padx=(16, 0), pady=7)

    # ── MAIN PAGE ─────────────────────────────────────────────────────────────

    def _build_main_page(self):
        p = self._page_main

        # Scrollable wrapper so content never clips vertically
        main_canvas = tk.Canvas(p, bg=BG, highlightthickness=0)
        main_sb = ttk.Scrollbar(p, orient=tk.VERTICAL, command=main_canvas.yview)
        main_canvas.configure(yscrollcommand=main_sb.set)
        main_sb.pack(side=tk.RIGHT, fill=tk.Y)
        main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll_inner = tk.Frame(main_canvas, bg=BG)
        canvas_win = main_canvas.create_window((0, 0), window=scroll_inner, anchor="nw")

        def _on_canvas_resize(e):
            main_canvas.itemconfig(canvas_win, width=e.width)
        main_canvas.bind("<Configure>", _on_canvas_resize)
        scroll_inner.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))

        def _on_mousewheel(e):
            cx, cy = main_canvas.winfo_rootx(), main_canvas.winfo_rooty()
            cw, ch = main_canvas.winfo_width(), main_canvas.winfo_height()
            mx, my = e.x_root, e.y_root
            if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                main_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        main_canvas.bind("<Enter>", lambda e: main_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        main_canvas.bind("<Leave>", lambda e: main_canvas.unbind_all("<MouseWheel>"))

        mp = scroll_inner

        # ── Now Playing card ─────────────────────────────────────────────────
        self._section_lbl(mp, "Now Playing")
        np = self._card(mp, pady=0)

        # Game name row + auto-play toggle
        status_row = tk.Frame(np, bg=SURFACE)
        status_row.pack(fill=tk.X, pady=(0, 4))

        # Game icon + name
        self.game_banner = tk.Label(
            status_row, text="No saved game running",
            bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 14, "bold"),
            anchor=tk.W)
        self.game_banner.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Auto toggle — right-aligned, cleaner
        auto_frame = tk.Frame(status_row, bg=SURFACE)
        auto_frame.pack(side=tk.RIGHT)
        tk.Label(auto_frame, text="Auto", bg=SURFACE, fg=TEXT_MUTED,
                 font=(F_UI, 8, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        tk.Checkbutton(auto_frame, variable=self.auto_mode,
                       bg=SURFACE, fg=ACCENT, selectcolor=ACCENT_BG,
                       activebackground=SURFACE, relief=tk.FLAT,
                       cursor="hand2").pack(side=tk.LEFT)

        # Mood / hint line
        self.mood_lbl = tk.Label(
            np, text="Add games in My Games \u2014 music starts when they run",
            bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 11),
            anchor=tk.W, justify=tk.LEFT)
        self.mood_lbl.pack(fill=tk.X, pady=(0, 16))

        self.playlist_display_lbl = tk.Label(
            np, text="Playlist: \u2014", bg=SURFACE, fg=ACCENT,
            font=(F_UI, 10, "italic"), anchor=tk.W)
        self.playlist_display_lbl.pack(fill=tk.X, pady=(0, 16))

        # Thin separator before track info
        tk.Frame(np, bg=BORDER2, height=1).pack(fill=tk.X, pady=(0, 16))

        # Track info — large and prominent
        self.track_lbl = tk.Label(
            np, text="Nothing playing", bg=SURFACE,
            fg=TEXT, font=(F_UI, 22, "bold"),
            justify=tk.LEFT, anchor=tk.W)
        self.track_lbl.pack(fill=tk.X, pady=(0, 4))

        self.artist_lbl = tk.Label(
            np, text="", bg=SURFACE, fg=TEXT_SEC, font=(F_UI, 12))

        # Status message area (Latest activity only)
        self.status_log_lbl = tk.Label(
            np, text="GameBeats ready.", bg=SURFACE2, fg=ACCENT,
            font=(F_UI, 10), anchor=tk.W, justify=tk.LEFT,
            padx=18, pady=16)
        self.status_log_lbl.pack(fill=tk.X, pady=(10, 0))

        # Hidden art label for PIL compatibility
        self.art_label = tk.Label(np, text="", bg=SURFACE)

        # ── Controls card ─────────────────────────────────────────────────────
        self._section_lbl(mp, "Controls")
        ctrl = self._card(mp, pady=0)

        # Transport controls — centred with generous spacing
        ctrl_row = tk.Frame(ctrl, bg=SURFACE)
        ctrl_row.pack(pady=(20, 30), anchor="center")

        self.prev_btn = CircleBtn(ctrl_row, "\u23ee", command=self._prev,
                                  size=64, font_size=16, canvas_bg=SURFACE)
        self.prev_btn.pack(side=tk.LEFT, padx=25)

        self.play_btn = CircleBtn(
            ctrl_row, "\u25b6", command=self._play_pause_toggle,
            size=84, bg=ACCENT, fg="#000", font_size=28,
            canvas_bg=SURFACE, accent=True)
        self.play_btn.pack(side=tk.LEFT, padx=25)

        self.next_btn = CircleBtn(ctrl_row, "\u23ed", command=self._next,
                                  size=64, font_size=16, canvas_bg=SURFACE)
        self.next_btn.pack(side=tk.LEFT, padx=25)

        seamless_row = tk.Frame(ctrl, bg=SURFACE)
        seamless_row.pack(fill=tk.X, pady=(0, 16))
        seamless_copy = tk.Frame(seamless_row, bg=SURFACE)
        seamless_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            seamless_copy,
            text="Seamless music",
            bg=SURFACE,
            fg=TEXT,
            font=(F_UI, 11, "bold"),
            anchor="w",
        ).pack(fill=tk.X)
        self._seamless_desc_lbl = tk.Label(
            seamless_copy,
            text="With this on, music will not pause when game sound is detected.",
            bg=SURFACE,
            fg=TEXT_MUTED,
            font=(F_UI, 9),
            anchor="w",
            justify=tk.LEFT,
        )
        self._seamless_desc_lbl.pack(fill=tk.X, pady=(2, 0))
        tk.Checkbutton(
            seamless_row,
            variable=self.seamless_music_var,
            command=self._save_player_settings,
            bg=SURFACE,
            fg=ACCENT,
            selectcolor=ACCENT_BG,
            activebackground=SURFACE,
            relief=tk.FLAT,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(18, 0))

        # Divider
        tk.Frame(ctrl, bg=BORDER2, height=1).pack(fill=tk.X, pady=(2, 16))

        # Action buttons row
        actions = tk.Frame(ctrl, bg=SURFACE)
        actions.pack(fill=tk.X, pady=(15, 20))

        self.block_pl_btn = RoundedButton(
            actions, text="\u2205  Block playlist",
            command=self._block_current_playlist,
            width=212, height=60, bg=SURFACE3, fg=AMBER,  # +12px to w/h for 6px padding
            font_size=10, canvas_bg=SURFACE, border_color=BORDER2)
        self.block_pl_btn.pack(side=tk.LEFT, padx=(0, 20))

        RoundedButton(
            actions, text="\u21ba  Try another",
            command=self._try_another_playlist,
            width=192, height=60, bg=SURFACE2, fg=TEXT_SEC,  # +12px to w/h for 6px padding
            font_size=10, canvas_bg=SURFACE, border_color=BORDER2,
        ).pack(side=tk.LEFT, padx=(0, 10))

    # ── PLAYLISTS PAGE ────────────────────────────────────────────────────────

    def _build_playlists_page(self):
        p = self._page_playlists

        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill=tk.X, pady=(4, 10))
        tk.Label(hdr, text="Your Playlists", bg=BG, fg=TEXT,
                 font=(F_UI, 16, "bold")).pack(side=tk.LEFT)
        btn_row = tk.Frame(hdr, bg=BG)
        btn_row.pack(side=tk.RIGHT, padx=(0, 4))
        self.pl_add_btn = RoundedButton(
            btn_row, text="+ Add link", command=self._add_playlist_link,
            width=120, height=36, bg=SURFACE2, fg=TEXT_SEC,
            font_size=10, canvas_bg=BG, border_color=BORDER2)
        self.pl_add_btn.pack(side=tk.RIGHT, padx=(6, 0))
        RoundedButton(btn_row, text="\u21ba Refresh", command=self._load_playlists,
                      width=120, height=36, bg=SURFACE2, fg=TEXT_SEC,
                      font_size=10, canvas_bg=BG, border_color=BORDER2).pack(side=tk.RIGHT)

        self.pl_status_lbl = tk.Label(
            p, text="Connect Spotify in Settings to load playlists.",
            bg=BG, fg=TEXT_MUTED, font=(F_UI, 10),
            wraplength=400, justify=tk.LEFT)
        self.pl_status_lbl.pack(fill=tk.X, pady=(0, 14))

        # Scrollable list
        wrapper = tk.Frame(p, bg=BG)
        wrapper.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrapper, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.pl_inner = tk.Frame(canvas, bg=BG)
        canvas_win = canvas.create_window((0, 0), window=self.pl_inner, anchor="nw")

        def on_resize(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind("<Configure>", on_resize)
        self.pl_inner.bind("<Configure>",
                           lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_mousewheel(e):
            cx, cy = canvas.winfo_rootx(), canvas.winfo_rooty()
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            mx, my = e.x_root, e.y_root
            if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                canvas.yview_scroll(-1 * (e.delta // 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    # ── GAMES PAGE ───────────────────────────────────────────────────────

    def _build_games_page(self):
        GamesPage(
            self._page_games,
            on_games_changed=lambda: self._log("Game list updated."),
        ).pack(fill=tk.BOTH, expand=True)

    # ── BLOCKED PAGE ──────────────────────────────────────────────────────────

    def _build_blocked_page(self):
        p = self._page_blocked

        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill=tk.X, pady=(4, 10))
        tk.Label(hdr, text="Blocked Playlists", bg=BG, fg=TEXT,
                 font=(F_UI, 16, "bold")).pack(side=tk.LEFT)
        RoundedButton(hdr, text="\u21ba Refresh", command=self._refresh_blocked_page,
                      width=90, height=30, bg=SURFACE2, fg=TEXT_SEC,
                      font_size=9, canvas_bg=BG, border_color=BORDER2).pack(side=tk.RIGHT, padx=(0, 4))

        self.blocked_status_lbl = tk.Label(
            p, text="Playlists blocked from auto-play appear here.",
            bg=BG, fg=TEXT_MUTED, font=(F_UI, 10),
            wraplength=400, justify=tk.LEFT)
        self.blocked_status_lbl.pack(fill=tk.X, pady=(0, 14))

        # Scrollable list
        wrapper = tk.Frame(p, bg=BG)
        wrapper.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrapper, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.blocked_inner = tk.Frame(canvas, bg=BG)
        canvas_win = canvas.create_window((0, 0), window=self.blocked_inner, anchor="nw")

        def on_resize(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind("<Configure>", on_resize)
        self.blocked_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_mousewheel(e):
            cx, cy = canvas.winfo_rootx(), canvas.winfo_rooty()
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            mx, my = e.x_root, e.y_root
            if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _refresh_blocked_page(self):
        if not hasattr(self, "blocked_inner"):
            return
        for w in self.blocked_inner.winfo_children():
            w.destroy()

        blocked = self._blocked_playlists()
        if not blocked:
            self.blocked_status_lbl.config(
                text="No blocked playlists \u2014 block one from the Player page.",
                fg=TEXT_MUTED)
            return

        count = len(blocked)
        self.blocked_status_lbl.config(
            text=f"{count} blocked playlist{'s' if count != 1 else ''}",
            fg=TEXT_SEC)

        for item in blocked:
            uri  = item.get("uri", "")
            name = item.get("name") or uri.split(":")[-1] or "Blocked playlist"
            query = item.get("query", "")

            row = tk.Frame(self.blocked_inner, bg=SURFACE2)
            row.pack(fill=tk.X, pady=3, padx=(0, 4))

            # Left: block badge
            badge = tk.Frame(row, bg="#3A1A10", width=52)
            badge.pack(side=tk.LEFT, fill=tk.Y)
            badge.pack_propagate(False)
            tk.Label(badge, text="\u2205", bg="#3A1A10", fg=AMBER,
                     font=("Segoe UI", 14)).pack(expand=True)

            # Right: unblock button (Packed FIRST so it claims space and avoids clipping)
            un_frame = tk.Frame(row, bg=SURFACE2)
            un_frame.pack(side=tk.RIGHT, padx=(8, 16))
            un_l = tk.Label(un_frame, text="Unblock", bg=SURFACE2, fg=ACCENT,
                            font=("Segoe UI", 9, "bold"), cursor="hand2")
            un_l.pack()
            un_l.bind("<Button-1>", lambda e, u=uri: (
                self._unblock_playlist(u),
                self._refresh_blocked_page(),
            ))

            # Middle: name + detail (Packed SECOND, expands into remaining space)
            col = tk.Frame(row, bg=SURFACE2)
            col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=14, pady=12)
            
            # Wrap after ~5 words (around 350px)
            tk.Label(col, text=name, bg=SURFACE2, fg=TEXT,
                     font=("Segoe UI", 11, "bold"), anchor=tk.W, justify=tk.LEFT, 
                     wraplength=350).pack(anchor=tk.W, fill=tk.X)
            
            detail = (query or uri)[:80]
            tk.Label(col, text=detail, bg=SURFACE2, fg=TEXT_MUTED,
                     font=("Segoe UI", 9), anchor=tk.W, justify=tk.LEFT,
                     wraplength=350).pack(anchor=tk.W, fill=tk.X)

    # ── SETTINGS PAGE ─────────────────────────────────────────────────────────

    def _build_settings_page(self):
        p = self._page_settings

        # ── Auto Playlists ────────────────────────────────────────────────────
        self._section_lbl(p, "Auto playlists")
        ap = self._card(p, pady=0)

        pick_row = tk.Frame(ap, bg=SURFACE)
        pick_row.pack(fill=tk.X, pady=(0, 12))
        tk.Label(pick_row, text="Playlists to consider", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10)).pack(side=tk.LEFT)
        pick_spin = tk.Spinbox(
            pick_row, from_=1, to=20,
            textvariable=self.playlist_limit_var,
            command=self._save_auto_playlist_settings,
            width=4, bg=SURFACE3, fg=TEXT,
            buttonbackground=SURFACE4, insertbackground=ACCENT,
            relief=tk.FLAT, font=(F_UI, 10),
        )
        pick_spin.pack(side=tk.RIGHT)
        pick_spin.bind("<FocusOut>", self._save_auto_playlist_settings)
        pick_spin.bind("<Return>",   self._save_auto_playlist_settings)

        resume_row = tk.Frame(ap, bg=SURFACE)
        resume_row.pack(fill=tk.X)
        tk.Label(resume_row, text="Resume / end-check delay", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10)).pack(side=tk.LEFT)
        resume_spin = tk.Spinbox(
            resume_row, from_=1, to=30,
            textvariable=self.resume_delay_var,
            command=self._save_audio_settings,
            width=4, bg=SURFACE3, fg=TEXT,
            buttonbackground=SURFACE4, insertbackground=ACCENT,
            relief=tk.FLAT, font=(F_UI, 10),
        )
        resume_spin.pack(side=tk.RIGHT)
        tk.Label(resume_row, text="sec", bg=SURFACE, fg=TEXT_MUTED,
                 font=(F_UI, 9)).pack(side=tk.RIGHT, padx=(0, 8))
        resume_spin.bind("<FocusOut>", self._save_audio_settings)
        resume_spin.bind("<Return>",   self._save_audio_settings)


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
            self.status_log_lbl.config(text=clean_msg[:120], fg=color)

    def _set_status(self, text, color=TEXT_SEC):
        self.status_pill.config(text=text, fg=color)
        self.status_dot.config(fg=color)

    def _animate_play_effect(self):
        # Animation removed - using cleaner UI without visualization
        pass

    def _on_spotify_ready(self):
        """After player is ready: verify, load playlists, start watchers."""
        ok, msg = self.spotify.verify_access()
        if ok:
            if hasattr(self, "auth_lbl"):
                self.auth_lbl.config(text=f"✓ {msg}", fg=ACCENT)
            self._log(msg)
        else:
            if hasattr(self, "auth_lbl"):
                self.auth_lbl.config(text=f"⚠ {msg[:80]}", fg=AMBER)
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
            self.pl_status_lbl.config(
                text="Add your playlists with + Add link (paste from Spotify Share).",
                fg=TEXT_SEC)
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
            self.config["playback_mode"] = "api"
            self._save_config()
            self.spotify = None
            if self.detector:
                self.detector.stop()
                self.detector = None
            self._log("Switched to API mode — connect credentials below.")
            if hasattr(self, "auth_lbl"):
                self.auth_lbl.config(text="Enter credentials and Connect", fg=TEXT_SEC)
            self._nav("settings")

    def _try_auto_login(self):
        cid = self.config.get("client_id")
        sec = self.config.get("client_secret")
        if cid and sec:
            self.auth = SpotifyAuth(cid, sec)
            if self.auth.load(TOKENS_FILE):
                self.spotify = SpotifyController(self.auth)
                self.root.after(400, self._on_spotify_ready)

    def _connect_spotify(self):
        cid  = self.cid_var.get().strip()
        csec = self.csec_var.get().strip()
        if not cid or not csec:
            self.auth_lbl.config(text="⚠ Enter both credentials", fg=AMBER)
            return
        self.config["client_id"]     = cid
        self.config["client_secret"] = csec
        self._save_config()
        self.auth = SpotifyAuth(cid, csec)
        self.auth_lbl.config(text="⏳ Browser opening…", fg=AMBER)
        self._log("Waiting for Spotify login…")

        def done(ok):
            if ok:
                self.config["playback_mode"] = "api"
                self.desktop_mode_var.set(False)
                self._save_config()
                self.spotify = SpotifyController(self.auth)
                self.auth.save(TOKENS_FILE)
                self._log("Spotify API connected!")
                self._on_spotify_ready()
            else:
                self.auth_lbl.config(text="✗ Auth failed — try again", fg=RED)

        self.auth.start_auth_flow(on_complete=lambda s: self.root.after(0, lambda: done(s)))

    def _build_faq_page(self):
        p = self._page_faq

        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill=tk.X, pady=(4, 10))
        tk.Label(hdr, text="FAQ & Help", bg=BG, fg=TEXT,
                 font=(F_UI, 16, "bold")).pack(side=tk.LEFT)

        # Scrollable wrapper
        wrapper = tk.Frame(p, bg=BG)
        wrapper.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(wrapper, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrapper, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=BG)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_resize(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind("<Configure>", on_resize)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_mousewheel(e):
            cx, cy = canvas.winfo_rootx(), canvas.winfo_rooty()
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            mx, my = e.x_root, e.y_root
            if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                canvas.yview_scroll(-1 * (e.delta // 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # Content Cards
        self._section_lbl(inner, "Important Information")
        c1 = self._card(inner)
        tk.Label(c1, text="Not a Spotify Replacement", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 11, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 6))
        tk.Label(c1, text="GameBeats is a companion tool designed to seamlessly integrate with your existing setup. It is not a standalone player; you must have the official Spotify client installed and running to use this application.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X, pady=(0, 12))
        
        tk.Label(c1, text="Spotify Free Users", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 11, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 6))
        tk.Label(c1, text="Supporting free Spotify accounts required overcoming significant technical limitations, but we made it happen. Please note that on first start, the free-tier desktop client might be a bit clunky to connect to. We apologize for any inconvenience, but it should work smoothly most of the time.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

        self._section_lbl(inner, "Important Setup Steps")
        c_web = self._card(inner)
        tk.Label(c_web, text="1. One-Time Login Window", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c_web, text="On your first run, a secondary Spotify window will open. You MUST log in to Spotify here to establish the connection. Crucially, make sure you log in using the exact same Spotify account that is currently active on your main Spotify Desktop app.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X, pady=(0, 12))

        tk.Label(c_web, text="2. Do Not Close the Helper Window", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c_web, text="While a game is running, you may notice this helper window remain open in the background. Please DO NOT close this window manually! It is required to maintain the connection. If you close it, your music will stop syncing.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X, pady=(0, 12))

        tk.Label(c_web, text="3. Desktop App Required", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c_web, text="Even with the helper window open, you must always have the official Spotify Desktop application running on your PC for the app to route audio and detect playback correctly.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

        self._section_lbl(inner, "Best Practices")
        c2 = self._card(inner)
        tk.Label(c2, text="1. Official Spotify Client Only", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c2, text="Please ensure you are using the Spotify Desktop client downloaded directly from the official Spotify website (.exe). GameBeats does not support the Microsoft Store version.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X, pady=(0, 12))
        
        tk.Label(c2, text="2. Dedicated Playback Device", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c2, text="For the best experience, ensure your Spotify account is actively playing only on your local desktop client. Remote playback from other devices may interrupt the application's tracking.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X, pady=(0, 12))

        tk.Label(c2, text="3. Adding Games Correctly", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c2, text="When adding games to your library, please select the actual game executable (.exe) from your installation folder. Avoid using desktop shortcuts or Steam URL links, as these cannot be properly tracked.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X, pady=(0, 12))

        tk.Label(c2, text="4. Audio Capture & Muting", bg=SURFACE, fg=TEXT,
                 font=(F_UI, 10, "bold"), anchor=tk.W).pack(fill=tk.X, pady=(0, 4))
        tk.Label(c2, text="GameBeats listens to your game's audio to automatically pause and resume music. Do not mute your games or Spotify in the Windows Volume Mixer, otherwise the detection will not work.",
                 bg=SURFACE, fg=TEXT_MUTED, font=(F_UI, 9), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

        self._section_lbl(inner, "Support & Contact")
        c3 = self._card(inner)
        tk.Label(c3, text="If something isn't working... have you tried turning it off and on again? Restarting the app fixes most issues!\n\nJokes aside, if you need further assistance or have recommendations, feel free to contact me at amongkencod10@gmail.com.\n\nThank you for your purchase, and have fun!",
                 bg=SURFACE, fg=TEXT, font=(F_UI, 10, "italic"), wraplength=450, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

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

    def _on_game_found(self, info):
        self.current_game = info
        self._game_pid = info.get("pid") or get_pid_for_proc(info.get("proc", ""))
        mood_info = MOOD_TO_PLAYLIST.get(info["mood"], {})
        color = mood_info.get("color", ACCENT)
        self.root.after(0, lambda: (
            self.game_banner.config(text=f"🎮  {info['name']}", fg=color),
            self.mood_lbl.config(
                text=f"Mood → {mood_info.get('name', info['mood'])}  ·  loud game audio pauses music…"),
            self._set_status(info["name"], color),
            self._log(f"Game running: {info['name']}"),
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
            self.game_banner.config(text="No saved game running", fg=TEXT_MUTED),
            self.mood_lbl.config(text="Add games in My Games — music starts when they run"),
            self.playlist_display_lbl.config(text="Playlist: —"),
            self._set_status("Watching games", ACCENT),
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
            self.playlist_display_lbl.config(text=f"Playlist: {self._current_playlist_name or '\u2014'}"),
            self.track_lbl.config(text=self._current_playlist_name or "Spotify Playlist"),
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
                err_lbl.config(text=err)

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
            self.pl_status_lbl.config(
                text="Enable playback in Settings.", fg=TEXT_MUTED)
            return
        if self._is_desktop_mode():
            self.pl_status_lbl.config(
                text="Your saved playlist links:", fg=TEXT_SEC)
        else:
            self.pl_status_lbl.config(text="Loading playlists…", fg=TEXT_SEC)
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
            self.pl_status_lbl.config(text=f"\u26a0  {short}", fg=AMBER, wraplength=400)
            if "premium" in err.lower() and not self._is_desktop_mode():
                self._log("Tip: enable Free desktop mode in Settings (no Premium).")
            return
        if not pls:
            if self._is_desktop_mode():
                self.pl_status_lbl.config(
                    text="No playlists yet \u2014 click + Add link above.", fg=TEXT_MUTED)
            else:
                self.pl_status_lbl.config(
                    text="No playlists found on this account.", fg=TEXT_MUTED)
            self._render_blocked_playlists(blocked)
            return
        self.pl_status_lbl.config(text=f"{len(pls)} playlist{'s' if len(pls) != 1 else ''}", fg=TEXT_SEC)
        for pl in pls[:30]:
            row = tk.Frame(self.pl_inner, bg=SURFACE, cursor="hand2")
            row.pack(fill=tk.X, pady=2)

            # Music note icon — compact pill
            note_c = tk.Canvas(row, width=48, height=48, bg=SURFACE, highlightthickness=0)
            note_c.pack(side=tk.LEFT, padx=(4, 0))
            note_c.create_oval(12, 12, 36, 36, fill=SURFACE3, outline="")
            note_c.create_text(24, 24, text="\u266B", fill=ACCENT, font=("Segoe UI", 12))

            col = tk.Frame(row, bg=SURFACE)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=12, padx=(4, 0))
            tk.Label(col, text=pl["name"], bg=SURFACE, fg=TEXT,
                     font=("Segoe UI", 10, "bold"), anchor=tk.W).pack(anchor=tk.W)
            tk.Label(col, text=f"{pl['tracks']} tracks", bg=SURFACE, fg=TEXT_MUTED,
                     font=("Segoe UI", 8), anchor=tk.W).pack(anchor=tk.W, pady=(1, 0))

            arrow = tk.Label(row, text="\u25B6", bg=SURFACE, fg=TEXT_MUTED,
                             font=("Segoe UI", 10), padx=16)
            arrow.pack(side=tk.RIGHT)

            def _set_row_bg(r, color):
                r.config(bg=color)
                for child in r.winfo_children():
                    try: child.config(bg=color)
                    except tk.TclError: pass

            all_widgets = row.winfo_children() + [row]
            for widget in all_widgets:
                widget.bind("<Button-1>",
                    lambda e, u=pl["uri"], n=pl["name"]: self._play_pl(u, n))
                widget.bind("<Enter>", lambda e, r=row: _set_row_bg(r, SURFACE2))
                widget.bind("<Leave>", lambda e, r=row: _set_row_bg(r, SURFACE))

            if self._is_desktop_mode():
                del_l = tk.Label(row, text="\u2715", bg=SURFACE, fg=TEXT_MUTED,
                                 font=("Segoe UI", 11), padx=10, cursor="hand2")
                del_l.pack(side=tk.RIGHT)
                del_l.bind("<Button-1>",
                    lambda e, u=pl["uri"]: self._remove_saved_pl(u))

        self._render_blocked_playlists(blocked)

    def _render_blocked_playlists(self, blocked):
        if not blocked:
            return
        tk.Label(
            self.pl_inner, text="BLOCKED PLAYLISTS",
            bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 8, "bold"),
        ).pack(anchor=tk.W, padx=2, pady=(16, 4))
        for item in blocked:
            uri  = item.get("uri", "")
            name = item.get("name") or uri.split(":")[-1] or "Blocked playlist"
            query = item.get("query", "")
            row = tk.Frame(self.pl_inner, bg=SURFACE2)
            row.pack(fill=tk.X, pady=2)

            badge = tk.Frame(row, bg="#3A1A10", width=48)
            badge.pack(side=tk.LEFT, fill=tk.Y)
            badge.pack_propagate(False)
            tk.Label(badge, text="\u2205", bg="#3A1A10", fg=AMBER,
                     font=("Segoe UI", 13)).pack(expand=True)

            col = tk.Frame(row, bg=SURFACE2)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=8)
            tk.Label(col, text=name, bg=SURFACE2, fg=TEXT,
                     font=("Segoe UI", 10, "bold"), anchor=tk.W).pack(anchor=tk.W)
            detail = (query or uri)[:52]
            tk.Label(col, text=detail, bg=SURFACE2, fg=TEXT_MUTED,
                     font=("Segoe UI", 8), anchor=tk.W).pack(anchor=tk.W)
            un_l = tk.Label(row, text="Unblock", bg=SURFACE2, fg=ACCENT,
                            font=("Segoe UI", 9, "bold"), padx=10, cursor="hand2")
            un_l.pack(side=tk.RIGHT)
            un_l.bind("<Button-1>", lambda e, u=uri: self._unblock_playlist(u))

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

    def _set_play_btn_icon(self, playing: bool, force_btn: bool = False):
        """Update internal playing state. Only updates the visible button
        icon when force_btn=True (i.e. user-initiated toggle)."""
        self._is_playing = bool(playing)
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
        self.vol_num.config(text=f"{v}%")
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
        self.track_lbl.config(text=playlist_title)
        self.artist_lbl.config(text="")
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
            with urllib.request.urlopen(url, timeout=5) as r:
                data = r.read()
            img = Image.open(BytesIO(data)).resize((70, 70), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._album_photo = photo
            self.root.after(0, lambda: self.art_label.config(
                image=photo, text="", width=70, height=70))
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
