"""`app.template_filters` -- and the ownership claim step 22b makes.

Two `PRE_EXISTING_COLLISIONS` entries were deleted at 22b. The register's
staleness test would have deleted them regardless, because taking
`TemplatesMixin` off the MRO hides its writes from a scan that reads only
`MegabonkApp`'s bases -- so passing that test proves nothing here. These tests
are what make the deletion honest: they assert the two names have exactly one
home in production, and that the scanner's unchanged `self.active_templates = `
reaches it.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
from app.template_filters import TemplateRuntimeFilters
from tests.support.template_filters import build_template_filters


class FakeThread:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _BareOwner:
    """Anything with a `__dict__`. The four delegators touch nothing else.

    `_template_filters_owner` is bound from the real class rather than
    reimplemented -- a copy here would pass while production diverged.
    """

    from gui_app import MegabonkApp as _App

    _template_filters_owner = _App._template_filters_owner
    del _App


class OwnershipTests(unittest.TestCase):
    """The two names have one home, and the app is a window onto it.

    These drive `MegabonkApp`'s property descriptors directly rather than
    building an app. That is not a dodge around
    `test_componentization_inventory`'s two double ratchets -- it is the more
    precise test: the delegators read and write `self.__dict__` and nothing
    else, so an app instance would add ~200 unrelated attributes and prove less.
    """

    def _set(self, name, target, value):
        from gui_app import MegabonkApp

        getattr(MegabonkApp, name).fset(target, value)

    def _get(self, name, target):
        from gui_app import MegabonkApp

        return getattr(MegabonkApp, name).fget(target)

    def test_the_app_property_reads_and_writes_the_owner(self) -> None:
        target = _BareOwner()
        owner = build_template_filters()
        target._template_filters = owner

        # The two writes `gui_scanner` makes, unchanged in shape by step 22.
        self._set("active_templates", target, ["Alpha"])
        self._set("template_stats", target, {"Alpha": {"rerolls_since_last": 0, "history": []}})

        self.assertEqual(owner.active_templates, ["Alpha"])
        self.assertEqual(
            owner.template_stats,
            {"Alpha": {"rerolls_since_last": 0, "history": []}},
        )
        self.assertEqual(self._get("active_templates", target), ["Alpha"])
        # No second copy anywhere on the app.
        for slot in ("active_templates", "template_stats", "_active_templates", "_template_stats"):
            self.assertNotIn(slot, target.__dict__)

    def test_the_getter_defaults_rather_than_raising_when_there_is_no_owner(self) -> None:
        """`MegabonkApp.__getattr__` forwards misses to `self.window`.

        A getter that raised AttributeError would be *caught* by that forwarding
        and answered by a widget -- a silent wrong answer rather than a failure.
        The fallback is the `ScannerMixin.client` affordance for app doubles;
        production always has the owner, which the test above pins.
        """
        target = _BareOwner()
        self.assertEqual(self._get("active_templates", target), [])
        self.assertEqual(self._get("template_stats", target), {})
        self._set("active_templates", target, ["Solo"])
        self.assertEqual(self._get("active_templates", target), ["Solo"])

    def test_the_real_init_builds_the_owner_and_keeps_no_slot(self) -> None:
        import ast
        import inspect

        import gui_app

        source = inspect.getsource(gui_app.MegabonkApp.__init__)
        tree = ast.parse(source.lstrip())
        assigned = {
            target.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        }
        self.assertIn("_template_filters", assigned)
        self.assertNotIn("active_templates", assigned)
        self.assertNotIn("template_stats", assigned)


class SyncTests(unittest.TestCase):
    """`sync` behaviour, preserved from `TemplatesMixin._sync_runtime_filters`."""

    def test_templates_mode_replaces_active_templates_from_the_selection(self) -> None:
        filters = build_template_filters(selected_template_names=lambda: ["Alpha", "Gamma"])
        filters.active_templates = ["Alpha"]
        filters.template_stats = {
            "Alpha": {"rerolls_since_last": 2, "history": [3]},
            "Beta": {"rerolls_since_last": 1, "history": [4]},
        }

        with patch.object(config, "EVALUATION_MODE", "templates"):
            filters.sync()

        self.assertEqual(filters.active_templates, ["Alpha", "Gamma"])
        # Existing stats survive; new names start at zero; dropped names are kept.
        self.assertEqual(filters.template_stats["Alpha"]["history"], [3])
        self.assertEqual(filters.template_stats["Gamma"], {"rerolls_since_last": 0, "history": []})
        self.assertEqual(filters.template_stats["Beta"], {"rerolls_since_last": 1, "history": [4]})

    def test_scores_mode_uses_the_active_tiers_and_leaves_active_templates_alone(self) -> None:
        filters = build_template_filters(selected_template_names=lambda: ["Alpha"])
        filters.active_templates = ["Alpha"]

        scores = {**config.SCORES_SYSTEM, "active_tiers": ["Light", "Perfect"]}
        with patch.object(config, "EVALUATION_MODE", "scores"):
            with patch.object(config, "SCORES_SYSTEM", scores):
                filters.sync()

        self.assertEqual(filters.active_templates, ["Alpha"])
        self.assertEqual(sorted(filters.template_stats), ["Light", "Perfect"])

    def test_announce_is_silent_when_the_scan_is_not_running(self) -> None:
        logs: list[str] = []
        filters = build_template_filters(
            selected_template_names=lambda: ["Alpha"],
            log=logs.append,
            is_scanning=lambda: False,
        )
        with patch.object(config, "EVALUATION_MODE", "templates"):
            filters.sync(announce=True)
        self.assertEqual(logs, [])

    def test_announce_is_silent_when_nothing_changed(self) -> None:
        """The `previous_names` snapshot is taken before the setdefault loop."""
        logs: list[str] = []
        filters = build_template_filters(
            selected_template_names=lambda: ["Alpha"],
            log=logs.append,
            is_scanning=lambda: True,
        )
        filters.template_stats = {"Alpha": {"rerolls_since_last": 0, "history": []}}
        with patch.object(config, "EVALUATION_MODE", "templates"):
            filters.sync(announce=True)
        self.assertEqual(logs, [])

    def test_announce_names_the_mode_and_the_new_selection(self) -> None:
        logs: list[tuple[object, dict]] = []

        def record_log(message, **kwargs) -> None:
            logs.append((message, kwargs))

        filters = build_template_filters(
            selected_template_names=lambda: ["Alpha", "Gamma"],
            log=record_log,
            is_scanning=lambda: True,
        )
        templates = [
            {"name": "Alpha", "color": "GREEN"},
            {"name": "Gamma", "color": "LIGHTRED_EX"},
        ]
        with patch.object(config, "EVALUATION_MODE", "templates"), patch.object(
            config, "TEMPLATES", templates
        ):
            filters.sync(announce=True)
        self.assertEqual(
            logs,
            [
                (
                    ["[*] Active templates updated live: ", "Alpha", ", ", "Gamma"],
                    {"tag": [None, "GREEN", None, "LIGHTRED_EX"]},
                )
            ],
        )

        logs.clear()
        scores = {**config.SCORES_SYSTEM, "active_tiers": ["Light"]}
        with patch.object(config, "EVALUATION_MODE", "scores"):
            with patch.object(config, "SCORES_SYSTEM", scores):
                filters.sync(announce=True)
        self.assertEqual(logs, [("[*] Active tiers updated live: Light", {})])

    def test_an_empty_selection_announces_none(self) -> None:
        logs: list[str] = []
        filters = build_template_filters(
            selected_template_names=list,
            log=logs.append,
            is_scanning=lambda: True,
        )
        filters.template_stats = {"Alpha": {"rerolls_since_last": 0, "history": []}}
        with patch.object(config, "EVALUATION_MODE", "templates"):
            filters.sync(announce=True)
        self.assertEqual(logs, ["[*] Active templates updated live: none"])

    def test_refresh_stats_runs_on_every_sync(self) -> None:
        calls: list[int] = []
        filters = build_template_filters(refresh_stats=lambda: calls.append(1))
        with patch.object(config, "EVALUATION_MODE", "templates"):
            filters.sync()
            filters.sync(announce=True)
        self.assertEqual(len(calls), 2)


class PortTests(unittest.TestCase):
    def test_the_constructor_takes_exactly_four_ports(self) -> None:
        """A silently-absorbed dependency is what `object.__new__` was retired for."""
        with self.assertRaises(TypeError):
            TemplateRuntimeFilters(
                selected_template_names=list,
                refresh_stats=lambda: None,
                log=lambda _m: None,
                is_scanning=lambda: False,
                window=SimpleNamespace(),
            )

    def test_selected_template_names_copies_rather_than_aliasing(self) -> None:
        source = ["Alpha"]
        filters = build_template_filters(selected_template_names=lambda: source)
        got = filters.selected_template_names()
        got.append("Beta")
        self.assertEqual(source, ["Alpha"])

    def test_is_scanning_is_asked_not_assumed(self) -> None:
        logs: list[tuple[object, dict]] = []

        def record_log(message, **kwargs) -> None:
            logs.append((message, kwargs))

        thread = FakeThread(alive=False)
        filters = build_template_filters(
            selected_template_names=lambda: ["Alpha"],
            log=record_log,
            is_scanning=lambda: thread.is_alive(),
        )
        with patch.object(config, "EVALUATION_MODE", "templates"):
            filters.sync(announce=True)
            self.assertEqual(logs, [])
            thread._alive = True
            filters.template_stats = {}
            filters.sync(announce=True)
        self.assertEqual(
            logs,
            [
                (
                    ["[*] Active templates updated live: ", "Alpha"],
                    {"tag": [None, "BLUE"]},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
