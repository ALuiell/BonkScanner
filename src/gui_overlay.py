from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from ui.canvas_preview import CanvasPreview, PreviewWidget
from ui.dialogs.tracked_items import TrackedItemPicker
from ui.module_tile import ModuleTile
from ui.run_toggle import OVERLAY_SERVER_CAPTIONS
from ui.segmented_toggle import ROLE_GO, SegmentedToggle
from ui.settings_card import OBS_RAIL_WIDTH, SettingsCard, build_workspace
from ui.shared import (
    SCANNER_REMINDER_LABEL,
    CollapsibleSection,
    CollapsibleSectionGroup,
    FlowLayout,
    TrackedRuleTagWidget,
    _make_scroll_section,
    _set_text,
    _set_text_input,
)
from ui.styles import _set_widget_style_role
from ui.tab_hero import STATE_DANGER, STATE_OFF, STATE_OK, STATE_WARN, TabHero
from projections.tracked_items import (
    available_tracked_item_names,
    dedupe_item_names,
    overlay_rule_id,
    session_rule_id,
    tracked_item_color,
    tracked_item_combo_display_name,
    tracked_item_command_label,
    tracked_item_display_name,
    tracked_rule_color,
    tracked_rule_display_label,
    tracked_rule_tag_label,
    uses_session_tracked_items,
)
from core.tracker.live_run import TrackedItemRule
from app.coordinator import AppCoordinator
from projections.obs import build_overlay_state
from core.stats.types import PLAYER_STAT_GROUPS
from core.luck_rarity import LUCK_RARITY_MODEL_ATTRIBUTION
from session_stats import SessionStats
from tracked_item_rules import tracked_item_rules_from_config


OVERLAY_WIDGET_LABELS = {
    "stage_summary": "Stage summary",
    "tracked_items": "Tracked items",
    "stats": "Stats",
    "kps": "KPS",
    "banishes": "Banishes",
    "luck_rarity": "Luck",
}

#: How wide the URL row's field and the widget picker beside it may get. The
#: longest URL this field ever holds is the single-widget one -- about 55
#: characters -- and it reads at this width with room over. The cards run the
#: full width of the tab now, so without a cap here the field would follow them
#: and hold a 55-character URL in 1300px.
_URL_MAX_WIDTH = 560

#: The width of the whole URL row -- its label, the capped field and the Copy
#: button. The mode picker above it is held to this so the two line up.
_SOURCE_ROW_MAX_WIDTH = 690

OVERLAY_KPS_METRIC_LABELS = (
    ("current", "Current KPS"),
    ("minute_avg", "60s Avg"),
    ("five_minute_avg", "5m Avg"),
    ("run_avg", "Run Avg"),
)

class Overlay:
    """OBS overlay runtime, settings view and tracked-item configuration."""

    def __init__(
        self,
        coordinator: AppCoordinator,
        *,
        session_stats: SessionStats,
        stats_tab: Callable[[], QWidget | None],
        set_tracked_item_rows: Callable[[Any], None],
        overlay_tab_active: Callable[[], bool],
        server_rebuilt: Callable[[Any], None],
        log: Callable[..., None] | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.session_stats = session_stats
        self._stats_tab = stats_tab
        self._set_tracked_item_rows = set_tracked_item_rows
        self._overlay_tab_active = overlay_tab_active
        self._server_rebuilt = server_rebuilt
        # Optional on purpose: the suite builds this object without an app, and
        # a status transition must never be the thing that raises.
        self._log_port = log
        self._last_logged_overlay_status: str | None = None

        self.overlay_state_store = coordinator.overlay_state_store
        self.live_run_tracker = coordinator.live_run_tracker
        self.overlay_server = coordinator.overlay_server

        self.tab_overlay: QWidget | None = None
        self.overlay_enabled_checkbox = None
        self.overlay_status_label = None
        self.overlay_server_toggle_btn = None
        self.overlay_url_entry = None
        self.overlay_widget_url_combo = None
        self.overlay_widget_url_entry = None
        self.overlay_port_entry = None
        self.overlay_template_combo = None
        self.overlay_widget_checkboxes = {}
        self.overlay_stats_checkboxes = {}
        self.overlay_stats_content = None
        self.overlay_tracked_items_label = None
        self.overlay_tracked_items_content = None
        self.overlay_tracked_items_toggle_btn = None
        self.overlay_item_names = ()
        self.overlay_item_search_entry = None
        self.overlay_item_selector = None
        self.overlay_map_one_only_checkbox = None
        self.overlay_add_tracked_item_btn = None
        self.overlay_tracked_rules_list = None
        self.overlay_remove_tracked_item_btn = None
        self.session_item_names = ()
        self.session_item_search_entry = None
        self.session_item_selector = None
        self.session_map_one_only_checkbox = None
        self.session_add_tracked_item_btn = None
        self.session_tracked_rules_list = None
        self.session_remove_tracked_item_btn = None

        self.overlay_state_store.set_state(
            build_overlay_state(self.live_run_tracker, self._effective_overlay_config())
        )

    def _log(self, message: str, *, tag: str | None = None) -> None:
        port = self._log_port
        if port is None:
            return
        try:
            port(message, tag=tag)
        except Exception:
            pass

    @property
    def tab_stats(self):
        return self._stats_tab()


    def _is_overlay_tab_active(self) -> bool:
        return self._overlay_tab_active()

    #: The two source modes card 1 offers. The mock drew a third, `Layout
    #: editor`, but that is the same URL with `?edit=true` on it rather than a
    #: state this control can rest in -- a segment that opens something and has
    #: to spring back is a button. It is the card's header action instead.
    SOURCE_MODE_FULL = "full"
    SOURCE_MODE_SINGLE = "single"

    def build(self) -> QWidget:
        self.tab_overlay = QWidget()
        tab_layout = QVBoxLayout(self.tab_overlay)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        overlay_scroll, _overlay_content, layout = _make_scroll_section()
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.addWidget(overlay_scroll)

        layout.addWidget(self._build_hero())

        # Full width, like the other two streaming tabs. The rail keeps its own
        # fixed width, so what the outer cap used to hold back is the URL row --
        # and that is capped where it belongs now, on the field itself.
        main_column, side_column = build_workspace(
            layout, rail_width=OBS_RAIL_WIDTH, max_width=None
        )

        self._build_source_card(main_column)
        self._build_widgets_card(main_column)
        self._build_behaviour_card(main_column)
        main_column.addStretch(1)

        self._build_preview_card(side_column)
        self._build_tip_card(side_column)
        side_column.addStretch(1)

        self.overlay_tracked_items_label = None

        layout.addStretch(1)
        self.refresh_overlay_item_selector()
        self.refresh_overlay_tracked_items_ui()
        self.refresh_overlay_ui()
        self._refresh_overlay_preview()
        return self.tab_overlay

    def _build_hero(self) -> TabHero:
        self.overlay_hero = TabHero(
            title="OBS Overlay",
            subtitle="Send live run data to OBS through a local browser source.",
            icon_path="media/obs_icon.svg",
            auto_text="Auto-start server",
            run_captions=OVERLAY_SERVER_CAPTIONS,
        )
        # Kept under their old names because `save_overlay_settings_from_ui` and
        # `refresh_overlay_ui` read them by name, and both still work: the auto
        # switch is a QCheckBox, and the run toggle answers `setText`.
        self.overlay_auto_start_cb = self.overlay_hero.auto_switch
        self.overlay_auto_start_cb.setChecked(config.OVERLAY.get("auto_start", False))
        self.overlay_auto_start_cb.setToolTip(
            "Start the overlay server automatically when the application starts."
        )
        self.overlay_auto_start_cb.stateChanged.connect(
            lambda _state: self.save_overlay_settings_from_ui()
        )

        self.overlay_server_toggle_btn = self.overlay_hero.run_toggle
        self.overlay_server_toggle_btn.toggle_requested.connect(self.toggle_overlay_server)
        return self.overlay_hero

    def _build_source_card(self, column: QVBoxLayout) -> None:
        editor_btn = QPushButton("Open layout editor")
        editor_btn.clicked.connect(self._open_overlay_layout_editor)
        card = SettingsCard(
            number=1,
            title="Browser source",
            subtitle="Copy once, paste into OBS and keep BonkScanner running.",
            action=editor_btn,
        )

        # `disable_inactive=False`: these are two choices, not two halves of one
        # transition, so both stay clickable. Shipping a picker on the default
        # made the unselected option unselectable once already -- see
        # `SegmentedToggle.__init__`.
        self.overlay_source_mode_toggle = SegmentedToggle(
            (
                (self.SOURCE_MODE_FULL, "Full overlay", ROLE_GO),
                (self.SOURCE_MODE_SINGLE, "Single widget", ROLE_GO),
            ),
            disable_inactive=False,
        )
        self.overlay_source_mode_toggle.activated.connect(self._on_overlay_source_mode)
        # Held to the width of the URL row under it, so the card reads as one
        # block of controls rather than a full-bleed banner over a short field.
        # A row with a trailing stretch rather than `setMaximumWidth` alone: a
        # widget narrower than its cell in a `QVBoxLayout` gets centred, which
        # would leave it lined up with nothing.
        self.overlay_source_mode_toggle.setMaximumWidth(_SOURCE_ROW_MAX_WIDTH)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(self.overlay_source_mode_toggle, 1)
        mode_row.addStretch(1)
        card.body.addLayout(mode_row)

        # The widget picker the mock dropped. Without it "Single widget" names a
        # mode but not a widget, and the field below has nothing to put in the
        # URL. Hidden in full-overlay mode rather than disabled: it is not a
        # choice that exists there.
        self.overlay_widget_url_row = QWidget()
        self.overlay_widget_url_row.setObjectName("fieldRow")
        widget_row = QHBoxLayout(self.overlay_widget_url_row)
        widget_row.setContentsMargins(0, 0, 0, 0)
        widget_row.setSpacing(8)
        widget_row.addWidget(QLabel("Widget:"))
        self.overlay_widget_url_combo = QComboBox()
        for widget_id, label in OVERLAY_WIDGET_LABELS.items():
            self.overlay_widget_url_combo.addItem(label, widget_id)
        self.overlay_widget_url_combo.currentIndexChanged.connect(
            lambda _index: self.refresh_overlay_ui()
        )
        self.overlay_widget_url_combo.setMaximumWidth(_URL_MAX_WIDTH)
        widget_row.addWidget(self.overlay_widget_url_combo, 1)
        widget_row.addStretch(1)
        self.overlay_widget_url_row.setVisible(False)
        card.body.addWidget(self.overlay_widget_url_row)

        url_row = QHBoxLayout()
        url_row.setContentsMargins(0, 0, 0, 0)
        url_row.setSpacing(8)
        url_row.addWidget(QLabel("URL:"))
        # One field for both modes. The two used to be visible at once; the
        # segmented control is what replaced that, and `refresh_overlay_ui`
        # decides which URL belongs here.
        self.overlay_url_entry = QLineEdit()
        self.overlay_url_entry.setReadOnly(True)
        self.overlay_url_entry.setMaximumWidth(_URL_MAX_WIDTH)
        url_row.addWidget(self.overlay_url_entry, 1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(
            lambda: self._copy_to_clipboard(self.overlay_url_entry.text(), copy_btn)
        )
        url_row.addWidget(copy_btn)
        # Keeps Copy against the field. Without it the button takes the surplus
        # the capped field refuses and ends up sitting at the far edge of the
        # card, a screen away from what it copies.
        url_row.addStretch(1)
        card.body.addLayout(url_row)

        port_row = QHBoxLayout()
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.setSpacing(8)
        port_row.addWidget(QLabel("Port:"))
        self.overlay_port_entry = QLineEdit(str(config.OVERLAY.get("port", 17845)))
        self.overlay_port_entry.setMaximumWidth(90)
        self.overlay_port_entry.editingFinished.connect(self.save_overlay_settings_from_ui)
        port_row.addWidget(self.overlay_port_entry)
        port_row.addWidget(QLabel("Local only"))
        port_row.addStretch(1)
        card.body.addLayout(port_row)

        column.addWidget(card)

    def _build_widgets_card(self, column: QVBoxLayout) -> None:
        self.overlay_widget_settings_btn = QPushButton("Widget Settings")
        self.overlay_widget_settings_btn.clicked.connect(
            self.open_overlay_widget_settings_dialog
        )
        card = SettingsCard(
            number=2,
            title="Overlay widgets",
            subtitle="Choose what is visible. Detailed settings stay one level deeper.",
            action=self.overlay_widget_settings_btn,
        )

        tiles = QGridLayout()
        tiles.setSpacing(8)
        tiles.setContentsMargins(0, 0, 0, 0)
        self.overlay_widget_checkboxes = {}
        widget_config = self._overlay_widget_config_by_id()
        for index, (widget_id, label) in enumerate(OVERLAY_WIDGET_LABELS.items()):
            tile = ModuleTile(label)
            tile.setChecked(bool(widget_config.get(widget_id, {}).get("enabled", True)))
            tile.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_widget_checkboxes[widget_id] = tile
            tiles.addWidget(tile, index // 3, index % 3)
        card.body.addLayout(tiles)

        column.addWidget(card)

    def _build_behaviour_card(self, column: QVBoxLayout) -> None:
        card = SettingsCard(
            number=3,
            title="Server & source behaviour",
            subtitle="Secondary options, kept out of the primary action's way.",
        )
        # The only real option there is. The mock's other one, "Remember last
        # canvas", describes something the browser editor already does
        # unconditionally -- off would mean discarding the canvas on restart.
        #
        # This is the same flag the Settings dialog edits, deliberately: it is
        # about OBS, and this is the OBS tab. The label is shared with the
        # dialog so one value does not appear under two names.
        self.overlay_scanner_reminder_cb = QCheckBox(SCANNER_REMINDER_LABEL)
        self.overlay_scanner_reminder_cb.setChecked(
            bool(getattr(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False))
        )
        self.overlay_scanner_reminder_cb.setToolTip(
            "Remind you to start the OBS recording when the scanner starts."
        )
        self.overlay_scanner_reminder_cb.stateChanged.connect(
            self._on_overlay_scanner_reminder_toggled
        )
        card.body.addWidget(self.overlay_scanner_reminder_cb)

        column.addWidget(card)

    #: How stale a client poll may be before the preview stops calling itself
    #: live. The page polls every `poll_ms` (500 by default), so this is five
    #: missed polls -- long enough not to flicker on a slow frame, short enough
    #: that closing OBS shows up while you are still looking at the tab.
    PREVIEW_LIVE_WINDOW_SECONDS = 2.5

    def _build_preview_card(self, column: QVBoxLayout) -> None:
        self.overlay_preview_badge = QLabel("NO SOURCE")
        self.overlay_preview_badge.setObjectName("heroBadge")
        self.overlay_preview_badge.setProperty("state", STATE_OFF)
        card = SettingsCard(
            number=None,
            title="Canvas preview",
            subtitle="Read-only — edit in the layout editor.",
            action=None,
        )
        # The badge is a header ornament rather than an action, so it goes in
        # the header row by hand instead of through `action`.
        card.findChild(QFrame, "settingsCardHead").layout().addWidget(
            self.overlay_preview_badge, 0, Qt.AlignVCenter
        )

        self.overlay_preview = CanvasPreview()
        card.body.addWidget(self.overlay_preview)
        self.overlay_preview_legend = QLabel("")
        self.overlay_preview_legend.setObjectName("previewLegend")
        self.overlay_preview_legend.setTextFormat(Qt.RichText)
        card.body.addWidget(self.overlay_preview_legend)
        column.addWidget(card)

        # Its own slow poll, because nothing else ticks when the scanner is off:
        # `update_overlay_state_from_tracker` only runs while there is tracker
        # activity, and "OBS was closed" has to become visible without any.
        self.overlay_preview_timer = QTimer(self.tab_overlay)
        self.overlay_preview_timer.setInterval(1000)
        self.overlay_preview_timer.timeout.connect(self._refresh_overlay_preview)
        self.overlay_preview_timer.start()

    def _refresh_overlay_preview(self) -> None:
        preview = getattr(self, "overlay_preview", None)
        if preview is None:
            return
        # Only while the tab is on screen: this repaints, and a background tab
        # repainting once a second for nobody is the cost the guard avoids.
        if not self._is_overlay_tab_active():
            return

        overlay_config = self._effective_overlay_config()
        preview.set_canvas(
            int(overlay_config.get("canvas_width", 1920) or 1920),
            int(overlay_config.get("canvas_height", 1080) or 1080),
        )

        enabled = [
            widget
            for widget in overlay_config.get("widgets", [])
            if isinstance(widget, dict) and widget.get("enabled")
        ]
        placed = [
            widget
            for widget in enabled
            if widget.get("x") is not None and widget.get("y") is not None
        ]
        if enabled and not placed:
            # The page's own rule: absolute positioning turns on only when at
            # least one widget carries coordinates, otherwise the browser flows
            # them by `order` through CSS this cannot reproduce. Saying so beats
            # drawing an empty canvas that looks like a lost layout.
            preview.set_placeholder(
                "Widgets are auto-arranged.\nOpen the layout editor to place them."
            )
            preview.set_widgets(())
        else:
            preview.set_placeholder("")
            preview.set_widgets(
                PreviewWidget(
                    label=OVERLAY_WIDGET_LABELS.get(
                        str(widget.get("id") or ""), str(widget.get("id") or "")
                    ),
                    x=int(widget.get("x") or 0),
                    y=int(widget.get("y") or 0),
                    width=int(widget.get("width") or 0),
                    height=int(widget.get("height") or 0),
                    # A block on a 1920 canvas in a 360px column is around
                    # twenty pixels wide; a number is what fits, and the legend
                    # below carries the names.
                    marker=str(index),
                )
                for index, widget in enumerate(placed, start=1)
            )

        legend = getattr(self, "overlay_preview_legend", None)
        if legend is not None:
            legend.setText(preview.legend_html())
        self._refresh_overlay_preview_badge()

    def _refresh_overlay_preview_badge(self) -> None:
        badge = getattr(self, "overlay_preview_badge", None)
        if badge is None:
            return
        server = getattr(self, "overlay_server", None)
        elapsed = None
        if server is not None:
            reader = getattr(server, "seconds_since_state_request", None)
            if callable(reader):
                elapsed = reader()

        if not (server is not None and server.is_running):
            caption, state = "SERVER OFF", STATE_OFF
        elif elapsed is None:
            # Never polled since this server started: the source has not been
            # added, or points somewhere else. Not an error -- just not live.
            caption, state = "NO SOURCE", STATE_WARN
        elif elapsed <= self.PREVIEW_LIVE_WINDOW_SECONDS:
            # "A browser source", not "OBS": the server cannot tell OBS from an
            # ordinary tab, so the badge does not claim to either.
            caption, state = "SOURCE LIVE", STATE_OK
        else:
            caption, state = "SOURCE IDLE", STATE_WARN

        badge.setText(caption)
        if badge.property("state") != state:
            badge.setProperty("state", state)
            style = badge.style()
            if style is not None:
                style.unpolish(badge)
                style.polish(badge)
            badge.update()

    def _build_tip_card(self, column: QVBoxLayout) -> None:
        tip = QFrame()
        tip.setObjectName("tipCard")
        tip.setProperty("tipCard", "true")
        tip_layout = QVBoxLayout(tip)
        tip_layout.setContentsMargins(12, 11, 12, 11)
        tip_layout.setSpacing(4)

        title = QLabel("◎ OBS CANVAS")
        title.setObjectName("tipCardTitle")
        tip_layout.addWidget(title)

        body = QLabel(
            "Match the Browser Source size in OBS to the overlay canvas "
            "(default 1920×1080). Open the layout editor only when positions or "
            "the canvas resolution need adjusting — it saves as you drag."
        )
        body.setObjectName("tipCardText")
        body.setWordWrap(True)
        tip_layout.addWidget(body)

        column.addWidget(tip)

    # -- card 1 behaviour ----------------------------------------------------

    def _on_overlay_source_mode(self, key: str) -> None:
        self.overlay_source_mode_toggle.set_active(key)
        self.overlay_widget_url_row.setVisible(key == self.SOURCE_MODE_SINGLE)
        self.refresh_overlay_ui()

    def _overlay_source_mode(self) -> str:
        toggle = getattr(self, "overlay_source_mode_toggle", None)
        if toggle is None:
            return self.SOURCE_MODE_FULL
        return toggle.active_key() or self.SOURCE_MODE_FULL

    def _open_overlay_layout_editor(self) -> None:
        """Open the editor URL in the browser. Not a mode -- a query parameter."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(f"{self._overlay_url_text()}?edit=true"))

    def _on_overlay_scanner_reminder_toggled(self, *_args) -> None:
        enabled = bool(self.overlay_scanner_reminder_cb.isChecked())
        config.SHOW_OBS_REMINDER_ON_START_SCANNER = enabled
        config.user_config["SHOW_OBS_REMINDER_ON_START_SCANNER"] = enabled
        config.save_config(config.user_config)

    def refresh_scanner_reminder_ui(self) -> None:
        """Re-read the reminder flag. Called after the Settings dialog saves.

        The dialog is the second editor of this one value. It is modal and built
        fresh per open, so it always shows the current state -- but nothing tells
        *this* checkbox that the dialog changed it, and a stale box would write
        the old value back on its next toggle.
        """
        checkbox = getattr(self, "overlay_scanner_reminder_cb", None)
        if checkbox is None:
            return
        enabled = bool(getattr(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False))
        if checkbox.isChecked() == enabled:
            return
        # Without the block this re-entry writes the value straight back to
        # config -- harmless today, but it turns a refresh into a save, which is
        # not what a refresh is for.
        checkbox.blockSignals(True)
        checkbox.setChecked(enabled)
        checkbox.blockSignals(False)

    def _copy_to_clipboard(self, text: str, button: QPushButton) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QTimer
        QGuiApplication.clipboard().setText(text)
        original_text = button.text()
        button.setText("Copied!")
        button.setEnabled(False)
        button.setStyleSheet("background-color: #2F9E6D; color: white; padding: 5px 10px; min-width: 50px;")
        def restore():
            button.setText(original_text)
            button.setEnabled(True)
            button.setStyleSheet("QPushButton { padding: 5px 10px; min-width: 50px; }")
        QTimer.singleShot(1500, restore)

    def open_overlay_widget_settings_dialog(self) -> None:
        dialog = QDialog(self.tab_overlay)
        dialog.setUpdatesEnabled(False)
        dialog.setWindowTitle("Widget Settings")
        dialog.resize(700, 760)
        dialog.setMinimumSize(640, 680)
        dialog_layout = QVBoxLayout(dialog)

        settings_tabs = QTabWidget()
        settings_tabs.setObjectName("subTabs")
        dialog_layout.addWidget(settings_tabs, 1)

        basic_tab = QWidget()
        basic_tab_layout = QVBoxLayout(basic_tab)
        basic_scroll, _basic_content, basic_layout = _make_scroll_section()
        basic_layout.setSpacing(10)
        basic_tab_layout.addWidget(basic_scroll)

        advanced_tab = QWidget()
        advanced_tab_layout = QVBoxLayout(advanced_tab)
        advanced_scroll, _advanced_content, advanced_layout = _make_scroll_section()
        advanced_layout.setSpacing(10)
        advanced_tab_layout.addWidget(advanced_scroll)

        stage_summary_group = QGroupBox("Stage Summary")
        stage_summary_layout = QVBoxLayout(stage_summary_group)
        stage_summary_layout.addWidget(QLabel("Configure the Stage Summary overlay widget."))
        stage_summary_widget_cfg = self._overlay_widget_config_by_id().get("stage_summary", {})
        self.overlay_stage_summary_bg_checkbox = QCheckBox("Show background")
        self.overlay_stage_summary_bg_checkbox.setChecked(float(stage_summary_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_stage_summary_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        stage_summary_layout.addWidget(self.overlay_stage_summary_bg_checkbox)
        basic_layout.addWidget(stage_summary_group)

        banishes_group = QGroupBox("Banishes")
        banishes_layout = QVBoxLayout(banishes_group)
        banishes_layout.addWidget(QLabel("Configure the Banishes overlay widget."))
        banishes_widget_cfg = self._overlay_widget_config_by_id().get("banishes", {})
        self.overlay_banishes_bg_checkbox = QCheckBox("Show background")
        self.overlay_banishes_bg_checkbox.setChecked(float(banishes_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_banishes_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        banishes_layout.addWidget(self.overlay_banishes_bg_checkbox)

        self.overlay_banishes_header_checkbox = QCheckBox("Show header")
        self.overlay_banishes_header_checkbox.setChecked(bool(banishes_widget_cfg.get("show_header", True)))
        self.overlay_banishes_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        banishes_layout.addWidget(self.overlay_banishes_header_checkbox)
        basic_layout.addWidget(banishes_group)

        kps_group = QGroupBox("KPS")
        kps_layout = QVBoxLayout(kps_group)
        kps_layout.addWidget(QLabel("Configure the compact KPS overlay widget."))
        kps_widget_cfg = self._overlay_widget_config_by_id().get("kps", {})
        self.overlay_kps_bg_checkbox = QCheckBox("Show background")
        self.overlay_kps_bg_checkbox.setChecked(float(kps_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_kps_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        kps_layout.addWidget(self.overlay_kps_bg_checkbox)

        self.overlay_kps_header_checkbox = QCheckBox("Show header")
        self.overlay_kps_header_checkbox.setChecked(bool(kps_widget_cfg.get("show_header", False)))
        self.overlay_kps_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        kps_layout.addWidget(self.overlay_kps_header_checkbox)

        kps_layout.addSpacing(12)
        self.overlay_kps_metric_checkboxes = {}
        selected_kps_metrics = set(self._overlay_selected_kps_metric_ids())
        for metric_id, metric_label in self._overlay_all_kps_metric_labels():
            checkbox = QCheckBox(metric_label)
            checkbox.setChecked(metric_id in selected_kps_metrics)
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_kps_metric_checkboxes[metric_id] = checkbox
            kps_layout.addWidget(checkbox)
        basic_layout.addWidget(kps_group)

        luck_group = QGroupBox("Luck")
        luck_layout = QVBoxLayout(luck_group)
        luck_layout.addWidget(QLabel("Configure the Luck overlay widget."))
        luck_widget_cfg = self._overlay_widget_config_by_id().get("luck_rarity", {})
        self.overlay_luck_bg_checkbox = QCheckBox("Show background")
        self.overlay_luck_bg_checkbox.setChecked(float(luck_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_luck_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        luck_layout.addWidget(self.overlay_luck_bg_checkbox)

        self.overlay_luck_header_checkbox = QCheckBox("Show header")
        self.overlay_luck_header_checkbox.setChecked(bool(luck_widget_cfg.get("show_header", True)))
        self.overlay_luck_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        luck_layout.addWidget(self.overlay_luck_header_checkbox)

        # Configured apart from the in-game widget's pair on purpose: a streamer
        # may want the frame on the stream and not in their own view.
        self.overlay_luck_bar_checkbox = QCheckBox("Show rarity bar")
        self.overlay_luck_bar_checkbox.setChecked(bool(luck_widget_cfg.get("show_bar", True)))
        self.overlay_luck_bar_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        luck_layout.addWidget(self.overlay_luck_bar_checkbox)

        self.overlay_luck_expected_checkbox = QCheckBox("Show expected frame")
        self.overlay_luck_expected_checkbox.setToolTip(LUCK_RARITY_MODEL_ATTRIBUTION)
        self.overlay_luck_expected_checkbox.setChecked(bool(luck_widget_cfg.get("show_expected", True)))
        self.overlay_luck_expected_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        luck_layout.addWidget(self.overlay_luck_expected_checkbox)

        luck_layout_row = QHBoxLayout()
        luck_layout_row.addWidget(QLabel("Expected layout:"))
        self.overlay_luck_layout_combo = QComboBox()
        for label, value in (("Column (2x2)", "column"), ("Row (single line)", "row")):
            self.overlay_luck_layout_combo.addItem(label, value)
        self.overlay_luck_layout_combo.setCurrentIndex(
            max(0, self.overlay_luck_layout_combo.findData(luck_widget_cfg.get("expected_layout", "column")))
        )
        self.overlay_luck_layout_combo.currentIndexChanged.connect(
            lambda _index: self.save_overlay_settings_from_ui()
        )
        luck_layout_row.addWidget(self.overlay_luck_layout_combo)
        luck_layout_row.addStretch(1)
        luck_layout.addLayout(luck_layout_row)
        basic_layout.addWidget(luck_group)
        basic_layout.addStretch(1)

        stats_group = CollapsibleSection("Stats", expanded=True)
        stats_layout = stats_group.body_layout
        stats_layout.addWidget(QLabel("Selected stats appear in the Stats overlay widget."))
        stats_widget_cfg = self._overlay_widget_config_by_id().get("stats", {})
        self.overlay_stats_bg_checkbox = QCheckBox("Show background")
        self.overlay_stats_bg_checkbox.setChecked(float(stats_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_stats_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        stats_layout.addWidget(self.overlay_stats_bg_checkbox)

        self.overlay_stats_header_checkbox = QCheckBox("Show header")
        self.overlay_stats_header_checkbox.setChecked(bool(stats_widget_cfg.get("show_header", True)))
        self.overlay_stats_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        stats_layout.addWidget(self.overlay_stats_header_checkbox)

        self.overlay_stats_short_labels_checkbox = QCheckBox("Short stat names")
        self.overlay_stats_short_labels_checkbox.setToolTip(
            "Show abbreviated stat names (DMG, AS, XP) as in the in-game overlay "
            "and the Twitch bot. Uncheck to show full names (Damage, Attack Speed, XP Gain)."
        )
        self.overlay_stats_short_labels_checkbox.setChecked(
            bool(stats_widget_cfg.get("short_stat_labels", True))
        )
        self.overlay_stats_short_labels_checkbox.stateChanged.connect(
            lambda _state: self.save_overlay_settings_from_ui()
        )
        stats_layout.addWidget(self.overlay_stats_short_labels_checkbox)

        stats_layout.addSpacing(12)
        stats_config_layout = QGridLayout()
        self.overlay_stats_checkboxes = {}
        selected_stats = set(self._overlay_selected_stat_labels())
        for index, label in enumerate(self._overlay_all_stat_labels()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(label in selected_stats)
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_stats_checkboxes[label] = checkbox
            stats_config_layout.addWidget(checkbox, index // 4, index % 4)
        stats_layout.addLayout(stats_config_layout)
        stats_layout.addSpacing(12)

        reset_btn_layout = QHBoxLayout()
        self.overlay_stats_reset_btn = QPushButton("Reset to Default Stats")
        self.overlay_stats_reset_btn.clicked.connect(self._reset_overlay_stats_to_default)
        reset_btn_layout.addWidget(self.overlay_stats_reset_btn)
        reset_btn_layout.addStretch(1)
        stats_layout.addLayout(reset_btn_layout)

        advanced_layout.addWidget(stats_group)

        items_group = CollapsibleSection(
            "Tracked Items",
            expanded=False,
        )
        items_layout = items_group.body_layout
        items_layout.addWidget(QLabel("Configure tracked item counters for the overlay."))

        self.overlay_use_session_tracked_items_cb = QCheckBox("Use Session Stats tracked items")
        self.overlay_use_session_tracked_items_cb.setChecked(uses_session_tracked_items(config.OVERLAY, default="custom"))
        self.overlay_use_session_tracked_items_cb.stateChanged.connect(self.on_overlay_tracked_items_source_toggled)
        items_layout.addWidget(self.overlay_use_session_tracked_items_cb)

        self.overlay_tracked_items_source_label = QLabel()
        self.overlay_tracked_items_source_label.setWordWrap(True)
        items_layout.addWidget(self.overlay_tracked_items_source_label)

        self.overlay_custom_tracked_items_widget = QWidget()
        overlay_custom_layout = QVBoxLayout(self.overlay_custom_tracked_items_widget)
        overlay_custom_layout.setContentsMargins(0, 0, 0, 0)
        overlay_custom_layout.setSpacing(8)

        top_layout = QVBoxLayout()
        top_layout.setSpacing(4)

        search_top_layout = QHBoxLayout()
        search_top_layout.addWidget(QLabel("Available Items (select one or more)"))
        search_top_layout.addStretch(1)
        top_layout.addLayout(search_top_layout)

        self.overlay_item_names = available_tracked_item_names()
        self.overlay_item_search_entry = QLineEdit()
        self.overlay_item_search_entry.setPlaceholderText("Search items...")
        self.overlay_item_search_entry.textChanged.connect(self.refresh_overlay_item_selector)
        top_layout.addWidget(self.overlay_item_search_entry)

        self.overlay_item_selector = QListWidget()
        self.overlay_item_selector.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.overlay_item_selector.setMinimumHeight(220)
        self.overlay_item_selector.setMaximumHeight(280)
        self.overlay_item_selector.setFlow(QListView.Flow.LeftToRight)
        self.overlay_item_selector.setWrapping(True)
        self.overlay_item_selector.setResizeMode(QListView.ResizeMode.Adjust)
        self.overlay_item_selector.setStyleSheet("QListWidget { font-size: 13px; }")
        top_layout.addWidget(self.overlay_item_selector)

        action_row = QHBoxLayout()
        self.overlay_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.overlay_map_one_only_checkbox.setChecked(True)
        self.overlay_map_one_only_checkbox.setToolTip("If checked, only counts gains on the first map.")
        action_row.addWidget(self.overlay_map_one_only_checkbox)
        action_row.addStretch(1)

        self.overlay_add_tracked_item_btn = QPushButton("Add Rule")
        self.overlay_add_tracked_item_btn.clicked.connect(self.add_overlay_tracked_item)
        action_row.addWidget(self.overlay_add_tracked_item_btn)

        top_layout.addLayout(action_row)
        overlay_custom_layout.addLayout(top_layout)

        overlay_custom_layout.addSpacing(10)

        tags_top_layout = QHBoxLayout()
        tags_top_layout.addWidget(QLabel("Currently tracked"))
        tags_top_layout.addStretch(1)

        overlay_custom_layout.addLayout(tags_top_layout)

        self.overlay_tags_container = QWidget()
        self.overlay_tags_container.setStyleSheet("background-color: #0B1220;")
        self.overlay_tags_layout = FlowLayout(self.overlay_tags_container, margin=6, spacing=4)

        self.overlay_tags_scroll = QScrollArea()
        self.overlay_tags_scroll.setWidgetResizable(True)
        self.overlay_tags_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #2B3648;
                border-radius: 6px;
                background-color: #0B1220;
            }
        """)
        self.overlay_tags_scroll.setWidget(self.overlay_tags_container)
        self.overlay_tags_scroll.setMinimumHeight(80)
        self.overlay_tags_scroll.setMaximumHeight(130)
        overlay_custom_layout.addWidget(self.overlay_tags_scroll)

        tags_bottom_layout = QHBoxLayout()
        self.overlay_clear_all_tags_btn = QPushButton("Clear All")
        self.overlay_clear_all_tags_btn.clicked.connect(self.clear_all_overlay_tracked_items)
        tags_bottom_layout.addWidget(self.overlay_clear_all_tags_btn)
        tags_bottom_layout.addStretch(1)

        overlay_custom_layout.addLayout(tags_bottom_layout)
        items_layout.addWidget(self.overlay_custom_tracked_items_widget)
        advanced_layout.addWidget(items_group)
        advanced_layout.addStretch(1)
        self.overlay_advanced_sections_group = CollapsibleSectionGroup((stats_group, items_group))

        settings_tabs.addTab(basic_tab, "Basic")
        settings_tabs.addTab(advanced_tab, "Advanced")

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Done")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dialog_layout.addLayout(close_row)

        self.refresh_overlay_item_selector()
        self.refresh_overlay_tracked_items_ui()
        dialog.setUpdatesEnabled(True)
        try:
            dialog.exec()
        finally:
            self._clear_overlay_widget_settings_dialog_refs()
            self.refresh_overlay_tracked_items_ui()

    def _reset_overlay_stats_to_default(self) -> None:
        if not getattr(self, "overlay_stats_checkboxes", None):
            return
        default_stats = set(self._overlay_default_stat_labels())
        for label, checkbox in self.overlay_stats_checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(label in default_stats)
            checkbox.blockSignals(False)
        self.save_overlay_settings_from_ui()

    def _clear_overlay_widget_settings_dialog_refs(self) -> None:
        self.overlay_stats_checkboxes = None
        self.overlay_stats_bg_checkbox = None
        self.overlay_stats_header_checkbox = None
        self.overlay_stats_short_labels_checkbox = None
        self.overlay_stats_reset_btn = None
        self.overlay_stage_summary_bg_checkbox = None
        self.overlay_kps_bg_checkbox = None
        self.overlay_kps_header_checkbox = None
        self.overlay_kps_metric_checkboxes = None
        self.overlay_banishes_bg_checkbox = None
        self.overlay_banishes_header_checkbox = None
        self.overlay_luck_bg_checkbox = None
        self.overlay_luck_header_checkbox = None
        self.overlay_luck_bar_checkbox = None
        self.overlay_luck_expected_checkbox = None
        self.overlay_luck_layout_combo = None
        self.overlay_item_search_entry = None
        self.overlay_item_selector = None
        self.overlay_map_one_only_checkbox = None
        self.overlay_add_tracked_item_btn = None
        self.overlay_clear_all_tags_btn = None
        self.overlay_tags_container = None
        self.overlay_tags_layout = None
        self.overlay_tags_scroll = None
        self.overlay_use_session_tracked_items_cb = None
        self.overlay_tracked_items_source_label = None
        self.overlay_custom_tracked_items_widget = None

    def toggle_overlay_server(self) -> None:
        server = getattr(self, "overlay_server", None)
        should_start = not bool(server is not None and server.is_running)
        config.OVERLAY["enabled"] = should_start
        config.user_config["OVERLAY"] = config.OVERLAY
        config.save_config(config.user_config)
        if should_start:
            self.start_overlay_server()
        else:
            self.stop_overlay_server()
        self.refresh_overlay_ui()

    def start_overlay_server(self) -> bool:
        self.save_overlay_settings_from_ui(persist=False)
        if self.overlay_server.is_running:
            return True
        self.overlay_server = self.coordinator.rebuild_overlay_server(
            host="127.0.0.1",
            port=int(config.OVERLAY.get("port", 17845)),
        )
        self._server_rebuilt(self.overlay_server)
        try:
            self.overlay_server.start()
        except OSError:
            self.refresh_overlay_ui()
            return False
        self.refresh_overlay_ui()
        return True

    def stop_overlay_server(self) -> None:
        self.overlay_server.stop()
        self.refresh_overlay_ui()

    def save_overlay_settings_from_ui(self, *, persist: bool = True) -> None:
        with config.config_lock:
            overlay = config.normalize_overlay_config(config.OVERLAY)
            port_text = self.overlay_port_entry.text().strip() if self.overlay_port_entry is not None else ""
            try:
                port = int(port_text)
            except ValueError:
                port = int(overlay.get("port", 17845))
            overlay["port"] = port
            if getattr(self, "overlay_auto_start_cb", None) is not None:
                overlay["auto_start"] = bool(self.overlay_auto_start_cb.isChecked())
            overlay = config.normalize_overlay_config(overlay)
            if self.overlay_port_entry is not None:
                _set_text_input(self.overlay_port_entry, str(overlay["port"]))

            widgets = []
            for widget in overlay.get("widgets", []):
                if not isinstance(widget, dict):
                    continue
                widget_id = str(widget.get("id") or "")
                if widget_id in self.overlay_widget_checkboxes:
                    widget = dict(widget)
                    widget["enabled"] = bool(self.overlay_widget_checkboxes[widget_id].isChecked())
                if widget_id == "stats" and getattr(self, "overlay_stats_checkboxes", None):
                    widget = dict(widget)
                    selected_stats = [
                        label
                        for label, checkbox in self.overlay_stats_checkboxes.items()
                        if checkbox.isChecked()
                    ]
                    widget["selected_stats"] = selected_stats or list(self._overlay_default_stat_labels())
                    if getattr(self, "overlay_stats_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_stats_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_stats_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_stats_header_checkbox.isChecked())
                    if getattr(self, "overlay_stats_short_labels_checkbox", None) is not None:
                        widget["short_stat_labels"] = bool(
                            self.overlay_stats_short_labels_checkbox.isChecked()
                        )
                if widget_id == "stage_summary" and getattr(self, "overlay_stage_summary_bg_checkbox", None) is not None:
                    widget = dict(widget)
                    widget["background_opacity"] = 0.4 if self.overlay_stage_summary_bg_checkbox.isChecked() else 0.0
                if widget_id == "kps":
                    widget = dict(widget)
                    if getattr(self, "overlay_kps_metric_checkboxes", None):
                        selected_kps_metrics = [
                            metric_id
                            for metric_id, checkbox in self.overlay_kps_metric_checkboxes.items()
                            if checkbox.isChecked()
                        ]
                        widget["selected_kps_metrics"] = selected_kps_metrics or ["current"]
                    if getattr(self, "overlay_kps_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_kps_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_kps_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_kps_header_checkbox.isChecked())
                if widget_id == "banishes":
                    widget = dict(widget)
                    if getattr(self, "overlay_banishes_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_banishes_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_banishes_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_banishes_header_checkbox.isChecked())
                if widget_id == "luck_rarity":
                    widget = dict(widget)
                    if getattr(self, "overlay_luck_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_luck_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_luck_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_luck_header_checkbox.isChecked())
                    if getattr(self, "overlay_luck_bar_checkbox", None) is not None:
                        widget["show_bar"] = bool(self.overlay_luck_bar_checkbox.isChecked())
                    if getattr(self, "overlay_luck_expected_checkbox", None) is not None:
                        widget["show_expected"] = bool(self.overlay_luck_expected_checkbox.isChecked())
                    if getattr(self, "overlay_luck_layout_combo", None) is not None:
                        widget["expected_layout"] = (
                            self.overlay_luck_layout_combo.currentData() or "column"
                        )
                widgets.append(widget)
            overlay["widgets"] = widgets
            if getattr(self, "overlay_tags_layout", None) is not None:
                overlay["tracked_items"] = config.OVERLAY.get("tracked_items", [])
            if getattr(self, "overlay_use_session_tracked_items_cb", None) is not None:
                overlay["tracked_items_source"] = (
                    "session" if self.overlay_use_session_tracked_items_cb.isChecked() else "custom"
                )
            config.OVERLAY = overlay
            config.user_config["OVERLAY"] = config.OVERLAY
            self.live_run_tracker.set_tracked_item_rules(self._combined_tracked_item_rules())
            self.update_overlay_state_from_tracker()
            if persist:
                config.save_config(config.user_config)
            if self.overlay_server.is_running and self.overlay_server.port != int(config.OVERLAY["port"]):
                self.overlay_server.stop()
                if bool(config.OVERLAY.get("enabled", False)):
                    self.start_overlay_server()
            self.refresh_overlay_ui()

    def refresh_overlay_ui(self) -> None:
        server = getattr(self, "overlay_server", None)
        running = bool(server is not None and server.is_running)
        if self.overlay_url_entry is not None:
            # One field, two modes. Which URL belongs in it is card 1's segmented
            # control; the field itself does not know there is a choice.
            _set_text_input(self.overlay_url_entry, self._overlay_visible_url_text())
        hero = getattr(self, "overlay_hero", None)
        if hero is not None:
            if running:
                hero.set_status("LIVE", STATE_OK)
            elif server is not None and server.last_error:
                # The badge stays a short label and the OS message goes to the
                # subtitle: `[WinError 10048] ...` is a sentence, and a sentence
                # in a 10.5px uppercase pill cannot be read.
                hero.set_status("PORT ERROR", STATE_DANGER, detail=str(server.last_error))
            else:
                hero.set_status("STOPPED", STATE_OFF)
        if getattr(self, "overlay_server_toggle_btn", None) is not None:
            start_text, stop_text = OVERLAY_SERVER_CAPTIONS
            self.overlay_server_toggle_btn.setText(stop_text if running else start_text)
            _set_widget_style_role(
                self.overlay_server_toggle_btn,
                "stopScanner" if running else "primary",
            )

    def refresh_overlay_item_selector(self) -> None:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is None:
            return
        query = ""
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip().lower()
        if selector.count() == 0:
            for item_name in getattr(self, "overlay_item_names", ()):
                display_name = tracked_item_display_name(item_name)
                item = QListWidgetItem(display_name)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setData(Qt.UserRole, item_name)
                item.setForeground(QBrush(QColor(tracked_item_color(item_name))))
                selector.addItem(item)

        for i in range(selector.count()):
            item = selector.item(i)
            item_name = str(item.data(Qt.UserRole) or item.text())
            display_name = tracked_item_display_name(item_name)
            haystacks = {item_name.lower(), display_name.lower()}
            if query and not any(query in haystack for haystack in haystacks):
                item.setHidden(True)
            else:
                item.setHidden(False)

    def refresh_overlay_tracked_items_ui(self) -> None:
        layout = getattr(self, "overlay_tags_layout", None)
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        tracked_count = 0
        for rule in config.OVERLAY.get("tracked_items") or ():
            if not isinstance(rule, dict):
                continue
            item_names = [str(name) for name in rule.get("item_names") or () if str(name).strip()]
            if not item_names:
                continue
            mode = str(rule.get("mode") or "all_run")
            label = tracked_rule_display_label(dict(rule), item_names, mode)
            rule_id = str(rule.get("id") or "")

            if layout is not None:
                accent = tracked_rule_color(item_names)
                tag = TrackedRuleTagWidget(
                    rule_id,
                    tracked_rule_tag_label(label, mode),
                    text_color=accent,
                    border_color=accent,
                    background_color="#18212C",
                )
                tag.remove_clicked.connect(self.remove_overlay_tracked_item)
                layout.addWidget(tag)
            tracked_count += 1

        if self.overlay_tracked_items_label is not None:
            if uses_session_tracked_items(config.OVERLAY, default="custom"):
                tracked_count = len(tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS))
                detail = "Using Session Stats tracked items. Map 1 only counts gains observed during stage 1."
            else:
                detail = "Map 1 only counts gains observed during stage 1."
            _set_text(self.overlay_tracked_items_label, f"Tracking {tracked_count} rule(s). {detail}")
        self._refresh_overlay_tracked_items_source_ui()

    def _refresh_overlay_tracked_items_source_ui(self) -> None:
        use_session = uses_session_tracked_items(config.OVERLAY, default="custom")
        custom_count = len(tracked_item_rules_from_config(config.OVERLAY))
        session_rules = tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        session_count = len(session_rules)
        source_label = getattr(self, "overlay_tracked_items_source_label", None)
        if source_label is not None:
            if use_session:
                preview = ", ".join(
                    tracked_item_command_label({"label": rule.label, "mode": rule.mode})
                    for rule in session_rules[:4]
                )
                if session_count > 4:
                    preview += ", ..."
                detail = preview or "No Session Stats tracked items configured"
                _set_text(
                    source_label,
                    f"Overlay source: Session Stats ({session_count}). Custom list is preserved ({custom_count}). {detail}",
                )
            else:
                _set_text(source_label, f"Overlay source: Custom ({custom_count}). Session Stats has {session_count} rule(s).")
        custom_widget = getattr(self, "overlay_custom_tracked_items_widget", None)
        if custom_widget is not None:
            custom_widget.setVisible(not use_session)
        for widget in (
            getattr(self, "overlay_map_one_only_checkbox", None),
            getattr(self, "overlay_item_search_entry", None),
            getattr(self, "overlay_item_selector", None),
            getattr(self, "overlay_add_tracked_item_btn", None),
            getattr(self, "overlay_clear_all_tags_btn", None),
        ):
            if widget is not None:
                widget.setEnabled(not use_session)

    def on_overlay_tracked_items_source_toggled(self, *_args) -> None:
        self.save_overlay_settings_from_ui()
        self.refresh_overlay_tracked_items_ui()

    def add_overlay_tracked_item(self) -> None:
        item_names = self._selected_overlay_item_names()
        if not item_names:
            return
        map_one_only = bool(self.overlay_map_one_only_checkbox.isChecked())
        mode = "map_1_only" if map_one_only else "all_run"
        display_name = tracked_item_combo_display_name(item_names)
        label = f"{display_name} Map 1" if map_one_only else display_name
        rule = {
            "id": overlay_rule_id(item_names, mode),
            "label": label,
            "item_names": item_names,
            "mode": mode,
        }
        existing_rules = [
            dict(raw_rule)
            for raw_rule in config.OVERLAY.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]
        existing_ids = {str(raw_rule.get("id") or "") for raw_rule in existing_rules}
        if rule["id"] not in existing_ids:
            existing_rules.append(rule)
        config.OVERLAY["tracked_items"] = existing_rules
        config.user_config["OVERLAY"] = config.OVERLAY

        if getattr(self, "overlay_item_selector", None) is not None:
            self.overlay_item_selector.clearSelection()
            self.overlay_item_selector.setCurrentItem(None)

        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def remove_overlay_tracked_item(self, rule_id: str) -> None:
        rule_id = str(rule_id)
        existing_rules = [
            dict(raw_rule)
            for raw_rule in config.OVERLAY.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]
        new_rules = [r for r in existing_rules if str(r.get("id") or "") != rule_id]
        config.OVERLAY["tracked_items"] = new_rules
        config.user_config["OVERLAY"] = config.OVERLAY
        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def clear_all_overlay_tracked_items(self) -> None:
        config.OVERLAY["tracked_items"] = []
        config.user_config["OVERLAY"] = config.OVERLAY
        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def open_session_tracked_item_settings_dialog(self) -> None:
        """The Session Stats tracked-item window.

        The hundred lines of construction this replaces are
        `ui/dialogs/tracked_items.TrackedItemPicker`'s. What stays here is what
        is actually the overlay component's: reading and writing
        `config.SESSION_TRACKED_ITEMS`, and rebuilding the tracker's rule set
        when it changes.
        """
        dialog = QDialog(self.tab_stats)
        dialog.setWindowTitle("Session Tracked Items")
        dialog.resize(930, 660)
        dialog.setMinimumSize(720, 520)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(14, 14, 14, 14)
        dialog_layout.setSpacing(12)

        picker = TrackedItemPicker(
            rules=self._session_tracked_item_config_from_ui,
            make_rule=self._make_session_tracked_rule,
        )
        picker.rules_changed.connect(self._apply_session_tracked_rules)
        dialog_layout.addWidget(picker, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        clear_btn = QPushButton("Remove all")
        # `danger`, and behind a confirmation, and no longer shoulder to
        # shoulder with Close: it used to sit next to the dismiss button and
        # wipe every rule on one click.
        clear_btn.setObjectName("danger")
        clear_btn.clicked.connect(
            lambda _checked=False: self._confirm_clear_session_tracked_items(dialog, picker)
        )
        footer.addWidget(clear_btn)
        footer.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        footer.addWidget(close_btn)
        dialog_layout.addLayout(footer)

        try:
            dialog.exec()
        finally:
            self.refresh_session_tracked_item_stats_ui()

    def _make_session_tracked_rule(self, item_names, mode: str) -> dict:
        """Build the persisted rule. The label is derived, as it always was."""
        item_names = tuple(str(name) for name in item_names)
        display_name = tracked_item_combo_display_name(item_names)
        return {
            "id": session_rule_id(item_names, mode),
            "label": f"{display_name} Map 1" if mode == "map_1_only" else display_name,
            "item_names": list(item_names),
            "mode": mode,
        }

    def _apply_session_tracked_rules(self, rules) -> None:
        config.SESSION_TRACKED_ITEMS["tracked_items"] = [dict(rule) for rule in rules]
        self.save_session_tracked_items_from_ui()

    def _confirm_clear_session_tracked_items(self, dialog, picker) -> None:
        confirmed = QMessageBox.question(
            dialog,
            "Remove all tracked items?",
            "Every rule below will be removed. This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed == QMessageBox.Yes:
            picker.clear_rules()

    def refresh_session_tracked_item_stats_ui(self) -> None:
        """Hand the tracked-item rules to the Session Stats tab.

        It used to join them into one string here -- `label: count (pct%) | ...`
        -- and write it into a label the scanner owned. The rows carry the items
        the rule matches and the condition it matches them under, and the join
        kept neither: the condition survived only as the `T1` suffix
        `tracked_item_command_label` adds for one of the two modes. The tab
        renders the rows now, so this hands them over whole.
        """
        if self.live_run_tracker is None:
            return
        self._set_tracked_item_rows(
            self.session_stats.session_tracked_item_stat_rows()
        )

    def save_session_tracked_items_from_ui(self) -> None:
        config.SESSION_TRACKED_ITEMS = config.normalize_session_tracked_items_config(config.SESSION_TRACKED_ITEMS)
        config.user_config["SESSION_TRACKED_ITEMS"] = config.SESSION_TRACKED_ITEMS
        config.save_config(config.user_config)
        if self.live_run_tracker is not None:
            self.live_run_tracker.set_tracked_item_rules(self._combined_tracked_item_rules())
        self.refresh_session_tracked_item_stats_ui()

    def _session_tracked_item_config_from_ui(self) -> list[dict[str, Any]]:
        return [
            dict(raw_rule)
            for raw_rule in config.SESSION_TRACKED_ITEMS.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]

    def _selected_overlay_item_names(self) -> list[str]:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is not None:
            selected_items = selector.selectedItems()
            if not selected_items and selector.currentItem() is not None:
                selected_items = [selector.currentItem()]
            item_names = [
                str(item.data(Qt.UserRole) or item.text()).strip()
                for item in selected_items
                if str(item.data(Qt.UserRole) or item.text()).strip()
            ]
            if item_names:
                return dedupe_item_names(item_names)
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip()
            for item_name in getattr(self, "overlay_item_names", ()):
                display_name = tracked_item_display_name(item_name)
                if item_name.lower() == query.lower() or display_name.lower() == query.lower():
                    return [item_name]
        return []

    def _tracked_item_config_from_ui(self) -> list[dict[str, Any]]:
        return [
            dict(raw_rule)
            for raw_rule in config.OVERLAY.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]

    def update_overlay_state_from_tracker(self) -> None:
        if self.overlay_state_store is None:
            return
        state = build_overlay_state(self.live_run_tracker, self._effective_overlay_config())
        self._log_overlay_status_transition(str(state.get("status") or ""))
        self.overlay_state_store.set_state(state)
        tab_active = getattr(self, "_is_overlay_tab_active", lambda: True)
        if getattr(self, "tab_overlay", None) is not None and tab_active():
            self.refresh_overlay_ui()

    # The overlay itself is now deliberately silent through a restart: it holds
    # the last good frame and says nothing. That silence needs somewhere to
    # land, or a genuinely stuck feed looks exactly like a healthy one. This is
    # that place -- one line per *transition*, never per tick, and only for the
    # states worth acting on. `reconnecting` is not one of them: it is the
    # expected shape of a game restart.
    _LOGGED_OVERLAY_STATUSES = {
        "stale": ("[WAIT] OBS overlay: no fresh game data; widgets are holding the last known values.", "warning"),
        "no_game": ("[WAIT] OBS overlay: game process is gone; widgets are holding the last known values.", "warning"),
    }

    def _log_overlay_status_transition(self, status: str) -> None:
        previous = getattr(self, "_last_logged_overlay_status", None)
        if status == previous:
            return
        self._last_logged_overlay_status = status
        entry = self._LOGGED_OVERLAY_STATUSES.get(status)
        if entry is not None:
            self._log(entry[0], tag=entry[1])
            return
        if status == "live" and previous in self._LOGGED_OVERLAY_STATUSES:
            self._log("[+] OBS overlay: live game data recovered.", tag="success")

    def mark_overlay_read_failed(self, *, no_game: bool = False) -> None:
        self.live_run_tracker.mark_read_failed(no_game=no_game)
        self.update_overlay_state_from_tracker()

    def overlay_should_refresh_live_stats(self) -> bool:
        return bool(
            getattr(config, "OVERLAY", {}).get("enabled", False)
            or (getattr(self, "overlay_server", None) is not None and self.overlay_server.is_running)
        )

    def apply_overlay_autostart(self) -> None:
        if bool(config.OVERLAY.get("auto_start", False)):
            self.start_overlay_server()
        self.update_overlay_state_from_tracker()

    def close_overlay_server(self) -> None:
        server = getattr(self, "overlay_server", None)
        if server is not None:
            server.stop()

    def _overlay_widget_config_by_id(self) -> dict[str, dict[str, Any]]:
        widgets: dict[str, dict[str, Any]] = {}
        for widget in config.OVERLAY.get("widgets", []):
            if isinstance(widget, dict) and widget.get("id"):
                widgets[str(widget["id"])] = dict(widget)
        return widgets

    def _overlay_url_text(self) -> str:
        return f"http://127.0.0.1:{int(config.OVERLAY.get('port', 17845))}/overlay"

    def _overlay_visible_url_text(self) -> str:
        """The URL card 1 is currently offering to copy."""
        if self._overlay_source_mode() == self.SOURCE_MODE_SINGLE:
            return self._overlay_selected_widget_url_text()
        return self._overlay_url_text()

    def _overlay_selected_widget_url_text(self) -> str:
        widget_id = "stats"
        if getattr(self, "overlay_widget_url_combo", None) is not None:
            widget_id = str(self.overlay_widget_url_combo.currentData() or widget_id)
        return f"{self._overlay_url_text()}/{widget_id}"

    @staticmethod
    def _overlay_default_stat_labels() -> tuple[str, ...]:
        return ("Damage", "Attack Speed", "Luck", "XP Gain")

    @classmethod
    def _overlay_all_stat_labels(cls) -> tuple[str, ...]:
        return tuple(spec.label for group in PLAYER_STAT_GROUPS for spec in group)

    @classmethod
    def _overlay_selected_stat_labels(cls) -> tuple[str, ...]:
        widget_config = {}
        for widget in config.OVERLAY.get("widgets", []):
            if isinstance(widget, dict) and widget.get("id") == "stats":
                widget_config = widget
                break
        allowed = set(cls._overlay_all_stat_labels())
        selected = tuple(
            str(label)
            for label in widget_config.get("selected_stats", ())
            if str(label) in allowed
        )
        return selected or cls._overlay_default_stat_labels()

    @staticmethod
    def _overlay_default_kps_metric_ids() -> tuple[str, ...]:
        return tuple(metric_id for metric_id, _label in OVERLAY_KPS_METRIC_LABELS)

    @staticmethod
    def _overlay_all_kps_metric_labels() -> tuple[tuple[str, str], ...]:
        return OVERLAY_KPS_METRIC_LABELS

    @classmethod
    def _overlay_selected_kps_metric_ids(cls) -> tuple[str, ...]:
        widget_config = {}
        for widget in config.OVERLAY.get("widgets", []):
            if isinstance(widget, dict) and widget.get("id") == "kps":
                widget_config = widget
                break
        allowed = {metric_id for metric_id, _label in cls._overlay_all_kps_metric_labels()}
        selected = tuple(
            str(metric_id)
            for metric_id in widget_config.get("selected_kps_metrics", ())
            if str(metric_id) in allowed
        )
        return selected or cls._overlay_default_kps_metric_ids()


    def _effective_overlay_tracked_item_rules(self) -> tuple[TrackedItemRule, ...]:
        if uses_session_tracked_items(config.OVERLAY, default="custom"):
            return tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        return tracked_item_rules_from_config(config.OVERLAY)

    def _effective_overlay_config(self) -> dict[str, Any]:
        overlay = dict(config.OVERLAY)
        if uses_session_tracked_items(overlay, default="custom"):
            overlay["tracked_items"] = list(config.SESSION_TRACKED_ITEMS.get("tracked_items") or [])
        return overlay

    def _combined_tracked_item_rules(self) -> tuple[TrackedItemRule, ...]:
        return combined_tracked_item_rules()


def combined_tracked_item_rules() -> tuple[TrackedItemRule, ...]:
    combined: dict[str, TrackedItemRule] = {}
    for rule_config in (config.OVERLAY, config.SESSION_TRACKED_ITEMS, config.TWITCH_BOT):
        for rule in tracked_item_rules_from_config(rule_config):
            combined[rule.id] = rule
    return tuple(combined.values())


def build_overlay(app: Any, coordinator: AppCoordinator, session_stats: SessionStats) -> Overlay:
    """Wire the overlay to its measured owners without giving it the app."""
    return Overlay(
        coordinator,
        session_stats=session_stats,
        # Step 25c moved the Session Stats tab into `Scanner`, which builds it.
        # These two ports are why that move was possible without touching this
        # module's behaviour: they were already the only production readers of
        # the two widgets outside `gui_scanner`, so only the object they name
        # changed.
        stats_tab=lambda: app._scanner.tab_stats,
        set_tracked_item_rows=lambda rows: app._scanner.set_tracked_item_rows(rows),
        overlay_tab_active=lambda: app._is_overlay_tab_active(),
        server_rebuilt=lambda server: setattr(app, "overlay_server", server),
        log=lambda message, tag=None: app.log(message, tag=tag),
    )

