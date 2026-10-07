from __future__ import annotations

import src  # noqa: F401
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from app.roll_analytics import RollAnalyticsService
from core.character_passives import (
    CHARACTER_PASSIVE_SPECS, CharacterPassiveSnapshot, CharacterPassiveStatus,
    CharacterPassiveEffectSnapshot, CharacterPassiveEffectKind,
)
from core.roll_analytics import confirmed_roll_counts, stable_roll_scope, aggregate_roll_counts
from core.stats.formats import PlayerStatFormat
from core.stats.types import ChaosTomeSnapshot, ChaosTomeStatSnapshot
from infra.roll_history_store import RollHistoryStore, validate_roll_history


def chaos(counts):
    return ChaosTomeSnapshot(sum(counts.values()), tuple(
        ChaosTomeStatSnapshot(i, str(i), 1, PlayerStatFormat.FLAT, n) for i, n in counts.items()
    ))


def dice(counts):
    spec = next(spec for spec in CHARACTER_PASSIVE_SPECS if spec.is_gamba)
    return CharacterPassiveSnapshot(spec.character_id, spec.character_name, spec.passive_id,
        spec.passive_name, spec.runtime_class, sum(counts.values()), CharacterPassiveStatus.SUPPORTED,
        tuple(CharacterPassiveEffectSnapshot(str(i), str(i), 1, PlayerStatFormat.FLAT,
              CharacterPassiveEffectKind.PERMANENT_ROLL, i, n) for i, n in counts.items()))


class RollHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "roll_history.json"
        self.store = RollHistoryStore(self.path)
        self.addCleanup(self.store.close)
        self.scope = stable_roll_scope("123:456", 100, 200)

    def test_reconnect_restart_and_source_denominators(self):
        self.store.observe(self.scope, {"chaos": {0: 2, 12: 1}, "dice": {30: 4}}, collecting=True)
        self.store.observe(self.scope, {"chaos": {0: 2, 12: 1}, "dice": {30: 4}}, collecting=True)
        self.store.close()
        reopened = RollHistoryStore(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.observe(self.scope, {"chaos": {0: 2, 12: 1}}, collecting=True), (0, False))
        reopened.observe(self.scope, {"chaos": {0: 3, 12: 1}}, collecting=True)
        snapshot = reopened.snapshot("chaos")
        self.assertEqual(snapshot.total, 4)
        self.assertEqual(snapshot.rows[0].percent, 75)
        self.assertEqual(reopened.snapshot("dice").total, 4)
        self.assertEqual(len(snapshot.rows), 27)

    def test_new_owner_or_process_is_a_new_scope(self):
        for scope in (self.scope, stable_roll_scope("123:456", 101, 201),
                      stable_roll_scope("123:457", 100, 200)):
            self.store.observe(scope, {"chaos": {12: 2}}, collecting=True)
        self.assertEqual(self.store.snapshot("chaos").total, 6)

    def test_lower_and_returning_snapshots_do_not_recount(self):
        for count in (10, 3, 0, 10, 11):
            self.store.observe(self.scope, {"chaos": {12: count}}, collecting=True)
        self.assertEqual(self.store.snapshot("chaos").total, 11)

    def test_off_checkpoints_and_resume_baseline_exclude_paused_rolls(self):
        self.store.observe(self.scope, {"chaos": {12: 10}}, collecting=True)
        self.store.observe(self.scope, {"chaos": {12: 20}}, collecting=False)
        self.store.observe(self.scope, {"chaos": {12: 30}}, collecting=True, baseline_sources={"chaos"})
        self.store.observe(self.scope, {"chaos": {12: 31}}, collecting=True)
        self.assertEqual(self.store.snapshot("chaos").total, 11)

    def test_atomic_failure_keeps_totals_and_checkpoint_retryable(self):
        self.store.observe(self.scope, {"chaos": {12: 2}}, collecting=True)
        original = self.path.read_bytes()
        with patch("infra.roll_history_store.os.replace", side_effect=OSError("disk full")):
            self.store.observe(self.scope, {"chaos": {12: 5}}, collecting=True)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.store.snapshot("chaos").total, 2)
        self.assertFalse(self.store.writable)
        self.assertIn("disk full", self.store.error)
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_second_instance_reads_history_but_cannot_write(self):
        self.store.observe(self.scope, {"chaos": {12: 2}}, collecting=True)
        second = RollHistoryStore(self.path)
        self.addCleanup(second.close)
        self.assertFalse(second.writable)
        self.assertEqual(second.snapshot("chaos").total, 2)
        second.observe(self.scope, {"chaos": {12: 7}}, collecting=True)
        self.assertEqual(second.snapshot("chaos").total, 2)

    def test_corrupt_file_is_preserved(self):
        self.store.close()
        self.path.write_text('{"v":1,', encoding="utf-8")
        reopened = RollHistoryStore(self.path)
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.writable)
        self.assertEqual(self.path.read_text(), '{"v":1,')

    def test_clear_keeps_reconnect_checkpoint_export_does_not_overwrite(self):
        self.store.observe(self.scope, {"chaos": {12: 2}}, collecting=True)
        self.store.clear()
        self.store.observe(self.scope, {"chaos": {12: 2}}, collecting=True)
        self.assertEqual(self.store.snapshot("chaos").total, 0)
        self.store.observe(self.scope, {"chaos": {12: 3}}, collecting=True)
        exported = self.path.parent / "export.json"
        self.store.export_json(exported)
        validate_roll_history(json.loads(exported.read_text()))
        with self.assertRaises(ValueError):
            self.store.export_json(self.path)
        self.assertEqual(self.store.snapshot("chaos").total, 1)

    def test_unknown_source_or_stat_and_negative_counts_rejected(self):
        for observations in ({"shrine": {12: 1}}, {"chaos": {999: 2}}, {"dice": {12: True}}):
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                self.store.observe(self.scope, observations, collecting=True)
        payload = {"v": 1, "totals": {"dice": {"12": -1}, "chaos": {}}, "checkpoints": {}}
        with self.assertRaises(ValueError):
            validate_roll_history(payload)

    def test_scanner_restart_keeps_scope_but_recycled_addresses_in_new_run_do_not(self):
        self.store.observe(self.scope, {"chaos": {12: 10}}, collecting=True,
                           run_id="scanner-run-a", run_timer=100)
        self.store.observe(self.scope, {"chaos": {12: 10}}, collecting=True,
                           run_id="scanner-run-b", run_timer=110)
        self.assertEqual(self.store.snapshot("chaos").total, 10)
        self.store.observe(self.scope, {"chaos": {12: 2}}, collecting=True,
                           run_id="scanner-run-c", run_timer=2)
        self.assertEqual(self.store.snapshot("chaos").total, 12)
        self.store.observe(self.scope, {"chaos": {12: 2}}, collecting=True,
                           run_id="scanner-run-d", run_timer=3)
        self.assertEqual(self.store.snapshot("chaos").total, 12)

    def test_new_scanner_uuid_without_clock_waits_instead_of_creating_duplicate(self):
        self.store.observe(self.scope, {"chaos": {12: 10}}, collecting=True,
                           run_id="a", run_timer=100)
        self.assertEqual(self.store.observe(self.scope, {"chaos": {12: 12}}, collecting=True,
                         run_id="b"), (0, None))
        self.assertEqual(self.store.snapshot("chaos").total, 10)
        self.store.observe(self.scope, {"chaos": {12: 12}}, collecting=True, run_id="b", run_timer=120)
        self.assertEqual(self.store.snapshot("chaos").total, 12)

    def test_first_available_clock_is_saved_even_without_new_rolls(self):
        self.store.observe(self.scope, {"chaos": {12: 10}}, collecting=True, run_id="a")
        self.store.observe(self.scope, {"chaos": {12: 10}}, collecting=True, run_id="a", run_timer=100)
        self.store.close()
        reopened = RollHistoryStore(self.path)
        self.addCleanup(reopened.close)
        reopened.observe(self.scope, {"chaos": {12: 2}}, collecting=True, run_id="b", run_timer=2)
        self.assertEqual(reopened.snapshot("chaos").total, 12)


class RollServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.service = RollAnalyticsService(RollHistoryStore(Path(tmp.name) / "history.json"))
        self.addCleanup(self.service.close)

    def observe(self, n, **kwargs):
        self.service.observe(process_identity="123:456", owner_stats=100, passive_ptr=200,
                             chaos=chaos({12: n}), passive=dice({30: n}), **kwargs)
        self.service.flush()

    def test_pause_resume_without_intermediate_reads(self):
        self.service.set_collection_active(True)
        self.observe(10)
        self.service.set_collection_active(False)
        self.service.set_collection_active(True)
        self.observe(30)
        self.observe(31)
        self.assertEqual(self.service.snapshot("chaos").total, 11)
        self.assertEqual(self.service.snapshot("dice").total, 11)
        self.assertEqual(self.service.status().session_recorded, 22)

    def test_nonpremium_start_and_activation_do_not_backfill(self):
        self.service.set_collection_active(False)
        self.observe(10)
        self.assertFalse(self.service.store.path.exists())
        self.service.set_collection_active(True)
        self.observe(20)
        self.observe(21)
        self.assertEqual(self.service.snapshot("dice").total, 1)

    def test_queued_resume_observations_baseline_only_the_first_snapshot(self):
        self.service.set_collection_active(False)
        self.service.set_collection_active(True)
        release = threading.Event()
        self.addCleanup(release.set)
        self.service._executor.submit(lambda: release.wait(3))
        for count in (20, 21, 22):
            self.service.observe(process_identity="123:456", owner_stats=100, passive_ptr=200,
                                 chaos=chaos({12: count}), passive=dice({30: count}))
        release.set()
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 2)
        self.assertEqual(self.service.snapshot("dice").total, 2)

    def test_ambiguous_partial_and_recovering_inputs_wait_for_confirmation(self):
        cs = replace(chaos({12: 3}), level=10)
        ps = replace(dice({30: 3}), status=CharacterPassiveStatus.UPDATING)
        self.assertEqual(confirmed_roll_counts(cs, ps), {})
        ps = replace(dice({30: 3}), pending=1, status=CharacterPassiveStatus.PARTIAL)
        self.assertEqual(confirmed_roll_counts(None, ps), {})
        self.assertEqual(confirmed_roll_counts(replace(chaos({12: 3}), ambiguous_rolls=1), None), {})
        self.assertEqual(confirmed_roll_counts(chaos({12: 3}), dice({30: 4})),
                         {"chaos": {12: 3}, "dice": {30: 4}})

    def test_non_dice_passives_and_missing_identity_never_collected(self):
        self.assertEqual(confirmed_roll_counts(None, replace(dice({30: 3}), character_id=0)), {})
        self.assertIsNone(stable_roll_scope("", 100, 200))
        self.service.set_collection_active(True)
        self.assertFalse(self.service.observe(process_identity="", owner_stats=100, passive_ptr=200,
                                              chaos=chaos({12: 3}), passive=None))
        self.assertEqual(self.service.snapshot("chaos").total, 0)

    def test_empty_history_has_unavailable_percent(self):
        snapshot = aggregate_roll_counts("dice", {})
        self.assertEqual(snapshot.total, 0)
        self.assertTrue(all(row.percent is None for row in snapshot.rows))

    def test_same_addresses_with_a_tracker_run_reset_get_a_new_checkpoint(self):
        self.service.set_collection_active(True)
        for run, count in (("a", 10), ("b", 2), ("b", 3)):
            self.service.observe(process_identity="123:456", owner_stats=100, passive_ptr=200,
                                 chaos=chaos({12: count}), passive=None, run_id=run)
            self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 13)

    def test_pause_baseline_survives_waiting_for_restart_identity_clock(self):
        scope = stable_roll_scope("123:456", 100, 200)
        self.service.store.observe(scope, {"chaos": {12: 10}}, collecting=True, run_id="a", run_timer=100)
        self.service.set_collection_active(False)
        self.service.set_collection_active(True)
        for timer, count in ((None, 20), (120, 20), (121, 21)):
            self.service.observe(process_identity="123:456", owner_stats=100, passive_ptr=200,
                                 chaos=chaos({12: count}), passive=None, run_id="b", run_timer=timer)
            self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 11)


class RollAnalyticsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.service = RollAnalyticsService(RollHistoryStore(Path(tmp.name) / "history.json"))
        self.addCleanup(self.service.close)
        self.app = NS(coordinator=NS(roll_analytics=self.service), has_premium_access=lambda: False,
                      roll_analytics_collection_active=lambda: self.service.set_collection_active(False))

    def test_saved_history_without_premium_and_source_switching(self):
        from app import config
        from ui.dialogs.roll_analytics import RollAnalyticsWindow
        self.service.set_collection_active(True)
        self.service.observe(process_identity="123:456", owner_stats=100, passive_ptr=200,
                             chaos=chaos({12: 3}), passive=dice({30: 4}))
        self.service.flush()
        with patch.object(config, "ROLL_ANALYTICS_ENABLED", True):
            window = RollAnalyticsWindow(self.app)
            self.addCleanup(window.close)
            self.assertEqual(window._total.text(), "4")
            self.assertEqual(window._table.rowCount(), 27)
            self.assertIn("Premium required", window._status.text())
            self.assertFalse(window._source_buttons["dice"].icon().isNull())
            self.assertFalse(window._source_buttons["chaos"].icon().isNull())
            window._source_buttons["chaos"].click()
            self.assertEqual(window._total.text(), "3")

    def test_enable_is_rejected_without_premium_before_config_write(self):
        from app import config
        from ui.dialogs.roll_analytics import set_roll_analytics_collection
        with patch.object(config, "ROLL_ANALYTICS_ENABLED", False), patch.object(config, "update_config") as write:
            self.assertFalse(set_roll_analytics_collection(self.app, True))
            write.assert_not_called()

    def test_config_write_failure_keeps_collection_and_checkbox_preference(self):
        from app import config
        from ui.dialogs.roll_analytics import set_roll_analytics_collection
        self.app.has_premium_access = lambda: True
        with patch.object(config, "ROLL_ANALYTICS_ENABLED", False), patch.object(
            config, "update_config", return_value=NS(success=False, reason="read-only profile")
        ), patch("ui.dialogs.roll_analytics.QMessageBox.warning") as notice:
            self.assertFalse(set_roll_analytics_collection(self.app, True))
            self.assertFalse(config.ROLL_ANALYTICS_ENABLED)
            notice.assert_called_once()

    def test_locked_collection_preserves_setting_and_view_button(self):
        from PySide6.QtWidgets import QPushButton
        from ui.tabs.session_stats import SessionStatsTab
        opened = Mock()
        toggled = Mock(return_value=True)
        view = SessionStatsTab(on_open_tracked_item_settings=lambda: None,
                               on_open_roll_analytics=opened, on_toggle_roll_analytics=toggled)
        root = view.build()
        self.addCleanup(root.close)
        view.set_roll_analytics_status(enabled=True, premium=False)
        self.assertTrue(view._roll_analytics_collect.isChecked())
        self.assertFalse(view._roll_analytics_collect.isEnabled())
        self.assertFalse(view._roll_analytics_locked.isHidden())
        button = next(b for b in root.findChildren(QPushButton) if b.text() == "Roll Analytics")
        self.assertTrue(button.isEnabled())
        button.click()
        opened.assert_called_once()
        view.set_roll_analytics_status(enabled=True, premium=True)
        self.assertFalse(view._roll_analytics_collect.isHidden())
        self.assertTrue(view._roll_analytics_locked.isHidden())
        toggled.assert_not_called()


class RollRefreshIntegrationTests(unittest.TestCase):
    def setUp(self):
        from tests.support.refresh_tasks import build_refresh_tasks
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.service = RollAnalyticsService(RollHistoryStore(Path(tmp.name) / "history.json"))
        self.addCleanup(self.service.close)
        self.active = True
        def active():
            return self.service.set_collection_active(self.active)
        self.tasks, self.world = build_refresh_tasks(
            roll_analytics_service=self.service, roll_analytics_active=active,
            tracker=NS(chaos_tome_snapshot=lambda: chaos({12: 3}),
                       character_passive_snapshot=lambda: dice({30: 4})),
        )
        self.client = NS(memory=NS(process_identity=lambda: "123:456"))
        self.reading = NS(passive_object_ptr=200)

    def test_collection_demands_both_sources_and_reservation_without_recording(self):
        self.assertTrue(self.tasks._should_refresh_chaos_tome())
        self.assertTrue(self.tasks._should_refresh_charge_shrines())
        self.active = False
        self.assertFalse(self.tasks._should_refresh_chaos_tome())
        self.assertFalse(self.tasks._should_refresh_charge_shrines())
        self.active = True
        self.world.lifecycle.completed_run = True
        self.assertFalse(self.tasks._should_refresh_chaos_tome())

    def test_premium_is_rechecked_after_the_read_before_history_publication(self):
        self.tasks._should_refresh_chaos_tome()
        self.active = False
        self.tasks._record_roll_analytics(self.client, 100, self.reading)
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 0)
        self.assertEqual(self.service.snapshot("dice").total, 0)

    def test_same_snapshots_are_consumed_without_extra_game_reads(self):
        for _ in range(3):
            self.tasks._record_roll_analytics(self.client, 100, self.reading)
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 3)
        self.assertEqual(self.service.snapshot("dice").total, 4)

    def test_new_owner_recovery_cannot_save_retained_old_chaos_snapshot(self):
        self.world.tracker.character_passive_snapshot = lambda: replace(
            dice({30: 4}), status=CharacterPassiveStatus.UPDATING, coverage="recovering_history"
        )
        self.tasks._record_roll_analytics(self.client, 101, NS(passive_object_ptr=201))
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 0)
        self.world.tracker.character_passive_snapshot = lambda: dice({30: 4})
        self.tasks._record_roll_analytics(self.client, 101, NS(passive_object_ptr=201))
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 3)

    def test_unavailable_chaos_read_cannot_save_retained_snapshot_under_new_owner(self):
        self.tasks._record_roll_analytics(self.client, 101, NS(passive_object_ptr=201),
                                          chaos_available=False)
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 0)
        self.assertEqual(self.service.snapshot("dice").total, 4)

    def test_terminal_collection_without_recording_reads_once_and_can_publish_finished_recovery(self):
        from app.refresh_coordinator import RefreshTickContext
        self.world.tracker.run_id = "run"
        self.world.lifecycle.completed_run = True
        self.tasks._refresh_charge_shrines_task = Mock(return_value=True)
        def read(_ctx):
            self.tasks._record_roll_analytics(self.client, 100, self.reading)
            return True
        self.tasks._refresh_chaos_tome_task = Mock(side_effect=read)
        for i in range(2):
            self.tasks._refresh_recording_lifecycle_task(RefreshTickContext(i, 0))
        self.service.flush()
        self.tasks._refresh_chaos_tome_task.assert_called_once()
        self.tasks._refresh_charge_shrines_task.assert_called_once()
        self.assertEqual(self.service.snapshot("dice").total, 4)

    def test_terminal_collection_retries_a_transient_read_failure(self):
        from app.refresh_coordinator import RefreshTickContext
        self.world.tracker.run_id = "run"
        self.world.lifecycle.completed_run = True
        self.tasks._refresh_charge_shrines_task = Mock(return_value=True)
        self.tasks._refresh_chaos_tome_task = Mock(side_effect=[False, True])
        with patch("app.refresh_tasks.time.monotonic", side_effect=[100, 101, 102]):
            for i in range(3):
                self.tasks._refresh_recording_lifecycle_task(RefreshTickContext(i, 0))
        self.assertEqual(self.tasks._refresh_chaos_tome_task.call_count, 2)

    def test_terminal_read_retries_stop_after_grace_period(self):
        from app.refresh_coordinator import RefreshTickContext
        self.world.tracker.run_id = "run"
        self.world.lifecycle.completed_run = True
        self.tasks._refresh_charge_shrines_task = Mock(return_value=False)
        self.tasks._refresh_chaos_tome_task = Mock(return_value=False)
        with patch("app.refresh_tasks.time.monotonic", side_effect=[100, 101, 106, 107]):
            for i in range(4):
                self.tasks._refresh_recording_lifecycle_task(RefreshTickContext(i, 0))
        self.assertEqual(self.tasks._refresh_charge_shrines_task.call_count, 2)
        self.tasks._refresh_chaos_tome_task.assert_not_called()

    def test_old_identity_cannot_publish_after_tracker_run_reset(self):
        self.world.tracker.run_id = "old"
        self.tasks._record_roll_analytics(self.client, 100, self.reading)
        self.service.flush()
        self.world.tracker.run_id = "new"
        self.world.tracker.chaos_tome_snapshot = lambda: chaos({12: 20})
        self.tasks._publish_last_roll_analytics()
        self.service.flush()
        self.assertEqual(self.service.snapshot("chaos").total, 3)


if __name__ == "__main__":
    unittest.main()
