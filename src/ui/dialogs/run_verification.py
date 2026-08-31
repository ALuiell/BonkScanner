"""Progress and result dialogs for the Recordings run verifier."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.run_verifier import (
    FindingSeverity,
    MechanicsVerificationStatus,
    ProcessEnvironmentStatus,
    RecordingCoverageStatus,
    TARGET_STAT_LABELS,
    VerificationFinding,
    VerificationReport,
    mechanics_profile_display_name,
)
from ui.dialogs.shell import (
    DIALOG_REGULAR,
    DIALOG_TALL,
    DIALOG_WIDE,
    dialog_body,
    dialog_card,
    dialog_danger_card,
    dialog_footer,
    dialog_info_card,
    dialog_note,
)
from ui.shared import StagedLoadingSpinner, _make_scroll_section


_SEVERITY_LABELS = {
    FindingSeverity.INCONSISTENCY: "Conflict",
    FindingSeverity.WARNING: "Needs review",
    FindingSeverity.UNAVAILABLE: "Could not be checked",
    FindingSeverity.MATCH: "Passed",
}

_SEVERITY_ORDER = {
    FindingSeverity.INCONSISTENCY: 0,
    FindingSeverity.WARNING: 1,
    FindingSeverity.UNAVAILABLE: 2,
    FindingSeverity.MATCH: 3,
}


_MECHANICS_DETAILS = {
    MechanicsVerificationStatus.PASSED: (
        "All available component and legal-source equations agree."
    ),
    MechanicsVerificationStatus.PARTIAL: (
        "The recorded values were checked, but some exact source evidence is missing."
    ),
    MechanicsVerificationStatus.CONFLICT: (
        "At least one comparable, confirmed stat equation conflicts."
    ),
    MechanicsVerificationStatus.NOT_CHECKED: (
        "This recording does not contain supported verifier checkpoints."
    ),
}

_COVERAGE_DETAILS = {
    RecordingCoverageStatus.COMPLETE: "The verifier telemetry is continuous and finalized.",
    RecordingCoverageStatus.PARTIAL: "Some required verifier evidence is unavailable.",
    RecordingCoverageStatus.LATE_START: "The beginning of the run was not recorded.",
    RecordingCoverageStatus.INTERRUPTED: "A material telemetry break was recorded.",
    RecordingCoverageStatus.INVALID: "The recording structure contains conflicting data.",
    RecordingCoverageStatus.LEGACY: "This recording predates verifier telemetry.",
    RecordingCoverageStatus.UNSUPPORTED: "The recorded rules are not supported by this build.",
}

_ENVIRONMENT_DETAILS = {
    ProcessEnvironmentStatus.CLEAN: "No review-worthy runtime indicators were found.",
    ProcessEnvironmentStatus.MODIFIED_INSTALLATION: (
        "Loader files are installed, but no loader module was captured as active."
    ),
    ProcessEnvironmentStatus.MODIFIED_RUNTIME: (
        "A mod loader was active. This does not by itself prove cheating."
    ),
    ProcessEnvironmentStatus.NEEDS_REVIEW: (
        "Unknown modules, persistent executable memory, or runtime changes need review."
    ),
    ProcessEnvironmentStatus.PARTIAL: "The process-environment scan was incomplete.",
    ProcessEnvironmentStatus.NOT_RECORDED: "This recording has no environment telemetry.",
    ProcessEnvironmentStatus.UNAVAILABLE: "The process-environment scan did not succeed.",
    ProcessEnvironmentStatus.UNSUPPORTED: "This environment telemetry format is unsupported.",
}


def _status_tone(value) -> str:
    if value in {
        MechanicsVerificationStatus.CONFLICT,
        ProcessEnvironmentStatus.NEEDS_REVIEW,
    }:
        return "danger" if value is MechanicsVerificationStatus.CONFLICT else "warning"
    if value in {
        MechanicsVerificationStatus.PARTIAL,
        MechanicsVerificationStatus.NOT_CHECKED,
        RecordingCoverageStatus.PARTIAL,
        RecordingCoverageStatus.LATE_START,
        RecordingCoverageStatus.INTERRUPTED,
        RecordingCoverageStatus.INVALID,
        RecordingCoverageStatus.LEGACY,
        RecordingCoverageStatus.UNSUPPORTED,
        ProcessEnvironmentStatus.MODIFIED_INSTALLATION,
        ProcessEnvironmentStatus.MODIFIED_RUNTIME,
        ProcessEnvironmentStatus.PARTIAL,
        ProcessEnvironmentStatus.NOT_RECORDED,
        ProcessEnvironmentStatus.UNAVAILABLE,
        ProcessEnvironmentStatus.UNSUPPORTED,
    }:
        return (
            "danger"
            if value is RecordingCoverageStatus.INVALID
            else "warning"
        )
    return "success"


def _axis_card(title: str, value, detail: str, parent: QWidget) -> QFrame:
    card = QFrame(parent)
    card.setObjectName("RunVerificationAxisCard")
    card.setProperty("verificationTone", _status_tone(value))
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(3)
    title_label = QLabel(title, card)
    title_label.setObjectName("RunVerificationAxisTitle")
    value_label = QLabel(value.value, card)
    value_label.setObjectName("RunVerificationAxisValue")
    detail_label = QLabel(detail, card)
    detail_label.setObjectName("RunVerificationAxisDetail")
    detail_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(value_label)
    layout.addWidget(detail_label)
    return card


def _primary_summary(report: VerificationReport) -> tuple[str, str, str]:
    status = report.mechanics_status
    if status is MechanicsVerificationStatus.CONFLICT:
        return (
            "Conflicts found",
            "Comparable recorded stat values disagree. Review the confirmed conflicts below.",
            "inconsistent",
        )
    if status is MechanicsVerificationStatus.PASSED:
        return (
            "No stat conflicts found",
            "The available mechanics checks agree; coverage and environment are shown separately.",
            "consistent",
        )
    if status is MechanicsVerificationStatus.PARTIAL:
        return (
            "Stat checks partially complete",
            "No confirmed conflict is required for this result, but some source evidence is missing.",
            "partial",
        )
    return (
        "Stat checks unavailable",
        "This recording cannot be evaluated with the current mechanics rules.",
        "unsupported_build",
    )


def _group_actionable_findings(
    findings: tuple[VerificationFinding, ...],
) -> tuple[VerificationFinding, ...]:
    source_incomplete = tuple(
        finding
        for finding in findings
        if finding.severity is FindingSeverity.UNAVAILABLE
        and finding.title.endswith("source attribution is incomplete")
    )
    if len(source_incomplete) < 2:
        return findings
    affected = ", ".join(
        TARGET_STAT_LABELS[finding.stat_id]
        for finding in source_incomplete
        if finding.stat_id in TARGET_STAT_LABELS
    )
    grouped = VerificationFinding(
        category="Coverage and limitations",
        severity=FindingSeverity.UNAVAILABLE,
        title="Exact source breakdown is incomplete",
        detail=(
            "The component equations were still checked. Affected stats: "
            f"{affected or 'target stats'}."
        ),
        elapsed_seconds=min(
            (
                finding.elapsed_seconds
                for finding in source_incomplete
                if finding.elapsed_seconds is not None
            ),
            default=None,
        ),
        occurrence_count=max(finding.occurrence_count for finding in source_incomplete),
        last_elapsed_seconds=max(
            finding.last_elapsed_seconds or finding.elapsed_seconds or 0.0
            for finding in source_incomplete
        ),
    )
    source_ids = {id(finding) for finding in source_incomplete}
    return tuple(finding for finding in findings if id(finding) not in source_ids) + (
        grouped,
    )


def _target_stat_results(report: VerificationReport) -> str:
    rows = ["<b>Target stat results</b><br><br>"]
    for stat_id, label in TARGET_STAT_LABELS.items():
        findings = tuple(
            finding
            for finding in report.findings
            if finding.stat_id == stat_id
            and finding.severity is not FindingSeverity.MATCH
        )
        if any(
            finding.severity is FindingSeverity.INCONSISTENCY for finding in findings
        ):
            state = "Conflict found"
        elif any(finding.severity is FindingSeverity.UNAVAILABLE for finding in findings):
            state = "Partially checked"
        elif report.mechanics_status is MechanicsVerificationStatus.NOT_CHECKED:
            state = "Not checked"
        else:
            state = "Passed"
        rows.append(f"&bull; <b>{html.escape(label)}</b>: {state}<br>")
    return "".join(rows)


def _finding_time_text(finding: VerificationFinding) -> str:
    first = finding.elapsed_seconds
    last = finding.last_elapsed_seconds
    if first is None:
        return ""
    if last is not None and last > first + 0.05:
        return f"{first:.1f}s–{last:.1f}s"
    return f"{first:.1f}s"


def _finding_card_html(finding: VerificationFinding) -> str:
    label = _SEVERITY_LABELS[finding.severity]
    context: list[str] = []
    if finding.occurrence_count > 1:
        context.append(f"{finding.occurrence_count} observations")
    time_text = _finding_time_text(finding)
    if time_text:
        context.append(time_text)
    context_text = f" · {' · '.join(context)}" if context else ""
    detail = finding.latest_detail or finding.detail
    return (
        f"<b>{html.escape(label)} · {html.escape(finding.title)}</b>"
        f"{html.escape(context_text)}<br><br>"
        f"{html.escape(detail)}"
    )


def _finding_card(finding: VerificationFinding) -> QFrame:
    text = _finding_card_html(finding)
    if finding.severity is FindingSeverity.INCONSISTENCY:
        return dialog_danger_card(text)
    if finding.severity is FindingSeverity.WARNING:
        return dialog_card(text)
    return dialog_info_card(text)


def _add_findings_section(
    layout: QVBoxLayout,
    parent: QWidget,
    title: str,
    findings: tuple[VerificationFinding, ...],
) -> None:
    if not findings:
        return
    title_label = QLabel(title, parent)
    title_label.setObjectName("RunVerificationSectionTitle")
    layout.addWidget(title_label)
    for finding in findings:
        layout.addWidget(_finding_card(finding))


class VerificationProgressDialog(QDialog):
    def __init__(self, recording_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RunVerificationProgressDialog")
        self.setWindowTitle("Run Verification")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        body = dialog_body(
            self,
            title="Run Verification",
            subtitle=str(recording_name),
            width=DIALOG_REGULAR,
        )
        progress_layout = QVBoxLayout()
        progress_layout.setContentsMargins(12, 14, 12, 14)
        progress_layout.setSpacing(10)
        progress_layout.addStretch(1)
        # Keep an explicit Python reference in addition to Qt parentship.  The
        # spinner owns a QTimer whose signal points back to a bound method; if
        # only the C++ object tree retains it, cyclic GC can otherwise retire
        # the wrapper while the visible widget is painting.
        self._spinner = StagedLoadingSpinner(
            colors=("#38BDF8", "#A78BFA"),
            object_name="RunVerificationSpinner",
            parent=self,
        )
        progress_layout.addWidget(self._spinner, 0, Qt.AlignHCenter)
        text = QLabel("Analyzing recording…", self)
        text.setObjectName("RunVerificationProgressText")
        text.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(text, 0, Qt.AlignHCenter)
        progress_layout.addStretch(1)
        body.addLayout(progress_layout)

    def done(self, result: int) -> None:
        # Stop the animation before QDialog hides the native surface.  The
        # spinner's hideEvent is a second guard for parent-driven teardown.
        self._spinner.stop()
        super().done(result)


class RunVerificationGuideDialog(QDialog):
    """Explain verifier terminology without crowding the result dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RunVerificationGuideDialog")
        self.setWindowTitle("How Run Verification Works")
        self.setModal(True)
        body = dialog_body(
            self,
            title="How Run Verification Works",
            subtitle=(
                "What BonkScanner checks, how to read the result, and what the "
                "verdict does not prove."
            ),
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )
        scroll, _scroll_content, scroll_layout = _make_scroll_section()
        body.addWidget(scroll, 1)

        scroll_layout.addWidget(
            dialog_info_card(
                "<b>1. Three separate results</b><br><br>"
                "The Overview separates <b>Game mechanics</b>, <b>Recording "
                "coverage</b>, and <b>Game environment</b>. An environment warning "
                "does not turn a passed stat equation into a mechanics conflict, and "
                "missing coverage is not presented as cheating.<br><br>"
                "<b>What does Verify Run check?</b><br><br>"
                "BonkScanner checks whether the values stored in the recording agree "
                "with each other and with the currently validated game formulas. The "
                "pilot rules cover <b>Powerup Multiplier</b>, <b>Powerup Drop Chance</b>, "
                "and <b>Elite Spawn Increase</b>, including their recorded components "
                "and tracked sources. It also records a privacy-safe list of native "
                "modules loaded by the game and common mod-loader artifacts in the "
                "game directory, plus anonymous/private executable memory regions "
                "inside the game process.<br><br>"
                "This is a consistency check. It highlights conflicts and missing "
                "evidence for manual review; it is not a full anti-cheat. External "
                "memory tools, kernel drivers, very short-lived regions, and "
                "sophisticated manual mappings can still evade this pilot."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>2. Recording information</b><br><br>"
                "&bull; <b>Game build</b> identifies the version of Megabonk whose "
                "memory layout and formulas were used.<br>"
                "&bull; <b>BonkScanner version</b> identifies the app version that "
                "created the recording.<br>"
                "&bull; <b>Verification rules</b> identify the versioned formulas and "
                "memory layout used for the analysis. The Technical rules ID is its "
                "exact internal identifier.<br>"
                "&bull; <b>Process environment</b> summarizes native-module scans, "
                "mod-loader indicators, private executable memory, and meaningful "
                "changes during the run. Installed loader files and an actually loaded "
                "loader are shown as different states. A single recovered scan failure "
                "or a one-off read/execute page is not treated as a review indicator.<br>"
                "It does not store absolute file paths, raw memory addresses, "
                "memory contents, or a Windows username. Existing private executable "
                "pages form the start baseline; persistent, writable, or correlated "
                "new pages can be highlighted for review.<br>"
                "&bull; <b>Not recorded</b> means the recording file does not contain "
                "that information. This is expected for older recordings."
            )
        )
        scroll_layout.addWidget(
            dialog_info_card(
                "<b>3. Individual check labels</b><br><br>"
                "&bull; <b>Matched</b> means the recorded values passed that check.<br>"
                "&bull; <b>Inconsistent</b> means two values or formulas conflict.<br>"
                "&bull; <b>Warning</b> means the data is incomplete or unusual and "
                "should be reviewed.<br>"
                "&bull; <b>Unavailable</b> means there was not enough recorded "
                "information to perform that check. It is not automatically evidence "
                "of cheating."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>4. Overall result</b><br><br>"
                "&bull; <b>Consistent</b>: all available checks agree.<br>"
                "&bull; <b>Inconsistent</b>: at least one confirmed conflict was found.<br>"
                "&bull; <b>Review required</b>: the pilot found an unknown or "
                "unrecognized third-party module, an active mod loader, persistent "
                "or writable private executable memory, a meaningful runtime change, "
                "or repeated/unrecovered scan failures. This is a "
                "reason to inspect the evidence, not an "
                "automatic cheating verdict.<br>"
                "&bull; <b>Partial</b>: only part of the run could be checked.<br>"
                "&bull; <b>Late start</b>: recording began after the run had already "
                "started.<br>"
                "&bull; <b>Interrupted</b>: required telemetry has a recorded gap.<br>"
                "&bull; <b>Unsupported build</b>: the game build or verification rules "
                "have not been validated by this BonkScanner version."
            )
        )
        scroll_layout.addWidget(
            dialog_note(
                "A Consistent result means the recorded evidence agrees with the "
                "implemented checks. It does not prove that the run is legitimate or "
                "that the local recording file was never modified."
            )
        )
        scroll_layout.addStretch(1)

        close_button = QPushButton("Got It", self)
        close_button.clicked.connect(self.accept)
        dialog_footer(self, primary=close_button)


class RunVerificationDialog(QDialog):
    def __init__(self, report: VerificationReport, parent=None) -> None:
        super().__init__(parent)
        self.report = report
        self.setObjectName("RunVerificationDialog")
        self.setWindowTitle("Run Verification")
        body = dialog_body(
            self,
            title="Run Verification",
            subtitle=f"{report.recording_name}  ·  {report.created_at or 'Unknown date'}",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        primary_title, primary_detail, primary_tone = _primary_summary(report)
        summary = QFrame(self)
        summary.setObjectName("RunVerificationSummary")
        summary.setProperty("verificationStatus", primary_tone)
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(5)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        status = QLabel(primary_title, summary)
        status.setObjectName("RunVerificationStatus")
        status_row.addWidget(status)
        status_row.addStretch(1)
        how_it_works_button = QPushButton("How it works", summary)
        how_it_works_button.setObjectName("RunVerificationHowItWorks")
        how_it_works_button.clicked.connect(self.open_guide)
        status_row.addWidget(how_it_works_button)
        summary_layout.addLayout(status_row)

        headline = QLabel(primary_detail, summary)
        headline.setObjectName("RunVerificationHeadline")
        headline.setWordWrap(True)
        summary_layout.addWidget(headline)

        actionable_findings = _group_actionable_findings(
            tuple(
                sorted(
                    (
                        finding
                        for finding in report.findings
                        if finding.severity is not FindingSeverity.MATCH
                    ),
                    key=lambda finding: (
                        _SEVERITY_ORDER[finding.severity],
                        finding.category.casefold(),
                        finding.title.casefold(),
                    ),
                )
            )
        )
        counts = QLabel(
            f"3 monitored stats  ·  {report.coverage_text}  ·  "
            f"{len(actionable_findings)} grouped finding(s)",
            summary,
        )
        counts.setObjectName("RunVerificationCounts")
        counts.setWordWrap(True)
        summary_layout.addWidget(counts)
        body.addWidget(summary)

        axes = QHBoxLayout()
        axes.setContentsMargins(0, 0, 0, 0)
        axes.setSpacing(8)
        axes.addWidget(
            _axis_card(
                "Game mechanics",
                report.mechanics_status,
                _MECHANICS_DETAILS[report.mechanics_status],
                self,
            ),
            1,
        )
        axes.addWidget(
            _axis_card(
                "Recording coverage",
                report.coverage_status,
                _COVERAGE_DETAILS[report.coverage_status],
                self,
            ),
            1,
        )
        axes.addWidget(
            _axis_card(
                "Game environment",
                report.process_environment_status,
                _ENVIRONMENT_DETAILS[report.process_environment_status],
                self,
            ),
            1,
        )
        body.addLayout(axes)

        tabs = QTabWidget(self)
        tabs.setObjectName("RunVerificationTabs")

        overview = QWidget(tabs)
        overview.setObjectName("RunVerificationOverview")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 10, 0, 0)
        overview_layout.setSpacing(10)
        scroll, _scroll_content, scroll_layout = _make_scroll_section()
        overview_layout.addWidget(scroll, 1)

        scroll_layout.addWidget(dialog_info_card(_target_stat_results(report)))

        conflicts = tuple(
            finding
            for finding in actionable_findings
            if finding.severity is FindingSeverity.INCONSISTENCY
        )
        environment = tuple(
            finding
            for finding in actionable_findings
            if finding.category == "Process environment"
            and finding.severity is not FindingSeverity.INCONSISTENCY
        )
        limitations = tuple(
            finding
            for finding in actionable_findings
            if finding not in conflicts and finding not in environment
        )
        _add_findings_section(
            scroll_layout, overview, "Confirmed conflicts", conflicts
        )
        _add_findings_section(
            scroll_layout, overview, "Game environment review", environment
        )
        _add_findings_section(
            scroll_layout, overview, "Coverage and limitations", limitations
        )
        if not actionable_findings:
            scroll_layout.addWidget(
                dialog_info_card(
                    "<b>No problems found in the available checks</b><br><br>"
                    "The supported recorded evidence agrees."
                )
            )

        profile_name = mechanics_profile_display_name(report.mechanics_profile)
        recording_info = dialog_info_card(
            "<b>Recording information</b><br><br>"
            f"Game build: {html.escape(report.game_build_id or 'Not recorded')}<br>"
            f"BonkScanner: {html.escape(report.scanner_version or 'Not recorded')}<br>"
            f"Verification rules: {html.escape(profile_name)}"
        )
        scroll_layout.addWidget(recording_info)
        scroll_layout.addWidget(
            dialog_note(
                "This is a consistency analysis, not proof that a run is legitimate."
            )
        )
        scroll_layout.addStretch(1)
        tabs.addTab(overview, "Overview")

        self._report_text = QPlainTextEdit(self)
        self._report_text.setObjectName("RunVerificationReportText")
        self._report_text.setReadOnly(True)
        self._report_text.setPlainText(report.to_text(include_guide=False))
        technical = QWidget(tabs)
        technical_layout = QVBoxLayout(technical)
        technical_layout.setContentsMargins(0, 10, 0, 0)
        technical_layout.setSpacing(8)
        technical_layout.addWidget(
            dialog_note(
                "Grouped technical evidence for troubleshooting, sharing, and export."
            )
        )
        technical_layout.addWidget(self._report_text, 1)
        tabs.addTab(technical, "Technical details")
        body.addWidget(tabs, 1)

        self._guide_dialog: RunVerificationGuideDialog | None = None

        copy_button = QPushButton("Copy Report", self)
        copy_button.clicked.connect(self.copy_report)
        export_button = QPushButton("Export Report", self)
        export_button.clicked.connect(self.export_report)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        dialog_footer(
            self,
            primary=close_button,
            secondary=export_button,
            leading=copy_button,
        )

    def open_guide(self) -> None:
        if self._guide_dialog is None:
            self._guide_dialog = RunVerificationGuideDialog(self)
        self._guide_dialog.exec()

    def copy_report(self) -> None:
        QApplication.clipboard().setText(self.report.to_text())

    def export_report(self) -> None:
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.report.recording_name
        ).strip("_") or "run"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Run Verification",
            f"{safe_name}_verification.txt",
            "Text files (*.txt);;All files (*.*)",
        )
        if not selected:
            return
        try:
            Path(selected).write_text(self.report.to_text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
