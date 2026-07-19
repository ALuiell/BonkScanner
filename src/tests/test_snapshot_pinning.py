"""Scrubbing the Live Stats timeline must survive the next refresh tick.

Reported from a live drive on 2026-07-19: while recording, dragging the
timeline to an earlier snapshot showed that snapshot's time, kills and items,
and roughly a second later the Run Summary and stage summary cards reverted to
the live run.

Cause, and it long predates the step-18 pilot that made the path easy to reach:
every live refresh tick ran `player_stats_selected_snapshot_index = None` and
repainted live values, with no guard for a selection the user had made by hand.
`app/player_stats_refresh.py` was byte-identical across the pilot's two commits.

These tests drive `refresh_live_player_stats_now` itself rather than the
predicate alone, because the predicate being correct proves nothing about the
two call sites that have to consult it -- the capture branch and the live
branch.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
from app.player_stats_refresh import player_stats_snapshot_is_pinned
from app.snapshot_store import LiveSnapshotStore
from core.game_state import RuntimeGameMode, RuntimeGameState
from gui_app import MegabonkApp
from ui.tabs.player_stats.live_stats import pin_for_selection


class FakeRecorder:
    def __init__(self, *, is_recording=True, should_capture=False) -> None:
        self.is_recording = is_recording
        self._should_capture = should_capture
        self.captures = 0

    def should_capture(self) -> bool:
        return self._should_capture

    def capture(self, **kwargs):
        self.captures += 1
        return SimpleNamespace(time_label=f"cap{self.captures}", stats={}, items=())

    def elapsed_label(self) -> str:
        return "00:42"


class RefreshDouble:
    """A plain stub, deliberately not `object.__new__(MegabonkApp)`.

    `PlayerStatsRefreshMixin` has not been converted to a component, so per the
    step-18 phase-1 migration plan this call site keeps an unbound call --
    `MegabonkApp.refresh_live_player_stats_now(double)` -- but against a plain
    namespace rather than a borrowed MRO. That keeps the `object.__new__`
    inventory confined to the one module it already occupies, which
    `test_componentization_inventory` enforces; it caught this file on the
    first run.

    Everything the refresh path reaches is assigned below, so a missing
    dependency surfaces as an explicit AttributeError naming it, rather than
    resolving silently through sixteen mixins.
    """


def build_refresh_app(*, snapshots, selected, pinned, should_capture=False):
    app = RefreshDouble()
    app.player_stats_vod_recorder = FakeRecorder(should_capture=should_capture)
    app.player_stats_vod_snapshots = list(snapshots)
    app.player_stats_selected_snapshot_index = selected
    app.player_stats_snapshot_pinned = pinned
    app.player_stats_auto_start_detection_streak = 0
    app.player_stats_recording_armed = False
    app.player_stats_auto_recording_suppressed = False

    rendered = {"live": 0, "snapshot": []}
    app._player_stats_view = SimpleNamespace(
        display_player_stats=lambda *a, **k: rendered.__setitem__("live", rendered["live"] + 1),
        display_player_stats_snapshot=lambda snap, **k: rendered["snapshot"].append(snap.time_label),
        refresh_player_stats_timeline_ui=lambda *a, **k: None,
        _refresh_vods_list_if_visible=lambda: None,
        mark_overlay_read_failed=lambda **k: None,
        refresh_session_tracked_item_stats_ui=lambda: None,
        update_overlay_state_from_tracker=lambda: None,
    )
    app.rendered = rendered

    app._is_live_stats_tab_active = lambda: True
    app._read_live_player_stats_data = lambda: (
        {}, (), True, (), True, (), True, (), True, (), True,
        21.5, None, None, 37, 2, 111, 0, None, (), True,
    )
    app._runtime_state_for_refresh = lambda: RuntimeGameState(mode=RuntimeGameMode.IN_GAME)
    app._maybe_auto_start_player_stats_recording = lambda **k: None
    app.live_run_tracker = SimpleNamespace(
        update=lambda *a, **k: None,
        update_chests_and_keys=lambda *a, **k: None,
        stage_summary_rows=lambda: [],
        runtime_snapshot=lambda: SimpleNamespace(),
        current_ui_kps=lambda: None,
        current_minute_avg_kps=lambda: None,
        current_five_minute_avg_kps=lambda: None,
    )
    # The real store, not a fake: it is cheap and pure, and the roadmap's
    # "was this test asserting a fiction?" rule applies to exactly this kind
    # of collaborator.
    store = LiveSnapshotStore()
    app._ensure_live_snapshot_store = lambda: store
    app.log = lambda *a, **k: None
    app.overlay_state_store = None
    return app


def snap(label):
    return SimpleNamespace(time_label=label, stats={}, items=())


class PinnedSnapshotSurvivesRefreshTests(unittest.TestCase):
    def _refresh(self, app):
        # `build_vod_capture_kwargs` reads a real RuntimeStateSnapshot; the
        # capture payload is not what these tests are about.
        with patch.object(config, "AUTO_START_RECORDING", False), patch(
            "app.player_stats_refresh.build_vod_capture_kwargs", lambda *a, **k: {}
        ):
            return MegabonkApp.refresh_live_player_stats_now(app)

    def test_pinned_snapshot_is_not_repainted_with_live_values(self) -> None:
        """The reported bug. Fails before the fix: rendered['live'] would be 1."""
        app = build_refresh_app(
            snapshots=[snap("00:10"), snap("00:20"), snap("00:30")],
            selected=0,
            pinned=True,
        )

        self._refresh(app)

        self.assertEqual(0, app.rendered["live"])
        self.assertEqual(0, app.player_stats_selected_snapshot_index)

    def test_unpinned_refresh_still_repaints_live_and_clears_selection(self) -> None:
        """The pin must not become a permanent freeze."""
        app = build_refresh_app(
            snapshots=[snap("00:10"), snap("00:20")], selected=1, pinned=False
        )

        self._refresh(app)

        self.assertEqual(1, app.rendered["live"])
        self.assertIsNone(app.player_stats_selected_snapshot_index)

    def test_capture_does_not_yank_the_selection_off_a_pinned_snapshot(self) -> None:
        """The slider must not jump to the newest snapshot under the user."""
        app = build_refresh_app(
            snapshots=[snap("00:10"), snap("00:20")],
            selected=0,
            pinned=True,
            should_capture=True,
        )

        self._refresh(app)

        self.assertEqual(3, len(app.player_stats_vod_snapshots))
        self.assertEqual(0, app.player_stats_selected_snapshot_index)
        self.assertEqual([], app.rendered["snapshot"])

    def test_capture_still_advances_when_not_pinned(self) -> None:
        app = build_refresh_app(
            snapshots=[snap("00:10")], selected=0, pinned=False, should_capture=True
        )

        self._refresh(app)

        self.assertEqual(1, app.player_stats_selected_snapshot_index)
        self.assertEqual(["cap1"], app.rendered["snapshot"])


class PinPredicateTests(unittest.TestCase):
    def test_pin_is_ignored_when_the_snapshot_list_was_emptied(self) -> None:
        """A stale pin must not freeze the view -- the range check is the guard."""
        owner = SimpleNamespace(
            player_stats_snapshot_pinned=True,
            player_stats_selected_snapshot_index=4,
            player_stats_vod_snapshots=[],
        )

        self.assertFalse(player_stats_snapshot_is_pinned(owner))

    def test_pin_is_ignored_without_a_selection(self) -> None:
        owner = SimpleNamespace(
            player_stats_snapshot_pinned=True,
            player_stats_selected_snapshot_index=None,
            player_stats_vod_snapshots=[snap("a")],
        )

        self.assertFalse(player_stats_snapshot_is_pinned(owner))

    def test_absent_flag_defaults_to_unpinned(self) -> None:
        """App doubles built without __init__ must not read as pinned."""
        owner = SimpleNamespace(
            player_stats_selected_snapshot_index=0,
            player_stats_vod_snapshots=[snap("a")],
        )

        self.assertFalse(player_stats_snapshot_is_pinned(owner))


class SliderPinsAndUnpinsTests(unittest.TestCase):
    """The slider alone must be able to clear the pin it sets."""

    def test_dragging_to_an_earlier_snapshot_pins(self) -> None:
        self.assertTrue(pin_for_selection(0, 3))
        self.assertTrue(pin_for_selection(1, 3))

    def test_dragging_to_the_newest_snapshot_unpins(self) -> None:
        self.assertFalse(pin_for_selection(2, 3))

    def test_a_single_snapshot_is_always_the_newest(self) -> None:
        self.assertFalse(pin_for_selection(0, 1))


if __name__ == "__main__":
    unittest.main()
