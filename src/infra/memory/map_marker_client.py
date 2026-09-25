"""Read-only IL2CPP adapter for Full Map and minimap activity markers.

The offsets in this module are intentionally isolated from the tracker and Qt
renderer.  They were verified live against the current game build on
2026-09-10; a future game update can therefore fail/reconnect here without
turning a stale read into a plausible marker position.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct
import time
from typing import Any, Callable

from core.item_metadata import ITEMS
from core.map_markers import (
    MapViewport,
    MerchantOffer,
    MerchantStockCapture,
    MinimapProjection,
    action_id_for_interactable,
)
from infra.memory.reader import MemoryReadError, ProcessMemory


class FullMapNotReadyError(RuntimeError):
    """The game has not initialized its FullMap runtime object yet."""


@dataclass(frozen=True, slots=True)
class DetectedMapActivity:
    object_ptr: int
    class_ptr: int
    class_name: str
    action_id: str
    world_x: float
    world_z: float
    uses_remaining: int | None = None


@dataclass(frozen=True, slots=True)
class MapMemoryFrame:
    map_id: int
    map_open: bool
    world_size: float
    viewport: MapViewport | None
    current_activity: DetectedMapActivity | None
    minimap_projection: MinimapProjection | None = None
    merchant_stock_capture: MerchantStockCapture | None = None
    map_seed: int | None = None
    # Seed-independent instance identity, including the game process lifetime.
    map_scope: tuple[str, int, int, int, int] | None = None


_ITEM_METADATA_BY_ID = {item.item_id: item for item in ITEMS}
_ITEM_RARITY_BY_VALUE = ("COMMON", "UNCOMMON", "RARE", "LEGENDARY")


class MapMarkerMemoryClient:
    MODULE_NAME = "GameAssembly.dll"
    MINIMAP_GEOMETRY_INTERVAL = 0.2

    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    OBJECT_KLASS_OFFSET = 0x0
    OBJECT_POINTER_SIZE = 0x8
    MANAGED_NATIVE_OFFSET = 0x10

    # Before IL2CPP initializes a type-info usage slot, 64-bit builds can keep
    # a tagged 32-bit metadata token there instead of an Il2CppClass pointer.
    # FullMap was observed as 0x2000A397 during startup. Dereferencing that token
    # at +CLASS_STATIC_FIELDS_OFFSET turns a normal waiting state into a Win32
    # partial-copy error and forces the tracker through its reconnect backoff.
    IL2CPP_METADATA_USAGE_TAG_MASK = 0xE0000000
    IL2CPP_TYPE_INFO_USAGE_TAG = 0x20000000
    IL2CPP_METADATA_TOKEN_FLAG = 0x1

    MY_PLAYER_TYPE_INFO_OFFSET = 0x2F620F8
    MY_PLAYER_INSTANCE_OFFSET = 0x08
    PLAYER_MINIMAP_CAMERA_OFFSET = 0x78
    PLAYER_MINIMAP_CAMERA_SCRIPT_OFFSET = 0x80
    PLAYER_INPUT_OFFSET = 0x48
    DETECT_INTERACTABLES_OFFSET = 0x20
    CURRENT_INTERACTABLE_OFFSET = 0x28

    MAP_CONTROLLER_TYPE_INFO_OFFSET = 0x2F58E08
    MAP_CONTROLLER_INDEX_OFFSET = 0x08
    MAP_CONTROLLER_CURRENT_STAGE_OFFSET = 0x18
    MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET = 0x2F59000
    MAP_GENERATION_MAP_SEED_OFFSET = 0x2C

    UI_MANAGER_TYPE_INFO_OFFSET = 0x2F9A528
    UI_MANAGER_INSTANCE_OFFSET = 0x00
    UI_MANAGER_ENCOUNTER_WINDOWS_OFFSET = 0x30
    UI_MANAGER_PAUSE_OFFSET = 0x40
    PAUSE_UI_MAP_OFFSET = 0x30
    PAUSE_UI_CURRENT_OFFSET = 0x38

    FULL_MAP_UI_TYPE_INFO_OFFSET = 0x2F9AF30
    FULL_MAP_TOGGLE_DELEGATE_OFFSET = 0x0
    FULL_MAP_WORLD_SIZE_OFFSET = 0x28
    FULL_MAP_DISPLAY_TRANSFORM_OFFSET = 0x50
    FULL_MAP_OPEN_COUNT_OFFSET = 0x60

    MINIMAP_CAMERA_TYPE_INFO_OFFSET = 0x2F5D440
    MINIMAP_ROTATION_DELEGATE_OFFSET = 0x00
    MINIMAP_SCRIPT_CAMERA_OFFSET = 0x48
    CAMERA_ORTHOGRAPHIC_SIZE_OFFSET = 0x450
    CAMERA_PROJECTION_X_OFFSET = 0xB0
    CAMERA_PROJECTION_Y_OFFSET = 0xC4

    SAVE_MANAGER_TYPE_INFO_OFFSET = 0x2F7C7C0
    SAVE_MANAGER_INSTANCE_OFFSET = 0x10
    SAVE_MANAGER_CONFIG_OFFSET = 0x20
    CONFIG_GAME_SETTINGS_OFFSET = 0x18
    GAME_SETTINGS_SHOW_HUD_OFFSET = 0x74

    MAP_EVENTS_DESERT_TYPE_INFO_OFFSET = 0x2F58F58
    MAP_EVENTS_DESERT_STORM_ACTIVE_OFFSET = 0x00
    CHALLENGES_TRACKER_TYPE_INFO_OFFSET = 0x2F7A598
    CHALLENGES_MODIFIER_NAMES_OFFSET = 0x10

    SHADY_GUY_TYPE_INFO_OFFSET = 0x2FB5928
    SHADY_CURRENTLY_INTERACTING_OFFSET = 0x00
    UPGRADE_BUTTON_PRICE_OFFSET = 0xDC
    ENCOUNTER_LEVELUP_SCREEN_OFFSET = 0x20
    ENCOUNTER_ACTIVE_WINDOW_OFFSET = 0x48
    ENCOUNTER_IN_PROGRESS_OFFSET = 0x58
    LEVELUP_UPGRADE_PICKER_OFFSET = 0x48
    LEVELUP_ENCOUNTER_TYPE_OFFSET = 0x9C
    UPGRADE_PICKER_BUTTONS_OFFSET = 0x20
    UPGRADE_PICKER_COUNT_OFFSET = 0x30
    UPGRADE_PICKER_ENCOUNTER_TYPE_OFFSET = 0x40
    UPGRADE_BUTTON_IS_ITEM_OFFSET = 0xC8
    UPGRADE_BUTTON_ITEM_DATA_OFFSET = 0xD0
    ITEM_DATA_ITEM_ID_OFFSET = 0x54
    ITEM_DATA_RARITY_OFFSET = 0x60
    SHADY_ENCOUNTER_TYPE = 7
    MAX_SHADY_OFFERS = 12
    MAX_UPGRADE_BUTTON_ARRAY_LENGTH = 64

    MULTICAST_DELEGATES_OFFSET = 0x78
    ARRAY_LENGTH_OFFSET = 0x18
    ARRAY_DATA_OFFSET = 0x20
    DELEGATE_TARGET_OFFSET = 0x20
    # The game's static FullMap event retains delegates for destroyed map
    # instances. Its managed array therefore grows throughout a long session;
    # hundreds of entries (707 in one live sample) were observed while only the
    # newest target was active. The high length cap is only a corruption guard:
    # work stays bounded because current FullMap subscriptions are appended and
    # only the newest tail is inspected.
    MAX_DELEGATE_ARRAY_LENGTH = 1_000_000
    MAX_DELEGATES_TO_SCAN = 128

    CLASS_NAME_POINTER_OFFSET = 0x10
    SHADY_RARITY_OFFSET = 0x90
    SHADY_DONE_OFFSET = 0xB0
    MICROWAVE_RARITY_OFFSET = 0x80
    MICROWAVE_USES_LEFT_OFFSET = 0x84
    MICROWAVE_IS_COOKING_OFFSET = 0x88
    MICROWAVE_HAS_ITEM_OFFSET = 0xF4
    SHRINE_DONE_OFFSET = 0x68
    EGG_DONE_OFFSET = 0xA0
    CHARACTER_FIGHT_CHARACTER_OFFSET = 0x58
    CHARACTER_FIGHT_DONE_OFFSET = 0x68
    CHARACTER_DATA_CHARACTER_OFFSET = 0x50

    NATIVE_COMPONENT_GAME_OBJECT_OFFSET = 0x20
    NATIVE_GAME_OBJECT_HANDLE_ROOT_OFFSET = 0x20
    NATIVE_GAME_OBJECT_NAME_OFFSET = 0x50
    HANDLE_ROOT_NEXT_OFFSET = 0x08
    HANDLE_VALUE_OFFSET = 0x18

    NATIVE_TRANSFORM_ACCESS_OFFSET = 0x28
    NATIVE_TRANSFORM_INDEX_OFFSET = 0x30
    TRANSFORM_ACCESS_MATRICES_OFFSET = 0x18
    TRANSFORM_ACCESS_PARENTS_OFFSET = 0x20
    TRANSFORM_ACCESS_COUNTS_OFFSET = 0x10
    TRANSFORM_ACCESS_NATIVE_TRANSFORMS_OFFSET = 0x30
    TRANSFORM_MATRIX_SIZE = 0x30
    RECT_TRANSFORM_RECT_OFFSET = 0xA8
    MAX_TRANSFORM_DEPTH = 128
    MAX_NATIVE_TRANSFORMS = 20_000

    HASHSET_SLOTS_OFFSET = 0x18
    HASHSET_COUNT_OFFSET = 0x20
    HASHSET_LAST_INDEX_OFFSET = 0x24
    HASHSET_SLOT_START_OFFSET = 0x20
    HASHSET_SLOT_SIZE = 0x10
    HASHSET_SLOT_HASH_CODE_OFFSET = 0x0
    HASHSET_SLOT_VALUE_OFFSET = 0x8
    MAX_CHALLENGE_MODIFIERS = 64

    ALLOWED_CLASSES = frozenset(
        {
            "InteractableMicrowave",
            "InteractableShadyGuy",
            "InteractableShrineMagnet",
            "InteractableShrineMoai",
            "InteractableShrineBalance",
            "InteractableShrineChallenge",
            "InteractableShrineCursed",
            "InteractableEgg",
            "InteractableCharacterFight",
        }
    )

    def __init__(
        self,
        process_name: str | None = None,
        *,
        memory: Any | None = None,
        module_name: str = MODULE_NAME,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if memory is None and not process_name:
            raise ValueError("process_name is required when memory is not provided.")
        self.module_name = module_name
        self._clock = clock
        self._owns_memory = memory is None
        self.memory = memory or ProcessMemory(str(process_name))
        self._module_base = int(self.memory.module_base_address(self.module_name))
        identity_reader = getattr(self.memory, "process_identity", None)
        self._game_process_identity = (
            str(identity_reader())
            if callable(identity_reader)
            else f"module:{self._module_base:X}"
        )
        self._full_map_ptr = 0
        self._player_ptr = 0
        self._detector_ptr = 0
        self._map_controller_static_fields = 0
        self._map_generation_static_fields = 0
        self._stage_ptr = 0
        self._stage_index = -1
        self._map_was_open = False
        self._viewport_cache: tuple[int, int, int, float, MapViewport] | None = None
        self._pause_map_root_native = 0
        self._pause_map_render_native = 0
        self._minimap_ui_ptr = 0
        self._minimap_root_native = 0
        self._minimap_renderer_native = 0
        self._minimap_render_native = 0
        self._minimap_viewport_cache: tuple[
            int, int, int, int, float, MapViewport, float
        ] | None = None
        self._tracked_classes: dict[int, tuple[int, str]] = {}
        self._last_microwave_uses: tuple[int, int] | None = None
        self._pending_stock_sample = None

    def close(self) -> None:
        self._last_microwave_uses = None
        self._pending_stock_sample = None
        if self._owns_memory and hasattr(self.memory, "close"):
            self.memory.close()

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
        full_map_viewport_enabled: bool = True,
    ) -> MapMemoryFrame:
        previous_full_map = self._full_map_ptr
        full_map = self._resolve_full_map()
        if not full_map:
            raise FullMapNotReadyError("Active FullMap instance is not available yet.")
        if full_map != previous_full_map:
            self._pending_stock_sample = None
            self._player_ptr = 0
            self._detector_ptr = 0
            self._map_was_open = False
            self._viewport_cache = None
            self._pause_map_root_native = 0
            self._pause_map_render_native = 0
            self._clear_minimap_cache()
            self._tracked_classes.clear()

        world_size = float(
            self.memory.read_float(full_map + self.FULL_MAP_WORLD_SIZE_OFFSET)
        )
        map_open = bool(
            self.memory.read_i32(full_map + self.FULL_MAP_OPEN_COUNT_OFFSET) > 0
        )
        if map_open and not self._map_was_open:
            self._viewport_cache = None
        viewport = (
            self._read_viewport(
                full_map,
                int(client_width or 0),
                int(client_height),
                max(0.01, float(display_scale)),
            )
            if map_open and full_map_viewport_enabled
            else None
        )
        self._map_was_open = map_open

        player = self._resolve_player()
        stage, stage_index = self._resolve_stage_scope()
        map_seed = self._resolve_map_seed_safe()
        if stage != self._stage_ptr or stage_index != self._stage_index:
            self._stage_ptr = stage
            self._stage_index = stage_index
            self._tracked_classes.clear()
            self._viewport_cache = None
            self._clear_minimap_cache()
        map_id = (
            (((map_seed or 0) & 0xFFFFFFFF) << 224)
            | ((full_map & 0xFFFFFFFFFFFFFFFF) << 160)
            | ((player & 0xFFFFFFFFFFFFFFFF) << 96)
            | ((stage & 0xFFFFFFFFFFFFFFFF) << 32)
            | (stage_index & 0xFFFFFFFF)
        )

        minimap_projection = None
        if minimap_enabled and not map_open:
            try:
                minimap_projection = self._read_minimap_projection(
                    player,
                    int(client_width or 0),
                    int(client_height),
                    max(0.01, float(display_scale)),
                )
            except Exception:
                # A stale camera/UI identity must hide this surface immediately;
                # it must never reuse the previous rectangle or rotation.
                self._clear_minimap_cache()
        elif not minimap_enabled:
            self._clear_minimap_cache()
        else:
            # Settings can change while Tab/Escape hides the minimap. Refresh
            # its layout immediately when that surface becomes visible again.
            self._minimap_viewport_cache = None

        current_activity = None
        if automatic_discovery and sample_automatic_discovery:
            try:
                detector = self._resolve_detector(player)
                current_ptr = self.memory.read_ptr(
                    detector + self.CURRENT_INTERACTABLE_OFFSET
                )
                current_activity = self._read_current_activity(current_ptr)
            except MemoryReadError:
                # Optional discovery must not discard a valid map/camera sample.
                # Re-resolve the detector without reconnecting the whole client.
                # Programming errors still reach the existing runtime boundary.
                self._detector_ptr = 0
        elif not automatic_discovery:
            # Do not retain or walk automatic-discovery state while the opt-in
            # setting is off. Full Map/player/stage reads remain necessary for
            # manual placement and its run-boundary cleanup.
            self._detector_ptr = 0
            if merchant_memory_enabled:
                self._tracked_classes = {
                    object_ptr: identity
                    for object_ptr, identity in self._tracked_classes.items()
                    if identity[1] == "InteractableShadyGuy"
                }
            else:
                self._tracked_classes.clear()

        merchant_stock_capture = None
        if not merchant_memory_enabled:
            self._pending_stock_sample = None
        if merchant_memory_enabled and sample_merchant_memory:
            try:
                merchant_stock_capture = self._read_shady_stock_capture(
                    map_id, map_seed=map_seed
                )
            except Exception:
                # Incomplete UI population, a close between passes, and stale
                # pointers all mean "not captured yet". The next valid opening
                # can retry without disrupting Full Map or minimap projection.
                merchant_stock_capture = None
                self._pending_stock_sample = None
        return MapMemoryFrame(
            # FullMap can outlive a run, and MyPlayer can survive a stage
            # transition. Combining both with MapController.currentStage/index
            # makes either boundary clear the run-scoped marker ledger.
            map_id=map_id,
            map_open=map_open,
            world_size=world_size,
            viewport=viewport,
            current_activity=current_activity,
            map_seed=map_seed,
            map_scope=(
                self._game_process_identity, full_map, player, stage, stage_index
            ),
            minimap_projection=minimap_projection,
            merchant_stock_capture=merchant_stock_capture,
        )

    def activity_is_active(
        self,
        object_ptr: int,
        *,
        expected_class_ptr: int | None = None,
        expected_class_name: str | None = None,
    ) -> bool:
        # Publish only the current successful sample, never a stale/recycled object.
        self._last_microwave_uses = None
        object_ptr = int(object_ptr)
        tracked = self._tracked_classes.get(object_ptr)
        if not tracked:
            # A replacement client has an empty discovery cache even though the
            # tracker still owns valid run-scoped markers.  Rehydrate only from
            # an identity that was previously proven through currentInteractable;
            # callers without that proof keep the original fail-closed result.
            if (
                not expected_class_ptr
                or expected_class_name not in self.ALLOWED_CLASSES
            ):
                return False
            tracked = (int(expected_class_ptr), str(expected_class_name))
            self._tracked_classes[object_ptr] = tracked
        expected_class_ptr, class_name = tracked
        actual_class, native = struct.unpack(
            "<Q8xQ", self.memory.read_bytes(object_ptr + self.OBJECT_KLASS_OFFSET, 24)
        )
        if actual_class != expected_class_ptr or not native:
            return False

        if class_name == "InteractableMicrowave":
            uses_left = self.memory.read_i32(
                object_ptr + self.MICROWAVE_USES_LEFT_OFFSET
            )
            if uses_left < 0:
                raise MemoryReadError(f"Invalid microwave uses remaining: {uses_left}")
            is_cooking = self._read_activity_flag(
                object_ptr, self.MICROWAVE_IS_COOKING_OFFSET
            )
            has_item = self._read_activity_flag(
                object_ptr, self.MICROWAVE_HAS_ITEM_OFFSET
            )
            self._last_microwave_uses = (object_ptr, uses_left)
            return uses_left > 0 or is_cooking or has_item
        if class_name == "InteractableShadyGuy":
            return not self._read_activity_flag(object_ptr, self.SHADY_DONE_OFFSET)
        if class_name == "InteractableEgg":
            return not self._read_activity_flag(object_ptr, self.EGG_DONE_OFFSET)
        if class_name == "InteractableCharacterFight":
            return not self._read_activity_flag(
                object_ptr, self.CHARACTER_FIGHT_DONE_OFFSET
            )
        return not self._read_activity_flag(object_ptr, self.SHRINE_DONE_OFFSET)

    def _read_activity_flag(self, object_ptr: int, offset: int) -> bool:
        value = self.memory.read_u8(object_ptr + offset)
        if value not in (0, 1):
            # Unknown state belongs to the tracker's preserve-and-retry path,
            # not the completed/consumed activity path.
            raise MemoryReadError(
                f"Invalid activity flag at 0x{object_ptr + offset:X}: {value}"
            )
        return value == 1

    def last_microwave_uses(self, object_ptr: int) -> int | None:
        """Reuse the lifecycle sample without another process-memory read."""
        sample = self._last_microwave_uses
        return sample[1] if sample is not None and sample[0] == object_ptr else None

    def _resolve_full_map(self) -> int:
        if self._full_map_ptr:
            try:
                if (
                    self._class_name(self._full_map_ptr) == "FullMap"
                    and self.memory.read_ptr(
                        self._full_map_ptr + self.MANAGED_NATIVE_OFFSET
                    )
                ):
                    return self._full_map_ptr
            except MemoryReadError:
                pass
            self._full_map_ptr = 0
            self._viewport_cache = None
            self._pause_map_root_native = 0
            self._pause_map_render_native = 0

        type_info = self.memory.read_ptr(
            self._module_base + self.FULL_MAP_UI_TYPE_INFO_OFFSET
        )
        if not type_info or self._is_uninitialized_type_info(type_info):
            return 0
        static_fields = self.memory.read_ptr(
            type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        if not static_fields:
            return 0
        delegate = self.memory.read_ptr(
            static_fields + self.FULL_MAP_TOGGLE_DELEGATE_OFFSET
        )
        if not delegate:
            return 0

        delegates = self.memory.read_ptr(delegate + self.MULTICAST_DELEGATES_OFFSET)
        if delegates:
            count = self.memory.read_i32(delegates + self.ARRAY_LENGTH_OFFSET)
            if not 0 <= count <= self.MAX_DELEGATE_ARRAY_LENGTH:
                raise MemoryReadError(f"FullMap delegate count is invalid: {count}")
            first_index = max(0, count - self.MAX_DELEGATES_TO_SCAN)
            for index in range(count - 1, first_index - 1, -1):
                entry = self.memory.read_ptr(
                    delegates
                    + self.ARRAY_DATA_OFFSET
                    + index * self.OBJECT_POINTER_SIZE
                )
                target = (
                    self.memory.read_ptr(entry + self.DELEGATE_TARGET_OFFSET)
                    if entry
                    else 0
                )
                if self._is_live_full_map(target):
                    self._full_map_ptr = target
                    return target

        target = self.memory.read_ptr(delegate + self.DELEGATE_TARGET_OFFSET)
        if self._is_live_full_map(target):
            self._full_map_ptr = target
        return self._full_map_ptr

    @classmethod
    def _is_uninitialized_type_info(cls, value: int) -> bool:
        # IL2CPP runtime metadata tokens have bit 0 set; initialized pointers
        # do not. The upper usage tag alone also matches valid low addresses
        # (e.g. 0x3258C080), so it cannot decide whether a slot is still lazy.
        # A non-token is only a pointer candidate: the normal memory reads and
        # live-object checks below must still succeed before accepting it.
        normalized = int(value)
        return bool(
            0 < normalized <= 0xFFFFFFFF
            and normalized & cls.IL2CPP_METADATA_TOKEN_FLAG
            and normalized & cls.IL2CPP_METADATA_USAGE_TAG_MASK
            == cls.IL2CPP_TYPE_INFO_USAGE_TAG
        )

    def _is_live_full_map(self, object_ptr: int) -> bool:
        if not object_ptr:
            return False
        try:
            return (
                self._class_name(object_ptr) == "FullMap"
                and bool(
                    self.memory.read_ptr(object_ptr + self.MANAGED_NATIVE_OFFSET)
                )
            )
        except MemoryReadError:
            return False

    def _resolve_player_and_detector(self) -> tuple[int, int]:
        player = self._resolve_player()
        return player, self._resolve_detector(player)

    def _resolve_player(self) -> int:
        type_info = self.memory.read_ptr(
            self._module_base + self.MY_PLAYER_TYPE_INFO_OFFSET
        )
        static_fields = self.memory.read_ptr(
            type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        player = self.memory.read_ptr(static_fields + self.MY_PLAYER_INSTANCE_OFFSET)
        if not player:
            raise MemoryReadError("MyPlayer.Instance is not initialized.")
        if player != self._player_ptr:
            self._player_ptr = player
            self._detector_ptr = 0
            self._clear_minimap_cache()
            self._tracked_classes.clear()
        return player

    def _resolve_detector(self, player: int) -> int:
        if self._detector_ptr:
            return self._detector_ptr
        player_input = self.memory.read_ptr(player + self.PLAYER_INPUT_OFFSET)
        detector = self.memory.read_ptr(
            player_input + self.DETECT_INTERACTABLES_OFFSET
        )
        if not detector:
            raise MemoryReadError("DetectInteractables is not initialized.")
        self._detector_ptr = detector
        return detector

    def _resolve_stage_scope(self) -> tuple[int, int]:
        static_fields = self._map_controller_static_fields
        if not static_fields:
            type_info = self.memory.read_ptr(
                self._module_base + self.MAP_CONTROLLER_TYPE_INFO_OFFSET
            )
            static_fields = self.memory.read_ptr(
                type_info + self.CLASS_STATIC_FIELDS_OFFSET
            )
            if not static_fields:
                raise MemoryReadError("MapController static fields are unavailable.")
            self._map_controller_static_fields = static_fields
        stage = self.memory.read_ptr(
            static_fields + self.MAP_CONTROLLER_CURRENT_STAGE_OFFSET
        )
        stage_index = self.memory.read_i32(
            static_fields + self.MAP_CONTROLLER_INDEX_OFFSET
        )
        return stage, stage_index

    def _resolve_map_seed_safe(self) -> int | None:
        try:
            static_fields = self._map_generation_static_fields
            if not static_fields:
                type_info = self.memory.read_ptr(
                    self._module_base
                    + self.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET
                )
                if not type_info or self._is_uninitialized_type_info(type_info):
                    return None
                static_fields = self.memory.read_ptr(
                    type_info + self.CLASS_STATIC_FIELDS_OFFSET
                )
                if not static_fields:
                    return None
                self._map_generation_static_fields = static_fields
            return int(
                self.memory.read_i32(
                    static_fields + self.MAP_GENERATION_MAP_SEED_OFFSET
                )
            )
        except Exception:
            return None

    def _read_current_activity(self, object_ptr: int) -> DetectedMapActivity | None:
        if not object_ptr:
            return None
        class_ptr = self.memory.read_ptr(object_ptr + self.OBJECT_KLASS_OFFSET)
        class_name = self._class_name_from_ptr(class_ptr)
        if class_name not in self.ALLOWED_CLASSES:
            return None

        rarity: int | None = None
        character: int | None = None
        if class_name == "InteractableMicrowave":
            rarity = self.memory.read_i32(object_ptr + self.MICROWAVE_RARITY_OFFSET)
        elif class_name == "InteractableShadyGuy":
            rarity = self.memory.read_i32(object_ptr + self.SHADY_RARITY_OFFSET)
        elif class_name == "InteractableCharacterFight":
            character_data = self.memory.read_ptr(
                object_ptr + self.CHARACTER_FIGHT_CHARACTER_OFFSET
            )
            if not character_data:
                return None
            character = self.memory.read_i32(
                character_data + self.CHARACTER_DATA_CHARACTER_OFFSET
            )
        action_id = action_id_for_interactable(class_name, rarity, character)
        if not action_id:
            return None

        self._tracked_classes[object_ptr] = (class_ptr, class_name)
        if not self.activity_is_active(object_ptr):
            return None
        transform = self._component_transform(object_ptr)
        world_x, _world_y, world_z = self._transform_point(
            transform, (0.0, 0.0, 0.0)
        )
        return DetectedMapActivity(
            object_ptr=object_ptr,
            class_ptr=class_ptr,
            class_name=class_name,
            action_id=action_id,
            world_x=world_x,
            world_z=world_z,
            uses_remaining=self.last_microwave_uses(object_ptr),
        )

    def _component_transform(self, component_ptr: int) -> int:
        native_component = self.memory.read_ptr(
            component_ptr + self.MANAGED_NATIVE_OFFSET
        )
        native_game_object = self.memory.read_ptr(
            native_component + self.NATIVE_COMPONENT_GAME_OBJECT_OFFSET
        )
        handle_root = self.memory.read_ptr(
            native_game_object + self.NATIVE_GAME_OBJECT_HANDLE_ROOT_OFFSET
        )
        handle_owner = self.memory.read_ptr(handle_root + self.HANDLE_ROOT_NEXT_OFFSET)
        handle = self.memory.read_ptr(handle_owner + self.HANDLE_VALUE_OFFSET)
        # Unity uses the low bit as a handle tag.  The live objects observed in
        # this build use an untagged handle, but masking makes the path safe for
        # the tagged variant as well.
        transform = self.memory.read_ptr(handle & ~1)
        if not transform:
            raise MemoryReadError("Component Transform handle is not available.")
        return transform

    def _clear_minimap_cache(self) -> None:
        self._minimap_ui_ptr = 0
        self._minimap_root_native = 0
        self._minimap_renderer_native = 0
        self._minimap_render_native = 0
        self._minimap_viewport_cache = None

    def _read_minimap_projection(
        self,
        player: int,
        client_width: int,
        client_height: int,
        display_scale: float,
    ) -> MinimapProjection | None:
        # Visibility is cheaper than camera and UI geometry. Keep these checks
        # live even while hidden so resuming never waits for the layout timer.
        if not self._read_hud_visible() or self._read_minimap_jammed():
            self._minimap_viewport_cache = None
            return None
        camera, script = struct.unpack(
            "<QQ", self.memory.read_bytes(player + self.PLAYER_MINIMAP_CAMERA_OFFSET, 16)
        )
        if (
            not script
            or self._class_name(script) != "MinimapCamera"
            or not camera
            or self._class_name(camera) != "Camera"
            or self.memory.read_ptr(script + self.MINIMAP_SCRIPT_CAMERA_OFFSET)
            != camera
        ):
            raise MemoryReadError("Minimap camera identity is unavailable.")

        camera_native = self.memory.read_ptr(camera + self.MANAGED_NATIVE_OFFSET)
        if not camera_native:
            raise MemoryReadError("Minimap camera native object is unavailable.")
        orthographic_size = float(
            self.memory.read_float(
                camera_native + self.CAMERA_ORTHOGRAPHIC_SIZE_OFFSET
            )
        )
        projection_x, projection_y = struct.unpack(
            "<f16xf",
            self.memory.read_bytes(camera_native + self.CAMERA_PROJECTION_X_OFFSET, 24),
        )
        camera_values = (orthographic_size, projection_x, projection_y)
        if (
            not all(math.isfinite(value) for value in camera_values)
            or orthographic_size <= 0.0
            or projection_x <= 0.0
            or projection_y <= 0.0
        ):
            raise MemoryReadError("Minimap camera projection is invalid.")
        expected_y = 1.0 / orthographic_size
        tolerance = max(0.0001, expected_y * 0.05)
        if abs(projection_y - expected_y) > tolerance:
            raise MemoryReadError(
                "Minimap orthographic size does not match its projection matrix."
            )
        aspect = projection_y / projection_x
        if not math.isfinite(aspect) or not 0.25 <= aspect <= 4.0:
            raise MemoryReadError(f"Minimap camera aspect is invalid: {aspect}")

        camera_transform = self._component_transform(camera)
        # Reuse each hierarchy node's sampled TRS for all three points. Separate
        # reads can mix camera frames and turn translation into a bogus rotation
        # (or fail the orthogonality check and hide the minimap for one tick).
        camera_origin, camera_right_point, camera_up_point = self._transform_points(
            camera_transform,
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        )
        right_x = camera_right_point[0] - camera_origin[0]
        right_z = camera_right_point[2] - camera_origin[2]
        up_x = camera_up_point[0] - camera_origin[0]
        up_z = camera_up_point[2] - camera_origin[2]
        right_length = math.hypot(right_x, right_z)
        up_length = math.hypot(up_x, up_z)
        if right_length <= 0.0001 or up_length <= 0.0001:
            raise MemoryReadError("Minimap camera ground-plane basis is invalid.")
        right_x, right_z = right_x / right_length, right_z / right_length
        up_x, up_z = up_x / up_length, up_z / up_length
        if abs(right_x * up_x + right_z * up_z) > 0.05:
            raise MemoryReadError("Minimap camera basis is not orthogonal.")

        minimap_ui = self._resolve_minimap_ui()
        root_native, render_native = self._resolve_minimap_native_transforms(
            minimap_ui
        )
        content_rect = self._read_minimap_viewport(
            root_native, render_native, client_width, client_height, display_scale
        )
        center_x = content_rect.left + content_rect.width / 2.0
        center_y = content_rect.top + content_rect.height / 2.0
        radius = min(content_rect.width, content_rect.height) / 2.0
        return MinimapProjection(
            visible=True,
            jammed=False,
            content_rect=content_rect,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
            camera_world_x=float(camera_origin[0]),
            camera_world_z=float(camera_origin[2]),
            camera_right_x=right_x,
            camera_right_z=right_z,
            camera_up_x=up_x,
            camera_up_z=up_z,
            orthographic_size=orthographic_size,
            aspect=aspect,
        )

    def _read_minimap_viewport(
        self,
        root_native: int,
        render_native: int,
        client_width: int,
        client_height: int,
        display_scale: float,
    ) -> MapViewport:
        # Only cache layout; camera pose, zoom, visibility and native identity
        # are still validated on every fast sample. A new surface or DPI/client
        # size invalidates immediately, other UI layout changes within 200 ms.
        key = (root_native, render_native, client_width, client_height, display_scale)
        now = self._clock()
        cached = self._minimap_viewport_cache
        if cached is not None and cached[:5] == key and now < cached[6]:
            return cached[5]
        self._minimap_viewport_cache = None
        render_bounds = self._read_rect_transform_bounds(render_native)
        screen_bounds = self._read_ui_screen_bounds(root_native)
        viewport = self._map_viewport_to_qt(
            render_bounds,
            screen_bounds,
            client_width=client_width,
            client_height=client_height,
            display_scale=display_scale,
        )
        if viewport.width <= 0.0 or viewport.height <= 0.0:
            raise MemoryReadError("Minimap content rectangle is invalid.")
        self._minimap_viewport_cache = (
            *key, viewport, now + self.MINIMAP_GEOMETRY_INTERVAL
        )
        return viewport

    def _resolve_minimap_ui(self) -> int:
        if self._minimap_ui_ptr:
            try:
                if (
                    self._class_name(self._minimap_ui_ptr) == "MinimapUi"
                    and self.memory.read_ptr(
                        self._minimap_ui_ptr + self.MANAGED_NATIVE_OFFSET
                    )
                ):
                    return self._minimap_ui_ptr
            except MemoryReadError:
                pass
            self._clear_minimap_cache()

        type_info = self.memory.read_ptr(
            self._module_base + self.MINIMAP_CAMERA_TYPE_INFO_OFFSET
        )
        if not type_info or self._is_uninitialized_type_info(type_info):
            raise MemoryReadError("MinimapCamera type info is unavailable.")
        static_fields = self.memory.read_ptr(
            type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        delegate = self.memory.read_ptr(
            static_fields + self.MINIMAP_ROTATION_DELEGATE_OFFSET
        )
        if not delegate:
            raise MemoryReadError("Minimap rotation delegate is unavailable.")

        delegates = self.memory.read_ptr(delegate + self.MULTICAST_DELEGATES_OFFSET)
        if delegates:
            count = self.memory.read_i32(delegates + self.ARRAY_LENGTH_OFFSET)
            if not 0 <= count <= self.MAX_DELEGATE_ARRAY_LENGTH:
                raise MemoryReadError(f"Minimap delegate count is invalid: {count}")
            first_index = max(0, count - self.MAX_DELEGATES_TO_SCAN)
            for index in range(count - 1, first_index - 1, -1):
                entry = self.memory.read_ptr(
                    delegates
                    + self.ARRAY_DATA_OFFSET
                    + index * self.OBJECT_POINTER_SIZE
                )
                target = (
                    self.memory.read_ptr(entry + self.DELEGATE_TARGET_OFFSET)
                    if entry
                    else 0
                )
                if self._is_live_component(target, "MinimapUi"):
                    self._minimap_ui_ptr = target
                    return target

        target = self.memory.read_ptr(delegate + self.DELEGATE_TARGET_OFFSET)
        if self._is_live_component(target, "MinimapUi"):
            self._minimap_ui_ptr = target
            return target
        raise MemoryReadError("A live MinimapUi target is unavailable.")

    def _is_live_component(self, object_ptr: int, expected_class: str) -> bool:
        if not object_ptr:
            return False
        try:
            return bool(
                self._class_name(object_ptr) == expected_class
                and self.memory.read_ptr(object_ptr + self.MANAGED_NATIVE_OFFSET)
            )
        except MemoryReadError:
            return False

    def _resolve_minimap_native_transforms(
        self, minimap_ui: int
    ) -> tuple[int, int]:
        managed_transform = self._component_transform(minimap_ui)
        root_native = self.memory.read_ptr(
            managed_transform + self.MANAGED_NATIVE_OFFSET
        )
        if not root_native or self._native_transform_name(root_native) != "Minimap":
            raise MemoryReadError("MinimapUi root Transform is invalid.")
        if (
            root_native != self._minimap_root_native
            or not self._minimap_renderer_native
            or not self._minimap_render_native
            or self._native_transform_name(self._minimap_renderer_native)
            != "MapRenderer"
            or self._native_transform_name(self._minimap_render_native)
            != "RenderTexture"
        ):
            self._minimap_root_native = root_native
            self._minimap_renderer_native = self._find_descendant_native_transform(
                root_native, "MapRenderer"
            )
            self._minimap_render_native = self._find_descendant_native_transform(
                self._minimap_renderer_native, "RenderTexture"
            )
        return root_native, self._minimap_render_native

    def _read_hud_visible(self) -> bool:
        type_info = self.memory.read_ptr(
            self._module_base + self.SAVE_MANAGER_TYPE_INFO_OFFSET
        )
        if not type_info or self._is_uninitialized_type_info(type_info):
            raise MemoryReadError("SaveManager type info is unavailable.")
        static_fields = self.memory.read_ptr(
            type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        save_manager = self.memory.read_ptr(
            static_fields + self.SAVE_MANAGER_INSTANCE_OFFSET
        )
        config = self.memory.read_ptr(save_manager + self.SAVE_MANAGER_CONFIG_OFFSET)
        game_settings = self.memory.read_ptr(
            config + self.CONFIG_GAME_SETTINGS_OFFSET
        )
        show_hud = self.memory.read_i32(
            game_settings + self.GAME_SETTINGS_SHOW_HUD_OFFSET
        )
        if show_hud not in (0, 1):
            raise MemoryReadError(f"HUD visibility value is invalid: {show_hud}")
        return show_hud == 1

    def _read_minimap_jammed(self) -> bool:
        desert_type_info = self.memory.read_ptr(
            self._module_base + self.MAP_EVENTS_DESERT_TYPE_INFO_OFFSET
        )
        if not desert_type_info or self._is_uninitialized_type_info(desert_type_info):
            raise MemoryReadError("MapEventsDesert type info is unavailable.")
        desert_static_fields = self.memory.read_ptr(
            desert_type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        storm_value = self.memory.read_u8(
            desert_static_fields + self.MAP_EVENTS_DESERT_STORM_ACTIVE_OFFSET
        )
        if storm_value not in (0, 1):
            raise MemoryReadError(f"Desert storm value is invalid: {storm_value}")
        if storm_value:
            return True

        challenge_type_info = self.memory.read_ptr(
            self._module_base + self.CHALLENGES_TRACKER_TYPE_INFO_OFFSET
        )
        if (
            not challenge_type_info
            or self._is_uninitialized_type_info(challenge_type_info)
        ):
            raise MemoryReadError("ChallengesTracker type info is unavailable.")
        challenge_static_fields = self.memory.read_ptr(
            challenge_type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        modifier_names = self.memory.read_ptr(
            challenge_static_fields + self.CHALLENGES_MODIFIER_NAMES_OFFSET
        )
        return self._managed_hashset_contains_string(modifier_names, "blind")

    def _managed_hashset_contains_string(
        self, set_address: int, expected: str
    ) -> bool:
        if not set_address:
            return False
        slots = self.memory.read_ptr(set_address + self.HASHSET_SLOTS_OFFSET)
        count = self.memory.read_i32(set_address + self.HASHSET_COUNT_OFFSET)
        last_index = self.memory.read_i32(
            set_address + self.HASHSET_LAST_INDEX_OFFSET
        )
        if not (
            0 <= count <= self.MAX_CHALLENGE_MODIFIERS
            and 0 <= last_index <= self.MAX_CHALLENGE_MODIFIERS
            and count <= last_index
        ):
            raise MemoryReadError(
                f"Challenge modifier HashSet is invalid: count={count}, "
                f"lastIndex={last_index}."
            )
        if count == 0:
            return False
        if not slots:
            raise MemoryReadError("Challenge modifier HashSet slots are unavailable.")
        active_count = 0
        found = False
        for index in range(last_index):
            slot = slots + self.HASHSET_SLOT_START_OFFSET + index * self.HASHSET_SLOT_SIZE
            if self.memory.read_i32(
                slot + self.HASHSET_SLOT_HASH_CODE_OFFSET
            ) < 0:
                continue
            value = self.memory.read_ptr(slot + self.HASHSET_SLOT_VALUE_OFFSET)
            if not value:
                raise MemoryReadError("Challenge modifier HashSet contains null.")
            active_count += 1
            name = self.memory.read_mono_string(value, max_length=64)
            if name is None:
                raise MemoryReadError("Challenge modifier string is unreadable.")
            found = found or name == expected
        if active_count != count:
            raise MemoryReadError(
                "Challenge modifier HashSet read was incomplete."
            )
        return found

    def _read_shady_stock_capture(
        self, map_id: int, *, map_seed: int | None = None
    ) -> MerchantStockCapture | None:
        previous_sample = self._pending_stock_sample
        self._pending_stock_sample = None
        gate = self._read_shady_offer_gate()
        if gate is None:
            return None
        first = self._read_shady_offer_cards(gate[2])
        first = self._read_shady_prices(gate, first)
        if self._read_shady_offer_gate() != gate:
            return None
        second = self._read_shady_offer_cards(gate[2])
        second = self._read_shady_prices(gate, second)
        if first != second or self._read_shady_offer_gate() != gate:
            return None

        # The UI reuses the same picker/buttons for different merchants. Two
        # reads in one poll can both see the previous shop's cards during an
        # opening transition. Confirm the merchant + offers on the next normal
        # throttled poll as well, without adding reads or sleeping the worker.
        sample = (map_id, gate, first)
        if sample != previous_sample:
            self._pending_stock_sample = sample
            return None

        merchant, _levelup, _picker = gate
        class_ptr = self.memory.read_ptr(merchant + self.OBJECT_KLASS_OFFSET)
        rarity = self.memory.read_i32(merchant + self.SHADY_RARITY_OFFSET)
        action_id = action_id_for_interactable("InteractableShadyGuy", rarity)
        if not action_id:
            return None
        self._tracked_classes[merchant] = (class_ptr, "InteractableShadyGuy")
        if not self.activity_is_active(merchant):
            return None
        transform = self._component_transform(merchant)
        world_x, _world_y, world_z = self._transform_point(
            transform, (0.0, 0.0, 0.0)
        )
        self._pending_stock_sample = sample
        return MerchantStockCapture(
            map_id=map_id,
            merchant_object_ptr=merchant,
            marker_id=f"auto:{merchant:X}",
            merchant_rarity=rarity,
            world_x=world_x,
            world_z=world_z,
            items=first,
            class_ptr=class_ptr,
            game_process_identity=self._game_process_identity,
            stage_ptr=self._stage_ptr,
            raw_stage_index=self._stage_index,
            map_seed=map_seed,
        )

    def _read_shady_prices(self, gate, offers):
        """Copy displayed prices; invalid data leaves the item stock usable."""
        try:
            _, _, picker = gate
            buttons = self.memory.read_ptr(picker + self.UPGRADE_PICKER_BUTTONS_OFFSET)
            enriched = []
            for index, offer in enumerate(offers):
                button = self.memory.read_ptr(buttons + self.ARRAY_DATA_OFFSET + index * 8)
                price = self.memory.read_i32(button + self.UPGRADE_BUTTON_PRICE_OFFSET)
                if price < 0:
                    return offers
                enriched.append(replace(offer, price=price))
            return tuple(enriched)
        except Exception:
            return offers

    def _read_shady_offer_gate(self) -> tuple[int, int, int] | None:
        ui_type_info = self.memory.read_ptr(
            self._module_base + self.UI_MANAGER_TYPE_INFO_OFFSET
        )
        if not ui_type_info or self._is_uninitialized_type_info(ui_type_info):
            return None
        ui_static_fields = self.memory.read_ptr(
            ui_type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        ui_manager = self.memory.read_ptr(
            ui_static_fields + self.UI_MANAGER_INSTANCE_OFFSET
        )
        if not self._is_live_component(ui_manager, "UiManager"):
            return None
        encounters = self.memory.read_ptr(
            ui_manager + self.UI_MANAGER_ENCOUNTER_WINDOWS_OFFSET
        )
        if not self._is_live_component(encounters, "EncounterWindows"):
            return None
        if self.memory.read_u8(
            encounters + self.ENCOUNTER_IN_PROGRESS_OFFSET
        ) != 1:
            return None
        levelup = self.memory.read_ptr(
            encounters + self.ENCOUNTER_LEVELUP_SCREEN_OFFSET
        )
        active = self.memory.read_ptr(
            encounters + self.ENCOUNTER_ACTIVE_WINDOW_OFFSET
        )
        if active != levelup or not self._is_live_component(levelup, "LevelupScreen"):
            return None
        if self.memory.read_i32(
            levelup + self.LEVELUP_ENCOUNTER_TYPE_OFFSET
        ) != self.SHADY_ENCOUNTER_TYPE:
            return None
        picker = self.memory.read_ptr(
            levelup + self.LEVELUP_UPGRADE_PICKER_OFFSET
        )
        if not self._is_live_component(picker, "UpgradePicker"):
            return None
        if self.memory.read_i32(
            picker + self.UPGRADE_PICKER_ENCOUNTER_TYPE_OFFSET
        ) != self.SHADY_ENCOUNTER_TYPE:
            return None

        shady_type_info = self.memory.read_ptr(
            self._module_base + self.SHADY_GUY_TYPE_INFO_OFFSET
        )
        if not shady_type_info or self._is_uninitialized_type_info(shady_type_info):
            return None
        shady_static_fields = self.memory.read_ptr(
            shady_type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        merchant = self.memory.read_ptr(
            shady_static_fields + self.SHADY_CURRENTLY_INTERACTING_OFFSET
        )
        if not self._is_live_component(merchant, "InteractableShadyGuy"):
            return None
        return merchant, levelup, picker

    def _read_shady_offer_cards(
        self, picker: int
    ) -> tuple[MerchantOffer, ...]:
        buttons = self.memory.read_ptr(
            picker + self.UPGRADE_PICKER_BUTTONS_OFFSET
        )
        count = self.memory.read_i32(picker + self.UPGRADE_PICKER_COUNT_OFFSET)
        if not 1 <= count <= self.MAX_SHADY_OFFERS or not buttons:
            raise MemoryReadError(f"Shady Guy offer count is invalid: {count}")
        array_length = self.memory.read_i32(buttons + self.ARRAY_LENGTH_OFFSET)
        if not count <= array_length <= self.MAX_UPGRADE_BUTTON_ARRAY_LENGTH:
            raise MemoryReadError(
                f"Shady Guy button array is invalid: {array_length}"
            )

        offers: list[MerchantOffer] = []
        for index in range(count):
            button = self.memory.read_ptr(
                buttons + self.ARRAY_DATA_OFFSET + index * self.OBJECT_POINTER_SIZE
            )
            if not self._is_live_component(button, "UpgradeButton"):
                raise MemoryReadError("Shady Guy offer button is unavailable.")
            if self.memory.read_u8(
                button + self.UPGRADE_BUTTON_IS_ITEM_OFFSET
            ) != 1:
                raise MemoryReadError("Shady Guy offer button is not an item.")
            item_data = self.memory.read_ptr(
                button + self.UPGRADE_BUTTON_ITEM_DATA_OFFSET
            )
            if not item_data or self._class_name(item_data) != "ItemData":
                raise MemoryReadError("Shady Guy ItemData is unavailable.")
            item_id = self.memory.read_i32(
                item_data + self.ITEM_DATA_ITEM_ID_OFFSET
            )
            rarity_value = self.memory.read_i32(
                item_data + self.ITEM_DATA_RARITY_OFFSET
            )
            metadata = _ITEM_METADATA_BY_ID.get(item_id)
            if (
                metadata is None
                or metadata.ui_name is None
                or metadata.rarity is None
                or not 0 <= rarity_value < len(_ITEM_RARITY_BY_VALUE)
                or metadata.rarity != _ITEM_RARITY_BY_VALUE[rarity_value]
            ):
                raise MemoryReadError(
                    f"Shady Guy item metadata is invalid: id={item_id}, "
                    f"rarity={rarity_value}."
                )
            offers.append(
                MerchantOffer(
                    item_id=item_id,
                    canonical_name=metadata.scanner_name,
                    display_name=metadata.ui_name,
                    rarity=metadata.rarity,
                )
            )
        return tuple(offers)

    def _read_viewport(
        self,
        full_map: int,
        client_width: int,
        client_height: int,
        display_scale: float,
    ) -> MapViewport:
        # Escape -> Tab is a second UI. FullMap.mapDisplayTransform keeps
        # pointing at the held-Tab map while the pause panel is visible, so use
        # the pause panel's own MapRender RectTransform in that state.
        native = self._resolve_pause_map_render_native_transform()
        transform = 0
        if not native:
            transform = self.memory.read_ptr(
                full_map + self.FULL_MAP_DISPLAY_TRANSFORM_OFFSET
            )
            native = self.memory.read_ptr(transform + self.MANAGED_NATIVE_OFFSET)
        map_bounds = self._read_rect_transform_bounds(
            native,
            point_reader=(
                (lambda point: self._transform_point_native(native, point))
                if not transform
                else (lambda point: self._transform_point(transform, point))
            ),
        )
        # A borderless Unity window keeps the native-size Win32 client while it
        # renders the UI in the selected in-game resolution.  Dividing Unity
        # coordinates only by Qt's device-pixel ratio therefore works by
        # accident when both resolutions match and shifts/shrinks the markers
        # at 1080p on a 1440p monitor.  The topmost RectTransform in this same
        # hierarchy is the live GameUI surface, so normalize through its actual
        # bounds before entering Qt logical pixels.
        screen_bounds = self._read_ui_screen_bounds(native)
        viewport = self._map_viewport_to_qt(
            map_bounds,
            screen_bounds,
            client_width=client_width,
            client_height=client_height,
            display_scale=display_scale,
        )
        if viewport.width <= 0.0 or viewport.height <= 0.0:
            raise MemoryReadError(f"Full Map viewport is invalid: {viewport}")
        self._viewport_cache = (
            full_map,
            client_width,
            client_height,
            display_scale,
            viewport,
        )
        return viewport

    def _read_rect_transform_bounds(
        self,
        native: int,
        *,
        point_reader: Callable[
            [tuple[float, float, float]], tuple[float, float, float]
        ] | None = None,
    ) -> tuple[float, float, float, float]:
        if not native:
            raise MemoryReadError("RectTransform native object is unavailable.")
        x, y, width, height = struct.unpack(
            "<4f",
            self.memory.read_bytes(native + self.RECT_TRANSFORM_RECT_OFFSET, 16),
        )
        local_corners = (
            (x, y, 0.0),
            (x, y + height, 0.0),
            (x + width, y + height, 0.0),
            (x + width, y, 0.0),
        )
        corners = (
            self._transform_points_native(native, local_corners)
            if point_reader is None
            else tuple(point_reader(point) for point in local_corners)
        )
        coordinates = tuple(
            float(value) for point in corners for value in point[:2]
        )
        if not all(math.isfinite(value) for value in coordinates):
            raise MemoryReadError("RectTransform bounds contain non-finite values.")
        left = min(point[0] for point in corners)
        right = max(point[0] for point in corners)
        bottom = min(point[1] for point in corners)
        top = max(point[1] for point in corners)
        if right <= left or top <= bottom:
            raise MemoryReadError(
                "RectTransform bounds are empty: "
                f"left={left}, bottom={bottom}, right={right}, top={top}."
            )
        return left, bottom, right, top

    def _read_ui_screen_bounds(
        self, native: int
    ) -> tuple[float, float, float, float]:
        return self._read_rect_transform_bounds(
            self._root_native_transform(native)
        )

    def _root_native_transform(self, native: int) -> int:
        access = self.memory.read_ptr(native + self.NATIVE_TRANSFORM_ACCESS_OFFSET)
        index = self.memory.read_i32(native + self.NATIVE_TRANSFORM_INDEX_OFFSET)
        packed_counts = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_COUNTS_OFFSET
        )
        capacity = packed_counts & 0xFFFFFFFF
        count = (packed_counts >> 32) & 0xFFFFFFFF
        if not (0 <= index < count <= capacity <= self.MAX_NATIVE_TRANSFORMS):
            raise MemoryReadError(
                "UI TransformAccess count is invalid: "
                f"index={index}, count={count}, capacity={capacity}."
            )
        parents = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_PARENTS_OFFSET
        )
        native_transforms = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_NATIVE_TRANSFORMS_OFFSET
        )
        if not parents or not native_transforms:
            raise MemoryReadError("UI Transform hierarchy is unavailable.")

        root_index = index
        depth = 0
        while True:
            if depth >= self.MAX_TRANSFORM_DEPTH:
                raise MemoryReadError("UI Transform hierarchy exceeded safe depth.")
            parent = self.memory.read_i32(parents + root_index * 4)
            if parent == -1:
                break
            if not 0 <= parent < count:
                raise MemoryReadError(
                    f"UI Transform parent index is invalid: {parent}."
                )
            root_index = parent
            depth += 1

        root_native = self.memory.read_ptr(
            native_transforms + root_index * self.OBJECT_POINTER_SIZE
        )
        if not root_native:
            raise MemoryReadError("UI root RectTransform is unavailable.")
        return root_native

    @staticmethod
    def _map_viewport_to_qt(
        map_bounds: tuple[float, float, float, float],
        screen_bounds: tuple[float, float, float, float],
        *,
        client_width: int,
        client_height: int,
        display_scale: float,
    ) -> MapViewport:
        map_left, map_bottom, map_right, map_top = map_bounds
        screen_left, screen_bottom, screen_right, screen_top = screen_bounds
        screen_width = screen_right - screen_left
        screen_height = screen_top - screen_bottom
        scale = float(display_scale)
        values = (
            map_left,
            map_bottom,
            map_right,
            map_top,
            screen_left,
            screen_bottom,
            screen_right,
            screen_top,
            screen_width,
            screen_height,
            scale,
        )
        if (
            not all(math.isfinite(float(value)) for value in values)
            or screen_width <= 0.0
            or screen_height <= 0.0
            or int(client_width) <= 0
            or int(client_height) <= 0
            or scale <= 0.0
        ):
            raise MemoryReadError(
                "Full Map coordinate spaces are invalid: "
                f"map={map_bounds}, screen={screen_bounds}, "
                f"client=({client_width}, {client_height}), scale={display_scale}."
            )

        logical_width = float(client_width) / scale
        logical_height = float(client_height) / scale
        return MapViewport(
            left=(map_left - screen_left) / screen_width * logical_width,
            top=(screen_top - map_top) / screen_height * logical_height,
            width=(map_right - map_left) / screen_width * logical_width,
            height=(map_top - map_bottom) / screen_height * logical_height,
        )

    def _resolve_pause_map_render_native_transform(self) -> int:
        type_info = self.memory.read_ptr(
            self._module_base + self.UI_MANAGER_TYPE_INFO_OFFSET
        )
        static_fields = self.memory.read_ptr(
            type_info + self.CLASS_STATIC_FIELDS_OFFSET
        )
        ui_manager = self.memory.read_ptr(
            static_fields + self.UI_MANAGER_INSTANCE_OFFSET
        )
        pause_ui = self.memory.read_ptr(ui_manager + self.UI_MANAGER_PAUSE_OFFSET)
        map_object = self.memory.read_ptr(pause_ui + self.PAUSE_UI_MAP_OFFSET)
        current_object = self.memory.read_ptr(
            pause_ui + self.PAUSE_UI_CURRENT_OFFSET
        )
        if not map_object or current_object != map_object:
            return 0

        root_native = self._game_object_transform_native(map_object)
        if not root_native:
            return 0
        if (
            root_native == self._pause_map_root_native
            and self._pause_map_render_native
            and self._native_transform_name(self._pause_map_render_native)
            == "MapRender"
        ):
            return self._pause_map_render_native

        render_native = self._find_descendant_native_transform(
            root_native,
            "MapRender",
        )
        self._pause_map_root_native = root_native
        self._pause_map_render_native = render_native
        return render_native

    def _game_object_transform_native(self, game_object: int) -> int:
        native_game_object = self.memory.read_ptr(
            game_object + self.MANAGED_NATIVE_OFFSET
        )
        handle_root = self.memory.read_ptr(
            native_game_object + self.NATIVE_GAME_OBJECT_HANDLE_ROOT_OFFSET
        )
        handle_owner = self.memory.read_ptr(handle_root + self.HANDLE_ROOT_NEXT_OFFSET)
        handle = self.memory.read_ptr(handle_owner + self.HANDLE_VALUE_OFFSET)
        managed_transform = self.memory.read_ptr(handle & ~1)
        return self.memory.read_ptr(
            managed_transform + self.MANAGED_NATIVE_OFFSET
        )

    def _native_transform_name(self, native_transform: int) -> str | None:
        native_game_object = self.memory.read_ptr(
            native_transform + self.NATIVE_COMPONENT_GAME_OBJECT_OFFSET
        )
        name_ptr = self.memory.read_ptr(
            native_game_object + self.NATIVE_GAME_OBJECT_NAME_OFFSET
        )
        return self.memory.read_ascii_string(name_ptr) if name_ptr else None

    def _find_descendant_native_transform(
        self,
        root_native: int,
        expected_name: str,
    ) -> int:
        access = self.memory.read_ptr(
            root_native + self.NATIVE_TRANSFORM_ACCESS_OFFSET
        )
        root_index = self.memory.read_i32(
            root_native + self.NATIVE_TRANSFORM_INDEX_OFFSET
        )
        packed_counts = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_COUNTS_OFFSET
        )
        capacity = packed_counts & 0xFFFFFFFF
        count = (packed_counts >> 32) & 0xFFFFFFFF
        if not (
            0 <= root_index < count <= capacity <= self.MAX_NATIVE_TRANSFORMS
        ):
            raise MemoryReadError(
                "Pause Map TransformAccess count is invalid: "
                f"root={root_index}, count={count}, capacity={capacity}."
            )

        parents = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_PARENTS_OFFSET
        )
        native_transforms = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_NATIVE_TRANSFORMS_OFFSET
        )
        for index in range(count):
            native_transform = self.memory.read_ptr(
                native_transforms + index * self.OBJECT_POINTER_SIZE
            )
            if not native_transform:
                continue
            if self._native_transform_name(native_transform) != expected_name:
                continue
            parent = index
            depth = 0
            while parent >= 0 and depth < self.MAX_TRANSFORM_DEPTH:
                if parent == root_index:
                    return native_transform
                parent = self.memory.read_i32(parents + parent * 4)
                depth += 1
        raise MemoryReadError(
            f"Pause Map descendant '{expected_name}' is not available."
        )

    def _transform_point(
        self, transform: int, local_point: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        native = self.memory.read_ptr(transform + self.MANAGED_NATIVE_OFFSET)
        return self._transform_point_native(native, local_point)

    def _transform_point_native(
        self,
        native: int,
        local_point: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        return self._transform_points_native(native, (local_point,))[0]

    def _transform_points(
        self,
        transform: int,
        local_points: tuple[tuple[float, float, float], ...],
    ) -> tuple[tuple[float, float, float], ...]:
        native = self.memory.read_ptr(transform + self.MANAGED_NATIVE_OFFSET)
        return self._transform_points_native(native, local_points)

    def _transform_points_native(
        self,
        native: int,
        local_points: tuple[tuple[float, float, float], ...],
    ) -> tuple[tuple[float, float, float], ...]:
        access, index = struct.unpack(
            "<Qi", self.memory.read_bytes(native + self.NATIVE_TRANSFORM_ACCESS_OFFSET, 12)
        )
        matrices, parents = struct.unpack(
            "<QQ", self.memory.read_bytes(access + self.TRANSFORM_ACCESS_MATRICES_OFFSET, 16)
        )
        if not matrices or not parents or index < 0:
            raise MemoryReadError("Transform hierarchy is not initialized.")

        points = tuple(tuple(float(value) for value in point) for point in local_points)
        depth = 0
        while index >= 0:
            if depth >= self.MAX_TRANSFORM_DEPTH:
                raise MemoryReadError("Transform hierarchy exceeded safe depth.")
            values = struct.unpack(
                "<12f",
                self.memory.read_bytes(
                    matrices + index * self.TRANSFORM_MATRIX_SIZE,
                    self.TRANSFORM_MATRIX_SIZE,
                ),
            )
            translation = values[0:3]
            rotation = values[4:8]
            scale = values[8:11]
            rotated = (
                self._rotate_vector(
                    rotation,
                    (point[0] * scale[0], point[1] * scale[1], point[2] * scale[2]),
                )
                for point in points
            )
            points = tuple(
                (point[0] + translation[0], point[1] + translation[1], point[2] + translation[2])
                for point in rotated
            )
            index = self.memory.read_i32(parents + index * 4)
            depth += 1
        return points

    @staticmethod
    def _rotate_vector(
        quaternion: tuple[float, float, float, float],
        vector: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        qx, qy, qz, qw = quaternion
        vx, vy, vz = vector
        tx = 2.0 * (qy * vz - qz * vy)
        ty = 2.0 * (qz * vx - qx * vz)
        tz = 2.0 * (qx * vy - qy * vx)
        return (
            vx + qw * tx + (qy * tz - qz * ty),
            vy + qw * ty + (qz * tx - qx * tz),
            vz + qw * tz + (qx * ty - qy * tx),
        )

    def _class_name(self, object_ptr: int) -> str | None:
        return self._class_name_from_ptr(
            self.memory.read_ptr(object_ptr + self.OBJECT_KLASS_OFFSET)
        )

    def _class_name_from_ptr(self, class_ptr: int) -> str | None:
        if not class_ptr:
            return None
        name_ptr = self.memory.read_ptr(class_ptr + self.CLASS_NAME_POINTER_OFFSET)
        return self.memory.read_ascii_string(name_ptr) if name_ptr else None
