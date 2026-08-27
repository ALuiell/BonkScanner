from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from ui.canvas_preview import CanvasPreview, PreviewWidget
from ui.dialogs.tracked_items import TrackedItemsDialog
from ui.dialogs.build_progression import BuildProgressionManagerDialog
from ui.module_tile import ModuleTile
from ui.run_toggle import OVERLAY_SERVER_CAPTIONS
from ui.segmented_toggle import ROLE_GO, SegmentedToggle
from ui.settings_card import OBS_RAIL_WIDTH, SettingsCard, build_workspace
from ui.shared import (
    SCANNER_REMINDER_LABEL,
    CollapsibleSection,
    CollapsibleSectionGroup,
    _make_scroll_section,
    _set_text_input,
)
from ui.styles import _set_widget_style_role
from ui.tab_hero import STATE_DANGER, STATE_OFF, STATE_OK, STATE_WARN, TabHero
from projections.tracked_items import uses_session_tracked_items
from core.tracker.live_run import TrackedItemRule
from app.coordinator import AppCoordinator
from app.tracked_item_settings import TrackedItemSettings, combine_rules
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
    "build_progression": "Build Progression",
}

#: How wide the URL row's field and the widget picker beside it may get. The
#: longest URL this field ever holds is the single-widget one -- about 55
#: characters -- and it reads at this width with room over. The cards run the
#: full width of the tab now, so without a cap here the field would follow them
#: and hold a 55-character URL in 1300px.
_URL_MAX_WIDTH = 560

#: What the styled field spends on itself before any text: `padding: 6px 8px`
#: and a 1px border on each side, plus room for the caret. Stated rather than
#: measured because Qt does not report stylesheet padding back -- `contentsMargins`
#: and `width() - contentsRect().width()` both return zero on these fields.
_URL_FIELD_CHROME = 20

#: The width of the whole URL row -- its label, the capped field and the Copy
#: button. The mode picker above it is held to this so the two line up.
_SOURCE_ROW_MAX_WIDTH = 690

def _fit_url_field(field) -> None:
    """Ask for the width this URL actually needs, up to the cap.

    The field is read-only and exists to be copied, which is exactly why it
    still has to be *readable*: scrolled to `...:17845/overlay`, a source
    pointed at the wrong port looks identical to a right one, and the only way
    to check is to select the text and drag. Without a minimum the row's
    trailing stretch takes half of every pixel the card has spare, and in a
    1100px window the field came out at 154px against a URL needing 287.

    Recomputed on every refresh because the text changes: the widget URLs are
    up to 14 characters longer than the full-overlay one, and a minimum left
    over from the shorter mode would be the same bug one size down.

    `_URL_MAX_WIDTH` still caps it. The longest URL the app can produce needs
    roughly half of that, so the cap is not what decides the width here -- it
    is the backstop for a hostname this code does not currently generate.
    """
    needed = field.fontMetrics().horizontalAdvance(field.text()) + _URL_FIELD_CHROME
    field.setMinimumWidth(min(_URL_MAX_WIDTH, needed))


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
        marshal_to_ui: Callable[[Callable[[], None]], bool] | None = None,
        log: Callable[..., None] | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.session_stats = session_stats
        self._stats_tab = stats_tab
        self._set_tracked_item_rows = set_tracked_item_rows
        self._overlay_tab_active = overlay_tab_active
        self._server_rebuilt = server_rebuilt
        self._marshal_to_ui = marshal_to_ui or self._run_ui_callback_now
        self._overlay_ui_refresh_lock = threading.Lock()
        self._overlay_ui_refresh_pending = False
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

        self.overlay_state_store.set_state(
            build_overlay_state(
                self.live_run_tracker,
                self._effective_overlay_config(),
                self._build_progression_snapshot(),
            )
        )

    @staticmethod
    def _run_ui_callback_now(callback: Callable[[], None]) -> bool:
        callback()
        return True

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
        """Copy `text`, and say so on the button for a second and a half.

        The button is not disabled while it says so. Disabling the widget the
        user has just clicked makes Qt hand the focus to the next one in the tab
        order, which here is the Port field -- and a `QLineEdit` selects its
        contents when it gains focus, so pressing Copy looked like it had opened
        the port for editing. Nothing needed the button off: copying the same
        URL twice is the same copy.

        A second press inside the window is therefore possible, and is ignored
        rather than stacked. Two overlapping restores would read the caption
        while it said "Copied!" and put that back as the permanent one.
        """
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QTimer

        QGuiApplication.clipboard().setText(text)
        if getattr(button, "_copy_feedback_pending", False):
            return
        button._copy_feedback_pending = True

        original_text = button.text()
        original_role = button.objectName()
        button.setText("Copied!")
        # The role the redesign already carries for this colour, instead of the
        # inline `#2F9E6D` that used to be set here -- and instead of the inline
        # padding rule the old restore left behind for good, which took the
        # button out of the stylesheet after the first copy.
        _set_widget_style_role(button, "SuccessButton")

        def restore():
            button.setText(original_text)
            _set_widget_style_role(button, original_role)
            button._copy_feedback_pending = False

        # Tie the delayed callback to the button's QObject lifetime. Closing
        # the tab or application during the feedback window must cancel the
        # callback instead of invoking Python against a deleted C++ widget.
        QTimer.singleShot(1500, button, restore)

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

        build_group = QGroupBox("Build Progression")
        build_layout = QVBoxLayout(build_group)
        build_layout.addWidget(QLabel("The same build definition is shared with Live Stats, in-game overlay, and Twitch."))
        configure_build = QPushButton("Configure Build Progression…")
        configure_build.clicked.connect(self.open_build_progression_dialog)
        build_layout.addWidget(configure_build)
        build_cfg = self._overlay_widget_config_by_id().get("build_progression", {})
        self.overlay_build_bg_checkbox = QCheckBox("Show background")
        self.overlay_build_bg_checkbox.setChecked(
            float(build_cfg.get("background_opacity", 0)) > 0
        )
        self.overlay_build_bg_checkbox.stateChanged.connect(
            lambda _state: self.save_overlay_settings_from_ui()
        )
        build_layout.addWidget(self.overlay_build_bg_checkbox)

        self.overlay_build_header_checkbox = QCheckBox("Show header")
        self.overlay_build_header_checkbox.setChecked(
            bool(build_cfg.get("show_header", False))
        )
        self.overlay_build_header_checkbox.stateChanged.connect(
            lambda _state: self.save_overlay_settings_from_ui()
        )
        build_layout.addWidget(self.overlay_build_header_checkbox)

        self.overlay_build_completed_checkbox = QCheckBox("Show completed rows")
        self.overlay_build_completed_checkbox.setChecked(bool(build_cfg.get("show_completed", False)))
        self.overlay_build_max_rows_spin = QSpinBox()
        self.overlay_build_max_rows_spin.setRange(1, 20)
        self.overlay_build_max_rows_spin.setValue(int(build_cfg.get("max_rows", 6)))
        self.overlay_build_completed_checkbox.stateChanged.connect(
            lambda _state: self.save_overlay_settings_from_ui()
        )
        build_layout.addWidget(self.overlay_build_completed_checkbox)
        self.overlay_build_max_rows_spin.valueChanged.connect(lambda _value: self.save_overlay_settings_from_ui())
        rows_line = QHBoxLayout()
        rows_line.addWidget(QLabel("Maximum non-completed rows"))
        rows_line.addWidget(self.overlay_build_max_rows_spin)
        rows_line.addStretch(1)
        build_layout.addLayout(rows_line)
        advanced_layout.addWidget(build_group)

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

        advanced_layout.addStretch(1)
        self.overlay_advanced_sections_group = CollapsibleSectionGroup((stats_group,))

        settings_tabs.addTab(basic_tab, "Basic")
        settings_tabs.addTab(advanced_tab, "Advanced")

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Done")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dialog_layout.addLayout(close_row)

        dialog.setUpdatesEnabled(True)
        try:
            dialog.exec()
        finally:
            self._clear_overlay_widget_settings_dialog_refs()
            # The tab is the dialog's parent, so closing a modal window does
            # not destroy it. Dispose it explicitly instead of retaining one
            # hidden QDialog per visit until the whole application closes.
            dialog.deleteLater()

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
        # These controls live inside the modal Widget Settings dialog. Qt has
        # already destroyed them when the dialog closes, so retaining their
        # Python wrappers makes the next server start raise ``Internal C++
        # object ... already deleted`` while it saves the current settings.
        self.overlay_build_bg_checkbox = None
        self.overlay_build_header_checkbox = None
        self.overlay_build_completed_checkbox = None
        self.overlay_build_max_rows_spin = None
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

    def toggle_overlay_server(self) -> None:
        server = getattr(self, "overlay_server", None)
        should_start = not bool(server is not None and server.is_running)
        enabled = False
        try:
            if should_start:
                enabled = self.start_overlay_server()
            else:
                self.stop_overlay_server()
        except Exception as exc:
            # This is a Qt slot. No server/config cleanup failure should escape
            # into Qt's event dispatcher and become a process-level crash.
            self._log(f"[-] OBS overlay server transition failed: {exc}", tag="error")
        finally:
            config.OVERLAY["enabled"] = bool(enabled)
            config.user_config["OVERLAY"] = config.OVERLAY
            try:
                config.save_config(config.user_config)
            except Exception as exc:
                self._log(f"[-] Could not save OBS overlay state: {exc}", tag="error")
            self.refresh_overlay_ui()

    def start_overlay_server(self) -> bool:
        try:
            self.save_overlay_settings_from_ui(persist=False)
            if self.overlay_server.is_running:
                return True
            self.overlay_server = self.coordinator.rebuild_overlay_server(
                host="127.0.0.1",
                port=int(config.OVERLAY.get("port", 17845)),
            )
            self._server_rebuilt(self.overlay_server)
            self.overlay_server.start()
        except Exception as exc:
            server = getattr(self, "overlay_server", None)
            if server is not None and not getattr(server, "last_error", None):
                try:
                    server.last_error = str(exc)
                except Exception:
                    pass
            self._log(f"[-] Could not start OBS overlay server: {exc}", tag="error")
            self.refresh_overlay_ui()
            return False
        self.refresh_overlay_ui()
        return True

    def stop_overlay_server(self) -> None:
        try:
            self.overlay_server.stop()
        except Exception as exc:
            self._log(f"[-] Could not stop OBS overlay server cleanly: {exc}", tag="error")
        finally:
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
                if widget_id == "build_progression":
                    widget = dict(widget)
                    if getattr(self, "overlay_build_bg_checkbox", None) is not None:
                        widget["background_opacity"] = (
                            0.4 if self.overlay_build_bg_checkbox.isChecked() else 0.0
                        )
                    if getattr(self, "overlay_build_header_checkbox", None) is not None:
                        widget["show_header"] = bool(
                            self.overlay_build_header_checkbox.isChecked()
                        )
                    if getattr(self, "overlay_build_completed_checkbox", None) is not None:
                        widget["show_completed"] = self.overlay_build_completed_checkbox.isChecked()
                    if getattr(self, "overlay_build_max_rows_spin", None) is not None:
                        widget["max_rows"] = self.overlay_build_max_rows_spin.value()
                    widget.pop("mode", None)
                widgets.append(widget)
            overlay["widgets"] = widgets
            # `tracked_items` and `tracked_items_source` need no branch here:
            # `overlay` starts as a normalized copy of `config.OVERLAY`, so both
            # carry through untouched. The two branches that used to write them
            # existed because widgets in this dialog could change them; the one
            # tracked-item window writes them itself now, through
            # `TrackedItemSettings`.
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
            _fit_url_field(self.overlay_url_entry)
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

    def open_build_progression_dialog(self) -> None:
        dialog = BuildProgressionManagerDialog(
            self.coordinator.build_progression_settings,
            self.coordinator.build_progression_service,
            self.tab_overlay,
        )
        dialog.exec()
        if dialog.changed:
            self.update_overlay_state_from_tracker()

    def _build_progression_snapshot(self):
        service = getattr(self.coordinator, "build_progression_service", None)
        reader = getattr(service, "snapshot", None)
        return reader() if callable(reader) else None

    def open_session_tracked_item_settings_dialog(self) -> None:
        """The one tracked-item window, opened on the Session Stats list.

        Named for the gear that opens it. It is not a Session-only window any
        more: OBS and `!session` are two more targets inside it, which is what
        let their two copies in the widget and command dialogs be deleted.

        What stays here is the wiring, not the screen: this component holds the
        tracker and the two refresh ports `TrackedItemSettings` needs.
        """
        dialog = TrackedItemsDialog(
            self._tracked_item_settings(),
            target_key="session",
            parent=self.tab_stats,
        )
        try:
            dialog.exec()
        finally:
            try:
                self.refresh_session_tracked_item_stats_ui()
            finally:
                dialog.deleteLater()

    def _tracked_item_settings(self) -> TrackedItemSettings:
        return TrackedItemSettings(
            tracker=lambda: self.live_run_tracker,
            combined_rules=combined_tracked_item_rules,
            refresh_session_rows=self.refresh_session_tracked_item_stats_ui,
            refresh_snapshot=self.session_stats.refresh_snapshot,
        )

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

    def update_overlay_state_from_tracker(self) -> None:
        if self.overlay_state_store is None:
            return
        state = build_overlay_state(
            self.live_run_tracker,
            self._effective_overlay_config(),
            self._build_progression_snapshot(),
        )
        self._log_overlay_status_transition(str(state.get("status") or ""))
        self.overlay_state_store.set_state(state)
        self._request_overlay_ui_refresh()

    def _request_overlay_ui_refresh(self) -> None:
        """Coalesce and marshal the only Qt part of state publication.

        Tracker publication is intentionally callable from non-GUI services
        (including Twitch commands). The state store is thread-safe; the tab,
        hero and line edits are not. Always pass that final repaint through the
        application's guarded UI invoker so a worker cannot touch Qt directly.
        """
        if getattr(self, "tab_overlay", None) is None:
            return
        with self._overlay_ui_refresh_lock:
            if self._overlay_ui_refresh_pending:
                return
            self._overlay_ui_refresh_pending = True

        def refresh_if_alive() -> None:
            try:
                if getattr(self, "tab_overlay", None) is None:
                    return
                tab_active = getattr(self, "_is_overlay_tab_active", lambda: True)
                if tab_active():
                    self.refresh_overlay_ui()
            except Exception as exc:
                # This body is executed as a queued Qt callback. A tab deleted
                # during shutdown, or any other late UI failure, must end here
                # instead of escaping through Qt's event dispatcher.
                self._log(f"[-] Could not refresh OBS overlay controls: {exc}", tag="error")
            finally:
                with self._overlay_ui_refresh_lock:
                    self._overlay_ui_refresh_pending = False

        try:
            accepted = self._marshal_to_ui(refresh_if_alive)
        except Exception:
            accepted = False
        if accepted is False:
            with self._overlay_ui_refresh_lock:
                self._overlay_ui_refresh_pending = False

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
    """Every tracked-item rule the three surfaces ask for, as tracker rules.

    Which lists exist and how they combine is `app.tracked_item_settings`'s;
    turning a config entry into a `TrackedItemRule` is the top-level
    `tracked_item_rules` adapter's, and nothing under `app/` may import it. So
    the combining is called from here, where both are legal to reach -- which
    is also where `gui_app` has always imported this from.
    """
    return combine_rules(tracked_item_rules_from_config)


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
        marshal_to_ui=lambda callback: app.marshal_to_ui(callback),
        log=lambda message, tag=None: app.log(message, tag=tag),
    )

