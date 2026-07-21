"""The two Twitch token workers, and the Twitch component's composition root.

Step 23 retired `TwitchBotMixin`: its widgets are `ui.tabs.twitch.TwitchTab`
(23b) and its behaviour is `app.twitch_session.TwitchSession` (23c). What is
left in this file is the two `QThread` subclasses and the function that wires
the component together.

The workers stay here for good. They cannot live under `ui/`, which the layer
table forbids from importing `infra`; they cannot live under `app/`, which
would need new `TOPLEVEL_DEBT` entries for `twitch_auth` in an allowlist that
may only shrink. Top level is where they belong, and it is where the
composition root can reach them, `gui_dialogs` and `twitch_bot` freely.

`arch_metrics` will keep reporting **two** hidden reads for this file --
`validation_finished` and `revoke_finished`. Both are `Signal(...)` **class**
attributes declared right here and read as `self.<signal>.emit()` inside the
declaring class's own `run()`. The metric flags them only because a class-level
assignment is not a `self.x =` assignment. They are not ambient reads through
`MegabonkApp` and no refactoring takes them to zero, which is why step 23's
criterion is stated as *seven ambient reads to zero* rather than the roadmap's
original "10 hidden reads reach 0".
"""

from PySide6.QtCore import QThread, QTimer, Signal
from twitch_auth import (
    TwitchAuthThread,
    TwitchTokenValidationResult,
    revoke_twitch_access_token,
    validate_twitch_access_token,
)
from twitch_bot import TwitchBotWorker


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


def build_twitch_session(app, view):
    """Construct `TwitchSession` and name its fourteen collaborators.

    The composition root for step 23c, called from `gui_app.__init__` at the
    point where `setup_twitch_bot_ui()` used to be, so the wiring and the
    startup validation happen in the same order and at the same moment.

    **Every factory closes over the parent window instead of taking one.**
    `TwitchBotMixin` passed `self.window` to the auth thread, both token
    workers, the bot worker, the validation timer and both dialogs. Binding it
    here is what lets `app/twitch_session.py` not contain the word `window` --
    step 23's third exit criterion -- while the Qt object tree stays exactly as
    it was, every one of them parented to the same window.

    `window` is re-read on each call rather than captured, the rule step 20's
    services and `_build_recordings_view` both follow: this runs during
    `__init__`, and a captured `app.window` would freeze whatever it was then.

    `tracker` and `session_stats_provider` are suppliers for the same reason.
    `live_run_tracker` is `None` until `gui_overlay` builds it, and the bot
    worker is created much later, on demand -- reading either eagerly here
    would hand the worker a `None` it never had before.

    `session_stats_provider` supplies the **application**, and that is
    deliberate: `TwitchBotWorker` answers `!session` through
    `getattr(provider, "format_twitch_session_summary", None)`, and that
    formatter is `OverlayMixin`'s. Passing the session or the tab here would
    turn `!session` into a silent empty answer -- no exception, green suite --
    which is the step-19 failure shape. Step 24 owns the overlay and re-points
    this one argument.
    """
    from app.player_stats_memory import player_stats_memory
    from app.twitch_session import TwitchSession
    from gui_dialogs import TwitchCommandSettingsDialog, TwitchCommandsHelpDialog

    def prime_disabled_items():
        """Warm the app's disabled-items cache before the dialog renders it.

        Both the `try`/`except` and the two attributes it writes are the
        application's, not Twitch's: `TwitchCommandSettingsDialog` reads
        `master.player_stats_disabled_items_cache` off the app
        (`gui_dialogs.py:1405`). Kept verbatim, including the bare swallow.
        """
        try:
            client = player_stats_memory(app)._get_player_stats_client()
            result = client.get_disabled_items()
            if result.available:
                app.player_stats_disabled_items_cache = result.items
                app.player_stats_disabled_items_refresh_pending = False
        except Exception:
            pass

    return TwitchSession(
        view=view,
        # `app.log` and `app.refresh_live_player_stats_now` are wrapped rather
        # than passed as bound methods, for the same late-resolution reason
        # `window` is: the mixin re-read both off `self` at call time, so a
        # captured bound method would freeze whatever the app had at build time
        # and silently ignore a later reassignment.
        log=lambda *args, **kwargs: app.log(*args, **kwargs),
        tracker=lambda: app.live_run_tracker,
        session_stats_provider=lambda: app,
        timer_factory=lambda: QTimer(app.window),
        auth_thread_factory=lambda: TwitchAuthThread(app.window),
        bot_worker_factory=lambda tracker, provider: TwitchBotWorker(
            tracker,
            session_stats_provider=provider,
            parent=app.window,
        ),
        validation_worker_factory=lambda token, **kwargs: TwitchTokenValidationWorker(
            token, parent=app.window, **kwargs
        ),
        revoke_worker_factory=lambda token: TwitchTokenRevokeWorker(token, parent=app.window),
        validate_token=validate_twitch_access_token,
        commands_help_dialog=lambda: TwitchCommandsHelpDialog(app.window),
        command_settings_dialog=lambda: TwitchCommandSettingsDialog(app.window, master=app),
        prime_disabled_items=prime_disabled_items,
        refresh_player_stats=lambda: app.refresh_live_player_stats_now(),
    )
