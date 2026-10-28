import unittest

from ui.spotify_window_guard import (
    OFFSCREEN_X,
    OFFSCREEN_Y,
    SpotifyWindowGuard,
)


class FakeWindowApi:
    def __init__(self, events, rects, visible):
        self.events = events
        self.rects = dict(rects)
        self.visible = set(visible)

    def is_visible(self, hwnd):
        return hwnd in self.visible

    def get_rect(self, hwnd):
        return self.rects.get(hwnd)

    def move(self, hwnd, x, y, width=0, height=0, keep_size=True):
        self.events.append(("move", hwnd, x, y, width, height, keep_size))
        old = self.rects.get(hwnd)
        if keep_size and old:
            self.rects[hwnd] = (x, y, old[2], old[3])
        else:
            self.rects[hwnd] = (x, y, width, height)
        return True

    def hide(self, hwnd):
        self.events.append(("hide", hwnd))
        self.visible.discard(hwnd)
        return True

    def spotify_windows(self):
        return list(self.rects)


class FakeDesktop:
    def __init__(self, api, events):
        self.api = api
        self.events = events

    def _show_spotify_for_uia(self, hwnd):
        # Must never be called: the guard replaces it with a no-show hider.
        self.events.append(("original_show", hwnd))
        self.api.visible.add(hwnd)
        return False

    def _hide_spotify_after_uia(self, hwnd, was_visible):
        self.events.append(("original_hide", hwnd, was_visible))
        if not was_visible:
            self.api.visible.discard(hwnd)


class TestSpotifyWindowGuard(unittest.TestCase):
    def _guard(self, rects=None, visible=None):
        events = []
        api = FakeWindowApi(
            events,
            rects if rects is not None else {10: (100, 100, 800, 600)},
            visible if visible is not None else set(),
        )
        desktop = FakeDesktop(api, events)
        guard = SpotifyWindowGuard(window_api=api, start_watcher=False)
        guard.install(desktop)
        return guard, desktop, api, events

    def test_hidden_window_is_moved_offscreen_and_never_shown(self):
        guard, desktop, api, events = self._guard()
        self.assertTrue(desktop._show_spotify_for_uia(10))
        self.assertEqual(
            events,
            [("move", 10, OFFSCREEN_X, OFFSCREEN_Y, 0, 0, True)],
        )
        self.assertEqual(api.rects[10], (OFFSCREEN_X, OFFSCREEN_Y, 800, 600))
        self.assertEqual(api.visible, set())

    def test_hide_keeps_window_offscreen_and_hidden(self):
        guard, desktop, api, events = self._guard()
        desktop._show_spotify_for_uia(10)
        desktop._hide_spotify_after_uia(10, False)
        self.assertEqual(
            events,
            [
                ("move", 10, OFFSCREEN_X, OFFSCREEN_Y, 0, 0, True),
                ("hide", 10),
            ],
        )

    def test_visible_window_is_moved_offscreen_then_hidden(self):
        guard, desktop, api, events = self._guard(visible={10})
        self.assertTrue(desktop._show_spotify_for_uia(10) is True)
        desktop._hide_spotify_after_uia(10, True)
        self.assertEqual(
            events,
            [
                ("move", 10, OFFSCREEN_X, OFFSCREEN_Y, 0, 0, True),
                ("hide", 10),
            ],
        )
        self.assertNotIn(10, api.visible)

    def test_install_is_idempotent_and_never_calls_original_show(self):
        guard, desktop, api, events = self._guard()
        guard.install(desktop)
        desktop._show_spotify_for_uia(10)
        self.assertEqual(events.count(("move", 10, OFFSCREEN_X, OFFSCREEN_Y, 0, 0, True)), 1)
        self.assertNotIn(("original_show", 10), events)
        self.assertNotIn(("original_hide", 10, False), events)

    def test_restore_all_returns_window_to_original_geometry(self):
        guard, desktop, api, events = self._guard()
        guard._move_offscreen_if_needed(10)
        guard.restore_all()
        self.assertEqual(api.rects[10], (100, 100, 800, 600))
        self.assertIn(("hide", 10), events)
        self.assertEqual(guard._rects, {})


if __name__ == "__main__":
    unittest.main()
