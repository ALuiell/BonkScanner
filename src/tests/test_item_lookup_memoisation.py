"""Memoisation of the item-name and item-count lookups.

These four functions are on the hot path of every stage summary, and a stage
summary re-walks a run from its first snapshot on every timeline frame. Caching
them took a Compare Runs frame with all sections enabled from ~83 ms to ~11 ms.

Caching a function changes nothing a caller can observe *only* while three
things hold, and each has a case below:

* the cached value is never handed out where a caller can mutate it --
  `create_stage_item_gain_tracker` stores `item_counts`' result and then
  mutates it in place, which is the one way this optimisation could corrupt
  real data rather than merely be slow;
* an argument the cache cannot hash still works, because the pre-cache code
  accepted anything `str()` would take;
* the answers themselves are unchanged.
"""

from __future__ import annotations

import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core import item_metadata, run_summary


class ItemCountsCopyTests(unittest.TestCase):
    """The cached mapping must never escape into a caller that mutates it."""

    def test_each_call_returns_an_independent_dict(self) -> None:
        items = ("Beer x3", "Key")

        first = run_summary.item_counts(items)
        first["Beer"] = 999
        first["Injected"] = 1
        second = run_summary.item_counts(items)

        self.assertEqual(3, second["Beer"], "a mutation leaked into the cache")
        self.assertNotIn("Injected", second)

    def test_the_stage_tracker_cannot_corrupt_later_counts(self) -> None:
        """The real path: the tracker mutates `confirmed_counts` in place."""
        items = ("Beer x2", "Key")

        tracker = run_summary.create_stage_item_gain_tracker(items)
        run_summary.update_stage_item_gain_tracker(tracker, ("Beer x5", "Key"))

        self.assertEqual({"Beer": 2, "Key": 1}, run_summary.item_counts(items))

    def test_a_list_and_a_tuple_of_the_same_items_agree(self) -> None:
        """The cache keys on a tuple; the callers pass both."""
        self.assertEqual(
            run_summary.item_counts(["Beer x3", "Key"]),
            run_summary.item_counts(("Beer x3", "Key")),
        )

    def test_empty_and_none_are_still_empty(self) -> None:
        self.assertEqual({}, run_summary.item_counts(()))
        self.assertEqual({}, run_summary.item_counts(None))

    def test_unhashable_entries_fall_back_instead_of_raising(self) -> None:
        """`lru_cache` cannot key on these; the old code only called `str()`.

        Compared against the uncached body rather than a literal: what
        `str(["Beer"])` folds to is the pre-existing behaviour's business, and
        this case is about the fallback firing at all.
        """
        unhashable = [["Beer"]]

        self.assertEqual(
            run_summary._compute_item_counts(unhashable),
            run_summary.item_counts(unhashable),
        )

    def test_stack_counts_and_the_trust_ceiling_are_unchanged(self) -> None:
        self.assertEqual({"Beer": 3}, run_summary.item_counts(("Beer x3",)))
        self.assertEqual({"Beer": 2}, run_summary.item_counts(("Beer", "Beer")))
        absurd = run_summary.MAX_TRUSTED_ITEM_STACK_COUNT + 1
        self.assertEqual({}, run_summary.item_counts((f"Beer x{absurd}",)))


class ItemNameNormalisationTests(unittest.TestCase):
    def test_caching_did_not_change_the_answers(self) -> None:
        """Compared against the uncached body, not against frozen literals."""
        names = (
            "Beer",
            "  Spiky   Shield  ",
            "GoldenRing",
            "Gloves Of Power",
            "Not A Real Item",
            "",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(
                    item_metadata._normalize_item_name_for_rarity.__wrapped__(name),
                    item_metadata.normalize_item_name_for_rarity(name),
                )
                self.assertEqual(
                    item_metadata._normalize_item_name_for_display.__wrapped__(name),
                    item_metadata.normalize_item_name_for_display(name),
                )

    def test_whitespace_still_collapses(self) -> None:
        self.assertEqual(
            item_metadata.normalize_item_name_for_display("Beer"),
            item_metadata.normalize_item_name_for_display("  Beer  "),
        )

    def test_non_string_arguments_still_work(self) -> None:
        """The pre-cache body called `str()`, so ints must not reach the cache raw."""
        self.assertEqual("123", item_metadata.normalize_item_name_for_display(123))
        self.assertEqual("123", item_metadata.normalize_item_name_for_rarity(123))
        self.assertEqual("None", item_metadata.normalize_item_name_for_display(None))

    def test_a_str_subclass_is_not_trusted_as_a_cache_key(self) -> None:
        """A subclass can redefine `__hash__`/`__eq__`; identity must not depend on it."""

        class Weird(str):
            def __hash__(self):  # pragma: no cover -- must never be reached
                raise AssertionError("cache keyed on a str subclass")

            def __eq__(self, other):  # pragma: no cover
                raise AssertionError("cache keyed on a str subclass")

        self.assertEqual("Beer", item_metadata.normalize_item_name_for_display(Weird("Beer")))

    def test_the_caches_are_bounded(self) -> None:
        """Names come from game memory; a corrupt read must not grow forever."""
        for index in range(item_metadata._ITEM_NAME_CACHE_SIZE + 200):
            item_metadata.normalize_item_name_for_display(f"junk-{index}")

        self.assertLessEqual(
            item_metadata._normalize_item_name_for_display.cache_info().currsize,
            item_metadata._ITEM_NAME_CACHE_SIZE,
        )


class StageSummaryEquivalenceTests(unittest.TestCase):
    """The summary itself, over a run that crosses a stage boundary."""

    def _snapshot(self, *, time_s, kills, items, stage_index=0, stage_ptr=1):
        from types import SimpleNamespace

        return SimpleNamespace(
            game_time_seconds=float(time_s),
            mob_kills=kills,
            items=items,
            items_available=True,
            stage_index=stage_index,
            stage_ptr=stage_ptr,
            map_seed=1,
        )

    def test_repeated_builds_over_the_same_run_agree(self) -> None:
        """A second build must not see a mutated cache entry from the first."""
        snapshots = [
            self._snapshot(time_s=0, kills=0, items=()),
            self._snapshot(time_s=30, kills=100, items=("Beer",)),
            self._snapshot(time_s=60, kills=250, items=("Beer", "Key")),
            self._snapshot(time_s=90, kills=400, items=("Beer x2", "Key"), stage_index=1, stage_ptr=2),
        ]

        first = run_summary.build_stage_summary(snapshots)
        second = run_summary.build_stage_summary(snapshots)

        self.assertEqual(first, second)

    def test_growing_prefixes_are_consistent(self) -> None:
        """Scrubbing builds every prefix; none may poison a later one."""
        snapshots = [
            self._snapshot(time_s=index * 10, kills=index * 50, items=("Beer",) * (index % 3 + 1))
            for index in range(12)
        ]

        forwards = [run_summary.build_stage_summary(snapshots[: i + 1]) for i in range(12)]
        backwards = [run_summary.build_stage_summary(snapshots[: i + 1]) for i in reversed(range(12))]

        self.assertEqual(forwards, list(reversed(backwards)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
