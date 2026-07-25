"""Confirmed item-count *decreases* in `process_item_deltas`.

Before this, `previous_item_counts` was monotonically non-decreasing for the
life of a run: the `current_count <= confirmed_count` branch dropped the
pending increase and `continue`d without writing back. Two consequences, one
live and one latent.

Live: after an item left the inventory its stale high baseline meant
re-acquiring it never registered, so `process_item_gain` never fired and the
tracked-item rules behind the OBS overlay, Session Stats and the Twitch
commands silently missed it.

Latent: the decrease is the microwave signal the loot tracker consumes. That
makes the confirmation ladder load-bearing rather than defensive -- the game
rebuilds the item array in place, and a decrease applied on first sight would
turn every torn read into a phantom craft.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from core.tracker.live_run import (
    LiveRunSnapshot,
    LiveRunTracker,
    TrackedItemRule,
)


ANVIL_RULE = TrackedItemRule(
    id="anvils_total",
    label="Anvils",
    item_names=("Anvil",),
    mode="all_run",
)


def snapshot(*, time_seconds: float, items=(), map_seed: int = 100) -> LiveRunSnapshot:
    return LiveRunSnapshot(
        captured_at=time_seconds,
        stats={},
        items=tuple(items),
        game_time_seconds=time_seconds,
        stage_time_seconds=time_seconds,
        map_seed=map_seed,
        stage_ptr=1000,
    )


def anvils(tracker: LiveRunTracker) -> int:
    return next(
        int(row["count"])
        for row in tracker.tracked_item_rows()
        if row["id"] == "anvils_total"
    )


class ConfirmedItemDecreaseTests(unittest.TestCase):
    def tracker_holding_two_anvils(self) -> LiveRunTracker:
        """A run whose confirmed baseline is `Anvil x2`."""
        tracker = LiveRunTracker(tracked_item_rules=(ANVIL_RULE,), clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x2",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x2",)))
        self.assertEqual(anvils(tracker), 2)
        return tracker

    def test_one_low_read_is_not_believed_and_a_second_agreeing_one_is(self) -> None:
        tracker = self.tracker_holding_two_anvils()

        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
        self.assertEqual(tracker.last_item_losses(), ())

        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x1",)))

        losses = tracker.last_item_losses()
        self.assertEqual(len(losses), 1)
        self.assertEqual(losses[0].item_name, "Anvil")
        self.assertEqual(losses[0].lost_count, 1)
        # Timestamped from the read that observed the drop, not the one that
        # confirmed it -- the mirror of `_PendingItemIncrease` on the gain side.
        self.assertEqual(losses[0].game_time_seconds, 3.0)
        self.assertEqual(losses[0].captured_at, 3.0)

    def test_a_dip_that_recovers_produces_neither_a_gain_nor_a_loss(self) -> None:
        """The torn read the confirmation ladder exists for. Applied on sight,
        the dip would be a loss and the recovery a fresh gain -- two events and
        an inflated total, from one bad frame."""
        tracker = self.tracker_holding_two_anvils()

        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x2",)))
        self.assertEqual(tracker.last_item_losses(), ())

        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x2",)))

        self.assertEqual(tracker.last_item_losses(), ())
        self.assertEqual(anvils(tracker), 2)

    def test_re_acquiring_after_a_confirmed_decrease_credits_the_gain_once(self) -> None:
        """The live bug. With the baseline stuck at its high-water mark, the
        re-acquisition read never exceeds it and no gain is ever credited."""
        tracker = self.tracker_holding_two_anvils()
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x1",)))

        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x2",)))
        self.assertEqual(anvils(tracker), 2)  # seen once, not yet confirmed

        tracker.update(snapshot(time_seconds=6.0, items=("Anvil x2",)))
        self.assertEqual(anvils(tracker), 3)

        # Exactly once: holding at the re-acquired count adds nothing further.
        tracker.update(snapshot(time_seconds=7.0, items=("Anvil x2",)))
        self.assertEqual(anvils(tracker), 3)

    def test_an_item_that_leaves_the_inventory_outright_is_a_confirmed_loss(self) -> None:
        """`Za Warudo` breaking, and the case the iteration set had to grow for:
        an item at zero is absent from `current_counts` altogether, so before
        this it was never visited and its baseline never moved."""
        tracker = self.tracker_holding_two_anvils()

        tracker.update(snapshot(time_seconds=3.0, items=()))
        tracker.update(snapshot(time_seconds=4.0, items=()))

        losses = tracker.last_item_losses()
        self.assertEqual([(event.item_name, event.lost_count) for event in losses], [("Anvil", 2)])

    def test_a_still_falling_count_confirms_in_steps_rather_than_all_at_once(self) -> None:
        """Each observation is credited only by the read that agrees with it, so
        a two-stage drop yields two losses and never over-counts the first."""
        tracker = LiveRunTracker(tracked_item_rules=(ANVIL_RULE,), clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x3",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x3",)))

        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x2",)))
        self.assertEqual(tracker.last_item_losses(), ())

        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x1",)))
        first = tracker.last_item_losses()
        self.assertEqual([event.lost_count for event in first], [1])

        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x1",)))
        second = tracker.last_item_losses()
        self.assertEqual([event.lost_count for event in second], [1])

    def test_losses_are_replaced_per_pass_rather_than_accumulated(self) -> None:
        """A consumer reads this in the pass that wrote it. Accumulating would
        make it a queue nothing drains."""
        tracker = self.tracker_holding_two_anvils()
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x1",)))
        self.assertEqual(len(tracker.last_item_losses()), 1)

        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x1",)))

        self.assertEqual(tracker.last_item_losses(), ())

    def test_a_new_run_clears_the_pending_decrease(self) -> None:
        """A dip left unconfirmed when the run ended must not settle against the
        next run's baseline."""
        tracker = self.tracker_holding_two_anvils()
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))

        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x1",), map_seed=200))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",), map_seed=200))

        self.assertEqual(tracker.last_item_losses(), ())
        self.assertEqual(tracker._pending_item_decreases, {})


if __name__ == "__main__":
    unittest.main()
