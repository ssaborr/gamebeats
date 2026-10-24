"""Deterministic frame selection for the in-room puppy.

The animator never touches canvas coordinates. It only chooses one of the
pre-authored 64x72 frames, which keeps the paws on the same baseline while the
rest of the character breathes, blinks, sings, and reacts.

The master clock runs at 30 Hz; every hold length in ``puppy_anim.json`` is an
even number of ticks, so the sprite advances on twos while UI easing can still
run on every tick.

The mouth is deliberately calmer than the UI clock.  A raw audio-meter sample
arrives twice per second and can sit right on a single threshold; switching on
that sample made the puppy look like it was vibrating.  The animator therefore
uses hysteresis (separate open/close levels) and a minimum state hold, and the
authored mouth holds are measured in several ticks rather than one or two.
"""

from __future__ import annotations


MOUTH_STATES = ("singing_open", "singing_closed", "singing_eyes_closed")


class PuppyAnimator:
    def __init__(self, spec: dict):
        if not spec or "states" not in spec:
            raise ValueError("puppy animation spec is missing states")
        self.spec = spec
        self.fps = int(spec.get("fps", 30) or 30)
        self.on_twos = int(spec.get("on_twos", 2) or 2)
        audio = spec.get("audio") or {}
        self.mouth_open_level = float(audio.get("open_level", 0.30))
        self.mouth_close_level = float(audio.get("close_level", 0.14))
        self.mouth_min_hold = max(1, int(audio.get("min_hold", 15)))
        self.mouth_frame_min_hold = max(1, int(audio.get("min_frame_hold", 6)))
        self._mouth_open = False
        self._last_frame = None
        self._last_frame_tick = 0
        self.mode = "idle"
        self.mode_start = 0
        self.state = "idle"
        self.state_start = 0

    # ── public API ───────────────────────────────────────────────────────────

    def set_mode(self, mode: str, tick: int) -> None:
        if mode != "singing" and mode not in self.spec["states"]:
            mode = "idle"
        if mode != self.mode:
            self.mode = mode
            self.mode_start = int(tick)
            self.state = None
            self.state_start = int(tick)
            # A new mode starts with a closed mouth; the first high sample can
            # then open it without inheriting a stale phrase from last time.
            self._mouth_open = False

    def frame(self, tick: int, mode: str | None = None,
              audio_level: float = 0.0, reduce_motion: bool = False) -> str:
        tick = int(tick)
        if mode is not None:
            self.set_mode(mode, tick)
        if reduce_motion:
            # A static frame per state is the whole reduce-motion contract:
            # no blink, breath, ear flick, mouth cycle, or head movement.
            state = "singing_closed" if self.mode == "singing" else self.mode
            frame = self._state_spec(state)["static"]
            self._last_frame = frame
            self._last_frame_tick = tick
            return frame

        candidate = self._choose_state(tick, audio_level)
        state = candidate
        # Hold every mouth pose for a readable beat.  The eyes-closed phrase
        # marker is scheduled, so it is allowed to break through immediately.
        if (
            candidate != "singing_eyes_closed"
            and candidate in MOUTH_STATES
            and self.state in MOUTH_STATES
            and candidate != self.state
            and tick > self.state_start
            and tick - self.state_start < self.mouth_min_hold
        ):
            state = self.state
        if state != self.state:
            self.state = state
            self.state_start = tick
        frame = self._frame_for_state(state, tick)
        if frame == self._last_frame:
            return frame
        # A state can end a frame or two after its next pose begins.  Without
        # this guard the second mouth pose appeared for a single rendered tick
        # before snapping shut, which read as a twitch.  Let the previous
        # mouth frame finish its beat; mode changes still cut immediately.
        if (
            state in MOUTH_STATES
            and self._last_frame is not None
            and tick > self._last_frame_tick
            and tick - self._last_frame_tick < self.mouth_frame_min_hold
        ):
            return self._last_frame
        self._last_frame = frame
        self._last_frame_tick = tick
        return frame

    # ── internals ────────────────────────────────────────────────────────────

    def _state_spec(self, state: str) -> dict:
        return self.spec["states"].get(state) or self.spec["states"]["idle"]

    def _choose_state(self, tick: int, audio_level: float) -> str:
        if self.mode == "singing":
            # Close the eyes for the last short beat of each six-second phrase.
            if (tick - self.mode_start) % 180 >= 150:
                return "singing_eyes_closed"
            level = float(audio_level or 0.0)
            # Two thresholds, not one: a meter that hovers near the boundary
            # must not flip the mouth on every sample.
            if self._mouth_open:
                if level <= self.mouth_close_level:
                    self._mouth_open = False
            elif level >= self.mouth_open_level:
                self._mouth_open = True
            return "singing_open" if self._mouth_open else "singing_closed"
        if self.mode in self.spec["states"]:
            return self.mode
        return "idle"

    def _frame_for_state(self, state: str, tick: int) -> str:
        spec = self._state_spec(state)
        frames = spec.get("frames") or ["idle_0"]
        holds = spec.get("hold") or [2]
        if len(holds) == 1:
            return frames[0]
        # Every state starts at its first authored frame.  Using global wall
        # time here made the first open pose last only until the next cycle
        # boundary, producing a one-frame mouth flap right after a transition.
        elapsed = max(0, tick - self.state_start)
        total = max(1, sum(int(v) for v in holds))
        offset = elapsed % total
        for frame, hold in zip(frames, holds):
            hold = max(1, int(hold))
            if offset < hold:
                return frame
            offset -= hold
        return frames[-1]
