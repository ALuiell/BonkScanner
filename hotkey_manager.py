from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class HotkeyBinding:
    hotkey: str
    callback: Callable[[], None]


@dataclass(frozen=True)
class _HotkeyVariant:
    required_scan_codes: frozenset[int]
    trigger_scan_code: int


@dataclass(frozen=True)
class _ParsedBinding:
    callback: Callable[[], None]
    variants: tuple[_HotkeyVariant, ...]


class ModifierAwareHotkeyManager:
    """Global hotkeys that tolerate configured game keys while the game is active."""

    def __init__(
        self,
        keyboard_module: object,
        *,
        allowed_game_keys: Iterable[str],
        is_game_window_active: Callable[[], bool],
    ) -> None:
        self.keyboard = keyboard_module
        self.is_game_window_active = is_game_window_active
        self.allowed_game_scan_codes = self._scan_codes_for_names(allowed_game_keys)
        self._bindings: tuple[_ParsedBinding, ...] = ()
        self._pressed_scan_codes: set[int] = set()
        self._hook_remover: Callable[[], None] | None = None
        self._fallback_removers: list[Callable[[], None]] = []
        self._lock = threading.RLock()

    def start(self, bindings: Iterable[HotkeyBinding]) -> None:
        self.stop()
        parsed_bindings: list[_ParsedBinding] = []
        fallback_bindings: list[HotkeyBinding] = []

        for binding in bindings:
            steps = self.keyboard.parse_hotkey(binding.hotkey)
            if len(steps) != 1:
                fallback_bindings.append(binding)
                continue
            parsed_bindings.append(self._parse_single_step_binding(steps[0], binding.callback))

        with self._lock:
            self._bindings = tuple(parsed_bindings)
            self._pressed_scan_codes.clear()

        try:
            if parsed_bindings:
                self._hook_remover = self.keyboard.hook(self._on_keyboard_event)
            for binding in fallback_bindings:
                remover = self.keyboard.add_hotkey(binding.hotkey, binding.callback)
                self._fallback_removers.append(remover)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        removers: list[Callable[[], None]] = []
        with self._lock:
            if self._hook_remover is not None:
                removers.append(self._hook_remover)
                self._hook_remover = None
            removers.extend(self._fallback_removers)
            self._fallback_removers.clear()
            self._bindings = ()
            self._pressed_scan_codes.clear()

        first_error: Exception | None = None
        for remover in removers:
            try:
                remover()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def reset_pressed_keys(self) -> None:
        with self._lock:
            self._pressed_scan_codes.clear()

    def _scan_codes_for_names(self, key_names: Iterable[str]) -> frozenset[int]:
        scan_codes: set[int] = set()
        for key_name in key_names:
            normalized_name = str(key_name).strip()
            if normalized_name:
                scan_codes.update(self.keyboard.key_to_scan_codes(normalized_name))
        return frozenset(scan_codes)

    @staticmethod
    def _parse_single_step_binding(
        step: tuple[tuple[int, ...], ...],
        callback: Callable[[], None],
    ) -> _ParsedBinding:
        if not step:
            raise ValueError("Hotkey must contain at least one key.")

        variants = {
            _HotkeyVariant(frozenset(combination), combination[-1])
            for combination in itertools.product(*step)
        }
        return _ParsedBinding(callback=callback, variants=tuple(variants))

    def _on_keyboard_event(self, event: object) -> None:
        scan_code = int(event.scan_code)
        event_type = str(event.event_type)
        callbacks: list[Callable[[], None]] = []

        with self._lock:
            if event_type == "up":
                self._pressed_scan_codes.discard(scan_code)
                return
            if event_type != "down" or scan_code in self._pressed_scan_codes:
                return

            self._pressed_scan_codes.add(scan_code)
            pressed_scan_codes = frozenset(self._pressed_scan_codes)
            candidates: list[tuple[Callable[[], None], bool]] = []

            for binding in self._bindings:
                for variant in binding.variants:
                    if variant.trigger_scan_code != scan_code:
                        continue
                    if not variant.required_scan_codes.issubset(pressed_scan_codes):
                        continue
                    extra_scan_codes = pressed_scan_codes - variant.required_scan_codes
                    if not extra_scan_codes:
                        candidates.append((binding.callback, False))
                        break
                    if extra_scan_codes.issubset(self.allowed_game_scan_codes):
                        candidates.append((binding.callback, True))
                        break

        game_window_active: bool | None = None
        for callback, requires_game_window in candidates:
            if requires_game_window:
                if game_window_active is None:
                    try:
                        game_window_active = bool(self.is_game_window_active())
                    except Exception:
                        game_window_active = False
                if not game_window_active:
                    continue
            callbacks.append(callback)

        for callback in callbacks:
            callback()
