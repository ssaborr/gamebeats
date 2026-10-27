import sys
import os
import time
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(BASE_DIR, "source")
if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)


class TestSpotifyDesktop(unittest.TestCase):
    def test_ensure_paused_flag(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._paused_by_game = False
        sd._local_status = MagicMock(return_value={"playing": False})
        sd._local_is_playing = MagicMock(return_value=False)
        sd._desktop_audible = MagicMock(return_value=True)
        sd._uia_toggle_playback = MagicMock(return_value=True)
        sd._send_media_command = MagicMock(return_value=True)
        sd._send_playback_command = MagicMock(return_value=True)
        sd._clear_mixer_mute = MagicMock()
        sd._active_pid = None
        sd._last_hwnd = None
        sd._log = MagicMock()
        
        # Bind real _remember_playback_state and ensure_paused
        sd._remember_playback_state = SpotifyDesktopController._remember_playback_state.__get__(sd, SpotifyDesktopController)
        sd.ensure_paused = SpotifyDesktopController.ensure_paused.__get__(sd, SpotifyDesktopController)
        
        # Test manual pause (paused_by_game=False)
        sd.ensure_paused(paused_by_game=False)
        self.assertFalse(sd._paused_by_game)
        
        # Test game auto-pause (paused_by_game=True)
        sd.ensure_paused(paused_by_game=True)
        self.assertTrue(sd._paused_by_game)

    def test_ensure_playing_clears_game_pause(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._paused_by_game = True
        sd._local_is_playing = MagicMock(return_value=True)
        sd._desktop_audible = MagicMock(return_value=True)
        sd._uia_toggle_playback = MagicMock(return_value=True)
        sd._clear_mixer_mute = MagicMock()
        sd._send_media_command = MagicMock(return_value=True)
        sd._log = MagicMock()
        
        sd._remember_playback_state = SpotifyDesktopController._remember_playback_state.__get__(sd, SpotifyDesktopController)
        sd.ensure_playing = SpotifyDesktopController.ensure_playing.__get__(sd, SpotifyDesktopController)
        sd.ensure_playing()
        
        self.assertFalse(sd._paused_by_game)

    def test_media_pause_calls_ensure_paused_without_game_flag(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd.ensure_paused = MagicMock(return_value=True)
        sd._media_pause = SpotifyDesktopController._media_pause.__get__(sd, SpotifyDesktopController)
        
        sd._media_pause()
        sd.ensure_paused.assert_called_with(paused_by_game=False)


class TestSpotifyWeb(unittest.TestCase):
    def test_web_ensure_paused_passes_flag(self):
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        sw._paused_by_game = False
        sw._desktop_sidecar_active = True
        sw._use_simplified_dual_flow = MagicMock(return_value=False)
        sw._uses_browser_player = MagicMock(return_value=False)
        sw._is_web_player_active = MagicMock(return_value=False)
        sw._uses_desktop_player = MagicMock(return_value=True)
        sw._source_peaks = MagicMock(return_value=(0.0, 0.0))
        sw._note_audio_source = MagicMock()
        sw._loopback_audible = MagicMock(return_value=False)
        sw._pause_desktop = SpotifyWebController._pause_desktop.__get__(
            sw, SpotifyWebController
        )
        sw._clear_mixer_mute = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.ensure_paused.return_value = True
        sw._desktop_helper = MagicMock(return_value=mock_desktop)
        sw._remember_playback_state = MagicMock()
        sw._log = MagicMock()
        
        sw.ensure_paused = SpotifyWebController.ensure_paused.__get__(sw, SpotifyWebController)
        
        sw.ensure_paused(paused_by_game=False)
        mock_desktop.ensure_paused.assert_called_with(paused_by_game=False)
        
        sw.ensure_paused(paused_by_game=True)
        mock_desktop.ensure_paused.assert_called_with(paused_by_game=True)


class TestAudioMonitorSources(unittest.TestCase):
    def test_all_spotify_pids_include_browser_and_desktop(self):
        from core import audio_monitor as am

        with patch.object(am, "_registered_music_pids", [222]), \
                patch.object(am, "_browser_audio_only", True), \
                patch.object(am, "_desktop_spotify_pids", return_value=[111]):
            self.assertEqual(am.get_all_spotify_pids(), [111, 222])

    def test_browser_peak_only_uses_registered_music_pids(self):
        from core import audio_monitor as am

        with patch.object(am, "_registered_music_pids", [222]), \
                patch.object(am, "_session_peak_for_pids", return_value=0.05) as peak:
            value, status = am.get_browser_spotify_peak()
        self.assertEqual(status, "ok")
        self.assertAlmostEqual(value, 0.05)
        peak.assert_called_once_with([222])


class TestSpotifyWebSourceFallback(unittest.TestCase):
    def _make_web(self):
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        sw._clear_mixer_mute = MagicMock()
        sw._uses_desktop_player = MagicMock(return_value=False)
        sw._remember_playback_state = MagicMock()
        sw._note_audio_source = MagicMock()
        sw._loopback_audible = MagicMock(return_value=False)
        sw._run_on_page = MagicMock(return_value=True)
        sw._last_error = ""
        return sw

    def test_pause_targets_audible_desktop_source(self):
        from core.spotify_web import SpotifyWebController
        sw = self._make_web()
        sw._source_peaks = MagicMock(return_value=(0.0, 0.05))
        sw._pause_desktop = MagicMock(return_value=True)
        sw._wait_for_silence = MagicMock(return_value=True)
        sw.ensure_paused = SpotifyWebController.ensure_paused.__get__(
            sw, SpotifyWebController
        )

        self.assertTrue(sw.ensure_paused(paused_by_game=True))
        sw._pause_desktop.assert_called_with(True)
        sw._run_on_page.assert_not_called()

    def test_resume_prefers_last_audible_desktop_source(self):
        from core.spotify_web import SpotifyWebController
        sw = self._make_web()
        sw._source_peaks = MagicMock(return_value=(0.0, 0.0))
        sw._last_audio_source = "desktop"
        sw._resume_desktop = MagicMock(return_value=True)
        sw.ensure_playing = SpotifyWebController.ensure_playing.__get__(
            sw, SpotifyWebController
        )

        self.assertTrue(sw.ensure_playing())
        sw._resume_desktop.assert_called_once()
        sw._run_on_page.assert_not_called()

    def test_resume_never_falls_back_to_global_media_key(self):
        from core.spotify_web import SpotifyWebController
        sw = self._make_web()
        sw._source_peaks = MagicMock(return_value=(0.0, 0.0))
        sw._loopback_audible = MagicMock(return_value=False)
        sw._run_on_page = MagicMock(return_value=False)
        sw._resume_desktop = MagicMock(return_value=False)
        sw._send_global_media_key = MagicMock(return_value=True)
        sw.ensure_playing = SpotifyWebController.ensure_playing.__get__(
            sw, SpotifyWebController
        )

        self.assertFalse(sw.ensure_playing())
        # A global media key can resume the other app whose audio just
        # stopped; auto-resume must stay targeted at Spotify.
        sw._send_global_media_key.assert_not_called()


class TestRuntimeOverlay(unittest.TestCase):
    def test_overlay_show_preserves_playing_state(self):
        from ui.runtime_overlay import RuntimeOverlay
        overlay = MagicMock(spec=RuntimeOverlay)
        overlay._fade_job = None
        overlay.play_btn = MagicMock()
        overlay.status_lbl = MagicMock()
        overlay.deiconify = MagicMock()
        overlay.update_status = MagicMock()
        overlay._position_window = MagicMock()
        overlay.attributes = MagicMock()
        overlay.focus_force = MagicMock()
        overlay._query_playing = MagicMock(return_value=True)
        overlay.show = RuntimeOverlay.show.__get__(overlay, RuntimeOverlay)

        overlay.show()
        overlay.update_status.assert_called_with(playing=True)

        overlay._query_playing = MagicMock(return_value=False)
        overlay.show()
        overlay.update_status.assert_called_with(playing=False)


class TestRuntimeOverlayRefusedActions(unittest.TestCase):
    def test_refused_play_does_not_paint_a_playing_icon(self):
        from ui.runtime_overlay import RuntimeOverlay
        overlay = MagicMock(spec=RuntimeOverlay)
        overlay.on_play = MagicMock(return_value=False)
        overlay.play_btn = MagicMock()
        overlay.status_lbl = MagicMock()
        overlay._play = RuntimeOverlay._play.__get__(overlay, RuntimeOverlay)

        self.assertFalse(overlay._play())
        overlay.play_btn.configure.assert_not_called()
        overlay.status_lbl.configure.assert_not_called()

    def test_refused_pause_does_not_paint_a_paused_icon(self):
        from ui.runtime_overlay import RuntimeOverlay
        overlay = MagicMock(spec=RuntimeOverlay)
        overlay.on_pause = MagicMock(return_value=False)
        overlay.play_btn = MagicMock()
        overlay.status_lbl = MagicMock()
        overlay._pause = RuntimeOverlay._pause.__get__(overlay, RuntimeOverlay)

        self.assertFalse(overlay._pause())
        overlay.play_btn.configure.assert_not_called()
        overlay.status_lbl.configure.assert_not_called()


class TestAppIntentionalPause(unittest.TestCase):
    def test_intentional_pause_active_manual_paused(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._intentional_pause_active = GameBeatsApp._intentional_pause_active.__get__(app, GameBeatsApp)
        
        app._manual_paused = True
        app._user_paused_flag = False
        app._paused_by_game_flag = False
        app.spotify = None
        app._pause_stack = []
        app._last_track_info = None
        self.assertTrue(app._intentional_pause_active())

    def test_intentional_pause_active_does_not_guess_from_track_progress(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._intentional_pause_active = GameBeatsApp._intentional_pause_active.__get__(app, GameBeatsApp)

        app._manual_paused = False
        app._user_paused_flag = False
        app._paused_by_game_flag = False
        app.spotify = None
        app._pause_stack = []

        # A stale "paused mid-track" snapshot must NOT be treated as an
        # intentional pause. Doing so used to suppress the notifier at a real
        # playlist end (and could misfire after a transient poll).
        app._last_track_info = {
            "name": "Test Song",
            "is_playing": False,
            "progress_ms": 45000,
            "duration_ms": 180000,
        }
        self.assertFalse(app._intentional_pause_active())

        # Explicit game-audio pause is authoritative.
        app._paused_by_game_flag = True
        self.assertTrue(app._intentional_pause_active())

    def test_update_np_does_not_clear_manual_pause_on_silence(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._update_np = GameBeatsApp._update_np.__get__(app, GameBeatsApp)
        app._intentional_pause_active = MagicMock(return_value=True)
        app._now_playing_playlist_title = MagicMock(return_value="My Playlist")
        app.track_lbl = MagicMock()
        app.artist_lbl = MagicMock()
        app._current_playlist_uri = "spotify:playlist:123"
        app._play_in_progress = False
        app._user_toggle_ts = time.time() - 4.0
        app._audio_monitor_running = True
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._manual_paused = True
        app._user_paused_flag = True
        app._mark_music_missing = MagicMock()
        
        # Stale track with is_playing=True
        t = {"name": "Test", "is_playing": True, "progress_ms": 50000, "duration_ms": 200000}
        app._update_np(t)
        
        # Manual pause should NOT be reset because Spotify is silent!
        self.assertTrue(app._manual_paused)
        self.assertTrue(app._user_paused_flag)

    def test_mark_music_missing_suppressed_when_intentional_pause(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._mark_music_missing = GameBeatsApp._mark_music_missing.__get__(app, GameBeatsApp)
        app._intentional_pause_active = MagicMock(return_value=True)
        app._user_toggle_ts = time.time() - 10.0
        app._playlist_end_pending = False
        app._music_missing_since = 123.0
        
        app._mark_music_missing()
        
        # Should clear music_missing_since and NOT set playlist_end_pending
        self.assertEqual(app._music_missing_since, 0.0)
        self.assertFalse(app._playlist_end_pending)

    def test_mark_music_missing_suppressed_until_playlist_audio_armed(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._mark_music_missing = GameBeatsApp._mark_music_missing.__get__(app, GameBeatsApp)
        app._intentional_pause_active = MagicMock(return_value=False)
        app._player_is_playing_cached = MagicMock(return_value=False)
        app._playlist_end_prompt_allowed = MagicMock(return_value=True)
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._should_handle_auto_stop = MagicMock(return_value=True)
        app._audio_monitor_running = True
        app._playlist_audio_armed = False
        app._user_toggle_ts = time.time() - 10.0
        app._music_missing_since = 123.0
        app._playlist_end_pending = False

        app._mark_music_missing()

        # Nothing has been heard from this playlist yet, so silence is not an
        # end-of-playlist signal and no notifier should be shown.
        self.assertEqual(app._music_missing_since, 0.0)
        self.assertFalse(app._playlist_end_pending)
        app._show_mascot_prompt.assert_not_called()

    def test_show_mascot_prompt_dismiss_defers_cooldown(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._defer_playlist_end_prompt = MagicMock()
        app._current_game = "TestGame"
        app._current_playlist_uri = "spotify:playlist:123"
        
        # Dismiss defer call
        app._defer_playlist_end_prompt(extra_seconds=60.0, until_audio=True, reason="User dismissed notifier")
        app._defer_playlist_end_prompt.assert_called_with(
            extra_seconds=60.0, until_audio=True, reason="User dismissed notifier"
        )

    def test_spotify_is_playing_for_toggle_respects_explicit_pause(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._spotify_is_playing_for_toggle = GameBeatsApp._spotify_is_playing_for_toggle.__get__(app, GameBeatsApp)

        # Explicit pause wins even if loopback still reports residual audio for
        # a moment. Otherwise the very next click sends *pause* again.
        app._spotify_sound_detected_recently = MagicMock(return_value=True)
        app._intentional_pause_active = MagicMock(return_value=True)
        app._is_web_mode = MagicMock(return_value=True)
        app._manual_paused = True
        self.assertFalse(app._spotify_is_playing_for_toggle())

        # Not paused + audible -> playing.
        app._intentional_pause_active = MagicMock(return_value=False)
        app._last_track_info = {}
        app._is_playing = True
        self.assertTrue(app._spotify_is_playing_for_toggle())

        # Not paused + silent + cached state paused -> paused.
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._last_track_info = {"is_playing": False}
        app._is_playing = False
        self.assertFalse(app._spotify_is_playing_for_toggle())

    def test_pause_spotify_for_game_audio(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._pause_spotify_for_game_audio = GameBeatsApp._pause_spotify_for_game_audio.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app._send_spotify_pause_command = MagicMock(return_value=True)
        app._seamless_music_enabled = MagicMock(return_value=False)
        app._manual_paused = False
        app._user_paused_flag = False
        app._clear_spotify_game_pause_claim = MagicMock()
        app._add_pause_reason = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._set_puppy_singing_visible = MagicMock()
        app.root = MagicMock()

        app._pause_spotify_for_game_audio(peak=0.5)

        app._send_spotify_pause_command.assert_called_with(
            paused_by_game=True, was_playing=True
        )
        self.assertTrue(app._paused_by_game_flag)

    def test_resume_spotify_after_game_quiet_respects_manual_pause(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._resume_spotify_after_game_quiet = GameBeatsApp._resume_spotify_after_game_quiet.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app._paused_by_game_flag = True
        app._manual_paused = True  # User intentionally paused!
        app._user_paused_flag = True
        
        app._resume_spotify_after_game_quiet()
        
        # Spotify should NOT be resumed
        app.spotify.ensure_playing.assert_not_called()
        self.assertTrue(app._paused_by_game_flag)

    def test_send_spotify_resume_command_never_replays_playlist(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_resume_command = GameBeatsApp._send_spotify_resume_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        # Normal resume fails and the targeted fallback is unavailable too.
        app.spotify.ensure_playing.return_value = False
        app.spotify.resume.return_value = False
        app.spotify.play.return_value = False
        app.spotify.media_play_pause.return_value = False
        app._spotify_audio_playing_now = MagicMock(return_value=False)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=False)
        app._send_targeted_spotify_command = MagicMock(return_value=False)
        app._audio_monitor_running = False
        app._current_playlist_uri = "spotify:playlist:current_123"
        app.spotify.play_playlist.return_value = True

        ok = app._send_spotify_resume_command()

        self.assertFalse(ok)
        self.assertEqual(app.spotify.ensure_playing.call_count, 1)
        app._send_targeted_spotify_command.assert_called_with("play")
        # Never navigate to/replay the playlist. That was the "resume starts
        # another playlist" bug.
        app.spotify.play_playlist.assert_not_called()

    def test_send_spotify_resume_command_uses_targeted_fallback(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_resume_command = GameBeatsApp._send_spotify_resume_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app.spotify.ensure_playing.return_value = False
        app._spotify_audio_playing_now = MagicMock(return_value=False)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=False)
        app._send_targeted_spotify_command = MagicMock(return_value=True)
        app._audio_monitor_running = False

        self.assertTrue(app._send_spotify_resume_command())
        app._send_targeted_spotify_command.assert_called_once_with("play")

    def test_send_spotify_resume_requires_audio_when_monitor_is_live(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_resume_command = GameBeatsApp._send_spotify_resume_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        # ensure_playing() says yes, but its cached state can be stale.
        app.spotify.ensure_playing.return_value = True
        app._spotify_audio_playing_now = MagicMock(return_value=False)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=False)
        app._wait_for_spotify_playback = MagicMock(return_value=False)
        app._send_targeted_spotify_command = MagicMock(return_value=True)
        app._audio_monitor_running = True

        self.assertFalse(app._send_spotify_resume_command())
        # It should try the targeted command once after ensure_playing(), then
        # verify actual audio again before claiming success.
        app._send_targeted_spotify_command.assert_called_once_with("play")

    def test_send_spotify_resume_uses_audio_that_actually_came_back(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_resume_command = GameBeatsApp._send_spotify_resume_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app.spotify.ensure_playing.return_value = True
        app._spotify_audio_playing_now = MagicMock(return_value=True)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=False)
        app._audio_monitor_running = True

        self.assertTrue(app._send_spotify_resume_command())
        # Already audible: no extra pause/toggle command is needed.
        app._send_targeted_spotify_command.assert_not_called()

    def test_desktop_resume_uses_fast_targeted_command_first(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_resume_command = GameBeatsApp._send_spotify_resume_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app._spotify_audio_playing_now = MagicMock(return_value=False)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=True)
        app._send_targeted_spotify_command = MagicMock(return_value=True)
        app._wait_for_spotify_playback = MagicMock(return_value=True)
        app._audio_monitor_running = True

        self.assertTrue(app._send_spotify_resume_command())
        app._send_targeted_spotify_command.assert_called_once_with("play")
        # The slow UIA/ensure path is skipped when the targeted command works.
        app.spotify.ensure_playing.assert_not_called()

    def test_desktop_pause_uses_fast_targeted_command_first(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_pause_command = GameBeatsApp._send_spotify_pause_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app._spotify_audio_playing_now = MagicMock(return_value=True)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=True)
        app._send_targeted_spotify_command = MagicMock(return_value=True)
        app._wait_for_spotify_playback = MagicMock(return_value=True)
        app._audio_monitor_running = True
        app._is_playing = True

        self.assertTrue(app._send_spotify_pause_command(was_playing=True))
        app._send_targeted_spotify_command.assert_called_once_with("pause")
        app.spotify.ensure_paused.assert_not_called()

    def test_send_spotify_pause_command_uses_targeted_fallback(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_pause_command = GameBeatsApp._send_spotify_pause_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app.spotify.ensure_paused.return_value = False
        app._spotify_audio_playing_now = MagicMock(return_value=True)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=False)
        app._send_targeted_spotify_command = MagicMock(return_value=True)
        app._wait_for_spotify_playback = MagicMock(return_value=True)
        app._audio_monitor_running = True
        app._is_playing = True

        self.assertTrue(app._send_spotify_pause_command())
        app._send_targeted_spotify_command.assert_called_once_with("pause")

    def test_send_spotify_pause_command_never_claims_pause_while_audio_remains(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._send_spotify_pause_command = GameBeatsApp._send_spotify_pause_command.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app.spotify.ensure_paused.return_value = True
        app._spotify_audio_playing_now = MagicMock(return_value=True)
        app._spotify_desktop_is_primary_source = MagicMock(return_value=False)
        app._send_targeted_spotify_command = MagicMock(return_value=True)
        app._wait_for_spotify_playback = MagicMock(return_value=False)
        app._audio_monitor_running = True
        app._is_playing = True

        self.assertFalse(app._send_spotify_pause_command())
        self.assertEqual(app._send_targeted_spotify_command.call_count, 2)

    def test_remember_current_playlist_preserves_manual_pause_by_default(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._remember_current_playlist = GameBeatsApp._remember_current_playlist.__get__(app, GameBeatsApp)
        app._manual_paused = True
        app._user_paused_flag = True
        app._current_playlist_uri = ""
        app._current_playlist_name = ""
        app._current_playlist_query = ""
        app.root = MagicMock()
        
        # When called without reset_pause_flags (e.g. from poller or metadata sync)
        app._remember_current_playlist("spotify:playlist:abc", "Test", "query", reset_pause_flags=False)
        self.assertTrue(app._manual_paused)
        self.assertTrue(app._user_paused_flag)

        # When explicitly called with reset_pause_flags=True (new game playlist launch)
        app._remember_current_playlist("spotify:playlist:xyz", "New Game", "query", reset_pause_flags=True)
        self.assertFalse(app._manual_paused)
        self.assertFalse(app._user_paused_flag)

    def test_fetch_track_suppresses_mark_missing_when_intentional_pause(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._fetch_track = GameBeatsApp._fetch_track.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app.spotify.get_current_track.return_value = None
        app._intentional_pause_active = MagicMock(return_value=True)
        app._last_track_info = {"name": "Paused Song", "is_playing": False}
        app.root = MagicMock()
        
        app._fetch_track()
        
        # Should NOT wipe _last_track_info and should NOT schedule _mark_music_missing
        self.assertIsNotNone(app._last_track_info)
        app.root.after.assert_not_called()


class TestDesktopStateAndControls(unittest.TestCase):
    def test_desktop_is_playing_from_window_titles(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._local_is_playing = MagicMock(return_value=None)
        sd._log = MagicMock()
        sd._desktop_is_playing = SpotifyDesktopController._desktop_is_playing.__get__(sd, SpotifyDesktopController)

        with patch("core.spotify_desktop._find_spotify_window_titles", return_value=["Daft Punk - One More Time"]):
            self.assertTrue(sd._desktop_is_playing())

        with patch("core.spotify_desktop._find_spotify_window_titles", return_value=["Spotify Free"]):
            self.assertFalse(sd._desktop_is_playing())

        with patch("core.spotify_desktop._find_spotify_window_titles", return_value=["Spotify"]):
            self.assertFalse(sd._desktop_is_playing())

        with patch("core.spotify_desktop._find_spotify_window_titles", return_value=[]):
            self.assertIsNone(sd._desktop_is_playing())

    def test_desktop_ensure_paused_idempotent_when_already_paused(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._paused_by_game = False
        sd._desktop_audible = MagicMock(return_value=False)  # Already paused!
        sd._uia_toggle_playback = MagicMock()
        sd._send_appcommand_to_spotify = MagicMock()
        sd._send_playback_command = MagicMock()
        sd._send_input_media_key = MagicMock()
        sd._remember_playback_state = MagicMock()
        sd.ensure_paused = SpotifyDesktopController.ensure_paused.__get__(sd, SpotifyDesktopController)

        with patch("core.audio_monitor.get_desktop_spotify_peak",
                   return_value=(0.0, "ok")):
            ok = sd.ensure_paused(paused_by_game=False)
        self.assertTrue(ok)
        sd._uia_toggle_playback.assert_not_called()
        sd._send_appcommand_to_spotify.assert_not_called()
        sd._send_playback_command.assert_not_called()
        sd._send_input_media_key.assert_not_called()

    def test_desktop_command_never_uses_global_media_key(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._send_appcommand_to_spotify = MagicMock(return_value=False)
        sd._send_input_media_key = MagicMock(return_value=True)
        sd._powershell_sendkeys = MagicMock(return_value=True)
        sd._log = MagicMock()
        sd._last_error = ""
        sd._send_playback_command = (
            SpotifyDesktopController._send_playback_command.__get__(
                sd, SpotifyDesktopController
            )
        )

        self.assertFalse(sd._send_playback_command("toggle", use_toggle=True))
        # A global key would be routed to whichever media app is active,
        # potentially the other app that just stopped playing.
        sd._send_input_media_key.assert_not_called()
        sd._powershell_sendkeys.assert_not_called()

    def test_desktop_ensure_playing_idempotent_when_already_playing(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._paused_by_game = False
        sd._desktop_audible = MagicMock(return_value=True)  # Already playing!
        sd._uia_toggle_playback = MagicMock()
        sd._send_appcommand_to_spotify = MagicMock()
        sd._send_playback_command = MagicMock()
        sd._send_input_media_key = MagicMock()
        sd._remember_playback_state = MagicMock()
        sd.ensure_playing = SpotifyDesktopController.ensure_playing.__get__(sd, SpotifyDesktopController)

        ok = sd.ensure_playing()
        self.assertTrue(ok)
        sd._uia_toggle_playback.assert_not_called()
        sd._send_appcommand_to_spotify.assert_not_called()
        sd._send_playback_command.assert_not_called()

    def test_desktop_known_pause_state_overrides_track_title(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._local_is_playing = MagicMock(return_value=None)
        sd._log = MagicMock()
        sd._playback_state_known = True
        sd._is_playing = False
        sd._desktop_is_playing = SpotifyDesktopController._desktop_is_playing.__get__(
            sd, SpotifyDesktopController
        )

        # Spotify's title often still shows the track while paused. Our own
        # confirmed command state must win.
        with patch(
            "core.spotify_desktop._find_spotify_window_titles",
            return_value=["Daft Punk - One More Time"],
        ):
            self.assertFalse(sd._desktop_is_playing())

        sd._is_playing = True
        with patch(
            "core.spotify_desktop._find_spotify_window_titles",
            return_value=["Spotify"],
        ):
            self.assertTrue(sd._desktop_is_playing())

    def test_desktop_resume_does_not_use_window_media_command_when_uia_fails(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._playback_state_known = True
        sd._is_playing = False          # We paused it.
        sd._paused_by_game = True       # Our auto-pause owns the resume.
        sd._desktop_audible = MagicMock(return_value=False)
        sd._uia_toggle_playback = MagicMock(return_value=False)
        sd._send_appcommand_to_spotify = MagicMock(return_value=True)
        sd._send_playback_command = MagicMock(return_value=True)
        sd._send_input_media_key = MagicMock(return_value=True)
        sd._remember_playback_state = MagicMock()
        sd.ensure_playing = SpotifyDesktopController.ensure_playing.__get__(
            sd, SpotifyDesktopController
        )

        self.assertFalse(sd.ensure_playing())
        sd._uia_toggle_playback.assert_called_once()
        # A window media command can still be routed by Windows to the other
        # app's media session; auto-resume must not fall back to it.
        sd._send_appcommand_to_spotify.assert_not_called()
        sd._send_input_media_key.assert_not_called()
        sd._remember_playback_state.assert_not_called()

    def test_desktop_resume_uses_spotify_ui_automation_first(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._playback_state_known = True
        sd._is_playing = False
        sd._paused_by_game = True
        sd._desktop_audible = MagicMock(return_value=False)
        sd._uia_toggle_playback = MagicMock(return_value=True)
        sd._send_appcommand_to_spotify = MagicMock(return_value=True)
        sd._send_input_media_key = MagicMock(return_value=True)
        sd._remember_playback_state = MagicMock()
        sd.ensure_playing = SpotifyDesktopController.ensure_playing.__get__(
            sd, SpotifyDesktopController
        )

        self.assertTrue(sd.ensure_playing())
        sd._uia_toggle_playback.assert_called_once()
        # UIA pressed Spotify's own button; do not also send a media command
        # that Windows could route to YouTube.
        sd._send_appcommand_to_spotify.assert_not_called()
        sd._send_input_media_key.assert_not_called()
        sd._remember_playback_state.assert_called_with(True, paused_by_game=False)

    def test_desktop_pause_does_not_use_window_media_command_when_uia_fails(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._paused_by_game = False
        sd._playback_state_known = True
        sd._is_playing = True           # We started it.
        sd._desktop_audible = MagicMock(return_value=True)
        sd._uia_toggle_playback = MagicMock(return_value=False)
        sd._send_appcommand_to_spotify = MagicMock(return_value=True)
        sd._send_playback_command = MagicMock(return_value=True)
        sd._send_input_media_key = MagicMock(return_value=True)
        sd._remember_playback_state = MagicMock()
        sd.ensure_paused = SpotifyDesktopController.ensure_paused.__get__(
            sd, SpotifyDesktopController
        )

        self.assertFalse(sd.ensure_paused(paused_by_game=False))
        sd._uia_toggle_playback.assert_called_once()
        sd._send_appcommand_to_spotify.assert_not_called()
        sd._send_input_media_key.assert_not_called()
        sd._remember_playback_state.assert_not_called()

    def test_desktop_pause_uses_spotify_ui_automation_first(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._paused_by_game = False
        sd._desktop_audible = MagicMock(return_value=True)
        sd._uia_toggle_playback = MagicMock(return_value=True)
        sd._send_appcommand_to_spotify = MagicMock(return_value=True)
        sd._send_input_media_key = MagicMock(return_value=True)
        sd._remember_playback_state = MagicMock()
        sd.ensure_paused = SpotifyDesktopController.ensure_paused.__get__(
            sd, SpotifyDesktopController
        )

        self.assertTrue(sd.ensure_paused(paused_by_game=True))
        sd._uia_toggle_playback.assert_called_once()
        sd._send_appcommand_to_spotify.assert_not_called()
        sd._send_input_media_key.assert_not_called()
        sd._remember_playback_state.assert_called_with(False, paused_by_game=True)

    def test_desktop_pause_reports_failure_when_no_command_delivered(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._clear_mixer_mute = MagicMock()
        sd._paused_by_game = False
        sd._playback_state_known = True
        sd._is_playing = True
        sd._desktop_audible = MagicMock(return_value=True)
        sd._uia_toggle_playback = MagicMock(return_value=False)
        sd._send_appcommand_to_spotify = MagicMock(return_value=False)
        sd._send_playback_command = MagicMock(return_value=False)
        sd._send_input_media_key = MagicMock(return_value=False)
        sd._remember_playback_state = MagicMock()
        sd.ensure_paused = SpotifyDesktopController.ensure_paused.__get__(
            sd, SpotifyDesktopController
        )

        self.assertFalse(sd.ensure_paused(paused_by_game=False))
        # Never record a pause that was not actually sent.
        sd._remember_playback_state.assert_not_called()

    def test_next_prev_track_delegates_to_media_methods(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd.media_next = MagicMock(return_value=True)
        sd.media_prev = MagicMock(return_value=True)
        sd.next_track = SpotifyDesktopController.next_track.__get__(sd, SpotifyDesktopController)
        sd.prev_track = SpotifyDesktopController.prev_track.__get__(sd, SpotifyDesktopController)

        self.assertTrue(sd.next_track())
        sd.media_next.assert_called_once()

        self.assertTrue(sd.prev_track())
        sd.media_prev.assert_called_once()

    def test_get_current_track_extracts_from_window_title(self):
        from core.spotify_desktop import SpotifyDesktopController
        sd = MagicMock(spec=SpotifyDesktopController)
        sd._local_status = MagicMock(return_value={})
        sd._log = MagicMock()
        sd._last_track_uri = "spotify:track:123"
        sd._last_uri = "spotify:playlist:abc"
        sd._last_query = "synthwave"
        sd._remember_playback_state = MagicMock()
        sd._is_playing = True
        sd._last_known_track_info = None
        sd.get_current_track = SpotifyDesktopController.get_current_track.__get__(sd, SpotifyDesktopController)

        with patch("core.spotify_desktop._find_spotify_window_titles", return_value=["The Weeknd - Blinding Lights"]):
            track = sd.get_current_track()
            self.assertIsNotNone(track)
            self.assertEqual(track["name"], "Blinding Lights")
            self.assertEqual(track["artist"], "The Weeknd")
            self.assertTrue(track["is_playing"])

        # When title flips to "Spotify" (paused)
        with patch("core.spotify_desktop._find_spotify_window_titles", return_value=["Spotify"]):
            track_paused = sd.get_current_track()
            self.assertIsNotNone(track_paused)
            self.assertEqual(track_paused["name"], "Blinding Lights")
            self.assertFalse(track_paused["is_playing"])


class TestWebBrowserOnlyControls(unittest.TestCase):
    def _make_web(self):
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        sw._clear_mixer_mute = MagicMock()
        sw._uses_desktop_player = MagicMock(return_value=False)
        sw._paused_by_game = False
        sw._page = MagicMock()   # simulate an open automation browser
        sw._context = MagicMock()
        sw._cdp_url = ""
        sw._run_on_page = MagicMock(return_value=True)
        sw._remember_playback_state = MagicMock()
        sw._desktop_helper = MagicMock()
        sw._send_global_media_key = MagicMock()
        sw._source_peaks = MagicMock(return_value=(0.0, 0.0))
        sw._note_audio_source = MagicMock()
        sw._loopback_audible = MagicMock(return_value=False)
        sw._log = MagicMock()
        sw._last_error = ""
        return sw

    def test_web_pause_with_closed_browser_does_not_launch(self):
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        sw._paused_by_game = False
        sw._uses_desktop_player = MagicMock(return_value=False)
        sw._source_peaks = MagicMock(return_value=(0.0, 0.0))
        sw._note_audio_source = MagicMock()
        sw._loopback_audible = MagicMock(return_value=False)
        sw._clear_mixer_mute = MagicMock()
        sw._remember_playback_state = MagicMock()
        sw._page = None
        sw._context = None
        sw._cdp_url = ""
        sw._run_on_page = MagicMock()
        sw.ensure_paused = SpotifyWebController.ensure_paused.__get__(
            sw, SpotifyWebController
        )

        self.assertTrue(sw.ensure_paused(paused_by_game=False))
        # No browser means no audio to stop. Launching one just to pause is
        # slow and can open an unwanted window.
        sw._run_on_page.assert_not_called()
        sw._remember_playback_state.assert_called_with(False, paused_by_game=False)

    def test_web_ensure_paused_is_browser_only(self):
        from core.spotify_web import SpotifyWebController
        sw = self._make_web()
        sw.ensure_paused = SpotifyWebController.ensure_paused.__get__(sw, SpotifyWebController)

        self.assertTrue(sw.ensure_paused(paused_by_game=False))

        sw._run_on_page.assert_called_once()
        sw._remember_playback_state.assert_called_with(False, paused_by_game=False)
        # No desktop tap / global media key: those caused the double toggle.
        sw._desktop_helper.assert_not_called()
        sw._send_global_media_key.assert_not_called()

    def test_web_ensure_playing_is_browser_only(self):
        from core.spotify_web import SpotifyWebController
        sw = self._make_web()
        sw.ensure_playing = SpotifyWebController.ensure_playing.__get__(sw, SpotifyWebController)

        self.assertTrue(sw.ensure_playing())

        sw._run_on_page.assert_called_once()
        sw._remember_playback_state.assert_called_with(True, paused_by_game=False)
        sw._desktop_helper.assert_not_called()
        sw._send_global_media_key.assert_not_called()

    def test_pause_player_idempotent_when_already_paused(self):
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        sw._player_is_playing = MagicMock(return_value=False)
        sw._click_player_control = MagicMock()
        sw._send_global_media_key = MagicMock()
        sw._pause_player = SpotifyWebController._pause_player.__get__(sw, SpotifyWebController)

        self.assertTrue(sw._pause_player(MagicMock()))
        sw._click_player_control.assert_not_called()
        sw._send_global_media_key.assert_not_called()

    def test_pause_player_clicks_page_once_and_verifies(self):
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        # First read: playing; after the click: paused.
        sw._player_is_playing = MagicMock(side_effect=[True, False])
        sw._click_player_control = MagicMock(return_value=True)
        sw._browser_audio_is_loud = MagicMock(return_value=False)
        sw._send_global_media_key = MagicMock()
        sw._pause_player = SpotifyWebController._pause_player.__get__(sw, SpotifyWebController)

        self.assertTrue(sw._pause_player(MagicMock()))
        sw._click_player_control.assert_called_once()
        sw._send_global_media_key.assert_not_called()

    def test_play_random_for_mood_attempts_exactly_one_playlist(self):
        from core import spotify_web as sw_mod
        from core.spotify_web import SpotifyWebController
        sw = MagicMock(spec=SpotifyWebController)
        sw.data_dir = "C:/tmp"
        sw.normalize_playlist_uri = lambda u: u
        sw._log = MagicMock()
        sw._last_error = ""
        sw._start_playback = MagicMock(return_value=None)
        sw.play_random_for_mood = SpotifyWebController.play_random_for_mood.__get__(
            sw, SpotifyWebController
        )

        pick = {
            "uri": "spotify:playlist:one",
            "name": "One",
            "query": "lofi",
            "pool": [
                {"uri": "spotify:playlist:one", "name": "One"},
                {"uri": "spotify:playlist:two", "name": "Two"},
                {"uri": "spotify:playlist:three", "name": "Three"},
            ],
        }
        with patch.object(sw_mod, "pick_random_playlist_uri", return_value=pick), \
             patch.object(sw_mod, "build_search_query", return_value="lofi"), \
             patch.object(sw_mod, "load_blocked_playlist_uris", return_value=[]), \
             patch.object(sw_mod, "playlist_uri_to_url", side_effect=lambda u: u):
            result = sw.play_random_for_mood(mood="chill", force_new=True)

        self.assertIsNone(result)
        # One attempt only. A failed/uncertain start must not silently open
        # another mix ("it starts another playlist").
        self.assertEqual(sw._start_playback.call_count, 1)
        self.assertIn(
            sw._start_playback.call_args[0][0],
            {
                "spotify:playlist:one",
                "spotify:playlist:two",
                "spotify:playlist:three",
            },
        )


class TestAudioMonitorRouting(unittest.TestCase):
    def test_register_music_player_pids_expands_children(self):
        from core import audio_monitor as am

        child = MagicMock()
        child.pid = 4321
        parent = MagicMock()
        parent.children.return_value = [child]
        with patch.object(am, "HAS_PSUTIL", True), \
             patch.object(am.psutil, "Process", return_value=parent), \
             patch.object(am, "_registered_music_pids", []), \
             patch.object(am, "close_spotify_loopback"):
            am.register_music_player_pids([1234])
            self.assertIn(1234, am._registered_music_pids)
            self.assertIn(4321, am._registered_music_pids)

    def test_registered_pids_are_unioned_with_desktop(self):
        from core import audio_monitor as am

        # In the simplified dual flow the browser is preferred, but the desktop
        # sidecar may be the audible source. Monitor both so the UI never reads
        # silence while music is playing.
        with patch.object(am, "_registered_music_pids", [777]), \
                patch.object(am, "_browser_audio_only", False), \
                patch.object(am, "_desktop_spotify_pids", return_value=[888]):
            self.assertEqual(am.get_all_spotify_pids(), [777, 888])


class TestAppNewRegressions(unittest.TestCase):
    def test_begin_playlist_switch_pause_updates_state_immediately(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._apply_user_pause_state = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._update_deck_status = MagicMock()
        app._log = MagicMock()
        app._is_playing = True

        GameBeatsApp._begin_playlist_switch_pause(app, "Blocked")

        app._apply_user_pause_state.assert_called_once_with(
            True, preserve_thinking=True
        )
        app._set_play_btn_icon.assert_called_once_with(False, force_btn=True)
        app._update_deck_status.assert_called_once()
        self.assertFalse(app._is_playing)
        self.assertTrue(app._playlist_switch_pause)
        self.assertFalse(app._playlist_switch_heard_silence)
        self.assertFalse(app._playlist_switch_pause_confirmed)
        self.assertGreater(app._track_change_anim_quiet_until, time.time())

    def test_transient_switch_pause_does_not_lock_the_thinking_overlay(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._user_toggle_ts = 0.0
        app._playlist_switch_pause = True
        app._playlist_audio_armed = True
        app._spotify_loud_streak = 4
        app._manual_paused = False
        app._user_paused_flag = False
        app._paused_by_game_flag = False
        app._playlist_end_pending = True
        app._music_missing_since = 12.0
        app._playlist_end_delay_seconds = MagicMock(return_value=4.0)
        app._mascot_notifier = None
        app._puppy_singing_overlay = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._stop_puppy_thinking = MagicMock()

        GameBeatsApp._apply_user_pause_state(
            app, True, preserve_thinking=True
        )

        self.assertFalse(app._manual_paused)
        self.assertFalse(app._user_paused_flag)
        self.assertFalse(app._paused_by_game_flag)
        self.assertTrue(app._playlist_switch_pause)
        self.assertFalse(app._playlist_audio_armed)
        self.assertEqual(app._spotify_loud_streak, 0)
        app._puppy_singing_overlay.set_animation_locked.assert_not_called()
        app._stop_puppy_thinking.assert_not_called()
        app._set_play_btn_icon.assert_called_once_with(False, force_btn=True)

    def test_transient_switch_pause_keeps_a_real_game_pause(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._user_toggle_ts = 0.0
        app._playlist_switch_pause = True
        app._playlist_audio_armed = True
        app._spotify_loud_streak = 0
        app._manual_paused = False
        app._user_paused_flag = False
        app._paused_by_game_flag = True
        app._playlist_end_pending = False
        app._music_missing_since = 0.0
        app._playlist_end_delay_seconds = MagicMock(return_value=4.0)
        app._mascot_notifier = None
        app._puppy_singing_overlay = MagicMock()
        app._set_play_btn_icon = MagicMock()

        GameBeatsApp._apply_user_pause_state(
            app, True, preserve_thinking=True
        )

        self.assertTrue(app._paused_by_game_flag)
        self.assertFalse(app._manual_paused)
        self.assertFalse(app._user_paused_flag)

    def test_adopt_switch_playback_resumes_icon_and_puppy_immediately(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._playlist_switch_pause = True
        app._playlist_switch_heard_silence = True
        app._playlist_switch_started_ts = time.time() - 5.0
        app._playlist_switch_audio_heard_ts = 0.0
        app._manual_paused = True
        app._user_paused_flag = True
        app._paused_by_game_flag = False
        app._spotify_started_by_us = False
        app._playback_started_ts = 0.0
        app._is_playing = False
        app._pause_stack = ["user"]
        app._puppy_action_state = "pause"
        app._puppy_action_hold = True
        app._puppy_action_reverse = False
        app._puppy_singing_overlay = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._set_puppy_singing_visible = MagicMock()
        app._log = MagicMock()

        result = GameBeatsApp._adopt_playlist_switch_playback(app)

        self.assertTrue(result)
        self.assertFalse(app._playlist_switch_pause)
        self.assertFalse(app._playlist_switch_heard_silence)
        self.assertFalse(app._playlist_switch_pause_confirmed)
        self.assertGreater(app._playlist_switch_audio_heard_ts, 0.0)
        self.assertFalse(app._manual_paused)
        self.assertFalse(app._user_paused_flag)
        self.assertTrue(app._spotify_started_by_us)
        self.assertTrue(app._is_playing)
        self.assertEqual(app._pause_stack, [])
        self.assertIsNone(app._puppy_action_state)
        app._puppy_singing_overlay.set_animation_locked.assert_called_once_with(False)
        app._puppy_singing_overlay.set_playback_state.assert_called_once_with(
            True, animate=False
        )
        app._set_play_btn_icon.assert_called_once_with(True, force_btn=True)
        app._set_puppy_singing_visible.assert_called_once_with(True)

    def test_adopt_switch_playback_ignores_a_real_pause(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._playlist_switch_pause = False
        app._is_playing = False
        app._set_play_btn_icon = MagicMock()
        app._set_puppy_singing_visible = MagicMock()

        self.assertFalse(GameBeatsApp._adopt_playlist_switch_playback(app))
        app._set_play_btn_icon.assert_not_called()
        app._set_puppy_singing_visible.assert_not_called()

    def test_pause_spotify_for_playlist_switch_sends_command(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app.spotify = MagicMock()
        app._send_spotify_pause_command = MagicMock(return_value=True)
        app.root = MagicMock()
        app._log = MagicMock()

        GameBeatsApp._pause_spotify_for_playlist_switch(app)

        app._send_spotify_pause_command.assert_called_once()
        app.root.after.assert_called_once()
        self.assertTrue(app._playlist_switch_pause_confirmed)

    def test_play_query_pauses_before_starting_next_playlist(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        order = []
        app._play_in_progress = False
        app._begin_playlist_switch_pause = MagicMock(
            side_effect=lambda reason: order.append("mark")
        )
        app._pause_spotify_for_playlist_switch = MagicMock(
            side_effect=lambda: order.append("pause")
        )
        app._skip_playlist_uris = MagicMock(return_value=set())
        app._current_playlist_uri = "spotify:playlist:old"
        app._blocked_playlist_uris = MagicMock(return_value=set())
        app._is_desktop_mode = MagicMock(return_value=False)
        app._is_web_mode = MagicMock(return_value=False)
        app._playlist_pick_count = MagicMock(return_value=5)
        app._end_behavior_key = MagicMock(return_value="next_pool")
        app._on_play_result = MagicMock()
        app.root = MagicMock()
        app._log = MagicMock()
        app.spotify = MagicMock()
        app.spotify.search_and_play = MagicMock(
            side_effect=lambda *a, **k: order.append("search") or {
                "uri": "spotify:playlist:new"
            }
        )

        class ImmediateThread:
            def __init__(self, target=None, daemon=None, **kwargs):
                self.target = target

            def start(self):
                self.target()

        with patch("ui.app.threading.Thread", ImmediateThread):
            GameBeatsApp._play_query_for_game(
                app,
                {"name": "Game", "mood": "chill", "tags": []},
                reason="Try another",
                pause_first=True,
            )

        self.assertEqual(order[:3], ["mark", "pause", "search"])
        app._begin_playlist_switch_pause.assert_called_once_with("Try another")
        app._pause_spotify_for_playlist_switch.assert_called_once()

    def test_play_query_queues_while_controller_is_busy(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._play_in_progress = True
        app._pending_play_request = None
        app._log = MagicMock()
        info = {"name": "Game", "mood": "chill", "tags": []}

        GameBeatsApp._play_query_for_game(
            app,
            info,
            force_new=True,
            exclude_uris={"spotify:playlist:old"},
            reason="Try another",
            pause_first=True,
        )

        pending = app._pending_play_request
        self.assertIsNotNone(pending)
        self.assertIs(pending["info"], info)
        self.assertTrue(pending["force_new"])
        self.assertEqual(pending["exclude_uris"], {"spotify:playlist:old"})
        self.assertEqual(pending["reason"], "Try another")
        self.assertTrue(pending["pause_first"])
        app._log.assert_called_once()

    def test_finish_play_query_starts_the_queued_request(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        info = {"name": "Game"}
        app._play_in_progress = True
        app._active_play_request_id = 7
        app.current_game = info
        app._play_query_for_game = MagicMock()
        app._pending_play_request = {
            "info": info,
            "force_new": False,
            "exclude_uris": {"spotify:playlist:old"},
            "reason": "Try another",
            "one_shot": False,
            "pause_first": True,
        }

        GameBeatsApp._finish_play_query(app, 7)

        self.assertFalse(app._play_in_progress)
        app._play_query_for_game.assert_called_once_with(
            info,
            force_new=False,
            exclude_uris={"spotify:playlist:old"},
            reason="Try another",
            one_shot=False,
            pause_first=True,
            _from_queue=True,
        )

    def test_stale_finish_does_not_clear_a_newer_request(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._play_in_progress = True
        app._active_play_request_id = 9
        app.current_game = {"name": "Game"}
        app._play_query_for_game = MagicMock()
        app._pending_play_request = {"info": app.current_game}

        GameBeatsApp._finish_play_query(app, 8)

        self.assertTrue(app._play_in_progress)
        app._play_query_for_game.assert_not_called()

    def test_queued_request_is_discarded_when_game_changes(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._play_in_progress = False
        app._closing = False
        app.current_game = {"name": "New Game"}
        app._play_query_for_game = MagicMock()
        app._pending_play_request = {"info": {"name": "Old Game"}}
        app._log = MagicMock()

        GameBeatsApp._process_pending_play_request(app)

        self.assertIsNone(app._pending_play_request)
        app._play_query_for_game.assert_not_called()
        app._log.assert_called_once()

    def test_on_play_result_keeps_busy_until_ui_callback_runs(self):
        from ui.app import GameBeatsApp

        class DeferredRoot:
            def __init__(self):
                self.jobs = []

            def after(self, delay, func=None, *args):
                if delay == 0 and func is not None:
                    self.jobs.append((func, args))
                return "job"

        app = GameBeatsApp.__new__(GameBeatsApp)
        app.root = DeferredRoot()
        app._play_in_progress = True
        app._active_play_request_id = 5
        app._play_request_seq = 5
        app._pending_play_request = None
        app._playlist_switch_started_ts = 0.0
        app._playlist_switch_audio_heard_ts = 0.0
        app._playlist_switch_heard_silence = False
        app._playlist_switch_pause_confirmed = True
        app._playlist_end_pending = True
        app._manual_paused = True
        app._user_paused_flag = True
        app._is_playing = True
        app._spotify_started_by_us = True
        app._playback_started_ts = time.time()
        app.current_game = None
        app._audio_monitor_running = False
        app.spotify = MagicMock()
        app.spotify._last_play_method = "web"
        app._log = MagicMock()
        app._remember_current_playlist = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._play_puppy_change_animation = MagicMock()
        app._schedule_fast_track_refresh = MagicMock()
        app._pause_started_playlist_if_game_loud = MagicMock()

        GameBeatsApp._on_play_result(
            app,
            {"uri": "spotify:playlist:new", "name": "New", "query": "q"},
            "chill",
            "q",
            request_id=5,
        )

        self.assertTrue(
            app._play_in_progress,
            "a long-press must queue until the result UI callback has run",
        )
        self.assertFalse(app._remember_current_playlist.called)
        for func, args in app.root.jobs:
            func(*args)

        self.assertFalse(app._play_in_progress)
        app._remember_current_playlist.assert_called_once()
        app._play_puppy_change_animation.assert_called_once_with(force=True)

    def test_on_play_result_finishes_playlist_thinking_with_one_swap(self):
        from ui.app import GameBeatsApp

        class ImmediateRoot:
            def after(self, delay, func=None, *args):
                if delay == 0 and func is not None:
                    func(*args)
                return "job"

        app = GameBeatsApp.__new__(GameBeatsApp)
        app.root = ImmediateRoot()
        app._play_in_progress = True
        app._active_play_request_id = 8
        app._play_request_seq = 8
        app._pending_play_request = None
        app._playlist_switch_started_ts = time.time() - 2.0
        app._playlist_switch_audio_heard_ts = 0.0
        app._playlist_switch_heard_silence = False
        app._playlist_switch_pause_confirmed = True
        app._playlist_end_pending = True
        app._manual_paused = False
        app._user_paused_flag = False
        app._is_playing = True
        app._spotify_started_by_us = True
        app._playback_started_ts = time.time()
        app.current_game = None
        app._audio_monitor_running = False
        app.spotify = MagicMock()
        app.spotify._last_play_method = "web"
        app._log = MagicMock()
        app._remember_current_playlist = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._finish_puppy_thinking = MagicMock(return_value=True)
        app._play_puppy_change_animation = MagicMock()
        app._schedule_fast_track_refresh = MagicMock()
        app._pause_started_playlist_if_game_loud = MagicMock()
        app._finish_play_query = MagicMock()

        GameBeatsApp._on_play_result(
            app,
            {"uri": "spotify:playlist:new", "name": "New", "query": "q"},
            "chill",
            "q",
            request_id=8,
        )

        app._finish_puppy_thinking.assert_called_once_with(play_change=True)
        app._play_puppy_change_animation.assert_not_called()

    def test_on_play_result_ignores_a_stale_request(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._play_in_progress = True
        app._active_play_request_id = 12
        app._pending_play_request = None
        app._log = MagicMock()
        app._remember_current_playlist = MagicMock()

        GameBeatsApp._on_play_result(
            app,
            {"uri": "spotify:playlist:old", "name": "Old", "query": "q"},
            "chill",
            "q",
            request_id=11,
        )

        self.assertTrue(app._play_in_progress)
        app._remember_current_playlist.assert_not_called()
        app._log.assert_called_once()

    def test_on_play_result_skips_change_when_a_request_is_queued(self):
        from ui.app import GameBeatsApp

        class ImmediateRoot:
            def after(self, delay, func=None, *args):
                if delay == 0 and func is not None:
                    func(*args)
                return "job"

        app = GameBeatsApp.__new__(GameBeatsApp)
        app.root = ImmediateRoot()
        app._play_in_progress = True
        app._active_play_request_id = 3
        app._pending_play_request = {"info": {"name": "Game"}}
        app._playlist_switch_started_ts = 0.0
        app._playlist_switch_audio_heard_ts = 0.0
        app._playlist_switch_heard_silence = False
        app._playlist_switch_pause_confirmed = False
        app._playlist_end_pending = False
        app._manual_paused = False
        app._user_paused_flag = False
        app._is_playing = True
        app._spotify_started_by_us = True
        app._playback_started_ts = time.time()
        app.current_game = None
        app._audio_monitor_running = False
        app.spotify = MagicMock()
        app.spotify._last_play_method = "web"
        app._log = MagicMock()
        app._remember_current_playlist = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._play_puppy_change_animation = MagicMock()
        app._finish_puppy_thinking = MagicMock(return_value=True)
        app._schedule_fast_track_refresh = MagicMock()
        app._pause_started_playlist_if_game_loud = MagicMock()
        app._finish_play_query = MagicMock()

        GameBeatsApp._on_play_result(
            app,
            {"uri": "spotify:playlist:new", "name": "New", "query": "q"},
            "chill",
            "q",
            request_id=3,
        )

        # The queued request owns the thinking loop now; this result must not
        # complete it with a stale headset-swap clip.
        app._finish_puppy_thinking.assert_not_called()
        app._play_puppy_change_animation.assert_not_called()
        app._finish_play_query.assert_called_once_with(3)

    def test_custom_playlist_claims_audio_before_controller_returns(self):
        from ui.app import GameBeatsApp

        class ImmediateRoot:
            def after(self, delay, func=None, *args):
                if delay == 0 and func is not None:
                    func(*args)
                return "job"

        app = GameBeatsApp.__new__(GameBeatsApp)
        observed = {}
        info = {"name": "Msedge"}

        class FakeSpotify:
            _last_error = ""
            _last_play_method = ""

            def ensure_active_device(self):
                return True

            def play_playlist(self, uri):
                observed["started_by_us"] = app._spotify_started_by_us
                observed["started_ts"] = app._playback_started_ts
                observed["uri"] = uri
                return False

        app.root = ImmediateRoot()
        app.spotify = FakeSpotify()
        app._is_web_mode = MagicMock(return_value=True)
        app._play_in_progress = False
        app._play_request_seq = 0
        app._active_play_request_id = 0
        app._pending_play_request = None
        app._is_playing = False
        app._spotify_started_by_us = False
        app._playback_started_ts = 0.0
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._log = MagicMock()

        GameBeatsApp._play_custom_playlist_for_game(
            app, info, "spotify:playlist:custom"
        )

        self.assertTrue(observed["started_by_us"])
        self.assertGreater(observed["started_ts"], 0.0)
        self.assertEqual(observed["uri"], "spotify:playlist:custom")
        self.assertFalse(app._play_in_progress)
        self.assertFalse(app._spotify_started_by_us)

    def test_update_np_suppresses_title_change_echo_after_switch(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._last_np_key = ("old", "Old", "Artist")
        app._last_track_info = {}
        app._last_track_info_ts = 0.0
        app._track_change_anim_quiet_until = time.time() + 5.0
        app._pending_play_request = None
        app._playlist_switch_pause = False
        app._puppy_reaction_until = 0.0
        app._play_puppy_change_animation = MagicMock()
        app._fresh_playback_grace = MagicMock(return_value=False)

        GameBeatsApp._update_np(
            app, {"uri": "new", "name": "New", "artist": "Artist"}
        )

        app._play_puppy_change_animation.assert_not_called()
        self.assertEqual(app._puppy_reaction_until, 0.0)
        self.assertEqual(app._last_np_key, ("new", "New", "Artist"))

        app._track_change_anim_quiet_until = 0.0
        GameBeatsApp._update_np(
            app, {"uri": "newer", "name": "Newer", "artist": "Artist"}
        )

        # Ordinary track changes get the small head-turn reaction, never the
        # headset-swap clip.  Thinking/skip animations are started by the
        # explicit next/previous action instead.
        app._play_puppy_change_animation.assert_not_called()
        self.assertGreater(app._puppy_reaction_until, 0.0)

    def test_update_np_finishes_skip_thinking_when_new_track_arrives(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._last_np_key = ("old", "Old", "Artist")
        app._last_track_info = {}
        app._last_track_info_ts = 0.0
        app._track_change_anim_quiet_until = 0.0
        app._pending_play_request = None
        app._playlist_switch_pause = False
        app._puppy_reaction_until = 0.0
        app._puppy_thinking_active = MagicMock(return_value=True)
        app._finish_puppy_thinking = MagicMock(return_value=True)
        app._play_puppy_change_animation = MagicMock()
        app._fresh_playback_grace = MagicMock(return_value=False)

        GameBeatsApp._update_np(
            app, {"uri": "new", "name": "New", "artist": "Artist"}
        )

        app._finish_puppy_thinking.assert_called_once_with(play_change=True)
        app._play_puppy_change_animation.assert_not_called()

    def test_update_np_finishes_skip_thinking_during_quiet_cooldown(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._last_np_key = ("old", "Old", "Artist")
        app._last_track_info = {}
        app._last_track_info_ts = 0.0
        app._track_change_anim_quiet_until = time.time() + 5.0
        app._pending_play_request = None
        app._playlist_switch_pause = False
        app._puppy_thinking_reason = "track"
        app._puppy_reaction_until = 0.0
        app._puppy_thinking_active = MagicMock(return_value=True)
        app._finish_puppy_thinking = MagicMock(return_value=True)
        app._play_puppy_change_animation = MagicMock()
        app._fresh_playback_grace = MagicMock(return_value=False)

        GameBeatsApp._update_np(
            app, {"uri": "new", "name": "New", "artist": "Artist"}
        )

        app._finish_puppy_thinking.assert_called_once_with(play_change=True)

    def test_update_np_keeps_playlist_loading_thinking(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._last_np_key = ("old", "Old", "Artist")
        app._last_track_info = {}
        app._last_track_info_ts = 0.0
        app._track_change_anim_quiet_until = 0.0
        app._pending_play_request = None
        app._playlist_switch_pause = True
        app._puppy_thinking_reason = "playlist"
        app._puppy_reaction_until = 0.0
        app._puppy_thinking_active = MagicMock(return_value=True)
        app._finish_puppy_thinking = MagicMock(return_value=True)
        app._play_puppy_change_animation = MagicMock()
        app._fresh_playback_grace = MagicMock(return_value=False)

        GameBeatsApp._update_np(
            app, {"uri": "new", "name": "New", "artist": "Artist"}
        )

        app._finish_puppy_thinking.assert_not_called()

    def test_fresh_playback_grace_holds_until_audio_or_timeout(self):
        from ui.app import FRESH_PLAYBACK_GRACE_SEC, GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._spotify_started_by_us = True
        app._playlist_audio_armed = False
        app._playback_started_ts = time.time()

        self.assertTrue(GameBeatsApp._fresh_playback_grace(app))

        app._playlist_audio_armed = True
        self.assertFalse(GameBeatsApp._fresh_playback_grace(app))

        app._playlist_audio_armed = False
        app._playback_started_ts = time.time() - FRESH_PLAYBACK_GRACE_SEC - 1
        self.assertFalse(GameBeatsApp._fresh_playback_grace(app))

    def test_fast_track_refresh_uses_background_fetch(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._closing = False
        app._track_refresh_jobs = []
        app.root = MagicMock()

        GameBeatsApp._schedule_fast_track_refresh(app)

        self.assertEqual(app.root.after.call_count, 5)
        self.assertEqual(
            [call.args[0] for call in app.root.after.call_args_list],
            [250, 800, 1600, 3000, 5500],
        )
        for call in app.root.after.call_args_list:
            self.assertEqual(call.args[1], app._fetch_track_async)

    def test_mark_music_missing_keeps_fresh_playback_playing(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app._user_toggle_ts = 0.0
        app._intentional_pause_active = MagicMock(return_value=False)
        app._player_is_playing_cached = MagicMock(return_value=False)
        app._playlist_end_prompt_allowed = MagicMock(return_value=True)
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._spotify_started_by_us = True
        app._playlist_audio_armed = False
        app._playback_started_ts = time.time()
        app._is_playing = True
        app._music_missing_since = 0.0
        app._playlist_end_pending = False

        GameBeatsApp._mark_music_missing(app)

        self.assertTrue(app._is_playing)
        self.assertEqual(app._music_missing_since, 0.0)
        self.assertFalse(app._playlist_end_pending)

    def test_on_play_result_clears_pause_before_starting_mascot(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        order = []

        class ImmediateRoot:
            def after(self, delay, func=None, *args):
                if delay == 0 and func is not None:
                    func(*args)
                return "job"

        app.root = ImmediateRoot()
        app._play_in_progress = True
        app._manual_paused = True
        app._user_paused_flag = True
        app._pause_stack = ["user"]
        app._playlist_end_pending = True
        app._is_playing = False
        app._spotify_started_by_us = False
        app._playback_started_ts = 0.0
        app._current_playlist_uri = "spotify:playlist:old"
        app.current_game = None
        app._audio_monitor_running = False
        app.spotify = MagicMock()
        app.spotify._last_play_method = "web"
        app._log = MagicMock()
        app._pause_started_playlist_if_game_loud = MagicMock()

        def remember(*args, **kwargs):
            order.append("remember")
            app._manual_paused = False
            app._user_paused_flag = False
            app._pause_stack = []

        def set_play(playing, force_btn=False):
            order.append((
                "set_play",
                app._manual_paused,
                app._user_paused_flag,
                list(app._pause_stack),
            ))
            app._is_playing = bool(playing)

        app._remember_current_playlist = MagicMock(side_effect=remember)
        app._set_play_btn_icon = MagicMock(side_effect=set_play)
        app._schedule_fast_track_refresh = MagicMock(
            side_effect=lambda: order.append("refresh")
        )

        GameBeatsApp._on_play_result(
            app,
            {
                "uri": "spotify:playlist:new",
                "name": "New",
                "query": "q",
            },
            "chill",
            "q",
        )

        self.assertEqual(order[0], "remember")
        self.assertEqual(order[1][0], "set_play")
        self.assertFalse(order[1][1])
        self.assertFalse(order[1][2])
        self.assertEqual(order[1][3], [])
        self.assertEqual(order[2], "refresh")
        self.assertGreater(app._playback_started_ts, 0.0)
        self.assertTrue(app._spotify_started_by_us)

    def test_on_play_result_skips_duplicate_change_when_switch_audio_was_heard(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)

        class ImmediateRoot:
            def after(self, delay, func=None, *args):
                if delay == 0 and func is not None:
                    func(*args)
                return "job"

        app.root = ImmediateRoot()
        app._play_in_progress = True
        app._manual_paused = False
        app._user_paused_flag = False
        app._playlist_switch_pause = True
        app._playlist_switch_started_ts = time.time() - 6.0
        app._playlist_switch_audio_heard_ts = time.time() - 3.0
        app._pause_stack = []
        app._playlist_end_pending = True
        app._is_playing = True
        app._spotify_started_by_us = True
        app._playback_started_ts = time.time()
        app._current_playlist_uri = "spotify:playlist:new"
        app.current_game = None
        app._audio_monitor_running = False
        app.spotify = MagicMock()
        app.spotify._last_play_method = "web"
        app._log = MagicMock()
        app._pause_started_playlist_if_game_loud = MagicMock()
        app._remember_current_playlist = MagicMock()
        app._set_play_btn_icon = MagicMock()
        app._play_puppy_change_animation = MagicMock()
        app._schedule_fast_track_refresh = MagicMock()

        GameBeatsApp._on_play_result(
            app,
            {"uri": "spotify:playlist:new", "name": "New", "query": "q"},
            "chill",
            "q",
        )

        # The monitor already started the bob when audio became audible, so
        # the late controller result must not interrupt it with another
        # headset-swap clip.
        app._play_puppy_change_animation.assert_not_called()
        self.assertEqual(app._playlist_switch_started_ts, 0.0)
        self.assertEqual(app._playlist_switch_audio_heard_ts, 0.0)

    def test_on_play_result_failure_does_not_autostart(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._on_play_result = GameBeatsApp._on_play_result.__get__(app, GameBeatsApp)
        app.spotify = MagicMock()
        app.spotify._last_uri = "spotify:playlist:bad"
        app.spotify._last_error = "Playback did not start"
        app._tried_playlist_uris = []
        app._playlist_end_pending = True
        app._log = MagicMock()

        app._on_play_result(None, "chill", "lofi")

        self.assertFalse(app._playlist_end_pending)
        self.assertIn("spotify:playlist:bad", app._tried_playlist_uris)
        app._play_query_for_game.assert_not_called()

    def test_update_np_never_clears_manual_pause_even_when_playing(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._update_np = GameBeatsApp._update_np.__get__(app, GameBeatsApp)
        app._intentional_pause_active = MagicMock(return_value=False)
        app._now_playing_playlist_title = MagicMock(return_value="My Playlist")
        app.track_lbl = MagicMock()
        app.artist_lbl = MagicMock()
        app._current_playlist_uri = "spotify:playlist:123"
        app._play_in_progress = False
        app._user_toggle_ts = time.time() - 30.0
        app._audio_monitor_running = True
        app._spotify_sound_detected_recently = MagicMock(return_value=True)
        app._manual_paused = True
        app._user_paused_flag = True
        app._set_play_btn_icon = MagicMock()
        app._mark_music_missing = MagicMock()

        app._update_np({"name": "Test", "is_playing": True})

        self.assertTrue(app._manual_paused)
        self.assertTrue(app._user_paused_flag)

    def test_notifier_suppressed_until_playlist_audio_starts(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._show_mascot_prompt = GameBeatsApp._show_mascot_prompt.__get__(
            app, GameBeatsApp
        )
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._hide_mascot_notifier_for_spotify_audio = MagicMock()
        app._set_puppy_singing_visible = MagicMock()
        app._control_overlay = None
        app._intentional_pause_active = MagicMock(return_value=False)
        app._player_is_playing_cached = MagicMock(return_value=False)
        app._audio_monitor_running = True
        app._playlist_audio_armed = False
        app._playlist_end_pending = True
        app._music_missing_since = 123.0
        app._log = MagicMock()

        with patch("ui.app.MascotNotifier") as notifier:
            app._show_mascot_prompt("Playlist ended — pick next?")

        notifier.assert_not_called()
        self.assertFalse(app._playlist_end_pending)
        self.assertEqual(app._music_missing_since, 0.0)

    def test_player_alive_cache_only_used_for_web(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._player_is_playing_cached = GameBeatsApp._player_is_playing_cached.__get__(
            app, GameBeatsApp
        )
        app._last_track_info = {"is_playing": True}
        app._last_track_info_ts = time.time()

        app._is_web_mode = MagicMock(return_value=False)
        self.assertFalse(app._player_is_playing_cached())

        app._is_web_mode = MagicMock(return_value=True)
        self.assertTrue(app._player_is_playing_cached())

        # A stale poll must not suppress a real end-of-playlist prompt.
        app._last_track_info_ts = time.time() - 30.0
        self.assertFalse(app._player_is_playing_cached())


class TestPlaybackUiResponsiveness(unittest.TestCase):
    def _make_app(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._set_play_btn_icon = GameBeatsApp._set_play_btn_icon.__get__(
            app, GameBeatsApp
        )
        app._set_puppy_singing_visible = (
            GameBeatsApp._set_puppy_singing_visible.__get__(app, GameBeatsApp)
        )
        app._hide_puppy_after_quiet = (
            GameBeatsApp._hide_puppy_after_quiet.__get__(app, GameBeatsApp)
        )
        app._mascot_notifier = None
        app._control_overlay = None
        app._puppy_singing_overlay = MagicMock()
        app._puppy_hide_job = None
        app._puppy_last_loud_ts = 0.0
        app.play_btn = MagicMock()
        app._update_deck_status = MagicMock()
        app._schedule_room_redraw = MagicMock()
        app._pulse_active = True
        app._pulse_job = MagicMock()
        app._puppy_audio_active = False
        app._spotify_started_by_us = True
        app.root = MagicMock()
        app._intentional_pause_active = MagicMock(return_value=False)
        return app

    def test_audio_tick_does_not_change_visible_icon(self):
        app = self._make_app()
        app._is_playing = True

        # The monitor calls this twice per second with the same state.
        app._set_play_btn_icon(True)

        app._schedule_room_redraw.assert_not_called()
        # Audio-meter ticks must never overwrite the explicit play/pause icon.
        app.play_btn.update_text.assert_not_called()

    def test_play_start_waits_for_audio_before_showing_the_puppy(self):
        app = self._make_app()
        app._is_playing = False
        app._audio_monitor_running = True
        app._spotify_audio_active = False

        app._set_play_btn_icon(True)

        app._puppy_singing_overlay.show.assert_not_called()
        self.assertFalse(app._puppy_audio_active)

    def test_play_start_shows_the_puppy_once_audio_is_loud(self):
        app = self._make_app()
        app._is_playing = False
        app._audio_monitor_running = True
        app._spotify_audio_active = True

        app._set_play_btn_icon(True)

        app._puppy_singing_overlay.show.assert_called_once()
        self.assertTrue(app._puppy_audio_active)

    def test_play_start_without_a_meter_still_shows_the_puppy(self):
        app = self._make_app()
        app._is_playing = False
        app._audio_monitor_running = False
        app._spotify_audio_active = False

        app._set_play_btn_icon(True)

        app._puppy_singing_overlay.show.assert_called_once()

    def test_play_command_without_a_meter_waits_for_gamebeats_playback(self):
        app = self._make_app()
        app._spotify_started_by_us = False
        app._is_playing = False
        app._audio_monitor_running = False
        app._spotify_audio_active = False

        app._set_play_btn_icon(True)

        app._puppy_singing_overlay.show.assert_not_called()

    def test_first_launch_does_not_show_puppy_before_gamebeats_playback(self):
        app = self._make_app()
        app._spotify_started_by_us = False
        app._is_playing = False
        app._audio_monitor_running = True
        app._puppy_singing_overlay.is_visible.return_value = False

        app._set_puppy_singing_visible(True)

        app._puppy_singing_overlay.show.assert_not_called()
        self.assertFalse(app._puppy_audio_active)

    def test_pause_clears_confirmed_audio_before_the_next_resume(self):
        app = self._make_app()
        app._is_playing = True
        app._spotify_audio_active = True

        app._set_play_btn_icon(False)

        self.assertFalse(app._spotify_audio_active)

    def test_forced_action_updates_visible_icon(self):
        from ui import theme as T
        app = self._make_app()
        app._is_playing = True

        app._set_play_btn_icon(False, force_btn=True)

        app.play_btn.update_text.assert_called_with(T.media_icon("play"))

    def test_real_play_state_change_redraws_once(self):
        app = self._make_app()
        app._is_playing = True

        app._set_play_btn_icon(False)

        app._schedule_room_redraw.assert_called_once_with(0)

    def test_desktop_puppy_overlay_is_translucent(self):
        from ui.mascot_notifier import PUPPY_OVERLAY_ALPHA

        self.assertLessEqual(PUPPY_OVERLAY_ALPHA, 0.85)
        self.assertGreater(PUPPY_OVERLAY_ALPHA, 0.5)

    def test_desktop_puppy_cadence_is_not_a_twitch(self):
        from ui.mascot_notifier import PUPPY_ANIMATION_INTERVAL

        # Small local changes can run at 10 fps; a full pose swap cannot.
        self.assertGreaterEqual(PUPPY_ANIMATION_INTERVAL, 80)
        self.assertLessEqual(PUPPY_ANIMATION_INTERVAL, 140)

    def test_desktop_puppy_does_not_restack_on_every_audio_tick(self):
        from ui.mascot_notifier import (
            PUPPY_TOPMOST_REASSERT_SEC,
            PuppySingingOverlay,
        )

        overlay = PuppySingingOverlay.__new__(PuppySingingOverlay)
        overlay._win = MagicMock()
        overlay._visible = True
        overlay._last_raise = 100.0
        overlay._raise_safe = MagicMock()

        with patch("ui.mascot_notifier.time.monotonic", return_value=100.4):
            overlay.show()
        overlay._raise_safe.assert_not_called()

        with patch(
            "ui.mascot_notifier.time.monotonic",
            return_value=100.0 + PUPPY_TOPMOST_REASSERT_SEC + 0.1,
        ):
            overlay.show()
        overlay._raise_safe.assert_called_once()

    def test_desktop_puppy_animation_uses_a_steady_deadline(self):
        from ui.mascot_notifier import (
            PUPPY_ANIMATION_INTERVAL,
            PuppySingingOverlay,
        )

        overlay = PuppySingingOverlay.__new__(PuppySingingOverlay)
        overlay._win = MagicMock()
        overlay._label = MagicMock()
        overlay._photos = ["a", "b", "c"]
        overlay._idx = 0
        overlay._after = None
        overlay._anim_next = None
        overlay._visible = True

        interval = PUPPY_ANIMATION_INTERVAL / 1000.0
        with patch("ui.mascot_notifier.time.monotonic", return_value=100.0):
            overlay._animate()
        # First call only arms the deadline; no frame change yet.
        overlay._label.configure.assert_not_called()
        self.assertAlmostEqual(overlay._anim_next, 100.0 + interval)
        self.assertEqual(
            overlay._win.after.call_args.args[0], PUPPY_ANIMATION_INTERVAL
        )

        # A tick 10 ms late advances exactly one beat and shortens the wait.
        with patch(
            "ui.mascot_notifier.time.monotonic",
            return_value=100.0 + interval + 0.01,
        ):
            overlay._animate()
        self.assertEqual(overlay._idx, 1)
        self.assertEqual(overlay._label.configure.call_count, 1)
        self.assertEqual(
            overlay._win.after.call_args.args[0],
            PUPPY_ANIMATION_INTERVAL - 10,
        )

    def test_desktop_puppy_animation_drops_beats_after_a_long_stall(self):
        from ui.mascot_notifier import (
            PUPPY_ANIMATION_INTERVAL,
            PuppySingingOverlay,
        )

        overlay = PuppySingingOverlay.__new__(PuppySingingOverlay)
        overlay._win = MagicMock()
        overlay._label = MagicMock()
        overlay._photos = ["a", "b", "c"]
        overlay._idx = 1
        overlay._after = None
        overlay._anim_next = 100.0
        overlay._visible = True

        interval = PUPPY_ANIMATION_INTERVAL / 1000.0
        with patch("ui.mascot_notifier.time.monotonic", return_value=112.0):
            overlay._animate()

        # Never burst through 120 skipped beats: resume cleanly instead.
        self.assertEqual(overlay._idx, 1)
        overlay._label.configure.assert_not_called()
        self.assertAlmostEqual(overlay._anim_next, 112.0 + interval)

    def test_singing_puppy_shows_without_a_detected_game(self):
        app = self._make_app()
        app.current_game = None

        app._set_puppy_singing_visible(True)

        app._puppy_singing_overlay.show.assert_called_once()
        self.assertTrue(app._puppy_audio_active)
        # The in-room mascot is driven by the master clock, so a meter tick
        # must not trigger a full room rebuild.
        app._schedule_room_redraw.assert_not_called()

    def test_singing_puppy_hides_on_intentional_pause(self):
        app = self._make_app()
        app._intentional_pause_active = MagicMock(return_value=True)

        app._set_puppy_singing_visible(True)

        app._puppy_singing_overlay.show.assert_not_called()
        app._puppy_singing_overlay.hide.assert_called_once_with(immediate=True)
        self.assertFalse(app._puppy_audio_active)

    def test_singing_puppy_survives_a_short_audio_dip(self):
        app = self._make_app()
        app._puppy_singing_overlay.is_visible.return_value = True

        app._set_puppy_singing_visible(True)
        app._set_puppy_singing_visible(False)

        # A ~0.5s meter dip schedules a delayed hide instead of blinking.
        app._puppy_singing_overlay.show.assert_called_once()
        app._puppy_singing_overlay.hide.assert_not_called()
        app.root.after.assert_called()
        self.assertFalse(app._puppy_audio_active)

    def test_singing_puppy_hides_after_a_long_quiet_run(self):
        app = self._make_app()
        app._puppy_singing_overlay.is_visible.return_value = True
        app._puppy_last_loud_ts = 0.0

        app._hide_puppy_after_quiet()

        app._puppy_singing_overlay.hide.assert_called_once_with()

    def test_playlist_switch_keeps_thinking_overlay_visible_without_audio(self):
        app = self._make_app()
        app._playlist_switch_pause = True
        app._puppy_thinking_active = MagicMock(return_value=True)
        app._paused_by_game_flag = False

        app._set_puppy_singing_visible(False)

        app._puppy_singing_overlay.set_animation_locked.assert_called_with(False)
        app._puppy_singing_overlay.play_thinking_animation.assert_called_once_with()
        app._puppy_singing_overlay.show.assert_called_once()
        app._puppy_singing_overlay.hide.assert_not_called()

    def test_playlist_switch_thinking_is_not_hidden_after_quiet(self):
        app = self._make_app()
        app._playlist_switch_pause = True
        app._puppy_thinking_active = MagicMock(return_value=True)

        app._hide_puppy_after_quiet()

        app._puppy_singing_overlay.hide.assert_not_called()


class TestOverlayPlacement(unittest.TestCase):
    def _overlay(self, *, saved=None, custom=None, dragged=False):
        from ui.mascot_notifier import PuppySingingOverlay

        overlay = PuppySingingOverlay.__new__(PuppySingingOverlay)
        win = MagicMock()
        win.winfo_vrootx.return_value = 0
        win.winfo_vrooty.return_value = 0
        win.winfo_vrootwidth.return_value = 1463
        win.winfo_vrootheight.return_value = 914
        win.winfo_reqwidth.return_value = 263
        win.winfo_reqheight.return_value = 205
        overlay._win = win
        overlay._saved_pos = saved
        overlay._custom_pos = custom
        overlay._dragged = dragged
        overlay._anchor_getter = None
        overlay._corner = "bottom-right"
        return overlay

    def test_stale_saved_position_is_clamped_into_the_current_desktop(self):
        overlay = self._overlay(saved=(2353, 1319))

        overlay._place()

        overlay._win.geometry.assert_called_once_with("+1200+709")
        self.assertEqual(overlay._saved_pos, (1200, 709))

    def test_dragged_position_cannot_be_restored_offscreen(self):
        overlay = self._overlay(custom=(-40, -30), dragged=True)

        overlay._place()

        overlay._win.geometry.assert_called_once_with("+0+0")
        self.assertEqual(overlay._custom_pos, (0, 0))


class TestAudioMonitorRegression(unittest.TestCase):
    def _make_app(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._auto_pause_allowed = GameBeatsApp._auto_pause_allowed.__get__(
            app, GameBeatsApp
        )
        app.spotify = MagicMock()
        app.auto_mode = MagicMock()
        app.auto_mode.get.return_value = True
        app._seamless_music_enabled = MagicMock(return_value=False)
        app._manual_paused = False
        app._user_paused_flag = False
        app._is_playing = True
        app._spotify_audio_active = False
        return app

    def test_auto_pause_works_without_app_started_playlist(self):
        app = self._make_app()
        # The playlist may have been playing before GameBeats attached.
        app._spotify_started_by_us = False

        self.assertTrue(app._auto_pause_allowed(spotify_loud=True))

    def test_auto_pause_requires_active_music(self):
        app = self._make_app()
        app._is_playing = False
        app._spotify_audio_active = False

        self.assertFalse(app._auto_pause_allowed(spotify_loud=False))

    def test_auto_pause_respects_keep_music_and_manual_pause(self):
        app = self._make_app()
        app._seamless_music_enabled.return_value = True
        self.assertFalse(app._auto_pause_allowed(spotify_loud=True))

        app._seamless_music_enabled.return_value = False
        app._manual_paused = True
        self.assertFalse(app._auto_pause_allowed(spotify_loud=True))

    def test_game_found_starts_audio_monitor_even_if_music_exists(self):
        from ui.app import GameBeatsApp
        app = MagicMock(spec=GameBeatsApp)
        app._on_game_found = GameBeatsApp._on_game_found.__get__(app, GameBeatsApp)
        app.current_game = None
        app._game_pid = None
        app._ensure_audio_monitor = MagicMock()
        app._autoplay_for_game = MagicMock()
        app.root = MagicMock()
        app.root.after = lambda delay, cb=None, *a, **kw: cb() if cb else None
        app.game_banner = MagicMock()
        app.mood_lbl = MagicMock()
        app._set_status = MagicMock()
        app._log = MagicMock()
        app._set_game_icon = MagicMock()
        app._update_deck_status = MagicMock()
        app._redraw_room = MagicMock()

        info = {"pid": 123, "proc": "msedge.exe", "name": "MSEDGE", "mood": "chill"}
        app._on_game_found(info)

        app._ensure_audio_monitor.assert_called_once_with(info)
        app._autoplay_for_game.assert_called_once_with(info)


class TestOverlayToggle(unittest.TestCase):
    def test_overlay_toggle_asks_app_for_state(self):
        from ui.runtime_overlay import RuntimeOverlay
        overlay = MagicMock(spec=RuntimeOverlay)
        overlay._pause = MagicMock()
        overlay._play = MagicMock()
        overlay._query_playing = MagicMock(return_value=True)
        overlay._toggle_play_pause = RuntimeOverlay._toggle_play_pause.__get__(
            overlay, RuntimeOverlay
        )

        overlay._toggle_play_pause()
        overlay._pause.assert_called_once()
        overlay._play.assert_not_called()

        overlay._query_playing = MagicMock(return_value=False)
        overlay._toggle_play_pause()
        overlay._play.assert_called_once()


class TestOtherAudioDetection(unittest.TestCase):
    def test_other_audio_excludes_spotify_and_gamebeats(self):
        from core import audio_monitor as am

        class FakeProc:
            def __init__(self, pid, name):
                self.pid = pid
                self._name = name

            def name(self):
                return self._name

        class FakeMeter:
            def __init__(self, peak):
                self.peak = peak

            def GetPeakValue(self):
                return self.peak

        class FakeSession:
            def __init__(self, proc, peak):
                self.Process = proc
                self._ctl = MagicMock()
                self._ctl.QueryInterface.return_value = FakeMeter(peak)

        sessions = [
            FakeSession(FakeProc(200, "msedge.exe"), 0.25),
            FakeSession(FakeProc(100, "chrome.exe"), 0.80),
            FakeSession(FakeProc(300, "GameBeats.exe"), 0.50),
        ]
        with patch.object(am, "HAS_PYCAW", True), \
             patch.object(am, "_browser_audio_only", False), \
             patch.object(am, "_ensure_com_initialized", lambda: None), \
             patch.object(am, "_spotify_exclusion_pids", lambda: {100, 300}), \
             patch.object(am.AudioUtilities, "GetAllSessions", lambda: sessions):
            peak, status = am.get_other_audio_peak()
        self.assertEqual(status, "ok")
        self.assertAlmostEqual(peak, 0.25, places=4)

    def test_measure_game_loud_reports_other_audio_without_game(self):
        from core import audio_monitor as am
        with patch.object(am, "_pids_for_game", lambda *_: set()), \
             patch.object(am, "get_other_audio_peak", lambda: (0.25, "ok")):
            loud, peak, mode, dbg = am.measure_game_loud()
        self.assertTrue(loud)
        self.assertAlmostEqual(peak, 0.25, places=4)
        self.assertEqual(mode, "other-session")
        self.assertTrue(dbg["other_loud"])

    def test_measure_game_loud_quiet_other_audio(self):
        from core import audio_monitor as am
        with patch.object(am, "_pids_for_game", lambda *_: set()), \
             patch.object(am, "get_other_audio_peak", lambda: (0.001, "ok")):
            loud, peak, mode, dbg = am.measure_game_loud()
        self.assertFalse(loud)
        self.assertEqual(mode, "other-session")
        self.assertFalse(dbg["other_loud"])


class TestSkipCompletionWatchdog(unittest.TestCase):
    def _app(self):
        from ui.app import GameBeatsApp

        app = GameBeatsApp.__new__(GameBeatsApp)
        app.root = MagicMock()
        app.root.after.return_value = "job"
        app._skip_request_seq = 5
        app._skip_completion_job = None
        app._puppy_thinking_active = MagicMock(return_value=True)
        app._puppy_thinking_reason = "track"
        app._intentional_pause_active = MagicMock(return_value=False)
        app._spotify_audio_active = True
        app._is_playing = True
        app._spotify_sound_detected_recently = MagicMock(return_value=False)
        app._finish_puppy_thinking = MagicMock(return_value=True)
        return app

    def test_watchdog_finishes_a_stalled_skip_while_audio_is_playing(self):
        from ui.app import GameBeatsApp

        app = self._app()
        GameBeatsApp._finish_stalled_skip(app, 5)

        app._finish_puppy_thinking.assert_called_once_with(play_change=True)

    def test_watchdog_ignores_stale_paused_or_silent_skips(self):
        from ui.app import GameBeatsApp

        app = self._app()
        GameBeatsApp._finish_stalled_skip(app, 4)
        app._finish_puppy_thinking.assert_not_called()

        app._puppy_thinking_reason = "playlist"
        GameBeatsApp._finish_stalled_skip(app, 5)
        app._finish_puppy_thinking.assert_not_called()

        app._puppy_thinking_reason = "track"
        app._intentional_pause_active.return_value = True
        GameBeatsApp._finish_stalled_skip(app, 5)
        app._finish_puppy_thinking.assert_not_called()

        app._intentional_pause_active.return_value = False
        app._spotify_audio_active = False
        app._is_playing = False
        GameBeatsApp._finish_stalled_skip(app, 5)
        app._finish_puppy_thinking.assert_not_called()

    def test_watchdog_is_scheduled_for_the_current_skip(self):
        from ui.app import SKIP_COMPLETION_WATCHDOG_MS, GameBeatsApp

        app = self._app()
        GameBeatsApp._schedule_skip_completion_watchdog(app, 5)

        app.root.after.assert_called_once()
        delay, callback = app.root.after.call_args.args
        self.assertEqual(delay, SKIP_COMPLETION_WATCHDOG_MS)
        callback()
        app._finish_puppy_thinking.assert_called_once_with(play_change=True)


class TestSkipWhilePaused(unittest.TestCase):
    def _app(self):
        from ui.app import GameBeatsApp
        app = GameBeatsApp.__new__(GameBeatsApp)
        app._manual_paused = True
        app._user_paused_flag = True
        app._paused_by_game_flag = False
        app._pause_stack = [("user", time.time())]
        app._playlist_switch_pause = True
        app._playlist_switch_heard_silence = True
        app._playlist_switch_pause_confirmed = True
        app._playlist_switch_audio_heard_ts = 123.0
        app._playlist_audio_armed = True
        app._spotify_loud_streak = 4
        app._music_missing_since = 100.0
        app._playlist_end_pending = True
        app._user_toggle_ts = 0.0
        app._playlist_end_prompt_not_before = 0.0
        app._playlist_end_delay_seconds = MagicMock(return_value=4.0)
        return app

    def test_next_while_paused_clears_only_the_user_pause(self):
        from ui.app import GameBeatsApp
        app = self._app()

        self.assertTrue(GameBeatsApp._clear_user_pause_for_skip(app))

        self.assertFalse(app._manual_paused)
        self.assertFalse(app._user_paused_flag)
        self.assertFalse(app._playlist_switch_pause)
        self.assertFalse(app._playlist_end_pending)
        self.assertFalse(app._playlist_audio_armed)
        self.assertEqual(app._spotify_loud_streak, 0)
        self.assertEqual(app._pause_stack, [])
        self.assertGreater(app._user_toggle_ts, 0.0)
        self.assertGreater(app._playlist_end_prompt_not_before, time.time())

    def test_skip_does_not_clear_a_game_audio_pause(self):
        from ui.app import GameBeatsApp
        app = self._app()
        app._manual_paused = False
        app._user_paused_flag = False
        app._paused_by_game_flag = True
        app._pause_stack = [("auto", time.time())]

        self.assertFalse(GameBeatsApp._clear_user_pause_for_skip(app))
        self.assertTrue(app._paused_by_game_flag)
        self.assertEqual(app._pause_stack[0][0], "auto")

    def test_confirmed_skip_audio_updates_the_visible_playing_state(self):
        from ui.app import GameBeatsApp
        app = self._app()
        app._manual_paused = False
        app._user_paused_flag = False
        app._pause_stack = []
        app._skip_request_seq = 7
        app._is_playing = False
        app._spotify_started_by_us = False
        app._playback_started_ts = 0.0
        app._last_spotify_loud_ts = 0.0
        app._spotify_audio_active = False
        app._intentional_pause_active = MagicMock(return_value=False)
        app._set_play_btn_icon = MagicMock()
        app._set_puppy_singing_visible = MagicMock()
        app._remove_pause_reason = MagicMock()

        self.assertTrue(GameBeatsApp._adopt_skip_playback(app, 7))
        self.assertTrue(app._is_playing)
        self.assertTrue(app._spotify_started_by_us)
        self.assertTrue(app._spotify_audio_active)
        app._set_play_btn_icon.assert_called_once_with(True, force_btn=True)
        app._set_puppy_singing_visible.assert_called_once_with(True)

    def test_stale_skip_result_is_ignored(self):
        from ui.app import GameBeatsApp
        app = self._app()
        app._manual_paused = False
        app._user_paused_flag = False
        app._skip_request_seq = 8
        app._is_playing = False
        app._intentional_pause_active = MagicMock(return_value=False)
        app._set_play_btn_icon = MagicMock()
        app._set_puppy_singing_visible = MagicMock()
        app._remove_pause_reason = MagicMock()

        self.assertFalse(GameBeatsApp._adopt_skip_playback(app, 7))
        self.assertFalse(app._is_playing)
        app._set_play_btn_icon.assert_not_called()


if __name__ == "__main__":
    unittest.main()

