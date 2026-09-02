"""Domain vocabulary and projection math for Full Map activity markers.

The memory adapter, renderer and settings UI need the same stable action
identifiers.  Keeping those identifiers and the world-to-map transform here
prevents UI labels from becoming persisted values and lets the projection be
tested without Qt or a running game.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class MapMarkerAction:
    id: str
    family: str
    label: str
    variant: str | None
    icon_name: str
    color: str
    outline_color: str = "#03080F"
    manual_only: bool = False

    @property
    def display_name(self) -> str:
        return f"{self.label} · {self.variant}" if self.variant else self.label

    @property
    def settings_icon_name(self) -> str:
        """Use the light counterpart when an icon stands on the dark dialog."""

        suffix = "_dark"
        return (
            self.icon_name[: -len(suffix)]
            if self.icon_name.endswith(suffix)
            else self.icon_name
        )


@dataclass(frozen=True, slots=True)
class MapViewport:
    """The map texture rectangle in game-client, top-left-origin pixels."""

    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


@dataclass(frozen=True, slots=True)
class WorldMapMarker:
    marker_id: str
    action_id: str
    world_x: float
    world_z: float
    source: str = "automatic"
    object_ptr: int = 0


@dataclass(frozen=True, slots=True)
class MapMarkerSnapshot:
    map_id: int = 0
    map_open: bool = False
    world_size: float = 0.0
    viewport: MapViewport | None = None
    markers: tuple[WorldMapMarker, ...] = ()


@dataclass(frozen=True, slots=True)
class MarkerPaletteRow:
    action_id: str
    left: float
    top: float
    width: float
    height: float

    def contains(self, x: float, y: float) -> bool:
        return (
            self.left <= x <= self.left + self.width
            and self.top <= y <= self.top + self.height
        )


@dataclass(frozen=True, slots=True)
class MarkerPalette:
    anchor_x: float
    anchor_y: float
    rows: tuple[MarkerPaletteRow, ...]
    selected_action_id: str | None = None


_RARITIES = (
    ("white", "White", "#F2F2E9"),
    ("blue", "Blue", "#48A9FF"),
    ("purple", "Purple", "#B378FF"),
    ("gold", "Gold", "#F5C84B"),
)
_RARITY_IDS = tuple(rarity_id for rarity_id, _label, _color in _RARITIES)
_SHADY_GUY_COLORS = {
    "white": "#16F28B",
    "blue": "#00D7FF",
    "purple": "#E04FFF",
    "gold": "#FF9F0A",
}


MAP_MARKER_ACTIONS: tuple[MapMarkerAction, ...] = tuple(
    MapMarkerAction(
        id=f"microwave_{rarity_id}",
        family="microwave",
        label="Microwave",
        variant=rarity_label,
        icon_name="microwave_dark" if rarity_id == "white" else "microwave",
        color=color,
    )
    for rarity_id, rarity_label, color in _RARITIES
) + tuple(
    MapMarkerAction(
        id=f"shady_guy_{rarity_id}",
        family="shady_guy",
        label="Shady Guy",
        variant=rarity_label,
        icon_name="shady_guy_dark",
        color=_SHADY_GUY_COLORS[rarity_id],
        outline_color="#03080F",
    )
    for rarity_id, rarity_label, _color in _RARITIES
) + (
    MapMarkerAction(
        id="magnet_shrine",
        family="magnet_shrine",
        label="Magnet Shrine",
        variant=None,
        icon_name="magnet",
        color="#55D6BE",
    ),
    MapMarkerAction(
        id="moai",
        family="moai",
        label="Moai",
        variant=None,
        icon_name="moai_dark",
        color="#B7C0CA",
    ),
    MapMarkerAction(
        id="balance_shrine",
        family="balance_shrine",
        label="Shrine of Balance",
        variant=None,
        icon_name="balance_shrine_dark",
        color="#D8BC78",
    ),
    MapMarkerAction(
        id="challenge_shrine",
        family="challenge_shrine",
        label="Challenge Shrine",
        variant=None,
        icon_name="challenge",
        color="#EF6A5B",
    ),
    MapMarkerAction(
        id="boss_curse",
        family="boss_curse",
        label="Boss Curse",
        variant=None,
        icon_name="boss_curse",
        color="#D85CFF",
    ),
    MapMarkerAction(
        id="egg",
        family="egg",
        label="Egg",
        variant=None,
        icon_name="egg",
        color="#BBD86A",
    ),
    MapMarkerAction(
        id="sus_bush",
        family="sus_bush",
        label="Sus Bush",
        variant=None,
        icon_name="sus_bush",
        color="#39B96C",
    ),
)

MAP_MARKER_ACTION_BY_ID = {action.id: action for action in MAP_MARKER_ACTIONS}

INTERACTABLE_ACTIONS = {
    "InteractableShrineMagnet": "magnet_shrine",
    "InteractableShrineMoai": "moai",
    "InteractableShrineBalance": "balance_shrine",
    "InteractableShrineChallenge": "challenge_shrine",
    "InteractableShrineCursed": "boss_curse",
    "InteractableEgg": "egg",
}

# InteractableCharacterFight is shared by several character encounters.  Only
# the Bush encounter belongs to the map-marker allowlist, so the class alone is
# not enough evidence.  CharacterData.eCharacter identifies Bush in this build.
BUSH_CHARACTER_VALUE = 9

MOUSE_BINDINGS = {"mouse_middle", "mouse4", "mouse5"}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "win")
_MODIFIER_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "option": "alt",
    "meta": "win",
    "super": "win",
}
_MOUSE_ALIASES = {
    "middlemouse": "mouse_middle",
    "middle_mouse": "mouse_middle",
    "mousemiddle": "mouse_middle",
    "mouse_4": "mouse4",
    "xbutton1": "mouse4",
    "backbutton": "mouse4",
    "mouse_5": "mouse5",
    "xbutton2": "mouse5",
    "forwardbutton": "mouse5",
}
_RESERVED_SINGLE_KEYS = {
    "tab",
    "escape",
    "esc",
    "space",
    "w",
    "a",
    "s",
    "d",
    "left",
    "right",
    "up",
    "down",
}
_NAMED_KEYS = {
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "pageup",
    "pagedown",
    "pause",
    "print",
    "return",
    "enter",
}
_KEY_TOKEN = re.compile(r"^[a-z0-9]$|^f(?:[1-9]|1[0-9]|2[0-4])$")


def normalize_input_binding(value: Any) -> str | None:
    """Return a stable keyboard/mouse binding, or ``None`` when unsafe.

    Plain movement keys and the Full Map controls are deliberately refused.
    Modified versions such as ``Ctrl+W`` remain available because they do not
    collide with ordinary movement.
    """

    raw = str(value or "").strip().lower().replace(" ", "")
    if not raw:
        return None
    raw = _MOUSE_ALIASES.get(raw, raw)
    if raw in MOUSE_BINDINGS:
        return raw

    parts = [part for part in raw.split("+") if part]
    if not parts:
        return None
    base = parts[-1]
    modifiers: set[str] = set()
    for part in parts[:-1]:
        modifier = _MODIFIER_ALIASES.get(part, part)
        if modifier not in _MODIFIER_ORDER:
            return None
        modifiers.add(modifier)

    base = {"esc": "escape", "pgup": "pageup", "pgdown": "pagedown"}.get(base, base)
    if not (_KEY_TOKEN.fullmatch(base) or base in _NAMED_KEYS):
        return None
    if not modifiers and base in _RESERVED_SINGLE_KEYS:
        return None

    ordered = [modifier for modifier in _MODIFIER_ORDER if modifier in modifiers]
    return "+".join((*ordered, base))


def display_input_binding(value: Any) -> str:
    binding = normalize_input_binding(value)
    if binding is None:
        return "Not assigned"
    mouse_labels = {
        "mouse_middle": "Middle Mouse",
        "mouse4": "Mouse 4",
        "mouse5": "Mouse 5",
    }
    if binding in mouse_labels:
        return mouse_labels[binding]
    labels = {
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "win": "Win",
        "escape": "Esc",
        "pageup": "Page Up",
        "pagedown": "Page Down",
        "return": "Enter",
    }
    return "+".join(labels.get(part, part.upper()) for part in binding.split("+"))


def normalize_map_marker_hotkeys(value: Any) -> list[dict[str, str]]:
    """Validate bindings, preserve order and keep the first use of each input."""

    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    normalized: list[dict[str, str]] = []
    seen_inputs: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        input_binding = normalize_input_binding(raw.get("input"))
        action_id = str(raw.get("action") or "").strip().lower()
        if (
            input_binding is None
            or input_binding in seen_inputs
            or action_id not in MAP_MARKER_ACTION_BY_ID
        ):
            continue
        seen_inputs.add(input_binding)
        normalized.append({"input": input_binding, "action": action_id})
    return normalized


def normalize_map_marker_settings(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    try:
        scale = float(source.get("scale", 1.0))
    except (TypeError, ValueError, OverflowError):
        scale = 1.0
    return {
        "enabled": bool(source.get("enabled", False)),
        # Automatic discovery is deliberately opt-in. Manual placement still
        # needs the Full Map projection, so it remains available independently.
        "automatic_discovery": bool(source.get("automatic_discovery", False)),
        "scale": max(0.5, min(scale, 3.0)),
        "hotkeys": normalize_map_marker_hotkeys(source.get("hotkeys")),
    }


def action_id_for_interactable(
    class_name: str,
    rarity: int | None = None,
    character: int | None = None,
) -> str | None:
    """Map one allow-listed IL2CPP class and optional rarity to a stable action."""

    if class_name == "InteractableMicrowave":
        family = "microwave"
    elif class_name == "InteractableShadyGuy":
        family = "shady_guy"
    elif class_name == "InteractableCharacterFight":
        return "sus_bush" if character == BUSH_CHARACTER_VALUE else None
    else:
        return INTERACTABLE_ACTIONS.get(class_name)

    if rarity is None or not 0 <= int(rarity) < len(_RARITY_IDS):
        return None
    return f"{family}_{_RARITY_IDS[int(rarity)]}"


def project_world_to_map(
    world_x: float,
    world_z: float,
    *,
    world_size: float,
    viewport: MapViewport,
) -> tuple[float, float] | None:
    """Project game X/Z onto the Full Map's top-left-origin texture rectangle.

    ``QueueRevealFog`` maps both axes from ``[-worldSize/2, +worldSize/2]`` to
    texture coordinates.  Unity texture Y grows up while the overlay's Y grows
    down, so Z is inverted only at the final screen conversion.
    """

    size = float(world_size)
    if size <= 0.0 or viewport.width <= 0.0 or viewport.height <= 0.0:
        return None
    u = (float(world_x) + size / 2.0) / size
    v = (float(world_z) + size / 2.0) / size
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None
    return (
        viewport.left + u * viewport.width,
        viewport.bottom - v * viewport.height,
    )


def map_marker_screen_geometry(
    world_x: float,
    world_z: float,
    *,
    world_size: float,
    viewport: MapViewport,
    scale: float = 1.0,
) -> tuple[float, float, float] | None:
    """Return the clamped visual centre and diameter of a map marker."""

    point = project_world_to_map(
        world_x,
        world_z,
        world_size=world_size,
        viewport=viewport,
    )
    if point is None:
        return None
    normalized_scale = max(0.5, min(float(scale), 3.0))
    icon_size = float(max(18, int(round(28 * normalized_scale))))
    half = icon_size / 2.0
    center_x, center_y = point
    inset = half + max(2.0, icon_size / 11.0)
    if viewport.width >= inset * 2.0:
        center_x = min(
            max(center_x, viewport.left + inset),
            viewport.right - inset,
        )
    if viewport.height >= inset * 2.0:
        center_y = min(
            max(center_y, viewport.top + inset),
            viewport.bottom - inset,
        )
    return center_x, center_y, icon_size


def unproject_map_to_world(
    screen_x: float,
    screen_y: float,
    *,
    world_size: float,
    viewport: MapViewport,
) -> tuple[float, float] | None:
    """Return game X/Z for a point inside the Full Map texture rectangle."""

    size = float(world_size)
    if size <= 0.0 or viewport.width <= 0.0 or viewport.height <= 0.0:
        return None
    if not viewport.contains(float(screen_x), float(screen_y)):
        return None
    u = (float(screen_x) - viewport.left) / viewport.width
    v = (viewport.bottom - float(screen_y)) / viewport.height
    return (u * size - size / 2.0, v * size - size / 2.0)


def build_marker_palette(
    anchor_x: float,
    anchor_y: float,
    *,
    viewport: MapViewport,
    scale: float = 1.0,
    selected_action_id: str | None = None,
) -> MarkerPalette:
    """Build the clamped hold-menu geometry used by input and the painter."""

    factor = max(0.75, min(float(scale), 2.0))
    # The complete palette is taller than the original marker set. Scale the
    # menu down just enough to keep every row reachable inside the visible map.
    base_total_height = (
        6.0 * 2.0
        + len(MAP_MARKER_ACTIONS) * 30.0
        + max(0, len(MAP_MARKER_ACTIONS) - 1) * 3.0
    )
    if base_total_height > 0.0 and base_total_height * factor > viewport.height:
        factor = max(0.01, viewport.height / base_total_height)
    row_width = 224.0 * factor
    row_height = 30.0 * factor
    gap = 3.0 * factor
    padding = 6.0 * factor
    total_height = (
        padding * 2.0
        + len(MAP_MARKER_ACTIONS) * row_height
        + max(0, len(MAP_MARKER_ACTIONS) - 1) * gap
    )
    left = float(anchor_x) + 18.0 * factor
    if left + row_width + padding * 2.0 > viewport.right:
        left = float(anchor_x) - row_width - padding * 2.0 - 18.0 * factor
    left = min(
        max(viewport.left, left),
        max(viewport.left, viewport.right - row_width - padding * 2.0),
    )
    top = min(
        max(viewport.top, float(anchor_y) - total_height / 2.0),
        max(viewport.top, viewport.bottom - total_height),
    )
    rows = tuple(
        MarkerPaletteRow(
            action_id=action.id,
            left=left + padding,
            top=top + padding + index * (row_height + gap),
            width=row_width,
            height=row_height,
        )
        for index, action in enumerate(MAP_MARKER_ACTIONS)
    )
    return MarkerPalette(
        anchor_x=float(anchor_x),
        anchor_y=float(anchor_y),
        rows=rows,
        selected_action_id=(
            selected_action_id
            if selected_action_id in MAP_MARKER_ACTION_BY_ID
            else None
        ),
    )


def select_marker_palette_action(
    palette: MarkerPalette, screen_x: float, screen_y: float
) -> MarkerPalette:
    selected = next(
        (
            row.action_id
            for row in palette.rows
            if row.contains(float(screen_x), float(screen_y))
        ),
        None,
    )
    if selected == palette.selected_action_id:
        return palette
    return MarkerPalette(
        anchor_x=palette.anchor_x,
        anchor_y=palette.anchor_y,
        rows=palette.rows,
        selected_action_id=selected,
    )
