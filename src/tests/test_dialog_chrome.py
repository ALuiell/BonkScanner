"""Every dialog is built on the shared shell, at one of the three widths.

The thing this protects is not visible in any one window. It is visible in the
set: before ``ui/dialogs/shell.py`` the fourteen dialogs were 223, 258, 274,
298, 305, 348, 355, 420, 560, 589, 640 and 760 wide, half of them had no title
inside the window, and the destructive button sat next to Cancel in some and
across the window from it in others. Nothing was broken; they just looked like
they came from different programs.

That is a class of defect no assertion about a single dialog can catch, so both
cases here are about the population:

* every ``QDialog`` subclass in the tree calls ``dialog_body``;
* every width it is called with is one of the three on the scale.

Read from the source rather than from built widgets, deliberately. Half of these
dialogs need a master object, a config fixture or a live tracker to construct,
and a check that skips the awkward ones is a check with holes exactly where the
odd dialogs are.
"""

from __future__ import annotations

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

import ast
import unittest
from pathlib import Path

from ui.dialogs.shell import DIALOG_COMPACT, DIALOG_REGULAR, DIALOG_WIDE

SRC_DIR = Path(src.__file__).resolve().parent

WIDTH_NAMES = {"DIALOG_COMPACT", "DIALOG_REGULAR", "DIALOG_WIDE"}
WIDTH_VALUES = {DIALOG_COMPACT, DIALOG_REGULAR, DIALOG_WIDE}

#: `shell.py` defines the scale; the update prompt is a stock `QMessageBox`
#: subclass with no body of its own to lay out.
EXEMPT_FILES = {"ui/dialogs/shell.py"}


def _dialog_classes() -> list[tuple[str, ast.ClassDef]]:
    found: list[tuple[str, ast.ClassDef]] = []
    for path in SRC_DIR.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(SRC_DIR).as_posix()
        if relative in EXEMPT_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if "QDialog" in bases:
                found.append((relative, node))
    return found


def _calls_named(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
    ]


class DialogChromeTests(unittest.TestCase):
    def test_there_are_dialogs_to_check(self) -> None:
        """Guards the guard: an empty sweep passes both cases below."""
        self.assertGreaterEqual(len(_dialog_classes()), 10)

    def test_every_dialog_uses_the_shared_shell(self) -> None:
        missing = [
            f"{path}:{node.name}"
            for path, node in _dialog_classes()
            if not _calls_named(node, "dialog_body")
        ]

        self.assertEqual(
            missing,
            [],
            "These dialogs build their own chrome instead of calling "
            "`dialog_body`, so their margins, title and button row are theirs "
            "alone: " + ", ".join(missing),
        )

    def test_every_dialog_width_is_on_the_scale(self) -> None:
        """A fourth width is how the set drifted apart the first time."""
        offenders: list[str] = []
        for path, node in _dialog_classes():
            for call in _calls_named(node, "dialog_body"):
                width = next(
                    (kw.value for kw in call.keywords if kw.arg == "width"), None
                )
                if width is None:
                    # The default is `DIALOG_REGULAR`, which is on the scale.
                    continue
                if isinstance(width, ast.Name) and width.id in WIDTH_NAMES:
                    continue
                if isinstance(width, ast.Constant) and width.value in WIDTH_VALUES:
                    continue
                offenders.append(f"{path}:{node.name}")

        self.assertEqual(
            offenders,
            [],
            "These dialogs pass a width that is not one of DIALOG_COMPACT / "
            "DIALOG_REGULAR / DIALOG_WIDE: " + ", ".join(offenders),
        )

    def test_no_dialog_sizes_itself_around_the_shell(self) -> None:
        """`resize` and `setMinimumSize` are the shell's to call.

        A dialog that calls one keeps the shared head and footer but goes back
        to picking its own number, which is most of the way back to where this
        started.
        """
        offenders: list[str] = []
        for path, node in _dialog_classes():
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr not in {"resize", "setMinimumSize", "setMinimumWidth"}:
                    continue
                if isinstance(func.value, ast.Name) and func.value.id == "self":
                    offenders.append(f"{path}:{node.name}.{func.attr}")

        self.assertEqual(
            offenders,
            [],
            "These dialogs set their own size next to the shell that already "
            "sets it: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
