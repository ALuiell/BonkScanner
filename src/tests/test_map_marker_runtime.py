from __future__ import annotations

import struct
import unittest
from dataclasses import replace
from unittest.mock import Mock

from app.map_marker_hotkeys import MapMarkerHotkeyController
from app.map_marker_tracker import MapMarkerTracker
from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerSnapshot,
    MapViewport,
    MerchantOffer,
    MerchantStockCapture,
    MinimapProjection,
    WorldMapMarker,
    action_id_for_interactable,
    build_marker_palette,
    map_marker_screen_geometry,
    minimap_marker_screen_geometry,
    project_world_to_minimap,
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
    def __init__(self, frames: list[MapMemoryFrame | Exception]) -> None:
        self.frames = list(frames)
        self.active: dict[int, bool] = {}
        self.automatic_discovery_values: list[bool] = []
        self.automatic_sample_values: list[bool] = []
        self.minimap_values: list[bool] = []
        self.merchant_memory_values: list[bool] = []
        self.merchant_sample_values: list[bool] = []
        self.active_checks: list[int] = []
        self.active_identity_checks: list[tuple[int, int | None, str | None]] = []
        self.closed = False

    def poll(
        self,
        *,
        client_height: int,
        client_width: int | None = None,
        display_scale: float = 1.0,
        automatic_discovery: bool = False,
        sample_automatic_discovery: bool = True,
        minimap_enabled: bool = False,
        merchant_memory_enabled: bool = False,
        sample_merchant_memory: bool = True,
    ) -> MapMemoryFrame:
        _ = client_height, client_width, display_scale
        self.automatic_discovery_values.append(bool(automatic_discovery))
        self.automatic_sample_values.append(bool(sample_automatic_discovery))
        self.minimap_values.append(bool(minimap_enabled))
        self.merchant_memory_values.append(bool(merchant_memory_enabled))
        self.merchant_sample_values.append(bool(sample_merchant_memory))
        frame = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        if isinstance(frame, Exception):
            raise frame
        return replace(
            frame, minimap_projection=frame.minimap_projection if minimap_enabled else None
        )

    def activity_is_active(
        self,
        object_ptr: int,
        *,
        expected_class_ptr: int | None = None,
        expected_class_name: str | None = None,
    ) -> bool:
        self.active_checks.append(object_ptr)
        self.active_identity_checks.append(
            (object_ptr, expected_class_ptr, expected_class_name)
        )
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
        self.byte_reads: list[tuple[int, int]] = []

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
        self.byte_reads.append((address, size))
        if address in self.blobs:
            return self.blobs[address]
        result = bytearray(size)
        for values, fmt in ((self.ptrs, "<Q"), (self.i32s, "<i"),
                            (self.u8s, "<B"), (self.floats, "<f")):
            width = struct.calcsize(fmt)
            for start, value in values.items():
                left, right = max(address, start), min(address + size, start + width)
                if left < right:
                    packed = struct.pack(fmt, value)
                    result[left - address:right - address] = packed[left - start:right - start]
        return bytes(result)

    def module_base_address(self, _module_name: str) -> int:
        return 0x100000


class MapMarkerProjectionTests(unittest.TestCase):
    def test_minimap_projection_rotates_and_hides_out_of_range_markers(self) -> None:
        projection = MinimapProjection(
            visible=True,
            jammed=False,
            content_rect=MapViewport(100.0, 200.0, 220.0, 220.0),
            center_x=210.0,
            center_y=310.0,
            radius=110.0,
            camera_world_x=10.0,
            camera_world_z=20.0,
            camera_right_x=0.0,
            camera_right_z=1.0,
            camera_up_x=-1.0,
            camera_up_z=0.0,
            orthographic_size=110.0,
            aspect=1.0,
        )

        self.assertEqual(
            project_world_to_minimap(10.0, 130.0, projection=projection),
            (320.0, 310.0),
        )
        self.assertIsNone(
            project_world_to_minimap(10.0, 131.0, projection=projection)
        )
        geometry = minimap_marker_screen_geometry(
            10.0, 20.0, projection=projection, scale=1.5
        )
        self.assertEqual(geometry, (210.0, 310.0, 54.0))

        jammed = replace(projection, jammed=True)
        self.assertIsNone(
            project_world_to_minimap(10.0, 20.0, projection=jammed)
        )

    def test_marker_scale_uses_larger_48_pixel_baseline(self) -> None:
        viewport = MapViewport(0.0, 0.0, 600.0, 600.0)
        expected_sizes = {
            0.5: 24.0,
            1.0: 48.0,
            1.7: 82.0,
            3.0: 144.0,
        }
        for scale, expected_size in expected_sizes.items():
            with self.subTest(scale=scale):
                geometry = map_marker_screen_geometry(
                    0.0,
                    0.0,
                    world_size=600.0,
                    viewport=viewport,
                    scale=scale,
                )
                self.assertIsNotNone(geometry)
                self.assertEqual(geometry[2], expected_size)

    def test_edge_marker_keeps_exact_projected_center(self) -> None:
        viewport = MapViewport(20.0, 30.0, 600.0, 600.0)
        top_left = map_marker_screen_geometry(
            -300.0,
            300.0,
            world_size=600.0,
            viewport=viewport,
            scale=1.0,
        )
        bottom_right = map_marker_screen_geometry(
            300.0,
            -300.0,
            world_size=600.0,
            viewport=viewport,
            scale=1.0,
        )

        self.assertEqual(top_left, (viewport.left, viewport.top, 48.0))
        self.assertEqual(bottom_right, (viewport.right, viewport.bottom, 48.0))

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
        self.assertEqual(
            action_id_for_interactable("InteractableShrineBalance"),
            "balance_shrine",
        )
        self.assertIn(
            "InteractableShrineBalance",
            MapMarkerMemoryClient.ALLOWED_CLASSES,
        )
        self.assertEqual(action_id_for_interactable("InteractableEgg"), "egg")
        self.assertEqual(
            action_id_for_interactable("InteractableCharacterFight", character=9),
            "sus_bush",
        )
        self.assertIsNone(action_id_for_interactable("InteractableChest"))
        self.assertIsNone(
            action_id_for_interactable("InteractableCharacterFight", character=10)
        )

    def test_egg_and_sus_bush_are_available_to_automatic_discovery(self) -> None:
        self.assertFalse(MAP_MARKER_ACTION_BY_ID["egg"].manual_only)
        self.assertFalse(MAP_MARKER_ACTION_BY_ID["sus_bush"].manual_only)
        self.assertFalse(MAP_MARKER_ACTION_BY_ID["challenge_shrine"].manual_only)

    def test_marker_actions_use_filled_pngs_except_existing_multicolor_assets(
        self,
    ) -> None:
        multicolor_icons = {"egg": "egg", "sus_bush": "sus_bush"}
        classic_icons = {
            "magnet_shrine": "magnet_dark.svg",
            "moai": "moai_dark.svg",
            "balance_shrine": "balance_shrine_dark.svg",
            "challenge_shrine": "challenge_dark.svg",
            "boss_curse": "boss_curse_dark.svg",
        }
        for action_id, action in MAP_MARKER_ACTION_BY_ID.items():
            if action_id in multicolor_icons:
                self.assertEqual(action.icon_name, multicolor_icons[action_id])
                self.assertEqual(action.outline_color, "#03080F")
                self.assertIsNone(action.icon_file)
                self.assertEqual(action.pictogram_file, f"{action_id}.svg")
                self.assertEqual(action.classic_pictogram_file, f"{action_id}.svg")
                continue
            expected_name = "bald_head" if action_id == "balance_shrine" else action_id
            self.assertEqual(action.icon_file, f"filled/{expected_name}.png")
            self.assertEqual(action.pictogram_file, action.icon_file)
            self.assertEqual(action.settings_pictogram_file, action.icon_file)
            self.assertEqual(action.outline_color, "#F5F7FA")
            expected_classic = classic_icons.get(
                action_id,
                "microwave_dark.svg"
                if action.family == "microwave"
                else "shady_guy_dark.svg",
            )
            self.assertEqual(action.classic_pictogram_file, expected_classic)

        balance = MAP_MARKER_ACTION_BY_ID["balance_shrine"]
        self.assertEqual(balance.label, "Bald Head")
        self.assertEqual(balance.icon_name, "bald_head")
        self.assertEqual(balance.icon_file, "filled/bald_head.png")

    def test_shady_guy_matches_neon_marker_mockup(self) -> None:
        expected_colors = {
            "white": "#16F28B",
            "blue": "#00D7FF",
            "purple": "#E04FFF",
            "gold": "#FF9F0A",
        }
        for rarity_id, expected_color in expected_colors.items():
            action = MAP_MARKER_ACTION_BY_ID[f"shady_guy_{rarity_id}"]
            self.assertEqual(action.color, expected_color)
            self.assertEqual(action.icon_name, f"shady_guy_{rarity_id}")
            self.assertEqual(
                action.icon_file,
                f"filled/shady_guy_{rarity_id}.png",
            )

        microwave = MAP_MARKER_ACTION_BY_ID["microwave_white"]
        self.assertEqual(microwave.color, "#F2F2E9")
        self.assertEqual(microwave.icon_file, "filled/microwave_white.png")

        magnet = MAP_MARKER_ACTION_BY_ID["magnet_shrine"]
        self.assertEqual(magnet.color, "#3478F6")
        self.assertEqual(magnet.icon_file, "filled/magnet_shrine.png")

    def test_boss_curse_uses_red_fill_distinct_from_challenge(self) -> None:
        challenge = MAP_MARKER_ACTION_BY_ID["challenge_shrine"]
        boss_curse = MAP_MARKER_ACTION_BY_ID["boss_curse"]

        self.assertEqual(challenge.color, "#EF6A5B")
        self.assertEqual(boss_curse.color, "#FF3B3B")
        self.assertNotEqual(boss_curse.color, challenge.color)

    def test_complete_palette_fits_small_full_map_at_large_scale(self) -> None:
        viewport = MapViewport(20.0, 30.0, 800.0, 800.0)
        palette = build_marker_palette(
            400.0,
            400.0,
            viewport=viewport,
            scale=2.0,
        )
        self.assertEqual(len(palette.rows), 15)
        self.assertGreaterEqual(palette.rows[0].top, viewport.top)
        self.assertLessEqual(
            palette.rows[-1].top + palette.rows[-1].height,
            viewport.bottom,
        )


class MapMarkerTrackerTests(unittest.TestCase):
    def test_microwave_counts_follow_each_object(self):
        first = DetectedMapActivity(1, 123, "InteractableMicrowave", "microwave_white", 0, 0, 3)
        second = replace(first, object_ptr=2, world_x=10, uses_remaining=1)
        client = FakeMarkerClient([
            self.frame(activity=first), self.frame(activity=second), self.frame(),
        ])
        counts = {1: 2, 2: 1}
        client.last_microwave_uses = counts.get
        tracker = MapMarkerTracker("game", client_factory=lambda _: client, automatic_scan_interval=0)
        options = dict(client_height=600, automatic_discovery=True)
        self.assertEqual(tracker.tick(**options).markers[0].uses_remaining, 3)
        snapshot = tracker.tick(**options)
        self.assertEqual([m.uses_remaining for m in snapshot.markers], [2, 1])
        counts[1] = 0
        self.assertEqual([m.uses_remaining for m in tracker.tick(**options).markers], [0, 1])
        client.active[1] = False
        self.assertEqual([m.object_ptr for m in tracker.tick(**options).markers], [2])
        self.assertEqual(tracker.tick(**options).markers[0].uses_remaining, 1)
        client.activity_is_active = Mock(side_effect=MemoryReadError("unavailable"))
        self.assertIsNone(tracker.tick(**options).markers[0].uses_remaining)
        client.frames = [self.frame(map_id=2)]
        self.assertEqual(tracker.tick(**options).markers, ())

    def test_microwave_counts_are_exposed_without_premium_option(self):
        activity = DetectedMapActivity(1, 123, "InteractableMicrowave", "microwave_white", 0, 0, 3)
        client = FakeMarkerClient([self.frame(activity=activity)])
        tracker = MapMarkerTracker("game", client_factory=lambda _: client, automatic_scan_interval=0)
        snapshot = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(snapshot.markers[0].uses_remaining, 3)
        # A temporary reconnect wait preserves the last known count.
        client.frames = [FullMapNotReadyError("waiting")]
        self.assertEqual(
            tracker.tick(client_height=600, automatic_discovery=True).markers[0].uses_remaining,
            3,
        )

    def _scheduled_tracker(self):
        projection = MinimapProjection(
            True, False, MapViewport(0, 0, 220, 220), 110, 110, 110,
            0, 0, 1, 0, 0, 1, 110, 1,
        )
        now = [0.0]
        client = FakeMarkerClient([self.frame(open=False, minimap=projection)])
        tracker = MapMarkerTracker("game", client_factory=lambda _: client, clock=lambda: now[0])
        options = dict(client_height=600, minimap_enabled=True, automatic_discovery=True)
        tracker.tick(**options)
        for i in range(100):
            ptr = i + 1
            marker_id = str(ptr)
            tracker._markers[marker_id] = WorldMapMarker(
                marker_id, "moai", float(i if i < 5 else 200), 0, object_ptr=ptr
            )
            tracker._automatic_by_object[ptr] = marker_id
            tracker._automatic_identity_by_object[ptr] = (0x123, "InteractableShrineMoai")
        return tracker, client, now, options

    def test_far_lifecycle_is_distributed_and_near_markers_stay_fast(self):
        from collections import Counter
        tracker, client, now, options = self._scheduled_tracker()
        for tick in range(1, 11):
            now[0] = tick / 10
            before = len(client.active_checks)
            tracker.tick(**options)
            self.assertLessEqual(len(client.active_checks) - before, 24)
        counts = Counter(client.active_checks)
        self.assertEqual([counts[ptr] for ptr in range(1, 6)], [10] * 5)
        self.assertEqual([counts[ptr] for ptr in range(6, 101)], [2] * 95)

    def test_camera_approach_and_full_map_override_far_deadlines(self):
        tracker, client, now, options = self._scheduled_tracker()
        now[0] = .1
        tracker.tick(**options)
        self.assertNotIn(6, client.active_checks)
        client.frames[0] = replace(client.frames[0], minimap_projection=replace(
            client.frames[0].minimap_projection, camera_world_x=200.0
        ))
        now[0] = .2
        client.active_checks.clear()
        tracker.tick(**options)
        self.assertIn(6, client.active_checks)
        client.frames[0] = replace(client.frames[0], map_open=True, viewport=self.viewport)
        now[0] = .3
        client.active_checks.clear()
        client.active[6] = False
        snapshot = tracker.tick(**options)
        self.assertEqual(len(client.active_checks), 100)
        self.assertNotIn(6, tracker._lifecycle_schedule)
        self.assertNotIn("6", {m.marker_id for m in snapshot.markers})

    def test_selected_far_activity_and_missing_projection_are_checked_fast(self):
        tracker, client, now, options = self._scheduled_tracker()
        now[0] = .1
        tracker.tick(**options)
        client.frames[0] = replace(client.frames[0], current_activity=DetectedMapActivity(
            6, 0x123, "InteractableShrineMoai", "moai", 200, 0
        ))
        now[0] = .2
        client.active_checks.clear()
        tracker.tick(**options)
        self.assertIn(6, client.active_checks)
        client.frames[0] = replace(client.frames[0], minimap_projection=None)
        now[0] = .3
        client.active_checks.clear()
        tracker.tick(**options)
        self.assertEqual(len(client.active_checks), 100)
        client.frames[0] = replace(client.frames[0], map_id=2, current_activity=None)
        now[0] = .4
        tracker.tick(**options)
        self.assertEqual(tracker._lifecycle_schedule, {})
        tracker.close()
        self.assertEqual(tracker._lifecycle_serial, 0)

    def test_far_lifecycle_recovers_after_missed_ticks_without_starvation(self):
        tracker, client, now, options = self._scheduled_tracker()
        now[0] = .1
        tracker.tick(**options)
        now[0] = 2.01
        client.active_checks.clear()
        tracker.tick(**options)
        self.assertEqual(set(client.active_checks), set(range(1, 101)))

    def test_close_clears_state_even_if_the_native_client_close_fails(self) -> None:
        client = FakeMarkerClient([])
        client.close = lambda: (_ for _ in ()).throw(OSError("stale handle"))
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)
        tracker._client = client

        tracker.close()

        self.assertIsNone(tracker._client)
        self.assertEqual(tracker.snapshot, MapMarkerSnapshot())

    def setUp(self) -> None:
        self.viewport = MapViewport(0, 0, 600, 600)

    def frame(
        self, *, map_id=1, activity=None, stock=None, minimap=None, open=True
    ) -> MapMemoryFrame:
        return MapMemoryFrame(
            map_id=map_id,
            map_open=open,
            world_size=600.0,
            viewport=self.viewport if open else None,
            current_activity=activity,
            minimap_projection=minimap,
            merchant_stock_capture=stock,
        )

    @staticmethod
    def stock(*, map_id: int = 1, object_ptr: int = 0x5150):
        return MerchantStockCapture(
            map_id=map_id,
            merchant_object_ptr=object_ptr,
            marker_id=f"auto:{object_ptr:X}",
            merchant_rarity=1,
            world_x=15.0,
            world_z=-25.0,
            items=(MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),),
            class_ptr=0xA100,
        )

    def test_visited_shady_stock_creates_only_that_marker_with_auto_off(self) -> None:
        capture = self.stock()
        client = FakeMarkerClient([self.frame(stock=capture)])
        tracker = MapMarkerTracker(
            "game",
            client_factory=lambda _name: client,
            automatic_scan_interval=0.0,
        )

        snapshot = tracker.tick(
            client_height=600,
            automatic_discovery=False,
            merchant_memory_enabled=True,
        )

        self.assertEqual(len(snapshot.markers), 1)
        self.assertEqual(snapshot.markers[0].action_id, "shady_guy_blue")
        self.assertEqual(snapshot.merchant_stocks, (capture,))
        self.assertEqual(client.automatic_discovery_values, [False])
        self.assertEqual(client.merchant_memory_values, [True])

        cleared = tracker.tick(client_height=600)
        self.assertEqual(cleared.markers, ())
        self.assertEqual(cleared.merchant_stocks, ())

    def test_same_rarity_merchants_keep_separate_stock_and_can_refresh(self) -> None:
        first = replace(self.stock(object_ptr=0x5150), merchant_rarity=0)
        # Reproduce an older wrong capture of A's offers against B's identity.
        second_wrong = replace(self.stock(object_ptr=0x6160), merchant_rarity=0)
        second_correct = replace(second_wrong, items=(MerchantOffer(0, "Key", "Key", "COMMON"),))
        client = FakeMarkerClient([
            self.frame(stock=first), self.frame(stock=second_wrong),
            self.frame(stock=second_correct),
        ])
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client, automatic_scan_interval=0.0)
        for _ in range(3):
            snapshot = tracker.tick(client_height=600, merchant_memory_enabled=True)
        stocks = {s.merchant_object_ptr: s.items for s in snapshot.merchant_stocks}
        self.assertEqual(stocks, {0x5150: first.items, 0x6160: second_correct.items})
        self.assertEqual(len(snapshot.markers), 2)
        self.assertEqual({m.action_id for m in snapshot.markers}, {"shady_guy_white"})
        self.assertEqual({m.object_ptr for m in snapshot.markers}, {0x5150, 0x6160})

    def test_minimap_surface_is_forwarded_without_replacing_full_map_state(self) -> None:
        projection = MinimapProjection(
            True,
            False,
            MapViewport(10.0, 20.0, 200.0, 200.0),
            110.0,
            120.0,
            100.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            1.0,
            100.0,
            1.0,
        )
        client = FakeMarkerClient(
            [self.frame(open=False, minimap=projection, stock=self.stock())]
        )
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)

        first = tracker.tick(
            client_height=600, minimap_enabled=True, merchant_memory_enabled=True
        )
        self.assertEqual(len(first.markers), 1)
        self.assertIsNone(first.minimap_projection)
        snapshot = tracker.tick(
            client_height=600, minimap_enabled=True, merchant_memory_enabled=True
        )

        self.assertFalse(snapshot.map_open)
        self.assertEqual(snapshot.minimap_projection, projection)
        self.assertEqual(client.minimap_values, [False, True])

    def test_empty_ledger_skips_minimap_but_keeps_discovery_and_manual_maps(self) -> None:
        client = FakeMarkerClient([self.frame()])
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)
        options = dict(client_height=600, minimap_enabled=True, automatic_discovery=True)
        for _ in range(2):
            tracker.tick(**options)
        self.assertEqual(client.minimap_values, [False, False])
        self.assertEqual(client.automatic_discovery_values, [True, True])
        self.assertTrue(tracker.snapshot.map_open)
        self.assertTrue(tracker.place_manual_marker("moai", screen_x=300, screen_y=300))
        tracker.tick(**options)
        self.assertTrue(client.minimap_values[-1])
        self.assertTrue(tracker.place_manual_marker("moai", screen_x=300, screen_y=300))
        tracker.tick(**options)
        self.assertFalse(client.minimap_values[-1])

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
                "microwave_white", screen_x=319, screen_y=300
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

    def test_manual_marker_can_be_removed_with_a_different_bound_action(self) -> None:
        client = FakeMarkerClient([self.frame()])
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)
        tracker.tick(client_height=600)

        tracker.place_manual_marker(
            "boss_curse", screen_x=300, screen_y=300
        )
        self.assertEqual(
            [marker.action_id for marker in tracker.snapshot.markers],
            ["boss_curse"],
        )

        tracker.place_manual_marker(
            "microwave_white", screen_x=300, screen_y=300
        )

        self.assertEqual(tracker.snapshot.markers, ())

    def test_manual_marker_hit_area_uses_scaled_projected_visual_icon(self) -> None:
        client = FakeMarkerClient([self.frame()])
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client)
        tracker.tick(client_height=600)

        tracker.place_manual_marker("moai", screen_x=0, screen_y=300)
        self.assertEqual(len(tracker.snapshot.markers), 1)

        # The centre remains on the map boundary; clicking the visible half of
        # the clipped marker must still remove it.
        tracker.place_manual_marker(
            "moai",
            screen_x=10,
            screen_y=300,
            scale=1.0,
        )
        self.assertEqual(tracker.snapshot.markers, ())

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

    def test_reconnect_rehydrates_activity_identity_without_losing_marker(self) -> None:
        now = [10.0]
        activity = DetectedMapActivity(
            object_ptr=0xABC,
            class_ptr=0x100,
            class_name="InteractableShrineMoai",
            action_id="moai",
            world_x=20.0,
            world_z=-30.0,
        )
        first_client = FakeMarkerClient(
            [self.frame(activity=activity), MemoryReadError("transient poll failure")]
        )
        replacement_client = FakeMarkerClient([self.frame()])
        clients = [first_client, replacement_client]
        tracker = MapMarkerTracker(
            "game",
            client_factory=lambda _name: clients.pop(0),
            clock=lambda: now[0],
            reconnect_interval=1.0,
            automatic_scan_interval=0.0,
        )

        discovered = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(
            [marker.marker_id for marker in discovered.markers],
            ["auto:ABC"],
        )

        failed = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(
            [marker.marker_id for marker in failed.markers],
            ["auto:ABC"],
        )
        self.assertTrue(first_client.closed)

        now[0] = 11.0
        recovered = tracker.tick(client_height=600, automatic_discovery=True)

        self.assertEqual(
            [marker.marker_id for marker in recovered.markers],
            ["auto:ABC"],
        )
        self.assertEqual(
            replacement_client.active_identity_checks,
            [(0xABC, 0x100, "InteractableShrineMoai")],
        )

    def test_transient_activity_read_failure_preserves_marker(self) -> None:
        activity = DetectedMapActivity(
            object_ptr=0xABC,
            class_ptr=0x100,
            class_name="InteractableShrineMoai",
            action_id="moai",
            world_x=20.0,
            world_z=-30.0,
        )

        class FlakyLifecycleClient(FakeMarkerClient):
            def __init__(self, frames: list[MapMemoryFrame]) -> None:
                super().__init__(frames)
                self.fail_next_lifecycle_read = True

            def activity_is_active(self, object_ptr: int, **kwargs) -> bool:
                if self.fail_next_lifecycle_read:
                    self.fail_next_lifecycle_read = False
                    raise MemoryReadError("transient lifecycle failure")
                return super().activity_is_active(object_ptr, **kwargs)

        client = FlakyLifecycleClient(
            [self.frame(activity=activity), self.frame(), self.frame()]
        )
        tracker = MapMarkerTracker(
            "game",
            client_factory=lambda _name: client,
            automatic_scan_interval=0.0,
        )

        tracker.tick(client_height=600, automatic_discovery=True)
        after_failure = tracker.tick(client_height=600, automatic_discovery=True)
        after_retry = tracker.tick(client_height=600, automatic_discovery=True)

        self.assertEqual(len(after_failure.markers), 1)
        self.assertEqual(len(after_retry.markers), 1)
        self.assertEqual(client.active_checks, [activity.object_ptr])

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
    def test_microwave_count_reuses_lifecycle_sample_without_reads(self):
        client, memory, obj = self.client("InteractableMicrowave")
        memory.i32s[obj + client.MICROWAVE_USES_LEFT_OFFSET] = 3
        self.assertTrue(client.activity_is_active(obj))
        memory.read_i32 = Mock(side_effect=AssertionError("extra read"))
        memory.read_u8 = Mock(side_effect=AssertionError("extra read"))
        memory.read_bytes = Mock(side_effect=AssertionError("extra read"))
        self.assertEqual(client.last_microwave_uses(obj), 3)
        self.assertIsNone(client.last_microwave_uses(obj + 1))
        with self.assertRaises(AssertionError):
            client.activity_is_active(obj)
        self.assertIsNone(client.last_microwave_uses(obj))

    def test_microwave_discovery_includes_live_count(self):
        client, memory, obj = self.client("InteractableMicrowave")
        memory.i32s[obj + client.MICROWAVE_USES_LEFT_OFFSET] = 2
        client._class_name_from_ptr = lambda _: "InteractableMicrowave"
        client._component_transform = lambda _: 0x4000
        client._transform_point = lambda *_: (12.0, 0.0, -34.0)
        self.assertEqual(client._read_current_activity(obj).uses_remaining, 2)
        memory.i32s[obj + client.MICROWAVE_USES_LEFT_OFFSET] = 0
        memory.u8s[obj + client.MICROWAVE_HAS_ITEM_OFFSET] = 1
        self.assertTrue(client.activity_is_active(obj))
        self.assertEqual(client.last_microwave_uses(obj), 0)
        memory.ptrs[obj] = 0xDEAD
        self.assertFalse(client.activity_is_active(obj))
        self.assertIsNone(client.last_microwave_uses(obj))

    def test_lifecycle_batches_header_and_still_rejects_recycled_objects(self):
        client, memory, obj = self.client("InteractableShadyGuy")
        self.assertTrue(client.activity_is_active(obj))
        self.assertEqual(memory.byte_reads, [(obj, 24)])
        self.assertEqual(memory.ptr_reads, [])
        memory.ptrs[obj] = 0xDEAD
        self.assertFalse(client.activity_is_active(obj))
        memory.ptrs[obj] = 0x2000
        memory.ptrs[obj + client.MANAGED_NATIVE_OFFSET] = 0
        self.assertFalse(client.activity_is_active(obj))

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

    def test_known_identity_rehydrates_replacement_client_cache(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        object_ptr = 0x1000
        class_ptr = 0x2000
        memory.ptrs[object_ptr] = class_ptr
        memory.ptrs[object_ptr + client.MANAGED_NATIVE_OFFSET] = 0x3000

        self.assertTrue(
            client.activity_is_active(
                object_ptr,
                expected_class_ptr=class_ptr,
                expected_class_name="InteractableShrineMoai",
            )
        )
        self.assertEqual(
            client._tracked_classes[object_ptr],
            (class_ptr, "InteractableShrineMoai"),
        )

    def test_egg_and_bush_use_their_own_done_flags(self) -> None:
        client, memory, obj = self.client("InteractableEgg")
        self.assertTrue(client.activity_is_active(obj))
        memory.u8s[obj + client.EGG_DONE_OFFSET] = 1
        self.assertFalse(client.activity_is_active(obj))

        client, memory, obj = self.client("InteractableCharacterFight")
        self.assertTrue(client.activity_is_active(obj))
        memory.u8s[obj + client.CHARACTER_FIGHT_DONE_OFFSET] = 1
        self.assertFalse(client.activity_is_active(obj))

    def test_character_fight_discovery_accepts_only_bush(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        object_ptr = 0x1000
        class_ptr = 0x2000
        character_data = 0x3000
        memory.ptrs[object_ptr] = class_ptr
        memory.ptrs[
            object_ptr + client.CHARACTER_FIGHT_CHARACTER_OFFSET
        ] = character_data
        memory.i32s[character_data + client.CHARACTER_DATA_CHARACTER_OFFSET] = 9
        client._class_name_from_ptr = lambda candidate: (
            "InteractableCharacterFight" if candidate == class_ptr else None
        )
        client.activity_is_active = lambda _candidate: True
        client._component_transform = lambda _candidate: 0x4000
        client._transform_point = lambda _transform, _point: (12.0, 0.0, -34.0)

        activity = client._read_current_activity(object_ptr)

        self.assertIsNotNone(activity)
        self.assertEqual(activity.action_id, "sus_bush")
        self.assertEqual((activity.world_x, activity.world_z), (12.0, -34.0))

        memory.i32s[character_data + client.CHARACTER_DATA_CHARACTER_OFFSET] = 10
        self.assertIsNone(client._read_current_activity(object_ptr))

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
            pressed = {0x06, 0x09, 0x11, 0x1B, ord("G"), 0x77}

            def GetAsyncKeyState(self, virtual_key: int) -> int:
                return 0x8000 if virtual_key in self.pressed else 0

        user32 = FakeUser32()
        input_state = WindowsMapMarkerInput(user32)
        self.assertTrue(input_state.is_pressed("mouse5"))
        self.assertTrue(input_state.is_pressed("ctrl+g"))
        self.assertTrue(input_state.is_pressed("f8"))
        self.assertTrue(input_state.is_map_surface_key_pressed())
        self.assertFalse(input_state.is_pressed("f9"))
        user32.pressed.discard(0x09)
        self.assertTrue(input_state.is_map_surface_key_pressed())
        user32.pressed.discard(0x1B)
        self.assertFalse(input_state.is_map_surface_key_pressed())

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
        client._read_ui_screen_bounds = lambda _native: (
            0.0,
            0.0,
            2560.0,
            1440.0,
        )
        viewport = client._read_viewport(full_map, 2560, 1440, 1.25)
        self.assertAlmostEqual(viewport.left, 26.6666, places=3)
        self.assertAlmostEqual(viewport.top, 229.3334, places=3)
        self.assertAlmostEqual(viewport.width, 800.0, places=3)
        self.assertAlmostEqual(viewport.height, 800.0, places=3)

    def test_full_hd_ui_is_scaled_to_a_1440p_client_before_qt_conversion(self) -> None:
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

        # Live 1920x1080-on-2560x1440 capture: the game's UI coordinates stop
        # at 1920x1080 while the borderless Win32 client remains 2560x1440.
        client._transform_point = lambda _transform, point: (
            25.0 + point[0],
            490.0 + point[1],
            0.0,
        )
        client._read_ui_screen_bounds = lambda _native: (
            0.0,
            0.0,
            1920.0,
            1080.0,
        )

        viewport = client._read_viewport(full_map, 2560, 1440, 1.25)

        self.assertAlmostEqual(viewport.left, 26.6667, places=3)
        self.assertAlmostEqual(viewport.top, 229.3333, places=3)
        self.assertAlmostEqual(viewport.width, 800.0, places=3)
        self.assertAlmostEqual(viewport.height, 800.0, places=3)

    def test_viewport_updates_when_game_resolution_changes_at_runtime(self) -> None:
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
        layout = {
            "origin_x": 33.3333,
            "origin_y": 653.3333,
            "scale": 4.0 / 3.0,
            "screen": (0.0, 0.0, 2560.0, 1440.0),
        }
        client._transform_point = lambda _transform, point: (
            layout["origin_x"] + point[0] * layout["scale"],
            layout["origin_y"] + point[1] * layout["scale"],
            0.0,
        )
        client._read_ui_screen_bounds = lambda _native: layout["screen"]

        native_1440p = client._read_viewport(full_map, 2560, 1440, 1.25)
        layout.update(
            origin_x=25.0,
            origin_y=490.0,
            scale=1.0,
            screen=(0.0, 0.0, 1920.0, 1080.0),
        )
        upscaled_1080p = client._read_viewport(full_map, 2560, 1440, 1.25)

        self.assertAlmostEqual(upscaled_1080p.left, native_1440p.left, places=3)
        self.assertAlmostEqual(upscaled_1080p.top, native_1440p.top, places=3)
        self.assertAlmostEqual(upscaled_1080p.width, native_1440p.width, places=3)
        self.assertAlmostEqual(upscaled_1080p.height, native_1440p.height, places=3)

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
        client._read_ui_screen_bounds = lambda _native: (
            0.0,
            0.0,
            2560.0,
            1440.0,
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
        client._transform_points_native = lambda _native, points: tuple(
            (1280.0 + point[0] * (4.0 / 3.0),
             680.0 + point[1] * (4.0 / 3.0), 0.0)
            for point in points
        )
        client._read_ui_screen_bounds = lambda _native: (
            0.0,
            0.0,
            2560.0,
            1440.0,
        )

        viewport = client._read_viewport(full_map, 2560, 1440, 1.25)

        self.assertAlmostEqual(viewport.left, 554.6667, places=3)
        self.assertAlmostEqual(viewport.top, 133.3333, places=3)
        self.assertAlmostEqual(viewport.width, 938.6667, places=3)
        self.assertAlmostEqual(viewport.height, 949.3333, places=3)

    def test_ui_screen_bounds_use_the_topmost_transform_in_hierarchy(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        native = 0x720000
        access = 0x730000
        parents = 0x740000
        native_transforms = 0x750000
        root_native = 0x760000
        middle_native = 0x770000

        memory.ptrs[native + client.NATIVE_TRANSFORM_ACCESS_OFFSET] = access
        memory.i32s[native + client.NATIVE_TRANSFORM_INDEX_OFFSET] = 2
        memory.ptrs[access + client.TRANSFORM_ACCESS_COUNTS_OFFSET] = (3 << 32) | 3
        memory.ptrs[access + client.TRANSFORM_ACCESS_PARENTS_OFFSET] = parents
        memory.ptrs[
            access + client.TRANSFORM_ACCESS_NATIVE_TRANSFORMS_OFFSET
        ] = native_transforms
        memory.i32s[parents] = -1
        memory.i32s[parents + 4] = 0
        memory.i32s[parents + 8] = 1
        memory.ptrs[native_transforms] = root_native
        memory.ptrs[native_transforms + 8] = middle_native
        memory.ptrs[native_transforms + 16] = native

        self.assertEqual(client._root_native_transform(native), root_native)

    def test_viewport_rejects_an_invalid_ui_screen_surface(self) -> None:
        with self.assertRaisesRegex(MemoryReadError, "coordinate spaces are invalid"):
            MapMarkerMemoryClient._map_viewport_to_qt(
                (25.0, 115.0, 775.0, 865.0),
                (0.0, 0.0, 0.0, 1080.0),
                client_width=2560,
                client_height=1440,
                display_scale=1.25,
            )

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

    def test_map_seed_changes_the_runtime_map_identity(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        memory.floats[full_map + client.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        client._resolve_full_map = lambda: full_map
        client._resolve_player = lambda: 0x400000
        client._resolve_stage_scope = lambda: (0x500000, 1)
        seeds = iter((42, 43))
        client._resolve_map_seed_safe = lambda: next(seeds)

        first = client.poll(client_height=600)
        second = client.poll(client_height=600)

        self.assertEqual((first.map_seed, second.map_seed), (42, 43))
        self.assertNotEqual(first.map_id, second.map_id)

    def test_memory_client_skips_minimap_projection_while_a_full_map_is_open(
        self,
    ) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        memory.floats[full_map + client.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 1
        client._resolve_full_map = lambda: full_map
        client._read_viewport = lambda *_args: MapViewport(20, 30, 600, 600)
        client._resolve_player = lambda: 0x400000
        client._resolve_stage_scope = lambda: (0x500000, 1)
        client._read_minimap_projection = lambda *_args: (_ for _ in ()).throw(
            AssertionError("minimap was sampled behind an open map")
        )

        frame = client.poll(
            client_width=1920,
            client_height=1080,
            minimap_enabled=True,
        )

        self.assertTrue(frame.map_open)
        self.assertIsNotNone(frame.viewport)
        self.assertIsNone(frame.minimap_projection)

    def test_memory_client_does_not_read_shady_ui_when_memory_is_off(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        full_map = 0x700000
        memory.floats[full_map + client.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        client._resolve_full_map = lambda: full_map
        client._resolve_player = lambda: 0x400000
        client._resolve_stage_scope = lambda: (0x500000, 1)
        client._read_shady_stock_capture = lambda _map_id: (_ for _ in ()).throw(
            AssertionError("Shady UI was read while merchant memory was disabled")
        )

        frame = client.poll(
            client_height=600,
            merchant_memory_enabled=False,
        )

        self.assertIsNone(frame.merchant_stock_capture)

    def test_stale_currently_interacting_is_not_enough_to_read_cards(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        ui_type_info = 0x200000
        ui_static = 0x210000
        ui_manager = 0x220000
        encounters = 0x230000
        memory.ptrs[
            client._module_base + client.UI_MANAGER_TYPE_INFO_OFFSET
        ] = ui_type_info
        memory.ptrs[ui_type_info + client.CLASS_STATIC_FIELDS_OFFSET] = ui_static
        memory.ptrs[ui_static + client.UI_MANAGER_INSTANCE_OFFSET] = ui_manager
        memory.ptrs[
            ui_manager + client.UI_MANAGER_ENCOUNTER_WINDOWS_OFFSET
        ] = encounters
        memory.u8s[encounters + client.ENCOUNTER_IN_PROGRESS_OFFSET] = 0
        client._is_live_component = lambda pointer, _class_name: bool(pointer)
        client._read_shady_offer_cards = lambda _picker: (_ for _ in ()).throw(
            AssertionError("Offer cards were read while the window was closed")
        )

        self.assertIsNone(client._read_shady_stock_capture(7))

    def test_stable_visible_offer_cards_produce_stock_with_prices(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        merchant = 0x510000
        levelup = 0x520000
        picker = 0x530000
        class_ptr = 0x540000
        offers = (
            MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),
            MerchantOffer(2, "SpikyShield", "Spiky Shield", "RARE"),
        )
        memory.ptrs[merchant + client.OBJECT_KLASS_OFFSET] = class_ptr
        memory.i32s[merchant + client.SHADY_RARITY_OFFSET] = 2
        client._read_shady_offer_gate = lambda: (merchant, levelup, picker)
        client._read_shady_offer_cards = lambda candidate: (
            offers if candidate == picker else ()
        )
        client.activity_is_active = lambda candidate: candidate == merchant
        client._component_transform = lambda candidate: (
            0x550000 if candidate == merchant else 0
        )
        client._transform_point = lambda _transform, _point: (12.5, 0.0, -40.0)
        client._stage_ptr = 0x9000
        client._stage_index = 1

        self.assertIsNone(client._read_shady_stock_capture(77, map_seed=4242))
        capture = client._read_shady_stock_capture(77, map_seed=4242)

        self.assertEqual(capture.map_id, 77)
        self.assertEqual(capture.merchant_object_ptr, merchant)
        self.assertEqual(
            capture.items,
            tuple(replace(item, price=0) for item in offers),
        )
        self.assertEqual((capture.world_x, capture.world_z), (12.5, -40.0))
        self.assertEqual(capture.game_process_identity, "module:100000")
        self.assertEqual(
            (capture.stage_ptr, capture.raw_stage_index, capture.map_seed),
            (0x9000, 1, 4242),
        )
        self.assertEqual(
            client._tracked_classes[merchant],
            (class_ptr, "InteractableShadyGuy"),
        )

    def test_reused_picker_does_not_copy_first_merchants_cards_to_second(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        merchant_a, merchant_b, picker, levelup = 0x510000, 0x520000, 0x530000, 0x540000
        for merchant in (merchant_a, merchant_b):
            memory.ptrs[merchant + client.OBJECT_KLASS_OFFSET] = 0x550000
            memory.i32s[merchant + client.SHADY_RARITY_OFFSET] = 0
        first = (MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),)
        second = (MerchantOffer(0, "Key", "Key", "COMMON"),)
        state = {"merchant": merchant_a, "offers": first}
        client._read_shady_offer_gate = lambda: (
            (state["merchant"], levelup, picker) if state["merchant"] else None
        )
        client._read_shady_offer_cards = lambda _picker: state["offers"]
        client.activity_is_active = lambda _merchant: True
        client._component_transform = lambda merchant: merchant
        client._transform_point = lambda merchant, _point: (float(merchant), 0.0, 0.0)

        self.assertIsNone(client._read_shady_stock_capture(7))
        capture_a = client._read_shady_stock_capture(7)
        self.assertEqual(capture_a.merchant_object_ptr, merchant_a)
        self.assertEqual(capture_a.items, tuple(replace(item, price=0) for item in first))

        # B is already the current merchant, but the reused UI still holds A's
        # complete cards for one sample. Same-poll double reads cannot detect it.
        state["merchant"] = merchant_b
        self.assertIsNone(client._read_shady_stock_capture(7))
        state["offers"] = second
        self.assertIsNone(client._read_shady_stock_capture(7))
        capture_b = client._read_shady_stock_capture(7)
        self.assertEqual(capture_b.merchant_object_ptr, merchant_b)
        self.assertEqual(capture_b.items, tuple(replace(item, price=0) for item in second))

        # Closing the UI invalidates confirmation, even if the same shop opens.
        state["merchant"] = None
        self.assertIsNone(client._read_shady_stock_capture(7))
        state["merchant"] = merchant_b
        self.assertIsNone(client._read_shady_stock_capture(7))
        self.assertEqual(
            client._read_shady_stock_capture(7).items,
            tuple(replace(item, price=0) for item in second),
        )
        # The same pointer tuple in another stage/run also starts unconfirmed.
        self.assertIsNone(client._read_shady_stock_capture(8))

    def test_shady_card_reader_requires_complete_known_item_array(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        picker = 0x610000
        buttons = 0x620000
        button_a = 0x630000
        button_b = 0x640000
        item_a = 0x650000
        item_b = 0x660000
        memory.ptrs[picker + client.UPGRADE_PICKER_BUTTONS_OFFSET] = buttons
        memory.i32s[picker + client.UPGRADE_PICKER_COUNT_OFFSET] = 2
        memory.i32s[buttons + client.ARRAY_LENGTH_OFFSET] = 8
        memory.ptrs[buttons + client.ARRAY_DATA_OFFSET] = button_a
        memory.ptrs[buttons + client.ARRAY_DATA_OFFSET + 8] = button_b
        for button, item in ((button_a, item_a), (button_b, item_b)):
            memory.u8s[button + client.UPGRADE_BUTTON_IS_ITEM_OFFSET] = 1
            memory.ptrs[button + client.UPGRADE_BUTTON_ITEM_DATA_OFFSET] = item
        memory.i32s[item_a + client.ITEM_DATA_ITEM_ID_OFFSET] = 0
        memory.i32s[item_a + client.ITEM_DATA_RARITY_OFFSET] = 0
        memory.i32s[item_b + client.ITEM_DATA_ITEM_ID_OFFSET] = 1
        memory.i32s[item_b + client.ITEM_DATA_RARITY_OFFSET] = 1
        client._is_live_component = lambda pointer, class_name: (
            class_name == "UpgradeButton" and pointer in {button_a, button_b}
        )
        client._class_name = lambda pointer: (
            "ItemData" if pointer in {item_a, item_b} else None
        )

        self.assertEqual(
            client._read_shady_offer_cards(picker),
            (
                MerchantOffer(0, "Key", "Key", "COMMON"),
                MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),
            ),
        )

        memory.i32s[item_b + client.ITEM_DATA_ITEM_ID_OFFSET] = 9999
        with self.assertRaisesRegex(MemoryReadError, "metadata is invalid"):
            client._read_shady_offer_cards(picker)

    def test_moving_minimap_camera_keeps_basis_independent_of_translation(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        transform, native, access, matrices, parents = (
            0x710000, 0x720000, 0x730000, 0x740000, 0x750000
        )
        memory.ptrs[transform + client.MANAGED_NATIVE_OFFSET] = native
        memory.ptrs[native + client.NATIVE_TRANSFORM_ACCESS_OFFSET] = access
        memory.i32s[native + client.NATIVE_TRANSFORM_INDEX_OFFSET] = 1
        memory.ptrs[access + client.TRANSFORM_ACCESS_MATRICES_OFFSET] = matrices
        memory.ptrs[access + client.TRANSFORM_ACCESS_PARENTS_OFFSET] = parents
        memory.i32s[parents + 4] = 0
        memory.i32s[parents] = -1
        reads = []
        original_read_bytes = memory.read_bytes

        def moving_matrix(address, size):
            if size != client.TRANSFORM_MATRIX_SIZE:
                return original_read_bytes(address, size)
            self.assertEqual(size, client.TRANSFORM_MATRIX_SIZE)
            reads.append(address)
            # Move both child and parent on every read, as the game can do
            # between RPM calls. The camera looks down; its parent turns 90 deg.
            half_root = 0.5 ** 0.5
            rotation = (
                (half_root, 0.0, 0.0, half_root)
                if address == matrices + client.TRANSFORM_MATRIX_SIZE
                else (0.0, half_root, 0.0, half_root)
            )
            return struct.pack(
                '<12f', len(reads) * 0.25, 10.0, len(reads) * 0.5, 0.0,
                *rotation, 1.0, 1.0, 1.0, 0.0,
            )

        memory.read_bytes = moving_matrix
        origins = []
        for _ in range(2):
            origin, right, up = client._transform_points(
                transform, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
            )
            origins.append(origin)
            self.assertAlmostEqual(right[0] - origin[0], 0.0, places=6)
            self.assertAlmostEqual(right[2] - origin[2], -1.0, places=6)
            self.assertAlmostEqual(up[0] - origin[0], 1.0, places=6)
            self.assertAlmostEqual(up[2] - origin[2], 0.0, places=6)
        self.assertNotEqual(origins[0], origins[1])
        self.assertEqual(reads, [matrices + client.TRANSFORM_MATRIX_SIZE, matrices] * 2)

    def _minimap_geometry_fixture(self):
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        player = 0x710000
        script = 0x720000
        camera = 0x730000
        camera_native = 0x740000
        camera_transform = 0x750000
        memory.ptrs[player + client.PLAYER_MINIMAP_CAMERA_SCRIPT_OFFSET] = script
        memory.ptrs[player + client.PLAYER_MINIMAP_CAMERA_OFFSET] = camera
        memory.ptrs[script + client.MINIMAP_SCRIPT_CAMERA_OFFSET] = camera
        memory.ptrs[camera + client.MANAGED_NATIVE_OFFSET] = camera_native
        memory.floats[
            camera_native + client.CAMERA_ORTHOGRAPHIC_SIZE_OFFSET
        ] = 110.0
        memory.floats[camera_native + client.CAMERA_PROJECTION_X_OFFSET] = 1.0 / 110.0
        memory.floats[camera_native + client.CAMERA_PROJECTION_Y_OFFSET] = 1.0 / 110.0
        client._class_name = lambda pointer: {
            script: "MinimapCamera",
            camera: "Camera",
        }.get(pointer)
        client._component_transform = lambda pointer: (
            camera_transform if pointer == camera else 0
        )

        def transform_points(transform, points):
            self.assertEqual(transform, camera_transform)
            return tuple((100.0 + point[0], 50.0, 200.0 + point[1]) for point in points)

        client._transform_points = transform_points
        client._resolve_minimap_ui = lambda: 0x760000
        client._resolve_minimap_native_transforms = lambda _ui: (
            0x770000,
            0x780000,
        )
        client._read_rect_transform_bounds = lambda _native: (
            2184.115,
            937.448,
            2518.654,
            1271.987,
        )
        client._read_ui_screen_bounds = lambda _native: (
            0.0,
            0.0,
            2560.0,
            1440.0,
        )
        client._read_hud_visible = lambda: True
        client._read_minimap_jammed = lambda: False
        return client, memory, player, camera_native

    def test_minimap_geometry_uses_unity_to_client_to_qt_normalization(self) -> None:
        client, _, player, _ = self._minimap_geometry_fixture()
        projection = client._read_minimap_projection(
            player,
            client_width=2048,
            client_height=1152,
            display_scale=1.25,
        )

        self.assertAlmostEqual(projection.content_rect.left, 1397.8336, places=3)
        self.assertAlmostEqual(projection.content_rect.top, 107.5283, places=3)
        self.assertAlmostEqual(projection.content_rect.width, 214.1050, places=3)
        self.assertAlmostEqual(projection.content_rect.height, 214.1050, places=3)
        self.assertEqual(
            (
                projection.camera_world_x,
                projection.camera_world_z,
                projection.camera_right_x,
                projection.camera_right_z,
                projection.camera_up_x,
                projection.camera_up_z,
            ),
            (100.0, 200.0, 1.0, 0.0, 0.0, 1.0),
        )

    def test_cached_minimap_layout_keeps_camera_motion_rotation_and_zoom_live(self) -> None:
        client, memory, player, camera_native = self._minimap_geometry_fixture()
        client._clock = lambda: 0.0
        bounds = Mock(wraps=client._read_rect_transform_bounds)
        client._read_rect_transform_bounds = bounds
        first = client._read_minimap_projection(player, 2048, 1152, 1.0)
        client._transform_points = Mock(return_value=(
            (120.0, 50.0, 220.0), (120.0, 50.0, 221.0), (119.0, 50.0, 220.0)
        ))
        memory.floats[camera_native + client.CAMERA_ORTHOGRAPHIC_SIZE_OFFSET] = 80.0
        memory.floats[camera_native + client.CAMERA_PROJECTION_X_OFFSET] = 1 / 80.0
        memory.floats[camera_native + client.CAMERA_PROJECTION_Y_OFFSET] = 1 / 80.0
        second = client._read_minimap_projection(player, 2048, 1152, 1.0)
        self.assertEqual(bounds.call_count, 1)
        self.assertEqual(first.content_rect, second.content_rect)
        self.assertEqual((second.camera_world_x, second.camera_world_z), (120.0, 220.0))
        self.assertEqual((second.camera_right_x, second.camera_right_z), (0.0, 1.0))
        self.assertEqual((second.camera_up_x, second.camera_up_z), (-1.0, 0.0))
        self.assertEqual(second.orthographic_size, 80.0)
        client._transform_points.assert_called_once()

    def test_minimap_layout_refreshes_on_deadline_resolution_dpi_and_identity(self) -> None:
        client, _, player, _ = self._minimap_geometry_fixture()
        now = [0.0]
        client._clock = lambda: now[0]
        bounds = Mock(wraps=client._read_rect_transform_bounds)
        client._read_rect_transform_bounds = bounds
        first = client._read_minimap_projection(player, 2048, 1152, 1.0)
        now[0] = 0.199
        client._read_minimap_projection(player, 2048, 1152, 1.0)
        self.assertEqual(bounds.call_count, 1)
        bounds.return_value = (1000.0, 100.0, 1200.0, 300.0)
        now[0] = 0.201
        moved = client._read_minimap_projection(player, 2048, 1152, 1.0)
        self.assertEqual(bounds.call_count, 2)
        self.assertNotEqual(moved.content_rect, first.content_rect)
        for count, (width, height, dpi) in enumerate(
            ((2560, 1152, 1.0), (2560, 1440, 1.0),
             (2560, 1440, 1.25), (2560, 1440, 1.5)), start=3
        ):
            projection = client._read_minimap_projection(player, width, height, dpi)
            self.assertEqual(bounds.call_count, count)
            self.assertAlmostEqual(projection.content_rect.width, 200.0 * width / 2560 / dpi)
            self.assertAlmostEqual(projection.content_rect.height, 200.0 * height / 1440 / dpi)
        for identity in ((0x990000, 0x780000), (0x990000, 0xAA0000)):
            count = bounds.call_count
            client._resolve_minimap_native_transforms = lambda _ui: identity
            client._read_minimap_projection(player, 2560, 1440, 1.5)
            self.assertEqual(bounds.call_count, count + 1)

    def test_hidden_or_jammed_minimap_skips_camera_and_refreshes_when_visible(self) -> None:
        for hidden, jammed in ((True, False), (False, True)):
            with self.subTest(hidden=hidden, jammed=jammed):
                client, memory, player, _ = self._minimap_geometry_fixture()
                client._clock = lambda: 0.0
                bounds = Mock(wraps=client._read_rect_transform_bounds)
                client._read_rect_transform_bounds = bounds
                client._read_minimap_projection(player, 2048, 1152, 1.0)
                camera = Mock(wraps=client._transform_points)
                client._transform_points = camera
                client._read_hud_visible = lambda: not hidden
                client._read_minimap_jammed = Mock(return_value=jammed)
                memory.ptr_reads.clear()
                self.assertIsNone(client._read_minimap_projection(player, 2048, 1152, 1.0))
                self.assertEqual(memory.ptr_reads, [])
                camera.assert_not_called()
                if hidden:
                    client._read_minimap_jammed.assert_not_called()
                self.assertIsNone(client._minimap_viewport_cache)
                client._read_hud_visible = lambda: True
                client._read_minimap_jammed = lambda: False
                self.assertIsNotNone(client._read_minimap_projection(player, 2048, 1152, 1.0))
                self.assertEqual(bounds.call_count, 2)

    def test_minimap_cache_clears_on_map_visibility_scope_and_read_failure(self) -> None:
        client, memory, player, _ = self._minimap_geometry_fixture()
        client._clock = lambda: 0.0
        bounds = Mock(wraps=client._read_rect_transform_bounds)
        client._read_rect_transform_bounds = bounds
        full_map = client._full_map_ptr = 0x810000
        client._resolve_full_map = lambda: full_map
        client._resolve_player = lambda: player
        scope = [0x820000, 1]
        client._resolve_stage_scope = lambda: tuple(scope)
        client._read_viewport = lambda *_args: MapViewport(0, 0, 600, 600)
        memory.floats[full_map + client.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0
        options = dict(client_width=2048, client_height=1152, minimap_enabled=True)
        self.assertIsNotNone(client.poll(**options).minimap_projection)
        # Tab/Escape hides the minimap and invalidates its layout immediately.
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 1
        self.assertIsNone(client.poll(**options).minimap_projection)
        self.assertIsNone(client._minimap_viewport_cache)
        memory.i32s[full_map + client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        self.assertIsNotNone(client.poll(**options).minimap_projection)
        self.assertEqual(bounds.call_count, 2)
        scope[1] = 2
        client.poll(**options)
        self.assertEqual(bounds.call_count, 3)
        camera_address = player + client.PLAYER_MINIMAP_CAMERA_OFFSET
        camera = memory.ptrs.pop(camera_address)
        self.assertIsNone(client.poll(**options).minimap_projection)
        self.assertIsNone(client._minimap_viewport_cache)
        memory.ptrs[camera_address] = camera
        self.assertIsNotNone(client.poll(**options).minimap_projection)
        self.assertEqual(bounds.call_count, 4)
        # A failed geometry refresh must not fall back to the previous rect.
        client._clock = lambda: 1.0
        bounds.side_effect = MemoryReadError("UI was replaced")
        self.assertIsNone(client.poll(**options).minimap_projection)
        self.assertIsNone(client._minimap_viewport_cache)
        bounds.side_effect = None
        self.assertIsNotNone(client.poll(**options).minimap_projection)
        options["minimap_enabled"] = False
        self.assertIsNone(client.poll(**options).minimap_projection)
        self.assertIsNone(client._minimap_viewport_cache)

    def test_rect_corners_share_one_sample_of_moving_transform_hierarchy(self) -> None:
        memory = FakeLifecycleMemory()
        client = MapMarkerMemoryClient(memory=memory)
        native, access, matrices, parents = 0x710000, 0x720000, 0x730000, 0x740000
        memory.ptrs[native + client.NATIVE_TRANSFORM_ACCESS_OFFSET] = access
        memory.i32s[native + client.NATIVE_TRANSFORM_INDEX_OFFSET] = 1
        memory.ptrs[access + client.TRANSFORM_ACCESS_MATRICES_OFFSET] = matrices
        memory.ptrs[access + client.TRANSFORM_ACCESS_PARENTS_OFFSET] = parents
        memory.i32s[parents + 4] = 0
        memory.i32s[parents] = -1
        matrix_reads = []
        original_read_bytes = memory.read_bytes

        def read_bytes(address, size):
            if address == native + client.RECT_TRANSFORM_RECT_OFFSET:
                return struct.pack("<4f", 0.0, 0.0, 200.0, 100.0)
            if size != client.TRANSFORM_MATRIX_SIZE:
                return original_read_bytes(address, size)
            matrix_reads.append(address)
            self.assertEqual(size, client.TRANSFORM_MATRIX_SIZE)
            return struct.pack(
                "<12f", float(len(matrix_reads)), 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0,
            )

        memory.read_bytes = read_bytes
        left, bottom, right, top = client._read_rect_transform_bounds(native)
        self.assertEqual((left, bottom, right, top), (3.0, 0.0, 203.0, 100.0))
        self.assertEqual(matrix_reads, [matrices + client.TRANSFORM_MATRIX_SIZE, matrices])

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


class MapMarkerResilienceTests(unittest.TestCase):
    """Exercise real poll/tick paths with controlled memory faults, not UI input."""

    def setUp(self) -> None:
        self.memory = FakeLifecycleMemory()
        self.now = [10.0]
        self.state = dict(seed=42, full_map=0x700000, player=0x400000,
                          stage=0x500000, index=1, process="game:1")
        self.object_ptr = 0x21000
        self.detector = 0x420000
        self.seed_address = 0x310000 + MapMarkerMemoryClient.MAP_GENERATION_MAP_SEED_OFFSET
        self.memory.ptrs[0x100000 + MapMarkerMemoryClient.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET] = 0x300000
        self.memory.ptrs[0x300000 + MapMarkerMemoryClient.CLASS_STATIC_FIELDS_OFFSET] = 0x310000
        self.memory.ptrs[0x400000 + MapMarkerMemoryClient.PLAYER_INPUT_OFFSET] = 0x410000
        self.memory.ptrs[0x410000 + MapMarkerMemoryClient.DETECT_INTERACTABLES_OFFSET] = self.detector
        self.current_address = self.detector + MapMarkerMemoryClient.CURRENT_INTERACTABLE_OFFSET
        self.memory.ptrs[self.current_address] = self.object_ptr
        self.memory.ptrs[self.object_ptr] = 0xA000
        self.memory.ptrs[self.object_ptr + MapMarkerMemoryClient.MANAGED_NATIVE_OFFSET] = 0x22000
        self.memory.ptrs[0x5150] = 0xA100
        self.memory.ptrs[0x5150 + MapMarkerMemoryClient.MANAGED_NATIVE_OFFSET] = 0x6000
        self.memory.floats[0x700000 + MapMarkerMemoryClient.FULL_MAP_WORLD_SIZE_OFFSET] = 600.0
        self.memory.i32s[0x700000 + MapMarkerMemoryClient.FULL_MAP_OPEN_COUNT_OFFSET] = 1
        read_i32 = self.memory.read_i32

        def read_seed(address):
            if address == self.seed_address:
                if self.state["seed"] is None:
                    raise MemoryReadError("injected seed read failure")
                return self.state["seed"]
            return read_i32(address)

        self.memory.read_i32 = read_seed
        self.projection = MinimapProjection(
            True, False, MapViewport(0, 0, 220, 220), 110, 110, 110,
            0, 0, 1, 0, 0, 1, 110, 1,
        )
        self.client = self.make_client()
        self.factory = Mock(return_value=self.client)
        self.tracker = MapMarkerTracker(
            "game", client_factory=self.factory, clock=lambda: self.now[0],
            automatic_scan_interval=0.0,
        )
        self.options = dict(client_height=600, automatic_discovery=True,
                            minimap_enabled=True, merchant_memory_enabled=True)

    def make_client(self):
        client = MapMarkerMemoryClient(memory=self.memory)
        client._game_process_identity = self.state["process"]
        client._full_map_ptr = self.state["full_map"]
        client._resolve_full_map = lambda: self.state["full_map"]
        client._resolve_player = lambda: self.state["player"]
        client._resolve_stage_scope = lambda: (self.state["stage"], self.state["index"])
        client._class_name_from_ptr = Mock(return_value="InteractableShrineMagnet")
        client._component_transform = Mock(return_value=0x23000)
        client._transform_point = Mock(return_value=(20.0, 0.0, -30.0))
        client._read_viewport = Mock(return_value=MapViewport(0, 0, 600, 600))
        client._read_minimap_projection = Mock(return_value=self.projection)
        client._read_shady_stock_capture = Mock(return_value=None)
        return client

    def remember_markers(self):
        frame = self.client.poll(client_height=600)
        capture = replace(MapMarkerTrackerTests.stock(map_id=frame.map_id),
                          map_seed=frame.map_seed)
        self.client._read_shady_stock_capture.return_value = capture
        self.tracker.tick(**self.options)
        self.assertTrue(self.tracker.place_manual_marker(
            "boss_curse", screen_x=500, screen_y=500,
        ))
        self.client._read_shady_stock_capture.return_value = None
        # No automatic rediscovery may conceal an accidental ledger clear.
        self.memory.ptrs[self.current_address] = 0
        self.assertEqual(len(self.tracker.snapshot.markers), 3)
        return self.tracker.snapshot

    def test_seed_read_failures_preserve_all_markers_stock_and_public_identity(self):
        before = self.remember_markers()
        for seed in (None, None, 42, None, 42):
            with self.subTest(seed=seed):
                self.state["seed"] = seed
                after = self.tracker.tick(**self.options)
                self.assertEqual(after.markers, before.markers)
                self.assertEqual(after.merchant_stocks, before.merchant_stocks)
                self.assertEqual(after.map_id, before.map_id)
                self.assertIs(self.tracker._client, self.client)
        self.assertEqual(self.factory.call_count, 1)

    def test_first_successful_seed_is_not_a_new_map_but_next_change_is(self):
        self.state["seed"] = None
        before = self.remember_markers()
        self.state["seed"] = 42
        after = self.tracker.tick(**self.options)
        self.assertEqual(after.markers, before.markers)
        self.assertEqual(len(after.merchant_stocks), 1)
        self.assertEqual(after.merchant_stocks[0].map_id, after.map_id)
        self.state["seed"] = 43
        changed = self.tracker.tick(**self.options)
        self.assertNotEqual(changed.map_id, after.map_id)
        self.assertEqual(changed.markers, ())
        self.assertEqual(changed.merchant_stocks, ())

    def test_zero_and_negative_seeds_are_values_not_read_failures(self):
        before = self.remember_markers()
        self.state["seed"] = 0
        changed = self.tracker.tick(**self.options)
        self.assertNotEqual(changed.map_id, before.map_id)
        self.assertEqual(changed.markers, ())
        self.tracker.place_manual_marker("moai", screen_x=300, screen_y=300)
        for seed in (None, 0, None):
            self.state["seed"] = seed
            self.assertEqual(len(self.tracker.tick(**self.options).markers), 1)
        self.state["seed"] = -7
        self.assertEqual(self.tracker.tick(**self.options).markers, ())

    def test_each_structural_boundary_clears_even_when_seed_does_not_change(self):
        for key in ("full_map", "player", "stage", "index", "process"):
            with self.subTest(boundary=key):
                self.setUp()
                self.remember_markers()
                if key == "process":
                    self.client._game_process_identity = "game:2"
                else:
                    self.state[key] += 1
                after = self.tracker.tick(**self.options)
                self.assertEqual(after.markers, ())
                self.assertEqual(after.merchant_stocks, ())

    def test_new_scope_with_unknown_seed_clears_once_and_learns_new_seed(self):
        self.remember_markers()
        self.state.update(seed=None, stage=0x510000)
        self.assertEqual(self.tracker.tick(**self.options).markers, ())
        self.tracker.place_manual_marker("moai", screen_x=300, screen_y=300)
        self.state["seed"] = 99
        self.assertEqual(len(self.tracker.tick(**self.options).markers), 1)

    def test_reconnect_with_unknown_seed_keeps_last_valid_seed_and_ledger(self):
        before = self.remember_markers()
        self.client._resolve_full_map = Mock(side_effect=MemoryReadError("disconnected"))
        failed = self.tracker.tick(**self.options)
        self.assertEqual(failed.markers, before.markers)
        replacement = self.make_client()
        self.factory.return_value = replacement
        self.state["seed"] = None
        self.now[0] += 1.1
        recovered = self.tracker.tick(**self.options)
        self.assertEqual(recovered.markers, before.markers)
        self.assertEqual(recovered.map_id, before.map_id)
        self.assertEqual(recovered.merchant_stocks, before.merchant_stocks)
        self.assertEqual(self.factory.call_count, 2)
        self.state["seed"] = 42
        self.assertEqual(self.tracker.tick(**self.options).markers, before.markers)
        self.state["seed"] = 43
        self.assertEqual(self.tracker.tick(**self.options).markers, ())

    def test_close_forgets_seed_and_scope(self):
        self.remember_markers()
        self.tracker.close()
        self.state["seed"] = None
        self.tracker.tick(**self.options)
        self.tracker.place_manual_marker("moai", screen_x=300, screen_y=300)
        self.state["seed"] = 99
        self.assertEqual(len(self.tracker.tick(**self.options).markers), 1)

    def test_stock_captured_during_seed_failure_uses_retained_map_id(self):
        before = self.remember_markers()
        self.state["seed"] = None
        self.client._read_shady_stock_capture.side_effect = lambda map_id, **kw: replace(
            before.merchant_stocks[0], map_id=map_id, map_seed=kw["map_seed"],
        )
        after = self.tracker.tick(**self.options)
        self.assertEqual(after.markers, before.markers)
        self.assertEqual(after.map_id, before.map_id)
        self.assertEqual(after.merchant_stocks[0].map_id, before.map_id)
        # Do not turn an unknown sample into confirmed analytics provenance.
        self.assertIsNone(after.merchant_stocks[0].map_seed)

    def test_seed_failure_does_not_accept_a_capture_from_another_map(self):
        before = self.remember_markers()
        self.state["seed"] = None
        for wrong_id in (123, before.map_id):
            with self.subTest(capture_id=wrong_id):
                self.client._read_shady_stock_capture.return_value = MapMarkerTrackerTests.stock(
                    map_id=wrong_id, object_ptr=0x9990,
                )
                after = self.tracker.tick(**self.options)
                self.assertEqual(after.markers, before.markers)
                self.assertEqual(after.merchant_stocks, before.merchant_stocks)

    def test_discovery_memory_faults_keep_projection_and_other_markers(self):
        for phase in ("detector", "current_pointer", "class", "transform"):
            with self.subTest(phase=phase):
                self.setUp()
                before = self.remember_markers()
                self.memory.i32s[0x700000 + self.client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
                self.memory.ptrs[self.current_address] = self.object_ptr
                owner, name = {
                    "detector": (self.client, "_resolve_detector"),
                    "current_pointer": (self.memory, "read_ptr"),
                    "class": (self.client, "_class_name_from_ptr"),
                    "transform": (self.client, "_transform_point"),
                }[phase]
                original = getattr(owner, name)

                def fail(*args):
                    if phase == "current_pointer" and args[0] != self.current_address:
                        return original(*args)
                    raise MemoryReadError("injected discovery fault")

                setattr(owner, name, fail)
                after = self.tracker.tick(**self.options)
                self.assertEqual(after.markers, before.markers)
                self.assertEqual(after.merchant_stocks, before.merchant_stocks)
                self.assertEqual(after.minimap_projection, self.projection)
                self.assertIs(self.tracker._client, self.client)
                self.assertEqual(self.client._detector_ptr, 0)
                setattr(owner, name, original)
                self.memory.ptrs[self.current_address] = self.object_ptr + 0x100
                self.memory.ptrs[self.object_ptr + 0x100] = 0xA000
                self.memory.ptrs[self.object_ptr + 0x100 + self.client.MANAGED_NATIVE_OFFSET] = 0x24000
                recovered = self.tracker.tick(**self.options)
                self.assertEqual(len(recovered.markers), 4)
                self.assertEqual(self.factory.call_count, 1)

    def test_discovery_programming_errors_are_not_swallowed_by_poll(self):
        self.client._read_current_activity = Mock(side_effect=RuntimeError("bug"))
        with self.assertRaisesRegex(RuntimeError, "bug"):
            self.client.poll(client_height=600, automatic_discovery=True)

    def test_invalid_done_preserves_marker_but_confirmed_done_removes_it(self):
        before = self.remember_markers()
        address = self.object_ptr + self.client.SHRINE_DONE_OFFSET
        self.memory.u8s[address] = 2
        self.assertEqual(self.tracker.tick(**self.options).markers, before.markers)
        self.memory.u8s[address] = 0
        self.assertEqual(self.tracker.tick(**self.options).markers, before.markers)
        self.memory.u8s[address] = 1
        after = self.tracker.tick(**self.options)
        self.assertEqual(len(after.markers), 2)
        self.assertNotIn(self.object_ptr, {m.object_ptr for m in after.markers})

    def test_all_activity_done_flags_reject_invalid_bytes(self):
        offsets = {
            "InteractableShadyGuy": self.client.SHADY_DONE_OFFSET,
            "InteractableEgg": self.client.EGG_DONE_OFFSET,
            "InteractableCharacterFight": self.client.CHARACTER_FIGHT_DONE_OFFSET,
        }
        for name in sorted(self.client.ALLOWED_CLASSES - {"InteractableMicrowave"}):
            offset = offsets.get(name, self.client.SHRINE_DONE_OFFSET)
            for value in (2, 255):
                with self.subTest(activity=name, value=value):
                    self.client._tracked_classes[self.object_ptr] = (0xA000, name)
                    self.memory.u8s[self.object_ptr + offset] = value
                    with self.assertRaises(MemoryReadError):
                        self.client.activity_is_active(self.object_ptr)
                    self.memory.u8s[self.object_ptr + offset] = 0

    def test_invalid_microwave_samples_hide_count_without_deleting_icon(self):
        self.client._class_name_from_ptr.return_value = "InteractableMicrowave"
        uses = self.object_ptr + self.client.MICROWAVE_USES_LEFT_OFFSET
        cooking = self.object_ptr + self.client.MICROWAVE_IS_COOKING_OFFSET
        item = self.object_ptr + self.client.MICROWAVE_HAS_ITEM_OFFSET
        self.memory.i32s[uses] = 3
        before = self.remember_markers()
        marker_id = f"auto:{self.object_ptr:X}"
        for address, value in ((uses, -1), (cooking, 2), (item, 255)):
            with self.subTest(address=address):
                self.memory.i32s[uses] = 3
                self.memory.u8s[cooking] = self.memory.u8s[item] = 0
                (self.memory.i32s if address == uses else self.memory.u8s)[address] = value
                after = self.tracker.tick(**self.options)
                self.assertEqual(len(after.markers), len(before.markers))
                self.assertIsNone(next(m for m in after.markers if m.marker_id == marker_id).uses_remaining)
        self.memory.i32s[uses] = 0
        self.memory.u8s[cooking] = 0
        self.memory.u8s[item] = 1
        after = self.tracker.tick(**self.options)
        self.assertEqual(next(m for m in after.markers if m.marker_id == marker_id).uses_remaining, 0)
        self.memory.u8s[item] = 0
        self.assertEqual(len(self.tracker.tick(**self.options).markers), 2)

    def test_projection_fault_hides_surface_without_erasing_ledger(self):
        before = self.remember_markers()
        self.memory.i32s[0x700000 + self.client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        self.client._read_minimap_projection.side_effect = [
            MemoryReadError("camera unavailable"), self.projection,
        ]
        hidden = self.tracker.tick(**self.options)
        self.assertEqual(hidden.markers, before.markers)
        self.assertIsNone(hidden.minimap_projection)
        shown = self.tracker.tick(**self.options)
        self.assertEqual(shown.markers, before.markers)
        self.assertEqual(shown.minimap_projection, self.projection)
        self.assertEqual(self.factory.call_count, 1)


if __name__ == "__main__":
    unittest.main()
