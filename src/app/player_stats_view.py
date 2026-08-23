"""The ports the player-stats app layer renders through.

``app/`` may not import ``ui/``. Before this module, ``player_stats_refresh``
and ``vod_capture`` reached the UI anyway -- through the shared ``self``, which
the layering table cannot see and the hidden-dependency metric only counts while
the code still sits in one of the eight original mixins. Moving that code to
``app/`` in step 14c did not remove those edges; it removed them from view.

So they are named here instead: no widgets, no Qt types. This is the step-10d
inversion (``app/update_flow.py`` + ``ui/update_prompt.py``) applied to the
refresh path -- the difference between an implicit contract and a stated one.

Three ports, not one -- and why that changed at step 19
======================================================

Step 14c named a single nine-operation ``PlayerStatsView``, after what the app
layer needed rather than after who implements it. Step 19 measured where those
nine actually live, and they are not one feature's:

===========  =========================================  ===========
Operations   Implemented in                             Owning step
===========  =========================================  ===========
5            ``ui/tabs/player_stats/live_stats.py``     19
3            ``gui_overlay.py``                         24
1            ``gui_layout.py``                          26
===========  =========================================  ===========

That is why ``player_stats_view(owner)`` had to return ``owner``: only
``MegabonkApp`` satisfies all nine at once. Step 19's exit criterion --
"``player_stats_view`` has no ambient-owner fallback in production" -- was
therefore unreachable inside step 19's own bounds. Injecting a real view meant
either converting the overlay and layout mixins, which step 19 forbids, or a
composite delegating four operations back to the ambient ``owner``, which is
step 18's stated rollback condition.

Splitting the port by implementer is what unblocks it, and it is not the
"changed address, paid nothing" move the roadmap warns about: those four
operations were never Player Stats' debt. They are the overlay's and the
layout's, mislabelled by a port named after its caller. Each now sits behind
the accessor its own step will convert, and each accessor's fallback dies with
that step -- 24 for ``overlay_view``, 26 for ``recordings_list_view``.

Only ``PlayerStatsView`` was expected to lose its ambient fallback at step 19.
The other two kept it *by design*, and the docstrings said which step removed
them, so a later reader could tell a scheduled fallback from a forgotten one.
**All three are closed as of step 26**: ``_overlay_view`` is injected by
``gui_app.__init__`` and ``_recordings_list_view`` by
``gui_layout._build_tab_router``. The ``owner`` branch in each resolver below
survives only for app doubles built with ``object.__new__``, which inject
neither.

What this deliberately does **not** do
======================================

- It does not move any implementation. ``gui_overlay.py`` and ``gui_layout.py``
  are untouched; ``MegabonkApp`` still satisfies all three protocols through
  its mixins, so every default dispatch is byte-for-byte what it was.
- It does not make the app layer *push* rendering decisions to the UI.
  ``refresh_live_player_stats_now`` still decides what to display and when;
  splitting "read a coherent sample" from "project it for a consumer" is the
  composable-reads design.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlayerStatsView(Protocol):
    """The Player Stats tabs, as the app layer sees them.

    Implemented by ``ui/tabs/player_stats/live_stats.py``. This is the port
    step 19 converts to a real injected object.
    """

    def display_player_stats(self, stats, items, **kwargs) -> None:
        """Render a live reading into the Live Stats tab."""

    def display_player_stats_snapshot(self, snapshot, *, items_text) -> None:
        """Render a captured recording snapshot into the Live Stats tab."""

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True) -> None:
        """Re-render the recording timeline after its snapshot list changed.

        `update_slider` was missing from this declaration until step 19, while
        two callers -- `gui_scanner.update_timer` and
        `gui_dialogs.SettingsDialog.save` -- passed it. Both sat outside
        `app/`, which is the only tree `test_view_ports.py` scans, so nothing
        reported the gap.
        """

    def set_recording_status_text(self, text: str) -> None:
        """Set the Live Stats status line (recording / paused / armed)."""

    def set_mob_kills_text(self, text: str) -> None:
        """Set the Live Stats mob-kills line."""

    def set_kps_averages_text(self, text: str) -> None:
        """Set the Live Stats 1-minute / 5-minute KPS line.

        The averages come from the same `_recent_kills_history` the instant KPS
        does, and `set_mob_kills_text` above has painted that at the fast
        cadence since step 17 -- so one line of the pair was live and the line
        under it was a 10 s reading of the same deque.
        """

    def set_chaos_tome_card(self, chaos_tome) -> None:
        """Render the Chaos Tome card from a tracker snapshot.

        `CHAOS_TRACKING_STATE` is read every fast tick and folded by
        `update_chaos_tome`, but the card was painted only by the 10 s payload.
        The Twitch `!chaos` command reads the tracker at command time, so chat
        was seeing rolls before the app's own card did.
        """

    def set_charge_shrine_card(self, shrines) -> None:
        """Render the Charge Shrine card from the fast tracker snapshot."""

    def set_in_game_time_text(self, text: str) -> None:
        """Set the Live Stats in-game time line.

        Its neighbours in that card were already fast -- `set_mob_kills_text`
        since step 17 and the Stage Summary rows since step 19 -- while the run
        clock beside them was written only by the 10 s `display_player_stats`
        payload. Two clocks in one card advancing at different rates read as a
        bug whichever one you trust.
        """

    def refresh_powerups_card(self) -> None:
        """Re-render the Powerups card from the tracker's current snapshot.

        Added at step 19 alongside `set_stage_summary_rows`, and for the same
        reason: `app/refresh_tasks.py` called it as `self._refresh_live_powerups_label()`
        through the shared namespace, which is a UI call the layer table
        forbids and the port existed to name. Renamed on the way through --
        it re-renders a card, and has not written a single label since the
        powerups card replaced the one-line readout.
        """

    def set_stage_summary_rows(self, rows) -> None:
        """Render stage-summary rows into the Live Stats tab.

        Added at step 19. Before it, `app/refresh_tasks.py` reached
        `self.player_stats_stage_summary_labels` -- a Qt widget -- and called
        the writer on it directly, which is the same leak step 17 closed for
        the mob-kills line. Six operations now, not five.
        """

    def set_items(self, items) -> None:
        """Render the live inventory into the Live Stats items panel.

        The same shape as `set_stage_summary_rows` and for the same reason: a
        fast task owns one panel's freshness and must not go through the
        whole-card `display_player_stats` payload to write it. Added with the
        `passive_items` task, which already holds the inventory the panel
        renders -- so this repaint costs no read.
        """

    def refresh_build_progression(self) -> None:
        """Re-render Build Progression from its shared evaluated snapshot.

        Existing refresh tasks call this port after publishing run-clock,
        inventory, stage-timer, or full-stat data.  The view never reads game
        memory and Build Progression does not add a scheduler task of its own.
        """


@runtime_checkable
class OverlayView(Protocol):
    """The OBS overlay and session panel, as the refresh path sees them.

    Implemented by ``gui_overlay.Overlay``, injected as ``_overlay_view`` by
    ``gui_app.__init__`` the line after it builds the component. The fallback
    to the app object is closed: step 24c converted the mixin but left the
    app's three forwarding methods answering this port, so the resolver kept
    returning the application and the protocol kept matching by accident until
    step 26 named the real implementer.
    """

    def update_overlay_state_from_tracker(self) -> None:
        """Republish tracker state to the OBS overlay."""

    def mark_overlay_read_failed(self, *, no_game: bool) -> None:
        """Tell the overlay a memory read failed, so it can degrade visibly."""

    def refresh_session_tracked_item_stats_ui(self) -> None:
        """Re-render the session tracked-item panel."""

    def refresh_scanner_reminder_ui(self) -> None:
        """Re-read the OBS reminder flag after something else wrote it.

        The flag has two editors -- the OBS Overlay tab's behaviour card and the
        Settings dialog -- and only the dialog knows when it has saved. Declared
        on the port rather than probed for with ``hasattr``: a probe that goes
        quietly false stops refreshing with nothing raising, which is exactly
        the failure recorded beside the timeline refresh in ``SettingsDialog``.
        """


@runtime_checkable
class RecordingsListView(Protocol):
    """The recordings list, as the capture lifecycle sees it.

    Implemented by ``gui_layout.TabRouter``, injected as
    ``_recordings_list_view`` by ``_build_tab_router``. The fallback to the app
    object is closed: step 26 made the router an object, and "re-render the
    recordings list if that tab is showing" is the router's question rather
    than the application's. It is injected from the composition root rather
    than from ``gui_app.__init__`` because the router does not exist until the
    layout is built.
    """

    def _refresh_vods_list_if_visible(self) -> None:
        """Re-render the recordings list, if that tab is showing."""


def _injected(owner, name: str):
    """An injected collaborator, or ``None``.

    Reads ``__dict__`` directly rather than ``getattr`` because app doubles are
    built with ``object.__new__(gui.MegabonkApp)`` and never run ``__init__``;
    the same lazy-fallback shape as ``_ensure_live_snapshot_store``.
    """
    return owner.__dict__.get(name)


def player_stats_view(owner) -> PlayerStatsView:
    """The Player Stats view the app layer should render through."""
    injected = _injected(owner, "_player_stats_view")
    return owner if injected is None else injected


def overlay_view(owner) -> OverlayView:
    """The overlay view the app layer should publish through.

    Production injects ``_overlay_view`` (step 26). The ``owner`` branch is the
    app-double affordance the other two resolvers keep, not a scheduled
    fallback any more.
    """
    injected = _injected(owner, "_overlay_view")
    return owner if injected is None else injected


def recordings_list_view(owner) -> RecordingsListView:
    """The recordings-list view the capture lifecycle should refresh through.

    Production injects ``_recordings_list_view`` (step 26). The ``owner``
    branch is the app-double affordance, not a scheduled fallback any more.
    """
    injected = _injected(owner, "_recordings_list_view")
    return owner if injected is None else injected
