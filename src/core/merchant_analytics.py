"""Pure data and aggregation for Shady Guy lifetime analytics."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from typing import Iterable

from core.item_metadata import ITEMS


MERCHANT_RARITY_NAMES = ("white", "blue", "purple", "gold")
MAP_FAMILIES = ("forest_desert", "graveyard")


@dataclass(frozen=True, slots=True)
class MerchantHistoryRecord:
    map_id: str
    merchant_id: str
    map_family: str | None
    stage: int
    merchant_rarity: str
    item_ids: tuple[int, ...]
    v: int = 1


@dataclass(frozen=True, slots=True)
class MerchantAnalyticsRow:
    item_id: int
    display_name: str
    offer_count: int
    merchant_percent: float


@dataclass(frozen=True, slots=True)
class MerchantAnalyticsSnapshot:
    merchants: int
    offers: int
    rarity_counts: tuple[tuple[str, int], ...]
    rows: tuple[MerchantAnalyticsRow, ...]


def stable_history_ids(
    runtime_map_id: int,
    merchant_object_ptr: int,
    *,
    game_process_identity: str = "",
    map_seed: int | None = None,
    stage: int | None = None,
) -> tuple[str, str]:
    """Return opaque IDs that survive a BonkScanner restart in one game process."""

    map_key = (
        f"merchant-map-v1:{game_process_identity}:{map_seed}:"
        f"{stage}:{int(runtime_map_id)}"
    )
    map_id = hashlib.sha256(map_key.encode("utf-8")).hexdigest()[:32]
    merchant_id = hashlib.sha256(
        f"merchant-v1:{map_id}:{int(merchant_object_ptr)}".encode("ascii")
    ).hexdigest()[:32]
    return map_id, merchant_id


def merchant_family_from_context(map_context) -> str | None:
    if map_context is None or not getattr(map_context, "activity_max", None):
        return None
    return "graveyard" if bool(getattr(map_context, "is_graveyard", False)) else "forest_desert"


def aggregate_merchant_history(
    records: Iterable[MerchantHistoryRecord],
    *,
    map_family: str | None = None,
    stage: int | None = None,
    merchant_rarity: str | None = None,
    search: str = "",
) -> MerchantAnalyticsSnapshot:
    selected = tuple(
        record
        for record in records
        if (map_family is None or record.map_family == map_family)
        and (stage is None or record.stage == stage)
        and (merchant_rarity is None or record.merchant_rarity == merchant_rarity)
    )
    merchants = len(selected)
    offers = sum(len(record.item_ids) for record in selected)
    rarity_counts = Counter(record.merchant_rarity for record in selected)
    occurrences = Counter(item_id for record in selected for item_id in record.item_ids)
    containing = Counter()
    for record in selected:
        containing.update(set(record.item_ids))

    metadata = {item.item_id: item for item in ITEMS}
    needle = str(search or "").strip().casefold()
    rows = []
    for item_id, count in occurrences.items():
        item = metadata.get(item_id)
        display_name = (
            item.ui_name or item.scanner_name
            if item is not None
            else f"Unknown item #{item_id}"
        )
        searchable = " ".join(
            (
                display_name,
                str(item_id),
                getattr(item, "scanner_name", ""),
                getattr(item, "enum_name", ""),
            )
        ).casefold()
        if needle and needle not in searchable:
            continue
        percent = (containing[item_id] / merchants * 100.0) if merchants else 0.0
        rows.append(MerchantAnalyticsRow(item_id, display_name, count, percent))
    rows.sort(key=lambda row: (-row.offer_count, row.display_name.casefold(), row.item_id))
    return MerchantAnalyticsSnapshot(
        merchants=merchants,
        offers=offers,
        rarity_counts=tuple((name, rarity_counts.get(name, 0)) for name in MERCHANT_RARITY_NAMES),
        rows=tuple(rows),
    )
