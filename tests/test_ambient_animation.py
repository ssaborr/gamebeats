import os
import sys
import unittest
from unittest.mock import MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(BASE_DIR, "source")
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)

from ui.app import GameBeatsApp


class TestRoomLayout(unittest.TestCase):
    def test_full_plate_has_zero_offset(self):
        scale, left, top = GameBeatsApp._room_layout(400, 250)
        self.assertAlmostEqual(scale, 1.0)
        self.assertAlmostEqual(left, 0.0)
        self.assertAlmostEqual(top, 0.0)

    def test_wide_canvas_crops_vertically_without_horizontal_offset(self):
        scale, left, top = GameBeatsApp._room_layout(2205, 698)
        self.assertAlmostEqual(scale, 5.5125)
        self.assertAlmostEqual(left, 0.0)
        self.assertGreater(top, 60.0)
        self.assertLess(top, 63.0)

    def test_rect_matches_the_fit_transform(self):
        layout = GameBeatsApp._room_layout(2205, 698)
        x0, y0, x1, y1 = GameBeatsApp._room_rect(layout, 0, 0, 400, 250)
        self.assertEqual(x0, 0)
        self.assertEqual(x1, 2205)
        self.assertLess(y0, 0)
        self.assertGreater(y1, 698)

        # A point on the visible top edge maps to canvas row zero.
        top = GameBeatsApp._room_layout(2205, 698)[2]
        x0, y0, x1, y1 = GameBeatsApp._room_rect(layout, 0, top, 400, top + 1)
        self.assertEqual(y0, 0)
        self.assertGreater(y1, 0)


class TestAmbientPooling(unittest.TestCase):
    def _app(self, reduce_motion=False):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._reduce_motion_enabled = lambda: reduce_motion
        app._room_hover = None
        app._anim_tick = 0
        app._ambient = {}
        app._room_canvas = MagicMock()
        app._room_label_hits = {}
        return app

    def test_ambient_layer_is_built_once_and_only_animated_afterward(self):
        app = self._app()
        canvas = app._room_canvas
        app._build_room_ambient(canvas, 2205, 698)
        created = canvas.create_rectangle.call_count
        deleted = canvas.delete.call_count
        self.assertGreater(created, 40)

        for tick in range(1, 12):
            app._anim_tick = tick
            app._animate_room_ambient(1000.0 + tick * 0.033, tick)

        self.assertEqual(canvas.create_rectangle.call_count, created)
        self.assertEqual(canvas.delete.call_count, deleted)

    def test_hover_reactions_reuse_pooled_items(self):
        app = self._app()
        canvas = app._room_canvas
        app._build_room_ambient(canvas, 2205, 698)
        created = canvas.create_rectangle.call_count
        deleted = canvas.delete.call_count

        for zone in ("shelf", "panel", "crate", None):
            app._set_room_hover(zone)
            app._anim_tick += 1
            app._animate_room_ambient(2000.0, app._anim_tick)

        # The CRT is decorative now; asking for its old hover zone is a no-op.
        app._set_room_hover("crt")
        self.assertIsNone(app._room_hover)

        self.assertEqual(canvas.create_rectangle.call_count, created)
        self.assertEqual(canvas.delete.call_count, deleted)
        self.assertIsNone(app._room_hover)

    def test_hotspot_outlines_are_hollow_and_brighten(self):
        app = self._app()
        canvas = app._room_canvas
        app._build_room_ambient(canvas, 2205, 698)
        outline_calls = [
            call for call in canvas.create_rectangle.call_args_list
            if "hotspot_outline" in call.kwargs.get("tags", ())
        ]
        self.assertEqual(len(outline_calls), 3)
        for call in outline_calls:
            self.assertEqual(call.kwargs.get("fill"), "")
            self.assertTrue(call.kwargs.get("outline"))

        app._set_room_hover("shelf")
        brightened = [
            call for call in canvas.itemconfigure.call_args_list
            if call.kwargs.get("outline")
        ]
        self.assertTrue(brightened)
        self.assertTrue(all(call.kwargs.get("fill") is None for call in brightened))

    def test_crt_never_becomes_a_hover_zone(self):
        app = self._app()
        app._room_canvas.winfo_width.return_value = 1000
        app._room_canvas.winfo_height.return_value = 620
        app._build_room_ambient(app._room_canvas, 1000, 620)

        # Centre of the CRT hotspot.
        scale, left, top = app._room_layout(1000, 620)
        x = int((70 - left) * scale)
        y = int((116 - top) * scale)
        self.assertEqual(app._room_zone_at(x, y), None)

    def test_reduce_motion_hides_rain_and_keeps_the_pool_static(self):
        app = self._app(reduce_motion=True)
        canvas = app._room_canvas
        app._build_room_ambient(canvas, 2205, 698)
        created = canvas.create_rectangle.call_count
        deleted = canvas.delete.call_count
        hidden_calls = [
            call for call in canvas.itemconfigure.call_args_list
            if call.kwargs.get("state") == "hidden"
        ]
        self.assertTrue(hidden_calls)

        app._anim_tick = 10
        app._animate_room_ambient(3000.0, 10)
        self.assertEqual(canvas.create_rectangle.call_count, created)
        self.assertEqual(canvas.delete.call_count, deleted)


class TestRoomClickTargets(unittest.TestCase):
    def _app(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._puppy_bbox = (0, 0, 0, 0)
        app._room_label_hits = {}
        app._room_hotspots = {
            "shelf": (10, 10, 60, 60),
            "panel": (10, 70, 60, 120),
        }
        app._nav = MagicMock()
        return app

    def test_clicking_anywhere_in_a_hotspot_navigates(self):
        from types import SimpleNamespace

        app = self._app()
        result = GameBeatsApp._on_room_canvas_click(
            app, SimpleNamespace(x=35, y=35)
        )
        self.assertEqual(result, "break")
        app._nav.assert_called_once_with("games")

    def test_label_box_outside_the_hotspot_still_navigates(self):
        from types import SimpleNamespace

        app = self._app()
        app._room_label_hits = {
            "lbl_crate": (100, 200, 240, 236, "crate"),
        }
        result = GameBeatsApp._on_room_canvas_click(
            app, SimpleNamespace(x=150, y=215)
        )
        self.assertEqual(result, "break")
        app._nav.assert_called_once_with("playlists")

    def test_crt_click_is_decorative_only(self):
        from types import SimpleNamespace

        app = self._app()
        app._room_hotspots["crt"] = (70, 70, 100, 100)
        result = GameBeatsApp._on_room_canvas_click(
            app, SimpleNamespace(x=80, y=80)
        )
        self.assertIsNone(result)
        app._nav.assert_not_called()


class TestVUPooling(unittest.TestCase):
    def test_vu_bars_are_created_once_and_then_updated(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._reduce_motion_enabled = lambda: False
        app._vu_canvas = MagicMock()
        app._vu_canvas.winfo_width.return_value = 400
        app._vu_canvas.winfo_height.return_value = 18
        app._vu_items = []
        app._vu_key = None
        app._vu_colors = []
        app._vu_heights = []
        app._vu_level = 0.7
        app._is_playing = True
        app._spotify_audio_active = False
        app._last_spotify_peak = 0.12

        app._draw_vu()
        created = app._vu_canvas.create_rectangle.call_count
        self.assertEqual(created, 21)
        app._vu_canvas.delete.reset_mock()

        for _ in range(6):
            app._animate_vu_tick(1.0)

        self.assertEqual(app._vu_canvas.create_rectangle.call_count, created)
        self.assertFalse(app._vu_canvas.delete.called)


class TestCassettePooling(unittest.TestCase):
    def test_reels_are_built_once_and_only_spokes_move(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._cart_canvas = MagicMock()
        app._cart_canvas.winfo_width.return_value = 100
        app._cart_canvas.winfo_height.return_value = 40
        app._cart_items = None
        app._cart_key = None
        app._is_playing = True
        app._spotify_audio_active = False

        app._draw_cart_cassette(app._cart_canvas)
        created = app._cart_canvas.create_line.call_count
        app._cart_canvas.delete.reset_mock()
        app._cart_canvas.create_line.reset_mock()

        for tick in range(6):
            app._update_cart_cassette(1.0 + tick * 0.033)

        self.assertEqual(app._cart_canvas.create_line.call_count, 0)
        self.assertFalse(app._cart_canvas.delete.called)
        self.assertGreaterEqual(app._cart_canvas.coords.call_count, 6)


if __name__ == "__main__":
    unittest.main()
