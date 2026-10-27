import json
import os
import sys
import time
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
from ui.puppy_gif import (
    PUPPY_BOB_GIF,
    PUPPY_CHANGE_GIF,
    PUPPY_PAUSE_GIF,
    PUPPY_THINKING_GIF,
    fit_frame,
    frame_index_at,
    load_gif_frames,
    normalize_animation_states,
    thinking_frame_index,
)

BG = T.BG
SURFACE = T.SURFACE
ACCENT = T.ACCENT
ACCENT2 = T.ACCENT2
TEXT = T.TEXT
TEXT_SEC = T.TEXT_MUTED
TRANSPARENT_KEY = "#010203"

NOTIFIER_CARD_BG = T.SURFACE
NOTIFIER_CARD_BORDER = T.WOOD
NOTIFIER_TEXT = T.TEXT
NOTIFIER_TEXT_SUB = T.GOLD
NOTIFIER_TEXT_MUTED = T.TEXT_MUTED
NOTIFIER_BTN_HOVER = T.SURFACE3

# The desktop singer and the in-room mascot are both driven by the same
# hand-authored headset-wearing bobbing-head GIF. Its frames share one cropped
# canvas, so the window and room baseline stay put while the head and ears move.
PUPPY_OVERLAY_GIF = PUPPY_BOB_GIF
PUPPY_OVERLAY_STATE_GIFS = (
    ("idle", PUPPY_BOB_GIF),
    ("pause", PUPPY_PAUSE_GIF),
    ("change", PUPPY_CHANGE_GIF),
    ("thinking", PUPPY_THINKING_GIF),
)
PUPPY_IDLE_FRAME = "idle_0"
# The GIFs are authored at 120 ms per frame. Keep that cadence so the bob reads
# at the same speed in the room and in the desktop overlay.
PUPPY_ANIMATION_INTERVAL = 120
# Short presses toggle playback; holding a little longer asks for another mix.
PUPPY_LONG_CLICK_MS = 650
PUPPY_CLICK_MOVE_TOLERANCE = 7
# Re-asserting topmost restacks the layered window; doing that on every audio
# meter tick visibly hitched the animation.  Twice per second is plenty to stay
# above a fullscreen game, so re-assert on a much slower cadence instead.
PUPPY_TOPMOST_REASSERT_SEC = 4.0
PUPPY_OVERLAY_ALPHA = 0.80


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


def _load_pixel_puppy_photo(name, max_size):
    """Load the hard-edged idle frame for the notifier card."""
    if not HAS_PIL:
        return None
    path = T.assets_dir() / "puppy_design" / "anim" / f"{name}.png"
    if not path.exists():
        return None
    try:
        img = Image.open(path).convert("RGBA")
        max_w, max_h = max_size
        scale = max(1, min(int(max_w // img.width), int(max_h // img.height)))
        if scale != 1:
            img = img.resize(
                (img.width * scale, img.height * scale),
                Image.Resampling.NEAREST,
            )
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def _build_singing_photos(max_size):
    """Load the bobbing-head GIF as transparent, consistently-sized photos.

    The source GIF is cropped to one shared box before scaling, so the overlay
    window itself never moves or resizes between beats.  Only the artwork inside
    the frame bobs.
    """
    if not HAS_PIL:
        return []

    path = T.assets_dir() / PUPPY_OVERLAY_GIF
    try:
        frames, _durations = load_gif_frames(path)
    except Exception:
        return []
    if not frames:
        return []

    photos = []
    for frame in frames:
        fitted = fit_frame(frame, max_size)
        if fitted is None:
            continue
        photos.append(ImageTk.PhotoImage(fitted))
    return photos


def _build_overlay_animation_photos(max_size=(170, 170)):
    """Load every desktop-puppy state on one transparent canvas.

    The idle bob is used as the size reference, then the pause/resume and
    playlist-change GIFs are scaled by the same factor and bottom-centre
    aligned.  Switching state therefore changes the pose, never the puppy's
    size or resting position.
    """
    if not HAS_PIL:
        return {}, {}, (0, 0)

    raw = {}
    for name, filename in PUPPY_OVERLAY_STATE_GIFS:
        path = T.assets_dir() / filename
        if not path.exists():
            continue
        try:
            frames, durations = load_gif_frames(path)
        except Exception:
            continue
        if frames:
            raw[name] = (frames, durations)

    if "idle" not in raw:
        return {}, {}, (0, 0)
    try:
        normalized, canvas = normalize_animation_states(
            raw,
            reference="idle",
            target_size=max_size,
            bottom_pad=0,
            margin=2,
        )
    except Exception:
        return {}, {}, (0, 0)

    photos = {}
    durations = {}
    for name, (frames, frame_durations) in normalized.items():
        try:
            photos[name] = [ImageTk.PhotoImage(frame) for frame in frames]
        except Exception:
            continue
        durations[name] = frame_durations
    if not photos.get("idle"):
        return {}, {}, (0, 0)
    return photos, durations, canvas


def _puppy_pos_file() -> str:
    """Path to the tiny JSON file that remembers the puppy's position."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[2]
    return str(base / "puppy_position.json")


class PuppySingingOverlay:
    def __init__(
        self,
        root,
        *,
        corner="bottom-right",
        anchor_getter=None,
        on_toggle_play_pause=None,
        on_try_another=None,
        get_playing=None,
    ):
        self._root = root
        self._corner = corner
        self._anchor_getter = anchor_getter
        self._on_toggle_play_pause = on_toggle_play_pause
        self._on_try_another = on_try_another
        self._get_playing = get_playing
        self._win = None
        self._label = None
        self._photos = []
        self._photos_by_state = {}
        self._durations_by_state = {}
        self._canvas_size = (0, 0)
        self._state = "idle"
        self._durations = ()
        self._idx = 0
        self._after = None
        self._fade_after = None
        self._anim_next = None
        self._state_started = 0.0
        self._active_reverse = False
        self._active_hold = False
        self._active_loops = 0
        self._base_paused = False
        # A pause locks the overlay to its drooped pose.  Unlike _base_paused,
        # this flag is set only for a real user/game pause, not for the brief
        # silence while a new playlist is loading.  While locked, long-press
        # "change" clips and the idle bob are not allowed to start.
        self._animation_locked = False
        self._last_raise = 0.0
        self._visible = False
        self._drag_x = 0
        self._drag_y = 0
        # The deck anchor is the default. A position is only treated as a
        # manual override after the user actually drags in this session;
        # otherwise a stale on-disk position can strand the puppy in a screen
        # corner instead of on the player dock.
        self._custom_pos = None
        self._saved_pos = self._load_pos()
        self._dragged = False
        # Press gesture state: a short release toggles playback, a long hold
        # asks for another playlist, and Ctrl + movement moves the window.
        self._press_active = False
        self._press_ctrl = False
        self._press_moved = False
        self._long_fired = False
        self._long_job = None
        self._press_root = (0, 0)
        self._drag_origin = (0, 0)
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
        win.attributes("-alpha", 0.0)
        win.attributes("-topmost", True)
        try:
            win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except Exception:
            pass
        win.withdraw()

        self._photos_by_state, self._durations_by_state, self._canvas_size = (
            _build_overlay_animation_photos((170, 170))
        )
        self._photos = list(self._photos_by_state.get("idle") or ())
        self._durations = tuple(self._durations_by_state.get("idle") or ())
        if self._photos:
            self._label = tk.Label(
                win,
                image=self._photos[0],
                bg=TRANSPARENT_KEY,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
        else:
            self._label = tk.Label(
                win,
                text="\u266a",
                font=T.retro_font(40, "bold"),
                fg=ACCENT,
                bg=TRANSPARENT_KEY,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
        self._label.pack()

        self._label.bind("<ButtonPress-1>", self._on_press)
        self._label.bind("<B1-Motion>", self._on_motion)
        self._label.bind("<ButtonRelease-1>", self._on_release)

        win.after(80, self._noactivate_safe)

    def _place(self):
        if self._win is None:
            return
        # If the user dragged it this session, use their position. A saved
        # position from a previous session is only a fallback when no anchor
        # is available.
        if self._custom_pos is not None and self._dragged:
            x, y = self._custom_pos
            self._win.geometry(f"+{x}+{y}")
            return
        if self._anchor_getter is not None:
            try:
                pos = self._anchor_getter()
            except Exception:
                pos = None
            if pos:
                x, y = pos
                self._win.geometry(f"+{int(x)}+{int(y)}")
                return
        if self._saved_pos is not None:
            x, y = self._saved_pos
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

    def _state_frames(self, state):
        frames = getattr(self, "_photos_by_state", {}).get(state)
        durations = getattr(self, "_durations_by_state", {}).get(state)
        if not frames:
            frames = getattr(self, "_photos", [])
            durations = getattr(self, "_durations", ())
        frames = list(frames or ())
        if not durations:
            durations = (PUPPY_ANIMATION_INTERVAL,) * len(frames)
        return frames, tuple(durations)

    def _draw_current_frame(self):
        if self._label is None:
            return
        frames, _durations = self._state_frames(getattr(self, "_state", "idle"))
        if not frames:
            return
        self._idx = max(0, min(int(getattr(self, "_idx", 0)), len(frames) - 1))
        try:
            self._label.configure(image=frames[self._idx])
        except Exception:
            pass

    def _set_state(
        self,
        state,
        *,
        reverse=False,
        hold=False,
        loops=0,
        start_at_end=False,
        start_anim=True,
    ):
        frames, _durations = self._state_frames(state)
        if not frames:
            return
        if state not in getattr(self, "_photos_by_state", {}):
            state = "idle"
        self._cancel_anim()
        self._state = state
        self._active_reverse = bool(reverse)
        self._active_hold = bool(hold)
        self._active_loops = max(0, int(loops or 0))
        self._state_started = time.monotonic()
        if start_at_end:
            self._idx = 0 if reverse else len(frames) - 1
        else:
            self._idx = len(frames) - 1 if reverse else 0
        self._draw_current_frame()
        self._anim_next = None
        if start_anim and self._visible:
            self._animate()

    def _hold_pause_pose(self, *, animate=False):
        """Freeze on the final drooped frame without restarting a held pose."""
        if (
            getattr(self, "_state", "idle") == "pause"
            and getattr(self, "_active_hold", False)
            and not getattr(self, "_active_reverse", False)
        ):
            return
        if animate and self._visible:
            self._play_pause_animation(False)
        else:
            self._set_state(
                "pause", hold=True, loops=1,
                start_at_end=True, start_anim=False,
            )

    def set_animation_locked(self, locked, *, animate=False):
        """Remember a real pause and stop idle/change animations from starting.

        A change clip that is already running is still allowed to finish; when
        it ends, the lock makes it settle into the drooped pause pose instead
        of the idle bob.
        """
        locked = bool(locked)
        self._animation_locked = locked
        if not locked:
            return
        self._base_paused = True
        if getattr(self, "_state", "idle") == "change":
            return
        self._hold_pause_pose(animate=animate)

    def _play_pause_animation(self, playing):
        """Pause droops and holds; resume plays that same motion backwards."""
        playing = bool(playing)
        self._base_paused = not playing
        self._animation_locked = not playing
        if playing:
            self._set_state("pause", reverse=True, hold=False, loops=1)
        else:
            self._set_state("pause", reverse=False, hold=True, loops=1)

    def _change_animation_active(self):
        """True while the current headset-swap clip is still playing."""
        if getattr(self, "_state", "idle") != "change":
            return False
        frames, durations = self._state_frames("change")
        if not frames:
            return False
        total = sum(durations) or len(frames) * PUPPY_ANIMATION_INTERVAL
        if total <= 0:
            return True
        elapsed = max(0.0, (time.monotonic() - self._state_started) * 1000.0)
        loops = max(1, int(getattr(self, "_active_loops", 1) or 1))
        return elapsed < total * loops

    def play_change_animation(self):
        # A long-press starts this clip directly and the app's try-another
        # callback asks for it again a moment later.  Never restart an
        # already-running change clip: one long-press must produce one clip.
        if self._change_animation_active():
            return True
        # A long-press must not start the headset-swap clip while the music is
        # paused.  Keep the drooped lock pose instead; the caller can still
        # perform its playlist action.
        if getattr(self, "_animation_locked", False):
            if getattr(self, "_state", "idle") != "change":
                self._hold_pause_pose(animate=False)
            return False
        if not self._visible:
            return False
        self._set_state("change", loops=1)
        return True

    def play_thinking_animation(self):
        """Loop the thinking clip until the caller swaps or pauses.

        A real pause lock keeps the drooped pose.  The app clears the lock
        before calling this for the transient playlist-switch pause.
        """
        frames, _durations = self._state_frames("thinking")
        if not frames or "thinking" not in getattr(self, "_photos_by_state", {}):
            # Older asset bundles keep the previous one-shot change clip.
            return self.play_change_animation()
        if getattr(self, "_animation_locked", False):
            return False
        if not self._visible:
            return False
        if getattr(self, "_state", "idle") == "thinking":
            return True
        self._set_state("thinking", loops=0)
        return True

    def set_playback_state(self, playing, *, animate=True):
        """Keep the overlay's pose in sync with app/audio pause changes."""
        playing = bool(playing)
        if playing:
            # Audio/play state is the source of truth for unlocking the pose.
            self._animation_locked = False
            if self._base_paused:
                self._base_paused = False
                # Let a playlist-change reaction finish instead of cutting it
                # off the instant the new track starts.
                if getattr(self, "_state", "idle") == "change":
                    return
                if animate and self._visible:
                    self._play_pause_animation(True)
                elif getattr(self, "_state", "idle") == "pause":
                    self._set_state("idle", loops=0)
        else:
            if not self._base_paused:
                self._base_paused = True
                if getattr(self, "_state", "idle") == "change":
                    return
                if animate and self._visible:
                    self._play_pause_animation(False)
                else:
                    self._set_state(
                        "pause", hold=True, loops=1,
                        start_at_end=True, start_anim=False,
                    )
            elif getattr(self, "_animation_locked", False):
                self._hold_pause_pose(animate=False)

    def _query_playing(self):
        if callable(self._get_playing):
            try:
                return bool(self._get_playing())
            except Exception:
                pass
        return not bool(getattr(self, "_base_paused", False))

    def _handle_click(self):
        playing = self._query_playing()
        target_paused = playing
        had_callback = callable(self._on_toggle_play_pause)
        if had_callback:
            try:
                accepted = self._on_toggle_play_pause()
            except Exception:
                accepted = False
            # A refused toggle (another command still in flight) must not
            # leave the puppy showing a pose the music is not in.
            if accepted is False:
                return
        # The app's pause/visibility callback may already have driven this
        # exact transition.  Do not restart the clip on top of it.
        if (
            had_callback
            and bool(getattr(self, "_base_paused", False)) == target_paused
        ):
            return
        # A real pause lock is released only by confirmed playback.  Do not
        # start the reverse/headset-on clip just because the app accepted the
        # resume request; a failed resume must stay frozen in the pause pose.
        if (
            had_callback
            and not target_paused
            and getattr(self, "_animation_locked", False)
        ):
            return
        # A playlist-change reaction owns the overlay until it ends.  A
        # pause/resume click during that clip may update the resting state,
        # but must not cut the change animation short.
        if getattr(self, "_state", "idle") == "change":
            self._base_paused = target_paused
            return
        self._play_pause_animation(not playing)

    def _cancel_long_job(self):
        job = getattr(self, "_long_job", None)
        if job is not None and self._win is not None:
            try:
                self._win.after_cancel(job)
            except Exception:
                pass
        self._long_job = None

    def _on_press(self, event):
        self._cancel_long_job()
        self._press_active = True
        self._press_ctrl = bool(int(getattr(event, "state", 0) or 0) & 0x0004)
        self._press_moved = False
        self._long_fired = False
        self._press_root = (int(event.x_root), int(event.y_root))
        if self._win is not None:
            try:
                self._drag_origin = (self._win.winfo_x(), self._win.winfo_y())
            except Exception:
                self._drag_origin = (0, 0)
        try:
            self._drag_x = int(event.x)
            self._drag_y = int(event.y)
        except Exception:
            self._drag_x = self._drag_y = 0
        if self._label is not None:
            try:
                self._label.configure(
                    cursor="fleur" if self._press_ctrl else "hand2"
                )
            except Exception:
                pass
        if not self._press_ctrl and self._win is not None:
            try:
                self._long_job = self._win.after(
                    PUPPY_LONG_CLICK_MS, self._fire_long_click
                )
            except Exception:
                self._long_job = None

    def _on_motion(self, event):
        if not self._press_active or self._win is None:
            return
        dx = int(event.x_root) - self._press_root[0]
        dy = int(event.y_root) - self._press_root[1]
        ctrl = bool(
            self._press_ctrl
            or (int(getattr(event, "state", 0) or 0) & 0x0004)
        )
        if ctrl:
            if not self._press_ctrl:
                # Let Ctrl pressed after mouse-down turn the gesture into a
                # move instead of a long-click.
                self._press_ctrl = True
                self._cancel_long_job()
                if self._label is not None:
                    try:
                        self._label.configure(cursor="fleur")
                    except Exception:
                        pass
            if max(abs(dx), abs(dy)) < 2:
                return
            x = self._drag_origin[0] + dx
            y = self._drag_origin[1] + dy
            try:
                self._win.geometry(f"+{x}+{y}")
            except Exception:
                return
            self._custom_pos = (x, y)
            self._dragged = True
            self._press_moved = True
            return
        if max(abs(dx), abs(dy)) > PUPPY_CLICK_MOVE_TOLERANCE:
            self._press_moved = True
            self._cancel_long_job()

    def _on_release(self, _event=None):
        if not getattr(self, "_press_active", False):
            return
        self._cancel_long_job()
        ctrl = self._press_ctrl
        moved = self._press_moved
        long_fired = self._long_fired
        if ctrl and moved and self._custom_pos is not None:
            self._save_pos(*self._custom_pos)
        self._press_active = False
        self._press_ctrl = False
        self._press_moved = False
        self._long_fired = False
        if self._label is not None:
            try:
                self._label.configure(cursor="hand2")
            except Exception:
                pass
        if not ctrl and not moved and not long_fired:
            self._handle_click()

    def _fire_long_click(self):
        self._long_job = None
        if (
            not getattr(self, "_press_active", False)
            or getattr(self, "_press_ctrl", False)
            or getattr(self, "_press_moved", False)
        ):
            return
        self._long_fired = True
        # A long press starts loading a new playlist, not a completed swap.
        # The app plays the headset-swap clip once the new audio starts.
        self.play_thinking_animation()
        if callable(self._on_try_another):
            try:
                self._on_try_another()
            except Exception:
                pass

    def _finish_reaction(self):
        if (
            getattr(self, "_animation_locked", False)
            or getattr(self, "_base_paused", False)
        ):
            self._set_state(
                "pause", hold=True, loops=1,
                start_at_end=True, start_anim=False,
            )
        else:
            self._set_state("idle", loops=0)

    def _update_reaction_frame(self, now):
        frames, durations = self._state_frames(getattr(self, "_state", "idle"))
        if not frames:
            return "finished"
        total = sum(durations) or len(frames) * PUPPY_ANIMATION_INTERVAL
        elapsed = max(0.0, (now - self._state_started) * 1000.0)
        loops = int(getattr(self, "_active_loops", 0) or 0)
        if loops and elapsed >= total * loops:
            if getattr(self, "_active_hold", False):
                idx = 0 if self._active_reverse else len(frames) - 1
                if idx != self._idx:
                    self._idx = idx
                    self._draw_current_frame()
                return "hold"
            self._finish_reaction()
            return "finished"
        if getattr(self, "_state", "idle") == "thinking":
            idx = thinking_frame_index(elapsed, durations)
        else:
            offset = elapsed % total
            idx = frame_index_at(offset, durations)
            if getattr(self, "_active_reverse", False):
                idx = len(frames) - 1 - idx
        if idx != self._idx:
            self._idx = idx
            self._draw_current_frame()
        return "active"

    def _noactivate_safe(self):
        if self._win is None:
            return
        try:
            _apply_noactivate(self._win.winfo_id())
        except Exception:
            pass

    def show(self):
        if self._win is None:
            self._build()
        if self._win is None:
            return
        if self._visible:
            # The window may have been pushed behind a fullscreen game even
            # though we still consider it visible.  Re-assert occasionally,
            # not on every audio-meter tick: restacking the layered window is
            # what made the animation hitch.
            self._ensure_topmost()
            return
        self._visible = True
        self._idx = 0
        self._anim_next = None
        self._cancel_fade()
        try:
            win = self._win
            self._place()
            win.attributes("-alpha", 0.0)
            win.deiconify()
            win.update_idletasks()
            win.lift()
            win.attributes("-topmost", True)
            self._noactivate_safe()
            # Windows sometimes maps an override-redirect Toplevel under the
            # foreground window on the first pass. Re-lift shortly after.
            win.after(60, self._raise_safe)
            win.after(220, self._raise_safe)
            # Re-anchor after the window manager has finished laying out the
            # dock; the first anchor query can run before the deck geometry is
            # final and would otherwise leave the puppy in the corner.
            win.after(90, self._place)
            win.after(320, self._place)
        except Exception:
            pass
        self._fade_to(PUPPY_OVERLAY_ALPHA, 180)
        self._last_raise = time.monotonic()
        if (
            getattr(self, "_animation_locked", False)
            or getattr(self, "_base_paused", False)
        ):
            # Paused overlays stay visible so another click can resume them.
            self._set_state(
                "pause", hold=True, loops=1,
                start_at_end=True, start_anim=False,
            )
        else:
            self._set_state("idle", loops=0, start_anim=False)
            self._animate()

    def _ensure_topmost(self):
        """Keep an always-on-top overlay above fullscreen games, slowly.

        ``show()`` is called about twice per second while music plays.  Each
        ``lift``/``SetWindowPos`` restack used to repaint the layered window
        and visibly stutter the frame animation, so throttle it.
        """
        if self._win is None:
            return
        now = time.monotonic()
        if now - self._last_raise < PUPPY_TOPMOST_REASSERT_SEC:
            return
        self._last_raise = now
        self._raise_safe()

    def _raise_safe(self):
        if not self._visible or self._win is None:
            return
        try:
            win = self._win
            if not win.winfo_viewable():
                win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
            self._noactivate_safe()
        except Exception:
            pass

    def is_visible(self) -> bool:
        return bool(self._visible)

    def _cancel_anim(self):
        if self._after is not None and self._win is not None:
            try:
                self._win.after_cancel(self._after)
            except Exception:
                pass
        self._after = None

    def _cancel_fade(self):
        if self._fade_after is not None and self._win is not None:
            try:
                self._win.after_cancel(self._fade_after)
            except Exception:
                pass
        self._fade_after = None

    def _withdraw_now(self):
        self._fade_after = None
        if self._win is not None:
            try:
                self._win.withdraw()
            except Exception:
                pass

    def _fade_to(self, target: float, duration_ms: int, on_done=None):
        """Ease the overlay alpha toward *target* without ever snapping."""
        self._cancel_fade()
        if self._win is None:
            return
        try:
            start = float(self._win.attributes("-alpha"))
        except Exception:
            start = 0.0
        steps = max(1, int(duration_ms / 16))

        def step(n=0):
            self._fade_after = None
            if self._win is None:
                return
            frac = min(1.0, (n + 1) / steps)
            eased = 1.0 - (1.0 - frac) ** 3
            alpha = start + (target - start) * eased
            try:
                self._win.attributes("-alpha", max(0.0, min(1.0, alpha)))
            except Exception:
                pass
            if frac < 1.0:
                try:
                    self._fade_after = self._win.after(16, step, n + 1)
                except Exception:
                    pass
            elif on_done is not None:
                try:
                    on_done()
                except Exception:
                    pass

        try:
            self._fade_after = self._win.after(16, step, 0)
        except Exception:
            pass

    def hide(self, immediate: bool = False):
        self._visible = False
        self._cancel_anim()
        self._cancel_long_job()
        self._press_active = False
        if immediate or self._win is None:
            self._cancel_fade()
            self._withdraw_now()
            return
        self._fade_to(0.0, 150, self._withdraw_now)

    def _animate(self):
        if not self._visible or self._win is None or self._label is None:
            return
        now = time.monotonic()
        state = getattr(self, "_state", "idle")
        state_photos = getattr(self, "_photos_by_state", {}).get(state)
        if state != "idle" and state_photos:
            if not getattr(self, "_state_started", 0.0):
                self._state_started = now
            result = self._update_reaction_frame(now)
            if result == "finished":
                # _finish_reaction() has already switched to the resting state
                # and armed that state's animation.
                return
            if result == "hold":
                self._after = None
                return
            try:
                self._after = self._win.after(
                    max(5, PUPPY_ANIMATION_INTERVAL), self._animate
                )
            except Exception:
                pass
            return

        # Idle bobbing is forbidden while the pause lock is set.  A change
        # reaction is allowed to finish above, but the idle loop must never
        # start or continue underneath a pause.
        if getattr(self, "_animation_locked", False):
            self._hold_pause_pose(animate=False)
            return

        photos = getattr(self, "_photos", [])
        if not photos:
            photos = getattr(self, "_photos_by_state", {}).get("idle", [])
        if not photos:
            # Text fallback (Pillow or assets unavailable): nothing to cycle.
            return
        interval = max(0.01, PUPPY_ANIMATION_INTERVAL / 1000.0)
        if self._anim_next is None:
            self._anim_next = now + interval
        # If the main UI was busy for a long stretch, drop the missed beats
        # instead of bursting through them.
        if now - self._anim_next > 0.35:
            self._anim_next = now + interval
        advanced = 0
        while now >= self._anim_next and advanced < 3:
            self._idx = (self._idx + 1) % len(photos)
            self._anim_next += interval
            advanced += 1
        if advanced:
            try:
                self._label.configure(image=photos[self._idx])
            except Exception:
                return
        # Schedule against the wall-clock deadline so Tk timer drift, a heavy
        # room repaint, or a slow frame never stretches one beat.
        delay = int(round((self._anim_next - now) * 1000))
        try:
            self._after = self._win.after(max(5, delay), self._animate)
        except Exception:
            pass

    def close(self):
        self.hide(immediate=True)
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
            corner_radius=0,
            border_width=2,
            border_color=NOTIFIER_CARD_BORDER,
        )
        card.pack(padx=2, pady=2)

        ctk.CTkLabel(
            card,
            text="\u266a  SIDE A COMPLETE",
            font=T.pixel_font(8, "bold"),
            fg_color="transparent",
            text_color=T.MINT,
        ).pack(padx=18, pady=(12, 2))

        photo = _load_pixel_puppy_photo(PUPPY_IDLE_FRAME, (96, 96))
        if photo:
            self._puppy_photo = photo
            tk.Label(
                card,
                image=self._puppy_photo,
                bg=NOTIFIER_CARD_BG,
                bd=0,
                highlightthickness=0,
            ).pack(pady=(2, 2))
        else:
            ctk.CTkLabel(
                card,
                text="\u266a",
                font=T.retro_font(40, "bold"),
                fg_color="transparent",
                text_color=T.GOLD,
            ).pack(pady=(2, 2))

        ctk.CTkLabel(
            card,
            text="Playlist finished",
            font=T.serif_font(24),
            fg_color="transparent",
            text_color=NOTIFIER_TEXT,
        ).pack(padx=18)

        name = (self._playlist_name or "your playlist")[:28]
        ctk.CTkLabel(
            card,
            text=name,
            font=T.retro_font(17),
            fg_color="transparent",
            text_color=NOTIFIER_TEXT_SUB,
        ).pack(padx=18, pady=(2, 6))

        self._timer_lbl = ctk.CTkLabel(
            card,
            text="",
            font=T.pixel_font(8),
            fg_color="transparent",
            text_color=NOTIFIER_TEXT_MUTED,
        )
        self._timer_lbl.pack()

        btn_row = ctk.CTkFrame(card, fg_color="transparent", corner_radius=0)
        btn_row.pack(padx=14, pady=(10, 6), fill="x")

        self._play_next_btn = ctk.CTkButton(
            btn_row,
            text="\u25b6  PLAY NEXT",
            fg_color=ACCENT,
            text_color=T.BG,
            hover_color=T.ACCENT_HOV,
            corner_radius=0,
            height=36,
            border_width=2,
            border_color=T.WOOD,
            command=self._on_click_play_next,
            font=T.pixel_font(9, "bold"),
        )
        self._play_next_btn.pack(side=tk.LEFT, fill="x", expand=True)

        ctk.CTkButton(
            card,
            text="DISMISS",
            fg_color="transparent",
            text_color=NOTIFIER_TEXT_MUTED,
            hover_color=NOTIFIER_BTN_HOVER,
            corner_radius=0,
            height=26,
            command=self._on_click_dismiss,
            font=T.pixel_font(8),
        ).pack(pady=(0, 10))


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
