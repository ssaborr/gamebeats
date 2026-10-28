import unittest
from unittest.mock import patch

from ui import spotify_targeted_transport as targeted


class FakeDesktop:
    def __init__(self):
        self.main_hwnd = 222
        self.states = []
        self.muted = 0
        self._gamebeats_targeted_transport = False

    def _is_spotify_main_window(self, hwnd):
        return hwnd == self.main_hwnd

    def _remember_playback_state(self, is_playing, paused_by_game=None):
        self.states.append((bool(is_playing), paused_by_game))

    def _clear_mixer_mute(self):
        self.muted += 1

    def ensure_paused(self, paused_by_game=False):
        raise AssertionError("core ensure_paused should be replaced")

    def ensure_playing(self):
        raise AssertionError("core ensure_playing should be replaced")

    def media_play_pause(self):
        raise AssertionError("core media_play_pause should be replaced")

    def _send_appcommand_to_spotify(self, appcommand, label):
        raise AssertionError("core appcommand should be replaced")

    def _uia_toggle_playback(self):
        raise AssertionError("core UIA should be replaced")

    def _uia_invoke_transport(self, title):
        raise AssertionError("core UIA should be replaced")


class TestTargetedTransport(unittest.TestCase):
    def _install(self, hwnds=(111, 222)):
        desktop = FakeDesktop()
        posts = []

        def fake_post(hwnd, appcommand):
            posts.append((hwnd, appcommand))
            return True

        finder = patch.object(
            targeted, "_find_spotify_hwnds", return_value=list(hwnds)
        )
        poster = patch.object(targeted, "_post_message", side_effect=fake_post)
        finder.start()
        poster.start()
        self.addCleanup(finder.stop)
        self.addCleanup(poster.stop)
        targeted.install_targeted_transport(desktop, logger=lambda _m: None)
        return desktop, posts

    def test_pause_and_resume_use_main_window_once(self):
        desktop, posts = self._install()
        self.assertTrue(desktop.ensure_paused(paused_by_game=True))
        self.assertTrue(desktop.ensure_playing())
        self.assertEqual(
            posts,
            [
                (222, targeted.APPCOMMAND_MEDIA_PAUSE),
                (222, targeted.APPCOMMAND_MEDIA_PLAY),
            ],
        )
        self.assertEqual(desktop.states, [(False, True), (True, False)])
        self.assertEqual(desktop.muted, 2)

    def test_next_and_previous_are_sent_exactly_once_to_main(self):
        desktop, posts = self._install()
        self.assertTrue(
            desktop._send_appcommand_to_spotify(
                targeted.APPCOMMAND_MEDIA_NEXTTRACK, "next"
            )
        )
        self.assertTrue(
            desktop._send_appcommand_to_spotify(
                targeted.APPCOMMAND_MEDIA_PREVIOUSTRACK, "prev"
            )
        )
        self.assertEqual(
            posts,
            [
                (222, targeted.APPCOMMAND_MEDIA_NEXTTRACK),
                (222, targeted.APPCOMMAND_MEDIA_PREVIOUSTRACK),
            ],
        )

    def test_uia_paths_are_disabled(self):
        desktop, _posts = self._install()
        self.assertFalse(desktop._uia_toggle_playback())
        self.assertFalse(desktop._uia_invoke_transport("Next"))
        self.assertEqual(desktop._uia_player_button(), (None, None, True))

    def test_no_spotify_window_fails_closed(self):
        desktop, posts = self._install(hwnds=())
        self.assertFalse(desktop.ensure_paused())
        self.assertFalse(desktop.ensure_playing())
        self.assertEqual(posts, [])

    def test_install_is_idempotent(self):
        desktop, posts = self._install()
        installed_pause = desktop.ensure_paused
        with patch.object(targeted, "_find_spotify_hwnds", return_value=[111, 222]):
            targeted.install_targeted_transport(desktop, logger=lambda _m: None)
        self.assertIs(desktop.ensure_paused, installed_pause)
        desktop.ensure_paused()
        self.assertEqual(posts, [(222, targeted.APPCOMMAND_MEDIA_PAUSE)])


if __name__ == "__main__":
    unittest.main()
