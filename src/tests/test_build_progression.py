from __future__ import annotations

from copy import deepcopy
import ast
from dataclasses import replace
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src
import ui.dialogs.build_progression as build_progression_dialogs
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from core.build_progression import (
    BuildProgressionDefinition,
    BuildRequirement,
    DeadlineKind,
    RequirementDeadline,
    RequirementKind,
    RequirementStatus,
    evaluate_build_progression,
)
from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL, PlayerStatValue
from core.tracker.live_run import LiveRunTracker
from core.tracker.snapshots import LiveRunSnapshot
from app.build_progression import (
    BuildProgressionService,
    active_definition_from_config,
    build_export_payload,
    build_from_export_payload,
    clone_build_config,
)
from app import config
from projections.build_progression import build_progression_payload, format_twitch_build
from projections.in_game_html import build_build_progression_overlay_html
from twitch_bot import TwitchBotWorker
from ui.dialogs.build_progression import (
    BuildProgressionDialog,
    BuildProgressionManagerDialog,
)


def runtime(
    *,
    time=100.0,
    items=("Anvil",),
    damage=2.0,
    stage=1,
    stage_time=0.0,
    duration=600.0,
    kills=None,
    player_level=None,
):
    tracker = LiveRunTracker(clock=lambda: 10.0)
    tracker.update(
        LiveRunSnapshot(
            captured_at=10.0,
            stats={"Damage": PlayerStatValue(PLAYER_STAT_SPEC_BY_LABEL["Damage"], damage)},
            items=tuple(items),
            game_time_seconds=time,
            stage_ptr=1,
            stage_index=max(0, stage - 1),
            mob_kills=kills,
            player_level=player_level,
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
    def test_editor_groups_items_before_stats_with_untimed_items_first(self):
        rows = [
            {
                "id": "common",
                "kind": "item",
                "target": "Key",
                "deadline": {"kind": "none"},
                "order": 0,
            },
            {
                "id": "timed-legendary",
                "kind": "item",
                "target": "Anvil",
                "deadline": {"kind": "stage_overtime", "stage": 2, "seconds": 0},
                "order": 1,
            },
            {
                "id": "rare",
                "kind": "item",
                "target": "Beefy Ring",
                "deadline": {"kind": "none"},
                "order": 2,
            },
            {
                "id": "legendary",
                "kind": "item",
                "target": "Ice Cube",
                "deadline": {"kind": "none"},
                "order": 3,
            },
            {
                "id": "stat",
                "kind": "stat",
                "target": "Damage",
                "deadline": {"kind": "none"},
                "order": 4,
            },
        ]

        ordered = sorted(rows, key=BuildProgressionDialog._requirement_display_sort_key)

        self.assertEqual(
            [row["id"] for row in ordered],
            ["legendary", "rare", "common", "timed-legendary", "stat"],
        )

    def test_percentage_requirements_stay_on_the_raw_stat_scale(self):
        build = config.normalize_build_definition_config({
            "name": "Percent build",
            "requirements": [{
                "id": "crit",
                "kind": "stat",
                "target": "Crit Chance",
                "required": 100,
            }],
        })
        self.assertEqual(build["requirements"][0]["required"], 100.0)
        self.assertEqual(BuildProgressionDialog._stat_entry_scale("Crit Chance"), 100.0)
        self.assertEqual(BuildProgressionDialog._stat_entry_scale("Crit Damage"), 2.0)

    def test_editor_never_shows_a_parentless_deadline_badge(self):
        app = QApplication.instance() or QApplication([])

        class ShowWatcher(QObject):
            def __init__(self):
                super().__init__()
                self.parentless_deadline_shows = 0

            def eventFilter(self, watched, event):
                if (
                    event.type() == QEvent.Show
                    and getattr(watched, "objectName", lambda: "")()
                    == "condBadge"
                    and getattr(watched, "parentWidget", lambda: None)() is None
                ):
                    self.parentless_deadline_shows += 1
                return False

        watcher = ShowWatcher()
        app.installEventFilter(watcher)
        self.addCleanup(app.removeEventFilter, watcher)
        build = {
            "name": "Test",
            "deadlines_enabled": True,
            "requirements": [{
                    "id": "deadline",
                    "kind": "item",
                    "target": "Anvil",
                    "required": 1,
                    "deadline": {
                        "kind": "stage_overtime",
                        "stage": 2,
                        "seconds": 300,
                    },
                }],
        }

        dialog = BuildProgressionDialog(build)
        self.addCleanup(dialog.done, QDialog.Rejected)
        app.processEvents()

        self.assertEqual(watcher.parentless_deadline_shows, 0)

    def test_items_and_stats_use_required_thresholds(self):
        _tracker, snap = runtime(items=("Anvil", "Anvil"), damage=3.5)
        definition = BuildProgressionDefinition(
            name="Test",
            requirements=(
                BuildRequirement("a", RequirementKind.ITEM, "Anvil", 1),
                BuildRequirement("d", RequirementKind.STAT, "Damage", 3.0),
            ),
        )
        result = evaluate_build_progression(definition, snap).snapshot
        self.assertTrue(result.complete)
        self.assertEqual(result.completed, 2)
        rows = {row.id: row for row in result.rows}
        self.assertEqual(rows["a"].current_display, "2")
        self.assertEqual(rows["d"].required_display, "3x")

    def test_progress_requirements_use_live_kills_and_player_level(self):
        _tracker, snap = runtime(items=(), kills=250, player_level=42)
        definition = BuildProgressionDefinition(
            requirements=(
                BuildRequirement("kills", RequirementKind.PROGRESS, "Kills", 200),
                BuildRequirement(
                    "level", RequirementKind.PROGRESS, "Player Level", 50
                ),
            ),
        )

        rows = {
            row.id: row
            for row in evaluate_build_progression(definition, snap).snapshot.rows
        }

        self.assertEqual(rows["kills"].current_display, "250")
        self.assertIs(rows["kills"].status, RequirementStatus.SATISFIED)
        self.assertEqual(rows["level"].current_display, "42")
        self.assertIsNot(rows["level"].status, RequirementStatus.SATISFIED)

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
        dialog = BuildProgressionDialog({"name": "Test", "requirements": []})
        self.addCleanup(dialog.done, QDialog.Rejected)

        self.assertTrue(dialog.stage.isHidden())
        self.assertTrue(dialog.time_entry.isHidden())
        self.assertTrue(dialog._stage_label.isHidden())
        self.assertTrue(dialog._time_label.isHidden())

        before_tier = next(
            button
            for button in dialog.deadline_group.buttons()
            if button.property("deadlineKind") == "stage_start"
        )
        before_tier.click()
        app.processEvents()
        self.assertFalse(dialog.stage.isHidden())
        self.assertFalse(dialog._stage_label.isHidden())
        self.assertTrue(dialog.time_entry.isHidden())
        self.assertTrue(dialog._time_label.isHidden())
        self.assertEqual(
            [dialog.stage.itemData(index) for index in range(dialog.stage.count())],
            [2, 3],
        )

        overtime = next(
            button
            for button in dialog.deadline_group.buttons()
            if button.property("deadlineKind") == "stage_overtime"
        )
        overtime.click()
        app.processEvents()
        self.assertEqual(
            [dialog.stage.itemData(index) for index in range(dialog.stage.count())],
            [1, 2, 3, 4],
        )
        self.assertEqual(dialog.time_entry.text(), "+05:00")
        self.assertEqual(BuildProgressionDialog._seconds("+05:00"), 300.0)

    def test_editor_uses_rarity_chips_and_a_single_row_for_requirement_values(self):
        app = QApplication.instance() or QApplication([])
        dialog = BuildProgressionDialog({"name": "Test", "requirements": []})
        self.addCleanup(dialog.done, QDialog.Rejected)
        dialog.show()
        app.processEvents()

        self.assertEqual(dialog.required.decimals(), 0)
        anvil = dialog._picker_buttons["Anvil"]
        self.assertEqual(anvil.objectName(), "pickChip")
        self.assertIn("border: 1px solid", anvil.styleSheet())
        hover_style = anvil.styleSheet().rsplit("QPushButton#pickChip:hover", 1)[1]
        self.assertIn("border: 1px solid", hover_style.split("}", 1)[0])
        anvil.click()
        self.assertEqual(dialog._selected_target(), "Anvil")
        self.assertTrue(anvil.isChecked())

        self.assertGreaterEqual(dialog.rules_scroll.height(), 100)
        self.assertIs(
            dialog._configurator_card.parentWidget(),
            dialog._rules_card.parentWidget(),
        )
        self.assertIsNot(
            dialog._configurator_card.parentWidget(),
            dialog._picker_card.parentWidget(),
        )

        dialog._draft["requirements"] = [
            {
                "id": "colour-row",
                "kind": "item",
                "target": "Anvil",
                "required": 1,
                "deadline": {
                    "kind": "stage_overtime",
                    "stage": 2,
                    "seconds": 300,
                },
            }
        ]
        dialog._refresh_rules()
        app.processEvents()
        requirement_row = dialog._rule_widgets["colour-row"]
        self.assertIsNotNone(requirement_row)
        self.assertIsInstance(requirement_row.layout(), QHBoxLayout)
        self.assertLessEqual(requirement_row.minimumHeight(), 48)
        self.assertEqual(
            dialog.rules_scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff
        )
        target = requirement_row.findChild(QLabel, "pickedChip")
        goal = requirement_row.findChild(QLabel, "condBadgeMuted")
        deadline = requirement_row.findChild(QLabel, "condBadge")
        self.assertEqual(target.text(), "Anvil")
        self.assertGreaterEqual(target.width(), 64)
        self.assertGreaterEqual(
            target.width() - target.contentsMargins().left() - target.contentsMargins().right(),
            target.fontMetrics().horizontalAdvance(target.text()),
        )
        self.assertEqual(goal.text(), "Required 1")
        self.assertGreaterEqual(goal.width(), 72)
        self.assertGreaterEqual(
            goal.width() - goal.contentsMargins().left() - goal.contentsMargins().right(),
            goal.fontMetrics().horizontalAdvance(goal.text()),
        )
        self.assertIn("color:", target.styleSheet())
        self.assertIsNone(requirement_row.findChild(QLabel, "BuildRequirementPriority"))
        self.assertEqual(deadline.text(), "T2 +05:00")
        self.assertEqual(requirement_row.objectName(), "trackedRowLast")
        self.assertIsNotNone(requirement_row.findChild(QPushButton, "chipRemove"))

        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("stat"))
        app.processEvents()
        self.assertEqual(dialog.required.decimals(), 2)

        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("progress"))
        app.processEvents()
        self.assertEqual(dialog.required.decimals(), 0)
        self.assertEqual(set(dialog._picker_buttons), {"Kills", "Player Level"})

    def test_editor_keeps_long_requirement_text_and_edit_action_visible(self):
        app = QApplication.instance() or QApplication([])
        requirements = [
            {
                "id": "long-item",
                "kind": "item",
                "target": "Grandma's Secret Tonic",
                "required": 15,
                "deadline": {
                    "kind": "stage_overtime",
                    "stage": 4,
                    "seconds": 720,
                },
            },
            {
                "id": "long-stat",
                "kind": "stat",
                "target": "Elite Spawn Increase",
                "required": 5,
                "deadline": {"kind": "none", "stage": None, "seconds": None},
            },
        ]
        dialog = BuildProgressionDialog(
            {"name": "Long labels", "requirements": requirements}
        )
        self.addCleanup(dialog.done, QDialog.Rejected)
        dialog.show()
        app.processEvents()

        for row_widget in dialog._rule_widgets.values():
            for object_name in ("pickedChip", "condBadgeMuted"):
                label = row_widget.findChild(QLabel, object_name)
                margins = label.contentsMargins()
                available = label.width() - margins.left() - margins.right()
                self.assertGreaterEqual(
                    available,
                    label.fontMetrics().horizontalAdvance(label.text()),
                )

        dialog._edit_rule("long-item")
        app.processEvents()
        self.assertEqual(dialog.selected_target.text(), "Grandma's Secret Tonic")
        self.assertFalse(dialog.selected_target.wordWrap())
        self.assertEqual(
            dialog.selected_target.width(), dialog.selected_target.sizeHint().width()
        )
        self.assertLess(dialog.selected_target.width(), dialog.width() // 2)
        self.assertEqual(dialog.add_button.text(), "Update requirement")
        self.assertGreaterEqual(
            dialog.add_button.width(),
            dialog.add_button.sizeHint().width(),
        )

    def test_editor_returns_to_add_mode_when_edited_rules_are_removed(self):
        app = QApplication.instance() or QApplication([])
        requirement = {
            "id": "anvil",
            "kind": "item",
            "target": "Anvil",
            "required": 1,
            "deadline": {"kind": "none", "stage": None, "seconds": None},
        }
        dialog = BuildProgressionDialog(
            {"name": "Test", "deadlines_enabled": True, "requirements": [requirement]}
        )
        self.addCleanup(dialog.done, QDialog.Rejected)

        dialog._edit_rule("anvil")
        self.assertEqual(dialog.add_button.text(), "Update requirement")
        self.assertFalse(dialog.cancel_edit_button.isHidden())
        dialog.required.setValue(9)
        dialog._save()
        self.assertIsNone(dialog.result_payload)
        self.assertEqual(
            dialog.validation_error.text(),
            "Update or cancel the requirement edit before saving the build.",
        )
        dialog._cancel_edit()

        self.assertEqual(dialog.add_button.text(), "Add requirement")
        self.assertTrue(dialog.cancel_edit_button.isHidden())
        self.assertIsNone(dialog._editing_id)
        self.assertEqual(dialog._selected_target(), "")
        self.assertEqual(dialog.required.value(), 1)
        self.assertEqual(dialog._draft["requirements"][0]["required"], 1)

        dialog._edit_rule("anvil")
        dialog._remove_rule("anvil")

        self.assertEqual(dialog.add_button.text(), "Add requirement")
        self.assertEqual(dialog._rendered_rule_ids, [])
        self.assertFalse(dialog.clear_button.isEnabled())

        dialog._draft["requirements"] = [requirement]
        dialog._refresh_rules()
        dialog._edit_rule("anvil")
        with patch("ui.dialogs.build_progression._ask_confirmation", return_value=True):
            dialog._remove_all()
        app.processEvents()

        self.assertEqual(dialog.add_button.text(), "Add requirement")
        self.assertEqual(dialog._rendered_rule_ids, [])

    def test_editor_reports_add_validation_inline_without_a_system_dialog(self):
        app = QApplication.instance() or QApplication([])
        dialog = BuildProgressionDialog({"name": "Test", "requirements": []})
        self.addCleanup(dialog.done, QDialog.Rejected)

        dialog._add_or_update()
        self.assertFalse(dialog.validation_error.isHidden())
        self.assertEqual(dialog.validation_error.text(), "Choose a target first.")

        dialog._select_target("Anvil")
        dialog._add_or_update()
        app.processEvents()

        self.assertEqual(len(dialog._draft["requirements"]), 1)
        self.assertEqual(dialog._selected_target(), "")
        self.assertEqual(dialog.add_button.text(), "Add requirement")
        self.assertTrue(dialog.validation_error.isHidden())

    def test_editor_formats_saved_stat_targets_for_people(self):
        self.assertEqual(
            BuildProgressionDialog._required_display(
                {"kind": "stat", "target": "Crit Chance", "required": 1.0}
            ),
            "100%",
        )
        self.assertEqual(
            BuildProgressionDialog._required_display(
                {"kind": "progress", "target": "Kills", "required": 250.0}
            ),
            "250",
        )

    def test_stage_start_and_overtime(self):
        _tracker, snap = runtime(stage=1, stage_time=500, duration=600)
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("start", RequirementKind.ITEM, "Missing", 1, deadline=RequirementDeadline(DeadlineKind.STAGE_START, stage=2)),
            BuildRequirement("ot", RequirementKind.ITEM, "Missing2", 1, deadline=RequirementDeadline(DeadlineKind.STAGE_OVERTIME, stage=1, seconds=30)),
        ))
        rows = {row.id: row for row in evaluate_build_progression(definition, snap).snapshot.rows}
        self.assertIs(rows["start"].status, RequirementStatus.WARNING)
        self.assertIs(rows["ot"].status, RequirementStatus.NEUTRAL)
        self.assertEqual(rows["start"].deadline_label, "BEFORE T2")
        self.assertEqual(rows["ot"].deadline_label, "T1 +00:30")
        overdue = replace(snap, fast_stage_timer=replace(snap.fast_stage_timer, stage_timer_seconds=631))
        rows = {row.id: row for row in evaluate_build_progression(definition, overdue).snapshot.rows}
        self.assertIs(rows["ot"].status, RequirementStatus.OVERDUE)

    def test_deadlines_master_toggle_preserves_manual_order(self):
        _tracker, snap = runtime(time=500, items=())
        definition = BuildProgressionDefinition(deadlines_enabled=False, requirements=(
            BuildRequirement("first", RequirementKind.ITEM, "A", 1, deadline=RequirementDeadline(DeadlineKind.STAGE_OVERTIME, stage=1, seconds=1), order=0),
            BuildRequirement("second", RequirementKind.ITEM, "B", 1, order=1),
        ))
        result = evaluate_build_progression(definition, snap).snapshot
        self.assertEqual([row.id for row in result.rows], ["first", "second"])
        self.assertTrue(all(row.status is RequirementStatus.NEUTRAL for row in result.rows))
        self.assertTrue(
            all("priority" not in row for row in build_progression_payload(result)["rows"])
        )

    def test_requirements_sort_untimed_before_active_deadlines(self):
        _tracker, snap = runtime(time=100, items=(), stage=1, stage_time=100, duration=600)
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement(
                "later", RequirementKind.ITEM, "A", 1,
                deadline=RequirementDeadline(DeadlineKind.STAGE_OVERTIME, stage=1, seconds=300),
                order=0,
            ),
            BuildRequirement("untimed", RequirementKind.ITEM, "B", 1, order=1),
            BuildRequirement(
                "sooner", RequirementKind.ITEM, "C", 1,
                deadline=RequirementDeadline(DeadlineKind.STAGE_OVERTIME, stage=1, seconds=0),
                order=2,
            ),
        ))

        result = evaluate_build_progression(definition, snap).snapshot

        self.assertEqual([row.id for row in result.rows], ["untimed", "sooner", "later"])

    def test_runtime_rows_put_failed_below_active_and_completed_last(self):
        _tracker, snap = runtime(
            items=("Anvil",),
            stage=1,
            stage_time=631,
            duration=600,
        )
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("done", RequirementKind.ITEM, "Anvil", 1),
            BuildRequirement(
                "failed",
                RequirementKind.ITEM,
                "Sucky Magnet",
                1,
                deadline=RequirementDeadline(
                    DeadlineKind.STAGE_OVERTIME,
                    stage=1,
                    seconds=0,
                ),
            ),
            BuildRequirement(
                "active",
                RequirementKind.ITEM,
                "Ice Cube",
                1,
                deadline=RequirementDeadline(
                    DeadlineKind.STAGE_OVERTIME,
                    stage=1,
                    seconds=120,
                ),
            ),
            BuildRequirement("untimed", RequirementKind.ITEM, "Joe's Dagger", 1),
        ))

        result = evaluate_build_progression(definition, snap).snapshot

        self.assertEqual(
            [row.id for row in result.rows],
            ["untimed", "active", "failed", "done"],
        )

    def test_unknown_is_not_zero_or_overdue(self):
        _tracker, snap = runtime(time=500)
        snap = replace(snap, latest_snapshot=None, fast_items=None)
        definition = BuildProgressionDefinition(requirements=(BuildRequirement(
            "a", RequirementKind.ITEM, "Anvil", 1,
            deadline=RequirementDeadline(DeadlineKind.STAGE_OVERTIME, stage=1, seconds=10),
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
        with_completed = build_progression_payload(
            result,
            {"max_rows": 1, "show_completed": True},
        )
        self.assertEqual(
            [row["id"] for row in with_completed["rows"]],
            ["one", "done"],
        )
        self.assertEqual(with_completed["hidden_completed"], 0)
        self.assertEqual(with_completed["hidden_remaining"], 1)
        twitch = format_twitch_build(result, max_chars=15)
        self.assertIn("more", twitch["requirements"])
        self.assertIn("COMPLETED:", twitch["completed_requirements"])

    def test_projection_uses_shared_base_item_rarity_colours(self):
        from core.item_metadata import ITEM_RARITY_COLOR_MAP

        _tracker, snap = runtime(items=())
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("legendary", RequirementKind.ITEM, "Anvil", 1),
            BuildRequirement("common", RequirementKind.ITEM, "Key", 1),
        ))

        payload = build_progression_payload(
            evaluate_build_progression(definition, snap).snapshot,
            {"max_rows": 20},
        )
        colours = {row["id"]: row["label_color"] for row in payload["rows"]}

        self.assertEqual(colours["legendary"], ITEM_RARITY_COLOR_MAP["LEGENDARY"])
        self.assertEqual(colours["common"], ITEM_RARITY_COLOR_MAP["COMMON"])

    def test_projection_keeps_completed_rows_inside_single_kind_sections(self):
        _tracker, snap = runtime(
            items=("Anvil",), damage=2.0, kills=100, player_level=20
        )
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("active-item", RequirementKind.ITEM, "Ice Cube", 1),
            BuildRequirement("done-item", RequirementKind.ITEM, "Anvil", 1),
            BuildRequirement("active-stat", RequirementKind.STAT, "Damage", 3.0),
            BuildRequirement("done-stat", RequirementKind.STAT, "Damage", 1.0),
            BuildRequirement(
                "active-progress", RequirementKind.PROGRESS, "Player Level", 30
            ),
            BuildRequirement(
                "done-progress", RequirementKind.PROGRESS, "Kills", 50
            ),
        ))
        result = evaluate_build_progression(definition, snap).snapshot

        payload = build_progression_payload(
            result,
            {"max_rows": 20, "show_completed": True},
        )
        html = build_build_progression_overlay_html(payload)

        self.assertEqual(
            [row["id"] for row in payload["rows"]],
            [
                "active-item",
                "done-item",
                "active-stat",
                "done-stat",
                "active-progress",
                "done-progress",
            ],
        )
        self.assertEqual(html.count(">ITEMS</span>"), 1)
        self.assertEqual(html.count(">STATS</span>"), 1)
        self.assertEqual(html.count(">PROGRESS</span>"), 1)

    def test_stat_labels_are_compact_in_build_overlay_and_twitch_output(self):
        _tracker, snap = runtime(items=(), damage=2.0)
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("damage", RequirementKind.STAT, "Damage", 3.0),
        ))
        result = evaluate_build_progression(definition, snap).snapshot

        payload = build_progression_payload(result)
        twitch = format_twitch_build(result)
        html = build_build_progression_overlay_html(payload, edit_mode=True)

        self.assertEqual(payload["rows"][0]["label"], "DMG")
        self.assertIn("DMG", twitch["requirements"])
        self.assertNotIn("Damage", twitch["requirements"])
        self.assertIn("DMG", html)

    def test_config_normalization_rejects_duplicates_and_invalid_values(self):
        normalized = config.normalize_build_definition_config({
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
        self.assertNotIn("ideal", row)
        self.assertNotIn("priority", row)
        migrated = config.normalize_build_definition_config({
            "requirements": [{
                "id": "old-clock", "kind": "item", "target": "Ice Cube",
                "required": 1, "deadline": {"kind": "run_clock", "seconds": 300},
            }]
        })
        self.assertEqual(migrated["requirements"][0]["deadline"]["kind"], "none")

        supported_before_tiers = config.normalize_build_definition_config({
            "requirements": [
                {
                    "id": "before-one",
                    "kind": "item",
                    "target": "Ice Cube",
                    "required": 1,
                    "deadline": {"kind": "stage_start", "stage": 1},
                },
                {
                    "id": "before-four",
                    "kind": "item",
                    "target": "Joe's Dagger",
                    "required": 1,
                    "deadline": {"kind": "stage_start", "stage": 4},
                },
            ],
        })
        self.assertEqual(
            [row["deadline"]["kind"] for row in supported_before_tiers["requirements"]],
            ["none", "none"],
        )
        self.assertTrue(
            all(
                row["deadline"]["stage"] is None
                for row in supported_before_tiers["requirements"]
            )
        )

        progress = config.normalize_build_definition_config({
            "requirements": [
                {"id": "kills", "kind": "progress", "target": "Kills", "required": 100},
                {"id": "level", "kind": "progress", "target": "Player Level", "required": 25},
                {"id": "bad-target", "kind": "progress", "target": "Gold", "required": 10},
                {"id": "fraction", "kind": "progress", "target": "Kills", "required": 1.5},
            ],
        })
        self.assertEqual(
            [row["target"] for row in progress["requirements"]],
            ["Kills", "Player Level"],
        )

    def test_build_library_discards_legacy_shape_and_repairs_active_selection(self):
        legacy = config.normalize_build_progression_config(
            {"schema_version": 2, "name": "Old build", "requirements": []}
        )
        self.assertEqual(
            legacy,
            {"schema_version": 3, "builds": [], "active_build_id": None},
        )

        library = config.normalize_build_progression_config(
            {
                "schema_version": 3,
                "active_build_id": "missing",
                "builds": [
                    {"id": "one", "name": "Build", "requirements": []},
                    {"id": "two", "name": "build", "requirements": []},
                ],
            }
        )
        self.assertEqual(library["active_build_id"], "one")
        self.assertEqual([build["name"] for build in library["builds"]], ["Build", "build (2)"])

    def test_obs_build_widget_migrates_modes_to_standard_panel_settings(self):
        text_overlay = config.normalize_overlay_config({
            "widgets": [{"id": "build_progression", "mode": "text"}],
        })
        text_widget = next(
            widget
            for widget in text_overlay["widgets"]
            if widget["id"] == "build_progression"
        )
        self.assertNotIn("mode", text_widget)
        self.assertFalse(text_widget["show_header"])
        self.assertEqual(text_widget["background_opacity"], 0.0)
        self.assertFalse(text_widget["show_border"])

        full_overlay = config.normalize_overlay_config({
            "widgets": [{"id": "build_progression", "mode": "full"}],
        })
        full_widget = next(
            widget
            for widget in full_overlay["widgets"]
            if widget["id"] == "build_progression"
        )
        self.assertNotIn("mode", full_widget)
        self.assertTrue(full_widget["show_header"])
        self.assertEqual(full_widget["background_opacity"], 0.4)
        self.assertTrue(full_widget["show_border"])

    def test_in_game_html_escapes_labels(self):
        _tracker, snap = runtime(items=())
        definition = BuildProgressionDefinition(name="<build>", requirements=(
            BuildRequirement("one", RequirementKind.ITEM, "<item>", 1),
        ))
        payload = build_progression_payload(evaluate_build_progression(definition, snap).snapshot)
        html = build_build_progression_overlay_html(payload)
        self.assertIn("&lt;build&gt;", html)
        self.assertNotIn("<item>", html)

    def test_in_game_html_uses_qt_tables_and_hides_unknown_question_marks(self):
        _tracker, snap = runtime(items=())
        snap = replace(snap, fast_items=None, latest_snapshot=None)
        definition = BuildProgressionDefinition(
            name="Moop Antena",
            requirements=(
                BuildRequirement("magnet", RequirementKind.ITEM, "Sucky Magnet", 1),
            ),
        )
        payload = build_progression_payload(
            evaluate_build_progression(definition, snap).snapshot
        )

        html = build_build_progression_overlay_html(payload)

        self.assertIn("Moop Antena&nbsp;&middot;&nbsp;0/1", html)
        self.assertIn("<table", html)
        self.assertNotIn("display:grid", html)
        self.assertNotIn("display:flex", html)
        self.assertNotIn(">?</", html)
        self.assertIn("Sucky Magnet&nbsp;&nbsp;", html)
        self.assertIn("--/1", html)

        payload["rows"][0]["status"] = "neutral"
        payload["rows"][0]["symbol"] = "·"
        neutral_html = build_build_progression_overlay_html(payload)
        self.assertNotIn(">·</", neutral_html)

    def test_twitch_build_command_uses_shared_service(self):
        tracker, _snap = runtime(items=())
        service = BuildProgressionService(tracker, BuildProgressionDefinition(name="Chat build", requirements=(
            BuildRequirement("one", RequirementKind.ITEM, "Anvil", 2),
        )))
        bot = TwitchBotWorker(tracker, build_progression_service=service)
        bot._send_chat = MagicMock()
        bot._handle_build("channel")
        self.assertEqual(bot._send_chat.call_count, 1)
        message = bot._send_chat.call_args.args[1]
        self.assertIn("Chat build", message)
        self.assertIn("0/1", message)
        self.assertIn("REMAINING:", message)
        self.assertIn("Anvil", message)
        self.assertNotIn("Next", message)
        self.assertNotIn("Due", message)

    def test_twitch_build_command_sends_completed_requirements_separately(self):
        tracker, _snap = runtime(items=("Anvil",))
        service = BuildProgressionService(
            tracker,
            BuildProgressionDefinition(
                name="Chat build",
                requirements=(
                    BuildRequirement("done", RequirementKind.ITEM, "Anvil", 1),
                    BuildRequirement("missing", RequirementKind.ITEM, "Ice Cube", 1),
                ),
            ),
        )
        bot = TwitchBotWorker(tracker, build_progression_service=service)
        bot._send_chat = MagicMock()

        bot._handle_build("channel")

        self.assertEqual(bot._send_chat.call_count, 2)
        first, completed = [
            call.args[1] for call in bot._send_chat.call_args_list
        ]
        self.assertIn("Chat build", first)
        self.assertIn("REMAINING:", first)
        self.assertIn("Ice Cube", first)
        self.assertNotIn("COMPLETED", first)
        self.assertIn("COMPLETED:", completed)
        self.assertIn("Anvil", completed)

    def test_twitch_build_lists_use_pipe_separators(self):
        _tracker, snap = runtime(items=("Anvil",))
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("done", RequirementKind.ITEM, "Anvil", 1),
            BuildRequirement("missing-one", RequirementKind.ITEM, "Ice Cube", 1),
            BuildRequirement("missing-two", RequirementKind.ITEM, "Joe's Dagger", 1),
        ))

        values = format_twitch_build(
            evaluate_build_progression(definition, snap).snapshot
        )

        self.assertIn("Ice Cube 0/1 |", values["requirements"])
        self.assertNotIn(";", values["requirements"])
        self.assertNotIn(";", values["completed_requirements"])

    def test_twitch_build_separates_remaining_from_failed(self):
        _tracker, snap = runtime(items=(), stage=1, stage_time=601, duration=600)
        definition = BuildProgressionDefinition(requirements=(
            BuildRequirement("active", RequirementKind.ITEM, "Ice Cube", 1),
            BuildRequirement(
                "failed",
                RequirementKind.ITEM,
                "Sucky Magnet",
                1,
                deadline=RequirementDeadline(
                    DeadlineKind.STAGE_OVERTIME,
                    stage=1,
                    seconds=0,
                ),
            ),
        ))

        values = format_twitch_build(
            evaluate_build_progression(definition, snap).snapshot
        )

        self.assertIn("REMAINING: · Ice Cube", values["requirements"])
        self.assertNotIn("Sucky Magnet", values["requirements"])
        self.assertIn("FAILED: × Sucky Magnet", values["failed_requirements"])


class BuildProgressionLibraryTests(unittest.TestCase):
    @staticmethod
    def _build(build_id: str, name: str, *, target="Anvil") -> dict:
        return config.normalize_build_definition_config(
            {
                "id": build_id,
                "name": name,
                "deadlines_enabled": True,
                "requirements": [
                    {
                        "id": f"{build_id}-requirement",
                        "kind": "item",
                        "target": target,
                        "required": 2,
                        "deadline": {"kind": "none", "stage": None, "seconds": None},
                    }
                ],
            }
        )

    @classmethod
    def _library(cls) -> dict:
        return {
            "schema_version": 3,
            "builds": [cls._build("one", "First"), cls._build("two", "Second")],
            "active_build_id": "one",
        }

    def test_active_definition_uses_only_the_selected_build(self):
        definition = active_definition_from_config(self._library())
        self.assertEqual(definition.name, "First")
        self.assertEqual([row.id for row in definition.requirements], ["one-requirement"])
        self.assertEqual(active_definition_from_config({}).requirements, ())

    def test_clone_generates_new_build_and_requirement_ids_and_unique_name(self):
        original = self._build("one", "First")
        duplicate = clone_build_config(original, ["First"])
        self.assertNotEqual(duplicate["id"], original["id"])
        self.assertNotEqual(
            duplicate["requirements"][0]["id"], original["requirements"][0]["id"]
        )
        self.assertEqual(duplicate["name"], "First (2)")

    def test_export_round_trip_strips_internal_ids_and_resolves_name_collision(self):
        original = self._build("one", "First")
        payload = build_export_payload(original)
        encoded = json.loads(json.dumps(payload))

        self.assertEqual(encoded["format"], "bonkscanner-build")
        self.assertNotIn("id", encoded["build"])
        self.assertNotIn("id", encoded["build"]["requirements"][0])

        imported = build_from_export_payload(encoded, ["First"])
        self.assertEqual(imported["name"], "First (2)")
        self.assertNotEqual(imported["id"], original["id"])
        self.assertNotEqual(
            imported["requirements"][0]["id"], original["requirements"][0]["id"]
        )

    def test_import_rejects_invalid_envelopes_and_partial_requirements(self):
        valid = build_export_payload(self._build("one", "First"))
        cases = [
            {},
            {**valid, "format": "other"},
            {**valid, "version": 99},
            {**valid, "build": {**valid["build"], "requirements": "bad"}},
            {
                **valid,
                "build": {
                    **valid["build"],
                    "requirements": [
                        {
                            "kind": "progress",
                            "target": "Unknown",
                            "required": 1,
                            "deadline": {"kind": "none"},
                        }
                    ],
                },
            },
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    build_from_export_payload(payload)

    def test_build_progression_uses_app_dialogs_for_messages_and_confirmations(self):
        tree = ast.parse(inspect.getsource(build_progression_dialogs))
        forbidden = {"QMessageBox", "QColorDialog", "QInputDialog"}
        used = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in forbidden
        }
        self.assertEqual(used, set())

    def test_manager_marks_active_card_and_switches_immediately(self):
        app = QApplication.instance() or QApplication([])
        state = self._library()
        writes = []

        def write(payload):
            nonlocal state
            state = config.normalize_build_progression_config(deepcopy(payload))
            writes.append(deepcopy(state))
            return deepcopy(state)

        service = MagicMock()
        manager = BuildProgressionManagerDialog(
            SimpleNamespace(read=lambda: deepcopy(state), write=write), service
        )
        self.addCleanup(manager.done, QDialog.Rejected)
        manager.show()
        app.processEvents()

        self.assertFalse(manager.card_widgets["one"]["active"].isEnabled())
        self.assertTrue(manager.card_widgets["two"]["active"].isEnabled())
        self.assertIsNotNone(
            manager.card_widgets["one"]["card"].findChild(QLabel, "condBadge")
        )

        manager._set_active("two")

        self.assertEqual(state["active_build_id"], "two")
        self.assertEqual(len(writes), 1)
        service.replace_definition.assert_called_once()
        self.assertEqual(service.replace_definition.call_args.args[0].name, "Second")
        self.assertFalse(manager.card_widgets["two"]["active"].isEnabled())

    def test_card_and_configure_button_open_editor_without_activating_build(self):
        app = QApplication.instance() or QApplication([])
        state = self._library()
        settings = SimpleNamespace(
            read=lambda: deepcopy(state),
            write=lambda payload: config.normalize_build_progression_config(payload),
        )
        manager = BuildProgressionManagerDialog(settings, MagicMock())
        self.addCleanup(manager.done, QDialog.Rejected)
        manager._edit_build = MagicMock()

        manager.card_widgets["two"]["open"].click()
        app.processEvents()

        manager._edit_build.assert_called_once_with("two")
        manager._edit_build.reset_mock()

        manager.card_widgets["two"]["configure"].click()
        app.processEvents()

        manager._edit_build.assert_called_once_with("two")
        self.assertEqual(manager.library["active_build_id"], "one")

    def test_deleting_active_build_selects_next_and_last_delete_leaves_empty(self):
        state = self._library()

        def write(payload):
            nonlocal state
            state = config.normalize_build_progression_config(deepcopy(payload))
            return deepcopy(state)

        service = MagicMock()
        manager = BuildProgressionManagerDialog(
            SimpleNamespace(read=lambda: deepcopy(state), write=write), service
        )
        self.addCleanup(manager.done, QDialog.Rejected)
        with patch("ui.dialogs.build_progression._ask_confirmation", return_value=True):
            manager._delete_build("one")
            self.assertEqual(state["active_build_id"], "two")
            manager._delete_build("two")

        self.assertEqual(state["builds"], [])
        self.assertIsNone(state["active_build_id"])
        self.assertEqual(service.replace_definition.call_count, 2)

    def test_manager_exports_and_imports_one_build_file(self):
        state = self._library()

        def write(payload):
            nonlocal state
            state = config.normalize_build_progression_config(deepcopy(payload))
            return deepcopy(state)

        manager = BuildProgressionManagerDialog(
            SimpleNamespace(read=lambda: deepcopy(state), write=write), MagicMock()
        )
        self.addCleanup(manager.done, QDialog.Rejected)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "shared-build.json"
            with (
                patch.object(
                    QFileDialog,
                    "getSaveFileName",
                    return_value=(str(path), ""),
                ) as save_picker,
                patch("ui.dialogs.build_progression._show_notice"),
            ):
                manager._export_build("one")
            self.assertEqual(save_picker.call_args.args[1], "Export Build")
            self.assertIn("*.json", save_picker.call_args.args[3])
            exported = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(exported["build"]["name"], "First")

            with (
                patch.object(
                    QFileDialog,
                    "getOpenFileName",
                    return_value=(str(path), ""),
                ) as open_picker,
                patch("ui.dialogs.build_progression._show_notice"),
            ):
                manager._import_build()
            self.assertEqual(open_picker.call_args.args[1], "Import Build")
            self.assertIn("*.json", open_picker.call_args.args[3])

        self.assertEqual(
            [build["name"] for build in state["builds"]],
            ["First", "Second", "First (2)"],
        )
        self.assertEqual(state["active_build_id"], "one")

    def test_first_saved_build_becomes_active_and_cancel_creates_nothing(self):
        state = {"schema_version": 3, "builds": [], "active_build_id": None}

        def write(payload):
            nonlocal state
            state = config.normalize_build_progression_config(deepcopy(payload))
            return deepcopy(state)

        service = MagicMock()
        manager = BuildProgressionManagerDialog(
            SimpleNamespace(read=lambda: deepcopy(state), write=write), service
        )
        self.addCleanup(manager.done, QDialog.Rejected)
        draft = self._build("created", "Created")

        cancelled = SimpleNamespace(exec=lambda: QDialog.Rejected, result_payload=None)
        with patch("ui.dialogs.build_progression.BuildProgressionDialog", return_value=cancelled):
            manager._open_editor(draft, create=True)
        self.assertEqual(state["builds"], [])

        saved = SimpleNamespace(exec=lambda: QDialog.Accepted, result_payload=draft)
        with patch("ui.dialogs.build_progression.BuildProgressionDialog", return_value=saved):
            manager._open_editor(draft, create=True)
        self.assertEqual([build["id"] for build in state["builds"]], ["created"])
        self.assertEqual(state["active_build_id"], "created")
        service.replace_definition.assert_called_once()

    def test_editing_inactive_build_does_not_reset_active_runtime_state(self):
        state = self._library()

        def write(payload):
            nonlocal state
            state = config.normalize_build_progression_config(deepcopy(payload))
            return deepcopy(state)

        service = MagicMock()
        manager = BuildProgressionManagerDialog(
            SimpleNamespace(read=lambda: deepcopy(state), write=write), service
        )
        self.addCleanup(manager.done, QDialog.Rejected)
        edited = deepcopy(state["builds"][1])
        edited["name"] = "Second Edited"
        child = SimpleNamespace(exec=lambda: QDialog.Accepted, result_payload=edited)
        with patch("ui.dialogs.build_progression.BuildProgressionDialog", return_value=child):
            manager._open_editor(deepcopy(state["builds"][1]), create=False)

        self.assertEqual(state["builds"][1]["name"], "Second Edited")
        service.replace_definition.assert_not_called()

    def test_editor_validates_unique_name_and_confirms_dirty_cancel(self):
        app = QApplication.instance() or QApplication([])
        dialog = BuildProgressionDialog(
            self._build("one", "First"), existing_names=["Second"]
        )
        self.addCleanup(dialog.done, QDialog.Rejected)
        dialog.show()
        app.processEvents()

        dialog.name_entry.setText("second")
        dialog._save()
        self.assertIsNone(dialog.result_payload)
        self.assertFalse(dialog.name_error.isHidden())

        dialog.name_entry.setText("Changed")
        with patch("ui.dialogs.build_progression._ask_confirmation", return_value=False):
            dialog.reject()
        self.assertTrue(dialog.isVisible())
        with patch("ui.dialogs.build_progression._ask_confirmation", return_value=True):
            dialog.reject()
        self.assertFalse(dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
