"""The one shared editor for the Build Progression definition."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.build_progression import definition_from_config
from app import config
from core.stats.formats import PlayerStatFormat
from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL
from projections.tracked_items import (
    available_tracked_item_names,
    group_tracked_items_by_rarity,
)
from ui.dialogs.shell import DIALOG_REGULAR, DIALOG_TALL, DIALOG_WIDE, dialog_body


DEADLINE_OPTIONS = (
    ("none", "No deadline", "Track progress only"),
    ("run_clock", "Run clock", "From the start of the run"),
    ("stage_start", "Stage start", "Before a stage begins"),
    ("stage_overtime", "Stage overtime", "Before an OT minute"),
)


class BuildProgressionHelpDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How Build Progression Works")
        layout = dialog_body(
            self,
            title="How Build Progression Works",
            subtitle="One live checklist shared by Live Stats, overlays, and Twitch.",
            width=DIALOG_REGULAR,
            height=520,
        )
        text = QLabel(
            "<b>Required and Ideal</b><br>Required controls completion. Ideal is an optional "
            "stretch target and never blocks BUILD COMPLETE.<br><br>"
            "<b>Deadlines</b><br>Use no deadline, a run-clock time, the start of a stage, "
            "or an overtime minute inside a stage. Yellow means two minutes remain; red "
            "means the requirement is late.<br><br>"
            "<b>Every run starts clean</b><br>The build definition is saved, but completed, "
            "late, and completion-time state resets when a new run begins.<br><br>"
            "<b>One build, separate presentation</b><br>OBS and the in-game overlay use the same "
            "requirements while keeping their own size and row-limit settings."
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        text.setAlignment(Qt.AlignTop)
        layout.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BuildProgressionDialog(QDialog):
    def __init__(self, settings, service, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build Progression")
        self._settings = settings
        self._service = service
        self._draft = deepcopy(settings.read())
        self._editing_id: str | None = None

        layout = dialog_body(
            self,
            title="Build Progression",
            subtitle="Define what the build needs and when each requirement should be ready.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )
        general = QHBoxLayout()
        self.name_entry = QLineEdit(str(self._draft.get("name") or "Build Progression"))
        self.name_entry.setPlaceholderText("Build name")
        self.name_entry.textChanged.connect(self._refresh_preview)
        general.addWidget(QLabel("Build name"))
        general.addWidget(self.name_entry, 1)
        self.deadlines_enabled = QCheckBox("Use deadlines")
        self.deadlines_enabled.setChecked(bool(self._draft.get("deadlines_enabled", True)))
        general.addWidget(self.deadlines_enabled)
        help_btn = QPushButton("How it works")
        help_btn.clicked.connect(lambda: BuildProgressionHelpDialog(self).exec())
        general.addWidget(help_btn)
        layout.addLayout(general)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_picker())
        split.addWidget(self._build_editor())
        split.setSizes([430, 560])
        layout.addWidget(split, 1)

        preview = QLabel()
        preview.setObjectName("chatPreview")
        preview.setWordWrap(True)
        self.preview = preview
        layout.addWidget(preview)

        footer = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        clear = footer.addButton("Remove all", QDialogButtonBox.DestructiveRole)
        clear.clicked.connect(self._remove_all)
        footer.accepted.connect(self._save)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)

        self._refresh_picker()
        self._refresh_rules()
        # Apply the default/loaded radio immediately.  Without this first
        # synchronization a freshly opened editor selected ``No deadline``
        # while still showing both Stage and Time, until the user clicked a
        # different deadline and came back.
        self._deadline_changed()

    def _build_picker(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 8, 0)
        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Choose requirement"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Items", "item")
        self.kind_combo.addItem("Stats", "stat")
        self.kind_combo.currentIndexChanged.connect(self._refresh_picker)
        kind_row.addWidget(self.kind_combo)
        layout.addLayout(kind_row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh_picker)
        layout.addWidget(self.search)
        self.picker = QTreeWidget()
        self.picker.setHeaderHidden(True)
        self.picker.itemSelectionChanged.connect(self._target_changed)
        layout.addWidget(self.picker, 1)
        return holder

    def _build_editor(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(QLabel("Configure requirement"))
        form = QFormLayout()
        self.required = QDoubleSpinBox()
        self.required.setRange(0.01, 99999)
        self.required.setDecimals(2)
        self.required.setValue(1)
        form.addRow("Required", self.required)
        self.ideal = QDoubleSpinBox()
        self.ideal.setRange(0, 99999)
        self.ideal.setDecimals(2)
        self.ideal.setSpecialValueText("Not set")
        form.addRow("Ideal (optional)", self.ideal)
        self.priority = QComboBox()
        for label, value in (("Normal", "normal"), ("Early", "early"), ("ASAP", "asap")):
            self.priority.addItem(label, value)
        form.addRow("Priority", self.priority)
        layout.addLayout(form)

        grid = QGridLayout()
        self.deadline_group = QButtonGroup(self)
        for index, (value, caption, hint) in enumerate(DEADLINE_OPTIONS):
            button = QRadioButton(f"{caption}\n{hint}")
            button.setProperty("deadlineKind", value)
            self.deadline_group.addButton(button)
            grid.addWidget(button, index // 2, index % 2)
            if value == "none":
                button.setChecked(True)
        self.deadline_group.buttonClicked.connect(self._deadline_changed)
        layout.addLayout(grid)

        deadline_form = QFormLayout()
        self.stage = QComboBox()
        for number in range(1, 5):
            self.stage.addItem(f"Stage {number}", number)
        deadline_form.addRow("Stage", self.stage)
        self.time_entry = QLineEdit("05:00")
        self.time_entry.setPlaceholderText("MM:SS")
        deadline_form.addRow("Time", self.time_entry)
        layout.addLayout(deadline_form)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        self.add_button = QPushButton("Add requirement")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self._add_or_update)
        actions.addWidget(self.add_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.rules = QListWidget()
        self.rules.setDragDropMode(QListWidget.InternalMove)
        self.rules.itemDoubleClicked.connect(lambda _item: self._edit_selected())
        layout.addWidget(self.rules, 1)
        rule_actions = QHBoxLayout()
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit_selected)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_selected)
        rule_actions.addWidget(edit)
        rule_actions.addWidget(remove)
        rule_actions.addStretch(1)
        layout.addLayout(rule_actions)
        return holder

    def _refresh_picker(self, *_args) -> None:
        self.picker.clear()
        kind = self.kind_combo.currentData() or "item"
        query = self.search.text().strip().casefold()
        if kind == "item":
            groups = group_tracked_items_by_rarity(available_tracked_item_names())
        else:
            groups = (("Player stats", tuple(config.ALL_STAT_LABELS)),)
        for caption, names in groups:
            visible = [name for name in names if not query or query in str(name).casefold()]
            if not visible:
                continue
            group = QTreeWidgetItem([f"{caption} · {len(visible)}"])
            group.setFlags(group.flags() & ~Qt.ItemIsSelectable)
            self.picker.addTopLevelItem(group)
            for name in visible:
                child = QTreeWidgetItem([str(name)])
                child.setData(0, Qt.UserRole, str(name))
                group.addChild(child)
            group.setExpanded(True)
        self._refresh_summary()

    def _deadline_kind(self) -> str:
        checked = self.deadline_group.checkedButton()
        return str(checked.property("deadlineKind") if checked else "none")

    def _deadline_changed(self, *_args) -> None:
        kind = self._deadline_kind()
        self.stage.setVisible(kind in {"stage_start", "stage_overtime"})
        self.time_entry.setVisible(kind in {"run_clock", "stage_overtime"})
        self._refresh_summary()

    def _selected_target(self) -> str:
        selected = self.picker.selectedItems()
        return str(selected[0].data(0, Qt.UserRole) or "") if selected else ""

    def _target_changed(self) -> None:
        kind = self.kind_combo.currentData() or "item"
        suffix = ""
        decimals = 0 if kind == "item" else 2
        if kind == "stat":
            spec = PLAYER_STAT_SPEC_BY_LABEL.get(self._selected_target())
            if spec is not None:
                if spec.value_format is PlayerStatFormat.PERCENT:
                    suffix = "%"
                elif spec.value_format is PlayerStatFormat.MULTIPLIER:
                    suffix = "x"
        for spin in (self.required, self.ideal):
            spin.setDecimals(decimals)
            spin.setSingleStep(1.0 if kind == "item" or suffix == "%" else 0.1)
            spin.setSuffix(suffix)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        target = self._selected_target() or "Choose an item or stat"
        self.summary.setText(f"{target} · required {self.required.value():g} · {self._deadline_kind().replace('_', ' ')}")

    @staticmethod
    def _seconds(text: str) -> float:
        parts = str(text).strip().split(":")
        if len(parts) != 2:
            raise ValueError("Time must use MM:SS")
        minutes, seconds = int(parts[0]), int(parts[1])
        if minutes < 0 or seconds < 0 or seconds > 59:
            raise ValueError("Time must use MM:SS")
        return float(minutes * 60 + seconds)

    def _add_or_update(self) -> None:
        self._sync_draft_order()
        target = self._selected_target()
        if not target:
            QMessageBox.warning(self, "Build Progression", "Choose an item or stat first.")
            return
        kind = str(self.kind_combo.currentData())
        required = float(self.required.value())
        ideal = float(self.ideal.value()) or None
        if kind == "item" and (not required.is_integer() or (ideal is not None and not ideal.is_integer())):
            QMessageBox.warning(self, "Build Progression", "Item counts must be whole numbers.")
            return
        if ideal is not None and ideal < required:
            QMessageBox.warning(self, "Build Progression", "Ideal must be at least Required.")
            return
        duplicate = next((r for r in self._draft.get("requirements", []) if r.get("kind") == kind and r.get("target") == target and r.get("id") != self._editing_id), None)
        if duplicate:
            QMessageBox.warning(self, "Build Progression", "That requirement is already configured.")
            return
        deadline_kind = self._deadline_kind()
        try:
            seconds = self._seconds(self.time_entry.text()) if deadline_kind in {"run_clock", "stage_overtime"} else None
        except ValueError as exc:
            QMessageBox.warning(self, "Build Progression", str(exc))
            return
        display_scale = 1.0
        if kind == "stat":
            spec = PLAYER_STAT_SPEC_BY_LABEL.get(target)
            display_scale = float(getattr(spec, "display_scale", 1.0) or 1.0)
        stored_required = required / display_scale
        stored_ideal = ideal / display_scale if ideal is not None else None
        payload = {
            "id": self._editing_id or uuid4().hex,
            "kind": kind,
            "target": target,
            "required": int(required) if kind == "item" else stored_required,
            "ideal": int(ideal) if kind == "item" and ideal is not None else stored_ideal,
            "priority": str(self.priority.currentData()),
            "deadline": {
                "kind": deadline_kind,
                "stage": self.stage.currentData() if deadline_kind in {"stage_start", "stage_overtime"} else None,
                "seconds": seconds,
            },
        }
        rules = self._draft.setdefault("requirements", [])
        if self._editing_id:
            index = next(i for i, row in enumerate(rules) if row.get("id") == self._editing_id)
            rules[index] = payload
        else:
            rules.append(payload)
        self._editing_id = None
        self.add_button.setText("Add requirement")
        self._refresh_rules()

    def _refresh_rules(self) -> None:
        self.rules.clear()
        for row in self._draft.get("requirements") or ():
            deadline = row.get("deadline") or {}
            kind = deadline.get("kind", "none")
            if kind == "run_clock":
                label = f"RUN · {self._clock(deadline.get('seconds'))}"
            elif kind == "stage_start":
                label = f"Before S{deadline.get('stage')}"
            elif kind == "stage_overtime":
                label = f"S{deadline.get('stage')} OT · {self._clock(deadline.get('seconds'))}"
            else:
                label = "No deadline"
            ideal = f" · ideal {row.get('ideal')}" if row.get("ideal") is not None else ""
            item = QListWidgetItem(f"{row.get('target')} · {row.get('required')}{ideal} · {str(row.get('priority', 'normal')).upper()} · {label}")
            item.setData(Qt.UserRole, str(row.get("id")))
            self.rules.addItem(item)
        self._refresh_preview()

    def _refresh_preview(self, *_args) -> None:
        if not hasattr(self, "preview"):
            return
        remaining = len(self._draft.get("requirements") or ())
        self.preview.setText(f"TWITCH · !BUILD  {self.name_entry.text() or 'Build Progression'} · 0/{remaining} | +{remaining} remaining")

    @staticmethod
    def _clock(seconds) -> str:
        total = max(0, int(seconds or 0))
        return f"{total // 60:02d}:{total % 60:02d}"

    def _ordered_ids(self) -> list[str]:
        return [str(self.rules.item(i).data(Qt.UserRole)) for i in range(self.rules.count())]

    def _sync_draft_order(self) -> None:
        ids = self._ordered_ids()
        if not ids:
            return
        by_id = {str(row.get("id")): row for row in self._draft.get("requirements", [])}
        self._draft["requirements"] = [by_id[rule_id] for rule_id in ids if rule_id in by_id]

    def _edit_selected(self) -> None:
        item = self.rules.currentItem()
        if item is None:
            return
        rule_id = str(item.data(Qt.UserRole))
        row = next((r for r in self._draft.get("requirements", []) if str(r.get("id")) == rule_id), None)
        if row is None:
            return
        self._editing_id = rule_id
        self.kind_combo.setCurrentIndex(0 if row.get("kind") == "item" else 1)
        self.search.setText(str(row.get("target") or ""))
        self._refresh_picker()
        matches = self.picker.findItems(str(row.get("target")), Qt.MatchExactly | Qt.MatchRecursive)
        if matches:
            self.picker.setCurrentItem(matches[0])
        display_scale = 1.0
        if row.get("kind") == "stat":
            spec = PLAYER_STAT_SPEC_BY_LABEL.get(str(row.get("target") or ""))
            display_scale = float(getattr(spec, "display_scale", 1.0) or 1.0)
        self.required.setValue(float(row.get("required") or 1) * display_scale)
        self.ideal.setValue(float(row.get("ideal") or 0) * display_scale)
        self.priority.setCurrentIndex(max(0, self.priority.findData(row.get("priority", "normal"))))
        deadline = row.get("deadline") or {}
        for button in self.deadline_group.buttons():
            if button.property("deadlineKind") == deadline.get("kind", "none"):
                button.setChecked(True)
        self.stage.setCurrentIndex(max(0, self.stage.findData(deadline.get("stage"))))
        self.time_entry.setText(self._clock(deadline.get("seconds")))
        self.add_button.setText("Update requirement")
        self._deadline_changed()

    def _remove_selected(self) -> None:
        self._sync_draft_order()
        item = self.rules.currentItem()
        if item is None:
            return
        rule_id = str(item.data(Qt.UserRole))
        self._draft["requirements"] = [r for r in self._draft.get("requirements", []) if str(r.get("id")) != rule_id]
        self._refresh_rules()

    def _remove_all(self) -> None:
        if QMessageBox.question(self, "Build Progression", "Remove every requirement?") == QMessageBox.Yes:
            self._draft["requirements"] = []
            self._refresh_rules()

    def _save(self) -> None:
        by_id = {str(row.get("id")): row for row in self._draft.get("requirements", [])}
        self._draft["requirements"] = [by_id[rule_id] for rule_id in self._ordered_ids() if rule_id in by_id]
        self._draft["name"] = self.name_entry.text().strip() or "Build Progression"
        self._draft["deadlines_enabled"] = self.deadlines_enabled.isChecked()
        normalized = self._settings.write(self._draft)
        self._service.replace_definition(definition_from_config(normalized))
        self.accept()
