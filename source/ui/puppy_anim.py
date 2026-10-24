"""Deterministic frame selection for the in-room puppy.

The animator never touches canvas coordinates. It only chooses one of the
pre-authored 64x72 frames, which keeps the paws on the same baseline while the
rest of the character breathes, blinks, sings, and reacts.

The master clock runs at 30 Hz; every hold length in ``puppy_anim.json`` is an
even number of ticks, so the sprite advances on twos while UI easing can still
run on every tick.
"""

from __future__ import annotations


class PuppyAnimator:
    def __init__(self, spec: dict):
        if not spec or "states" not in spec:
            raise ValueError("puppy animation spec is missing states")
        self.spec = spec
        self.fps = int(spec.get("fps", 30) or 30)
        self.on_twos = int(spec.get("on_twos", 2) or 2)
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

    def frame(self, tick: int, mode: str | None = None,
              audio_level: float = 0.0, reduce_motion: bool = False) -> str:
        tick = int(tick)
        if mode is not None:
            self.set_mode(mode, tick)
        if reduce_motion:
            # A static frame per state is the whole reduce-motion contract:
            # no blink, breath, ear flick, mouth cycle, or head movement.
            state = "singing_closed" if self.mode == "singing" else self.mode
            return self._state_spec(state)["static"]

        state = self._choose_state(tick, audio_level)
        if state != self.state:
            self.state = state
            self.state_start = tick
        return self._frame_for_state(state, tick)

    # ── internals ────────────────────────────────────────────────────────────

    def _state_spec(self, state: str) -> dict:
        return self.spec["states"].get(state) or self.spec["states"]["idle"]

    def _choose_state(self, tick: int, audio_level: float) -> str:
        if self.mode == "singing":
            # Close the eyes for the last short beat of each six-second phrase.
            if (tick - self.mode_start) % 180 >= 150:
                return "singing_eyes_closed"
            if float(audio_level or 0.0) >= 0.25:
                return "singing_open"
            return "singing_closed"
        if self.mode in self.spec["states"]:
            return self.mode
        return "idle"

    def _frame_for_state(self, state: str, tick: int) -> str:
        spec = self._state_spec(state)
        frames = spec.get("frames") or ["idle_0"]
        holds = spec.get("hold") or [2]
        if len(holds) == 1:
            return frames[0]
        if state in ("singing_open", "singing_closed", "singing_eyes_closed"):
            # Mouth frames are intentionally phase-locked to the global clock.
            elapsed = tick
        else:
            elapsed = max(0, tick - self.state_start)
        total = max(1, sum(int(v) for v in holds))
        offset = elapsed % total
        for frame, hold in zip(frames, holds):
            hold = max(1, int(hold))
            if offset < hold:
                return frame
            offset -= hold
        return frames[-1]
