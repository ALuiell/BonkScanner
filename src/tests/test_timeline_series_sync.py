from unittest.mock import patch

import pytest

from app import config
from tests.support.compare_runs import build_compare_runs_tab
from tests.support.player_stats import build_recordings_tab
from ui.timeline_controls import (
    LEGACY_COMPARE_RUNS_SERIES_SLOTS_CONFIG_KEY,
    LEGACY_RECORDINGS_SERIES_SLOTS_CONFIG_KEY,
    TIMELINE_SERIES_SLOTS_CONFIG_KEY,
    TIMELINE_POWERUPS_CONFIG_KEY,
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


def test_failed_slot_persistence_rolls_back_the_shared_value() -> None:
    shared = TimelineSeriesSlots(slots=(("Damage",), (), (), ()))
    observed = []
    shared.subscribe(observed.append)

    with patch(
        "ui.timeline_controls.save_timeline_series_slots",
        side_effect=OSError("config unavailable"),
    ), pytest.raises(OSError, match="config unavailable"):
        shared.set_slot(0, ("Luck",))

    assert shared.slots[0] == ("Damage",)
    assert observed == []


def test_unsuccessful_slot_save_result_rolls_back_the_shared_value() -> None:
    shared = TimelineSeriesSlots(slots=(("Damage",), (), (), ()))

    with patch(
        "ui.timeline_controls.save_timeline_series_slots",
        return_value=config.ConfigSaveResult(False, "verification failed"),
    ), pytest.raises(OSError, match="verification failed"):
        shared.set_slot(0, ("Luck",))

    assert shared.slots[0] == ("Damage",)


def test_broken_slot_subscriber_does_not_starve_the_next_tab() -> None:
    shared = TimelineSeriesSlots(slots=(("Damage",), (), (), ()))
    observed = []
    shared.subscribe(
        lambda _slots: (_ for _ in ()).throw(RuntimeError("tab deleted"))
    )
    shared.subscribe(observed.append)

    with patch("ui.timeline_controls.save_timeline_series_slots"):
        shared.set_slot(0, ("Luck",))

    assert shared.slots[0] == ("Luck",)
    assert observed == [(("Luck",), (), (), ())]


def test_powerups_migrate_out_of_slots_and_sync_independently() -> None:
    user_config = {TIMELINE_SERIES_SLOTS_CONFIG_KEY:
                   [["Damage"], ["@powerups"], ["Luck"], []]}
    with patch.object(config, "user_config", user_config), patch.object(config, "save_config"):
        shared = TimelineSeriesSlots()
        recordings = build_recordings_tab(timeline_series_slots=shared)
        compare = build_compare_runs_tab(timeline_series_slots=shared)
        assert shared.powerups_enabled
        assert shared.slots == (("Damage",), (), ("Luck",), ())
        recordings.on_recording_powerups_changed(False)
        assert not recordings._powerups_enabled
        assert not compare._powerups_enabled
        assert user_config[TIMELINE_POWERUPS_CONFIG_KEY] is False
        compare.on_compare_run_powerups_changed(True)
        assert recordings._powerups_enabled
        assert compare._powerups_enabled
        shared.set_slot(1, ("Difficulty",))
        assert shared.slots[1] == ("Difficulty",)
        assert shared.powerups_enabled
        assert TimelineSeriesSlots().powerups_enabled
        assert TimelineSeriesSlots().slots == shared.slots


def test_explicit_powerups_off_overrides_legacy_slot() -> None:
    with patch.object(config, "user_config", {
        TIMELINE_SERIES_SLOTS_CONFIG_KEY: [["@powerups"], [], [], []],
        TIMELINE_POWERUPS_CONFIG_KEY: False,
    }):
        shared = TimelineSeriesSlots()
        assert not shared.powerups_enabled
        assert all(not slot for slot in shared.slots)


def test_failed_powerups_save_restores_config_and_does_not_notify_tabs() -> None:
    user_config = {TIMELINE_POWERUPS_CONFIG_KEY: False}
    with patch.object(config, "user_config", user_config), patch.object(
        config, "save_config", return_value=config.ConfigSaveResult(False, "disk full")
    ):
        shared = TimelineSeriesSlots()
        observed = []
        shared.subscribe(observed.append)
        with pytest.raises(OSError, match="disk full"):
            shared.set_powerups_enabled(True)
        assert not shared.powerups_enabled
        assert user_config == {TIMELINE_POWERUPS_CONFIG_KEY: False}
        assert observed == []
