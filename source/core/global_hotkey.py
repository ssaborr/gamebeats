"""
global_hotkey.py
────────────────
Global hotkey listener (Ctrl+Alt+N) to resume next playlist when mascot notifier is visible.

This runs in a separate daemon thread and does NOT interfere with game input.
Works even when the game window has focus (true global hotkey).

Architecture:
  • One listener thread per app instance
  • Non-blocking event-driven
  • Safe to call from game context
  • Zero impact on game performance
"""

import threading
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    try:
        from pynput import keyboard
        HAS_PYNPUT = True
    except ImportError:
        HAS_PYNPUT = False
else:
    HAS_PYNPUT = False


class GlobalHotkeyListener:
    """
    Listens for Ctrl+Alt+N (configurable) globally and fires callback.
    
    Parameters
    ----------
    callback : callable
        Called (on listener thread) when hotkey pressed.
        Should dispatch heavy work to a daemon thread.
    hotkey : tuple
        (modifier_keys, trigger_key)
        E.g., ({keyboard.Key.ctrl, keyboard.Key.alt}, keyboard.Key.n)
    """

    def __init__(self, callback, hotkey=None):
        self.callback = callback
        self._listener = None
        self._running = False
        
        # Default: Ctrl+Alt+N
        if hotkey is None:
            hotkey = ({keyboard.Key.ctrl, keyboard.Key.alt}, keyboard.Key.n)
        
        self._modifiers, self._trigger = hotkey
        self._pressed = set()

    def start(self) -> None:
        """Start listening in a daemon thread."""
        if not HAS_PYNPUT or self._listener is not None:
            return
        
        self._running = True
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _on_press(self, key) -> None:
        """Called when any key pressed (from listener thread)."""
        if not self._running:
            return
        
        try:
            self._pressed.add(key)
            
            # Check if all modifiers are held AND trigger pressed
            if self._trigger in self._pressed:
                # For special keys, compare directly
                modifiers_held = all(m in self._pressed for m in self._modifiers)
                if modifiers_held:
                    if callable(self.callback):
                        self.callback()
        except Exception:
            pass

    def _on_release(self, key) -> None:
        """Called when any key released (from listener thread)."""
        try:
            self._pressed.discard(key)
        except Exception:
            pass
