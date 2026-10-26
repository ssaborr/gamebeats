import json
import os
import sys
import unittest
from unittest.mock import MagicMock

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


if __name__ == "__main__":
    unittest.main()
