
"""
games_page.py — "My Games" tab for GameBeats.

User adds games manually by picking an .exe file.
"""

import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
import threading
import os
import re
import sys
import ctypes

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

from core.detector import (
    MOOD_TO_PLAYLIST, MOODS,
    load_games, save_games, add_game, remove_game,
)
from core.game_tags import fetch_game_info, fallback_game_info
from ui import theme as T

# ── Palette (from theme) ─────────────────────────────────────────────────────


def _puppy_logo_path() -> str:
    """Find the puppy logo.png across common install / dev layouts."""
    # games_page.py lives at source/ui/ — go up 3 levels to reach the project root
    ui_dir     = os.path.dirname(os.path.abspath(__file__))   # source/ui/
    source_dir = os.path.dirname(ui_dir)                       # source/
    root_dir   = os.path.dirname(source_dir)                   # project root
    candidates = [
        os.path.join(root_dir,      "puppies", "puppy logo.png"),
        os.path.join(os.getcwd(),   "puppies", "puppy logo.png"),
        os.path.join(source_dir,    "puppies", "puppy logo.png"),
    ]
    if getattr(sys, "frozen", False):
        exe_dir    = os.path.dirname(sys.executable)
        bundle_dir = getattr(sys, "_MEIPASS", "")
        candidates += [
            os.path.join(bundle_dir, "puppies", "puppy logo.png"),
            os.path.join(exe_dir,    "puppies", "puppy logo.png"),
        ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return ""


def _load_window_icon():
    """Load the puppy logo as a Tk-compatible PhotoImage for window icons."""
    path = _puppy_logo_path()
    if not path:
        return None
    try:
        if HAS_PIL:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((64, 64), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        return tk.PhotoImage(file=path)
    except Exception:
        return None


# ── Palette (from theme) ─────────────────────────────────────────────────────
BG     = T.BG
SURF   = T.SURF
SURF2  = T.SURF2
SURF3  = T.SURF3
SURF4  = T.SURF4
ACCENT = T.ACCENT
ACCENT2 = T.ACCENT2
TEXT   = T.TEXT
TEXT2  = T.TEXT2
TEXT3  = T.TEXT3
RED    = T.RED
AMBER  = T.AMBER
BORDER = T.BORDER
GREEN  = T.GREEN
RADIUS_LG = T.RADIUS_LG
RADIUS_MD = T.RADIUS_MD
RADIUS_SM = T.RADIUS_SM
ROW_H  = 88
BANNER_W = 152
BANNER_H = 70

_PIL_ICON_CACHE = {}


def _hex_rgb(hex_color):
    try:
        return (
            int(hex_color[1:3], 16),
            int(hex_color[3:5], 16),
            int(hex_color[5:7], 16),
        )
    except Exception:
        return (24, 24, 27)


def _extract_exe_icon_image(exe_path, size=52):
    if not HAS_PIL or not exe_path or not os.path.exists(exe_path):
        return None
    key = (os.path.abspath(exe_path), int(size))
    cached = _PIL_ICON_CACHE.get(key)
    if cached is not None:
        return cached.copy()

    icons = []
    try:
        import win32api
        import win32con
        import win32gui
        import win32ui

        large, small = win32gui.ExtractIconEx(exe_path, 0)
        icons = list(large or []) + list(small or [])
        if not icons:
            return None
        hicon = icons[0]

        hdc_screen = win32gui.GetDC(0)
        screen_dc = win32ui.CreateDCFromHandle(hdc_screen)
        mem_dc = screen_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(screen_dc, size, size)
        old_bitmap = mem_dc.SelectObject(bitmap)

        brush = win32gui.CreateSolidBrush(win32api.RGB(*_hex_rgb(SURF2)))
        try:
            win32gui.FillRect(mem_dc.GetSafeHdc(), (0, 0, size, size), brush)
        finally:
            win32gui.DeleteObject(brush)

        win32gui.DrawIconEx(
            mem_dc.GetSafeHdc(), 0, 0, hicon, size, size,
            0, None, win32con.DI_NORMAL,
        )
        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGBA",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits, "raw", "BGRA", 0, 1,
        ).copy()

        mem_dc.SelectObject(old_bitmap)
        win32gui.DeleteObject(bitmap.GetHandle())
        mem_dc.DeleteDC()
        screen_dc.DeleteDC()
        win32gui.ReleaseDC(0, hdc_screen)

        _PIL_ICON_CACHE[key] = image
        return image.copy()
    except Exception:
        return None
    finally:
        try:
            import win32gui
            for icon in icons:
                try:
                    win32gui.DestroyIcon(icon)
                except Exception:
                    pass
        except Exception:
            pass


def _lighten(h, a=22):
    try:
        return "#{:02x}{:02x}{:02x}".format(
            min(255, int(h[1:3],16)+a), min(255, int(h[3:5],16)+a),
            min(255, int(h[5:7],16)+a))
    except Exception:
        return h


def _mood_tint(hex_color, blend=0.35):
    """Tk-safe highlight bg for selected mood."""
    try:
        r, g, b = (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
                   int(hex_color[5:7], 16))
        br, bg_, bb = (int(SURF3[1:3], 16), int(SURF3[3:5], 16), int(SURF3[5:7], 16))
        t = blend
        return "#{:02x}{:02x}{:02x}".format(
            int(r * (1 - t) + br * t),
            int(g * (1 - t) + bg_ * t),
            int(b * (1 - t) + bb * t),
        )
    except Exception:
        return SURF3


def _add_rounded_corners(im, radius=10):
    if not HAS_PIL:
        return im
    from PIL import Image, ImageDraw
    mask = Image.new("L", im.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), im.size], radius, fill=255)
    result = im.copy()
    result.putalpha(mask)
    return result


def get_game_square_icon_image(info, size=44):
    """Square icon for the player tab (Steam banner, exe icon, or mood gradient)."""
    if not info:
        return None
    exe_path = info.get("exe_path", "")
    mood = info.get("mood", "chill")
    color = MOOD_TO_PLAYLIST.get(mood, {}).get("color", ACCENT)
    game_name = info.get("name", "")
    app_id = info.get("app_id", "")
    px = int(size)

    if HAS_PIL:
        from PIL import Image

        thumb = get_game_thumbnail_image(
            game_name, app_id, exe_path, color,
            size=(max(px * 2, 80), max(px, 48)),
        )
        if thumb:
            w, h = thumb.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            square = thumb.crop((left, top, left + side, top + side))
            if square.size != (px, px):
                square = square.resize((px, px), Image.Resampling.LANCZOS)
            return square

    if exe_path and os.path.exists(exe_path):
        img = _extract_exe_icon_image(exe_path, px)
        if img:
            return img
    return _generate_gradient_fallback(color, size=(px, px), radius=8)


def get_game_thumbnail_image(game_name, app_id="", exe_path="", color=ACCENT, size=(120, 56)):
    """Landscape banner / icon for the games list."""
    if not HAS_PIL:
        return None
    from PIL import Image, ImageDraw

    banner_w, banner_h = size
    banner_dir = os.path.join("data", "banners")
    os.makedirs(banner_dir, exist_ok=True)

    if not app_id and game_name:
        try:
            from core.game_tags import _steam_search
            app_id = _steam_search(game_name)
            if app_id:
                try:
                    games = load_games()
                    for k in list(games.keys()):
                        if k.lower() == game_name.lower() + ".exe" or k.lower() == game_name.lower():
                            games[k]["app_id"] = app_id
                            save_games(games)
                            break
                except Exception:
                    pass
        except Exception:
            pass

    if app_id:
        cache_path = os.path.join(banner_dir, f"{app_id}.jpg")
        if os.path.exists(cache_path):
            try:
                img = Image.open(cache_path).convert("RGBA")
                return _add_rounded_corners(
                    img.resize((banner_w, banner_h), Image.Resampling.LANCZOS), radius=8)
            except Exception:
                pass
        else:
            import requests
            url = f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    with open(cache_path, "wb") as f:
                        f.write(r.content)
                    img = Image.open(cache_path).convert("RGBA")
                    return _add_rounded_corners(
                        img.resize((banner_w, banner_h), Image.Resampling.LANCZOS), radius=8)
            except Exception:
                pass

    gradient_im = _generate_gradient_fallback(color, size=(banner_w, banner_h), radius=8)
    if not gradient_im:
        return None

    if exe_path and os.path.exists(exe_path):
        try:
            raw_img = _extract_exe_icon_image(exe_path, 48)
            if raw_img:
                cx, cy = banner_w // 2, banner_h // 2
                circle_im = Image.new("RGBA", (banner_w, banner_h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(circle_im)
                draw.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(255, 255, 255, 45))
                gradient_im = Image.alpha_composite(gradient_im, circle_im)
                icon_resized = raw_img.resize((30, 30), Image.Resampling.LANCZOS).convert("RGBA")
                gradient_im.paste(icon_resized, (cx - 15, cy - 15), icon_resized)
                return gradient_im
        except Exception:
            pass

    return gradient_im


def _generate_gradient_fallback(color_hex, size=(BANNER_W, BANNER_H), radius=8):
    if not HAS_PIL:
        return None
    from PIL import Image, ImageDraw
    r, g, b = _hex_rgb(color_hex)
    im = Image.new("RGBA", size)
    draw = ImageDraw.Draw(im)
    
    target_r, target_g, target_b = (30, 27, 75)
    for x in range(size[0]):
        t = x / size[0]
        cur_r = int(r * (1 - t) + target_r * t)
        cur_g = int(g * (1 - t) + target_g * t)
        cur_b = int(b * (1 - t) + target_b * t)
        draw.line([(x, 0), (x, size[1])], fill=(cur_r, cur_g, cur_b, 255))
        
    return _add_rounded_corners(im, radius)


class AddGameDialog(ctk.CTkToplevel):
    def __init__(self, parent, proc_name, display_name, exe_path="", on_save=None):
        super().__init__(parent)
        self.title("Add Game")
        self.configure(fg_color=BG)
        self.resizable(True, True)
        self.grab_set()
        self.on_save   = on_save
        self._proc     = proc_name
        self._exe      = exe_path
        self._fetched_tags  = []
        self._fetched_query = ""
        self._fetched_app_id = ""

        w = 900
        # Query the Windows workarea (screen minus taskbar) via ctypes
        try:
            import ctypes.wintypes
            work_rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_rect), 0)  # SPI_GETWORKAREA
            wa_top    = work_rect.top
            wa_bottom = work_rect.bottom
            workarea_h = wa_bottom - wa_top
        except Exception:
            wa_top = 0
            wa_bottom = parent.winfo_screenheight()
            workarea_h = wa_bottom
        # Keep dialog shorter than the workarea; leave ~80px for title bar + breathing room
        h = min(750, workarea_h - 80)
        self.minsize(w, min(550, h))
        px = parent.winfo_rootx() + max(0, (parent.winfo_width()  - w) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 2)
        # Clamp vertically so the window never starts above wa_top or goes below wa_bottom
        py = max(wa_top, min(py, wa_bottom - h - 40))
        self.geometry(f"{w}x{h}+{px}+{py}")

        # Set window icon to the app's puppy logo
        _icon = _load_window_icon()
        if _icon:
            self._icon_ref = _icon  # keep a reference so GC doesn't collect it
            self.after(50,  lambda: self.iconphoto(False, _icon))
            self.after(200, lambda: self.iconphoto(False, _icon))

        # Bottom buttons first so they always stay visible
        brow = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        brow.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 16))
        inner = ctk.CTkFrame(brow, fg_color=BG, corner_radius=0)
        inner.pack()
        ctk.CTkButton(inner, text="Cancel", command=self.destroy,
                      fg_color=SURF2, text_color=TEXT2, hover_color=SURF3,
                      corner_radius=10, width=140, height=48,
                      font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=6)
        ctk.CTkButton(inner, text="Add Game ✓", command=self._save,
                      fg_color=ACCENT, text_color="#ffffff", hover_color=_lighten(ACCENT),
                      corner_radius=10, width=160, height=48,
                      font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=6)

        self._build(proc_name, display_name)
        self._tag_fetching = True
        self.after(50, lambda: self._apply_tags(fallback_game_info(display_name)))
        threading.Thread(target=self._fetch_tags_worker,
                         args=(display_name,), daemon=True).start()

    def _build(self, proc_name, display_name):
        ctk.CTkLabel(self, text="🎮  Add Game", fg_color="transparent",
                     text_color=TEXT, font=("Segoe UI", 14, "bold")).pack(pady=(16, 2))
        ctk.CTkLabel(self, text="Name your game and choose a music mood.",
                     fg_color="transparent", text_color=TEXT2,
                     font=("Segoe UI", 10)).pack()

        # Scrollable form
        outer = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        scroll_frame = ctk.CTkScrollableFrame(outer, fg_color=BG,
                                               scrollbar_button_color="#cbd5e1",
                                               scrollbar_button_hover_color="#94a3b8")
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        pad = ctk.CTkFrame(scroll_frame, fg_color=BG, corner_radius=0)
        pad.pack(fill=tk.X, padx=20)

        ctk.CTkLabel(pad, text="Game name", fg_color="transparent",
                     text_color=TEXT2, font=("Segoe UI", 10)).pack(anchor=tk.W)
        self._name_var = tk.StringVar(value=display_name)
        self._name_entry = ctk.CTkEntry(pad, textvariable=self._name_var,
                                         fg_color=SURF2, border_color=BORDER,
                                         text_color=TEXT, corner_radius=8,
                                         font=("Segoe UI", 11), height=42)
        self._name_entry.pack(fill=tk.X, pady=(3, 10))

        ctk.CTkLabel(pad, text="Executable: " + os.path.basename(self._exe or proc_name),
                     fg_color="transparent", text_color=TEXT3,
                     font=("Consolas", 9)).pack(anchor=tk.W, pady=(0, 8))

        self._tags_lbl = ctk.CTkLabel(pad, text="🔍 Looking up Steam tags…",
                                       fg_color="transparent", text_color=AMBER,
                                       font=("Segoe UI", 9), wraplength=360,
                                       justify="left", anchor="w")
        self._tags_lbl.pack(anchor=tk.W, pady=(0, 8))

        ctk.CTkLabel(pad, text="Spotify search query  (optional override)",
                     fg_color="transparent", text_color=TEXT2,
                     font=("Segoe UI", 10)).pack(anchor=tk.W)
        self._query_var = tk.StringVar()
        ctk.CTkEntry(pad, textvariable=self._query_var,
                     fg_color=SURF2, border_color=BORDER, text_color=TEXT,
                     corner_radius=8, font=("Segoe UI", 11), height=38).pack(
            fill=tk.X, pady=(3, 12))

        # ── Spotify Playlist Link ─────────────────────────────────────────────
        ctk.CTkLabel(pad, text="Spotify Playlist Link  (optional — overrides mood search)",
                     fg_color="transparent", text_color=TEXT2,
                     font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(4, 0))
        self._playlist_url_var = tk.StringVar()
        ctk.CTkEntry(pad, textvariable=self._playlist_url_var,
                     fg_color=SURF2, border_color=BORDER, text_color=TEXT,
                     corner_radius=8, font=("Segoe UI", 11), height=38).pack(
            fill=tk.X, pady=(3, 2))
        self._playlist_valid_lbl = ctk.CTkLabel(pad,
            text="Paste a Spotify playlist link (e.g. https://open.spotify.com/playlist/...)",
            fg_color="transparent", text_color=TEXT3, font=ctk.CTkFont(family="Segoe UI", size=11), anchor="w")
        self._playlist_valid_lbl.pack(anchor=tk.W, pady=(0, 10))
        self._playlist_url_var.trace_add("write", self._validate_playlist_url)

        ctk.CTkLabel(pad, text="Music mood", fg_color="transparent",
                     text_color=TEXT2, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 6))

        self._mood_var  = tk.StringVar(value=MOODS[0])
        self._mood_btns = {}
        grid = ctk.CTkFrame(pad, fg_color=BG, corner_radius=0)
        grid.pack(fill=tk.X)
        cols = 3
        for i, mood in enumerate(MOODS):
            info  = MOOD_TO_PLAYLIST[mood]
            color = info["color"]
            r, c  = divmod(i, cols)
            btn = ctk.CTkButton(grid, text=info["name"],
                                fg_color=SURF3, text_color=TEXT2,
                                hover_color=SURF4, corner_radius=8,
                                font=("Segoe UI", 9), height=36,
                                command=lambda m=mood, col=color: self._sel_mood(m, col))
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            grid.columnconfigure(c, weight=1)
            self._mood_btns[mood] = btn

        fi = MOOD_TO_PLAYLIST[MOODS[0]]
        self._mood_btns[MOODS[0]].configure(
            fg_color=_mood_tint(fi["color"]), text_color=fi["color"])

    def _sel_mood(self, mood, color):
        self._mood_var.set(mood)
        for m, ob in self._mood_btns.items():
            ob.configure(fg_color=SURF3, text_color=TEXT2)
        self._mood_btns[mood].configure(fg_color=_mood_tint(color), text_color=color)

    def _fetch_tags_worker(self, game_name: str):
        try:
            info = fetch_game_info(game_name)
        except Exception:
            info = fallback_game_info(game_name)
        root = self.winfo_toplevel()
        root.after(0, lambda i=info: self._finish_tags(i))

    def _finish_tags(self, info):
        if not self.winfo_exists():
            return
        self._tag_fetching = False
        self._apply_tags(info, from_steam=True)

    def _apply_tags(self, info, from_steam=False):
        if not self.winfo_exists() or not info:
            return

        self._fetched_tags  = info.get("tags", [])
        self._fetched_query = info.get("query", "")
        self._fetched_app_id = info.get("app_id", "")
        mood = info.get("mood", MOODS[0])

        tag_names = [t for t in self._fetched_tags if not t.startswith("_custom_query:")]
        if tag_names:
            self._tags_lbl.configure(
                text="🏷 " + "  ".join(f"#{t}" for t in tag_names[:6]),
                text_color=ACCENT)
        elif from_steam:
            self._tags_lbl.configure(
                text="ℹ Not on Steam — mood from game name", text_color=TEXT2)
        elif self._tag_fetching:
            self._tags_lbl.configure(
                text="🔍 Looking up Steam tags…", text_color=AMBER)
        else:
            self._tags_lbl.configure(
                text="ℹ Mood suggested from game name", text_color=TEXT2)

        if self._fetched_query:
            self._query_var.set(self._fetched_query)

        if mood in self._mood_btns:
            self._mood_var.set(mood)
            for ob in self._mood_btns.values():
                ob.configure(fg_color=SURF3, text_color=TEXT2)
            info2 = MOOD_TO_PLAYLIST[mood]
            c = info2["color"]
            self._mood_btns[mood].configure(fg_color=_mood_tint(c), text_color=c)

    def _validate_playlist_url(self, *_args):
        """Real-time validation of the Spotify playlist URL field."""
        url = self._playlist_url_var.get().strip()
        if not url:
            self._playlist_valid_lbl.configure(
                text="Paste a Spotify playlist link (e.g. https://open.spotify.com/playlist/...)",
                text_color=TEXT3)
            return
        uri = self._extract_playlist_uri(url)
        if uri:
            self._playlist_valid_lbl.configure(
                text=f"✓ Valid playlist: {uri}", text_color="#22c55e")
        else:
            self._playlist_valid_lbl.configure(
                text="✗ Invalid link — must be a Spotify playlist URL", text_color="#f43f5e")

    @staticmethod
    def _extract_playlist_uri(text: str) -> str:
        """Extract spotify:playlist:ID from a Spotify URL or URI. Returns '' if invalid."""
        text = (text or "").strip()
        if not text:
            return ""
        m = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]{15,25})", text)
        if m:
            return f"spotify:playlist:{m.group(1)}"
        m2 = re.match(r"^spotify:playlist:([a-zA-Z0-9]{15,25})$", text)
        if m2:
            return text
        return ""

    def _save(self):
        name = self._name_var.get().strip() or self._proc
        mood = self._mood_var.get()
        tags = list(self._fetched_tags)
        cq   = self._query_var.get().strip()
        if cq:
            tags = [t for t in tags if not t.startswith("_custom_query:")]
            tags.append(f"_custom_query:{cq}")
        elif self._fetched_query:
            tags = [t for t in tags if not t.startswith("_custom_query:")]
            tags.append(f"_custom_query:{self._fetched_query}")
        playlist_uri = self._extract_playlist_uri(
            self._playlist_url_var.get().strip())
        if self.on_save:
            self.on_save(self._proc, name, mood, self._exe, tags, playlist_uri, self._fetched_app_id)
        self.destroy()


class GamesPage(ctk.CTkFrame):
    def __init__(self, parent, on_games_changed=None, **kw):
        super().__init__(parent, fg_color="transparent", corner_radius=0, **kw)
        self.on_games_changed = on_games_changed
        self._icon_photos = []
        self._build()

    def _build(self):
        hdr = T.page_title(self, "My Games")
        T.primary_button(hdr, text="+ Add Game", command=self._add_by_exe,
                         width=118, height=34).pack(side=tk.RIGHT, padx=(0, 2))

        saved_wrap = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        saved_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self._scroll = ctk.CTkScrollableFrame(
            saved_wrap, fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT3,
            corner_radius=RADIUS_LG,
        )
        self._scroll.pack(fill=tk.BOTH, expand=True)
        self._saved_inner = self._scroll

        self._refresh_saved()

    def _add_by_exe(self):
        path = filedialog.askopenfilename(
            title="Select your game's .exe",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")])
        if not path:
            return
        proc = os.path.basename(path).lower()
        name = (os.path.basename(path)
                .replace(".exe", "").replace("_", " ").replace("-", " ").title())
        AddGameDialog(
            self.winfo_toplevel(),
            proc_name=proc,
            display_name=name,
            exe_path=path,
            on_save=self._on_saved,
        )

    def _on_saved(self, proc_name, display_name, mood, exe_path, tags,
                  spotify_playlist_uri="", app_id=""):
        add_game(proc_name, display_name, mood, exe_path, tags,
                 spotify_playlist_uri=spotify_playlist_uri, app_id=app_id)
        self._refresh_saved()
        if self.on_games_changed:
            self.on_games_changed()

    def _refresh_saved(self):
        for w in self._saved_inner.winfo_children():
            w.destroy()
        self._icon_photos = []

        games = load_games()
        if not games:
            empty = ctk.CTkFrame(self._saved_inner, fg_color="transparent", corner_radius=0)
            empty.pack(fill=tk.X, pady=12, padx=2)
            ctk.CTkLabel(empty,
                         text="No games added yet",
                         fg_color="transparent", text_color=TEXT,
                         font=T.ctk_font(14, "bold")).pack()
            ctk.CTkLabel(empty,
                         text="Click + Add Game to link a game and pick its music mood.",
                         fg_color="transparent", text_color=TEXT3,
                         font=T.ctk_font(12), justify="center").pack(pady=(2, 0))
            return

        for proc_name, info in games.items():
            mood_info = MOOD_TO_PLAYLIST.get(info.get("mood", "chill"), {})
            color = mood_info.get("color", ACCENT)
            self._saved_row(proc_name, info, color, mood_info)

    def _saved_row(self, proc_name, info, color, mood_info):
        row = ctk.CTkFrame(
            self._saved_inner, fg_color=SURF, corner_radius=RADIUS_SM,
            height=ROW_H, border_width=0,
        )
        row.pack(fill=tk.X, pady=3, padx=0)
        row.pack_propagate(False)

        accent_bar = ctk.CTkFrame(row, fg_color=color, width=3, corner_radius=2)
        accent_bar.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=0)

        self._pack_game_icon(row, proc_name, info, color)

        col = ctk.CTkFrame(row, fg_color="transparent", corner_radius=0)
        col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=10)

        title_row = ctk.CTkFrame(col, fg_color="transparent", corner_radius=0)
        title_row.pack(fill=tk.X, anchor=tk.W, pady=(0, 2))

        ctk.CTkLabel(title_row, text=info.get("name", proc_name), fg_color="transparent",
                     text_color=TEXT, font=T.ctk_font(14, "bold"),
                     anchor="w").pack(side=tk.LEFT)

        ctk.CTkLabel(title_row, text=f"  \u00b7  {proc_name}", fg_color="transparent",
                     text_color=TEXT3, font=T.ctk_font(10)).pack(side=tk.LEFT)

        mood_tint = _mood_tint(color, blend=0.88)
        mood_badge = ctk.CTkLabel(
            title_row,
            text=f"  {mood_info.get('name', '').upper()}  ",
            fg_color=mood_tint,
            text_color=color,
            font=T.ctk_font(9, "bold"),
            corner_radius=6,
            height=18,
        )
        mood_badge.pack(side=tk.LEFT, padx=(8, 2))

        if info.get("spotify_playlist_uri"):
            playlist_badge = ctk.CTkLabel(
                title_row,
                text="  PLAYLIST  ",
                fg_color="#dcfce7",
                text_color=GREEN,
                font=T.ctk_font(9, "bold"),
                corner_radius=6,
                height=18,
            )
            playlist_badge.pack(side=tk.LEFT, padx=(4, 2))

        tags = [t for t in info.get("tags", [])
                if not t.startswith("_custom_query:")]
        if tags:
            tag_str = "  ".join(f"#{t}" for t in tags[:5])
            ctk.CTkLabel(col, text=tag_str, fg_color="transparent",
                         text_color=TEXT3, font=T.ctk_font(10)).pack(
                anchor=tk.W, pady=(2, 0))

        del_btn = ctk.CTkButton(
            row, text="\u2715", fg_color="transparent",
            text_color=TEXT3, hover_color="#fee2e2",
            width=32, height=32, corner_radius=RADIUS_MD,
            font=T.ctk_font(12, "bold"),
            command=lambda p=proc_name: self._delete(p),
        )
        del_btn.pack(side=tk.RIGHT, padx=16)

    def _pack_game_icon(self, row, proc_name, info, color):
        banner_w = 148
        banner_h = ROW_H
        holder = ctk.CTkFrame(
            row, fg_color=SURF2, width=banner_w, height=banner_h, corner_radius=0,
        )
        holder.pack(side=tk.LEFT, padx=(6, 0), pady=0)
        holder.pack_propagate(False)

        lbl = ctk.CTkLabel(
            holder, text="", fg_color=SURF2, corner_radius=0,
            width=banner_w, height=banner_h,
        )
        lbl.pack(fill=tk.BOTH, expand=True)

        app_id = info.get("app_id", "")
        exe_path = info.get("exe_path", "")
        game_name = info.get("name", proc_name)
        root = self.winfo_toplevel()

        def _load_banner():
            try:
                img = get_game_thumbnail_image(
                    game_name, app_id, exe_path, color, size=(banner_w, banner_h),
                )
            except Exception:
                img = None

            def _apply():
                if img and HAS_PIL:
                    try:
                        ctk_img = ctk.CTkImage(
                            light_image=img, dark_image=img, size=(banner_w, banner_h),
                        )
                        self._icon_photos.append(ctk_img)
                        lbl.configure(image=ctk_img, text="")
                        return
                    except Exception:
                        pass
                self._draw_gradient_placeholder(lbl, color, (banner_w, banner_h))

            try:
                root.after(0, _apply)
            except Exception:
                pass

        threading.Thread(target=_load_banner, daemon=True).start()

    def _get_game_banner_image(self, game_name, app_id, exe_path, color):
        return get_game_thumbnail_image(game_name, app_id, exe_path, color)

    def _draw_gradient_placeholder(self, lbl, color, size=(120, 56)):
        try:
            img = _generate_gradient_fallback(color, size=size, radius=8)
            if img and HAS_PIL:
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
                self._icon_photos.append(ctk_img)
                lbl.configure(image=ctk_img, text="")
                return
        except Exception:
            pass
        lbl.configure(image=None, text="\U0001f3ae", text_color="#ffffff")

    def _delete(self, proc_name):
        remove_game(proc_name)
        self._refresh_saved()
        if self.on_games_changed:
            self.on_games_changed()
