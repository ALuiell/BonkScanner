from __future__ import annotations

from math import isfinite

from app.snapshot_store import LiveSnapshotStore
from projections import formatting


class PlayerStatsMixin:
    def _ensure_live_snapshot_store(self) -> LiveSnapshotStore:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.snapshot_store
        # No coordinator means an app double built without __init__. Constructing
        # one here would bind an overlay HTTP port, so those keep a bare store.
        store = self.__dict__.get("_live_snapshot_store")
        if store is None:
            store = LiveSnapshotStore()
            self.__dict__["_live_snapshot_store"] = store
        return store

    # Backward-compatible attribute access over LiveSnapshotStore's fields.
    # Production code should call _ensure_live_snapshot_store() and use its
    # methods directly; these properties exist so external pokes (tests, and
    # any object.__new__()-built app double that never runs __init__) keep
    # working unchanged.
    @property
    def player_stats_last_known_items(self):
        return self._ensure_live_snapshot_store().last_known_items

    @player_stats_last_known_items.setter
    def player_stats_last_known_items(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_items = value

    @property
    def player_stats_last_known_weapons(self):
        return self._ensure_live_snapshot_store().last_known_weapons

    @player_stats_last_known_weapons.setter
    def player_stats_last_known_weapons(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_weapons = value

    @property
    def player_stats_last_known_tomes(self):
        return self._ensure_live_snapshot_store().last_known_tomes

    @player_stats_last_known_tomes.setter
    def player_stats_last_known_tomes(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_tomes = value

    @property
    def player_stats_last_known_damage_sources(self):
        return self._ensure_live_snapshot_store().last_known_damage_sources

    @player_stats_last_known_damage_sources.setter
    def player_stats_last_known_damage_sources(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_damage_sources = value

    @property
    def player_stats_last_known_banishes(self):
        return self._ensure_live_snapshot_store().last_known_banishes

    @player_stats_last_known_banishes.setter
    def player_stats_last_known_banishes(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_banishes = value

    @property
    def player_stats_live_banishes(self):
        return self._ensure_live_snapshot_store().live_banishes

    @player_stats_live_banishes.setter
    def player_stats_live_banishes(self, value) -> None:
        self._ensure_live_snapshot_store().live_banishes = value

    @property
    def player_stats_last_seed(self):
        return self._ensure_live_snapshot_store().last_seed

    @player_stats_last_seed.setter
    def player_stats_last_seed(self, value) -> None:
        self._ensure_live_snapshot_store().last_seed = value

    @property
    def player_stats_last_run_timer(self):
        return self._ensure_live_snapshot_store().last_run_timer

    @player_stats_last_run_timer.setter
    def player_stats_last_run_timer(self, value) -> None:
        self._ensure_live_snapshot_store().last_run_timer = value


    @classmethod
    def _item_total_count(cls, items) -> int:
        return formatting._item_total_count(items)

    @classmethod
    def format_items_rarity_summary_rich_text(cls, items) -> str:
        return formatting.format_items_rarity_summary_rich_text(items)

    @classmethod
    def sort_items_for_display(cls, items, mode: str | None) -> tuple[str, ...]:
        return formatting.sort_items_for_display(items, mode)

    @classmethod
    def _item_rarity_rank(cls, item_text: str) -> int:
        return formatting._item_rarity_rank(item_text)


    @staticmethod
    def format_duration(seconds: int) -> str:
        return formatting.format_duration(seconds)

    @staticmethod
    def format_elapsed_time(seconds: float | int) -> str:
        return formatting.format_elapsed_time(seconds)

    @classmethod
    def format_in_game_time(cls, seconds: float | None) -> str:
        return formatting.format_in_game_time(seconds)

    @staticmethod
    def format_mob_kills(value: int | None, kps: int | None = None) -> str:
        return formatting.format_mob_kills(value, kps)

    @staticmethod
    def format_kps_averages(
        minute_avg_kps: int | None,
        five_minute_avg_kps: int | None,
    ) -> str:
        return formatting.format_kps_averages(minute_avg_kps, five_minute_avg_kps)

    @staticmethod
    def format_damage_source_value(value: int | float) -> str:
        return formatting.format_damage_source_value(value)

    @staticmethod
    def format_player_level(value: int | None) -> str:
        return formatting.format_player_level(value)

    @staticmethod
    def format_items(items) -> str:
        return formatting.format_items(items)


    @classmethod
    def format_snapshot_new_items(cls, previous_snapshot, snapshot) -> str:
        return formatting.format_snapshot_new_items(previous_snapshot, snapshot)

    @classmethod
    def format_snapshot_item_gains_preview(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        return formatting.format_snapshot_item_gains_preview(previous_snapshot, snapshot, segment_snapshots=segment_snapshots)

    @classmethod
    def diff_new_items(cls, previous_items, current_items) -> tuple[str, ...]:
        return formatting.diff_new_items(previous_items, current_items)

    @classmethod
    def diff_item_gains(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        return formatting.diff_item_gains(previous_items, current_items)

    @classmethod
    def summarize_item_segment_changes(cls, snapshots) -> dict[str, tuple[tuple[str, int], ...]]:
        return formatting.summarize_item_segment_changes(snapshots)

    @classmethod
    def format_snapshot_item_changes_details(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        return formatting.format_snapshot_item_changes_details(previous_snapshot, snapshot, segment_snapshots=segment_snapshots)

    @classmethod
    def format_item_gains_by_rarity(
        cls,
        gains: tuple[tuple[str, int], ...],
        *,
        max_items: int | None = None,
    ) -> str:
        return formatting.format_item_gains_by_rarity(gains, max_items=max_items)

    @classmethod
    def format_snapshot_compare_summary(
        cls,
        base_snapshot,
        snapshot,
        *,
        base_index: int | None,
        current_index: int | None,
        segment_snapshots=(),
    ) -> str:
        return formatting.format_snapshot_compare_summary(base_snapshot, snapshot, base_index=base_index, current_index=current_index, segment_snapshots=segment_snapshots)

    @classmethod
    def format_banishes_rich_text(cls, banishes) -> str:
        return formatting.format_banishes_rich_text(banishes)

    @staticmethod
    def merge_banish_appearance_order(previous_banishes, current_banishes) -> tuple[str, ...]:
        return formatting.merge_banish_appearance_order(previous_banishes, current_banishes)

    @classmethod
    def _item_counts(cls, items) -> dict[str, int]:
        return formatting._item_counts(items)

    @classmethod
    def build_stage_summary(cls, snapshots) -> list[dict[str, str]]:
        return formatting.build_stage_summary(snapshots)

    @classmethod
    def format_items_rich_text(cls, items) -> str:
        return formatting.format_items_rich_text(items)

    @staticmethod
    def _split_item_stack_suffix(item_text: str) -> tuple[str, str]:
        return formatting._split_item_stack_suffix(item_text)

    @staticmethod
    def _normalize_item_name_for_rarity(item_name: str) -> str:
        return formatting._normalize_item_name_for_rarity(item_name)

    @staticmethod
    def _normalize_item_name_for_display(item_name: str) -> str:
        return formatting._normalize_item_name_for_display(item_name)

    @staticmethod
    def calculate_player_chests_per_minute(stats) -> float | None:
        return formatting.calculate_player_chests_per_minute(stats)

    @classmethod
    def resolve_snapshot_chests_per_minute(cls, snapshot) -> float | None:
        return formatting.resolve_snapshot_chests_per_minute(snapshot)

    @staticmethod
    def format_chests_per_minute(value: float | None) -> str:
        return formatting.format_chests_per_minute(value)

    @classmethod
    def format_powerups_duration(cls, stats) -> str:
        return formatting.format_powerups_duration(stats)

    def format_live_powerups(self, stats) -> str:
        formatter = getattr(self.live_run_tracker, "format_powerups_summary", None)
        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
        if callable(formatter) and callable(snapshot_reader):
            try:
                if getattr(snapshot_reader(), "available", False) is True:
                    return formatter(include_left_word=False)
            except Exception:
                pass
        return self.format_powerups_duration(stats)


    def format_live_powerups_card(self, stats) -> tuple[str, dict[str, str]]:
        values = {name: "--" for name in ("Rage", "Clock", "Shield", "Stonks")}
        title = "Powerups"

        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
        snapshot = snapshot_reader() if callable(snapshot_reader) else None
        if getattr(snapshot, "available", False):
            pm_display = str(getattr(snapshot, "powerup_multiplier_display", "--") or "--")
            if pm_display != "--":
                title = f"Powerups (PM {pm_display})"
            active_by_name = {
                str(getattr(effect, "name", "")): effect
                for effect in getattr(snapshot, "active", ()) or ()
            }
            for effect_name in values:
                effect = active_by_name.get(effect_name)
                if effect is not None:
                    left_text = f"({self.format_seconds_compact(effect.remaining_seconds)}s)"
                    if (
                        getattr(effect, "pickup_ui", None) is None
                        or getattr(effect, "expires_ui", None) is None
                    ):
                        values[effect_name] = left_text
                    else:
                        values[effect_name] = (
                            f"{effect.pickup_ui} -> {effect.expires_ui} "
                            f"{left_text}"
                        )
                    continue
                duration = (
                    getattr(snapshot, "clock_duration_seconds", None)
                    if effect_name == "Clock"
                    else getattr(snapshot, "standard_duration_seconds", None)
                )
                if duration is not None:
                    values[effect_name] = f"-- ({self.format_seconds_compact(duration)}s)"
            return title, values

        stat = (stats or {}).get("Powerup Multiplier")
        try:
            powerup_multiplier = float(getattr(stat, "value", None))
        except (TypeError, ValueError):
            return title, values
        if not isfinite(powerup_multiplier):
            return title, values

        pm_display = str(getattr(stat, "display_value", "") or "").strip()
        if pm_display:
            title = f"Powerups (PM {pm_display})"
        standard_duration = self.format_seconds_compact(15.0 * powerup_multiplier)
        clock_duration = self.format_seconds_compact(12.0 * powerup_multiplier)
        values["Rage"] = f"-- ({standard_duration}s)"
        values["Clock"] = f"-- ({clock_duration}s)"
        values["Shield"] = f"-- ({standard_duration}s)"
        values["Stonks"] = f"-- ({standard_duration}s)"
        return title, values

    @staticmethod
    def format_seconds_compact(value: float) -> str:
        return formatting.format_seconds_compact(value)

    @staticmethod
    def chests_card_values(
        opened_by_stage: dict[int, int] | None,
        total_by_stage: dict[int, int] | None,
        opened: int | None,
        total: int | None,
        paid: int | None,
        key_procs: int | None,
        free: int | None,
        keys: int | None,
        expected: float | None,
        total_is_minimum: bool = False,
    ) -> dict[str, str]:
        return formatting.chests_card_values(
            opened_by_stage,
            total_by_stage,
            opened,
            total,
            paid,
            key_procs,
            free,
            keys,
            expected,
            total_is_minimum,
        )


