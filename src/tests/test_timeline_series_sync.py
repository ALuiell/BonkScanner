from unittest.mock import patch

from app import config
from tests.support.compare_runs import build_compare_runs_tab
from tests.support.player_stats import build_recordings_tab
from ui.timeline_controls import (
    LEGACY_COMPARE_RUNS_SERIES_SLOTS_CONFIG_KEY,
    LEGACY_RECORDINGS_SERIES_SLOTS_CONFIG_KEY,
    TIMELINE_SERIES_SLOTS_CONFIG_KEY,
    TimelineSeriesSlots,
)


def test_series_change_in_either_tab_updates_the_other_and_persists() -> None:
    user_config = {}
    with patch.object(config, "user_config", user_config), patch.object(
        config, "save_config"
    ) as save_config:
        shared = TimelineSeriesSlots()
        recordings = build_recordings_tab(timeline_series_slots=shared)
        compare = build_compare_runs_tab(timeline_series_slots=shared)

        recordings._set_slot(0, ("Damage",))
        assert recordings._slots[0] == ("Damage",)
        assert compare._series_slots[0] == ("Damage",)

        compare._set_series_slot(1, ("Luck",))
        assert recordings._slots[1] == ("Luck",)
        assert compare._series_slots[1] == ("Luck",)

        expected = [["Damage"], ["Luck"], [], []]
        assert user_config[TIMELINE_SERIES_SLOTS_CONFIG_KEY] == expected
        assert user_config[LEGACY_RECORDINGS_SERIES_SLOTS_CONFIG_KEY] == expected
        assert user_config[LEGACY_COMPARE_RUNS_SERIES_SLOTS_CONFIG_KEY] == expected
        assert save_config.call_count == 2


def test_shared_slots_migrate_the_existing_recordings_preference_first() -> None:
    recordings_slots = [["Damage"], [], [], []]
    compare_slots = [["Luck"], [], [], []]
    with patch.object(
        config,
        "user_config",
        {
            LEGACY_RECORDINGS_SERIES_SLOTS_CONFIG_KEY: recordings_slots,
            LEGACY_COMPARE_RUNS_SERIES_SLOTS_CONFIG_KEY: compare_slots,
        },
    ):
        assert TimelineSeriesSlots().slots[0] == ("Damage",)
