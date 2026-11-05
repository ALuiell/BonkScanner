"""Shared current stat values, their consumers, and historical isolation."""
from __future__ import annotations

import src  # noqa: F401
import unittest
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import config
from app.read_sources import DISPLAY_STATS
from app.refresh_coordinator import RefreshCoordinator, RefreshTickContext
from app.refresh_tasks import build_refresh_coordinator
from core.stats.live import current_player_stats
from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL, PlayerStatValue, PlayerStatsSnapshot, PowerupReadHealth
from core.tracker.live_run import LiveRunTracker
from core.tracker.snapshots import LiveRunSnapshot
from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError
from projections.in_game import project_in_game_overlay
from projections.in_game_html import build_stats_overlay_html
from projections.obs import build_overlay_state_from_snapshot
from projections.twitch import format_luck
from projections.vod import build_vod_capture_payload
from tests.support.player_stats import (
    RecordingItemsSectionView, RecordingStatCardsView, build_live_stats_tab,
)
from tests.support.refresh_tasks import build_refresh_tasks
from tests.test_player_stats import build_player_stats_memory


def stat(label, value):
    return PlayerStatValue(PLAYER_STAT_SPEC_BY_LABEL[label], value)


class CurrentStatsTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.tracker = LiveRunTracker(clock=lambda: self.now)
        self.snapshot = LiveRunSnapshot(
            captured_at=100.0, game_time_seconds=10.0, map_seed=42,
            stats={label: stat(label, 1.0) for label in (
                "Luck", "Difficulty", "XP Gain", "Powerup Multiplier", "Damage",
            )},
        )
        self.tracker.update(self.snapshot)
        self.now = 101.0

    def publish(self):
        self.tracker.update_fast_luck(2.0)
        self.tracker.update_live_stats({"Difficulty": 0.5, "XP Gain": 3.0})
        self.tracker.update_powerups(SimpleNamespace(
            powerup_multiplier=2.5, powerup_multiplier_captured_at=self.now,
        ))

    def test_all_four_values_share_one_boundary_without_mutating_history(self):
        before = deepcopy(self.snapshot)
        self.publish()
        runtime = self.tracker.runtime_snapshot()
        values = current_player_stats(runtime)
        self.assertEqual({key: values[key].value for key in values}, {
            "Luck": 2.0, "Difficulty": 0.5, "XP Gain": 3.0,
            "Powerup Multiplier": 2.5, "Damage": 1.0,
        })
        self.assertEqual(self.snapshot, before)
        self.assertEqual(runtime.latest_snapshot, before)
        self.assertEqual(len(self.tracker.snapshots), 1)
        self.assertEqual(build_vod_capture_payload(runtime).stats, before.stats)
        values.clear()
        self.assertEqual(len(self.tracker.live_stats()), 5)

    def test_new_full_sample_wins_until_the_next_fast_read(self):
        self.publish()
        self.now = 102.0
        newer = replace(self.snapshot, captured_at=self.now, game_time_seconds=12.0,
                        stats={key: stat(key, 4.0) for key in self.snapshot.stats})
        self.tracker.update(newer)
        self.assertEqual(self.tracker.live_stats(), newer.stats)
        self.now = 102.5
        self.tracker.update_live_stats({"Difficulty": 0.75})
        self.assertEqual(self.tracker.live_stats()["Difficulty"].value, 0.75)

    def test_failure_expiry_and_zero_are_distinct(self):
        self.publish()
        self.tracker.update_fast_luck(0.0)
        self.tracker.update_live_stats({"Difficulty": None, "XP Gain": 0.0})
        values = self.tracker.live_stats()
        self.assertEqual(values["Luck"].value, 0.0)
        self.assertEqual(values["Difficulty"].value, 1.0)
        self.assertEqual(values["XP Gain"].value, 0.0)
        self.now = 104.1
        values = self.tracker.live_stats()
        self.assertEqual(values["Luck"].value, 1.0)
        self.assertEqual(values["XP Gain"].value, 1.0)
        self.assertEqual(values["Powerup Multiplier"].value, 2.5)
        self.now = 109.1
        self.assertEqual(self.tracker.live_stats(), self.snapshot.stats)

    def test_failed_full_stat_does_not_hide_a_usable_fast_value(self):
        self.publish()
        self.now = 102.0
        self.tracker.update(replace(self.snapshot, captured_at=self.now,
                                    stats={"XP Gain": stat("XP Gain", None)}))
        self.assertEqual(self.tracker.live_stats()["XP Gain"].value, 3.0)

    def test_cached_multiplier_keeps_its_physical_timestamp(self):
        self.publish()
        self.now = 102.0
        newer = replace(self.snapshot, captured_at=102.0,
                        stats={"Powerup Multiplier": stat("Powerup Multiplier", 3.0)})
        self.tracker.update(newer)
        self.now = 102.5
        self.tracker.update_powerups(SimpleNamespace(
            powerup_multiplier=2.5, powerup_multiplier_captured_at=101.0,
        ))
        self.assertEqual(self.tracker.live_stats()["Powerup Multiplier"].value, 3.0)

    def test_multiplier_health_is_independent_of_effects_health(self):
        self.assertFalse(self.tracker.update_powerups(SimpleNamespace(
            powerup_multiplier=2.5, powerup_multiplier_captured_at=self.now,
            status_effects_health=PowerupReadHealth(available=False, complete=False),
        )))
        self.assertEqual(self.tracker.live_stats()["Powerup Multiplier"].value, 2.5)
        self.tracker.update_powerups(SimpleNamespace(
            powerup_multiplier=4.0, powerup_multiplier_captured_at=self.now,
            multiplier_health=PowerupReadHealth(available=False, complete=False),
        ))
        self.assertEqual(self.tracker.live_stats()["Powerup Multiplier"].value, 1.0)

    def test_new_run_and_process_loss_clear_old_fast_readings(self):
        self.publish()
        self.now = 102.0
        new_run = replace(self.snapshot, captured_at=102.0, game_time_seconds=1.0)
        self.tracker.update(new_run)
        self.assertEqual(self.tracker.live_stats(), new_run.stats)
        self.publish()
        self.tracker.mark_read_failed(no_game=True)
        self.assertEqual(self.tracker.live_stats(), new_run.stats)

    def test_completed_run_and_unaccepted_clock_reset_use_retained_sample(self):
        self.publish()
        self.tracker.update_fast_run_timer(1.0)
        self.assertEqual(self.tracker.live_stats(), self.snapshot.stats)
        self.tracker.update_fast_run_timer(11.0)
        self.tracker.mark_run_completed()
        self.assertEqual(self.tracker.live_stats(), self.snapshot.stats)

    def test_projections_agree_on_current_values_and_preserve_full_sample(self):
        self.publish()
        runtime = self.tracker.runtime_snapshot()
        projection = project_in_game_overlay(runtime)
        self.assertEqual(projection.luck, 2.0)
        html = build_stats_overlay_html(
            projection.latest_snapshot, ["Difficulty", "XP Gain", "Powerup Multiplier"],
            0, 11.0, 600.0, False, live_stats=projection.stats,
        )
        self.assertIn("50%", html)
        self.assertIn("3x", html)
        self.assertIn("2.5x", html)
        overlay = build_overlay_state_from_snapshot(runtime, {
            "widgets": [{"id": "stats", "enabled": True,
                         "selected_stats": list(self.snapshot.stats)}],
        })
        obs = {row["label"]: row["value"] for row in overlay["stats"]}
        self.assertEqual(obs["XP Gain"], "3x")
        self.assertEqual(obs["Difficulty"], "50%")
        self.assertEqual(obs["Powerup Multiplier"], "2.5x")
        self.assertEqual(format_luck(runtime, lambda _key, template, **kw: template.format(**kw)),
                         format_luck(SimpleNamespace(luck=2.0, loot_stats=runtime.loot_stats),
                                     lambda _key, template, **kw: template.format(**kw)))

    def test_live_tab_repaints_both_layouts_and_historical_render_stays_old(self):
        self.publish()
        view = build_live_stats_tab(live_run_tracker=lambda: self.tracker)
        expanded = Mock()
        compact = Mock()
        view._stat_value_rows = {"XP Gain": expanded}
        view._compact_stat_value_rows = {"XP Gain": compact}
        view.set_live_stats(self.tracker.live_stats())
        expanded.setText.assert_called_with("3x")
        compact.setText.assert_called_with("3x")
        view._items_section = RecordingItemsSectionView()
        view._stat_cards = RecordingStatCardsView()
        view.display_player_stats(self.snapshot.stats, live=False)
        expanded.setText.assert_called_with("1x")
        view.display_player_stats(self.snapshot.stats)
        expanded.setText.assert_called_with("3x")
        recorded = PlayerStatsSnapshot(elapsed_seconds=10, captured_at=100.0,
                                       game_time_seconds=10.0, stats=deepcopy(self.snapshot.stats))
        view._vod_snapshots = lambda: [recorded]
        view.display_player_stats_snapshot(recorded)
        expanded.setText.assert_called_with("1x")
        view.display_player_stats_snapshot(recorded, live_capture=True)
        expanded.setText.assert_called_with("3x")
        self.assertEqual(recorded.stats, self.snapshot.stats)


class DisplayReadTests(unittest.TestCase):
    def test_narrow_read_uses_exactly_two_floats_and_matches_full_read(self):
        memory = build_player_stats_memory()
        entries = 0x20000500
        for label, value in (("Difficulty", 0.75), ("XP Gain", 2.5)):
            memory.floats[entries + PLAYER_STAT_SPEC_BY_LABEL[label].offset] = value
        client = PlayerStatsClient(memory=memory)
        with patch.object(memory, "read_float", wraps=memory.read_float) as reads:
            narrow = client.get_display_stats()
            self.assertEqual(reads.call_count, 2)
        full = client.get_player_stats()
        self.assertEqual(narrow, {key: full[key].value for key in narrow})
        del memory.floats[entries + PLAYER_STAT_SPEC_BY_LABEL["Difficulty"].offset]
        self.assertEqual(client.get_display_stats(), {"Difficulty": None, "XP Gain": 2.5})

    def test_scheduled_pass_is_one_second_shares_reads_and_republishes_obs(self):
        now = [100.0]
        tracker = LiveRunTracker(clock=lambda: now[0])
        tracker.update(LiveRunSnapshot(captured_at=99.0, stats={}, game_time_seconds=1.0))
        reader = Mock(return_value={"Difficulty": 0.5, "XP Gain": 3.0})
        client = SimpleNamespace(resolve_owner_stats=lambda: 123, get_luck=lambda _owner: 2.0,
                                 get_display_stats=reader)
        service, world = build_refresh_tasks(
            stats_client=client, tracker=tracker, tab_active=True,
            widget_refresh_active=lambda widget: widget == "stats",
        )
        painted = []
        world.view.set_live_stats = painted.append
        context = RefreshTickContext(1, now[0])
        service._publish_fast_luck(context)
        service._publish_fast_display_stats(context)
        service._publish_fast_display_stats(context)
        service._publish_live_stats_view()
        self.assertEqual(reader.call_count, 1)
        self.assertIsNotNone(context.metadata_for(DISPLAY_STATS))
        self.assertEqual(painted[-1]["XP Gain"].value, 3.0)
        self.assertTrue(world.overlay_syncs)
        with patch.object(service, "_should_refresh_passive_items", return_value=True), \
             patch.object(service, "_refresh_passive_items_task", side_effect=lambda ctx: service._publish_fast_display_stats(ctx)):
            coordinator = build_refresh_coordinator(service, refresh_full_snapshot=lambda **_kw: True,
                                                     coordinator=RefreshCoordinator(clock=lambda: now[0]))
            coordinator.tick()
            initial = reader.call_count
            now[0] = 100.5
            coordinator.tick()
            self.assertEqual(reader.call_count, initial)
            now[0] = 101.0
            coordinator.tick()
            self.assertEqual(reader.call_count, initial + 1)

    def test_failed_read_clears_only_its_values_and_pinned_view_is_not_repainted(self):
        tracker = LiveRunTracker(clock=lambda: 100.0)
        tracker.update(LiveRunSnapshot(captured_at=99.0, stats={"XP Gain": stat("XP Gain", 1.0)},
                                       game_time_seconds=1.0))
        tracker.update_live_stats({"XP Gain": 3.0})
        service, world = build_refresh_tasks(
            tracker=tracker, tab_active=True, pinned=True,
            stats_client=SimpleNamespace(resolve_owner_stats=lambda: 123,
                get_display_stats=Mock(side_effect=MemoryReadError("missing"))),
        )
        world.view.set_live_stats = Mock()
        service._publish_fast_display_stats(RefreshTickContext(1, 100.0))
        service._publish_live_stats_view()
        self.assertEqual(tracker.live_stats()["XP Gain"].value, 1.0)
        world.view.set_live_stats.assert_not_called()

    def test_inventory_failure_does_not_starve_current_stats_or_overlay_publication(self):
        tracker = LiveRunTracker(clock=lambda: 100.0)
        tracker.update(LiveRunSnapshot(captured_at=99.0, stats={}, game_time_seconds=1.0))
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 123, get_luck=lambda _owner: 2.0,
            get_display_stats=lambda _owner: {"Difficulty": 0.5, "XP Gain": 3.0},
            get_passive_items=Mock(side_effect=MemoryReadError("inventory unavailable")),
        )
        service, world = build_refresh_tasks(
            stats_client=client, tracker=tracker, tab_active=True,
            widget_refresh_active=lambda widget: widget == "stats",
        )
        painted = []
        world.view.set_live_stats = painted.append
        self.assertFalse(service._refresh_passive_items_task(RefreshTickContext(1, 100.0)))
        self.assertEqual(painted[-1]["XP Gain"].value, 3.0)
        self.assertTrue(world.overlay_syncs)

    def test_stats_widget_can_demand_existing_multiplier_task(self):
        service, _ = build_refresh_tasks()
        with patch.object(config, "IN_GAME_OVERLAY", {
            "enabled": True, "widgets": {"stats": {"enabled": True,
                "selected_stats": ["Powerup Multiplier"]}},
        }):
            self.assertTrue(service._should_refresh_powerup_tracker())


if __name__ == "__main__":
    unittest.main()
