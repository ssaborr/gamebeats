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


if __name__ == "__main__":
    unittest.main()
