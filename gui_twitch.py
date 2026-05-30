import config
from twitch_auth import TwitchAuthThread
from twitch_bot import TwitchBotWorker
from gui_styles import _button_state_stylesheet

class TwitchBotMixin:
    def setup_twitch_bot_ui(self):
        self.twitch_auth_thread = None
        self.twitch_bot_worker = None

        self.twitch_connect_btn.clicked.connect(self.start_twitch_auth)
        self.twitch_bot_toggle_btn.clicked.connect(self.toggle_twitch_bot)

        from PySide6.QtCore import QSettings
        settings = QSettings("ALuiell", "BonkScanner")
        token = settings.value("twitch_oauth_token", "")

        self.twitch_disconnect_btn.clicked.connect(self.disconnect_twitch)

        # Restore UI state if already configured
        if config.TWITCH_BOT.get("username") and token:
            self.twitch_auth_status_label.setText(f"Connected as <span style='color:#4fd67a;'>{config.TWITCH_BOT['username']}</span>")
            self.twitch_connect_btn.setVisible(False)
            self.twitch_disconnect_btn.setVisible(True)

        self.twitch_tier_combo.currentTextChanged.connect(self.save_twitch_settings)
        self.twitch_cooldown_spin.valueChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_stats_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_bans_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_items_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_weapons_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_tomes_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_stages_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_cmd_scanner_cb.stateChanged.connect(self.save_twitch_settings)
        self.twitch_stage_announcements_cb.stateChanged.connect(self.save_twitch_settings)

    def save_twitch_settings(self, *_):
        config.TWITCH_BOT["access_tier"] = self.twitch_tier_combo.currentText()
        config.TWITCH_BOT["cooldown_seconds"] = self.twitch_cooldown_spin.value()
        config.TWITCH_BOT["stage_announcements"] = self.twitch_stage_announcements_cb.isChecked()
        config.TWITCH_BOT["commands"]["stats"] = self.twitch_cmd_stats_cb.isChecked()
        config.TWITCH_BOT["commands"]["bans"] = self.twitch_cmd_bans_cb.isChecked()
        config.TWITCH_BOT["commands"]["items"] = self.twitch_cmd_items_cb.isChecked()
        config.TWITCH_BOT["commands"]["weapons"] = self.twitch_cmd_weapons_cb.isChecked()
        config.TWITCH_BOT["commands"]["tomes"] = self.twitch_cmd_tomes_cb.isChecked()
        config.TWITCH_BOT["commands"]["stages"] = self.twitch_cmd_stages_cb.isChecked()
        config.TWITCH_BOT["commands"]["scanner"] = self.twitch_cmd_scanner_cb.isChecked()
        config.save_config(config.user_config)

    def start_twitch_auth(self):
        self.twitch_connect_btn.setEnabled(False)
        self.twitch_auth_status_label.setText("<span style='color:#ffd23f;'>Waiting for browser authorization...</span>")
        self.twitch_auth_thread = TwitchAuthThread(self.window)
        self.twitch_auth_thread.auth_success.connect(self.on_twitch_auth_success)
        self.twitch_auth_thread.auth_error.connect(self.on_twitch_auth_error)
        self.twitch_auth_thread.start()

    def on_twitch_auth_success(self, username, token):
        from PySide6.QtCore import QSettings
        settings = QSettings("ALuiell", "BonkScanner")
        settings.setValue("twitch_oauth_token", token)

        self.twitch_connect_btn.setEnabled(True)
        self.twitch_connect_btn.setVisible(False)
        self.twitch_disconnect_btn.setVisible(True)
        self.twitch_auth_status_label.setText(f"Connected as <span style='color:#4fd67a;'>{username}</span>")
        config.TWITCH_BOT["username"] = username
        config.save_config(config.user_config)
        self.log(f"Twitch bot authenticated as {username}", tag="success")

    def disconnect_twitch(self):
        from PySide6.QtCore import QSettings
        import urllib.request
        import urllib.parse
        from twitch_auth import CLIENT_ID

        settings = QSettings("ALuiell", "BonkScanner")
        token = settings.value("twitch_oauth_token", "")
        
        self.stop_twitch_bot()
        config.TWITCH_BOT["username"] = ""
        config.save_config(config.user_config)
        
        settings.remove("twitch_oauth_token")
        
        if token:
            try:
                data = urllib.parse.urlencode({"client_id": CLIENT_ID, "token": token}).encode("utf-8")
                req = urllib.request.Request("https://id.twitch.tv/oauth2/revoke", data=data)
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        
        self.twitch_auth_status_label.setText("<span style='color:#f08b72;'>Not connected</span>")
        self.twitch_connect_btn.setVisible(True)
        self.twitch_disconnect_btn.setVisible(False)

    def on_twitch_auth_error(self, err):
        self.twitch_connect_btn.setEnabled(True)
        self.twitch_auth_status_label.setText("<span style='color:#f08b72;'>Authorization failed.</span>")
        self.log(f"Twitch auth error: {err}", tag="error")

    def toggle_twitch_bot(self):
        if self._is_twitch_bot_active():
            self.stop_twitch_bot()
        else:
            self.start_twitch_bot()

    def start_twitch_bot(self):
        if not config.TWITCH_BOT.get("oauth_token"):
            self.log("Cannot start Twitch Bot: Not connected.", tag="error")
            return

        if self.twitch_bot_worker and self.twitch_bot_worker.isRunning():
            return

        self.twitch_bot_toggle_btn.setText("Stop Bot")
        self.twitch_bot_toggle_btn.setStyleSheet(_button_state_stylesheet("#B91C1C", "#DC2626"))
        
        self.twitch_bot_worker = TwitchBotWorker(self.live_run_tracker, self.window)
        self.twitch_bot_worker.status_updated.connect(self.on_twitch_bot_status)
        self.twitch_bot_worker.log_message.connect(self.on_twitch_bot_log)
        self.twitch_bot_worker.finished.connect(self.on_twitch_bot_finished)
        self.twitch_bot_worker.start()

    def stop_twitch_bot(self):
        if self.twitch_bot_worker:
            self.twitch_bot_worker.stop()
            self.twitch_bot_worker.wait(2000)

    def _update_twitch_bot_status_ui(self, status: str) -> None:
        status_lower = status.lower()
        if "error" in status_lower:
            formatted = f'Status: <span style="color:#f08b72;">{status}</span>'
        elif "connected" in status_lower:
            formatted = f'Status: <span style="color:#4fd67a;">{status}</span>'
        elif "connecting" in status_lower:
            formatted = f'Status: <span style="color:#ffd23f;">{status}</span>'
        elif "stopped" in status_lower:
            formatted = 'Status: <span style="color:#f08b72;">Stopped</span>'
        else:
            formatted = f'Status: {status}'
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

    def _is_twitch_bot_active(self) -> bool:
        worker = getattr(self, "twitch_bot_worker", None)
        return worker is not None and worker.isRunning()
