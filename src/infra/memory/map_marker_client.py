"""Read-only IL2CPP adapter for Full Map activity markers.

The offsets in this module are intentionally isolated from the tracker and Qt
renderer.  They were verified live against the current game build on
2026-08-21; a future game update can therefore fail/reconnect here without
turning a stale read into a plausible marker position.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any, Callable

from core.map_markers import MapViewport, action_id_for_interactable
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


@dataclass(frozen=True, slots=True)
class MapMemoryFrame:
    map_id: int
    map_open: bool
    world_size: float
    viewport: MapViewport | None
    current_activity: DetectedMapActivity | None


class MapMarkerMemoryClient:
    MODULE_NAME = "GameAssembly.dll"

    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    MANAGED_NATIVE_OFFSET = 0x10

    # Before IL2CPP initializes a type-info usage slot, 64-bit builds can keep
    # a tagged 32-bit metadata token there instead of an Il2CppClass pointer.
    # FullMap was observed as 0x2000A397 during startup. Dereferencing that token
    # at +CLASS_STATIC_FIELDS_OFFSET turns a normal waiting state into a Win32
    # partial-copy error and forces the tracker through its reconnect backoff.
    IL2CPP_METADATA_USAGE_TAG_MASK = 0xE0000000
    IL2CPP_TYPE_INFO_USAGE_TAG = 0x20000000

    MY_PLAYER_TYPE_INFO_OFFSET = 0x2F620F8
    MY_PLAYER_INSTANCE_OFFSET = 0x08
    PLAYER_INPUT_OFFSET = 0x48
    DETECT_INTERACTABLES_OFFSET = 0x20
    CURRENT_INTERACTABLE_OFFSET = 0x28

    MAP_CONTROLLER_TYPE_INFO_OFFSET = 0x2F58E08
    MAP_CONTROLLER_INDEX_OFFSET = 0x08
    MAP_CONTROLLER_CURRENT_STAGE_OFFSET = 0x18

    UI_MANAGER_TYPE_INFO_OFFSET = 0x2F9A528
    UI_MANAGER_INSTANCE_OFFSET = 0x00
    UI_MANAGER_PAUSE_OFFSET = 0x40
    PAUSE_UI_MAP_OFFSET = 0x30
    PAUSE_UI_CURRENT_OFFSET = 0x38

    FULL_MAP_UI_TYPE_INFO_OFFSET = 0x2F9AF30
    FULL_MAP_WORLD_SIZE_OFFSET = 0x28
    FULL_MAP_DISPLAY_TRANSFORM_OFFSET = 0x50
    FULL_MAP_OPEN_COUNT_OFFSET = 0x60

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
    ) -> None:
        if memory is None and not process_name:
            raise ValueError("process_name is required when memory is not provided.")
        self.module_name = module_name
        self._owns_memory = memory is None
        self.memory = memory or ProcessMemory(str(process_name))
        self._module_base = int(self.memory.module_base_address(self.module_name))
        self._full_map_ptr = 0
        self._player_ptr = 0
        self._detector_ptr = 0
        self._map_controller_static_fields = 0
        self._stage_ptr = 0
        self._stage_index = -1
        self._map_was_open = False
        self._viewport_cache: tuple[int, int, int, float, MapViewport] | None = None
        self._pause_map_root_native = 0
        self._pause_map_render_native = 0
        self._tracked_classes: dict[int, tuple[int, str]] = {}

    def close(self) -> None:
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
    ) -> MapMemoryFrame:
        previous_full_map = self._full_map_ptr
        full_map = self._resolve_full_map()
        if not full_map:
            raise FullMapNotReadyError("Active FullMap instance is not available yet.")
        if full_map != previous_full_map:
            self._player_ptr = 0
            self._detector_ptr = 0
            self._map_was_open = False
            self._viewport_cache = None
            self._pause_map_root_native = 0
            self._pause_map_render_native = 0
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
            if map_open
            else None
        )
        self._map_was_open = map_open

        player = self._resolve_player()
        stage, stage_index = self._resolve_stage_scope()
        if stage != self._stage_ptr or stage_index != self._stage_index:
            self._stage_ptr = stage
            self._stage_index = stage_index
            self._tracked_classes.clear()
            self._viewport_cache = None
        current_activity = None
        if automatic_discovery and sample_automatic_discovery:
            detector = self._resolve_detector(player)
            current_ptr = self.memory.read_ptr(
                detector + self.CURRENT_INTERACTABLE_OFFSET
            )
            current_activity = self._read_current_activity(current_ptr)
        elif not automatic_discovery:
            # Do not retain or walk automatic-discovery state while the opt-in
            # setting is off. Full Map/player/stage reads remain necessary for
            # manual placement and its run-boundary cleanup.
            self._detector_ptr = 0
            self._tracked_classes.clear()
        return MapMemoryFrame(
            # FullMap can outlive a run, and MyPlayer can survive a stage
            # transition. Combining both with MapController.currentStage/index
            # makes either boundary clear the run-scoped marker ledger.
            map_id=(
                ((full_map & 0xFFFFFFFFFFFFFFFF) << 160)
                | ((player & 0xFFFFFFFFFFFFFFFF) << 96)
                | ((stage & 0xFFFFFFFFFFFFFFFF) << 32)
                | (stage_index & 0xFFFFFFFF)
            ),
            map_open=map_open,
            world_size=world_size,
            viewport=viewport,
            current_activity=current_activity,
        )

    def activity_is_active(self, object_ptr: int) -> bool:
        tracked = self._tracked_classes.get(int(object_ptr))
        if not tracked:
            return False
        expected_class_ptr, class_name = tracked
        if self.memory.read_ptr(object_ptr) != expected_class_ptr:
            return False
        if not self.memory.read_ptr(object_ptr + self.MANAGED_NATIVE_OFFSET):
            return False

        if class_name == "InteractableMicrowave":
            uses_left = self.memory.read_i32(
                object_ptr + self.MICROWAVE_USES_LEFT_OFFSET
            )
            is_cooking = bool(
                self.memory.read_u8(object_ptr + self.MICROWAVE_IS_COOKING_OFFSET)
            )
            has_item = bool(
                self.memory.read_u8(object_ptr + self.MICROWAVE_HAS_ITEM_OFFSET)
            )
            return uses_left > 0 or is_cooking or has_item
        if class_name == "InteractableShadyGuy":
            return not bool(self.memory.read_u8(object_ptr + self.SHADY_DONE_OFFSET))
        if class_name == "InteractableEgg":
            return not bool(self.memory.read_u8(object_ptr + self.EGG_DONE_OFFSET))
        if class_name == "InteractableCharacterFight":
            return not bool(
                self.memory.read_u8(object_ptr + self.CHARACTER_FIGHT_DONE_OFFSET)
            )
        return not bool(self.memory.read_u8(object_ptr + self.SHRINE_DONE_OFFSET))

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
        delegate = self.memory.read_ptr(static_fields)
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
                    delegates + self.ARRAY_DATA_OFFSET + index * 8
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
        normalized = int(value)
        return bool(
            0 < normalized <= 0xFFFFFFFF
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

    def _read_current_activity(self, object_ptr: int) -> DetectedMapActivity | None:
        if not object_ptr:
            return None
        class_ptr = self.memory.read_ptr(object_ptr)
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
        if point_reader is None:
            point_reader = lambda point: self._transform_point_native(native, point)
        corners = tuple(
            point_reader(point)
            for point in (
                (x, y, 0.0),
                (x, y + height, 0.0),
                (x + width, y + height, 0.0),
                (x + width, y, 0.0),
            )
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

        root_native = self.memory.read_ptr(native_transforms + root_index * 8)
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
            native_transform = self.memory.read_ptr(native_transforms + index * 8)
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
        access = self.memory.read_ptr(native + self.NATIVE_TRANSFORM_ACCESS_OFFSET)
        index = self.memory.read_i32(native + self.NATIVE_TRANSFORM_INDEX_OFFSET)
        matrices = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_MATRICES_OFFSET
        )
        parents = self.memory.read_ptr(
            access + self.TRANSFORM_ACCESS_PARENTS_OFFSET
        )
        if not matrices or not parents or index < 0:
            raise MemoryReadError("Transform hierarchy is not initialized.")

        point = tuple(float(value) for value in local_point)
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
            point = self._rotate_vector(
                rotation,
                (
                    point[0] * scale[0],
                    point[1] * scale[1],
                    point[2] * scale[2],
                ),
            )
            point = (
                point[0] + translation[0],
                point[1] + translation[1],
                point[2] + translation[2],
            )
            index = self.memory.read_i32(parents + index * 4)
            depth += 1
        return point

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
        return self._class_name_from_ptr(self.memory.read_ptr(object_ptr))

    def _class_name_from_ptr(self, class_ptr: int) -> str | None:
        if not class_ptr:
            return None
        name_ptr = self.memory.read_ptr(class_ptr + self.CLASS_NAME_POINTER_OFFSET)
        return self.memory.read_ascii_string(name_ptr) if name_ptr else None
