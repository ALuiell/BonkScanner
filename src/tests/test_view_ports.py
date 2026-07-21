"""Each app-layer render call must go through the port that declares it.

Step 14c named one nine-operation ``PlayerStatsView``. Step 19 measured where
those nine are implemented and found three features, not one:

* 7 in ``ui/tabs/player_stats/live_stats.py`` (step 19 -- five original, plus
  ``set_stage_summary_rows`` and ``refresh_powerups_card``, which replaced the
  last two app-layer calls that reached the UI through the shared namespace)
* 3 in ``gui_overlay.py`` (step 24)
* 1 in ``gui_layout.py`` (step 26)

That is why the accessor had to return the app object: only ``MegabonkApp``
satisfies all nine. Splitting the port is what lets step 19 inject a real
Player Stats view without a composite that delegates four operations back to
the ambient namespace -- which is step 18's rollback condition.

The split only holds if call sites keep using the right accessor, and nothing
else checks that: ``MegabonkApp`` still satisfies all three protocols, so
``player_stats_view(self).update_overlay_state_from_tracker()`` would work
exactly as before while quietly re-merging the ports. This scans the app layer
by AST and fails on the first such call.

It also enforces the direction of travel: ``PlayerStatsView`` is expected to
lose its ambient fallback at step 19, while the other two keep theirs by
design. If a fourth accessor appears, or an operation is added to a protocol
without a home, this test names it.
"""
from __future__ import annotations

import ast
import os
import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app.player_stats_view import (
    OverlayView,
    PlayerStatsView,
    RecordingsListView,
    overlay_view,
    player_stats_view,
    recordings_list_view,
)

SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(SRC_ROOT, "app")

ACCESSORS = {
    "player_stats_view": PlayerStatsView,
    "overlay_view": OverlayView,
    "recordings_list_view": RecordingsListView,
}


def _protocol_operations(protocol) -> set[str]:
    """The method names a Protocol declares, excluding typing machinery."""
    return {
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("__")
    }


def _app_files() -> list[str]:
    found = []
    for root, dirs, files in os.walk(APP_ROOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        found.extend(os.path.join(root, f) for f in files if f.endswith(".py"))
    return sorted(found)


def _rel(path: str) -> str:
    return os.path.relpath(path, SRC_ROOT).replace("\\", "/")


def _accessor_calls() -> list[tuple[str, str, str, int]]:
    """Every `<accessor>(...).<operation>` in `app/`, as (accessor, op, file, line).

    A call bound to a local first (`view = player_stats_view(self)` then
    `view.foo()`) is resolved by following the assignment within the same
    function, because that shape is already in the codebase and skipping it
    would leave a hole exactly where the mixed-port bug lived.

    **The third form is the injected one, and it was a real hole.** Step 20
    converts the app mixins into services that receive their ports as
    constructor callables -- `VodCapture(player_stats_view=lambda:
    player_stats_view(owner))` -- and then call `self._player_stats_view().foo()`.
    Neither of the first two forms sees that, so `VodCapture`'s port calls went
    unchecked from the moment it was converted, and step 20f's `RefreshTasks`
    would have done the same. `_injected_ports` below recovers the binding by
    reading the resolver's keyword lambdas together with `__init__`'s
    `self._x = x`, so a service cannot escape the routing check by taking its
    port through the constructor. The vacuity guard is what surfaced this:
    the scan silently fell from 13 calls to 8.
    """
    calls: list[tuple[str, str, str, int]] = []

    for path in _app_files():
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        rel = _rel(path)
        injected = _injected_ports(tree)

        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # locals bound to an accessor result, within this function
            bound: dict[str, str] = {}
            for node in ast.walk(func):
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target = node.targets[0]
                value = node.value
                if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
                    continue
                if isinstance(value.func, ast.Name) and value.func.id in ACCESSORS:
                    bound[target.id] = value.func.id

            for node in ast.walk(func):
                if not isinstance(node, ast.Attribute):
                    continue
                base = node.value
                # player_stats_view(self).operation
                if (
                    isinstance(base, ast.Call)
                    and isinstance(base.func, ast.Name)
                    and base.func.id in ACCESSORS
                ):
                    calls.append((base.func.id, node.attr, rel, node.lineno))
                # view.operation, where view = player_stats_view(self)
                elif isinstance(base, ast.Name) and base.id in bound:
                    calls.append((bound[base.id], node.attr, rel, node.lineno))
                # self._view().operation, where the service was constructed with
                # `view=lambda: player_stats_view(owner)` and `__init__` did
                # `self._view = view`.
                elif (
                    isinstance(base, ast.Call)
                    and isinstance(base.func, ast.Attribute)
                    and isinstance(base.func.value, ast.Name)
                    and base.func.value.id == "self"
                    and base.func.attr in injected
                ):
                    calls.append((injected[base.func.attr], node.attr, rel, node.lineno))

    return calls


def _injected_ports(tree: ast.Module) -> dict[str, str]:
    """`self.<attr>` -> accessor, for ports handed to a service's constructor.

    Two halves, both read from the module rather than declared by hand so this
    cannot drift from the code: the resolver's `Name(kw=lambda: accessor(owner))`
    keywords give `kw -> accessor`, and each class's `__init__` doing
    `self._x = x` gives `_x -> kw`.
    """
    keyword_to_accessor: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg is None or not isinstance(keyword.value, ast.Lambda):
                continue
            body = keyword.value.body
            if (
                isinstance(body, ast.Call)
                and isinstance(body.func, ast.Name)
                and body.func.id in ACCESSORS
            ):
                keyword_to_accessor[keyword.arg] = body.func.id

    attr_to_accessor: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
            continue
        for statement in ast.walk(node):
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target, value = statement.targets[0], statement.value
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(value, ast.Name)
                and value.id in keyword_to_accessor
            ):
                attr_to_accessor[target.attr] = keyword_to_accessor[value.id]
    return attr_to_accessor


class ViewPortRoutingTests(unittest.TestCase):
    def test_every_accessor_call_uses_a_port_that_declares_the_operation(self) -> None:
        misrouted = []
        for accessor, operation, rel, lineno in _accessor_calls():
            declared = _protocol_operations(ACCESSORS[accessor])
            if operation not in declared:
                owner = [
                    name
                    for name, proto in ACCESSORS.items()
                    if operation in _protocol_operations(proto)
                ]
                misrouted.append(
                    f"{rel}:{lineno}: {accessor}(...).{operation} -- "
                    f"{'use ' + owner[0] + '()' if owner else 'no port declares this'}"
                )

        self.assertEqual(
            misrouted,
            [],
            "app-layer call(s) routed through the wrong view port:\n  "
            + "\n  ".join(misrouted),
        )

    def test_the_harness_actually_finds_calls(self) -> None:
        """Step 13's guard: a scan that finds nothing passes trivially."""
        calls = _accessor_calls()
        self.assertGreater(len(calls), 10, "accessor scan found almost nothing")
        self.assertEqual(
            sorted({accessor for accessor, _, _, _ in calls}),
            sorted(ACCESSORS),
            "not every accessor is exercised by the app layer",
        )

    def test_the_three_protocols_partition_the_declared_surface(self) -> None:
        """No operation is dropped, duplicated, or invented by the split.

        Eleven now: the original nine, plus `set_stage_summary_rows` and
        `refresh_powerups_card`, both added at step 19 to replace an app-layer
        call that reached the UI through the shared namespace instead of
        through this port.
        """
        groups = [_protocol_operations(p) for p in ACCESSORS.values()]
        union: set[str] = set()
        for group in groups:
            self.assertEqual(
                union & group, set(), "an operation is declared by two ports"
            )
            union |= group
        self.assertEqual(
            len(union),
            11,
            f"expected the original nine plus the two step-19 additions, got {sorted(union)}",
        )

    def test_the_scheduled_fallbacks_are_the_ones_still_expected(self) -> None:
        """The overlay and recordings-list fallbacks are deliberate, until 24/26.

        Pinned so that removing one is a decision someone makes on purpose,
        and so that a reader can tell a scheduled fallback from a forgotten
        one. Update this when step 24 or 26 lands.
        """
        owner = type("Owner", (), {})()
        self.assertIs(overlay_view(owner), owner)
        self.assertIs(recordings_list_view(owner), owner)

        injected = object()
        owner.__dict__["_player_stats_view"] = injected
        self.assertIs(player_stats_view(owner), injected)


if __name__ == "__main__":
    unittest.main()
