"""Every function-body import of a local module must actually resolve.

Written after step 21 shipped a crash on the **first line of the real app**
while all 663 tests, `test_import_direction`, pyflakes and a 12322-leaf
differential trace were green.

What happened
=============

Step 21a moved `_apply_summary_label_padding` from `gui_layout` into
`ui.shared` and had `gui_layout` import it back. Step 21d moved the Compare Runs
panel builders out of `gui_layout`, which left that re-import unused; pyflakes
said so, and it was deleted.

But `ui/tabs/player_stats/live_stats.py:496` imports that name from
`gui_layout` **inside `build()`** -- a deliberate deferral, because a
module-scope import there closes the
`gui_layout -> ui.tabs.player_stats -> live_stats -> gui_layout` cycle. Nothing
saw it:

* **pyflakes** analyses one file at a time; the deleted name was unused *in
  `gui_layout`*, which was true.
* **`test_import_direction`** parses ASTs and never imports, by design.
* **The suite** never builds the Live Stats tab -- 52 `object.__new__` doubles
  exist precisely to avoid paying for `MegabonkApp.__init__`.
* **The step-21 differential trace** builds the Recordings and Compare Runs
  tabs offscreen. Not this one. Its "0 differing leaves" was true and blind.

Every check was correct about its own subject and the app did not start.

Why this check, rather than "build the app in a test"
=====================================================

Constructing `MegabonkApp` starts a `QApplication`, ~166 widgets, an overlay
server, a hotkey manager and two timers. That belongs in the packaged-exe run,
not in a unit suite that would then own the flakiness.

A deferred import is a *dependency declared away from where it is checked*, and
the only reason it drifts silently is that nothing resolves it until the line
runs. So resolve them all, here, deterministically. This generalises to steps
22-26, every one of which moves names between these modules.

Third-party deferred imports (`win32cred`, `keyring`) are skipped: those are
guarded on purpose and their absence is a supported state.
"""

from __future__ import annotations

import ast
import importlib
import os
import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Top-level names that are local to this repository. An import whose root is
#: not one of these is stdlib or third-party and is not this check's business.
LOCAL_ROOTS = {
    "app",
    "core",
    "infra",
    "projections",
    "ui",
    "gui_app",
    "gui_dialogs",
    "gui_in_game_overlay",
    "gui_in_game_overlay_settings",
    "gui_in_game_overlay_window",
    "gui_layout",
    "gui_overlay",
    "gui_run_control",
    "gui_scanner",
    "gui_templates",
    "gui_twitch",
    "live_run_tracker",
    "twitch_auth",
    "twitch_bot",
}


def _production_files() -> list[str]:
    found = []
    for root, dirs, files in os.walk(SRC_ROOT):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", "tests", "media"}]
        for name in files:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _deferred_imports() -> list[tuple[str, int, str, tuple[str, ...]]]:
    """`(relative path, line, module, names)` for each in-function import."""
    found: list[tuple[str, int, str, tuple[str, ...]]] = []
    for path in _production_files():
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        rel = os.path.relpath(path, SRC_ROOT).replace("\\", "/")
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                if node.level:  # relative import; not used in this tree
                    continue
                if node.module.split(".")[0] not in LOCAL_ROOTS:
                    continue
                found.append((rel, node.lineno, node.module, tuple(a.name for a in node.names)))
    return found


class DeferredImportTests(unittest.TestCase):
    def test_every_deferred_local_import_resolves(self) -> None:
        broken: list[str] = []
        for rel, line, module, names in _deferred_imports():
            try:
                imported = importlib.import_module(module)
            except Exception as exc:  # noqa: BLE001 -- the finding
                broken.append(f"src/{rel}:{line}: cannot import {module} ({exc})")
                continue
            for name in names:
                if not hasattr(imported, name):
                    broken.append(f"src/{rel}:{line}: {module} has no {name!r}")

        self.assertEqual(
            broken,
            [],
            "deferred import(s) naming something that no longer exists. These do "
            "not run until the line does, so nothing else in the suite sees them "
            "-- step 21 deleted a name from `gui_layout` that "
            "`live_stats.build()` imported, and the app crashed on startup with "
            "every check green:\n  " + "\n  ".join(broken),
        )

    def test_the_scan_actually_finds_the_deferred_imports(self) -> None:
        """Step 13's guard: a scan that finds nothing passes trivially."""
        found = _deferred_imports()
        self.assertGreater(len(found), 8, "the deferred-import scan found almost nothing")
        # The one that broke, pinned by module: `live_stats.build()` defers its
        # `gui_layout` layout helpers to avoid a real import cycle, so this
        # entry is expected to survive until step 26 moves the layout helpers.
        self.assertIn(
            "gui_layout",
            {module for _rel, _line, module, _names in found},
            "the gui_layout deferral is gone from the scan; if it was paid off, "
            "update this guard to another real deferral rather than deleting it",
        )


if __name__ == "__main__":
    unittest.main()
