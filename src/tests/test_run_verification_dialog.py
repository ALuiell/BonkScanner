from __future__ import annotations

import gc
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: E402,F401 -- path bootstrap
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QWidget,
)

from core.run_verifier import (  # noqa: E402
    FindingSeverity,
    MechanicsVerificationStatus,
    ProcessEnvironmentStatus,
    RecordingCoverageStatus,
    VerificationFinding,
    VerificationReport,
    VerificationStatus,
)
from ui.dialogs.run_verification import (  # noqa: E402
    RunVerificationDialog,
    RunVerificationGuideDialog,
    VerificationProgressDialog,
)
from ui.shared import StagedLoadingPage, StagedLoadingSpinner  # noqa: E402
from ui.tabs.player_stats.recordings import RecordingsTab  # noqa: E402


class RunVerificationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_progress_spinner_and_caption_are_centered_and_stacked(self) -> None:
        parent = QWidget()
        dialog = VerificationProgressDialog("Fixture", parent)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)

        dialog.show()
        self.qt.processEvents()

        spinner = dialog.findChild(StagedLoadingSpinner, "RunVerificationSpinner")
        caption = dialog.findChild(QLabel, "RunVerificationProgressText")
        self.assertIsNotNone(spinner)
        self.assertIsNotNone(caption)
        self.assertIs(dialog._spinner, spinner)
        self.assertTrue(spinner._timer.isActive())
        spinner_center = spinner.mapTo(dialog, spinner.rect().center())
        caption_center = caption.mapTo(dialog, caption.rect().center())
        self.assertLessEqual(
            abs(spinner_center.x() - dialog.rect().center().x()),
            1,
        )
        self.assertLessEqual(
            abs(caption_center.x() - dialog.rect().center().x()),
            1,
        )
        caption_top = caption.mapTo(dialog, caption.rect().topLeft()).y()
        spinner_bottom = spinner.mapTo(dialog, spinner.rect().bottomLeft()).y()
        self.assertGreater(caption_top, spinner_bottom)

        for _attempt in range(3):
            gc.collect()
            self.qt.processEvents()
        self.assertIs(dialog._spinner, spinner)

        dialog.done(QDialog.Accepted)
        self.qt.processEvents()
        self.assertFalse(spinner._timer.isActive())

    def test_staged_loading_page_retains_its_animated_spinner(self) -> None:
        page = StagedLoadingPage(
            lambda _workspace: iter(()),
            object_prefix="Fixture",
        )
        self.addCleanup(page.close)

        spinner = page.findChild(StagedLoadingSpinner, "FixtureLoadingSpinner")
        self.assertIsNotNone(spinner)
        self.assertIs(page._loading_spinner, spinner)

    @staticmethod
    def _report() -> VerificationReport:
        return VerificationReport(
            status=VerificationStatus.CONSISTENT,
            recording_name="Fixture",
            created_at="2026-08-30",
            game_build_id="pe-6980d323-036fa000",
            scanner_version="3.0.1",
            mechanics_profile="bonkscanner-target-stats-2026-08-30",
            checkpoint_count=1,
            event_count=0,
            match_count=12,
            inconsistency_count=0,
            warning_count=0,
            unavailable_count=0,
            findings=(),
            coverage_text="1/1 stable checkpoints",
            mechanics_status=MechanicsVerificationStatus.PASSED,
            coverage_status=RecordingCoverageStatus.COMPLETE,
            process_environment_status=ProcessEnvironmentStatus.CLEAN,
        )

    def test_result_uses_a_separate_how_it_works_dialog(self) -> None:
        parent = QWidget()
        dialog = RunVerificationDialog(self._report(), parent)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)

        button = dialog.findChild(QPushButton, "RunVerificationHowItWorks")
        report_text = dialog.findChild(QPlainTextEdit, "RunVerificationReportText")
        self.assertIsNotNone(button)
        self.assertEqual(button.text(), "How it works")
        self.assertIsNotNone(report_text)
        self.assertNotIn("Field guide:", report_text.toPlainText())

        with patch.object(RunVerificationGuideDialog, "exec", return_value=0) as opened:
            button.click()

        opened.assert_called_once_with()
        self.assertIsNotNone(dialog._guide_dialog)
        self.assertIs(dialog._guide_dialog.parent(), dialog)

    def test_result_is_a_wide_overview_with_separate_technical_details(self) -> None:
        parent = QWidget()
        dialog = RunVerificationDialog(self._report(), parent)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)

        tabs = dialog.findChild(QTabWidget, "RunVerificationTabs")
        self.assertGreaterEqual(dialog.minimumWidth(), 900)
        self.assertIsNotNone(tabs)
        self.assertEqual(tabs.count(), 2)
        self.assertEqual(tabs.tabText(0), "Overview")
        self.assertEqual(tabs.tabText(1), "Technical details")
        self.assertEqual(tabs.currentIndex(), 0)
        overview_text = " ".join(
            label.text() for label in tabs.widget(0).findChildren(QLabel)
        )
        self.assertIn("Target stat results", overview_text)
        self.assertIn("No problems found in the available checks", overview_text)
        axis_values = {
            label.text()
            for label in dialog.findChildren(QLabel, "RunVerificationAxisValue")
        }
        self.assertEqual(axis_values, {"Passed", "Complete", "Clean"})

    def test_repeated_findings_render_as_one_grouped_issue(self) -> None:
        base = self._report()
        report = VerificationReport(
            **{
                **base.__dict__,
                "status": VerificationStatus.INCONSISTENT,
                "mechanics_status": MechanicsVerificationStatus.CONFLICT,
                "inconsistency_count": 143,
                "findings": (
                    VerificationFinding(
                        category="Source reconciliation",
                        severity=FindingSeverity.INCONSISTENCY,
                        title=(
                            "Powerup Multiplier permanent modifiers do not match "
                            "additive component"
                        ),
                        detail="Component delta 0; modifier sum 0.160776878.",
                        elapsed_seconds=72.2,
                        stat_id=40,
                        occurrence_count=143,
                        last_elapsed_seconds=366.3,
                        latest_detail="Component delta 0; modifier sum 0.674582017.",
                    ),
                ),
            }
        )
        parent = QWidget()
        dialog = RunVerificationDialog(report, parent)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)

        tabs = dialog.findChild(QTabWidget, "RunVerificationTabs")
        overview_text = " ".join(
            label.text() for label in tabs.widget(0).findChildren(QLabel)
        )
        title = "Powerup Multiplier permanent modifiers do not match additive component"
        self.assertEqual(overview_text.count(title), 1)
        self.assertIn("143 observations", overview_text)
        self.assertIn("72.2s–366.3s", overview_text)
        details = dialog.findChild(QPlainTextEdit, "RunVerificationReportText")
        self.assertIn("72.2s-366.3s (143 occurrences)", details.toPlainText())

    def test_how_it_works_dialog_explains_fields_checks_and_limits(self) -> None:
        parent = QWidget()
        guide = RunVerificationGuideDialog(parent)
        self.addCleanup(parent.close)
        self.addCleanup(guide.close)

        text = " ".join(label.text() for label in guide.findChildren(QLabel))
        self.assertIn("Game build", text)
        self.assertIn("Verification rules", text)
        self.assertIn("Matched", text)
        self.assertIn("Process environment", text)
        self.assertIn("Review required", text)
        self.assertIn("private executable memory", text)
        self.assertIn("manual mappings", text)
        self.assertIn("Unsupported build", text)
        self.assertIn("does not prove that the run is legitimate", text)

    def test_environment_warning_does_not_relabel_passed_mechanics(self) -> None:
        base = self._report()
        report = VerificationReport(
            **{
                **base.__dict__,
                "status": VerificationStatus.REVIEW_REQUIRED,
                "warning_count": 1,
                "process_environment_status": (
                    ProcessEnvironmentStatus.MODIFIED_RUNTIME
                ),
                "findings": (
                    VerificationFinding(
                        category="Process environment",
                        severity=FindingSeverity.WARNING,
                        title="A mod loader was active in the game process",
                        detail="Loaded module: winhttp.dll.",
                    ),
                ),
            }
        )
        parent = QWidget()
        dialog = RunVerificationDialog(report, parent)
        self.addCleanup(parent.close)
        self.addCleanup(dialog.close)

        summary = dialog.findChild(QLabel, "RunVerificationStatus")
        self.assertEqual(summary.text(), "No stat conflicts found")
        axis_values = {
            label.text()
            for label in dialog.findChildren(QLabel, "RunVerificationAxisValue")
        }
        self.assertEqual(axis_values, {"Passed", "Complete", "Modified runtime"})


class RecordingsVerificationLifecycleTests(unittest.TestCase):
    class _Progress:
        instances = []

        def __init__(self, recording_name, parent) -> None:
            self.recording_name = recording_name
            self.parent = parent
            self.shown = False
            self.done_result = None
            self.delete_later_called = False
            self.instances.append(self)

        def show(self) -> None:
            self.shown = True

        def done(self, result) -> None:
            self.done_result = result

        def deleteLater(self) -> None:
            self.delete_later_called = True

    class _Result:
        instances = []

        def __init__(self, report, parent) -> None:
            self.report = report
            self.parent = parent
            self.exec_called = False
            self.delete_later_called = False
            self.instances.append(self)

        def exec(self) -> int:
            self.exec_called = True
            return QDialog.Accepted

        def deleteLater(self) -> None:
            self.delete_later_called = True

    def setUp(self) -> None:
        self._Progress.instances = []
        self._Result.instances = []

    def _view(self) -> RecordingsTab:
        parent = object()
        view = RecordingsTab(
            tabview=SimpleNamespace(),
            vod_library=SimpleNamespace(),
            window=lambda: parent,
            vod_recorder=lambda: SimpleNamespace(is_recording=False, path=None),
            is_active=lambda: True,
            log=lambda *_args, **_kwargs: None,
            schedule=None,
        )
        view._loaded_vod = SimpleNamespace(
            metadata=SimpleNamespace(path=Path("fixture.jsonl"), name="Fixture"),
            snapshots=(),
        )
        return view

    def test_completed_verification_retires_both_dialogs(self) -> None:
        view = self._view()
        report = RunVerificationDialogTests._report()

        with (
            patch(
                "ui.tabs.player_stats.recordings.VerificationProgressDialog",
                self._Progress,
            ),
            patch(
                "ui.tabs.player_stats.recordings.RunVerificationDialog",
                self._Result,
            ),
            patch("ui.tabs.player_stats.recordings.verify_vod", return_value=report),
        ):
            view.verify_selected_vod()

        progress = self._Progress.instances[0]
        result = self._Result.instances[0]
        self.assertTrue(progress.shown)
        self.assertEqual(progress.done_result, QDialog.Accepted)
        self.assertTrue(progress.delete_later_called)
        self.assertTrue(result.exec_called)
        self.assertTrue(result.delete_later_called)
        self.assertIsNone(view._verification_progress_dialog)
        self.assertIsNone(view._verification_result_dialog)
        self.assertFalse(view._verification_in_progress)

    def test_invalidated_verification_retires_progress_dialog(self) -> None:
        view = self._view()
        progress = self._Progress("Fixture", object())
        view._verification_progress_dialog = progress
        view._verification_in_progress = True

        view._invalidate_verification_ui()

        self.assertEqual(progress.done_result, QDialog.Rejected)
        self.assertTrue(progress.delete_later_called)
        self.assertIsNone(view._verification_progress_dialog)
        self.assertFalse(view._verification_in_progress)


if __name__ == "__main__":
    unittest.main()
