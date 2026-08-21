"""Tap/hold gesture state for the single retained manual marker mode."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from core.map_markers import (
    MarkerPalette,
    MapMarkerSnapshot,
    build_marker_palette,
    normalize_map_marker_hotkeys,
    select_marker_palette_action,
)


@dataclass(frozen=True, slots=True)
class MarkerGestureUpdate:
    palette: MarkerPalette | None = None
    placement: tuple[str, float, float] | None = None


@dataclass(slots=True)
class _ActiveGesture:
    binding: str
    assigned_action_id: str
    map_id: int
    anchor_x: float
    anchor_y: float
    pressed_at: float
    palette: MarkerPalette | None = None


class MapMarkerHotkeyController:
    def __init__(
        self,
        input_state: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        hold_seconds: float = 0.35,
    ) -> None:
        self.input_state = input_state
        self._clock = clock
        self._hold_seconds = max(0.1, float(hold_seconds))
        self._active: _ActiveGesture | None = None
        self._previous_pressed: dict[str, bool] = {}

    def reset(self) -> None:
        self._active = None
        self._previous_pressed.clear()

    def poll(
        self,
        bindings: Any,
        snapshot: MapMarkerSnapshot,
        *,
        cursor_x: float,
        cursor_y: float,
        scale: float = 1.0,
    ) -> MarkerGestureUpdate:
        normalized = normalize_map_marker_hotkeys(bindings)
        pressed = {
            row["input"]: bool(self.input_state.is_pressed(row["input"]))
            for row in normalized
        }
        now = self._clock()
        result = MarkerGestureUpdate()

        active = self._active
        if active is not None:
            binding_exists = any(
                row["input"] == active.binding for row in normalized
            )
            valid_map = bool(
                snapshot.map_open
                and snapshot.viewport is not None
                and snapshot.map_id == active.map_id
            )
            if not binding_exists or not valid_map:
                self._active = None
            elif pressed.get(active.binding, False):
                if active.palette is None and now - active.pressed_at >= self._hold_seconds:
                    active.palette = build_marker_palette(
                        active.anchor_x,
                        active.anchor_y,
                        viewport=snapshot.viewport,
                        scale=scale,
                        selected_action_id=active.assigned_action_id,
                    )
                if active.palette is not None:
                    active.palette = select_marker_palette_action(
                        active.palette, cursor_x, cursor_y
                    )
                    result = MarkerGestureUpdate(palette=active.palette)
            else:
                selected = (
                    active.palette.selected_action_id
                    if active.palette is not None
                    else active.assigned_action_id
                )
                if selected:
                    result = MarkerGestureUpdate(
                        placement=(
                            selected,
                            active.anchor_x,
                            active.anchor_y,
                        )
                    )
                self._active = None

        if self._active is None and result.placement is None:
            viewport = snapshot.viewport
            if snapshot.map_open and viewport is not None and viewport.contains(cursor_x, cursor_y):
                for row in normalized:
                    binding = row["input"]
                    if pressed[binding] and not self._previous_pressed.get(binding, False):
                        self._active = _ActiveGesture(
                            binding=binding,
                            assigned_action_id=row["action"],
                            map_id=snapshot.map_id,
                            anchor_x=float(cursor_x),
                            anchor_y=float(cursor_y),
                            pressed_at=now,
                        )
                        break

        self._previous_pressed = pressed
        return result
