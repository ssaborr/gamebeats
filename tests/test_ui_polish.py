import os
import sys
import time
import unittest
from unittest.mock import MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(BASE_DIR, "source")
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)

from ui.app import (
    GameBeatsApp,
    compute_initial_window_size,
    format_clock,
)


class TestWindowFit(unittest.TestCase):
    def test_high_dpi_window_stays_inside_the_screen(self):
        w, h = compute_initial_window_size(2560, 1440, 1.75)
        self.assertLessEqual(w, 1280)
        self.assertLessEqual(h, 860)
        self.assertLessEqual(int(h * 1.75), 1440)
        self.assertLessEqual(int(w * 1.75), 2560)

    def test_150_percent_1080p_keeps_the_deck_visible(self):
        w, h = compute_initial_window_size(1920, 1080, 1.5)
        self.assertGreaterEqual(h, 700)
        self.assertLessEqual(int(h * 1.5), 1080)
        self.assertLessEqual(int(w * 1.5), 1920)

    def test_low_resolution_uses_the_available_width(self):
        w, h = compute_initial_window_size(1366, 768, 1.0)
        self.assertEqual(w, 1280)
        self.assertLessEqual(h, 768)
        self.assertGreaterEqual(h, 700)


class TestDeckProgress(unittest.TestCase):
    def _app(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app.progress_bar = MagicMock()
        app.elapsed_lbl = MagicMock()
        app.duration_lbl = MagicMock()
        app.track_lbl = MagicMock()
        app.track_lbl.cget.return_value = "The Unknown"
        return app

    def test_clock_formatting(self):
        self.assertEqual(format_clock(0), "0:00")
        self.assertEqual(format_clock(65.9), "1:05")
        self.assertEqual(format_clock(-4), "0:00")
        self.assertEqual(format_clock("nope"), "--:--")

    def test_progress_extrapolates_only_while_playing(self):
        app = self._app()
        now = time.time()
        app._track_progress_base = (30.0, 120.0, now - 10.0, True)
        app._update_deck_progress(now)
        fraction = app.progress_bar.set_progress.call_args[0][0]
        self.assertAlmostEqual(fraction, 40.0 / 120.0, places=2)

        app.progress_bar.reset_mock()
        app._track_progress_base = (30.0, 120.0, now - 10.0, False)
        app._update_deck_progress(now)
        fraction = app.progress_bar.set_progress.call_args[0][0]
        self.assertAlmostEqual(fraction, 30.0 / 120.0, places=2)

    def test_missing_seek_data_shows_a_live_status(self):
        app = self._app()
        app._track_progress_base = None
        app._is_playing = True
        app._update_deck_progress()
        app.progress_bar.set_status.assert_called_with("LIVE", active=True)
        app.elapsed_lbl.configure.assert_called_with(text="")

    def test_no_track_never_reports_live(self):
        app = self._app()
        app.track_lbl.cget.return_value = "Nothing playing"
        app._track_progress_base = None
        app._is_playing = True
        app._update_deck_progress()
        app.progress_bar.set_status.assert_called_with("STANDBY", active=False)


class TestSpriteScale(unittest.TestCase):
    def test_puppy_scale_is_a_whole_number(self):
        self.assertEqual(GameBeatsApp._puppy_scale_for_width(2205), 5)
        self.assertEqual(GameBeatsApp._puppy_scale_for_width(1600), 4)
        self.assertGreaterEqual(GameBeatsApp._puppy_scale_for_width(200), 3)
        scale = GameBeatsApp._puppy_scale_for_width(2205)
        self.assertEqual((64 * scale, 72 * scale), (320, 360))


class TestBackgroundCaches(unittest.TestCase):
    def test_seamless_cache_does_not_read_tk(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._seamless_music_value = True
        app.seamless_music_var = MagicMock()
        self.assertTrue(app._seamless_music_enabled())
        app.seamless_music_var.get.assert_not_called()

    def test_auto_pause_uses_the_cached_value(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app.spotify = object()
        app.auto_mode = MagicMock()
        app._auto_mode_value = False
        app._seamless_music_value = False
        app._is_playing = True
        self.assertFalse(app._auto_pause_allowed(False))
        app.auto_mode.get.assert_not_called()


class TestShortcutGuard(unittest.TestCase):
    def test_text_focus_blocks_global_shortcuts(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app.root = MagicMock()
        entry = MagicMock()
        entry.winfo_class.return_value = "Entry"
        app.root.focus_get.return_value = entry
        self.assertTrue(app._shortcut_typing())

        app.root.focus_get.return_value = None
        self.assertFalse(app._shortcut_typing())

    def test_modifier_state_is_detected(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        event = MagicMock(state=0x4)
        self.assertTrue(app._shortcut_modified(event))
        event.state = 0
        self.assertFalse(app._shortcut_modified(event))


class TestToplineVisibility(unittest.TestCase):
    def _app(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app.topline = MagicMock()
        app.content = MagicMock()
        return app

    def test_den_hides_the_breadcrumb_strip(self):
        app = self._app()
        app.topline.winfo_manager.return_value = "pack"
        GameBeatsApp._set_topline_visible(app, False)
        app.topline.pack_forget.assert_called_once_with()

    def test_other_pages_restore_the_breadcrumb_strip_before_content(self):
        app = self._app()
        app.topline.winfo_manager.return_value = ""
        GameBeatsApp._set_topline_visible(app, True)
        app.topline.pack.assert_called_once_with(
            fill="x", before=app.content
        )

    def test_nav_uses_den_visibility_rule(self):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._page_main = MagicMock()
        app._page_playlists = None
        app._page_games = None
        app._page_blocked = None
        app._page_settings = None
        app._page_faq = None
        app._active_page_widget = None
        app._set_topline_visible = MagicMock()
        app._show_page = MagicMock()
        app._paint_footer = MagicMock()
        app._redraw_room = MagicMock()
        app._start_puppy_animation = MagicMock()
        app._stop_puppy_animation = MagicMock()

        GameBeatsApp._nav(app, "main")

        app._set_topline_visible.assert_called_once_with(False)


class TestPageTransition(unittest.TestCase):
    def _app(self, reduce_motion):
        app = GameBeatsApp.__new__(GameBeatsApp)
        app.root = MagicMock()
        app.content = MagicMock()
        app.content.winfo_width.return_value = 1000
        app._page_transition_job = None
        app._reduce_motion_enabled = MagicMock(return_value=reduce_motion)
        return app

    def test_reduce_motion_shows_the_page_immediately(self):
        app = self._app(True)
        target = MagicMock()
        previous = MagicMock()

        GameBeatsApp._show_page(app, target, previous)

        target.place.assert_called_once_with(
            x=0, y=0, relwidth=1, relheight=1
        )
        previous.place_forget.assert_called_once_with()
        app.root.after.assert_not_called()

    def test_normal_switch_slides_the_new_page_in(self):
        app = self._app(False)
        target = MagicMock()
        previous = MagicMock()
        app.root.after.return_value = "transition-job"

        GameBeatsApp._show_page(app, target, previous)

        target.place.assert_called_once_with(
            x=18, y=0, relwidth=1, relheight=1
        )
        target.lift.assert_called_once_with()
        app.root.after.assert_called_once()
        self.assertEqual(app._page_transition_target, target)
        self.assertEqual(app._page_transition_previous, previous)

    def test_transition_finishes_at_rest_and_hides_the_old_page(self):
        app = self._app(False)
        target = MagicMock()
        previous = MagicMock()
        app._page_transition_target = target
        app._page_transition_previous = previous
        app._page_transition_offset = 18
        app._page_transition_step = 5
        app._page_transition_steps = 6

        GameBeatsApp._step_page_transition(app)

        target.place.assert_called_once_with(
            x=0, y=0, relwidth=1, relheight=1
        )
        previous.place_forget.assert_called_once_with()
        self.assertIsNone(app._page_transition_target)
        self.assertIsNone(app._page_transition_previous)


if __name__ == "__main__":
    unittest.main()
