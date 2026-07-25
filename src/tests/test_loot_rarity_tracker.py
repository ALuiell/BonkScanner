"""The loot tracker: actual rarities against what the game's model expected.

Every confirmed item gain is a roll, and the three sources that roll by a
different model are excluded rather than attributed. The state machine that
does it runs over noisy reads, which is the shape of problem the powerup timing
work needed two live captures to get right -- so these tests drive the whole
wiring (`LiveRunTracker` -> `items` -> `loot`) rather than the loot functions in
isolation, except where only a module-level call can reach the case.

Design, measured windows and evidence levels: `docs/updates/functional_updates.md`,
item 5 ("Verified Game Mechanics" / "Detection Design").
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from core.luck_rarity import calculate_luck_rarity_probabilities
from core.tracker import loot
from core.tracker.live_run import LiveRunSnapshot, LiveRunTracker
from core.tracker.snapshots import ItemGainEvent
from projections.vod import build_vod_capture_kwargs

# One item per tier, plus the two the design names outright. `Corrupt Artefact`
# is in no metadata table on purpose: it stands in both for a Corrupt-chest item
# (`EItemRarity.Corrupted`, outside our four tiers) and for an item a game
# update adds before we know about it.
LEGENDARY_ITEMS = ("Anvil", "Snek", "Bonker", "Giant Fork")
RARE_ITEM = "Quins Mask"
UNCOMMON_ITEM = "Beacon"
COMMON_ITEM = "Wrench"
SELF_CONSUMING_ITEM = "Za Warudo"
UNRESOLVABLE_ITEM = "Corrupt Artefact"

DEFAULT_LUCK = 0.5


class _Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class LootRun:
    """A run driven one 1 s pass at a time, in the production order.

    Each pass publishes Luck, then the interactable counters, then the
    inventory -- which is the order `_refresh_passive_items_task` uses and the
    order the exclusions are specified against.

    Every acquisition needs **two** passes: a rise is held pending and credited
    only when a later read agrees, and the gain it then emits is stamped with
    the time and the Luck of the pass that *observed* the rise.
    """

    def __init__(self, *, luck: float = DEFAULT_LUCK, start_time: float = 0.0) -> None:
        self.clock = _Clock(start_time)
        self.tracker = LiveRunTracker(clock=self.clock)
        self.time = start_time
        self.items: tuple[str, ...] = ()
        self.stage_ptr = 1000
        self.map_seed = 100
        self.luck = luck

    def begin(self, items=(), *, counters: dict[str, int] | None = None) -> "LootRun":
        """The pass that seeds the item baseline, which is never a gain.

        A run starts with an empty inventory, so `items` is only for the
        late-attach case: whatever is held when the app arrives is absorbed into
        the baseline in one block by `initial_item_increase_candidates`, and
        that block reaches the loot tracker with no Luck -- the tracker-wide
        run reset clears the fast reading on the very pass that seeds -- so it
        falls out of both sides on its own. That is the right answer for items
        whose rolls were never observed, and the reason a late-attached run has
        to report itself unmeasurable rather than short.
        """
        return self.tick(items, counters=counters)

    def tick(
        self,
        items=None,
        *,
        counters: dict[str, int] | None = None,
        luck: float | None = None,
        advance: float = 1.0,
    ) -> "LootRun":
        self.time += advance
        self.clock.now = self.time
        if items is not None:
            self.items = tuple(items)
        self.tracker.update_fast_luck(self.luck if luck is None else luck)
        if counters is not None:
            self.tracker.update_loot_interactables(counters)
        self.tracker.update(
            LiveRunSnapshot(
                captured_at=self.time,
                stats={},
                items=self.items,
                game_time_seconds=self.time,
                stage_time_seconds=self.time,
                map_seed=self.map_seed,
                stage_ptr=self.stage_ptr,
            )
        )
        return self

    def acquire(self, item: str, *, counters: dict[str, int] | None = None) -> "LootRun":
        """One acquisition, observed on this pass and confirmed on the next."""
        self.tick(self.items + (item,), counters=counters)
        return self.tick()

    def lose(self, item: str) -> "LootRun":
        """One item leaving the inventory, again observed then confirmed."""
        remaining = list(self.items)
        remaining.remove(item)
        self.tick(remaining)
        return self.tick()

    def new_map(self) -> "LootRun":
        self.stage_ptr += 1
        return self.tick()

    def stats(self):
        return self.tracker.get_loot_stats()

    def actual(self) -> dict[str, int]:
        return self.stats().actual


def expectation_for(luck: float, rolls: int = 1) -> dict[str, float]:
    probabilities = calculate_luck_rarity_probabilities(luck)
    return {tier: (value or 0.0) / 100.0 * rolls for tier, value in probabilities.items()}


class LootExclusionTests(unittest.TestCase):
    """The three sources that do not roll on the chest model."""

    def test_a_decrease_opens_a_tier_debt_the_next_same_tier_gain_settles(self) -> None:
        """The microwave signal. A craft consumes 1 and yields 1, so the total
        never moves -- only the individual count does. Other tiers arriving in
        between are ordinary rolls and must not be touched by the debt."""
        run = LootRun().begin()
        run.acquire(LEGENDARY_ITEMS[0])
        run.acquire(COMMON_ITEM)
        self.assertEqual(run.actual()["LEGENDARY"], 1)

        run.lose(LEGENDARY_ITEMS[0])
        self.assertEqual(run.stats().outstanding_tier_debts, ("LEGENDARY",))

        run.acquire(UNCOMMON_ITEM)
        self.assertEqual(run.actual()["UNCOMMON"], 1, "a different tier still counts")
        self.assertEqual(run.stats().outstanding_tier_debts, ("LEGENDARY",))

        run.acquire(LEGENDARY_ITEMS[1])
        self.assertEqual(run.actual()["LEGENDARY"], 1, "the craft output is not a roll")
        self.assertEqual(run.stats().outstanding_tier_debts, ())

        run.acquire(LEGENDARY_ITEMS[2])
        self.assertEqual(run.actual()["LEGENDARY"], 2, "the debt is settled, not standing")

    def test_a_second_decrease_before_the_first_settles_queues(self) -> None:
        """Two crafts owe two exclusions. A set, or a single slot, would let the
        second craft output through as a genuine roll."""
        run = LootRun().begin()
        run.acquire(LEGENDARY_ITEMS[0])
        run.acquire(LEGENDARY_ITEMS[1])

        run.lose(LEGENDARY_ITEMS[0])
        run.lose(LEGENDARY_ITEMS[1])
        self.assertEqual(
            run.stats().outstanding_tier_debts, ("LEGENDARY", "LEGENDARY")
        )

        before = run.actual()["LEGENDARY"]
        run.acquire(LEGENDARY_ITEMS[2])
        run.acquire(LEGENDARY_ITEMS[3])
        self.assertEqual(run.actual()["LEGENDARY"], before)
        self.assertEqual(run.stats().outstanding_tier_debts, ())

        run.acquire(LEGENDARY_ITEMS[0])
        self.assertEqual(run.actual()["LEGENDARY"], before + 1)

    def test_debts_clear_at_map_generation(self) -> None:
        """A craft output the player never collected is lying on the floor of a
        stage that no longer exists. Carried forward, its debt would swallow a
        legitimate roll on the new map."""
        run = LootRun().begin()
        run.acquire(LEGENDARY_ITEMS[0])
        run.lose(LEGENDARY_ITEMS[0])
        self.assertEqual(run.stats().outstanding_tier_debts, ("LEGENDARY",))

        run.new_map()
        self.assertEqual(run.stats().outstanding_tier_debts, ())

        before = run.actual()["LEGENDARY"]
        run.acquire(LEGENDARY_ITEMS[1])
        self.assertEqual(run.actual()["LEGENDARY"], before + 1)

    def test_za_warudo_leaving_the_inventory_opens_no_debt(self) -> None:
        """The only self-consuming item in the game: it breaks when the player
        is killed. Read as a craft it raises a phantom LEGENDARY debt and eats
        the next genuine legendary, so `actual` undercounts while `expected`
        does not."""
        run = LootRun().begin()
        run.acquire(SELF_CONSUMING_ITEM)
        counted_before = run.actual()["LEGENDARY"]

        run.lose(SELF_CONSUMING_ITEM)
        self.assertEqual(run.stats().outstanding_tier_debts, ())

        run.acquire(LEGENDARY_ITEMS[0])
        self.assertEqual(run.actual()["LEGENDARY"], counted_before + 1)

    def test_moai_excludes_the_next_gain_and_shady_guy_the_preceding_one(self) -> None:
        """Mirror images. The Moai counter fires when the player picks, before
        the grant; the merchant's fires once trading ends, after it."""
        idle = {loot.MOAI_COUNTER_LABEL: 0, loot.SHADY_GUY_COUNTER_LABEL: 0}
        run = LootRun().begin()
        # The counter baseline has to be laid down *after* the run reset, which
        # clears per-map state along with everything else -- so the first read of
        # a run is a first sighting and never an increment.
        run.tick(counters=idle)

        # Moai: the increment lands, then its item, in the same or the next pass.
        run.tick(
            run.items + (LEGENDARY_ITEMS[0],),
            counters={**idle, loot.MOAI_COUNTER_LABEL: 1},
        )
        run.tick(counters={**idle, loot.MOAI_COUNTER_LABEL: 1})
        self.assertEqual(run.actual()["LEGENDARY"], 0, "the Moai item is not a chest roll")

        # Shady Guy, counter one pass behind its item: the gain has been
        # observed but not yet credited when the increment is read.
        run.tick(run.items + (RARE_ITEM,), counters={**idle, loot.MOAI_COUNTER_LABEL: 1})
        run.tick(
            counters={
                **idle,
                loot.MOAI_COUNTER_LABEL: 1,
                loot.SHADY_GUY_COUNTER_LABEL: 1,
            }
        )
        self.assertEqual(run.actual()["RARE"], 0, "the merchant's item is not a roll")

        # Shady Guy again, counter two passes behind: the gain is already
        # counted, so the window has to reach back and undo it.
        run.tick(run.items + (UNCOMMON_ITEM,))
        run.tick()
        self.assertEqual(run.actual()["UNCOMMON"], 1)
        run.tick(
            counters={
                **idle,
                loot.MOAI_COUNTER_LABEL: 1,
                loot.SHADY_GUY_COUNTER_LABEL: 2,
            }
        )
        self.assertEqual(run.actual()["UNCOMMON"], 0)
        self.assertEqual(
            run.stats().expected["UNCOMMON"],
            0.0,
            "an undone roll leaves no expectation behind either",
        )

    def test_an_increment_with_no_gain_in_its_window_excludes_nothing(self) -> None:
        """The statue the player opened and walked away from -- and the guard
        against a window that never closes quietly eating an unrelated roll
        minutes later."""
        idle = {loot.MOAI_COUNTER_LABEL: 0, loot.SHADY_GUY_COUNTER_LABEL: 0}
        run = LootRun().begin()
        run.tick(counters=idle)
        run.tick(counters={**idle, loot.MOAI_COUNTER_LABEL: 1})

        for _ in range(6):
            run.tick(counters={**idle, loot.MOAI_COUNTER_LABEL: 1})

        run.acquire(LEGENDARY_ITEMS[0], counters={**idle, loot.MOAI_COUNTER_LABEL: 1})
        self.assertEqual(run.actual()["LEGENDARY"], 1)

    def test_counters_resetting_at_map_generation_is_not_an_increment(self) -> None:
        """Every counter resets per map. Read as movement, a stage change would
        open a burst of exclusions and blank out the new map's first rolls."""
        used = {loot.MOAI_COUNTER_LABEL: 3, loot.SHADY_GUY_COUNTER_LABEL: 2}
        fresh = {loot.MOAI_COUNTER_LABEL: 0, loot.SHADY_GUY_COUNTER_LABEL: 0}
        run = LootRun().begin()
        run.tick(counters=used)
        run.tick(counters=used)
        run.tick(counters=fresh)

        run.acquire(LEGENDARY_ITEMS[0], counters=fresh)
        self.assertEqual(run.actual()["LEGENDARY"], 1)
        run.acquire(RARE_ITEM, counters=fresh)
        self.assertEqual(run.actual()["RARE"], 1)


class LootAccumulationTests(unittest.TestCase):
    """What goes into `actual` and `expected`, and what stays out of both."""

    def test_expectation_uses_the_luck_at_the_gain_not_at_confirmation(self) -> None:
        """Luck sweeps continuously through a run, so a roll scored against the
        reading at confirmation is scored one tick along the curve from where it
        happened. `_PendingItemIncrease` carries the observing pass's value."""
        observing_luck = 0.5
        confirming_luck = 50.0
        run = LootRun(luck=observing_luck).begin()
        run.tick(run.items + (LEGENDARY_ITEMS[0],), luck=observing_luck)
        run.tick(luck=confirming_luck)

        expected = run.stats().expected
        at_observation = expectation_for(observing_luck)
        at_confirmation = expectation_for(confirming_luck)
        for tier, value in at_observation.items():
            self.assertAlmostEqual(expected[tier], value, places=9)
        self.assertNotAlmostEqual(
            at_observation["LEGENDARY"], at_confirmation["LEGENDARY"], places=3
        )

    def test_an_unresolvable_rarity_contributes_to_neither_side(self) -> None:
        """A Corrupt-chest item, or one a game update added after our table was
        written. Counted in `actual` alone it would drift the two halves apart;
        counted in `expected` alone, the same in reverse."""
        run = LootRun().begin()
        run.acquire(UNRESOLVABLE_ITEM)

        stats = run.stats()
        self.assertEqual(sum(stats.actual.values()), 0)
        self.assertEqual(sum(stats.expected.values()), 0.0)
        self.assertEqual(
            stats.acquisitions, 1, "it is still an acquisition for the residual check"
        )

    def test_a_stack_increase_on_an_owned_item_is_a_full_roll(self) -> None:
        """Duplicates stack rather than leaving the pool, so the second copy was
        rolled exactly like the first -- the item list shows `x2` where a naive
        reading sees no new item at all.

        The second half is the case a per-item view still misses: two copies
        arriving between one confirmed read and the next are two rolls, and
        `gained_count` is the only thing that says so."""
        run = LootRun().begin()
        run.acquire(f"{LEGENDARY_ITEMS[0]} x1")
        self.assertEqual(run.actual()["LEGENDARY"], 1)

        run.tick((f"{LEGENDARY_ITEMS[0]} x2",))
        run.tick()
        self.assertEqual(run.actual()["LEGENDARY"], 2)

        run.tick((f"{LEGENDARY_ITEMS[0]} x4",))
        run.tick()

        self.assertEqual(run.actual()["LEGENDARY"], 4)
        for tier, value in expectation_for(DEFAULT_LUCK, rolls=4).items():
            self.assertAlmostEqual(run.stats().expected[tier], value, places=9)

    def test_attaching_mid_run_yields_the_unavailable_state(self) -> None:
        """Stricter than `!chests`. The items already held are absorbed into the
        item baseline in one silent block, which leaves `actual` short by that
        block and `expected` short by the same rolls -- so partial numbers are
        not a smaller answer, they are a different and wrong one."""
        late = LootRun(start_time=900.0).begin((COMMON_ITEM,))
        late.acquire(LEGENDARY_ITEMS[0])

        stats = late.stats()
        self.assertFalse(stats.available)
        self.assertEqual(sum(stats.actual.values()), 0)
        self.assertEqual(sum(stats.expected.values()), 0.0)
        # The residual check does not depend on availability and keeps counting.
        self.assertGreater(stats.acquisitions, 0)

        early = LootRun().begin()
        early.acquire(LEGENDARY_ITEMS[0])
        self.assertTrue(early.stats().available)
        self.assertEqual(early.stats().actual["LEGENDARY"], 1)

    def test_a_new_run_clears_state(self) -> None:
        """Two mechanisms enforce this and either one alone is enough: the
        tracker-wide `_reset_for_new_run` calls `loot.reset`, and the loot lane
        recognises a run clock that has gone backwards on its own. Removing
        just the first leaves this test green, which is the redundancy working
        rather than a gap -- removing the clearing itself reddens it.
        """
        run = LootRun().begin()
        run.acquire(LEGENDARY_ITEMS[0])
        self.assertEqual(run.actual()["LEGENDARY"], 1)

        # The run clock going backwards is what `_should_reset_for_snapshot`
        # reads as a new match, and it has to fall by more than the run-timer
        # tolerance to be one.
        run.tick(advance=600.0)
        run.time = 0.0
        run.items = ()
        run.tick(())
        run.acquire(RARE_ITEM)

        stats = run.stats()
        self.assertEqual(stats.actual["LEGENDARY"], 0)
        self.assertEqual(stats.actual["RARE"], 1)
        self.assertEqual(stats.acquisitions, 1)

    def test_a_spurious_reset_does_not_wipe_a_valid_run(self) -> None:
        """`_ChestState`'s guard, for the same reason it exists there.

        This module runs on the 1 s item lane and the tracker-wide reset arrives
        from the 10 s snapshot, so when the item lane starts the new run first
        -- which it does whenever the fast run timer is absent and
        `update_items` therefore has no clock to refuse on -- the late reset
        would zero rolls that are already real.

        Module-level because that ordering cannot be produced through the
        tracker's public surface: there, `update` resets before it ever folds a
        delta.
        """
        state = loot._LootState()
        loot.observe_run_position(state, stage_index=1, game_time_seconds=1500.0)
        loot.process_item_gains(
            state, (_gain(LEGENDARY_ITEMS[0], captured_at=1500.0),)
        )
        self.assertEqual(state.actual["LEGENDARY"], 1)

        # The item lane sees the new match first and starts the run itself.
        loot.observe_run_position(state, stage_index=1, game_time_seconds=2.0)
        self.assertEqual(state.actual["LEGENDARY"], 0)
        self.assertTrue(state.expected_detected_run_reset)
        loot.process_item_gains(state, (_gain(RARE_ITEM, captured_at=3.0),))
        self.assertEqual(state.actual["RARE"], 1)

        # ...and the snapshot lane's reset arrives afterwards.
        loot.reset(state)

        self.assertEqual(state.actual["RARE"], 1, "the new run's rolls survive")
        self.assertFalse(state.expected_detected_run_reset)
        loot.reset(state)
        self.assertEqual(state.actual["RARE"], 0, "the guard is spent, not sticky")


class LootStatsOnRuntimeSnapshotTests(unittest.TestCase):
    """The summary has to travel on the boundary object, not on the tracker.

    ``projections/`` may import ``core/`` only, so the OBS projector cannot
    reach the rarity model or ``_LootState``; it has to be handed the finished
    numbers. Reading the summary off ``runtime_snapshot()`` is therefore not a
    convenience -- it is the only route the layer rule leaves open.
    """

    def test_runtime_snapshot_carries_the_same_summary_as_the_getter(self) -> None:
        run = LootRun().begin()
        run.acquire(LEGENDARY_ITEMS[0])
        run.acquire(COMMON_ITEM)

        published = run.tracker.runtime_snapshot().loot_stats

        self.assertEqual(published, run.stats())
        self.assertEqual(published.actual["LEGENDARY"], 1)
        self.assertEqual(published.actual["COMMON"], 1)
        self.assertTrue(published.available)

    def test_runtime_snapshot_carries_the_unavailable_state(self) -> None:
        """An unmeasurable run must reach the projections *as* unmeasurable.

        Publishing zeros with ``available`` left true would give every surface a
        number that looks like an answer and is not one.
        """
        run = LootRun(start_time=600.0).begin((LEGENDARY_ITEMS[0],))
        run.acquire(COMMON_ITEM)

        published = run.tracker.runtime_snapshot().loot_stats

        self.assertFalse(published.available)
        self.assertEqual(published.actual, {tier: 0 for tier in published.actual})


class LootStatsInRecordingsTests(unittest.TestCase):
    """What a recording carries, and what it deliberately does not.

    Absence is the whole point: an older file and an unmeasurable run both omit
    the field, and both mean "not recorded". Writing zeros for the second would
    make it indistinguishable from a run that gained nothing.
    """

    def test_a_measurable_run_serializes_its_per_tier_totals(self) -> None:
        run = LootRun().begin()
        run.acquire(LEGENDARY_ITEMS[0])
        run.acquire(COMMON_ITEM)

        values = build_vod_capture_kwargs(run.tracker.runtime_snapshot())

        self.assertEqual(1, values["loot_actual"]["LEGENDARY"])
        self.assertEqual(1, values["loot_actual"]["COMMON"])
        self.assertGreater(values["loot_expected"]["LEGENDARY"], 0.0)

    def test_an_unmeasurable_run_records_nothing_rather_than_zeros(self) -> None:
        run = LootRun(start_time=600.0).begin((LEGENDARY_ITEMS[0],))
        run.acquire(COMMON_ITEM)

        values = build_vod_capture_kwargs(run.tracker.runtime_snapshot())

        self.assertIsNone(values["loot_actual"])
        self.assertIsNone(values["loot_expected"])


def _gain(item_name: str, *, captured_at: float, luck: float = DEFAULT_LUCK) -> ItemGainEvent:
    return ItemGainEvent(
        item_name=item_name,
        gained_count=1,
        luck=luck,
        game_time_seconds=captured_at,
        stage_index=1,
        map_seed=100,
        captured_at=captured_at,
    )


if __name__ == "__main__":
    unittest.main()
