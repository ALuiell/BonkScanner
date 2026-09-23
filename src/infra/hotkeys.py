from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class HotkeyBinding:
    hotkey: str
    callback: Callable[[], None]
    require_game_window: bool = False


@dataclass(frozen=True)
class _HotkeyVariant:
    required_scan_codes: frozenset[int]
    trigger_scan_code: int


@dataclass(frozen=True)
class _ParsedBinding:
    callback: Callable[[], None]
    variants: tuple[_HotkeyVariant, ...]
    require_game_window: bool


class ModifierAwareHotkeyManager:
    """Global hotkeys that tolerate configured game keys while the game is active."""

    def __init__(
        self,
        keyboard_module: object,
        *,
        allowed_game_keys: Iterable[str],
        is_game_window_active: Callable[[], bool],
        state_reader: Callable[[Iterable[int]], dict[int, bool | None]] | None = None,
    ) -> None:
        self.keyboard = keyboard_module
        self._state_reader = state_reader
        self._key_revision: dict[int, object] = {}
        self._release_seen: dict[int, float] = {}
        self._repaired_before: dict[int, float] = {}
        self._reconcile_stop = threading.Event()
        self._reconcile_thread: threading.Thread | None = None
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
            parsed_bindings.append(
                self._parse_single_step_binding(
                    steps[0],
                    binding.callback,
                    require_game_window=binding.require_game_window,
                )
            )

        with self._lock:
            self._bindings = tuple(parsed_bindings)
            self._pressed_scan_codes.clear()

        try:
            if parsed_bindings:
                self._hook_remover = self.keyboard.hook(self._on_keyboard_event)
            for binding in fallback_bindings:
                remover = self.keyboard.add_hotkey(binding.hotkey, binding.callback)
                self._fallback_removers.append(remover)
            if parsed_bindings and self._state_reader is not None:
                self._reconcile_stop = threading.Event()
                self._reconcile_thread = threading.Thread(
                    target=self._reconcile_loop, args=(self._reconcile_stop,),
                    name="BonkScannerKeyReleaseRepair", daemon=True,
                )
                self._reconcile_thread.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        self._reconcile_stop.set()
        repair_thread, self._reconcile_thread = self._reconcile_thread, None
        removers: list[Callable[[], None]] = []
        with self._lock:
            if self._hook_remover is not None:
                removers.append(self._hook_remover)
                self._hook_remover = None
            removers.extend(self._fallback_removers)
            self._fallback_removers.clear()
            self._bindings = ()
            self._pressed_scan_codes.clear()
            self._key_revision.clear()
            self._release_seen.clear()
            self._repaired_before.clear()

        first_error: Exception | None = None
        for remover in removers:
            try:
                remover()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if (repair_thread is not None and repair_thread.ident is not None
                and repair_thread is not threading.current_thread()):
            repair_thread.join(timeout=0.5)
        if first_error is not None:
            raise first_error

    def reset_pressed_keys(self) -> None:
        with self._lock:
            self._pressed_scan_codes.clear()
            self._key_revision.clear()
            self._release_seen.clear()
            self._repaired_before.clear()

    def _reconcile_loop(self, stop: threading.Event) -> None:
        while not stop.wait(0.25):
            self.reconcile_pressed_keys()

    def reconcile_pressed_keys(self) -> int:
        """Clear only twice-confirmed releases; never invoke a binding callback."""
        if self._state_reader is None:
            return 0
        with self._lock:
            baseline = dict(self._key_revision)
        if not baseline:
            return 0
        sampled_at = time.time()
        try:
            states = self._state_reader(baseline)
        except Exception:
            states = {}  # Unknown breaks a sequence of release confirmations.
        now = time.monotonic()
        repaired = 0
        with self._lock:
            for code, revision in baseline.items():
                # A new DOWN (including repeat), UP, reset or rebind invalidates
                # an older sample. These are key revisions, not scan commands.
                if self._key_revision.get(code) is not revision:
                    continue
                if states.get(code) is not False:
                    self._release_seen.pop(code, None)
                    continue
                since = self._release_seen.setdefault(code, now)
                if now - since < 0.2:
                    continue
                self._pressed_scan_codes.discard(code)
                self._key_revision.pop(code, None)
                self._release_seen.pop(code, None)
                self._repaired_before[code] = sampled_at
                repaired += 1
        return repaired

    def any_key_pressed(self, key_names: Iterable[str]) -> bool:
        scan_codes = self._scan_codes_for_names(key_names)
        with self._lock:
            return bool(self._pressed_scan_codes.intersection(scan_codes))

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
        *,
        require_game_window: bool = False,
    ) -> _ParsedBinding:
        if not step:
            raise ValueError("Hotkey must contain at least one key.")

        variants = {
            _HotkeyVariant(frozenset(combination), combination[-1])
            for combination in itertools.product(*step)
        }
        return _ParsedBinding(
            callback=callback,
            variants=tuple(variants),
            require_game_window=bool(require_game_window),
        )

    def _on_keyboard_event(self, event: object) -> None:
        scan_code = int(event.scan_code)
        event_type = str(event.event_type)
        callbacks: list[Callable[[], None]] = []

        with self._lock:
            cutoff = self._repaired_before.get(scan_code)
            latest_repair = max(self._repaired_before.values(), default=0.0)
            event_time = getattr(event, "time", None)
            if (cutoff is not None and event_time is not None
                    and event_time < cutoff <= time.time()):
                # An older queued repeat must not become a fresh press just
                # because the physical release repaired our cached state.
                return
            self._repaired_before.pop(scan_code, None)
            if event_type == "up":
                self._pressed_scan_codes.discard(scan_code)
                self._key_revision.pop(scan_code, None)
                self._release_seen.pop(scan_code, None)
                return
            if event_type != "down":
                return
            self._key_revision[scan_code] = object()
            self._release_seen.pop(scan_code, None)
            if scan_code in self._pressed_scan_codes:
                return

            self._pressed_scan_codes.add(scan_code)
            pressed_scan_codes = frozenset(self._pressed_scan_codes)
            candidates: list[tuple[Callable[[], None], bool]] = []

            for binding in self._bindings:
                if (not binding.require_game_window and event_time is not None
                        and event_time < latest_repair <= time.time()):
                    # Repairing a missing modifier UP must not reinterpret an
                    # older queued F6 as an unmodified press. Movement stays safe.
                    continue
                for variant in binding.variants:
                    if variant.trigger_scan_code != scan_code:
                        continue
                    if not variant.required_scan_codes.issubset(pressed_scan_codes):
                        continue
                    extra_scan_codes = pressed_scan_codes - variant.required_scan_codes
                    if not extra_scan_codes:
                        candidates.append(
                            (binding.callback, binding.require_game_window)
                        )
                        break
                    if binding.require_game_window:
                        candidates.append((binding.callback, True))
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
