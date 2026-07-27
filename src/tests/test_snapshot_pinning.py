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
from app.player_stats_memory import player_stats_memory
from app.snapshot_selection import player_stats_snapshot_is_pinned
from app.snapshot_store import LiveSnapshotStore
from tests.support.run_lifecycle import install_run_lifecycle
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
    # Three doubles, because step 19 split the one nine-operation port into the
    # three features that actually implement it. Faking them separately is the
    # point: a single object satisfying all nine is what let the app layer
    # reach the overlay and the recordings list through "the player stats
    # view" without anything noticing.
    app._player_stats_view = SimpleNamespace(
        display_player_stats=lambda *a, **k: rendered.__setitem__("live", rendered["live"] + 1),
        display_player_stats_snapshot=lambda snap, **k: rendered["snapshot"].append(snap.time_label),
        refresh_player_stats_timeline_ui=lambda *a, **k: None,
        set_recording_status_text=lambda text: None,
        set_mob_kills_text=lambda text: None,
        set_in_game_time_text=lambda text: None,
    )
    app._overlay_view = SimpleNamespace(
        mark_overlay_read_failed=lambda **k: None,
        refresh_session_tracked_item_stats_ui=lambda: None,
        update_overlay_state_from_tracker=lambda: None,
    )
    app._recordings_list_view = SimpleNamespace(
        _refresh_vods_list_if_visible=lambda: None,
    )
    app.rendered = rendered

    app._is_live_stats_tab_active = lambda: True
    # `refresh_live_player_stats_now` reads through `player_stats_memory(app)`
    # now, so the whole-tuple stub lands on the resolved service rather than the
    # app double. The resolver takes the `__dict__` branch (no coordinator) and
    # caches the same instance the refresh path re-resolves.
    player_stats_memory(app)._read_live_player_stats_data = lambda _context=None: (
        {}, (), True, (), True, (), True, (), True, (), True,
        21.5, None, None, 37, 2, 111, 0, None, (), True, False,
    )
    # A real `RunLifecycle` with its game-state read faked, not a stubbed
    # method: `state_for_refresh` with a cold cache falls through to the
    # uncached read, so this drives the service's own branch rather than
    # replacing it.
    install_run_lifecycle(
        app, game_states=lambda: RuntimeGameState(mode=RuntimeGameMode.IN_GAME)
    )
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
    # No coordinator on an app double, so this is where the resolver looks.
    app._live_snapshot_store = store
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


class FastTaskStageSummaryPinTests(unittest.TestCase):
    """The *fast* tasks must honour the pin too, not just the refresh tick.

    Reported from a live drive on 2026-07-20: with a recording running,
    scrubbing the timeline left showed the historical stage summary and then it
    "flickered" back to live values, while every other panel stayed put.

    Cause: `d7d1350` put the pin guard on `refresh_live_player_stats_now`, and
    `9c59abd` -- which moved these two stage-summary writes out of the widget
    and behind `PlayerStatsView` -- created two more writers that never got it.
    They run at the fast cadence, so they repainted live rows roughly once a
    second. Only the stage summary and the mob-kills line misbehaved because
    those are the only two things the fast tasks write.

    Driving the tasks rather than the predicate, for the reason this module's
    header already gives: a correct predicate proves nothing about a call site
    that does not consult it. Before the fix both tests below fail.
    """

    def build_owner(self, *, pinned: bool):
        recorded = {
            "stage_rows": [],
            "mob_kills": [],
            "powerups": [],
            "in_game_time": [],
        }

        # A plain owner, not a `RefreshTasksMixin` subclass: step 20f converted
        # the mixin into the `RefreshTasks` service, so the tasks are resolved
        # with `refresh_tasks(owner)` below. The owner still supplies exactly the
        # collaborators the service's constructor lambdas reach for, which is
        # what keeps this driving the real path rather than a stub.
        class Owner:
            def __init__(self) -> None:
                self.player_stats_vod_snapshots = [snap("00:10"), snap("00:20")]
                self.player_stats_selected_snapshot_index = 0
                self.player_stats_snapshot_pinned = pinned
                # The fast tasks reach the client through
                # `player_stats_memory(self)._get_player_stats_client()`, whose
                # service reads `self.player_stats_client`. Feeding the fake here
                # (rather than overriding the method) drives the real service
                # path. The two reconnect streaks that stood here are the
                # service's fields now (step 20).
                self.player_stats_client = SimpleNamespace(
                    get_run_timer=lambda: 30.0,
                    get_killed_mobs=lambda: 100,
                    get_stage_timer_context=lambda: (25.0, 2, 480.0),
                    resolve_owner_stats=lambda: 0x1234,
                    get_powerup_tracking_snapshot=lambda owner_stats: SimpleNamespace(),
                )
                self.live_run_tracker = SimpleNamespace(
                    track_kills=lambda *a: None,
                    update_fast_run_timer=lambda *a: None,
                    current_ui_kps=lambda: 12,
                    current_minute_avg_kps=lambda: 10,
                    current_five_minute_avg_kps=lambda: 8,
                    chaos_tome_snapshot=lambda: None,
                    stage_summary_rows=lambda: [{"stage": "live"}],
                    update_fast_stage_timer=lambda **k: None,
                    mark_feature_available=lambda feature: None,
                )
                self._player_stats_view = SimpleNamespace(
                    set_stage_summary_rows=lambda rows: recorded["stage_rows"].append(rows),
                    set_mob_kills_text=lambda text: recorded["mob_kills"].append(text),
                    set_in_game_time_text=(
                        lambda text: recorded["in_game_time"].append(text)
                    ),
                    set_kps_averages_text=lambda text: None,
                    set_chaos_tome_card=lambda chaos_tome: None,
                )

            def _is_live_stats_tab_active(self) -> bool:
                return True

            def update_overlay_state_from_tracker(self) -> None:
                pass

            # The combat task's other overlay command. Unlike the panel writes
            # above it is *not* pin-guarded -- the in-game overlay always shows
            # live values -- so it is here only to keep the real call path
            # intact for the assertions that are about the pin.
            def refresh_in_game_overlay_kps(self) -> None:
                pass

        return Owner(), recorded

    def test_powerups_task_does_not_repaint_the_card_while_pinned(self) -> None:
        """The third writer, found by counting them rather than by the report.

        `display_player_stats` paints the Powerups card from the *snapshot's*
        stats; `refresh_powerups_card` repaints it from the live tracker. Both
        the success and the failure path of the task called it unguarded.
        """
        from app.refresh_coordinator import RefreshTickContext
        from app.refresh_tasks import refresh_tasks

        for pinned, expected in ((True, 0), (False, 1)):
            owner, recorded = self.build_owner(pinned=pinned)
            owner.live_run_tracker.update_powerups = lambda snapshot: True
            owner._player_stats_view.refresh_powerups_card = (
                lambda: recorded["powerups"].append(1)
            )
            refresh_tasks(owner)._refresh_powerups_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0))
            self.assertEqual(expected, len(recorded["powerups"]))

    def test_event_timer_task_does_not_repaint_stage_summary_while_pinned(self) -> None:
        from app.refresh_coordinator import RefreshTickContext
        from app.refresh_tasks import refresh_tasks

        owner, recorded = self.build_owner(pinned=True)
        refresh_tasks(owner)._refresh_event_timer_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0))
        self.assertEqual([], recorded["stage_rows"])

        owner, recorded = self.build_owner(pinned=False)
        refresh_tasks(owner)._refresh_event_timer_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0))
        self.assertEqual([[{"stage": "live"}]], recorded["stage_rows"])

    def test_combat_metrics_task_does_not_repaint_stage_summary_while_pinned(self) -> None:
        from app.refresh_coordinator import RefreshTickContext
        from app.refresh_tasks import refresh_tasks

        owner, recorded = self.build_owner(pinned=True)
        refresh_tasks(owner)._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0))
        self.assertEqual([], recorded["stage_rows"])
        self.assertEqual([], recorded["mob_kills"])
        # The run clock is written earlier in the task than the other two, so it
        # needs the pin guard in its own right rather than inheriting theirs.
        self.assertEqual([], recorded["in_game_time"])

        owner, recorded = self.build_owner(pinned=False)
        refresh_tasks(owner)._refresh_combat_metrics_task(RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0))
        self.assertEqual([[{"stage": "live"}]], recorded["stage_rows"])
        self.assertEqual(1, len(recorded["mob_kills"]))
        self.assertEqual(["In-Game Time: 00:30"], recorded["in_game_time"])
