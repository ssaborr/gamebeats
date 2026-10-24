"""
GameBeats design tokens and reusable UI helpers.

The visual language follows the "Player 1's Room" pixel-art den:
plum/navy walls, warm wood, cream type, mint/gold/orange accents.
"""

import ctypes
import os
import sys
from pathlib import Path

import tkinter as tk
import customtkinter as ctk

UI_SCALE = 1.0


# ── Bundled fonts ─────────────────────────────────────────────────────────────

def assets_dir() -> Path:
    """Locate the bundled assets directory in dev and compiled builds."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "assets")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "assets")
    try:
        here = Path(__file__).resolve()
        # source/ui/theme.py -> project root/assets
        candidates.append(here.parents[2] / "assets")
        candidates.append(here.parents[1] / "assets")
    except Exception:
        pass
    candidates.append(Path.cwd() / "assets")
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            pass
    return Path("assets")


_FONTS_LOADED = False


def load_bundled_fonts() -> bool:
    """Load the open-source pixel fonts privately for this process."""
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return True
    if sys.platform != "win32":
        return False
    font_dir = assets_dir() / "fonts"
    names = (
        "Silkscreen-Regular.ttf",
        "Silkscreen-Bold.ttf",
        "VT323-Regular.ttf",
        "Fraunces-Italic.ttf",
    )
    loaded = False
    for name in names:
        path = font_dir / name
        try:
            if path.exists():
                # FR_PRIVATE (0x10): process-local font, no system install.
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)
                loaded = True
        except Exception:
            pass
    _FONTS_LOADED = loaded
    return loaded


def init_dpi():
    """Enable per-monitor DPI awareness before any Tk window is created."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def apply_ctk_scaling(root):
    """Keep layout at 1:1; DPI awareness handles crisp rendering without enlarging widgets."""
    global UI_SCALE
    UI_SCALE = 1.0
    ctk.set_widget_scaling(1.0)
    ctk.set_window_scaling(1.0)
    return UI_SCALE


def scaled_px(n):
    """Fixed pixel size — do not scale layout with DPI."""
    return int(n)


# ── Palette ───────────────────────────────────────────────────────────────────
# Core room palette from the Figma den concept.
PLUM      = "#1B1030"
NIGHT     = "#1A1111"
WALL      = "#28182F"
WOOD      = "#7A3E0E"
WOOD_DARK = "#381F30"
DECK      = "#54303A"
DECK_TOP  = "#75403F"
MAGENTA   = "#7A2E5B"
CREAM     = "#FFF3D0"
GOLD      = "#FDB75C"
ORANGE    = "#FF8A3D"
MINT      = "#7CFFC4"
ROSE      = "#D8B7B4"
DUST      = "#C79AA5"

BG         = PLUM
SIDEBAR    = NIGHT
SURFACE    = "#2A1830"
SURFACE2   = "#381F30"
SURFACE3   = "#332035"
SURFACE4   = "#4A2A3F"
ACCENT     = MINT
ACCENT2    = GOLD
ACCENT_HOV = "#A7FFD9"
ACCENT_DIM = "#39786B"
ACCENT_BG  = "#203A32"
ACCENT_GLOW= "#1D2F2B"
TEXT       = CREAM
TEXT_SEC   = GOLD
TEXT_MUTED = ROSE
BORDER     = DECK
BORDER2    = WOOD
RED        = ORANGE
AMBER      = GOLD
GREEN      = MINT
PURPLE     = "#C084FC"
BLUE       = MINT

SURF  = SURFACE
SURF2 = SURFACE2
SURF3 = SURFACE3
SURF4 = SURFACE4
TEXT2 = TEXT_SEC
TEXT3 = TEXT_MUTED
SHADOW = NIGHT

# ── Layout ──────────────────────────────────────────────────────────────────
SIDEBAR_W  = 228
NAV_H      = 34
WIN_W      = 1280
WIN_H      = 860
RADIUS_SM  = 3
RADIUS_MD  = 5
RADIUS_LG  = 7
RADIUS_XL  = 10

DEFAULT_PADX = 10
DEFAULT_PADY = 6

# ── Typography ──────────────────────────────────────────────────────────────
load_bundled_fonts()

F_FALLBACK = ("Segoe UI Variable Display", "Segoe UI", "Inter", "Arial")
F_UI       = F_FALLBACK[0]
F_PIXEL    = "Silkscreen" if _FONTS_LOADED else "Consolas"
F_RETRO    = "VT323" if _FONTS_LOADED else "Consolas"
F_SERIF    = "Fraunces 9pt" if _FONTS_LOADED else "Georgia"

F_TITLE    = (F_SERIF, 31, "italic")
F_HEADING  = (F_PIXEL, 14, "bold")
F_LABEL    = (F_RETRO, 18)
F_BODY     = (F_RETRO, 17)
F_SMALL    = (F_RETRO, 15)
F_MICRO    = (F_PIXEL, 10, "bold")
F_CAPTION  = (F_PIXEL, 10)
F_MONO     = ("Consolas", 12)

NAV_ITEMS = [
    ("main",     "The Den",       "\u2302"),
    ("games",    "Game Shelf",    "\u25a5"),
    ("playlists","Record Crate",  "\u25c9"),
    ("blocked",  "Blocked",       "\u2298"),
    ("settings", "Control Panel", "\u2692"),
    ("faq",      "FAQ & Help",    "\u2726"),
]


def pixel_font(size, weight="normal", slant="roman"):
    return ctk.CTkFont(family=F_PIXEL, size=size, weight=weight, slant=slant)


def retro_font(size, weight="normal", slant="roman"):
    return ctk.CTkFont(family=F_RETRO, size=size, weight=weight, slant=slant)


def serif_font(size, weight="normal", slant="italic"):
    return ctk.CTkFont(family=F_SERIF, size=size, weight=weight, slant=slant)


def ctk_font(size, weight="normal", slant="roman"):
    return ctk.CTkFont(family=F_UI, size=size, weight=weight, slant=slant)


# ── Reusable widgets ────────────────────────────────────────────────────────

def elevate_frame(parent, fg_color=SURFACE, border_color=BORDER, border_width=1,
                  corner_radius=RADIUS_MD, **kwargs):
    """A dark physical panel with a crisp pixel border."""
    return ctk.CTkFrame(
        parent, fg_color=fg_color, border_width=border_width,
        border_color=border_color, corner_radius=corner_radius, **kwargs,
    )


def elevated_card(parent, pady=0, padx=0, fill=tk.BOTH, expand=True):
    """Dark content surface inspired by the den's wooden panels."""
    outer = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    outer.pack(fill=fill, expand=expand, pady=pady, padx=padx)

    card = ctk.CTkFrame(
        outer, fg_color=SURFACE, border_width=1,
        border_color=BORDER, corner_radius=RADIUS_MD,
    )
    card.pack(fill=tk.BOTH, expand=True)

    content = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
    content.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)
    return content


def section_header(parent, text, pady=(0, 6), color=ACCENT2):
    """Small physical label above a panel."""
    ctk.CTkLabel(
        parent, text=str(text).upper(), fg_color="transparent",
        text_color=color, font=pixel_font(12, "bold"), anchor="w",
    ).pack(fill=tk.X, padx=2, pady=pady)


def page_title(parent, text, subtitle=None):
    """Object-view heading with an eyebrow and a serif display title."""
    hdr = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    hdr.pack(fill=tk.X, pady=(2, 14))

    col = ctk.CTkFrame(hdr, fg_color="transparent", corner_radius=0)
    col.pack(side=tk.LEFT, fill=tk.X, expand=True)

    if subtitle:
        ctk.CTkLabel(
            col, text=str(subtitle).upper(), fg_color="transparent",
            text_color=TEXT_MUTED, font=pixel_font(10), anchor="w",
        ).pack(anchor="w")
    ctk.CTkLabel(
        col, text=text, fg_color="transparent", text_color=TEXT,
        font=serif_font(30, slant="italic"), anchor="w",
    ).pack(anchor="w", pady=(5, 0))
    return hdr


def object_header(parent, eyebrow, title, subtitle=None, on_back=None):
    """Large Figma-style object-view heading with a back-to-room control."""
    hdr = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    hdr.pack(fill=tk.X, pady=(2, 16))

    left = ctk.CTkFrame(hdr, fg_color="transparent", corner_radius=0)
    left.pack(side=tk.LEFT, fill=tk.X, expand=True)
    ctk.CTkLabel(
        left, text=str(eyebrow).upper(), fg_color="transparent",
        text_color=TEXT_MUTED, font=pixel_font(11), anchor="w",
    ).pack(anchor="w")
    ctk.CTkLabel(
        left, text=title, fg_color="transparent", text_color=TEXT,
        font=serif_font(33, slant="italic"), anchor="w",
    ).pack(anchor="w", pady=(6, 0))
    if subtitle:
        ctk.CTkLabel(
            left, text=subtitle, fg_color="transparent", text_color=TEXT_MUTED,
            font=retro_font(18), anchor="w", justify=tk.LEFT, wraplength=720,
        ).pack(anchor="w", pady=(5, 0))

    if on_back:
        back = ctk.CTkFrame(hdr, fg_color="transparent", corner_radius=0)
        back.pack(side=tk.RIGHT, anchor="n", padx=(16, 0))
        ctk.CTkButton(
            back, text="\u00d7", command=on_back, width=34, height=34,
            fg_color=SURFACE2, text_color=GOLD, hover_color=DECK,
            border_width=2, border_color=WOOD, corner_radius=0,
            font=retro_font(24, "bold"),
        ).pack()
        ctk.CTkLabel(
            back, text="BACK TO THE ROOM", fg_color="transparent",
            text_color=TEXT_MUTED, font=pixel_font(8),
        ).pack(pady=(4, 0))
    return hdr


def primary_button(parent, text, command=None, width=120, height=34, **kwargs):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=ACCENT, text_color=BG,
        hover_color=ACCENT_HOV, corner_radius=RADIUS_SM,
        height=height, width=width,
        font=pixel_font(12, "bold"), **kwargs,
    )


def ghost_button(parent, text, command=None, width=100, height=32, **kwargs):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color="transparent", text_color=TEXT,
        hover_color=SURFACE3, corner_radius=RADIUS_SM,
        height=height, width=width,
        border_width=1, border_color=WOOD,
        font=pixel_font(11, "bold"), **kwargs,
    )


def pixel_button(parent, text, command=None, width=110, height=32,
                 active=False, accent=False, **kwargs):
    """Dark physical button that flashes mint on hover."""
    normal_bg = ACCENT if accent else (ACCENT_BG if active else SURFACE2)
    normal_fg = BG if accent else (ACCENT if active else TEXT)
    btn = ctk.CTkButton(
        parent, text=text, command=command, width=width, height=height,
        fg_color=normal_bg, text_color=normal_fg,
        hover_color=ACCENT if not accent else ACCENT_HOV,
        border_width=2, border_color=WOOD, corner_radius=0,
        font=pixel_font(11, "bold"), **kwargs,
    )
    if not accent:
        def _enter(_e):
            try:
                btn.configure(text_color=BG)
            except Exception:
                pass
        def _leave(_e):
            try:
                btn.configure(text_color=normal_fg)
            except Exception:
                pass
        btn.bind("<Enter>", _enter, add="+")
        btn.bind("<Leave>", _leave, add="+")
    return btn


def info_banner(parent, text, color="transparent", fg=ACCENT):
    return ctk.CTkLabel(
        parent, text=text, fg_color=color, text_color=fg,
        font=retro_font(15), anchor="w", justify=tk.LEFT,
        padx=0, pady=4, corner_radius=0,
    )


def divider(parent, pady=(8, 8)):
    """Spacer only — no visible line."""
    ctk.CTkFrame(parent, fg_color="transparent", height=pady[0] + pady[1]).pack(
        fill=tk.X,
    )


def rule(parent, color=BORDER, pady=(4, 8)):
    ctk.CTkFrame(parent, fg_color=color, height=2, corner_radius=0).pack(
        fill=tk.X, pady=pady,
    )


class SidebarPanel(ctk.CTkFrame):
    """Legacy compact sidebar. Kept for compatibility; the den uses a footer nav."""

    def __init__(self, parent, on_nav, logo_photo=None, **kw):
        super().__init__(
            parent, fg_color=SIDEBAR, width=SIDEBAR_W,
            corner_radius=0, border_width=0, **kw,
        )
        self.pack_propagate(False)
        self.on_nav = on_nav
        self._logo_photo = logo_photo
        self._active = "main"
        self._hovered = None
        self._items = {}
        self.brand_frame = None
        self._build()

    def _build(self):
        self.brand_frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.brand_frame.pack(fill=tk.X, padx=14, pady=(14, 10))

        brand_row = ctk.CTkFrame(self.brand_frame, fg_color="transparent", corner_radius=0)
        brand_row.pack(fill=tk.X)

        if self._logo_photo:
            tk.Label(
                brand_row, image=self._logo_photo, bg=SIDEBAR,
                bd=0, highlightthickness=0,
            ).pack(side=tk.LEFT, padx=(0, 10))
        else:
            ctk.CTkLabel(
                brand_row, text="\u266a", fg_color="transparent",
                text_color=ACCENT, font=pixel_font(18, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 10))

        text_col = ctk.CTkFrame(brand_row, fg_color="transparent", corner_radius=0)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ctk.CTkLabel(
            text_col, text="GAMEBEATS", fg_color="transparent",
            text_color=TEXT, font=pixel_font(14, "bold"), anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            text_col, text="THE DEN / VOL. 01", fg_color="transparent",
            text_color=TEXT_MUTED, font=pixel_font(8), anchor="w",
        ).pack(fill=tk.X)

        nav_section = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        nav_section.pack(fill=tk.X, padx=8, pady=(6, 4))

        for page, label, icon in NAV_ITEMS:
            self._items[page] = self._create_nav_item(nav_section, page, label, icon)

        ctk.CTkFrame(self, fg_color="transparent", corner_radius=0).pack(
            fill=tk.BOTH, expand=True,
        )

        footer = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        footer.pack(fill=tk.X, padx=14, pady=(0, 12))

        ctk.CTkLabel(
            footer, text="\u25cf  READY", fg_color="transparent",
            text_color=TEXT_MUTED, font=pixel_font(8),
        ).pack(side=tk.LEFT)

        self.set_active("main")

    def _create_nav_item(self, parent, page, label, icon):
        shell = ctk.CTkFrame(
            parent, fg_color="transparent", corner_radius=RADIUS_SM, height=NAV_H,
        )
        shell.pack(fill=tk.X, pady=1)
        shell.pack_propagate(False)

        pill = ctk.CTkFrame(shell, fg_color="transparent", corner_radius=RADIUS_SM)
        pill.pack(fill=tk.BOTH, expand=True, padx=2)

        inner = ctk.CTkFrame(pill, fg_color="transparent", corner_radius=RADIUS_SM)
        inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        icon_lbl = ctk.CTkLabel(
            inner, text=icon, width=24, fg_color="transparent",
            text_color=TEXT_MUTED, font=retro_font(16),
        )
        icon_lbl.pack(side=tk.LEFT, padx=(4, 0))

        text_lbl = ctk.CTkLabel(
            inner, text=label, fg_color="transparent",
            text_color=TEXT_MUTED, font=pixel_font(9), anchor="w",
        )
        text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        widgets = (shell, pill, inner, icon_lbl, text_lbl)
        for w in widgets:
            w.bind("<Button-1>", lambda e, p=page: self._click(p))
            w.bind("<Enter>", lambda e, p=page: self._on_hover(p, True))
            w.bind("<Leave>", lambda e, p=page: self._on_hover(p, False))

        return {"shell": shell, "pill": pill, "inner": inner, "icon": icon_lbl, "label": text_lbl}

    def _click(self, page):
        if self.on_nav:
            self.on_nav(page)

    def _on_hover(self, page, entering):
        if page == self._active:
            return
        self._hovered = page if entering else None
        self._paint_item(page)

    def _paint_item(self, page):
        w = self._items[page]
        active = page == self._active
        hovered = page == self._hovered and not active

        if active:
            bg = ACCENT_BG
            icon_c = ACCENT
            text_c = TEXT
            weight = "bold"
        elif hovered:
            bg = SURFACE3
            icon_c = TEXT
            text_c = TEXT
            weight = "normal"
        else:
            bg = "transparent"
            icon_c = TEXT_MUTED
            text_c = TEXT_MUTED
            weight = "normal"

        w["pill"].configure(fg_color=bg)
        w["icon"].configure(text_color=icon_c)
        w["label"].configure(text_color=text_c, font=pixel_font(9, weight))

    def set_active(self, page):
        self._active = page
        self._hovered = None
        for p in self._items:
            self._paint_item(p)


load_bundled_fonts()
init_dpi()
