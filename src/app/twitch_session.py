"""Twitch auth, token lifecycle and bot-worker lifecycle, in one object.

Step 23c, the behaviour half of retiring `TwitchBotMixin`. The widget half is
`ui.tabs.twitch.TwitchTab` (23b).

Everything that is not `config` or a credential arrives as a constructor
argument. That is not ceremony -- it is what the layer table leaves available.
`app/` may import `core`, `infra` and `projections`, so `infra.twitch_credentials`
is a plain import; but `twitch_auth` and `twitch_bot` are still top-level
modules, and reaching them from here would need new `TOPLEVEL_DEBT` entries in
an allowlist that may only shrink. So the four worker classes, the QTimer and
the two dialogs come in as factories from the composition root in `gui_twitch`,
which is top-level and may import them freely. It is also the shape the roadmap
asks for in as many words: "explicit auth, worker lifecycle, runtime-snapshot,
logging, settings, scheduler, and view ports".

**No factory takes a parent.** `TwitchBotMixin` passed `self.window` to the
auth thread, both token workers, the bot worker, the validation timer and both
dialogs -- seven of its ambient reads in one name. The parent is a composition
concern, so the factories close over it and the word `window` does not occur in
this file. That is step 23's third exit criterion, and it is checked
structurally by `test_twitch_component.py` rather than by reading.

`session_stats_provider` is the explicit session-summary owner
---------------------------------------------------------------
`TwitchBotWorker` answers `!session` by doing
`getattr(self.session_stats_provider, "format_twitch_session_summary", None)`
in its worker thread (`twitch_bot.py:377`). That formatter is owned by the
explicit `gui_overlay.Overlay` session-stats provider
(`gui_overlay.py:1048`), not Twitch's, and it reads a snapshot that
`gui_overlay` writes and `gui_scanner` triggers -- not one line of which was
ever in `gui_twitch.py`. Measured, not assumed by name.

The provider cannot become this object: the `getattr` would return `None`,
`!session` would answer with nothing, and it would do so with no exception and
a green suite. Step 24 therefore gives the snapshot and formatter one owner,
`gui_overlay.Overlay`, and the composition root supplies that object directly;
the application is no longer exposed through this port.
"""

from __future__ import annotations

from typing import Any, Callable

from app import config
from infra.twitch_credentials import (
    delete_twitch_oauth_token,
    get_twitch_oauth_token,
    set_twitch_oauth_token,
)

_VALIDATION_INTERVAL_MS = 60 * 60 * 1000


class TwitchSession:
    def __init__(
        self,
        *,
        view,
        log: Callable[..., None],
        tracker: Callable[[], Any],
        session_stats_provider: Callable[[], Any],
        timer_factory: Callable[[], Any],
        auth_thread_factory: Callable[[], Any],
        bot_worker_factory: Callable[[Any, Any], Any],
        validation_worker_factory: Callable[..., Any],
        revoke_worker_factory: Callable[[str], Any],
        validate_token: Callable[[str], Any],
        commands_help_dialog: Callable[[], Any],
        command_settings_dialog: Callable[[], Any],
        prime_disabled_items: Callable[[], None],
        refresh_player_stats: Callable[[], None],
    ) -> None:
        self._view = view
        self._log = log
        self._tracker = tracker
        self._session_stats_provider = session_stats_provider
        self._auth_thread_factory = auth_thread_factory
        self._bot_worker_factory = bot_worker_factory
        self._validation_worker_factory = validation_worker_factory
        self._revoke_worker_factory = revoke_worker_factory
        self._validate_token = validate_token
        self._commands_help_dialog = commands_help_dialog
        self._command_settings_dialog = command_settings_dialog
        self._prime_disabled_items = prime_disabled_items
        self._refresh_player_stats = refresh_player_stats

        self._auth_thread = None
        self._bot_worker = None
        self._validation_worker = None
        self._revoke_worker = None
        self._start_bot_after_validation = False

        self._validation_timer = timer_factory()
        self._validation_timer.setInterval(_VALIDATION_INTERVAL_MS)
        self._validation_timer.timeout.connect(
            lambda: self.validate_async(log_on_success=False, context="periodic")
        )

    # -- surface the shutdown path still reaches (gui_scanner, step 25) ----

    @property
    def auth_thread(self):
        return self._auth_thread

    # -- startup ----------------------------------------------------------

    def start(self) -> None:
        """Wire the view and restore state. Was `setup_twitch_bot_ui`."""
        self._view.bind(
            on_connect=self.start_auth,
            on_disconnect=self.disconnect,
            on_toggle_bot=self.toggle_bot,
            on_auto_connect_changed=self.save_auto_connect,
            on_command_settings=self.open_command_settings,
            on_settings_changed=self.save_settings,
            on_bonkhelp_toggled=self.on_bonkhelp_toggled,
        )

        token = get_twitch_oauth_token()
        if config.TWITCH_BOT.get("username") and token:
            self._view.show_connected(config.TWITCH_BOT["username"])
            self.validate_async(
                log_on_success=False,
                start_bot_on_success=config.TWITCH_BOT.get("auto_connect", False),
                context="startup",
            )
        else:
            self._view.show_disconnected()

    # -- settings ---------------------------------------------------------

    def save_auto_connect(self, *_) -> None:
        config.TWITCH_BOT["auto_connect"] = self._view.auto_connect_enabled()
        config.save_config(config.user_config)

    def save_settings(self, *_) -> None:
        settings = self._view.read_settings()
        commands = settings.pop("commands")
        config.TWITCH_BOT.update(settings)
        config.TWITCH_BOT["commands"].update(commands)
        config.save_config(config.user_config)

    def on_bonkhelp_toggled(self, *_) -> None:
        if self._view.bonkhelp_enabled():
            if not config.user_config.get("SKIP_TWITCH_HELP_WARNING", False):
                dialog = self._commands_help_dialog()
                dialog.exec()
                if dialog.dont_show_again:
                    config.user_config["SKIP_TWITCH_HELP_WARNING"] = True
                    config.save_config(config.user_config)
        self.save_settings()

    def open_command_settings(self) -> None:
        # The order is the mixin's and it matters: the dialog renders the
        # disabled-items cache, so the cache is primed and the live stats
        # refreshed before it is built. Both are player-stats operations owned
        # by the application, which is why they are ports rather than code here.
        self._prime_disabled_items()
        self._refresh_player_stats()
        self._command_settings_dialog().exec()

    # -- auth -------------------------------------------------------------

    def start_auth(self) -> None:
        self._view.show_authorizing()
        self._auth_thread = self._auth_thread_factory()
        self._auth_thread.auth_success.connect(self.on_auth_success)
        self._auth_thread.auth_error.connect(self.on_auth_error)
        self._auth_thread.start()

    def on_auth_success(self, username, token) -> None:
        try:
            set_twitch_oauth_token(token)
        except Exception as exc:
            self._view.show_auth_failed()
            self._log(f"Twitch credential storage error: {exc}", tag="error")
            return

        self._view.show_validating()
        self.validate_async(
            log_on_success=False,
            start_bot_on_success=config.TWITCH_BOT.get("auto_connect", False),
            fallback_username=username,
            context="auth",
        )

    def on_auth_error(self, err) -> None:
        self._view.show_auth_failed()
        self._log(f"Twitch auth error: {err}", tag="error")

    def disconnect(self) -> None:
        token = get_twitch_oauth_token()

        self.stop_bot()
        delete_twitch_oauth_token()
        self._clear_session_state()

        if token:
            self._start_token_revoke(token)
        self._view.show_disconnected()

    # -- bot lifecycle ----------------------------------------------------

    def toggle_bot(self) -> None:
        if self.is_bot_active():
            self.stop_bot()
        else:
            self.start_bot()

    def is_bot_active(self) -> bool:
        return self._bot_worker is not None and self._bot_worker.isRunning()

    def start_bot(self) -> None:
        if not get_twitch_oauth_token():
            self._log("Cannot start Twitch Bot: Not connected.", tag="error")
            return

        if self.validate_async(
            log_on_success=False,
            start_bot_on_success=True,
            context="start_bot",
        ):
            return

        self._log("Cannot start Twitch Bot: Stored Twitch token is invalid.", tag="error")

    def _start_bot_worker(self) -> None:
        if self._bot_worker and self._bot_worker.isRunning():
            return

        self._view.show_bot_running()

        self._bot_worker = self._bot_worker_factory(
            self._tracker(),
            self._session_stats_provider(),
        )
        self._bot_worker.status_updated.connect(self.on_bot_status)
        self._bot_worker.log_message.connect(self.on_bot_log)
        self._bot_worker.finished.connect(self.on_bot_finished)
        self._bot_worker.start()

    def stop_bot(self) -> None:
        worker = self._bot_worker
        if worker:
            worker.stop()
            worker.wait(2000)

    def on_bot_status(self, status) -> None:
        self._view.show_bot_status(status)

    def on_bot_log(self, msg) -> None:
        self._log(f"[Twitch] {msg}")

    def on_bot_finished(self) -> None:
        self._view.show_bot_stopped()
        if "error" not in self._view.bot_status_text().lower():
            self._view.show_bot_status("Stopped")

    # -- token validation -------------------------------------------------

    def validate(self, *, log_on_success: bool = True) -> bool:
        """Synchronous validation. Kept because it is a different code path
        from `validate_async`, with its own timer and logging decisions."""
        token = get_twitch_oauth_token()
        if not token:
            self._validation_timer.stop()
            return False

        validation = self._validate_token(token)
        if validation.valid:
            username = validation.login or str(config.TWITCH_BOT.get("username") or "").strip().lower()
            if username and username != config.TWITCH_BOT.get("username"):
                config.TWITCH_BOT["username"] = username
                config.save_config(config.user_config)
            if username:
                self._view.show_connected(username)
            self._validation_timer.start()
            if log_on_success:
                self._log("Twitch token validated.", tag="success")
            return True

        if validation.transient_error:
            self._validation_timer.start()
            self._log(validation.error_message, tag="warning")
            return False

        delete_twitch_oauth_token()
        self.stop_bot()
        self._clear_session_state()
        self._view.show_disconnected()
        self._log(validation.error_message or "Stored Twitch token is invalid.", tag="warning")
        return False

    def validate_async(
        self,
        *,
        log_on_success: bool = True,
        start_bot_on_success: bool = False,
        fallback_username: str = "",
        context: str = "periodic",
    ) -> bool:
        token = get_twitch_oauth_token()
        if not token:
            self._validation_timer.stop()
            return False

        worker = self._validation_worker
        if worker is not None and worker.isRunning():
            if start_bot_on_success:
                self._start_bot_after_validation = True
            return True

        self._start_bot_after_validation = bool(start_bot_on_success)
        worker = self._validation_worker_factory(
            token,
            context=context,
            log_on_success=log_on_success,
            start_bot_on_success=start_bot_on_success,
            fallback_username=fallback_username,
        )
        worker.validation_finished.connect(self._on_validation_finished)
        worker.finished.connect(self._on_validation_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._validation_worker = worker
        worker.start()
        return True

    def _on_validation_worker_finished(self) -> None:
        self._validation_worker = None

    def _on_validation_finished(
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
            self._start_bot_after_validation = False
            self._view.enable_connect()
            return

        should_start_bot = bool(start_bot_on_success or self._start_bot_after_validation)
        self._start_bot_after_validation = False

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
                self._view.show_connected(username)
            self._view.enable_connect()
            self._validation_timer.start()
            if context == "auth":
                self._log(f"Twitch bot authenticated as {username}", tag="success")
            elif log_on_success:
                self._log("Twitch token validated.", tag="success")
            if should_start_bot:
                self._start_bot_worker()
            return

        self._view.enable_connect()
        if getattr(validation, "transient_error", False) and context != "auth":
            self._validation_timer.start()
            self._log(validation.error_message, tag="warning")
            if should_start_bot:
                self._log("Cannot start Twitch Bot: Twitch token validation failed.", tag="error")
            return

        delete_twitch_oauth_token()
        self.stop_bot()
        self._clear_session_state()
        self._view.show_disconnected()
        message = getattr(validation, "error_message", "") or "Stored Twitch token is invalid."
        self._log(message, tag="error" if context == "auth" else "warning")

    # -- token revocation -------------------------------------------------

    def _start_token_revoke(self, token: str) -> None:
        worker = self._revoke_worker
        if worker is not None and worker.isRunning():
            return
        worker = self._revoke_worker_factory(token)
        worker.revoke_finished.connect(self._on_revoke_finished)
        worker.finished.connect(self._on_revoke_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._revoke_worker = worker
        worker.start()

    def _on_revoke_finished(self, revoked: bool, message: str) -> None:
        if not revoked and message:
            self._log(f"Twitch token revoke warning: {message}", tag="warning")

    def _on_revoke_worker_finished(self) -> None:
        self._revoke_worker = None

    def _clear_session_state(self) -> None:
        self._validation_timer.stop()
        config.TWITCH_BOT["username"] = ""
        config.save_config(config.user_config)
