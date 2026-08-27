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

`session_snapshot` is the command's narrow read port
----------------------------------------------------
Session-wide counters belong to the independent `session_stats.SessionStats`
read model. The bot receives only its snapshot callback; `TwitchBotWorker`
owns the Twitch-specific template and chat formatting. Neither the OBS overlay
nor the in-game overlay participates in this path.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app import config
from infra.crash_journal import log_runtime_event
from infra.twitch_credentials import (
    delete_twitch_oauth_token,
    get_twitch_oauth_token,
    set_twitch_oauth_token,
)

_VALIDATION_INTERVAL_MS = 60 * 60 * 1000
# The OAuth callback can be validating the supplied token with a five-second
# HTTP timeout when the window is closed.
_AUTH_SHUTDOWN_WAIT_MS = 6_000
_BOT_SHUTDOWN_WAIT_MS = 12_000
_REQUEST_SHUTDOWN_WAIT_MS = 6_000


class TwitchSession:
    def __init__(
        self,
        *,
        view,
        log: Callable[..., None],
        tracker: Callable[[], Any],
        session_snapshot: Callable[[], dict[str, Any]],
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
        marshal_to_ui: Callable[[Callable[[], None]], bool] | None = None,
    ) -> None:
        self._view = view
        self._log = log
        self._tracker = tracker
        self._session_snapshot = session_snapshot
        self._auth_thread_factory = auth_thread_factory
        self._bot_worker_factory = bot_worker_factory
        self._validation_worker_factory = validation_worker_factory
        self._revoke_worker_factory = revoke_worker_factory
        self._validate_token = validate_token
        self._commands_help_dialog = commands_help_dialog
        self._command_settings_dialog = command_settings_dialog
        self._prime_disabled_items = prime_disabled_items
        self._refresh_player_stats = refresh_player_stats
        self._marshal_to_ui = marshal_to_ui or self._run_ui_callback_now

        self._auth_thread = None
        self._bot_worker = None
        self._validation_worker = None
        self._revoke_worker = None
        self._start_bot_after_validation = False
        self._shutting_down = False

        self._validation_timer = timer_factory()
        self._validation_timer.setInterval(_VALIDATION_INTERVAL_MS)
        self._validation_timer.timeout.connect(
            lambda: self.validate_async(log_on_success=False, context="periodic")
        )

    @staticmethod
    def _run_ui_callback_now(callback: Callable[[], None]) -> bool:
        callback()
        return True

    def _queue_ui(self, callback: Callable[[], None]) -> bool:
        """Run a worker result through the application's guarded UI invoker."""
        if self._shutting_down:
            return False

        def guarded() -> None:
            if self._shutting_down:
                return
            try:
                callback()
            except Exception as exc:
                # This function is itself a queued Qt callback. Contain late
                # widget/lifecycle failures here rather than letting them escape
                # through the event dispatcher.
                self._log(f"Twitch UI callback failed: {exc}", tag="error")

        try:
            return self._marshal_to_ui(guarded) is not False
        except Exception as exc:
            self._log(f"Could not queue Twitch UI callback: {exc}", tag="error")
            return False

    def _queue_worker_ui(
        self,
        attribute: str,
        worker,
        callback: Callable[..., None],
        *args,
    ) -> bool:
        def if_current() -> None:
            if getattr(self, attribute, None) is worker:
                callback(*args)

        return self._queue_ui(if_current)

    @staticmethod
    def _delete_worker_later(worker) -> None:
        delete_later = getattr(worker, "deleteLater", None)
        if callable(delete_later):
            try:
                delete_later()
            except Exception:
                pass

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
                try:
                    dialog.exec()
                    if dialog.dont_show_again:
                        config.user_config["SKIP_TWITCH_HELP_WARNING"] = True
                        config.save_config(config.user_config)
                finally:
                    delete_later = getattr(dialog, "deleteLater", None)
                    if callable(delete_later):
                        delete_later()
        self.save_settings()

    def open_command_settings(self) -> None:
        # The order is the mixin's and it matters: the dialog renders the
        # disabled-items cache, so the cache is primed and the live stats
        # refreshed before it is built. Both are player-stats operations owned
        # by the application, which is why they are ports rather than code here.
        self._prime_disabled_items()
        self._refresh_player_stats()
        dialog = self._command_settings_dialog()
        try:
            dialog.exec()
        finally:
            delete_later = getattr(dialog, "deleteLater", None)
            if callable(delete_later):
                delete_later()
        # The dialog is where templates are edited and the tab's chat preview is
        # what they look like; without this the preview keeps showing the old
        # wording until something else happens to redraw it, which is the exact
        # claim the card makes and breaks.
        self._view.refresh_chat_preview()

    # -- auth -------------------------------------------------------------

    def start_auth(self) -> None:
        if self._shutting_down:
            return
        current = self._auth_thread
        if current is not None and current.isRunning():
            return
        self._view.show_authorizing()
        worker = None
        try:
            worker = self._auth_thread_factory()
            self._name_worker(worker, "TwitchAuthThread")
            worker.auth_success.connect(
                lambda username, token, current=worker: self._queue_worker_ui(
                    "_auth_thread", current, self.on_auth_success, username, token
                )
            )
            worker.auth_error.connect(
                lambda error, current=worker: self._queue_worker_ui(
                    "_auth_thread", current, self.on_auth_error, error
                )
            )
            worker.finished.connect(
                lambda current=worker: self._queue_ui(
                    lambda: self._on_auth_worker_finished(current)
                )
            )
            self._auth_thread = worker
            worker.start()
        except Exception as exc:
            if self._auth_thread is worker:
                self._auth_thread = None
            if worker is not None:
                self._delete_worker_later(worker)
            self._view.show_auth_failed()
            self._log(f"Twitch authorization could not start: {exc}", tag="error")

    def _on_auth_worker_finished(self, worker) -> None:
        if self._auth_thread is worker:
            self._auth_thread = None
        self._delete_worker_later(worker)

    def on_auth_success(self, username, token) -> None:
        if self._shutting_down:
            return
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
        if self._shutting_down:
            return
        self._view.show_auth_failed()
        self._log(f"Twitch auth error: {err}", tag="error")

    def disconnect(self) -> None:
        try:
            token = get_twitch_oauth_token()
        except Exception as exc:
            token = ""
            self._log(f"Twitch credential read error: {exc}", tag="error")

        self.stop_bot()
        try:
            delete_twitch_oauth_token()
        except Exception as exc:
            self._log(f"Twitch credential removal error: {exc}", tag="error")
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
        worker = self._bot_worker
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            if self._bot_worker is worker:
                self._bot_worker = None
            return False

    def start_bot(self) -> None:
        if self._shutting_down:
            return
        try:
            token = get_twitch_oauth_token()
        except Exception as exc:
            self._log(f"Cannot read stored Twitch token: {exc}", tag="error")
            return
        if not token:
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
        if self._shutting_down:
            return
        if self._bot_worker and self._bot_worker.isRunning():
            return

        self._view.show_bot_running()

        worker = None
        try:
            worker = self._bot_worker_factory(
                self._tracker(),
                self._session_snapshot,
            )
            self._name_worker(worker, "TwitchBotWorker")
            worker.status_updated.connect(
                lambda status, current=worker: self._queue_worker_ui(
                    "_bot_worker", current, self.on_bot_status, status
                )
            )
            worker.log_message.connect(
                lambda message, current=worker: self._queue_worker_ui(
                    "_bot_worker", current, self.on_bot_log, message
                )
            )
            worker.finished.connect(
                lambda current=worker: self._queue_ui(
                    lambda: self._on_bot_worker_finished(current)
                )
            )
            self._bot_worker = worker
            worker.start()
        except Exception as exc:
            if self._bot_worker is worker:
                self._bot_worker = None
            if worker is not None:
                self._delete_worker_later(worker)
            self._view.show_bot_stopped()
            self._view.show_bot_status(f"Error: {exc}")
            self._log(f"Cannot start Twitch Bot: {exc}", tag="error")

    def stop_bot(self) -> None:
        worker = self._bot_worker
        if worker is not None and worker.isRunning():
            self._view.show_bot_status("Stopping...")
        self._stop_bot(wait_ms=0)

    def _stop_bot(self, *, wait_ms: int, ensure_finished: bool = False) -> None:
        worker = self._bot_worker
        if worker:
            log_runtime_event(
                "twitch.worker.stop_requested",
                worker=self._worker_name(worker),
            )
            try:
                worker.stop()
            except RuntimeError as exc:
                if self._bot_worker is worker:
                    self._bot_worker = None
                self._log(f"Twitch worker was already disposed: {exc}", tag="warning")
                return
            if wait_ms > 0 or ensure_finished:
                self._wait_for_worker(
                    worker,
                    wait_ms,
                    ensure_finished=ensure_finished,
                )

    def shutdown(self) -> None:
        """Stop every Twitch-owned timer and worker before the Qt app exits."""
        if self._shutting_down:
            return
        self._shutting_down = True
        log_runtime_event("twitch.shutdown.begin")
        self._start_bot_after_validation = False
        self._validation_timer.stop()
        self._stop_bot(
            wait_ms=_BOT_SHUTDOWN_WAIT_MS,
            ensure_finished=True,
        )
        self._stop_auth_thread()
        self._wait_for_worker(
            self._validation_worker,
            _REQUEST_SHUTDOWN_WAIT_MS,
            ensure_finished=True,
        )
        self._wait_for_worker(
            self._revoke_worker,
            _REQUEST_SHUTDOWN_WAIT_MS,
            ensure_finished=True,
        )
        for attribute in (
            "_auth_thread",
            "_bot_worker",
            "_validation_worker",
            "_revoke_worker",
        ):
            worker = getattr(self, attribute, None)
            setattr(self, attribute, None)
            if worker is not None:
                self._delete_worker_later(worker)
        log_runtime_event("twitch.shutdown.complete")

    def _stop_auth_thread(self) -> None:
        worker = self._auth_thread
        if worker is None:
            return
        shutdown_server = getattr(worker, "_shutdown_server", None)
        if callable(shutdown_server):
            shutdown_server()
        self._wait_for_worker(
            worker,
            _AUTH_SHUTDOWN_WAIT_MS,
            ensure_finished=True,
        )

    @staticmethod
    def _worker_name(worker) -> str:
        object_name = getattr(worker, "objectName", None)
        if callable(object_name):
            try:
                name = object_name()
            except Exception:
                name = ""
            if name:
                return str(name)
        return type(worker).__name__

    @staticmethod
    def _name_worker(worker, name: str) -> None:
        set_name = getattr(worker, "setObjectName", None)
        if callable(set_name):
            set_name(name)

    @classmethod
    def _wait_for_worker(
        cls,
        worker,
        wait_ms: int,
        *,
        ensure_finished: bool = False,
    ) -> bool:
        if worker is None:
            return True
        wait = getattr(worker, "wait", None)
        if not callable(wait):
            return True

        name = cls._worker_name(worker)
        started_at = time.monotonic()
        timed_result = wait(wait_ms)
        is_running = getattr(worker, "isRunning", None)
        running_after = bool(is_running()) if callable(is_running) else False
        log_runtime_event(
            "twitch.worker.wait",
            worker=name,
            timeout_ms=wait_ms,
            result=timed_result,
            running=running_after,
            elapsed_ms=round((time.monotonic() - started_at) * 1000),
        )

        if ensure_finished and (timed_result is False or running_after):
            # A timed-out QThread must not remain parented to the window when it
            # is destroyed. The HTTP workers have their own request timeouts;
            # this second wait is the hard lifecycle barrier after the soft UI
            # budget has expired.
            log_runtime_event("twitch.worker.wait_extended", worker=name)
            wait()
            running_after = bool(is_running()) if callable(is_running) else False
            log_runtime_event(
                "twitch.worker.wait_extended_complete",
                worker=name,
                running=running_after,
                elapsed_ms=round((time.monotonic() - started_at) * 1000),
            )
        return not running_after

    def on_bot_status(self, status) -> None:
        if self._shutting_down:
            return
        self._view.show_bot_status(status)

    def on_bot_log(self, msg) -> None:
        if self._shutting_down:
            return
        self._log(f"[Twitch] {msg}")

    def on_bot_finished(self) -> None:
        if self._shutting_down:
            return
        self._view.show_bot_stopped()
        if "error" not in self._view.bot_status_text().lower():
            self._view.show_bot_status("Stopped")

    def _on_bot_worker_finished(self, worker) -> None:
        if self._bot_worker is worker:
            self._bot_worker = None
        self._delete_worker_later(worker)
        self.on_bot_finished()

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
        if self._shutting_down:
            return False
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
        worker = None
        try:
            worker = self._validation_worker_factory(
                token,
                context=context,
                log_on_success=log_on_success,
                start_bot_on_success=start_bot_on_success,
                fallback_username=fallback_username,
            )
            self._name_worker(worker, "TwitchTokenValidationWorker")
            worker.validation_finished.connect(
                lambda *result, current=worker: self._queue_worker_ui(
                    "_validation_worker",
                    current,
                    self._on_validation_finished,
                    *result,
                )
            )
            worker.finished.connect(
                lambda current=worker: self._queue_ui(
                    lambda: self._on_validation_worker_finished(current)
                )
            )
            self._validation_worker = worker
            worker.start()
            return True
        except Exception as exc:
            if self._validation_worker is worker:
                self._validation_worker = None
            if worker is not None:
                self._delete_worker_later(worker)
            self._start_bot_after_validation = False
            self._view.enable_connect()
            self._log(f"Twitch token validation could not start: {exc}", tag="error")
            return False

    def _on_validation_worker_finished(self, worker=None) -> None:
        if worker is None or self._validation_worker is worker:
            self._validation_worker = None
        if worker is not None:
            self._delete_worker_later(worker)

    def _on_validation_finished(
        self,
        token: str,
        validation,
        log_on_success: bool,
        start_bot_on_success: bool,
        fallback_username: str,
        context: str,
    ) -> None:
        if self._shutting_down:
            return
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
        if self._shutting_down:
            return
        worker = self._revoke_worker
        if worker is not None and worker.isRunning():
            return
        worker = None
        try:
            worker = self._revoke_worker_factory(token)
            self._name_worker(worker, "TwitchTokenRevokeWorker")
            worker.revoke_finished.connect(
                lambda revoked, message, current=worker: self._queue_worker_ui(
                    "_revoke_worker",
                    current,
                    self._on_revoke_finished,
                    revoked,
                    message,
                )
            )
            worker.finished.connect(
                lambda current=worker: self._queue_ui(
                    lambda: self._on_revoke_worker_finished(current)
                )
            )
            self._revoke_worker = worker
            worker.start()
        except Exception as exc:
            if self._revoke_worker is worker:
                self._revoke_worker = None
            if worker is not None:
                self._delete_worker_later(worker)
            self._log(f"Twitch token revoke warning: {exc}", tag="warning")

    def _on_revoke_finished(self, revoked: bool, message: str) -> None:
        if not revoked and message:
            self._log(f"Twitch token revoke warning: {message}", tag="warning")

    def _on_revoke_worker_finished(self, worker=None) -> None:
        if worker is None or self._revoke_worker is worker:
            self._revoke_worker = None
        if worker is not None:
            self._delete_worker_later(worker)

    def _clear_session_state(self) -> None:
        self._validation_timer.stop()
        config.TWITCH_BOT["username"] = ""
        config.save_config(config.user_config)
