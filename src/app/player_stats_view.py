"""The port the player-stats app layer renders through.

``app/`` may not import ``ui/``. Before this module, ``player_stats_refresh``
and ``vod_capture`` reached the UI anyway -- through the shared ``self``, which
the layering table cannot see and the hidden-dependency metric only counts while
the code still sits in one of the eight original mixins. Moving that code to
``app/`` in step 14c did not remove those edges; it removed them from view.

So they are named here instead. ``PlayerStatsView`` is the whole surface the app
layer needs from the UI: eight operations, no widgets, no Qt types. This is the
step-10d inversion (``app/update_flow.py`` + ``ui/update_prompt.py``) applied to
the refresh path -- the difference between an implicit contract and a stated one.

**The default view is the app object itself, and that is deliberate.**
``player_stats_view(owner)`` returns ``owner`` unless something injected a
replacement. ``MegabonkApp`` satisfies this protocol through its mixins, so
dispatch is byte-for-byte what it was before -- this commit states the contract
without changing behaviour. What it buys today is that the app layer depends on
a named, documented, substitutable interface rather than on whatever happens to
be reachable through a shared namespace, and that a test can drive the refresh
path with a recording double instead of a window.

Two things this deliberately does **not** do, because both are behaviour
changes and belong to a later step:

- It does not make the app layer *push* rendering decisions to the UI.
  ``refresh_live_player_stats_now`` still decides what to display and when;
  splitting "read a coherent sample" from "project it for a consumer" is the
  composable-reads design, which needs step 12 first.
- It does not remove the owner-bound mixin shape. These are still methods on
  ``MegabonkApp``, because ~44 of them are called class-qualified from the suite
  and resolve only through the MRO. Tabs-as-classes is step 15.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlayerStatsView(Protocol):
    """Everything the player-stats app layer asks the UI to do."""

    # -- live stats rendering -------------------------------------------------
    def display_player_stats(self, stats, items, **kwargs) -> None:
        """Render a live reading into the Live Stats tab."""

    def display_player_stats_snapshot(self, snapshot, *, items_text) -> None:
        """Render a captured recording snapshot into the Live Stats tab."""

    def refresh_player_stats_timeline_ui(self) -> None:
        """Re-render the recording timeline after its snapshot list changed."""

    def set_recording_status_text(self, text: str) -> None:
        """Set the Live Stats status line (recording / paused / armed)."""

    def set_mob_kills_text(self, text: str) -> None:
        """Set the Live Stats mob-kills line."""

    # -- neighbouring views that mirror the same reading ----------------------
    def update_overlay_state_from_tracker(self) -> None:
        """Republish tracker state to the OBS overlay."""

    def mark_overlay_read_failed(self, *, no_game: bool) -> None:
        """Tell the overlay a memory read failed, so it can degrade visibly."""

    def refresh_session_tracked_item_stats_ui(self) -> None:
        """Re-render the session tracked-item panel."""

    def _refresh_vods_list_if_visible(self) -> None:
        """Re-render the recordings list, if that tab is showing."""


def player_stats_view(owner) -> PlayerStatsView:
    """The view the app layer should render through.

    Defaults to ``owner`` itself: ``MegabonkApp`` implements this protocol via
    its mixins, so the default preserves the original dispatch exactly. An
    injected ``_player_stats_view`` takes precedence, which is what lets a test
    -- or a future headless consumer -- drive the refresh path without a window.

    Reads ``__dict__`` directly rather than ``getattr`` because app doubles are
    built with ``object.__new__(gui.MegabonkApp)`` and never run ``__init__``;
    the same lazy-fallback shape as ``_ensure_live_snapshot_store``.
    """
    injected = owner.__dict__.get("_player_stats_view")
    return owner if injected is None else injected
