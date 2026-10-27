import json
import os
import random
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(BASE_DIR, "source")
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)

from PIL import Image

from ui.puppy_anim import PuppyAnimator


SPEC_PATH = os.path.join(BASE_DIR, "assets", "puppy_design", "puppy_anim.json")
ANIM_DIR = os.path.join(BASE_DIR, "assets", "puppy_design", "anim")


def _load_spec():
    with open(SPEC_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _pixels(img):
    if hasattr(img, "get_flattened_data"):
        return img.get_flattened_data()
    return img.getdata()


class TestPuppyAnimationAssets(unittest.TestCase):
    def setUp(self):
        self.spec = _load_spec()
        self.frame_names = set()
        for state in self.spec["states"].values():
            self.frame_names.update(state["frames"])
            if state.get("static"):
                self.frame_names.add(state["static"])

    def test_spec_declares_room_grid_and_locked_baseline(self):
        self.assertEqual(self.spec["size"], [64, 72])
        self.assertEqual(self.spec["baseline_y"], 70)
        self.assertEqual(self.spec["fps"], 30)
        self.assertEqual(self.spec["on_twos"], 2)

    def test_all_frames_are_hard_pixel_sprites_on_the_baseline(self):
        self.assertGreaterEqual(len(self.frame_names), 12)
        for name in sorted(self.frame_names):
            path = os.path.join(ANIM_DIR, f"{name}.png")
            self.assertTrue(os.path.exists(path), name)
            img = Image.open(path).convert("RGBA")
            self.assertEqual(img.size, (64, 72), name)

            alpha = img.getchannel("A")
            self.assertTrue(set(_pixels(alpha)) <= {0, 255}, name)

            colors = {
                pixel[:3]
                for pixel in _pixels(img)
                if pixel[3] == 255
            }
            self.assertLessEqual(len(colors), 19, f"{name} has {len(colors)} colours")

            opaque_rows = [
                y for y in range(img.height)
                if any(img.getpixel((x, y))[3] for x in range(img.width))
            ]
            self.assertEqual(max(opaque_rows) + 1, 70, f"{name} feet drifted")

    def test_reduce_motion_static_frames_exist(self):
        for state_name, state in self.spec["states"].items():
            static = state.get("static")
            self.assertIn(static, self.frame_names, state_name)


class TestPuppyAnimator(unittest.TestCase):
    def setUp(self):
        self.spec = _load_spec()
        self.anim = PuppyAnimator(self.spec)

    def _frames(self, state):
        return self.spec["states"][state]["frames"]

    def test_idle_loop_contains_blink_and_ear_flick(self):
        seen = {
            self.anim.frame(tick, "idle")
            for tick in range(0, 240)
        }
        self.assertIn("idle_blink", seen)
        self.assertIn("idle_flick", seen)
        self.assertTrue(seen <= set(self._frames("idle")))

    def test_singing_mouth_follows_audio_level(self):
        self.assertIn(
            self.anim.frame(30, "singing", audio_level=1.0),
            self._frames("singing_open"),
        )
        self.assertIn(
            self.anim.frame(30, "singing", audio_level=0.0),
            self._frames("singing_closed"),
        )
        # The eyes-closed beat is the last second of the six-second phrase.
        self.assertIn(
            self.anim.frame(200, "singing", audio_level=1.0),
            self._frames("singing_eyes_closed"),
        )

    def test_mouth_cadence_is_readable_not_a_twitch(self):
        # Two poses alternating every 2 ticks (15 changes/sec) looked like a
        # vibration.  Keep each authored pose on screen for at least a third
        # of a second at 30 Hz.
        open_holds = self.spec["states"]["singing_open"]["hold"]
        self.assertTrue(all(int(hold) >= 10 for hold in open_holds), open_holds)
        self.assertGreaterEqual(sum(int(h) for h in open_holds), 20)

    def test_singing_mouth_uses_hysteresis_and_a_minimum_hold(self):
        seen = []

        self.anim.frame(0, "singing", audio_level=0.9)
        seen.append(self.anim.state)
        # Chatter right on the old 0.25 boundary must not flip the mouth.
        for tick in range(1, 15):
            level = 0.05 if tick % 2 else 0.9
            self.anim.frame(tick, "singing", audio_level=level)
            seen.append(self.anim.state)
        self.assertEqual(set(seen), {"singing_open"}, seen)

        # After the hold expires a genuinely quiet sample changes the state.
        self.anim.frame(15, "singing", audio_level=0.0)
        self.assertEqual(self.anim.state, "singing_closed")
        # ...and a loud sample cannot immediately re-open it.
        for tick in range(16, 30):
            self.anim.frame(tick, "singing", audio_level=0.9)
            self.assertEqual(self.anim.state, "singing_closed")
        self.anim.frame(30, "singing", audio_level=0.9)
        self.assertEqual(self.anim.state, "singing_open")

    def test_no_mouth_frame_flashes_for_a_single_tick(self):
        anim = PuppyAnimator(self.spec)
        minimum = int(self.spec["audio"].get("min_frame_hold", 6))
        last_frame = None
        last_tick = 0
        shortest = 10 ** 9
        for tick in range(0, 120):
            level = 0.9 if (tick // 10) % 2 == 0 else 0.0
            frame = anim.frame(tick, "singing", audio_level=level)
            if last_frame is None:
                last_frame, last_tick = frame, tick
            elif frame != last_frame:
                shortest = min(shortest, tick - last_tick)
                last_frame, last_tick = frame, tick
        self.assertGreaterEqual(shortest, minimum)

    def test_reaction_is_one_held_pose(self):
        state = self.spec["states"]["reaction"]
        self.assertEqual(len(state["frames"]), 1)
        self.assertGreaterEqual(int(state["hold"][0]), 20)

    def test_reduce_motion_returns_one_static_frame_per_mode(self):
        for mode in ("idle", "paused", "alert", "reaction", "happy", "encore"):
            expected = self.spec["states"][mode]["static"]
            self.assertEqual(
                self.anim.frame(123, mode, reduce_motion=True), expected, mode
            )
        self.assertEqual(
            self.anim.frame(123, "singing", audio_level=1.0, reduce_motion=True),
            self.spec["states"]["singing_closed"]["static"],
        )

    def test_track_change_and_pet_states_are_in_place_frames(self):
        self.assertEqual(self.anim.frame(40, "reaction"), "alert_1")
        self.assertIn(self.anim.frame(41, "reaction"), self._frames("reaction"))
        self.assertEqual(self.anim.frame(40, "happy"), "happy")
        self.assertIn(self.anim.frame(40, "paused"), self._frames("paused"))

    def test_unknown_mode_falls_back_to_idle(self):
        frame = self.anim.frame(10, "does-not-exist")
        self.assertIn(frame, self._frames("idle"))


class TestDesktopOverlayGif(unittest.TestCase):
    """The small desktop singer now uses the hand-authored bob GIF."""

    def test_overlay_gif_decodes_to_matching_transparent_frames(self):
        from ui.mascot_notifier import PUPPY_OVERLAY_GIF
        from ui.puppy_gif import load_gif_frames

        path = os.path.join(BASE_DIR, "assets", PUPPY_OVERLAY_GIF)
        self.assertTrue(os.path.exists(path), path)
        frames, durations = load_gif_frames(path)
        self.assertGreaterEqual(len(frames), 8)
        self.assertEqual(len(frames), len(durations))
        size = frames[0].size
        for frame in frames:
            self.assertEqual(frame.size, size)
            # The backyard black backdrop is gone; all four corners are clear.
            for corner in (
                (0, 0), (size[0] - 1, 0), (0, size[1] - 1),
                (size[0] - 1, size[1] - 1),
            ):
                self.assertEqual(frame.getpixel(corner)[3], 0)
        self.assertNotEqual(_pixels(frames[0]), _pixels(frames[1]))

    def test_no_legacy_frame_wears_the_removed_headset(self):
        names = [
            p[:-4] for p in os.listdir(ANIM_DIR)
            if p.endswith(".png") and p != "contact_sheet.png"
        ]
        self.assertGreaterEqual(len(names), 12)
        x0, y0, x1, y1 = (16, 8, 50, 15)
        hardware = {
            (42, 23, 58),
            (58, 43, 58),
            (107, 90, 107),
            (199, 184, 176),
        }
        for name in names:
            img = Image.open(os.path.join(ANIM_DIR, f"{name}.png")).convert("RGBA")
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pixel = img.getpixel((x, y))
                    if pixel[3] == 0:
                        continue
                    self.assertNotIn(
                        pixel[:3], hardware,
                        f"{name} still draws headset hardware at {(x, y)}",
                    )


class TestRoomGifAsset(unittest.TestCase):
    def test_room_gif_frames_share_the_sprite_canvas_and_baseline(self):
        from ui.puppy_gif import PUPPY_BOB_GIF, load_gif_frames, normalize_sprite_frames

        path = os.path.join(BASE_DIR, "assets", PUPPY_BOB_GIF)
        self.assertTrue(os.path.exists(path), path)
        frames, durations = load_gif_frames(path)
        self.assertGreaterEqual(len(frames), 8)
        self.assertEqual(len(frames), len(durations))

        normalized = normalize_sprite_frames(frames)
        self.assertEqual(len(normalized), len(frames))
        size = normalized[0].size
        self.assertAlmostEqual(size[0] / size[1], 64 / 72, places=2)
        bottoms = set()
        for frame in normalized:
            self.assertEqual(frame.size, size)
            self.assertEqual(frame.getpixel((0, 0))[3], 0)
            bottoms.add(frame.getchannel("A").getbbox()[3])
        self.assertEqual(len(bottoms), 1, "feet drifted between GIF frames")

    def test_gif_frame_index_loops_on_the_authored_timing(self):
        from ui.puppy_gif import frame_index_at

        durations = (120, 120, 120)
        self.assertEqual(frame_index_at(0, durations), 0)
        self.assertEqual(frame_index_at(119, durations), 0)
        self.assertEqual(frame_index_at(120, durations), 1)
        self.assertEqual(frame_index_at(250, durations), 2)
        self.assertEqual(frame_index_at(360, durations), 0)

    def test_room_and_overlay_use_the_same_bobbing_mascot(self):
        from ui.app import PUPPY_ROOM_GIF
        from ui.mascot_notifier import PUPPY_OVERLAY_GIF
        from ui.puppy_gif import PUPPY_BOB_GIF

        self.assertEqual(PUPPY_ROOM_GIF, PUPPY_BOB_GIF)
        self.assertEqual(PUPPY_OVERLAY_GIF, PUPPY_BOB_GIF)

    def test_room_bobs_only_while_gamebeats_is_playing(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._puppy_gif_frames = (object(), object())
        app._puppy_gif_durations = (120, 120)
        app._reduce_motion_enabled = MagicMock(return_value=False)
        app._spotify_started_by_us = True
        app._is_playing = True
        app._spotify_audio_active = False
        app._intentional_pause_active = MagicMock(return_value=False)

        self.assertEqual(app._puppy_frame_name(now=0.0), "gif:0")
        self.assertEqual(app._puppy_frame_name(now=0.13), "gif:1")
        # 240 ms wraps back to the first bob.
        self.assertEqual(app._puppy_frame_name(now=0.24), "gif:0")

        # External Spotify audio is not GameBeats playback: hold the first pose.
        app._spotify_started_by_us = False
        app._spotify_audio_active = True
        self.assertEqual(app._puppy_frame_name(now=0.13), "gif:0")

        # GameBeats started the track, but playback is stopped or paused.
        app._spotify_started_by_us = True
        app._is_playing = False
        self.assertEqual(app._puppy_frame_name(now=0.13), "gif:0")
        app._is_playing = True
        app._intentional_pause_active.return_value = True
        self.assertEqual(app._puppy_frame_name(now=0.13), "gif:0")

        app._intentional_pause_active.return_value = False
        app._reduce_motion_enabled.return_value = True
        self.assertEqual(app._puppy_frame_name(now=0.13), "gif:0")


class TestPuppyCanvasNeverMoves(unittest.TestCase):
    def test_animation_swaps_image_without_touching_coordinates(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        canvas = MagicMock()
        canvas.winfo_exists.return_value = True
        app._room_canvas = canvas
        app._room_puppy_item = 7
        app._room_puppy_base = (100, 200, 192, 216)
        app._room_puppy_sprite_key = ("idle_0", 192, 216)
        app._puppy_frame_name = lambda now=None: "idle_0"
        app._puppy_bbox = None
        app._room_puppy_photo = None

        GameBeatsApp._animate_room_puppy.__get__(app, GameBeatsApp)()

        canvas.coords.assert_not_called()
        canvas.itemconfigure.assert_not_called()
        # The 30 Hz tick must not re-stack the puppy above UI overlays.
        canvas.tag_raise.assert_not_called()
        self.assertEqual(app._puppy_bbox, (100, 200, 292, 416))

    def test_missing_frame_never_moves_the_existing_image(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        canvas = MagicMock()
        canvas.winfo_exists.return_value = True
        app._room_canvas = canvas
        app._room_puppy_item = 7
        app._room_puppy_base = (100, 200, 192, 216)
        app._room_puppy_sprite_key = ("idle_0", 192, 216)
        app._puppy_frame_name = lambda now=None: "sing_0"
        app._puppy_image_for = MagicMock(return_value=None)
        app._puppy_bbox = None
        app._room_puppy_photo = None

        GameBeatsApp._animate_room_puppy.__get__(app, GameBeatsApp)()

        canvas.coords.assert_not_called()
        canvas.itemconfigure.assert_not_called()
        self.assertEqual(app._puppy_bbox, (100, 200, 292, 416))

    def test_audio_meter_dip_does_not_rebuild_the_room(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._puppy_singing_overlay = MagicMock()
        app._puppy_audio_active = False
        app._puppy_hide_job = None
        app._puppy_last_loud_ts = 0.0
        app._mascot_notifier = None
        app._spotify_started_by_us = True
        app._intentional_pause_active = lambda: False
        app._schedule_room_redraw = MagicMock()
        app.root = MagicMock()

        GameBeatsApp._set_puppy_singing_visible.__get__(
            app, GameBeatsApp
        )(True)

        app._puppy_singing_overlay.show.assert_called_once()
        # The master clock polls the play state; a full room rebuild here made
        # the den flicker every time the meter dipped.
        app._schedule_room_redraw.assert_not_called()

    def test_petting_uses_a_small_overlay_item_without_redrawing(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        canvas = MagicMock()
        canvas.winfo_width.return_value = 2240
        app._room_canvas = canvas
        app._puppy_bbox = (960, 452, 1280, 812)
        app._redraw_room = MagicMock()
        app._pet_heart_job = None
        app._heart_until = 0.0
        app._puppy_mood_until = 0.0
        app.status_log_lbl = MagicMock()
        app.root = MagicMock()
        app.root.after.return_value = "heart-job"

        GameBeatsApp._pet_puppy.__get__(app, GameBeatsApp)()

        app._redraw_room.assert_not_called()
        canvas.delete.assert_called_with("pet_heart")
        args, kwargs = canvas.create_text.call_args
        self.assertEqual(args[:2], (1120, 426))
        self.assertEqual(kwargs["text"], "\u2665")
        self.assertIn("pet_heart", kwargs["tags"])
        app.root.after.assert_called_once()
        self.assertEqual(app.root.after.call_args.args[0], 1200)
        self.assertGreater(app._heart_until, 0.0)

    def test_redraw_puppy_reuses_the_current_photo(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        canvas = MagicMock()
        canvas.type.return_value = "image"
        app._room_canvas = canvas
        app._room_puppy_item = 7
        app._room_puppy_photo = object()
        app._room_puppy_sprite_key = ("idle_0", 320, 360)
        app._puppy_image_for = MagicMock()

        GameBeatsApp._draw_room_puppy.__get__(
            app, GameBeatsApp
        )(canvas, "idle_0", (960, 452, 320, 360))

        app._puppy_image_for.assert_not_called()
        canvas.create_image.assert_not_called()
        # A rebuild may raise the puppy; the tick loop may not.
        canvas.tag_raise.assert_called_once_with("puppy")


class TestMultiStateAnimationAssets(unittest.TestCase):
    """Idle, pause, and change must share one canvas and one paw baseline."""

    def _normalized(self, target_size, bottom_pad, margin):
        from ui.puppy_gif import (
            PUPPY_BOB_GIF,
            PUPPY_CHANGE_GIF,
            PUPPY_PAUSE_GIF,
            load_gif_frames,
            normalize_animation_states,
        )

        raw = {}
        for name, filename in (
            ("idle", PUPPY_BOB_GIF),
            ("pause", PUPPY_PAUSE_GIF),
            ("change", PUPPY_CHANGE_GIF),
        ):
            path = os.path.join(BASE_DIR, "assets", filename)
            self.assertTrue(os.path.exists(path), path)
            raw[name] = load_gif_frames(path)
        return normalize_animation_states(
            raw,
            reference="idle",
            target_size=target_size,
            bottom_pad=bottom_pad,
            margin=margin,
        )

    def test_all_states_share_canvas_and_feet_baseline(self):
        states, canvas = self._normalized((64, 72), 2, 1)
        self.assertEqual(set(states), {"idle", "pause", "change"})
        self.assertGreater(canvas[0], 64, "reaction headset/droop needs width")
        self.assertGreater(canvas[1], 72, "reaction headset/droop needs height")
        for name, (frames, durations) in states.items():
            self.assertTrue(frames, name)
            self.assertEqual(len(frames), len(durations), name)
            bottoms = set()
            for frame in frames:
                self.assertEqual(frame.size, canvas, name)
                bbox = frame.getchannel("A").getbbox()
                self.assertIsNotNone(bbox, name)
                bottoms.add(bbox[3])
            self.assertEqual(
                bottoms, {canvas[1] - 2},
                f"{name} feet drifted off the shared baseline",
            )

    def test_overlay_states_use_the_same_large_canvas(self):
        states, canvas = self._normalized((170, 170), 0, 2)
        self.assertEqual(canvas, (263, 205))
        for name, (frames, _durations) in states.items():
            for frame in frames:
                self.assertEqual(frame.size, canvas, name)
                self.assertEqual(
                    frame.getchannel("A").getbbox()[3], canvas[1], name
                )

    def test_room_body_scale_stays_64_wide(self):
        states, _canvas = self._normalized((64, 72), 2, 1)
        widths = []
        for frame in states["idle"][0]:
            bbox = frame.getchannel("A").getbbox()
            widths.append(bbox[2] - bbox[0])
        # The old mascot body was 64 source pixels wide.  The larger reaction
        # canvas must not shrink it to make room for headphones.
        self.assertGreaterEqual(max(widths), 62)
        self.assertLessEqual(max(widths), 64)


class TestRoomPuppyActions(unittest.TestCase):
    def _make_app(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._puppy_gif_states = {
            "idle": (("i0", "i1"), (120, 120)),
            "pause": (("p0", "p1"), (120, 120)),
            "change": (("c0", "c1"), (120, 120)),
        }
        app._puppy_gif_frames = ("i0", "i1")
        app._puppy_gif_durations = (120, 120)
        app._puppy_action_state = None
        app._puppy_action_started = 0.0
        app._puppy_action_loops = 1
        app._puppy_action_reverse = False
        app._puppy_action_hold = False
        app._reduce_motion_enabled = MagicMock(return_value=False)
        app._spotify_started_by_us = True
        app._is_playing = True
        app._spotify_audio_active = False
        app._intentional_pause_active = MagicMock(return_value=False)
        return app

    def test_change_action_advances_then_returns_to_the_bob(self):
        app = self._make_app()
        app._start_puppy_action("change", now=100.0)
        self.assertEqual(app._puppy_action_state, "change")
        self.assertEqual(app._puppy_frame_name(now=100.0), "action:change:0")
        self.assertEqual(app._puppy_frame_name(now=100.12), "action:change:1")
        self.assertTrue(
            app._puppy_frame_name(now=101.0).startswith("gif:")
        )
        self.assertIsNone(app._puppy_action_state)

    def test_pause_action_holds_its_last_pose(self):
        app = self._make_app()
        app._is_playing = False
        app._intentional_pause_active.return_value = True
        app._start_puppy_action("pause", hold=True, now=200.0)
        self.assertEqual(app._puppy_frame_name(now=201.0), "action:pause:1")
        self.assertEqual(app._puppy_frame_name(now=220.0), "action:pause:1")
        self.assertEqual(app._puppy_action_state, "pause")

    def test_stale_pause_hold_is_cleared_after_resume(self):
        app = self._make_app()
        app._start_puppy_action("pause", hold=True, now=200.0)
        # Playback has resumed and no pause flag remains, but a duplicate
        # notification left the old hold behind.
        app._is_playing = True
        self.assertTrue(app._puppy_frame_name(now=201.0).startswith("gif:"))
        self.assertIsNone(app._puppy_action_state)

    def test_resume_action_plays_the_pause_clip_backwards(self):
        app = self._make_app()
        app._start_puppy_action("pause", reverse=True, now=300.0)
        self.assertEqual(app._puppy_frame_name(now=300.0), "action:pause:1")
        self.assertEqual(app._puppy_frame_name(now=300.12), "action:pause:0")
        self.assertTrue(app._puppy_frame_name(now=301.0).startswith("gif:"))
        self.assertIsNone(app._puppy_action_state)

    def test_reduced_motion_skips_actions(self):
        app = self._make_app()
        app._reduce_motion_enabled.return_value = True
        app._start_puppy_action("change", now=400.0)
        self.assertIsNone(app._puppy_action_state)

    def test_pause_first_does_not_stomp_the_change_animation(self):
        app = self._make_app()
        now = time.time()
        app._start_puppy_action("change", now=now)
        app._puppy_action_started = now
        app._react_to_playback_change(False)
        self.assertEqual(app._puppy_action_state, "change")
        self.assertFalse(app._puppy_action_hold)

    def test_change_finishing_while_paused_settles_into_pause_hold(self):
        app = self._make_app()
        app._is_playing = False
        app._intentional_pause_active.return_value = True
        app._start_puppy_action("change", now=600.0)

        self.assertEqual(app._puppy_frame_name(now=601.0), "action:pause:1")
        self.assertEqual(app._puppy_action_state, "pause")
        self.assertTrue(app._puppy_action_hold)
        self.assertFalse(app._puppy_action_reverse)
        # The pose must stay put on later frames, too.
        self.assertEqual(app._puppy_frame_name(now=700.0), "action:pause:1")

    def test_duplicate_pause_does_not_restart_the_forward_droop(self):
        app = self._make_app()
        app._is_playing = False
        app._intentional_pause_active.return_value = True
        app._start_puppy_action("pause", hold=True, now=700.0)

        app._react_to_playback_change(False)

        self.assertEqual(app._puppy_action_state, "pause")
        self.assertEqual(app._puppy_action_started, 700.0)

    def test_duplicate_resume_does_not_restart_the_reverse_clip(self):
        app = self._make_app()
        app._start_puppy_action("pause", hold=True, now=time.time() - 0.1)
        app._react_to_playback_change(True)
        started = app._puppy_action_started
        self.assertTrue(app._puppy_action_reverse)

        app._react_to_playback_change(True)

        self.assertEqual(app._puppy_action_started, started)
        self.assertTrue(app._puppy_action_reverse)
        self.assertFalse(app._puppy_action_hold)

    def test_first_track_start_does_not_play_a_resume_animation(self):
        app = self._make_app()
        app._react_to_playback_change(True)
        self.assertIsNone(app._puppy_action_state)

    def test_resume_reverses_an_existing_pause_action(self):
        app = self._make_app()
        app._start_puppy_action("pause", hold=True, now=500.0)
        app._puppy_action_started = 500.0
        app._react_to_playback_change(True)
        self.assertEqual(app._puppy_action_state, "pause")
        self.assertTrue(app._puppy_action_reverse)
        self.assertFalse(app._puppy_action_hold)

    def test_action_frame_name_selects_the_requested_gif_state(self):
        app = self._make_app()
        first = MagicMock()
        second = MagicMock()
        app._puppy_gif_states["change"] = ((first, second), (120, 120))
        app._puppy_photo_cache = {}

        result = app._puppy_image_for("action:change:1", (8, 8))

        self.assertIs(result, second.resize.return_value)
        second.resize.assert_called_once()
        first.resize.assert_not_called()

    def test_change_animation_uses_a_short_cooldown_for_polling(self):
        app = self._make_app()
        app._puppy_singing_overlay = MagicMock()
        app._puppy_change_cooldown_until = 0.0

        app._play_puppy_change_animation(force=True)
        self.assertEqual(app._puppy_action_state, "change")
        self.assertEqual(
            app._puppy_singing_overlay.play_change_animation.call_count, 1
        )

        app._puppy_action_state = None
        app._play_puppy_change_animation()
        self.assertIsNone(
            app._puppy_action_state,
            "polling should not restart a just-triggered change clip",
        )
        self.assertEqual(
            app._puppy_singing_overlay.play_change_animation.call_count, 1
        )

    def test_duplicate_change_request_does_not_restart_a_running_clip(self):
        app = self._make_app()
        app._puppy_singing_overlay = MagicMock()
        app._puppy_change_cooldown_until = 0.0

        self.assertTrue(app._play_puppy_change_animation(force=True))
        started = app._puppy_action_started

        self.assertFalse(app._play_puppy_change_animation(force=True))

        self.assertEqual(app._puppy_action_started, started)
        self.assertEqual(
            app._puppy_singing_overlay.play_change_animation.call_count, 1
        )

    def test_paused_music_blocks_room_change_animation(self):
        app = self._make_app()
        app._is_playing = False
        app._intentional_pause_active.return_value = True
        app._puppy_singing_overlay = MagicMock()
        app._puppy_change_cooldown_until = 0.0

        changed = app._play_puppy_change_animation(force=True)

        self.assertFalse(changed)
        self.assertEqual(app._puppy_action_state, "pause")
        self.assertTrue(app._puppy_action_hold)
        app._puppy_singing_overlay.set_animation_locked.assert_called_with(
            True, animate=False
        )
        app._puppy_singing_overlay.play_change_animation.assert_not_called()

    def test_playing_music_allows_change_animation_and_unlocks_overlay(self):
        app = self._make_app()
        app._puppy_singing_overlay = MagicMock()
        app._puppy_change_cooldown_until = 0.0

        changed = app._play_puppy_change_animation(force=True)

        self.assertTrue(changed)
        self.assertEqual(app._puppy_action_state, "change")
        app._puppy_singing_overlay.set_animation_locked.assert_called_with(False)
        app._puppy_singing_overlay.play_change_animation.assert_called_once_with()


class TestDesktopPuppyControls(unittest.TestCase):
    def _make_overlay(self, playing=True):
        from ui.mascot_notifier import PuppySingingOverlay

        root = MagicMock()
        overlay = PuppySingingOverlay(root, corner="bottom-left")
        overlay._win = MagicMock()
        overlay._win.winfo_x.return_value = 10
        overlay._win.winfo_y.return_value = 20
        overlay._win.after.return_value = "job"
        overlay._label = MagicMock()
        overlay._visible = True
        overlay._photos = ["i0", "i1"]
        overlay._durations = (120, 120)
        overlay._photos_by_state = {
            "idle": ["i0", "i1"],
            "pause": ["p0", "p1"],
            "change": ["c0", "c1"],
        }
        overlay._durations_by_state = {
            "idle": (120, 120),
            "pause": (120, 120),
            "change": (120, 120),
        }
        overlay._state = "idle"
        overlay._base_paused = not playing
        overlay._animation_locked = False
        overlay._on_toggle_play_pause = MagicMock()
        overlay._on_try_another = MagicMock()
        overlay._get_playing = MagicMock(return_value=playing)
        overlay._save_pos = MagicMock()
        return overlay

    @staticmethod
    def _event(x=100, y=100, state=0):
        event = MagicMock()
        event.x = 5
        event.y = 5
        event.x_root = x
        event.y_root = y
        event.state = state
        return event

    def test_short_click_pauses_and_holds_the_drooped_pose(self):
        overlay = self._make_overlay(playing=True)
        event = self._event()

        overlay._on_press(event)
        overlay._on_release(event)

        overlay._on_toggle_play_pause.assert_called_once_with()
        self.assertTrue(overlay._base_paused)
        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        self.assertFalse(overlay._active_reverse)
        self.assertEqual(overlay._idx, 0)

    def test_refused_toggle_leaves_the_pose_alone(self):
        overlay = self._make_overlay(playing=True)
        overlay._on_toggle_play_pause.return_value = False

        overlay._on_press(self._event())
        overlay._on_release(self._event())

        overlay._on_toggle_play_pause.assert_called_once_with()
        self.assertEqual(overlay._state, "idle")
        self.assertFalse(overlay._base_paused)

    def test_second_click_plays_the_pause_clip_in_reverse(self):
        overlay = self._make_overlay(playing=False)

        overlay._on_press(self._event())
        overlay._on_release(self._event())

        overlay._on_toggle_play_pause.assert_called_once_with()
        self.assertFalse(overlay._base_paused)
        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_reverse)
        self.assertFalse(overlay._active_hold)
        self.assertEqual(overlay._idx, 1)

    def test_long_click_tries_another_without_toggling(self):
        from ui.mascot_notifier import PUPPY_LONG_CLICK_MS

        self.assertEqual(PUPPY_LONG_CLICK_MS, 650)
        overlay = self._make_overlay(playing=True)
        event = self._event()

        overlay._on_press(event)
        self.assertEqual(overlay._long_job, "job")
        overlay._fire_long_click()
        overlay._on_release(event)

        overlay._on_try_another.assert_called_once_with()
        overlay._on_toggle_play_pause.assert_not_called()
        self.assertEqual(overlay._state, "change")
        self.assertTrue(overlay._long_fired is False)

    def test_ctrl_drag_moves_and_saves_without_toggling(self):
        overlay = self._make_overlay(playing=True)
        press = self._event(state=0x0004)
        move = self._event(x=150, y=140, state=0x0004)

        overlay._on_press(press)
        overlay._on_motion(move)
        overlay._on_release(move)

        overlay._win.geometry.assert_called_once_with("+60+60")
        overlay._save_pos.assert_called_once_with(60, 60)
        overlay._on_toggle_play_pause.assert_not_called()
        overlay._on_try_another.assert_not_called()

    def test_ctrl_pressed_mid_drag_still_moves_and_saves(self):
        overlay = self._make_overlay(playing=True)
        press = self._event(state=0)
        move = self._event(x=140, y=130, state=0x0004)

        overlay._on_press(press)
        overlay._on_motion(move)
        overlay._on_release(move)

        overlay._win.geometry.assert_called_once_with("+50+50")
        overlay._save_pos.assert_called_once_with(50, 50)
        overlay._on_try_another.assert_not_called()
        overlay._on_toggle_play_pause.assert_not_called()

    def test_plain_drag_does_not_move_or_toggle(self):
        overlay = self._make_overlay(playing=True)
        press = self._event()
        move = self._event(x=130, y=100)

        overlay._on_press(press)
        overlay._on_motion(move)
        overlay._on_release(move)

        overlay._win.geometry.assert_not_called()
        overlay._on_toggle_play_pause.assert_not_called()
        self.assertIsNone(overlay._long_job)

    def test_change_animation_is_idempotent_while_active(self):
        overlay = self._make_overlay(playing=True)

        self.assertTrue(overlay.play_change_animation())
        overlay._idx = 1
        started = overlay._state_started

        self.assertTrue(overlay.play_change_animation())

        self.assertEqual(overlay._state, "change")
        self.assertEqual(overlay._idx, 1)
        self.assertEqual(overlay._state_started, started)

    def test_change_animation_is_not_cut_off_by_new_track_state(self):
        overlay = self._make_overlay(playing=False)
        overlay.play_change_animation()
        self.assertEqual(overlay._state, "change")

        overlay.set_playback_state(True)

        self.assertEqual(overlay._state, "change")
        self.assertFalse(overlay._base_paused)

    def test_change_finishing_while_paused_returns_to_the_drooped_pose(self):
        overlay = self._make_overlay(playing=False)
        overlay.play_change_animation()

        overlay._update_reaction_frame(overlay._state_started + 10.0)

        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        self.assertFalse(overlay._active_reverse)
        self.assertEqual(overlay._idx, 1)

    def test_change_finishing_while_playing_returns_to_idle(self):
        overlay = self._make_overlay(playing=True)
        overlay.play_change_animation()

        overlay._update_reaction_frame(overlay._state_started + 10.0)

        self.assertEqual(overlay._state, "idle")
        self.assertFalse(overlay._active_hold)
        self.assertEqual(overlay._idx, 0)

    def test_resume_click_during_change_updates_rest_state_only(self):
        overlay = self._make_overlay(playing=False)
        overlay.play_change_animation()

        overlay._handle_click()

        self.assertEqual(overlay._state, "change")
        self.assertFalse(overlay._base_paused)
        self.assertTrue(overlay._active_loops)

    def test_pause_click_during_change_keeps_the_change_clip(self):
        overlay = self._make_overlay(playing=True)
        overlay.play_change_animation()

        overlay._handle_click()

        self.assertEqual(overlay._state, "change")
        self.assertTrue(overlay._base_paused)

    def test_locked_pause_blocks_change_animation(self):
        overlay = self._make_overlay(playing=False)
        overlay.set_animation_locked(True)

        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        self.assertFalse(overlay.play_change_animation())
        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        self.assertFalse(overlay._active_reverse)
        self.assertEqual(overlay._idx, 1)

    def test_long_click_while_paused_holds_pose_but_still_requests_another(self):
        overlay = self._make_overlay(playing=False)
        overlay.set_animation_locked(True)

        overlay._on_press(self._event())
        overlay._fire_long_click()

        overlay._on_try_another.assert_called_once_with()
        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        self.assertNotEqual(overlay._state, "change")

    def test_lock_does_not_cut_an_inflight_change_clip(self):
        overlay = self._make_overlay(playing=True)
        self.assertTrue(overlay.play_change_animation())
        overlay.set_animation_locked(True)

        self.assertEqual(overlay._state, "change")
        overlay._update_reaction_frame(overlay._state_started + 10.0)

        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)

    def test_resume_unlocks_and_reverses_the_pause_pose(self):
        overlay = self._make_overlay(playing=False)
        overlay.set_animation_locked(True)

        overlay.set_playback_state(True)

        self.assertFalse(overlay._animation_locked)
        self.assertFalse(overlay._base_paused)
        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_reverse)
        self.assertFalse(overlay._active_hold)

    def test_resume_click_waits_for_confirmed_audio_before_unlocking(self):
        overlay = self._make_overlay(playing=False)
        overlay.set_animation_locked(True)
        overlay._on_toggle_play_pause.return_value = True

        overlay._handle_click()

        # The app accepted the command, but the pose stays locked until the
        # audio/play state actually comes back.
        self.assertTrue(overlay._animation_locked)
        self.assertTrue(overlay._base_paused)
        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        self.assertFalse(overlay._active_reverse)

        overlay.set_playback_state(True)
        self.assertFalse(overlay._animation_locked)
        self.assertTrue(overlay._active_reverse)

    def test_locked_idle_never_bobs(self):
        overlay = self._make_overlay(playing=True)
        overlay.set_animation_locked(True)
        overlay._state = "idle"

        overlay._animate()

        self.assertEqual(overlay._state, "pause")
        self.assertTrue(overlay._active_hold)
        overlay._win.after.assert_not_called()

    def test_duplicate_resume_does_not_restart_the_reverse_clip(self):
        overlay = self._make_overlay(playing=False)
        overlay._on_press(self._event())
        overlay._on_release(self._event())
        self.assertTrue(overlay._active_reverse)
        started = overlay._state_started

        overlay.set_playback_state(True)

        self.assertEqual(overlay._state_started, started)
        self.assertTrue(overlay._active_reverse)


class TestPuppyStateFuzz(unittest.TestCase):
    """Deterministic fuzzing for the room/overlay animation state machines."""

    STATES = {
        "idle": (("i0", "i1", "i2", "i3"), (120, 120, 120, 120)),
        "pause": (("p0", "p1", "p2", "p3"), (120, 120, 120, 120)),
        "change": (("c0", "c1", "c2", "c3"), (120, 120, 120, 120)),
    }

    def _make_room_app(self, now):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._puppy_gif_states = self.STATES
        app._puppy_gif_frames = self.STATES["idle"][0]
        app._puppy_gif_durations = self.STATES["idle"][1]
        app._puppy_action_state = None
        app._puppy_action_started = 0.0
        app._puppy_action_loops = 1
        app._puppy_action_reverse = False
        app._puppy_action_hold = False
        app._puppy_change_cooldown_until = 0.0
        app._puppy_singing_overlay = None
        app._reduce_motion_enabled = MagicMock(return_value=False)
        app._spotify_started_by_us = True
        app._is_playing = True
        app._spotify_audio_active = True
        app._manual_paused = False
        app._user_paused_flag = False
        app._paused_by_game_flag = False
        app._intentional_pause_active = lambda: bool(
            app._manual_paused
            or app._user_paused_flag
            or app._paused_by_game_flag
        )
        return app

    def _render_room(self, app, now, seed, step):
        frame = app._puppy_frame_name(now)
        pressed = app._intentional_pause_active()
        if frame.startswith("action:"):
            _, state, index = frame.split(":")
            frames = self.STATES[state][0]
            self.assertTrue(
                0 <= int(index) < len(frames),
                f"seed={seed} step={step}: bad frame {frame}",
            )
            if (
                not pressed
                and app._is_playing
                and state == "pause"
                and app._puppy_action_hold
            ):
                self.fail(
                    f"seed={seed} step={step}: stale droop while playing "
                    f"({frame})"
                )
        elif frame.startswith("gif:"):
            # A paused puppy may only show the neutral bob while a change
            # reaction is still playing; once that ends it must hold the pose.
            if pressed and not app._puppy_action_active("change"):
                self.fail(
                    f"seed={seed} step={step}: paused puppy fell back to {frame}"
                )
        else:
            self.fail(f"seed={seed} step={step}: unknown frame {frame}")
        return frame

    def test_seeded_room_pause_resume_change_transitions(self):
        from ui import app as app_mod

        for seed in range(250):
            rng = random.Random(seed)
            now = [1000.0]
            app = self._make_room_app(now[0])

            def set_playing(playing):
                previous = app._is_playing
                app._is_playing = bool(playing)
                if previous != app._is_playing:
                    app._react_to_playback_change(app._is_playing)

            def user_paused():
                return bool(app._manual_paused or app._user_paused_flag)

            def manual_pause():
                if user_paused():
                    return
                app._manual_paused = True
                app._user_paused_flag = True
                app._paused_by_game_flag = False
                set_playing(False)

            def manual_resume():
                if not user_paused():
                    return
                app._manual_paused = False
                app._user_paused_flag = False
                app._paused_by_game_flag = False
                set_playing(True)

            def game_pause():
                if user_paused() or app._paused_by_game_flag:
                    return
                app._paused_by_game_flag = True
                app._is_playing = False
                app._react_to_playback_change(False)

            def game_resume():
                if user_paused() or not app._paused_by_game_flag:
                    return
                app._paused_by_game_flag = False
                app._is_playing = True
                app._react_to_playback_change(True)

            def playlist_pause():
                app._is_playing = False
                app._react_to_playback_change(False)
                app._manual_paused = True
                app._user_paused_flag = True
                app._paused_by_game_flag = False

            def new_playlist():
                app._manual_paused = False
                app._user_paused_flag = False
                app._paused_by_game_flag = False
                set_playing(True)

            with patch.object(app_mod.time, "time", side_effect=lambda: now[0]):
                for step in range(50):
                    event = rng.randrange(14)
                    if event == 0:
                        manual_pause()
                    elif event == 1:
                        manual_resume()
                    elif event == 2:
                        game_pause()
                    elif event == 3:
                        game_resume()
                    elif event == 4:
                        playlist_pause()
                    elif event == 5:
                        new_playlist()
                    elif event == 6:
                        app._play_puppy_change_animation(force=True)
                    elif event == 7:
                        app._play_puppy_change_animation()
                    elif event in (8, 9):
                        now[0] += rng.choice(
                            [0.0, 0.03, 0.06, 0.12, 0.24, 0.6, 1.5, 3.0]
                        )
                    elif event == 11:
                        app._react_to_playback_change(False)
                    elif event == 12:
                        app._react_to_playback_change(True)
                    elif event == 13:
                        if app._is_playing:
                            manual_pause()
                        elif user_paused():
                            manual_resume()
                        elif app._paused_by_game_flag:
                            game_resume()
                        else:
                            new_playlist()
                    self._render_room(app, now[0], seed, step)

                now[0] += 3.0
                frame = self._render_room(app, now[0], seed, "final")
                with self.subTest(seed=seed):
                    if app._intentional_pause_active():
                        self.assertEqual(
                            frame,
                            f"action:pause:{len(self.STATES['pause'][0]) - 1}",
                            "paused puppy must settle on its drooped pose",
                        )
                        self.assertTrue(app._puppy_action_hold)
                    else:
                        self.assertFalse(
                            frame.startswith("action:"),
                            f"resumed puppy must return to the bob ({frame})",
                        )

    def test_seeded_overlay_pause_resume_try_another(self):
        from ui import mascot_notifier as mn

        def event(x=100, y=100):
            e = MagicMock()
            e.x = 5
            e.y = 5
            e.x_root = x
            e.y_root = y
            e.state = 0
            return e

        for seed in range(180):
            rng = random.Random(seed)
            now = [100.0]
            controls = TestDesktopPuppyControls()
            overlay = controls._make_overlay(playing=True)
            overlay._saved_pos = (10, 20)
            app = {
                "playing": True,
                "busy": False,
                "jobs": [],
            }

            def queue(kind, success):
                app["jobs"].append(
                    {"kind": kind, "ticks": rng.randint(1, 4), "success": success}
                )

            def toggle():
                if app["busy"]:
                    return False
                if app["playing"]:
                    # Optimistic pause; the command may later fail.
                    app["playing"] = False
                    overlay.set_playback_state(False, animate=True)
                    if rng.random() < 0.25:
                        queue("pause", False)
                    return True
                app["busy"] = True
                queue("resume", rng.random() >= 0.25)
                return True

            def try_another():
                # The app re-triggers its change reaction, then pauses the old
                # mix while it searches for the next playlist.
                overlay.play_change_animation()
                app["playing"] = False
                overlay.set_playback_state(False, animate=True)
                queue("switch", rng.random() >= 0.2)

            def run_jobs():
                due = []
                for job in app["jobs"]:
                    job["ticks"] -= 1
                    if job["ticks"] <= 0:
                        due.append(job)
                app["jobs"] = [j for j in app["jobs"] if j["ticks"] > 0]
                for job in due:
                    app["busy"] = False
                    if job["kind"] == "resume":
                        app["playing"] = bool(job["success"])
                        overlay.set_playback_state(app["playing"])
                        if app["playing"]:
                            overlay.show()
                        else:
                            overlay.set_playback_state(False, animate=True)
                    elif job["kind"] == "pause":
                        # A failed pause means the music is still playing.
                        app["playing"] = bool(job["success"])
                        overlay.set_playback_state(app["playing"])
                    elif job["kind"] == "switch":
                        app["playing"] = bool(job["success"])
                        overlay.set_playback_state(app["playing"])
                        if app["playing"]:
                            overlay.show()

            overlay._on_toggle_play_pause = toggle
            overlay._on_try_another = try_another
            overlay._get_playing = lambda: app["playing"]

            with patch.object(mn.time, "monotonic", side_effect=lambda: now[0]):
                with patch.object(mn, "_apply_noactivate", return_value=None):
                    for step in range(50):
                        ev = rng.randrange(12)
                        state_before = overlay._state
                        if ev == 0:
                            if overlay._visible:
                                overlay._handle_click()
                        elif ev == 1:
                            if overlay._visible:
                                press = event()
                                overlay._on_press(press)
                                overlay._on_release(press)
                        elif ev == 2:
                            if overlay._visible:
                                press = event()
                                overlay._on_press(press)
                                overlay._fire_long_click()
                                overlay._on_release(press)
                        elif ev == 3:
                            overlay.play_change_animation()
                        elif ev == 4:
                            overlay.set_playback_state(True, animate=True)
                        elif ev == 5:
                            overlay.set_playback_state(False, animate=True)
                        elif ev == 6:
                            overlay.hide(immediate=True)
                        elif ev == 7:
                            overlay.show()
                        elif ev in (8, 9):
                            now[0] += rng.choice(
                                [0.0, 0.03, 0.06, 0.12, 0.25, 0.6, 1.5]
                            )
                            if ev == 9:
                                run_jobs()
                            overlay._animate()
                        elif ev == 10:
                            overlay._animate()
                        else:
                            run_jobs()

                        if overlay._state not in ("idle", "pause", "change"):
                            self.fail(
                                f"seed={seed} step={step}: bad state "
                                f"{overlay._state}"
                            )
                        if (
                            ev in (0, 1, 2)
                            and state_before == "change"
                            and overlay._visible
                        ):
                            self.assertEqual(
                                overlay._state,
                                "change",
                                "a click must not cut the change clip short",
                            )
                        if (
                            not overlay._base_paused
                            and overlay._state == "pause"
                            and overlay._active_hold
                            and not overlay._active_reverse
                        ):
                            self.fail(
                                f"seed={seed} step={step}: stale droop while "
                                "playing"
                            )

                    now[0] += 3.0
                    with patch.object(mn, "_apply_noactivate", return_value=None):
                        for _ in range(20):
                            now[0] += 0.1
                            overlay._animate()
                        overlay.show()
                        for _ in range(20):
                            now[0] += 0.1
                            overlay._animate()

            with self.subTest(seed=seed):
                frames = overlay._state_frames(overlay._state)[0]
                if overlay._base_paused:
                    self.assertEqual(overlay._state, "pause")
                    self.assertTrue(overlay._active_hold)
                    self.assertEqual(overlay._idx, len(frames) - 1)
                else:
                    self.assertEqual(overlay._state, "idle")


class TestPlayPauseFailureRecovery(unittest.TestCase):
    def _make_app(self, playing):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        state = {"playing": bool(playing)}
        app.root = MagicMock()
        app.root.after.side_effect = lambda _delay, fn, *args: fn(*args)
        app.spotify = MagicMock()
        app._is_playing = bool(playing)
        app._manual_paused = not playing
        app._user_paused_flag = not playing
        app._paused_by_game_flag = False
        app._begin_play_pause = MagicMock(return_value=True)
        app._finish_play_pause = MagicMock()
        app._send_spotify_pause_command = MagicMock(return_value=False)
        app._send_spotify_resume_command = MagicMock(return_value=False)
        app._spotify_is_playing_for_toggle = lambda: state["playing"]
        app._set_play_btn_icon = MagicMock()
        app._log = MagicMock()
        pause_calls = []

        def apply_pause(paused):
            pause_calls.append(bool(paused))
            app._manual_paused = bool(paused)
            app._user_paused_flag = bool(paused)
            if paused:
                app._paused_by_game_flag = False

        app._apply_user_pause_state = apply_pause
        return app, state, pause_calls

    @staticmethod
    def _inline_thread():
        class InlineThread:
            def __init__(self, target, daemon=True):
                self.target = target

            def start(self):
                self.target()

        return InlineThread

    def test_failed_resume_restores_the_paused_pose_and_flags(self):
        app, state, pause_calls = self._make_app(playing=False)
        with patch("ui.app.threading.Thread", self._inline_thread()):
            self.assertTrue(app._play_pause_toggle())

        self.assertEqual(pause_calls, [False, True])
        self.assertTrue(app._manual_paused)
        self.assertTrue(app._user_paused_flag)
        self.assertEqual(app._set_play_btn_icon.call_args.args[0], False)

    def test_failed_pause_reverts_to_the_playing_pose_and_flags(self):
        app, state, pause_calls = self._make_app(playing=True)
        with patch("ui.app.threading.Thread", self._inline_thread()):
            self.assertTrue(app._play_pause_toggle())

        self.assertEqual(pause_calls, [True, False])
        self.assertFalse(app._manual_paused)
        self.assertFalse(app._user_paused_flag)
        self.assertEqual(app._set_play_btn_icon.call_args.args[0], True)


class TestDesktopPuppySettingsCopy(unittest.TestCase):
    def test_gesture_help_names_all_three_actions(self):
        from ui.app import PUPPY_OVERLAY_GESTURES, PUPPY_OVERLAY_HELP

        gestures = dict(PUPPY_OVERLAY_GESTURES)
        self.assertIn("CLICK", gestures)
        self.assertIn("LONG CLICK", gestures)
        self.assertIn("CTRL + DRAG", gestures)
        self.assertIn("pause", gestures["CLICK"].lower())
        self.assertIn("another playlist", gestures["LONG CLICK"].lower())
        self.assertIn("move", gestures["CTRL + DRAG"].lower())
        self.assertIn("stays visible", PUPPY_OVERLAY_HELP.lower())


if __name__ == "__main__":
    unittest.main()
