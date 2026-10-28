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
from urllib.parse import urlparse
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
from ui.puppy_gif import (
    PUPPY_BOB_GIF,
    PUPPY_CHANGE_GIF,
    PUPPY_PAUSE_GIF,
    PUPPY_THINKING_GIF,
    frame_index_at as _gif_frame_index_at,
    thinking_frame_index as _thinking_frame_index,
    load_gif_frames as _load_gif_frames,
    normalize_animation_states as _normalize_animation_states,
    normalize_sprite_frames as _normalize_gif_frames,
)
from ui.runtime_overlay import RuntimeOverlay
from ui.spotify_targeted_transport import install_targeted_transport
from ui.spotify_window_guard import SpotifyWindowGuard
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


PUPPY_ROOM_GIF = PUPPY_BOB_GIF
PUPPY_ROOM_STATE_GIFS = (
    ("idle", PUPPY_ROOM_GIF),
    ("pause", PUPPY_PAUSE_GIF),
    ("change", PUPPY_CHANGE_GIF),
    ("thinking", PUPPY_THINKING_GIF),
)
PUPPY_OVERLAY_GESTURES = (
    ("CLICK", "Pause or resume the music"),
    ("LONG CLICK", "Try another playlist"),
    ("CTRL + DRAG", "Move the puppy anywhere on screen"),
)
PUPPY_OVERLAY_HELP = (
    "The little desktop puppy appears while music plays and stays visible "
    "when you pause, so you can click it again to resume."
)


def _load_puppy_gif(name, *, sprite=False):
    """Decode one of the hand-authored GIF mascots into room-ready frames."""
    path = _design_asset_path(name)
    if not path or not HAS_PIL:
        return (), ()
    try:
        frames, durations = _load_gif_frames(path)
        if sprite:
            frames = _normalize_gif_frames(frames)
        return frames, durations
    except Exception:
        return (), ()


def _load_puppy_animation_states():
    """Load idle/pause/change room animations on one shared canvas."""
    raw = {}
    if HAS_PIL:
        for name, filename in PUPPY_ROOM_STATE_GIFS:
            path = _design_asset_path(filename)
            if not path:
                continue
            try:
                frames, durations = _load_gif_frames(path)
            except Exception:
                continue
            if frames:
                raw[name] = (frames, durations)
    if "idle" in raw:
        try:
            normalized, canvas = _normalize_animation_states(
                raw,
                reference="idle",
                target_size=(64, 72),
                bottom_pad=2,
                margin=1,
            )
            if normalized.get("idle", ((), ()))[0]:
                return normalized, canvas
        except Exception:
            pass
    # Legacy fallback: one bob state on the old 64x72 sprite canvas.
    frames, durations = _load_puppy_gif(PUPPY_ROOM_GIF, sprite=True)
    if frames:
        return {"idle": (frames, durations)}, (64, 72)
    return {}, (64, 72)


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
# The stop/resume paths use a purposefully stricter gate than the visual VU
# meter.  It is the same threshold core uses for source selection, so a tiny
# residual tail cannot make a pause look like a failure (or vice versa).
SPOTIFY_SOURCE_AUDIBLE_THRESHOLD = 0.0015

# Serialise pause/resume commands.  The audio monitor runs on its own thread;
# without this, a user click and an auto-pause can both toggle Spotify and
# leave the UI claiming the opposite of what is actually playing.
_SPOTIFY_COMMAND_FALLBACK_LOCK = threading.RLock()
# A newly-started playlist can take a few seconds to surface its first track
# and audible meter data.  During that window the old mix is already silent,
# so keep the freshly-started play state (and mascot) instead of treating the
# missing metadata as a pause.
FRESH_PLAYBACK_GRACE_SEC = 12.0
# If Spotify's local-status call stalls, do not leave an explicit skip
# thinking forever.  The normal metadata completion usually lands in ~1-2s;
# this is only a safety net for a hung fetch while audio is still playing.
SKIP_COMPLETION_WATCHDOG_MS = 4000


def _is_spotify_web_url(url) -> bool:
    """True only for the real open.spotify.com web player host."""
    try:
        parsed = urlparse(str(url or ""))
        return (
            parsed.scheme in ("http", "https")
            and (parsed.hostname or "").lower() == "open.spotify.com"
        )
    except Exception:
        return False


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
# The CRT is decorative on purpose: it gets no hover outline and no cursor
# change.  The three object hotspots below are full click targets, not just
# hover hints; clicking anywhere inside one navigates to its page.
ROOM_HOTSPOT_PAGES = {
    "shelf": "games",
    "panel": "settings",
    "crate": "playlists",
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
        add_focus_ring(self, base_border=border_color or None, width=2)

    def update_text(self, text):
        self.configure(text=text)

    def set_bg(self, bg):
        self.configure(fg_color=bg)


class CircleBtn(ctk.CTkButton):
    def __init__(self, parent, text="", command=None, size=60,
                 bg=SURFACE3, fg=TEXT, font_size=16, canvas_bg=SURFACE,
                 accent=False, icon=False, **kwargs):
        super().__init__(
            parent, text=text, command=command,
            width=size, height=size, corner_radius=size // 2,
            fg_color=bg, text_color=fg,
            font=(
                T.icon_font(font_size)
                if icon else T.retro_font(font_size, "bold")
            ),
            border_width=0,
            hover_color=T.ACCENT_HOV if accent else SURFACE4,
            **kwargs,
        )
        self.size = size
        self.accent = accent
        self._icon = bool(icon)
        add_focus_ring(self, base_border=None, width=2)

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


def add_focus_ring(widget, base_border=None, focus=GOLD, width=2):
    """Give a widget a crisp, pixel-thin focus ring without moving it."""
    try:
        widget.configure(takefocus=1)
    except Exception:
        pass

    def _focus_in(_event=None):
        try:
            widget.configure(border_width=width, border_color=focus)
        except Exception:
            pass

    def _focus_out(_event=None):
        try:
            widget.configure(
                border_width=width if base_border else 0,
                border_color=base_border or focus,
            )
        except Exception:
            pass

    try:
        widget.bind("<FocusIn>", _focus_in, add="+")
        widget.bind("<FocusOut>", _focus_out, add="+")
    except Exception:
        pass
    return widget


def compute_initial_window_size(screen_w, screen_h, ui_scale=1.0,
                                design_w=WIN_W, design_h=WIN_H):
    """Fit the design window inside the *logical* screen area.

    Tk screen dimensions are physical pixels while geometry strings are
    logical. Dividing the screen by the UI scale prevents a 1260x800 window
    from becoming 2205x1400 on a 150-175% display and hanging off the taskbar.
    """
    try:
        scale = max(1.0, float(ui_scale or 1.0))
    except Exception:
        scale = 1.0
    try:
        screen_w = max(1.0, float(screen_w))
        screen_h = max(1.0, float(screen_h))
    except Exception:
        screen_w, screen_h = float(design_w), float(design_h)

    # Leave room for the taskbar and the custom window controls. The hard
    # minimum stays at the design minimum so the deck never collapses.
    avail_w = max(960.0, screen_w / scale - 60.0)
    avail_h = max(700.0, screen_h / scale - 40.0)
    w = min(int(design_w), max(960, int(avail_w)))
    h = min(int(design_h), max(700, int(avail_h)))
    return w, h


def format_clock(seconds):
    """Format seconds as m:ss for the deck's segmented progress rail."""
    try:
        value = max(0, int(float(seconds)))
    except Exception:
        return "--:--"
    return f"{value // 60}:{value % 60:02d}"


class PixelProgress(tk.Canvas):
    """A pooled, segmented progress rail that only recolours its items."""

    def __init__(self, parent, segments=32, height=12, bg=NIGHT,
                 gap=2, **kwargs):
        super().__init__(
            parent, height=height, bg=bg, highlightthickness=0, bd=0,
            takefocus=0, **kwargs,
        )
        self.segments = max(4, int(segments))
        self.gap = max(1, int(gap))
        self._fraction = 0.0
        self._status_text = ""
        self._status_active = False
        self._items = []
        self._border = None
        self._label = None
        self.bind("<Configure>", lambda _e: self._build(), add="+")

    def _build(self):
        self.delete("progress_seg")
        try:
            w = max(1, self.winfo_width())
            h = max(1, self.winfo_height())
        except Exception:
            return
        usable = max(self.segments, w - self.gap * (self.segments - 1))
        seg_w = max(1, usable // self.segments)
        self._items = []
        x = 0
        for _ in range(self.segments):
            item = self.create_rectangle(
                x, 0, x + seg_w, h, fill=SURFACE4, outline="",
                tags=("progress_seg",),
            )
            self._items.append((item, x, seg_w))
            x += seg_w + self.gap
        self._border = self.create_rectangle(
            0, 0, w - 1, h - 1, outline=WOOD, width=1,
            tags=("progress_seg",),
        )
        self._label = self.create_text(
            w // 2, h // 2, text="", fill=GOLD,
            font=T.pixel_font(8, "bold"), tags=("progress_seg",),
        )
        self._paint()

    def set_progress(self, fraction):
        try:
            value = max(0.0, min(1.0, float(fraction)))
        except Exception:
            value = 0.0
        changed_status = bool(self._status_text)
        self._status_text = ""
        self._status_active = False
        if abs(value - self._fraction) < 0.0015 and not changed_status:
            return
        self._fraction = value
        self._paint()

    def set_status(self, text, active=False):
        """Show a live/standby label when the source exposes no seek data."""
        status = str(text or "").upper()
        active = bool(active)
        if (
            status == self._status_text
            and active == self._status_active
            and self._fraction == 0.0
        ):
            return
        self._status_text = status
        self._status_active = active
        self._fraction = 0.0
        try:
            if self._label is not None:
                self.itemconfigure(
                    self._label,
                    text=self._status_text,
                    fill=GOLD if active else TEXT_MUTED,
                )
        except Exception:
            pass
        self._paint()

    def _paint(self):
        if not self._items:
            return
        count = self.segments
        played = int(self._fraction * count)
        head = played if self._fraction > 0.0 and played < count else -1
        for index, (item, _x, _w) in enumerate(self._items):
            if index < played:
                color = GOLD
            elif index == head:
                color = CREAM
            else:
                color = SURFACE4
            try:
                self.itemconfigure(item, fill=color)
            except Exception:
                pass
        try:
            if self._label is not None:
                self.itemconfigure(
                    self._label,
                    state="normal" if self._status_text else "hidden",
                    text=self._status_text,
                )
        except Exception:
            pass


class PixelToggle(tk.Canvas):
    """A square-edged two-state switch with a visible focus ring."""

    def __init__(self, parent, variable, command=None, width=44, height=20,
                 bg=DECK, **kwargs):
        super().__init__(
            parent, width=width, height=height, bg=bg, highlightthickness=0,
            bd=0, takefocus=1, cursor="hand2", **kwargs,
        )
        self.variable = variable
        self.command = command
        # Never use self._w / self._h here: Tkinter reserves `_w` for the
        # widget's Tcl command path, and overwriting it breaks every canvas
        # operation with "invalid command name".
        self._cw, self._ch = int(width), int(height)
        self._track = self.create_rectangle(
            1, 1, self._cw - 2, self._ch - 2,
            fill=SURFACE4, outline=BORDER2,
        )
        self._knob = self.create_rectangle(
            3, 3, 15, self._ch - 3, fill=TEXT_MUTED, outline="",
        )
        self._led = self.create_rectangle(
            self._cw - 10, self._ch // 2 - 2,
            self._cw - 6, self._ch // 2 + 2,
            fill=NIGHT, outline="",
        )
        self._ring = self.create_rectangle(
            0, 0, self._cw - 1, self._ch - 1,
            outline=GOLD, width=1, state="hidden",
        )
        self.bind("<Button-1>", self._toggle, add="+")
        self.bind("<space>", self._toggle, add="+")
        self.bind("<Return>", self._toggle, add="+")
        self.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.bind("<FocusOut>", lambda _e: self._set_focus(False), add="+")
        try:
            self.variable.trace_add("write", lambda *_a: self._paint())
        except Exception:
            pass
        self._paint()

    def _toggle(self, _event=None):
        try:
            self.variable.set(not bool(self.variable.get()))
        except Exception:
            return "break"
        if self.command is not None:
            try:
                self.command()
            except Exception:
                pass
        try:
            self.focus_set()
        except Exception:
            pass
        return "break"

    def _set_focus(self, focused):
        try:
            self.itemconfigure(self._ring, state="normal" if focused else "hidden")
        except Exception:
            pass

    def _paint(self):
        try:
            on = bool(self.variable.get())
        except Exception:
            on = False
        track = ACCENT_BG if on else SURFACE4
        outline = MINT if on else BORDER2
        knob_left = self._cw - 17 if on else 3
        try:
            self.itemconfigure(self._track, fill=track, outline=outline)
            self.coords(
                self._knob, knob_left, 3, knob_left + 12, self._ch - 3,
            )
            self.itemconfigure(
                self._knob, fill=CREAM if on else TEXT_MUTED,
            )
            self.itemconfigure(self._led, fill=MINT if on else NIGHT)
            self.tag_raise(self._ring)
        except Exception:
            pass


class PixelToast(tk.Frame):
    """Small in-room notification that is reused, never re-created per tick."""

    def __init__(self, parent):
        super().__init__(
            parent, bg=NIGHT, bd=0,
            highlightbackground=GOLD, highlightthickness=2,
        )
        self._eyebrow = tk.Label(
            self, text="", bg=NIGHT, fg=GOLD, anchor="w",
            font=T.pixel_font(9, "bold"),
        )
        self._eyebrow.pack(anchor="w", padx=12, pady=(7, 0))
        self._body = tk.Label(
            self, text="", bg=NIGHT, fg=CREAM, anchor="w", justify=tk.LEFT,
            font=T.retro_font(15),
        )
        self._body.pack(anchor="w", padx=12, pady=(1, 8))
        self._job = None
        self._parent = parent
        self._visible = False

    def show(self, eyebrow, body, ms=2800):
        try:
            self._eyebrow.configure(text=str(eyebrow).upper())
            self._body.configure(text=str(body))
            try:
                width = max(320, int(self._parent.winfo_width() * 0.52))
            except Exception:
                width = 420
            self._body.configure(wraplength=width)
            self.place(relx=0.5, y=12, anchor="n")
            self.lift()
        except Exception:
            return
        self._visible = True
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        try:
            self._job = self.after(max(400, int(ms)), self.hide)
        except Exception:
            self._job = None

    def hide(self):
        self._job = None
        self._visible = False
        try:
            self.place_forget()
        except Exception:
            pass


class PixelTooltip:
    """One reusable dark tooltip with a one-pixel gold border."""

    def __init__(self, root):
        self.root = root
        self.win = None
        self.label = None
        self.job = None
        self.widget = None

    def attach(self, widget, text):
        try:
            widget.bind(
                "<Enter>", lambda _e, w=widget, t=text: self._schedule(w, t),
                add="+",
            )
            widget.bind("<Leave>", lambda _e: self._hide(), add="+")
            widget.bind("<ButtonPress>", lambda _e: self._hide(), add="+")
        except Exception:
            pass
        return widget

    def _schedule(self, widget, text):
        self._cancel()
        try:
            self.job = self.root.after(
                420, lambda: self._show(widget, text)
            )
        except Exception:
            self.job = None

    def _cancel(self):
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None

    def _show(self, widget, text):
        self.job = None
        self.widget = widget
        try:
            if not widget.winfo_exists():
                return
            state = ""
            try:
                state = str(widget.cget("state"))
            except Exception:
                state = ""
            if state.lower() == "disabled":
                return
        except Exception:
            return
        try:
            if self.win is None or not self.win.winfo_exists():
                self.win = tk.Toplevel(self.root)
                self.win.withdraw()
                self.win.overrideredirect(True)
                try:
                    self.win.attributes("-topmost", True)
                except Exception:
                    pass
                self.label = tk.Label(
                    self.win, text="", bg=NIGHT, fg=CREAM,
                    font=T.pixel_font(9), padx=7, pady=4,
                    highlightbackground=GOLD, highlightthickness=1,
                )
                self.label.pack()
            self.label.configure(text=str(text))
            self.win.update_idletasks()
            ww = max(1, self.win.winfo_reqwidth())
            wh = max(1, self.win.winfo_reqheight())
            x = widget.winfo_rootx() + widget.winfo_width() // 2 - ww // 2
            y = widget.winfo_rooty() - wh - 8
            if y < 0:
                y = widget.winfo_rooty() + widget.winfo_height() + 8
            x = max(4, x)
            try:
                sw = self.win.winfo_screenwidth()
                x = min(x, max(4, sw - ww - 4))
            except Exception:
                pass
            self.win.geometry(f"+{int(x)}+{int(y)}")
            self.win.deiconify()
            self.win.lift()
        except Exception:
            self._hide()

    def _hide(self):
        self._cancel()
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.withdraw()
        except Exception:
            pass


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

        # Tk geometry uses logical pixels while winfo_screen* is physical. Fit
        # the design window to the logical screen first, then center using the
        # physical size. This keeps a 176% display from making the window taller
        # than the monitor.
        try:
            ui_scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            ui_scale = 1.0
        self._ui_scale = ui_scale
        init_w, init_h = compute_initial_window_size(sw, sh, ui_scale)
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
        self._playback_started_ts = 0.0
        self._play_in_progress = False
        self._autoplay_pending = False
        self._game_audio = None
        self.auto_mode   = tk.BooleanVar(value=True)
        # Plain-Python mirrors for background threads. Tk variables must only
        # be read on the Tk thread; the audio monitor used to crash at startup
        # with "main thread is not in main loop" when it read auto_mode.
        self._auto_mode_value = True
        self.seamless_music_var = tk.BooleanVar(
            value=bool(self.configure.get("seamless_music", False))
        )
        self._seamless_music_value = bool(
            self.configure.get("seamless_music", False)
        )
        self.startup_var = tk.BooleanVar(value=False)
        self.reduce_motion_var = tk.BooleanVar(
            value=bool(self.configure.get("reduce_motion", False))
        )
        self.desktop_mode_var = tk.BooleanVar(
            value=self.configure.get("playback_mode", "desktop") == "desktop")
        self.cid_var = tk.StringVar(value=self.configure.get("client_id", ""))
        self.csec_var = tk.StringVar(value=self.configure.get("client_secret", ""))
        # auth_lbl is used for status updates during Spotify connection
        self.auth_lbl = ctk.CTkLabel(self.root, text="", fg_color="transparent", text_color=TEXT)
        self.volume_var  = tk.IntVar(value=50)
        self._track_job  = None
        self._track_refresh_jobs = []
        self._track_fetch_busy = False
        self._album_photo = None
        self._game_icon_ctk = None
        self._is_playing  = False
        self._user_toggle_ts = 0.0  # timestamp of last user play/pause click
        self._play_pause_busy = False
        self._play_pause_watchdog = None
        self._spotify_command_lock = threading.RLock()
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
        # "browser" or "desktop" - the source we actually stopped.  Resume uses
        # this instead of a union audio meter that can include unrelated media.
        self._paused_spotify_source = ""
        self._spotify_browser_kind_cache = (0.0, "")
        # A playlist search intentionally pauses the old mix.  This is a
        # transient switch pause, not a user/game pause: the first sustained
        # audio from the newly selected playlist should resume the UI and
        # puppy immediately instead of waiting for the playlist result.
        self._playlist_switch_pause = False
        self._playlist_switch_started_ts = 0.0
        self._playlist_switch_heard_silence = False
        self._playlist_switch_audio_heard_ts = 0.0
        self._playlist_switch_pause_confirmed = False
        # Coalesce "Try another" requests instead of silently dropping them
        # while the previous controller operation is still finishing.
        self._pending_play_request = None
        self._track_change_anim_quiet_until = 0.0
        self._play_request_seq = 0
        self._active_play_request_id = 0
        self._skip_request_seq = 0
        self._skip_completion_job = None
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
            self.root,
            corner="bottom-left",
            on_toggle_play_pause=self._puppy_overlay_toggle,
            on_try_another=self._puppy_overlay_try_another,
            get_playing=self._puppy_overlay_playing,
        )
        self._build_ui()
        self._install_shortcuts()
        # Make layout responsive to window resizes
        self.root.bind("<Configure>", lambda e: self._on_root_resize())

    def _install_shortcuts(self):
        """Global media/navigation keys, suppressed inside text fields."""
        bindings = (
            ("<space>", self._shortcut_space),
            ("<Left>", self._shortcut_prev),
            ("<Right>", self._shortcut_next),
            ("<KeyPress-1>", lambda e: self._shortcut_nav(e, "main")),
            ("<KeyPress-2>", lambda e: self._shortcut_nav(e, "games")),
            ("<KeyPress-3>", lambda e: self._shortcut_nav(e, "playlists")),
            ("<KeyPress-4>", lambda e: self._shortcut_nav(e, "settings")),
            ("<Escape>", self._shortcut_escape),
            ("<F1>", self._shortcut_help),
        )
        for sequence, callback in bindings:
            try:
                self.root.bind_all(sequence, callback, add="+")
            except Exception:
                pass

    def _shortcut_typing(self):
        try:
            widget = self.root.focus_get()
        except Exception:
            return False
        if widget is None:
            return False
        try:
            cls = str(widget.winfo_class()).lower()
        except Exception:
            cls = ""
        if cls in (
            "entry", "text", "tentry", "spinbox", "tscale", "scale",
            "combobox", "tcombobox",
        ):
            return True
        try:
            if isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox, tk.Scale)):
                return True
        except Exception:
            pass
        return False

    def _shortcut_modified(self, event):
        try:
            return bool(int(event.state) & (0x4 | 0x8 | 0x20000))
        except Exception:
            return False

    def _shortcut_space(self, event=None):
        if event is not None and self._shortcut_modified(event):
            return None
        if self._shortcut_typing():
            return None
        try:
            focused = self.root.focus_get()
            if isinstance(focused, (ctk.CTkButton, tk.Button, PixelToggle)):
                return None
        except Exception:
            pass
        try:
            self._play_pause_toggle()
        except Exception:
            pass
        return "break"

    def _shortcut_prev(self, event=None):
        if event is not None and self._shortcut_modified(event):
            return None
        if self._shortcut_typing():
            return None
        try:
            self._prev()
        except Exception:
            pass
        return "break"

    def _shortcut_next(self, event=None):
        if event is not None and self._shortcut_modified(event):
            return None
        if self._shortcut_typing():
            return None
        try:
            self._next()
        except Exception:
            pass
        return "break"

    def _shortcut_nav(self, event, page):
        if event is not None and self._shortcut_modified(event):
            return None
        if self._shortcut_typing():
            return None
        try:
            self._nav(page)
        except Exception:
            pass
        return "break"

    def _shortcut_escape(self, event=None):
        if getattr(self, "_help_win", None) is not None:
            self._close_shortcuts()
            return "break"
        try:
            if getattr(self, "_toast", None) is not None:
                self._toast.hide()
        except Exception:
            pass
        if getattr(self, "_current_page", "main") != "main":
            try:
                self._nav("main")
            except Exception:
                pass
            return "break"
        return None

    def _shortcut_help(self, event=None):
        try:
            if getattr(self, "_help_win", None) is not None:
                self._help_win.lift()
                return "break"
        except Exception:
            pass
        try:
            win = tk.Toplevel(self.root)
            self._help_win = win
            win.overrideredirect(True)
            try:
                win.attributes("-topmost", True)
            except Exception:
                pass
            win.configure(bg=GOLD)
            frame = tk.Frame(win, bg=NIGHT, padx=18, pady=14)
            frame.pack(padx=2, pady=2)
            tk.Label(
                frame, text="KEYBOARD SHORTCUTS", bg=NIGHT, fg=GOLD,
                font=T.pixel_font(11, "bold"), anchor="w",
            ).pack(fill=tk.X, pady=(0, 8))
            rows = (
                ("SPACE", "Play / pause"),
                ("\u2190 / \u2192", "Previous / next track"),
                ("1 / 2 / 3 / 4", "Den / Games / Playlists / Settings"),
                ("ESC", "Back / dismiss"),
                ("F1", "This card"),
            )
            for key, label in rows:
                row = tk.Frame(frame, bg=NIGHT)
                row.pack(fill=tk.X, pady=1)
                tk.Label(
                    row, text=key, bg=NIGHT, fg=CREAM,
                    font=T.pixel_font(9, "bold"), width=14, anchor="w",
                ).pack(side=tk.LEFT)
                tk.Label(
                    row, text=label, bg=NIGHT, fg=TEXT_MUTED,
                    font=T.retro_font(15), anchor="w",
                ).pack(side=tk.LEFT)
            tk.Label(
                frame, text="Click anywhere to close", bg=NIGHT,
                fg=TEXT_MUTED, font=T.retro_font(12),
            ).pack(fill=tk.X, pady=(10, 0))
            win.update_idletasks()
            ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
            rx = self.root.winfo_rootx() + (self.root.winfo_width() - ww) // 2
            ry = self.root.winfo_rooty() + (self.root.winfo_height() - wh) // 2
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            rx = max(4, min(rx, sw - ww - 4))
            ry = max(4, min(ry, sh - wh - 4))
            win.geometry(f"+{int(rx)}+{int(ry)}")
            win.bind("<Button-1>", lambda _e: self._close_shortcuts())
            win.bind("<Escape>", lambda _e: self._close_shortcuts())
            win.focus_set()
        except Exception:
            self._help_win = None
        return "break"

    def _close_shortcuts(self):
        win = getattr(self, "_help_win", None)
        self._help_win = None
        try:
            if win is not None and win.winfo_exists():
                win.destroy()
        except Exception:
            pass

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
        self._ensure_spotify_window_guard()
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
        # Called from the audio-monitor thread, so never touch a Tk variable.
        if hasattr(self, "_seamless_music_value"):
            return bool(self._seamless_music_value)
        try:
            return bool(self.configure.get("seamless_music", False))
        except Exception:
            return False

    def _on_auto_toggle(self):
        try:
            enabled = bool(self.auto_mode.get())
        except Exception:
            enabled = not bool(getattr(self, "_auto_mode_value", True))
        self._auto_mode_value = enabled
        self._log("Auto-play " + ("on" if enabled else "off"))

    def _save_player_settings(self, *_):
        try:
            enabled = bool(self.seamless_music_var.get())
        except Exception:
            enabled = bool(self.configure.get("seamless_music", False))
        self._seamless_music_value = enabled
        self.configure["seamless_music"] = enabled
        self._save_config()
        if enabled and getattr(self, "_paused_by_game_flag", False):
            threading.Thread(
                target=self._resume_spotify_after_game_quiet,
                daemon=True,
            ).start()

    def _save_motion_setting(self, *_):
        try:
            enabled = bool(self.reduce_motion_var.get())
        except Exception:
            enabled = False
        self.configure["reduce_motion"] = enabled
        self._save_config()
        self._log("Reduce motion " + ("on" if enabled else "off"))
        # Rebuild the pooled ambient layer so the room immediately respects
        # the setting instead of waiting for the next resize.
        try:
            if getattr(self, "_current_page", "") == "main":
                self._schedule_room_redraw(0)
        except Exception:
            pass

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
        # The room uses the same hand-authored states as the desktop overlay:
        # an idle bob, a pause/resume reaction, and a playlist-change reaction.
        # All states share one canvas and baseline so the mascot never jumps.
        self._puppy_gif_states, self._puppy_gif_canvas = (
            _load_puppy_animation_states()
        )
        self._puppy_gif_frames, self._puppy_gif_durations = (
            self._puppy_gif_states.get("idle", ((), ()))
        )
        self._puppy_photo_cache = {}
        self._puppy_mood_until = 0.0
        self._puppy_reaction_until = 0.0
        self._puppy_action_state = None
        self._puppy_action_started = 0.0
        self._puppy_action_loops = 1
        self._puppy_action_reverse = False
        self._puppy_action_hold = False
        self._puppy_change_cooldown_until = 0.0
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
        self._room_label_hits = {}
        self._room_hover = None
        self._vu_items = []
        self._vu_key = None
        self._vu_colors = []
        self._vu_heights = []
        self._cart_items = None
        self._cart_key = None
        self._heart_until = 0.0
        self._pet_heart_job = None
        self._puppy_audio_smooth = 0.0
        self._footer_buttons = {}
        self._footer_tools = {}
        self._is_maximized = False
        self._restore_geometry = ""
        self._brand_widgets = []
        self._tooltips = PixelTooltip(self.root)
        self._track_progress_base = None

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

        self._brand_frame = brand
        self._brand_widgets = [brand, paw, brand_title]

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

        for button, hint in (
            (close_btn, "Close GameBeats"),
            (max_btn, "Maximize / restore"),
            (min_btn, "Minimize"),
        ):
            add_focus_ring(button, base_border=None, width=1)
            self._tooltips.attach(button, hint)

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

        details_btn = T.FooterButton(
            topline, text="THE LITTLE DETAILS",
            icon=T.ui_icon("faq"), command=lambda: self._nav("faq"),
            width=194, height=28, base_color=BG, hover_color=SURFACE3,
            text_color=ROSE, icon_color=ROSE, text_size=9, icon_size=12,
        )
        details_btn.pack(side=tk.RIGHT, padx=(0, 28), pady=8)
        self._tooltips.attach(details_btn, "Field notes, shortcuts and help")

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
            ("main", "den", "THE DEN"),
            ("games", "games", "GAME SHELF"),
            ("playlists", "playlists", "RECORD CRATE"),
            ("settings", "settings", "CONTROL PANEL"),
        ]
        for page, icon_name, label in nav_items:
            btn = T.FooterButton(
                nav, text=label, icon=T.ui_icon(icon_name),
                command=lambda p=page: self._nav(p), width=148, height=34,
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

        overlay_btn = T.FooterButton(
            tools, text="OVERLAY", icon=T.ui_icon("overlay"),
            command=self._show_control_overlay, width=98, height=34,
        )
        overlay_btn.pack(side=tk.RIGHT, padx=2, pady=14)
        self._footer_tools["overlay"] = overlay_btn

        faq_btn = T.FooterButton(
            tools, text="FAQ", icon=T.ui_icon("faq"),
            command=lambda: self._nav("faq"), width=74, height=34,
        )
        faq_btn.pack(side=tk.RIGHT, padx=2, pady=14)
        self._footer_tools["faq"] = faq_btn

        blocked_btn = T.FooterButton(
            tools, text="BLOCKED", icon=T.ui_icon("blocked"),
            command=lambda: self._nav("blocked"), width=106, height=34,
        )
        blocked_btn.pack(side=tk.RIGHT, padx=2, pady=14)
        self._footer_tools["blocked"] = blocked_btn

        nav_hints = {
            "main": "The Den  [1]",
            "games": "Game Shelf  [2]",
            "playlists": "Record Crate  [3]",
            "settings": "Control Panel  [4]",
        }
        for page, button in self._footer_buttons.items():
            add_focus_ring(button, base_border=None, width=1)
            self._tooltips.attach(button, nav_hints.get(page, page.title()))
        for key, hint in (
            ("overlay", "Open the desktop puppy controller"),
            ("faq", "Field notes and help"),
            ("blocked", "Manage blocked playlists"),
        ):
            button = self._footer_tools.get(key)
            if button is not None:
                add_focus_ring(button, base_border=None, width=1)
                self._tooltips.attach(button, hint)

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
            self.playlist_display_lbl.configure(wraplength=max(130, cart_w - 58))
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

        previous = getattr(self, "_active_page_widget", None)
        self._current_page = page
        frames = [
            getattr(self, "_page_main", None),
            getattr(self, "_page_playlists", None),
            getattr(self, "_page_games", None),
            getattr(self, "_page_blocked", None),
            getattr(self, "_page_settings", None),
            getattr(self, "_page_faq", None),
        ]

        page_map = {
            "main": getattr(self, "_page_main", None),
            "playlists": getattr(self, "_page_playlists", None),
            "games": getattr(self, "_page_games", None),
            "blocked": getattr(self, "_page_blocked", None),
            "settings": getattr(self, "_page_settings", None),
            "faq": getattr(self, "_page_faq", None),
        }
        target = page_map.get(page)

        # The den uses the full height of the content area.  Every other page
        # keeps the breadcrumb / clock strip so the room label does not feel
        # disconnected from the rest of the app.
        self._set_topline_visible(page != "main")

        for frame in frames:
            if frame is None or frame is target:
                continue
            try:
                frame.place_forget()
            except Exception:
                try:
                    frame.pack_forget()
                except Exception:
                    pass

        if target is not None:
            self._show_page(target, previous)
            self._active_page_widget = target

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

    def _set_topline_visible(self, visible):
        """Show or hide the breadcrumb strip without disturbing pack order."""
        topline = getattr(self, "topline", None)
        content = getattr(self, "content", None)
        if topline is None:
            return
        try:
            managed = bool(topline.winfo_manager())
        except Exception:
            managed = False
        try:
            if visible:
                if not managed:
                    topline.pack(fill=tk.X, before=content)
            elif managed:
                topline.pack_forget()
        except Exception:
            pass

    def _cancel_page_transition(self):
        job = getattr(self, "_page_transition_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._page_transition_job = None

    def _show_page(self, target, previous=None):
        """Reveal a page with a short slide-in, or instantly if motion is off."""
        self._cancel_page_transition()
        if target is None:
            return

        if target is previous:
            try:
                target.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception:
                pass
            return

        if previous is None or self._reduce_motion_enabled():
            try:
                target.place(x=0, y=0, relwidth=1, relheight=1)
                target.lift()
            except Exception:
                pass
            if previous is not None:
                try:
                    previous.place_forget()
                except Exception:
                    pass
            return

        try:
            self.content.update_idletasks()
            width = max(1, int(self.content.winfo_width()))
        except Exception:
            width = WIN_W
        offset = max(8, min(24, int(width * 0.018)))
        self._page_transition_target = target
        self._page_transition_previous = previous
        self._page_transition_offset = offset
        self._page_transition_step = 0
        self._page_transition_steps = 6
        try:
            target.place(x=offset, y=0, relwidth=1, relheight=1)
            target.lift()
            self._page_transition_job = self.root.after(
                14, self._step_page_transition
            )
        except Exception:
            try:
                target.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception:
                pass

    def _step_page_transition(self):
        self._page_transition_job = None
        target = getattr(self, "_page_transition_target", None)
        if target is None:
            return
        step = int(getattr(self, "_page_transition_step", 0)) + 1
        total = max(1, int(getattr(self, "_page_transition_steps", 6)))
        self._page_transition_step = step
        if step >= total:
            try:
                target.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception:
                pass
            previous = getattr(self, "_page_transition_previous", None)
            if previous is not None and previous is not target:
                try:
                    previous.place_forget()
                except Exception:
                    pass
            self._page_transition_target = None
            self._page_transition_previous = None
            return
        remaining = (1.0 - (step / float(total))) ** 2
        offset = int(getattr(self, "_page_transition_offset", 12) * remaining)
        try:
            target.place(x=max(0, offset), y=0, relwidth=1, relheight=1)
            target.lift()
            self._page_transition_job = self.root.after(
                14, self._step_page_transition
            )
        except Exception:
            try:
                target.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception:
                pass

    def _make_footer_button_clickable(self, button):
        """Give every part of a footer button the hand cursor.

        The button is created with a solid NIGHT fill, so its internal canvas
        is a real hit target across the whole padded rectangle.  This helper
        extends the hand cursor to that canvas and the internal text label so
        the full-sized target feels clickable, not just the glyphs.
        """
        for widget in (
            button,
            getattr(button, "_canvas", None),
            getattr(button, "_text_label", None),
            getattr(button, "_image_label", None),
        ):
            if widget is None:
                continue
            try:
                widget.configure(cursor="hand2")
            except Exception:
                pass

    def _paint_footer(self, page):
        for key, btn in getattr(self, "_footer_buttons", {}).items():
            try:
                if hasattr(btn, "set_active"):
                    btn.set_active(key == page)
                elif key == page:
                    btn.configure(fg_color=SURFACE2, text_color=ACCENT)
                else:
                    btn.configure(fg_color=NIGHT, text_color=TEXT_MUTED)
            except Exception:
                pass
        for key, btn in getattr(self, "_footer_tools", {}).items():
            try:
                if hasattr(btn, "set_active"):
                    btn.set_active(key == page)
                elif key == page:
                    btn.configure(fg_color=SURFACE2, text_color=ACCENT)
                else:
                    btn.configure(fg_color=NIGHT, text_color=TEXT_MUTED)
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

        self._active_page_widget = None
        self._page_transition_job = None
        self._page_transition_target = None
        self._page_transition_previous = None
        self._page_transition_step = 0
        self._page_transition_steps = 6
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
        # Reused in-room notification for track changes, playlist switches,
        # shortcuts, and recoverable errors. It lives above the room canvas.
        self._toast = PixelToast(mp)
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
        self._deck.grid_columnconfigure(0, weight=1)
        self._deck.grid_rowconfigure(1, weight=1)
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
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
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
        body.grid(row=1, column=0, sticky="nsew", padx=9, pady=(7, 4))
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
            head, fg_color="transparent", width=40, height=40, corner_radius=0,
            border_width=0,
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
            text_color=TEXT, font=T.pixel_font(12, "bold"),
            anchor="w", justify=tk.LEFT, wraplength=160,
        )
        self.game_banner.pack(fill=tk.X)

        self.mood_lbl = ctk.CTkLabel(
            name_col, text="Waiting for a game", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(14),
            anchor="w", justify=tk.LEFT, wraplength=160,
        )
        self.mood_lbl.pack(fill=tk.X, pady=(1, 0))

        playlist_panel = ctk.CTkFrame(
            cart_label, fg_color=SURFACE3, corner_radius=3,
            border_width=1, border_color=BORDER2,
        )
        playlist_panel.pack(fill=tk.X, padx=7, pady=(4, 0))

        ctk.CTkLabel(
            playlist_panel, text="\u25b8  NOW LOADED", fg_color="transparent",
            text_color=ACCENT, font=T.pixel_font(8, "bold"), anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(5, 0))

        self.playlist_display_lbl = ctk.CTkLabel(
            playlist_panel, text="Nothing loaded yet", fg_color="transparent",
            text_color=CREAM, font=T.retro_font(18),
            anchor="w", justify=tk.LEFT, wraplength=190,
        )
        self.playlist_display_lbl.pack(fill=tk.X, padx=8, pady=(0, 6))

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
        # Inset display bevel: a lit upper lip and a dark lower lip.
        try:
            tk.Frame(disp, bg="#7A4350", height=1).place(x=2, y=2, relwidth=0.99)
            tk.Frame(disp, bg=SURFACE, height=1).place(
                x=2, rely=1.0, y=-3, relwidth=0.99,
            )
        except Exception:
            pass

        inner = ctk.CTkFrame(disp, fg_color=NIGHT, corner_radius=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=7)

        status_row = ctk.CTkFrame(inner, fg_color="transparent", corner_radius=0)
        status_row.pack(fill=tk.X)

        self.deck_status_lbl = ctk.CTkLabel(
            status_row, text="\u25cb  STANDING BY", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(10, "bold"),
        )
        self.deck_status_lbl.pack(side=tk.LEFT)

        ctk.CTkLabel(
            status_row, text="SIDE A / AUTO", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        ).pack(side=tk.RIGHT)

        self.track_lbl = ctk.CTkLabel(
            inner, text="Nothing playing", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(24),
            anchor="w", justify=tk.LEFT,
        )
        self.track_lbl.pack(fill=tk.X, pady=(2, 0))

        self.deck_artist_lbl = ctk.CTkLabel(
            inner, text="Connect Spotify in Control Panel", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(16),
            anchor="w", justify=tk.LEFT,
        )
        self.deck_artist_lbl.pack(fill=tk.X, pady=(0, 1))

        # Segmented tape-counter progress rail. The items are pooled; only
        # their fills change as the master clock advances.
        progress_row = ctk.CTkFrame(inner, fg_color="transparent", corner_radius=0)
        progress_row.pack(fill=tk.X, pady=(3, 1))
        self.elapsed_lbl = ctk.CTkLabel(
            progress_row, text="0:00", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(8), width=32,
        )
        self.elapsed_lbl.pack(side=tk.LEFT)
        self.progress_bar = PixelProgress(
            progress_row, segments=36, height=12, bg=NIGHT,
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.duration_lbl = ctk.CTkLabel(
            progress_row, text="0:00", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(8), width=32,
        )
        self.duration_lbl.pack(side=tk.LEFT)

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
            ctrl, T.media_icon("prev"), command=self._prev, size=32,
            font_size=17, bg=SURFACE2, fg=TEXT, canvas_bg=NIGHT, icon=True,
        )
        self.prev_btn.pack(side=tk.LEFT, padx=3)

        self.play_btn = CircleBtn(
            ctrl, T.media_icon("play"), command=self._play_pause_toggle,
            size=42, bg=GOLD, fg=BG, font_size=22,
            canvas_bg=NIGHT, accent=True, icon=True,
        )
        self.play_btn.pack(side=tk.LEFT, padx=4)

        self.next_btn = CircleBtn(
            ctrl, T.media_icon("next"), command=self._next, size=32,
            font_size=17, bg=SURFACE2, fg=TEXT, canvas_bg=NIGHT, icon=True,
        )
        self.next_btn.pack(side=tk.LEFT, padx=3)

        self.status_log_lbl = ctk.CTkLabel(
            inner, text="GameBeats ready.", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(14),
            anchor="w", justify=tk.LEFT,
        )
        self.status_log_lbl.pack(fill=tk.X, pady=(3, 0))

        # ── Deck bottom ─────────────────────────────────────────────────────
        bottom = ctk.CTkFrame(self._deck, fg_color=DECK, height=34, corner_radius=0)
        bottom.grid(row=2, column=0, sticky="ew", padx=9, pady=(0, 7))
        bottom.grid_propagate(False)
        self._deck_bottom = bottom

        auto = ctk.CTkFrame(bottom, fg_color="transparent", corner_radius=0)
        auto.pack(side=tk.LEFT)
        ctk.CTkLabel(
            auto, text="AUTO", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        ).pack(side=tk.LEFT, padx=(0, 4))
        self._auto_toggle = PixelToggle(
            auto, variable=self.auto_mode, bg=DECK, width=44, height=20,
            command=self._on_auto_toggle,
        )
        self._auto_toggle.pack(side=tk.LEFT)

        seamless = ctk.CTkFrame(bottom, fg_color="transparent", corner_radius=0)
        seamless.pack(side=tk.LEFT, padx=(14, 0))
        ctk.CTkLabel(
            seamless, text="KEEP MUSIC", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(9),
        ).pack(side=tk.LEFT, padx=(0, 4))
        self._keep_music_toggle = PixelToggle(
            seamless, variable=self.seamless_music_var,
            command=self._save_player_settings, bg=DECK, width=44, height=20,
        )
        self._keep_music_toggle.pack(side=tk.LEFT)

        self.block_pl_btn = T.pixel_button(
            bottom, text="\u2298  BLOCK", command=self._block_current_playlist,
            width=82, height=27,
        )
        self.block_pl_btn.pack(side=tk.RIGHT, padx=(5, 0))
        add_focus_ring(self.block_pl_btn, base_border=None, width=2)

        self.try_another_btn = T.pixel_button(
            bottom, text="\u21ba  TRY ANOTHER", command=self._try_another_playlist,
            width=128, height=27,
        )
        self.try_another_btn.pack(side=tk.RIGHT)
        add_focus_ring(self.try_another_btn, base_border=None, width=2)

        # Pixel tooltips: one reusable window, attached to the controls that
        # benefit from a keyboard hint.
        for widget, text in (
            (self.prev_btn, "Previous track  [\u2190]"),
            (self.play_btn, "Play / pause  [Space]"),
            (self.next_btn, "Next track  [\u2192]"),
            (self.progress_bar, "Track progress"),
            (self.deck_led, "Spotify output \u00b7 open Control Panel"),
            (self.deck_status_lbl, "Playback state"),
            (self.block_pl_btn, "Block this playlist"),
            (self.try_another_btn, "Pick another playlist"),
        ):
            self._tooltips.attach(widget, text)

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
        key = (name, int(size[0]), int(size[1]))
        cached = self._puppy_photo_cache.get(key)
        if cached is not None:
            return cached
        sprite = None
        if isinstance(name, str) and name.startswith("action:"):
            try:
                _prefix, state, raw_index = name.split(":", 2)
                index = int(raw_index)
            except Exception:
                return None
            state_frames = getattr(self, "_puppy_gif_states", {}).get(state)
            if not state_frames:
                return None
            frames = state_frames[0]
            if not frames:
                return None
            sprite = frames[index % len(frames)]
        elif isinstance(name, str) and name.startswith("gif:"):
            try:
                index = int(name.split(":", 1)[1])
            except Exception:
                return None
            frames = getattr(self, "_puppy_gif_frames", ())
            if not frames:
                return None
            sprite = frames[index % len(frames)]
        else:
            sprite = getattr(self, "_puppy_sprites", {}).get(name)
        if sprite is None:
            return None
        try:
            resampling = getattr(Image, "Resampling", Image)
            scaled = sprite.resize((int(size[0]), int(size[1])), resampling.NEAREST)
            self._puppy_photo_cache[key] = scaled
            return scaled
        except Exception:
            return None

    @staticmethod
    def _puppy_scale_for_width(width):
        """Integer sprite scale, kept close to the old 15% canvas width."""
        try:
            scale = int(round(float(width) * 0.15 / 64.0))
        except Exception:
            scale = 3
        return max(3, scale)

    def _draw_room_puppy(self, canvas, sprite_name, geometry):
        px, py, pw, ph = geometry
        key = (sprite_name, int(pw), int(ph))
        photo = self._room_puppy_photo
        if photo is None or self._room_puppy_sprite_key != key:
            sprite = self._puppy_image_for(sprite_name, (pw, ph))
            if sprite is None:
                return
            try:
                photo = ImageTk.PhotoImage(sprite)
            except Exception:
                return
            self._room_puppy_photo = photo
        try:
            if self._room_puppy_item is None or not canvas.type(self._room_puppy_item):
                self._room_puppy_item = canvas.create_image(
                    px, py, anchor="nw", image=photo, tags=("puppy",)
                )
            else:
                canvas.itemconfigure(self._room_puppy_item, image=photo)
                canvas.coords(self._room_puppy_item, px, py)
            self._room_puppy_sprite_key = key
            # This method only runs during a full room rebuild, before the UI
            # overlays are recreated, so raising the puppy here is safe.  The
            # animation tick must never do it (see _animate_room_puppy).
            canvas.tag_raise("puppy")
        except Exception:
            pass

    def _reduce_motion_enabled(self):
        try:
            return bool(self.configure.get("reduce_motion", False))
        except Exception:
            return False

    def _puppy_audio_level(self):
        """Smoothed, clamped Spotify level for the mouth animation.

        The meter only produces a sample twice per second and individual
        samples dip between beats.  A little attack/release smoothing keeps
        those gaps from snapping the mouth shut; the animator's hysteresis and
        minimum hold then prevent threshold chatter.
        """
        try:
            peak = float(getattr(self, "_last_spotify_peak", 0.0) or 0.0)
        except Exception:
            peak = 0.0
        target = max(0.0, min(1.0, peak / 0.18))
        previous = float(getattr(self, "_puppy_audio_smooth", 0.0) or 0.0)
        rate = 0.45 if target > previous else 0.22
        level = previous + (target - previous) * rate
        if level < 0.005:
            level = 0.0
        self._puppy_audio_smooth = level
        return level

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

    def _puppy_should_animate(self) -> bool:
        """True only while GameBeats itself is actively playing, not paused."""
        if self._reduce_motion_enabled():
            return False
        try:
            # _spotify_started_by_us separates GameBeats playback from audio
            # that happens to be coming from Spotify in another window.
            if not getattr(self, "_spotify_started_by_us", False):
                return False
            if not getattr(self, "_is_playing", False):
                return False
            if self._intentional_pause_active():
                return False
        except Exception:
            return False
        return True

    def _puppy_animation_locked(self) -> bool:
        """A real pause locks both the room and desktop puppy animations.

        This is deliberately based on intentional pause (user/game), not the
        brief silence while a new playlist loads.  The playlist-switch pause
        is a transient loading state and may show the thinking loop; a real
        user/game pause still holds the drooped pose.
        """
        try:
            return bool(self._intentional_pause_active())
        except Exception:
            return True

    def _hold_room_pause_pose(self):
        """Freeze the room puppy on the drooped frame without restarting it."""
        state = getattr(self, "_puppy_action_state", None)
        if (
            state == "pause"
            and getattr(self, "_puppy_action_hold", False)
            and not getattr(self, "_puppy_action_reverse", False)
        ):
            return
        self._start_puppy_action("pause", loops=1, hold=True)

    def _start_puppy_action(
        self, state, *, loops=1, reverse=False, hold=False, now=None,
    ):
        """Play a one-shot reaction on the in-room puppy.

        Action frames use the same normalized canvas as the idle bob.  A
        pause reaction holds its final drooped pose while paused; a resume
        reaction runs the same clip backwards and then returns to the bob.
        """
        if self._reduce_motion_enabled():
            return
        state_frames = getattr(self, "_puppy_gif_states", {}).get(state)
        if not state_frames or not state_frames[0]:
            return
        self._puppy_action_state = state
        self._puppy_action_started = time.time() if now is None else float(now)
        # loops=0 is reserved for the indefinite thinking loop.
        self._puppy_action_loops = max(0, int(loops or 0))
        self._puppy_action_reverse = bool(reverse)
        self._puppy_action_hold = bool(hold)

    def _puppy_action_active(self, state=None, now=None):
        action = getattr(self, "_puppy_action_state", None)
        if not action or (state is not None and action != state):
            return False
        state_frames = getattr(self, "_puppy_gif_states", {}).get(action)
        if not state_frames or not state_frames[0]:
            return False
        loops = int(getattr(self, "_puppy_action_loops", 1) or 0)
        if loops <= 0:
            # Infinite actions (the thinking loop) stay active until the
            # caller explicitly replaces or stops them.
            return True
        durations = tuple(state_frames[1] or ())
        total = sum(durations) if durations else len(state_frames[0]) * 120
        current = time.time() if now is None else float(now)
        started = float(getattr(self, "_puppy_action_started", current))
        return (current - started) * 1000.0 < total * loops

    def _puppy_thinking_active(self) -> bool:
        return bool(
            getattr(self, "_puppy_action_state", None) == "thinking"
            and self._puppy_action_active("thinking")
        )

    def _cancel_puppy_thinking_timeout(self):
        job = getattr(self, "_puppy_thinking_timeout_job", None)
        self._puppy_thinking_timeout_job = None
        root = getattr(self, "root", None)
        if job is not None and root is not None:
            try:
                root.after_cancel(job)
            except Exception:
                pass

    def _schedule_puppy_thinking_timeout(self, reason=""):
        self._cancel_puppy_thinking_timeout()
        root = getattr(self, "root", None)
        if root is None:
            return
        try:
            self._puppy_thinking_timeout_job = root.after(
                45000, lambda r=reason: self._puppy_thinking_timeout(r)
            )
        except Exception:
            self._puppy_thinking_timeout_job = None

    def _cancel_skip_completion_watchdog(self):
        job = getattr(self, "_skip_completion_job", None)
        self._skip_completion_job = None
        root = getattr(self, "root", None)
        if job is not None and root is not None:
            try:
                root.after_cancel(job)
            except Exception:
                pass

    def _schedule_skip_completion_watchdog(self, request_id):
        """Finish an explicit skip if Spotify metadata never arrives.

        The normal path completes from fresh metadata (usually within two
        seconds).  A hung local-status request used to leave the thinking loop
        up for many seconds while the replacement track was already audible.
        """
        self._cancel_skip_completion_watchdog()
        root = getattr(self, "root", None)
        if root is None:
            return
        try:
            self._skip_completion_job = root.after(
                SKIP_COMPLETION_WATCHDOG_MS,
                lambda rid=request_id: self._finish_stalled_skip(rid),
            )
        except Exception:
            self._skip_completion_job = None

    def _finish_stalled_skip(self, request_id):
        self._skip_completion_job = None
        if request_id != int(getattr(self, "_skip_request_seq", 0) or 0):
            return
        if not self._puppy_thinking_active():
            return
        if getattr(self, "_puppy_thinking_reason", "") != "track":
            return
        if self._intentional_pause_active():
            return
        # A failed skip can leave silence.  Only celebrate when the player is
        # actually producing audio; otherwise leave the normal timeout alone.
        try:
            recently_loud = self._spotify_sound_detected_recently(2.0)
        except Exception:
            recently_loud = False
        if not (
            getattr(self, "_spotify_audio_active", False)
            or getattr(self, "_is_playing", False)
            or recently_loud
        ):
            return
        self._finish_puppy_thinking(play_change=True)

    def _puppy_thinking_timeout(self, reason=""):
        if not self._puppy_thinking_active():
            return
        if str(reason or "") != str(getattr(self, "_puppy_thinking_reason", "")):
            return
        self._stop_puppy_thinking(hold_pause=self._puppy_animation_locked())

    def _stop_puppy_thinking(self, *, hold_pause=False, update_overlay=True):
        """End the thinking loop without starting a headset-swap clip."""
        self._cancel_skip_completion_watchdog()
        if not self._puppy_thinking_active():
            return False
        self._cancel_puppy_thinking_timeout()
        self._puppy_action_state = None
        self._puppy_action_loops = 1
        self._puppy_action_reverse = False
        self._puppy_action_hold = False
        self._puppy_thinking_reason = ""
        if hold_pause:
            self._hold_room_pause_pose()
        overlay = getattr(self, "_puppy_singing_overlay", None)
        if update_overlay and overlay is not None:
            try:
                if hold_pause:
                    overlay.set_animation_locked(True, animate=False)
                else:
                    overlay.set_playback_state(
                        not self._intentional_pause_active(), animate=False
                    )
            except Exception:
                pass
        return True

    def _start_puppy_thinking_animation(self, *, reason="track", now=None):
        """Show the thinking loop while a track/playlist is loading.

        The loop is indefinite, so it must be finished by
        ``_finish_puppy_thinking`` or stopped by ``_stop_puppy_thinking``.
        A real user/game pause still wins; only the transient playlist-switch
        pause is allowed to show thinking.
        """
        if self._reduce_motion_enabled():
            return False
        state_frames = getattr(self, "_puppy_gif_states", {}).get("thinking")
        if not state_frames or not state_frames[0]:
            # Old asset bundles fall back to the previous one-shot clip.
            return self._play_puppy_change_animation(force=True)
        switch_pause = bool(getattr(self, "_playlist_switch_pause", False))
        if str(reason or "track") != "track":
            self._cancel_skip_completion_watchdog()
        if getattr(self, "_paused_by_game_flag", False):
            return False
        if self._puppy_animation_locked() and not switch_pause:
            self._hold_room_pause_pose()
            overlay = getattr(self, "_puppy_singing_overlay", None)
            if overlay is not None:
                try:
                    overlay.set_animation_locked(True, animate=False)
                except Exception:
                    pass
            return False
        if self._puppy_thinking_active():
            # A track skip can be promoted to a playlist switch while the loop
            # is already running; keep the same clip and extend its safety
            # timeout instead of restarting the intro.
            self._puppy_thinking_reason = str(reason or "track")
            self._schedule_puppy_thinking_timeout(self._puppy_thinking_reason)
            return True
        self._start_puppy_action("thinking", loops=0, now=now)
        self._puppy_thinking_reason = str(reason or "track")
        self._schedule_puppy_thinking_timeout(self._puppy_thinking_reason)
        overlay = getattr(self, "_puppy_singing_overlay", None)
        if overlay is not None:
            try:
                # The switch began, so thinking may temporarily replace the
                # drooped switch-pause pose.  A real pause will re-lock it.
                overlay.set_animation_locked(False)
                overlay.play_thinking_animation()
            except Exception:
                pass
        return True

    def _finish_puppy_thinking(self, *, play_change=True):
        """Stop thinking and play one headset-swap clip when appropriate."""
        self._cancel_skip_completion_watchdog()
        if not self._puppy_thinking_active():
            return False
        self._cancel_puppy_thinking_timeout()
        self._puppy_thinking_reason = ""
        if play_change and self._play_puppy_change_animation(force=True):
            return True
        self._stop_puppy_thinking(hold_pause=self._puppy_animation_locked())
        return True

    def _react_to_playback_change(self, playing):
        # Starting the next playlist pauses the old one first.  Do not let
        # that pause reaction stomp the playlist-change animation the user
        # just triggered.
        if self._puppy_action_active("change"):
            return
        action = getattr(self, "_puppy_action_state", None)
        if action == "thinking":
            # The transient playlist-switch pause is part of loading, not a
            # user pause.  Keep the thinking loop through it.
            if getattr(self, "_playlist_switch_pause", False):
                return
            if playing:
                # The new audio is starting; the completion path decides when
                # to replace thinking with the headset-swap clip.
                return
            self._stop_puppy_thinking(hold_pause=True)
            action = getattr(self, "_puppy_action_state", None)
        if playing:
            # Only reverse the pause clip when the puppy was actually paused.
            # A first track at launch should start with the normal bob.
            if action != "pause":
                return
            # An audio-meter tick and the resume command can both fire.  Do
            # not restart a reverse clip that is already running.
            if (
                getattr(self, "_puppy_action_reverse", False)
                and self._puppy_action_active("pause")
            ):
                return
            self._start_puppy_action("pause", loops=1, reverse=True)
        else:
            # Likewise, repeated pause notifications must not restart the
            # forward droop (or reset an already-held pause pose).
            if (
                action == "pause"
                and not getattr(self, "_puppy_action_reverse", False)
                and (
                    getattr(self, "_puppy_action_hold", False)
                    or self._puppy_action_active("pause")
                )
            ):
                return
            self._start_puppy_action("pause", loops=1, hold=True)

    def _play_puppy_change_animation(self, *, force=False):
        """Animate a song/playlist switch in the room and desktop overlay."""
        now = time.time()
        if self._reduce_motion_enabled():
            return False
        overlay = getattr(self, "_puppy_singing_overlay", None)
        if self._puppy_animation_locked():
            # Paused music owns the pose.  A long-press may still ask for
            # another playlist, but it must not start a headset-swap clip or
            # leave the room puppy bobbing.  An already-running change clip is
            # allowed to finish (same rule as the desktop overlay).
            if not self._puppy_action_active("change"):
                self._hold_room_pause_pose()
            if overlay is not None:
                try:
                    overlay.set_animation_locked(True, animate=False)
                except Exception:
                    pass
            return False
        if not force and now < getattr(self, "_puppy_change_cooldown_until", 0.0):
            return False
        if self._puppy_action_active("change"):
            # A long-press starts the overlay clip immediately and then calls
            # this method.  Restarting the room clip there made the puppy
            # visibly stutter.  One active change clip is enough.
            self._track_change_anim_quiet_until = max(
                float(getattr(self, "_track_change_anim_quiet_until", 0.0) or 0.0),
                now + 2.0,
            )
            return False
        self._cancel_puppy_thinking_timeout()
        self._puppy_thinking_reason = ""
        self._puppy_change_cooldown_until = now + 2.0
        self._track_change_anim_quiet_until = max(
            float(getattr(self, "_track_change_anim_quiet_until", 0.0) or 0.0),
            now + 7.0,
        )
        self._start_puppy_action("change", loops=1)
        if overlay is not None:
            try:
                overlay.set_animation_locked(False)
                overlay.play_change_animation()
            except Exception:
                pass
        return True

    def _puppy_frame_name(self, now=None):
        now = time.time() if now is None else now
        action = getattr(self, "_puppy_action_state", None)
        # Self-heal a stale drooped pose.  If playback is running and nothing
        # is intentionally paused any more, a held pause frame must not stay
        # on screen (it can happen when the pause flags and _is_playing are
        # updated from different callbacks in quick succession).
        if (
            action == "pause"
            and getattr(self, "_puppy_action_hold", False)
            and not getattr(self, "_puppy_action_reverse", False)
            and getattr(self, "_is_playing", False)
        ):
            try:
                still_paused = self._intentional_pause_active()
            except Exception:
                still_paused = False
            if not still_paused:
                self._puppy_action_state = None
                self._puppy_action_hold = False
                action = None
        state_frames = (
            getattr(self, "_puppy_gif_states", {}).get(action) if action else None
        )
        if state_frames and state_frames[0]:
            frames, durations = state_frames
            durations = tuple(durations or ())
            if not durations:
                durations = (120,) * len(frames)
            total = sum(durations)
            elapsed = max(0.0, (now - float(
                getattr(self, "_puppy_action_started", now)
            )) * 1000.0)
            if action == "thinking":
                # A real pause always wins over a stale thinking loop.  The
                # playlist-switch pause is allowed to keep thinking visible.
                if (
                    self._intentional_pause_active()
                    and not getattr(self, "_playlist_switch_pause", False)
                ):
                    self._stop_puppy_thinking(hold_pause=True)
                    action = getattr(self, "_puppy_action_state", None)
                    state_frames = (
                        getattr(self, "_puppy_gif_states", {}).get(action)
                        if action else None
                    )
                    if not state_frames or not state_frames[0]:
                        gif_frames = getattr(self, "_puppy_gif_frames", ())
                        return "gif:0" if gif_frames else "idle"
                    frames, durations = state_frames
                    durations = tuple(durations or ()) or (120,) * len(frames)
                    total = sum(durations)
                else:
                    return f"action:thinking:{_thinking_frame_index(elapsed, durations)}"
            loops = max(1, int(getattr(self, "_puppy_action_loops", 1) or 1))
            hold = bool(getattr(self, "_puppy_action_hold", False))
            reverse = bool(getattr(self, "_puppy_action_reverse", False))
            if total <= 0:
                return f"action:{action}:0"
            if elapsed >= total * loops:
                if not hold:
                    self._puppy_action_state = None
                    # If a change clip ends while the music is still paused,
                    # settle into the drooped pause pose instead of snapping
                    # back to the neutral bob frame.
                    try:
                        still_paused = self._intentional_pause_active()
                    except Exception:
                        still_paused = False
                    pause_state = getattr(
                        self, "_puppy_gif_states", {}
                    ).get("pause")
                    if still_paused and pause_state and pause_state[0]:
                        pause_frames, pause_durations = pause_state
                        pause_durations = tuple(pause_durations or ())
                        pause_total = (
                            sum(pause_durations)
                            or len(pause_frames) * 120
                        )
                        self._puppy_action_state = "pause"
                        self._puppy_action_started = (
                            now - pause_total / 1000.0 - 0.001
                        )
                        self._puppy_action_loops = 1
                        self._puppy_action_reverse = False
                        self._puppy_action_hold = True
                        return f"action:pause:{len(pause_frames) - 1}"
                else:
                    index = 0 if reverse else len(frames) - 1
                    return f"action:{action}:{index}"
            else:
                offset = elapsed % total
                index = _gif_frame_index_at(offset, durations)
                if reverse:
                    index = len(frames) - 1 - index
                return f"action:{action}:{index}"
        gif_frames = getattr(self, "_puppy_gif_frames", ())
        if gif_frames:
            # Hold the first pose whenever playback is stopped or paused; the
            # bobbing loop only runs while GameBeats is actually playing music.
            if not self._puppy_should_animate():
                return "gif:0"
            durations = getattr(self, "_puppy_gif_durations", ())
            return f"gif:{_gif_frame_index_at(now * 1000.0, durations)}"
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
            # Do NOT raise the puppy here.  The tick loop runs 30 times a
            # second, and raising on every tick pulled the mascot above the
            # room labels, status caption, and hover outlines.  The stable
            # order is established once in _redraw_room (puppy above ambient,
            # UI overlays above puppy) and then left alone.
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
            name: self._room_rect(layout, *ROOM_HOTSPOTS[name])
            for name in ROOM_HOTSPOT_PAGES
        }

        outlines = {}
        outline_width = max(1, int(round(layout[0] * 0.32)))
        for name in ROOM_HOTSPOT_PAGES:
            rect = self._room_rect(layout, *ROOM_HOTSPOTS[name])
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
        for i in range(9):
            pane = ROOM_WINDOW_PANES[i % len(ROOM_WINDOW_PANES)]
            pane_w = max(1, pane[2] - pane[0] - 1)
            pane_h = max(1, pane[3] - pane[1] - 3)
            bx = pane[0] + (i * 7) % pane_w
            by = pane[1] + (i * 11) % pane_h
            item = canvas.create_rectangle(
                0, 0, 1, 1, fill=(GOLD, ROSE, CREAM)[i % 3],
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

            # The CRT is pure ambience.  It no longer reacts to hovering; the
            # scanline drift and occasional glitch stay on a slow, constant
            # loop so the room feels alive without a hotspot outline.
            for scan in ambient["crt_scan"]:
                y = 94.0 + ((tick * 2.2 + scan["offset"]) % 38.0)
                rect = self._room_rect(layout, 40.5, y, 99.5, y + 0.55)
                canvas.coords(scan["id"], *rect)
                canvas.itemconfigure(scan["id"], fill=ACCENT_DIM)

            show_glitch = tick % 37 in (0, 1, 2)
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
        # Only the three navigable objects get a hover treatment.  The CRT is
        # decorative and must not draw an outline or change the cursor.
        if zone not in ROOM_HOTSPOT_PAGES:
            zone = None
        if zone == self._room_hover:
            return
        self._room_hover = zone
        self._apply_room_hover()
        canvas = getattr(self, "_room_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(cursor="hand2" if zone else "")
            except Exception:
                pass
        try:
            self._update_hover_overlays(
                self._anim_tick, static=self._reduce_motion_enabled()
            )
        except Exception:
            pass

    def _room_zone_at(self, x, y):
        """Return the navigable room zone under a canvas point.

        Label boxes extend beyond some hotspots (the crate label sits below
        the record crate), so both the label rectangle and the larger object
        region count as a click target.
        """
        for _tag, (x0, y0, x1, y1, zone) in getattr(
            self, "_room_label_hits", {}
        ).items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return zone
        for name, bbox in getattr(self, "_room_hotspots", {}).items():
            if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return name if name in ROOM_HOTSPOT_PAGES else None
        return None

    def _on_room_canvas_motion(self, event):
        self._set_room_hover(self._room_zone_at(event.x, event.y))

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

    def _retry_room_art(self, _event=None):
        self._room_pil = _load_design_room("den_room.png")
        self._room_dim_pil = _load_design_room("den_room_dim.png")
        self._room_base_cache = None
        self._room_base_key = None
        if self._room_pil is None:
            try:
                self._toast.show(
                    "ROOM ART",
                    "Still missing. Check assets/room/den_room.png.",
                    4200,
                )
            except Exception:
                pass
        self._schedule_room_redraw(0)

    def _draw_room_error(self, canvas, w, h):
        """Explicit, recoverable empty state instead of a blank room."""
        try:
            canvas.delete("all")
            canvas.configure(bg=BG)
            panel_w = min(max(340, int(w * 0.46)), 620)
            panel_h = 188
            x0 = (w - panel_w) // 2
            y0 = max(20, (h - panel_h) // 2)
            x1, y1 = x0 + panel_w, y0 + panel_h
            canvas.create_rectangle(
                x0, y0, x1, y1, fill=NIGHT, outline=WOOD, width=2,
                tags=("room_error",),
            )
            canvas.create_rectangle(
                x0 + 8, y0 + 8, x1 - 8, y0 + 10, fill="#7A4350",
                outline="", tags=("room_error",),
            )
            canvas.create_text(
                w // 2, y0 + 46, text="ROOM SIGNAL LOST",
                font=T.pixel_font(15, "bold"), fill=GOLD,
                tags=("room_error",),
            )
            canvas.create_text(
                w // 2, y0 + 82,
                text="The den artwork could not be loaded.",
                font=T.retro_font(16), fill=TEXT,
                tags=("room_error",),
            )
            canvas.create_text(
                w // 2, y0 + 106,
                text="The player deck still works. Retry the room plate?",
                font=T.retro_font(14), fill=TEXT_MUTED,
                tags=("room_error",),
            )
            rx0, ry0 = w // 2 - 62, y0 + 132
            rx1, ry1 = w // 2 + 62, y0 + 164
            canvas.create_rectangle(
                rx0, ry0, rx1, ry1, fill=ACCENT, outline=GOLD, width=1,
                tags=("room_retry",),
            )
            canvas.create_text(
                w // 2, (ry0 + ry1) // 2, text="RETRY",
                font=T.pixel_font(10, "bold"), fill=BG,
                tags=("room_retry",),
            )
            canvas.tag_bind(
                "room_retry", "<Button-1>",
                lambda _e: self._retry_room_art(),
            )
            canvas.tag_bind(
                "room_retry", "<Enter>",
                lambda _e: canvas.configure(cursor="hand2"),
            )
            canvas.tag_bind(
                "room_retry", "<Leave>",
                lambda _e: canvas.configure(cursor=""),
            )
        except Exception:
            pass

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
            self._draw_room_error(canvas, w, h)
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
            self._draw_room_error(canvas, w, h)
            return

        now = time.time()
        sprite_name = self._puppy_frame_name(now)

        # The mascot is the big in-room puppy, centred over the player deck.
        # One integer scale keeps every authored pixel a clean NxN square.  The
        # shared animation canvas is wider/taller than the old 64x72 body box
        # so reactions (headphones off, pause droop) fit without shrinking the
        # puppy; the feet baseline remains fixed.
        puppy_scale = self._puppy_scale_for_width(w)
        body_w, body_h = getattr(self, "_puppy_gif_canvas", (64, 72))
        body_w = max(1, int(body_w))
        body_h = max(1, int(body_h))
        pw = body_w * puppy_scale
        ph = body_h * puppy_scale
        px = (w - pw) // 2
        paw_margin = 2 * puppy_scale
        perch_y = h - ph + paw_margin - 1
        py = max(0, perch_y)
        px = max(0, min(px, w - pw - 4))
        self._puppy_bbox = (px, py, px + pw, py + ph)
        self._room_puppy_base = (px, py, pw, ph)
        # The shared reaction canvas has transparent headroom.  Remember where
        # the puppy's actual pixels begin so the pet heart sits above the head
        # rather than floating in the empty padding.
        self._puppy_visual_top = py
        try:
            idle_frames = getattr(self, "_puppy_gif_frames", ())
            if idle_frames:
                idle_frame = idle_frames[0]
                alpha_box = idle_frame.getchannel("A").getbbox()
                if alpha_box:
                    source_h = max(1, idle_frame.size[1])
                    self._puppy_visual_top = py + int(
                        alpha_box[1] * (ph / source_h)
                    )
        except Exception:
            pass

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
            # Shadow follows the puppy body, not the transparent reaction
            # canvas (which may include headphones held off to the side).
            shadow_w = int(64 * puppy_scale * 0.62)
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
        self._room_label_hits = {}
        label_x = int(w * 0.79)
        self._draw_room_label(canvas, label_x, int(h * 0.335),
                              "THE GAME SHELF", "lbl_shelf",
                              lambda: self._nav("games"))
        self._draw_room_label(canvas, label_x, int(h * 0.60),
                              "TWEAK A LITTLE", "lbl_board",
                              lambda: self._nav("settings"))
        self._draw_room_label(canvas, int(w * 0.78), int(h * 0.845),
                              "DIG FOR A VIBE", "lbl_crate",
                              lambda: self._nav("playlists"))

        # Pet heart (tap feedback only; the mascot itself never floats).
        # A redraw only recreates the heart while its short timer is active;
        # petting itself uses the lightweight methods below instead of
        # rebuilding the whole room twice.
        if time.time() < getattr(self, "_heart_until", 0.0):
            self._show_pet_heart()

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
            fs = max(10, int(canvas.winfo_width() * 0.0085))
            pad = max(10, int(fs * 1.25))
            box_h = max(30, int(fs * 2.9))
            txt = canvas.create_text(
                x + pad, y + box_h // 2, text=text, anchor="w",
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
                x + box_w - pad, y + box_h // 2, text="\u2197",
                anchor="e", font=(F_RETRO, -max(13, int(fs * 1.45))),
                fill=CREAM, tags=("overlay", f"{tag}_arrow"),
            )
            zone = {"lbl_shelf": "shelf", "lbl_board": "panel",
                    "lbl_crate": "crate"}.get(tag)
            self._room_label_hits[tag] = (
                x, y, x + box_w, y + box_h, zone,
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
        zone = self._room_zone_at(event.x, event.y)
        page = ROOM_HOTSPOT_PAGES.get(zone)
        if page:
            self._nav(page)
            # The same click can also hit a canvas text/box tag binding. Stop
            # here so a single click never navigates twice.
            return "break"

    def _pet_puppy(self):
        now = time.time()
        self._heart_until = now + 1.2
        self._puppy_mood_until = now + 1.2
        if hasattr(self, "status_log_lbl"):
            self.status_log_lbl.configure(text="Puppy says hi.", text_color=GOLD)
        self._show_pet_heart()
        # The heart is its own small canvas item.  Petting used to trigger two
        # full room redraws (and another one 1.25s later), which flashed the
        # ambient layer and labels around the mascot.
        job = getattr(self, "_pet_heart_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        try:
            self._pet_heart_job = self.root.after(1200, self._hide_pet_heart)
        except Exception:
            self._pet_heart_job = None

    def _show_pet_heart(self):
        canvas = getattr(self, "_room_canvas", None)
        if canvas is None:
            return
        try:
            x0, y0, x1, _y1 = getattr(self, "_puppy_bbox", (0, 0, 0, 0))
            if x1 <= x0:
                return
            visual_top = getattr(self, "_puppy_visual_top", y0)
            width = max(1, canvas.winfo_width())
            canvas.delete("pet_heart")
            canvas.create_text(
                (x0 + x1) // 2, visual_top - 26, text="\u2665",
                anchor="s", font=(F_RETRO, -max(20, int(width * 0.015))),
                fill=ORANGE, tags=("overlay", "pet_heart"),
            )
        except Exception:
            pass

    def _hide_pet_heart(self):
        self._pet_heart_job = None
        canvas = getattr(self, "_room_canvas", None)
        if canvas is None:
            return
        try:
            canvas.delete("pet_heart")
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
            self._update_deck_progress(now)
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
            PixelToggle(
                startup_row, variable=self.startup_var, bg=SURFACE,
                command=self._toggle_startup, width=44, height=20,
            ).pack(side=tk.RIGHT, padx=2)

        # ── Puppy Overlay ─────────────────────────────────────────────────────
        T.rule(ap, color=BORDER, pady=(10, 8))
        motion_row = ctk.CTkFrame(ap, fg_color="transparent", corner_radius=0)
        motion_row.pack(fill=tk.X)
        motion_copy = ctk.CTkFrame(motion_row, fg_color="transparent", corner_radius=0)
        motion_copy.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ctk.CTkLabel(
            motion_copy, text="Reduce motion", fg_color="transparent",
            text_color=TEXT, font=T.retro_font(17), anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            motion_copy,
            text="Freeze dust, rain, glow pulses, and the room's idle movement. "
                 "The player and progress rail keep working.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(15), anchor="w", justify=tk.LEFT, wraplength=620,
        ).pack(fill=tk.X, pady=(2, 0))
        self._motion_toggle = PixelToggle(
            motion_row, variable=self.reduce_motion_var, bg=SURFACE,
            command=self._save_motion_setting, width=44, height=20,
        )
        self._motion_toggle.pack(side=tk.RIGHT, padx=(14, 2))

        T.section_header(
            content, "02 / DESKTOP PUPPY + CONTROL PANEL", pady=(14, 6)
        )
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
            text_color=TEXT, font=T.retro_font(20), anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            ov_copy,
            text=PUPPY_OVERLAY_HELP,
            fg_color="transparent", text_color=TEXT_SEC,
            font=T.retro_font(17), anchor="w", justify=tk.LEFT, wraplength=680,
        ).pack(fill=tk.X, pady=(4, 10))

        T.primary_button(
            ov_copy, "\u25a3  OPEN CONTROL PANEL", command=self._show_control_overlay,
            width=204, height=34,
        ).pack(anchor="w")

        gestures = ctk.CTkFrame(
            ov, fg_color=NIGHT, corner_radius=0,
            border_width=2, border_color=WOOD,
        )
        gestures.pack(fill=tk.X, pady=(14, 0))
        ctk.CTkLabel(
            gestures, text="PUPPY CONTROLS", fg_color="transparent",
            text_color=GOLD, font=T.pixel_font(11, "bold"), anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(10, 5))
        for key, description in PUPPY_OVERLAY_GESTURES:
            row = ctk.CTkFrame(gestures, fg_color="transparent", corner_radius=0)
            row.pack(fill=tk.X, padx=12, pady=3)
            ctk.CTkLabel(
                row, text=key, fg_color=GOLD, text_color=NIGHT,
                corner_radius=0, width=112, height=26,
                font=T.pixel_font(10, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 12))
            ctk.CTkLabel(
                row, text=description, fg_color="transparent",
                text_color=TEXT, font=T.retro_font(17), anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ctk.CTkLabel(
            gestures,
            text="Need manual skip, block, and playlist controls? The larger "
                 "control panel opens with the button above.",
            fg_color="transparent", text_color=TEXT_SEC,
            font=T.retro_font(16), anchor="w", justify=tk.LEFT, wraplength=720,
        ).pack(fill=tk.X, padx=12, pady=(6, 10))

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

        PixelToggle(
            km_row, variable=self.seamless_music_var,
            command=self._save_player_settings, bg=SURFACE,
            width=44, height=20,
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
        self._ensure_spotify_window_guard()
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
            helper = self._spotify_desktop_controller()
            if helper is None and hasattr(self, 'spotify') and self.spotify:
                if hasattr(self.spotify, 'launch_spotify'):
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
        play_started = False
        self._play_request_seq = int(getattr(self, "_play_request_seq", 0)) + 1
        request_id = self._play_request_seq
        self._active_play_request_id = request_id
        # Attribute the upcoming audio to GameBeats before the controller
        # returns.  The controller can take 20+ seconds to confirm playback;
        # gating the overlay on that result made it appear long after music.
        self._spotify_started_by_us = True
        self._playback_started_ts = time.time()
        try:
            if self._is_web_mode() and self.spotify:
                if not self.spotify.ensure_active_device():
                    err = getattr(self.spotify, "_last_error", "") or "browser failed"
                    self.root.after(0, lambda e=err: self._log(
                        f"⚠ Web player failed to start: {e}"))
                    return
            elif self.spotify:
                self.spotify.ensure_active_device()

            ok = False
            try:
                ok = bool(self.spotify.play_playlist(playlist_uri))
            except Exception:
                ok = False
            play_started = ok

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
            if not play_started and request_id == getattr(self, "_active_play_request_id", 0):
                # Do not leave an early "ours" claim behind when the assigned
                # playlist genuinely failed to start.
                try:
                    if (
                        not getattr(self, "_is_playing", False)
                        and not self._spotify_sound_detected_recently(2.0)
                    ):
                        self._spotify_started_by_us = False
                except Exception:
                    pass
            # Clear the busy flag and run any queued request on the Tk thread,
            # after the success callback above has updated the deck.
            try:
                self.root.after(0, lambda rid=request_id: self._finish_play_query(rid))
            except Exception:
                self._play_in_progress = False

    def _on_game_lost(self):
        self._stop_audio_monitor()
        self.current_game = None
        self._game_pid = None
        self._play_in_progress = False
        self._pending_play_request = None
        self._play_request_seq = int(getattr(self, "_play_request_seq", 0)) + 1
        self._active_play_request_id = 0
        self._playlist_end_pending = False
        self._music_missing_since = 0.0
        if self.spotify and self._spotify_started_by_us:
            threading.Thread(target=self.spotify.media_stop, daemon=True).start()
        if self.spotify and hasattr(self.spotify, "reset_session"):
            self.spotify.reset_session()
        self._spotify_started_by_us = False
        self._playlist_switch_pause = False
        self._playlist_switch_heard_silence = False
        self._playlist_switch_started_ts = 0.0
        self._playlist_switch_audio_heard_ts = 0.0
        self._playlist_switch_pause_confirmed = False
        self.root.after(0, lambda: (
            self.game_banner.configure(text="NO SAVED GAME RUNNING", text_color=TEXT_MUTED),
            self.mood_lbl.configure(text="Waiting for a game"),
            self.playlist_display_lbl.configure(text="Nothing loaded yet"),
            self.track_lbl.configure(text="Nothing playing"),
            self.deck_artist_lbl.configure(text="Connect Spotify in Control Panel"),
            self._set_status("Watching games", ACCENT),
            self._clear_game_icon(),
            self._log("Game closed \u2014 music paused."),
            self._update_deck_status(),
            self._redraw_room(),
        ))

    def _begin_playlist_switch_pause(self, reason=""):
        """Freeze playback/UI immediately when the user asks for another mix.

        Searching Spotify for the next playlist can take several seconds. The
        old mix must not keep playing during that search. This runs on the Tk
        thread so the play button, room puppy, and pause flags update at once.
        """
        self._is_playing = False
        # Mark this as a transient switch pause *before* the pause reaction so
        # a thinking loop that is already running is not replaced by the
        # drooped pose.
        self._playlist_switch_pause = True
        try:
            self._react_to_playback_change(False)
        except Exception:
            pass
        try:
            self._apply_user_pause_state(True, preserve_thinking=True)
        except Exception:
            pass
        self._playlist_switch_pause = True
        self._playlist_switch_started_ts = time.time()
        self._playlist_switch_heard_silence = False
        self._playlist_switch_audio_heard_ts = 0.0
        self._playlist_switch_pause_confirmed = False
        try:
            self._start_puppy_thinking_animation(reason="playlist")
        except Exception:
            pass
        # The user already chose a new playlist; suppress incidental title
        # changes from replaying the change clip while it loads.
        self._track_change_anim_quiet_until = max(
            float(getattr(self, "_track_change_anim_quiet_until", 0.0) or 0.0),
            time.time() + 12.0,
        )
        try:
            self._set_play_btn_icon(False, force_btn=True)
            self._update_deck_status()
        except Exception:
            pass
        try:
            label = str(reason or "Playlist switch").strip()
            self._log(f"{label}: pausing current playlist while the next one loads…")
        except Exception:
            pass

    def _adopt_playlist_switch_playback(self):
        """Resume the UI/puppy as soon as the new playlist is audible.

        The playlist-search worker can take many seconds to report its final
        result while Spotify has already started the new mix.  Waiting for
        that result left the play icon and puppy frozen in the switch pause.
        This runs on the Tk thread from the audio monitor after a sustained
        loud streak, so it only fires when the replacement playlist is real.
        """
        if not getattr(self, "_playlist_switch_pause", False):
            return False
        if getattr(self, "_paused_by_game_flag", False):
            # A real game pause won the race; keep the pause pose.
            return False
        self._playlist_switch_pause = False
        self._playlist_switch_heard_silence = False
        self._playlist_switch_audio_heard_ts = time.time()
        self._playlist_switch_pause_confirmed = False
        self._track_change_anim_quiet_until = max(
            float(getattr(self, "_track_change_anim_quiet_until", 0.0) or 0.0),
            time.time() + 6.0,
        )
        self._manual_paused = False
        self._user_paused_flag = False
        self._paused_by_game_flag = False
        self._spotify_started_by_us = True
        self._playback_started_ts = time.time()
        self._is_playing = True
        self._last_spotify_loud_ts = time.time()
        self._music_missing_since = 0.0
        self._playlist_end_pending = False
        try:
            self._pause_stack.clear()
        except Exception:
            pass
        # This is a fresh playlist, not a resume: drop a held pause pose so
        # the bob can start on the next room frame.
        try:
            if getattr(self, "_puppy_action_state", None) == "pause":
                self._puppy_action_state = None
                self._puppy_action_hold = False
                self._puppy_action_reverse = False
        except Exception:
            pass
        try:
            overlay = getattr(self, "_puppy_singing_overlay", None)
            if overlay is not None:
                overlay.set_animation_locked(False)
                overlay.set_playback_state(True, animate=False)
        except Exception:
            pass
        self._set_play_btn_icon(True, force_btn=True)
        self._set_puppy_singing_visible(True)
        # The replacement playlist is audible now: end the thinking loop and
        # play exactly one headset-swap clip to mark the completed switch.  If
        # another long-press is already queued, keep thinking for that request.
        try:
            if getattr(self, "_pending_play_request", None) is None:
                self._finish_puppy_thinking(play_change=True)
        except Exception:
            pass
        try:
            self._log(
                "New playlist audio confirmed - resuming play icon and puppy."
            )
        except Exception:
            pass
        return True

    def _pause_spotify_for_playlist_switch(self):
        """Send the actual Spotify pause on the worker thread, before searching."""
        if not self.spotify:
            return
        try:
            ok = self._send_spotify_pause_command(was_playing=True)
        except Exception:
            ok = False
        # Only adopt replacement audio after the old mix was actually paused.
        # Otherwise a momentary gap in the old playlist could be mistaken for
        # the new one starting.
        self._playlist_switch_pause_confirmed = bool(ok)
        try:
            msg = (
                "Current playlist paused; finding the next one…"
                if ok
                else "Could not confirm the pause; continuing to the next playlist."
            )
            self.root.after(0, lambda m=msg: self._log(m))
        except Exception:
            pass

    def _finish_play_query(self, request_id=None):
        """Mark the controller operation done, then run a queued request.

        This must stay on the Tk thread: keeping ``_play_in_progress`` true
        until the result's UI callback runs prevents a long-press in between
        from being overwritten by the old result.
        """
        if (
            request_id is not None
            and request_id != getattr(self, "_active_play_request_id", 0)
        ):
            # A newer request owns the UI now; do not clear its busy state.
            return
        self._play_in_progress = False
        self._process_pending_play_request()

    def _queue_pending_play_request(
        self, info, force_new=False, exclude_uris=None,
        reason="Playing", one_shot: bool = False, pause_first: bool = False,
    ):
        """Remember one latest playlist request while another is loading.

        The Spotify controller can keep finalising for 10-20 seconds after
        the new mix is already audible.  Dropping a long-press during that
        window made "Try another" feel random.  Keep the newest request and
        run it as soon as the active controller operation really finishes.
        """
        self._pending_play_request = {
            "info": info,
            "force_new": bool(force_new),
            "exclude_uris": set(exclude_uris or []),
            "reason": reason,
            "one_shot": bool(one_shot),
            "pause_first": bool(pause_first),
        }
        try:
            self._log(
                "Another playlist is still loading - queued this request."
            )
        except Exception:
            pass

    def _process_pending_play_request(self):
        """Start the queued request once no playlist worker is active."""
        if getattr(self, "_play_in_progress", False):
            return
        pending = getattr(self, "_pending_play_request", None)
        if not pending:
            return
        self._pending_play_request = None
        if getattr(self, "_closing", False):
            return
        info = pending.get("info")
        if info is not None and info is not getattr(self, "current_game", None):
            try:
                self._log("Queued playlist request discarded (game changed).")
            except Exception:
                pass
            return
        try:
            self._play_query_for_game(
                info,
                force_new=pending.get("force_new", False),
                exclude_uris=pending.get("exclude_uris"),
                reason=pending.get("reason", "Playing"),
                one_shot=pending.get("one_shot", False),
                pause_first=pending.get("pause_first", False),
                _from_queue=True,
            )
        except Exception as ex:
            try:
                self._log(f"Queued playlist request failed: {ex}")
            except Exception:
                pass

    def _play_query_for_game(self, info, force_new=False, exclude_uris=None, reason="Playing", one_shot: bool = False, pause_first: bool = False, _from_queue: bool = False):
        if self._play_in_progress and not _from_queue:
            self._queue_pending_play_request(
                info,
                force_new=force_new,
                exclude_uris=exclude_uris,
                reason=reason,
                one_shot=one_shot,
                pause_first=pause_first,
            )
            return
        if pause_first:
            self._begin_playlist_switch_pause(reason)
        self._play_request_seq = int(getattr(self, "_play_request_seq", 0)) + 1
        request_id = self._play_request_seq
        self._active_play_request_id = request_id

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
            if pause_first:
                # Silence the old mix before the search/playlist navigation.
                self._pause_spotify_for_playlist_switch()
            # Attribute the upcoming audio to GameBeats immediately.  The
            # controller can take several seconds to return its result after
            # Spotify is already playing; without this, the overlay gate sees
            # "not started by us" and waits for that slow result.
            self._spotify_started_by_us = True
            self._playback_started_ts = time.time()
            try:
                if self._is_web_mode():
                    self.root.after(0, lambda q=search_q: self._log(
                        f"Searching for a playlist to play…"))
                    if self.spotify:
                        if not self.spotify.ensure_active_device():
                            err = getattr(self.spotify, "_last_error", "") or "browser failed"
                            self.root.after(0, lambda e=err: self._log(
                                f"⚠ Web player failed to start: {e}"))
                            self.root.after(0, lambda rid=request_id: self._on_play_result(None, mood, search_q, rid))
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
            self.root.after(0, lambda r=result, q=search_q, rid=request_id: self._on_play_result(r, mood, q, rid))

        threading.Thread(target=_run, daemon=True).start()

    def _on_play_result(self, result, mood, search_q, request_id=None):
        if (
            request_id is not None
            and request_id != getattr(self, "_active_play_request_id", 0)
        ):
            try:
                self._log("Ignored a stale playlist result.")
            except Exception:
                pass
            return
        # Keep _play_in_progress true until the scheduled UI callback has
        # applied this result.  A long-press in that gap is queued instead of
        # racing the stale result.
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
                    # A playlist switch already showed exactly one change
                    # clip when the user asked for it.  The controller result
                    # can arrive many seconds later; do not replay the clip
                    # then, and do not replay it if a newer request is queued.
                    switch_started = (
                        float(getattr(self, "_playlist_switch_started_ts", 0.0) or 0.0)
                        > 0.0
                    )
                    pending_after = (
                        getattr(self, "_pending_play_request", None) is not None
                    )
                    self._spotify_started_by_us = True
                    self._playback_started_ts = time.time()
                    # Clear the switch-pause flags *before* applying the play
                    # state.  _set_play_btn_icon checks _intentional_pause_active
                    # before starting the mascot, so the old order kept the pup
                    # in gif:0 until the next audio-meter tick.
                    self._remember_current_playlist(picked_uri, picked_name, picked_query, reset_pause_flags=True)
                    self._set_play_btn_icon(True, force_btn=True)
                    # Keep title polling from triggering a second change
                    # reaction right after the playlist starts.
                    self._track_change_anim_quiet_until = max(
                        float(getattr(self, "_track_change_anim_quiet_until", 0.0) or 0.0),
                        time.time() + 6.0,
                    )
                    # A newer long-press is queued: keep thinking for that
                    # request instead of completing the animation for this
                    # (already superseded) result.
                    if not pending_after:
                        if not self._finish_puppy_thinking(play_change=True):
                            if not switch_started:
                                self._play_puppy_change_animation(force=True)
                    self._playlist_switch_started_ts = 0.0
                    self._playlist_switch_audio_heard_ts = 0.0
                    self._playlist_switch_heard_silence = False
                    self._playlist_switch_pause_confirmed = False
                    # The web player often exposes the new song a beat or two
                    # after starting.  Poll quickly for the first several
                    # seconds instead of waiting for the 4s steady-state tick.
                    self._schedule_fast_track_refresh()
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
                finally:
                    # Run a coalesced long-press only after this result's UI
                    # state has been applied, so it cannot be overwritten.
                    self._finish_play_query(request_id)
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
            self._playlist_switch_pause = False
            self._playlist_switch_heard_silence = False
            self._playlist_switch_started_ts = 0.0
            self._playlist_switch_audio_heard_ts = 0.0
            self._playlist_switch_pause_confirmed = False
            # Do not leave an early "ours" claim behind after a real failure;
            # otherwise unrelated Spotify audio could reveal the puppy.
            try:
                if (
                    not getattr(self, "_is_playing", False)
                    and not self._spotify_sound_detected_recently(2.0)
                ):
                    self._spotify_started_by_us = False
            except Exception:
                pass
            err = getattr(self.spotify, "_last_error", "") or "No playlist found"
            self._log(f"⚠ Playlist did not start: {err[:100]}")
            self._log("No playlist was switched automatically — use Try another if needed.")
            # Do not leave the loading loop running for 45s after a real
            # failure.  A queued long-press will start its own thinking loop.
            if getattr(self, "_pending_play_request", None) is None:
                self._stop_puppy_thinking(hold_pause=False)
            # A queued long-press still deserves a real attempt even if this
            # particular search/play failed.
            self._finish_play_query(request_id)

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
            and getattr(self, "_auto_mode_value", True)
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
                        if (self._spotify_loud_streak == 1
                                and not getattr(self, "_playlist_audio_armed", False)):
                            # The first audible tick is the best moment to ask
                            # the web player for the real first-track title.
                            self.root.after(0, self._schedule_fast_track_refresh)
                        # A replacement playlist often becomes audible before
                        # the slow search/controller worker returns.  Once the
                        # old mix has gone silent and the new audio has been
                        # sustained for ~1s, adopt it immediately so the icon
                        # and puppy do not sit frozen in the switch pause.
                        if (
                            getattr(self, "_playlist_switch_pause", False)
                            and not getattr(self, "_paused_by_game_flag", False)
                            and getattr(self, "_playlist_switch_pause_confirmed", False)
                            and getattr(self, "_playlist_switch_heard_silence", False)
                            and self._spotify_loud_streak >= 1
                        ):
                            self.root.after(
                                0, self._adopt_playlist_switch_playback
                            )
                        intentional_pause = bool(
                            getattr(self, "_manual_paused", False)
                            or getattr(self, "_user_paused_flag", False)
                            or getattr(self, "_paused_by_game_flag", False)
                        )
                        if not intentional_pause:
                            resumed_now = not bool(
                                getattr(self, "_is_playing", False)
                            )
                            self._is_playing = True
                            if resumed_now:
                                self.root.after(0, lambda: (
                                    # First confirmed audio should update the
                                    # icon immediately; waiting for the resume
                                    # worker made the button lag behind music.
                                    self._set_play_btn_icon(True, force_btn=True),
                                    self._react_to_playback_change(True),
                                ))
                            else:
                                self.root.after(
                                    0, lambda: self._set_play_btn_icon(True)
                                )
                            self._remove_pause_reason("user")
                            self._remove_pause_reason("auto")
                    else:
                        self._spotify_loud_streak = 0
                        if getattr(self, "_playlist_switch_pause", False):
                            self._playlist_switch_heard_silence = True
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
            user_paused = bool(
                getattr(self, "_manual_paused", False)
                or getattr(self, "_user_paused_flag", False)
            )
            game_paused = bool(getattr(self, "_paused_by_game_flag", False))
            started_by_us = bool(getattr(self, "_spotify_started_by_us", False))
            switch_pause = bool(getattr(self, "_playlist_switch_pause", False))
            thinking = self._puppy_thinking_active()
            # Do not reveal the puppy for Spotify audio that GameBeats did not
            # start (including a previous session still playing at launch).
            active = (
                bool(visible)
                and not intentionally_stopped
                and not notifier_up
                and started_by_us
            )
            self._puppy_audio_active = active
            # No room repaint here.  The in-room mascot reads the play state on
            # the master clock, so rebuilding the whole den for every meter
            # dip made the canvas flicker around the puppy.

            if overlay is None:
                return

            if not started_by_us and not notifier_up:
                # No GameBeats playback has started yet (first launch, or the
                # user is playing Spotify elsewhere): keep the puppy hidden.
                try:
                    if overlay.is_visible():
                        overlay.hide(immediate=True)
                except Exception:
                    pass
                self._puppy_audio_active = False
                return

            hide_job = getattr(self, "_puppy_hide_job", None)
            if (
                switch_pause
                and thinking
                and not notifier_up
                and not game_paused
                and started_by_us
            ):
                # The next playlist is still loading, so there may be no audio
                # meter ticks.  Keep the thinking loop on screen instead of
                # hiding it or locking into the drooped pause pose.
                if hide_job is not None:
                    try:
                        self.root.after_cancel(hide_job)
                    except Exception:
                        pass
                    self._puppy_hide_job = None
                try:
                    overlay.set_animation_locked(False)
                    overlay.play_thinking_animation()
                except Exception:
                    pass
                overlay.show()
                return

            if active:
                self._puppy_last_loud_ts = time.time()
                if hide_job is not None:
                    try:
                        self.root.after_cancel(hide_job)
                    except Exception:
                        pass
                    self._puppy_hide_job = None
                try:
                    overlay.set_animation_locked(False)
                    overlay.set_playback_state(True, animate=True)
                except Exception:
                    pass
                overlay.show()
                return

            if intentionally_stopped:
                if hide_job is not None:
                    try:
                        self.root.after_cancel(hide_job)
                    except Exception:
                        pass
                    self._puppy_hide_job = None
                # A manual pause keeps the desktop puppy on screen (frozen in
                # its drooped pose) so another click can resume playback.
                try:
                    overlay.set_animation_locked(True, animate=bool(user_paused))
                except Exception:
                    pass
                if user_paused and not game_paused:
                    try:
                        if overlay.is_visible():
                            overlay.set_playback_state(False, animate=True)
                            return
                    except Exception:
                        pass
                try:
                    overlay.set_playback_state(False, animate=False)
                except Exception:
                    pass
                overlay.hide(immediate=True)
                return

            if notifier_up:
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
        if (
            getattr(self, "_playlist_switch_pause", False)
            and self._puppy_thinking_active()
        ):
            # A playlist search can take 20+ seconds without any audio.  The
            # thinking overlay is the loading indicator and must stay up.
            return
        try:
            if time.time() - float(getattr(self, "_puppy_last_loud_ts", 0.0) or 0.0) < 1.0:
                return
            user_paused = bool(
                getattr(self, "_manual_paused", False)
                or getattr(self, "_user_paused_flag", False)
            )
            game_paused = bool(getattr(self, "_paused_by_game_flag", False))
            if (
                self._intentional_pause_active()
                or getattr(self, "_mascot_notifier", None) is not None
            ):
                if (
                    user_paused
                    and not game_paused
                    and getattr(self, "_mascot_notifier", None) is None
                ):
                    try:
                        if overlay.is_visible():
                            return
                    except Exception:
                        pass
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
            if hasattr(self, "_send_spotify_pause_command"):
                ok = bool(self._send_spotify_pause_command(
                    paused_by_game=True, was_playing=True
                ))
            elif hasattr(self.spotify, "ensure_paused"):
                try:
                    ok = bool(self.spotify.ensure_paused(paused_by_game=True))
                except TypeError:
                    ok = bool(self.spotify.ensure_paused())
            else:
                ok = bool(self.spotify.media_stop())
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Other-audio pause failed: {e}"))

        if ok:
            self._remember_spotify_pause_claim(True)
            self._paused_by_game_flag = True
            self._playlist_end_pending = False
            self._music_missing_since = 0.0
            self._playlist_audio_armed = False
            self._spotify_loud_streak = 0
            self._playlist_switch_pause = False
            self._playlist_switch_heard_silence = False
            self._playlist_switch_pause_confirmed = False
            self._add_pause_reason("auto")
            self._is_playing = False
            if already_paused_by_game:
                self.root.after(0, lambda: (
                    self._set_play_btn_icon(False, force_btn=True),
                    self._react_to_playback_change(False),
                    self._set_puppy_singing_visible(False),
                ))
            else:
                self.root.after(0, lambda p=peak: (
                    self._set_play_btn_icon(False, force_btn=True),
                    self._react_to_playback_change(False),
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

        # Check only the source that was actually paused.  A union loopback
        # meter can stay "loud" because of unrelated browser audio (for example
        # YouTube) and would otherwise skip the real Spotify resume.
        source = str(getattr(self, "_paused_spotify_source", "") or "")
        if source:
            s_peak, s_status = self._spotify_source_peak(source)
            if (s_status == "ok"
                    and s_peak >= SPOTIFY_SOURCE_AUDIBLE_THRESHOLD):
                # Spotify is already playing. Mark it resumed and skip command.
                self._paused_spotify_source = ""
                self._paused_by_game_flag = False
                self._remove_pause_reason("auto")
                self._is_playing = True
                self._music_missing_since = 0.0
                self._last_spotify_loud_ts = time.time()
                self.root.after(0, lambda: (
                    self._set_play_btn_icon(True, force_btn=True),
                    self._react_to_playback_change(True),
                ))
                return

        ok = False
        try:
            ok = bool(self._send_spotify_resume_command())
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Other-audio resume failed: {e}"))

        if ok:
            self._remember_spotify_pause_claim(False)
            self._paused_by_game_flag = False
            self._remove_pause_reason("auto")
            self._is_playing = True
            self._music_missing_since = 0.0
            self._last_spotify_loud_ts = time.time()
            self.root.after(0, lambda: (
                self._set_play_btn_icon(True, force_btn=True),
                self._react_to_playback_change(True),
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
            self._playlist_switch_pause = False
            self._playlist_switch_heard_silence = False
            self._playlist_switch_pause_confirmed = False
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
            self.playlist_display_lbl.configure(text=(self._current_playlist_name or "Nothing loaded yet")),
            self.track_lbl.configure(text=self._current_playlist_name or "Spotify Playlist"),
            self.deck_artist_lbl.configure(text="Spotify"),
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
        game_snapshot = self.current_game
        try:
            auto_mode = bool(self.auto_mode.get())
        except Exception:
            auto_mode = True

        if not uri:
            self._log("No current playlist to block yet.")
            return
        if game_snapshot and auto_mode:
            # Feedback only when this block will actually pick a replacement.
            self._start_puppy_thinking_animation(reason="playlist")

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


            if game_snapshot and auto_mode:
                # _play_query_for_game starts its own worker thread. Route back
                # through the Tk thread so pause state and the play icon update
                # safely before the (possibly slow) next-playlist search.
                def _start_next():
                    if self.current_game is not game_snapshot:
                        self._playlist_end_pending = False
                        return
                    self._play_query_for_game(
                        game_snapshot,
                        force_new=False,
                        exclude_uris=set(self._tried_playlist_uris),
                        reason="Blocked \u2014 picking another",
                        pause_first=True,
                    )

                self.root.after(0, _start_next)
            elif self.spotify:
                # No game running — just stop
                threading.Thread(target=self.spotify.media_stop, daemon=True).start()

        threading.Thread(target=_go, daemon=True).start()

    def _try_another_playlist(self):
        if not self.current_game:
            self._log("Start a saved game first, then GameBeats can pick another playlist.")
            return
        self._start_puppy_thinking_animation(reason="playlist")

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

        try:
            # Prefer reusing the established Spotify connection/device.
            # pause_first silences the current mix before the search starts.
            self._play_query_for_game(
                self.current_game,
                force_new=False,
                exclude_uris=set(self._tried_playlist_uris),  # Exclude all tried playlists
                reason="Picking another playlist",
                pause_first=True,
            )
        except Exception as ex:
            self._log(f"Try-another failed: {ex}")

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
        # CTkToplevel gives us the dark immersive title bar automatically;
        # a plain tk.Toplevel keeps the bright native chrome and clashes with
        # the rest of the den.
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("Add playlist link")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        # CTkToplevel scales width/height by the display DPI but leaves the
        # +x+y offset alone. Convert our logical size before centering so the
        # dialog stays centred over the den on high-DPI screens.
        w, h = 500, 432
        try:
            scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            scale = 1.0
        dw, dh = int(w * scale), int(h * scale)
        rx = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dw) // 2)
        ry = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dh) // 2)
        dlg.geometry(f"{w}x{h}+{rx}+{ry}")

        _icon = _load_puppy_window_icon((48, 48))
        if _icon:
            dlg._icon_ref = _icon
            dlg.after(50, lambda: dlg.iconphoto(False, _icon))
            dlg.after(200, lambda: dlg.iconphoto(False, _icon))

        ctk.CTkFrame(dlg, fg_color=ACCENT, height=3, corner_radius=0).pack(fill=tk.X)

        body = ctk.CTkFrame(dlg, fg_color="transparent", corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True, padx=24, pady=(16, 18))

        head = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        head.pack(fill=tk.X)

        logo_path = _puppy_logo_path()
        if logo_path and HAS_PIL:
            try:
                resampling = getattr(Image, "Resampling", Image)
                pup = Image.open(logo_path).convert("RGBA").resize(
                    (44, 50), resampling.NEAREST,
                )
                dlg._dialog_puppy = ctk.CTkImage(
                    light_image=pup, dark_image=pup, size=(44, 50),
                )
                ctk.CTkLabel(head, image=dlg._dialog_puppy, text="").pack(
                    side=tk.LEFT, padx=(0, 14),
                )
            except Exception:
                pass

        col = ctk.CTkFrame(head, fg_color="transparent", corner_radius=0)
        col.pack(side=tk.LEFT, anchor="w")

        ctk.CTkLabel(
            col, text="RECORD CRATE / NEW SLEEVE", fg_color="transparent",
            text_color=GOLD, font=T.pixel_font(10, "bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            col, text="Add playlist link", fg_color="transparent",
            text_color=TEXT, font=T.serif_font(27, "bold"), anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            col, text="File a Spotify mix in the crate.", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(15), anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        panel = ctk.CTkFrame(
            body, fg_color=SURFACE, border_width=2, border_color=WOOD,
            corner_radius=0,
        )
        panel.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

        pad = ctk.CTkFrame(panel, fg_color="transparent", corner_radius=0)
        pad.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 10))

        name_var = tk.StringVar(value="My playlist")
        link_var = tk.StringVar()

        ctk.CTkLabel(
            pad, text="NAME", fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(10, "bold"), anchor="w",
        ).pack(fill=tk.X)
        name_entry = ctk.CTkEntry(
            pad, textvariable=name_var, fg_color=SURFACE2, border_color=WOOD,
            border_width=1, text_color=TEXT, corner_radius=0,
            font=T.retro_font(17), height=42,
        )
        name_entry.pack(fill=tk.X, pady=(3, 10))

        ctk.CTkLabel(
            pad, text="SPOTIFY LINK", fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(10, "bold"), anchor="w",
        ).pack(fill=tk.X)
        link_entry = ctk.CTkEntry(
            pad, textvariable=link_var, fg_color=SURFACE2, border_color=WOOD,
            border_width=1, text_color=TEXT, corner_radius=0,
            placeholder_text="https://open.spotify.com/playlist/...",
            placeholder_text_color=TEXT_MUTED,
            font=T.retro_font(17), height=42,
        )
        link_entry.pack(fill=tk.X, pady=(3, 5))

        ctk.CTkLabel(
            pad, text="Right-click the playlist in Spotify \u2192 Share \u2192 Copy link.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), anchor="w", justify=tk.LEFT,
            wraplength=420,
        ).pack(fill=tk.X)

        err_lbl = ctk.CTkLabel(
            pad, text=" ", fg_color="transparent", text_color=AMBER,
            font=T.retro_font(14), anchor="w", justify=tk.LEFT,
            wraplength=420,
        )
        err_lbl.pack(fill=tk.X, pady=(5, 0))

        def save(_event=None):
            name = name_var.get().strip() or "My playlist"
            link = link_var.get().strip()
            if not link:
                err_lbl.configure(
                    text="Paste a Spotify playlist link first.", text_color=AMBER)
                link_entry.focus_set()
                return
            if not self.spotify:
                err_lbl.configure(
                    text="Spotify is not connected yet.", text_color=ORANGE)
                return
            try:
                ok, err = self.spotify.add_playlist_link(name, link)
            except Exception as exc:
                ok, err = False, str(exc)
            if ok:
                dlg.grab_release()
                dlg.destroy()
                self._load_playlists()
                self._log(f"Playlist added: {name}")
            else:
                err_lbl.configure(
                    text=err or "Could not add that link.", text_color=ORANGE)
                link_entry.focus_set()

        brow = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        brow.pack(fill=tk.X, pady=(14, 0))

        ctk.CTkLabel(
            brow, text="ESC TO CLOSE", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.pixel_font(8), anchor="w",
        ).pack(side=tk.LEFT)
        add_btn = T.pixel_button(
            brow, text="+ ADD LINK", command=save, width=132, height=38,
            accent=True,
        )
        add_btn.pack(side=tk.RIGHT)
        T.pixel_button(
            brow, text="CANCEL", command=dlg.destroy, width=104, height=38,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        name_entry.bind("<Return>", lambda _e: link_entry.focus_set())
        link_entry.bind("<Return>", save)
        dlg.after(100, link_entry.focus_set)
        dlg.after(120, dlg.lift)

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
        actual_changed = playing != previous
        changed = actual_changed or bool(force_btn)
        self._is_playing = playing
        if not playing:
            # Stale meter state must not make the next play request reveal the
            # desktop puppy before the new audio is actually audible.
            self._spotify_audio_active = False
        if actual_changed:
            try:
                self._react_to_playback_change(playing)
            except Exception:
                pass
        # The play button used to pulse between four golds while playing.  That
        # made the pause/resume icon look like it was flickering, especially
        # when audio ticks repeated.  Keep the button a single solid gold.
        if getattr(self, "_pulse_job", None):
            try:
                self.root.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None
        self._pulse_active = False
        # Only an explicit user/auto action may change the visible icon.
        # Audio-meter ticks call this method too, and letting them overwrite
        # the icon is what made the UI show "paused" while music was audible.
        if force_btn and hasattr(self, "play_btn"):
            try:
                self.play_btn.update_text(
                    T.media_icon("pause") if playing else T.media_icon("play")
                )
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
                    # Do not reveal/bob the desktop puppy just because a play
                    # command was accepted.  Wait until the audio meter has
                    # actually heard music; the monitor calls this method with
                    # the confirmed state on the first loud tick.  Otherwise
                    # the puppy bobs during playlist loading with no sound.
                    if getattr(self, "_audio_monitor_running", False):
                        # With a live meter, wait for confirmed audio.  The
                        # monitor calls this method with the real loud state.
                        if getattr(self, "_spotify_audio_active", False):
                            self._set_puppy_singing_visible(True)
                    else:
                        # No meter is available (e.g. no game session), so the
                        # play state is the best signal we have.
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

    def _spotify_browser_page_kind(self) -> str:
        """Return 'controller' / 'player' only when that page is Spotify.

        Playwright objects are thread-affine, so the URL check runs on the
        browser worker thread.  An empty result means we must not send any
        browser command: the page may be YouTube or another site.
        """
        controller = getattr(self, "spotify", None)
        if controller is None:
            return ""
        now = time.time()
        cached = getattr(self, "_spotify_browser_kind_cache", None)
        if cached and 0.0 <= now - cached[0] <= 1.0:
            return cached[1]

        def _classify():
            for kind, attr in (("controller", "_page"), ("player", "_player_page")):
                page = getattr(controller, attr, None)
                if page is None:
                    continue
                try:
                    if page.is_closed():
                        continue
                    url = str(getattr(page, "url", "") or "")
                except Exception:
                    continue
                if _is_spotify_web_url(url):
                    return kind
            return ""

        browser_call = getattr(controller, "_browser_call", None)
        result = ""
        if callable(browser_call):
            try:
                result = str(browser_call(_classify, timeout=2.0, default="") or "")
            except TypeError:
                try:
                    result = str(browser_call(_classify) or "")
                except Exception:
                    result = ""
            except Exception:
                result = ""
        else:
            try:
                result = str(_classify() or "")
            except Exception:
                result = ""
        self._spotify_browser_kind_cache = (time.time(), result)
        return result

    def _send_spotify_browser_command(
        self, action: str, paused_by_game: bool = False
    ) -> bool:
        """Control only a browser page that is still on open.spotify.com."""
        controller = getattr(self, "spotify", None)
        if controller is None or action not in ("play", "pause"):
            return False
        kind = self._spotify_browser_page_kind()
        if kind not in ("controller", "player"):
            return False
        attr = "_player_page" if kind == "player" else "_page"

        def _work():
            page = getattr(controller, attr, None)
            if page is None:
                return False
            try:
                if page.is_closed():
                    return False
                url = str(getattr(page, "url", "") or "")
                if not _is_spotify_web_url(url):
                    # The page navigated between the source check and the
                    # command.  Never press Space on an arbitrary website.
                    return False
            except Exception:
                return False

            desired = action == "play"
            try:
                state = controller._player_is_playing(page)
            except Exception:
                state = None
            if state is desired:
                # Already in the requested state.  Do not toggle back.
                return True

            # Spotify's play/pause control can spend several seconds waiting
            # to become "actionable" while the page's Space shortcut still
            # toggles immediately.  Send Space only to this already-verified
            # Spotify page; never a global media key.  The caller still waits
            # for real audio before declaring success, and a retry re-reads
            # the state above so it cannot press twice.
            if state is not None:
                try:
                    page.keyboard.press("Space")
                    return True
                except Exception:
                    pass

            # Unknown page state (or the shortcut failed): use Spotify's own
            # verified control path.  It is slower, but remains page-scoped.
            method_name = "_pause_player" if action == "pause" else "_play_player"
            method = getattr(controller, method_name, None)
            if not callable(method):
                return False
            try:
                return bool(method(page))
            except Exception:
                return False

        browser_call = getattr(controller, "_browser_call", None)
        if callable(browser_call):
            try:
                return bool(browser_call(_work, timeout=15.0, default=False))
            except TypeError:
                try:
                    return bool(browser_call(_work) or False)
                except Exception:
                    return False
            except Exception:
                return False
        try:
            return bool(_work())
        except Exception:
            return False

    def _ensure_spotify_window_guard(self):
        """Create the UI-side guard that keeps Spotify's window off-screen."""
        guard = getattr(self, "_spotify_window_guard", None)
        if guard is not None:
            return guard
        try:
            guard = SpotifyWindowGuard(logger=self._log)
        except Exception as ex:
            try:
                self._log(f"Could not start Spotify window guard: {ex}")
            except Exception:
                pass
            return None
        self._spotify_window_guard = guard
        return guard

    def _spotify_desktop_controller(self):
        """Return Spotify's desktop controller if one is available."""
        controller = getattr(self, "spotify", None)
        if controller is None:
            return None
        guard = self._ensure_spotify_window_guard()
        helper = getattr(controller, "_desktop_helper", None)
        if callable(helper):
            desktop = getattr(controller, "_desktop_player", None)
            if desktop is None:
                try:
                    desktop = helper()
                except Exception:
                    desktop = None
            if desktop is not None:
                try:
                    install_targeted_transport(desktop, logger=self._log)
                except Exception as ex:
                    try:
                        self._log(f"Could not install targeted Spotify transport: {ex}")
                    except Exception:
                        pass
                if guard is not None:
                    guard.install(desktop)
            return desktop
        try:
            install_targeted_transport(controller, logger=self._log)
        except Exception as ex:
            try:
                self._log(f"Could not install targeted Spotify transport: {ex}")
            except Exception:
                pass
        if guard is not None:
            guard.install(controller)
        return controller

    def _spotify_source_available(self, source: str) -> bool:
        if source == "browser":
            return bool(self._spotify_browser_page_kind())
        if source == "desktop":
            desktop = self._spotify_desktop_controller()
            if desktop is None:
                return False
            return any(
                callable(getattr(desktop, name, None))
                for name in ("ensure_paused", "pause", "media_stop")
            )
        return False

    def _spotify_source_peak(self, source: str) -> tuple:
        """(peak, status) for one Spotify source, never a union meter."""
        try:
            from core.audio_monitor import (
                get_browser_spotify_peak,
                get_desktop_spotify_peak,
            )
            if source == "browser":
                peak, status = get_browser_spotify_peak()
            elif source == "desktop":
                peak, status = get_desktop_spotify_peak()
            else:
                return 0.0, "unknown"
            return float(peak or 0.0), str(status or "")
        except Exception:
            return 0.0, "unknown"

    def _spotify_active_source(self) -> str:
        """Pick the one source GameBeats is allowed to control right now."""
        if getattr(self, "spotify", None) is None:
            return ""
        threshold = SPOTIFY_SOURCE_AUDIBLE_THRESHOLD

        # Fast path: the last source that actually produced audio is usually
        # still the right one.  Confirm it with its own meter before returning,
        # so a stale flag can never make us target a silent source.  This also
        # avoids a browser-thread round trip for desktop playback.
        for candidate in (
            str(getattr(self, "_paused_spotify_source", "") or ""),
            str(getattr(self.spotify, "_last_audio_source", "") or ""),
        ):
            if candidate not in ("browser", "desktop"):
                continue
            if not self._spotify_source_available(candidate):
                continue
            peak, status = self._spotify_source_peak(candidate)
            if status == "ok" and peak >= threshold:
                return candidate

        browser_kind = self._spotify_browser_page_kind()
        browser_peak, browser_status = (0.0, "no-page")
        if browser_kind:
            browser_peak, browser_status = self._spotify_source_peak("browser")
        desktop = self._spotify_desktop_controller()
        desktop_peak, desktop_status = (0.0, "no-desktop")
        if desktop is not None:
            desktop_peak, desktop_status = self._spotify_source_peak("desktop")

        b_ok = browser_status == "ok" and browser_peak >= threshold
        d_ok = desktop_status == "ok" and desktop_peak >= threshold
        if b_ok and browser_peak >= desktop_peak and browser_kind:
            return "browser"
        if d_ok:
            return "desktop"

        preferred = str(getattr(self, "_paused_spotify_source", "") or "")
        if preferred == "browser" and browser_kind:
            return "browser"
        if preferred == "desktop" and desktop is not None:
            return "desktop"

        last = str(getattr(self.spotify, "_last_audio_source", "") or "")
        if last == "browser" and browser_kind:
            return "browser"
        if last == "desktop" and desktop is not None:
            return "desktop"

        uses_browser = getattr(self.spotify, "_uses_browser_player", None)
        if browser_kind and callable(uses_browser):
            try:
                if uses_browser():
                    return "browser"
            except Exception:
                pass
        if desktop is not None:
            return "desktop"
        if browser_kind:
            return "browser"
        return ""

    def _send_spotify_source_command(
        self, source: str, action: str, paused_by_game: bool = False
    ) -> bool:
        if action not in ("play", "pause"):
            return False
        if source == "browser":
            return self._send_spotify_browser_command(action, paused_by_game)
        if source == "desktop":
            desktop = self._spotify_desktop_controller()
            if desktop is None:
                return False
            try:
                if action == "pause":
                    method = getattr(desktop, "ensure_paused", None)
                    if callable(method):
                        return bool(method(paused_by_game=paused_by_game))
                    for name in ("pause", "media_stop"):
                        method = getattr(desktop, name, None)
                        if callable(method):
                            return bool(method())
                    return False
                method = getattr(desktop, "ensure_playing", None)
                if callable(method):
                    return bool(method())
                for name in ("resume", "play"):
                    method = getattr(desktop, name, None)
                    if callable(method):
                        return bool(method())
            except Exception:
                return False
            return False
        return False

    def _spotify_source_matches(
        self, source: str, playing: bool, allow_unknown: bool = False
    ) -> bool:
        if not source:
            return not bool(playing)
        peak, status = self._spotify_source_peak(source)
        if status != "ok":
            # An unavailable meter cannot prove either state.  The caller may
            # trust a successful targeted command, but otherwise fail closed.
            return bool(allow_unknown)
        if playing:
            return peak >= SPOTIFY_SOURCE_AUDIBLE_THRESHOLD
        return peak < SPOTIFY_SOURCE_AUDIBLE_THRESHOLD

    def _spotify_audio_playing_now(self) -> bool:
        """Best-effort *actual* audio check for one safe Spotify source."""
        source = self._spotify_active_source()
        if not source:
            return False
        peak, status = self._spotify_source_peak(source)
        return bool(status == "ok" and peak > SPOTIFY_UI_AUDIO_ON_THRESHOLD)

    def _wait_for_spotify_playback(
        self, playing: bool, timeout: float = 1.6, source: str = None,
        allow_unknown: bool = False, stable_samples: int = 2,
    ) -> bool:
        """Wait until one Spotify source *stably* matches the requested state.

        A single quiet WASAPI sample must not prove a pause: quiet passages and
        track transitions can dip below the threshold while music is still
        playing.  Requiring consecutive matching samples prevents a false
        "paused" state, and the same gate avoids declaring a slow resume.
        """
        target_source = source
        if target_source is None:
            target_source = self._spotify_active_source()
        if not target_source:
            return False
        need = max(1, int(stable_samples))
        matched_samples = 0
        deadline = time.time() + max(0.0, float(timeout))
        while True:
            if self._spotify_source_matches(
                target_source, playing, allow_unknown=allow_unknown
            ):
                matched_samples += 1
                if matched_samples >= need:
                    return True
            else:
                matched_samples = 0
            if time.time() >= deadline:
                return False
            time.sleep(0.12)

    def _spotify_desktop_is_primary_source(self) -> bool:
        """Compatibility helper: is the desktop client the safe source?"""
        return self._spotify_active_source() == "desktop"

    def _send_targeted_spotify_command(self, action: str) -> bool:
        """Compatibility wrapper for the source-targeted command path.

        This never sends WM_APPCOMMAND or a global media key; it only controls
        the desktop client's own UI or a Spotify browser page.
        """
        source = self._spotify_active_source()
        if not source:
            return False
        return self._send_spotify_source_command(source, action)

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

    def _get_spotify_command_lock(self):
        """Lock shared by user and audio-monitor pause/resume commands."""
        lock = getattr(self, "_spotify_command_lock_obj", None)
        if lock is None:
            lock = getattr(self, "_spotify_command_lock", None)
            if lock is None or not hasattr(lock, "__enter__"):
                lock = _SPOTIFY_COMMAND_FALLBACK_LOCK
            self._spotify_command_lock_obj = lock
        return lock

    def _send_spotify_pause_command(
        self, paused_by_game: bool = False, was_playing: bool = None
    ) -> bool:
        if not self.spotify:
            return False
        with self._get_spotify_command_lock():
            source = self._spotify_active_source()
            if not source:
                # Nothing safe to control.  Never report "paused" without a
                # source: this was the path that left the UI drooped while
                # Spotify kept playing.
                try:
                    self._log("Spotify pause skipped: no safe Spotify source.")
                except Exception:
                    pass
                return False

            def _mark_paused():
                self._remember_spotify_playback_state(False)
                self._remember_spotify_pause_claim(bool(paused_by_game))
                self._paused_spotify_source = source

            ok = self._send_spotify_source_command(
                source, "pause", paused_by_game=paused_by_game
            )
            if not ok:
                # A failed/partial command can still mean Spotify was already
                # silent.  Silence is safe to observe, but never toggle again.
                if self._wait_for_spotify_playback(
                    False, timeout=0.45, source=source,
                    allow_unknown=False, stable_samples=3,
                ):
                    _mark_paused()
                    return True
                return False

            # Confirm with sustained silence on the same source.  A single
            # quiet sample or a track transition must not count as a pause.
            # Deliberately no retry: if the first toggle actually landed but
            # the meter was late, a second toggle would resume the music while
            # the UI claimed it was paused.
            if self._wait_for_spotify_playback(
                False, timeout=2.0, source=source,
                allow_unknown=False, stable_samples=3,
            ):
                _mark_paused()
                return True
            return False

    def _send_spotify_resume_command(self) -> bool:
        if not self.spotify:
            return False
        with self._get_spotify_command_lock():
            source = str(getattr(self, "_paused_spotify_source", "") or "")
            if source and not self._spotify_source_available(source):
                source = ""
            if not source:
                source = self._spotify_active_source()
            try:
                _clear_spotify_mixer_mute()
            except Exception:
                pass

            def _mark_playing():
                self._remember_spotify_playback_state(True)
                self._remember_spotify_pause_claim(False)
                self._paused_spotify_source = ""

            if not source:
                return False

            # The targeted command itself is idempotent: both browser and
            # desktop controllers check the real playback state before
            # toggling.  Do not add a pre-command audio wait here; that would
            # make every resume slower and could mistake decaying pause tail
            # audio for an already-playing source.
            ok = self._send_spotify_source_command(source, "play")
            if not ok:
                # The command can fail after the audio has already started.
                # Accept only real audio; do not toggle again.
                if self._wait_for_spotify_playback(
                    True, timeout=0.6, source=source,
                    allow_unknown=False, stable_samples=2,
                ):
                    _mark_playing()
                    return True
                return False

            # Same rule as pause: no blind retry.  If Spotify started playing
            # but the meter is slow, a retry would pause it again.
            if self._wait_for_spotify_playback(
                True, timeout=2.2, source=source,
                allow_unknown=False, stable_samples=3,
            ):
                _mark_playing()
                return True
            return False

    def _remember_spotify_pause_claim(self, paused: bool):
        """Keep core's game-pause claim in sync with a targeted command."""
        targets = [getattr(self, "spotify", None)]
        desktop = self._spotify_desktop_controller()
        if desktop is not None:
            targets.append(desktop)
        seen = set()
        for target in targets:
            if target is None or id(target) in seen:
                continue
            seen.add(id(target))
            try:
                target._paused_by_game = bool(paused)
            except Exception:
                continue

    def _remember_spotify_playback_state(self, playing: bool):
        """Mirror a confirmed targeted command into core's cached state."""
        targets = [getattr(self, "spotify", None)]
        desktop = self._spotify_desktop_controller()
        if desktop is not None:
            targets.append(desktop)
        seen = set()
        for target in targets:
            if target is None or id(target) in seen:
                continue
            seen.add(id(target))
            try:
                target._is_playing = bool(playing)
                target._playback_state_known = True
            except Exception:
                continue

    def _apply_user_pause_state(self, paused: bool, *, preserve_thinking=False):
        self._user_toggle_ts = time.time()
        # Any explicit user/auto pause supersedes a transient playlist-switch
        # pause.  _begin_playlist_switch_pause passes preserve_thinking=True
        # because its pause is the loading state that owns the thinking loop.
        if not preserve_thinking:
            self._playlist_switch_pause = False
            self._playlist_switch_audio_heard_ts = 0.0
            self._playlist_switch_pause_confirmed = False
        # The next end-of-playlist check must wait until this playlist's
        # audio is actually heard again.  Silence during a pause/resume
        # transition is not a finished playlist.
        self._playlist_audio_armed = False
        self._spotify_loud_streak = 0
        if paused:
            if preserve_thinking:
                # This is the transient playlist-switch pause, not a real
                # user pause.  Keep the thinking loop visible and do not lock
                # the overlay into the drooped pause pose.  A game pause is
                # still left intact and remains authoritative.
                self._playlist_end_pending = False
                self._music_missing_since = 0.0
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
                self._manual_paused = True
                self._user_paused_flag = True
                self._paused_by_game_flag = False
                self._add_pause_reason("user")
                self._remove_pause_reason("auto")
                self._playlist_end_pending = False
                self._music_missing_since = 0.0
                # A real pause owns the drooped pose.  Clear the room thinking
                # loop here; the overlay lock below replaces its clip too.
                self._stop_puppy_thinking(
                    hold_pause=False, update_overlay=False
                )
                # Keep the playlist-end prompt from firing immediately after a
                # resume (audio may need a moment to come back).
                self._playlist_end_prompt_not_before = (
                    time.time() + max(3.0, self._playlist_end_delay_seconds())
                )
                # Lock the desktop puppy before the button update can trigger
                # its visibility path, so a long-press cannot start a change
                # clip during the pause.
                try:
                    overlay = getattr(self, "_puppy_singing_overlay", None)
                    if overlay is not None:
                        overlay.set_animation_locked(True, animate=True)
                except Exception:
                    pass
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

    def _clear_user_pause_for_skip(self) -> bool:
        """A next/previous command is also an intent to hear the new track.

        Spotify starts audio on some players when you press "next" while
        paused.  The old pause flags made the audio monitor keep the UI in the
        paused pose even though the new song was audible.  Clear only a user
        pause here; a game-audio pause is still authoritative until the game
        is quiet again.  The UI only flips to playing once the new audio is
        actually confirmed.
        """
        user_paused = bool(
            getattr(self, "_manual_paused", False)
            or getattr(self, "_user_paused_flag", False)
        )
        if not user_paused:
            return False
        self._manual_paused = False
        self._user_paused_flag = False
        self._remove_pause_reason("user")
        if not getattr(self, "_paused_by_game_flag", False):
            try:
                self.spotify._paused_by_game = False
            except Exception:
                pass
        self._playlist_switch_pause = False
        self._playlist_switch_heard_silence = False
        self._playlist_switch_pause_confirmed = False
        self._playlist_switch_audio_heard_ts = 0.0
        self._playlist_audio_armed = False
        self._spotify_loud_streak = 0
        self._music_missing_since = 0.0
        self._playlist_end_pending = False
        self._user_toggle_ts = time.time()
        self._playlist_end_prompt_not_before = (
            self._user_toggle_ts + max(4.0, self._playlist_end_delay_seconds())
        )
        return True

    def _skip_request_is_current(self, request_id) -> bool:
        try:
            return int(request_id) == int(
                getattr(self, "_skip_request_seq", 0) or 0
            )
        except Exception:
            return False

    def _confirm_skip_playback(self, request_id):
        """Wait briefly for a paused next/prev command to start audio."""
        deadline = time.time() + 2.4
        while time.time() < deadline:
            if not self._skip_request_is_current(request_id):
                return False
            if self._intentional_pause_active():
                return False
            playing = self._spotify_audio_playing_now()
            if not playing:
                playing = bool(self._read_spotify_is_playing())
            if playing:
                self.root.after(
                    0, lambda rid=request_id: self._adopt_skip_playback(rid)
                )
                return True
            time.sleep(0.15)
        return False

    def _adopt_skip_playback(self, request_id) -> bool:
        """Show playing after a next/prev command produced real audio."""
        if not self._skip_request_is_current(request_id):
            return False
        if self._intentional_pause_active():
            return False
        self._manual_paused = False
        self._user_paused_flag = False
        self._remove_pause_reason("user")
        self._remove_pause_reason("auto")
        self._spotify_started_by_us = True
        self._playback_started_ts = time.time()
        self._last_spotify_loud_ts = self._playback_started_ts
        self._spotify_audio_active = True
        self._music_missing_since = 0.0
        self._playlist_end_pending = False
        self._playlist_audio_armed = True
        self._is_playing = True
        self._set_play_btn_icon(True, force_btn=True)
        self._set_puppy_singing_visible(True)
        # Audio from the new track is confirmed: replace the thinking loop
        # with the single completion clip.
        try:
            self._finish_puppy_thinking(play_change=True)
        except Exception:
            pass
        return True

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
        was_playing = bool(getattr(self, "_is_playing", False))
        self._apply_user_pause_state(True)
        def _do_pause():
            try:
                ok = self._send_spotify_pause_command(was_playing=was_playing)
            except Exception:
                ok = False
            def finish():
                self._finish_play_pause()
                if ok:
                    self._set_play_btn_icon(False, force_btn=True)
                else:
                    # The command was not confirmed by actual audio.  It is
                    # safer to keep the playing pose than to show a droop for
                    # music the user can still hear.  A later audio tick can
                    # still reconcile the state.
                    self._apply_user_pause_state(False)
                    self._set_play_btn_icon(True, force_btn=True)
                    self._log("Spotify pause did not confirm — still playing.")
            self.root.after(0, finish)
        try:
            threading.Thread(target=_do_pause, daemon=True).start()
        except Exception as ex:
            self._finish_play_pause()
            self._apply_user_pause_state(False)
            self._set_play_btn_icon(True, force_btn=True)
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
                    # The targeted retry could not make Spotify audible.
                    # Return to the paused pose instead of lying about it.
                    self._apply_user_pause_state(True)
                    self._set_play_btn_icon(False, force_btn=True)
                    self._log("Spotify resume did not confirm — click Play again.")
            self.root.after(0, finish)
        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception as ex:
            self._finish_play_pause()
            self._apply_user_pause_state(True)
            self._set_play_btn_icon(False, force_btn=True)
            self._log(f"Could not start resume command: {ex}")
            return False
        return True

    def _play_pause_toggle(self):
        """Single-button toggle: pause if playing, play if paused.

        Returns False only when the request was refused because another
        play/pause action is already in flight.
        """
        if not self.spotify or not self._begin_play_pause():
            return False
        self._user_toggle_ts = time.time()

        was_playing = self._spotify_is_playing_for_toggle()
        target_playing = not was_playing
        self._apply_user_pause_state(not target_playing)

        def go():
            ok = False
            try:
                if was_playing:
                    ok = self._send_spotify_pause_command(was_playing=True)
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
                    if target_playing:
                        # Resume failed: remain visibly paused so the next
                        # click still means Play.
                        self._apply_user_pause_state(True)
                        self._set_play_btn_icon(False, force_btn=True)
                    else:
                        # Pause failed: Spotify is still audible, so restore
                        # the playing pose and clear the optimistic droop.
                        self._apply_user_pause_state(False)
                        self._set_play_btn_icon(True, force_btn=True)

            self.root.after(0, finish)

        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception as ex:
            self._finish_play_pause()
            if target_playing:
                self._apply_user_pause_state(True)
                self._set_play_btn_icon(False, force_btn=True)
            else:
                self._apply_user_pause_state(False)
                self._set_play_btn_icon(True, force_btn=True)
            self._log(f"Could not start play/pause command: {ex}")
        return True

    def _play_pause(self):
        """Legacy alias — routes to the toggle."""
        self._play_pause_toggle()

    def _next(self):
        if self.spotify:
            self._skip_request_seq = int(
                getattr(self, "_skip_request_seq", 0) or 0
            ) + 1
            request_id = self._skip_request_seq
            watch_playback = self._clear_user_pause_for_skip()
            self._start_puppy_thinking_animation(reason="track")
            # Detect the new track's metadata quickly so the headset-swap
            # completion clip follows the music instead of waiting for the
            # next 4s steady-state poll.
            self._schedule_fast_track_refresh()
            if not watch_playback:
                self._schedule_skip_completion_watchdog(request_id)
            threading.Thread(
                target=self._media_next,
                args=(watch_playback, request_id),
                daemon=True,
            ).start()

    def _media_next(self, watch_playback=False, request_id=None):
        try:
            if hasattr(self.spotify, "media_next"):
                self.spotify.media_next()
            elif hasattr(self.spotify, "next_track"):
                self.spotify.next_track()
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Next track error: {e}"))
            return
        if watch_playback:
            self._confirm_skip_playback(request_id)

    def _prev(self):
        if self.spotify:
            self._skip_request_seq = int(
                getattr(self, "_skip_request_seq", 0) or 0
            ) + 1
            request_id = self._skip_request_seq
            watch_playback = self._clear_user_pause_for_skip()
            self._start_puppy_thinking_animation(reason="track")
            self._schedule_fast_track_refresh()
            if not watch_playback:
                self._schedule_skip_completion_watchdog(request_id)
            threading.Thread(
                target=self._media_prev,
                args=(watch_playback, request_id),
                daemon=True,
            ).start()

    def _media_prev(self, watch_playback=False, request_id=None):
        try:
            self.spotify.media_prev()
        except Exception as ex:
            self.root.after(0, lambda e=ex: self._log(f"Previous track error: {e}"))
            return
        if watch_playback:
            self._confirm_skip_playback(request_id)

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

    def _schedule_fast_track_refresh(self):
        """Poll now-playing a few times right after a playlist starts.

        The steady-state poll is every 4s.  A new web-player track can appear
        several seconds after the playlist starts, so one slow poll used to
        leave the old song in the deck until the next tick.  These short
        follow-ups catch the new metadata as soon as Spotify publishes it.
        """
        if getattr(self, "_closing", False):
            return
        jobs = getattr(self, "_track_refresh_jobs", None)
        if jobs is None:
            jobs = []
            self._track_refresh_jobs = jobs
        for job in jobs:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        jobs.clear()
        for delay in (250, 800, 1600, 3000, 5500):
            try:
                jobs.append(self.root.after(delay, self._fetch_track_async))
            except Exception:
                pass

    def _fetch_track_async(self):
        if self.spotify:
            threading.Thread(target=self._fetch_track, daemon=True).start()

    def _fetch_track(self):
        if not self.spotify:
            return
        if getattr(self, "_track_fetch_busy", False):
            return
        self._track_fetch_busy = True
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
        finally:
            self._track_fetch_busy = False

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
        previous_np_key = getattr(self, "_last_np_key", None)
        fresh_start = self._fresh_playback_grace()
        track_changed = False
        try:
            key = (
                str(t.get("uri") or ""),
                str(t.get("name") or "").strip(),
                str(t.get("artist") or "").strip(),
            )
            track_changed = (
                self._last_np_key is not None and key != self._last_np_key
            )
            if track_changed:
                now = time.time()
                # A playlist switch/long-press already owns the change clip.
                # Suppress the title-poll echo so one user action does not
                # produce a second, unrelated animation a few seconds later.
                pending_request = (
                    getattr(self, "_pending_play_request", None) is not None
                )
                switch_loading = (
                    bool(getattr(self, "_playlist_switch_pause", False))
                    and getattr(self, "_puppy_thinking_reason", "") == "playlist"
                )
                if self._puppy_thinking_active():
                    # A next/previous click owns the transition.  Finish the
                    # thinking loop as soon as the new track is actually
                    # playing, then play one completion clip.  The cooldown
                    # below only exists to suppress *automatic* track-change
                    # reactions; it must not leave an explicit skip thinking.
                    if not (pending_request or switch_loading):
                        self._finish_puppy_thinking(play_change=True)
                else:
                    quiet_change = (
                        now < float(getattr(self, "_track_change_anim_quiet_until", 0.0) or 0.0)
                        or pending_request
                        or getattr(self, "_playlist_switch_pause", False)
                    )
                    if not quiet_change:
                        # Ordinary track changes should not play the
                        # headset-swap clip.  Keep only the tiny in-place
                        # head-turn reaction.
                        self._puppy_reaction_until = now + 1.15
            self._last_np_key = key
        except Exception:
            pass
        if not hasattr(self, "track_lbl"):
            return
        playlist_changed = False
        playlist_uri = t.get("playlist_uri") or t.get("context_uri")
        if (
            playlist_uri
            and str(playlist_uri).startswith("spotify:playlist:")
            and playlist_uri != self._current_playlist_uri
        ):
            playlist_changed = True
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
                    text=self._current_playlist_name
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

        # Right after a switch, Spotify's mediaSession can still expose the
        # previous song for a moment.  Do not put that stale title back over
        # the new playlist name; wait for the first genuinely different track.
        stale_start_song = False
        if fresh_start and previous_np_key:
            prev_name = str(previous_np_key[1] or "").strip().lower()
            if prev_name and song_title.lower() == prev_name:
                stale_start_song = True
        if not stale_start_song:
            self.track_lbl.configure(text=song_title)

        # Keep the deck's playlist line in sync even when the track poller is
        # recovering from a desktop/web hand-off (previously it stayed "—").
        if playlist_title and playlist_title.lower() != "nothing playing":
            try:
                self.playlist_display_lbl.configure(
                    text=playlist_title
                )
            except Exception:
                pass

        artist = str(t.get("artist") or "").strip()
        if not artist or artist.lower() in ("web player", "spotify"):
            artist = "Spotify web player"
        if not stale_start_song:
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
        effective_is_playing = (
            (not intentional)
            and (t_is_playing or spotify_sound or fresh_start)
        )
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

        # The poller is the source of truth for the progress rail; the master
        # clock extrapolates between polls so the tape keeps moving smoothly.
        try:
            progress_ms = float(t.get("progress_ms") or 0.0)
            duration_ms = float(t.get("duration_ms") or 0.0)
        except (TypeError, ValueError):
            progress_ms, duration_ms = 0.0, 0.0
        if duration_ms > 0:
            self._track_progress_base = (
                progress_ms / 1000.0,
                duration_ms / 1000.0,
                time.time(),
                bool(effective_is_playing),
            )
        else:
            self._track_progress_base = None
        self._update_deck_progress(time.time())

        if (
            getattr(self, "_current_page", "") == "main"
            and getattr(self, "_toast", None) is not None
        ):
            raw_title = str(t.get("name") or "").strip()
            silent = (
                not raw_title
                or str(t.get("uri") or "") == getattr(self, "SILENT_TRACK_URI", "")
                or raw_title.lower() in ("spotify", "gdi+ window", "spotify.exe")
            )
            if playlist_changed and playlist_title:
                self._toast.show("PLAYLIST", playlist_title, 2800)
            elif track_changed and not silent and not stale_start_song:
                self._toast.show(
                    "NOW PLAYING", f"{raw_title} \u2014 {artist}", 2800,
                )

    def _update_deck_progress(self, now=None):
        """Advance the segmented rail from the last poll snapshot."""
        bar = getattr(self, "progress_bar", None)
        if bar is None:
            return
        now = time.time() if now is None else now
        base = getattr(self, "_track_progress_base", None)
        if not base:
            has_track = False
            try:
                label_text = str(self.track_lbl.cget("text") or "").strip().lower()
                has_track = label_text not in (
                    "", "nothing playing", "spotify", "gdi+ window", "spotify.exe",
                )
            except Exception:
                has_track = False
            playing = bool(
                has_track
                and (
                    getattr(self, "_is_playing", False)
                    or getattr(self, "_spotify_audio_active", False)
                )
            )
            try:
                bar.set_status("LIVE" if playing else "STANDBY", active=playing)
            except Exception:
                bar.set_progress(0.0)
            key = ("status", playing)
            if key != getattr(self, "_progress_label_key", None):
                for label in (
                    getattr(self, "elapsed_lbl", None),
                    getattr(self, "duration_lbl", None),
                ):
                    if label is not None:
                        try:
                            label.configure(text="")
                        except Exception:
                            pass
                self._progress_label_key = key
            return
        try:
            position, duration, base_ts, playing = base
            position = float(position)
            duration = float(duration)
            if duration <= 0:
                raise ValueError
            if playing:
                position += max(0.0, now - float(base_ts))
            position = max(0.0, min(duration, position))
        except Exception:
            bar.set_progress(0.0)
            return
        bar.set_progress(position / duration)
        key = (int(position), int(duration))
        if key != getattr(self, "_progress_label_key", None):
            try:
                self.elapsed_lbl.configure(text=format_clock(position))
                self.duration_lbl.configure(text=format_clock(duration))
            except Exception:
                pass
            self._progress_label_key = key

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

    def _fresh_playback_grace(self, now=None) -> bool:
        """True while a just-started playlist has not produced audio yet.

        Metadata and loopback audio can lag behind the play command by several
        seconds.  This is not a pause, so silence in that window must not clear
        _is_playing or freeze the mascot.
        """
        if not getattr(self, "_spotify_started_by_us", False):
            return False
        if getattr(self, "_playlist_audio_armed", False):
            return False
        started = float(getattr(self, "_playback_started_ts", 0.0) or 0.0)
        if started <= 0.0:
            return False
        now = time.time() if now is None else now
        return (now - started) < FRESH_PLAYBACK_GRACE_SEC

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
        # A freshly started playlist can be silent while the web player loads
        # the first track. Keep the play state so the mascot starts bobbing as
        # soon as the music starts instead of waiting for the audio meter.
        if self._fresh_playback_grace(now):
            self._music_missing_since = 0.0
            self._playlist_end_pending = False
            if not getattr(self, "_is_playing", False):
                self._is_playing = True
            return
        self._is_playing = False
        self._track_progress_base = None
        self._update_deck_progress()
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
            self._start_puppy_thinking_animation(reason="playlist")

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
                        pause_first=True,
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
            self._start_puppy_thinking_animation(reason="playlist")

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
                    pause_first=True,
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

    # ── DESKTOP PUPPY CALLBACKS ───────────────────────────────────────────────

    def _puppy_overlay_playing(self):
        try:
            return bool(self._spotify_is_playing_for_toggle())
        except Exception:
            try:
                return not self._intentional_pause_active()
            except Exception:
                return False

    def _puppy_overlay_toggle(self):
        return self._play_pause_toggle()

    def _puppy_overlay_try_another(self):
        self._try_another_playlist()

    # ── OVERLAY CONTROL CALLBACKS ─────────────────────────────────────────────

    def _overlay_play(self):
        """Play button from control overlay."""
        accepted = bool(self._play())
        if accepted and self._control_overlay:
            self._control_overlay.update_status(playing=True)
        return accepted

    def _overlay_pause(self):
        """Pause button from control overlay."""
        accepted = bool(self._pause())
        if accepted and self._control_overlay:
            self._control_overlay.update_status(playing=False)
        return accepted

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
            guard = getattr(self, "_spotify_window_guard", None)
            if guard is not None:
                guard.shutdown()
        except Exception:
            pass
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
        for job in list(getattr(self, "_track_refresh_jobs", []) or []):
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._track_refresh_jobs = []
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
