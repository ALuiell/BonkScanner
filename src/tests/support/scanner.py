"""Builders for the two step-25 components.

Same shape as `support/twitch.py` and `support/templates_panel.py`: the **real**
constructors, with explicit fakes for every collaborator. Nothing here is a
`MagicMock` -- a stand-in that answers any attribute is how a conversion ships
a green suite over a branch that no longer runs (steps 19 and 22a both recorded
it, and step 25's own trace harness was broken twice by exactly that shape).

Two builders rather than one, because the components are two objects. They are
mutually referential in production -- the scanner asks run control where the
game window is, run control asks the scanner whether the scan was cancelled --
so `build_scanner` builds a `RunControl` unless it is given one, and wires the
pair the way `gui_app` does. A test that only cares about one side gets a real
object on the other, not a stub of it.

**The dialog factories fail by default.** `toggle_main_loop` shows a reroll
warning and, sometimes, an OBS reminder. A test that reaches one it did not
arrange for should say so loudly rather than receive a benign object.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from app.template_filters import TemplateRuntimeFilters
from gui_run_control import RunControl
from gui_scanner import Scanner


class FakeLabel:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.stylesheet = ""
        self.enabled = True

    def setText(self, value) -> None:
        self._text = value

    def text(self) -> str:
        return self._text

    def setStyleSheet(self, value) -> None:
        self.stylesheet = value

    def setWordWrap(self, _value) -> None:
        pass

    def setEnabled(self, value) -> None:
        self.enabled = bool(value)


class FakeLogBox:
    """Enough of `LogView` for `_append_log`, and it keeps what it was given.

    One method, because that is the whole port now. It used to stand in for a
    `QTextEdit` -- `moveCursor` and `insertHtml` -- back when the scanner built
    the markup itself; the panel owns records and their rendering since.
    """

    def __init__(self) -> None:
        self.entries: list[tuple] = []

    def append_log(self, message, tag=None) -> None:
        self.entries.append((message, tag))

    def text(self) -> str:
        return "".join(str(message) for message, _tag in self.entries)


class FakeThread:
    """Records the arguments `toggle_main_loop` starts the worker with."""

    def __init__(self, target=None, daemon=None, **_kwargs) -> None:
        self.target = target
        self.daemon = daemon
        self.started = False
        self.alive = False

    def start(self) -> None:
        self.started = True
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive


class AliveThread:
    def is_alive(self) -> bool:
        return True


class DeadThread:
    def is_alive(self) -> bool:
        return False


def _refuse(name):
    def factory(*_args, **_kwargs):
        raise AssertionError(
            f"{name} was opened by a test that did not arrange for it"
        )

    return factory


def build_run_control(
    *,
    log=None,
    schedule=None,
    client=None,
    abort_requested=None,
    toggle_scan=None,
    player_movement=None,
    toggle_recording=None,
    toggle_overlay_edit=None,
    provider=None,
) -> RunControl:
    """A real `RunControl`; `calls` records what each port was asked for.

    `toggle_overlay_edit` defaults to `None`, i.e. *not registered*. That is
    the pre-step `hasattr` branch's false side, and defaulting to it means a
    test that wants the F9 binding has to say so -- the opposite of the guard
    it replaces, which was silently true and would have gone silently false.
    """
    calls = {"log": [], "scheduled": [], "toggle_scan": 0, "player_movement": 0, "toggle_recording": 0,
             "toggle_overlay_edit": 0}

    def record_log(message, tag=None):
        calls["log"].append((message, tag))

    def record_schedule(delay_ms, callback):
        calls["scheduled"].append((delay_ms, callback))
        callback()

    def record_toggle_scan():
        calls["toggle_scan"] += 1

    def record_player_movement():
        calls["player_movement"] += 1

    def record_toggle_recording():
        calls["toggle_recording"] += 1

    run_control = RunControl(
        log=log or record_log,
        schedule=schedule or record_schedule,
        client=client or (lambda: None),
        abort_requested=abort_requested or (lambda: False),
        toggle_scan=toggle_scan or record_toggle_scan,
        player_movement=player_movement or record_player_movement,
        toggle_recording=toggle_recording or record_toggle_recording,
        toggle_overlay_edit=toggle_overlay_edit,
    )
    run_control.run_control_provider = provider
    # The component fixture represents the normal post-startup state. Tests of
    # hook registration and fail-closed behavior override this explicitly.
    run_control.player_movement_guard_available = True
    run_control.calls = calls
    return run_control


def build_scanner(
    *,
    run_control=None,
    coordinator=None,
    filters=None,
    selected_template_names=None,
    schedule=None,
    can_log=None,
    log_box=None,
    status_label=None,
    toggle_btn=None,
    add_tab=None,
    refresh_session_stats_snapshot=None,
    refresh_session_tracked_item_stats_ui=None,
    open_tracked_item_settings_dialog=None,
    is_recording=None,
    refresh_timeline=None,
    is_shutting_down=None,
    reroll_warning_dialog=None,
    obs_reminder_dialog=None,
) -> Scanner:
    """A real `Scanner`. `scanner.calls` records the ports it exercised."""
    calls = {
        "log": [],
        "scheduled": [],
        "tabs": [],
        "snapshot_refreshes": 0,
        "tracked_item_refreshes": 0,
        "tracked_item_dialogs": 0,
        "timeline_refreshes": 0,
    }

    def record_log(message, tag=None):
        calls["log"].append((message, tag))

    def record_schedule(delay_ms, callback):
        calls["scheduled"].append((delay_ms, getattr(callback, "__name__", "lambda")))
        # Delay 0 is "as soon as the Qt loop turns"; anything later is a
        # deliberate deferral (for example the 1s session clock), and running
        # it inline would recurse.
        if int(delay_ms) == 0:
            callback()

    if coordinator is None:
        coordinator = SimpleNamespace(client=None)
    if filters is None:
        filters = TemplateRuntimeFilters(
            selected_template_names=selected_template_names or (lambda: ["LIGHT"]),
            refresh_stats=lambda: None,
            log=record_log,
            is_scanning=lambda: False,
        )
    if run_control is None:
        run_control = build_run_control(client=lambda: coordinator.client)

    scanner = Scanner(
        coordinator,
        run_control=run_control,
        filters=filters,
        schedule=schedule or record_schedule,
        can_log=can_log or (lambda: True),
        log_box=log_box or (lambda: None),
        status_label=status_label or (lambda: None),
        toggle_btn=toggle_btn or (lambda: None),
        add_tab=add_tab or (lambda widget, title: calls["tabs"].append(title)),
        refresh_session_stats_snapshot=(
            refresh_session_stats_snapshot
            or (lambda: calls.__setitem__("snapshot_refreshes", calls["snapshot_refreshes"] + 1))
        ),
        refresh_session_tracked_item_stats_ui=(
            refresh_session_tracked_item_stats_ui
            or (lambda: calls.__setitem__("tracked_item_refreshes", calls["tracked_item_refreshes"] + 1))
        ),
        open_tracked_item_settings_dialog=(
            open_tracked_item_settings_dialog
            or (lambda: calls.__setitem__("tracked_item_dialogs", calls["tracked_item_dialogs"] + 1))
        ),
        is_recording=is_recording or (lambda: False),
        refresh_timeline=(
            refresh_timeline
            or (lambda: calls.__setitem__("timeline_refreshes", calls["timeline_refreshes"] + 1))
        ),
        is_shutting_down=is_shutting_down or (lambda: False),
        reroll_warning_dialog=reroll_warning_dialog or _refuse("RerollWarningDialog"),
        obs_reminder_dialog=obs_reminder_dialog or _refuse("ObsRecordingReminderDialog"),
    )
    if log_box is None:
        # Nothing asserts on the log through the widget by default, so the
        # cheap capture above stands in -- but `log` itself is the real one,
        # guard included.
        scanner.log = record_log
    scanner.calls = calls
    return scanner


def build_pair(*, provider=None, **scanner_kwargs):
    """Both components, wired to each other exactly as `gui_app` wires them.

    This is the fixture for anything that crosses the boundary -- the focus
    wait, the confirmed-target `esc`, the reconnect -- because those are the
    paths where a port pointed at the wrong object still passes a one-sided
    test.
    """
    coordinator = scanner_kwargs.pop("coordinator", None) or SimpleNamespace(client=None)
    holder: dict[str, Scanner] = {}
    run_control = build_run_control(
        client=lambda: coordinator.client,
        abort_requested=lambda: holder["scanner"]._scan_abort_requested(),
        toggle_scan=lambda: holder["scanner"].toggle_scan_event(),
        player_movement=lambda: holder["scanner"].handle_player_movement(),
        provider=provider,
    )
    scanner = build_scanner(run_control=run_control, coordinator=coordinator, **scanner_kwargs)
    holder["scanner"] = scanner
    return scanner, run_control


__all__ = [
    "AliveThread",
    "DeadThread",
    "FakeLabel",
    "FakeLogBox",
    "FakeThread",
    "build_pair",
    "build_run_control",
    "build_scanner",
    "threading",
]
