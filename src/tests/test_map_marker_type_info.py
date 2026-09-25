"""Regression coverage for low-address IL2CPP type-info pointers.

The resolver and tracker are real; the memory backend is a strict byte map.
No game process is opened and no process memory is written.
"""
from __future__ import annotations

import struct
import unittest
from unittest.mock import Mock

from app.map_marker_hotkeys import MapMarkerHotkeyController
from app.map_marker_tracker import MapMarkerTracker
from core.map_markers import MapViewport, map_marker_screen_geometry
from infra.memory.map_marker_client import FullMapNotReadyError, MapMarkerMemoryClient
from infra.memory.reader import MemoryReadError


class TypeInfoMemory:
    """Fail on unmapped bytes rather than silently returning a plausible zero."""

    def __init__(self) -> None:
        self.data: dict[int, int] = {}
        self.strings: dict[int, str] = {}
        self.reads: list[tuple[int, int]] = []

    def put(self, address: int, fmt: str, value: int | float) -> None:
        self.data.update(enumerate(struct.pack(fmt, value), start=address))

    def read_bytes(self, address: int, size: int) -> bytes:
        self.reads.append((address, size))
        try:
            return bytes(self.data[address + offset] for offset in range(size))
        except KeyError as exc:
            raise MemoryReadError(f"Unmapped test memory at 0x{address:X}.") from exc

    def read_ptr(self, address: int) -> int:
        return struct.unpack("<Q", self.read_bytes(address, 8))[0]

    def read_i32(self, address: int) -> int:
        return struct.unpack("<i", self.read_bytes(address, 4))[0]

    def read_float(self, address: int) -> float:
        return struct.unpack("<f", self.read_bytes(address, 4))[0]

    def read_u8(self, address: int) -> int:
        return self.read_bytes(address, 1)[0]

    def read_ascii_string(self, address: int) -> str | None:
        return self.strings.get(address)

    def module_base_address(self, _module: str) -> int:
        return 0x100000

    def process_identity(self) -> str:
        return "synthetic:1"


def full_map_client(type_info: int = 0x3258C080):
    """Only viewport/Unity transform math are stubbed, not pointer resolution."""
    memory = TypeInfoMemory()
    client = MapMarkerMemoryClient(memory=memory)
    base = client._module_base
    full_map = 0x53000000
    memory.put(base + client.FULL_MAP_UI_TYPE_INFO_OFFSET, "<Q", type_info)
    memory.put(type_info + client.CLASS_STATIC_FIELDS_OFFSET, "<Q", 0x51000000)
    memory.put(type_info + client.CLASS_NAME_POINTER_OFFSET, "<Q", 0x54000000)
    memory.strings[0x54000000] = "FullMap"
    memory.put(0x51000000 + client.FULL_MAP_TOGGLE_DELEGATE_OFFSET, "<Q", 0x52000000)
    memory.put(0x52000000 + client.MULTICAST_DELEGATES_OFFSET, "<Q", 0)
    memory.put(0x52000000 + client.DELEGATE_TARGET_OFFSET, "<Q", full_map)
    memory.put(full_map, "<Q", type_info)
    memory.put(full_map + client.MANAGED_NATIVE_OFFSET, "<Q", 0x55000000)
    memory.put(full_map + client.FULL_MAP_WORLD_SIZE_OFFSET, "<f", 600.0)
    memory.put(full_map + client.FULL_MAP_OPEN_COUNT_OFFSET, "<i", 1)

    memory.put(base + client.MY_PLAYER_TYPE_INFO_OFFSET, "<Q", 0x60000000)
    memory.put(0x60000000 + client.CLASS_STATIC_FIELDS_OFFSET, "<Q", 0x60001000)
    memory.put(0x60001000 + client.MY_PLAYER_INSTANCE_OFFSET, "<Q", 0x60002000)
    memory.put(0x60002000 + client.PLAYER_INPUT_OFFSET, "<Q", 0x60003000)
    memory.put(0x60003000 + client.DETECT_INTERACTABLES_OFFSET, "<Q", 0x60004000)
    memory.put(0x60004000 + client.CURRENT_INTERACTABLE_OFFSET, "<Q", 0x63000000)
    memory.put(base + client.MAP_CONTROLLER_TYPE_INFO_OFFSET, "<Q", 0x61000000)
    memory.put(0x61000000 + client.CLASS_STATIC_FIELDS_OFFSET, "<Q", 0x61001000)
    memory.put(0x61001000 + client.MAP_CONTROLLER_CURRENT_STAGE_OFFSET, "<Q", 0x61002000)
    memory.put(0x61001000 + client.MAP_CONTROLLER_INDEX_OFFSET, "<i", 0)
    memory.put(base + client.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET, "<Q", 0x62000000)
    memory.put(0x62000000 + client.CLASS_STATIC_FIELDS_OFFSET, "<Q", 0x62001000)
    memory.put(0x62001000 + client.MAP_GENERATION_MAP_SEED_OFFSET, "<i", 42)

    memory.put(0x63000000, "<Q", 0x63001000)
    memory.put(0x63000008, "<Q", 0)
    memory.put(0x63000000 + client.MANAGED_NATIVE_OFFSET, "<Q", 0x63002000)
    memory.put(0x63001000 + client.CLASS_NAME_POINTER_OFFSET, "<Q", 0x63003000)
    memory.strings[0x63003000] = "InteractableShrineMoai"
    memory.put(0x63000000 + client.SHRINE_DONE_OFFSET, "<B", 0)
    client._read_viewport = Mock(return_value=MapViewport(0, 0, 600, 600))
    client._component_transform = Mock(return_value=0x64000000)
    client._transform_point = Mock(return_value=(20.0, 0.0, 30.0))
    return client, memory, full_map


class MapMarkerTypeInfoTests(unittest.TestCase):
    def test_aligned_pointer_candidates_are_not_uninitialized_tokens(self):
        for pointer in (
            0x1FFFFFF8, 0x20000000, 0x2000A390, 0x3258C080,
            0x3FFFFFF8, 0x40000000, 0x13258C080, 0x7FFE3258C080,
        ):
            with self.subTest(pointer=hex(pointer)):
                self.assertFalse(MapMarkerMemoryClient._is_uninitialized_type_info(pointer))

    def test_type_token_requires_low_bit_not_just_non_eight_byte_alignment(self):
        for pointer in (0x20000002, 0x20000004, 0x2000A396, 0x3258C082):
            with self.subTest(pointer=hex(pointer)):
                self.assertFalse(MapMarkerMemoryClient._is_uninitialized_type_info(pointer))
        for token in (0x20000001, 0x2000A391, 0x2000A397, 0x3258C081, 0x3FFFFFFF):
            with self.subTest(token=hex(token)):
                self.assertTrue(MapMarkerMemoryClient._is_uninitialized_type_info(token))
        # The helper recognizes a particular token, not all invalid pointers.
        for other in (0, -1, 0xFFFFFFFF, 0x12000A397):
            with self.subTest(non_token=other):
                self.assertFalse(MapMarkerMemoryClient._is_uninitialized_type_info(other))

    def test_full_map_resolves_low_addresses_and_range_boundaries(self):
        for pointer in (0x1FFFFFF8, 0x20000000, 0x3258C080, 0x3FFFFFF8, 0x40000000, 0x13258C080):
            with self.subTest(pointer=hex(pointer)):
                client, memory, full_map = full_map_client(pointer)
                self.assertEqual(client._resolve_full_map(), full_map)
                self.assertIn((pointer + client.CLASS_STATIC_FIELDS_OFFSET, 8), memory.reads)
                self.assertEqual(client._full_map_ptr, full_map)
                self.assertEqual(client._resolve_full_map(), full_map)

    def test_null_and_real_tokens_are_never_dereferenced(self):
        for token in (0, 0x20000001, 0x2000A397, 0x3258C081, 0x3FFFFFFF):
            with self.subTest(token=hex(token)):
                memory = TypeInfoMemory()
                client = MapMarkerMemoryClient(memory=memory)
                slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET
                memory.put(slot, "<Q", token)
                for _ in range(3):
                    with self.assertRaises(FullMapNotReadyError):
                        client.poll(client_height=600)
                self.assertEqual(memory.reads, [(slot, 8)] * 3)
                self.assertEqual(client._full_map_ptr, 0)

    def test_token_to_reported_pointer_recovers_both_marker_paths_same_client(self):
        client, memory, full_map = full_map_client()
        slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET
        memory.put(slot, "<Q", 0x2000A397)
        factory = Mock(return_value=client)
        tracker = MapMarkerTracker("unused", client_factory=factory, automatic_scan_interval=0)
        self.addCleanup(tracker.close)
        options = dict(client_height=600, client_width=600, automatic_discovery=True,
                       minimap_enabled=False, merchant_memory_enabled=False)
        for _ in range(3):
            waiting = tracker.tick(**options)
            self.assertFalse(waiting.map_open)
            self.assertFalse(tracker.place_manual_marker("boss_curse", screen_x=100, screen_y=100))
        self.assertEqual(memory.reads, [(slot, 8)] * 3)

        memory.put(slot, "<Q", 0x3258C080)
        ready = tracker.tick(**options)
        self.assertTrue(ready.map_open)
        self.assertEqual(ready.world_size, 600)
        self.assertEqual(client._full_map_ptr, full_map)
        self.assertEqual([(m.source, m.action_id) for m in ready.markers], [("automatic", "moai")])
        pressed = {"f8"}
        input_state = Mock()
        input_state.is_pressed.side_effect = lambda key: key in pressed
        hotkeys = MapMarkerHotkeyController(input_state, clock=lambda: 1.0)
        bindings = [{"input": "f8", "action": "boss_curse"}]
        hotkeys.poll(bindings, ready, cursor_x=100, cursor_y=100)
        pressed.clear()
        gesture = hotkeys.poll(bindings, ready, cursor_x=100, cursor_y=100)
        self.assertEqual(gesture.placement, ("boss_curse", 100.0, 100.0))
        self.assertTrue(tracker.place_manual_marker("boss_curse", screen_x=100, screen_y=100))
        retained = tracker.tick(**options)
        self.assertEqual({m.source for m in retained.markers}, {"manual", "automatic"})
        for marker in retained.markers:
            self.assertIsNotNone(map_marker_screen_geometry(
                marker.world_x, marker.world_z, world_size=retained.world_size, viewport=retained.viewport))
        factory.assert_called_once_with("unused")

    def test_valid_pointer_is_not_enough_without_static_fields_delegate_and_live_map(self):
        for failure in ("static_fields", "delegate", "wrong_class", "native_gone"):
            with self.subTest(failure=failure):
                client, memory, full_map = full_map_client()
                if failure == "static_fields":
                    memory.put(0x3258C080 + client.CLASS_STATIC_FIELDS_OFFSET, "<Q", 0)
                elif failure == "delegate":
                    memory.put(0x51000000 + client.FULL_MAP_TOGGLE_DELEGATE_OFFSET, "<Q", 0)
                elif failure == "wrong_class":
                    memory.strings[0x54000000] = "NotFullMap"
                else:
                    memory.put(full_map + client.MANAGED_NATIVE_OFFSET, "<Q", 0)
                with self.assertRaises(FullMapNotReadyError):
                    client.poll(client_height=600)
                self.assertIn((0x3258C080 + client.CLASS_STATIC_FIELDS_OFFSET, 8), memory.reads)
                self.assertEqual(client._full_map_ptr, 0)

    def test_unreadable_low_pointer_raises_and_tracker_reconnects_after_repair(self):
        client, memory, _ = full_map_client()
        slot = client._module_base + client.FULL_MAP_UI_TYPE_INFO_OFFSET
        memory.put(slot, "<Q", 0x3258D080)  # Even, but deliberately unmapped.
        with self.assertRaisesRegex(MemoryReadError, "Unmapped test memory"):
            client.poll(client_height=600)
        self.assertEqual(client._full_map_ptr, 0)
        now = [0.0]
        replacement = MapMarkerMemoryClient(memory=memory)
        factory = Mock(side_effect=[client, replacement])
        tracker = MapMarkerTracker("unused", client_factory=factory, clock=lambda: now[0])
        self.addCleanup(tracker.close)
        failed = tracker.tick(client_height=600, map_surface_enabled=False)
        self.assertFalse(failed.map_open)
        self.assertIsNone(tracker._client)
        self.assertEqual(factory.call_count, 1)
        memory.put(slot, "<Q", 0x3258C080)
        now[0] = 0.5
        self.assertFalse(tracker.tick(client_height=600, map_surface_enabled=False).map_open)
        self.assertEqual(factory.call_count, 1)
        now[0] = 1.1
        self.assertTrue(tracker.tick(client_height=600, map_surface_enabled=False).map_open)
        self.assertEqual(factory.call_count, 2)

    def test_seed_helper_accepts_low_pointer_but_not_real_token(self):
        client, memory, _ = full_map_client()
        slot = client._module_base + client.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET
        memory.put(slot, "<Q", 0x2000A397)
        self.assertIsNone(client._resolve_map_seed_safe())
        self.assertEqual(memory.reads, [(slot, 8)])
        memory.put(slot, "<Q", 0x3258C080)
        memory.put(0x51000000 + client.MAP_GENERATION_MAP_SEED_OFFSET, "<i", 0)
        self.assertEqual(client._resolve_map_seed_safe(), 0)
        memory.put(0x51000000 + client.MAP_GENERATION_MAP_SEED_OFFSET, "<i", -7)
        self.assertEqual(client._resolve_map_seed_safe(), -7)

    def test_minimap_ui_helper_accepts_low_pointer_after_real_token(self):
        client, memory, full_map = full_map_client()
        slot = client._module_base + client.MINIMAP_CAMERA_TYPE_INFO_OFFSET
        memory.put(slot, "<Q", 0x2000A397)
        with self.assertRaisesRegex(MemoryReadError, "type info is unavailable"):
            client._resolve_minimap_ui()
        self.assertEqual(memory.reads, [(slot, 8)])
        memory.put(slot, "<Q", 0x3258C080)
        memory.strings[0x54000000] = "MinimapUi"
        self.assertEqual(client._resolve_minimap_ui(), full_map)


if __name__ == "__main__":
    unittest.main()
