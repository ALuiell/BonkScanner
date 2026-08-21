from __future__ import annotations

import struct
import unittest

from app.map_marker_hotkeys import MapMarkerHotkeyController
from app.map_marker_tracker import MapMarkerTracker
from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerSnapshot,
    MapViewport,
    action_id_for_interactable,
    build_marker_palette,
    project_world_to_map,
    unproject_map_to_world,
)
from infra.map_marker_input import WindowsMapMarkerInput, virtual_key_for_token
from infra.memory.map_marker_client import (
    DetectedMapActivity,
    FullMapNotReadyError,
    MapMarkerMemoryClient,
    MapMemoryFrame,
)
from infra.memory.reader import MemoryReadError


class FakeMarkerClient:
    def __init__(self, frames: list[MapMemoryFrame]) -> None:
        self.frames = list(frames)
        self.active: dict[int, bool] = {}
        self.automatic_discovery_values: list[bool] = []
        self.automatic_sample_values: list[bool] = []
        self.active_checks: list[int] = []
        self.closed = False

    def poll(
        self,
        *,
        client_height: int,
        client_width: int | None = None,
        display_scale: float = 1.0,
        automatic_discovery: bool = False,
        sample_automatic_discovery: bool = True,
    ) -> MapMemoryFrame:
        _ = client_height, client_width, display_scale
        self.automatic_discovery_values.append(bool(automatic_discovery))
        self.automatic_sample_values.append(bool(sample_automatic_discovery))
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0]

    def activity_is_active(self, object_ptr: int) -> bool:
        self.active_checks.append(object_ptr)
        return self.active.get(object_ptr, True)

    def close(self) -> None:
        self.closed = True


class FakeInput:
    def __init__(self) -> None:
        self.pressed: set[str] = set()

    def is_pressed(self, binding: str) -> bool:
        return binding in self.pressed


class FakeLifecycleMemory:
    def __init__(self) -> None:
        self.ptrs: dict[int, int] = {}
        self.ptr_reads: list[int] = []
        self.i32s: dict[int, int] = {}
        self.u8s: dict[int, int] = {}
        self.floats: dict[int, float] = {}
        self.blobs: dict[int, bytes] = {}

    def read_ptr(self, address: int) -> int:
        self.ptr_reads.append(address)
        return self.ptrs.get(address, 0)

    def read_i32(self, address: int) -> int:
        return self.i32s.get(address, 0)

    def read_u8(self, address: int) -> int:
        return self.u8s.get(address, 0)

    def read_float(self, address: int) -> float:
        return self.floats.get(address, 0.0)

    def read_bytes(self, address: int, size: int) -> bytes:
        return self.blobs.get(address, b"\0" * size)

    def module_base_address(self, _module_name: str) -> int:
        return 0x100000


class MapMarkerProjectionTests(unittest.TestCase):
    def test_live_calibration_projects_to_recorded_player_arrow(self) -> None:
        viewport = MapViewport(33.333296, 286.666654, 1000.00003, 1000.00003)
        point = project_world_to_map(
            -72.762466,
            -246.898972,
            world_size=600.0,
            viewport=viewport,
        )
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 412.0625, places=2)
        self.assertAlmostEqual(point[1], 1198.1650, places=2)

    def test_projection_round_trip_and_bounds(self) -> None:
        viewport = MapViewport(100.0, 200.0, 900.0, 900.0)
        point = project_world_to_map(
            123.5, -87.25, world_size=600.0, viewport=viewport
        )
        self.assertIsNotNone(point)
        world = unproject_map_to_world(
            *point, world_size=600.0, viewport=viewport
        )
        self.assertAlmostEqual(world[0], 123.5)
        self.assertAlmostEqual(world[1], -87.25)
        self.assertIsNone(
            unproject_map_to_world(99, 200, world_size=600, viewport=viewport)
        )

    def test_interactable_action_mapping(self) -> None:
        self.assertEqual(
            action_id_for_interactable("InteractableMicrowave", 1),
            "microwave_blue",
        )
        self.assertEqual(
            action_id_for_interactable("InteractableShadyGuy", 3),
            "shady_guy_gold",
        )
        self.assertEqual(
            action_id_for_interactable("InteractableShrineCursed"),
            "boss_curse",
        )
        self.assertIsNone(action_id_for_interactable("InteractableChest"))
        self.assertIsNone(action_id_for_interactable("InteractableEgg"))
        self.assertIsNone(action_id_for_interactable("InteractableSusBush"))

    def test_egg_and_sus_bush_are_explicitly_manual_only(self) -> None:
        self.assertTrue(MAP_MARKER_ACTION_BY_ID["egg"].manual_only)
        self.assertTrue(MAP_MARKER_ACTION_BY_ID["sus_bush"].manual_only)
        self.assertFalse(MAP_MARKER_ACTION_BY_ID["challenge_shrine"].manual_only)

    def test_light_marker_fills_use_dark_pictograms(self) -> None:
        self.assertEqual(
            MAP_MARKER_ACTION_BY_ID["microwave_white"].icon_name,
            "microwave_dark",
        )
        self.assertEqual(
            MAP_MARKER_ACTION_BY_ID["shady_guy_white"].icon_name,
            "shady_guy_dark",
        )
        self.assertEqual(MAP_MARKER_ACTION_BY_ID["moai"].icon_name, "moai_dark")
        self.assertEqual(
            MAP_MARKER_ACTION_BY_ID["microwave_white"].settings_icon_name,
            "microwave",
        )
        self.assertEqual(
            MAP_MARKER_ACTION_BY_ID["shady_guy_white"].settings_icon_name,
            "shady_guy",
        )
        self.assertEqual(
            MAP_MARKER_ACTION_BY_ID["moai"].settings_icon_name,
            "moai",
        )

    def test_complete_palette_fits_small_full_map_at_large_scale(self) -> None:
        viewport = MapViewport(20.0, 30.0, 800.0, 800.0)
        palette = build_marker_palette(
            400.0,
            400.0,
            viewport=viewport,
            scale=2.0,
        )
        self.assertEqual(len(palette.rows), 14)
        self.assertGreaterEqual(palette.rows[0].top, viewport.top)
        self.assertLessEqual(
            palette.rows[-1].top + palette.rows[-1].height,
            viewport.bottom,
        )


class MapMarkerTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.viewport = MapViewport(0, 0, 600, 600)

    def frame(self, *, map_id=1, activity=None, open=True) -> MapMemoryFrame:
        return MapMemoryFrame(
            map_id=map_id,
            map_open=open,
            world_size=600.0,
            viewport=self.viewport if open else None,
            current_activity=activity,
        )

    def test_automatic_marker_is_added_removed_and_reset_with_map(self) -> None:
        activity = DetectedMapActivity(
            object_ptr=0xABC,
            class_ptr=0x100,
            class_name="InteractableShrineMoai",
            action_id="moai",
            world_x=20.0,
            world_z=-30.0,
        )
        client = FakeMarkerClient(
            [self.frame(activity=activity), self.frame(), self.frame(map_id=2)]
        )
        tracker = MapMarkerTracker(
            "game",
            client_factory=lambda _name: client,
            automatic_scan_interval=0.0,
        )

        first = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(len(first.markers), 1)
        self.assertEqual(first.markers[0].action_id, "moai")

        client.active[activity.object_ptr] = False
        second = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(second.markers, ())

        tracker.place_manual_marker(
            "boss_curse", screen_x=300, screen_y=300
        )
        self.assertEqual(len(tracker.snapshot.markers), 1)
        third = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(third.map_id, 2)
        self.assertEqual(third.markers, ())

    def test_manual_marker_toggles_and_is_replaced_by_nearby_automatic(self) -> None:
        client = FakeMarkerClient([self.frame()])
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)
        tracker.tick(client_height=600)

        self.assertTrue(
            tracker.place_manual_marker(
                "microwave_white", screen_x=300, screen_y=300
            )
        )
        self.assertEqual(len(tracker.snapshot.markers), 1)
        self.assertTrue(
            tracker.place_manual_marker(
                "microwave_white", screen_x=306, screen_y=300
            )
        )
        self.assertEqual(tracker.snapshot.markers, ())

        tracker.place_manual_marker(
            "microwave_blue", screen_x=300, screen_y=300
        )
        client.frames[0] = self.frame(
            activity=DetectedMapActivity(
                object_ptr=0xDEF,
                class_ptr=0x101,
                class_name="InteractableMicrowave",
                action_id="microwave_white",
                world_x=5.0,
                world_z=0.0,
            )
        )
        snapshot = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(len(snapshot.markers), 1)
        self.assertEqual(snapshot.markers[0].source, "automatic")

    def test_disabled_automatic_discovery_ignores_and_clears_auto_markers(self) -> None:
        activity = DetectedMapActivity(
            object_ptr=0xABC,
            class_ptr=0x100,
            class_name="InteractableShrineMoai",
            action_id="moai",
            world_x=20.0,
            world_z=-30.0,
        )
        client = FakeMarkerClient([self.frame(activity=activity)])
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)

        disabled = tracker.tick(client_height=600)
        self.assertEqual(disabled.markers, ())
        self.assertEqual(client.automatic_discovery_values, [False])

        enabled = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(len(enabled.markers), 1)
        tracker.place_manual_marker(
            "boss_curse", screen_x=300, screen_y=300
        )

        disabled_again = tracker.tick(client_height=600)
        self.assertEqual(
            [marker.source for marker in disabled_again.markers],
            ["manual"],
        )
        self.assertEqual(
            client.automatic_discovery_values,
            [False, True, False],
        )
        self.assertEqual(client.active_checks, [])

    def test_automatic_object_reads_are_throttled_to_100_ms(self) -> None:
        now = [10.0]
        activity = DetectedMapActivity(
            object_ptr=0xABC,
            class_ptr=0x100,
            class_name="InteractableShrineMoai",
            action_id="moai",
            world_x=20.0,
            world_z=-30.0,
        )
        client = FakeMarkerClient(
            [self.frame(activity=activity), self.frame()]
        )
        tracker = MapMarkerTracker(
            "game",
            client_factory=lambda _name: client,
            clock=lambda: now[0],
            automatic_scan_interval=0.1,
        )

        first = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(len(first.markers), 1)
        client.active[activity.object_ptr] = False

        for elapsed in (0.025, 0.050, 0.075):
            now[0] = 10.0 + elapsed
            snapshot = tracker.tick(
                client_height=600,
                automatic_discovery=True,
            )
            self.assertEqual(len(snapshot.markers), 1)

        now[0] = 10.1
        removed = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(removed.markers, ())
        self.assertEqual(client.active_checks, [activity.object_ptr])
        self.assertEqual(
            client.automatic_sample_values,
            [True, False, False, False, True],
        )
        self.assertEqual(client.automatic_discovery_values, [True] * 5)
        self.assertAlmostEqual(tracker._next_automatic_scan_at, 10.2)

    def test_full_map_wait_keeps_client_and_recovers_on_the_next_tick(self) -> None:
        frame = self.frame(open=True)

        class WaitingThenReadyClient(FakeMarkerClient):
            def __init__(self) -> None:
                super().__init__([frame])
                self.poll_count = 0

            def poll(self, **kwargs) -> MapMemoryFrame:
                self.poll_count += 1
                if self.poll_count == 1:
                    raise FullMapNotReadyError("FullMap is still lazy")
                return super().poll(**kwargs)

        client = WaitingThenReadyClient()
        factory_calls = []
        tracker = MapMarkerTracker(
            "game",
            client_factory=lambda process_name: factory_calls.append(process_name)
            or client,
        )

        waiting = tracker.tick(client_height=600)
        self.assertFalse(waiting.map_open)
        self.assertFalse(client.closed)

        recovered = tracker.tick(client_height=600)
        self.assertTrue(recovered.map_open)
        self.assertEqual(factory_calls, ["game"])
        self.assertFalse(client.closed)


class MapMarkerGestureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 10.0
        self.input = FakeInput()
        self.controller = MapMarkerHotkeyController(
            self.input,
            clock=lambda: self.now,
            hold_seconds=0.35,
        )
        self.snapshot = MapMarkerSnapshot(
            map_id=4,
            map_open=True,
            world_size=600,
            viewport=MapViewport(0, 0, 800, 800),
        )
        self.bindings = [{"input": "f8", "action": "challenge_shrine"}]

    def test_quick_tap_places_assigned_marker_at_press_position(self) -> None:
        self.input.pressed.add("f8")
        self.controller.poll(
            self.bindings, self.snapshot, cursor_x=200, cursor_y=300
        )
        self.now += 0.1
        self.input.pressed.clear()
        update = self.controller.poll(
            self.bindings, self.snapshot, cursor_x=500, cursor_y=600
        )
        self.assertEqual(update.placement, ("challenge_shrine", 200.0, 300.0))
        self.assertIsNone(update.palette)

    def test_hold_opens_palette_and_release_uses_hovered_action(self) -> None:
        self.input.pressed.add("f8")
        self.controller.poll(
            self.bindings, self.snapshot, cursor_x=250, cursor_y=400
        )
        self.now += 0.4
        opened = self.controller.poll(
            self.bindings, self.snapshot, cursor_x=250, cursor_y=400
        )
        self.assertIsNotNone(opened.palette)
        boss_row = next(
            row for row in opened.palette.rows if row.action_id == "boss_curse"
        )
        hovered = self.controller.poll(
            self.bindings,
            self.snapshot,
            cursor_x=boss_row.left + boss_row.width / 2,
            cursor_y=boss_row.top + boss_row.height / 2,
        )
        self.assertEqual(hovered.palette.selected_action_id, "boss_curse")
        self.input.pressed.clear()
        released = self.controller.poll(
            self.bindings, self.snapshot, cursor_x=0, cursor_y=0
        )
        self.assertEqual(released.placement, ("boss_curse", 250.0, 400.0))

    def test_hold_release_outside_palette_cancels(self) -> None:
        self.input.pressed.add("f8")
        self.controller.poll(
            self.bindings, self.snapshot, cursor_x=250, cursor_y=400
        )
        self.now += 0.4
        opened = self.controller.poll(
            self.bindings, self.snapshot, cursor_x=250, cursor_y=400
        )
        self.assertIsNotNone(opened.palette)
        self.assertIsNone(opened.palette.selected_action_id)

        self.input.pressed.clear()
        released = self.controller.poll(
            self.bindings, self.snapshot, cursor_x=0, cursor_y=0
        )
        self.assertIsNone(released.placement)
        self.assertIsNone(released.palette)


class MapMarkerLifecycleTests(unittest.TestCase):
    def client(self, class_name: str, *, object_ptr: int = 0x1000):
        memory = FakeLifecycleMemory()
        class_ptr = 0x2000
        memory.ptrs[object_ptr] = class_ptr
        memory.ptrs[object_ptr + MapMarkerMemoryClient.MANAGED_NATIVE_OFFSET] = 0x3000
        client = MapMarkerMemoryClient(memory=memory)
        client._tracked_classes = {object_ptr: (class_ptr, class_name)}
        return client, memory, object_ptr

    def test_done_flag_finishes_shrines_and_shady_guy(self) -> None:
        client, memory, obj = self.client("InteractableShrineChallenge")
        self.assertTrue(client.activity_is_active(obj))
        memory.u8s[obj + client.SHRINE_DONE_OFFSET] = 1
        self.assertFalse(client.activity_is_active(obj))

        client, memory, obj = self.client("InteractableShadyGuy")
        memory.u8s[obj + client.SHADY_DONE_OFFSET] = 1
        self.assertFalse(client.activity_is_active(obj))

    def test_microwave_stays_until_last_item_is_collected(self) -> None:
        client, memory, obj = self.client("InteractableMicrowave")
        memory.i32s[obj + client.MICROWAVE_USES_LEFT_OFFSET] = 0
        memory.u8s[obj + client.MICROWAVE_IS_COOKING_OFFSET] = 1
        self.assertTrue(client.activity_is_active(obj))
        memory.u8s[obj + client.MICROWAVE_IS_COOKING_OFFSET] = 0
        memory.u8s[obj + client.MICROWAVE_HAS_ITEM_OFFSET] = 1
        self.assertTrue(client.activity_is_active(obj))
        memory.u8s[obj + client.MICROWAVE_HAS_ITEM_OFFSET] = 0
        self.assertFalse(client.activity_is_active(obj))

    def test_virtual_key_translation_covers_keyboard_and_mouse(self) -> None:
        self.assertEqual(virtual_key_for_token("f24"), 0x87)
        self.assertEqual(virtual_key_for_token("mouse5"), 0x06)
        self.assertEqual(virtual_key_for_token("a"), ord("A"))

        class FakeUser32:
            pressed = {0x06, 0x11, ord("G"), 0x77}

            def GetAsyncKeyState(self, virtual_key: int) -> int:
                return 0x8000 if virtual_key in self.pressed else 0

        input_state = WindowsMapMarkerInput(FakeUser32())
        self.assertTrue(input_state.is_pressed("mouse5"))
        self.assertTrue(input_state.is_pressed("ctrl+g"))
        self.assertTrue(input_state.is_pressed("f8"))
        self.assertFalse(input_state.is_pressed("f9"))

    def test_lazy_full_map_type_info_recovers_without_invalid_dereference(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        type_info_slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET
        lazy_token = 0x2000A397
        memory.ptrs[type_info_slot] = lazy_token

        with self.assertRaises(FullMapNotReadyError):
            client.poll(client_height=600)
        self.assertNotIn(
            lazy_token + client.CLASS_STATIC_FIELDS_OFFSET,
            memory.ptr_reads,
        )

        type_info = 0x200000
        static_fields = 0x210000
        delegate = 0x220000
        full_map = 0x700000
        memory.ptrs[type_info_slot] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[static_fields] = delegate
        memory.ptrs[delegate + client.MULTICAST_DELEGATES_OFFSET] = 0
        memory.ptrs[delegate + client.DELEGATE_TARGET_OFFSET] = full_map
        memory.floats[full_map + client.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        client._is_live_full_map = lambda candidate: candidate == full_map
        client._resolve_player = lambda: 0x400000
        client._resolve_stage_scope = lambda: (0x500000, 1)

        frame = client.poll(client_height=600)
        self.assertEqual(frame.world_size, 600.0)
        self.assertFalse(frame.map_open)

    def test_skipped_automatic_sample_preserves_cached_detector_state(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        detector = 0x710000
        object_ptr = 0x720000
        tracked = (0x730000, "InteractableShrineMoai")
        client._full_map_ptr = full_map
        client._detector_ptr = detector
        client._tracked_classes[object_ptr] = tracked
        client._resolve_full_map = lambda: full_map
        client._resolve_player = lambda: 0x400000
        client._resolve_stage_scope = lambda: (0, -1)

        def unexpected_detector_read(_player: int) -> int:
            raise AssertionError("automatic detector was read before 100 ms elapsed")

        client._resolve_detector = unexpected_detector_read
        memory.floats[full_map + client.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0

        frame = client.poll(
            client_height=600,
            automatic_discovery=True,
            sample_automatic_discovery=False,
        )

        self.assertIsNone(frame.current_activity)
        self.assertEqual(client._detector_ptr, detector)
        self.assertEqual(client._tracked_classes[object_ptr], tracked)

    def test_large_full_map_delegate_array_resolves_live_tail(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        type_info = 0x200000
        static_fields = 0x210000
        delegate = 0x220000
        delegates = 0x230000
        live_entry = 0x240000
        full_map = 0x700000
        count = 557
        type_info_slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET
        last_entry_slot = delegates + client.ARRAY_DATA_OFFSET + (count - 1) * 8

        memory.ptrs[type_info_slot] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[static_fields] = delegate
        memory.ptrs[delegate + client.MULTICAST_DELEGATES_OFFSET] = delegates
        memory.i32s[delegates + client.ARRAY_LENGTH_OFFSET] = count
        memory.ptrs[last_entry_slot] = live_entry
        memory.ptrs[live_entry + client.DELEGATE_TARGET_OFFSET] = full_map
        client._is_live_full_map = lambda candidate: candidate == full_map

        self.assertEqual(client._resolve_full_map(), full_map)
        self.assertIn(last_entry_slot, memory.ptr_reads)
        self.assertNotIn(delegates + client.ARRAY_DATA_OFFSET, memory.ptr_reads)

    def test_large_full_map_delegate_array_scans_only_bounded_tail(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        type_info = 0x200000
        static_fields = 0x210000
        delegate = 0x220000
        delegates = 0x230000
        count = 10_000
        type_info_slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET

        memory.ptrs[type_info_slot] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[static_fields] = delegate
        memory.ptrs[delegate + client.MULTICAST_DELEGATES_OFFSET] = delegates
        memory.i32s[delegates + client.ARRAY_LENGTH_OFFSET] = count

        self.assertEqual(client._resolve_full_map(), 0)

        first_slot = delegates + client.ARRAY_DATA_OFFSET
        end_slot = first_slot + count * 8
        array_reads = [
            address
            for address in memory.ptr_reads
            if first_slot <= address < end_slot
        ]
        self.assertEqual(len(array_reads), client.MAX_DELEGATES_TO_SCAN)
        self.assertEqual(
            min(array_reads),
            first_slot + (count - client.MAX_DELEGATES_TO_SCAN) * 8,
        )
        self.assertEqual(max(array_reads), first_slot + (count - 1) * 8)

    def test_impossible_full_map_delegate_array_length_still_fails_closed(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        type_info = 0x200000
        static_fields = 0x210000
        delegate = 0x220000
        delegates = 0x230000
        type_info_slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET

        memory.ptrs[type_info_slot] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[static_fields] = delegate
        memory.ptrs[delegate + client.MULTICAST_DELEGATES_OFFSET] = delegates
        memory.i32s[delegates + client.ARRAY_LENGTH_OFFSET] = (
            client.MAX_DELEGATE_ARRAY_LENGTH + 1
        )

        with self.assertRaisesRegex(MemoryReadError, "delegate count is invalid"):
            client._resolve_full_map()

    def test_full_map_viewport_is_converted_from_native_to_qt_pixels(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        transform = 0x710000
        native = 0x720000
        memory.ptrs[full_map + client.FULL_MAP_DISPLAY_TRANSFORM_OFFSET] = transform
        memory.ptrs[transform + client.MANAGED_NATIVE_OFFSET] = native
        memory.blobs[native + client.RECT_TRANSFORM_RECT_OFFSET] = struct.pack(
            "<4f", 0.0, -375.0, 750.0, 750.0
        )

        client._transform_point = lambda _transform, point: (
            33.3333 + point[0] * (4.0 / 3.0),
            653.3333 + point[1] * (4.0 / 3.0),
            0.0,
        )
        viewport = client._read_viewport(full_map, 2560, 1440, 1.25)
        self.assertAlmostEqual(viewport.left, 26.6666, places=3)
        self.assertAlmostEqual(viewport.top, 229.3334, places=3)
        self.assertAlmostEqual(viewport.width, 800.0, places=3)
        self.assertAlmostEqual(viewport.height, 800.0, places=3)

    def test_full_map_viewport_tracks_layout_changes_for_same_map_and_window(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        transform = 0x710000
        native = 0x720000
        memory.ptrs[full_map + client.FULL_MAP_DISPLAY_TRANSFORM_OFFSET] = transform
        memory.ptrs[transform + client.MANAGED_NATIVE_OFFSET] = native
        memory.blobs[native + client.RECT_TRANSFORM_RECT_OFFSET] = struct.pack(
            "<4f", 0.0, 0.0, 800.0, 800.0
        )
        layout = {"left": 300.0, "bottom": 100.0, "scale": 1.0}
        client._transform_point = lambda _transform, point: (
            layout["left"] + point[0] * layout["scale"],
            layout["bottom"] + point[1] * layout["scale"],
            0.0,
        )

        tab_viewport = client._read_viewport(full_map, 2560, 1440, 1.0)
        layout.update(left=20.0, bottom=20.0, scale=1.7)
        pause_viewport = client._read_viewport(full_map, 2560, 1440, 1.0)

        self.assertEqual(tab_viewport, MapViewport(300.0, 540.0, 800.0, 800.0))
        self.assertEqual(pause_viewport, MapViewport(20.0, 60.0, 1360.0, 1360.0))
        self.assertNotEqual(tab_viewport, pause_viewport)

    def test_pause_map_uses_its_own_map_render_viewport(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        native = 0x730000
        memory.blobs[native + client.RECT_TRANSFORM_RECT_OFFSET] = struct.pack(
            "<4f", -440.0, -445.0, 880.0, 890.0
        )
        client._resolve_pause_map_render_native_transform = lambda: native
        client._transform_point_native = lambda _native, point: (
            1280.0 + point[0] * (4.0 / 3.0),
            680.0 + point[1] * (4.0 / 3.0),
            0.0,
        )

        viewport = client._read_viewport(full_map, 2560, 1440, 1.25)

        self.assertAlmostEqual(viewport.left, 554.6667, places=3)
        self.assertAlmostEqual(viewport.top, 133.3333, places=3)
        self.assertAlmostEqual(viewport.width, 938.6667, places=3)
        self.assertAlmostEqual(viewport.height, 949.3333, places=3)

    def test_pause_map_render_is_selected_only_for_current_pause_map(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        type_info = 0x200000
        static_fields = 0x210000
        ui_manager = 0x220000
        pause_ui = 0x230000
        map_object = 0x240000
        root_native = 0x250000
        render_native = 0x260000
        memory.ptrs[
            client._module_base + client.UI_MANAGER_TYPE_INFO_OFFSET
        ] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[static_fields + client.UI_MANAGER_INSTANCE_OFFSET] = ui_manager
        memory.ptrs[ui_manager + client.UI_MANAGER_PAUSE_OFFSET] = pause_ui
        memory.ptrs[pause_ui + client.PAUSE_UI_MAP_OFFSET] = map_object
        memory.ptrs[pause_ui + client.PAUSE_UI_CURRENT_OFFSET] = map_object
        client._game_object_transform_native = lambda _object: root_native
        client._find_descendant_native_transform = (
            lambda _root, _name: render_native
        )

        self.assertEqual(
            client._resolve_pause_map_render_native_transform(),
            render_native,
        )

        memory.ptrs[pause_ui + client.PAUSE_UI_CURRENT_OFFSET] = 0xDEAD
        self.assertEqual(client._resolve_pause_map_render_native_transform(), 0)

    def test_new_player_instance_invalidates_detector_and_tracked_objects(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        client._tracked_classes = {0xDEAD: (0xBEEF, "InteractableShrineMoai")}

        type_info = 0x200000
        static_fields = 0x300000
        first_player = 0x400000
        first_input = 0x410000
        first_detector = 0x420000
        memory.ptrs[client._module_base + client.MY_PLAYER_TYPE_INFO_OFFSET] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[static_fields + client.MY_PLAYER_INSTANCE_OFFSET] = first_player
        memory.ptrs[first_player + client.PLAYER_INPUT_OFFSET] = first_input
        memory.ptrs[first_input + client.DETECT_INTERACTABLES_OFFSET] = first_detector

        self.assertEqual(
            client._resolve_player_and_detector(),
            (first_player, first_detector),
        )
        self.assertEqual(client._tracked_classes, {})

        client._tracked_classes[0xCAFE] = (0xBABE, "InteractableShadyGuy")
        second_player = 0x500000
        second_input = 0x510000
        second_detector = 0x520000
        memory.ptrs[static_fields + client.MY_PLAYER_INSTANCE_OFFSET] = second_player
        memory.ptrs[second_player + client.PLAYER_INPUT_OFFSET] = second_input
        memory.ptrs[second_input + client.DETECT_INTERACTABLES_OFFSET] = second_detector

        self.assertEqual(
            client._resolve_player_and_detector(),
            (second_player, second_detector),
        )
        self.assertEqual(client._tracked_classes, {})

    def test_memory_client_skips_detector_path_when_automatic_is_off(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        memory.floats[
            full_map + client.FULL_MAP_WORLD_SIZE_OFFSET
        ] = 600.0
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        client._resolve_full_map = lambda: full_map
        client._resolve_player = lambda: 0x400000
        client._resolve_stage_scope = lambda: (0x500000, 1)

        def unexpected_detector(_player: int) -> int:
            raise AssertionError("automatic detector path was read while disabled")

        client._resolve_detector = unexpected_detector
        frame = client.poll(client_height=600, automatic_discovery=False)

        self.assertIsNone(frame.current_activity)
        self.assertFalse(frame.map_open)

    def test_stage_scope_uses_current_stage_pointer_and_index(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        type_info = 0x600000
        static_fields = 0x610000
        memory.ptrs[
            client._module_base + client.MAP_CONTROLLER_TYPE_INFO_OFFSET
        ] = type_info
        memory.ptrs[type_info + client.CLASS_STATIC_FIELDS_OFFSET] = static_fields
        memory.ptrs[
            static_fields + client.MAP_CONTROLLER_CURRENT_STAGE_OFFSET
        ] = 0x620000
        memory.i32s[static_fields + client.MAP_CONTROLLER_INDEX_OFFSET] = 1

        self.assertEqual(client._resolve_stage_scope(), (0x620000, 1))

        memory.ptrs[
            static_fields + client.MAP_CONTROLLER_CURRENT_STAGE_OFFSET
        ] = 0x630000
        memory.i32s[static_fields + client.MAP_CONTROLLER_INDEX_OFFSET] = 2
        self.assertEqual(client._resolve_stage_scope(), (0x630000, 2))


if __name__ == "__main__":
    unittest.main()
