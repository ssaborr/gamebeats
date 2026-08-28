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
                 on_block=None, on_try_another=None, on_close=None):
        super().__init__(root)
        self.root = root
        self.on_play        = on_play        or (lambda: None)
        self.on_pause       = on_pause       or (lambda: None)
        self.on_prev        = on_prev        or (lambda: None)
        self.on_next        = on_next        or (lambda: None)
        self.on_block       = on_block       or (lambda: None)
        self.on_try_another = on_try_another or (lambda: None)
        self.on_close       = on_close       or (lambda: None)

        self.title("GameBeats Control")
        self.attributes("-alpha", 0.93)
        self.attributes("-topmost", True)
        self.configure(fg_color=SURFACE)
        self.geometry("380x440")
        self.resizable(False, False)

        # Track state
        self._is_playing = False
        self._visible    = False
        self._fade_job   = None

        self._build_ui()
        self.withdraw()

    def _build_ui(self):
        """Build the overlay UI with CTk widgets."""
        container = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        container.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0)
        header.pack(fill=tk.X, pady=(0, 8))
        ctk.CTkLabel(header, text="🎵  Music Control",
                     fg_color="transparent", text_color=ACCENT2,
                     font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        ctk.CTkButton(header, text="✕",
                      command=self.hide,
                      fg_color="transparent", text_color=TEXT_SEC,
                      hover_color=SURFACE2, width=32, height=32,
                      corner_radius=8, font=("Segoe UI", 13)).pack(side=tk.RIGHT)

        # ── Transport controls (Prev / Play / Next) ───────────────────────────
        ctrl = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0, height=90)
        ctrl.pack(fill=tk.X, pady=(0, 8))
        ctrl.pack_propagate(False)

        self.prev_btn = ctk.CTkButton(ctrl, text="⏮",
                                       command=self._on_prev,
                                       fg_color=SURFACE3, text_color=TEXT,
                                       hover_color=_lighten(SURFACE3),
                                       width=56, height=56, corner_radius=28,
                                       font=("Segoe UI", 16, "bold"))
        self.prev_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.play_btn = ctk.CTkButton(ctrl, text="▶",
                                       command=self._toggle_play_pause,
                                       fg_color=ACCENT, text_color="#000",
                                       hover_color=_lighten(ACCENT),
                                       width=84, height=84, corner_radius=42,
                                       font=("Segoe UI", 36, "bold"))
        self.play_btn.pack(side=tk.LEFT, expand=True)

        self.next_btn = ctk.CTkButton(ctrl, text="⏭",
                                       command=self._on_next,
                                       fg_color=SURFACE3, text_color=TEXT,
                                       hover_color=_lighten(SURFACE3),
                                       width=56, height=56, corner_radius=28,
                                       font=("Segoe UI", 16, "bold"))
        self.next_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # ── Status ────────────────────────────────────────────────────────────
        self.status_lbl = ctk.CTkLabel(container, text="Ready to play",
                                        fg_color="transparent", text_color=TEXT_SEC,
                                        font=("Segoe UI", 11))
        self.status_lbl.pack(anchor=tk.CENTER, pady=(0, 8))

        # ── Separator ─────────────────────────────────────────────────────────
        ctk.CTkFrame(container, fg_color=BORDER, height=1, corner_radius=0).pack(
            fill=tk.X, pady=(0, 16))

        # ── Action buttons ────────────────────────────────────────────────────
        actions = ctk.CTkFrame(container, fg_color="transparent", corner_radius=0)
        actions.pack(fill=tk.X, pady=(0, 12))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        self.block_btn = ctk.CTkButton(actions, text="🚫  Block Playlist",
                                        command=self._on_block,
                                        fg_color=SURFACE3, text_color=AMBER,
                                        hover_color=_lighten(SURFACE3),
                                        corner_radius=10, height=46,
                                        border_width=1, border_color=BORDER,
                                        font=("Segoe UI", 10, "bold"))
        self.block_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.try_btn = ctk.CTkButton(actions, text="↺  Try Another",
                                      command=self._on_try_another,
                                      fg_color=SURFACE2, text_color=TEXT_SEC,
                                      hover_color=SURFACE3,
                                      corner_radius=10, height=46,
                                      border_width=1, border_color=BORDER,
                                      font=("Segoe UI", 10, "bold"))
        self.try_btn.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # ── Hint ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(container,
                     text="Keyboard: Space = play/pause  |  ← → = prev/next",
                     fg_color="transparent", text_color=TEXT_MUT,
                     font=("Segoe UI", 8), wraplength=340).pack(
            anchor=tk.W, pady=(10, 0))

    # ── Button callbacks ──────────────────────────────────────────────────────

    def _toggle_play_pause(self):
        if self._is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        self._is_playing = True
        self.play_btn.configure(text="⏸")
        self.status_lbl.configure(text="▶ Playing", text_color=ACCENT2)
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
        self._is_playing = False
        self.play_btn.configure(text="▶")
        self.status_lbl.configure(text="Ready to play", text_color=TEXT_SEC)
        self.deiconify()
        self._position_window()
        self.attributes("-topmost", True)
        self._visible = True

    def _position_window(self):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - 380) // 2
        y  = (sh - 440) // 2
        self.geometry(f"+{x}+{y}")

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
                self.status_lbl.configure(text="▶ Playing", text_color=ACCENT2)
            else:
                self.play_btn.configure(text="▶")
                self.status_lbl.configure(text="⏸ Paused", text_color=AMBER)

    def notify_game_active(self):
        """Called when game audio starts — auto-hide overlay."""
        self.hide()

    def notify_music_playing(self):
        """Called when music starts — update status."""
        self.update_status(playing=True)
