import config
from PySide6.QtCore import QThread, QTimer, Signal
from twitch_auth import TwitchAuthThread, revoke_twitch_access_token, validate_twitch_access_token
from twitch_bot import TwitchBotWorker
from twitch_credentials import delete_twitch_oauth_token, get_twitch_oauth_token, set_twitch_oauth_token
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
        validation = validate_twitch_access_token(self.token)
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
        revoked, message = revoke_twitch_access_token(self.token)
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
        self.twitch_token_validation_timer.timeout.connect(self.validate_twitch_session_async)

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
