"""Builders for the componentized player-stats views.

This is the shape the step-18 phase-1 plan calls for, and the alternative to
``object.__new__(MegabonkApp)``: a helper that calls the component's **real**
constructor with explicit fakes. The difference that matters is failure mode --
adding a constructor argument breaks every call site here loudly, where
``object.__new__`` absorbs a new dependency silently and surfaces it as an
``AttributeError`` at the first read, in whichever test happens to reach it
first.

Deliberately not a "minimal ``MegabonkApp``" builder. That would rebuild the
ambient namespace under a nicer name, which is the step-18 rollback condition.
Each component gets its own builder, added by the step that converts it.
"""

from __future__ import annotations

from ui.tabs.player_stats.recording_timeline import RecordingTimelineView


class FakeTimelineWidget:
    """Records every call, so a test can assert on the rendered trace."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple] = []

    def setText(self, text) -> None:
        self.calls.append(("setText", text))

    def setStyleSheet(self, sheet) -> None:
        self.calls.append(("setStyleSheet", sheet))

    def setEnabled(self, enabled) -> None:
        self.calls.append(("setEnabled", enabled))

    def setMaximum(self, maximum) -> None:
        self.calls.append(("setMaximum", maximum))

    def setValue(self, value) -> None:
        self.calls.append(("setValue", value))

    @property
    def text(self):
        """The last text written, or None."""
        for method, value in reversed(self.calls):
            if method == "setText":
                return value
        return None


class FakeRecorder:
    def __init__(self, *, is_recording: bool = False, elapsed: str = "00:42") -> None:
        self.is_recording = is_recording
        self._elapsed = elapsed

    def elapsed_label(self) -> str:
        return self._elapsed


class FakeSnapshot:
    def __init__(self, time_label: str) -> None:
        self.time_label = time_label


class RecordingTimelineHarness:
    """A built `RecordingTimelineView` plus the state its ports read."""

    def __init__(self, view, widgets, state) -> None:
        self.view = view
        self.record_btn = widgets["record_btn"]
        self.timeline_label = widgets["timeline_label"]
        self.slider = widgets["slider"]
        self.slider_time_label = widgets["slider_time_label"]
        self.state = state

    @property
    def toggles(self) -> int:
        return self.state["toggles"]

    @property
    def selections(self) -> list[int]:
        return self.state["selections"]

    def texts(self) -> dict[str, str | None]:
        return {
            "record_btn": self.record_btn.text,
            "timeline_label": self.timeline_label.text,
            "slider_time_label": self.slider_time_label.text,
        }


def build_recording_timeline_view(
    *,
    recording: bool = False,
    elapsed: str = "00:42",
    armed: bool = False,
    snapshot_labels: tuple[str, ...] = (),
    selected_index: int | None = None,
    waiting_mode: str | None = None,
) -> RecordingTimelineHarness:
    """Construct the pilot component through its real constructor."""
    state = {
        "recorder": FakeRecorder(is_recording=recording, elapsed=elapsed),
        "snapshots": [FakeSnapshot(label) for label in snapshot_labels],
        "selected": selected_index,
        "armed": armed,
        "waiting_mode": waiting_mode,
        "toggles": 0,
        "selections": [],
    }

    def on_toggle() -> None:
        state["toggles"] += 1

    def on_select(index: int) -> None:
        state["selections"].append(index)
        state["selected"] = index

    view = RecordingTimelineView(
        recorder=lambda: state["recorder"],
        snapshots=lambda: state["snapshots"],
        selected_index=lambda: state["selected"],
        recording_armed=lambda: state["armed"],
        waiting_mode=lambda: state["waiting_mode"],
        on_toggle_recording=on_toggle,
        on_snapshot_selected=on_select,
    )
    widgets = {
        "record_btn": FakeTimelineWidget("record_btn"),
        "timeline_label": FakeTimelineWidget("timeline_label"),
        "slider": FakeTimelineWidget("slider"),
        "slider_time_label": FakeTimelineWidget("slider_time_label"),
    }
    view.attach_widgets(**widgets)
    return RecordingTimelineHarness(view, widgets, state)
