"""The one shared editor for the Build Progression definition."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from app.build_progression import definition_from_config
from app import config
from core.build_progression import format_priority
from core.stats.formats import PlayerStatFormat
from core.stats.types import PLAYER_STAT_SPEC_BY_LABEL
from projections.tracked_items import (
    available_tracked_item_names,
    group_tracked_items_by_rarity,
    tracked_item_color,
    tracked_item_display_name,
)
from ui.dialogs.tracked_items import _chip_stylesheet, _pick_stylesheet
from ui.dialogs.shell import (
    DIALOG_REGULAR,
    DIALOG_TALL,
    DIALOG_WIDE,
    dialog_body,
    dialog_footer,
)
from ui.shared import FlowLayout, _clear_layout


DEADLINE_OPTIONS = (
    ("none", "No deadline", "Track progress only"),
    ("run_clock", "Run clock", "From the start of the run"),
    ("stage_start", "Tier start", "Before a tier begins"),
    ("stage_overtime", "Tier overtime", "Before an OT minute"),
)


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _eyebrow(text: str) -> QLabel:
    label = QLabel(str(text).upper())
    label.setObjectName("kpiLabel")
    return label


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
            "<b>Deadlines</b><br>Use no deadline, a run-clock time, the start of a tier, "
            "or an overtime minute inside a tier. Yellow means two minutes remain; red "
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
        general_card = _card()
        general = QHBoxLayout(general_card)
        general.setContentsMargins(12, 12, 12, 12)
        general.setSpacing(10)
        general.addWidget(_eyebrow("Build definition"))
        self.name_entry = QLineEdit(str(self._draft.get("name") or "Build Progression"))
        self.name_entry.setPlaceholderText("Build name")
        self.name_entry.textChanged.connect(self._refresh_preview)
        general.addWidget(self.name_entry, 1)
        self.deadlines_enabled = QCheckBox("Use deadlines")
        self.deadlines_enabled.setChecked(bool(self._draft.get("deadlines_enabled", True)))
        general.addWidget(self.deadlines_enabled)
        help_btn = QPushButton("How it works")
        help_btn.clicked.connect(lambda: BuildProgressionHelpDialog(self).exec())
        general.addWidget(help_btn)
        layout.addWidget(general_card)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_left_column())
        split.addWidget(self._build_rules())
        split.setStretchFactor(0, 11)
        split.setStretchFactor(1, 9)
        split.setSizes([500, 400])
        layout.addWidget(split, 1)

        preview = QLabel()
        preview.setObjectName("chatPreview")
        preview.setWordWrap(True)
        self.preview = preview
        layout.addWidget(preview)

        save = QPushButton("Save")
        cancel = QPushButton("Cancel")
        clear = QPushButton("Remove all")
        clear.clicked.connect(self._remove_all)
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        dialog_footer(
            self,
            primary=save,
            secondary=cancel,
            destructive=clear,
        )

        self._refresh_picker()
        self._refresh_rules()
        # Apply the default/loaded radio immediately.  Without this first
        # synchronization a freshly opened editor selected ``No deadline``
        # while still showing both Tier and Time, until the user clicked a
        # different deadline and came back.
        self._deadline_changed()

    def _build_left_column(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("cardContent")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._picker_card = self._build_picker()
        self._configurator_card = self._build_editor()
        layout.addWidget(self._picker_card, 1)
        layout.addWidget(self._configurator_card)
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
        self.selected_target = QLabel("Choose a target")
        self.selected_target.setObjectName("buildSelectedTarget")
        editor_head.addWidget(self.selected_target)
        builder_layout.addLayout(editor_head)

        self.required = QDoubleSpinBox()
        self.required.setRange(1, 99999)
        self.required.setDecimals(0)
        self.required.setSingleStep(1)
        self.required.setValue(1)
        self.ideal = QDoubleSpinBox()
        self.ideal.setRange(0, 99999)
        self.ideal.setDecimals(0)
        self.ideal.setSingleStep(1)
        self.ideal.setSpecialValueText("Not set")
        self.priority = QComboBox()
        for label, value in (("High", "asap"), ("Medium", "early"), ("Low", "normal")):
            self.priority.addItem(label, value)
        self.priority.setCurrentIndex(self.priority.findData("normal"))
        fields = QHBoxLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(8)
        fields.addWidget(self._field("Required", self.required), 1)
        fields.addWidget(self._field("Ideal (optional)", self.ideal), 1)
        fields.addWidget(self._field("Priority", self.priority), 1)
        builder_layout.addLayout(fields)

        grid = QGridLayout()
        self.deadline_group = QButtonGroup(self)
        for index, (value, caption, hint) in enumerate(DEADLINE_OPTIONS):
            button = QRadioButton(f"{caption}\n{hint}")
            button.setObjectName("deadlineTile")
            button.setMinimumHeight(52)
            button.setProperty("deadlineKind", value)
            self.deadline_group.addButton(button)
            grid.addWidget(button, index // 2, index % 2)
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
        self.time_entry = QLineEdit("05:00")
        self.time_entry.setPlaceholderText("MM:SS")
        self._time_label = QLabel("Time")
        self._time_label.setObjectName("dialogHint")
        deadline_details.addWidget(self._time_label)
        deadline_details.addWidget(self.time_entry)
        deadline_details.addStretch(1)
        builder_layout.addLayout(deadline_details)

        self.summary = QLabel()
        self.summary.setObjectName("dialogHint")
        self.summary.setWordWrap(False)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.summary, 1)
        self.add_button = QPushButton("Add requirement")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self._add_or_update)
        actions.addWidget(self.add_button)
        builder_layout.addLayout(actions)
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
        self.rules = QListWidget()
        self.rules.setObjectName("buildRequirementList")
        self.rules.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rules.setDragDropMode(QListWidget.InternalMove)
        self.rules.itemDoubleClicked.connect(lambda _item: self._edit_selected())
        rules_layout.addWidget(self.rules, 1)
        rule_actions = QHBoxLayout()
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit_selected)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_selected)
        rule_actions.addWidget(edit)
        rule_actions.addWidget(remove)
        rule_actions.addStretch(1)
        rules_layout.addLayout(rule_actions)
        return rules_card

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

    def _refresh_picker(self, *_args) -> None:
        _clear_layout(self._picker_groups)
        self._picker_buttons = {}
        kind = self.kind_combo.currentData() or "item"
        query = self.search.text().strip().casefold()
        if kind == "item":
            groups = group_tracked_items_by_rarity(available_tracked_item_names())
        else:
            groups = (("Player stats", tuple(config.ALL_STAT_LABELS)),)
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
                colour = tracked_item_color(name) if kind == "item" else "#93C5FD"
                button.setStyleSheet(_pick_stylesheet(colour))
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
        self._selected_target_name = ""
        self.search.clear()
        self._refresh_picker()
        self._target_changed()

    def _select_target(self, target: str) -> None:
        self._selected_target_name = str(target)
        for name, button in self._picker_buttons.items():
            button.setChecked(name == self._selected_target_name)
        self._target_changed()

    def _deadline_kind(self) -> str:
        checked = self.deadline_group.checkedButton()
        return str(checked.property("deadlineKind") if checked else "none")

    def _deadline_changed(self, *_args) -> None:
        kind = self._deadline_kind()
        stage_visible = kind in {"stage_start", "stage_overtime"}
        time_visible = kind in {"run_clock", "stage_overtime"}
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
        decimals = 0 if kind == "item" else 2
        self.required.setMinimum(1 if kind == "item" else 0.01)
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
        kind = self.kind_combo.currentData() or "item"
        colour = (
            tracked_item_color(target)
            if self._selected_target() and kind == "item"
            else "#93C5FD"
        )
        self.selected_target.setText(target)
        if self._selected_target():
            self.selected_target.setStyleSheet(
                _chip_stylesheet(colour).replace("pickedChip", "buildSelectedTarget")
            )
        else:
            self.selected_target.setStyleSheet("")
        self.summary.setText(
            f"{target} · required {self.required.value():g} · "
            f"{self._deadline_kind().replace('_', ' ')}"
        )

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
        requirements = self._draft.get("requirements") or ()
        self.rules_count.setText(
            f"{len(requirements)} configured" if requirements else "Empty"
        )
        for row in requirements:
            deadline = row.get("deadline") or {}
            kind = deadline.get("kind", "none")
            if kind == "run_clock":
                label = f"RUN · {self._clock(deadline.get('seconds'))}"
            elif kind == "stage_start":
                label = f"Before T{deadline.get('stage')}"
            elif kind == "stage_overtime":
                label = f"T{deadline.get('stage')} OT · {self._clock(deadline.get('seconds'))}"
            else:
                label = "No deadline"
            ideal = f" · ideal {row.get('ideal')}" if row.get("ideal") is not None else ""
            priority = format_priority(str(row.get("priority") or "normal"))
            item = QListWidgetItem(
                f"{row.get('target')} · {row.get('required')}{ideal} · {priority} · {label}"
            )
            item.setData(Qt.UserRole, str(row.get("id")))
            self.rules.addItem(item)
            row_widget = self._build_requirement_row(row, label, priority)
            item.setSizeHint(row_widget.sizeHint())
            self.rules.setItemWidget(item, row_widget)
        self._refresh_preview()

    @staticmethod
    def _build_requirement_row(row: dict, deadline: str, priority: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName("BuildRequirementRow")
        widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        widget.setMinimumHeight(40)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(9)

        target = str(row.get("target") or "Requirement")
        target_colour = (
            tracked_item_color(target)
            if str(row.get("kind") or "item") == "item"
            else "#93C5FD"
        )
        target_label = QLabel(target)
        target_label.setObjectName("BuildRequirementTarget")
        target_label.setStyleSheet(
            f"color: {target_colour}; background: transparent;"
            " font-size: 12px; font-weight: 700;"
        )
        target_label.setToolTip(target)
        target_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(target_label, 1)

        required = row.get("required")
        ideal = row.get("ideal")
        goal_text = str(required)
        if ideal is not None:
            goal_text += f" · ideal {ideal}"
        goal = QLabel(goal_text)
        goal.setObjectName("BuildRequirementGoal")
        goal.setStyleSheet(
            "color: #C7D0DC; background: transparent; font-size: 11px;"
        )
        goal.setToolTip(goal_text)
        goal.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(goal)

        priority_colour = {
            "High": "#F6B85A",
            "Medium": "#93C5FD",
            "Low": "#7F8A98",
        }.get(priority, "#7F8A98")
        priority_label = QLabel(priority)
        priority_label.setObjectName("BuildRequirementPriority")
        priority_label.setStyleSheet(
            "QLabel#BuildRequirementPriority {"
            f" color: {priority_colour}; border: 1px solid {priority_colour};"
            " background: transparent; border-radius: 6px; padding: 2px 6px;"
            " font-size: 11px; font-weight: 700;"
            "}"
        )
        layout.addWidget(priority_label)

        deadline_label = QLabel(deadline)
        deadline_label.setObjectName("BuildRequirementDeadline")
        deadline_label.setStyleSheet(
            "QLabel#BuildRequirementDeadline {"
            " color: #B9DFFF; background-color: #10263A;"
            " border: 1px solid #1F4D70; border-radius: 6px;"
            " padding: 2px 7px; font-size: 11px; font-weight: 700;"
            "}"
        )
        layout.addWidget(deadline_label)
        return widget

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
        self._select_target(str(row.get("target") or ""))
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
