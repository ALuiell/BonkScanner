"""No widget may be styled only by the fallback stylesheet.

``build_qt_app_stylesheet`` picks its base with

    base_stylesheet = redesign_stylesheet or legacy_stylesheet

so ``legacy_stylesheet`` is what ships *instead of* the redesign asset when that
file cannot be read -- not alongside it. Any rule that exists only in the legacy
block therefore applies in no real build. Nine did: the amber warning card and
its title, the Support heading, note and divider, and the four brand-coloured
support buttons. They looked plain grey for as long as the redesign asset has
been shipping, and nothing failed, because a missing QSS rule is not an error --
the widget just renders with whatever it inherits.

This is a ratchet on that, and it only knows one thing: an ``objectName`` that
the legacy block names must also be named by the sheet that actually ships.
Names styled by property selectors, by inline stylesheets or not at all are none
of its business -- it never asks whether a rule *should* exist, only whether one
that does exist is reachable.
"""

from __future__ import annotations

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

import re
import unittest
from pathlib import Path

SRC_DIR = Path(src.__file__).resolve().parent
STYLES = SRC_DIR / "ui" / "styles.py"
REDESIGN = SRC_DIR.parent / "ui_assets" / "bonkscanner_redesign.qss"

#: Where the fallback block starts and ends inside `styles.py`. Sliced by
#: markers rather than line numbers so an edit above it does not silently move
#: the window and leave this reading the wrong text.
LEGACY_START = "legacy_stylesheet = ("
LEGACY_END = "redesign_path = Path("

OBJECT_NAME = re.compile(r'setObjectName\(\s*"([A-Za-z_]\w*)"\s*\)')


def _legacy_block(styles_source: str) -> str:
    start = styles_source.index(LEGACY_START)
    end = styles_source.index(LEGACY_END)
    return styles_source[start:end]


def _object_names_set_in_production() -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for path in SRC_DIR.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in OBJECT_NAME.finditer(text):
            names.setdefault(match.group(1), set()).add(
                path.relative_to(SRC_DIR).as_posix()
            )
    return names


def _names_selected_by(sheet: str) -> set[str]:
    return set(re.findall(r"#([A-Za-z_]\w*)", sheet))


class StylesheetOrphanTests(unittest.TestCase):
    def test_the_fallback_sheet_styles_nothing_the_shipped_one_misses(self) -> None:
        styles_source = STYLES.read_text(encoding="utf-8")
        legacy = _legacy_block(styles_source)
        shipped = styles_source.replace(legacy, "") + REDESIGN.read_text(
            encoding="utf-8"
        )

        legacy_names = _names_selected_by(legacy)
        shipped_names = _names_selected_by(shipped)
        live_names = _object_names_set_in_production()

        orphans = {
            name: sorted(where)
            for name, where in live_names.items()
            if name in legacy_names and name not in shipped_names
        }

        self.assertEqual(
            orphans,
            {},
            "These object names are styled only by the fallback stylesheet, "
            "which ships only when the redesign asset cannot be read -- so in "
            "a real build they are unstyled. Move the rule into "
            "ui_assets/bonkscanner_redesign.qss:\n"
            + "\n".join(f"  {name}: {', '.join(w)}" for name, w in sorted(orphans.items())),
        )

    def test_the_slice_actually_finds_the_fallback_block(self) -> None:
        """Guards the guard.

        Both markers moving or being renamed would make `_legacy_block` return
        something empty or wrong, and an empty block has no orphans in it -- the
        case above would pass by finding nothing to check.
        """
        legacy = _legacy_block(STYLES.read_text(encoding="utf-8"))

        self.assertIn("QFrame#StatCard", legacy)
        self.assertGreater(len(_names_selected_by(legacy)), 10)
        self.assertIn(
            "base_stylesheet = redesign_stylesheet or legacy_stylesheet",
            STYLES.read_text(encoding="utf-8"),
            "The fallback is selected some other way now; this file's premise "
            "needs re-reading before its result means anything.",
        )


if __name__ == "__main__":
    unittest.main()
