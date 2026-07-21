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

from ui.tabs.player_stats.items_section import ItemsSectionView
from app.vod_library import VodLibrary
from ui.tabs.player_stats.live_stats import LiveStatsTab
from ui.tabs.player_stats.recordings import RecordingsTab
from ui.tabs.player_stats.recording_timeline import RecordingTimelineView
from ui.tabs.player_stats.stat_cards import StatCardsView


class RecordingStatCardsView:
    """Records what a tab asked the stat-card panels to render.

    Replaces the four ``app.display_weapon_cards = lambda *a, **k: None``
    stubs the suite used before step 19. Those stubs stood in for methods that
    resolved through ``MegabonkApp``'s MRO; the tabs now hold a real
    collaborator, so the double is an object rather than four loose attributes
    and the calls it absorbs are assertable instead of discarded.

    Deliberately not a ``MagicMock``: the signatures are pinned here, so
    changing one on ``StatCardsView`` fails these tests loudly rather than
    being silently accepted.
    """

    def __init__(self) -> None:
        self.weapons: list[tuple[tuple, str | None]] = []
        self.tomes: list[tuple[tuple, str | None]] = []
        self.chaos: list[tuple[object, str | None]] = []
        self.damage_sources: list[tuple[tuple, str | None]] = []
        self.invalidations = 0

    def invalidate(self) -> None:
        self.invalidations += 1

    def display_weapons(self, weapons, *, status_text: str | None = None) -> None:
        self.weapons.append((tuple(weapons or ()), status_text))

    def display_tomes(self, tomes, *, status_text: str | None = None) -> None:
        self.tomes.append((tuple(tomes or ()), status_text))

    def display_chaos_tome(self, chaos_tome, *, status_text: str | None = None) -> None:
        self.chaos.append((chaos_tome, status_text))

    def display_damage_sources(self, damage_sources, *, status_text: str | None = None) -> None:
        self.damage_sources.append((tuple(damage_sources or ()), status_text))


class RecordingItemsSectionView:
    """Records what a tab asked the Items panel to render.

    Same role as `RecordingStatCardsView`, for the surface that
    `_update_items_section` used to serve. The scope argument is gone: each
    scope now holds its own view, so "which scope" is answered by *which
    object* was called rather than by a string passed to a shared one.
    """

    def __init__(self) -> None:
        self.updates: list[tuple[tuple, str | None]] = []
        self.toggles = 0
        self.collapses = 0

    def update(self, items=(), *, items_text: str | None = None) -> None:
        self.updates.append((tuple(items or ()), items_text))

    def toggle_expanded(self) -> None:
        self.toggles += 1

    def collapse(self) -> None:
        self.collapses += 1

    def on_sort_changed(self) -> None:
        self.updates.append(("<sort>", None))


def items_section_over(label) -> ItemsSectionView:
    """A real `ItemsSectionView` that writes into `label` and nothing else.

    For the three tests that assert on the *rendered* items text rather than
    on the call. Before step 19 they reached the renderer through the shared
    `self`'s widget, so they never named `_update_items_section` and did not
    show up as coverage in a grep for it -- but they are the only assertions
    the items path has, and a recording double would silently swallow them.

    The group, rarity label, toggle button and sort combo are absent, which
    the view already guards for; passing `None` keeps these tests asserting
    exactly what they asserted before.
    """
    return ItemsSectionView(
        group=None,
        label=label,
        rarity_label=None,
        toggle_btn=None,
        sort_combo=None,
    )


class FakeCardsLayout:
    """Enough QLayout surface for `StatCardsView` to render into."""

    def __init__(self) -> None:
        self.items: list = []

    def addLayout(self, layout) -> None:
        self.items.append(("layout", layout))

    def addWidget(self, widget) -> None:
        self.items.append(("widget", widget))

    def addStretch(self, stretch) -> None:
        self.items.append(("stretch", stretch))

    def count(self) -> int:
        return len(self.items)

    def takeAt(self, index):
        return self.items.pop(index)


def build_stat_cards_view() -> tuple[StatCardsView, dict]:
    """Construct `StatCardsView` through its real constructor.

    Returns the view and the eight widgets it owns, so a test can assert on
    the status lines without reaching into the view's privates.
    """
    widgets = {
        "weapons_layout": FakeCardsLayout(),
        "weapons_status_label": FakeTimelineWidget("weapons_status_label"),
        "tomes_layout": FakeCardsLayout(),
        "tomes_status_label": FakeTimelineWidget("tomes_status_label"),
        "chaos_layout": FakeCardsLayout(),
        "chaos_status_label": FakeTimelineWidget("chaos_status_label"),
        "damage_sources_layout": FakeCardsLayout(),
        "damage_sources_status_label": FakeTimelineWidget("damage_sources_status_label"),
    }
    return StatCardsView(**widgets), widgets


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


class RecordingTimeline:
    """Stands in for the Qt timeline strip on a tab that was never built.

    `build()` is what constructs the real `RecordingTimelineView`, and it needs
    offscreen Qt. Every test that reaches `refresh_player_stats_timeline_ui`
    asserts that it was *called*, not what it painted -- the painting is
    covered by `test_recording_timeline_view.py` and the differential trace --
    so recording the calls is the honest stand-in. Before step 19 these tests
    stubbed the method on the app instead, which asserted even less.
    """

    def __init__(self) -> None:
        self.refreshes: list[bool] = []
        self.slider_values: list = []

    def refresh(self, *, update_slider: bool = True) -> None:
        self.refreshes.append(update_slider)

    def handle_slider_value(self, value) -> None:
        self.slider_values.append(value)

    def install(self, layout) -> None:  # pragma: no cover -- build() is not run
        raise AssertionError("RecordingTimeline is for tabs that are never built")


class RecordingPlayerStatsView:
    """Records what the app layer asked the Live Stats tab to render.

    Replaces the loose `app.display_player_stats = lambda *a, **k: None` stubs
    the suite used while `LiveStatsTabMixin` was a base of `MegabonkApp`. Those
    stood in for methods that resolved through the MRO; the app now holds a
    real collaborator at `_player_stats_view`, so the double is one object and
    the calls it absorbs are assertable instead of discarded.

    Deliberately not a `MagicMock`: every signature here is pinned against
    `PlayerStatsView`, so adding an operation to the port -- or changing one --
    fails these tests loudly rather than being silently accepted. That is the
    same failure-mode argument the module docstring makes for
    `object.__new__`.
    """

    def __init__(self) -> None:
        self.displays: list[dict] = []
        self.snapshots: list[tuple] = []
        self.timeline_refreshes: list[bool] = []
        self.status_texts: list[str] = []
        self.mob_kills_texts: list[str] = []
        self.stage_summary_rows: list = []
        self.powerups_refreshes = 0

    def display_player_stats(self, stats, items=(), **kwargs) -> None:
        self.displays.append({"stats": stats, "items": tuple(items), "kwargs": kwargs})

    def display_player_stats_snapshot(self, snapshot, *, items_text=None) -> None:
        self.snapshots.append((snapshot, items_text))

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True) -> None:
        self.timeline_refreshes.append(update_slider)

    def set_recording_status_text(self, text: str) -> None:
        self.status_texts.append(text)

    def set_mob_kills_text(self, text: str) -> None:
        self.mob_kills_texts.append(text)

    def set_stage_summary_rows(self, rows) -> None:
        self.stage_summary_rows.append(rows)

    def refresh_powerups_card(self) -> None:
        self.powerups_refreshes += 1


def build_live_stats_tab(**overrides) -> LiveStatsTab:
    """Construct `LiveStatsTab` through its **real** constructor.

    The alternative to `object.__new__(MegabonkApp)` for the Live Stats tab,
    and the reason this module exists: adding a constructor argument breaks
    every call site here loudly, where `object.__new__` absorbs a new
    dependency silently and surfaces it as an `AttributeError` in whichever
    test happens to reach it first.

    `build()` is **not** called -- that needs real offscreen Qt and is covered
    by `tools/step19_live_stats_smoke.py` and the differential trace. Tests
    that need widgets assign the private ones they assert on, which is honest
    about the fact that they are testing a renderer against stand-in widgets.
    """
    defaults = {
        "tabview": None,
        "live_run_tracker": lambda: None,
        "vod_recorder": lambda: None,
        "vod_snapshots": lambda: [],
        "selected_snapshot_index": lambda: None,
        "recording_waiting_mode": lambda: None,
        "ensure_live_snapshot_store": lambda: None,
        "is_recording_armed": lambda: False,
        "on_toggle_recording": lambda: None,
        "on_snapshot_selected": lambda index, *, pinned: None,
    }
    unknown = set(overrides) - set(defaults)
    assert not unknown, f"not LiveStatsTab constructor arguments: {sorted(unknown)}"
    defaults.update(overrides)
    view = LiveStatsTab(**defaults)
    view._recording_timeline = RecordingTimeline()
    return view


#: What an app double calls a Live Stats widget, mapped to what the tab calls
#: it. Spelled out rather than derived, so renaming one on `LiveStatsTab` fails
#: here loudly instead of silently dropping a test's only assertion target --
#: which is the shape of fault step 19 shipped twice.
ADOPTED_WIDGETS = {
    "player_stats_status_label": "_status_label",
    "player_stats_rows": "_stat_value_rows",
    "player_stats_mob_kills_label": "_mob_kills_label",
    "player_stats_banishes_label": "_banishes_label",
    "player_stats_in_game_time_label": "_in_game_time_label",
    "player_stats_chests_per_minute_label": "_chests_per_minute_label",
    "player_stats_powerups_duration_label": "_powerups_duration_label",
    "player_stats_level_label": "_level_label",
    "player_stats_new_items_label": "_new_items_label",
    "player_stats_kps_averages_label": "_kps_averages_label",
    "player_stats_stage_summary_labels": "_stage_summary_labels",
    "player_stats_chests_card_values": "_chests_card_values",
    "player_stats_powerups_group": "_powerups_group",
    "player_stats_live_powerup_labels": "_powerup_labels",
    "_live_stat_cards": "_stat_cards",
    "_live_items_section": "_items_section",
}


def attach_player_stats_view(app) -> LiveStatsTab:
    """Give `app` a **real** `LiveStatsTab`, adopting the widgets it carries.

    Idempotent: a test that stubs two operations gets one view back both
    times.

    Deliberately the real tab rather than a recording double. Several of these
    tests assert on the *rendered* text -- "the real formatter, through the
    real writer" -- and a recorder would swallow those assertions silently.
    That is the mistake step 19 recorded for the items path: a grep by method
    name undercounts coverage in a shared-namespace codebase, because the
    widget is the other way in. Tests that only care that an operation was
    called still override that one operation on the instance.

    Before step 19 none of this was needed: `LiveStatsTabMixin` was a base of
    `MegabonkApp`, so the shared namespace *was* the view, and every one of
    these widgets was a public name on it.
    """
    view = app.__dict__.get("_player_stats_view")
    if view is not None:
        return view
    view = build_live_stats_tab(
        live_run_tracker=lambda: getattr(app, "live_run_tracker", None),
        vod_snapshots=lambda: getattr(app, "player_stats_vod_snapshots", []),
        vod_recorder=lambda: getattr(app, "player_stats_vod_recorder", None),
        selected_snapshot_index=lambda: getattr(
            app, "player_stats_selected_snapshot_index", None
        ),
        ensure_live_snapshot_store=lambda: app._ensure_live_snapshot_store(),
    )
    for public, private in ADOPTED_WIDGETS.items():
        if public in app.__dict__:
            setattr(view, private, app.__dict__[public])
    app._player_stats_view = view
    return view


def build_recordings_tab(**overrides) -> RecordingsTab:
    """Construct `RecordingsTab` through its **real** constructor.

    Added by step 21c, the step that converted the tab -- the migration order
    this module's header states: a call site is migrated by the step that
    converts its subject, never in bulk ahead of it.

    `build()` is **not** called, for the same reason `build_live_stats_tab`
    does not call it: that needs real offscreen Qt. Tests that need widgets
    assign the private ones they assert on, and the *built* tab is covered by
    `tools/step21_vod_trace.py`, which drives it offscreen through seventeen
    scenarios.

    `vod_library` defaults to a real `VodLibrary` over an empty index, not a
    stub: it is the object step 21 exists to introduce, and a test that stubs
    it proves nothing about the wiring. Pass one built over a fake
    `load_cached`/`refresh_index` to drive the index.
    """
    defaults = {
        "tabview": None,
        "vod_library": VodLibrary(load_cached=tuple, refresh_index=tuple),
        "window": lambda: None,
        "vod_recorder": lambda: None,
        "is_active": lambda: True,
        "log": lambda *args, **kwargs: None,
        "schedule": None,
    }
    unknown = set(overrides) - set(defaults)
    assert not unknown, f"not RecordingsTab constructor arguments: {sorted(unknown)}"
    defaults.update(overrides)
    return RecordingsTab(**defaults)
