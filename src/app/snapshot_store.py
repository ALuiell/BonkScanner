"""LiveSnapshotStore: the last-known-value fallback for the heavy 10-second
player-stats reads (items, weapons, tomes, damage sources, banishes) plus the
map metadata used to detect a new match.

Moved out of ``PlayerStatsMixin`` without behaviour change. Before this, five
attributes (``player_stats_last_known_items`` and friends) lived directly on
the shared ``self``, readable and writable by any mixin with no owner and no
contract -- exactly the pattern the roadmap's primary metric exists to catch.
They are one component now, with an explicit interface.

Implements the last-known-value fallback introduced by ``caa8564`` ("Preserve
items across transient empty reads"): when a memory read fails or returns
empty, the previous good value survives instead of flashing to empty. That
behaviour is load-bearing -- see the two
``test_refresh_live_player_stats_now_preserves_last_known_items_when_*``
tests -- and is preserved exactly, including one quirk: a fresh store
defaults ``last_known_items`` to ``()`` while every other field defaults to
``None``. That asymmetry is inherited from ``gui_app.py``'s original
``__init__`` (items was never touched by the ``caa8564`` fix, which only
changed the *reset* path to ``None``) and changes first-read behaviour if
"corrected", so it stays exactly as it was.

Qt-free and I/O-free: no widget reads, no memory client calls. Callers pass
in whatever they already read and get back the effective value to display.

**Step 20 removed the owner-side mixin.** ``LiveSnapshotStoreMixin`` was the
first of the five app-side MRO bases to go, and the cheapest, because the
store was already a constructed object -- the mixin held only an accessor and
eight compatibility properties over fields the store already exposes. See
``live_snapshot_store`` below for what replaced the accessor and why the
properties were deleted rather than moved.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MergedValue:
    """Result of merging a single-signal read (items) with its fallback."""

    effective: tuple[Any, ...]
    available: bool


@dataclass(frozen=True)
class MergedFeature:
    """Result of merging a dual-signal read (weapons/tomes/damage sources).

    ``available`` mirrors the read's own availability (an empty-but-available
    read against an existing last-known value becomes unavailable); the
    separate ``effective_available`` tracks whether *something* is on screen,
    which stays true once a last-known value exists even if this tick's read
    was itself unavailable. Downstream code (the tracker snapshot vs. the
    immediate UI display call) genuinely wants both signals.
    """

    effective: tuple[Any, ...]
    available: bool
    effective_available: bool


@dataclass(frozen=True)
class MergedBanishes:
    banishes: tuple[str, ...]
    available: bool


@dataclass(frozen=True)
class LiveSnapshotStoreState:
    """Immutable read-only view of the store's current state."""

    last_known_items: tuple[Any, ...] | None
    last_known_weapons: tuple[Any, ...] | None
    last_known_tomes: tuple[Any, ...] | None
    last_known_damage_sources: tuple[Any, ...] | None
    last_known_banishes: tuple[str, ...] | None
    live_banishes: tuple[str, ...]
    last_seed: int | None
    last_run_timer: float | None


class LiveSnapshotStore:
    """Application-state component, not a widget model. One writer: the
    player-stats refresh cycle in ``app/player_stats_refresh.py``.
    """

    def __init__(self) -> None:
        self.last_known_items: tuple[Any, ...] | None = ()
        self.last_known_weapons: tuple[Any, ...] | None = None
        self.last_known_tomes: tuple[Any, ...] | None = None
        self.last_known_damage_sources: tuple[Any, ...] | None = None
        self.last_known_banishes: tuple[str, ...] | None = None
        self.live_banishes: tuple[str, ...] = ()
        self.last_seed: int | None = None
        self.last_run_timer: float | None = None

    def snapshot(self) -> LiveSnapshotStoreState:
        return LiveSnapshotStoreState(
            last_known_items=self.last_known_items,
            last_known_weapons=self.last_known_weapons,
            last_known_tomes=self.last_known_tomes,
            last_known_damage_sources=self.last_known_damage_sources,
            last_known_banishes=self.last_known_banishes,
            live_banishes=self.live_banishes,
            last_seed=self.last_seed,
            last_run_timer=self.last_run_timer,
        )

    def is_new_match(self, *, map_seed: int | None, run_timer_seconds: float | None) -> bool:
        is_new_match = False
        prev_seed = self.last_seed
        prev_time = self.last_run_timer
        if run_timer_seconds is not None:
            if prev_time is None and run_timer_seconds <= 5.0:
                is_new_match = True

            # Map seed changed or appeared on low game time
            if map_seed is not None and (prev_seed is None or int(map_seed) != int(prev_seed)):
                if run_timer_seconds <= 5.0:
                    is_new_match = True

            # Timer went backward (reset)
            if prev_time is not None and run_timer_seconds + 1.0 < prev_time:
                is_new_match = True
        return is_new_match

    def reset_for_new_match(self) -> None:
        self.last_known_items = None
        self.last_known_weapons = None
        self.last_known_tomes = None
        self.last_known_damage_sources = None
        self.last_known_banishes = None
        self.live_banishes = ()

    def record_match_tick(self, *, map_seed: int | None, run_timer_seconds: float | None) -> None:
        self.last_seed = map_seed
        self.last_run_timer = run_timer_seconds

    def reset_match_metadata(self) -> None:
        self.last_seed = None
        self.last_run_timer = None

    def merge_items(self, items: tuple[Any, ...], items_available: bool) -> MergedValue:
        last_known_items = self.last_known_items
        if items_available and (items or last_known_items is None):
            effective_items = items
            self.last_known_items = items
        elif last_known_items is not None:
            # The game can expose an empty inventory dictionary for a single
            # refresh while it is being updated. Do not turn that into a real
            # item loss or let it reset the stage-summary item baseline.
            effective_items = last_known_items
            items_available = False
        else:
            effective_items = ()
        return MergedValue(effective=effective_items, available=items_available)

    def merge_weapons(self, weapons: tuple[Any, ...], weapons_available: bool) -> MergedFeature:
        return self._merge_feature("last_known_weapons", weapons, weapons_available)

    def merge_tomes(self, tomes: tuple[Any, ...], tomes_available: bool) -> MergedFeature:
        return self._merge_feature("last_known_tomes", tomes, tomes_available)

    def merge_damage_sources(
        self,
        damage_sources: tuple[Any, ...],
        damage_sources_available: bool,
    ) -> MergedFeature:
        return self._merge_feature("last_known_damage_sources", damage_sources, damage_sources_available)

    def _merge_feature(self, attr: str, value: tuple[Any, ...], available: bool) -> MergedFeature:
        last_known = getattr(self, attr)
        if available:
            if value or last_known is None:
                effective = value
                setattr(self, attr, value)
                effective_available = True
            else:
                effective = last_known
                available = False
                effective_available = True
        else:
            effective = last_known or ()
            effective_available = last_known is not None
        return MergedFeature(effective=effective, available=available, effective_available=effective_available)

    def merge_banishes(
        self,
        banishes: tuple[str, ...],
        banishes_available: bool,
        *,
        merge_fn: Callable[[tuple[str, ...], tuple[str, ...]], tuple[str, ...]],
    ) -> MergedBanishes:
        if banishes_available:
            last_known_banishes = self.last_known_banishes
            if banishes or last_known_banishes is None:
                banishes = merge_fn(self.live_banishes, banishes)
                self.live_banishes = banishes
                self.last_known_banishes = banishes
            else:
                banishes = last_known_banishes
                banishes_available = False
        else:
            last_known_banishes = self.last_known_banishes
            banishes = last_known_banishes if last_known_banishes is not None else self.live_banishes
        return MergedBanishes(banishes=banishes, available=banishes_available)
