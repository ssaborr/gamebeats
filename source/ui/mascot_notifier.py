import json
import os
import sys
from pathlib import Path
import tkinter as tk
import customtkinter as ctk


try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False


IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    _user32 = ctypes.windll.user32

    GWL_EXSTYLE = -20
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOOLWINDOW = 0x00000080
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    HWND_TOPMOST = -1


from ui import theme as T

BG = T.BG
SURFACE = T.SURFACE
ACCENT = T.ACCENT
ACCENT2 = T.ACCENT2
TEXT = T.TEXT
TEXT_SEC = T.TEXT_MUTED
TRANSPARENT_KEY = "#010203"

NOTIFIER_CARD_BG = "#1a1628"
NOTIFIER_CARD_BORDER = "#3d3560"
NOTIFIER_TEXT = "#ffffff"
NOTIFIER_TEXT_SUB = "#d8d4ea"
NOTIFIER_TEXT_MUTED = "#a9a3bf"
NOTIFIER_BTN_HOVER = "#2d2648"

PUPPY_SINGING_FRAMES = ("puppy_sing_open.png", "puppy_sing_closed.png")
PUPPY_IDLE_FRAME = "puppy_idle.png"
PUPPY_ANIMATION_INTERVAL = 420


def _apply_noactivate(hwnd: int):
    if not IS_WINDOWS:
        return
    try:
        old = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            old | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )
        _user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except Exception:
        pass


def _asset_path(filename: str) -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", "")
        if bundle_dir:
            candidates.append(Path(bundle_dir) / "assets" / "puppy" / filename)
        candidates.append(Path(sys.executable).resolve().parent / "assets" / "puppy" / filename)

    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "assets" / "puppy" / filename)
    candidates.append(Path.cwd() / "assets" / "puppy" / filename)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _alpha_bbox(images, threshold: int = 5, padding: int = 16):
    boxes = []
    for img in images:
        if img.mode != "RGBA":
            continue
        alpha = img.getchannel("A").point(lambda px: 255 if px > threshold else 0)
        box = alpha.getbbox()
        if box:
            boxes.append(box)
    if not boxes:
        return None

    width, height = images[0].size
    left = max(0, min(box[0] for box in boxes) - padding)
    top = max(0, min(box[1] for box in boxes) - padding)
    right = min(width, max(box[2] for box in boxes) + padding)
    bottom = min(height, max(box[3] for box in boxes) + padding)
    return left, top, right, bottom


def _load_puppy_photos(filenames, max_size):
    if not HAS_PIL:
        return []

    images = []
    for filename in filenames:
        path = _asset_path(filename)
        if not path.exists():
            return []
        images.append(Image.open(path).convert("RGBA"))

    box = _alpha_bbox(images)
    photos = []
    for img in images:
        if box:
            img = img.crop(box)
        img.thumbnail(max_size, Image.LANCZOS)
        photos.append(ImageTk.PhotoImage(img))
    return photos


def _puppy_pos_file() -> str:
    """Path to the tiny JSON file that remembers the puppy's position."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[2]
    return str(base / "puppy_position.json")


class PuppySingingOverlay:
    def __init__(self, root, *, corner="bottom-right"):
        self._root = root
        self._corner = corner
        self._win = None
        self._label = None
        self._photos = []
        self._idx = 0
        self._after = None
        self._visible = False
        self._drag_x = 0
        self._drag_y = 0
        self._custom_pos = self._load_pos()   # restore last dragged position
        root.after(0, self._build)

    def _load_pos(self):
        try:
            with open(_puppy_pos_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            x, y = int(data["x"]), int(data["y"])
            return (x, y)
        except Exception:
            return None

    def _save_pos(self, x: int, y: int):
        try:
            with open(_puppy_pos_file(), "w", encoding="utf-8") as f:
                json.dump({"x": x, "y": y}, f)
        except Exception:
            pass

    def _build(self):
        if self._win is not None:
            return

        win = tk.Toplevel(self._root)
        self._win = win
        win.overrideredirect(True)
        win.configure(bg=TRANSPARENT_KEY)
        win.attributes("-alpha", 0.55)
        win.attributes("-topmost", True)
        try:
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except Exception:
            pass
        win.withdraw()

        self._photos = _load_puppy_photos(PUPPY_SINGING_FRAMES, (170, 170))
        if self._photos:
            self._label = tk.Label(
                win,
                image=self._photos[0],
                bg=TRANSPARENT_KEY,
                bd=0,
                highlightthickness=0,
                cursor="fleur",
            )
        else:
            self._label = tk.Label(
                win,
                text="♪",
                font=("Segoe UI", 40, "bold"),
                fg=ACCENT,
                bg=TRANSPARENT_KEY,
                bd=0,
                highlightthickness=0,
                cursor="fleur",
            )
        self._label.pack()

        # Drag bindings
        self._label.bind("<ButtonPress-1>", self._on_drag_start)
        self._label.bind("<B1-Motion>", self._on_drag_move)

        win.after(80, self._noactivate_safe)

    def _place(self):
        if self._win is None:
            return
        # If user dragged, use their position
        if self._custom_pos is not None:
            x, y = self._custom_pos
            self._win.geometry(f"+{x}+{y}")
            return
        win = self._win
        margin = 24
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        positions = {
            "bottom-right": (sw - w - margin, sh - h - margin - 40),
            "bottom-left": (margin, sh - h - margin - 40),
            "top-right": (sw - w - margin, margin),
            "top-left": (margin, margin),
        }
        x, y = positions.get(self._corner, positions["bottom-right"])
        win.geometry(f"+{x}+{y}")

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_move(self, event):
        if self._win is None:
            return
        x = self._win.winfo_x() + (event.x - self._drag_x)
        y = self._win.winfo_y() + (event.y - self._drag_y)
        self._win.geometry(f"+{x}+{y}")
        self._custom_pos = (x, y)
        self._save_pos(x, y)

    def _noactivate_safe(self):
        if self._win is None:
            return
        try:
            _apply_noactivate(self._win.winfo_id())
        except Exception:
            pass

    def show(self):
        if self._visible:
            return
        if self._win is None:
            self._build()
        if self._win is None:
            return
        self._visible = True
        try:
            self._place()
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._noactivate_safe()
        except Exception:
            pass
        self._animate()

    def hide(self):
        self._visible = False
        if self._after is not None and self._win is not None:
            try:
                self._win.after_cancel(self._after)
            except Exception:
                pass
        self._after = None
        if self._win is not None:
            try:
                self._win.withdraw()
            except Exception:
                pass

    def _animate(self):
        if not self._visible or self._win is None or self._label is None:
            return
        if self._photos:
            self._idx = (self._idx + 1) % len(self._photos)
            try:
                self._label.configure(image=self._photos[self._idx])
            except Exception:
                return
        try:
            self._after = self._win.after(PUPPY_ANIMATION_INTERVAL, self._animate)
        except Exception:
            pass

    def close(self):
        self.hide()
        win = self._win
        self._win = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass


class MascotNotifier:
    def __init__(
        self,
        root,
        on_play_next,
        on_play_another=None,
        *,
        on_dismiss=None,
        on_quit=None,
        playlist_name="",
        auto_play_seconds=0,
        corner="bottom-right",
    ):
        self._root = root
        self._on_play_next = on_play_next
        self._on_play_another = on_play_another
        self._on_dismiss = on_dismiss
        self._on_quit = on_quit
        self._playlist_name = playlist_name
        self._auto_play_sec = auto_play_seconds
        self._corner = corner

        self._closed = False
        self._win = None
        self._timer_lbl = None
        self._countdown = auto_play_seconds
        self._after_tick = None
        self._after_slide = None
        self._after_loading = None
        self._puppy_photo = None
        self._play_next_btn = None
        self._play_next_pending = False
        self._loading_phase = 0

        root.after(0, self._build)

    def _build(self):
        if self._closed:
            return

        win = tk.Toplevel(self._root)
        self._win = win
        win.overrideredirect(True)
        win.configure(bg=TRANSPARENT_KEY)
        win.attributes("-alpha", 0.92)
        try:
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except Exception:
            pass
        win.withdraw()

        self._populate(win)
        win.after(60, self._finalize)

    def _finalize(self):
        if self._closed or self._win is None:
            return

        win = self._win
        try:
            win.update_idletasks()
            x, y = self._target_position(win)
            start_y = min(win.winfo_screenheight() - win.winfo_reqheight(), y + 70)
            win.geometry(f"+{x}+{start_y}")
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
            self._slide_in(x, y, start_y)
            win.after(50, self._lift_safe)
            win.after(80, self._noactivate_safe)
        except Exception:
            pass

        if self._auto_play_sec > 0:
            self._tick_countdown()

    def _populate(self, win):
        outer = tk.Frame(win, bg=TRANSPARENT_KEY)
        outer.pack(fill="both", expand=True)

        card = ctk.CTkFrame(
            outer,
            fg_color=NOTIFIER_CARD_BG,
            corner_radius=16,
            border_width=1,
            border_color=NOTIFIER_CARD_BORDER,
        )
        card.pack(padx=2, pady=2)

        photos = _load_puppy_photos((PUPPY_IDLE_FRAME,), (96, 96))
        if photos:
            self._puppy_photo = photos[0]
            tk.Label(
                card,
                image=self._puppy_photo,
                bg=NOTIFIER_CARD_BG,
                bd=0,
                highlightthickness=0,
            ).pack(pady=(14, 4))
        else:
            ctk.CTkLabel(
                card,
                text="♪",
                font=ctk.CTkFont(family="Segoe UI", size=30, weight="bold"),
                fg_color="transparent",
                text_color=NOTIFIER_TEXT,
            ).pack(pady=(14, 4))

        ctk.CTkLabel(
            card,
            text="Playlist finished",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="transparent",
            text_color=NOTIFIER_TEXT,
        ).pack(padx=18)

        name = (self._playlist_name or "your playlist")[:28]
        ctk.CTkLabel(
            card,
            text=name,
            font=ctk.CTkFont(family="Segoe UI", size=9),
            fg_color="transparent",
            text_color=NOTIFIER_TEXT_SUB,
        ).pack(padx=18, pady=(2, 10))

        self._timer_lbl = ctk.CTkLabel(
            card,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=8),
            fg_color="transparent",
            text_color=NOTIFIER_TEXT_MUTED,
        )
        self._timer_lbl.pack()

        btn_row = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        btn_row.pack(padx=18, pady=(10, 6), fill="x")

        self._play_next_btn = ctk.CTkButton(
            btn_row,
            text="▶ Play Next",
            fg_color=ACCENT,
            text_color=NOTIFIER_TEXT,
            hover_color=ACCENT2,
            corner_radius=8,
            command=self._on_click_play_next,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        )
        self._play_next_btn.pack(side=tk.LEFT, fill="x", expand=True)

        ctk.CTkButton(
            card,
            text="dismiss",
            fg_color="transparent",
            text_color=NOTIFIER_TEXT_MUTED,
            hover_color=NOTIFIER_BTN_HOVER,
            corner_radius=8,
            command=self._on_click_dismiss,
            font=ctk.CTkFont(family="Segoe UI", size=10),
        ).pack(pady=(0, 12))


    def _target_position(self, win):
        margin = 24
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        positions = {
            "bottom-right": (sw - w - margin, sh - h - margin - 40),
            "bottom-left": (margin, sh - h - margin - 40),
            "top-right": (sw - w - margin, margin),
            "top-left": (margin, margin),
        }
        x, y = positions.get(self._corner, positions["bottom-right"])
        return x, y

    def _place(self, win):
        x, y = self._target_position(win)
        win.geometry(f"+{x}+{y}")

    def _slide_in(self, x, target_y, current_y):
        if self._closed or self._win is None:
            return
        if current_y <= target_y:
            try:
                self._win.geometry(f"+{x}+{target_y}")
            except Exception:
                pass
            self._after_slide = None
            return
        next_y = max(target_y, current_y - 12)
        try:
            self._win.geometry(f"+{x}+{next_y}")
            self._after_slide = self._win.after(12, self._slide_in, x, target_y, next_y)
        except Exception:
            self._after_slide = None

    def _lift_safe(self):
        if self._closed or self._win is None:
            return
        try:
            self._win.lift()
            self._win.attributes("-topmost", True)
        except Exception:
            pass

    def _noactivate_safe(self):
        if self._closed or self._win is None:
            return
        try:
            _apply_noactivate(self._win.winfo_id())
            self._win.lift()
            self._win.attributes("-topmost", True)
        except Exception:
            pass

    def _tick_countdown(self):
        if self._closed or self._win is None:
            return
        if self._countdown <= 0:
            self._do_play_next()
            return
        try:
            if self._timer_lbl:
                self._timer_lbl.configure(text=f"Auto-plays in {self._countdown}s")
        except Exception:
            pass
        self._countdown -= 1
        try:
            self._after_tick = self._win.after(1000, self._tick_countdown)
        except Exception:
            pass

    def _on_click_play_next(self):
        self._do_play_next()

    def _set_play_next_loading(self):
        if self._play_next_btn is None:
            return
        try:
            self._play_next_btn.configure(
                text=".",
                state="disabled",
            )
            if self._timer_lbl:
                self._timer_lbl.configure(text="")
        except Exception:
            pass
        self._loading_phase = 0
        self._animate_play_next_loading()

    def _animate_play_next_loading(self):
        if (
            self._closed
            or not self._play_next_pending
            or self._win is None
            or self._play_next_btn is None
        ):
            self._after_loading = None
            return
        dots = "." * ((self._loading_phase % 3) + 1)
        self._loading_phase += 1
        try:
            self._play_next_btn.configure(
                text=dots,
                state="disabled",
            )
            self._after_loading = self._win.after(340, self._animate_play_next_loading)
        except Exception:
            self._after_loading = None

    def _on_click_play_another(self):
        if self._closed:
            return
        self._closed = True
        self._destroy_win()
        if callable(self._on_play_another):
            try:
                self._on_play_another()
            except Exception:
                pass

    def _on_click_dismiss(self):
        if self._closed:
            return
        self._closed = True
        self._destroy_win()
        if callable(self._on_quit):
            try:
                self._on_quit()
            except Exception:
                pass
        if callable(self._on_dismiss):
            try:
                self._on_dismiss()
            except Exception:
                pass

    def _do_play_next(self):
        if self._closed or self._play_next_pending:
            return
        self._play_next_pending = True
        if self._after_tick is not None and self._win is not None:
            try:
                self._win.after_cancel(self._after_tick)
            except Exception:
                pass
        self._after_tick = None
        self._set_play_next_loading()
        if callable(self._on_play_next):
            try:
                self._on_play_next()
            except Exception:
                pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._destroy_win()
        if callable(self._on_dismiss):
            try:
                self._on_dismiss()
            except Exception:
                pass

    def _destroy_win(self):
        if self._after_tick is not None:
            try:
                if self._win:
                    self._win.after_cancel(self._after_tick)
            except Exception:
                pass
            self._after_tick = None

        if self._after_slide is not None:
            try:
                if self._win:
                    self._win.after_cancel(self._after_slide)
            except Exception:
                pass
            self._after_slide = None

        if self._after_loading is not None:
            try:
                if self._win:
                    self._win.after_cancel(self._after_loading)
            except Exception:
                pass
            self._after_loading = None
        self._play_next_pending = False

        win = self._win
        self._win = None
        if win is not None:
            try:
                win.withdraw()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass
