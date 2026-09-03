"""Stateful automatic/manual marker tracker above the memory adapter."""
from __future__ import annotations

import math
import time
from typing import Callable

from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerSnapshot,
    WorldMapMarker,
    map_marker_screen_geometry,
    unproject_map_to_world,
)
from infra.memory.map_marker_client import FullMapNotReadyError, MapMarkerMemoryClient


class MapMarkerTracker:
    def __init__(
        self,
        process_name: str,
        *,
        client_factory: Callable[[str], MapMarkerMemoryClient] = MapMarkerMemoryClient,
        clock: Callable[[], float] = time.monotonic,
        reconnect_interval: float = 1.0,
        automatic_scan_interval: float = 0.1,
    ) -> None:
        self.process_name = process_name
        self._client_factory = client_factory
        self._clock = clock
        self._reconnect_interval = max(0.05, float(reconnect_interval))
        self._automatic_scan_interval = max(0.0, float(automatic_scan_interval))
        self._next_automatic_scan_at = 0.0
        self._client: MapMarkerMemoryClient | None = None
        self._next_connect_at = 0.0
        self._map_id = 0
        self._markers: dict[str, WorldMapMarker] = {}
        self._automatic_by_object: dict[int, str] = {}
        self._manual_counter = 0
        self._snapshot = MapMarkerSnapshot()

    @property
    def snapshot(self) -> MapMarkerSnapshot:
        return self._snapshot

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                # A stale/recycled process handle must not prevent the Qt
                # overlay timer from being stopped during disable or shutdown.
                pass
        self._next_automatic_scan_at = 0.0
        self._snapshot = MapMarkerSnapshot()

    def tick(
        self,
        *,
        client_height: int,
        client_width: int | None = None,
        display_scale: float = 1.0,
        automatic_discovery: bool = False,
    ) -> MapMarkerSnapshot:
        automatic_enabled = bool(automatic_discovery)
        automatic_now = self._clock() if automatic_enabled else 0.0
        sample_automatic = bool(
            automatic_enabled
            and automatic_now >= self._next_automatic_scan_at
        )
        client = self._connect_if_due()
        if client is None:
            self._snapshot = MapMarkerSnapshot(
                map_id=self._map_id,
                markers=tuple(self._markers.values()),
            )
            return self._snapshot

        try:
            frame = client.poll(
                client_height=max(1, int(client_height)),
                client_width=(
                    max(1, int(client_width)) if client_width is not None else None
                ),
                display_scale=max(0.01, float(display_scale)),
                automatic_discovery=automatic_enabled,
                sample_automatic_discovery=sample_automatic,
            )
        except FullMapNotReadyError:
            # FullMap type info is initialized lazily by the game. Keep this
            # process handle and retry on the next 25 ms marker tick so the
            # first map open cannot look like a broken widget for a full
            # reconnect interval.
            self._snapshot = MapMarkerSnapshot(
                map_id=self._map_id,
                markers=tuple(self._markers.values()),
            )
            return self._snapshot
        except Exception:
            self._disconnect_for_retry()
            self._snapshot = MapMarkerSnapshot(
                map_id=self._map_id,
                markers=tuple(self._markers.values()),
            )
            return self._snapshot

        if frame.map_id != self._map_id:
            self._map_id = frame.map_id
            self._markers.clear()
            self._automatic_by_object.clear()

        if not automatic_enabled:
            self._next_automatic_scan_at = 0.0
            for marker_id in self._automatic_by_object.values():
                self._markers.pop(marker_id, None)
            self._automatic_by_object.clear()
        elif sample_automatic:
            # FullMap projection and manual input stay on the 25 ms UI cadence.
            # Only automatic object discovery and lifecycle reads are throttled.
            interval = self._automatic_scan_interval
            previous_deadline = self._next_automatic_scan_at
            if interval <= 0.0:
                self._next_automatic_scan_at = automatic_now
            elif previous_deadline <= 0.0:
                self._next_automatic_scan_at = automatic_now + interval
            else:
                # Advance from the previous deadline instead of from the actual
                # tick time. This avoids turning a nominal 100 ms cadence into
                # 100 ms plus one 25 ms UI-tick scheduling delay every cycle.
                elapsed = max(0.0, automatic_now - previous_deadline)
                steps = max(1, int(math.floor(elapsed / interval)) + 1)
                self._next_automatic_scan_at = previous_deadline + steps * interval
            for object_ptr, marker_id in tuple(self._automatic_by_object.items()):
                try:
                    active = client.activity_is_active(object_ptr)
                except Exception:
                    active = False
                if not active:
                    self._automatic_by_object.pop(object_ptr, None)
                    self._markers.pop(marker_id, None)

            detected = frame.current_activity
            if (
                detected is not None
                and detected.object_ptr not in self._automatic_by_object
            ):
                self._replace_nearby_manual_marker(
                    detected.action_id, detected.world_x, detected.world_z
                )
                marker_id = f"auto:{detected.object_ptr:X}"
                self._markers[marker_id] = WorldMapMarker(
                    marker_id=marker_id,
                    action_id=detected.action_id,
                    world_x=detected.world_x,
                    world_z=detected.world_z,
                    source="automatic",
                    object_ptr=detected.object_ptr,
                )
                self._automatic_by_object[detected.object_ptr] = marker_id

        self._snapshot = MapMarkerSnapshot(
            map_id=frame.map_id,
            map_open=frame.map_open,
            world_size=frame.world_size,
            viewport=frame.viewport,
            markers=tuple(self._markers.values()),
        )
        return self._snapshot

    def place_manual_marker(
        self,
        action_id: str,
        *,
        screen_x: float,
        screen_y: float,
        scale: float = 1.0,
    ) -> bool:
        if action_id not in MAP_MARKER_ACTION_BY_ID:
            return False
        snapshot = self._snapshot
        if not snapshot.map_open or snapshot.viewport is None:
            return False
        # Tapping on or just around an existing manual icon toggles it off,
        # regardless of which action is assigned to the pressed hotkey. The
        # binding selects what to place in empty space; requiring the same
        # action here would instead stack a new icon over the existing one.
        # Walk newest-first because insertion order is also painting order, so
        # this removes the visible topmost icon from any legacy overlap.
        # Test against the projected visual centre. Edge markers keep their
        # exact world position and the painter clips the part outside the map.
        for marker_id, marker in reversed(tuple(self._markers.items())):
            if marker.source != "manual":
                continue
            geometry = map_marker_screen_geometry(
                marker.world_x,
                marker.world_z,
                world_size=snapshot.world_size,
                viewport=snapshot.viewport,
                scale=scale,
            )
            if geometry is None:
                continue
            center_x, center_y, icon_size = geometry
            hit_radius = icon_size / 2.0 + max(8.0, icon_size * 0.15)
            if math.hypot(center_x - screen_x, center_y - screen_y) <= hit_radius:
                self._markers.pop(marker_id, None)
                self._refresh_snapshot_markers()
                return True

        world = unproject_map_to_world(
            screen_x,
            screen_y,
            world_size=snapshot.world_size,
            viewport=snapshot.viewport,
        )
        if world is None:
            return False
        world_x, world_z = world

        self._manual_counter += 1
        marker_id = f"manual:{self._manual_counter}"
        self._markers[marker_id] = WorldMapMarker(
            marker_id=marker_id,
            action_id=action_id,
            world_x=world_x,
            world_z=world_z,
            source="manual",
        )
        self._refresh_snapshot_markers()
        return True

    def _connect_if_due(self) -> MapMarkerMemoryClient | None:
        if self._client is not None:
            return self._client
        now = self._clock()
        if now < self._next_connect_at:
            return None
        try:
            self._client = self._client_factory(self.process_name)
        except Exception:
            self._next_connect_at = now + self._reconnect_interval
            return None
        return self._client

    def _disconnect_for_retry(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        self._next_connect_at = self._clock() + self._reconnect_interval

    def _replace_nearby_manual_marker(
        self, action_id: str, world_x: float, world_z: float
    ) -> None:
        action = MAP_MARKER_ACTION_BY_ID[action_id]
        for marker_id, marker in tuple(self._markers.items()):
            marker_action = MAP_MARKER_ACTION_BY_ID.get(marker.action_id)
            if (
                marker.source == "manual"
                and marker_action is not None
                and marker_action.family == action.family
                and math.hypot(marker.world_x - world_x, marker.world_z - world_z)
                <= 25.0
            ):
                self._markers.pop(marker_id, None)

    def _refresh_snapshot_markers(self) -> None:
        snapshot = self._snapshot
        self._snapshot = MapMarkerSnapshot(
            map_id=snapshot.map_id,
            map_open=snapshot.map_open,
            world_size=snapshot.world_size,
            viewport=snapshot.viewport,
            markers=tuple(self._markers.values()),
        )
