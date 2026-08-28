"""
GameBeats design tokens and reusable UI helpers.
"""

import sys
import tkinter as tk
import customtkinter as ctk

UI_SCALE = 1.0


def init_dpi():
    """Enable per-monitor DPI awareness before any Tk window is created."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes
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
BG         = "#eef0f6"
SIDEBAR    = "#f4f5fa"
SURFACE    = "#ffffff"
SURFACE2   = "#f4f5fa"
SURFACE3   = "#eceff6"
SURFACE4   = "#dde3ef"
ACCENT     = "#6d28d9"
ACCENT2    = "#7c3aed"
ACCENT_HOV = "#5b21b6"
ACCENT_DIM = "#ddd6fe"
ACCENT_BG  = "#ede9fe"
ACCENT_GLOW= "#f3efff"
TEXT       = "#0f172a"
TEXT_SEC   = "#4338ca"
TEXT_MUTED = "#64748b"
BORDER     = "#e2e8f0"
BORDER2    = "#d1d9e8"
RED        = "#ef4444"
AMBER      = "#d97706"
GREEN      = "#10b981"
PURPLE     = "#8b5cf6"
BLUE       = "#3b82f6"

SURF  = SURFACE
SURF2 = SURFACE2
SURF3 = SURFACE3
SURF4 = SURFACE4
TEXT2 = TEXT_SEC
TEXT3 = TEXT_MUTED
SHADOW = BORDER

# ── Layout (compact) ────────────────────────────────────────────────────────
SIDEBAR_W  = 228
NAV_H      = 34
WIN_W      = 960
WIN_H      = 680
RADIUS_SM  = 8
RADIUS_MD  = 10
RADIUS_LG  = 12
RADIUS_XL  = 16

DEFAULT_PADX = 10
DEFAULT_PADY = 6

# ── Typography (text-forward) ───────────────────────────────────────────────
F_FALLBACK = ("Segoe UI Variable Display", "Segoe UI", "Inter", "Arial")
F_UI       = F_FALLBACK[0]
F_TITLE    = (F_UI, 21, "bold")
F_HEADING  = (F_UI, 17, "bold")
F_LABEL    = (F_UI, 15)
F_BODY     = (F_UI, 14)
F_SMALL    = (F_UI, 13)
F_MICRO    = (F_UI, 12, "bold")
F_CAPTION  = (F_UI, 12)
F_MONO     = ("Consolas", 11)

NAV_ITEMS = [
    ("main",     "Home",       "\u2302"),
    ("games",    "My Games",   "\u25c6"),
    ("blocked",  "Blocked",    "\u2298"),
    ("settings", "Settings",   "\u2699"),
    ("faq",      "FAQ & Help", "\u2139"),
]


def ctk_font(size, weight="normal", slant="roman"):
    return ctk.CTkFont(family=F_UI, size=size, weight=weight, slant=slant)


def elevated_card(parent, pady=0, padx=0, fill=tk.BOTH, expand=True):
    """Borderless content surface — no lines, minimal padding."""
    outer = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    outer.pack(fill=fill, expand=expand, pady=pady, padx=padx)

    card = ctk.CTkFrame(
        outer, fg_color=SURFACE, border_width=0, corner_radius=RADIUS_LG,
    )
    card.pack(fill=tk.BOTH, expand=True)

    content = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
    content.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)
    return content


def section_header(parent, text, pady=(0, 6)):
    """Page title only — no rules or boxes."""
    ctk.CTkLabel(
        parent, text=text, fg_color="transparent",
        text_color=TEXT, font=ctk_font(17, "bold"), anchor="w",
    ).pack(fill=tk.X, padx=2, pady=pady)


def page_title(parent, text, subtitle=None):
    hdr = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    hdr.pack(fill=tk.X, pady=(0, 10))
    col = ctk.CTkFrame(hdr, fg_color="transparent", corner_radius=0)
    col.pack(side=tk.LEFT, fill=tk.X, expand=True)
    ctk.CTkLabel(
        col, text=text, fg_color="transparent", text_color=TEXT,
        font=ctk_font(19, "bold"), anchor="w",
    ).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(
            col, text=subtitle, fg_color="transparent", text_color=TEXT_MUTED,
            font=ctk_font(13), anchor="w",
        ).pack(anchor="w", pady=(1, 0))
    return hdr


def primary_button(parent, text, command=None, width=120, height=34, **kwargs):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color=ACCENT, text_color="#ffffff",
        hover_color=ACCENT_HOV, corner_radius=RADIUS_SM,
        height=height, width=width,
        font=ctk_font(13, "bold"), **kwargs,
    )


def ghost_button(parent, text, command=None, width=100, height=32, **kwargs):
    return ctk.CTkButton(
        parent, text=text, command=command,
        fg_color="transparent", text_color=TEXT,
        hover_color=SURFACE3, corner_radius=RADIUS_SM,
        height=height, width=width,
        font=ctk_font(12, "bold"), **kwargs,
    )


def info_banner(parent, text, color="transparent", fg=ACCENT):
    return ctk.CTkLabel(
        parent, text=text, fg_color=color, text_color=fg,
        font=ctk_font(13), anchor="w", justify=tk.LEFT,
        padx=0, pady=4, corner_radius=0,
    )


def divider(parent, pady=(8, 8)):
    """Spacer only — no visible line."""
    ctk.CTkFrame(parent, fg_color="transparent", height=pady[0] + pady[1]).pack(
        fill=tk.X,
    )


class SidebarPanel(ctk.CTkFrame):
    """Compact sidebar — no separator lines."""

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
                text_color=ACCENT, font=ctk_font(18, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 10))

        text_col = ctk.CTkFrame(brand_row, fg_color="transparent", corner_radius=0)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ctk.CTkLabel(
            text_col, text="GameBeats", fg_color="transparent",
            text_color=TEXT, font=ctk_font(15, "bold"), anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            text_col, text="Music for your game", fg_color="transparent",
            text_color=TEXT_MUTED, font=ctk_font(12), anchor="w",
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

        foot_row = ctk.CTkFrame(footer, fg_color="transparent", corner_radius=0)
        foot_row.pack(fill=tk.X)

        ctk.CTkLabel(
            foot_row, text="\u25cf  Ready", fg_color="transparent",
            text_color=TEXT_MUTED, font=ctk_font(12),
        ).pack(side=tk.LEFT)

        ctk.CTkLabel(
            foot_row, text="@ssaborr", fg_color="transparent",
            text_color=TEXT_MUTED, font=ctk_font(11),
        ).pack(side=tk.RIGHT)

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
            text_color=TEXT_MUTED, font=ctk_font(14),
        )
        icon_lbl.pack(side=tk.LEFT, padx=(4, 0))

        text_lbl = ctk.CTkLabel(
            inner, text=label, fg_color="transparent",
            text_color=TEXT_MUTED, font=ctk_font(13), anchor="w",
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
        w["label"].configure(text_color=text_c, font=ctk_font(13, weight))

    def set_active(self, page):
        self._active = page
        self._hovered = None
        for p in self._items:
            self._paint_item(p)


init_dpi()
