"""Stateful automatic/manual marker tracker above the memory adapter."""
from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Callable

from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerSnapshot,
    MerchantStockCapture,
    WorldMapMarker,
    action_id_for_interactable,
    map_marker_screen_geometry,
    unproject_map_to_world,
)
from infra.memory.map_marker_client import FullMapNotReadyError, MapMarkerMemoryClient
from core.shady_prices import shady_price


class MapMarkerTracker:
    FAR_LIFECYCLE_INTERVAL = 0.5
    LIFECYCLE_PHASES = 5

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
        # The memory client caches the class identity learned when an activity
        # enters currentInteractable.  A transient poll failure replaces that
        # client, but the already-discovered marker ledger intentionally
        # survives the retry.  Keep the minimum identity here as well so the
        # replacement client can safely resume lifecycle checks instead of
        # treating every cache miss as an inactive object.
        self._automatic_identity_by_object: dict[int, tuple[int, str]] = {}
        self._lifecycle_schedule: dict[int, tuple[int, float]] = {}
        self._lifecycle_serial = 0
        self._merchant_stocks: dict[int, MerchantStockCapture] = {}
        self._price_economy = None
        self._next_price_sample_at = 0.0
        # A visited merchant may create a marker even while ordinary automatic
        # discovery is disabled. Track those separately so entitlement loss
        # removes only the premium-created markers, not manual user marks.
        self._merchant_created_objects: set[int] = set()
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
        self._map_id = 0
        self._markers.clear()
        self._automatic_by_object.clear()
        self._automatic_identity_by_object.clear()
        self._lifecycle_schedule.clear()
        self._lifecycle_serial = 0
        self._merchant_stocks.clear()
        self._price_economy = None
        self._next_price_sample_at = 0.0
        self._merchant_created_objects.clear()
        self._snapshot = MapMarkerSnapshot()

    def tick(
        self,
        *,
        client_height: int,
        client_width: int | None = None,
        display_scale: float = 1.0,
        automatic_discovery: bool = False,
        minimap_enabled: bool = False,
        merchant_memory_enabled: bool = False,
        microwave_uses_enabled: bool = False,
        merchant_prices_enabled: bool = False,
    ) -> MapMarkerSnapshot:
        automatic_enabled = bool(automatic_discovery)
        merchant_enabled = bool(merchant_memory_enabled)
        prices_enabled = bool(merchant_enabled and merchant_prices_enabled)
        if not prices_enabled:
            self._clear_stock_prices()
            self._price_economy = None
            self._next_price_sample_at = 0.0
        if not microwave_uses_enabled:
            for marker_id, marker in self._markers.items():
                if marker.uses_remaining is not None:
                    self._markers[marker_id] = replace(marker, uses_remaining=None)
        heavy_reads_enabled = automatic_enabled or merchant_enabled
        automatic_now = self._clock() if heavy_reads_enabled else 0.0
        sample_heavy = bool(
            heavy_reads_enabled and automatic_now + 1e-9 >= self._next_automatic_scan_at
        )

        if not merchant_enabled:
            self._merchant_stocks.clear()
            if not automatic_enabled:
                for object_ptr in tuple(self._merchant_created_objects):
                    marker_id = self._automatic_by_object.pop(object_ptr, None)
                    self._automatic_identity_by_object.pop(object_ptr, None)
                    if marker_id is not None:
                        self._markers.pop(marker_id, None)
            self._merchant_created_objects.clear()

        client = self._connect_if_due()
        if client is None:
            self._snapshot = MapMarkerSnapshot(
                map_id=self._map_id,
                markers=tuple(self._markers.values()),
                merchant_stocks=(
                    tuple(self._merchant_stocks.values())
                    if merchant_enabled
                    else ()
                ),
            )
            return self._snapshot

        try:
            poll_kwargs = dict(
                client_height=max(1, int(client_height)),
                client_width=(
                    max(1, int(client_width)) if client_width is not None else None
                ),
                display_scale=max(0.01, float(display_scale)),
                automatic_discovery=automatic_enabled,
                sample_automatic_discovery=(automatic_enabled and sample_heavy),
            )
            # Keep old test adapters and third-party ports source compatible
            # when neither new Premium feature is active.
            if minimap_enabled or merchant_enabled:
                poll_kwargs.update(
                    # Discovery still runs with an empty ledger. Once the
                    # first marker arrives, projection starts on the next
                    # 25 ms tick; no camera/UI reads are needed before that.
                    minimap_enabled=bool(minimap_enabled and self._markers),
                    merchant_memory_enabled=merchant_enabled,
                    sample_merchant_memory=(merchant_enabled and sample_heavy),
                )
            if prices_enabled:
                poll_kwargs['merchant_prices_enabled'] = True
            frame = client.poll(**poll_kwargs)
        except FullMapNotReadyError:
            # FullMap type info is initialized lazily by the game. Keep this
            # process handle and retry on the next 25 ms marker tick so the
            # first map open cannot look like a broken widget for a full
            # reconnect interval.
            self._snapshot = MapMarkerSnapshot(
                map_id=self._map_id,
                markers=tuple(self._markers.values()),
                merchant_stocks=(
                    tuple(self._merchant_stocks.values())
                    if merchant_enabled
                    else ()
                ),
            )
            return self._snapshot
        except Exception:
            self._disconnect_for_retry()
            self._snapshot = MapMarkerSnapshot(
                map_id=self._map_id,
                markers=tuple(self._markers.values()),
                merchant_stocks=(
                    tuple(self._merchant_stocks.values())
                    if merchant_enabled
                    else ()
                ),
            )
            return self._snapshot

        if frame.map_id != self._map_id:
            self._price_economy = None
            self._next_price_sample_at = 0.0
            self._map_id = frame.map_id
            self._markers.clear()
            self._automatic_by_object.clear()
            self._automatic_identity_by_object.clear()
            self._lifecycle_schedule.clear()
            self._lifecycle_serial = 0
            self._merchant_stocks.clear()
            self._merchant_created_objects.clear()

        if not heavy_reads_enabled:
            self._next_automatic_scan_at = 0.0
            self._lifecycle_schedule.clear()
            self._lifecycle_serial = 0
        elif sample_heavy:
            # Full Map/minimap projection and manual input stay on the 25 ms UI
            # cadence. Object lifecycle and offer-card reads are throttled.
            interval = self._automatic_scan_interval
            previous_deadline = self._next_automatic_scan_at
            if interval <= 0.0:
                self._next_automatic_scan_at = automatic_now
            elif previous_deadline <= 0.0:
                self._next_automatic_scan_at = automatic_now + interval
            else:
                elapsed = max(0.0, automatic_now - previous_deadline)
                steps = max(1, int(math.floor(elapsed / interval)) + 1)
                self._next_automatic_scan_at = previous_deadline + steps * interval

        if not automatic_enabled:
            for marker_id in self._automatic_by_object.values():
                if not merchant_enabled or marker_id not in {
                    self._automatic_by_object.get(ptr)
                    for ptr in self._merchant_created_objects
                }:
                    self._markers.pop(marker_id, None)
            for object_ptr in tuple(self._automatic_by_object):
                if merchant_enabled and object_ptr in self._merchant_created_objects:
                    continue
                self._automatic_by_object.pop(object_ptr, None)
                self._automatic_identity_by_object.pop(object_ptr, None)

        if sample_heavy:
            self._lifecycle_schedule = {
                ptr: schedule for ptr, schedule in self._lifecycle_schedule.items()
                if ptr in self._automatic_by_object
            }
            for object_ptr, marker_id in tuple(self._automatic_by_object.items()):
                if not self._lifecycle_check_due(object_ptr, marker_id, frame, automatic_now):
                    continue
                expected_identity = self._automatic_identity_by_object.get(object_ptr)
                try:
                    active = client.activity_is_active(
                        object_ptr,
                        expected_class_ptr=(
                            expected_identity[0] if expected_identity is not None else None
                        ),
                        expected_class_name=(
                            expected_identity[1] if expected_identity is not None else None
                        ),
                    )
                except Exception:
                    # A failed ReadProcessMemory call is unknown state, not
                    # proof that the player consumed the activity.  Preserve
                    # the marker and retry on the next automatic sample.
                    marker = self._markers.get(marker_id)
                    if marker is not None and marker.uses_remaining is not None:
                        self._markers[marker_id] = replace(marker, uses_remaining=None)
                    continue
                if (
                    active and microwave_uses_enabled and expected_identity is not None
                    and expected_identity[1] == "InteractableMicrowave"
                ):
                    marker = self._markers.get(marker_id)
                    uses_reader = getattr(client, "last_microwave_uses", None)
                    uses = uses_reader(object_ptr) if callable(uses_reader) else None
                    if marker is not None and marker.uses_remaining != uses:
                        self._markers[marker_id] = replace(marker, uses_remaining=uses)
                if not active:
                    self._lifecycle_schedule.pop(object_ptr, None)
                    self._automatic_by_object.pop(object_ptr, None)
                    self._automatic_identity_by_object.pop(object_ptr, None)
                    self._markers.pop(marker_id, None)
                    self._merchant_stocks.pop(object_ptr, None)
                    self._merchant_created_objects.discard(object_ptr)

        if automatic_enabled and sample_heavy:
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
                    uses_remaining=(
                        detected.uses_remaining if microwave_uses_enabled else None
                    ),
                )
                self._automatic_by_object[detected.object_ptr] = marker_id
                self._automatic_identity_by_object[detected.object_ptr] = (
                    detected.class_ptr,
                    detected.class_name,
                )

        capture = frame.merchant_stock_capture if merchant_enabled else None
        capture_changed = bool(
            capture is not None
            and capture != self._merchant_stocks.get(capture.merchant_object_ptr)
        )
        if (
            capture is not None
            and capture.map_id == frame.map_id
        ):
            object_ptr = capture.merchant_object_ptr
            marker_id = self._automatic_by_object.get(object_ptr)
            if marker_id is None:
                action_id = action_id_for_interactable(
                    "InteractableShadyGuy", capture.merchant_rarity
                )
                if action_id is not None:
                    self._replace_nearby_manual_marker(
                        action_id, capture.world_x, capture.world_z
                    )
                    marker_id = capture.marker_id
                    self._markers[marker_id] = WorldMapMarker(
                        marker_id=marker_id,
                        action_id=action_id,
                        world_x=capture.world_x,
                        world_z=capture.world_z,
                        source="automatic",
                        object_ptr=object_ptr,
                    )
                    self._automatic_by_object[object_ptr] = marker_id
                    self._automatic_identity_by_object[object_ptr] = (
                        capture.class_ptr,
                        "InteractableShadyGuy",
                    )
                    self._merchant_created_objects.add(object_ptr)
            if marker_id is not None:
                # A fresh confirmed visible UI capture is authoritative. Never
                # pin a merchant to its first sample forever: reopening the shop
                # must also repair a stale capture from an earlier UI transition.
                self._merchant_stocks[object_ptr] = capture
                self._merchant_created_objects.add(object_ptr)

        if prices_enabled and self._merchant_stocks:
            self._refresh_stock_prices(client, automatic_now, capture_changed)

        self._snapshot = MapMarkerSnapshot(
            map_id=frame.map_id,
            map_open=frame.map_open,
            world_size=frame.world_size,
            viewport=frame.viewport,
            markers=tuple(self._markers.values()),
            minimap_projection=(
                frame.minimap_projection if minimap_enabled else None
            ),
            merchant_stocks=(
                tuple(self._merchant_stocks.values()) if merchant_enabled else ()
            ),
        )
        return self._snapshot

    def _clear_stock_prices(self) -> None:
        for pointer, stock in self._merchant_stocks.items():
            if any(item.price is not None for item in stock.items):
                self._merchant_stocks[pointer] = replace(
                    stock, items=tuple(replace(item, price=None) for item in stock.items)
                )

    def _refresh_stock_prices(self, client, now: float, new_capture: bool) -> None:
        # Two small economy samples per second, independent of merchant count.
        # Recompute only on changed inputs or a newly captured stock.
        changed = False
        if new_capture or now >= self._next_price_sample_at:
            self._next_price_sample_at = now + .5
            try:
                economy = client.read_shady_economy()
            except Exception:
                self._price_economy = None
                self._clear_stock_prices()
                return
            changed = economy != self._price_economy
            self._price_economy = economy
        if self._price_economy is None or not (changed or new_capture):
            return
        for pointer, stock in self._merchant_stocks.items():
            items = tuple(
                replace(item, price=shady_price(self._price_economy, item.rarity, item.slot_multiplier))
                if item.slot_multiplier is not None else item
                for item in stock.items
            )
            if items != stock.items:
                self._merchant_stocks[pointer] = replace(stock, items=items)

    def _lifecycle_check_due(self, object_ptr, marker_id, frame, now: float) -> bool:
        projection = frame.minimap_projection
        marker = self._markers.get(marker_id)
        current = frame.current_activity
        capture = frame.merchant_stock_capture
        # Full Map shows all retained objects. Without a valid minimap camera
        # we cannot classify distance safely, so retain the usual fast checks.
        fast = (
            frame.map_open or projection is None or not projection.visible
            or projection.jammed or marker is None
            or (current is not None and current.object_ptr == object_ptr)
            or (capture is not None and capture.merchant_object_ptr == object_ptr)
        )
        if not fast:
            # Enclose the visible minimap footprint, with a margin to keep
            # objects approaching its edge on the fast lifecycle cadence.
            radius = projection.orthographic_size * max(1.0, projection.aspect) * 1.15
            dx = marker.world_x - projection.camera_world_x
            dz = marker.world_z - projection.camera_world_z
            fast = dx * dx + dz * dz <= radius * radius

        interval = self.FAR_LIFECYCLE_INTERVAL
        step = interval / self.LIFECYCLE_PHASES
        schedule = self._lifecycle_schedule.get(object_ptr)
        if schedule is None:
            slot = self._lifecycle_serial % self.LIFECYCLE_PHASES
            self._lifecycle_serial += 1
            due = math.floor(now / interval) * interval + slot * step
            if due < now - 1e-9:
                due += interval
            schedule = (slot, due)
            self._lifecycle_schedule[object_ptr] = schedule
        slot, due = schedule
        if not fast and now + 1e-9 < due:
            return False
        # Preserve each object's phase even while nearby. Entering the far
        # group therefore does not synchronize every deadline into one spike.
        due = math.floor(now / interval) * interval + slot * step
        if due <= now + 1e-9:
            due += interval
        self._lifecycle_schedule[object_ptr] = (slot, due)
        return True

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
        self._price_economy = None
        self._next_price_sample_at = 0.0
        self._clear_stock_prices()
        self._lifecycle_schedule.clear()
        self._lifecycle_serial = 0
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
            minimap_projection=snapshot.minimap_projection,
            merchant_stocks=snapshot.merchant_stocks,
        )
