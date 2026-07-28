"""The recording timeline strip, as a component rather than a mixin.

This is the step-18 pilot: one player-stats view object whose collaborators
arrive through its constructor instead of through a shared ``MegabonkApp``
``self``, and whose Qt widgets are private to it.

Scope, and why it is this small
===============================

Step 18 names "one player-stats view object" and points at ``LiveStatsTabMixin``.
Measured against the code, that conversion is not reachable inside step 18's
own bounds, and the reason is worth recording because it is a precondition for
step 19 rather than an opinion about it:

``PlayerStatsCardsMixin`` renders Weapons, Tomes, Chaos Tome, Damage Sources and
Items for **four scopes** (``live``, ``vod``, ``compare_a``, ``compare_b``) by
composing attribute names as strings against the shared object --
``getattr(self, f"{prefix}_weapons_layout", None)``, 22 such names in all. Each
of its 14 guards is a silent ``return`` when the lookup yields ``None``.
``LiveStatsTabMixin`` calls into it eight times with ``scope="live"``.

So making ``LiveStatsTabMixin``'s widgets private does not raise: it makes those
lookups return ``None`` and the panels stop rendering, silently, with no test
failure. Fixing that means converting the cards renderer too -- and the cards
renderer serves the Compare Runs scopes, which step 18 explicitly excludes.
Injecting the app object as a widget namespace is the step's stated rollback
condition. Hence the pilot is the part of the Live Stats tab that the cards
renderer does not reach.

The four widgets below were verified against that surface: none of them appears
in the cards renderer's 22 name templates, and before this commit each was
touched in exactly two places -- ``_build_live_stats_tab`` (creation) and
``refresh_player_stats_timeline_ui`` (rendering). ``player_stats_status_label``
was deliberately *excluded* despite sitting in the same strip, because
``display_player_stats`` and ``_reset_live_player_stats_ui`` also write it; a
widget with three writers is not yet ownable.

What the constructor makes visible
==================================

Seven dependencies that used to be ambient reads on ``self``. Reads are
suppliers rather than values because the app layer rebinds the underlying state
(``app/vod_capture.py`` reassigns the snapshot list; ``app/player_stats_refresh.py``
appends to it and moves the index), so a component holding the value would go
stale where a mixin reading ``self`` did not. That difference is exactly the
kind of thing a shared namespace hides.

No forwarding method is added to ``MegabonkApp``'s MRO. The two existing entry
points -- ``refresh_player_stats_timeline_ui`` and
``on_player_stats_slider_changed`` -- already existed and now delegate here.
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider

from app import config
from core.game_state import RuntimeGameMode
from ui.segmented_toggle import ROLE_GO, ROLE_HALT, SegmentedToggle
from ui.throttle import UiUpdateThrottle


class RecordingTimelineView:
    """Record button, timeline label, snapshot slider and its caption."""

    def __init__(
        self,
        *,
        recorder: Callable[[], object],
        snapshots: Callable[[], Sequence],
        selected_index: Callable[[], int | None],
        recording_armed: Callable[[], bool],
        waiting_mode: Callable[[], str | None],
        on_toggle_recording: Callable[[], None],
        on_snapshot_selected: Callable[[int], None],
        throttle: UiUpdateThrottle | None = None,
    ) -> None:
        self._recorder = recorder
        self._snapshots = snapshots
        self._selected_index = selected_index
        self._recording_armed = recording_armed
        self._waiting_mode = waiting_mode
        self._on_toggle_recording = on_toggle_recording
        self._on_snapshot_selected = on_snapshot_selected

        # Slider-drag rate limiting. `on_snapshot_selected` re-renders the whole
        # Live Stats tab -- stat rows, items, four cards -- and a drag emits one
        # `valueChanged` per pixel; injectable so a test can drive the
        # coalescing with a fake clock rather than an event loop.
        self._throttle = throttle or UiUpdateThrottle()
        self._requested_index: int | None = None

        self._record_btn = None
        self._timeline_label = None
        self._slider = None
        self._slider_time_label = None

    # -- construction ---------------------------------------------------------

    def install(self, content_layout) -> None:
        """Create the strip's widgets and place them in the tab's layout.

        The widget order, the stretch, and the two direct ``addWidget`` calls
        reproduce `_build_live_stats_tab`'s original block exactly; the strip's
        appearance is part of what the pilot must not change.
        """
        controls = QHBoxLayout()
        # The same control the header uses, for the same three reasons its
        # docstring gives -- and one more that is this strip's own: the old
        # button rendered *three* states as two pictures. `armed` and
        # `recording` both read "Stop Recording" in red, so "waiting for the
        # run to start" and "writing snapshots right now" were indistinguishable
        # without reading the line beside them. Here `armed` is the same Stop
        # segment in amber outline: pressing it still cancels, but nothing about
        # it claims a recording is running.
        #
        # It also measured 290x33 as `Start Recording (F8)` and 221x37 as
        # `Stop Recording` -- a 69x4 jump, with no size floor anywhere. Fixed
        # captions make that arithmetic go away rather than pinning it.
        self._record_btn = SegmentedToggle(
            (
                ("record", "●  Rec", ROLE_GO),
                ("stop", "■  Stop", ROLE_HALT),
            )
        )
        self._record_btn.activated.connect(lambda _key: self._on_toggle_recording())
        # The hotkey used to live inside the Start caption, which meant it
        # disappeared exactly when the user wanted it -- while recording, to
        # stop without reaching for the mouse. Beside the control it is true in
        # every state.
        hotkey_hint = QLabel(config.PLAYER_STATS_RECORD_HOTKEY.upper())
        hotkey_hint.setObjectName("hotkeyHint")
        self._timeline_label = QLabel("Live stats")
        controls.addWidget(self._record_btn)
        controls.addWidget(hotkey_hint, 0, Qt.AlignVCenter)
        controls.addStretch(1)
        controls.addWidget(self._timeline_label)
        content_layout.addLayout(controls)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setEnabled(False)
        self._slider.valueChanged.connect(self.handle_slider_value)
        content_layout.addWidget(self._slider)

        self._slider_time_label = QLabel("Timeline: live stats")
        content_layout.addWidget(self._slider_time_label)

        # Render the true state immediately, because nothing else will.
        # Every other caller of `refresh_player_stats_timeline_ui` is a
        # recording-lifecycle event, a capture, a scanner event or a dialog --
        # none of them fires at startup. Without this the button keeps the
        # caption baked in above and reads "Start Recording" even when
        # `AUTO_START_RECORDING` has already armed the app, so the first click
        # takes the *stop* branch ("cancel auto-start") and only the second
        # one arms. That is the double-click-to-start reported on 2026-07-19,
        # and it is a widget lying about state rather than a toggle bug.
        self.refresh()

    def attach_widgets(
        self, *, record_btn, timeline_label, slider, slider_time_label
    ) -> None:
        """Adopt pre-built widgets. For tests and for the trace harness only."""
        self._record_btn = record_btn
        self._timeline_label = timeline_label
        self._slider = slider
        self._slider_time_label = slider_time_label

    # -- rendering ------------------------------------------------------------

    def refresh(self, *, update_slider: bool = True) -> None:
        recorder = self._recorder()
        snapshots = self._snapshots()
        snapshot_count = len(snapshots)
        recording_armed = self._recording_armed()
        waiting_mode = self._waiting_mode()

        # Three states, three pictures. Stop is the live segment for both
        # `armed` and `recording` because pressing it is what either one
        # offers -- cancel the arming, or end the recording -- but `armed`
        # carries the variant, so red never appears before a snapshot does.
        if recorder.is_recording:
            self._record_btn.set_active("stop")
        elif recording_armed:
            self._record_btn.set_active("stop", variant="armed")
        else:
            self._record_btn.set_active("record")

        if recorder.is_recording and snapshot_count:
            self._slider.setEnabled(True)
            self._slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                index = self._selected_index()
                self._slider.setValue(index if index is not None else snapshot_count - 1)
        else:
            self._slider.setEnabled(False)
            self._slider.setMaximum(1)
            self._slider.setValue(0)

        if recorder.is_recording:
            prefix = f"Recording {recorder.elapsed_label()} | "
            if snapshot_count:
                selected = self._selected_index()
                mode = snapshots[selected].time_label if selected is not None else "--"
                self._timeline_label.setText(f"{prefix}{snapshot_count} snapshots | {mode}")
            elif waiting_mode == RuntimeGameMode.PAUSED_IN_GAME.value:
                self._timeline_label.setText(f"{prefix}Paused in game")
            else:
                self._timeline_label.setText(f"{prefix}No snapshots")
        elif recording_armed:
            self._timeline_label.setText("Recording armed | waiting for run")
        else:
            self._timeline_label.setText("Live stats")

        if recorder.is_recording and snapshot_count:
            first = snapshots[0].time_label
            last = snapshots[-1].time_label
            selected = self._selected_index()
            current = snapshots[selected].time_label if selected is not None else "--"
            self._slider_time_label.setText(
                f"Timeline: {first} - {last} | Selected: {current}"
            )
        elif recorder.is_recording:
            self._slider_time_label.setText(
                f"Timeline: recording {recorder.elapsed_label()} | waiting for first snapshot"
            )
        elif recording_armed:
            self._slider_time_label.setText("Timeline: recording armed | waiting for run")
        else:
            self._slider_time_label.setText("Timeline: live stats")

    # -- commands -------------------------------------------------------------

    def handle_slider_value(self, value) -> None:
        snapshots = self._snapshots()
        snapshot_count = len(snapshots)
        if snapshot_count == 0:
            return
        index = min(max(int(round(float(value))), 0), snapshot_count - 1)
        # With nothing queued the app's selected index is the truth, and
        # comparing against it is what keeps `refresh`'s own `setValue` from
        # looping back in here. With a frame queued the two differ, and the
        # queued index is what the slider is actually showing.
        current = self._requested_index if self._throttle.has_pending else self._selected_index()
        if current == index:
            return
        self._requested_index = index
        # Immediate and cheap, so the caption tracks the drag; selecting the
        # snapshot re-renders the whole Live Stats tab, so that is coalesced.
        self._slider_time_label.setText(self._timeline_range_text(index))
        self._throttle.request(lambda: self._select_snapshot(index))

    def _select_snapshot(self, index: int) -> None:
        self._on_snapshot_selected(index)
        self.refresh(update_slider=False)

    def _timeline_range_text(self, index: int) -> str:
        snapshots = self._snapshots()
        if not snapshots:
            return "Timeline: live stats"
        index = min(max(int(index), 0), len(snapshots) - 1)
        return (
            f"Timeline: {snapshots[0].time_label} - {snapshots[-1].time_label}"
            f" | Selected: {snapshots[index].time_label}"
        )
