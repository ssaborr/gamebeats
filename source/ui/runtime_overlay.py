"""
runtime_overlay.py — Complete manual music control panel overlay.

Features:
- Manual play/pause control (no audio detection required)
- Previous/Next track buttons
- Block playlist and Try another buttons
- Always-on-top transparent window that doesn't interfere with gameplay
- Appears when requested, auto-hides on game audio detection
"""

import tkinter as tk
import customtkinter as ctk
import threading
import time
import sys
import ctypes

from ui import theme as T

BG      = T.BG
SURFACE = T.SURFACE
SURFACE2= T.SURFACE2
SURFACE3= T.SURFACE3
SURFACE4= T.SURFACE4
ACCENT  = T.ACCENT
ACCENT2 = T.ACCENT2
TEXT    = T.TEXT
TEXT_SEC= T.TEXT_SEC
TEXT_MUT= T.TEXT_MUTED
BORDER  = T.BORDER
RED     = T.RED
AMBER   = T.AMBER

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from ctypes import wintypes


def _lighten(h, a=22):
    try:
        return "#{:02x}{:02x}{:02x}".format(
            min(255, int(h[1:3], 16)+a), min(255, int(h[3:5], 16)+a),
            min(255, int(h[5:7], 16)+a))
    except Exception:
        return h


class RuntimeOverlay(ctk.CTkToplevel):
    """
    Complete manual music control panel overlay.
    Appears during gameplay for manual pause/resume/prev/next/block/try controls.
    """

    def __init__(self, root, on_play=None, on_pause=None, on_prev=None, on_next=None,
                 on_block=None, on_try_another=None, on_close=None, get_playing=None):
        super().__init__(root)
        self.root = root
        self.on_play        = on_play        or (lambda: None)
        self.on_pause       = on_pause       or (lambda: None)
        self.on_prev        = on_prev        or (lambda: None)
        self.on_next        = on_next        or (lambda: None)
        self.on_block       = on_block       or (lambda: None)
        self.on_try_another = on_try_another or (lambda: None)
        self.on_close       = on_close       or (lambda: None)
        self.get_playing    = get_playing    or (lambda: bool(self._is_playing))

        self.title("GameBeats Control")
        self.overrideredirect(True)
        self.attributes("-alpha", 0.96)
        self.attributes("-topmost", True)
        self.configure(fg_color=T.NIGHT)
        self.geometry("380x446")
        self.resizable(False, False)

        # Track state
        self._is_playing = False
        self._visible    = False
        self._fade_job   = None

        self._build_ui()
        self.withdraw()

        # Keyboard shortcuts
        self.bind("<space>", lambda e: self._toggle_play_pause())
        self.bind("<Left>", lambda e: self._on_prev())
        self.bind("<Right>", lambda e: self._on_next())
        self.bind("<Escape>", lambda e: self.hide())

    def _build_ui(self):
        """Build the overlay UI with CTk widgets."""
        shell = ctk.CTkFrame(
            self, fg_color=SURFACE, corner_radius=0,
            border_width=2, border_color=T.WOOD,
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        container = ctk.CTkFrame(shell, fg_color=SURFACE, corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0)
        header.pack(fill=tk.X, pady=(0, 10))

        title_lbl = ctk.CTkLabel(
            header, text="\u25b6  GB / REMOTE", fg_color="transparent",
            text_color=ACCENT2, font=T.pixel_font(11, "bold"),
        )
        title_lbl.pack(side=tk.LEFT)

        close_btn = ctk.CTkButton(
            header, text="\u00d7", command=self.hide,
            fg_color="transparent", text_color=T.TEXT_MUTED,
            hover_color=SURFACE2, width=30, height=28,
            corner_radius=0, font=T.retro_font(22, "bold"),
        )
        close_btn.pack(side=tk.RIGHT)

        for widget in (header, title_lbl):
            widget.bind("<ButtonPress-1>", self._start_drag, add="+")
            widget.bind("<B1-Motion>", self._drag, add="+")

        # ── Transport controls (Prev / Play / Next) ───────────────────────────
        ctrl = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0, height=92)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ctrl.pack_propagate(False)

        self.prev_btn = ctk.CTkButton(
            ctrl, text="\u23ee", command=self._on_prev,
            fg_color=SURFACE3, text_color=TEXT,
            hover_color=SURFACE4,
            width=56, height=56, corner_radius=28,
            border_width=2, border_color=T.WOOD,
            font=T.retro_font(20, "bold"),
        )
        self.prev_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.play_btn = ctk.CTkButton(
            ctrl, text="\u25b6", command=self._toggle_play_pause,
            fg_color=ACCENT2, text_color=BG,
            hover_color=T.ACCENT_HOV,
            width=84, height=84, corner_radius=42,
            font=T.retro_font(34, "bold"),
        )
        self.play_btn.pack(side=tk.LEFT, expand=True)

        self.next_btn = ctk.CTkButton(
            ctrl, text="\u23ed", command=self._on_next,
            fg_color=SURFACE3, text_color=TEXT,
            hover_color=SURFACE4,
            width=56, height=56, corner_radius=28,
            border_width=2, border_color=T.WOOD,
            font=T.retro_font(20, "bold"),
        )
        self.next_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # ── Status ────────────────────────────────────────────────────────────
        self.status_lbl = ctk.CTkLabel(
            container, text="Ready when you are.", fg_color="transparent",
            text_color=TEXT_SEC, font=T.retro_font(17),
        )
        self.status_lbl.pack(anchor=tk.CENTER, pady=(0, 8))

        # ── Separator ─────────────────────────────────────────────────────────
        ctk.CTkFrame(container, fg_color=BORDER, height=2, corner_radius=0).pack(
            fill=tk.X, pady=(0, 14))

        # ── Action buttons ────────────────────────────────────────────────────
        actions = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0)
        actions.pack(fill=tk.X, pady=(0, 10))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        self.block_btn = ctk.CTkButton(
            actions, text="\u2298  BLOCK", command=self._on_block,
            fg_color=SURFACE2, text_color=AMBER,
            hover_color=SURFACE4, corner_radius=0, height=44,
            border_width=2, border_color=T.WOOD,
            font=T.pixel_font(9, "bold"),
        )
        self.block_btn.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.try_btn = ctk.CTkButton(
            actions, text="\u21ba  TRY ANOTHER", command=self._on_try_another,
            fg_color=T.ACCENT_BG, text_color=ACCENT,
            hover_color=T.ACCENT_DIM,
            corner_radius=0, height=44,
            border_width=2, border_color=T.WOOD,
            font=T.pixel_font(9, "bold"),
        )
        self.try_btn.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        # ── Hint ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(
            container,
            text="SPACE = PLAY / PAUSE   \u00b7   \u2190 \u2192 = PREV / NEXT",
            fg_color="transparent", text_color=TEXT_MUT,
            font=T.pixel_font(7), wraplength=330,
        ).pack(anchor=tk.W, pady=(8, 0))

    def _start_drag(self, event):
        self._drag_ox = event.x_root - self.winfo_x()
        self._drag_oy = event.y_root - self.winfo_y()

    def _drag(self, event):
        try:
            x = event.x_root - self._drag_ox
            y = event.y_root - self._drag_oy
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ── Button callbacks ──────────────────────────────────────────────────────

    def _query_playing(self):
        try:
            return bool(self.get_playing())
        except Exception:
            return bool(self._is_playing)

    def _toggle_play_pause(self):
        # Ask the app for the real state instead of trusting the overlay's
        # last optimistic icon. This prevents a second click from re-sending
        # the same command.
        if self._query_playing():
            self._pause()
        else:
            self._play()

    def _play(self):
        self._is_playing = True
        self.play_btn.configure(text="⏸")
        self.status_lbl.configure(text="\u25b6 Playing", text_color=ACCENT)
        self.on_play()

    def _pause(self):
        self._is_playing = False
        self.play_btn.configure(text="▶")
        self.status_lbl.configure(text="⏸ Paused", text_color=AMBER)
        self.on_pause()

    def _on_prev(self):
        self.status_lbl.configure(text="⏮ Previous", text_color=TEXT_SEC)
        self.on_prev()

    def _on_next(self):
        self.status_lbl.configure(text="⏭ Next", text_color=TEXT_SEC)
        self.on_next()

    def _on_block(self):
        self.status_lbl.configure(text="🚫 Playlist blocked", text_color=RED)
        self.on_block()

    def _on_try_another(self):
        self.status_lbl.configure(text="↺ Finding another...", text_color=TEXT_SEC)
        self.on_try_another()

    # ── Visibility ────────────────────────────────────────────────────────────

    def show(self):
        if self._fade_job:
            self.after_cancel(self._fade_job)
        self.update_status(playing=self._query_playing())
        self.deiconify()
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._position_window()
        self.attributes("-topmost", True)
        self._visible = True
        try:
            self.lift()
        except Exception:
            pass
        try:
            self.focus_force()
        except Exception:
            pass
        # The first deiconify of an override-redirect window can end up behind
        # the foreground window on Windows. Re-assert it briefly afterwards.
        try:
            self.after(60, self._raise_safe)
            self.after(220, self._raise_safe)
        except Exception:
            pass

    def _raise_safe(self):
        if not self._visible:
            return
        try:
            if not self.winfo_viewable():
                self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
        except Exception:
            pass

    def _position_window(self):
        try:
            self.update_idletasks()
        except Exception:
            pass
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = max(380, self.winfo_width())
        h = max(446, self.winfo_height())
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def hide(self):
        if self._fade_job:
            self.after_cancel(self._fade_job)
            self._fade_job = None
        self.withdraw()
        self._visible = False

    def is_visible(self):
        return self._visible

    def update_status(self, playing=None):
        if playing is not None:
            self._is_playing = playing
            if playing:
                self.play_btn.configure(text="⏸")
                self.status_lbl.configure(text="\u25b6 Playing", text_color=ACCENT)
            else:
                self.play_btn.configure(text="▶")
                self.status_lbl.configure(text="⏸ Paused", text_color=AMBER)

    def notify_game_active(self):
        """Called when game audio starts — auto-hide overlay."""
        self.hide()

    def notify_music_playing(self):
        """Called when music starts — update status."""
        self.update_status(playing=True)
