"""Stateful automatic/manual marker tracker above the memory adapter."""
from __future__ import annotations

import math
import time
from typing import Callable

from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerSnapshot,
    WorldMapMarker,
    unproject_map_to_world,
)
from infra.memory.map_marker_client import MapMarkerMemoryClient


class MapMarkerTracker:
    def __init__(
        self,
        process_name: str,
        *,
        client_factory: Callable[[str], MapMarkerMemoryClient] = MapMarkerMemoryClient,
        clock: Callable[[], float] = time.monotonic,
        reconnect_interval: float = 1.0,
    ) -> None:
        self.process_name = process_name
        self._client_factory = client_factory
        self._clock = clock
        self._reconnect_interval = max(0.05, float(reconnect_interval))
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
            client.close()
        self._snapshot = MapMarkerSnapshot()

    def tick(
        self,
        *,
        client_height: int,
        client_width: int | None = None,
        display_scale: float = 1.0,
        automatic_discovery: bool = False,
    ) -> MapMarkerSnapshot:
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
                automatic_discovery=bool(automatic_discovery),
            )
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

        if not automatic_discovery:
            for marker_id in self._automatic_by_object.values():
                self._markers.pop(marker_id, None)
            self._automatic_by_object.clear()
        else:
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
    ) -> bool:
        if action_id not in MAP_MARKER_ACTION_BY_ID:
            return False
        snapshot = self._snapshot
        if not snapshot.map_open or snapshot.viewport is None:
            return False
        world = unproject_map_to_world(
            screen_x,
            screen_y,
            world_size=snapshot.world_size,
            viewport=snapshot.viewport,
        )
        if world is None:
            return False
        world_x, world_z = world

        # Tapping the same action directly on an existing manual icon toggles it
        # off.  This gives the one retained manual mode an undo path without
        # adding a second delete mode or making the click-through overlay active.
        pixel_radius = 12.0
        world_radius = (
            pixel_radius / snapshot.viewport.width * snapshot.world_size
        )
        for marker_id, marker in tuple(self._markers.items()):
            if (
                marker.source == "manual"
                and marker.action_id == action_id
                and math.hypot(marker.world_x - world_x, marker.world_z - world_z)
                <= world_radius
            ):
                self._markers.pop(marker_id, None)
                self._refresh_snapshot_markers()
                return True

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
