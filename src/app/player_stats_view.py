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

Only ``PlayerStatsView`` is expected to lose its ambient fallback at step 19.
The other two keep it *by design*, and the docstrings say which step removes
them, so a later reader can tell a scheduled fallback from a forgotten one.

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


@runtime_checkable
class OverlayView(Protocol):
    """The OBS overlay and session panel, as the refresh path sees them.

    Implemented by ``gui_overlay.py``. **Step 24** converts this one; until
    then ``overlay_view()`` falls back to the app object on purpose.
    """

    def update_overlay_state_from_tracker(self) -> None:
        """Republish tracker state to the OBS overlay."""

    def mark_overlay_read_failed(self, *, no_game: bool) -> None:
        """Tell the overlay a memory read failed, so it can degrade visibly."""

    def refresh_session_tracked_item_stats_ui(self) -> None:
        """Re-render the session tracked-item panel."""


@runtime_checkable
class RecordingsListView(Protocol):
    """The recordings list, as the capture lifecycle sees it.

    Implemented by ``gui_layout.py``. **Step 26** converts this one; until then
    ``recordings_list_view()`` falls back to the app object on purpose.
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

    Falls back to ``owner`` **by design until step 24**, which converts
    ``OverlayMixin``. This is a scheduled fallback, not an overlooked one.
    """
    injected = _injected(owner, "_overlay_view")
    return owner if injected is None else injected


def recordings_list_view(owner) -> RecordingsListView:
    """The recordings-list view the capture lifecycle should refresh through.

    Falls back to ``owner`` **by design until step 26**, which retires
    ``GuiLayoutMixin``. This is a scheduled fallback, not an overlooked one.
    """
    injected = _injected(owner, "_recordings_list_view")
    return owner if injected is None else injected
