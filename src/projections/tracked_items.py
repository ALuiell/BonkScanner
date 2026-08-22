"""Pure naming, ordering and colouring for tracked-item rules.

These were `OverlayMixin` static/classmethods, and they were the whole of the
production class-qualified surface the componentization inventory tracked: four
sites in `gui_dialogs.py` named `OverlayMixin.<helper>` because the Twitch
tracked-items dialog needed the overlay's item palette and tag labels. A
class-qualified reference does not follow a method onto a component, so
retiring `OverlayMixin` with those sites in place is exactly the step-14b
breakage the inventory exists to prevent.

Module-level functions retire the failure mode rather than relocate it, the
same move steps 19, 20 and 21d made: a free function has no class to be
orphaned from.

`projections/` may import `core/` only, so nothing here touches
`TrackedItemRule` -- rule *construction* needs that type and stays with its
owner. What lives here is the part that only ever needed item metadata.
"""
from __future__ import annotations

from typing import Any

from core.item_metadata import (
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    available_item_display_names,
    item_display_color,
    normalize_item_name_for_rarity,
    preferred_item_display_name,
)
from core.luck_rarity import game_rarity_name
from projections.item_sort import ITEM_RARITY_SORT_ORDER


def tracked_item_display_name(item_name: str) -> str:
    return preferred_item_display_name(str(item_name))


def tracked_item_rarity_rank(item_name: str) -> int:
    canonical_name = normalize_item_name_for_rarity(str(item_name))
    rarity = ITEM_RARITY_BY_NAME.get(canonical_name)
    return ITEM_RARITY_SORT_ORDER.get(rarity, -1)


def tracked_item_sort_key(item_name: str) -> tuple[int, str]:
    return (-tracked_item_rarity_rank(item_name), tracked_item_display_name(item_name).lower())


def available_tracked_item_names() -> tuple[str, ...]:
    return tuple(sorted(available_item_display_names(), key=tracked_item_sort_key))


#: Group captions for the picker, in the order `tracked_item_sort_key` already
#: produces. The list has been sorted by rarity since it was written; nothing
#: said so, so 87 items read as one arbitrary run.
RARITY_GROUP_LABELS = (
    ("LEGENDARY", game_rarity_name("LEGENDARY")),
    ("RARE", game_rarity_name("RARE")),
    ("UNCOMMON", game_rarity_name("UNCOMMON")),
    ("COMMON", game_rarity_name("COMMON")),
    (None, "Other"),
)


def tracked_item_rarity(item_name: str) -> str | None:
    canonical_name = normalize_item_name_for_rarity(str(item_name))
    return ITEM_RARITY_BY_NAME.get(canonical_name)


def group_tracked_items_by_rarity(item_names) -> list[tuple[str, tuple[str, ...]]]:
    """`(caption, names)` per rarity, empty groups dropped.

    Takes the order it is given rather than re-sorting: the caller passes
    `available_tracked_item_names()`, which is already sorted by rarity and
    then by name, and a second sort here could silently disagree with it.
    """
    buckets: dict[str | None, list[str]] = {}
    for item_name in item_names:
        buckets.setdefault(tracked_item_rarity(item_name), []).append(str(item_name))
    groups = []
    for rarity, caption in RARITY_GROUP_LABELS:
        names = buckets.pop(rarity, [])
        if names:
            groups.append((caption, tuple(names)))
    # Anything with a rarity the captions do not name still has to appear --
    # a silently dropped item is an item the user cannot track.
    leftovers = [name for names in buckets.values() for name in names]
    if leftovers:
        groups.append(("Other", tuple(leftovers)))
    return groups


def tracked_item_color(item_name: str) -> str:
    direct_color = item_display_color(item_name)
    if direct_color:
        return direct_color
    canonical_name = normalize_item_name_for_rarity(str(item_name))
    rarity = ITEM_RARITY_BY_NAME.get(canonical_name)
    return ITEM_RARITY_COLOR_MAP.get(rarity, "#E5E7EB")


def tracked_item_combo_display_name(item_names: list[str] | tuple[str, ...]) -> str:
    return " + ".join(tracked_item_display_name(item_name) for item_name in item_names)


def tracked_rule_color(item_names: list[str] | tuple[str, ...]) -> str:
    if not item_names:
        return "#E5E7EB"
    ranked_items = sorted(
        item_names,
        key=lambda item_name: ITEM_RARITY_SORT_ORDER.get(
            ITEM_RARITY_BY_NAME.get(normalize_item_name_for_rarity(str(item_name))), -1
        ),
        reverse=True,
    )
    return tracked_item_color(ranked_items[0])


def tracked_rule_tag_label(label: str, mode: str) -> str:
    label = str(label).strip() or "Item"
    if mode == "map_1_only":
        lowered = label.casefold()
        if lowered.endswith((" map 1", " map1", " t1")):
            return label
        return f"{label} [Map 1]"
    if mode == "all_run":
        return label
    return f"{label} [{mode}]"


def tracked_rule_display_label(
    rule: dict[str, Any],
    item_names: list[str],
    mode: str,
) -> str:
    raw_label = str(rule.get("label") or " + ".join(item_names))
    if len(item_names) != 1:
        return raw_label
    canonical_name = str(item_names[0])
    preferred_name = tracked_item_display_name(canonical_name)
    default_label = f"{canonical_name} Map 1" if mode == "map_1_only" else canonical_name
    preferred_label = f"{preferred_name} Map 1" if mode == "map_1_only" else preferred_name
    return preferred_label if raw_label == default_label else raw_label


def tracked_item_command_label(row: dict[str, Any]) -> str:
    label = str(row.get("label") or "").strip() or "Item"
    mode = str(row.get("mode") or "")
    if mode != "map_1_only":
        return label

    lowered = label.casefold()
    for suffix in (" map 1", " map1", " t1"):
        if lowered.endswith(suffix):
            label = label[: -len(suffix)].rstrip()
            break
    if label.casefold().endswith(" t1"):
        return label
    return f"{label} T1"


def uses_session_tracked_items(source_config: dict[str, Any], *, default: str = "custom") -> bool:
    return str(source_config.get("tracked_items_source") or default).strip().lower() == "session"


def overlay_rule_id(item_names: list[str] | tuple[str, ...], mode: str) -> str:
    return f"{_folded_item_names(item_names)}_{mode}"


def session_rule_id(item_names: list[str] | tuple[str, ...], mode: str) -> str:
    return f"session_{_folded_item_names(item_names)}_{mode}"


def dedupe_item_names(item_names: list[str] | tuple[str, ...]) -> list[str]:
    deduped: list[str] = []
    for item_name in item_names:
        value = str(item_name).strip()
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _folded_item_names(item_names: list[str] | tuple[str, ...]) -> str:
    folded = "_".join(
        "".join(char.lower() for char in item_name if char.isalnum())
        for item_name in item_names
    )
    return folded or "item"
