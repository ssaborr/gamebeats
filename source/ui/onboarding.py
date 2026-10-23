"""
GameBeats — First-launch onboarding overlay.

Shows as a full-screen overlay on top of the main window.
Steps: Welcome → Create Spotify App → Enter Credentials → Connect → Done
Disappears after setup and never shows again.
"""
import tkinter as tk
import customtkinter as ctk
import threading

from ui import theme as T

# ── Palette (from theme) ──────────────────────────────────────────────────────
BG      = T.BG
SURF    = T.SURF
SURF2   = T.SURF2
SURF3   = T.SURF3
SURF4   = T.SURF4
ACCENT  = T.ACCENT
ACCENT2 = T.ACCENT2
TEXT    = T.TEXT
TEXT2   = T.TEXT2
TEXT3   = T.TEXT3
RED     = T.RED
AMBER   = T.AMBER
BORDER  = T.BORDER

REDIRECT_URI = "http://127.0.0.1:8888/callback"


def _open_url_hidden(url: str) -> None:
    """No-op — browser opening disabled."""
    pass


def _lighten(h, amt=22):
    try:
        r = min(255, int(h[1:3], 16) + amt)
        g = min(255, int(h[3:5], 16) + amt)
        b = min(255, int(h[5:7], 16) + amt)
        return f"#{r:02x}{g:02x}{b:02x}"
    except:
        return h


# ── Main onboarding overlay ───────────────────────────────────────────────────

class OnboardingOverlay(ctk.CTkFrame):
    """
    Full-screen overlay placed over the root window.
    Call .show() to display, .destroy() when done.

    on_complete(auth, spotify) is called when the user finishes.
    auth / spotify may be None if the user skips.
    """

    STEPS = ["welcome", "create_app", "credentials", "connect", "done"]

    def __init__(self, root, SpotifyAuth, SpotifyController,
                 on_complete, tokens_file, config_file):
        super().__init__(root, fg_color=BG, corner_radius=0)
        self._app = root
        self._SpotifyAuth       = SpotifyAuth
        self._SpotifyController = SpotifyController
        self._on_complete       = on_complete
        self._tokens_file       = tokens_file
        self._config_file       = config_file

        self._step = 0
        self._cid  = tk.StringVar()
        self._csec = tk.StringVar()
        self._auth    = None
        self._spotify = None
        self._spinning = False

        # Expand window height for onboarding; restore original size when done
        self._orig_geometry = root.geometry()
        try:
            geo = self._orig_geometry
            wh  = geo.split("+")[0]
            w   = wh.split("x")[0]
            pos = "+" + "+".join(geo.split("+")[1:]) if "+" in geo else ""
            root.geometry(f"{w}x760{pos}")
        except Exception:
            root.geometry("440x760")

        self.place(x=0, y=0, relwidth=1, relheight=1)
        self._render()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _render(self):
        print(f"_render called, step={self._step}, name={self.STEPS[self._step]}")
        for w in self.winfo_children():
            w.destroy()
        try:
            getattr(self, f"_step_{self.STEPS[self._step]}")()
            print(f"_render done for step={self._step}")
        except Exception as exc:
            import traceback
            print(f"RENDER ERROR: {exc}")
            ctk.CTkLabel(self, text=f"Error on step {self._step}:\n{exc}",
                         fg_color="transparent", text_color=RED,
                         font=T.retro_font(15), wraplength=380,
                         justify="left").pack(pady=40, padx=20)
            traceback.print_exc()

    def _next(self):
        print(f"_next called, current step={self._step}")
        if self._step < len(self.STEPS) - 1:
            self._step += 1
            self._render()

    def _back(self):
        if self._step > 0:
            self._step -= 1
            self._render()

    # ── Progress dots ─────────────────────────────────────────────────────────

    def _dots(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        f.pack(pady=(12, 6))
        for i, _ in enumerate(self.STEPS):
            active = i == self._step
            done   = i < self._step
            color  = ACCENT if active else (TEXT2 if done else SURF3)
            size   = 10 if active else 7
            c = tk.Canvas(f, width=size, height=size, bg=BG, highlightthickness=0)
            c.pack(side=tk.LEFT, padx=4)
            c.create_oval(0, 0, size, size, fill=color, outline="")

    # ── Shared layout helpers ─────────────────────────────────────────────────

    def _hero(self, parent, emoji, title, subtitle):
        ctk.CTkLabel(parent, text=emoji, fg_color="transparent",
                     font=T.retro_font(44)).pack(pady=(40, 6))
        ctk.CTkLabel(parent, text=title, fg_color="transparent",
                     text_color=TEXT, font=T.serif_font(30, "bold")).pack()
        ctk.CTkLabel(parent, text=subtitle, fg_color="transparent",
                     text_color=TEXT2, font=T.retro_font(16),
                     wraplength=350, justify="center").pack(pady=(6, 24))

    def _btn(self, parent, text, cmd, bg=ACCENT, fg="#000", disabled=False):
        """CTkButton styled consistently."""
        state = "disabled" if disabled else "normal"
        b = ctk.CTkButton(parent, text=text, command=cmd,
                          fg_color=bg, text_color=fg,
                          hover_color=_lighten(bg),
                          font=T.pixel_font(9, "bold"),
                          corner_radius=0, height=42,
                          state=state)
        return b

    def _nav_row(self, parent, back=True,
                 next_text="Continue →", next_cmd=None,
                 next_bg=ACCENT, next_fg="#000", next_disabled=False):
        row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        row.pack(pady=(18, 0))
        if back:
            self._btn(row, "← Back", self._back,
                      bg=SURF2, fg=TEXT2).pack(side=tk.LEFT, padx=5)
        btn = self._btn(row, next_text, next_cmd or self._next,
                        bg=next_bg, fg=next_fg, disabled=next_disabled)
        btn.pack(side=tk.LEFT, padx=5)
        return btn

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 0 — Welcome
    # ══════════════════════════════════════════════════════════════════════════

    def _step_welcome(self):
        self._dots(self)

        ctk.CTkLabel(self, text="🎮", fg_color="transparent",
                     font=T.retro_font(34)).pack(pady=(10, 4))
        ctk.CTkLabel(self, text="Welcome to GameBeats", fg_color="transparent",
                     text_color=TEXT, font=T.serif_font(30, "bold")).pack()
        ctk.CTkLabel(self,
                     text="Plays music that matches your game's vibe — automatically.\n"
                          "Setup takes about 2 minutes.",
                     fg_color="transparent", text_color=TEXT2,
                     font=T.retro_font(15), wraplength=340,
                     justify="center").pack(pady=(4, 14))

        features = [
            ("🎮", "Detects your active game"),
            ("🎵", "Plays mood-matched music on Spotify"),
            ("🤫", "Only plays when game isn't playing audio"),
            ("⚡", "Runs silently in the background"),
        ]
        for icon, desc in features:
            row = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
            row.pack(fill=tk.X, padx=40, pady=2)
            ctk.CTkLabel(row, text=icon, fg_color="transparent",
                         font=T.retro_font(15)).pack(side=tk.LEFT, padx=10, pady=8)
            ctk.CTkLabel(row, text=desc, fg_color="transparent",
                         text_color=TEXT, font=T.retro_font(15)).pack(side=tk.LEFT, pady=8)

        ctk.CTkFrame(self, fg_color="transparent", height=20, corner_radius=0).pack()

        def _go_next():
            print("ARROW CLICKED - going to step", self._step + 1)
            self._next()

        ctk.CTkButton(self, text="  ❯  ", command=_go_next,
                      fg_color=ACCENT, text_color=BG,
                      hover_color=T.ACCENT_HOV,
                      font=T.serif_font(30, "bold"),
                      corner_radius=50, width=80, height=56).pack()

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 1 — Create Spotify App
    # ══════════════════════════════════════════════════════════════════════════

    def _step_create_app(self):
        self._dots(self)
        self._hero(self, "🔑", "Create a free Spotify app",
                   "GameBeats controls Spotify on your behalf.\n"
                   "This needs a free developer app — it only takes a minute.")

        steps = [
            ("1", "Open the Spotify Dashboard",
             "developer.spotify.com/dashboard",
             "https://developer.spotify.com/dashboard"),
            ("2", 'Click "Create app"',
             'Any name works — e.g. "GameBeats"', None),
            ("3", "Add this exact Redirect URI",
             REDIRECT_URI, None),
            ("4", "Copy your Client ID & Secret",
             "You'll paste them on the next screen", None),
        ]

        for step in steps:
            num, title, detail, url = step
            card = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
            card.pack(fill=tk.X, padx=40, pady=3)

            # Badge
            badge = ctk.CTkFrame(card, fg_color=ACCENT, width=28, height=28,
                                  corner_radius=0)
            badge.pack(side=tk.LEFT, padx=(12, 10), pady=12)
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text=num, fg_color="transparent",
                         text_color=BG, font=T.pixel_font(9, "bold")).place(
                relx=.5, rely=.5, anchor="center")

            col = ctk.CTkFrame(card, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
            col.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10)
            ctk.CTkLabel(col, text=title, fg_color="transparent",
                         text_color=TEXT, font=T.pixel_font(9, "bold"),
                         anchor="w").pack(anchor=tk.W)

            if url:
                lnk = ctk.CTkLabel(col, text=detail, fg_color="transparent",
                                   text_color=ACCENT, font=T.retro_font(14),
                                   cursor="hand2", anchor="w")
                lnk.pack(anchor=tk.W)
                lnk.bind("<Button-1>", lambda e, u=url: _open_url_hidden(u))
            else:
                if num == "3":
                    uri_row = ctk.CTkFrame(col, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
                    uri_row.pack(anchor=tk.W)
                    uri_lbl = ctk.CTkLabel(uri_row, text=REDIRECT_URI,
                                           fg_color=SURF3, text_color=ACCENT,
                                           font=T.retro_font(14), corner_radius=0)
                    uri_lbl.pack(side=tk.LEFT, padx=(0, 6), ipadx=8, ipady=3)
                    self._copy_lbl = ctk.CTkLabel(uri_row, text="📋 Copy",
                                                   fg_color="transparent",
                                                   text_color=TEXT2,
                                                   font=T.retro_font(14), cursor="hand2")
                    self._copy_lbl.pack(side=tk.LEFT)
                    self._copy_lbl.bind("<Button-1>", self._copy_uri)
                    warn_row = ctk.CTkFrame(col, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
                    warn_row.pack(anchor=tk.W, pady=(3, 0))
                    ctk.CTkLabel(warn_row, text="⚠  Must be 127.0.0.1 — NOT localhost",
                                 fg_color="transparent", text_color=AMBER,
                                 font=T.pixel_font(7, "bold")).pack(side=tk.LEFT)
                else:
                    ctk.CTkLabel(col, text=detail, fg_color="transparent",
                                 text_color=TEXT2, font=T.retro_font(14),
                                 anchor="w").pack(anchor=tk.W)

        btn_row = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        btn_row.pack(pady=(14, 0))
        ctk.CTkButton(btn_row, text="Open Dashboard ↗",
                      command=lambda: _open_url_hidden("https://developer.spotify.com/dashboard"),
                      fg_color=SURF2, text_color=ACCENT, hover_color=SURF3,
                      font=T.pixel_font(9, "bold"), corner_radius=0,
                      height=38, width=180).pack()

        self._nav_row(self, next_text="I've done this →")

    def _copy_uri(self, e=None):
        self.clipboard_clear()
        self.clipboard_append(REDIRECT_URI)
        self._copy_lbl.configure(text="✓ Copied!", text_color=ACCENT)
        self.after(2200, lambda: self._copy_lbl.configure(text="📋 Copy", text_color=TEXT2))

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 2 — Enter credentials
    # ══════════════════════════════════════════════════════════════════════════

    def _step_credentials(self):
        self._dots(self)
        self._hero(self, "📋", "Paste your credentials",
                   "Open your app on the Spotify Dashboard\nand copy the Client ID and Client Secret.")

        form = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        form.pack(fill=tk.X, padx=44)

        # Client ID
        ctk.CTkLabel(form, text="Client ID", fg_color="transparent",
                     text_color=TEXT2, font=T.retro_font(15)).pack(anchor=tk.W, pady=(0, 3))
        self._cid_entry = ctk.CTkEntry(form, textvariable=self._cid,
                                        fg_color=SURF2, border_color=BORDER,
                                        text_color=TEXT, corner_radius=0,
                                        font=T.retro_font(16), height=44)
        self._cid_entry.pack(fill=tk.X, pady=(0, 12))

        # Client Secret
        ctk.CTkLabel(form, text="Client Secret", fg_color="transparent",
                     text_color=TEXT2, font=T.retro_font(15)).pack(anchor=tk.W, pady=(0, 3))
        sec_row = ctk.CTkFrame(form, fg_color="transparent", corner_radius=0)
        sec_row.pack(fill=tk.X)
        self._sec_entry = ctk.CTkEntry(sec_row, textvariable=self._csec,
                                        fg_color=SURF2, border_color=BORDER,
                                        text_color=TEXT, corner_radius=0,
                                        font=T.retro_font(16), height=44, show="•")
        self._sec_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        eye = ctk.CTkButton(sec_row, text="👁", width=44, height=44,
                             fg_color=SURF2, text_color=TEXT2, hover_color=SURF3,
                             corner_radius=0, font=T.retro_font(18),
                             command=self._toggle_sec)
        eye.pack(side=tk.LEFT, padx=(4, 0))
        self._show_sec = False

        self._cred_err = ctk.CTkLabel(form, text="", fg_color="transparent",
                                       text_color=RED, font=T.retro_font(15))
        self._cred_err.pack(anchor=tk.W, pady=(8, 0))

        self._nav_row(self, next_text="Next →", next_cmd=self._validate_creds)

    def _toggle_sec(self):
        self._show_sec = not self._show_sec
        self._sec_entry.configure(show="" if self._show_sec else "•")

    def _validate_creds(self):
        cid  = self._cid.get().strip()
        csec = self._csec.get().strip()
        if len(cid) < 20:
            self._cred_err.configure(text="⚠  Client ID looks too short — check and paste again")
            return
        if len(csec) < 20:
            self._cred_err.configure(text="⚠  Client Secret looks too short — check and paste again")
            return
        self._cred_err.configure(text="")
        self._next()

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 3 — Connect / OAuth
    # ══════════════════════════════════════════════════════════════════════════

    def _step_connect(self):
        self._dots(self)
        self._hero(self, "🔗", "Connect to Spotify",
                   "Click the button below — your browser will open\n"
                   "and ask you to log in to Spotify.")

        # Quick checklist
        chk = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
        chk.pack(fill=tk.X, padx=44, pady=(0, 16))
        ctk.CTkLabel(chk, text="Before clicking, make sure your Spotify app has:",
                     fg_color="transparent", text_color=TEXT2,
                     font=T.pixel_font(8, "bold")).pack(anchor=tk.W, padx=12, pady=(8, 4))
        for line in [
            "✓  Redirect URI set to:  http://127.0.0.1:8888/callback",
            "✗  Remove any  http://localhost:8888/callback  entries",
            "✗  Remove any  https://localhost:8888/callback  entries",
        ]:
            color = ACCENT if line.startswith("✓") else RED
            ctk.CTkLabel(chk, text=line, fg_color="transparent",
                         text_color=color, font=T.retro_font(14), anchor="w").pack(
                fill=tk.X, padx=12, pady=2)
        ctk.CTkFrame(chk, fg_color="transparent", height=8, corner_radius=0).pack()

        self._conn_status = ctk.CTkLabel(self, text="", fg_color="transparent",
                                          text_color=TEXT2, font=T.retro_font(16),
                                          wraplength=360)
        self._conn_status.pack(pady=(0, 8))

        self._spinner = ctk.CTkLabel(self, text="", fg_color="transparent",
                                      text_color=ACCENT, font=T.retro_font(24))
        self._spinner.pack()

        self._conn_btn = ctk.CTkButton(self, text="Connect Spotify ↗",
                                        command=self._do_connect,
                                        fg_color=ACCENT, text_color=BG,
                                        hover_color=T.ACCENT_HOV,
                                        font=T.pixel_font(10, "bold"),
                                        corner_radius=0, height=52, width=220)
        self._conn_btn.pack(pady=(18, 0))

        nav = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        nav.pack(pady=(16, 0))
        ctk.CTkButton(nav, text="← Back", command=self._back,
                      fg_color=SURF2, text_color=TEXT2, hover_color=SURF3,
                      font=T.pixel_font(9, "bold"), corner_radius=0,
                      height=38, width=100).pack(side=tk.LEFT, padx=5)
        self._finish_btn = ctk.CTkButton(nav, text="Finish Setup →",
                                          command=self._finish,
                                          fg_color=SURF3, text_color=TEXT3,
                                          hover_color=SURF4,
                                          font=T.pixel_font(9, "bold"),
                                          corner_radius=0, height=38, width=140,
                                          state="disabled")
        self._finish_btn.pack(side=tk.LEFT, padx=5)

    def _do_connect(self):
        cid  = self._cid.get().strip()
        csec = self._csec.get().strip()
        self._auth = self._SpotifyAuth(cid, csec)
        self._conn_btn.configure(text="Opening browser…", state="disabled")
        self._conn_status.configure(text="Waiting for you to log in…", text_color=AMBER)
        self._spinning = True
        self._spin_chars = ["◐", "◓", "◑", "◒"]
        self._spin_i = 0
        self._animate()
        self._auth.start_auth_flow(
            on_complete=lambda ok: self.after(0, lambda: self._on_auth(ok)))

    def _animate(self):
        if not self._spinning:
            return
        self._spinner.configure(text=self._spin_chars[self._spin_i % 4])
        self._spin_i += 1
        self.after(200, self._animate)

    def _on_auth(self, ok):
        self._spinning = False
        self._spinner.configure(text="")
        if ok:
            self._spotify = self._SpotifyController(self._auth)
            self._conn_status.configure(text="✓  Connected! Click Finish Setup →",
                                        text_color=ACCENT)
            self._conn_btn.configure(text="✓ Connected", fg_color=T.ACCENT_BG,
                                     state="disabled")
            self._finish_btn.configure(state="normal", fg_color=ACCENT,
                                       text_color=BG, hover_color=T.ACCENT_HOV)
        else:
            self._conn_status.configure(
                text="✗  Auth failed. Check your credentials and try again.", text_color=RED)
            self._conn_btn.configure(text="Try Again ↗", state="normal")

    def _finish(self):
        if not self._spotify:
            return
        import json
        cid  = self._cid.get().strip()
        csec = self._csec.get().strip()
        config = {"client_id": cid, "client_secret": csec, "setup_done": True}
        with open(self._config_file, "w") as f:
            json.dump(config, f, indent=2)
        self._auth.save(self._tokens_file)
        self._next()

    # ══════════════════════════════════════════════════════════════════════════
    #  STEP 4 — Done 🎉
    # ══════════════════════════════════════════════════════════════════════════

    def _step_done(self):
        self._dots(self)

        ctk.CTkLabel(self, text="🎉", fg_color="transparent",
                     font=T.retro_font(54)).pack(pady=(48, 6))
        ctk.CTkLabel(self, text="You're all set!", fg_color="transparent",
                     text_color=TEXT, font=T.serif_font(32, "bold")).pack()
        ctk.CTkLabel(self,
                     text="GameBeats is ready.\nLaunch a game and music starts automatically.",
                     fg_color="transparent", text_color=TEXT2,
                     font=T.retro_font(16), justify="center", wraplength=330).pack(pady=(8, 30))

        tips = [
            ("🎮", "Start a game — music kicks in automatically"),
            ("🎛️", "Control playback from the Player tab"),
            ("🎵", "Browse and play your playlists"),
        ]
        for icon, tip in tips:
            row = ctk.CTkFrame(self, fg_color=SURF2, corner_radius=0, border_width=1, border_color=BORDER)
            row.pack(fill=tk.X, padx=52, pady=3)
            ctk.CTkLabel(row, text=icon, fg_color="transparent",
                         font=T.retro_font(18)).pack(side=tk.LEFT, padx=12, pady=9)
            ctk.CTkLabel(row, text=tip, fg_color="transparent",
                         text_color=TEXT, font=T.retro_font(15)).pack(side=tk.LEFT, pady=9)

        ctk.CTkButton(self, text="Open GameBeats →",
                      command=self._complete,
                      fg_color=ACCENT, text_color=BG,
                      hover_color=T.ACCENT_HOV,
                      font=T.pixel_font(10, "bold"),
                      corner_radius=0, height=52, width=220).pack(pady=16)

    def _complete(self):
        self.place_forget()
        try:
            self._app.geometry(self._orig_geometry)
        except Exception:
            pass
        self._on_complete(self._auth, self._spotify)