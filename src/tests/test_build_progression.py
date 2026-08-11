from __future__ import annotations

from dataclasses import replace
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import src
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from core.build_progression import (
    BuildProgressionDefinition,
    BuildRequirement,
    DeadlineKind,
    Priority,
    RequirementDeadline,
    RequirementKind,
    RequirementStatus,
    evaluate_build_progression,
)
from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL, PlayerStatValue
from core.tracker.live_run import LiveRunTracker
from core.tracker.snapshots import LiveRunSnapshot
from app.build_progression import BuildProgressionService
from app import config
from projections.build_progression import build_progression_payload, format_twitch_build
from projections.in_game_html import build_build_progression_overlay_html
from twitch_bot import TwitchBotWorker
from ui.dialogs.build_progression import BuildProgressionDialog


def runtime(*, time=100.0, items=("Anvil",), damage=2.0, stage=1, stage_time=0.0, duration=600.0):
    tracker = LiveRunTracker(clock=lambda: 10.0)
    tracker.update(
        LiveRunSnapshot(
            captured_at=10.0,
            stats={"Damage": PlayerStatValue(PLAYER_STAT_SPEC_BY_LABEL["Damage"], damage)},
            items=tuple(items),
            game_time_seconds=time,
            stage_ptr=1,
            stage_index=max(0, stage - 1),
        )
    )
    tracker.update_fast_run_timer(time)
    tracker.update_fast_stage_timer(
        stage_timer_seconds=stage_time,
        stage_index=max(0, stage - 1),
        stage_duration_seconds=duration,
    )
    snap = tracker.runtime_snapshot()
    return tracker, replace(snap, current_stage_index=stage)


class BuildProgressionTests(unittest.TestCase):
    def test_items_stats_required_and_ideal(self):
        _tracker, snap = runtime(items=("Anvil", "Anvil"), damage=3.5)
        definition = BuildProgressionDefinition(
            name="Test",
            requirements=(
                BuildRequirement("a", RequirementKind.ITEM, "Anvil", 1, 3),
                BuildRequirement("d", RequirementKind.STAT, "Damage", 3.0, 5.0),
            ),
        )
        result = evaluate_build_progression(definition, snap).snapshot
        self.assertTrue(result.complete)
        self.assertEqual(result.completed, 2)
        rows = {row.id: row for row in result.rows}
        self.assertEqual(rows["a"].current_display, "2")
        self.assertEqual(rows["d"].required_display, "3x")
        self.assertEqual(rows["d"].ideal_display, "5x")

    def test_stacked_live_inventory_strings_use_their_embedded_count(self):
        _tracker, snap = runtime(items=("Wizard's Hat x198", "Beefy Ring x1"))
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("hat", RequirementKind.ITEM, "Wizard's Hat", 200),
            BuildRequirement("ring", RequirementKind.ITEM, "Beefy Ring", 1),
        ))

        rows = {
            row.id: row
            for row in evaluate_build_progression(definition, snap).snapshot.rows
        }

        self.assertEqual(rows["hat"].current, 198)
        self.assertEqual(rows["hat"].current_display, "198")
        self.assertEqual(rows["ring"].current, 1)
        self.assertIs(rows["ring"].status, RequirementStatus.SATISFIED)

    def test_editor_hides_irrelevant_deadline_fields_on_first_open(self):
        app = QApplication.instance() or QApplication([])
        settings = SimpleNamespace(
            read=lambda: {
                "schema_version": 1,
                "name": "Test",
                "deadlines_enabled": True,
                "requirements": [],
            },
            write=MagicMock(),
        )
        dialog = BuildProgressionDialog(settings, SimpleNamespace())
        self.addCleanup(dialog.close)

        self.assertTrue(dialog.stage.isHidden())
        self.assertTrue(dialog.time_entry.isHidden())
        self.assertTrue(dialog._stage_label.isHidden())
        self.assertTrue(dialog._time_label.isHidden())

        run_clock = next(
            button
            for button in dialog.deadline_group.buttons()
            if button.property("deadlineKind") == "run_clock"
        )
        run_clock.click()
        app.processEvents()
        self.assertTrue(dialog.stage.isHidden())
        self.assertTrue(dialog._stage_label.isHidden())
        self.assertFalse(dialog.time_entry.isHidden())
        self.assertFalse(dialog._time_label.isHidden())

    def test_editor_uses_rarity_chips_and_a_single_row_for_requirement_values(self):
        app = QApplication.instance() or QApplication([])
        settings = SimpleNamespace(
            read=lambda: {
                "schema_version": 1,
                "name": "Test",
                "deadlines_enabled": True,
                "requirements": [],
            },
            write=MagicMock(),
        )
        dialog = BuildProgressionDialog(settings, SimpleNamespace())
        self.addCleanup(dialog.close)
        dialog.show()
        app.processEvents()

        self.assertEqual(dialog.required.decimals(), 0)
        self.assertEqual(dialog.ideal.decimals(), 0)
        self.assertEqual(
            [dialog.priority.itemText(i) for i in range(dialog.priority.count())],
            ["High", "Medium", "Low"],
        )
        self.assertEqual(dialog.priority.currentText(), "Low")
        anvil = dialog._picker_buttons["Anvil"]
        self.assertEqual(anvil.objectName(), "pickChip")
        self.assertIn("border: 1px solid", anvil.styleSheet())
        anvil.click()
        self.assertEqual(dialog._selected_target(), "Anvil")
        self.assertTrue(anvil.isChecked())

        field_tops = {
            dialog.required.parentWidget().geometry().top(),
            dialog.ideal.parentWidget().geometry().top(),
            dialog.priority.parentWidget().geometry().top(),
        }
        self.assertEqual(len(field_tops), 1)
        self.assertGreaterEqual(dialog.rules.height(), 100)
        self.assertGreater(
            dialog._configurator_card.geometry().top(),
            dialog._picker_card.geometry().top(),
        )
        self.assertGreater(dialog._rules_card.height(), dialog._picker_card.height())

        dialog._draft["requirements"] = [
            {
                "id": "colour-row",
                "kind": "item",
                "target": "Anvil",
                "required": 1,
                "ideal": None,
                "priority": "asap",
                "deadline": {
                    "kind": "stage_overtime",
                    "stage": 2,
                    "seconds": 300,
                },
            }
        ]
        dialog._refresh_rules()
        requirement_row = dialog.rules.itemWidget(dialog.rules.item(0))
        self.assertIsNotNone(requirement_row)
        self.assertGreaterEqual(requirement_row.minimumHeight(), 40)
        self.assertEqual(
            dialog.rules.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff
        )
        target = requirement_row.findChild(QLabel, "BuildRequirementTarget")
        priority = requirement_row.findChild(QLabel, "BuildRequirementPriority")
        deadline = requirement_row.findChild(QLabel, "BuildRequirementDeadline")
        self.assertIn("color:", target.styleSheet())
        self.assertEqual(priority.text(), "High")
        self.assertEqual(deadline.text(), "T2 OT · 05:00")

        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("stat"))
        app.processEvents()
        self.assertEqual(dialog.required.decimals(), 2)
        self.assertEqual(dialog.ideal.decimals(), 2)

    def test_run_clock_warning_and_overdue_boundaries(self):
        definition = BuildProgressionDefinition(
            requirements=(BuildRequirement(
                "a", RequirementKind.ITEM, "Anvil", 2,
                deadline=RequirementDeadline(DeadlineKind.RUN_CLOCK, seconds=300),
            ),),
        )
        for now, expected in ((180, RequirementStatus.WARNING), (300, RequirementStatus.WARNING), (301, RequirementStatus.OVERDUE)):
            _tracker, snap = runtime(time=now)
            row = evaluate_build_progression(definition, snap).snapshot.rows[0]
            self.assertIs(row.status, expected)

    def test_stage_start_and_overtime(self):
        _tracker, snap = runtime(stage=1, stage_time=500, duration=600)
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("start", RequirementKind.ITEM, "Missing", 1, deadline=RequirementDeadline(DeadlineKind.STAGE_START, stage=2)),
            BuildRequirement("ot", RequirementKind.ITEM, "Missing2", 1, deadline=RequirementDeadline(DeadlineKind.STAGE_OVERTIME, stage=1, seconds=30)),
        ))
        rows = {row.id: row for row in evaluate_build_progression(definition, snap).snapshot.rows}
        self.assertIs(rows["start"].status, RequirementStatus.WARNING)
        self.assertIs(rows["ot"].status, RequirementStatus.NEUTRAL)
        self.assertEqual(rows["start"].deadline_label, "Before T2")
        self.assertEqual(rows["ot"].deadline_label, "T1 OT · 00:30")
        overdue = replace(snap, fast_stage_timer=replace(snap.fast_stage_timer, stage_timer_seconds=631))
        rows = {row.id: row for row in evaluate_build_progression(definition, overdue).snapshot.rows}
        self.assertIs(rows["ot"].status, RequirementStatus.OVERDUE)

    def test_deadlines_master_toggle_and_priority_sort(self):
        _tracker, snap = runtime(time=500, items=())
        definition = BuildProgressionDefinition(deadlines_enabled=False, requirements=(
            BuildRequirement("normal", RequirementKind.ITEM, "A", 1, priority=Priority.NORMAL, deadline=RequirementDeadline(DeadlineKind.RUN_CLOCK, seconds=1), order=0),
            BuildRequirement("asap", RequirementKind.ITEM, "B", 1, priority=Priority.ASAP, order=1),
        ))
        result = evaluate_build_progression(definition, snap).snapshot
        self.assertEqual([row.id for row in result.rows], ["asap", "normal"])
        self.assertTrue(all(row.status is RequirementStatus.NEUTRAL for row in result.rows))
        self.assertEqual(
            [row["priority"] for row in build_progression_payload(result)["rows"]],
            ["high", "low"],
        )

    def test_unknown_is_not_zero_or_overdue(self):
        _tracker, snap = runtime(time=500)
        snap = replace(snap, latest_snapshot=None, fast_items=None)
        definition = BuildProgressionDefinition(requirements=(BuildRequirement(
            "a", RequirementKind.ITEM, "Anvil", 1,
            deadline=RequirementDeadline(DeadlineKind.RUN_CLOCK, seconds=10),
        ),))
        row = evaluate_build_progression(definition, snap).snapshot.rows[0]
        self.assertIsNone(row.current)
        self.assertIs(row.status, RequirementStatus.UNKNOWN)

    def test_service_resets_transition_state_on_run_id(self):
        tracker, _snap = runtime(time=100, items=("Anvil",))
        service = BuildProgressionService(tracker, BuildProgressionDefinition(requirements=(
            BuildRequirement("a", RequirementKind.ITEM, "Anvil", 1),
        )))
        first = service.snapshot()
        self.assertEqual(first.completion_time_seconds, 100)
        tracker.run_id = "new-run"
        tracker.update_fast_run_timer(5)
        second = service.snapshot()
        self.assertEqual(second.completion_time_seconds, 5)

    def test_projection_hides_completed_and_bounds_rows(self):
        _tracker, snap = runtime(items=("Anvil",))
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("done", RequirementKind.ITEM, "Anvil", 1),
            BuildRequirement("one", RequirementKind.ITEM, "A", 1),
            BuildRequirement("two", RequirementKind.ITEM, "B", 1),
        ))
        result = evaluate_build_progression(definition, snap).snapshot
        payload = build_progression_payload(result, {"max_rows": 1})
        self.assertEqual(payload["hidden_completed"], 1)
        self.assertEqual(payload["hidden_remaining"], 1)
        twitch = format_twitch_build(result, max_rows=1)
        self.assertIn("+1 remaining", twitch["remaining_suffix"])

    def test_config_normalization_rejects_duplicates_and_invalid_values(self):
        normalized = config.normalize_build_progression_config({
            "name": "  My build  ",
            "requirements": [
                {"id": "one", "kind": "item", "target": "Anvil", "required": 2, "ideal": 4, "priority": "asap", "deadline": {"kind": "stage_overtime", "stage": 9, "seconds": 30}},
                {"id": "duplicate", "kind": "item", "target": "Anvil", "required": 1},
                {"id": "bad", "kind": "item", "target": "Ice Cube", "required": 1.5},
            ],
        })
        self.assertEqual(normalized["name"], "My build")
        self.assertEqual(len(normalized["requirements"]), 1)
        row = normalized["requirements"][0]
        self.assertEqual(row["deadline"]["stage"], 4)
        self.assertEqual(row["ideal"], 4)

    def test_in_game_html_escapes_labels(self):
        _tracker, snap = runtime(items=())
        definition = BuildProgressionDefinition(name="<build>", requirements=(
            BuildRequirement("one", RequirementKind.ITEM, "<item>", 1),
        ))
        payload = build_progression_payload(evaluate_build_progression(definition, snap).snapshot)
        html = build_build_progression_overlay_html(payload)
        self.assertIn("&lt;build&gt;", html)
        self.assertNotIn("<item>", html)

    def test_twitch_build_command_uses_shared_service(self):
        tracker, _snap = runtime(items=())
        service = BuildProgressionService(tracker, BuildProgressionDefinition(name="Chat build", requirements=(
            BuildRequirement("one", RequirementKind.ITEM, "Anvil", 2),
        )))
        bot = TwitchBotWorker(tracker, build_progression_service=service)
        bot._send_chat = MagicMock()
        bot._handle_build("channel")
        message = bot._send_chat.call_args.args[1]
        self.assertIn("Chat build", message)
        self.assertIn("0/1", message)
        self.assertNotIn("Next", message)
        self.assertNotIn("Due", message)


if __name__ == "__main__":
    unittest.main()
