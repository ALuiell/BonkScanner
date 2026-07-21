"""Step 18 phase 1 -- the two componentization blockers, measured and ratcheted.

Step 18 may not convert a mixin into a constructor-injected component until both
compatibility constraints are named, because both silently defeat the
conversion:

1. **Class-qualified references** (`SomeMixin.method`) resolve through
   `MegabonkApp`'s MRO rather than through an instance. They do not follow a
   method when it moves onto a component, and -- the reason this file exists --
   they are invisible to every other check in the suite. Step 14b asserted that
   all 59 methods it *moved* resolved from their new modules and still shipped a
   live `AttributeError`, because a call site that **stayed behind** kept naming
   the old class. The Chaos Tome panel was broken for two commits through a
   green suite and a reported-working exe. Steps 7, 13, 14b and 14c all hit some
   form of this.

2. **`object.__new__(MegabonkApp)` test doubles**, which skip `__init__`
   entirely. Constructor injection is incompatible with them: a component that
   takes its tracker/recorder/command ports as constructor arguments can never
   be reached from an instance that was never constructed.

Both were re-measured by AST here, and both differ from the estimates recorded
in the roadmap. The numbers below are the measurement, not the estimate.

Measured 2026-07-19 at `84291cb`
================================

**Class-qualified references: 219 occurrences across 96 names** -- but the split
is the finding, and the roadmap's flat "184 across 82" hides it:

    production   19 occurrences /  8 names
    tests       200 occurrences / 89 names

**91% of the constraint is test-side**, and it is the mechanical
`MegabonkApp.method(fake_self, ...)` unbound-call idiom, not production
coupling. The production surface a component conversion must actually retarget
is eight names:

    OverlayMixin._overlay_available_item_names     gui_dialogs.py:1256
    OverlayMixin._tracked_item_color               gui_dialogs.py:1550
    OverlayMixin._tracked_rule_color               gui_dialogs.py:1583
    OverlayMixin._tracked_rule_tag_label           gui_dialogs.py:1586
    OverlayMixin._tracked_item_rules_from_config   gui_overlay.py:1344,1348

**Step 21d removed the last of this file's own tab entries.** The nine
`format_compare_runs_*` classmethods, the three config readers and
`_nearest_snapshot_index` on `CompareRunsMixin` were sixteen unbound
`MegabonkApp.<name>(...)` call sites in the suite. They are module-level
functions in `ui/tabs/compare_runs/tab.py` (or, for the nine, simply gone --
`projections.formatting` is the target now). Same treatment as step 19's
`chaos_stats_in_game_order` and step 20's two memory recorders: a free function
has no class to be orphaned from, so the failure mode is retired rather than
relocated.

**Step 20 removed both `PlayerStatsMemoryMixin` entries**, which were twelve of
the eighteen sites -- ten in `app/player_stats_memory.py` and two in
`app/player_stats_refresh.py`. Both are now the module-level
`record_player_stats_game_data_memory_success` / `_failure`, matching the
sibling pair in `app/refresh_tasks.py` that always had that shape. The two are
one policy over two clients and only one of them looked it.

Like step 19's `_chaos_stats_in_game_order`, this **retires** the failure mode
rather than relocating it: a free function has no class to be orphaned from, so
the conversion of `PlayerStatsMemoryMixin` into a service can no longer strand
a call site the way 14b stranded the Chaos Tome panel. The production ratchets
tightened to 6 sites / 5 names, and all five that remain are `OverlayMixin`'s,
owned by step 24.

Note what is *not* in that list: the Player Stats view mixins
(`LiveStatsTabMixin`, `RecordingsTabMixin`) have **zero** production
class-qualified callers. Converting a player-stats view object is therefore
not blocked by this constraint at all -- which is why it was the bounded pilot.

**Step 19 removed the one player-stats entry**,
`PlayerStatsCardsMixin._chaos_stats_in_game_order` (was cards.py:385) -- the
exact name that broke at 14b. It is now the module-level
`ui.tabs.player_stats.stat_cards.chaos_stats_in_game_order`, which retires the
failure mode instead of relocating it: the 14b breakage was a call site naming
a class the method had left, and a free function has no class to leave. The
production ratchets tightened to 18 sites / 7 names.

**`object.__new__` app doubles: 71, all in one file.** Every one is in
`src/tests/test_gui_run_control.py`. The roadmap's 71 was off by one and did not
record the confinement, which is the operative fact: the migration is a
single-module change, not a suite-wide one.

Fixture/builder migration plan
==============================

The 71 doubles exist to get a `MegabonkApp`-shaped namespace without paying for
`__init__` (which builds a `QApplication`, ~166 widgets, an `AppCoordinator`, an
overlay server and a hotkey manager). They are not testing `MegabonkApp`; they
are borrowing its MRO to call one method with a hand-stubbed `self`.

The replacement is **not** one "minimal app" builder -- that would re-create the
ambient namespace under a nicer name, which is the step-18 rollback condition.
It is two distinct moves, applied per call site:

1. **Component builders (the target shape).** For each converted component, a
   `build_<component>(**overrides)` helper in `src/tests/support/` that calls
   the real constructor with fake ports and fake widgets. Explicit, typed, and
   it fails loudly when a dependency is added -- the opposite of
   `object.__new__`, which absorbs new dependencies silently as `AttributeError`
   at the first read.
2. **Plain namespace doubles for what is not yet converted.** Call sites whose
   subject is still a mixin keep an unbound call, but against a
   `SimpleNamespace`-style stub rather than `object.__new__(MegabonkApp)`. This
   removes the *class* dependency without pretending the method has moved.

Migration order follows conversion order: a call site is migrated by the step
that converts its subject, never in bulk ahead of it. Bulk-migrating first would
produce 71 builder calls for components that do not exist yet.

Both counts below are ratchets. They may shrink; they may not grow.
"""

from __future__ import annotations

import ast
import importlib
import os
import unittest
from collections import defaultdict

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `MegabonkApp` plus its declared bases. Parsed from the class statement rather
# than imported, so this list cannot drift from `gui_app.py`.
MRO_MODULES = {
    "MegabonkApp": "gui_app",
    "GuiLayoutMixin": "gui_layout",
    "RunControlMixin": "gui_run_control",
    "OverlayMixin": "gui_overlay",
    "InGameOverlayMixin": "gui_in_game_overlay",
    # `PlayerStatsRefreshMixin` was here until step 20g converted it into the
    # `PlayerStatsRefresh` service, taking `MegabonkApp` to nine bases and the
    # app-layer slice to zero. It was the last of the five app-side bases the
    # step named.
    # `TemplatesMixin` was here until step 22c. `gui_templates.py` held three
    # unrelated things: 22a took map evaluation to `app.map_scoring`, 22b took
    # the runtime filter state to `app.template_filters`, 22c made the rest
    # `ui.tabs.templates.TemplatesPanel` and moved the two footer dialogs to
    # `MegabonkApp`. The module is deleted; `MegabonkApp` is at **six** bases.
    # Both of step 21's subjects were here. 21c converted `RecordingsTabMixin`
    # into `RecordingsTab` and 21d converted `CompareRunsMixin` into
    # `CompareRunsTab`, each an object built by its own composition root in
    # `gui_layout`. `MegabonkApp` went 9 -> 8 -> **7** bases, and the two
    # recording tabs are gone from this map for good: neither has a class to be
    # qualified through any more.
    # `TwitchBotMixin` was here until step 23. Its widgets became
    # `ui.tabs.twitch.TwitchTab` (23b) and its behaviour became
    # `app.twitch_session.TwitchSession` (23c), wired by `build_twitch_session`
    # in `gui_twitch.py` -- which survives holding only the two token `QThread`
    # classes, because neither `ui/` nor `app/` may import `twitch_auth`.
    # `MegabonkApp` is at **five** bases.
    "ScannerMixin": "gui_scanner",
}

# Ratchets, measured 2026-07-19 at 84291cb. These may only shrink.
# Tightened at step 19 (19 -> 18 sites, 8 -> 7 names): the cards renderer's
# `_chaos_stats_in_game_order` became a module-level function in
# `ui/tabs/player_stats/stat_cards.py`, which is what retires the failure mode
# rather than relocating it -- a free function cannot be orphaned by its class
# moving, which is precisely what broke at 14b.
MAX_PRODUCTION_CLASS_QUALIFIED_SITES = 6
MAX_PRODUCTION_CLASS_QUALIFIED_NAMES = 5
# Tightened at step 21c (60 -> 55) and 21d (55 -> 52). The eight doubles whose
# subject was one of the two recording tabs now call the component builders those
# conversions added: `tests/support/player_stats.build_recordings_tab` (5) and
# `tests/support/compare_runs.build_compare_runs_tab` (3). Step 20h recorded that
# 60 would hold until steps 21-26; step 21 is the first to move it, and it is the
# migration order this file's header states -- a call site is migrated by the
# step that converts its subject.
#
# 52 is the *measured* count, not a margin. It was left at 55 for one commit
# after 21d had already reached 52, which is the failure mode a ratchet is meant
# to prevent: three doubles of slack is three that can be added back for free.
#
# Tightened at step 22 (52 -> 48). Four doubles retired, each because its
# subject stopped being a mixin method:
#   22a  test_format_stats_includes_bald_heads_...  -> tests/test_map_scoring.py
#          (a free function needs no app at all)
#   22c  test_edit_template_dialog_opens_template_manager
#        test_save_checkbox_state_updates_runtime_templates_without_restart
#        test_refresh_scores_ui_updates_runtime_tiers_without_restart
#          -> tests/test_templates_panel.py, via
#             tests/support/templates_panel.build_templates_panel
#
# 48 is measured, not rounded down to a safe number. The step-22 inventory found
# 21d had reported 52 while leaving the constant at 55, and the `<=` comparison
# hid it; repeating that here would be repeating the thing that fix was for.
MAX_OBJECT_NEW_APP_DOUBLES = 47

# The one module allowed to build app doubles without `__init__`.
OBJECT_NEW_HOME = "tests/test_gui_run_control.py"

PRODUCTION_CLASS_QUALIFIED_NAMES = {
    "OverlayMixin._overlay_available_item_names",
    "OverlayMixin._tracked_item_color",
    "OverlayMixin._tracked_item_rules_from_config",
    "OverlayMixin._tracked_rule_color",
    "OverlayMixin._tracked_rule_tag_label",
}


def _declared_mro_class_names() -> list[str]:
    path = os.path.join(SRC_ROOT, "gui_app.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MegabonkApp":
            return ["MegabonkApp"] + [
                base.id for base in node.bases if isinstance(base, ast.Name)
            ]
    raise AssertionError("MegabonkApp class statement not found in gui_app.py")


def _python_files() -> list[str]:
    found = []
    for root, dirs, files in os.walk(SRC_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _rel(path: str) -> str:
    return os.path.relpath(path, SRC_ROOT).replace("\\", "/")


def _referenced_class(node: ast.expr, mro: set[str]) -> str | None:
    """The MRO class a node names, bare (`MegabonkApp`) or dotted (`gui.MegabonkApp`).

    Both forms must be recognised. The dotted one was missed by the first
    version of this scan, and the omission was invisible until the confinement
    test was mutated with `object.__new__(gui_app.MegabonkApp)` and stayed
    green -- an undercount in the measurement, not just a gap in the mutation.
    """
    if isinstance(node, ast.Name) and node.id in mro:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in mro:
        return node.attr
    return None


def _spelling(node: ast.expr) -> str:
    """How a class was written at a call site, for reporting."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "<dynamic>"


def _scan() -> tuple[dict[str, list], dict[str, list]]:
    """AST scan, not regex: a regex counts class statements and docstrings too."""
    mro = set(_declared_mro_class_names())
    qualified: dict[str, list] = defaultdict(list)
    object_new: dict[str, list] = defaultdict(list)

    for path in _python_files():
        rel = _rel(path)
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                owner = _referenced_class(node.value, mro)
                if owner is not None:
                    qualified[f"{owner}.{node.attr}"].append((rel, node.lineno))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "__new__"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "object"
                and node.args
            ):
                # Every `object.__new__` counts, however the class is spelled.
                # Matching only known MRO names let an aliased import
                # (`MegabonkApp as _MA`) slip the ratchet silently; there is no
                # legitimate other use of `object.__new__` in this tree, so the
                # broad match costs nothing and closes the evasion.
                object_new[_spelling(node.args[0])].append((rel, node.lineno))
    return qualified, object_new


class ClassQualifiedReferenceTests(unittest.TestCase):
    def test_every_class_qualified_reference_still_resolves(self) -> None:
        """The step-14b trap: the MRO check does not cover these.

        A moved method resolving from its new module proves nothing about a call
        site that stayed behind naming the old class. Assert the reference
        itself, which is the only thing that would have caught the Chaos Tome
        break.
        """
        qualified, _ = _scan()
        self.assertTrue(qualified, "scan found no class-qualified references at all")

        unresolved = []
        for name, sites in sorted(qualified.items()):
            class_name, attribute = name.split(".", 1)
            module = importlib.import_module(MRO_MODULES[class_name])
            owner = getattr(module, class_name)
            if not hasattr(owner, attribute):
                unresolved.append(f"{name} -- first at {sites[0][0]}:{sites[0][1]}")

        self.assertEqual(
            [],
            unresolved,
            "class-qualified references that no longer resolve:\n  "
            + "\n  ".join(unresolved),
        )

    def test_mro_module_map_covers_the_declared_bases(self) -> None:
        """If a base is added to MegabonkApp, this map must learn about it."""
        self.assertEqual(sorted(_declared_mro_class_names()), sorted(MRO_MODULES))

    def test_production_class_qualified_surface_does_not_grow(self) -> None:
        qualified, _ = _scan()
        production: dict[str, list] = defaultdict(list)
        for name, sites in qualified.items():
            for rel, lineno in sites:
                if not rel.startswith("tests/"):
                    production[name].append((rel, lineno))

        total = sum(len(sites) for sites in production.values())
        self.assertLessEqual(
            total,
            MAX_PRODUCTION_CLASS_QUALIFIED_SITES,
            "new production class-qualified call site(s); these do not follow a "
            "method onto a component",
        )
        self.assertLessEqual(
            len(production),
            MAX_PRODUCTION_CLASS_QUALIFIED_NAMES,
            f"new class-qualified name(s): "
            f"{sorted(set(production) - PRODUCTION_CLASS_QUALIFIED_NAMES)}",
        )
        self.assertTrue(
            set(production) <= PRODUCTION_CLASS_QUALIFIED_NAMES,
            f"unrecorded class-qualified name(s): "
            f"{sorted(set(production) - PRODUCTION_CLASS_QUALIFIED_NAMES)}",
        )

    def test_class_qualified_allowlist_does_not_outlive_its_debt(self) -> None:
        """An entry that no longer names a real call site must be removed.

        Added at step 19, for the reason `test_import_direction`'s equivalent
        already exists: a subset assertion alone lets the list keep entries for
        debt that has been paid, and a ratchet nobody has to shrink stops being
        a ratchet. Step 19 retired
        `PlayerStatsCardsMixin._chaos_stats_in_game_order` and the subset check
        stayed green over the stale entry.
        """
        qualified, _ = _scan()
        production = {
            name
            for name, sites in qualified.items()
            if any(not rel.startswith("tests/") for rel, _ in sites)
        }
        self.assertEqual(
            sorted(PRODUCTION_CLASS_QUALIFIED_NAMES - production),
            [],
            "allowlist entries with no remaining production call site; delete "
            "them and tighten MAX_PRODUCTION_CLASS_QUALIFIED_*",
        )


class ObjectNewAppDoubleTests(unittest.TestCase):
    def test_app_double_count_does_not_grow(self) -> None:
        _, object_new = _scan()
        total = sum(len(sites) for sites in object_new.values())
        self.assertLessEqual(
            total,
            MAX_OBJECT_NEW_APP_DOUBLES,
            "new object.__new__ app double(s); constructor injection cannot "
            "reach an instance that never ran __init__",
        )

    def test_app_doubles_stay_confined_to_one_module(self) -> None:
        """The migration is single-module. Keep it that way.

        A double appearing in a second test module means the pattern is
        spreading faster than the conversion retires it.
        """
        _, object_new = _scan()
        homes = {rel for sites in object_new.values() for rel, _ in sites}
        self.assertLessEqual(
            homes,
            {OBJECT_NEW_HOME},
            f"object.__new__ app doubles escaped {OBJECT_NEW_HOME}: "
            f"{sorted(homes - {OBJECT_NEW_HOME})}",
        )

    def test_app_doubles_target_only_the_app_class(self) -> None:
        """They borrow MegabonkApp's MRO; none targets a mixin directly."""
        _, object_new = _scan()
        self.assertEqual(["MegabonkApp"], sorted(object_new))


if __name__ == "__main__":
    unittest.main()
