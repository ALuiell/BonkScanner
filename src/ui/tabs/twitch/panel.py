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
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import config
from ui.module_tile import ModuleTile
from ui.run_toggle import TWITCH_BOT_CAPTIONS
from ui.settings_card import SettingsCard
from ui.shared import _make_scroll_section
from ui.styles import _set_widget_style_role
from ui.tab_hero import STATE_DANGER, STATE_OFF, STATE_OK, STATE_WARN, TabHero

# The four authorization strings that used to be inline-styled HTML in a label
# are gone: those states are badge captions now, and their colours come from the
# stylesheet through the badge's `state` property rather than from spans written
# here. `Waiting for authorization...` was the reason the merge was worth doing
# -- it never had a chance of fitting the suffix the mock offered it.

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
        self._hero = None
        self._account_entry = None
        self._account_suffix = None
        self._connect_btn = None
        self._disconnect_btn = None
        self._target_channel_entry = None
        self._auto_connect_cb = None
        self._bot_toggle_btn = None
        self._tier_combo = None
        self._global_cooldown_spin = None
        self._cooldown_spin = None
        self._command_settings_btn = None
        self._stage_announcements_cb = None
        self._commands_announcements_cb = None
        self._command_cbs: dict[str, ModuleTile] = {}
        self._chat_preview = None

        # The bot's status as a *string*, kept apart from whatever the badge is
        # currently rendering. `TwitchSession.on_bot_finished` decides whether to
        # write "Stopped" by reading this back and looking for "error" in it --
        # if it were the merged badge's text, a disconnect could make that check
        # read the account's state and overwrite a real error message.
        self._bot_status = "Stopped"
        # Which half of the lifecycle owns the badge. Authorization and the bot
        # are sequential, not concurrent -- `start_bot` refuses without a token
        # and the Connect button hides once connected -- so one badge carries
        # both, and this says which end of it is live.
        self._authorized = False
        self._auth_badge = ("NOT CONNECTED", STATE_OFF)
        self._bot_badge = ("STOPPED", STATE_OFF)
        self._badge_detail = ""

    # -- construction -----------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self._tab

    def build(self) -> QWidget:
        self._tab = QWidget()
        tab_layout = QVBoxLayout(self._tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)

        twitch_scroll, _twitch_content, twitch_layout = _make_scroll_section()
        twitch_layout.setSpacing(12)
        twitch_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.addWidget(twitch_scroll)

        twitch_layout.addWidget(self._build_hero())

        workspace = QHBoxLayout()
        workspace.setSpacing(12)
        twitch_layout.addLayout(workspace)

        main_column = QVBoxLayout()
        main_column.setSpacing(12)
        workspace.addLayout(main_column, 1)

        side_column = QVBoxLayout()
        side_column.setSpacing(12)
        workspace.addLayout(side_column, 0)

        self._build_account_card(main_column)
        self._build_commands_card(main_column)
        self._build_announcements_card(main_column)
        main_column.addStretch(1)

        self._build_preview_card(side_column)
        side_column.addStretch(1)

        twitch_layout.addStretch(1)
        self._render_badge()
        return self._tab

    def _build_hero(self):
        self._hero = TabHero(
            title="Twitch Bot",
            subtitle="Answer chat commands and announce important run events.",
            icon_path="media/twitch_icon.svg",
            auto_text="Auto-connect bot",
            run_captions=TWITCH_BOT_CAPTIONS,
        )
        self._auto_connect_cb = self._hero.auto_switch
        self._auto_connect_cb.setChecked(config.TWITCH_BOT.get("auto_connect", False))
        self._auto_connect_cb.setToolTip(
            "Start the bot automatically after Twitch authorization and when the application starts."
        )
        self._bot_toggle_btn = self._hero.run_toggle
        return self._hero

    def _build_account_card(self, column) -> None:
        # Still a pair with swapped visibility rather than one caption-swapping
        # button: the two are not halves of a toggle -- one authorizes and the
        # other revokes -- and a button that renames itself is the shape the run
        # toggle was built to retire.
        self._connect_btn = QPushButton("Connect to Twitch")
        self._connect_btn.setObjectName("primary")
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("danger")
        self._disconnect_btn.setVisible(False)

        auth_buttons = QWidget()
        auth_row = QHBoxLayout(auth_buttons)
        auth_row.setContentsMargins(0, 0, 0, 0)
        auth_row.setSpacing(6)
        auth_row.addWidget(self._connect_btn)
        auth_row.addWidget(self._disconnect_btn)

        card = SettingsCard(
            number=1,
            title="Account & channel",
            subtitle="Authorization first; where the messages go sits beside it.",
        )
        card.findChild(QFrame, "settingsCardHead").layout().addWidget(
            auth_buttons, 0, Qt.AlignVCenter
        )

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        account_row = QWidget()
        account_layout = QHBoxLayout(account_row)
        account_layout.setContentsMargins(0, 0, 0, 0)
        account_layout.setSpacing(8)
        self._account_entry = QLineEdit()
        self._account_entry.setReadOnly(True)
        self._account_entry.setPlaceholderText("Not authorized")
        self._account_entry.setText(str(config.TWITCH_BOT.get("username") or ""))
        account_layout.addWidget(self._account_entry, 1)
        # One word, because the four long authorization states now live in the
        # hero badge where a lifecycle belongs. This says only whether there is
        # a usable token.
        self._account_suffix = QLabel("")
        self._account_suffix.setObjectName("fieldSuffix")
        account_layout.addWidget(self._account_suffix)
        form.addRow("Twitch account:", account_row)

        self._target_channel_entry = QLineEdit()
        self._target_channel_entry.setPlaceholderText(
            config.TWITCH_BOT.get("username") or "Authorized account"
        )
        self._target_channel_entry.setText(config.TWITCH_BOT.get("target_channel", ""))
        form.addRow("Target channel:", self._target_channel_entry)

        self._tier_combo = QComboBox()
        self._tier_combo.addItems(["Everyone", "Mods & VIPs", "Subs & Mods"])
        self._tier_combo.setCurrentText(config.TWITCH_BOT.get("access_tier", "Everyone"))
        form.addRow("Access tier:", self._tier_combo)

        cooldown_row = QWidget()
        cooldown_layout = QHBoxLayout(cooldown_row)
        cooldown_layout.setContentsMargins(0, 0, 0, 0)
        cooldown_layout.setSpacing(8)
        self._global_cooldown_spin = QSpinBox()
        self._global_cooldown_spin.setRange(0, 600)
        self._global_cooldown_spin.setValue(config.TWITCH_BOT.get("global_cooldown_seconds", 1))
        self._global_cooldown_spin.setSuffix(" sec")
        cooldown_layout.addWidget(self._global_cooldown_spin)
        cooldown_layout.addWidget(QLabel("global"))
        self._cooldown_spin = QSpinBox()
        self._cooldown_spin.setRange(0, 600)
        self._cooldown_spin.setValue(config.TWITCH_BOT.get("cooldown_seconds", 5))
        self._cooldown_spin.setSuffix(" sec")
        cooldown_layout.addWidget(self._cooldown_spin)
        cooldown_layout.addWidget(QLabel("per command"))
        cooldown_layout.addStretch(1)
        form.addRow("Cooldowns:", cooldown_row)

        card.body.addLayout(form)
        column.addWidget(card)

    def _build_commands_card(self, column) -> None:
        self._command_settings_btn = QPushButton("Command Settings")
        card = SettingsCard(
            number=2,
            title="Chat commands",
            subtitle="Aliases and message templates open separately.",
            action=self._command_settings_btn,
        )

        commands = config.TWITCH_BOT.get("commands", {})
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        for index, key in enumerate(_COMMAND_KEYS):
            tile = ModuleTile(f"!{key}")
            tile.setChecked(command_checked(commands, key))
            self._command_cbs[key] = tile
            grid.addWidget(tile, index // 3, index % 3)
        card.body.addLayout(grid)

        column.addWidget(card)

    def _build_announcements_card(self, column) -> None:
        card = SettingsCard(
            number=3,
            title="Announcements",
            subtitle="Bot messages that happen without a viewer asking.",
        )

        self._stage_announcements_cb = QCheckBox("Announce stage transitions")
        self._stage_announcements_cb.setChecked(
            config.TWITCH_BOT.get("stage_announcements", True)
        )
        card.body.addWidget(self._stage_announcements_cb)

        self._commands_announcements_cb = QCheckBox("Periodically announce available commands")
        self._commands_announcements_cb.setChecked(
            config.TWITCH_BOT.get("commands_announcements", False)
        )
        card.body.addWidget(self._commands_announcements_cb)

        column.addWidget(card)

    def _build_preview_card(self, column) -> None:
        card = SettingsCard(
            number=None,
            title="Chat preview",
            subtitle="The message shape before it reaches Twitch.",
        )
        card.setMaximumWidth(360)

        self._chat_preview = QLabel()
        self._chat_preview.setObjectName("chatPreview")
        self._chat_preview.setWordWrap(True)
        self._chat_preview.setTextFormat(Qt.RichText)
        card.body.addWidget(self._chat_preview)

        column.addWidget(card)
        self.refresh_chat_preview()

    def refresh_chat_preview(self) -> None:
        """Render the preview from the *configured* template, not a mock string.

        The mock drew an invented response. Reading the real template is what
        makes the card's claim -- "the message shape before it reaches Twitch" --
        true, and it means editing a template in the command dialog shows up
        here.
        """
        if self._chat_preview is None:
            return
        templates = config.TWITCH_BOT.get("templates", {}) or {}
        defaults = config.DEFAULT_TWITCH_BOT.get("templates", {}) or {}
        body = str(templates.get("kps") or defaults.get("kps") or "")
        channel = str(config.TWITCH_BOT.get("target_channel") or "").strip()
        viewer = channel or "viewer"
        self._chat_preview.setText(
            f"<div style='color:#8A94A3'>{viewer}:</div>"
            f"<div style='color:#EDF1F5'>!kps</div>"
            f"<div style='color:#38BDF8; margin-top:6px'>BonkScanner:</div>"
            f"<div style='color:#EDF1F5'>{body}</div>"
        )

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
        # `toggle_requested`, not `clicked`: only the live segment of a
        # `RunToggle` can fire, so the signal cannot ask for a transition that
        # is not on offer. The startup smoke caught this one -- a `QPushButton`
        # habit that raises at construction rather than at click time.
        self._bot_toggle_btn.toggle_requested.connect(on_toggle_bot)
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
        """The bot's own status string -- never the merged badge's caption.

        `TwitchSession.on_bot_finished` searches this for "error" to decide
        whether to overwrite it with "Stopped". Returning what the badge happens
        to be showing would let an account state answer a question about the
        bot, and quietly erase a real error message.
        """
        return self._bot_status

    # -- rendering what it is told ----------------------------------------

    def _render_badge(self) -> None:
        """Paint the one badge that carries both halves of the lifecycle.

        Authorization owns it until there is a token; after that the bot does.
        That rule is what stops the periodic token validation from stomping the
        bot's status: `_on_validation_finished` calls `show_connected` on every
        successful check, and the validation timer runs for as long as the bot
        is up.
        """
        if self._hero is None:
            return
        caption, state = self._bot_badge if self._authorized else self._auth_badge
        self._hero.set_status(caption, state, detail=self._badge_detail)

    def show_connected(self, username: str) -> None:
        self._authorized = True
        self._auth_badge = ("CONNECTED", STATE_OK)
        self._badge_detail = ""
        if self._account_entry is not None:
            self._account_entry.setText(str(username))
        if self._account_suffix is not None:
            self._account_suffix.setText("Authorized")
            self._account_suffix.setProperty("state", STATE_OK)
            _repolish(self._account_suffix)
        self._connect_btn.setVisible(False)
        self._disconnect_btn.setVisible(True)
        if self._target_channel_entry is not None:
            self._target_channel_entry.setPlaceholderText(username)
        self._render_badge()

    def show_disconnected(self) -> None:
        self._authorized = False
        self._auth_badge = ("NOT CONNECTED", STATE_OFF)
        self._badge_detail = ""
        if self._account_suffix is not None:
            self._account_suffix.setText("")
            self._account_suffix.setProperty("state", STATE_OFF)
            _repolish(self._account_suffix)
        self._connect_btn.setVisible(True)
        self._disconnect_btn.setVisible(False)
        self._render_badge()

    def show_authorizing(self) -> None:
        self._connect_btn.setEnabled(False)
        self._authorized = False
        self._auth_badge = ("AUTHORIZING", STATE_WARN)
        self._badge_detail = "Finish the authorization in your browser."
        self._render_badge()

    def show_validating(self) -> None:
        self._authorized = False
        self._auth_badge = ("VALIDATING", STATE_WARN)
        self._badge_detail = ""
        self._render_badge()

    def show_auth_failed(self) -> None:
        self._connect_btn.setEnabled(True)
        self._authorized = False
        self._auth_badge = ("AUTH FAILED", STATE_DANGER)
        self._badge_detail = ""
        self._render_badge()

    def enable_connect(self) -> None:
        self._connect_btn.setEnabled(True)

    def show_bot_status(self, status: str) -> None:
        self._bot_status = str(status)
        status_lower = self._bot_status.lower()
        # The same five branches the status label had, mapped onto badge states
        # rather than onto inline colours.
        if "error" in status_lower:
            # The worker's message is a sentence; the badge stays a label and
            # the sentence goes where it can be read.
            self._bot_badge = ("ERROR", STATE_DANGER)
            self._badge_detail = self._bot_status
        elif "connected" in status_lower:
            self._bot_badge = ("CONNECTED", STATE_OK)
            self._badge_detail = ""
        elif "connecting" in status_lower:
            self._bot_badge = ("CONNECTING", STATE_WARN)
            self._badge_detail = ""
        elif "stopped" in status_lower:
            self._bot_badge = ("STOPPED", STATE_OFF)
            self._badge_detail = ""
        else:
            self._bot_badge = (self._bot_status.upper(), STATE_OFF)
            self._badge_detail = ""
        self._render_badge()

    def show_bot_running(self) -> None:
        start_text, stop_text = TWITCH_BOT_CAPTIONS
        self._bot_toggle_btn.setText(stop_text)
        _set_widget_style_role(self._bot_toggle_btn, "stopScanner")

    def show_bot_stopped(self) -> None:
        start_text, _stop_text = TWITCH_BOT_CAPTIONS
        self._bot_toggle_btn.setText(start_text)
        _set_widget_style_role(self._bot_toggle_btn, "primary")


def _repolish(widget) -> None:
    """Re-match the stylesheet after a property changed. See `ModuleTile`."""
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
