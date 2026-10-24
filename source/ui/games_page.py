
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
TEXT_MUTED = T.TEXT_MUTED
NIGHT  = T.NIGHT
DECK   = T.DECK
WOOD   = T.WOOD
MINT   = T.MINT
GOLD   = T.GOLD
ORANGE = T.ORANGE
CREAM  = T.CREAM
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
    """Square icon for the player tab (exe icon, Steam banner, or gradient)."""
    if not info:
        return None
    exe_path = info.get("exe_path", "")
    mood = info.get("mood", "chill")
    color = MOOD_TO_PLAYLIST.get(mood, {}).get("color", ACCENT)
    game_name = info.get("name", "")
    app_id = info.get("app_id", "")
    px = int(size)

    # Prefer the real executable icon; it is crisp at cart/player sizes and
    # works for non-Steam games too.
    if exe_path and os.path.exists(exe_path):
        img = _extract_exe_icon_image(exe_path, px)
        if img:
            return img

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

    return (
        _pixel_gamepad_icon(color, size=px)
        or _generate_gradient_fallback(color, size=(px, px), radius=8)
    )


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


def _pixel_gamepad_icon(color_hex, size=46):
    """Tiny pixel-art gamepad fallback for games with no readable icon."""
    if not HAS_PIL:
        return None
    from PIL import ImageDraw

    im = _generate_gradient_fallback(color_hex, size=(size, size), radius=6)
    if im is None:
        return None
    draw = ImageDraw.Draw(im)
    s = int(size)
    line = max(1, s // 23)

    # Cartridge / panel
    draw.rounded_rectangle(
        [int(s * 0.10), int(s * 0.16), int(s * 0.90), int(s * 0.84)],
        radius=max(3, s // 12),
        fill=(18, 10, 24, 255),
        outline=(255, 243, 208, 255),
        width=line,
    )
    # Gamepad shell
    draw.rounded_rectangle(
        [int(s * 0.20), int(s * 0.40), int(s * 0.80), int(s * 0.68)],
        radius=max(3, s // 10),
        fill=(124, 255, 196, 255),
    )
    # D-pad
    cx, cy = int(s * 0.34), int(s * 0.54)
    arm = max(1, s // 13)
    draw.rectangle([cx - arm, cy - arm * 3, cx + arm, cy + arm * 3], fill=(27, 16, 48, 255))
    draw.rectangle([cx - arm * 3, cy - arm, cx + arm * 3, cy + arm], fill=(27, 16, 48, 255))
    # Face buttons
    for dx, dy, col in (
        (int(s * 0.66), int(s * 0.50), (255, 138, 61, 255)),
        (int(s * 0.72), int(s * 0.56), (253, 183, 92, 255)),
    ):
        r = max(1, s // 14)
        draw.ellipse([dx - r, dy - r, dx + r, dy + r], fill=col)
    return im


class AddGameDialog(ctk.CTkToplevel):
    def __init__(self, parent, proc_name, display_name, exe_path="", on_save=None,
                 existing=None):
        super().__init__(parent)
        self.title("Add Game" if not existing else "Edit Game")
        self.configure(fg_color=BG)
        self.resizable(True, True)
        self.grab_set()
        self.on_save   = on_save
        self._proc     = proc_name
        self._exe      = exe_path
        self._existing = existing or {}
        self._fetched_tags  = []
        self._fetched_query = ""
        self._fetched_app_id = ""
        self._prefill_mood = self._existing.get("mood") or None
        self._user_changed_mood = False
        self._prefill_query = next(
            (t.split(":", 1)[1] for t in self._existing.get("tags", [])
             if str(t).startswith("_custom_query:")),
            "",
        )

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
        ctk.CTkButton(inner, text="CANCEL", command=self.destroy,
                      fg_color=SURF2, text_color=TEXT, hover_color=SURF3,
                      border_width=2, border_color=T.WOOD,
                      corner_radius=0, width=140, height=42,
                      font=T.pixel_font(11, "bold")).pack(side=tk.LEFT, padx=6)
        ctk.CTkButton(inner, text="ADD GAME \u2713", command=self._save,
                      fg_color=ACCENT, text_color=BG, hover_color=T.ACCENT_HOV,
                      corner_radius=0, width=160, height=42,
                      font=T.pixel_font(11, "bold")).pack(side=tk.LEFT, padx=6)

        self._build(proc_name, display_name)
        self._tag_fetching = True
        self.after(50, lambda: self._apply_tags(fallback_game_info(display_name)))
        threading.Thread(target=self._fetch_tags_worker,
                         args=(display_name,), daemon=True).start()

    def _build(self, proc_name, display_name):
        head = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        head.pack(pady=(14, 4))

        logo_path = _puppy_logo_path()
        if logo_path and HAS_PIL:
            try:
                resampling = getattr(Image, "Resampling", Image)
                pup = Image.open(logo_path).convert("RGBA").resize(
                    (52, 59), resampling.NEAREST,
                )
                self._dialog_puppy = ctk.CTkImage(
                    light_image=pup, dark_image=pup, size=(52, 59),
                )
                ctk.CTkLabel(head, image=self._dialog_puppy, text="").pack(
                    side=tk.LEFT, padx=(0, 14),
                )
            except Exception:
                pass

        col = ctk.CTkFrame(head, fg_color="transparent", corner_radius=0)
        col.pack(side=tk.LEFT, anchor="w")

        ctk.CTkLabel(
            col,
            text="EDIT GAME" if self._existing else "ADD A GAME",
            fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(11, "bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            col, text="Let's make you a mixtape.", fg_color="transparent",
            text_color=TEXT, font=T.serif_font(27, "bold"), anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            col,
            text="Name it, choose a mood, and GameBeats handles the rest.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(16), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Scrollable form
        outer = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        scroll_frame = ctk.CTkScrollableFrame(outer, fg_color=BG,
                                               scrollbar_button_color=T.DECK,
                                               scrollbar_button_hover_color=T.WOOD)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        pad = ctk.CTkFrame(scroll_frame, fg_color=BG, corner_radius=0)
        pad.pack(fill=tk.X, padx=20)

        ctk.CTkLabel(pad, text="GAME NAME", fg_color="transparent",
                     text_color=GOLD, font=T.pixel_font(11, "bold")).pack(anchor=tk.W)
        ctk.CTkLabel(
            pad, text="This is what appears on the shelf and in the deck.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), anchor="w",
        ).pack(anchor=tk.W, pady=(2, 4))
        self._name_var = tk.StringVar(
            value=self._existing.get("name") or display_name
        )
        self._name_entry = ctk.CTkEntry(pad, textvariable=self._name_var,
                                         fg_color=SURF2, border_color=WOOD,
                                         text_color=TEXT, corner_radius=0,
                                         font=T.retro_font(18), height=46)
        self._name_entry.pack(fill=tk.X, pady=(0, 10))

        ctk.CTkLabel(pad, text="EXECUTABLE  \u00b7  " + os.path.basename(self._exe or proc_name),
                     fg_color="transparent", text_color=TEXT_MUTED,
                     font=T.retro_font(14)).pack(anchor=tk.W, pady=(0, 8))

        self._tags_lbl = ctk.CTkLabel(pad, text="\U0001f50d Looking up Steam tags\u2026",
                                       fg_color="transparent", text_color=AMBER,
                                       font=T.retro_font(15), wraplength=620,
                                       justify="left", anchor="w")
        self._tags_lbl.pack(anchor=tk.W, pady=(0, 10))

        ctk.CTkLabel(pad, text="SPOTIFY SEARCH  (OPTIONAL)",
                     fg_color="transparent", text_color=GOLD,
                     font=T.pixel_font(11, "bold")).pack(anchor=tk.W)
        ctk.CTkLabel(
            pad, text="Used to find a mix when you have not pasted a playlist link.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), anchor="w",
        ).pack(anchor=tk.W, pady=(2, 4))
        self._query_var = tk.StringVar()
        ctk.CTkEntry(pad, textvariable=self._query_var,
                     fg_color=SURF2, border_color=WOOD, text_color=TEXT,
                     corner_radius=0, font=T.retro_font(17), height=42).pack(
            fill=tk.X, pady=(0, 12))

        # ── Spotify Playlist Link ─────────────────────────────────────────────
        ctk.CTkLabel(pad, text="SPOTIFY PLAYLIST LINK  (OPTIONAL \u00b7 OVERRIDES MOOD)",
                     fg_color="transparent", text_color=GOLD,
                     font=T.pixel_font(11, "bold")).pack(anchor=tk.W, pady=(4, 0))
        ctk.CTkLabel(
            pad, text="Paste a link from Spotify Share. Leave blank to use the mood search.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), anchor="w",
        ).pack(anchor=tk.W, pady=(2, 4))
        self._playlist_url_var = tk.StringVar()
        ctk.CTkEntry(pad, textvariable=self._playlist_url_var,
                     fg_color=SURF2, border_color=WOOD, text_color=TEXT,
                     corner_radius=0, font=T.retro_font(17), height=42).pack(
            fill=tk.X, pady=(0, 2))
        self._playlist_valid_lbl = ctk.CTkLabel(pad,
            text="Paste a Spotify playlist link (e.g. https://open.spotify.com/playlist/...)",
            fg_color="transparent", text_color=TEXT_MUTED, font=T.retro_font(14),
            anchor="w")
        self._playlist_valid_lbl.pack(anchor=tk.W, pady=(0, 10))
        self._playlist_url_var.trace_add("write", self._validate_playlist_url)

        ctk.CTkLabel(pad, text="MUSIC MOOD", fg_color="transparent",
                     text_color=GOLD, font=T.pixel_font(11, "bold")).pack(
            anchor=tk.W, pady=(0, 2))
        ctk.CTkLabel(
            pad, text="Pick the feeling. You can change it any time.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.retro_font(14), anchor="w",
        ).pack(anchor=tk.W, pady=(0, 6))

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
                                fg_color=SURF3, text_color=TEXT,
                                hover_color=SURF4, corner_radius=6,
                                font=T.retro_font(15), height=40,
                                command=lambda m=mood, col=color: self._sel_mood(m, col))
            btn.grid(row=r, column=c, padx=3, pady=3, sticky="ew")
            grid.columnconfigure(c, weight=1)
            self._mood_btns[mood] = btn

        fi = MOOD_TO_PLAYLIST[MOODS[0]]
        self._mood_btns[MOODS[0]].configure(
            fg_color=_mood_tint(fi["color"]), text_color=fi["color"])

        existing_uri = self._existing.get("spotify_playlist_uri") or ""
        if existing_uri:
            self._playlist_url_var.set(existing_uri)
        if self._prefill_query:
            self._query_var.set(self._prefill_query)

        if self._prefill_mood in self._mood_btns:
            self._mood_var.set(self._prefill_mood)
            for mood_key, ob in self._mood_btns.items():
                ob.configure(fg_color=SURF3, text_color=TEXT)
            mood_info = MOOD_TO_PLAYLIST[self._prefill_mood]
            self._mood_btns[self._prefill_mood].configure(
                fg_color=_mood_tint(mood_info["color"]),
                text_color=mood_info["color"],
            )

    def _sel_mood(self, mood, color):
        self._user_changed_mood = True
        self._mood_var.set(mood)
        for m, ob in self._mood_btns.items():
            ob.configure(fg_color=SURF3, text_color=TEXT)
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
        if self._prefill_mood and not self._user_changed_mood:
            mood = self._prefill_mood

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

        if self._fetched_query and not self._prefill_query:
            self._query_var.set(self._fetched_query)

        if mood in self._mood_btns:
            self._mood_var.set(mood)
            for ob in self._mood_btns.values():
                ob.configure(fg_color=SURF3, text_color=TEXT)
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
                text=f"✓ Valid playlist: {uri}", text_color=T.MINT)
        else:
            self._playlist_valid_lbl.configure(
                text="✗ Invalid link — must be a Spotify playlist URL", text_color=T.RED)

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
    def __init__(self, parent, on_games_changed=None, on_back=None, **kw):
        super().__init__(parent, fg_color="transparent", corner_radius=0, **kw)
        self.on_games_changed = on_games_changed
        self.on_back = on_back
        self._icon_photos = []
        self._build()

    def _build(self):
        hdr = T.object_header(
            self,
            "THE DEN / YOUR COLLECTION",
            "Adventures, on tape.",
            "Pick a cart to give it a soundtrack. There's always room for another adventure.",
            on_back=self.on_back,
        )
        T.primary_button(
            hdr, text="+  ADD GAME", command=self._add_by_exe,
            width=138, height=36,
        ).pack(side=tk.RIGHT, anchor="n", padx=(12, 0))

        saved_wrap = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        saved_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self._scroll = ctk.CTkScrollableFrame(
            saved_wrap, fg_color="transparent",
            scrollbar_button_color=T.DECK,
            scrollbar_button_hover_color=T.WOOD,
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
            empty.pack(fill=tk.X, pady=(18, 4), padx=2)
            ctk.CTkLabel(
                empty, text="The shelf is empty.", fg_color="transparent",
                text_color=TEXT, font=T.serif_font(28, slant="italic"), anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                empty,
                text="Add your first game. It only takes one real .exe and a mood.",
                fg_color="transparent", text_color=TEXT_MUTED,
                font=T.retro_font(17), anchor="w",
            ).pack(anchor="w", pady=(4, 0))

        ctk.CTkLabel(
            self._saved_inner,
            text="YOUR CARTS  /  PICK A CART TO EDIT ITS LABEL",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.pixel_font(10, "bold"), anchor="w",
        ).pack(fill=tk.X, pady=(12, 0), padx=2)

        shelf = ctk.CTkFrame(self._saved_inner, fg_color="transparent", corner_radius=0)
        shelf.pack(fill=tk.X, pady=(4, 0))

        canvas = tk.Canvas(
            shelf, bg=BG, highlightthickness=0, bd=0, height=356,
            cursor="arrow",
        )
        canvas.pack(fill=tk.X, expand=True)
        hscroll = ctk.CTkScrollbar(
            shelf, orientation="horizontal", command=canvas.xview,
            height=10, fg_color=BG, button_color=DECK,
            button_hover_color=WOOD,
        )
        hscroll.pack(fill=tk.X, pady=(1, 0))
        canvas.configure(xscrollcommand=hscroll.set)

        row = ctk.CTkFrame(canvas, fg_color=BG, corner_radius=0)
        win = canvas.create_window(0, 0, window=row, anchor="nw")

        def _sync(_e=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
                canvas.itemconfigure(
                    win, width=max(row.winfo_reqwidth(), canvas.winfo_width()),
                )
            except Exception:
                pass

        if games:
            for index, (proc_name, info) in enumerate(games.items()):
                mood_key = info.get("mood", "chill")
                mood_info = MOOD_TO_PLAYLIST.get(mood_key, MOOD_TO_PLAYLIST["chill"])
                color = mood_info.get("color", ACCENT)
                self._cart_cell(row, index, proc_name, info, color, mood_info)
        self._insert_cell(row)

        row.bind("<Configure>", _sync, add="+")
        canvas.bind("<Configure>", _sync, add="+")
        canvas.bind(
            "<Shift-MouseWheel>",
            lambda e: canvas.xview_scroll(-1 if e.delta > 0 else 1, "units"),
        )
        self.after(40, _sync)

        foot = ctk.CTkFrame(self._saved_inner, fg_color="transparent", corner_radius=0)
        foot.pack(fill=tk.X, pady=(14, 6), padx=2)
        ctk.CTkLabel(
            foot,
            text="\u2726  REAL EXECUTABLES ONLY. NO SHORTCUTS, NO STEAM LINKS.",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.pixel_font(9, "bold"), anchor="w",
        ).pack(side=tk.LEFT)
        ctk.CTkLabel(
            foot, text=f"{len(games)} CARTS & COUNTING",
            fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(9, "bold"), anchor="e",
        ).pack(side=tk.RIGHT)

    # ── Shelf cart ────────────────────────────────────────────────────────────

    def _cart_cell(self, parent, index, proc_name, info, color, mood_info):
        cell = ctk.CTkFrame(
            parent, fg_color="transparent", corner_radius=0,
            width=198, height=342,
        )
        cell.pack(side=tk.LEFT, padx=(0, 12), anchor="n")
        cell.pack_propagate(False)

        label_text = self._contrast_color(color)
        name = str(info.get("name") or proc_name or "GAME")
        mood_name = re.sub(r"[^\x00-\x7F]+", "", str(mood_info.get("name", ""))).strip()
        mood_name = mood_name or str(info.get("mood", "chill")).replace("_", " ").title()

        cart = ctk.CTkFrame(
            cell, fg_color=SURF2, corner_radius=0,
            border_width=3, border_color=NIGHT, width=198, height=260,
        )
        cart.pack(fill=tk.X)
        cart.pack_propagate(False)

        ridges = ctk.CTkFrame(cart, fg_color="transparent", corner_radius=0, height=10)
        ridges.pack(fill=tk.X, padx=28, pady=(4, 0))
        for _ in range(5):
            ctk.CTkFrame(ridges, fg_color=DECK, width=4, height=6, corner_radius=0).pack(
                side=tk.LEFT, padx=3,
            )

        label = ctk.CTkFrame(
            cart, fg_color=color, corner_radius=0, height=132,
        )
        label.pack(fill=tk.X, padx=8, pady=(4, 0))
        label.pack_propagate(False)

        top = ctk.CTkFrame(label, fg_color="transparent", corner_radius=0)
        top.pack(fill=tk.X, padx=8, pady=(5, 0))
        ctk.CTkLabel(
            top, text=f"0{index + 1} / CART", fg_color="transparent",
            text_color=label_text, font=T.pixel_font(8, "bold"), anchor="w",
        ).pack(side=tk.LEFT)
        ctk.CTkLabel(
            top, text="GB", fg_color="transparent",
            text_color=label_text, font=T.pixel_font(8, "bold"), anchor="e",
        ).pack(side=tk.RIGHT)

        body = ctk.CTkFrame(label, fg_color="transparent", corner_radius=0)
        body.pack(fill=tk.X, padx=8, pady=(4, 0))

        icon_holder = ctk.CTkFrame(
            body, fg_color=NIGHT, corner_radius=2,
            width=46, height=46, border_width=1, border_color=WOOD,
        )
        icon_holder.pack(side=tk.LEFT, padx=(0, 7))
        icon_holder.pack_propagate(False)
        icon_lbl = ctk.CTkLabel(
            icon_holder, text="\U0001f3ae", fg_color="transparent",
            text_color=CREAM, font=T.retro_font(19),
        )
        icon_lbl.pack(fill=tk.BOTH, expand=True)

        info_col = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        info_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ctk.CTkLabel(
            info_col, text=name.upper(), fg_color="transparent",
            text_color=label_text, font=T.pixel_font(11, "bold"),
            anchor="w", justify=tk.LEFT, wraplength=125,
        ).pack(fill=tk.X)

        ctk.CTkLabel(
            info_col, text=proc_name.upper(), fg_color="transparent",
            text_color=label_text, font=T.retro_font(12),
            anchor="w",
        ).pack(fill=tk.X, pady=(1, 0))

        # Executable icons are cheap to extract and cached, so load them on
        # the UI thread. This guarantees the cart actually shows the game's
        # icon instead of an empty black tile.
        try:
            cart_icon = None
            exe_path = info.get("exe_path", "")
            if exe_path and os.path.exists(exe_path):
                cart_icon = _extract_exe_icon_image(exe_path, 46)
            if cart_icon is None:
                cart_icon = _pixel_gamepad_icon(color, 46)
            if cart_icon is not None:
                ctk_img = ctk.CTkImage(
                    light_image=cart_icon, dark_image=cart_icon, size=(46, 46),
                )
                self._icon_photos.append(ctk_img)
                icon_lbl.configure(image=ctk_img, text="")
        except Exception:
            pass

        ctk.CTkLabel(
            label, text=mood_name.upper(), fg_color=CREAM, text_color=NIGHT,
            font=T.serif_font(11, "bold"), corner_radius=0,
            padx=4, pady=1, anchor="w",
        ).pack(anchor="w", padx=8, pady=(4, 5))

        cass = ctk.CTkFrame(
            cart, fg_color=NIGHT, corner_radius=0,
            border_width=2, border_color=WOOD, height=48,
        )
        cass.pack(fill=tk.X, padx=8, pady=(6, 0))
        cass.pack_propagate(False)

        reel = tk.Canvas(cass, bg=NIGHT, highlightthickness=0, bd=0, width=1, height=44)
        reel.pack(fill=tk.BOTH, expand=True)
        reel.bind("<Configure>", lambda e, c=reel, col=color: self._draw_cart_reels(c, col))

        base = ctk.CTkFrame(cart, fg_color="transparent", corner_radius=0)
        base.pack(fill=tk.X, padx=8, pady=(4, 3))
        ctk.CTkLabel(
            base, text="SIDE A", fg_color="transparent", text_color=TEXT_MUTED,
            font=T.pixel_font(8, "bold"),
        ).pack(side=tk.LEFT)
        ctk.CTkLabel(
            base, text="AUTO", fg_color="transparent", text_color=GOLD,
            font=T.pixel_font(8, "bold"),
        ).pack(side=tk.RIGHT)

        self._wood_shelf(cell)

        ctk.CTkLabel(
            cell, text=f"0{index + 1} / READY TO PLAY",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.pixel_font(9), anchor="center",
        ).pack(fill=tk.X, pady=(5, 1))

        actions = ctk.CTkFrame(cell, fg_color="transparent", corner_radius=0)
        actions.pack(fill=tk.X)
        ctk.CTkButton(
            actions, text="EDIT LABEL \u2197",
            command=lambda p=proc_name, i=info: self._edit_game(p, i),
            fg_color="transparent", text_color=MINT, hover_color=SURF3,
            font=T.pixel_font(9, "bold"), width=102, height=22,
            corner_radius=0,
        ).pack(side=tk.LEFT)
        ctk.CTkButton(
            actions, text="\u2715 REMOVE",
            command=lambda p=proc_name: self._delete(p),
            fg_color="transparent", text_color=TEXT_MUTED, hover_color=SURF3,
            font=T.pixel_font(9), width=76, height=22,
            corner_radius=0,
        ).pack(side=tk.RIGHT)

        # 3D bevel + hover glow. The lit top edge and dark bottom edge make the
        # cart read as a physical object instead of a flat rectangle.
        try:
            tk.Frame(cart, bg=_lighten(SURF2, 26), height=2).place(
                x=0, y=0, relwidth=1,
            )
            tk.Frame(cart, bg=NIGHT, height=3).place(
                x=0, rely=1.0, y=-3, relwidth=1,
            )

            def _hover(on):
                try:
                    cart.configure(border_color=color if on else NIGHT)
                    label.configure(fg_color=_lighten(color, 14) if on else color)
                except Exception:
                    pass

            for widget in (cart, label, body, info_col, icon_holder):
                widget.bind("<Enter>", lambda e: _hover(True), add="+")
                widget.bind("<Leave>", lambda e: _hover(False), add="+")
        except Exception:
            pass

    def _insert_cell(self, parent):
        cell = ctk.CTkFrame(
            parent, fg_color="transparent", corner_radius=0,
            width=198, height=342,
        )
        cell.pack(side=tk.LEFT, padx=(0, 4), anchor="n")
        cell.pack_propagate(False)

        slot = ctk.CTkFrame(
            cell, fg_color=SURF2, corner_radius=0,
            border_width=2, border_color=WOOD, width=198, height=260,
        )
        slot.pack(fill=tk.X)
        slot.pack_propagate(False)

        inner = ctk.CTkFrame(slot, fg_color="transparent", corner_radius=0)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        plus = ctk.CTkLabel(
            inner, text="+", fg_color="transparent", text_color=GOLD,
            font=T.retro_font(38, "bold"),
        )
        plus.pack()
        title = ctk.CTkLabel(
            inner, text="ADD A GAME", fg_color="transparent", text_color=CREAM,
            font=T.pixel_font(11, "bold"),
        )
        title.pack(pady=(0, 2))
        hint = ctk.CTkLabel(
            inner, text="Choose the real .exe\nnot a shortcut", fg_color="transparent",
            text_color=TEXT_MUTED, font=T.retro_font(14), justify=tk.CENTER,
        )
        hint.pack(pady=(0, 6))
        T.primary_button(
            inner, text="CHOOSE .EXE", command=self._add_by_exe,
            width=132, height=28,
        ).pack()

        for widget in (slot, inner, plus, title, hint):
            try:
                widget.bind("<Button-1>", lambda e: self._add_by_exe())
                widget.configure(cursor="hand2")
            except Exception:
                pass

        self._wood_shelf(cell)
        ctk.CTkLabel(
            cell, text="EMPTY SLOT / DROP A GAME .EXE HERE",
            fg_color="transparent", text_color=TEXT_MUTED,
            font=T.pixel_font(9), anchor="center",
        ).pack(fill=tk.X, pady=(5, 1))
        ctk.CTkLabel(
            cell, text=" ", fg_color="transparent",
            font=T.pixel_font(9),
        ).pack(fill=tk.X)

    @staticmethod
    def _wood_shelf(parent):
        tk.Frame(parent, bg=ORANGE, height=3, bd=0, highlightthickness=0).pack(fill=tk.X)
        tk.Frame(
            parent, bg=WOOD, height=9, bd=0,
            highlightbackground=NIGHT, highlightthickness=2,
        ).pack(fill=tk.X)

    @staticmethod
    def _contrast_color(hex_color):
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            return NIGHT if (0.299 * r + 0.587 * g + 0.114 * b) > 120 else CREAM
        except Exception:
            return CREAM

    def _draw_cart_reels(self, canvas, color):
        try:
            canvas.delete("all")
            w = max(60, canvas.winfo_width())
            h = max(30, canvas.winfo_height())
            cy = h // 2
            canvas.create_line(int(w * 0.18), cy, int(w * 0.82), cy, fill=WOOD, width=1)
            radius = max(8, min(15, h // 3))
            for cx in (int(w * 0.24), int(w * 0.76)):
                canvas.create_oval(
                    cx - radius, cy - radius, cx + radius, cy + radius,
                    outline=GOLD, width=2, fill=NIGHT,
                )
                canvas.create_rectangle(
                    cx - 3, cy - 3, cx + 3, cy + 3, fill=color, outline="",
                )
            canvas.create_rectangle(
                w // 2 - 14, cy - 9, w // 2 + 14, cy + 9,
                fill=SURF2, outline=WOOD, width=1,
            )
            canvas.create_text(
                w // 2, cy, text="GB", fill=GOLD,
                font=(T.F_PIXEL, -8, "bold"),
            )
        except Exception:
            pass

    def _edit_game(self, proc_name, info):
        AddGameDialog(
            self.winfo_toplevel(),
            proc_name=proc_name,
            display_name=info.get("name", proc_name),
            exe_path=info.get("exe_path", ""),
            on_save=self._on_saved,
            existing=info,
        )

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
                     text_color=TEXT, font=T.retro_font(19, "bold"),
                     anchor="w").pack(side=tk.LEFT)

        ctk.CTkLabel(title_row, text=f"  \u00b7  {proc_name}", fg_color="transparent",
                     text_color=TEXT3, font=T.retro_font(13)).pack(side=tk.LEFT)

        mood_tint = _mood_tint(color, blend=0.88)
        mood_badge = ctk.CTkLabel(
            title_row,
            text=f"  {mood_info.get('name', '').upper()}  ",
            fg_color=mood_tint,
            text_color=color,
            font=T.pixel_font(11, "bold"),
            corner_radius=RADIUS_SM,
            height=18,
        )
        mood_badge.pack(side=tk.LEFT, padx=(8, 2))

        if info.get("spotify_playlist_uri"):
            playlist_badge = ctk.CTkLabel(
                title_row,
                text="  PLAYLIST  ",
                fg_color=T.ACCENT_BG,
                text_color=T.MINT,
                font=T.pixel_font(11, "bold"),
                corner_radius=RADIUS_SM,
                height=18,
            )
            playlist_badge.pack(side=tk.LEFT, padx=(4, 2))

        tags = [t for t in info.get("tags", [])
                if not t.startswith("_custom_query:")]
        if tags:
            tag_str = "  ".join(f"#{t}" for t in tags[:5])
            ctk.CTkLabel(col, text=tag_str, fg_color="transparent",
                         text_color=TEXT3, font=T.retro_font(13)).pack(
                anchor=tk.W, pady=(2, 0))

        del_btn = ctk.CTkButton(
            row, text="\u2715", fg_color="transparent",
            text_color=TEXT3, hover_color=SURF4,
            width=32, height=32, corner_radius=RADIUS_MD,
            font=T.pixel_font(11, "bold"),
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
