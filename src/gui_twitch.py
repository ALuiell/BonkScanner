from app import config
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from twitch_auth import (
    TwitchAuthThread,
    TwitchTokenValidationResult,
    revoke_twitch_access_token,
    validate_twitch_access_token,
)
from twitch_bot import TwitchBotWorker
from infra.twitch_credentials import delete_twitch_oauth_token, get_twitch_oauth_token, set_twitch_oauth_token
from gui_shared import _make_scroll_section
from gui_styles import _button_state_stylesheet


class TwitchTokenValidationWorker(QThread):
    validation_finished = Signal(str, object, bool, bool, str, str)

    def __init__(
        self,
        token: str,
        *,
        context: str,
        log_on_success: bool,
        start_bot_on_success: bool,
        fallback_username: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.token = token
        self.context = context
        self.log_on_success = log_on_success
        self.start_bot_on_success = start_bot_on_success
        self.fallback_username = fallback_username

    def run(self) -> None:
        try:
            validation = validate_twitch_access_token(self.token)
        except Exception as exc:
            validation = TwitchTokenValidationResult(
                valid=False,
                error_message=f"Token validation failed: {exc}",
                transient_error=True,
            )
        self.validation_finished.emit(
            self.token,
            validation,
            self.log_on_success,
            self.start_bot_on_success,
            self.fallback_username,
            self.context,
        )


class TwitchTokenRevokeWorker(QThread):
    revoke_finished = Signal(bool, str)

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token

    def run(self) -> None:
        try:
            revoked, message = revoke_twitch_access_token(self.token)
        except Exception as exc:
            revoked, message = False, f"Token revoke failed: {exc}"
        self.revoke_finished.emit(revoked, message)


class TwitchBotMixin:
    def setup_twitch_bot_ui(self):
        self.twitch_auth_thread = None
        self.twitch_bot_worker = None
        self.twitch_token_validation_worker = None
        self.twitch_token_revoke_worker = None
        self._twitch_start_bot_after_validation = False
        self.twitch_token_validation_timer = QTimer(self.window)
        self.twitch_token_validation_timer.setInterval(60 * 60 * 1000)
        self.twitch_token_validation_timer.timeout.connect(
            lambda: self.validate_twitch_session_async(
                log_on_success=False,
                context="periodic",
            )
        )

        self.twitch_connect_btn.clicked.connect(self.start_twitch_auth)
        self.twitch_bot_toggle_btn.clicked.connect(self.toggle_twitch_bot)
        self.twitch_auto_connect_cb.stateChanged.connect(self.save_twitch_auto_connect)
        self.twitch_command_settings_btn.clicked.connect(self.open_twitch_command_settings_dialog)

        token = get_twitch_oauth_token()

        self.twitch_disconnect_btn.clicked.connect(self.disconnect_twitch)

        # Restore UI state if already configured
        if config.TWITCH_BOT.get("username") and token:
            self._set_twitch_connected_ui(config.TWITCH_BOT["username"])
            self.validate_twitch_session_async(
                log_on_success=False,
                start_bot_on_success=config.TWITCH_BOT.get("auto_connect", False),
                context="startup",
            )
        else:
            self.twitch_auth_status_label.setText("<span style='color: #f08b72; font-weight: bold;'>Not connected</span>")
            self.twitch_connect_btn.setVisible(True)
            self.twitch_disconnect_btn.setVisible(False)

        self.twitch_tier_combo.currentTextChanged.connect(self.save_twitch_settings)
        self.twitch_target_channel_entry.editingFinished.connect(self.save_twitch_settings)
        self.twitch_global_cooldown_spin.valueChanged.connect(self.save_twitch_settings)
        self.twitch_cooldown_spin.valueChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_stats_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_session_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_bans_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_items_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_weapons_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_tomes_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_chaos_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_stages_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_powerups_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_kps_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_scanner_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_chests_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_presets_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_disabled_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_commands_cb.stateChanged.connect(self.on_twitch_commands_toggled)
        self.twitch_stage_announcements_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_commands_announcements_cb.stateChanged.connect(self.save_twitch_settings)

    def save_twitch_auto_connect(self, *_):
        config.TWITCH_BOT["auto_connect"] = self.twitch_auto_connect_cb.isChecked()
        config.save_config(config.user_config)

    def save_twitch_settings(self, *_):
        config.TWITCH_BOT["access_tier"] = self.twitch_tier_combo.currentText()
        target_channel = self.twitch_target_channel_entry.text().strip().lstrip("#").lower()
        config.TWITCH_BOT["target_channel"] = target_channel
        config.TWITCH_BOT["global_cooldown_seconds"] = self.twitch_global_cooldown_spin.value()
        config.TWITCH_BOT["cooldown_seconds"] = self.twitch_cooldown_spin.value()
        config.TWITCH_BOT["stage_announcements"] = self.twitch_stage_announcements_cb.isChecked()
        config.TWITCH_BOT["commands_announcements"] = self.twitch_commands_announcements_cb.isChecked()
        config.TWITCH_BOT["commands"]["stats"] = self.twitch_cmd_stats_cb.isChecked()
        config.TWITCH_BOT["commands"]["session"] = self.twitch_cmd_session_cb.isChecked()
        config.TWITCH_BOT["commands"]["bans"] = self.twitch_cmd_bans_cb.isChecked()
        config.TWITCH_BOT["commands"]["items"] = self.twitch_cmd_items_cb.isChecked()
        config.TWITCH_BOT["commands"]["weapons"] = self.twitch_cmd_weapons_cb.isChecked()
        config.TWITCH_BOT["commands"]["tomes"] = self.twitch_cmd_tomes_cb.isChecked()
        config.TWITCH_BOT["commands"]["chaos"] = self.twitch_cmd_chaos_cb.isChecked()
        config.TWITCH_BOT["commands"]["stages"] = self.twitch_cmd_stages_cb.isChecked()
        config.TWITCH_BOT["commands"]["powerups"] = self.twitch_cmd_powerups_cb.isChecked()
        config.TWITCH_BOT["commands"]["kps"] = self.twitch_cmd_kps_cb.isChecked()
        config.TWITCH_BOT["commands"]["scanner"] = self.twitch_cmd_scanner_cb.isChecked()
        config.TWITCH_BOT["commands"]["chests"] = self.twitch_cmd_chests_cb.isChecked()
        config.TWITCH_BOT["commands"]["presets"] = self.twitch_cmd_presets_cb.isChecked()
        config.TWITCH_BOT["commands"]["bonkhelp"] = self.twitch_cmd_commands_cb.isChecked()
        config.TWITCH_BOT["commands"]["disabled"] = self.twitch_cmd_disabled_cb.isChecked()
        config.save_config(config.user_config)

    def on_twitch_commands_toggled(self, *_):
        if self.twitch_cmd_commands_cb.isChecked():
            if not config.user_config.get("SKIP_TWITCH_HELP_WARNING", False):
                from gui_dialogs import TwitchCommandsHelpDialog
                dialog = TwitchCommandsHelpDialog(self.window)
                dialog.exec()
                if dialog.dont_show_again:
                    config.user_config["SKIP_TWITCH_HELP_WARNING"] = True
                    config.save_config(config.user_config)
        self.save_twitch_settings()

    def start_twitch_auth(self):
        self.twitch_connect_btn.setEnabled(False)
        self.twitch_auth_status_label.setText("<span style='color: #ffd23f; font-weight: bold;'>Waiting for authorization...</span>")
        self.twitch_auth_thread = TwitchAuthThread(self.window)
        self.twitch_auth_thread.auth_success.connect(self.on_twitch_auth_success)
        self.twitch_auth_thread.auth_error.connect(self.on_twitch_auth_error)
        self.twitch_auth_thread.start()

    def on_twitch_auth_success(self, username, token):
        try:
            set_twitch_oauth_token(token)
        except Exception as exc:
            self.twitch_connect_btn.setEnabled(True)
            self.twitch_auth_status_label.setText("<span style='color: #f08b72; font-weight: bold;'>Authorization failed</span>")
            self.log(f"Twitch credential storage error: {exc}", tag="error")
            return

        self.twitch_auth_status_label.setText("<span style='color: #ffd23f; font-weight: bold;'>Validating token...</span>")
        self.validate_twitch_session_async(
            log_on_success=False,
            start_bot_on_success=config.TWITCH_BOT.get("auto_connect", False),
            fallback_username=username,
            context="auth",
        )

    def disconnect_twitch(self):
        token = get_twitch_oauth_token()

        self.stop_twitch_bot()
        delete_twitch_oauth_token()
        self._clear_twitch_session_state()

        if token:
            self._start_twitch_token_revoke(token)
        self._set_twitch_disconnected_ui()

    def on_twitch_auth_error(self, err):
        self.twitch_connect_btn.setEnabled(True)
        self.twitch_auth_status_label.setText("<span style='color: #f08b72; font-weight: bold;'>Authorization failed</span>")
        self.log(f"Twitch auth error: {err}", tag="error")

    def toggle_twitch_bot(self):
        if self._is_twitch_bot_active():
            self.stop_twitch_bot()
        else:
            self.start_twitch_bot()

    def start_twitch_bot(self):
        if not get_twitch_oauth_token():
            self.log("Cannot start Twitch Bot: Not connected.", tag="error")
            return

        if self.validate_twitch_session_async(
            log_on_success=False,
            start_bot_on_success=True,
            context="start_bot",
        ):
            return

        self.log("Cannot start Twitch Bot: Stored Twitch token is invalid.", tag="error")

    def _start_twitch_bot_worker(self):
        if self.twitch_bot_worker and self.twitch_bot_worker.isRunning():
            return

        self.twitch_bot_toggle_btn.setText("Stop Bot")
        self.twitch_bot_toggle_btn.setStyleSheet(_button_state_stylesheet("#B91C1C", "#DC2626"))
        
        self.twitch_bot_worker = TwitchBotWorker(
            self.live_run_tracker,
            session_stats_provider=self,
            parent=self.window,
        )
        self.twitch_bot_worker.status_updated.connect(self.on_twitch_bot_status)
        self.twitch_bot_worker.log_message.connect(self.on_twitch_bot_log)
        self.twitch_bot_worker.finished.connect(self.on_twitch_bot_finished)
        self.twitch_bot_worker.start()

    def stop_twitch_bot(self):
        worker = getattr(self, "twitch_bot_worker", None)
        if worker:
            worker.stop()
            worker.wait(2000)

    def _update_twitch_bot_status_ui(self, status: str) -> None:
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
        self.twitch_bot_status_label.setText(formatted)

    def on_twitch_bot_status(self, status):
        self._update_twitch_bot_status_ui(status)

    def on_twitch_bot_log(self, msg):
        self.log(f"[Twitch] {msg}")

    def on_twitch_bot_finished(self):
        self.twitch_bot_toggle_btn.setText("Start Bot")
        self.twitch_bot_toggle_btn.setStyleSheet("")
        if "error" not in self.twitch_bot_status_label.text().lower():
            self._update_twitch_bot_status_ui("Stopped")

    def validate_twitch_session(self, *, log_on_success: bool = True) -> bool:
        token = get_twitch_oauth_token()
        if not token:
            self.twitch_token_validation_timer.stop()
            return False

        validation = validate_twitch_access_token(token)
        if validation.valid:
            username = validation.login or str(config.TWITCH_BOT.get("username") or "").strip().lower()
            if username and username != config.TWITCH_BOT.get("username"):
                config.TWITCH_BOT["username"] = username
                config.save_config(config.user_config)
            if username:
                self._set_twitch_connected_ui(username)
            self.twitch_token_validation_timer.start()
            if log_on_success:
                self.log("Twitch token validated.", tag="success")
            return True

        if validation.transient_error:
            self.twitch_token_validation_timer.start()
            self.log(validation.error_message, tag="warning")
            return False

        delete_twitch_oauth_token()
        self.stop_twitch_bot()
        self._clear_twitch_session_state()
        self._set_twitch_disconnected_ui()
        self.log(validation.error_message or "Stored Twitch token is invalid.", tag="warning")
        return False

    def validate_twitch_session_async(
        self,
        *,
        log_on_success: bool = True,
        start_bot_on_success: bool = False,
        fallback_username: str = "",
        context: str = "periodic",
    ) -> bool:
        token = get_twitch_oauth_token()
        if not token:
            self.twitch_token_validation_timer.stop()
            return False

        worker = getattr(self, "twitch_token_validation_worker", None)
        if worker is not None and worker.isRunning():
            if start_bot_on_success:
                self._twitch_start_bot_after_validation = True
            return True

        self._twitch_start_bot_after_validation = bool(start_bot_on_success)
        worker = TwitchTokenValidationWorker(
            token,
            context=context,
            log_on_success=log_on_success,
            start_bot_on_success=start_bot_on_success,
            fallback_username=fallback_username,
            parent=self.window,
        )
        worker.validation_finished.connect(self._on_twitch_token_validation_finished)
        worker.finished.connect(self._on_twitch_token_validation_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self.twitch_token_validation_worker = worker
        worker.start()
        return True

    def _on_twitch_token_validation_worker_finished(self) -> None:
        self.twitch_token_validation_worker = None

    def _on_twitch_token_validation_finished(
        self,
        token: str,
        validation,
        log_on_success: bool,
        start_bot_on_success: bool,
        fallback_username: str,
        context: str,
    ) -> None:
        current_token = get_twitch_oauth_token()
        if current_token != token:
            self._twitch_start_bot_after_validation = False
            self.twitch_connect_btn.setEnabled(True)
            return

        should_start_bot = bool(start_bot_on_success or getattr(self, "_twitch_start_bot_after_validation", False))
        self._twitch_start_bot_after_validation = False

        if validation.valid:
            username = (
                getattr(validation, "login", "")
                or fallback_username
                or str(config.TWITCH_BOT.get("username") or "").strip().lower()
            )
            if username and username != config.TWITCH_BOT.get("username"):
                config.TWITCH_BOT["username"] = username
                config.save_config(config.user_config)
            if username:
                self._set_twitch_connected_ui(username)
            self.twitch_connect_btn.setEnabled(True)
            self.twitch_token_validation_timer.start()
            if context == "auth":
                self.log(f"Twitch bot authenticated as {username}", tag="success")
            elif log_on_success:
                self.log("Twitch token validated.", tag="success")
            if should_start_bot:
                self._start_twitch_bot_worker()
            return

        self.twitch_connect_btn.setEnabled(True)
        if getattr(validation, "transient_error", False) and context != "auth":
            self.twitch_token_validation_timer.start()
            self.log(validation.error_message, tag="warning")
            if should_start_bot:
                self.log("Cannot start Twitch Bot: Twitch token validation failed.", tag="error")
            return

        delete_twitch_oauth_token()
        self.stop_twitch_bot()
        self._clear_twitch_session_state()
        self._set_twitch_disconnected_ui()
        message = getattr(validation, "error_message", "") or "Stored Twitch token is invalid."
        self.log(message, tag="error" if context == "auth" else "warning")

    def _start_twitch_token_revoke(self, token: str) -> None:
        worker = getattr(self, "twitch_token_revoke_worker", None)
        if worker is not None and worker.isRunning():
            return
        worker = TwitchTokenRevokeWorker(token, parent=self.window)
        worker.revoke_finished.connect(self._on_twitch_token_revoke_finished)
        worker.finished.connect(self._on_twitch_token_revoke_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self.twitch_token_revoke_worker = worker
        worker.start()

    def _on_twitch_token_revoke_finished(self, revoked: bool, message: str) -> None:
        if not revoked and message:
            self.log(f"Twitch token revoke warning: {message}", tag="warning")

    def _on_twitch_token_revoke_worker_finished(self) -> None:
        self.twitch_token_revoke_worker = None

    def _clear_twitch_session_state(self) -> None:
        self.twitch_token_validation_timer.stop()
        config.TWITCH_BOT["username"] = ""
        config.save_config(config.user_config)

    def _set_twitch_connected_ui(self, username: str) -> None:
        self.twitch_auth_status_label.setText(
            f"Connected as <span style='color: #4fd67a; font-weight: bold;'>{username}</span>"
        )
        self.twitch_connect_btn.setVisible(False)
        self.twitch_disconnect_btn.setVisible(True)
        if getattr(self, "twitch_target_channel_entry", None) is not None:
            self.twitch_target_channel_entry.setPlaceholderText(username)

    def _set_twitch_disconnected_ui(self) -> None:
        self.twitch_auth_status_label.setText(
            "<span style='color: #f08b72; font-weight: bold;'>Not connected</span>"
        )
        self.twitch_connect_btn.setVisible(True)
        self.twitch_disconnect_btn.setVisible(False)

    def _is_twitch_bot_active(self) -> bool:
        worker = getattr(self, "twitch_bot_worker", None)
        return worker is not None and worker.isRunning()

    def open_twitch_command_settings_dialog(self):
        from gui_dialogs import TwitchCommandSettingsDialog
        try:
            client = self._get_player_stats_client()
            result = client.get_disabled_items()
            if result.available:
                self.player_stats_disabled_items_cache = result.items
                self.player_stats_disabled_items_refresh_pending = False
        except Exception:
            pass
        self.refresh_live_player_stats_now()
        dialog = TwitchCommandSettingsDialog(self.window, master=self)
        dialog.exec()

    def _build_twitch_bot_tab(self):
        self.tab_twitch = QWidget()
        tab_layout = QVBoxLayout(self.tab_twitch)
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

        # LEFT COLUMN WIDGETS
        # 1. Twitch Account Connection Card
        auth_group = QGroupBox("Twitch Account")
        auth_layout = QVBoxLayout(auth_group)
        auth_layout.setContentsMargins(16, 12, 16, 12)
        auth_layout.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(QLabel("Account Status:"))
        self.twitch_auth_status_label = QLabel("<span style='color: #f08b72; font-weight: bold;'>Not connected</span>")
        self.twitch_auth_status_label.setTextFormat(Qt.RichText)
        status_row.addWidget(self.twitch_auth_status_label)
        status_row.addStretch(1)
        auth_layout.addLayout(status_row)

        self.twitch_auth_buttons_layout = QHBoxLayout()
        self.twitch_auth_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.twitch_connect_btn = QPushButton("Connect to Twitch")
        self.twitch_connect_btn.setObjectName("TwitchConnectButton")
        self.twitch_auth_buttons_layout.addWidget(self.twitch_connect_btn)

        self.twitch_disconnect_btn = QPushButton("Disconnect")
        self.twitch_disconnect_btn.setObjectName("DangerButton")
        self.twitch_disconnect_btn.setVisible(False)
        self.twitch_auth_buttons_layout.addWidget(self.twitch_disconnect_btn)
        auth_layout.addLayout(self.twitch_auth_buttons_layout)

        # Target Channel input field under connection
        target_layout = QFormLayout()
        target_layout.setContentsMargins(0, 4, 0, 0)
        self.twitch_target_channel_entry = QLineEdit()
        self.twitch_target_channel_entry.setPlaceholderText(config.TWITCH_BOT.get("username") or "Authorized account")
        self.twitch_target_channel_entry.setText(config.TWITCH_BOT.get("target_channel", ""))
        target_layout.addRow("Target Channel:", self.twitch_target_channel_entry)
        auth_layout.addLayout(target_layout)

        left_col.addWidget(auth_group)

        # 2. Bot Control Card
        control_group = QGroupBox("Bot Control")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(16, 12, 16, 12)
        control_layout.setSpacing(10)

        bot_status_row = QHBoxLayout()
        bot_status_row.setContentsMargins(0, 0, 0, 0)
        bot_status_row.addWidget(QLabel("Bot Status:"))
        self.twitch_bot_status_label = QLabel("<span style='color: #f08b72; font-weight: bold;'>Stopped</span>")
        self.twitch_bot_status_label.setTextFormat(Qt.RichText)
        self.twitch_bot_status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        bot_status_row.addWidget(self.twitch_bot_status_label)
        bot_status_row.addStretch(1)
        control_layout.addLayout(bot_status_row)

        self.twitch_auto_connect_cb = QCheckBox("Auto-connect")
        self.twitch_auto_connect_cb.setChecked(config.TWITCH_BOT.get("auto_connect", False))
        self.twitch_auto_connect_cb.setToolTip(
            "Start the bot automatically after Twitch authorization and when the application starts."
        )
        control_layout.addWidget(self.twitch_auto_connect_cb)

        self.twitch_bot_toggle_btn = QPushButton("Start Bot")
        self.twitch_bot_toggle_btn.setObjectName("SuccessButton")
        self.twitch_bot_toggle_btn.setMinimumHeight(36)
        btn_font = self.twitch_bot_toggle_btn.font()
        btn_font.setBold(True)
        self.twitch_bot_toggle_btn.setFont(btn_font)
        control_layout.addWidget(self.twitch_bot_toggle_btn)

        left_col.addWidget(control_group)

        # 3. Bot Settings Card (under Bot Control in left column)
        settings_group = QGroupBox("Bot Settings")
        settings_main_layout = QVBoxLayout(settings_group)
        settings_main_layout.setContentsMargins(16, 12, 16, 12)
        settings_main_layout.setSpacing(10)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)

        self.twitch_tier_combo = QComboBox()
        self.twitch_tier_combo.addItems(["Everyone", "Mods & VIPs", "Subs & Mods"])
        self.twitch_tier_combo.setCurrentText(config.TWITCH_BOT.get("access_tier", "Everyone"))
        form_layout.addRow("Access Tier:", self.twitch_tier_combo)

        self.twitch_global_cooldown_spin = QSpinBox()
        self.twitch_global_cooldown_spin.setRange(0, 600)
        self.twitch_global_cooldown_spin.setValue(config.TWITCH_BOT.get("global_cooldown_seconds", 1))
        self.twitch_global_cooldown_spin.setSuffix(" sec")
        form_layout.addRow("Global Cooldown:", self.twitch_global_cooldown_spin)

        self.twitch_cooldown_spin = QSpinBox()
        self.twitch_cooldown_spin.setRange(0, 600)
        self.twitch_cooldown_spin.setValue(config.TWITCH_BOT.get("cooldown_seconds", 5))
        self.twitch_cooldown_spin.setSuffix(" sec")
        form_layout.addRow("Command Cooldown:", self.twitch_cooldown_spin)

        settings_main_layout.addLayout(form_layout)

        left_col.addWidget(settings_group)
        left_col.addStretch(1)

        # RIGHT COLUMN WIDGETS
        # 1. Chat Commands Config Card
        commands_group = QGroupBox("Command Configuration")
        commands_main_layout = QVBoxLayout(commands_group)
        commands_main_layout.setContentsMargins(16, 12, 16, 12)
        commands_main_layout.setSpacing(10)

        commands_header_layout = QHBoxLayout()
        commands_header_layout.setContentsMargins(4, 0, 0, 0)
        commands_header_lbl = QLabel("Active Chat Commands:")
        commands_header_lbl.setStyleSheet("font-weight: bold;")
        self.twitch_command_settings_btn = QPushButton("Command Settings")
        commands_header_layout.addWidget(commands_header_lbl)
        commands_header_layout.addStretch(1)
        commands_header_layout.addWidget(self.twitch_command_settings_btn)
        commands_main_layout.addLayout(commands_header_layout)

        self.twitch_cmd_stats_cb = QCheckBox("!stats")
        self.twitch_cmd_stats_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("stats", True))
        self.twitch_cmd_session_cb = QCheckBox("!session")
        self.twitch_cmd_session_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("session", True))
        self.twitch_cmd_bans_cb = QCheckBox("!bans")
        self.twitch_cmd_bans_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("bans", True))
        self.twitch_cmd_items_cb = QCheckBox("!items")
        self.twitch_cmd_items_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("items", True))
        self.twitch_cmd_weapons_cb = QCheckBox("!weapons")
        self.twitch_cmd_weapons_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("weapons", True))
        self.twitch_cmd_tomes_cb = QCheckBox("!tomes")
        self.twitch_cmd_tomes_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("tomes", True))
        self.twitch_cmd_chaos_cb = QCheckBox("!chaos")
        self.twitch_cmd_chaos_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("chaos", True))
        self.twitch_cmd_stages_cb = QCheckBox("!stages")
        self.twitch_cmd_stages_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("stages", True))
        self.twitch_cmd_powerups_cb = QCheckBox("!powerups")
        self.twitch_cmd_powerups_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("powerups", True))
        self.twitch_cmd_kps_cb = QCheckBox("!kps")
        self.twitch_cmd_kps_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("kps", True))
        self.twitch_cmd_scanner_cb = QCheckBox("!scanner")
        self.twitch_cmd_scanner_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("scanner", True))
        self.twitch_cmd_chests_cb = QCheckBox("!chests")
        self.twitch_cmd_chests_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("chests", False))
        self.twitch_cmd_presets_cb = QCheckBox("!presets")
        self.twitch_cmd_presets_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("presets", False))
        self.twitch_cmd_commands_cb = QCheckBox("!bonkhelp")
        self.twitch_cmd_commands_cb.setChecked(
            config.TWITCH_BOT.get("commands", {}).get(
                "bonkhelp",
                config.TWITCH_BOT.get("commands", {}).get("commands", True),
            )
        )
        self.twitch_cmd_disabled_cb = QCheckBox("!disabled")
        self.twitch_cmd_disabled_cb.setChecked(config.TWITCH_BOT.get("commands", {}).get("disabled", False))

        commands_grid = QGridLayout()
        commands_grid.setVerticalSpacing(14)
        commands_grid.setHorizontalSpacing(12)
        commands_grid.setContentsMargins(4, 0, 0, 0)
        # Arrange in 3 columns:
        commands_grid.addWidget(self.twitch_cmd_stats_cb, 0, 0)
        commands_grid.addWidget(self.twitch_cmd_session_cb, 0, 1)
        commands_grid.addWidget(self.twitch_cmd_bans_cb, 0, 2)

        commands_grid.addWidget(self.twitch_cmd_items_cb, 1, 0)
        commands_grid.addWidget(self.twitch_cmd_weapons_cb, 1, 1)
        commands_grid.addWidget(self.twitch_cmd_tomes_cb, 1, 2)

        commands_grid.addWidget(self.twitch_cmd_chaos_cb, 2, 0)
        commands_grid.addWidget(self.twitch_cmd_stages_cb, 2, 1)
        commands_grid.addWidget(self.twitch_cmd_powerups_cb, 2, 2)

        commands_grid.addWidget(self.twitch_cmd_kps_cb, 3, 0)
        commands_grid.addWidget(self.twitch_cmd_scanner_cb, 3, 1)
        commands_grid.addWidget(self.twitch_cmd_chests_cb, 3, 2)

        commands_grid.addWidget(self.twitch_cmd_presets_cb, 4, 0)
        commands_grid.addWidget(self.twitch_cmd_commands_cb, 4, 1)
        commands_grid.addWidget(self.twitch_cmd_disabled_cb, 4, 2)

        commands_main_layout.addLayout(commands_grid)

        # Separator line before Announcements (with larger vertical margins)
        commands_divider = QFrame()
        commands_divider.setFrameShape(QFrame.HLine)
        commands_divider.setFrameShadow(QFrame.Sunken)
        commands_divider.setStyleSheet("background-color: #2B3648; max-height: 1px; margin: 14px 4px;")
        commands_main_layout.addWidget(commands_divider)

        # Announcements layout with left margin to match the checkboxes grid
        ann_layout = QVBoxLayout()
        ann_layout.setContentsMargins(4, 0, 0, 0)
        ann_layout.setSpacing(6)

        ann_title = QLabel("Announcements:")
        ann_title.setStyleSheet("font-weight: bold; margin-top: 6px; margin-bottom: 4px;")
        ann_layout.addWidget(ann_title)

        self.twitch_stage_announcements_cb = QCheckBox("Announce Stage Transitions")
        self.twitch_stage_announcements_cb.setChecked(config.TWITCH_BOT.get("stage_announcements", True))
        ann_layout.addWidget(self.twitch_stage_announcements_cb)

        self.twitch_commands_announcements_cb = QCheckBox("Periodically announce available commands")
        self.twitch_commands_announcements_cb.setChecked(config.TWITCH_BOT.get("commands_announcements", False))
        ann_layout.addWidget(self.twitch_commands_announcements_cb)

        commands_main_layout.addLayout(ann_layout)

        right_col.addWidget(commands_group)
        right_col.addStretch(1)

        # Add stretch and add to tabview
        twitch_layout.addStretch(1)
        self.tabview.addTab(self.tab_twitch, "Twitch Bot")

        self._build_in_game_overlay_tab()
        self.tabview.addTab(self.tab_in_game_overlay, "In-Game Overlay")
