"""Stateful automatic/manual marker tracker above the memory adapter."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
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
from infra.crash_journal import log_runtime_event
from infra.memory.map_marker_client import (
    ActivityRead,
    FullMapNotReadyError,
    MapMarkerMemoryClient,
)
from infra.memory.reader import MemoryReadError


@dataclass(slots=True)
class _RetiredMarker:
    marker: WorldMapMarker
    identity: tuple[int, str]
    native_ptr: int
    stock: MerchantStockCapture | None
    merchant_created: bool
    expires_at: float
    next_check_at: float


@dataclass(slots=True)
class _UnreadableMarker:
    first_at: float
    last_at: float
    failures: int


class MapMarkerTracker:
    FAR_LIFECYCLE_INTERVAL = 0.5
    LIFECYCLE_PHASES = 5
    COMPLETION_CONFIRM_SECONDS = 0.35
    RECOVERY_WINDOW_SECONDS = 3.0
    UNREADABLE_HIDE_SECONDS = 2.0
    UNREADABLE_MAX_GAP_SECONDS = 1.0
    UNREADABLE_MIN_FAILURES = 3
    UNREADABLE_RECOVERY_SECONDS = 30.0
    RECOVERY_CHECK_INTERVAL = 0.5
    RECOVERY_CHECK_BUDGET = 8
    MAX_RETIRED_MARKERS = 128

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
        self._map_scope: tuple[str, int, int, int, int] | int | None = None
        self._last_valid_seed: int | None = None
        self._markers: dict[str, WorldMapMarker] = {}
        self._automatic_by_object: dict[int, str] = {}
        # The memory client caches the class identity learned when an activity
        # enters currentInteractable.  A transient poll failure replaces that
        # client, but the already-discovered marker ledger intentionally
        # survives the retry.  Keep the minimum identity here as well so the
        # replacement client can safely resume lifecycle checks instead of
        # treating every cache miss as an inactive object.
        self._automatic_identity_by_object: dict[int, tuple[int, str]] = {}
        self._native_by_object: dict[int, int] = {}
        self._completion_pending: dict[int, float] = {}
        self._unreadable_since: dict[int, _UnreadableMarker] = {}
        self._retired_markers: dict[int, _RetiredMarker] = {}
        self._lifecycle_failed: set[int] = set()
        self._poll_problem: str | None = None
        self._next_problem_log_at = 0.0
        self._lifecycle_schedule: dict[int, tuple[int, float]] = {}
        self._lifecycle_serial = 0
        self._merchant_stocks: dict[int, MerchantStockCapture] = {}
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
        self._map_scope = None
        self._last_valid_seed = None
        self._markers.clear()
        self._automatic_by_object.clear()
        self._automatic_identity_by_object.clear()
        self._clear_lifecycle_recovery()
        self._lifecycle_schedule.clear()
        self._lifecycle_serial = 0
        self._merchant_stocks.clear()
        self._merchant_created_objects.clear()
        self._snapshot = MapMarkerSnapshot()
        self._poll_problem = None
        self._next_problem_log_at = 0.0

    def recover(self) -> None:
        """Reconnect on the owning worker without destroying the map ledger."""
        self._disconnect_for_retry()
        self._next_connect_at = 0.0
        self._completion_pending.clear()
        self._unreadable_since.clear()
        self._snapshot = replace(
            self._snapshot, map_open=False, viewport=None, minimap_projection=None,
            map_read_succeeded=False,
        )

    def tick(
        self,
        *,
        client_height: int,
        client_width: int | None = None,
        display_scale: float = 1.0,
        automatic_discovery: bool = False,
        minimap_enabled: bool = False,
        merchant_memory_enabled: bool = False,
        map_surface_enabled: bool = True,
    ) -> MapMarkerSnapshot:
        automatic_enabled = bool(automatic_discovery)
        merchant_enabled = bool(merchant_memory_enabled)
        self._retired_markers = {
            ptr: entry for ptr, entry in self._retired_markers.items()
            if automatic_enabled or (merchant_enabled and entry.merchant_created)
        }
        heavy_reads_enabled = automatic_enabled or merchant_enabled
        automatic_now = self._clock() if heavy_reads_enabled else 0.0
        sample_heavy = bool(
            heavy_reads_enabled and automatic_now + 1e-9 >= self._next_automatic_scan_at
        )

        if not merchant_enabled:
            # Automatic icons may remain enabled, but revoked merchant memory
            # must not come back from the short recovery window later.
            for entry in self._retired_markers.values():
                entry.stock = None
                entry.merchant_created = False
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
            self._unreadable_since.clear()
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
            if not map_surface_enabled:
                poll_kwargs["full_map_viewport_enabled"] = False
            frame = client.poll(**poll_kwargs)
        except FullMapNotReadyError as exc:
            self._note_poll_problem(exc)
            self._completion_pending.clear()
            self._unreadable_since.clear()
            # Lazy FullMap initialization and incomplete stage identity are
            # waiting states. Keep the ledger/handle, hide stale geometry, and
            # retry on the next UI tick without advancing lifecycle checks.
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
        except Exception as exc:
            self._note_poll_problem(exc)
            self._completion_pending.clear()
            self._unreadable_since.clear()
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

        if self._poll_problem is not None:
            self._event("poll.recovered", previous=self._poll_problem, markers=len(self._markers))
            self._poll_problem = None

        # Keep instance identity separate from the optional seed sample. The
        # tracker (unlike a replaced memory client) survives a reconnect.
        # Older adapters without a structural scope retain their map_id contract.
        scope = frame.map_scope if frame.map_scope is not None else frame.map_id
        scope_changed = scope != self._map_scope
        seed_changed = (
            frame.map_seed is not None
            and self._last_valid_seed is not None
            and frame.map_seed != self._last_valid_seed
        )
        if not scope_changed and frame.map_seed is None:
            # Keep public identity stable too (manual gestures and stock use it).
            # Never relabel a capture belonging to another map.
            capture = frame.merchant_stock_capture
            if capture is not None:
                capture = (
                    replace(capture, map_id=self._map_id)
                    if capture.map_id == frame.map_id else None
                )
            frame = replace(
                frame, map_id=self._map_id, merchant_stock_capture=capture
            )
        if scope_changed or seed_changed:
            if self._map_scope is not None:
                self._event(
                    "scope.reset", old_scope=self._map_scope, new_scope=scope,
                    old_seed=self._last_valid_seed, new_seed=frame.map_seed,
                    markers=len(self._markers), retired=len(self._retired_markers),
                )
            self._markers.clear()
            self._automatic_by_object.clear()
            self._automatic_identity_by_object.clear()
            self._clear_lifecycle_recovery()
            self._lifecycle_schedule.clear()
            self._lifecycle_serial = 0
            self._merchant_stocks.clear()
            self._merchant_created_objects.clear()
        elif frame.map_id != self._map_id:
            # The first successful seed enriches identity, not map lifetime.
            # Keep stock attached without inventing its missing seed provenance.
            self._merchant_stocks = {
                ptr: replace(stock, map_id=frame.map_id)
                for ptr, stock in self._merchant_stocks.items()
            }
            for entry in self._retired_markers.values():
                if entry.stock is not None:
                    entry.stock = replace(entry.stock, map_id=frame.map_id)
        if scope_changed:
            self._last_valid_seed = None
        if frame.map_seed is not None:
            self._last_valid_seed = frame.map_seed
        self._map_scope = scope
        self._map_id = frame.map_id

        if not heavy_reads_enabled:
            self._completion_pending.clear()
            self._unreadable_since.clear()
            self._native_by_object.clear()
            self._lifecycle_failed.clear()
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
            for cache in (self._completion_pending, self._unreadable_since, self._native_by_object):
                for ptr in tuple(cache):
                    if ptr not in self._automatic_by_object:
                        cache.pop(ptr, None)
            self._lifecycle_failed.intersection_update(self._automatic_by_object)
            for object_ptr, marker_id in tuple(self._automatic_by_object.items()):
                if not self._lifecycle_check_due(object_ptr, marker_id, frame, automatic_now):
                    continue
                identity = self._automatic_identity_by_object.get(object_ptr)
                try:
                    sample = self._read_lifecycle(client, object_ptr, identity)
                except Exception as exc:
                    # Unknown interrupts confirmation; a failed read never
                    # counts as another observation of completion.
                    self._completion_pending.pop(object_ptr, None)
                    if object_ptr not in self._lifecycle_failed:
                        self._event("activity.unknown", object_ptr=object_ptr, error=str(exc))
                    self._lifecycle_failed.add(object_ptr)
                    marker = self._markers.get(marker_id)
                    if marker is not None and marker.uses_remaining is not None:
                        self._markers[marker_id] = replace(marker, uses_remaining=None)
                    if isinstance(exc, MemoryReadError):
                        unreadable = self._unreadable_since.get(object_ptr)
                        if (unreadable is None or automatic_now - unreadable.last_at
                                > self.UNREADABLE_MAX_GAP_SECONDS):
                            unreadable = _UnreadableMarker(automatic_now, automatic_now, 1)
                            self._unreadable_since[object_ptr] = unreadable
                        else:
                            unreadable.last_at = automatic_now
                            unreadable.failures += 1
                        if (unreadable.failures >= self.UNREADABLE_MIN_FAILURES
                                and automatic_now - unreadable.first_at + 1e-9
                                >= self.UNREADABLE_HIDE_SECONDS):
                            # The map itself was read successfully. Hide only this
                            # persistently unreadable object, while retaining a
                            # bounded chance to recover its proven identity.
                            self._retire_automatic(
                                object_ptr, automatic_now, reason="unreadable",
                                recovery_seconds=self.UNREADABLE_RECOVERY_SECONDS,
                            )
                    else:
                        self._unreadable_since.pop(object_ptr, None)
                    continue
                self._lifecycle_failed.discard(object_ptr)
                self._unreadable_since.pop(object_ptr, None)
                native = self._native_by_object.get(object_ptr, 0)
                if not sample.identity_valid or (
                    native and sample.native_ptr and sample.native_ptr != native
                ):
                    self._remove_automatic(object_ptr, reason="identity_lost")
                    continue
                marker = self._markers.get(marker_id)
                if marker is not None and marker.uses_remaining != sample.uses_remaining:
                    self._markers[marker_id] = replace(marker, uses_remaining=sample.uses_remaining)
                if sample.active:
                    if object_ptr in self._completion_pending:
                        self._event("activity.confirmation_cancelled", object_ptr=object_ptr)
                    self._completion_pending.pop(object_ptr, None)
                    if sample.native_ptr:
                        self._native_by_object[object_ptr] = sample.native_ptr
                    continue
                first = self._completion_pending.get(object_ptr)
                if first is None:
                    self._completion_pending[object_ptr] = automatic_now
                    self._event("activity.completion_pending", object_ptr=object_ptr)
                elif automatic_now - first + 1e-9 >= self.COMPLETION_CONFIRM_SECONDS:
                    self._retire_automatic(object_ptr, automatic_now)
            self._recover_retired(client, automatic_now)

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
                    uses_remaining=detected.uses_remaining,
                )
                self._retired_markers.pop(detected.object_ptr, None)
                if detected.native_ptr:
                    self._native_by_object[detected.object_ptr] = detected.native_ptr
                self._automatic_by_object[detected.object_ptr] = marker_id
                self._automatic_identity_by_object[detected.object_ptr] = (
                    detected.class_ptr,
                    detected.class_name,
                )

        capture = frame.merchant_stock_capture if merchant_enabled else None
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
                    self._retired_markers.pop(object_ptr, None)
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
                # Prices are visit snapshots too: without a new capture, keep
                # the last displayed values instead of recalculating them.
                self._merchant_stocks[object_ptr] = capture
                self._merchant_created_objects.add(object_ptr)

        self._snapshot = MapMarkerSnapshot(
            map_id=frame.map_id,
            map_read_succeeded=True,
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

    @staticmethod
    def _event(event: str, **fields) -> None:
        # Diagnostics must not become another reason to lose the whole widget.
        try:
            log_runtime_event(f"map_marker.{event}", **fields)
        except Exception:
            pass

    def _note_poll_problem(self, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        now = self._clock()
        if self._poll_problem is None or now >= self._next_problem_log_at:
            self._event("poll.waiting", error=detail, markers=len(self._markers))
            self._next_problem_log_at = now + 30.0
        self._poll_problem = detail

    def _clear_lifecycle_recovery(self) -> None:
        self._completion_pending.clear()
        self._unreadable_since.clear()
        self._retired_markers.clear()
        self._native_by_object.clear()
        self._lifecycle_failed.clear()

    @staticmethod
    def _read_lifecycle(
        client, object_ptr: int, identity: tuple[int, str] | None,
    ) -> ActivityRead:
        active = client.activity_is_active(
            object_ptr,
            expected_class_ptr=identity[0] if identity is not None else None,
            expected_class_name=identity[1] if identity is not None else None,
        )
        reader = getattr(client, "last_activity_read", None)
        sample = reader(object_ptr) if callable(reader) else None
        if isinstance(sample, ActivityRead) and sample.object_ptr == object_ptr:
            return sample
        # Older adapters cannot prove native identity, so they cannot safely
        # resurrect a completed marker. Preserve their boolean/count API.
        uses_reader = getattr(client, "last_microwave_uses", None)
        uses = (
            uses_reader(object_ptr)
            if identity is not None and identity[1] == "InteractableMicrowave"
            and callable(uses_reader) else None
        )
        return ActivityRead(object_ptr, bool(active), True, uses_remaining=uses)

    def _remove_automatic(self, object_ptr: int, *, reason: str) -> None:
        marker_id = self._automatic_by_object.pop(object_ptr, None)
        self._automatic_identity_by_object.pop(object_ptr, None)
        self._native_by_object.pop(object_ptr, None)
        self._completion_pending.pop(object_ptr, None)
        self._unreadable_since.pop(object_ptr, None)
        self._lifecycle_failed.discard(object_ptr)
        self._lifecycle_schedule.pop(object_ptr, None)
        self._markers.pop(marker_id, None)
        self._merchant_stocks.pop(object_ptr, None)
        self._merchant_created_objects.discard(object_ptr)
        self._event("activity.removed", object_ptr=object_ptr, reason=reason,
                    markers=len(self._markers))

    def _retire_automatic(
        self, object_ptr: int, now: float, *, reason: str = "completed",
        recovery_seconds: float = RECOVERY_WINDOW_SECONDS,
    ) -> None:
        marker = self._markers.get(self._automatic_by_object.get(object_ptr))
        identity = self._automatic_identity_by_object.get(object_ptr)
        native = self._native_by_object.get(object_ptr, 0)
        if marker is not None and identity is not None and native:
            if len(self._retired_markers) >= self.MAX_RETIRED_MARKERS:
                self._retired_markers.pop(next(iter(self._retired_markers)))
            self._retired_markers[object_ptr] = _RetiredMarker(
                marker, identity, native, self._merchant_stocks.get(object_ptr),
                object_ptr in self._merchant_created_objects,
                now + recovery_seconds, now + self.RECOVERY_CHECK_INTERVAL,
            )
        self._remove_automatic(object_ptr, reason=reason)

    def _recover_retired(self, client, now: float) -> None:
        # Bounded oldest-deadline-first checks avoid bursts and starvation.
        budget = self.RECOVERY_CHECK_BUDGET
        for object_ptr, entry in sorted(
            tuple(self._retired_markers.items()), key=lambda pair: pair[1].next_check_at
        ):
            if now >= entry.expires_at:
                self._retired_markers.pop(object_ptr, None)
                continue
            if budget <= 0 or now + 1e-9 < entry.next_check_at:
                continue
            budget -= 1
            entry.next_check_at = now + self.RECOVERY_CHECK_INTERVAL
            try:
                sample = self._read_lifecycle(client, object_ptr, entry.identity)
            except Exception:
                continue  # Do not extend the expiry on repeated read failures.
            if not sample.identity_valid or sample.native_ptr != entry.native_ptr:
                self._retired_markers.pop(object_ptr, None)
                self._event("activity.recovery_rejected", object_ptr=object_ptr)
                continue
            if not sample.active:
                continue
            marker = replace(entry.marker, uses_remaining=sample.uses_remaining)
            self._replace_nearby_manual_marker(marker.action_id, marker.world_x, marker.world_z)
            self._markers[marker.marker_id] = marker
            self._automatic_by_object[object_ptr] = marker.marker_id
            self._automatic_identity_by_object[object_ptr] = entry.identity
            self._native_by_object[object_ptr] = entry.native_ptr
            if entry.stock is not None:
                self._merchant_stocks[object_ptr] = entry.stock
            if entry.merchant_created:
                self._merchant_created_objects.add(object_ptr)
            self._retired_markers.pop(object_ptr, None)
            self._event("activity.restored", object_ptr=object_ptr, markers=len(self._markers))

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
            or object_ptr in self._completion_pending
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
