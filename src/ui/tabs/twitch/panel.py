"""The Twitch Bot tab: its widgets, and the only code that touches them.

Step 23b. `TwitchBotMixin` built ~240 lines of widgets onto the shared
`MegabonkApp` namespace and then read them back off `self` from twenty-odd
methods. This is the widget half of retiring it; `app.twitch_session` (23c) is
the behaviour half.

**Every twitch widget moves whole.** Measured before the move, exactly as steps
21c, 21d and 22c measured theirs: grepping the tree for all twenty-two
`twitch_*` widget names plus `tab_twitch` finds **no production reader outside
`gui_twitch.py`**. The single other mention anywhere was
`self.twitch_target_channel_entry = None` in `gui_app.__init__`, and that line
is gone with them. That measurement is what lets them become private fields
here rather than stay as app surface behind a port.

They also lose the `twitch_` prefix. It existed only to keep twenty-two names
apart inside one shared namespace; on an object that owns nothing else, it is
noise.

**This object decides nothing.** It reports what is on screen
(`read_settings`, `auto_connect_enabled`, `bonkhelp_enabled`, `bot_status_text`)
and renders what it is told (`show_connected`, `show_bot_status`, ...). Which
config keys those values land in, whether a token is valid, and when a worker
starts are `TwitchSession`'s -- so the two can be tested apart, and so the
formatting rules that used to be spread across four methods sit next to the
labels they format.

**Two phases, because the original had two.** `build()` runs from
`gui_layout.setup_ui`, where the tab used to be built; `bind()` runs from
`gui_app.__init__`, where `setup_twitch_bot_ui` used to connect the signals.
Keeping them apart preserves the original order -- widgets exist for a full
construction pass before any handler can fire -- rather than re-deriving it.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import config
from ui.shared import StartupSafeComboBox, _make_scroll_section
from ui.styles import _set_widget_style_role

_NOT_CONNECTED = "<span style='color: #f08b72; font-weight: bold;'>Not connected</span>"
_WAITING = "<span style='color: #ffd23f; font-weight: bold;'>Waiting for authorization...</span>"
_VALIDATING = "<span style='color: #ffd23f; font-weight: bold;'>Validating token...</span>"
_AUTH_FAILED = "<span style='color: #f08b72; font-weight: bold;'>Authorization failed</span>"

# The eleven command checkboxes, in grid order. `bonkhelp` is listed under the
# key it is stored as; the checkbox was named `commands` for years and the
# config still carries a legacy `commands` fallback, which `build` honours.
_COMMAND_KEYS = (
    "stats",
    "session",
    "bans",
    "items",
    "weapons",
    "tomes",
    "chaos",
    "stages",
    "powerups",
    "kps",
    "scanner",
    "chests",
    "luck",
    "presets",
    "bonkhelp",
    "disabled",
)

# Defaults as the mixin had them inline, per checkbox.
_COMMAND_DEFAULTS = {
    "chests": False,
    "luck": False,
    "presets": False,
    "disabled": False,
}


def command_checked(commands: dict, key: str) -> bool:
    """Whether a command checkbox starts checked.

    Module level and Qt-free so the `bonkhelp` fallback can be tested without
    building widgets -- `build()` needs real offscreen Qt, which the suite does
    not run (see `tests/support/templates_panel.py` for the same rule).
    """
    if key == "bonkhelp":
        # The checkbox was `commands` before it was `bonkhelp`; the fallback is
        # the mixin's, kept verbatim.
        return bool(commands.get("bonkhelp", commands.get("commands", True)))
    return bool(commands.get(key, _COMMAND_DEFAULTS.get(key, True)))


class TwitchTab:
    def __init__(self) -> None:
        self._tab = None
        self._auth_status_label = None
        self._auth_buttons_layout = None
        self._connect_btn = None
        self._disconnect_btn = None
        self._target_channel_entry = None
        self._bot_status_label = None
        self._auto_connect_cb = None
        self._bot_toggle_btn = None
        self._tier_combo = None
        self._global_cooldown_spin = None
        self._cooldown_spin = None
        self._command_settings_btn = None
        self._stage_announcements_cb = None
        self._commands_announcements_cb = None
        self._command_cbs: dict[str, QCheckBox] = {}

    # -- construction -----------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self._tab

    def build(self) -> QWidget:
        self._tab = QWidget()
        tab_layout = QVBoxLayout(self._tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        twitch_scroll, _twitch_content, twitch_layout = _make_scroll_section()
        twitch_layout.setSpacing(10)
        tab_layout.addWidget(twitch_scroll)

        # Create a horizontal layout inside the scrollable content for two columns
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(16)
        columns_layout.setContentsMargins(8, 8, 8, 8)
        twitch_layout.addLayout(columns_layout)

        # Left column layout (Connection, Bot Control & Settings)
        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        left_col.setContentsMargins(0, 0, 0, 0)
        columns_layout.addLayout(left_col, stretch=1)

        # Right column layout (Commands Configuration)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)
        right_col.setContentsMargins(0, 0, 0, 0)
        columns_layout.addLayout(right_col, stretch=2)

        self._build_auth_card(left_col)
        self._build_control_card(left_col)
        self._build_settings_card(left_col)
        left_col.addStretch(1)

        self._build_commands_card(right_col)
        right_col.addStretch(1)

        twitch_layout.addStretch(1)
        return self._tab

    def _build_auth_card(self, left_col) -> None:
        auth_group = QGroupBox("Twitch Account")
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setContentsMargins(16, 12, 16, 12)
        auth_layout.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(QLabel("Account Status:"))
        self._auth_status_label = QLabel(_NOT_CONNECTED)
        self._auth_status_label.setTextFormat(Qt.RichText)
        status_row.addWidget(self._auth_status_label)
        status_row.addStretch(1)
        auth_layout.addLayout(status_row)

        self._auth_buttons_layout = QHBoxLayout()
        self._auth_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._connect_btn = QPushButton("Connect to Twitch")
        self._connect_btn.setObjectName("primary")
        self._auth_buttons_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("danger")
        self._disconnect_btn.setVisible(False)
        self._auth_buttons_layout.addWidget(self._disconnect_btn)
        auth_layout.addLayout(self._auth_buttons_layout)

        # Target Channel input field under connection
        target_layout = QFormLayout()
        target_layout.setContentsMargins(0, 4, 0, 0)
        self._target_channel_entry = QLineEdit()
        self._target_channel_entry.setPlaceholderText(
            config.TWITCH_BOT.get("username") or "Authorized account"
        )
        self._target_channel_entry.setText(config.TWITCH_BOT.get("target_channel", ""))
        target_layout.addRow("Target Channel:", self._target_channel_entry)
        auth_layout.addLayout(target_layout)

        left_col.addWidget(auth_group)

    def _build_control_card(self, left_col) -> None:
        control_group = QGroupBox("Bot Control")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(16, 12, 16, 12)
        control_layout.setSpacing(10)

        bot_status_row = QHBoxLayout()
        bot_status_row.setContentsMargins(0, 0, 0, 0)
        bot_status_row.addWidget(QLabel("Bot Status:"))
        # Single-quoted attributes, matching the mixin byte for byte. The
        # *rendered* status below uses double quotes and always did; the
        # initial label did not. The differential trace caught the difference.
        self._bot_status_label = QLabel(
            "<span style='color: #f08b72; font-weight: bold;'>Stopped</span>"
        )
        self._bot_status_label.setTextFormat(Qt.RichText)
        self._bot_status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        bot_status_row.addWidget(self._bot_status_label)
        bot_status_row.addStretch(1)
        control_layout.addLayout(bot_status_row)

        self._auto_connect_cb = QCheckBox("Auto-connect")
        self._auto_connect_cb.setChecked(config.TWITCH_BOT.get("auto_connect", False))
        self._auto_connect_cb.setToolTip(
            "Start the bot automatically after Twitch authorization and when the application starts."
        )
        control_layout.addWidget(self._auto_connect_cb)

        self._bot_toggle_btn = QPushButton("Start Bot")
        self._bot_toggle_btn.setObjectName("primary")
        self._bot_toggle_btn.setMinimumHeight(36)
        btn_font = self._bot_toggle_btn.font()
        btn_font.setBold(True)
        self._bot_toggle_btn.setFont(btn_font)
        control_layout.addWidget(self._bot_toggle_btn)

        left_col.addWidget(control_group)

    def _build_settings_card(self, left_col) -> None:
        settings_group = QGroupBox("Bot Settings")
        settings_main_layout = QVBoxLayout(settings_group)
        settings_main_layout.setContentsMargins(16, 12, 16, 12)
        settings_main_layout.setSpacing(10)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)

        self._tier_combo = StartupSafeComboBox()
        self._tier_combo.addItems(["Everyone", "Mods & VIPs", "Subs & Mods"])
        self._tier_combo.setCurrentText(config.TWITCH_BOT.get("access_tier", "Everyone"))
        form_layout.addRow("Access Tier:", self._tier_combo)

        self._global_cooldown_spin = QSpinBox()
        self._global_cooldown_spin.setRange(0, 600)
        self._global_cooldown_spin.setValue(config.TWITCH_BOT.get("global_cooldown_seconds", 1))
        self._global_cooldown_spin.setSuffix(" sec")
        form_layout.addRow("Global Cooldown:", self._global_cooldown_spin)

        self._cooldown_spin = QSpinBox()
        self._cooldown_spin.setRange(0, 600)
        self._cooldown_spin.setValue(config.TWITCH_BOT.get("cooldown_seconds", 5))
        self._cooldown_spin.setSuffix(" sec")
        form_layout.addRow("Command Cooldown:", self._cooldown_spin)

        settings_main_layout.addLayout(form_layout)
        left_col.addWidget(settings_group)

    def _build_commands_card(self, right_col) -> None:
        commands_group = QGroupBox("Command Configuration")
        commands_main_layout = QVBoxLayout(commands_group)
        commands_main_layout.setContentsMargins(16, 12, 16, 12)
        commands_main_layout.setSpacing(10)

        commands_header_layout = QHBoxLayout()
        commands_header_layout.setContentsMargins(4, 0, 0, 0)
        commands_header_lbl = QLabel("Active Chat Commands:")
        commands_header_lbl.setStyleSheet("font-weight: bold; background: transparent;")
        self._command_settings_btn = QPushButton("Command Settings")
        commands_header_layout.addWidget(commands_header_lbl)
        commands_header_layout.addStretch(1)
        commands_header_layout.addWidget(self._command_settings_btn)
        commands_main_layout.addLayout(commands_header_layout)

        commands = config.TWITCH_BOT.get("commands", {})
        for key in _COMMAND_KEYS:
            checkbox = QCheckBox(f"!{key}")
            checkbox.setChecked(command_checked(commands, key))
            self._command_cbs[key] = checkbox

        commands_grid = QGridLayout()
        commands_grid.setVerticalSpacing(14)
        commands_grid.setHorizontalSpacing(12)
        commands_grid.setContentsMargins(4, 0, 0, 0)
        for index, key in enumerate(_COMMAND_KEYS):
            commands_grid.addWidget(self._command_cbs[key], index // 3, index % 3)
        commands_main_layout.addLayout(commands_grid)

        # Separator line before Announcements (with larger vertical margins)
        commands_divider = QFrame()
        commands_divider.setFrameShape(QFrame.HLine)
        commands_divider.setFrameShadow(QFrame.Sunken)
        commands_divider.setStyleSheet(
            "background-color: #2B3648; max-height: 1px; margin: 14px 4px;"
        )
        commands_main_layout.addWidget(commands_divider)

        # Announcements layout with left margin to match the checkboxes grid
        ann_layout = QVBoxLayout()
        ann_layout.setContentsMargins(4, 0, 0, 0)
        ann_layout.setSpacing(6)

        ann_title = QLabel("Announcements:")
        ann_title.setStyleSheet(
            "font-weight: bold; margin-top: 6px; margin-bottom: 4px; background: transparent;"
        )
        ann_layout.addWidget(ann_title)

        self._stage_announcements_cb = QCheckBox("Announce Stage Transitions")
        self._stage_announcements_cb.setChecked(
            config.TWITCH_BOT.get("stage_announcements", True)
        )
        ann_layout.addWidget(self._stage_announcements_cb)

        self._commands_announcements_cb = QCheckBox("Periodically announce available commands")
        self._commands_announcements_cb.setChecked(
            config.TWITCH_BOT.get("commands_announcements", False)
        )
        ann_layout.addWidget(self._commands_announcements_cb)

        commands_main_layout.addLayout(ann_layout)
        right_col.addWidget(commands_group)

    # -- wiring -----------------------------------------------------------

    def bind(
        self,
        *,
        on_connect: Callable[[], None],
        on_disconnect: Callable[[], None],
        on_toggle_bot: Callable[[], None],
        on_auto_connect_changed: Callable[..., None],
        on_command_settings: Callable[[], None],
        on_settings_changed: Callable[..., None],
        on_bonkhelp_toggled: Callable[..., None],
    ) -> None:
        """Connect the widgets to the session, in the mixin's original order."""
        self._connect_btn.clicked.connect(on_connect)
        self._bot_toggle_btn.clicked.connect(on_toggle_bot)
        self._auto_connect_cb.stateChanged.connect(on_auto_connect_changed)
        self._command_settings_btn.clicked.connect(on_command_settings)
        self._disconnect_btn.clicked.connect(on_disconnect)

        self._tier_combo.currentTextChanged.connect(on_settings_changed)
        self._target_channel_entry.editingFinished.connect(on_settings_changed)
        self._global_cooldown_spin.valueChanged.connect(on_settings_changed)
        self._cooldown_spin.valueChanged.connect(on_settings_changed)
        for key, checkbox in self._command_cbs.items():
            # `bonkhelp` is the one command checkbox with its own handler: it
            # raises the alias dialog before saving.
            if key == "bonkhelp":
                checkbox.stateChanged.connect(on_bonkhelp_toggled)
            else:
                checkbox.stateChanged.connect(on_settings_changed)
        self._stage_announcements_cb.stateChanged.connect(on_settings_changed)
        self._commands_announcements_cb.stateChanged.connect(on_settings_changed)

    # -- reporting what is on screen --------------------------------------

    def read_settings(self) -> dict:
        """What the settings widgets currently say, as plain data.

        Where it lands in `config` is `TwitchSession.save_settings`'s decision,
        not this object's.
        """
        return {
            "access_tier": self._tier_combo.currentText(),
            "target_channel": self._target_channel_entry.text().strip().lstrip("#").lower(),
            "global_cooldown_seconds": self._global_cooldown_spin.value(),
            "cooldown_seconds": self._cooldown_spin.value(),
            "stage_announcements": self._stage_announcements_cb.isChecked(),
            "commands_announcements": self._commands_announcements_cb.isChecked(),
            "commands": {key: cb.isChecked() for key, cb in self._command_cbs.items()},
        }

    def auto_connect_enabled(self) -> bool:
        return self._auto_connect_cb.isChecked()

    def bonkhelp_enabled(self) -> bool:
        return self._command_cbs["bonkhelp"].isChecked()

    def bot_status_text(self) -> str:
        return self._bot_status_label.text()

    # -- rendering what it is told ----------------------------------------

    def show_connected(self, username: str) -> None:
        self._auth_status_label.setText(
            f"Connected as <span style='color: #4fd67a; font-weight: bold;'>{username}</span>"
        )
        self._connect_btn.setVisible(False)
        self._disconnect_btn.setVisible(True)
        if self._target_channel_entry is not None:
            self._target_channel_entry.setPlaceholderText(username)

    def show_disconnected(self) -> None:
        self._auth_status_label.setText(_NOT_CONNECTED)
        self._connect_btn.setVisible(True)
        self._disconnect_btn.setVisible(False)

    def show_authorizing(self) -> None:
        self._connect_btn.setEnabled(False)
        self._auth_status_label.setText(_WAITING)

    def show_validating(self) -> None:
        self._auth_status_label.setText(_VALIDATING)

    def show_auth_failed(self) -> None:
        self._connect_btn.setEnabled(True)
        self._auth_status_label.setText(_AUTH_FAILED)

    def enable_connect(self) -> None:
        self._connect_btn.setEnabled(True)

    def show_bot_status(self, status: str) -> None:
        status_lower = status.lower()
        if "error" in status_lower:
            formatted = f'<span style="color: #f08b72; font-weight: bold;">{status}</span>'
        elif "connected" in status_lower:
            formatted = f'<span style="color: #4fd67a; font-weight: bold;">{status}</span>'
        elif "connecting" in status_lower:
            formatted = f'<span style="color: #ffd23f; font-weight: bold;">{status}</span>'
        elif "stopped" in status_lower:
            formatted = '<span style="color: #f08b72; font-weight: bold;">Stopped</span>'
        else:
            formatted = f'<span style="color: #A0B0C5; font-weight: bold;">{status}</span>'
        self._bot_status_label.setText(formatted)

    def show_bot_running(self) -> None:
        self._bot_toggle_btn.setText("Stop Bot")
        _set_widget_style_role(self._bot_toggle_btn, "stopScanner")

    def show_bot_stopped(self) -> None:
        self._bot_toggle_btn.setText("Start Bot")
        _set_widget_style_role(self._bot_toggle_btn, "primary")
