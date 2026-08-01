"""The one writer of the three tracked-item lists.

Everything here is about the *republish*, not about the config write. Writing
was never the part that broke: the three dialogs that this replaced each wrote
their own key correctly, and then disagreed about what else a change has to
reach. One of them reached nothing at all -- ``TwitchCommandSettingsDialog``
guarded the tracker rebuild with
``hasattr(master, "_combined_tracked_item_rules")``, a method on
``gui_overlay.Overlay`` and not on the application it probed, so the rebuild
never ran in any build.

That bug had a test. It passed, because the test's ``master`` double was a
``SimpleNamespace`` given ``_combined_tracked_item_rules`` by hand -- the probe
was true there and false everywhere else. So the cases below never assert
against a double that was handed the thing under test: the ports are recorders,
and what is asserted is that all four of them fired.
"""

from __future__ import annotations

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

import unittest
from types import SimpleNamespace

from app import config
from app.tracked_item_settings import (
    OVERLAY,
    SESSION,
    SOURCE_OWN,
    SOURCE_SESSION,
    TWITCH,
    TrackedItemSettings,
    combine_rules,
    rule_id,
)


def _rule(item_names, mode="map_1_only"):
    return {
        "id": "_".join(item_names).lower() + "_" + mode,
        "label": " + ".join(item_names),
        "item_names": list(item_names),
        "mode": mode,
    }


class _Recorder:
    """The four things a write has to reach, each one counting its calls."""

    def __init__(self) -> None:
        self.rule_sets: list[tuple] = []
        self.saves = 0
        self.session_rows = 0
        self.snapshots = 0
        self.combined = ("combined",)

    def settings(self) -> TrackedItemSettings:
        tracker = SimpleNamespace(
            set_tracked_item_rules=lambda rules: self.rule_sets.append(tuple(rules))
        )
        return TrackedItemSettings(
            tracker=lambda: tracker,
            combined_rules=lambda: self.combined,
            refresh_session_rows=lambda: setattr(
                self, "session_rows", self.session_rows + 1
            ),
            refresh_snapshot=lambda: setattr(self, "snapshots", self.snapshots + 1),
            save=lambda: setattr(self, "saves", self.saves + 1),
        )


class TrackedItemSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            "SESSION_TRACKED_ITEMS": config.SESSION_TRACKED_ITEMS,
            "OVERLAY": config.OVERLAY,
            "TWITCH_BOT": config.TWITCH_BOT,
        }
        config.SESSION_TRACKED_ITEMS = {"tracked_items": []}
        config.OVERLAY = {"tracked_items": [], "tracked_items_source": SOURCE_OWN}
        config.TWITCH_BOT = {"tracked_items": [], "tracked_items_source": SOURCE_OWN}
        self.recorder = _Recorder()
        self.settings = self.recorder.settings()

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            setattr(config, name, value)

    def test_writing_any_list_republishes_every_rule(self) -> None:
        """All three targets, because the bug was in exactly one of them.

        A case that only drove Session Stats would have passed against the code
        this replaced.
        """
        for target in (SESSION, OVERLAY, TWITCH):
            with self.subTest(target=target.key):
                before = len(self.recorder.rule_sets)
                self.settings.set_rules(target, [_rule(["Anvil"])])

                self.assertEqual(
                    self.recorder.rule_sets[before:], [self.recorder.combined]
                )

    def test_a_write_saves_and_refreshes_as_well_as_republishing(self) -> None:
        self.settings.set_rules(TWITCH, [_rule(["Anvil"])])

        self.assertEqual(self.recorder.saves, 1)
        self.assertEqual(self.recorder.session_rows, 1)
        self.assertEqual(self.recorder.snapshots, 1)

    def test_the_written_list_lands_in_that_targets_config_key(self) -> None:
        self.settings.set_rules(OVERLAY, [_rule(["Anvil"])])

        self.assertEqual(len(config.OVERLAY["tracked_items"]), 1)
        self.assertEqual(config.SESSION_TRACKED_ITEMS["tracked_items"], [])
        self.assertEqual(config.TWITCH_BOT["tracked_items"], [])
        self.assertIs(config.user_config["OVERLAY"], config.OVERLAY)

    def test_switching_the_source_republishes_too(self) -> None:
        """Mirroring changes what a surface counts without touching a list."""
        self.settings.set_source(TWITCH, SOURCE_SESSION)

        self.assertEqual(config.TWITCH_BOT["tracked_items_source"], SOURCE_SESSION)
        self.assertEqual(self.recorder.rule_sets, [self.recorder.combined])
        self.assertEqual(self.recorder.saves, 1)

    def test_session_stats_cannot_mirror(self) -> None:
        """It is the list the other two mirror; there is nothing above it."""
        self.settings.set_source(SESSION, SOURCE_SESSION)

        self.assertEqual(self.settings.source(SESSION), SOURCE_OWN)
        self.assertEqual(self.recorder.rule_sets, [])

    def test_effective_rules_follow_the_source(self) -> None:
        self.settings.set_rules(SESSION, [_rule(["Anvil"])])
        self.settings.set_rules(OVERLAY, [_rule(["Clover"], "all_run")])

        self.assertEqual(
            [rule["item_names"] for rule in self.settings.effective_rules(OVERLAY)],
            [["Clover"]],
        )

        self.settings.set_source(OVERLAY, SOURCE_SESSION)

        self.assertEqual(
            [rule["item_names"] for rule in self.settings.effective_rules(OVERLAY)],
            [["Anvil"]],
        )
        # Its own list is kept, not discarded: switching back has to bring it
        # back, and the window says so on screen.
        self.assertEqual(
            [rule["item_names"] for rule in self.settings.rules(OVERLAY)], [["Clover"]]
        )

    def test_a_config_container_replaced_wholesale_is_still_written(self) -> None:
        """`config.OVERLAY` is rebound by other savers, not mutated in place.

        Holding the dict from construction is the failure this guards: the next
        `config.OVERLAY = normalize(...)` anywhere else would leave this writing
        into an object nothing reads.
        """
        config.OVERLAY = {"tracked_items": [], "tracked_items_source": SOURCE_OWN}

        self.settings.set_rules(OVERLAY, [_rule(["Anvil"])])

        self.assertEqual(len(config.OVERLAY["tracked_items"]), 1)


class RuleIdentityTests(unittest.TestCase):
    def test_each_target_prefixes_its_rule_ids(self) -> None:
        """Two surfaces tracking the same thing need two counters.

        `combine_rules` keys by id, so without the prefixes one of the two would
        vanish into the other and both would read the same number.
        """
        ids = {
            target.key: rule_id(target, ["Anvil"], "map_1_only")
            for target in (SESSION, OVERLAY, TWITCH)
        }

        self.assertEqual(len(set(ids.values())), 3, ids)
        self.assertEqual(ids["overlay"], "anvil_map_1_only")

    def test_combining_keeps_one_rule_per_id_across_the_three_lists(self) -> None:
        saved = (config.SESSION_TRACKED_ITEMS, config.OVERLAY, config.TWITCH_BOT)
        config.SESSION_TRACKED_ITEMS = {"tracked_items": [_rule(["Anvil"])]}
        config.OVERLAY = {"tracked_items": [_rule(["Anvil"])]}
        config.TWITCH_BOT = {"tracked_items": []}
        try:
            seen = []

            def rules_from_config(container):
                built = tuple(
                    SimpleNamespace(id=str(rule.get("id")))
                    for rule in container.get("tracked_items") or ()
                )
                seen.append(len(built))
                return built

            combined = combine_rules(rules_from_config)
        finally:
            (
                config.SESSION_TRACKED_ITEMS,
                config.OVERLAY,
                config.TWITCH_BOT,
            ) = saved

        # All three lists were read, and the two rules sharing an id collapsed.
        self.assertEqual(seen, [1, 1, 0])
        self.assertEqual(len(combined), 1)


if __name__ == "__main__":
    unittest.main()
