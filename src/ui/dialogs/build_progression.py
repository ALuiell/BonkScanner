"""Build Progression library manager and the shared build editor."""
from __future__ import annotations

from copy import deepcopy
from html import escape
import os
from pathlib import Path
import re
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QFileDialog, QLineEdit, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from app.build_progression import (
    active_build_from_config,
    build_export_payload,
    build_from_export_payload,
    clone_build_config,
    definition_from_config,
    unique_build_name,
)
from app import config
from core.stats.formats import PlayerStatFormat
from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL
from core.build_progression import PROGRESS_TARGETS, CAP_SUPPORTED_ITEMS
from core.json_safety import dumps_strict_json, loads_strict_json
from projections.tracked_items import (
    available_tracked_item_names,
    group_tracked_items_by_rarity,
    tracked_item_color,
    tracked_item_display_name,
    tracked_item_rarity_rank,
)
from ui.dialogs.tracked_items import _chip_stylesheet, _pick_stylesheet
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
from ui.shared import FlowLayout, _clear_layout
from ui.styles import (
    _template_manager_card_stylesheet,
    _template_manager_header_stylesheet,
)


DEADLINE_OPTIONS = (
    ("none", "No deadline", "Track progress only"),
    ("stage_start", "Before tier", "Complete before a tier begins"),
    ("stage_overtime", "Tier overtime", "Complete before an OT minute"),
)

KIND_COLORS = {
    "stat": "#93C5FD",
    "progress": "#5EEAD4",
}


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _eyebrow(text: str) -> QLabel:
    label = QLabel(str(text).upper())
    label.setObjectName("kpiLabel")
    return label


def _build_pick_stylesheet(colour: str) -> str:
    # The shared picker only changes the fill on hover. In this dense editor
    # that leaves the strong checked outline on a different chip, which makes
    # the visual hover target appear offset from the cursor.
    return (
        _pick_stylesheet(colour)
        + "QPushButton#pickChip:hover {"
        + f"border: 1px solid {colour};"
        + "}"
    )


class BuildProgressionNoticeDialog(QDialog):
    """A silent, app-styled replacement for native QMessageBox notices."""

    def __init__(self, parent, *, title: str, message: str, danger: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(str(title))
        body = dialog_body(
            self,
            title=str(title),
            subtitle="Build Progression",
            width=DIALOG_REGULAR,
        )
        safe_message = escape(str(message)).replace("\n", "<br>")
        body.addWidget(
            dialog_danger_card(safe_message)
            if danger
            else dialog_info_card(safe_message)
        )
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        dialog_footer(self, primary=close_button)


class BuildProgressionConfirmDialog(QDialog):
    """A silent, app-styled yes/no decision with an explicit result."""

    def __init__(
        self,
        parent,
        *,
        title: str,
        message: str,
        confirm_text: str,
        destructive: bool = False,
    ) -> None:
        super().__init__(parent)
        self.confirmed = False
        self.setWindowTitle(str(title))
        body = dialog_body(self, title=str(title), width=DIALOG_REGULAR)
        message_label = QLabel(str(message))
        message_label.setObjectName("dialogSubject")
        message_label.setWordWrap(True)
        body.addWidget(message_label)
        if destructive:
            body.addWidget(dialog_note("This action cannot be undone."))
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        confirm_button = QPushButton(str(confirm_text))
        confirm_button.clicked.connect(self._confirm)
        if destructive:
            dialog_footer(
                self,
                secondary=cancel_button,
                destructive=confirm_button,
            )
        else:
            dialog_footer(self, secondary=cancel_button, primary=confirm_button)

    def _confirm(self) -> None:
        self.confirmed = True
        self.accept()


def _release_dialog(dialog) -> None:
    """Release a modal even if its parent died inside the nested event loop."""
    if dialog is None:
        return
    delete_later = getattr(dialog, "deleteLater", None)
    if not callable(delete_later):
        return
    try:
        delete_later()
    except RuntimeError:
        pass


def _show_notice(parent, title: str, message: str, *, danger: bool = False) -> None:
    dialog = BuildProgressionNoticeDialog(
        parent,
        title=title,
        message=message,
        danger=danger,
    )
    try:
        dialog.exec()
    finally:
        _release_dialog(dialog)


def _ask_confirmation(
    parent,
    title: str,
    message: str,
    *,
    confirm_text: str,
    destructive: bool = False,
) -> bool:
    dialog = BuildProgressionConfirmDialog(
        parent,
        title=title,
        message=message,
        confirm_text=confirm_text,
        destructive=destructive,
    )
    try:
        dialog.exec()
        return dialog.confirmed
    finally:
        _release_dialog(dialog)


class BuildProgressionHelpDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How Build Progression Works")
        self.setModal(True)
        layout = dialog_body(
            self,
            title="How Build Progression Works",
            subtitle="A complete guide to building, tracking, and displaying your live checklist.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        scroll = QScrollArea()
        scroll.setObjectName("buildProgressionGuideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scroll_content.setObjectName("cardContent")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        scroll_layout.addWidget(
            dialog_info_card(
                "<b>1. Create a build and make it active</b><br><br>"
                "Open <b>Build Progression</b> from the Live Stats tab. Your library can hold "
                "multiple builds: create, configure, duplicate, delete, import, or export them "
                "as JSON files.<br><br>"
                "Only one build is tracked at a time. Select <b>Set Active</b> on its library "
                "card; editing another build does not activate it."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>2. Add and arrange requirements</b><br><br>"
                "Choose a target from the catalog, enter its required value, configure an "
                "optional deadline, and add it to the checklist. Existing rows can be edited, "
                "reordered, or removed before you save the build.<br><br>"
                "&bull; <b>Items</b> track copies in the inventory.<br>"
                "&bull; <b>Stats</b> track live player attributes; the editor handles percentage "
                "and multiplier display formats for you.<br>"
                "&bull; <b>Progress</b> tracks whole-number run goals such as Kills and Player Level."
            )
        )
        scroll_layout.addWidget(
            dialog_info_card(
                "<b>3. Min, Max, Ideal, and Cap targets</b><br><br>"
                "The required value is the <b>Min</b>. An item may also have a <b>Max</b>, and a "
                "stat may have an <b>Ideal</b>. Once Min is reached, the displayed target switches "
                "to Max or Ideal and stays active until that second target is reached. The live "
                "checklist shows only the new number, without a Max or Ideal label.<br><br>"
                "Supported radius items can use <b>Cap</b> instead of a fixed Max. Cap starts with "
                "the first copy and calculates the remaining copies from the captured Size stat; "
                "it updates as the run changes. An em dash means the cap cannot be resolved yet.<br><br>"
                "Progress requirements use one target only."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>4. Deadlines apply to Min</b><br><br>"
                "Choose <b>No deadline</b>, <b>Before tier</b>, or <b>Tier overtime</b>. Before tier "
                "must be completed before that tier starts; Tier overtime adds a minute target "
                "inside the selected tier.<br><br>"
                "The deadline judges when Min was first reached. Reaching Max, Ideal, or Cap later "
                "does not make an on-time Min late. If Min was late, that late result remains visible "
                "while the second target is active and after the full requirement is completed.<br><br>"
                "A deadline turns yellow in its final two minutes and red when overdue."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>5. Read the live checklist</b><br><br>"
                "Rows are grouped as <b>Items, Stats, then Progress</b>. Item names use rarity "
                "colours, Stats are blue, and Progress is teal. Symbols and deadline colours show "
                "whether a row is active, completed on time, or completed late.<br><br>"
                "Within each group, active Min targets come first, followed by active Max, Ideal, "
                "or Cap targets and then rows without deadlines. Completed-on-time rows follow, "
                "then rows completed late, with overdue unfinished requirements at the end. "
                "Active Min targets with the nearest deadlines rise within their group."
            )
        )
        scroll_layout.addWidget(
            dialog_info_card(
                "<b>6. Control what remains visible</b><br><br>"
                "Turn <b>Show completed</b> off to remove every fully completed row, including "
                "requirements completed late. A row that has reached Min but is still working "
                "toward Max, Ideal, or Cap remains visible because it is still active.<br><br>"
                "The row limit caps how many unfinished requirements are shown. When nothing "
                "remains, the widget collapses to the build-complete state."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>7. One active build, several live surfaces</b><br><br>"
                "The same active build and runtime progress are shared by the <b>Live Stats</b> "
                "tab, <b>OBS widget</b>, <b>in-game overlay</b>, and Twitch <b>!build</b> command. "
                "Changing the active build updates every surface.<br><br>"
                "Display controls are independent: OBS and the in-game overlay keep their own "
                "enabled state, scale, row limit, and Show completed preference where available."
            )
        )
        scroll_layout.addWidget(
            dialog_note(
                "Build definitions stay saved between runs, but live completion, late status, "
                "and completion times reset when a new run begins. If a live value falls below "
                "its current target, that requirement can become active again."
            )
        )
        scroll_layout.addStretch(1)

        close_button = QPushButton("Got It")
        close_button.clicked.connect(self.accept)
        dialog_footer(self, primary=close_button)


def show_build_progression_help(parent=None) -> None:
    dialog = BuildProgressionHelpDialog(parent)
    try:
        dialog.exec()
    finally:
        _release_dialog(dialog)


class BuildProgressionManagerDialog(QDialog):
    """A lightweight hub; each card opens the existing full build editor."""

    CARD_COLOUR = "#5BA7FF"

    def __init__(self, settings, service, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build Progression")
        self._settings = settings
        self._service = service
        self._library = config.normalize_build_progression_config(settings.read())
        self._persisted_library = deepcopy(self._library)
        self.card_widgets: dict[str, dict[str, QWidget]] = {}
        self.changed = False

        layout = dialog_body(
            self,
            title="Build Progression",
            subtitle="Choose a build to configure, or select which build all live surfaces track.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        library_label = _eyebrow("Build library")
        toolbar.addWidget(library_label)
        toolbar.addStretch(1)
        self.import_button = QPushButton("Import Build")
        self.import_button.clicked.connect(self._import_build)
        toolbar.addWidget(self.import_button)
        self.new_button = QPushButton("New Build")
        self.new_button.setObjectName("primary")
        self.new_button.clicked.connect(self._new_build)
        toolbar.addWidget(self.new_button)
        layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("cardContent")
        self.cards_layout = QVBoxLayout(self.scroll_content)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(10)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll, 1)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        dialog_footer(self, secondary=close_button)
        self._refresh_cards()

    @property
    def library(self) -> dict:
        return deepcopy(self._library)

    def _builds(self) -> list[dict]:
        return self._library.setdefault("builds", [])

    def _build(self, build_id: str) -> dict | None:
        return next(
            (build for build in self._builds() if str(build.get("id")) == str(build_id)),
            None,
        )

    def _existing_names(self, *, exclude_id: str | None = None) -> list[str]:
        return [
            str(build.get("name") or "")
            for build in self._builds()
            if str(build.get("id")) != str(exclude_id)
        ]

    def _persist(self, *, refresh_service: bool) -> bool:
        try:
            saved = self._settings.write(deepcopy(self._library))
            if not isinstance(saved, dict):
                raise TypeError("The settings writer returned an invalid build library.")
            self._library = config.normalize_build_progression_config(saved)
        except Exception as exc:
            self._library = deepcopy(self._persisted_library)
            self._refresh_cards()
            _show_notice(
                self,
                "Build Progression Not Saved",
                str(exc) or "The build library could not be saved.",
                danger=True,
            )
            return False
        self._persisted_library = deepcopy(self._library)
        self.changed = True
        # Refresh before a service error can open another nested modal. The
        # application may close from that nested event loop and destroy this
        # manager, so no QWidget must be touched after the warning returns.
        self._refresh_cards()
        if refresh_service:
            try:
                self._service.replace_definition(
                    definition_from_config(active_build_from_config(self._library))
                )
            except Exception as exc:
                _show_notice(
                    self,
                    "Build Saved with Warnings",
                    "The build was saved, but live surfaces could not be refreshed. "
                    f"Restart BonkScanner before relying on it.\n\n{exc}",
                    danger=True,
                )
        return True

    def _refresh_cards(self) -> None:
        _clear_layout(self.cards_layout)
        self.card_widgets.clear()
        builds = self._builds()
        if not builds:
            self.cards_layout.addWidget(self._build_empty_state())
            self.cards_layout.addStretch(1)
            return
        active_id = str(self._library.get("active_build_id") or "")
        for build in builds:
            build_id = str(build.get("id") or "")
            card = self._build_card(build, active=build_id == active_id)
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)

    def _build_empty_state(self) -> QWidget:
        card = _card()
        card.setObjectName("BuildManagerEmpty")
        body = QVBoxLayout(card)
        body.setContentsMargins(24, 28, 24, 28)
        body.setSpacing(12)
        title = QLabel("No builds yet")
        title.setObjectName("sectionTitle")
        title.setAlignment(Qt.AlignCenter)
        body.addWidget(title)
        note = QLabel(
            "Create a build from scratch or import a shared BonkScanner build file."
        )
        note.setObjectName("dialogHint")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        body.addWidget(note)
        actions = QHBoxLayout()
        actions.addStretch(1)
        import_button = QPushButton("Import Build")
        import_button.clicked.connect(self._import_build)
        actions.addWidget(import_button)
        create_button = QPushButton("New Build")
        create_button.setObjectName("primary")
        create_button.clicked.connect(self._new_build)
        actions.addWidget(create_button)
        actions.addStretch(1)
        body.addLayout(actions)
        return card

    @staticmethod
    def _summary(build: dict) -> str:
        counts = {"item": 0, "stat": 0, "progress": 0}
        for requirement in build.get("requirements") or ():
            kind = str(requirement.get("kind") or "")
            if kind in counts:
                counts[kind] += 1
        return (
            f"Items {counts['item']}  •  Stats {counts['stat']}  •  "
            f"Progress {counts['progress']}"
        )

    @staticmethod
    def _display_name(name: str) -> str:
        return name if len(name) <= 72 else f"{name[:69]}…"

    def _build_card(self, build: dict, *, active: bool) -> QWidget:
        build_id = str(build.get("id") or "")
        name = str(build.get("name") or "Build Progression")
        card = QFrame()
        card.setObjectName("TemplateManagerCard")
        card.setStyleSheet(
            _template_manager_card_stylesheet(self.CARD_COLOUR, active)
        )
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 14, 16, 14)
        body.setSpacing(10)

        header = QHBoxLayout()
        open_button = QPushButton(self._display_name(name))
        open_button.setObjectName("BuildManagerOpen")
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setToolTip(f"Configure {name}")
        open_button.setMinimumWidth(0)
        open_button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        open_button.setStyleSheet(
            _template_manager_header_stylesheet(self.CARD_COLOUR)
        )
        open_button.clicked.connect(
            lambda _checked=False, selected_id=build_id: self._edit_build(selected_id)
        )
        header.addWidget(open_button, 1)
        if active:
            badge = QLabel("ACTIVE")
            badge.setObjectName("condBadge")
            badge.setToolTip("This build is shown in Live Stats, overlays, and Twitch")
            header.addWidget(badge)
        body.addLayout(header)

        summary = QLabel(self._summary(build))
        summary.setObjectName("dialogHint")
        body.addWidget(summary)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        configure_button = QPushButton("Configure")
        configure_button.setToolTip(f"Configure {name}")
        configure_button.clicked.connect(
            lambda _checked=False, selected_id=build_id: self._edit_build(selected_id)
        )
        actions.addWidget(configure_button)
        active_button = QPushButton("Active" if active else "Set Active")
        active_button.setEnabled(not active)
        active_button.setToolTip(
            "Currently active" if active else "Use this build on every live surface"
        )
        active_button.clicked.connect(
            lambda _checked=False, selected_id=build_id: self._set_active(selected_id)
        )
        actions.addWidget(active_button)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(
            lambda _checked=False, selected_id=build_id: self._duplicate_build(selected_id)
        )
        actions.addWidget(duplicate_button)
        export_button = QPushButton("Export")
        export_button.clicked.connect(
            lambda _checked=False, selected_id=build_id: self._export_build(selected_id)
        )
        actions.addWidget(export_button)
        delete_button = QPushButton("Delete")
        delete_button.setObjectName("danger")
        delete_button.clicked.connect(
            lambda _checked=False, selected_id=build_id: self._delete_build(selected_id)
        )
        actions.addWidget(delete_button)
        body.addLayout(actions)
        self.card_widgets[build_id] = {
            "card": card,
            "open": open_button,
            "configure": configure_button,
            "active": active_button,
            "duplicate": duplicate_button,
            "export": export_button,
            "delete": delete_button,
        }
        return card

    def _open_editor(self, build: dict, *, create: bool) -> None:
        build_id = str(build.get("id") or "")
        dialog = None
        try:
            dialog = BuildProgressionDialog(
                build,
                existing_names=self._existing_names(
                    exclude_id=None if create else build_id
                ),
                parent=self,
            )
            if dialog.exec() != QDialog.Accepted or dialog.result_payload is None:
                return
            result = deepcopy(dialog.result_payload)
        except Exception as exc:
            _show_notice(
                self,
                "Build Editor Error",
                str(exc) or "The build editor could not be opened.",
                danger=True,
            )
            return
        finally:
            _release_dialog(dialog)
        if create:
            self._builds().append(result)
            became_active = not self._library.get("active_build_id")
            if became_active:
                self._library["active_build_id"] = result["id"]
            self._persist(refresh_service=became_active)
            return
        for index, current in enumerate(self._builds()):
            if str(current.get("id")) == build_id:
                self._builds()[index] = result
                break
        self._persist(
            refresh_service=str(self._library.get("active_build_id") or "") == build_id
        )

    def _new_build(self) -> None:
        draft = config.normalize_build_definition_config(
            {
                "id": uuid4().hex,
                "name": unique_build_name("New Build", self._existing_names()),
                "deadlines_enabled": True,
                "requirements": [],
            }
        )
        self._open_editor(draft, create=True)

    def _edit_build(self, build_id: str) -> None:
        build = self._build(build_id)
        if build is not None:
            self._open_editor(deepcopy(build), create=False)

    def _duplicate_build(self, build_id: str) -> None:
        build = self._build(build_id)
        if build is None:
            return
        duplicate = clone_build_config(build, self._existing_names())
        self._open_editor(duplicate, create=True)

    def _set_active(self, build_id: str) -> None:
        if self._build(build_id) is None:
            return
        if str(self._library.get("active_build_id") or "") == build_id:
            return
        self._library["active_build_id"] = build_id
        self._persist(refresh_service=True)

    def _delete_build(self, build_id: str) -> None:
        build = self._build(build_id)
        if build is None:
            return
        if not _ask_confirmation(
            self,
            "Delete Build",
            f'Delete "{build.get("name") or "Build Progression"}"?',
            confirm_text="Delete",
            destructive=True,
        ):
            return
        builds = self._builds()
        index = next(
            (i for i, current in enumerate(builds) if str(current.get("id")) == build_id),
            None,
        )
        if index is None:
            return
        was_active = str(self._library.get("active_build_id") or "") == build_id
        del builds[index]
        if was_active:
            self._library["active_build_id"] = (
                builds[min(index, len(builds) - 1)]["id"] if builds else None
            )
        self._persist(refresh_service=was_active)

    def _import_build(self) -> None:
        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Build",
            "",
            "BonkScanner Build (*.json);;JSON Files (*.json)",
        )
        if not filename:
            return
        try:
            payload = loads_strict_json(Path(filename).read_text(encoding="utf-8"))
            build = build_from_export_payload(payload, self._existing_names())
        except (OSError, UnicodeError, ValueError) as exc:
            _show_notice(self, "Import Failed", str(exc), danger=True)
            return
        became_active = not self._library.get("active_build_id")
        self._builds().append(build)
        if became_active:
            self._library["active_build_id"] = build["id"]
        if not self._persist(refresh_service=became_active):
            return
        _show_notice(
            self,
            "Build Imported",
            f'Imported "{build["name"]}".',
        )

    @staticmethod
    def _safe_filename(name: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name)).strip(" ._")
        return safe or "BonkScanner Build"

    def _export_build(self, build_id: str) -> None:
        build = self._build(build_id)
        if build is None:
            return
        suggested = f"{self._safe_filename(str(build.get('name') or 'Build'))}.json"
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Build",
            suggested,
            "BonkScanner Build (*.json);;JSON Files (*.json)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                dumps_strict_json(
                    build_export_payload(build), indent=2, ensure_ascii=False
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            _show_notice(
                self,
                "Export Failed",
                f"Could not export the build: {exc}",
                danger=True,
            )
            return
        _show_notice(
            self,
            "Build Exported",
            f'Exported "{build.get("name") or "Build Progression"}".',
        )


def show_build_progression_manager(settings, service, parent=None) -> bool:
    """Run the one-shot library manager and release all of its child dialogs."""
    dialog = None
    try:
        dialog = BuildProgressionManagerDialog(settings, service, parent)
        dialog.exec()
        return bool(dialog.changed)
    except Exception as exc:
        try:
            _show_notice(
                parent,
                "Build Progression Error",
                str(exc) or "Build Progression could not be opened.",
                danger=True,
            )
        except Exception:
            pass
        return False
    finally:
        _release_dialog(dialog)


class BuildProgressionDialog(QDialog):
    def __init__(self, build=None, *, existing_names=(), parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure Build")
        self.result_payload: dict | None = None
        self._draft = config.normalize_build_definition_config(build or {})
        self._original_draft = deepcopy(self._draft)
        self._existing_names = {
            str(name).strip().casefold() for name in existing_names if str(name).strip()
        }
        self._editing_id: str | None = None
        self._editing_form_snapshot: tuple | None = None

        layout = dialog_body(
            self,
            title="Configure Build",
            subtitle="Define the items, stats, and run progress the build needs.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL + 40,
        )
        general_card = _card()
        general_outer = QVBoxLayout(general_card)
        general_outer.setContentsMargins(12, 12, 12, 12)
        general_outer.setSpacing(6)
        general = QGridLayout()
        general.setContentsMargins(0, 0, 0, 0)
        general.setHorizontalSpacing(10)
        general.setVerticalSpacing(8)
        general.addWidget(_eyebrow("Build definition"), 0, 0)
        self.name_entry = QLineEdit(str(self._draft.get("name") or "Build Progression"))
        self.name_entry.setPlaceholderText("Build name")
        general.addWidget(self.name_entry, 0, 1, 1, 2)
        self.deadlines_enabled = QCheckBox("Use deadlines")
        self.deadlines_enabled.setChecked(bool(self._draft.get("deadlines_enabled", True)))
        general.addWidget(self.deadlines_enabled, 1, 1)
        help_btn = QPushButton("How it works")
        help_btn.clicked.connect(lambda: show_build_progression_help(self))
        general.addWidget(help_btn, 1, 2)
        general.setColumnStretch(1, 1)
        general_outer.addLayout(general)
        self.name_error = QLabel()
        self.name_error.setObjectName("formError")
        self.name_error.hide()
        general_outer.addWidget(self.name_error)
        self.name_entry.textChanged.connect(self._clear_name_error)
        layout.addWidget(general_card)

        self._split = QSplitter(Qt.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._build_left_column())
        self._split.addWidget(self._build_right_column())
        self._split.setStretchFactor(0, 42)
        self._split.setStretchFactor(1, 58)
        self._split.setSizes([500, 700])
        layout.addWidget(self._split, 1)

        save = QPushButton("Save")
        cancel = QPushButton("Cancel")
        self.clear_button = QPushButton("Remove all")
        self.clear_button.clicked.connect(self._remove_all)
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        dialog_footer(
            self,
            primary=save,
            secondary=cancel,
            destructive=self.clear_button,
        )

        self._refresh_picker()
        self._select_target("")
        self._refresh_rules()
        self._deadline_changed()

    def _build_left_column(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("cardContent")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._picker_card = self._build_picker()
        layout.addWidget(self._picker_card, 1)
        return holder

    def _build_right_column(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("cardContent")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._configurator_card = self._build_editor()
        layout.addWidget(self._configurator_card)
        layout.addWidget(self._build_rules(), 1)
        return holder

    def _build_picker(self) -> QWidget:
        holder = _card()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        kind_row = QHBoxLayout()
        kind_row.addWidget(_eyebrow("Available targets"))
        kind_row.addStretch(1)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Items", "item")
        self.kind_combo.addItem("Stats", "stat")
        self.kind_combo.addItem("Progress", "progress")
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        kind_row.addWidget(self.kind_combo)
        layout.addLayout(kind_row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh_picker)
        layout.addWidget(self.search)
        self.picker = QScrollArea()
        self.picker.setObjectName("buildPicker")
        self.picker.setWidgetResizable(True)
        self.picker.setFrameShape(QFrame.NoFrame)
        self.picker.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._picker_body = QWidget()
        self._picker_body.setObjectName("cardContent")
        self._picker_groups = QVBoxLayout(self._picker_body)
        self._picker_groups.setContentsMargins(0, 0, 0, 0)
        self._picker_groups.setSpacing(5)
        self.picker.setWidget(self._picker_body)
        layout.addWidget(self.picker, 1)
        self._picker_buttons: dict[str, QPushButton] = {}
        self._selected_target_name = ""
        self._picker_empty = QLabel("Nothing matches that search")
        self._picker_empty.setObjectName("tableEmpty")
        self._picker_empty.setVisible(False)
        layout.addWidget(self._picker_empty)
        return holder

    def _build_editor(self) -> QWidget:
        builder = _card()
        builder_layout = QVBoxLayout(builder)
        builder_layout.setContentsMargins(12, 12, 12, 12)
        builder_layout.setSpacing(8)
        editor_head = QHBoxLayout()
        editor_head.setContentsMargins(0, 0, 0, 0)
        editor_head.addWidget(_eyebrow("Configure requirement"))
        editor_head.addStretch(1)
        builder_layout.addLayout(editor_head)
        self.selected_target = QLabel("Choose a target")
        self.selected_target.setObjectName("buildSelectedTarget")
        self.selected_target.setWordWrap(False)
        self.selected_target.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed
        )
        builder_layout.addWidget(self.selected_target, 0, Qt.AlignLeft)

        # --- Required (progress) / Min (stats) ---
        self.required = QDoubleSpinBox()
        self.required.setRange(1, 99999)
        self.required.setDecimals(0)
        self.required.setSingleStep(1)
        self.required.setValue(1)
        self.required.valueChanged.connect(self._refresh_summary)
        self._required_field = self._field("Required", self.required)

        self.ideal_required = QDoubleSpinBox()
        self.ideal_required.setRange(0, 99999)
        self.ideal_required.setDecimals(2)
        self.ideal_required.setSingleStep(0.1)
        self.ideal_required.setValue(0)
        self.ideal_required.setSpecialValueText(" ")
        self.ideal_required.valueChanged.connect(self._refresh_summary)
        self._ideal_field = self._field("Ideal", self.ideal_required)

        # --- Min/Max (items) ---
        self.min_required = QSpinBox()
        self.min_required.setRange(1, 99999)
        self.min_required.setSingleStep(1)
        self.min_required.setValue(1)
        self.min_required.valueChanged.connect(self._refresh_summary)
        self._min_field = self._field("Min", self.min_required)

        self.max_required = QSpinBox()
        self.max_required.setRange(0, 99999)
        self.max_required.setSingleStep(1)
        self.max_required.setValue(0)
        self.max_required.setSpecialValueText(" ")
        self.max_required.valueChanged.connect(self._refresh_summary)
        self._max_field = self._field("Max", self.max_required)

        # --- Cap tracking (supported items only) ---
        self.cap_checkbox = QCheckBox("Track radius cap")
        self.cap_checkbox.setObjectName("capTracking")
        self.cap_checkbox.toggled.connect(self._cap_tracking_toggled)
        self._cap_widget = self.cap_checkbox
        self._cap_widget.hide()

        # Fixed labels for cap mode
        self._cap_first_copy_label = QLabel("First copy: 1")
        self._cap_first_copy_label.setObjectName("dialogHint")
        self._cap_first_copy_label.hide()
        self._cap_auto_label = QLabel("Cap: Auto")
        self._cap_auto_label.setObjectName("dialogHint")
        self._cap_auto_label.hide()

        fields = QHBoxLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(8)
        fields.addWidget(self._required_field, 1)
        fields.addWidget(self._ideal_field, 1)
        fields.addWidget(self._min_field, 1)
        fields.addWidget(self._max_field, 1)
        fields.addWidget(self._cap_first_copy_label)
        fields.addWidget(self._cap_auto_label)
        builder_layout.addLayout(fields)
        builder_layout.addWidget(self._cap_widget)

        grid = QGridLayout()
        self.deadline_group = QButtonGroup(self)
        for index, (value, caption, hint) in enumerate(DEADLINE_OPTIONS):
            button = QRadioButton(f"{caption}\n{hint}")
            button.setObjectName("deadlineTile")
            button.setMinimumHeight(52)
            button.setProperty("deadlineKind", value)
            self.deadline_group.addButton(button)
            grid.addWidget(button, 0, index)
            if value == "none":
                button.setChecked(True)
        self.deadline_group.buttonClicked.connect(self._deadline_changed)
        grid.setSpacing(8)
        builder_layout.addLayout(grid)

        deadline_details = QHBoxLayout()
        deadline_details.setContentsMargins(0, 0, 0, 0)
        deadline_details.setSpacing(8)
        self.stage = QComboBox()
        for number in range(1, 5):
            self.stage.addItem(f"Tier {number}", number)
        self._stage_label = QLabel("Tier")
        self._stage_label.setObjectName("dialogHint")
        deadline_details.addWidget(self._stage_label)
        deadline_details.addWidget(self.stage)
        self.time_entry = QLineEdit("+05:00")
        self.time_entry.setPlaceholderText("+MM:SS")
        self._time_label = QLabel("Time")
        self._time_label.setObjectName("dialogHint")
        deadline_details.addWidget(self._time_label)
        deadline_details.addWidget(self.time_entry)
        deadline_details.addStretch(1)
        builder_layout.addLayout(deadline_details)

        self.summary = QLabel()
        self.summary.setObjectName("dialogHint")
        self.summary.setWordWrap(True)
        builder_layout.addWidget(self.summary)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        self.cancel_edit_button = QPushButton("Cancel edit")
        self.cancel_edit_button.clicked.connect(self._cancel_edit)
        self.cancel_edit_button.hide()
        actions.addWidget(self.cancel_edit_button)
        self.add_button = QPushButton("Add requirement")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self._add_or_update)
        actions.addWidget(self.add_button)
        builder_layout.addLayout(actions)
        self.validation_error = QLabel()
        self.validation_error.setObjectName("addNote")
        self.validation_error.setStyleSheet(
            "QLabel#addNote { color: #FB7185; background: transparent; }"
        )
        self.validation_error.setWordWrap(True)
        self.validation_error.hide()
        builder_layout.addWidget(self.validation_error)
        return builder

    def _build_rules(self) -> QWidget:
        rules_card = _card()
        self._rules_card = rules_card
        rules_layout = QVBoxLayout(rules_card)
        rules_layout.setContentsMargins(12, 12, 12, 12)
        rules_layout.setSpacing(8)
        rules_head = QHBoxLayout()
        rules_head.addWidget(_eyebrow("Build requirements"))
        rules_head.addStretch(1)
        self.rules_count = QLabel()
        self.rules_count.setObjectName("pickerCount")
        rules_head.addWidget(self.rules_count)
        rules_layout.addLayout(rules_head)
        self.rules_scroll = QScrollArea()
        self.rules_scroll.setObjectName("buildRequirementList")
        self.rules_scroll.setWidgetResizable(True)
        self.rules_scroll.setFrameShape(QFrame.NoFrame)
        self.rules_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rules_host = QWidget()
        self._rules_host.setObjectName("cardContent")
        self._rules_layout = QVBoxLayout(self._rules_host)
        self._rules_layout.setContentsMargins(0, 0, 0, 0)
        self._rules_layout.setSpacing(0)
        self._rules_layout.setAlignment(Qt.AlignTop)
        self.rules_scroll.setWidget(self._rules_host)
        rules_layout.addWidget(self.rules_scroll, 1)
        self._rules_empty = QLabel("No requirements configured")
        self._rules_empty.setObjectName("tableEmpty")
        rules_layout.addWidget(self._rules_empty)
        self._rendered_rule_ids: list[str] = []
        self._rule_widgets: dict[str, QWidget] = {}
        return rules_card

    def _cap_tracking_toggled(self, checked: bool) -> None:
        if checked:
            self._min_field.hide()
            self._max_field.hide()
            self._cap_first_copy_label.show()
            self._cap_auto_label.show()
        else:
            self._min_field.show()
            self._max_field.show()
            self._cap_first_copy_label.hide()
            self._cap_auto_label.hide()
        self._refresh_summary()

    @staticmethod
    def _field(caption: str, control: QWidget) -> QWidget:
        field = QWidget()
        field.setObjectName("buildField")
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(caption)
        label.setObjectName("dialogHint")
        layout.addWidget(label)
        layout.addWidget(control)
        return field

    @staticmethod
    def _set_field_caption(field: QWidget, caption: str) -> None:
        label = field.findChild(QLabel)
        if label is not None:
            label.setText(caption)

    def _refresh_picker(self, *_args) -> None:
        _clear_layout(self._picker_groups)
        self._picker_buttons = {}
        kind = self.kind_combo.currentData() or "item"
        query = self.search.text().strip().casefold()
        if kind == "item":
            groups = group_tracked_items_by_rarity(available_tracked_item_names())
        elif kind == "stat":
            groups = (("Player stats", tuple(config.ALL_STAT_LABELS)),)
        else:
            groups = (("Run progress", PROGRESS_TARGETS),)
        visible_total = 0
        for caption, names in groups:
            visible = [
                name
                for name in names
                if not query
                or query in tracked_item_display_name(name).casefold()
                or query in str(name).casefold()
            ]
            if not visible:
                continue
            visible_total += len(visible)
            header = QLabel(f"{caption} · {len(visible)}")
            header.setObjectName("pickerGroup")
            self._picker_groups.addWidget(header)
            row = QWidget()
            row.setObjectName("cardContent")
            flow = FlowLayout(row, margin=0, spacing=5)
            for name in visible:
                button = QPushButton(tracked_item_display_name(name))
                button.setObjectName("pickChip")
                button.setCheckable(True)
                button.setChecked(str(name) == self._selected_target_name)
                button.setCursor(Qt.PointingHandCursor)
                colour = self._target_colour(kind, str(name))
                button.setStyleSheet(_build_pick_stylesheet(colour))
                button.clicked.connect(
                    lambda _checked=False, target=str(name): self._select_target(target)
                )
                self._picker_buttons[str(name)] = button
                flow.addWidget(button)
            self._picker_groups.addWidget(row)
        self._picker_groups.addStretch(1)
        self._picker_empty.setVisible(visible_total == 0)
        self._refresh_summary()

    def _kind_changed(self, *_args) -> None:
        self._clear_validation_error()
        self._selected_target_name = ""
        self.search.clear()
        self._refresh_picker()
        self._select_target("")

    def _select_target(self, target: str) -> None:
        self._clear_validation_error()
        self._selected_target_name = str(target)
        for name, button in self._picker_buttons.items():
            button.setChecked(name == self._selected_target_name)

        kind = self.kind_combo.currentData() or "item"
        is_item = kind == "item"
        is_stat = kind == "stat"
        cap_supported = is_item and target in CAP_SUPPORTED_ITEMS
        if not cap_supported and self.cap_checkbox.isChecked():
            self.cap_checkbox.setChecked(False)

        self._set_field_caption(self._required_field, "Min" if is_stat else "Required")
        self._required_field.setVisible(not is_item)
        self._ideal_field.setVisible(is_stat)
        self._min_field.setVisible(is_item and not self.cap_checkbox.isChecked())
        self._max_field.setVisible(is_item and not self.cap_checkbox.isChecked())
        self._cap_widget.setVisible(cap_supported)
        self._cap_first_copy_label.setVisible(is_item and self.cap_checkbox.isChecked())
        self._cap_auto_label.setVisible(is_item and self.cap_checkbox.isChecked())

        if not is_item:
            self.cap_checkbox.setChecked(False)

        self._target_changed()

    def _deadline_kind(self) -> str:
        checked = self.deadline_group.checkedButton()
        return str(checked.property("deadlineKind") if checked else "none")

    def _deadline_changed(self, *_args) -> None:
        self._clear_validation_error()
        kind = self._deadline_kind()
        previous_stage = self.stage.currentData()
        allowed_stages = (2, 3) if kind == "stage_start" else (1, 2, 3, 4)
        current_stages = tuple(
            self.stage.itemData(index) for index in range(self.stage.count())
        )
        if current_stages != allowed_stages:
            self.stage.blockSignals(True)
            self.stage.clear()
            for number in allowed_stages:
                self.stage.addItem(f"Tier {number}", number)
            selected = self.stage.findData(previous_stage)
            self.stage.setCurrentIndex(selected if selected >= 0 else 0)
            self.stage.blockSignals(False)
        stage_visible = kind in {"stage_start", "stage_overtime"}
        time_visible = kind == "stage_overtime"
        self.stage.setVisible(stage_visible)
        self._stage_label.setVisible(stage_visible)
        self.time_entry.setVisible(time_visible)
        self._time_label.setVisible(time_visible)
        self._refresh_summary()

    def _selected_target(self) -> str:
        return self._selected_target_name

    def _target_changed(self) -> None:
        kind = self.kind_combo.currentData() or "item"
        suffix = ""
        whole_number = kind in {"item", "progress"}
        decimals = 0 if whole_number else 2
        self.required.setMinimum(1 if whole_number else 0.01)
        if kind == "stat":
            spec = PLAYER_STAT_SPEC_BY_LABEL.get(self._selected_target())
            if spec is not None:
                if spec.value_format is PlayerStatFormat.PERCENT:
                    suffix = "%"
                elif spec.value_format is PlayerStatFormat.MULTIPLIER:
                    suffix = "x"
        self.required.setDecimals(decimals)
        self.required.setSingleStep(1.0 if whole_number or suffix == "%" else 0.1)
        self.required.setSuffix(suffix)
        self.ideal_required.setDecimals(decimals)
        self.ideal_required.setSingleStep(
            1.0 if whole_number or suffix == "%" else 0.1
        )
        self.ideal_required.setSuffix(suffix)
        self._refresh_summary()

    @staticmethod
    def _stat_entry_scale(target: str) -> float:
        """Convert between a user-facing stat target and its stored raw value."""
        spec = PLAYER_STAT_SPEC_BY_LABEL.get(str(target))
        if spec is None:
            return 1.0
        scale = float(getattr(spec, "display_scale", 1.0) or 1.0)
        if spec.value_format is PlayerStatFormat.PERCENT:
            scale *= 100.0
        return scale

    def _refresh_summary(self) -> None:
        target = self._selected_target() or "Choose a target"
        kind = self.kind_combo.currentData() or "item"
        colour = self._target_colour(kind, target)
        self.selected_target.setText(target)
        if self._selected_target():
            self.selected_target.setStyleSheet(
                _chip_stylesheet(colour).replace("pickedChip", "buildSelectedTarget")
            )
        else:
            self.selected_target.setStyleSheet("")

        if kind == "item":
            if self.cap_checkbox.isChecked():
                req_text = "first copy 1 · cap auto"
            else:
                req_text = f"min {self.min_required.value()}"
                if self.max_required.value() > 0:
                    req_text += f" max {self.max_required.value()}"
        elif kind == "stat":
            req_text = f"min {self.required.value():g}"
            if self.ideal_required.value() > 0:
                req_text += f" ideal {self.ideal_required.value():g}"
        else:
            req_text = f"required {self.required.value():g}"

        self.summary.setText(
            f"{target} · {req_text} · "
            f"{self._deadline_kind().replace('_', ' ')}"
        )

    @staticmethod
    def _seconds(text: str) -> float:
        value = str(text).strip()
        if value.startswith("+"):
            value = value[1:].strip()
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("Overtime must use +MM:SS")
        minutes, seconds = int(parts[0]), int(parts[1])
        if minutes < 0 or seconds < 0 or seconds > 59:
            raise ValueError("Overtime must use +MM:SS")
        return float(minutes * 60 + seconds)

    def _add_or_update(self) -> None:
        self._clear_validation_error()
        self._sync_draft_order()
        target = self._selected_target()
        if not target:
            self._show_validation_error("Choose a target first.")
            return
        kind = str(self.kind_combo.currentData() or "item")
        if kind == "item":
            if self.cap_checkbox.isChecked():
                required = 1.0
                max_required = None
                cap_tracking = True
            else:
                required = float(self.min_required.value())
                max_val = self.max_required.value()
                max_required = max_val if max_val > 0 else None
                cap_tracking = False
                if max_required is not None and max_required < required:
                    self._show_validation_error("Max must be ≥ Min")
                    return
        elif kind == "stat":
            required = float(self.required.value())
            ideal_val = float(self.ideal_required.value())
            max_required = ideal_val if ideal_val > 0 else None
            cap_tracking = False
            if max_required is not None and max_required < required:
                self._show_validation_error("Ideal must be ≥ Min")
                return
        else:
            required = float(self.required.value())
            max_required = None
            cap_tracking = False

        if kind in {"item", "progress"} and not required.is_integer():
            self._show_validation_error("This target requires a whole number.")
            return
        duplicate = next((r for r in self._draft.get("requirements", []) if r.get("kind") == kind and r.get("target") == target and r.get("id") != self._editing_id), None)
        if duplicate:
            self._show_validation_error("That requirement is already configured.")
            return
        deadline_kind = self._deadline_kind()
        try:
            seconds = self._seconds(self.time_entry.text()) if deadline_kind == "stage_overtime" else None
        except ValueError as exc:
            self._show_validation_error(str(exc))
            return
        entry_scale = self._stat_entry_scale(target) if kind == "stat" else 1.0
        stored_required = required / entry_scale
        stored_max_required = (
            max_required / entry_scale
            if kind == "stat" and max_required is not None
            else max_required
        )
        payload = {
            "id": self._editing_id or uuid4().hex,
            "kind": kind,
            "target": target,
            "required": int(required) if kind in {"item", "progress"} else stored_required,
            "deadline": {
                "kind": deadline_kind,
                "stage": self.stage.currentData() if deadline_kind in {"stage_start", "stage_overtime"} else None,
                "seconds": seconds,
            },
        }
        if stored_max_required is not None:
            payload["max_required"] = (
                int(stored_max_required)
                if kind == "item"
                else stored_max_required
            )
        if cap_tracking:
            payload["cap_tracking"] = True

        rules = self._draft.setdefault("requirements", [])
        if self._editing_id:
            index = next(i for i, row in enumerate(rules) if row.get("id") == self._editing_id)
            rules[index] = payload
        else:
            rules.append(payload)
        self._reset_editing_state()
        self._clear_editor_form()
        self._refresh_rules()

    def _refresh_rules(self) -> None:
        _clear_layout(self._rules_layout)
        self._rule_widgets = {}
        requirements = sorted(
            self._draft.get("requirements") or (),
            key=self._requirement_display_sort_key,
        )
        self.rules_count.setText(
            f"{len(requirements)} configured" if requirements else "Empty"
        )
        self._rules_empty.setVisible(not requirements)
        self._rendered_rule_ids = [str(row.get("id") or "") for row in requirements]
        for index, row in enumerate(requirements):
            label = self._deadline_label(row.get("deadline") or {})
            row_widget = self._build_requirement_row(
                row,
                label,
                last=index == len(requirements) - 1,
            )
            rule_id = str(row.get("id") or "")
            self._rule_widgets[rule_id] = row_widget
            self._rules_layout.addWidget(row_widget)
        self._refresh_rule_actions()

    @staticmethod
    def _deadline_label(deadline: dict) -> str:
        kind = str(deadline.get("kind") or "none")
        if kind == "stage_start":
            return f"BEFORE T{deadline.get('stage') or 1}"
        if kind == "stage_overtime":
            return f"T{deadline.get('stage') or 1} +{BuildProgressionDialog._clock(deadline.get('seconds'))}"
        return ""

    @staticmethod
    def _requirement_display_sort_key(row: dict):
        kind = str(row.get("kind") or "item")
        deadline = row.get("deadline") or {}
        deadline_kind = str(deadline.get("kind") or "none")
        deadline_rank = {
            "stage_start": (0, int(deadline.get("stage") or 1), 0),
            "stage_overtime": (
                0,
                int(deadline.get("stage") or 1),
                int(deadline.get("seconds") or 0),
            ),
            "none": (1, 99, 0),
        }.get(deadline_kind, (1, 99, 0))
        kind_rank = {"item": 0, "stat": 1, "progress": 2}.get(kind, 3)
        untimed_rank = 0 if deadline_kind == "none" else 1
        rarity_rank = (
            -tracked_item_rarity_rank(str(row.get("target") or ""))
            if kind == "item"
            else 0
        )
        return (
            kind_rank,
            untimed_rank,
            rarity_rank,
            deadline_rank,
            int(row.get("order") or 0),
        )

    def _build_requirement_row(
        self,
        row: dict,
        deadline: str,
        *,
        last: bool,
    ) -> QWidget:
        widget = QWidget()
        widget.setObjectName("trackedRowLast" if last else "trackedRow")
        widget.setMinimumHeight(42)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(8)

        target = str(row.get("target") or "Requirement")
        target_colour = self._target_colour(
            str(row.get("kind") or "item"), target
        )
        target_label = QLabel(target)
        target_label.setObjectName("pickedChip")
        target_label.setStyleSheet(_chip_stylesheet(target_colour))
        target_label.setToolTip(target)
        target_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        target_label.setWordWrap(False)
        target_label.setMinimumWidth(max(64, target_label.fontMetrics().horizontalAdvance(target) + 20))
        layout.addWidget(target_label)

        kind = str(row.get("kind") or "item")
        if kind == "item":
            required_val = int(row.get("required", 1))
            max_val = row.get("max_required")
            cap = bool(row.get("cap_tracking", False))
            if cap:
                badge_text = "Cap Auto"
            elif max_val is not None:
                badge_text = f"Min {required_val} \u00b7 Max {int(max_val)}"
            else:
                badge_text = f"Required {required_val}"
        elif kind == "stat":
            required_text = self._required_display(row)
            ideal_value = row.get("max_required")
            if ideal_value is not None:
                ideal_text = self._required_display(row, value=ideal_value)
                badge_text = f"Min {required_text} \u00b7 Ideal {ideal_text}"
            else:
                badge_text = f"Required {required_text}"
        else:
            badge_text = f"Required {self._required_display(row)}"

        goal = QLabel(badge_text)
        goal.setObjectName("condBadgeMuted")
        goal.setToolTip(badge_text)
        goal.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        goal.setWordWrap(False)
        goal.setMinimumWidth(goal.fontMetrics().horizontalAdvance(badge_text) + 20)
        layout.addWidget(goal)
        layout.addStretch(1)

        deadline_label = QLabel(deadline)
        deadline_label.setObjectName("condBadge")
        layout.addWidget(deadline_label)
        deadline_label.setVisible(bool(deadline))

        rule_id = str(row.get("id") or "")
        edit = QPushButton("Edit")
        edit.setObjectName("buildRuleEdit")
        edit.setCursor(Qt.PointingHandCursor)
        edit.setToolTip("Edit this requirement")
        edit.setStyleSheet(
            "QPushButton#buildRuleEdit { background: transparent; color: #93C5FD;"
            " border: 1px solid #2A3542; border-radius: 6px; padding: 2px 7px; }"
            "QPushButton#buildRuleEdit:hover { border-color: #3E82C6; color: #B9DFFF; }"
        )
        edit.clicked.connect(
            lambda _checked=False, selected_id=rule_id: self._edit_rule(selected_id)
        )
        layout.addWidget(edit)

        remove = QPushButton("✕")
        remove.setObjectName("chipRemove")
        remove.setFixedSize(20, 20)
        remove.setCursor(Qt.PointingHandCursor)
        remove.setToolTip("Remove this requirement")
        remove.clicked.connect(
            lambda _checked=False, selected_id=rule_id: self._remove_rule(selected_id)
        )
        layout.addWidget(remove)
        return widget

    @staticmethod
    def _clock(seconds) -> str:
        total = max(0, int(seconds or 0))
        return f"{total // 60:02d}:{total % 60:02d}"

    @staticmethod
    def _target_colour(kind: str, target: str) -> str:
        if kind == "item":
            return tracked_item_color(target)
        return KIND_COLORS.get(kind, "#C7D0DC")

    @staticmethod
    def _required_display(row: dict, *, value=None) -> str:
        kind = str(row.get("kind") or "item")
        try:
            value = float(row.get("required") if value is None else value)
        except (TypeError, ValueError):
            return "--"
        if kind in {"item", "progress"}:
            return str(int(value))
        target = str(row.get("target") or "")
        spec = PLAYER_STAT_SPEC_BY_LABEL.get(target)
        value *= BuildProgressionDialog._stat_entry_scale(target)
        suffix = ""
        if spec is not None:
            if spec.value_format is PlayerStatFormat.PERCENT:
                suffix = "%"
            elif spec.value_format is PlayerStatFormat.MULTIPLIER:
                suffix = "x"
        return f"{value:g}{suffix}"

    def _reset_editing_state(self) -> None:
        self._editing_id = None
        self._editing_form_snapshot = None
        self.add_button.setText("Add requirement")
        self.cancel_edit_button.hide()

    def _show_validation_error(self, message: str) -> None:
        self.validation_error.setText(str(message))
        self.validation_error.show()

    def _clear_validation_error(self) -> None:
        error = getattr(self, "validation_error", None)
        if error is not None:
            error.clear()
            error.hide()

    def _clear_editor_form(self) -> None:
        self._selected_target_name = ""
        self.search.clear()
        for button in self._picker_buttons.values():
            button.setChecked(False)
        self.required.setValue(1)
        self.ideal_required.setValue(0)
        self.min_required.setValue(1)
        self.max_required.setValue(0)
        self.cap_checkbox.setChecked(False)
        for button in self.deadline_group.buttons():
            if button.property("deadlineKind") == "none":
                button.setChecked(True)
                break
        self._deadline_changed()
        self.time_entry.setText("+05:00")
        self._target_changed()

    def _cancel_edit(self) -> None:
        """Leave edit mode without mutating the draft requirement."""
        self._reset_editing_state()
        self._clear_editor_form()
        self._clear_validation_error()

    def _refresh_rule_actions(self, *_args) -> None:
        self.clear_button.setEnabled(bool(self._draft.get("requirements")))

    def _clear_name_error(self, *_args) -> None:
        self.name_error.clear()
        self.name_error.hide()

    def _ordered_ids(self) -> list[str]:
        return list(self._rendered_rule_ids)

    def _sync_draft_order(self) -> None:
        ids = self._ordered_ids()
        if not ids:
            return
        by_id = {str(row.get("id")): row for row in self._draft.get("requirements", [])}
        self._draft["requirements"] = [by_id[rule_id] for rule_id in ids if rule_id in by_id]

    def _edit_rule(self, rule_id: str) -> None:
        row = next((r for r in self._draft.get("requirements", []) if str(r.get("id")) == rule_id), None)
        if row is None:
            return
        self._editing_id = rule_id
        kind = str(row.get("kind") or "item")
        kind_index = self.kind_combo.findData(kind)
        self.kind_combo.setCurrentIndex(max(0, kind_index))
        self.search.setText(str(row.get("target") or ""))
        self._refresh_picker()
        self._select_target(str(row.get("target") or ""))
        entry_scale = self._stat_entry_scale(str(row.get("target") or "")) if kind == "stat" else 1.0
        if kind == "item":
            self.min_required.setValue(int(row.get("required") or 1))
            self.max_required.setValue(int(row.get("max_required") or 0))
            self.cap_checkbox.setChecked(bool(row.get("cap_tracking", False)))
        elif kind == "stat":
            self.required.setValue(float(row.get("required") or 1) * entry_scale)
            self.ideal_required.setValue(
                float(row.get("max_required") or 0) * entry_scale
            )
        else:
            self.required.setValue(float(row.get("required") or 1))
        deadline = row.get("deadline") or {}
        for button in self.deadline_group.buttons():
            if button.property("deadlineKind") == deadline.get("kind", "none"):
                button.setChecked(True)
        self._deadline_changed()
        self.stage.setCurrentIndex(max(0, self.stage.findData(deadline.get("stage"))))
        self.time_entry.setText(f"+{self._clock(deadline.get('seconds'))}")
        self.add_button.setText("Update requirement")
        self.cancel_edit_button.show()
        self._refresh_summary()
        self._editing_form_snapshot = self._form_signature()

    def _remove_rule(self, rule_id: str) -> None:
        self._sync_draft_order()
        self._draft["requirements"] = [r for r in self._draft.get("requirements", []) if str(r.get("id")) != rule_id]
        if self._editing_id == rule_id:
            self._reset_editing_state()
        self._refresh_rules()

    def _remove_all(self) -> None:
        if _ask_confirmation(
            self,
            "Remove All Requirements?",
            "Remove every requirement from this build?",
            confirm_text="Remove All",
            destructive=True,
        ):
            self._draft["requirements"] = []
            self._reset_editing_state()
            self._refresh_rules()

    def _current_payload(self) -> dict:
        self._sync_draft_order()
        payload = deepcopy(self._draft)
        payload["name"] = self.name_entry.text().strip()
        payload["deadlines_enabled"] = self.deadlines_enabled.isChecked()
        return payload

    def _form_signature(self) -> tuple:
        kind = str(self.kind_combo.currentData() or "item")
        return (
            kind,
            self._selected_target(),
            float(self.min_required.value()) if kind == "item" else float(self.required.value()),
            (
                int(self.max_required.value())
                if kind == "item"
                else float(self.ideal_required.value()) if kind == "stat" else None
            ),
            bool(self.cap_checkbox.isChecked()) if kind == "item" else False,
            self._deadline_kind(),
            self.stage.currentData(),
            self.time_entry.text().strip(),
        )

    def _is_dirty(self) -> bool:
        pending_edit_changed = (
            self._editing_id is not None
            and self._editing_form_snapshot is not None
            and self._form_signature() != self._editing_form_snapshot
        )
        return self._current_payload() != self._original_draft or pending_edit_changed

    def _confirm_discard(self) -> bool:
        if not self._is_dirty():
            return True
        return _ask_confirmation(
            self,
            "Discard Changes?",
            "Discard the unsaved changes to this build?",
            confirm_text="Discard",
            destructive=True,
        )

    def reject(self) -> None:
        if self._confirm_discard():
            super().reject()

    def closeEvent(self, event) -> None:
        if self.result() == QDialog.Accepted or self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    def _save(self) -> None:
        if self._editing_id is not None:
            self._show_validation_error(
                "Update or cancel the requirement edit before saving the build."
            )
            self.add_button.setFocus()
            return
        payload = self._current_payload()
        name = str(payload.get("name") or "").strip()
        if not name:
            self.name_error.setText("Enter a build name.")
            self.name_error.show()
            self.name_entry.setFocus()
            return
        if name.casefold() in self._existing_names:
            self.name_error.setText("A build with this name already exists.")
            self.name_error.show()
            self.name_entry.setFocus()
            return
        payload["name"] = name
        normalized = config.normalize_build_definition_config(payload)
        self.result_payload = normalized
        self._original_draft = deepcopy(normalized)
        self.accept()
