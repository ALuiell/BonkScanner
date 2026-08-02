"""The two painted Live Stats controls take their colours from the stylesheet.

`LabeledSwitch` (Expanded) and `CompactItemsSortComboBox` (the sort glyph) draw
themselves in `paintEvent`, so ordinary QSS rules -- `color`, `background`,
`border` -- cannot reach them. They get their palette through ``qproperty-``
instead, and this file is what keeps that true.

The failure it exists for is silent in both directions, and the code defaults are
deliberately equal to the design values -- the widget has to look right when the
QSS asset is missing, which `build_stylesheet` treats as legal. That equality is
what makes the obvious test vacuous: reading the expected colour off a polished
widget proves nothing, because a deleted stylesheet block leaves exactly the same
answer. So each control is checked three ways:

* the sheet *declares* every property, asserted against its text -- this is what
  fails if the QSS block is deleted or a value there is edited;
* the property *exists* on the widget -- this is what fails on a rename, because
  a renamed property makes the stylesheet's declaration inert and
  ``widget.property()`` return ``None``;
* an override actually lands -- this is what fails if the ``qproperty-`` channel
  stops working at all, which no comparison against a default can show.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from PySide6.QtWidgets import QApplication

from ui.shared import LabeledSwitch, resource_path
from ui.styles import build_qt_app_stylesheet
from ui.tabs.player_stats.items_section import CompactItemsSortComboBox


#: Nothing in the code can produce these, so a widget reporting one can only
#: have read it from the sheet applied a line earlier.
TAMPER = "#FF00FF"

#: The design values, as the stylesheet states them. Kept here spelled out
#: rather than imported: this file is the second opinion on that block, and a
#: shared constant would agree with a typo.
SWITCH_PALETTE = {
    "labelColor": "#8A94A3",
    "labelDisabledColor": "#5C6675",
    "trackOnColor": "#2F6FB0",
    "trackOnBorderColor": "#3E82C6",
    "knobOnColor": "#EDF1F5",
    "trackOffColor": "#141A22",
    "trackOffBorderColor": "#2E3A48",
    "trackHoverBorderColor": "#38495E",
    "knobOffColor": "#5C6675",
}

GLYPH_PALETTE = {
    "glyphColor": "#EDF1F5",
    "glyphActiveColor": "#FACC15",
}


def _app_with_design_stylesheet() -> tuple[QApplication, str]:
    app = QApplication.instance() or QApplication([])
    sheet = build_qt_app_stylesheet(
        resource_path("media/checkmark.svg").replace("\\", "/")
    )
    app.setStyleSheet(sheet)
    return app, sheet


def _repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _colour(widget, name: str) -> str:
    value = widget.property(name)
    assert value is not None, f"{name} is not a registered property"
    return value.name().upper()


def _block(sheet: str, selector: str) -> str:
    """The body of one rule. Raises rather than returns empty if it is gone."""
    assert selector in sheet, f"the stylesheet no longer has a `{selector}` rule"
    return sheet.split(selector, 1)[1].split("{", 1)[1].split("}", 1)[0]


def _assert_declared(sheet: str, selector: str, palette: dict[str, str]) -> None:
    body = _block(sheet, selector)
    for name, expected in palette.items():
        declaration = f"qproperty-{name}: {expected};"
        assert declaration in body, f"{selector} does not declare `{declaration}`"


def test_the_expanded_switch_reads_its_whole_palette_from_the_stylesheet() -> None:
    app, sheet = _app_with_design_stylesheet()
    switch = LabeledSwitch("Expanded")
    switch.ensurePolished()

    _assert_declared(sheet, 'QCheckBox[labeledSwitch="true"]', SWITCH_PALETTE)
    for name, expected in SWITCH_PALETTE.items():
        assert _colour(switch, name) == expected.upper(), name

    # Selected by property, not objectName: Live Stats and Recordings name their
    # instances differently and both must be reached.
    app.setStyleSheet(
        f'{sheet}\nQCheckBox[labeledSwitch="true"] {{ qproperty-trackOnColor: {TAMPER}; }}'
    )
    _repolish(switch)
    assert _colour(switch, "trackOnColor") == TAMPER


def test_the_sort_glyph_reads_both_of_its_colours_from_the_stylesheet() -> None:
    app, sheet = _app_with_design_stylesheet()
    combo = CompactItemsSortComboBox()
    combo.ensurePolished()

    _assert_declared(sheet, "QComboBox#ItemsSortCombo", GLYPH_PALETTE)
    for name, expected in GLYPH_PALETTE.items():
        assert _colour(combo, name) == expected.upper(), name

    app.setStyleSheet(
        f"{sheet}\nQComboBox#ItemsSortCombo {{ qproperty-glyphActiveColor: {TAMPER}; }}"
    )
    _repolish(combo)
    assert _colour(combo, "glyphActiveColor") == TAMPER


def test_the_sort_control_is_not_wearing_the_primary_accent_when_idle() -> None:
    """`#3E82C6` is the primary border in this design -- the lit `go` segment.

    Sorting is the least consequential control on the panel, and while it wore
    that border it out-shouted `Rec`. Accent on hover is fine; accent at rest is
    the thing this asserts against.
    """
    _app, sheet = _app_with_design_stylesheet()

    idle = _block(sheet, "QComboBox#ItemsSortCombo")
    assert "#3E82C6" not in idle, idle
    assert "#33414F" in idle, idle
    # Accent on hover is the point of contrast, so it has to still be there.
    assert "#3E82C6" in _block(sheet, "QComboBox#ItemsSortCombo:hover")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
