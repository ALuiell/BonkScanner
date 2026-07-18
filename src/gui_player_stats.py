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


    def format_live_powerups(self, stats) -> str:
        formatter = getattr(self.live_run_tracker, "format_powerups_summary", None)
        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
        if callable(formatter) and callable(snapshot_reader):
            try:
                if getattr(snapshot_reader(), "available", False) is True:
                    return formatter(include_left_word=False)
            except Exception:
                pass
        return formatting.format_powerups_duration(stats)


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
                    left_text = f"({formatting.format_seconds_compact(effect.remaining_seconds)}s)"
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
                    values[effect_name] = f"-- ({formatting.format_seconds_compact(duration)}s)"
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
        standard_duration = formatting.format_seconds_compact(15.0 * powerup_multiplier)
        clock_duration = formatting.format_seconds_compact(12.0 * powerup_multiplier)
        values["Rage"] = f"-- ({standard_duration}s)"
        values["Clock"] = f"-- ({clock_duration}s)"
        values["Shield"] = f"-- ({standard_duration}s)"
        values["Stonks"] = f"-- ({standard_duration}s)"
        return title, values

