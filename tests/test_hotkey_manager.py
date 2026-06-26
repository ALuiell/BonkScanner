from __future__ import annotations

import types
import unittest

from hotkey_manager import HotkeyBinding, ModifierAwareHotkeyManager


class FakeKeyboard:
    def __init__(self) -> None:
        self.scan_codes = {
            "f9": (67,),
            "w": (17,),
            "left shift": (42,),
            "right shift": (54,),
            "ctrl": (29,),
        }
        self.hook_callback = None
        self.hook_remove_calls = 0
        self.add_hotkey_calls: list[tuple[str, object]] = []
        self.fallback_remove_calls = 0

    def key_to_scan_codes(self, key_name: str) -> tuple[int, ...]:
        return self.scan_codes[key_name]

    def parse_hotkey(self, hotkey: str):
        return tuple(
            tuple(self.key_to_scan_codes(key.strip()) for key in step.split("+"))
            for step in hotkey.split(",")
        )

    def hook(self, callback):
        self.hook_callback = callback

        def remove() -> None:
            self.hook_remove_calls += 1
            self.hook_callback = None

        return remove

    def add_hotkey(self, hotkey: str, callback):
        self.add_hotkey_calls.append((hotkey, callback))

        def remove() -> None:
            self.fallback_remove_calls += 1

        return remove

    def emit(self, key_name: str, event_type: str) -> None:
        callback = self.hook_callback
        if callback is None:
            raise AssertionError("Keyboard hook is not active")
        callback(types.SimpleNamespace(scan_code=self.scan_codes[key_name][0], event_type=event_type))


class ModifierAwareHotkeyManagerTests(unittest.TestCase):
    def make_manager(self, *, game_active: bool = True, allowed_keys=("w", "left shift")):
        keyboard = FakeKeyboard()
        manager = ModifierAwareHotkeyManager(
            keyboard,
            allowed_game_keys=allowed_keys,
            is_game_window_active=lambda: game_active,
        )
        calls: list[str] = []
        manager.start((HotkeyBinding("f9", lambda: calls.append("f9")),))
        return keyboard, manager, calls

    def test_exact_hotkey_fires_even_outside_game(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=False)

        keyboard.emit("f9", "down")

        self.assertEqual(calls, ["f9"])

    def test_allowed_held_game_key_fires_while_game_is_active(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=True)

        keyboard.emit("w", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, ["f9"])

    def test_allowed_held_game_key_is_blocked_outside_game(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=False)

        keyboard.emit("w", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, [])

    def test_non_whitelisted_modifier_blocks_plain_hotkey(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=True)

        keyboard.emit("ctrl", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, [])

    def test_configured_modifier_remains_part_of_hotkey(self) -> None:
        keyboard = FakeKeyboard()
        calls: list[str] = []
        manager = ModifierAwareHotkeyManager(
            keyboard,
            allowed_game_keys=("w",),
            is_game_window_active=lambda: False,
        )
        manager.start((HotkeyBinding("ctrl+f9", lambda: calls.append("ctrl+f9")),))

        keyboard.emit("ctrl", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, ["ctrl+f9"])

    def test_game_key_can_accompany_configured_modifier_in_game(self) -> None:
        keyboard = FakeKeyboard()
        calls: list[str] = []
        manager = ModifierAwareHotkeyManager(
            keyboard,
            allowed_game_keys=("w",),
            is_game_window_active=lambda: True,
        )
        manager.start((HotkeyBinding("ctrl+f9", lambda: calls.append("ctrl+f9")),))

        keyboard.emit("w", "down")
        keyboard.emit("ctrl", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, ["ctrl+f9"])

    def test_repeat_keydown_and_later_game_key_do_not_retrigger(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=True)

        keyboard.emit("f9", "down")
        keyboard.emit("f9", "down")
        keyboard.emit("w", "down")

        self.assertEqual(calls, ["f9"])

    def test_release_allows_next_physical_press(self) -> None:
        keyboard, _manager, calls = self.make_manager()

        keyboard.emit("f9", "down")
        keyboard.emit("f9", "up")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, ["f9", "f9"])

    def test_right_shift_is_distinct_from_allowed_left_shift(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=True, allowed_keys=("left shift",))

        keyboard.emit("right shift", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, [])

    def test_allowed_left_shift_fires_while_game_is_active(self) -> None:
        keyboard, _manager, calls = self.make_manager(game_active=True, allowed_keys=("left shift",))

        keyboard.emit("left shift", "down")
        keyboard.emit("f9", "down")

        self.assertEqual(calls, ["f9"])

    def test_multi_step_hotkey_uses_keyboard_fallback(self) -> None:
        keyboard = FakeKeyboard()
        manager = ModifierAwareHotkeyManager(
            keyboard,
            allowed_game_keys=("w",),
            is_game_window_active=lambda: True,
        )
        callback = lambda: None

        manager.start((HotkeyBinding("f9,w", callback),))

        self.assertEqual(keyboard.add_hotkey_calls, [("f9,w", callback)])
        self.assertIsNone(keyboard.hook_callback)

        manager.stop()
        self.assertEqual(keyboard.fallback_remove_calls, 1)

    def test_stop_removes_only_the_owned_hook(self) -> None:
        keyboard, manager, _calls = self.make_manager()

        manager.stop()

        self.assertEqual(keyboard.hook_remove_calls, 1)
        self.assertIsNone(keyboard.hook_callback)


if __name__ == "__main__":
    unittest.main()
