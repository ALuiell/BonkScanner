"""No two of `MegabonkApp`'s mixins may assign the same `self.<name>`.

Written after step 19 shipped exactly that fault and nothing caught it.

`LiveStatsTabMixin._build_live_stats_tab` set `self._stat_cards` and
`self._items_section`; `RecordingsTabMixin._build_recordings_tab` set the same
two names. Both mixins are bases of one `MegabonkApp`, so they are one
namespace: the Recordings builder runs second and won. The Live Stats tab then
rendered into the *Recordings* tab's widgets, and its own panels sat on
"Waiting for weapon data..." forever.

Every other check was green. The full suite passed, because each test injects
the component it needs and never builds both tabs. The differential traces
passed, because they drive the components directly. The construction smoke
passed, because it built one tab. `arch_metrics` scored the names as *owned*
rather than hidden, because the reading file also assigns them -- so a
collision reads as good hygiene by that metric.

This is the shared-namespace failure the whole componentization exists to
remove, reintroduced by the componentization, under names that look private
because they start with an underscore. An underscore is not a scope when the
object is shared.

The check is deliberately structural rather than a list of known names: it
parses every mixin in `MegabonkApp`'s declared bases, collects what each
assigns to `self`, and fails on any name assigned by more than one. It costs
nothing and it generalises to steps 20-26, which will add many more component
handles to the same object.
"""
from __future__ import annotations

import ast
import os
import unittest
from collections import defaultdict

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Names legitimately written by more than one mixin, each with the reason.
# This is a debt register, not a permission slip: it may shrink and may not
# grow, exactly like `TOPLEVEL_DEBT` in `test_import_direction.py`. The
# staleness test below deletes entries that stop being real collisions.
#
# Every one of these is genuinely *shared state* co-owned by two features --
# scan lifecycle, recording lifecycle, the timeline pin -- which is a different
# thing from the fault this file was written for. Step 19's bug was two
# **component handles** colliding: each tab thought `self._stat_cards` was its
# own. Shared state has an ownership question that steps 20-26 answer by moving
# it into a service; a component handle has no such question, and a collision
# there is always a bug.
#
# Measured at `5be11f8`. The first draft of this register guessed five entries
# and four of them were not collisions at all -- the staleness test is what
# said so.
PRE_EXISTING_COLLISIONS: dict[str, str] = {
    "_hotkey_manager": "scan lifecycle, co-owned by RunControl and Scanner",
    "is_running": "scan lifecycle, co-owned by RunControl and Scanner",
    "active_templates": "template state, co-owned by Scanner and Templates",
    "template_stats": "template state, co-owned by Scanner and Templates",
    # `_player_stats_completed_run` was here until step 20. It is
    # `RunLifecycle`'s now -- the service extracted precisely because it was
    # written by `player_stats_refresh` and `vod_capture` and read by
    # `refresh_tasks` as well -- so the staleness test below deleted it.
    # That is the register working, and the debt it named being paid.
    # `player_stats_auto_start_detection_streak` was here until step 20.
    # The refresh tick reset it directly; it calls
    # `VodCaptureMixin.note_run_not_in_game()` now, so vod_capture is the
    # only writer and the staleness test deleted the entry. Third
    # consecutive step in which this register has shrunk on its own.
    # `player_stats_disabled_items_cache` and
    # `player_stats_disabled_items_refresh_pending` were here until step 20
    # converted `PlayerStatsMemoryMixin` into the `PlayerStatsMemory` service.
    # The service no longer *assigns* the cache on the shared `self` -- it reads
    # and writes the app-owned cache through injected accessors -- so
    # `TwitchBotMixin` is the only remaining mixin writer and the staleness test
    # deleted both entries.
    # `player_stats_game_data_client` was here too: its coordinator-delegating
    # property moved to `MegabonkApp` (a `__dict__` write, not the `self.x = `
    # assignment the scanner counts), leaving `player_stats_refresh` its only
    # mixin writer. Fifth consecutive step in which this register shrank because
    # the staleness test demanded it, not because anyone remembered.
    # `player_stats_selected_snapshot_index` left this register when step 20
    # converted `VodCaptureMixin` into `VodCapture`. It had two writers, the
    # refresh tick and vod_capture; the service does not write it at all --
    # its three writes to the snapshot buffer were one semantic act and became
    # the injected `reset_snapshot_buffer` command. **Fourth** consecutive
    # step in which this register has shrunk because the staleness test
    # demanded it, not because anyone remembered.
    # `player_stats_snapshot_pinned` was here until step 19. `LiveStatsTab`
    # leaving the MRO left `vod_capture` as its only mixin writer, so the
    # staleness test below deleted it -- which is the register working.
    # `compare_runs_list_signature` was the last entry, and step 21 paid it:
    # the Recordings tab's refresh callback no longer writes the Compare Runs
    # tab's signature. `app.vod_library.VodLibrary` owns the index and *tells*
    # each tab to invalidate its own, so the name has one writer again. Fifth
    # consecutive step in which the staleness test below emptied a slot.
}


def _mro_class_modules() -> dict[str, str]:
    """`MegabonkApp`'s declared bases, parsed from the class statement."""
    path = os.path.join(SRC_ROOT, "gui_app.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MegabonkApp":
            return [base.id for base in node.bases if isinstance(base, ast.Name)]
    raise AssertionError("MegabonkApp class statement not found")


def _class_defs() -> dict[str, ast.ClassDef]:
    """Every class defined under `src/`, by name."""
    found: dict[str, ast.ClassDef] = {}
    for root, dirs, files in os.walk(SRC_ROOT):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", "tests"}]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as handle:
                try:
                    tree = ast.parse(handle.read(), filename=path)
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    found.setdefault(node.name, node)
    return found


def _self_assignments(class_def: ast.ClassDef) -> set[str]:
    """Every `self.NAME = ...` a class performs, at any nesting depth.

    Includes assignments inside nested closures, because the VOD load and
    metadata-refresh completion callbacks are closures that write selection
    state from a worker thread. Step 21c moved both off the MRO into
    `RecordingsTab`, which is why the depth guard below scans that class by
    name rather than through `MegabonkApp`'s bases.
    """
    names: set[str] = set()
    for node in ast.walk(class_def):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            names |= _attribute_names(target)
    return names


def _attribute_names(node: ast.expr) -> set[str]:
    found: set[str] = set()
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            found.add(node.attr)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            found |= _attribute_names(element)
    elif isinstance(node, ast.Starred):
        found |= _attribute_names(node.value)
    return found


def _assignments_by_mixin() -> dict[str, set[str]]:
    classes = _class_defs()
    result: dict[str, set[str]] = {}
    for name in _mro_class_modules():
        class_def = classes.get(name)
        assert class_def is not None, f"could not find class {name} under src/"
        result[name] = _self_assignments(class_def)
    return result


class MixinAttributeCollisionTests(unittest.TestCase):
    def test_no_attribute_is_assigned_by_two_mixins(self) -> None:
        owners: dict[str, list[str]] = defaultdict(list)
        for mixin, names in _assignments_by_mixin().items():
            for name in names:
                owners[name].append(mixin)

        collisions = {
            name: sorted(mixins)
            for name, mixins in owners.items()
            if len(mixins) > 1 and name not in PRE_EXISTING_COLLISIONS
        }

        self.assertEqual(
            collisions,
            {},
            "attribute(s) assigned by more than one mixin on the shared "
            "`MegabonkApp` namespace. Whichever builder runs last wins and the "
            "other feature silently writes into the wrong widgets:\n  "
            + "\n  ".join(f"{n}: {m}" for n, m in sorted(collisions.items())),
        )

    def test_the_two_tabs_own_their_components_separately(self) -> None:
        """The specific regression, now retired rather than guarded.

        Step 19 removed one half structurally: `LiveStatsTab` stopped being a
        base of `MegabonkApp`, so its `_stat_cards` and `_items_section` sit on
        its own object and *cannot* collide. That is the fix the underscore
        prefix was mistaken for.

        **Step 21c removed the other half.** `RecordingsTab` is an object too,
        so its two handles went back to the un-prefixed `_stat_cards` /
        `_items_section` -- which is now correct, not a regression: two private
        attributes on two different objects are not one namespace. The
        `_vod_`-prefix that used to be required is exactly the workaround a real
        conversion retires.

        What remains checkable is that neither tab has come back onto the MRO,
        and that no *mixin* claims the un-prefixed names while it is one.
        """
        assignments = _assignments_by_mixin()

        for gone in ("LiveStatsTabMixin", "RecordingsTabMixin", "CompareRunsMixin"):
            self.assertNotIn(
                gone,
                assignments,
                f"{gone} is back in MegabonkApp's bases",
            )

        tab = _self_assignments(_class_defs()["RecordingsTab"])
        self.assertIn("_stat_cards", tab)
        self.assertIn("_items_section", tab)

        everywhere = set().union(*assignments.values())
        self.assertEqual(
            {"_stat_cards", "_items_section"} & everywhere,
            set(),
            "the un-prefixed handles are on a mixin again; on the shared "
            "object they collide with whatever else claims them",
        )

    def test_the_scan_actually_reads_the_mixins(self) -> None:
        """Step 13's guard: a scan that finds nothing passes trivially."""
        assignments = _assignments_by_mixin()
        # This counts `MegabonkApp`'s bases, and they are being retired one per
        # commit (20f -> 10, 20g -> 9, 21c -> 8, 21d -> 7). The guard exists to
        # catch a scan that reads *nothing*, so it tracks the shrinking MRO
        # rather than pinning it -- the MRO itself is ratcheted by
        # `test_componentization_inventory`'s `MRO_MODULES`, which is where a
        # base reappearing gets caught.
        self.assertGreater(len(assignments), 3, "found almost no mixins")
        # Shrinks with the MRO for the same reason the base count does: steps
        # 21c and 21d took the two recording tabs' assignments off it
        # (231 -> 195 -> 143).
        self.assertGreater(
            sum(len(names) for names in assignments.values()),
            100,
            "found almost no assignments; the walk is not reaching method bodies",
        )
        # A name assigned inside a nested closure must be seen, or the walk is
        # shallower than the code it checks. Anchored on `RecordingsTab` by name
        # rather than through the MRO: step 21c took it off `MegabonkApp`'s
        # bases, and after that **no remaining mixin assigns `self.X` inside a
        # nested function at all** (measured), so routing this guard through
        # `_assignments_by_mixin` would leave it asserting nothing.
        self.assertIn(
            "_list_signature",
            _self_assignments(_class_defs()["RecordingsTab"]),
            "assignments inside nested functions are being missed",
        )

    def test_the_collision_register_does_not_outlive_its_debt(self) -> None:
        """A register entry that is no longer a real collision must go.

        Written the same way `test_allowlists_do_not_outlive_their_debt` is,
        and for the same reason: step 17 was caught by that check four times.
        """
        owners: dict[str, list[str]] = defaultdict(list)
        for mixin, names in _assignments_by_mixin().items():
            for name in names:
                owners[name].append(mixin)

        stale = sorted(
            name
            for name in PRE_EXISTING_COLLISIONS
            if len(owners.get(name, [])) <= 1
        )
        self.assertEqual(
            stale,
            [],
            "PRE_EXISTING_COLLISIONS entries that are no longer assigned by "
            "two mixins. A step paid that debt -- delete the entry so the "
            "register keeps shrinking.",
        )


if __name__ == "__main__":
    unittest.main()
