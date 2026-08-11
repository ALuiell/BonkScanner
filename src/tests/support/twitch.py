"""Builders for the Twitch component (step 23).

Same shape as `support/templates_panel.py`: the **real** constructor, with
explicit fakes for every collaborator. Nothing here is a `MagicMock` that
answers any call -- a stand-in that silently satisfies an attribute is how a
conversion produces a green suite over a broken branch (steps 19 and 22a both
recorded it).

**The threads are determinised, not waited on.** `TwitchSession` spawns four
`QThread`s in production. The doubles below run their work *inline* on
`start()` and then emit, so a result cannot be "not arrived yet" while an
assertion passes. This is deliberate and it is what the step-23 brief demands:
a background result the harness merely failed to wait for must not read as
equivalent.

**The dialog factories fail by default.** A test that opens a dialog it did not
arrange for should say so loudly rather than get a benign object back.
"""

from __future__ import annotations

from app.twitch_session import TwitchSession


class FakeSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class FakeTimer:
    """The 60-minute validation timer, with its cadence made observable."""

    def __init__(self) -> None:
        self.interval = None
        self.timeout = FakeSignal()
        self.starts = 0
        self.stops = 0

    def setInterval(self, ms) -> None:
        self.interval = ms

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def fire(self) -> None:
        self.timeout.emit()


class FakeTab:
    """Records what the session asked the view to render."""

    def __init__(
        self,
        *,
        settings=None,
        auto_connect=False,
        bonkhelp=False,
        bot_status="Stopped",
    ) -> None:
        self.calls: list = []
        self.handlers: dict = {}
        self._settings = settings or {
            "access_tier": "Everyone",
            "target_channel": "",
            "global_cooldown_seconds": 1,
            "cooldown_seconds": 5,
            "stage_announcements": True,
            "commands_announcements": False,
            "commands": {},
        }
        self._auto_connect = auto_connect
        self._bonkhelp = bonkhelp
        self._bot_status = bot_status

    def bind(self, **handlers) -> None:
        self.handlers = handlers

    def read_settings(self) -> dict:
        # A copy: the session pops "commands" out of what it is handed, and a
        # fake that let that mutate its own state would hide the bug.
        settings = dict(self._settings)
        settings["commands"] = dict(self._settings["commands"])
        return settings

    def auto_connect_enabled(self) -> bool:
        return self._auto_connect

    def bonkhelp_enabled(self) -> bool:
        return self._bonkhelp

    def bot_status_text(self) -> str:
        return self._bot_status

    def show_connected(self, username) -> None:
        self.calls.append(("show_connected", username))

    def show_disconnected(self) -> None:
        self.calls.append(("show_disconnected",))

    def show_authorizing(self) -> None:
        self.calls.append(("show_authorizing",))

    def show_validating(self) -> None:
        self.calls.append(("show_validating",))

    def show_auth_failed(self) -> None:
        self.calls.append(("show_auth_failed",))

    def enable_connect(self) -> None:
        self.calls.append(("enable_connect",))

    def show_bot_status(self, status) -> None:
        self._bot_status = status
        self.calls.append(("show_bot_status", status))

    def show_bot_running(self) -> None:
        self.calls.append(("show_bot_running",))

    def show_bot_stopped(self) -> None:
        self.calls.append(("show_bot_stopped",))

    def refresh_chat_preview(self) -> None:
        # The command dialog is where templates are edited; the preview is what
        # they look like. Recorded so a test can assert the session redraws it
        # after the dialog closes.
        self.calls.append(("refresh_chat_preview",))


class FakeAuthThread:
    def __init__(self) -> None:
        self.auth_success = FakeSignal()
        self.auth_error = FakeSignal()
        self.started = 0
        self.shutdowns = 0
        self.waited = []
        self.running = True

    def start(self) -> None:
        self.started += 1

    def isRunning(self) -> bool:
        return self.running

    def _shutdown_server(self) -> None:
        self.shutdowns += 1
        self.running = False

    def wait(self, ms=None) -> bool:
        self.waited.append(ms)
        self.running = False
        return True


class FakeValidationWorker:
    """Runs inline on `start()` -- see the module docstring on threads."""

    def __init__(self, token, *, result=None, running=False, **kwargs) -> None:
        self.token = token
        self.kwargs = kwargs
        self.validation_finished = FakeSignal()
        self.finished = FakeSignal()
        self.result = result
        self._running = running
        self.started = 0
        self.waited = []

    def isRunning(self) -> bool:
        return self._running

    def deleteLater(self) -> None:
        pass

    def wait(self, ms=None) -> bool:
        self.waited.append(ms)
        self._running = False
        return True

    def start(self) -> None:
        self.started += 1
        if self.result is None:
            return
        self.validation_finished.emit(
            self.token,
            self.result,
            self.kwargs.get("log_on_success", False),
            self.kwargs.get("start_bot_on_success", False),
            self.kwargs.get("fallback_username", ""),
            self.kwargs.get("context", "periodic"),
        )
        self.finished.emit()


class FakeRevokeWorker:
    def __init__(self, token, *, outcome=None, running=False) -> None:
        self.token = token
        self.revoke_finished = FakeSignal()
        self.finished = FakeSignal()
        self.outcome = outcome
        self._running = running
        self.started = 0
        self.waited = []

    def isRunning(self) -> bool:
        return self._running

    def deleteLater(self) -> None:
        pass

    def wait(self, ms=None) -> bool:
        self.waited.append(ms)
        self._running = False
        return True

    def start(self) -> None:
        self.started += 1
        if self.outcome is None:
            return
        self.revoke_finished.emit(*self.outcome)
        self.finished.emit()


class FakeBotWorker:
    def __init__(self, tracker=None, session_snapshot=None) -> None:
        self.tracker = tracker
        self.session_snapshot = session_snapshot
        self.status_updated = FakeSignal()
        self.log_message = FakeSignal()
        self.finished = FakeSignal()
        self.started = 0
        self.stopped = 0
        self.waited = []
        self.running = False

    def isRunning(self) -> bool:
        return self.running

    def start(self) -> None:
        self.started += 1
        self.running = True

    def stop(self) -> None:
        self.stopped += 1
        self.running = False

    def wait(self, ms=None) -> bool:
        self.waited.append(ms)
        self.running = False
        return True


def _explodes(name):
    def factory(*_args, **_kwargs):
        raise AssertionError(
            f"{name} was opened but this test did not arrange for it"
        )

    return factory


class Harness:
    """The session plus everything it was handed, for assertions."""

    def __init__(self, session, tab, timer, logs, calls) -> None:
        self.session = session
        self.tab = tab
        self.timer = timer
        self.logs = logs
        self.calls = calls


def build_session(
    *,
    tab=None,
    tracker=None,
    session_snapshot=None,
    validation_result=None,
    validation_running=False,
    revoke_outcome=None,
    validate_token=None,
    commands_help_dialog=None,
    command_settings_dialog=None,
) -> Harness:
    """Construct the real `TwitchSession` with explicit fakes."""
    tab = tab if tab is not None else FakeTab()
    timer = FakeTimer()
    logs: list = []
    calls: dict = {"auth_threads": [], "bot_workers": [], "validation": [], "revoke": [], "primed": 0, "refreshed": 0}

    def auth_thread_factory():
        thread = FakeAuthThread()
        calls["auth_threads"].append(thread)
        return thread

    def bot_worker_factory(tracker_arg, snapshot_arg):
        worker = FakeBotWorker(tracker_arg, snapshot_arg)
        calls["bot_workers"].append(worker)
        return worker

    def validation_worker_factory(token, **kwargs):
        worker = FakeValidationWorker(
            token, result=validation_result, running=validation_running, **kwargs
        )
        calls["validation"].append(worker)
        return worker

    def revoke_worker_factory(token):
        worker = FakeRevokeWorker(token, outcome=revoke_outcome)
        calls["revoke"].append(worker)
        return worker

    def prime():
        calls["primed"] += 1

    def refresh():
        calls["refreshed"] += 1

    session = TwitchSession(
        view=tab,
        log=lambda message, tag=None: logs.append((message, tag)),
        tracker=lambda: tracker,
        session_snapshot=session_snapshot,
        timer_factory=lambda: timer,
        auth_thread_factory=auth_thread_factory,
        bot_worker_factory=bot_worker_factory,
        validation_worker_factory=validation_worker_factory,
        revoke_worker_factory=revoke_worker_factory,
        validate_token=validate_token or _explodes("validate_token"),
        commands_help_dialog=commands_help_dialog or _explodes("TwitchCommandsHelpDialog"),
        command_settings_dialog=command_settings_dialog or _explodes("TwitchCommandSettingsDialog"),
        prime_disabled_items=prime,
        refresh_player_stats=refresh,
    )
    return Harness(session, tab, timer, logs, calls)
